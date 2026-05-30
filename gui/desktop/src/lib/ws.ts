// WebSocket 客户端 — 单例 + 自动重连 + channel 多路订阅
//
// 用法：
//   const sub = wsClient.subscribe('log:stream', (data) => ...);
//   sub(); // 取消订阅
import { getBackend } from './backend';

export interface WsMessage {
  channel: string;
  data: unknown;
  ts: number;
}

type Handler = (data: unknown, msg: WsMessage) => void;

export type WsStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

class WsClient {
  private ws: WebSocket | null = null;
  private retry = 0;
  private retryTimer: number | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private statusListeners = new Set<(s: WsStatus) => void>();
  private status: WsStatus = 'idle';
  private stopped = false;

  start() {
    this.stopped = false;
    // 幂等：已在连接/已连接则不重复发起（防 StrictMode 双跑、重复 start）
    if (this.ws && (this.status === 'connecting' || this.status === 'open')) return;
    this.connect();
  }

  stop() {
    this.stopped = true;
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    if (this.ws) {
      try { this.ws.close(); } catch { /* noop */ }
      this.ws = null;
    }
    this.setStatus('closed');
  }

  getStatus(): WsStatus {
    return this.status;
  }

  onStatus(listener: (s: WsStatus) => void): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => { this.statusListeners.delete(listener); };
  }

  subscribe(channel: string, handler: Handler): () => void {
    let set = this.handlers.get(channel);
    if (!set) {
      set = new Set();
      this.handlers.set(channel, set);
    }
    set.add(handler);
    return () => {
      const cur = this.handlers.get(channel);
      cur?.delete(handler);
      if (cur && cur.size === 0) this.handlers.delete(channel);
    };
  }

  private setStatus(s: WsStatus) {
    if (this.status === s) return;
    this.status = s;
    this.statusListeners.forEach(l => l(s));
  }

  private connect() {
    if (this.stopped) return;
    const { token, wsUrl } = getBackend();
    if (!token) {
      // 没 token 等同未配置，跳过；用户手动设置后调 start()
      this.setStatus('idle');
      return;
    }
    // 新建前关掉残留连接，防句柄泄漏（换 token / StrictMode 双跑）
    if (this.ws) {
      try { this.ws.close(); } catch { /* noop */ }
      this.ws = null;
    }
    this.setStatus('connecting');
    const url = `${wsUrl}/?token=${encodeURIComponent(token)}`;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (e) {
      this.scheduleRetry();
      return;
    }
    this.ws = ws;

    ws.addEventListener('open', () => {
      this.retry = 0;
      this.setStatus('open');
    });

    ws.addEventListener('message', ev => {
      let msg: WsMessage | null = null;
      try {
        msg = JSON.parse(String(ev.data)) as WsMessage;
      } catch {
        return;
      }
      if (!msg || typeof msg !== 'object') return;
      const handlers = this.handlers.get(msg.channel);
      if (!handlers) return;
      handlers.forEach(h => {
        try { h(msg.data, msg); } catch (e) { console.error('ws handler threw', e); }
      });
    });

    ws.addEventListener('error', () => {
      this.setStatus('error');
    });

    ws.addEventListener('close', () => {
      this.ws = null;
      this.setStatus('closed');
      this.scheduleRetry();
    });
  }

  private scheduleRetry() {
    if (this.stopped) return;
    this.retry++;
    const delay = Math.min(30_000, 500 * Math.pow(2, this.retry - 1)); // 0.5s → 1s → 2s → 4s → 8s … cap 30s
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }
}

export const wsClient = new WsClient();
