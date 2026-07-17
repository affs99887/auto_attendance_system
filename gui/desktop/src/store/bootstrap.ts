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
import { useStartupStore } from './startup';
import { useToastStore } from './toast';
import { useProxyStore } from './proxy';
import { useExchangeRateStore } from './exchangeRate';
import { useWeatherStore } from './weather';
import { DEFAULT_WEATHER_LOCATION } from '../lib/weatherLocations';
import { useStartupLogStore } from './startupLog';
import { useServiceStore } from './service';
import { useWechatBarkStore } from './wechatBark';

const REFRESH_INTERVAL_MS = 15_000;
const FX_REFRESH_INTERVAL_MS = 5 * 60_000; // 汇率轮询：5 分钟
const WEATHER_REFRESH_INTERVAL_MS = 15 * 60_000; // 天气轮询：15 分钟
const PING_INTERVAL_MS = 400;
const READY_TIMEOUT_MS = 35_000;

async function weatherTargetIds(): Promise<string[]> {
  await useWeatherStore.getState().hydrate();
  return Array.from(new Set([
    DEFAULT_WEATHER_LOCATION.id,
    useWeatherStore.getState().activeLocationId,
  ]));
}

function refreshWeatherTargets(force = false) {
  void (async () => {
    const ids = await weatherTargetIds();
    await Promise.all(ids.map(locationId => (
      useWeatherStore.getState().refreshLocation(locationId, force)
    )));
  })();
}

function refreshWeatherTargetsAfterCurrent(force = false) {
  void weatherTargetIds().then(ids => {
    for (const locationId of ids) {
      useWeatherStore.getState().refreshLocationAfterCurrent(locationId, force);
    }
  });
}

export function useBackendBootstrap() {
  const status = useStartupStore(s => s.status);
  const overlayDismissed = useStartupStore(s => s.overlayDismissed);
  // 服务运行状态：用于暂停/恢复 effect2 的 WS + 15s 轮询（running 翻 false 自动 cleanup，翻 true 自动重建）
  const serviceRunning = useServiceStore(s => s.running);

  // effect0：监听后端服务（main.py）运行状态
  //  - 有桥（Electron）：标记 available，补拉一次 getStatus，并订阅 onStatus 推送驱动 running。
  //  - 无桥（纯浏览器 / dev）：available=false，running 恒 true（降级，正常路径行为不变）。
  useEffect(() => {
    const service = window.AAS_SERVICE;
    if (!service) {
      useServiceStore.getState().setAvailable(false);
      useServiceStore.getState().setRunning(true);
      return;
    }
    const applyRunning = (running: boolean) => {
      const serviceState = useServiceStore.getState();
      const wasRunning = serviceState.running;
      serviceState.setRunning(running);
      if (!wasRunning && running && useStartupStore.getState().status === 'ready') {
        // 服务快速重启时，旧天气请求可能仍在超时窗口内；排队一次强制刷新，
        // 等旧请求收尾后自动补跑，不能被 loading 去重吞掉。
        refreshWeatherTargetsAfterCurrent(true);
      }
    };
    useServiceStore.getState().setAvailable(true);
    void service.getStatus()
      .then(p => applyRunning(!!p?.running))
      .catch(() => { /* ignore */ });
    const off = service.onStatus(p => applyRunning(!!p?.running));
    return off; // StrictMode 安全：cleanup 即取消订阅
  }, []);

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
          // 真正通过 HTTP 探活后再触发天气；若重启前的旧请求仍未结束，
          // 每个地点都会把这次强制刷新排到各自旧请求之后执行。
          refreshWeatherTargetsAfterCurrent(true);
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
      // 去重（did-finish-load 补推 / 重复推送）；但失败态须放行——否则重试后唯一的
      // 恢复路径（同一 token 的补推）也被丢弃，UI 永久卡在 starting。
      if (p.token === st.currentToken && st.status !== 'failed') return;
      const wasReady = st.status === 'ready';
      st.setCurrentToken(p.token);
      if (wasReady) {
        // 已就绪又来新 token（后端无声重启换 token）：重连 WS + 刷新
        wsClient.stop();
        wsClient.start();
        void useSystemStore.getState().refresh();
        refreshWeatherTargetsAfterCurrent(true);
        return;
      }
      st.setPhase('正在确认服务可用…');
      void probeReady(useStartupStore.getState().epoch);
    }

    const off = startup.onStatus(handle);
    void startup.getStatus().then(handle).catch(() => { /* ignore */ });

    // 监听 store：失败态点"重试"会调用 setStarting（status→starting 且 epoch+1）。
    // setStarting 仅作废在途探活而不会重发探活，故这里订阅 status 边沿——
    // 当 failed→starting 且已握有 token 时，主动以新 epoch 重启探活循环，
    // 让重试成为真正的恢复入口（后端随后就绪即可进入 ready，无需重启整个应用）。
    let prevStatus = useStartupStore.getState().status;
    const offStore = useStartupStore.subscribe(s => {
      if (cancelled) return;
      if (prevStatus === 'failed' && s.status === 'starting' && s.currentToken) {
        void probeReady(s.epoch);
      }
      prevStatus = s.status;
    });

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
      offStore();
      offLog?.();
    };
  }, []);

  // effect2：就绪后才拉数据 + 订阅 WS（去掉原 if(cfg.token) 守卫——ready 必有有效 token）
  // 同时依赖 serviceRunning：服务停止时 cleanup（clearInterval + unsubs + wsClient.stop()），
  // 恢复运行时自动重建。serviceRunning 初值 true，正常路径行为不变。
  useEffect(() => {
    if (status !== 'ready' || !serviceRunning) return;

    void useSystemStore.getState().refresh();
    void useLogsStore.getState().loadTail(500);
    // 汇率首屏拉取（FxSection 自身不触发首拉；WS exchange_rate:update 仅增量更新 resp.latest，
    // resp 为 null 时 applyWsUpdate 会 no-op，故这里负责拉到首份序列）
    void useExchangeRateStore.getState().refresh();
    // 天气首屏拉取；由统一 bootstrap 管理轮询和窗口恢复补刷。
    refreshWeatherTargets();

    const refreshTimer = window.setInterval(() => {
      void useSystemStore.getState().refresh();
    }, REFRESH_INTERVAL_MS);

    // 汇率 5 分钟轮询 + 窗口重新可见/聚焦时补刷（与 system 15s 轮询同期生命周期，cleanup 一并清理）
    const fxRefreshTimer = window.setInterval(() => {
      void useExchangeRateStore.getState().refresh();
    }, FX_REFRESH_INTERVAL_MS);

    const weatherRefreshTimer = window.setInterval(() => {
      refreshWeatherTargets();
    }, WEATHER_REFRESH_INTERVAL_MS);

    // Electron 恢复窗口时通常会连续触发 visible + focus；合并为一次补刷，
    // 避免上游快速失败时同一轮恢复连续发出两次请求。
    let resumeRefreshTimer: number | null = null;
    const scheduleResumeRefresh = () => {
      if (document.visibilityState !== 'visible') return;
      if (resumeRefreshTimer !== null) window.clearTimeout(resumeRefreshTimer);
      resumeRefreshTimer = window.setTimeout(() => {
        resumeRefreshTimer = null;
        void useExchangeRateStore.getState().refresh();
        refreshWeatherTargets();
      }, 200);
    };
    const onVisible = () => {
      if (document.visibilityState === 'visible') scheduleResumeRefresh();
    };
    const onFocus = () => {
      scheduleResumeRefresh();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onFocus);

    const unsubs: Array<() => void> = [];

    // 断线重连补偿：onStatus 在每次状态变化时回调（订阅时也会先回放当前状态）。
    // 断线期间错过的 log:stream 推送与系统状态变化只能靠这里追回——
    //   refresh() 立即拉回最新系统快照；
    //   loadTail(500) 重拉日志尾部填补断流期的空洞（在途流式行由 loadTail 内部合并保留）。
    // 仅在"已建立过一次 open 之后又重新 open"时补刷，首连不触发（首连已由上方 refresh/loadTail 覆盖）。
    let everOpened = false;
    unsubs.push(wsClient.onStatus(s => {
      if (s !== 'open') return;
      if (everOpened) {
        void useSystemStore.getState().refresh();
        void useLogsStore.getState().loadTail(500);
      }
      everOpened = true;
    }));

    wsClient.start();

    unsubs.push(wsClient.subscribe('log:stream', data => {
      const d = data as { line?: string };
      if (typeof d?.line === 'string') {
        useLogsStore.getState().appendLine(d.line);
      }
    }));

    unsubs.push(wsClient.subscribe('proxy:status', () => {
      void useProxyStore.getState().refreshConfig();
      void useProxyStore.getState().refreshProfiles();
    }));

    // 汇率最新报价推送（data = {price, time, base, quote}，仅取 price/time 合并进 resp.latest）
    unsubs.push(wsClient.subscribe('exchange_rate:update', data => {
      const d = data as { price?: number; time?: number };
      if (typeof d?.price === 'number' && typeof d?.time === 'number') {
        useExchangeRateStore.getState().applyWsUpdate({ price: d.price, time: d.time });
      }
    }));

    // 微信 Bark 转发：状态推送（不含日志）驱动仪表盘卡片与独立页；日志走单独频道增量追加
    unsubs.push(wsClient.subscribe('wechat_bark:status', data => {
      useWechatBarkStore.getState().applyWsStatus(
        data as { running?: boolean; stopping?: boolean; platform_supported?: boolean; config_path?: string },
      );
    }));

    unsubs.push(wsClient.subscribe('wechat_bark:log', data => {
      const d = data as { lines?: string[] };
      if (Array.isArray(d?.lines)) useWechatBarkStore.getState().appendLogs(d.lines);
    }));

    // 系统唤醒补刷（Electron powerMonitor resume 经 preload AAS_POWER 转发）：
    // 睡眠期间上面的轮询定时器全部停摆，唤醒后立即补一轮系统快照 + 汇率 + 天气，
    // 不用等各自的下个轮询周期
    const offResume = window.AAS_POWER?.onResume(() => {
      void useSystemStore.getState().refresh();
      void useExchangeRateStore.getState().refresh();
      refreshWeatherTargets();
    });

    return () => {
      window.clearInterval(refreshTimer);
      window.clearInterval(fxRefreshTimer);
      window.clearInterval(weatherRefreshTimer);
      if (resumeRefreshTimer !== null) window.clearTimeout(resumeRefreshTimer);
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onFocus);
      offResume?.();
      unsubs.forEach(fn => fn());
      wsClient.stop();
    };
  }, [status, serviceRunning]);

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
