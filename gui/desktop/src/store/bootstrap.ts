// 后端连接引导 — 在 React Root 挂载时调用 useBackendBootstrap()，
// 拉一次状态/日志 + 启动 WS + 注册所有 channel 订阅。
import { useEffect } from 'react';
import { announceBackend } from '../lib/backend';
import { wsClient } from '../lib/ws';
import { useSystemStore } from './system';
import { useLogsStore } from './logs';
import { usePunchStore } from './punch';

const REFRESH_INTERVAL_MS = 15_000;

export function useBackendBootstrap() {
  useEffect(() => {
    const cfg = announceBackend();

    // 主动拉取一次
    void useSystemStore.getState().refresh();
    void useLogsStore.getState().loadTail(500);

    // 定时刷新快照 — 兜底 WS 漏推送
    const refreshTimer = window.setInterval(() => {
      void useSystemStore.getState().refresh();
    }, REFRESH_INTERVAL_MS);

    // WS 订阅
    const unsubs: Array<() => void> = [];
    if (cfg.token) {
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
        // 任何变更都触发一次完整 refresh（简单可靠；后续可改 mergeUpdate）
        void useSystemStore.getState().refresh();
      }));

      unsubs.push(wsClient.subscribe('task:changed', () => {
        void useSystemStore.getState().refresh();
      }));
    }

    return () => {
      window.clearInterval(refreshTimer);
      unsubs.forEach(fn => fn());
      wsClient.stop();
    };
  }, []);
}
