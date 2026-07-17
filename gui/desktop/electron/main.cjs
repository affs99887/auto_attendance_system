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

const { app, BrowserWindow, Tray, Menu, nativeImage, shell, dialog, ipcMain, screen, powerMonitor, net } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn, execFileSync } = require('node:child_process');

// 项目根目录：
//  - dev: gui/desktop/electron/../../../ → C:\auto_attendance_system
//  - packaged: resources/backend/（由 electron-builder.yml extraResources 复制）
const PROJECT_ROOT = app.isPackaged
  ? path.join(process.resourcesPath, 'backend')
  : path.resolve(__dirname, '..', '..', '..');
// 后端可写数据根：dev=项目根；打包=平台各自的数据目录（含配置与日志）。
// 可用环境变量 AAS_DATA_DIR 覆盖，便于将来切到其它位置。
const LEGACY_DATA_DIR = 'C:\\auto_attendance_system';
// macOS 打包态用系统标准的 userData 目录（~/Library/Application Support/<app>），
// Windows 沿用历史固定目录以兼容既有用户数据
const PACKAGED_DATA_DIR = process.platform === 'darwin'
  ? app.getPath('userData')
  : LEGACY_DATA_DIR;
const DATA_DIR = process.env.AAS_DATA_DIR
  || (app.isPackaged ? PACKAGED_DATA_DIR : PROJECT_ROOT);
const TOKEN_PATH = path.join(DATA_DIR, 'logs', '.gui_token');
// 窗口尺寸/位置/最大化状态持久化文件（关窗缩托盘不退进程，靠 resize/move 防抖落盘覆盖关闭场景）
const WINDOW_STATE_PATH = path.join(DATA_DIR, 'window-state.json');
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
// 重启定时器句柄（崩溃 2s / 主动重启 300ms 共用一个槽位）。
// 存成模块变量使其可被 spawnPython/service:stop/before-quit 主动取消，
// 杜绝「定时器到点时旧引用已被新 spawn 占用 → 再 spawn 覆盖成孤儿」的竞态。
let pendingRestartTimer = null;
// 正在等待某个被 kill 的进程 exit（service:stop/restart 发出 taskkill 后置 true，
// 该进程 exit 处理完成后清回 false）。期间拒绝并发的 service:* 请求，
// 避免「旧进程未真正退出就被第二条请求当作已停止」而再 spawn 出双进程。
let killPending = false;

// 取消挂起的重启定时器（统一入口，防止句柄泄漏后回调误触发 spawn）
function clearPendingRestart() {
  if (pendingRestartTimer) {
    clearTimeout(pendingRestartTimer);
    pendingRestartTimer = null;
  }
}

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
function resolvePythonCommand() {
  if (process.env.AAS_PYTHON) return process.env.AAS_PYTHON;
  if (process.platform === 'win32') return 'python';
  if (process.platform === 'darwin') {
    // Finder 启动的 app 拿到的 PATH 不含 Homebrew 目录，按常见安装位置探测绝对路径；
    // /usr/bin/python3 放最后（未装 Command Line Tools 时它是个会弹安装窗的替身）
    const candidates = ['/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3'];
    for (const cand of candidates) {
      if (fs.existsSync(cand)) return cand;
    }
  }
  return 'python3';
}

function spawnPython() {
  // 守卫：已有在跟踪的进程时直接返回，杜绝旧进程存活时被新 spawn 覆盖引用（孤儿根因之一）。
  if (pythonProc) {
    console.warn('[aas-electron] spawnPython 跳过：已有 Python 进程在运行');
    return;
  }
  // 进入新一轮 spawn，先取消任何挂起的重启定时器，避免它到点后再 spawn 出第二个进程。
  clearPendingRestart();
  // 直接跑 main.py --gui（跳过 start.py 那层 subprocess，少一个进程、少一个窗口）
  const mainPy = path.join(PROJECT_ROOT, 'main.py');
  if (!fs.existsSync(mainPy)) {
    console.error('[aas-electron] main.py not found:', mainPy);
    pushStatus({ state: 'failed', reason: `未找到 main.py：${mainPy}` });
    return;
  }
  // cwd 不存在时 spawn 直接报 ENOENT（mac 首启时 userData 目录尚未建立），先确保存在
  try { fs.mkdirSync(DATA_DIR, { recursive: true }); } catch { /* ignore */ }
  // 启动前清掉过期 token 文件，避免读到老 token
  try { fs.unlinkSync(TOKEN_PATH); } catch { /* ignore */ }
  // 每轮启动从头展示日志：清空缓冲（崩溃重启时不残留上一轮 traceback）
  logBuffer = [];
  logCarry = '';

  const pyCmd = resolvePythonCommand();
  console.info('[aas-electron] spawning:', pyCmd, mainPy, '--gui', '(cwd:', DATA_DIR + ')');
  // 用绝对脚本路径运行打包内 main.py（sys.path[0]=resources/backend → 导入打包副本的 modules），
  // 但 cwd 指向数据根 DATA_DIR，使后端所有相对路径（logs/.env/dynamic_config.json 等）命中真实数据。
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
  // 闭包捕获本次 spawn 出的 proc：用它与全局 pythonProc 比对，过滤掉「过期进程」的迟到 error/exit。
  const proc = pythonProc;
  // python 的 stdout/stderr：转发到 Electron 控制台调试 + 解析进启动日志缓冲推给渲染进程
  pythonProc.stdout?.on('data', d => { process.stdout.write(`[py] ${d}`); ingestChunk(d.toString('utf8')); });
  pythonProc.stderr?.on('data', d => { process.stderr.write(`[py] ${d}`); ingestChunk(d.toString('utf8')); }); // traceback 在 stderr

  // spawn 失败（python 不在 PATH / 无法执行）只触发 'error' 不触发 'exit'——首装最高频故障
  pythonProc.on('error', err => {
    console.error('[aas-electron] python spawn error:', err.message);
    // 该路径不会再来 'exit'，必须在此清空引用：否则配合开头的 `if (pythonProc) return` 守卫，
    // 残留的失败 proc 引用会永久挡住后续 service:start/重启。仅当仍是本次 proc 才清，避免误清新进程。
    if (pythonProc === proc) pythonProc = null;
    // 'error' 不会再触发 'exit'，三态标志的复位本应在 exit 处理器完成，这里必须补做：
    // 否则若本次 spawn 是 service:restart 触发（restarting=true）却 spawn 失败，restarting 将悬空残留，
    // 待用户经 service:restart 的 `!pythonProc` 分支重新拉起新进程后，新进程将来真实崩溃时会误入 restarting
    // 分支绕过限频统计直接重启。manualStop 同理一并复位，确保状态机回到干净的「未运行」态。
    restarting = false;
    manualStop = false;
    killPending = false; // 解除可能的并发拒绝
    pushStatus({
      state: 'failed',
      reason: `无法启动 Python（${err.message}）。请确认已安装 Python 并加入 PATH。`,
    });
    pushServiceStatus(false); // spawn 失败：服务未运行
  });

  pythonProc.on('exit', (code, signal) => {
    console.warn(`[aas-electron] python exited code=${code} signal=${signal}`);
    // 只有退出的正是当前跟踪的进程才清空引用；否则是已被替换的旧进程的迟到 exit，作废以免清掉新进程。
    if (pythonProc === proc) {
      pythonProc = null;
    } else {
      console.warn('[aas-electron] 忽略过期 Python 进程的 exit（引用已被新进程占用）');
      return;
    }
    // 本进程是被 service:stop/restart 主动 kill 的：此 exit 到达即解除并发拒绝，放行后续 service:* 请求。
    killPending = false;
    if (appQuitting) return;

    // —— 服务控制三分支：手动停止 / 主动重启 / 崩溃 ——
    // 1) 用户主动停止：清标志、推 running=false，不自动重启
    if (manualStop) { manualStop = false; pushServiceStatus(false); return; }
    // 2) 用户主动重启：清标志，延迟 300ms 后重新 spawn（spawn 成功会推 running=true）
    //    定时器句柄存入 pendingRestartTimer 以便可取消；回调内再校验 !pythonProc && !manualStop 防覆盖。
    if (restarting) {
      restarting = false;
      clearPendingRestart();
      pendingRestartTimer = setTimeout(() => {
        pendingRestartTimer = null;
        if (!appQuitting && !pythonProc && !manualStop) spawnPython();
      }, 300);
      return;
    }
    // 3) 其余为崩溃：进入下方原有限频自动重启逻辑

    // 检查重启频率
    const now = Date.now();
    restartHistory = restartHistory.filter(t => now - t < RESTART_WINDOW_MS);
    if (restartHistory.length >= RESTART_MAX) {
      console.error(`[aas-electron] 重启过频（最近 1 小时已 ${restartHistory.length} 次），停止自动重启`);
      // 不再弹系统 showErrorBox：pushStatus(failed) 已把原因推给渲染端（系统横幅/启动覆盖层展示）
      pushStatus({ state: 'failed', reason: `Python 后端反复崩溃（1 小时内 ${restartHistory.length} 次），已停止自动重启。请查看 logs/app.log 后手动重启。` });
      pushServiceStatus(false); // 彻底放弃自动重启：服务已停止
      return;
    }
    restartHistory.push(now);
    console.info(`[aas-electron] 2 秒后自动重启 Python (第 ${restartHistory.length}/${RESTART_MAX} 次)`);
    // 同样把句柄存入 pendingRestartTimer，回调内再校验：若用户已手动启动/停止则不再补 spawn。
    clearPendingRestart();
    pendingRestartTimer = setTimeout(() => {
      pendingRestartTimer = null;
      if (!appQuitting && !pythonProc && !manualStop) spawnPython();
    }, 2000);
  });

  // 拉起后开始侦测就绪（重启也会重新 arm，旧代际自动作废）
  armReadiness();
  pushServiceStatus(true); // spawn 成功：服务已在运行
}

// ============================================================================
// watchdog 互斥检查
// ============================================================================
function checkWatchdogRunning() {
  if (process.platform === 'darwin') {
    try {
      const out = execFileSync('pgrep', ['-f', 'watchdog.py'], { encoding: 'utf8', timeout: 8000 });
      return String(out).trim().length > 0;
    } catch {
      // pgrep 无匹配时以退出码 1 结束，落到这里视为未运行
      return false;
    }
  }
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
  // 进程从未真正起来（spawn 失败 / pid 未分配）：taskkill /pid undefined 会静默失败，
  // 且这种 proc 不会触发 'exit'，引用永远不会被清。此处直接置空并复位状态机，
  // 否则 killPending=true 与残留 pythonProc 会双重卡死后续 service:* 控制。
  if (pythonProc.pid == null) {
    pythonProc = null;
    killPending = false;
    restarting = false;
    manualStop = false;
    pushServiceStatus(false);
    return;
  }
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
  // 不在此处置空 pythonProc：taskkill 是异步发出的，旧进程此刻尚未真正退出。
  // 引用统一由该进程的 'exit' 处理器在确认 pythonProc === proc 后清空，
  // 避免「刚置 null → 并发请求误判已停止 → 再 spawn 出双进程」的竞态。
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
  // 超时抛错前最后再查一次：截止判定基于挂钟（Date.now），若机器在等待期间睡眠，
  // 唤醒后 while 条件会先判超时退出而跳过检查——但 token 文件此刻可能早已写出。
  // 这里补一次读取，避免「睡眠跨过启动窗口 → 唤醒即误报启动超时」。
  if (fs.existsSync(TOKEN_PATH)) {
    const token = fs.readFileSync(TOKEN_PATH, 'utf-8').trim();
    if (token) return token;
  }
  throw new Error(`token 文件 ${TOKEN_PATH} 在 ${timeoutMs}ms 内未生成`);
}

// ============================================================================
// 睡眠/唤醒处理（修复 M93：唤醒后误报启动超时 / 不对后端做任何健康检查）
//  - HTTP GET /api/v1/ping 探活：用 Electron net（走主进程，无跨域/鉴权约束），
//    后端 ping 无需 token，只确认 HTTP 真在监听。
//  - handleResume：唤醒后若仍认为后端在运行（pythonProc != null），先重新 armReadiness（token
//    已存在则立即推送，把渲染端从睡眠中可能误置的 failed/starting 态拉回 ready），再探活；
//    后端无响应则按崩溃路径处理（kill 僵尸引用，由 exit 处理器走限频自动重启）。
// ============================================================================
function pingBackend(timeoutMs = 4000) {
  return new Promise(resolve => {
    let done = false;
    const finish = ok => { if (!done) { done = true; resolve(ok); } };
    try {
      const req = net.request(`http://127.0.0.1:${HTTP_PORT}/api/v1/ping`);
      const timer = setTimeout(() => { try { req.abort(); } catch { /* ignore */ } finish(false); }, timeoutMs);
      req.on('response', res => { clearTimeout(timer); finish(res.statusCode >= 200 && res.statusCode < 500); res.on('data', () => {}); });
      req.on('error', () => { clearTimeout(timer); finish(false); });
      req.end();
    } catch {
      finish(false);
    }
  });
}

async function handleResume() {
  if (appQuitting) return;
  // 先向渲染层广播「系统刚唤醒」（power:resume），供页面立即补刷数据；
  // 与后端进程是否在跑无关，故放在 pythonProc 判断之前。
  if (mainWindow && !mainWindow.isDestroyed()) {
    try { mainWindow.webContents.send('power:resume'); } catch { /* ignore */ }
  }
  // 唤醒时后端本就不在跟踪（未启动 / 之前已失败）：不擅自拉起，保留用户手动启动入口。
  if (!pythonProc) return;
  // 先重新侦测就绪：token 已存在会立即推送，修复「睡眠跨过启动窗口 → 渲染端停在 failed」。
  armReadiness();
  // 再探活 HTTP；无响应说明后端实际已死（睡眠期间被系统回收等），按崩溃路径处理：
  // kill 僵尸引用触发其 'exit' → 走限频自动重启。手动停止/重启进行中（killPending）时不介入。
  const alive = await pingBackend();
  if (alive || appQuitting || killPending || !pythonProc) return;
  console.warn('[aas-electron] 唤醒后后端无响应，按崩溃路径重启');
  killPython();
}

// ============================================================================
// 窗口状态持久化（尺寸 / 位置 / 最大化）
//  - loadWindowState: 读 JSON，失败/不存在返回 null
//  - saveWindowState: 写 JSON，失败静默
//  - isVisibleOnSomeDisplay: 越界校验，bounds 与任一显示器 workArea 有可见交集才采用
// ============================================================================
function loadWindowState() {
  try {
    const raw = fs.readFileSync(WINDOW_STATE_PATH, 'utf-8');
    const state = JSON.parse(raw);
    if (state && typeof state === 'object') return state;
    return null;
  } catch {
    return null;
  }
}

function saveWindowState(state) {
  try {
    fs.writeFileSync(WINDOW_STATE_PATH, JSON.stringify(state), 'utf-8');
  } catch {
    /* ignore */
  }
}

// ============================================================================
// GUI 设置持久化（gui-settings.json）
//  打包应用以 file:// 加载，渲染进程 localStorage 跨重启不可靠；
//  天气收藏地点等需要记忆的数据统一落到该文件，
//  经 AAS_SETTINGS（preload）get/set。写盘防抖 300ms，退出前强制 flush。
// ============================================================================
const GUI_SETTINGS_PATH = path.join(DATA_DIR, 'gui-settings.json');
let guiSettings = null;       // 惰性加载缓存（主进程内存为权威）
let guiSettingsTimer = null;  // 防抖写盘定时器

function getGuiSettings() {
  if (guiSettings == null) {
    let raw = null;
    try {
      raw = fs.readFileSync(GUI_SETTINGS_PATH, 'utf-8');
    } catch (e) {
      // 文件不存在（ENOENT，首次启动）属正常，静默；其他读失败（如被杀毒软件临时锁住）留条日志便于排查
      if (!e || e.code !== 'ENOENT') {
        console.warn('[aas-electron] gui-settings.json 读取失败:', e && e.message);
      }
    }
    if (raw == null) {
      guiSettings = {};
    } else {
      try {
        const o = JSON.parse(raw);
        guiSettings = o && typeof o === 'object' ? o : {};
      } catch {
        // 内容损坏：直接回退空对象会在下次写盘时把损坏文件覆盖掉，备忘录等用户数据将永久丢失。
        // 先把损坏文件改名留档为 .bak（覆盖旧 .bak），至少可人工恢复，再按空设置起步。
        try {
          fs.renameSync(GUI_SETTINGS_PATH, GUI_SETTINGS_PATH + '.bak');
          console.warn('[aas-electron] gui-settings.json 内容损坏，已留档为 gui-settings.json.bak');
        } catch (e2) {
          console.warn('[aas-electron] gui-settings.json 损坏留档失败:', e2 && e2.message);
        }
        guiSettings = {};
      }
    }
  }
  return guiSettings;
}

function flushGuiSettings() {
  if (guiSettingsTimer) { clearTimeout(guiSettingsTimer); guiSettingsTimer = null; }
  if (guiSettings == null) return;
  try {
    // 原子写：先写同目录临时文件再 rename 覆盖（同分区 rename 是原子替换），
    // 避免写盘瞬间崩溃/断电留下半截 JSON 毁掉备忘录等用户数据
    const tmp = GUI_SETTINGS_PATH + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(guiSettings, null, 2), 'utf-8');
    fs.renameSync(tmp, GUI_SETTINGS_PATH);
  } catch { /* ignore */ }
}

ipcMain.handle('settings:get-all', () => getGuiSettings());
ipcMain.on('settings:set', (_event, key, value) => {
  if (typeof key !== 'string' || !key) return;
  const s = getGuiSettings();
  if (value === undefined || value === null) delete s[key];
  else s[key] = value;
  if (guiSettingsTimer) clearTimeout(guiSettingsTimer);
  guiSettingsTimer = setTimeout(flushGuiSettings, 300);
});

function isVisibleOnSomeDisplay(bounds) {
  if (
    !bounds ||
    typeof bounds.x !== 'number' || typeof bounds.y !== 'number' ||
    typeof bounds.width !== 'number' || typeof bounds.height !== 'number'
  ) {
    return false;
  }
  return screen.getAllDisplays().some(d => {
    const wa = d.workArea;
    // 矩形相交（任意可见交集即可，防窗口落到已拔掉的副屏外）
    return (
      bounds.x < wa.x + wa.width &&
      bounds.x + bounds.width > wa.x &&
      bounds.y < wa.y + wa.height &&
      bounds.y + bounds.height > wa.y
    );
  });
}

// ============================================================================
// 创建主窗口（不再等 token —— 立刻显示，token 经 IPC 后到）
// ============================================================================
async function createWindow() {
  const savedState = loadWindowState();
  // 默认 1480x920：不设 x/y 让其居中；有可见的历史 bounds 才复用尺寸+位置
  const winOpts = {
    width: 1480,
    height: 920,
    minWidth: 1100,
    minHeight: 700,
    title: 'AAS',
    backgroundColor: '#2a2926',
    // 自绘标题栏：Windows 整条 chrome 自绘（Win11 风格）；macOS 保留系统红绿灯
    // （hiddenInset 隐藏系统标题栏但留红绿灯），自绘的三个窗口键由渲染层按平台隐藏
    ...(process.platform === 'darwin'
      ? { titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 12, y: 12 } }
      : { frame: false, titleBarStyle: 'hidden' }),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // 缩托盘/最小化/被遮挡后仍要保持定时刷新与 WS 推送处理，故关闭隐藏窗口的定时器节流
      backgroundThrottling: false,
      // token 不再随窗口创建注入（窗口先于后端就绪），仅保留 http/ws 默认值；
      // token 由 backend:status('token') 异步推送
      additionalArguments: [
        `--aas-http=http://127.0.0.1:${HTTP_PORT}`,
        `--aas-ws=ws://127.0.0.1:${WS_PORT}`,
      ],
    },
  };

  if (savedState && isVisibleOnSomeDisplay(savedState)) {
    winOpts.width = savedState.width;
    winOpts.height = savedState.height;
    winOpts.x = savedState.x;
    winOpts.y = savedState.y;
  }

  const win = new BrowserWindow(winOpts);

  mainWindow = win;

  win.once('ready-to-show', () => {
    win.show();
    // 上次为最大化：show 后再 maximize（保留还原后的普通 bounds）
    if (savedState && savedState.isMaximized) win.maximize();
  });

  // resize / move 防抖落盘：仅在非最大化时记录普通 bounds（最大化的 bounds 不入库，便于还原）
  let saveTimer = null;
  const scheduleSave = () => {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      saveTimer = null;
      if (win.isDestroyed()) return;
      if (win.isMaximized()) return;
      const b = win.getBounds();
      saveWindowState({ width: b.width, height: b.height, x: b.x, y: b.y, isMaximized: false });
    }, 300);
  };
  win.on('resize', scheduleSave);
  win.on('move', scheduleSave);

  // 最大化：记录 isMaximized=true，但普通 bounds 沿用上次保存的非最大化值（避免把最大化尺寸当成还原尺寸）
  win.on('maximize', () => {
    const prev = loadWindowState();
    const b = win.getBounds();
    saveWindowState({
      width: prev && typeof prev.width === 'number' ? prev.width : b.width,
      height: prev && typeof prev.height === 'number' ? prev.height : b.height,
      x: prev && typeof prev.x === 'number' ? prev.x : b.x,
      y: prev && typeof prev.y === 'number' ? prev.y : b.y,
      isMaximized: true,
    });
  });
  // 还原：此时 getBounds 即普通 bounds，记录 isMaximized=false
  win.on('unmaximize', () => {
    const b = win.getBounds();
    saveWindowState({ width: b.width, height: b.height, x: b.x, y: b.y, isMaximized: false });
  });

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
      // 缩托盘：关窗只是隐藏，进程与后端继续运行；真正退出走托盘菜单。
      e.preventDefault();
      win.hide();
      return;
    }
  });

  // 外链用系统浏览器打开，不在 Electron 内部跳转。
  // 协议白名单：页面上可能渲染来自外部数据源的链接，url 可能是 file:///、UNC 路径
  // 或已注册的自定义协议（ms-msdt: 类）——一旦 openExternal 这类 url 即在本机触发程序执行。
  // 故仅放行 http/https，其余一律丢弃（不打开、不报错）。
  win.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const u = new URL(url);
      if (u.protocol === 'https:' || u.protocol === 'http:') shell.openExternal(url);
    } catch { /* 非法 url 直接忽略 */ }
    return { action: 'deny' };
  });

  // 阻止渲染进程整页跳转到外部站点：preload 暴露的 AAS_SERVICE/AAS_FILES（含读任意 yaml 的 pickConfigFile）
  // 等桥接 API 会随窗口可用，若渲染进程被诱导导航到远程页面，这些能力将暴露给该远程页面。
  // 只允许停留在本应用页面（dev=Vite dev server，prod=本地 dist 的 file://），其余一律拦截改用外部浏览器打开。
  win.webContents.on('will-navigate', (e, url) => {
    const allowed = IS_DEV ? url.startsWith(DEV_SERVER_URL) : url.startsWith('file://');
    if (allowed) return;
    e.preventDefault();
    try {
      const u = new URL(url);
      if (u.protocol === 'https:' || u.protocol === 'http:') shell.openExternal(url);
    } catch { /* 非法 url 直接忽略 */ }
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
  if (process.platform === 'darwin' && !image.isEmpty()) {
    // mac 菜单栏图标要用 template 模式（按透明形状渲染，系统自动适配深浅色菜单栏）。
    // 彩色图会退化成剪影，能用；正式发布前建议补一张黑白 tray-iconTemplate.png
    image = image.resize({ width: 16, height: 16 });
    image.setTemplateImage(true);
  }
  tray = new Tray(image);
  tray.setToolTip('AAS');
  const menu = Menu.buildFromTemplate([
    { label: '显示主窗口', click: () => { if (mainWindow) { mainWindow.show(); mainWindow.focus(); } } },
    { type: 'separator' },
    { label: '打开日志目录', click: () => shell.openPath(path.join(DATA_DIR, 'logs')) },
    { type: 'separator' },
    { label: '退出（停止后端 + GUI）', click: () => { appQuitting = true; app.quit(); } },
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

// ============================================================================
// 微信 Bark 转发 IPC（页面上的三个系统级操作；监听仅 macOS 生效，故都带平台守卫）
// ============================================================================
// 后端 spawn 时 cwd=DATA_DIR，配置文件按相对路径写出，就落在数据根下
const WECHAT_BARK_CONFIG_PATH = path.join(DATA_DIR, 'wechat_bark_config.json');

ipcMain.handle('wechat-bark:open-privacy', () => {
  // 打开 macOS「完全磁盘访问」设置页（监听要读通知中心数据库需要该权限）；其它系统没有这个设置页
  if (process.platform !== 'darwin') return { ok: false, reason: '仅 macOS 支持' };
  void shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles');
  return { ok: true };
});

ipcMain.handle('wechat-bark:show-config', async () => {
  // 在文件管理器中定位配置文件；还没保存过（文件不存在）时降级为直接打开数据目录
  if (fs.existsSync(WECHAT_BARK_CONFIG_PATH)) {
    shell.showItemInFolder(WECHAT_BARK_CONFIG_PATH);
    return { ok: true };
  }
  const err = await shell.openPath(DATA_DIR); // 空串=成功，非空=错误信息
  return err ? { ok: false, reason: err } : { ok: true };
});

ipcMain.handle('wechat-bark:sync-login-item', (_event, enabled) => {
  // 登录自启只在 macOS 打包版有意义（dev 下注册的是 electron.exe，纯属捣乱），其余环境 no-op
  if (process.platform !== 'darwin' || !app.isPackaged) return { ok: true, skipped: true };
  app.setLoginItemSettings({ openAtLogin: !!enabled, openAsHidden: true });
  return { ok: true };
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
  // 上一次 kill 尚未收到 exit：拒绝并发，避免旧进程未真正退出就被当作已停止而再 spawn 出双进程。
  if (killPending) return { success: false, message: '正在停止上一个进程，请稍候再试' };
  if (pythonProc) return { success: true, message: '已在运行' };
  manualStop = false;
  restarting = false;
  // 手动启动优先：取消任何挂起的（崩溃/重启）定时器，统一由本次 spawn 接管，杜绝定时器到点后再 spawn。
  clearPendingRestart();
  spawnPython(); // 成功会在 spawnPython 末尾推 service:status running=true
  return { success: true };
});

ipcMain.handle('service:stop', () => {
  if (killPending) return { success: false, message: '正在处理上一个请求，请稍候再试' };
  // 主动停止：先取消挂起的自动重启定时器，否则停止后定时器到点仍会把后端重新拉起。
  clearPendingRestart();
  if (!pythonProc) { pushServiceStatus(false); return { success: true, message: '未在运行' }; }
  manualStop = true; // 标记为主动停止：exit handler 不会自动重启
  killPending = true; // 等待该进程 exit 期间拒绝并发的 service:* 请求
  killPython();
  return { success: true };
});

ipcMain.handle('service:restart', () => {
  if (killPending) return { success: false, message: '正在处理上一个请求，请稍候再试' };
  // 取消挂起的崩溃/重启定时器，由本次重启流程统一接管，避免旧定时器额外 spawn。
  clearPendingRestart();
  // 此分支等价于一次直接启动：除 manualStop 外也复位 restarting，避免上一轮残留的 restarting
  // 被本次 spawn 出的新进程继承——否则新进程将来崩溃会误入 exit 的 restarting 分支绕过限频。
  if (!pythonProc) { manualStop = false; restarting = false; spawnPython(); return { success: true }; }
  restarting = true; // 标记为主动重启：exit handler 退出后会再 spawn（这里不二次 spawn，避免双进程竞态）
  killPending = true; // 等待该进程 exit 期间拒绝并发的 service:* 请求
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
  for (const name of ['.env', 'dynamic_config.json']) {
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
// 单实例锁（修复 M28）
//  托盘化设计下关窗只是 hide 到托盘（见 win.on('close')），用户极易误以为已退出而再次
//  双击快捷方式 → 第二个 Electron 实例正常启动并再 spawn 一个 python main.py --gui：
//  两个后端抢 8765/8766 端口、第二实例 unlink 掉第一实例正在用的 .gui_token。
//  这里抢单实例锁：抢不到说明已有实例在运行，本进程直接退出；已有实例收到
//  second-instance 事件时把窗口显示并聚焦，等价于「二次启动只唤起已有窗口」。
// ============================================================================
const gotInstanceLock = app.requestSingleInstanceLock();
if (!gotInstanceLock) {
  // 抢锁失败：已有实例在运行，本进程立即退出（不创建窗口、不 spawn 后端）
  app.exit(0);
} else {
  app.on('second-instance', () => {
    // 二次启动被本（首个）实例接管：把主窗口从托盘唤起并聚焦
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  // macOS：点 Dock 图标 / Finder 再次打开会触发 activate（而不是 second-instance），
  // 没有这个监听的话，隐藏到菜单栏后的窗口就唤不回来了
  app.on('activate', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
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
        'watchdog 会自动启动一个 main.py，与 GUI 模式启动的 Python 进程冲突（端口占用、共享文件竞争）。\n\n' +
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
  // 监听系统唤醒：睡眠跨过启动/探活窗口后，唤醒重新侦测就绪 + 探活后端（详见 handleResume）。
  // powerMonitor 须在 app ready 后注册。
  powerMonitor.on('resume', () => { void handleResume(); });
});

app.on('window-all-closed', () => {
  // 关窗已被拦截为"隐藏到托盘"，此事件正常不会触发；
  // 所有平台都不在这里退出，退出统一走托盘菜单的显式退出
});

app.on('before-quit', () => {
  appQuitting = true;
  clearPendingRestart(); // 退出前取消挂起的重启定时器，防止其到点后又把后端拉起
  flushGuiSettings();
  killPython();
});
