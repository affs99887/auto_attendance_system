// Preload — 通过 contextBridge 暴露给渲染进程：
//   window.AAS_BACKEND — 后端连接配置（http / ws；token 现由 AAS_STARTUP 异步送达）
//   window.AAS_WINDOW  — 窗口控制（最小化 / 最大化 / 关闭）
//   window.AAS_STARTUP — 后端启动状态（拉取 + 订阅主进程推送）
//   window.AAS_SYSTEM  — 系统能力（打开日志目录）
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

contextBridge.exposeInMainWorld('AAS_SYSTEM', {
  openLogs: () => ipcRenderer.invoke('system:open-logs'), // resolve 空串=成功，非空=错误
});
