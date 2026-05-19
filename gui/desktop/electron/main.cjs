// Electron 主进程
// - spawn `python start.py --mode gui` 作为后端
// - 等待 logs/.gui_token 文件出现
// - 读 token，创建 BrowserWindow + preload 注入到 window.AAS_BACKEND
// - dev 模式加载 Vite dev server，prod 模式加载 dist/
// - 单实例锁 + 托盘菜单 + 关窗口缩到托盘
//
// 启动方式：
//   1. dev:  AAS_DEV=1 npx electron electron/main.cjs   （Vite 必须先启）
//   2. prod: npx electron .                             （走 build 后的 dist）

const { app, BrowserWindow, Tray, Menu, nativeImage, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');

const PROJECT_ROOT = path.resolve(__dirname, '..', '..', '..');
const TOKEN_PATH = path.join(PROJECT_ROOT, 'logs', '.gui_token');
const DEV_SERVER_URL = process.env.AAS_DEV_SERVER || 'http://127.0.0.1:5173';
const HTTP_PORT = parseInt(process.env.AAS_HTTP_PORT || '8765', 10);
const WS_PORT = parseInt(process.env.AAS_WS_PORT || '8766', 10);
const IS_DEV = Boolean(process.env.AAS_DEV);

let pythonProc = null;
let mainWindow = null;
let tray = null;
let appQuitting = false;

// ============================================================================
// 单实例锁 — 第二次启动唤起已有窗口
// ============================================================================
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  process.exit(0);
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      if (!mainWindow.isVisible()) mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ============================================================================
// 启动 Python 后端
// ============================================================================
function spawnPython() {
  const startPy = path.join(PROJECT_ROOT, 'start.py');
  if (!fs.existsSync(startPy)) {
    console.error('[aas-electron] start.py not found:', startPy);
    return;
  }
  // 启动前清掉过期 token 文件，避免读到老 token
  try { fs.unlinkSync(TOKEN_PATH); } catch { /* ignore */ }

  const pyCmd = process.env.AAS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  console.info('[aas-electron] spawning:', pyCmd, 'start.py --mode gui');
  pythonProc = spawn(pyCmd, ['start.py', '--mode', 'gui'], {
    cwd: PROJECT_ROOT,
    stdio: ['ignore', 'inherit', 'inherit'],
    detached: false,
  });
  pythonProc.on('exit', (code, signal) => {
    console.warn(`[aas-electron] python exited code=${code} signal=${signal}`);
    pythonProc = null;
    // 仅当用户没主动退出时考虑重启（这里先不自动重启，让用户手动重开）
  });
}

function killPython() {
  if (!pythonProc) return;
  try {
    if (process.platform === 'win32') {
      // Windows: 用 taskkill /T 杀进程树
      spawn('taskkill', ['/pid', String(pythonProc.pid), '/T', '/F']);
    } else {
      pythonProc.kill('SIGTERM');
    }
  } catch (e) {
    console.error('[aas-electron] killPython failed:', e);
  }
  pythonProc = null;
}

// ============================================================================
// 等待 token 文件出现
// ============================================================================
async function waitForToken(timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (fs.existsSync(TOKEN_PATH)) {
      const token = fs.readFileSync(TOKEN_PATH, 'utf-8').trim();
      if (token) return token;
    }
    await new Promise(r => setTimeout(r, 500));
  }
  throw new Error(`token 文件 ${TOKEN_PATH} 在 ${timeoutMs}ms 内未生成`);
}

// ============================================================================
// 创建主窗口
// ============================================================================
async function createWindow() {
  let token = '';
  try {
    token = await waitForToken(60_000);
    console.info('[aas-electron] token ready, preparing window');
  } catch (e) {
    console.error('[aas-electron] token wait failed:', e.message);
    // 继续创建窗口，让前端在"未连接"状态下显示，用户可看到错误
  }

  const win = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    title: '自动打卡系统',
    backgroundColor: '#2a2926',
    // 自绘标题栏（设计稿本身是 Win 11 风格的 chrome）
    frame: false,
    titleBarStyle: 'hidden',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: [
        `--aas-token=${token}`,
        `--aas-http=http://127.0.0.1:${HTTP_PORT}`,
        `--aas-ws=ws://127.0.0.1:${WS_PORT}`,
      ],
    },
  });

  mainWindow = win;

  win.once('ready-to-show', () => win.show());

  win.on('close', e => {
    if (!appQuitting) {
      e.preventDefault();
      win.hide();
    }
  });

  // 外链用系统浏览器打开，不在 Electron 内部跳转
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  if (IS_DEV) {
    await win.loadURL(DEV_SERVER_URL);
  } else {
    await win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }
}

// ============================================================================
// 托盘菜单
// ============================================================================
function createTray() {
  const iconPath = path.join(__dirname, 'tray-icon.png');
  let image;
  if (fs.existsSync(iconPath)) {
    image = nativeImage.createFromPath(iconPath);
  } else {
    // 占位 16x16 透明 PNG
    image = nativeImage.createEmpty();
  }
  tray = new Tray(image);
  tray.setToolTip('自动打卡系统');
  const menu = Menu.buildFromTemplate([
    { label: '显示主窗口', click: () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } } },
    { type: 'separator' },
    { label: '打开日志目录', click: () => shell.openPath(path.join(PROJECT_ROOT, 'logs')) },
    { label: '打开 punch_records', click: () => shell.openPath(path.join(PROJECT_ROOT, 'punch_records')) },
    { type: 'separator' },
    { label: '退出（停止 Bot + GUI）', click: () => { appQuitting = true; app.quit(); } },
  ]);
  tray.setContextMenu(menu);
  tray.on('double-click', () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } });
}

// ============================================================================
// 生命周期
// ============================================================================
app.on('ready', async () => {
  spawnPython();
  await createWindow();
  createTray();
});

app.on('window-all-closed', () => {
  // 我们把关窗变成隐藏到托盘，所以这里只在 macOS 之外才退出
  // 因为 close 已经 preventDefault，这个事件不会触发，留作保险
  if (process.platform !== 'darwin') {
    // do nothing — let user explicitly quit from tray
  }
});

app.on('before-quit', () => {
  appQuitting = true;
  killPython();
});
