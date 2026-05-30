// Electron 主进程
// - spawn `python main.py --gui` 作为后端（windowsHide，无控制台窗口）
// - 窗口与后端【并行】启动：窗口立刻创建显示，不再等 token
// - 后端就绪后（写出 logs/.gui_token）由主进程经 IPC 把 token 异步推给渲染进程
// - dev 模式加载 Vite dev server，prod 模式加载 dist/
// - 单实例锁 + 托盘菜单 + 关窗口缩到托盘
//
// 启动方式：
//   1. dev:  AAS_DEV=1 npx electron electron/main.cjs   （Vite 必须先启）
//   2. prod: npx electron .                             （走 build 后的 dist）

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, dialog, ipcMain } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn, execFileSync } = require('node:child_process');

// 项目根目录：
//  - dev: gui/desktop/electron/../../../ → C:\auto_attendance_system
//  - packaged: resources/backend/（由 electron-builder.yml extraResources 复制）
const PROJECT_ROOT = app.isPackaged
  ? path.join(process.resourcesPath, 'backend')
  : path.resolve(__dirname, '..', '..', '..');
const TOKEN_PATH = path.join(PROJECT_ROOT, 'logs', '.gui_token');
const DEV_SERVER_URL = process.env.AAS_DEV_SERVER || 'http://127.0.0.1:5173';
const HTTP_PORT = parseInt(process.env.AAS_HTTP_PORT || '8765', 10);
const WS_PORT = parseInt(process.env.AAS_WS_PORT || '8766', 10);
const IS_DEV = Boolean(process.env.AAS_DEV);

let pythonProc = null;
let mainWindow = null;
let tray = null;
let appQuitting = false;

// 崩溃重启频率控制（最近 1 小时内最多 5 次）
const RESTART_WINDOW_MS = 3600 * 1000;
const RESTART_MAX = 5;
let restartHistory = [];

// ============================================================================
// 后端启动状态（推给渲染进程的 backend:status）
//  - latestStatus: 最近一次状态，供 backend:get-status 拉取 + did-finish-load 补推
//  - readyGen:     代际计数，每次（重）spawn 自增，作废旧的 waitForToken 结果
// ============================================================================
let latestStatus = { state: 'starting', reason: null };
let readyGen = 0;

function pushStatus(payload) {
  latestStatus = payload;
  if (mainWindow && !mainWindow.isDestroyed() && !appQuitting) {
    try { mainWindow.webContents.send('backend:status', payload); } catch { /* ignore */ }
  }
}

// 每次 spawn 后重新 arm：等 token → 推给渲染进程；超时/失败 → 推 failed
function armReadiness() {
  const gen = ++readyGen;
  pushStatus({ state: 'starting', reason: null });
  waitForToken(120_000)
    .then(token => {
      if (gen !== readyGen) return; // 已有更新的 spawn，丢弃过期 token
      console.info('[aas-electron] token ready, notifying renderer');
      pushStatus({
        state: 'token',
        token,
        httpUrl: `http://127.0.0.1:${HTTP_PORT}`,
        wsUrl: `ws://127.0.0.1:${WS_PORT}`,
      });
    })
    .catch(err => {
      if (gen !== readyGen) return;
      console.error('[aas-electron] token wait failed:', err.message);
      pushStatus({ state: 'failed', reason: `后端启动超时：${err.message}（端口可能被占用，请查看日志）` });
    });
}

// ============================================================================
// 启动 Python 后端 + 崩溃重启
// ============================================================================
function spawnPython() {
  // 直接跑 main.py --gui（跳过 start.py 那层 subprocess，少一个进程、少一个窗口）
  const mainPy = path.join(PROJECT_ROOT, 'main.py');
  if (!fs.existsSync(mainPy)) {
    console.error('[aas-electron] main.py not found:', mainPy);
    pushStatus({ state: 'failed', reason: `未找到 main.py：${mainPy}` });
    return;
  }
  // 启动前清掉过期 token 文件，避免读到老 token
  try { fs.unlinkSync(TOKEN_PATH); } catch { /* ignore */ }

  const pyCmd = process.env.AAS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  console.info('[aas-electron] spawning:', pyCmd, 'main.py --gui');
  pythonProc = spawn(pyCmd, ['main.py', '--gui'], {
    cwd: PROJECT_ROOT,
    // 不用 'inherit'：Electron 主进程无 console，inherit 会让 python 自己开一个控制台窗口
    stdio: ['ignore', 'pipe', 'pipe'],
    // windowsHide → CREATE_NO_WINDOW，python.exe 不弹黑窗
    windowsHide: true,
    detached: false,
  });
  // python 的 stdout/stderr 转发到 Electron 控制台便于调试（不再有独立窗口）
  pythonProc.stdout?.on('data', d => process.stdout.write(`[py] ${d}`));
  pythonProc.stderr?.on('data', d => process.stderr.write(`[py] ${d}`));

  // spawn 失败（python 不在 PATH / 无法执行）只触发 'error' 不触发 'exit'——首装最高频故障
  pythonProc.on('error', err => {
    console.error('[aas-electron] python spawn error:', err.message);
    pushStatus({
      state: 'failed',
      reason: `无法启动 Python（${err.message}）。请确认已安装 Python 并加入 PATH。`,
    });
  });

  pythonProc.on('exit', (code, signal) => {
    console.warn(`[aas-electron] python exited code=${code} signal=${signal}`);
    pythonProc = null;
    if (appQuitting) return;

    // 检查重启频率
    const now = Date.now();
    restartHistory = restartHistory.filter(t => now - t < RESTART_WINDOW_MS);
    if (restartHistory.length >= RESTART_MAX) {
      console.error(`[aas-electron] 重启过频（最近 1 小时已 ${restartHistory.length} 次），停止自动重启`);
      pushStatus({ state: 'failed', reason: `Python 后端反复崩溃（1 小时内 ${restartHistory.length} 次），已停止自动重启。请查看日志。` });
      if (mainWindow) {
        dialog.showErrorBox(
          'Python 后端反复崩溃',
          `过去 1 小时内已重启 ${restartHistory.length} 次，已停止自动重启。\n请检查 logs/attendance_system.log 后手动重启程序。`,
        );
      }
      return;
    }
    restartHistory.push(now);
    console.info(`[aas-electron] 2 秒后自动重启 Python (第 ${restartHistory.length}/${RESTART_MAX} 次)`);
    setTimeout(() => { if (!appQuitting) spawnPython(); }, 2000);
  });

  // 拉起后开始侦测就绪（重启也会重新 arm，旧代际自动作废）
  armReadiness();
}

// ============================================================================
// watchdog 互斥检查
// ============================================================================
function checkWatchdogRunning() {
  if (process.platform !== 'win32') return false;
  try {
    const out = execFileSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        "(Get-CimInstance Win32_Process -Filter \"name='python.exe' OR name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*watchdog.py*' } | Measure-Object).Count",
      ],
      { encoding: 'utf8', timeout: 8000, windowsHide: true },
    );
    return parseInt(String(out).trim(), 10) > 0;
  } catch (e) {
    console.warn('[aas-electron] watchdog 检测失败（跳过）:', e.message);
    return false;
  }
}

function killPython() {
  if (!pythonProc) return;
  try {
    if (process.platform === 'win32') {
      // Windows: 用 taskkill /T 杀进程树（连带 python 拉起的 mihomo 子进程一起回收）
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
// 创建主窗口（不再等 token —— 立刻显示，token 经 IPC 后到）
// ============================================================================
async function createWindow() {
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
      // token 不再随窗口创建注入（窗口先于后端就绪），仅保留 http/ws 默认值；
      // token 由 backend:status('token') 异步推送
      additionalArguments: [
        `--aas-http=http://127.0.0.1:${HTTP_PORT}`,
        `--aas-ws=ws://127.0.0.1:${WS_PORT}`,
      ],
    },
  });

  mainWindow = win;

  win.once('ready-to-show', () => win.show());

  // 渲染进程加载完成后补推一次最近状态（解决 push 早于渲染进程注册监听的竞态；HMR/重载也安全幂等）
  win.webContents.on('did-finish-load', () => pushStatus(latestStatus));

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
// 窗口控制 IPC（自绘标题栏的三个按钮）
// ============================================================================
ipcMain.on('window:minimize', () => {
  mainWindow?.minimize();
});
ipcMain.on('window:maximize-toggle', () => {
  if (!mainWindow) return;
  if (mainWindow.isMaximized()) mainWindow.unmaximize();
  else mainWindow.maximize();
});
ipcMain.on('window:close', () => {
  // close 走 win.on('close') → 隐藏到托盘（appQuitting=false 时）
  mainWindow?.close();
});
ipcMain.handle('window:is-maximized', () => mainWindow?.isMaximized() ?? false);

// ============================================================================
// 后端状态拉取 + 打开日志（供"系统启动中"覆盖层使用）
// ============================================================================
ipcMain.handle('backend:get-status', () => latestStatus);

ipcMain.handle('system:open-logs', () => {
  const dir = path.join(PROJECT_ROOT, 'logs');
  try { fs.mkdirSync(dir, { recursive: true }); } catch { /* ignore */ }
  return shell.openPath(dir); // 返回空串=成功，非空=错误信息
});

// ============================================================================
// 生命周期
// ============================================================================
app.on('ready', async () => {
  if (checkWatchdogRunning()) {
    const choice = dialog.showMessageBoxSync({
      type: 'warning',
      title: '检测到 watchdog 运行中',
      message: '检测到 watchdog.py 进程正在运行',
      detail:
        'watchdog 会自动启动一个 main.py，与 GUI 模式启动的 Python 进程冲突（Telegram bot polling 重复、共享文件竞争）。\n\n' +
        '建议：先停止 watchdog（任务管理器结束 python.exe 或对应终端 Ctrl+C），再启动 GUI。',
      buttons: ['仍然继续启动', '退出'],
      defaultId: 1,
      cancelId: 1,
    });
    if (choice === 1) {
      app.exit(0);
      return;
    }
  }
  // 窗口与后端并行：先拉起后端，再立刻建窗口（窗口不等 token）
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
