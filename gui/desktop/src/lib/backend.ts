// 后端连接配置 — token / HTTP URL / WS URL
//
// 优先级：
//   1. override —— 主进程经 IPC 异步送达的 token/url（生产模式真正来源，见 store/bootstrap.ts）
//   2. localStorage 'aas.dev_token' / 'aas.dev_http' / 'aas.dev_ws'（开发模式手动设置）
//   3. window.AAS_BACKEND —— preload 注入（token 现恒为空，仅 http/ws 作默认）
//   4. 默认值（127.0.0.1:8765 / :8766）
//
// 注意：token 不再随窗口创建注入，window.AAS_BACKEND.token 恒为空串；
// 因此把 override 提到最高优先级，且只有 AAS_BACKEND.token 非空时才采用它，
// 否则会挡掉 localStorage dev token。

/** 主进程推送/渲染进程解析得到的后端配置（最高优先级） */
export interface StartupPayloadToken {
  state: 'token';
  token: string;
  httpUrl: string;
  wsUrl: string;
}
export type StartupPayload =
  | { state: 'starting'; reason?: string | null }
  | { state: 'failed'; reason: string }
  | StartupPayloadToken;

declare global {
  interface Window {
    AAS_BACKEND?: {
      token: string;
      httpUrl: string;
      wsUrl: string;
    };
    /** Electron preload 注入的窗口控制（纯浏览器下为 undefined） */
    AAS_WINDOW?: {
      minimize: () => void;
      maximizeToggle: () => void;
      close: () => void;
      isMaximized: () => Promise<boolean>;
    };
    /** 后端启动状态桥（纯浏览器下为 undefined） */
    AAS_STARTUP?: {
      getStatus: () => Promise<StartupPayload>;
      onStatus: (cb: (p: StartupPayload) => void) => () => void;
    };
    /** 系统能力桥（纯浏览器下为 undefined） */
    AAS_SYSTEM?: {
      openLogs: () => Promise<string>;
    };
  }
}

const DEFAULT_HTTP = 'http://127.0.0.1:8765';
const DEFAULT_WS = 'ws://127.0.0.1:8766';

export interface BackendConfig {
  token: string;
  httpUrl: string;
  wsUrl: string;
  source: 'electron' | 'localStorage' | 'default';
}

let override: { token: string; httpUrl: string; wsUrl: string } | null = null;

/** 主进程经 IPC 送达 token 后调用，置为最高优先级来源。 */
export function setBackendOverride(next: { token: string; httpUrl: string; wsUrl: string }) {
  override = next;
}

export function getBackend(): BackendConfig {
  if (override) {
    return { ...override, source: 'electron' };
  }
  if (typeof window !== 'undefined' && window.localStorage) {
    const token = localStorage.getItem('aas.dev_token') || '';
    if (token) {
      return {
        token,
        httpUrl: localStorage.getItem('aas.dev_http') || DEFAULT_HTTP,
        wsUrl: localStorage.getItem('aas.dev_ws') || DEFAULT_WS,
        source: 'localStorage',
      };
    }
  }
  if (typeof window !== 'undefined' && window.AAS_BACKEND) {
    const b = window.AAS_BACKEND;
    // token 非空才用 electron 注入（现 token 恒空，主要取 http/ws 默认）
    if (b.token) {
      return { ...b, source: 'electron' };
    }
    return { token: '', httpUrl: b.httpUrl || DEFAULT_HTTP, wsUrl: b.wsUrl || DEFAULT_WS, source: 'default' };
  }
  return { token: '', httpUrl: DEFAULT_HTTP, wsUrl: DEFAULT_WS, source: 'default' };
}

/** 浏览器/Electron 启动时调一次，把当前 token 暴露到 console 便于排错。 */
export function announceBackend(): BackendConfig {
  const cfg = getBackend();
  const masked = cfg.token ? cfg.token.slice(0, 8) + '...' : '(none)';
  // eslint-disable-next-line no-console
  console.info(
    `[AAS_BACKEND] source=${cfg.source} http=${cfg.httpUrl} ws=${cfg.wsUrl} token=${masked}`,
  );
  return cfg;
}
