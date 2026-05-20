// Preload — 通过 contextBridge 暴露给渲染进程：
//   window.AAS_BACKEND — 后端连接配置（token / http / ws）
//   window.AAS_WINDOW  — 窗口控制（最小化 / 最大化 / 关闭）
const { contextBridge, ipcRenderer } = require('electron');

function readArg(key) {
  const prefix = `--${key}=`;
  const found = process.argv.find(a => a.startsWith(prefix));
  return found ? found.slice(prefix.length) : '';
}

contextBridge.exposeInMainWorld('AAS_BACKEND', {
  token: readArg('aas-token'),
  httpUrl: readArg('aas-http') || 'http://127.0.0.1:8765',
  wsUrl: readArg('aas-ws') || 'ws://127.0.0.1:8766',
});

contextBridge.exposeInMainWorld('AAS_WINDOW', {
  minimize: () => ipcRenderer.send('window:minimize'),
  maximizeToggle: () => ipcRenderer.send('window:maximize-toggle'),
  close: () => ipcRenderer.send('window:close'),
  isMaximized: () => ipcRenderer.invoke('window:is-maximized'),
});
