// Preload — 通过 contextBridge 暴露给渲染进程：
//   window.AAS_BACKEND — 后端连接配置（http / ws；token 现由 AAS_STARTUP 异步送达）
//   window.AAS_WINDOW  — 窗口控制（最小化 / 最大化 / 关闭）
//   window.AAS_STARTUP — 后端启动状态（拉取 + 订阅主进程推送）
//   window.AAS_SERVICE — 服务控制（启动/停止/重启后端 + 订阅运行状态推送）
//   window.AAS_SYSTEM  — 系统能力（打开日志目录）
//   window.AAS_FILES   — 文件选择（选本地 Clash 配置文件）
//   window.AAS_LOG     — 启动日志（python stdout/stderr 原始行，供启动覆盖层展示）
//   window.AAS_SETTINGS — GUI 设置持久化（主进程 gui-settings.json）
//   window.AAS_POWER   — 系统睡眠唤醒事件订阅
//   window.AAS_WECHAT_BARK — 微信 Bark 转发的系统级操作（隐私设置 / 定位配置 / 登录项）
//   window.AAS_PLATFORM — 运行平台标识（'darwin'/'win32'/...，渲染层按平台微调 UI）
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('AAS_PLATFORM', process.platform);

function readArg(key) {
  const prefix = `--${key}=`;
  const found = process.argv.find(a => a.startsWith(prefix));
  return found ? found.slice(prefix.length) : '';
}

contextBridge.exposeInMainWorld('AAS_BACKEND', {
  token: readArg('aas-token'), // 现恒为空串（token 走 IPC），保留以兼容旧逻辑
  httpUrl: readArg('aas-http') || 'http://127.0.0.1:8765',
  wsUrl: readArg('aas-ws') || 'ws://127.0.0.1:8766',
});

contextBridge.exposeInMainWorld('AAS_WINDOW', {
  minimize: () => ipcRenderer.send('window:minimize'),
  maximizeToggle: () => ipcRenderer.send('window:maximize-toggle'),
  close: () => ipcRenderer.send('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:is-maximized'),
});

contextBridge.exposeInMainWorld('AAS_STARTUP', {
  // mount 时主动拉一次（兜底 push 早于监听注册）
  getStatus: () => ipcRenderer.invoke('backend:get-status'),
  // 订阅主进程推送，返回注销函数
  onStatus: (cb) => {
    const handler = (_e, payload) => cb(payload);
    ipcRenderer.on('backend:status', handler);
    return () => ipcRenderer.removeListener('backend:status', handler);
  },
});

contextBridge.exposeInMainWorld('AAS_SERVICE', {
  // 拉取当前运行状态：Promise<{ running:boolean }>
  getStatus: () => ipcRenderer.invoke('service:get-status'),
  // 启动 / 停止 / 重启后端：Promise<{ success:boolean, message?:string }>
  start:   () => ipcRenderer.invoke('service:start'),
  stop:    () => ipcRenderer.invoke('service:stop'),
  restart: () => ipcRenderer.invoke('service:restart'),
  // 订阅服务运行状态推送（service:status），返回注销函数
  onStatus: (cb) => {
    const handler = (_e, payload) => cb(payload);
    ipcRenderer.on('service:status', handler);
    return () => ipcRenderer.removeListener('service:status', handler);
  },
});

contextBridge.exposeInMainWorld('AAS_SYSTEM', {
  openLogs: () => ipcRenderer.invoke('system:open-logs'), // resolve 空串=成功，非空=错误
});

contextBridge.exposeInMainWorld('AAS_FILES', {
  // 选本地 Clash 配置文件：resolve {name, content} 或 null（取消）；reject=读取失败
  pickConfigFile: () => ipcRenderer.invoke('proxy:pick-config-file'),
});

contextBridge.exposeInMainWorld('AAS_LOG', {
  getBuffer: () => ipcRenderer.invoke('backend:get-log'),
  onLog: (cb) => {
    const handler = (_e, payload) => cb(payload);
    ipcRenderer.on('backend:log', handler);
    return () => ipcRenderer.removeListener('backend:log', handler);
  },
});

contextBridge.exposeInMainWorld('AAS_SETTINGS', {
  // 全量拉取持久化 GUI 设置（主进程 gui-settings.json，跨重启可靠）
  getAll: () => ipcRenderer.invoke('settings:get-all'),
  // 写入单个键（主进程防抖落盘；value 传 null 删除该键）
  set: (key, value) => ipcRenderer.send('settings:set', key, value),
});

contextBridge.exposeInMainWorld('AAS_POWER', {
  // 订阅系统休眠唤醒通知（主进程 powerMonitor resume 广播），供页面唤醒后立即补刷数据；
  // 返回注销函数（与其它桥一致，供 React effect cleanup 用）
  onResume: (cb) => {
    const handler = () => cb();
    ipcRenderer.on('power:resume', handler);
    return () => ipcRenderer.removeListener('power:resume', handler);
  },
});

contextBridge.exposeInMainWorld('AAS_WECHAT_BARK', {
  // 打开 macOS「完全磁盘访问」设置页；非 mac 返回 {ok:false}
  openPrivacySettings: () => ipcRenderer.invoke('wechat-bark:open-privacy'),
  // 文件管理器中定位 wechat_bark_config.json（不存在时降级为打开数据目录）
  showConfig: () => ipcRenderer.invoke('wechat-bark:show-config'),
  // 把「登录后自动启动」同步到系统登录项（仅 macOS 打包版生效，其余 no-op 返 skipped）
  syncLoginItem: (enabled) => ipcRenderer.invoke('wechat-bark:sync-login-item', !!enabled),
});
