// 代码包打包器（瘦壳 + 代码 OTA 的产出端）
// ----------------------------------------------------------------------------
// 把「已编译前端 dist + 后端 .py 源码」组装成一个版本化代码包 zip，并产出 manifest.json，
// 供 GitHub Release 分发、壳子运行期下载校验后原子切换（阶段2）。
//
// 关键边界：
//  - bin/（mihomo 56MB + geo）与 msedgedriver 不进代码包——它们体积大、极少变，由壳子固定发一次，
//    后端经 AAS_BIN_DIR 回指（见 main.cjs / proxy_manager._bin_dir）。代码包只装频繁变动的 .py 与 dist。
//  - 前端必须预先 build（本脚本不替你跑 vite build，只校验 dist 已存在）——后端是解释执行可直接拉源码跑，
//    前端是编译产物，故由 CI/本地先 `npm run build` 出 dist，本脚本再打包。
//
// 用法：
//   AAS_OTA_SIGNING_KEY=<Ed25519 PKCS8 PEM> node scripts/build-code-bundle.mjs --version 2.1.0
//     [--min-shell 0.1.0] [--out <dir>] [--repo owner/name] [--sign-key <pem-file>]
//   node scripts/build-code-bundle.mjs --verify-config  # 只校验壳内信任锚与 requirements 指纹，不需要私钥/dist
//   （本地便捷：先 npm run build 再 npm run bundle -- --version 2.1.0；注意 npm 把 -- 之后的参数只挂到
//    脚本字符串链尾，故 package.json 的 bundle 脚本里 `node build-code-bundle.mjs` 必须保持在 && 链尾，
//    否则收不到 --version 会静默回退用壳子 package.json 版本号。CI 直接 node 调用不受此限。）
//
// 产出（默认 <repo>/release/code-bundle/<version>/；同版本目录不可覆盖）：
//   aas-code-<version>.zip   —— 解包后含 backend/ + dist/ + bundle.json
//   manifest.json            —— Ed25519 签名信封；signed 内含版本、摘要、大小、壳版本门禁等元数据

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const AdmZip = require('adm-zip'); // devDependency；仅打包期用，不进壳子运行时

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// gui/desktop/scripts → 仓库根：上 3 层（scripts → desktop → gui → repo）
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const GUI_DESKTOP = path.resolve(__dirname, '..');

// ---- 解析参数 ----
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--version') out.version = argv[++i];
    else if (a === '--min-shell') out.minShell = argv[++i];
    else if (a === '--out') out.out = argv[++i];
    else if (a === '--repo') out.repo = argv[++i];
    else if (a === '--sign-key') out.signKey = argv[++i];
    else if (a === '--verify-config') out.verifyConfig = true;
  }
  return out;
}
const args = parseArgs(process.argv.slice(2));

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf-8'));
}

const shellPkg = readJson(path.join(GUI_DESKTOP, 'package.json'));
// 代码包版本：优先 --version；否则回退壳子 package.json 版本（本地调试用）。CI 必传 --version（来自 tag）。
const VERSION = args.version || shellPkg.aasCodeVersion || '0.0.0';
// 本代码包要求的最低壳子版本：默认=当前壳子版本（不要求升壳）。当代码新增了需要新壳能力（如新 IPC）
// 时由 --min-shell 抬高，壳子端阶段3 据此判定「太旧则跳过更新并提示升级客户端」。
const MIN_SHELL = args.minShell || shellPkg.version || '0.0.0';
const OUT_DIR = path.resolve(args.out || path.join(REPO_ROOT, 'release', 'code-bundle', VERSION));
// GitHub 仓库标识 owner/name：CI 经 --repo "${{ github.repository }}" 注入（或读 GITHUB_REPOSITORY）。
// 该值进入签名载荷；客户端必须与壳内固定可信仓库完全一致，资产 URL 由壳自行拼接。
const REPO = args.repo || process.env.GITHUB_REPOSITORY || 'affs99887/auto_attendance_system';
const OTA_TRUST = shellPkg.aasOtaTrust;

// 版本号格式校验：必须与壳子 isSafeVersionName 同口径（纯数字三段版本），
// 否则壳子的 current 指针白名单会拒收，导致更新永远不被采纳。
const STRICT_VERSION_RE = /^\d+\.\d+\.\d+$/;
if (!STRICT_VERSION_RE.test(shellPkg.aasCodeVersion || '')) {
  console.error(`[bundle] package.json 缺少合法的 aasCodeVersion：${shellPkg.aasCodeVersion || '(空)'}`);
  process.exit(1);
}
if (!STRICT_VERSION_RE.test(VERSION)) {
  console.error(`[bundle] 非法版本号：${VERSION}（必须是纯数字三段版本，如 2.1.0）`);
  process.exit(1);
}
if (!STRICT_VERSION_RE.test(MIN_SHELL)) {
  console.error(`[bundle] 非法最低壳版本：${MIN_SHELL}（必须是纯数字三段版本，如 0.1.0）`);
  process.exit(1);
}
if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(REPO)) {
  console.error(`[bundle] 非法 GitHub 仓库标识：${REPO}`);
  process.exit(1);
}

// JSON Canonicalization 的精简实现：对象键递归排序、数组保序。产出端与壳子验证端必须完全同口径，
// 这样镜像即使改写字段顺序/空白也不会影响签名，任何字段值变化则必然验签失败。
function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map(k => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`;
}

const ASSET_MAX_BYTES_HARD = 256 << 20;
const EXTRACTED_MAX_BYTES = 384 << 20;
const EXTRACTED_MAX_FILES = 10_000;
const EXTRACTED_MAX_SINGLE_FILE = 128 << 20;
const INSTALLED_MANIFEST_FILE = '.ota-manifest.json';

// 与客户端 updater.hashBundleTree 完全同口径；同时在签名前执行客户端接收上限，避免发布必被拒绝的包。
function hashBundleTree(rootDir) {
  const root = path.resolve(rootDir);
  const nodes = [];
  const windowsPaths = new Map();
  let entryCount = 0;
  let totalBytes = 0;
  const validateWindowsPath = (rel) => {
    for (const segment of rel.split('/')) {
      if (!segment || /[\x00-\x1f<>:"\\|?*]/.test(segment) || /[ .]$/.test(segment)) {
        throw new Error(`代码包路径无法在 Windows 安全落地: ${rel}`);
      }
      const base = segment.split('.')[0];
      if (/^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(base)) {
        throw new Error(`代码包使用 Windows 保留名称: ${rel}`);
      }
    }
    const key = rel.toLowerCase();
    const existing = windowsPaths.get(key);
    if (existing && existing !== rel) throw new Error(`代码包含 Windows 大小写冲突路径: ${existing} / ${rel}`);
    windowsPaths.set(key, rel);
  };
  const walk = (dir) => {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
      .sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(root, full).split(path.sep).join('/');
      if (rel === INSTALLED_MANIFEST_FILE) throw new Error(`${INSTALLED_MANIFEST_FILE} 是客户端保留文件名`);
      validateWindowsPath(rel);
      entryCount += 1;
      if (entryCount > EXTRACTED_MAX_FILES) throw new Error(`代码包条目数超过上限 ${EXTRACTED_MAX_FILES}`);
      const stat = fs.lstatSync(full);
      if (stat.isSymbolicLink()) throw new Error(`代码包不允许符号链接: ${rel}`);
      if (stat.isDirectory()) {
        nodes.push({ path: rel, type: 'directory' });
        walk(full);
        continue;
      }
      if (!stat.isFile()) throw new Error(`代码包含非普通文件: ${rel}`);
      if (stat.size > EXTRACTED_MAX_SINGLE_FILE) throw new Error(`代码包单文件超过上限: ${rel}`);
      totalBytes += stat.size;
      if (totalBytes > EXTRACTED_MAX_BYTES) throw new Error(`代码包总大小超过上限 ${EXTRACTED_MAX_BYTES}`);
      const sha256 = crypto.createHash('sha256').update(fs.readFileSync(full)).digest('hex');
      nodes.push({ path: rel, type: 'file', size: stat.size, sha256 });
    }
  };
  walk(root);
  nodes.sort((a, b) => a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  return crypto.createHash('sha256').update(canonicalJson(nodes), 'utf-8').digest('hex');
}

function sha256NormalizedFile(file) {
  const normalized = fs.readFileSync(file, 'utf-8').replace(/\r\n/g, '\n');
  return crypto.createHash('sha256').update(normalized, 'utf-8').digest('hex');
}

function validateOtaTrust() {
  if (!OTA_TRUST || !/^[A-Za-z0-9_.-]{1,100}$/.test(OTA_TRUST.keyId || '')
      || typeof OTA_TRUST.publicKeySpkiBase64 !== 'string'
      || !/^[A-Za-z0-9+/]+={0,2}$/.test(OTA_TRUST.publicKeySpkiBase64)) {
    throw new Error('package.json 缺少合法的 aasOtaTrust 信任锚');
  }
  const publicKey = crypto.createPublicKey({
    key: Buffer.from(OTA_TRUST.publicKeySpkiBase64, 'base64'),
    format: 'der',
    type: 'spki',
  });
  if (publicKey.asymmetricKeyType !== 'ed25519') {
    throw new Error(`受信公钥类型为 ${publicKey.asymmetricKeyType || 'unknown'}`);
  }
  return publicKey;
}

let trustedPublicKey;
try {
  trustedPublicKey = validateOtaTrust();
} catch (e) {
  console.error(`[bundle] OTA 信任锚无效：${e.message}`);
  process.exit(1);
}

function loadSigningKey() {
  // CI 从 GitHub Secret AAS_OTA_SIGNING_KEY 注入 PEM；本地验证可传 --sign-key <pem>。
  // 没有私钥必须失败，绝不降级生成“只有 SHA256、没有来源认证”的 manifest。
  const pem = args.signKey
    ? fs.readFileSync(path.resolve(args.signKey), 'utf-8')
    : process.env.AAS_OTA_SIGNING_KEY;
  if (!pem) {
    console.error('[bundle] 缺少 OTA Ed25519 私钥：请设置 AAS_OTA_SIGNING_KEY 或传 --sign-key <pem>');
    process.exit(1);
  }
  try {
    const key = crypto.createPrivateKey(pem);
    if (key.asymmetricKeyType !== 'ed25519') throw new Error(`密钥类型为 ${key.asymmetricKeyType || 'unknown'}`);
    const derivedPublicDer = crypto.createPublicKey(key).export({ format: 'der', type: 'spki' });
    const trustedPublicDer = trustedPublicKey.export({ format: 'der', type: 'spki' });
    if (derivedPublicDer.length !== trustedPublicDer.length
        || !crypto.timingSafeEqual(derivedPublicDer, trustedPublicDer)) {
      throw new Error(`私钥与客户端信任锚 ${OTA_TRUST.keyId} 不匹配`);
    }
    return key;
  } catch (e) {
    console.error(`[bundle] OTA 私钥无效：${e.message}`);
    process.exit(1);
  }
}

// 代码 OTA 不在客户端运行时从 PyPI/镜像安装代码。requirements 变更必须随新壳发布，并由壳内
// aasRequirementsHash 显式声明；否则旧壳会下载到未被 Ed25519 覆盖的 wheel，破坏更新信任链。
const SOURCE_REQUIREMENTS = path.join(REPO_ROOT, 'requirements.txt');
const supportedRequirementsHash = shellPkg.aasRequirementsHash;
if (!/^[0-9a-f]{64}$/i.test(supportedRequirementsHash || '')) {
  console.error('[bundle] package.json 缺少合法的 aasRequirementsHash');
  process.exit(1);
}
if (!fs.existsSync(SOURCE_REQUIREMENTS)) {
  console.error(`[bundle] 缺少依赖清单：${SOURCE_REQUIREMENTS}`);
  process.exit(1);
}
const requirementsHash = sha256NormalizedFile(SOURCE_REQUIREMENTS);
if (requirementsHash.toLowerCase() !== supportedRequirementsHash.toLowerCase()) {
  console.error(
    '[bundle] requirements.txt 已变化，不能作为纯代码 OTA 发布；请先发布新壳并更新 package.json 的 '
    + `aasRequirementsHash（当前实际值 ${requirementsHash}）`,
  );
  process.exit(1);
}

if (args.verifyConfig) {
  console.log(`[bundle] OTA 配置校验通过（KeyId=${OTA_TRUST.keyId}, requirementsHash=${requirementsHash}）`);
  process.exit(0);
}

// 在清理/生成任何 release 产物前先验证私钥；缺 Secret 时 CI 立即失败，不留下可误发布的半成品。
const signingKey = loadSigningKey();

// ---- 校验前端已构建 ----
const GUI_DIST = path.join(GUI_DESKTOP, 'dist');
if (!fs.existsSync(path.join(GUI_DIST, 'index.html'))) {
  console.error(`[bundle] 未找到 ${path.join(GUI_DIST, 'index.html')}；请先在 gui/desktop 跑 \`npm run build\` 生成 dist。`);
  process.exit(1);
}

// 每个版本使用独立输出目录且禁止原地覆盖：同 tag 重建会产生不同 ZIP，覆盖会破坏已发布 manifest/ZIP 配对。
const zipName = `aas-code-${VERSION}.zip`;
const zipPath = path.join(OUT_DIR, zipName);
const manifestPath = path.join(OUT_DIR, 'manifest.json');
if (fs.existsSync(OUT_DIR)) {
  console.error(`[bundle] 版本 ${VERSION} 的产物已存在，禁止原地覆盖；请使用新版本号或显式指定空的 --out 目录`);
  process.exit(1);
}

// 所有内容先在最终目录旁的独立临时目录完整生成；最后只做一次目录 rename，ZIP/manifest 不会出现半套状态。
const OUT_PARENT = path.dirname(OUT_DIR);
fs.mkdirSync(OUT_PARENT, { recursive: true });
const WORK_DIR = path.join(OUT_PARENT, `.tmp-${path.basename(OUT_DIR)}-${process.pid}-${Date.now()}`);
const STAGE = path.join(WORK_DIR, 'stage');
const VERIFY_DIR = path.join(WORK_DIR, 'verify');
const PUBLISH_DIR = path.join(WORK_DIR, 'publish');
const TEMP_ZIP = path.join(PUBLISH_DIR, zipName);
const TEMP_MANIFEST = path.join(PUBLISH_DIR, 'manifest.json');
const STAGE_BACKEND = path.join(STAGE, 'backend');
const STAGE_DIST = path.join(STAGE, 'dist');
let buildError = null;
let builtAt;
let treeSha256;
let sha256;
let size;
const TAG = `code-v${VERSION}`;

try {
  fs.mkdirSync(STAGE_BACKEND, { recursive: true });
  fs.mkdirSync(PUBLISH_DIR, { recursive: true });

  // ---- 拷贝后端（与 electron-builder.yml extraResources 的白名单/排除保持一致；但不含 bin/msedgedriver）----
  const BACKEND_FILES = ['main.py', 'start.py', 'watchdog.py', 'requirements.txt', '.env.example'];
  for (const f of BACKEND_FILES) {
    const src = path.join(REPO_ROOT, f);
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, path.join(STAGE_BACKEND, f));
    } else if (f === 'main.py' || f === 'requirements.txt') {
      throw new Error(`缺少客户端必需的后端文件：${f}`);
    } else {
      console.warn(`[bundle] 跳过缺失的可选后端文件：${f}`);
    }
  }

  const copyFilter = (src) => {
    const base = path.basename(src);
    if (base === '__pycache__') return false;
    if (src.endsWith('.pyc')) return false;
    return true;
  };
  for (const d of ['modules', 'templates']) {
    const src = path.join(REPO_ROOT, d);
    if (fs.existsSync(src)) {
      fs.cpSync(src, path.join(STAGE_BACKEND, d), { recursive: true, filter: copyFilter });
    } else if (d === 'modules') {
      throw new Error('缺少客户端必需的后端目录：modules');
    } else {
      console.warn(`[bundle] 跳过缺失的可选后端目录：${d}`);
    }
  }

  // ---- 拷贝前端 dist + 写 bundle.json ----
  fs.cpSync(GUI_DIST, STAGE_DIST, { recursive: true });
  builtAt = new Date().toISOString();
  const bundleMeta = { version: VERSION, builtAt, minShellVersion: MIN_SHELL, requirementsHash };
  fs.writeFileSync(path.join(STAGE, 'bundle.json'), JSON.stringify(bundleMeta, null, 2));
  if (!fs.existsSync(path.join(STAGE_BACKEND, 'main.py'))
      || !fs.statSync(path.join(STAGE_BACKEND, 'modules')).isDirectory()
      || !fs.existsSync(path.join(STAGE_DIST, 'index.html'))) {
    throw new Error('代码包最终结构不完整（需要 backend/main.py、backend/modules、dist/index.html）');
  }

  // 整棵文件树摘要进入 Ed25519 签名载荷；客户端每次启动都会重新计算，防止落地后损坏/篡改。
  treeSha256 = hashBundleTree(STAGE);

  // ---- 在临时目录打 ZIP，并执行客户端同口径大小上限 ----
  const zip = new AdmZip();
  zip.addLocalFolder(STAGE);
  zip.writeZip(TEMP_ZIP);
  const zipBuf = fs.readFileSync(TEMP_ZIP);
  size = zipBuf.length;
  if (size <= 0 || size > ASSET_MAX_BYTES_HARD) throw new Error(`ZIP 大小超出客户端上限 1-${ASSET_MAX_BYTES_HARD}`);
  sha256 = crypto.createHash('sha256').update(zipBuf).digest('hex');

  // ---- 生成签名 manifest ----
  const signed = {
    version: VERSION,
    builtAt,
    minShellVersion: MIN_SHELL,
    requirementsHash,
    treeSha256,
    repository: REPO,
    tag: TAG,
    asset: zipName,
    sha256,
    size,
  };
  const signature = crypto.sign(
    null,
    Buffer.from(canonicalJson(signed), 'utf-8'),
    signingKey,
  ).toString('base64');
  if (!crypto.verify(null, Buffer.from(canonicalJson(signed), 'utf-8'), trustedPublicKey, Buffer.from(signature, 'base64'))) {
    throw new Error('产出 manifest 自验签失败');
  }
  const manifest = {
    schemaVersion: 1,
    signed,
    signature: { algorithm: 'ed25519', keyId: OTA_TRUST.keyId, value: signature },
  };
  fs.writeFileSync(TEMP_MANIFEST, JSON.stringify(manifest, null, 2));

  // 自解压后再次核对结构和树摘要，防止打包器异常生成客户端必拒绝的 ZIP。
  new AdmZip(TEMP_ZIP).extractAllTo(VERIFY_DIR, true);
  if (!fs.existsSync(path.join(VERIFY_DIR, 'backend', 'main.py'))
      || !fs.existsSync(path.join(VERIFY_DIR, 'dist', 'index.html'))
      || hashBundleTree(VERIFY_DIR) !== treeSha256) {
    throw new Error('ZIP 自解压后的结构或文件树摘要不一致');
  }

  // stage/verify 不属于发布目录；清理后一次原子提升完整 publish 目录。并发构建只有一个能占用 OUT_DIR。
  fs.rmSync(STAGE, { recursive: true, force: true });
  fs.rmSync(VERIFY_DIR, { recursive: true, force: true });
  fs.renameSync(PUBLISH_DIR, OUT_DIR);
} catch (e) {
  buildError = e;
} finally {
  try { fs.rmSync(WORK_DIR, { recursive: true, force: true }); } catch { /* ignore */ }
}

if (buildError) {
  console.error(`[bundle] 构建失败：${buildError.message}`);
  process.exit(1);
}

console.log('[bundle] 完成');
console.log(`  版本      : ${VERSION}`);
console.log(`  tag       : ${TAG}`);
console.log(`  仓库      : ${REPO}`);
console.log(`  最低壳版本: ${MIN_SHELL}`);
console.log(`  zip       : ${zipPath}`);
console.log(`  大小      : ${(size / 1024 / 1024).toFixed(2)} MB`);
console.log(`  sha256    : ${sha256}`);
console.log(`  treeSha256: ${treeSha256}`);
console.log(`  reqHash   : ${requirementsHash}`);
console.log(`  签名 KeyId: ${OTA_TRUST.keyId}`);
console.log(`  manifest  : ${manifestPath}`);
