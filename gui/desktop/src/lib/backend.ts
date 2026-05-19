// 后端连接配置 — token / HTTP URL / WS URL
//
// 三层优先级：
//   1. Electron preload 注入的 window.AAS_BACKEND（生产模式）
//   2. localStorage 'aas.dev_token' / 'aas.dev_http' / 'aas.dev_ws'（开发模式手动设置）
//   3. 默认值（127.0.0.1:8765 / :8766，空 token → 请求会 401，用于看到鉴权效果）

declare global {
  interface Window {
    AAS_BACKEND?: {
      token: string;
      httpUrl: string;
      wsUrl: string;
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

export function getBackend(): BackendConfig {
  if (typeof window !== 'undefined' && window.AAS_BACKEND) {
    return { ...window.AAS_BACKEND, source: 'electron' };
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
