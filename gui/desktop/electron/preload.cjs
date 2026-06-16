// Preload — 通过 contextBridge 暴露给渲染进程：
//   window.AAS_BACKEND — 后端连接配置（http / ws；token 现由 AAS_STARTUP 异步送达）
//   window.AAS_WINDOW  — 窗口控制（最小化 / 最大化 / 关闭）
//   window.AAS_STARTUP — 后端启动状态（拉取 + 订阅主进程推送）
//   window.AAS_SERVICE — 服务控制（启动/停止/重启后端 + 订阅运行状态推送）
//   window.AAS_SYSTEM  — 系统能力（打开日志目录）
//   window.AAS_FILES   — 文件选择（选本地 Clash 配置文件）
//   window.AAS_LOG     — 启动日志（python stdout/stderr 原始行，供启动覆盖层展示）
const { contextBridge, ipcRenderer } = require('electron');

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
  // 用系统默认图片查看器打开本地截图（不弹浏览器）；resolve 空串=成功，非空=错误信息
  openScreenshot: (relPath) => ipcRenderer.invoke('screenshot:open', relPath),
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

contextBridge.exposeInMainWorld('AAS_EPD', {
  // 订阅主进程推送的蓝牙设备流（select-bluetooth-device 拦截后实时转发）
  onDevices: (cb) => {
    const handler = (_e, devices) => cb(devices);
    ipcRenderer.on('epd:ble-devices', handler);
    return () => ipcRenderer.removeListener('epd:ble-devices', handler);
  },
  // 回选设备（空串=取消本次扫描请求）
  select: (deviceId) => ipcRenderer.send('epd:ble-select', deviceId || ''),
  // 蓝牙配对确认请求（渲染端用应用内对话框确认）
  onPairing: (cb) => {
    const handler = (_e, req) => cb(req);
    ipcRenderer.on('epd:ble-pairing', handler);
    return () => ipcRenderer.removeListener('epd:ble-pairing', handler);
  },
  // 配对确认结果回传
  pairingResponse: (confirmed) => ipcRenderer.send('epd:ble-pairing-response', !!confirmed),
  // 方案2：请求主进程注入一次可信键盘输入(F24)产生 user activation，供渲染层在手势上下文里
  // 调 requestDevice 自动重连(定时推送无手势)。resolve true=已注入 / false=不可用。
  tryGestureReconnect: () => ipcRenderer.invoke('epd:gesture-reconnect'),
  // 追加一条墨水屏日志到主进程 logs/epaper.log（主进程防抖落盘，保留长历史可外部翻查）
  appendLog: (line) => ipcRenderer.send('epd:log-append', line),
});
