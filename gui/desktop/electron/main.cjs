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
const { fileURLToPath } = require('node:url');
const { spawn, execFileSync } = require('node:child_process');
const updater = require('./updater.cjs'); // 代码 OTA：查 manifest/下载校验/落地 versions+current 指针
const SHELL_PACKAGE = require('../package.json');
// 启动加载复验与联网更新必须使用同一可信仓库。正式包固定默认仓库；仅 dev/测试允许 env 覆盖。
const UPDATE_REPO = (!app.isPackaged && process.env.AAS_UPDATE_REPO) || updater.DEFAULT_REPO;

// ============================================================================
// 代码目录解析（瘦壳 + 代码 OTA 的地基）
//  壳子（Electron 运行时 + main.cjs/preload + 内置 bin）固定不变，后端 .py 与前端 dist
//  作为可更新的「代码包」独立存在。本函数决定本次启动到底跑哪一份代码，优先级：
//    1) 环境变量 AAS_CODE_DIR：显式指向一个含 backend/ 与 dist/ 的目录（dev/测试/手动覆盖）
//    2) <userData>/aas-code/versions/<current 指针>：OTA 更新落地的版本目录（阶段2写入）
//    3) 内置基线：打包=resources/backend + resources/app/dist；dev=仓库源码 + gui/desktop/dist
//  返回 { backendDir, frontendDir, version, source }。backend 与 frontend 分开定位：
//  内置态二者父目录不同（resources/backend vs resources/app/dist），外部代码包则同根。
//  任一外部来源结构校验失败 → 回退下一优先级，保证「更新坏了也能用内置版起来」。
// ============================================================================
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..'); // dev: 仓库根 C:\auto_attendance_system
// userData 仅在此取一次并经 CODE_HOME/CODE_VERSIONS_DIR/CODE_CURRENT_PTR 全程复用。
// 阶段2 实现 OTA 写入时必须复用这三个常量、禁止再次 app.getPath('userData')——否则 package.json 的
// name(auto-attendance-desktop) 与 electron-builder 的 productName(AutoAttendance) 差异会让读/写目录
// 错位（壳子读 A 目录、OTA 写 B 目录），永远读不到更新。
const CODE_HOME = path.join(app.getPath('userData'), 'aas-code');
const CODE_VERSIONS_DIR = path.join(CODE_HOME, 'versions');
const CODE_CURRENT_PTR = path.join(CODE_HOME, 'current');

// 读取代码包元数据，失败返回 null。正式 OTA 会额外核对版本与当前壳支持的依赖指纹。
function readBundleMetadata(dir) {
  try {
    const o = JSON.parse(fs.readFileSync(path.join(dir, 'bundle.json'), 'utf-8'));
    return o && typeof o === 'object' && !Array.isArray(o) ? o : null;
  } catch { return null; }
}

function readBundleVersion(dir) {
  const meta = readBundleMetadata(dir);
  return (meta && typeof meta.version === 'string' && meta.version) || null;
}

function otaBundleCompatibilityError(dir, expectedVersion) {
  try {
    updater.verifyInstalledBundle({
      dir,
      expectedVersion,
      repo: UPDATE_REPO,
      shellVersion: app.getVersion(),
    });
  } catch (e) {
    return e && e.message ? e.message : 'bundle.json 兼容性字段非法';
  }
  return null;
}

// 校验一个「代码包目录」结构是否完整：必须同时有 backend/main.py 与 dist/index.html，
// 缺任一即视为损坏/未就绪，触发回退到下一优先级（绝不加载半截代码导致白屏或起不来）。
function isValidBundleDir(dir) {
  try {
    return !!dir
      && fs.existsSync(path.join(dir, 'backend', 'main.py'))
      && fs.existsSync(path.join(dir, 'dist', 'index.html'));
  } catch { return false; }
}

// 内置基线（优先级3）：打包态 = 安装包内 resources/backend + resources/app/dist；
// dev = 仓库源码 + gui/desktop/dist。永远存在，作为首装/离线/更新损坏时的兜底。
function builtinCodeDir() {
  if (app.isPackaged) {
    const backendDir = path.join(process.resourcesPath, 'backend');
    return {
      backendDir,
      frontendDir: path.join(process.resourcesPath, 'app', 'dist'),
      version: readBundleVersion(backendDir) || SHELL_PACKAGE.aasCodeVersion || app.getVersion(),
      source: 'builtin',
    };
  }
  return {
    backendDir: REPO_ROOT,
    frontendDir: path.join(REPO_ROOT, 'gui', 'desktop', 'dist'),
    version: readBundleVersion(REPO_ROOT) || SHELL_PACKAGE.aasCodeVersion || 'dev',
    source: 'dev',
  };
}

// 版本目录名白名单：只允许纯数字三段版本（如 2.1.0）的单段名。
// 这样 ../、绝对路径、路径分隔符一律被拒，杜绝 current 指针（将来由阶段2 OTA 写入，或被外部篡改）
// 经 path.join 穿越出 versions/ 目录、诱导壳子加载并 spawn 任意目录下的 main.py。
function isSafeVersionName(ver) {
  return /^\d+\.\d+\.\d+$/.test(ver);
}

function resolveCodeDir() {
  // 1) 显式覆盖（AAS_CODE_DIR 指向含 backend/ 与 dist/ 的代码包根）。
  //    仅 dev/测试承认：打包态(app.isPackaged)一律忽略——正式安装包不给「环境变量指向任意本机代码」留
  //    注入口（可信外壳不应被用户级环境变量诱导加载/spawn 任意代码）。打包态的代码更新只走优先级2 的
  //    OTA 版本目录（受 versions/ 容器 + isSafeVersionName 约束，及阶段2 的下发校验）。
  //    相对路径先 path.resolve 归一，避免相对主进程 cwd（托盘/快捷方式启动时不固定）解析出不可预期目录。
  if (!app.isPackaged && process.env.AAS_CODE_DIR) {
    const envDir = path.resolve(process.env.AAS_CODE_DIR);
    if (isValidBundleDir(envDir)) {
      return {
        backendDir: path.join(envDir, 'backend'),
        frontendDir: path.join(envDir, 'dist'),
        version: readBundleVersion(envDir) || 'env',
        source: 'env',
      };
    }
    console.warn('[aas-electron] AAS_CODE_DIR 结构无效（缺 backend/main.py 或 dist/index.html），忽略：', envDir);
  }
  // 2) OTA 版本目录（current 指针指向 versions/<version>）。dev 默认忽略，避免本机安装版遗留的
  // current 让开发启动悄悄运行旧 OTA 代码；需要联调时显式 AAS_USE_OTA=1。
  if (app.isPackaged || process.env.AAS_USE_OTA === '1') {
    try {
      if (fs.existsSync(CODE_CURRENT_PTR)) {
        const ver = fs.readFileSync(CODE_CURRENT_PTR, 'utf-8').trim();
        if (ver && isSafeVersionName(ver)) {
          const builtinVersion = SHELL_PACKAGE.aasCodeVersion;
          if (isSafeVersionName(builtinVersion) && updater.compareVersions(ver, builtinVersion) <= 0) {
            console.info(`[aas-electron] 内置代码 ${builtinVersion} 不低于磁盘 OTA ${ver}，优先使用新版内置代码`);
            return builtinCodeDir();
          }
          const dir = path.join(CODE_VERSIONS_DIR, ver);
          if (isValidBundleDir(dir)) {
            const compatibilityError = otaBundleCompatibilityError(dir, ver);
            if (!compatibilityError) {
              return {
                backendDir: path.join(dir, 'backend'),
                frontendDir: path.join(dir, 'dist'),
                version: ver,
                source: 'ota',
              };
            }
            console.warn(`[aas-electron] current 指向的 OTA 版本不兼容（${compatibilityError}），回退内置：`, dir);
          } else {
            console.warn('[aas-electron] current 指向的版本目录无效，回退内置：', dir);
          }
        } else if (ver) {
          console.warn('[aas-electron] current 指针含非法版本名，回退内置：', ver);
        }
      }
    } catch (e) {
      console.warn('[aas-electron] 读取 current 指针失败，回退内置：', e.message);
    }
  }
  // 3) 内置基线
  return builtinCodeDir();
}

const CODE = resolveCodeDir();
// 后端代码根（含 main.py / modules / templates）。原 PROJECT_ROOT 语义不变，仅来源可被 OTA 覆盖。
const PROJECT_ROOT = CODE.backendDir;
// 前端编译产物目录（含 index.html / assets）。prod 用 file:// 从此加载（vite base:'./' 故相对路径可解析）。
const FRONTEND_DIR = CODE.frontendDir;
const CODE_VERSION = CODE.version;
// 壳子固定 bin（mihomo 二进制 + geo）：体积大且极少变，不随代码包更新而下发。
// 经 AAS_BIN_DIR 注入给后端，使迁到外部目录的后端仍能找到它（详见 spawnPython 的 env）。
//  - 打包：resources/backend/bin（extraResources 随壳子发一次，永远存在）
//  - dev ：仓库根 bin（由 scripts/fetch-mihomo.ps1 准备）
const STABLE_BIN_DIR = app.isPackaged
  ? path.join(process.resourcesPath, 'backend', 'bin')
  : path.join(REPO_ROOT, 'bin');
// Edge 驱动同样属于壳子稳定资源，不进入 OTA 代码包。后端不能再按自身 __file__（OTA 版本目录）寻找。
const STABLE_EDGE_DRIVER_PATH = app.isPackaged
  ? path.join(process.resourcesPath, 'backend', 'msedgedriver.exe')
  : path.join(REPO_ROOT, 'msedgedriver.exe');
console.info(`[aas-electron] code source=${CODE.source} version=${CODE_VERSION} backend=${PROJECT_ROOT}`);
// 后端 Python 解释器：可由 AAS_PYTHON 指定，否则按平台取 python/python3。
const PY_CMD = process.env.AAS_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
// 最近一次成功启动的 OTA 版本（供失败回滚）。
const CODE_LASTGOOD_PTR = path.join(CODE_HOME, 'last-good');
const CODE_BLACKLIST_PATH = path.join(CODE_HOME, 'blacklist'); // 启动失败被回滚过的版本，不再自动重装
// 后端可写数据根：dev=仓库根 REPO_ROOT；打包=用户指定的现有数据目录（含真实记录/截图/配置）。
// 数据根锚定「壳子/机器」而非「代码包」：dev 用固定 REPO_ROOT（不随 AAS_CODE_DIR/OTA 漂移），
// 否则切换代码包会把 punch_records/screenshots/logs/.gui_token 等写到代码包目录、读不到真实数据。
// 可用环境变量 AAS_DATA_DIR 覆盖，便于将来切到 %APPDATA% 等。
const LEGACY_DATA_DIR = 'C:\\auto_attendance_system';
const DATA_DIR = process.env.AAS_DATA_DIR
  || (app.isPackaged ? LEGACY_DATA_DIR : REPO_ROOT);
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
let bluetoothRequest = null;
let pairingRequest = null;

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

// ============================================================================
// OTA 版本健康门 / 回滚（阶段3）
//  - 新 staged 的 OTA 版本首次启动若「拿不到 token / 反复崩溃」，自动回退到上一个已知良好版本并重启；
//    无良好版本可退则清除 current 指针 → 下次启动回退内置基线（离线兜底由 resolveCodeDir 保证）。
//  - 后端 token + 前端真实 API 探活同时成功并稳定运行 90 秒，才记为 last-good。
//  - rolledBack 一次性：回滚后重启加载的就是 good/内置，CODE_VERSION 不再等于失败版本，不会再触发，杜绝死循环。
// ============================================================================
function readLastGood() {
  try { return fs.readFileSync(CODE_LASTGOOD_PTR, 'utf-8').trim() || null; } catch { return null; }
}
function readBlacklist() {
  try { return fs.readFileSync(CODE_BLACKLIST_PATH, 'utf-8').split('\n').map((s) => s.trim()).filter(Boolean); } catch { return []; }
}
function addToBlacklist(ver) {
  if (!ver) return;
  try {
    if (!readBlacklist().includes(ver)) { fs.mkdirSync(CODE_HOME, { recursive: true }); fs.appendFileSync(CODE_BLACKLIST_PATH, ver + '\n', 'utf-8'); }
  } catch { /* ignore */ }
}
function writeCurrentPointer(ver) {
  fs.mkdirSync(path.dirname(CODE_CURRENT_PTR), { recursive: true });
  const tmp = `${CODE_CURRENT_PTR}.tmp`;
  fs.writeFileSync(tmp, ver, 'utf-8');
  fs.renameSync(tmp, CODE_CURRENT_PTR);
}
let goodTimer = null; // 「稳定运行」确认计时器：后端+渲染端均健康后延时仍未崩才记 good
let rendererReadyTimer = null; // 后端已就绪后等待当前渲染代际完成真实 API 探活
let backendReadyGen = 0;
let rendererReady = false;
function clearGoodTimer() { if (goodTimer) { clearTimeout(goodTimer); goodTimer = null; } }
function clearRendererReadyTimer() {
  if (rendererReadyTimer) { clearTimeout(rendererReadyTimer); rendererReadyTimer = null; }
}
function cleanupOldCodeVersions() {
  // 清理的硬门禁：当前实际运行版本必须已经写成 last-good；否则它仍处于待验证阶段，绝不回收任何正式版本。
  if (appQuitting || readLastGood() !== CODE_VERSION) return;
  if (CODE.source !== 'ota' || otaBundleCompatibilityError(path.join(CODE_VERSIONS_DIR, CODE_VERSION), CODE_VERSION)) return;
  updater.cleanupOldVersions({
    versionsDir: CODE_VERSIONS_DIR,
    currentPtr: CODE_CURRENT_PTR,
    lastGoodPtr: CODE_LASTGOOD_PTR,
    runningVersion: CODE_VERSION,
    log: (line) => { console.info(line); pushLogLines([line]); },
  });
}
function markCurrentGood() {
  if (!app.isPackaged) return;                        // dev 不参与 OTA 健康门
  if (CODE.source !== 'ota' || !CODE_VERSION) return; // 只记 OTA 版本；内置/dev 本就是兜底
  const integrityError = otaBundleCompatibilityError(path.join(CODE_VERSIONS_DIR, CODE_VERSION), CODE_VERSION);
  if (integrityError) {
    // 90 秒稳定窗口内若代码目录发生损坏/意外写入，绝不能先污染 last-good；按确定性坏版本回滚并拉黑。
    maybeRollback(`代码包完整性复验失败: ${integrityError}`, { blacklist: true });
    return;
  }
  if (readLastGood() !== CODE_VERSION) {
    try {
      fs.mkdirSync(CODE_HOME, { recursive: true });
      const tmp = `${CODE_LASTGOOD_PTR}.tmp`;
      fs.writeFileSync(tmp, CODE_VERSION, 'utf-8');
      fs.renameSync(tmp, CODE_LASTGOOD_PTR);
    } catch { return; }
  }
  // 指针已原子落盘且回读确认后才清理；cleanupOldVersions 还会额外保护 current、last-good 与运行中版本。
  cleanupOldCodeVersions();
}
// 后端拿到 token 且 React 完成真实 API 探活后才启动稳定计时；任一端失败/重载都会取消。
const STABLE_RUN_MS = 90_000;
const RENDERER_READY_TIMEOUT_MS = 60_000;
function maybeScheduleMarkGood(gen) {
  if (!app.isPackaged || CODE.source !== 'ota') return;
  if (readLastGood() === CODE_VERSION) { cleanupOldCodeVersions(); return; }
  if (gen !== readyGen || backendReadyGen !== gen || !rendererReady || appQuitting) return;
  if (goodTimer) return;
  clearRendererReadyTimer();
  clearGoodTimer();
  goodTimer = setTimeout(() => {
    goodTimer = null;
    if (gen === readyGen && backendReadyGen === gen && rendererReady && !appQuitting) markCurrentGood();
  }, STABLE_RUN_MS);
}
function scheduleRendererReadyDeadline(gen) {
  clearRendererReadyTimer();
  if (!app.isPackaged || CODE.source !== 'ota' || readLastGood() === CODE_VERSION || rendererReady) return;
  if (gen <= 0 || backendReadyGen !== gen) return; // 后端 token 尚未就绪时不开始计算前端探活时限
  rendererReadyTimer = setTimeout(() => {
    rendererReadyTimer = null;
    if (gen === readyGen && backendReadyGen === gen && !rendererReady && !appQuitting) {
      // 页面能加载但应用级探活始终不成功：回退当前版本；不拉黑，给网络/机器偶发慢启动留重试机会。
      maybeRollback('前端健康探测超时', { blacklist: false });
    }
  }, RENDERER_READY_TIMEOUT_MS);
}
let rolledBack = false;
// reason=失败原因；opts.blacklist=是否拉黑当前版本（崩溃=确定性坏→拉黑；超时=可能只是慢→不拉黑，留待重试）。
function maybeRollback(reason, opts) {
  const blacklist = !opts || opts.blacklist !== false;
  if (rolledBack || appQuitting) return false;
  if (!app.isPackaged) return false;       // 回滚只在打包态生效（dev 即便残留 current 指针也不 relaunch/quit）
  if (CODE.source !== 'ota') return false; // 只回滚 OTA 加载的版本；内置/dev 失败属真实问题，不回滚
  if (readLastGood() === CODE_VERSION) return false; // 已证明稳定的版本不因后来偶发系统/驱动故障被误回滚
  clearGoodTimer();                        // 失败了，撤销「稳定运行」确认
  clearRendererReadyTimer();               // 回滚流程已开始，不再保留前端健康截止计时
  const good = readLastGood();
  // 可用的回退目标：存在、非当前失败版本、结构完整，且仍兼容当前壳/依赖指纹。
  // 新壳升级过依赖后，旧 last-good 可能已不兼容；此时直接回退内置，避免写入一个下次启动仍会拒绝的指针。
  const goodDir = good && isSafeVersionName(good) ? path.join(CODE_VERSIONS_DIR, good) : '';
  const goodUsable = goodDir && good !== CODE_VERSION
    && isValidBundleDir(goodDir) && !otaBundleCompatibilityError(goodDir, good);
  let msg;
  if (goodUsable) {
    try { writeCurrentPointer(good); } catch { return false; } // 写指针失败：本次不回滚，保持可重试
    msg = `新版本 ${CODE_VERSION} 启动失败(${reason})，回滚到 ${good} 并重启`;
  } else {
    // 无 good / good 目录失效 / good 就是当前失败版本 → 清 current 指针，下次启动经 resolveCodeDir 回退内置基线
    try { fs.rmSync(CODE_CURRENT_PTR, { force: true }); } catch { return false; }
    msg = `新版本 ${CODE_VERSION} 启动失败(${reason})，无可用回退版本，清除指针回退内置并重启`;
  }
  rolledBack = true;
  if (blacklist) addToBlacklist(CODE_VERSION); // 仅崩溃路径拉黑：自动更新不会再装回来；超时不拉黑以免误封健康慢启动版本
  console.warn('[aas-electron] ' + msg);
  pushLogLines([msg]);
  appQuitting = true;
  app.relaunch();
  app.quit();
  return true;
}

// 每次 spawn 后重新 arm：等 token → 推给渲染进程；超时/失败 → 推 failed
function armReadiness() {
  const gen = ++readyGen;
  backendReadyGen = 0;
  // 每一轮后端启动都必须由渲染端针对这一轮 token/API 重新探活，不能沿用上一轮的健康握手。
  rendererReady = false;
  clearGoodTimer();
  clearRendererReadyTimer();
  pushStatus({ state: 'starting', reason: null });
  // 未验证过的 OTA 新版本首启给更长超时（重依赖冷启动可能数分钟），常规启动仍用 120s，避免把慢启动误判为坏。
  const isUnprovenOta = app.isPackaged && CODE.source === 'ota' && readLastGood() !== CODE_VERSION;
  const tokenTimeout = isUnprovenOta ? 300_000 : 120_000;
  waitForToken(tokenTimeout)
    .then(token => {
      if (gen !== readyGen) return; // 已有更新的 spawn，丢弃过期 token
      console.info('[aas-electron] token ready, notifying renderer');
      backendReadyGen = gen;
      pushStatus({
        state: 'token',
        token,
        httpUrl: `http://127.0.0.1:${HTTP_PORT}`,
        wsUrl: `ws://127.0.0.1:${WS_PORT}`,
      });
      scheduleRendererReadyDeadline(gen);
      maybeScheduleMarkGood(gen);
    })
    .catch(err => {
      if (gen !== readyGen) return;
      console.error('[aas-electron] token wait failed:', err.message);
      pushStatus({ state: 'failed', reason: `后端启动超时：${err.message}（端口可能被占用，请查看日志）` });
      maybeRollback('启动超时', { blacklist: false }); // 超时可能只是慢：回滚但不拉黑，下次仍可重试该版本
    });
}

// ============================================================================
// 启动 Python 后端 + 崩溃重启
// ============================================================================
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
  // 启动前清掉过期 token 文件，避免读到老 token
  try { fs.unlinkSync(TOKEN_PATH); } catch { /* ignore */ }
  // 每轮启动从头展示日志：清空缓冲（崩溃重启时不残留上一轮 traceback）
  logBuffer = [];
  logCarry = '';

  const pyCmd = PY_CMD;
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
    // AAS_BIN_DIR：把 mihomo 所在 bin 指向壳子固定位置——后端代码经 OTA 迁到外部目录后，
    //   其 __file__ 推导的 code_root/bin 已不含 mihomo（bin 不进代码包），靠此环境变量回指壳子 bin。
    //   后端 proxy_manager._bin_dir / config._mihomo_binary_missing 读取该变量，未设时沿用原 code_root/bin。
    env: {
      ...process.env,
      AAS_PLAIN_CONSOLE: '1',
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
      // OTA 目录必须保持签名文件树不变；禁止 import 生成未签名 __pycache__/*.pyc，
      // 否则下一次启动的 treeSha256 复验会拒绝刚运行过的健康版本。
      PYTHONDONTWRITEBYTECODE: '1',
      AAS_DATA_DIR: DATA_DIR,
      AAS_BIN_DIR: STABLE_BIN_DIR,
      AAS_MSEDGEDRIVER_PATH: STABLE_EDGE_DRIVER_PATH,
    },
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
    clearGoodTimer(); // 后端退出（崩溃/重启/停止）：撤销「稳定运行」确认，不把当前版本误记为良好
    clearRendererReadyTimer(); // 后端代际已结束，前端对该代际的探活截止计时作废
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
      pushStatus({ state: 'failed', reason: `Python 后端反复崩溃（1 小时内 ${restartHistory.length} 次），已停止自动重启。请查看 logs/attendance_system.log 后手动重启。` });
      pushServiceStatus(false); // 彻底放弃自动重启：服务已停止
      maybeRollback('反复崩溃'); // 若崩的是新 OTA 版本，回滚到上个良好版本再重启
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
  // 先向渲染层广播「系统刚唤醒」（power:resume）：休眠中蓝牙链路必掉，墨水屏侧要靠这个
  // 信号立即校验连接/触发重连，与后端进程是否在跑无关，故放在 pythonProc 判断之前。
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
//  墨水屏连接历史 / 备忘录 / 自动推送 / 倒置渲染等需要记忆的数据统一落到该文件，
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

// ============================================================================
// 墨水屏日志持久化（logs/epaper.log）
//  渲染进程每条墨水屏日志经 epd:log-append 追加；发送图片时 ⇑/⇓ hex 可达上千条，
//  故主进程缓冲后防抖 250ms 合并写盘（而非每条同步写）；持续日志会一直重置防抖，
//  所以另设 max-wait：距队首入队超 2 秒直接落盘，保证长传输期间周期性写盘、内存有界。
//  单文件超上限按「保留尾部一半」滚动截断，无需外部依赖。退出前 before-quit 强制 flush。
// ============================================================================
const EPAPER_LOG_PATH = path.join(DATA_DIR, 'logs', 'epaper.log');
const EPAPER_LOG_MAX_BYTES = 1024 * 1024; // 1 MB；超出截掉前半，避免无限增长
const EPAPER_LOG_MAX_WAIT_MS = 2000;      // 防抖强制落盘上限：距队首入队超此时长直接 flush
let epaperLogDirReady = false;
let epaperLogQueue = [];     // 待写行缓冲
let epaperLogTimer = null;   // 防抖落盘定时器
let epaperLogFirstAt = 0;    // 队首那条日志的入队时刻（max-wait 判定基准）

function flushEpaperLog() {
  if (epaperLogTimer) { clearTimeout(epaperLogTimer); epaperLogTimer = null; }
  if (!epaperLogQueue.length) return;
  const chunk = epaperLogQueue.join('\n') + '\n';
  try {
    if (!epaperLogDirReady) {
      fs.mkdirSync(path.dirname(EPAPER_LOG_PATH), { recursive: true });
      epaperLogDirReady = true;
    }
    fs.appendFileSync(EPAPER_LOG_PATH, chunk, 'utf-8');
    // 写成功才清队列；若先清再写，写失败这批日志就被静默丢弃了
    epaperLogQueue = [];
    // 超过上限：仅保留尾部约一半，并从首个换行后切起避免留下半行
    const { size } = fs.statSync(EPAPER_LOG_PATH);
    if (size > EPAPER_LOG_MAX_BYTES) {
      const buf = fs.readFileSync(EPAPER_LOG_PATH);
      const tail = buf.subarray(buf.length - Math.floor(EPAPER_LOG_MAX_BYTES / 2));
      const nl = tail.indexOf(0x0a);
      fs.writeFileSync(EPAPER_LOG_PATH, nl >= 0 ? tail.subarray(nl + 1) : tail);
    }
  } catch {
    // 写盘失败（如 logs 目录被删/被占用）不影响主流程：日志留在队列等下次落盘重试。
    // 目录标记复位让下次重建目录；截断队列防持续失败时内存无限涨；
    // 刷新 firstAt 让连续日志期间的强制落盘至少隔 2 秒再试（稀疏日志仍走 250ms 防抖重试）。
    epaperLogDirReady = false;
    if (epaperLogQueue.length > 1000) epaperLogQueue.splice(0, epaperLogQueue.length - 1000);
    epaperLogFirstAt = Date.now();
  }
}

ipcMain.on('epd:log-append', (_event, line) => {
  if (typeof line !== 'string' || !line) return;
  if (!epaperLogQueue.length) epaperLogFirstAt = Date.now();
  epaperLogQueue.push(line);
  // 队首等太久（发图时日志间隔常小于 250ms，纯防抖会被一直重置）：不再重置定时器，直接落盘
  if (Date.now() - epaperLogFirstAt >= EPAPER_LOG_MAX_WAIT_MS) {
    flushEpaperLog();
    return;
  }
  if (epaperLogTimer) clearTimeout(epaperLogTimer);
  epaperLogTimer = setTimeout(flushEpaperLog, 250);
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
    // 自绘标题栏（设计稿本身是 Win 11 风格的 chrome）
    frame: false,
    titleBarStyle: 'hidden',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // 缩托盘/最小化/被遮挡后仍要后台定时推送与「一键重连」全速运行，故关闭隐藏窗口的定时器节流
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
  installBluetoothHandlers(win);

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
    try { win.webContents.send('update:status', lastUpdateStatus); } catch { /* ignore */ } // 补推 OTA 状态
    if (logBuffer.length) {
      try { win.webContents.send('backend:log', { lines: logBuffer.slice() }); } catch { /* ignore */ }
    }
  });

  // OTA 首次启动的健康判定不能只看 Python token：前端 bundle 语法错误/资源缺失会白屏，后端仍可能正常。
  // React 在完成后端真实探活后经 update:renderer-ready 握手；在此之前若主框架加载失败或渲染进程崩溃，
  // 立即按坏版本回滚。已记 last-good 的版本不参与自动回滚（maybeRollback 内有门禁）。
  win.webContents.on('did-fail-load', (_event, code, desc, _url, isMainFrame) => {
    if (!isMainFrame || code === -3) return; // ERR_ABORTED 常见于正常导航替换，不判坏
    rendererReady = false;
    clearGoodTimer();
    clearRendererReadyTimer();
    maybeRollback(`前端加载失败 ${code}: ${desc}`);
  });
  win.webContents.on('render-process-gone', (_event, details) => {
    rendererReady = false;
    clearGoodTimer();
    clearRendererReadyTimer();
    maybeRollback(`前端进程退出: ${details && details.reason ? details.reason : 'unknown'}`);
  });
  win.on('unresponsive', () => {
    rendererReady = false;
    clearGoodTimer();
    clearRendererReadyTimer();
    maybeRollback('前端无响应', { blacklist: false });
  });

  win.on('close', e => {
    if (!appQuitting) {
      // 缩托盘：保留挂起的 native 蓝牙请求，让后台「一键重连」/扫描在托盘里继续跑
      //（只有用户点「取消重连」才停）。真正退出/窗口销毁/重载才释放，见下方 closed /
      // did-start-navigation 与 before-quit。
      e.preventDefault();
      win.hide();
      return;
    }
    resolvePendingBleRequests(); // 真正退出：释放挂起的 native 蓝牙请求，避免扫描状态泄漏
  });
  // 窗口真正销毁时再兜底一次（直接退出/异常销毁路径）
  win.on('closed', resolvePendingBleRequests);
  // 重载（dev HMR / webContents.reload）：旧页面随导航销毁，其 pending requestDevice 的 callback
  // 不会被渲染层调用，须在主帧开始导航时兜底解析，释放扫描状态。
  win.webContents.on('did-start-navigation', (_e, _url, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) {
      rendererReady = false;
      clearGoodTimer();
      clearRendererReadyTimer();
      scheduleRendererReadyDeadline(readyGen); // 后端仍健康时，给新页面代际重新开启探活截止时间
      resolvePendingBleRequests();
    }
  });

  // 外链用系统浏览器打开，不在 Electron 内部跳转。
  // 协议白名单：AI 资讯专区把外部 RSS/接口返回的 item.url 直接渲染为 <a target="_blank">，
  // 数据源不受本机控制。若上游 feed 被投毒/中间人篡改，url 可能是 file:///、UNC 路径 \\evil\share\x.exe
  // 或已注册的自定义协议（ms-msdt: 类）——一旦 openExternal 这类 url，点击资讯条目即在本机触发程序执行。
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
    // dev：只放行 Vite dev server；prod：只放行「停留在 FRONTEND_DIR 目录内」的 file:// 页面。
    // 收紧理由：前端来源已可被 OTA/内置切换到不同（甚至用户可写的）目录，若仍放行任意 file://，
    // 被投毒/XSS 的页面可整页导航到本机任意 html，并继承 preload 的 AAS_SERVICE/AAS_FILES 等能力。
    // 故按来源目录前缀收口；fileURLToPath 跨平台正确处理盘符与百分号编码。
    let allowed = false;
    if (IS_DEV) {
      allowed = url.startsWith(DEV_SERVER_URL);
    } else {
      try {
        const u = new URL(url);
        if (u.protocol === 'file:') {
          const target = path.resolve(fileURLToPath(url));
          const base = path.resolve(FRONTEND_DIR);
          allowed = target === base || target.startsWith(base + path.sep);
        }
      } catch { /* 非法/非 file: url 不放行 */ }
    }
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
    // prod 从 FRONTEND_DIR 加载（内置=resources/app/dist；OTA=外部版本目录的 dist）。
    // 仍是 file:// 协议，will-navigate 白名单的 startsWith('file://') 照旧放行，无需改动。
    await win.loadFile(path.join(FRONTEND_DIR, 'index.html'));
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
  tray.setToolTip('AAS');
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

// 兜底解析挂起的原生蓝牙请求（修复 E17）：
//  Chromium 的 select-bluetooth-device / setBluetoothPairingHandler 在拿到 callback 后，
//  必须调用一次该 callback 原生请求才会结束；否则 native 蓝牙扫描状态泄漏（持续耗电/占用适配器），
//  且渲染层 store.scanning 卡在 true（下次 openScan 被 `if (scanning) return` 吞掉，再也打不开扫描）。
//  窗口关闭(缩托盘)/销毁/重载时，渲染页的 modal 可能未选/未取消就消失，须在此统一兜底：
//  设备选择回空串(=取消)、配对确认回 { confirmed:false }，确保挂起的 native 请求被解析、扫描状态释放。
function resolvePendingBleRequests() {
  if (bluetoothRequest) {
    const cb = bluetoothRequest.callback;
    bluetoothRequest = null;
    try { cb(''); } catch { /* 请求可能已失效，忽略 */ }
  }
  if (pairingRequest) {
    const cb = pairingRequest.callback;
    pairingRequest = null;
    try { cb({ confirmed: false }); } catch { /* 请求可能已失效，忽略 */ }
  }
}

// 设备列表去重 + 原样透传名称（空串=无名设备，由渲染端决定过滤/隐藏）
function mapBleDevices(deviceList) {
  const map = new Map();
  for (const device of deviceList || []) {
    if (!device || !device.deviceId) continue;
    map.set(device.deviceId, { deviceId: device.deviceId, deviceName: device.deviceName || '' });
  }
  return Array.from(map.values());
}

function installBluetoothHandlers(win) {
  // 拦截系统原生蓝牙选择器：把扫到的设备实时推给渲染进程，由页面自定义 modal 展示并回选。
  // 该事件会随新设备被发现而多次触发，每次携带累积的 deviceList 与一个新的 callback —— 始终保留最新的。
  win.webContents.on('select-bluetooth-device', (event, deviceList, callback) => {
    event.preventDefault();
    bluetoothRequest = { callback };
    if (!win.isDestroyed()) {
      win.webContents.send('epd:ble-devices', mapBleDevices(deviceList));
    }
  });

  // 蓝牙配对确认：不再弹系统 messageBox，推给渲染进程用应用内对话框确认后回传。
  win.webContents.session.setBluetoothPairingHandler((details, callback) => {
    if (details.pairingKind === 'confirmPin' || details.pairingKind === 'confirm') {
      pairingRequest = { callback };
      if (!win.isDestroyed()) {
        win.webContents.send('epd:ble-pairing', {
          kind: details.pairingKind,
          deviceId: details.deviceId || '蓝牙设备',
          pin: String(details.pin || ''),
        });
      }
      return;
    }
    callback({ confirmed: false });
  });
}

// 渲染端应用内对话框的配对确认结果
ipcMain.on('epd:ble-pairing-response', (_event, confirmed) => {
  if (!pairingRequest) return;
  const cb = pairingRequest.callback;
  pairingRequest = null;
  try { cb({ confirmed: !!confirmed }); } catch { /* 请求可能已失效，忽略 */ }
});

// 渲染端从自定义 modal 回选设备（空串=取消）。callback 只能调用一次，调用后请求即解析/取消。
ipcMain.on('epd:ble-select', (_event, deviceId) => {
  if (!bluetoothRequest) return;
  const cb = bluetoothRequest.callback;
  bluetoothRequest = null;
  try { cb(deviceId || ''); } catch { /* 请求可能已失效，忽略 */ }
});

// 方案2：定时推送(无用户手势)时，主进程向渲染层注入一次可信键盘输入(F24，isTrusted=true)，
// 使渲染层得以在 user activation 上下文中调用 navigator.bluetooth.requestDevice 自动重连。
// 选 F24(几乎无默认绑定/无人使用)避免误触；渲染层仅在"已武装"的短窗口内响应。
// 注：窗口缩托盘/隐藏时 sendInputEvent 可能无效，故渲染层有 2s 兜底降级为"提示手动"，
// 本调用只负责尽力注入、绝不抛错(失败 resolve false 即可)。
ipcMain.handle('epd:gesture-reconnect', () => {
  try {
    if (!mainWindow || mainWindow.isDestroyed()) return false;
    const wc = mainWindow.webContents;
    wc.sendInputEvent({ type: 'keyDown', keyCode: 'F24' });
    wc.sendInputEvent({ type: 'keyUp', keyCode: 'F24' });
    return true;
  } catch (e) {
    console.warn('[aas-electron] epd:gesture-reconnect 注入失败:', e && e.message);
    return false;
  }
});

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

// 当前运行的代码信息（瘦壳 + OTA）：codeVersion=本次加载的代码包版本；
// shellVersion=壳子(package.json)版本；source=代码来源（env/ota/builtin/dev）。供「关于」页展示。
ipcMain.handle('app:get-code-version', () => ({
  codeVersion: CODE_VERSION,
  shellVersion: app.getVersion(),
  source: CODE.source,
}));

// ============================================================================
// 代码 OTA 自更新（阶段2）：查 manifest → 下载校验 → 落地 versions/<ver> + 写 current 指针。
//  - 落地后「下次启动」由 resolveCodeDir 加载新代码（壳子不重打包）；可经 update:relaunch 立即重启生效。
//  - 仅打包态自动触发：dev 自动触发会把 OTA 代码 stage 进 userData，下次 dev 启动反而加载它而非仓库源码。
//  - 失败安全：网络/校验失败只记日志+推状态，绝不影响当前已加载版本的运行。
// ============================================================================
// 仅 dev/测试承认 env 覆盖仓库/镜像；打包态一律用 updater 硬编码可信源——与 AAS_CODE_DIR「打包态忽略」一致，
// 杜绝用户级环境变量把 OTA 改向攻击者仓库（借受信任安装包持久化执行任意代码）。
const UPDATE_MIRRORS = (!app.isPackaged && process.env.AAS_UPDATE_MIRRORS)
  ? process.env.AAS_UPDATE_MIRRORS.split(',').map((s) => s.trim())
  : updater.DEFAULT_MIRRORS;
let lastUpdateStatus = { status: 'idle' };
let updateInFlight = null; // 进行中的 Promise：去重 + 让并发 apply 都 await 到同一最终结果
let updateInFlightAllowsBlacklisted = false;
let updateInterval = null;
let updateStartupTimer = null;
const UPDATE_INTERVAL_MS = 6 * 60 * 60 * 1000;

function pushUpdateStatus(payload) {
  lastUpdateStatus = payload;
  if (mainWindow && !mainWindow.isDestroyed() && !appQuitting) {
    try { mainWindow.webContents.send('update:status', payload); } catch { /* ignore */ }
  }
}

// 检查并（若有新版）下载落地。updateInFlight 持有进行中的 Promise：并发调用（启动自动触发 + 用户手动 apply）
// 复用同一次执行、并都 await 到同一最终结果，避免并发跑两遍下载/解压到同一 versionsDir。
function triggerUpdate({ allowBlacklisted = false } = {}) {
  if (appQuitting) return Promise.resolve({ status: 'error', error: '应用正在退出' });
  if (updateInFlight) {
    // 用户点击“下载”撞上自动检查时，先复用网络请求；若自动流程只因黑名单跳过，再立即以手动权限重试。
    if (allowBlacklisted && !updateInFlightAllowsBlacklisted) {
      return updateInFlight.then((r) => r && r.skippedBad ? triggerUpdate({ allowBlacklisted: true }) : r);
    }
    return updateInFlight;
  }
  if (lastUpdateStatus.status === 'staged') return Promise.resolve(lastUpdateStatus);
  pushUpdateStatus({ status: 'checking' });
  const log = (line) => { console.info(line); pushLogLines([line]); };
  updateInFlightAllowsBlacklisted = allowBlacklisted;
  updateInFlight = (async () => {
    try {
      const r = await updater.runAutoUpdate({
        repo: UPDATE_REPO,
        mirrors: UPDATE_MIRRORS,
        currentVersion: CODE_VERSION,
        shellVersion: app.getVersion(),
        versionsDir: CODE_VERSIONS_DIR,
        currentPtr: CODE_CURRENT_PTR,
        blacklist: readBlacklist(),
        allowBlacklisted,
        log,
      });
      pushUpdateStatus(r);
      return r;
    } finally {
      updateInFlight = null;
      updateInFlightAllowsBlacklisted = false;
    }
  })();
  return updateInFlight;
}

ipcMain.handle('update:check', async () => {
  try {
    const { available, manifest } = await updater.checkForUpdate({
      repo: UPDATE_REPO, currentVersion: CODE_VERSION,
      log: (l) => console.info(l),
    });
    if (!available) return { status: 'up-to-date', currentVersion: CODE_VERSION, latest: manifest.version };
    const compatibilityBlocker = updater.getManifestCompatibilityBlocker({
      manifest,
      shellVersion: app.getVersion(),
    });
    if (compatibilityBlocker) return compatibilityBlocker;
    return { status: 'available', currentVersion: CODE_VERSION, latest: manifest.version };
  } catch (e) {
    return { status: 'error', error: e.message };
  }
});

// 手动操作是显式用户选择，允许重试曾被健康门拉黑的版本；定时/启动自动更新仍严格跳过。
ipcMain.handle('update:apply', () => triggerUpdate({ allowBlacklisted: true }));

ipcMain.handle('update:get-status', () => lastUpdateStatus);

// React 只有在自身已挂载且用当前 token 完成 /ping + /status 探活后才调用此握手。
// 与 backendReadyGen 同时满足后才开始 90 秒稳定计时，防止前端白屏却把 OTA 标成 last-good。
ipcMain.handle('update:renderer-ready', (event) => {
  if (!mainWindow || mainWindow.isDestroyed() || event.sender !== mainWindow.webContents) {
    return { ok: false, error: 'invalid renderer' };
  }
  rendererReady = true;
  clearRendererReadyTimer();
  maybeScheduleMarkGood(readyGen);
  return { ok: true };
});

// 立即重启壳子使已落地的新版本生效（resolveCodeDir 重新读 current 指针）。
ipcMain.handle('update:relaunch', () => {
  if (lastUpdateStatus.status !== 'staged') return { ok: false, error: '当前没有待应用的更新' };
  appQuitting = true;
  app.relaunch();
  app.quit();
  return { ok: true };
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
// 单实例锁（修复 M28）
//  托盘化设计下关窗只是 hide 到托盘（见 win.on('close')），用户极易误以为已退出而再次
//  双击快捷方式 → 第二个 Electron 实例正常启动并再 spawn 一个 python main.py --gui：
//  两个后端抢 8765/8766 端口、第二实例 unlink 掉第一实例正在用的 .gui_token、
//  Telegram bot 双 polling 触发 409、punch_records JSON 被两进程并发写。
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
  // 先建窗口显示（覆盖层先出来），再拉起后端。代码 OTA 只接受与当前壳依赖指纹一致的包，
  // 不会在客户端运行时联网执行 pip；依赖变化必须通过新版客户端交付。
  migrateLegacyDataIfNeeded();
  await createWindow();
  createTray();
  spawnPython();
  // 监听系统唤醒：睡眠跨过启动/探活窗口后，唤醒重新侦测就绪 + 探活后端（详见 handleResume）。
  // powerMonitor 须在 app ready 后注册。
  powerMonitor.on('resume', () => { void handleResume(); });
  // 代码 OTA：仅打包态在启动后延迟触发一次自动检查/下载（dev 不自动，避免把 OTA 代码 stage 进 userData
  // 后下次 dev 启动反加载它而非仓库源码）。延迟让后端/窗口先就绪，全程非阻塞、失败安全。
  if (app.isPackaged) {
    updateStartupTimer = setTimeout(() => {
      updateStartupTimer = null;
      void triggerUpdate();
    }, 8000);
    // 应用长期驻留托盘时也能发现更新；已有 staged 版本时 triggerUpdate 会幂等短路。
    updateInterval = setInterval(() => { void triggerUpdate(); }, UPDATE_INTERVAL_MS);
  }
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
  clearPendingRestart(); // 退出前取消挂起的重启定时器，防止其到点后又把后端拉起
  clearGoodTimer();      // 取消「稳定运行」确认计时器
  clearRendererReadyTimer(); // 取消前端健康截止计时器
  if (updateStartupTimer) { clearTimeout(updateStartupTimer); updateStartupTimer = null; }
  if (updateInterval) { clearInterval(updateInterval); updateInterval = null; }
  flushGuiSettings();
  flushEpaperLog();
  killPython();
});
