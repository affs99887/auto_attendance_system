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

/** 代码 OTA 更新状态（主进程 update:status 推送 / apply/getStatus 返回）。
 *  staged=已落地新版；shell/dependencies-outdated=需先升级客户端；error=失败但不影响当前运行。 */
export type UpdateStatus =
  | { status: 'idle' }
  | { status: 'checking' }
  | { status: 'up-to-date'; currentVersion?: string }
  | { status: 'staged'; version: string }
  | { status: 'shell-outdated'; version: string; requiredShell: string }
  | { status: 'dependencies-outdated'; version: string }
  | { status: 'error'; error: string; skippedBad?: string };

export type UpdateCheckResult =
  | { status: 'available'; currentVersion: string; latest: string }
  | { status: 'up-to-date'; currentVersion: string; latest: string }
  | { status: 'shell-outdated'; version: string; requiredShell: string }
  | { status: 'dependencies-outdated'; version: string }
  | { status: 'error'; error: string };

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
    /** 后端服务（main.py）进程控制桥（纯浏览器下为 undefined） */
    AAS_SERVICE?: {
      getStatus: () => Promise<{ running: boolean }>;
      start: () => Promise<{ success: boolean; message?: string }>;
      stop: () => Promise<{ success: boolean; message?: string }>;
      restart: () => Promise<{ success: boolean; message?: string }>;
      /** 订阅服务运行状态推送，返回取消订阅函数 */
      onStatus: (cb: (p: { running: boolean }) => void) => () => void;
    };
    /** 系统能力桥（纯浏览器下为 undefined） */
    AAS_SYSTEM?: {
      openLogs: () => Promise<string>;
      /** 用系统默认图片查看器打开本地截图原图。入参为后端返回的相对路径；resolve 空串=成功，非空=错误信息 */
      openScreenshot: (path: string) => Promise<string>;
    };
    /** 文件选择桥（纯浏览器下为 undefined）：选本地 Clash 配置文件并读内容 */
    AAS_FILES?: {
      pickConfigFile: () => Promise<{ name: string; content: string } | null>;
    };
    /** 启动日志桥（纯浏览器下为 undefined）：python stdout/stderr 原始行 */
    AAS_LOG?: {
      getBuffer: () => Promise<string[]>;
      onLog: (cb: (p: { lines: string[] }) => void) => () => void;
    };
    /** GUI 设置持久化桥（主进程 gui-settings.json；纯浏览器下为 undefined）。
     *  打包应用以 file:// 加载时 localStorage 跨重启不可靠，需要记忆的设置以此为权威。 */
    AAS_SETTINGS?: {
      getAll: () => Promise<Record<string, unknown>>;
      set: (key: string, value: unknown) => void;
    };
    /** 墨水屏蓝牙选择桥（纯浏览器下为 undefined）：
     *  主进程拦截 select-bluetooth-device 后把设备流实时推给渲染进程，
     *  由页面自定义 modal 展示并回选 deviceId（空串=取消）。 */
    AAS_EPD?: {
      /** 订阅扫描到的设备流（name 可能为空串=无名设备），返回取消订阅函数 */
      onDevices: (cb: (devices: Array<{ deviceId: string; deviceName: string }>) => void) => () => void;
      /** 回选设备（deviceId 空串=取消本次请求） */
      select: (deviceId: string) => void;
      /** 蓝牙配对确认请求（渲染端用应用内对话框确认），返回取消订阅函数 */
      onPairing: (cb: (req: { kind: 'confirmPin' | 'confirm'; deviceId: string; pin: string }) => void) => () => void;
      /** 配对确认结果回传 */
      pairingResponse: (confirmed: boolean) => void;
      /** 方案2：请求主进程注入一次可信键盘输入(F24)产生 user activation，供渲染层在手势上下文里
       *  调 requestDevice 自动重连(定时推送无手势场景)。resolve true=已注入 / false=不可用或失败。 */
      tryGestureReconnect: () => Promise<boolean>;
      /** 追加一条墨水屏日志到主进程 logs/epaper.log（防抖落盘，保留长历史；旧 preload / 纯浏览器下为 undefined） */
      appendLog?: (line: string) => void;
    };
    /** 瘦壳 + 代码 OTA 自更新桥（旧 preload / 纯浏览器下为 undefined）。
     *  壳子固定不变，后端 .py 与前端 dist 作为可更新「代码包」独立存在；
     *  getInfo 返回本次启动实际加载的代码来源与版本，check/apply 查/下更新，relaunch 重启生效。 */
    AAS_UPDATE?: {
      /** 当前运行的代码信息：codeVersion=代码包版本；shellVersion=壳子(package.json)版本；
       *  source=代码来源（env 覆盖 / ota 更新目录 / builtin 内置 / dev 源码）。 */
      getInfo: () => Promise<{
        codeVersion: string;
        shellVersion: string;
        source: 'env' | 'ota' | 'builtin' | 'dev';
      }>;
      /** 仅查询是否有新版（不下载）。 */
      check: () => Promise<UpdateCheckResult>;
      /** 检查并下载落地新版（与启动自动触发互斥去重）。落地后需 relaunch 或下次启动生效。 */
      apply: () => Promise<UpdateStatus>;
      /** 拉取最近一次更新状态（兜底 push 早于监听注册）。 */
      getStatus: () => Promise<UpdateStatus>;
      /** React 已挂载且完成后端真实探活；用于防止白屏版本被误标为 last-good。 */
      rendererReady?: () => Promise<{ ok: boolean; error?: string }>;
      /** 立即重启壳子使已落地新版生效。 */
      relaunch: () => Promise<{ ok: boolean; error?: string }>;
      /** 订阅更新状态推送，返回注销函数。 */
      onStatus: (cb: (s: UpdateStatus) => void) => () => void;
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
