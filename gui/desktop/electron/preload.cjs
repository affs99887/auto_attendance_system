// Preload — 通过 contextBridge 把后端连接配置（token / http / ws）
// 暴露到 window.AAS_BACKEND，供渲染进程的 lib/backend.ts 读取。
const { contextBridge } = require('electron');

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
