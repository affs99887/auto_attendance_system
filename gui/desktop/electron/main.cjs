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
// 后端可写数据根：dev=项目根；打包=用户指定的现有数据目录（含真实记录/截图/配置）。
// 可用环境变量 AAS_DATA_DIR 覆盖，便于将来切到 %APPDATA% 等。
const LEGACY_DATA_DIR = 'C:\\auto_attendance_system';
const DATA_DIR = process.env.AAS_DATA_DIR
  || (app.isPackaged ? LEGACY_DATA_DIR : PROJECT_ROOT);
const TOKEN_PATH = path.join(DATA_DIR, 'logs', '.gui_token');
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
// 服务控制状态机标志（供 service:* IPC 区分「手动停止 / 重启 / 崩溃」三种 exit）
//  - manualStop:        true 表示本次 exit 是用户主动停止（service:stop），不自动重启
//  - restarting:        true 表示本次 exit 是用户主动重启（service:restart），exit 后再 spawn
//  - lastServiceRunning:最近一次推给渲染进程的运行状态，供 did-finish-load 补推
// ============================================================================
let manualStop = false;
let restarting = false;
let lastServiceRunning = true;

// ============================================================================
// 后端启动状态（推给渲染进程的 backend:status）
//  - latestStatus: 最近一次状态，供 backend:get-status 拉取 + did-finish-load 补推
//  - readyGen:     代际计数，每次（重）spawn 自增，作废旧的 waitForToken 结果
// ============================================================================
let latestStatus = { state: 'starting', reason: null };
let readyGen = 0;

// 启动日志环形缓冲（最近 N 行 python stdout/stderr），供启动覆盖层实时展示
const LOG_BUFFER_MAX = 300;
let logBuffer = [];
let logCarry = ''; // 跨 data 块的半行残留

function pushStatus(payload) {
  latestStatus = payload;
  if (mainWindow && !mainWindow.isDestroyed() && !appQuitting) {
    try { mainWindow.webContents.send('backend:status', payload); } catch { /* ignore */ }
  }
}

// 推送「服务运行状态」给渲染进程（独立通道 service:status）
//  - 绝不复用 backend:status：那条通道会触发 StartupOverlay 的全屏 failed/启动中遮罩，
//    服务停止/重启不应弹启动遮罩，故单独走 service:status 只带 { running }。
function pushServiceStatus(running) {
  lastServiceRunning = running;
  if (mainWindow && !mainWindow.isDestroyed() && !appQuitting) {
    try { mainWindow.webContents.send('service:status', { running }); } catch { /* ignore */ }
  }
}

// 启动日志：入环形缓冲并增量推给渲染进程
function pushLogLines(lines) {
  if (!lines.length) return;
  for (const ln of lines) logBuffer.push(ln);
  if (logBuffer.length > LOG_BUFFER_MAX) logBuffer.splice(0, logBuffer.length - LOG_BUFFER_MAX);
  if (mainWindow && !mainWindow.isDestroyed() && !appQuitting) {
    try { mainWindow.webContents.send('backend:log', { lines }); } catch { /* ignore */ }
  }
}

// 把一块 stdout/stderr 文本解析成显示行：剥离 ANSI、处理 \r 同行刷新、半行跨块续接
function ingestChunk(text) {
  const cleaned = text.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, ''); // 剥离 ANSI CSI 转义
  const parts = (logCarry + cleaned).split('\n');
  logCarry = parts.pop() ?? ''; // 末尾无换行的半行留到下一块
  const out = [];
  for (let seg of parts) {
    seg = seg.replace(/\r+$/, '');                                      // 去 \r\n 行尾
    if (seg.includes('\r')) seg = seg.slice(seg.lastIndexOf('\r') + 1); // 进度条同行刷新只留末帧
    if (seg.length) out.push(seg);
  }
  pushLogLines(out);
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
  // 每轮启动从头展示日志：清空缓冲（崩溃重启时不残留上一轮 traceback）
  logBuffer = [];
  logCarry = '';

  const pyCmd = process.env.AAS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  console.info('[aas-electron] spawning:', pyCmd, mainPy, '--gui', '(cwd:', DATA_DIR + ')');
  // 用绝对脚本路径运行打包内 main.py（sys.path[0]=resources/backend → 导入打包副本的 modules），
  // 但 cwd 指向数据根 DATA_DIR，使后端所有相对路径（punch_records/screenshots/logs/.env 等）命中真实数据。
  pythonProc = spawn(pyCmd, [mainPy, '--gui'], {
    cwd: DATA_DIR,
    // 不用 'inherit'：Electron 主进程无 console，inherit 会让 python 自己开一个控制台窗口
    stdio: ['ignore', 'pipe', 'pipe'],
    // windowsHide → CREATE_NO_WINDOW，python.exe 不弹黑窗
    windowsHide: true,
    detached: false,
    // GUI/管道环境：朴素文本(去 ANSI/清屏) + 行不缓冲(实时) + 强制 UTF-8(中文不乱码)。
    // configure_console_encoding 只设 errors=replace 不强制 utf-8，故 PYTHONIOENCODING 必须显式给。
    env: { ...process.env, AAS_PLAIN_CONSOLE: '1', PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
  });
  // python 的 stdout/stderr：转发到 Electron 控制台调试 + 解析进启动日志缓冲推给渲染进程
  pythonProc.stdout?.on('data', d => { process.stdout.write(`[py] ${d}`); ingestChunk(d.toString('utf8')); });
  pythonProc.stderr?.on('data', d => { process.stderr.write(`[py] ${d}`); ingestChunk(d.toString('utf8')); }); // traceback 在 stderr

  // spawn 失败（python 不在 PATH / 无法执行）只触发 'error' 不触发 'exit'——首装最高频故障
  pythonProc.on('error', err => {
    console.error('[aas-electron] python spawn error:', err.message);
    pushStatus({
      state: 'failed',
      reason: `无法启动 Python（${err.message}）。请确认已安装 Python 并加入 PATH。`,
    });
    pushServiceStatus(false); // spawn 失败：服务未运行
  });

  pythonProc.on('exit', (code, signal) => {
    console.warn(`[aas-electron] python exited code=${code} signal=${signal}`);
    pythonProc = null;
    if (appQuitting) return;

    // —— 服务控制三分支：手动停止 / 主动重启 / 崩溃 ——
    // 1) 用户主动停止：清标志、推 running=false，不自动重启
    if (manualStop) { manualStop = false; pushServiceStatus(false); return; }
    // 2) 用户主动重启：清标志，延迟 300ms 后重新 spawn（spawn 成功会推 running=true）
    if (restarting) { restarting = false; setTimeout(() => { if (!appQuitting) spawnPython(); }, 300); return; }
    // 3) 其余为崩溃：进入下方原有限频自动重启逻辑

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
      pushServiceStatus(false); // 彻底放弃自动重启：服务已停止
      return;
    }
    restartHistory.push(now);
    console.info(`[aas-electron] 2 秒后自动重启 Python (第 ${restartHistory.length}/${RESTART_MAX} 次)`);
    setTimeout(() => { if (!appQuitting) spawnPython(); }, 2000);
  });

  // 拉起后开始侦测就绪（重启也会重新 arm，旧代际自动作废）
  armReadiness();
  pushServiceStatus(true); // spawn 成功：服务已在运行
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

  // 渲染进程加载完成后补推一次最近状态 + 当前启动日志全量（解决 push 早于渲染进程注册监听的竞态；HMR/重载也安全幂等）
  win.webContents.on('did-finish-load', () => {
    pushStatus(latestStatus);
    pushServiceStatus(lastServiceRunning); // 补推服务运行状态（解决 push 早于渲染进程注册监听的竞态）
    if (logBuffer.length) {
      try { win.webContents.send('backend:log', { lines: logBuffer.slice() }); } catch { /* ignore */ }
    }
  });

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
    { label: '打开日志目录', click: () => shell.openPath(path.join(DATA_DIR, 'logs')) },
    { label: '打开 punch_records', click: () => shell.openPath(path.join(DATA_DIR, 'punch_records')) },
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

// 启动日志全量拉取（渲染进程注册晚于早期日志时兜底）
ipcMain.handle('backend:get-log', () => logBuffer.slice());

// 选本地 Clash 配置文件，读内容回传渲染进程填入 textarea（dev/packaged 均可用）
ipcMain.handle('proxy:pick-config-file', async () => {
  const r = await dialog.showOpenDialog(mainWindow, {
    title: '选择 Clash 配置文件',
    properties: ['openFile'],
    filters: [
      { name: 'Clash 配置', extensions: ['yaml', 'yml'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });
  if (r.canceled || !r.filePaths || r.filePaths.length === 0) return null;
  const fp = r.filePaths[0];
  if (fs.statSync(fp).size > 2 * 1024 * 1024) {
    throw new Error('配置文件过大（>2MB），请确认选对了文件');
  }
  return { name: path.basename(fp), content: fs.readFileSync(fp, 'utf-8') };
});

ipcMain.handle('system:open-logs', () => {
  const dir = path.join(DATA_DIR, 'logs');
  try { fs.mkdirSync(dir, { recursive: true }); } catch { /* ignore */ }
  return shell.openPath(dir); // 返回空串=成功，非空=错误信息
});

// 用系统默认图片查看器打开本地截图原图（入参为后端返回的相对路径，如 screenshots\user\punch_in\xxx.png）
// 返回空串=成功，非空=错误信息（resolve 给渲染进程）
ipcMain.handle('screenshot:open', (_e, relPath) => {
  try {
    if (typeof relPath !== 'string' || !relPath) return 'invalid path';
    const root = path.resolve(DATA_DIR, 'screenshots');
    const abs = path.resolve(DATA_DIR, relPath);
    // 防目录穿越：必须落在 DATA_DIR/screenshots 之内
    if (abs !== root && !abs.startsWith(root + path.sep)) return 'forbidden path';
    if (!fs.existsSync(abs) || !fs.statSync(abs).isFile()) return 'file not found';
    return shell.openPath(abs); // 调系统默认图片查看器
  } catch (e) {
    return String((e && e.message) || e);
  }
});

// ============================================================================
// 服务控制 IPC（启动 / 停止 / 重启 后端 Python 进程）
//  - 运行状态以 pythonProc != null 为准
//  - manualStop / restarting 标志告诉 exit handler 本次退出该如何处理
// ============================================================================
ipcMain.handle('service:get-status', () => {
  return { running: pythonProc != null };
});

ipcMain.handle('service:start', () => {
  if (pythonProc) return { success: true, message: '已在运行' };
  manualStop = false;
  restarting = false;
  spawnPython(); // 成功会在 spawnPython 末尾推 service:status running=true
  return { success: true };
});

ipcMain.handle('service:stop', () => {
  if (!pythonProc) { pushServiceStatus(false); return { success: true, message: '未在运行' }; }
  manualStop = true; // 标记为主动停止：exit handler 不会自动重启
  killPython();
  return { success: true };
});

ipcMain.handle('service:restart', () => {
  if (!pythonProc) { manualStop = false; spawnPython(); return { success: true }; }
  restarting = true; // 标记为主动重启：exit handler 退出后会再 spawn（这里不二次 spawn，避免双进程竞态）
  killPython();
  return { success: true };
});

// ============================================================================
// 一次性数据迁移（安全网，仅打包模式）
//  - 仅当 DATA_DIR 改到「与现有目录不同的别处」（如 %APPDATA%）且尚未迁过时才执行；
//  - 默认 DATA_DIR 即 LEGACY_DATA_DIR（C:\auto_attendance_system）时直接 return，为空操作；
//  - 逐项拷贝，目标已存在则跳过，绝不覆盖；完成写 .migrated 标记，只迁一次。
// ============================================================================
function migrateLegacyDataIfNeeded() {
  if (!app.isPackaged) return;
  if (path.resolve(DATA_DIR) === path.resolve(LEGACY_DATA_DIR)) return; // 指向现有目录=无需迁移
  if (!fs.existsSync(LEGACY_DATA_DIR)) return;                           // 没有旧数据可迁
  const marker = path.join(DATA_DIR, '.migrated');
  if (fs.existsSync(marker)) return;                                    // 只迁一次
  try { fs.mkdirSync(DATA_DIR, { recursive: true }); } catch { /* ignore */ }
  for (const name of ['punch_records', 'screenshots', '.env', 'dynamic_config.json', 'scheduled_tasks.json']) {
    const src = path.join(LEGACY_DATA_DIR, name);
    const dst = path.join(DATA_DIR, name);
    if (fs.existsSync(src) && !fs.existsSync(dst)) {                     // 目标已存在则跳过，绝不覆盖
      try {
        fs.cpSync(src, dst, { recursive: true, force: false, errorOnExist: false });
        console.info('[aas-electron] migrated', name, '->', dst);
      } catch (e) {
        console.warn('[aas-electron] migrate skip', name, e.message);
      }
    }
  }
  try { fs.writeFileSync(marker, new Date().toISOString()); } catch { /* ignore */ }
}

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
  migrateLegacyDataIfNeeded();
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
