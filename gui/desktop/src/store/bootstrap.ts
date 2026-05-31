// 后端连接引导 —— 在 React Root 挂载时调用 useBackendBootstrap()。
//
// 与"窗口先于后端就绪"配合：
//  - effect1：监听主进程 AAS_STARTUP 启动状态；收到 token 后 ping+status 探活，成功才置 ready；
//             后端重启换 token 时重连 WS。无 AAS_STARTUP（纯浏览器/dev）直接 ready。
//  - effect2：仅 status==='ready' 时才拉状态/日志、起定时刷新、订阅 WS。
//  - effect3：ready/失败的 toast 边沿提示。
import { useEffect } from 'react';
import { announceBackend, setBackendOverride, type StartupPayload } from '../lib/backend';
import { wsClient } from '../lib/ws';
import { api } from '../lib/api';
import { useSystemStore } from './system';
import { useLogsStore } from './logs';
import { usePunchStore } from './punch';
import { useStartupStore } from './startup';
import { useToastStore } from './toast';
import { useProxyStore } from './proxy';
import { useStartupLogStore } from './startupLog';

const REFRESH_INTERVAL_MS = 15_000;
const PING_INTERVAL_MS = 400;
const READY_TIMEOUT_MS = 35_000;

export function useBackendBootstrap() {
  const status = useStartupStore(s => s.status);
  const overlayDismissed = useStartupStore(s => s.overlayDismissed);

  // effect1：监听启动状态 + ping/status 探活
  useEffect(() => {
    const startup = window.AAS_STARTUP;

    // 无壳（纯浏览器 / vite dev，无 Electron）：直接就绪，沿用 localStorage/默认 token
    if (!startup) {
      announceBackend();
      useStartupStore.getState().setReady();
      return;
    }

    let cancelled = false;
    let pingTimer: number | null = null;

    async function probeReady(epoch: number) {
      const deadline = Date.now() + READY_TIMEOUT_MS;
      while (!cancelled && Date.now() < deadline) {
        if (useStartupStore.getState().epoch !== epoch) return; // 发生了 failed/重启，放弃本轮
        try {
          await api.ping();        // 无鉴权，确认 HTTP 真在监听（token 出现早于 bind）
          await api.getStatus();   // 带 token，确认 token 有效（防僵尸进程占端口的假就绪）
          if (cancelled || useStartupStore.getState().epoch !== epoch) return;
          useStartupStore.getState().setReady();
          return;
        } catch {
          // 还没起来 / token 暂不可用，继续轮询
        }
        await new Promise<void>(r => { pingTimer = window.setTimeout(r, PING_INTERVAL_MS); });
      }
      if (!cancelled && useStartupStore.getState().epoch === epoch) {
        useStartupStore.getState().setFailed('后端 HTTP 服务未在预期时间内就绪，请查看日志');
      }
    }

    function handle(p: StartupPayload) {
      if (cancelled || !p) return;
      const st = useStartupStore.getState();
      if (p.state === 'starting') { st.setStarting('正在启动后端服务…'); useStartupLogStore.getState().reset(); return; }
      if (p.state === 'failed') { st.setFailed(p.reason); return; }
      // p.state === 'token'
      setBackendOverride({ token: p.token, httpUrl: p.httpUrl, wsUrl: p.wsUrl });
      if (p.token === st.currentToken) return; // 去重（did-finish-load 补推 / 重复推送）
      const wasReady = st.status === 'ready';
      st.setCurrentToken(p.token);
      if (wasReady) {
        // 已就绪又来新 token（后端无声重启换 token）：重连 WS + 刷新
        wsClient.stop();
        wsClient.start();
        void useSystemStore.getState().refresh();
        return;
      }
      st.setPhase('正在确认服务可用…');
      void probeReady(useStartupStore.getState().epoch);
    }

    const off = startup.onStatus(handle);
    void startup.getStatus().then(handle).catch(() => { /* ignore */ });

    // 启动日志：订阅 Electron 转发的 python stdout/stderr + 拉一次全量兜底（注册晚于早期日志）
    const log = window.AAS_LOG;
    let offLog: (() => void) | undefined;
    if (log) {
      offLog = log.onLog(p => {
        if (!cancelled && p?.lines) useStartupLogStore.getState().append(p.lines);
      });
      void log.getBuffer()
        .then(lines => { if (!cancelled && Array.isArray(lines)) useStartupLogStore.getState().reset(lines); })
        .catch(() => { /* ignore */ });
    }

    return () => {
      cancelled = true;
      if (pingTimer !== null) window.clearTimeout(pingTimer);
      off();
      offLog?.();
    };
  }, []);

  // effect2：就绪后才拉数据 + 订阅 WS（去掉原 if(cfg.token) 守卫——ready 必有有效 token）
  useEffect(() => {
    if (status !== 'ready') return;

    void useSystemStore.getState().refresh();
    void useLogsStore.getState().loadTail(500);

    const refreshTimer = window.setInterval(() => {
      void useSystemStore.getState().refresh();
    }, REFRESH_INTERVAL_MS);

    const unsubs: Array<() => void> = [];
    wsClient.start();

    unsubs.push(wsClient.subscribe('log:stream', data => {
      const d = data as { line?: string };
      if (typeof d?.line === 'string') {
        useLogsStore.getState().appendLine(d.line);
      }
    }));

    unsubs.push(wsClient.subscribe('punch:progress', data => {
      const d = data as { title?: string; content?: string; message?: string };
      usePunchStore.getState().push({
        title: d?.title ?? '',
        content: d?.content ?? '',
        message: d?.message,
      });
    }));

    unsubs.push(wsClient.subscribe('status:update', () => {
      void useSystemStore.getState().refresh();
    }));

    unsubs.push(wsClient.subscribe('task:changed', () => {
      void useSystemStore.getState().refresh();
    }));

    unsubs.push(wsClient.subscribe('proxy:status', () => {
      void useProxyStore.getState().refreshConfig();
    }));

    return () => {
      window.clearInterval(refreshTimer);
      unsubs.forEach(fn => fn());
      wsClient.stop();
    };
  }, [status]);

  // effect3：成功 / 失败 toast 边沿
  useEffect(() => {
    const st = useStartupStore.getState();
    if (status === 'ready' && !st.readyToastShown) {
      st.setReadyToastShown(true);
      useToastStore.getState().push('ok', '启动成功，系统已就绪');
    }
    if (status === 'failed' && overlayDismissed) {
      useToastStore.getState().push('err', st.reason || '后端启动失败');
    }
  }, [status, overlayDismissed]);
}
