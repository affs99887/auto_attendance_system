// 壳子代码 OTA 更新模块（阶段2）
// ----------------------------------------------------------------------------
// 职责：查 manifest → 比版本 → 下载 zip（ghproxy 镜像 + 直连双保险）→ 校验 SHA256 →
//       解压到 <userData>/aas-code/versions/<ver> → 原子写 current 指针。
//       下次启动 main.cjs 的 resolveCodeDir 即加载新代码，壳子无需重打包。
//
// 安全边界（本模块只对这些负责，做对做严）：
//  - manifest 只允许从 GitHub HTTPS 直连获取，并用壳内固化的 Ed25519 公钥验签；镜像绝不参与元数据下载。
//  - 资产可走镜像，但下载内容必须匹配“已验签 manifest”内的 SHA256，镜像只能造成 DoS，不能替换代码。
//  - 可信仓库(repo)与镜像列表为壳子常量；打包态不接受环境变量覆盖（见 main.cjs），杜绝把「更新来源」
//    （manifest 从哪个仓库取）改向攻击者仓库——这是比「manifest 内容被篡改」更前置的攻击面。
//  - 下载内容必须 SHA256 与 manifest 严格相符（大小若给也校验），否则丢弃，绝不落地。
//  - 解压后必须结构合法（backend/main.py + dist/index.html，与 resolveCodeDir.isValidBundleDir 同口径）。
//  - 全程原子落位：临时目录解压 → 校验 → rename 到 versions/<ver> → 原子写指针；任一步失败都不影响现有版本。
//
// 本模块同时提供最低壳版本、Python 依赖指纹门禁与坏版本黑名单检查；
// 首启联合健康判定、自动回滚和进程重启由 main.cjs 负责。

const { net } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const { aasOtaTrust, aasRequirementsHash } = require('../package.json');

// 可信源固定为编译期常量。是否允许 env(AAS_UPDATE_REPO/AAS_UPDATE_MIRRORS)覆盖，由 main.cjs 按 app.isPackaged
// 决定：打包态一律用这些硬编码值、绝不认 env——否则用户级环境变量(HKCU\Environment 无需管理员即可写)可把 OTA
// 改向攻击者仓库，借受信任的已安装应用持久化执行任意代码（与 main.cjs 对 AAS_CODE_DIR 的「打包态忽略」同思路）。
// 镜像域名易变，dev 联调时可经 AAS_UPDATE_MIRRORS 覆盖；最后一个 '' = 直连兜底。
const DEFAULT_REPO = 'affs99887/auto_attendance_system';
const DEFAULT_MIRRORS = ['https://ghfast.top/', 'https://mirror.ghproxy.com/', 'https://ghproxy.net/', ''];
if (!aasOtaTrust || typeof aasOtaTrust.keyId !== 'string'
    || typeof aasOtaTrust.publicKeySpkiBase64 !== 'string') {
  throw new Error('package.json 缺少合法的 aasOtaTrust 信任锚');
}
const SIGNING_KEY_ID = aasOtaTrust.keyId;
// Ed25519 SubjectPublicKeyInfo DER（Base64）。package.json 是客户端与发布脚本共用的唯一信任锚来源；
// 对应私钥仅存 GitHub Secret AAS_OTA_SIGNING_KEY，绝不下发。
const TRUSTED_MANIFEST_KEYS = Object.freeze({
  [SIGNING_KEY_ID]: aasOtaTrust.publicKeySpkiBase64,
});
const SUPPORTED_REQUIREMENTS_HASH = typeof aasRequirementsHash === 'string'
  ? aasRequirementsHash.toLowerCase()
  : '';

const MANIFEST_TIMEOUT_MS = 15_000;
const ASSET_TIMEOUT_MS = 180_000;
const MANIFEST_MAX_BYTES = 1 << 20;        // 1 MB：manifest 是小 JSON，超此即视为异常
const RELEASES_API_MAX_BYTES = 8 << 20;    // 单页 8 MB：Release body/assets 可能较大，但必须有硬上限
const RELEASES_PER_PAGE = 100;
const RELEASES_MAX_PAGES = 10;             // 最多枚举 1000 个 Release；额外探测一页确认是否完整
const MAX_REDIRECTS = 5;
const ASSET_MAX_BYTES_HARD = 256 << 20;    // 256 MB：manifest 未给 size 时的硬上限兜底，防 OOM
const EXTRACTED_MAX_BYTES = 384 << 20;      // 解压后总大小硬上限，防 zip bomb 填满磁盘
const EXTRACTED_MAX_FILES = 10_000;
const EXTRACTED_MAX_SINGLE_FILE = 128 << 20;
const INSTALLED_MANIFEST_FILE = '.ota-manifest.json'; // 保留签名信封，供每次启动重新验证解压后的整棵文件树

// 版本名白名单：与 main.cjs.isSafeVersionName / 打包器版本号校验严格同口径。
function isSafeVersionName(ver) {
  return typeof ver === 'string' && /^\d+\.\d+\.\d+$/.test(ver);
}

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map(k => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(',')}}`;
}

// 对解压目录生成确定性的文件树摘要：相对路径、大小和逐文件 SHA256 一并纳入。
// 签名信封旁车文件本身不属于 ZIP，故排除；其余临时/未知文件都会改变摘要并被拒绝。
function hashBundleTree(rootDir) {
  const root = path.resolve(rootDir);
  const nodes = [];
  let entryCount = 0;
  let totalBytes = 0;
  const walk = (dir) => {
    const entries = fs.readdirSync(dir, { withFileTypes: true })
      .sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(root, full).split(path.sep).join('/');
      if (rel === INSTALLED_MANIFEST_FILE) continue;
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

function verifyManifestEnvelope(envelope, repo) {
  if (!envelope || envelope.schemaVersion !== 1 || !envelope.signed || !envelope.signature) {
    throw new Error('manifest 签名信封格式非法');
  }
  const sigMeta = envelope.signature;
  if (sigMeta.algorithm !== 'ed25519' || typeof sigMeta.keyId !== 'string') {
    throw new Error('manifest 签名算法或 keyId 非法');
  }
  const publicKeyB64 = TRUSTED_MANIFEST_KEYS[sigMeta.keyId];
  if (!publicKeyB64) throw new Error(`manifest 使用未信任的签名密钥: ${safeForLog(sigMeta.keyId)}`);
  if (typeof sigMeta.value !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(sigMeta.value)) {
    throw new Error('manifest 签名字段非法');
  }
  const signature = Buffer.from(sigMeta.value, 'base64');
  if (signature.length !== 64) throw new Error('manifest Ed25519 签名长度非法');
  const publicKey = crypto.createPublicKey({
    key: Buffer.from(publicKeyB64, 'base64'),
    format: 'der',
    type: 'spki',
  });
  const ok = crypto.verify(
    null,
    Buffer.from(canonicalJson(envelope.signed), 'utf-8'),
    publicKey,
    signature,
  );
  if (!ok) throw new Error('manifest Ed25519 签名验证失败');

  const manifest = envelope.signed;
  if (!isSafeVersionName(manifest.version)) throw new Error('manifest 版本号非法');
  if (!isSafeVersionName(manifest.minShellVersion)) throw new Error('manifest 最低壳版本非法');
  if (manifest.repository !== repo) throw new Error('manifest 仓库标识与壳内可信仓库不一致');
  if (!/^[0-9a-f]{64}$/i.test(manifest.sha256 || '')) throw new Error('manifest sha256 字段非法');
  if (!/^[0-9a-f]{64}$/i.test(manifest.treeSha256 || '')) throw new Error('manifest treeSha256 字段非法');
  if (!/^[0-9a-f]{64}$/i.test(manifest.requirementsHash || '')) {
    throw new Error('manifest requirementsHash 字段非法');
  }
  if (!Number.isSafeInteger(manifest.size) || manifest.size <= 0 || manifest.size > ASSET_MAX_BYTES_HARD) {
    throw new Error(`manifest size 超出允许范围(1-${ASSET_MAX_BYTES_HARD})`);
  }
  if (manifest.tag !== `code-v${manifest.version}`) throw new Error('manifest tag 与版本号不一致');
  if (manifest.asset !== `aas-code-${manifest.version}.zip`) throw new Error('manifest asset 与版本号不一致');
  return manifest;
}

// 数字点分版本比较：a>b 返回 1，a<b 返回 -1，相等 0。忽略预发布标签（我方版本均为纯数字点分）。
function compareVersions(a, b) {
  // 不转 Number，避免 API 中超长数字段溢出为 Infinity 后把不同版本误判成相等。
  const parts = (value) => String(value).split('.').map((part) => {
    const match = /^\d+/.exec(part);
    return ((match && match[0]) || '0').replace(/^0+(?=\d)/, '');
  });
  const pa = parts(a);
  const pb = parts(b);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const aa = pa[i] || '0';
    const bb = pb[i] || '0';
    if (aa.length !== bb.length) return aa.length > bb.length ? 1 : -1;
    if (aa !== bb) return aa > bb ? 1 : -1;
  }
  return 0;
}

// 返回阻止当前壳加载该 manifest 的明确原因；null 表示兼容。
// requirementsHash 绑定当前壳发布时审核过的依赖集合：代码 OTA 不会联网执行 pip，依赖变化必须随新壳发布。
function getManifestCompatibilityBlocker({ manifest, shellVersion }) {
  if (!manifest || !isSafeVersionName(manifest.version)
      || !isSafeVersionName(manifest.minShellVersion)
      || !/^[0-9a-f]{64}$/i.test(manifest.requirementsHash || '')) {
    throw new Error('无法判断 manifest 兼容性：字段非法');
  }
  if (!isSafeVersionName(shellVersion)) throw new Error('客户端壳版本号非法');
  if (!/^[0-9a-f]{64}$/.test(SUPPORTED_REQUIREMENTS_HASH)) {
    throw new Error('客户端缺少合法的 Python 依赖信任指纹');
  }
  if (compareVersions(manifest.minShellVersion, shellVersion) > 0) {
    return { status: 'shell-outdated', version: manifest.version, requiredShell: manifest.minShellVersion };
  }
  if (manifest.requirementsHash.toLowerCase() !== SUPPORTED_REQUIREMENTS_HASH) {
    return { status: 'dependencies-outdated', version: manifest.version };
  }
  return null;
}

// 校验一个地址只能是 github 的 https 资产地址（manifest 可被篡改，必须夹住协议+主机）。
function assertGithubHttps(url) {
  let u;
  try { u = new URL(url); } catch { throw new Error('非法 URL: ' + url); }
  if (u.protocol !== 'https:') throw new Error('仅允许 https，拒绝: ' + url);
  const host = u.hostname.toLowerCase();
  if (host !== 'github.com' && host !== 'api.github.com' && host !== 'objects.githubusercontent.com'
      && host !== 'release-assets.githubusercontent.com' && !host.endsWith('.githubusercontent.com')) {
    throw new Error('资产主机不在白名单(github): ' + host);
  }
}

function assertHttps(url) {
  let u;
  try { u = new URL(url); } catch { throw new Error('非法 URL: ' + url); }
  if (u.protocol !== 'https:') throw new Error('仅允许 https，拒绝: ' + url);
}

// 把完整 https URL 套上镜像前缀；'' 前缀=直连。
function withMirror(mirror, url) {
  if (!mirror) return url;
  return mirror.replace(/\/+$/, '') + '/' + url;
}

function assertRepoName(repo) {
  if (typeof repo !== 'string' || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo) || repo.length > 200) {
    throw new Error('GitHub 仓库名非法');
  }
}

function releasesApiUrl(repo, page) {
  assertRepoName(repo);
  if (!Number.isSafeInteger(page) || page < 1 || page > RELEASES_MAX_PAGES + 1) throw new Error('Release API 页码非法');
  return `https://api.github.com/repos/${repo}/releases?per_page=${RELEASES_PER_PAGE}&page=${page}`;
}

function manifestUrl(repo, tag) {
  assertRepoName(repo);
  if (typeof tag !== 'string' || !/^code-v\d+\.\d+\.\d+$/.test(tag)) throw new Error('代码 Release 标签非法');
  return `https://github.com/${repo}/releases/download/${tag}/manifest.json`;
}

// 去掉控制字符并截断，防止把（可被篡改的）manifest URL/错误信息含 \r\n 拼进日志、注入伪造日志行。
function safeForLog(s) {
  let out = ""; for (const ch of String(s)) { if (ch.charCodeAt(0) >= 32) out += ch; } return out.slice(0, 200);
}

// 用 Electron net 下载 URL 到 Buffer（跟随重定向、走 app 网络栈），带超时与字节上限。
function fetchBuffer(url, timeoutMs, maxBytes, validateUrl = assertHttps, headers = null) {
  return new Promise((resolve, reject) => {
    let done = false;
    let redirectCount = 0;
    const finish = (err, buf) => { if (!done) { done = true; err ? reject(err) : resolve(buf); } };
    let req;
    try {
      validateUrl(url);
      req = net.request({ url, redirect: 'manual' });
      if (headers) {
        for (const [name, value] of Object.entries(headers)) req.setHeader(name, value);
      }
    } catch (e) {
      return finish(e);
    }
    const timer = setTimeout(() => { try { req.abort(); } catch { /* ignore */ } finish(new Error(`下载超时 ${timeoutMs}ms`)); }, timeoutMs);
    req.on('redirect', (_statusCode, _method, redirectUrl) => {
      try {
        redirectCount++;
        if (redirectCount > MAX_REDIRECTS) throw new Error(`重定向次数超过上限 ${MAX_REDIRECTS}`);
        validateUrl(redirectUrl);
        req.followRedirect();
      } catch (e) {
        clearTimeout(timer);
        try { req.abort(); } catch { /* ignore */ }
        finish(e);
      }
    });
    req.on('response', (res) => {
      const code = res.statusCode || 0;
      if (code < 200 || code >= 300) {
        clearTimeout(timer);
        res.on('error', () => {}); // 与 2xx 分支对称，避免未挂 error 监听时 EventEmitter 抛未捕获异常
        res.on('data', () => {});
        res.on('end', () => {});
        return finish(new Error(`HTTP ${code}`));
      }
      const chunks = [];
      let received = 0;
      res.on('data', (c) => {
        received += c.length;
        // 防 OOM：响应体超过上限立即中止（manifest/资产分别传入小/大上限）
        if (maxBytes && received > maxBytes) {
          try { req.abort(); } catch { /* ignore */ }
          clearTimeout(timer);
          return finish(new Error(`响应体超过上限 ${maxBytes} 字节`));
        }
        chunks.push(c);
      });
      res.on('end', () => { clearTimeout(timer); finish(null, Buffer.concat(chunks)); });
      res.on('error', (e) => { clearTimeout(timer); finish(e); });
    });
    req.on('error', (e) => { clearTimeout(timer); finish(e); });
    req.end();
  });
}

// 从已枚举的 Release 中按纯数字版本排序，选出最高的正式 code-vX.Y.Z，并严格核对 manifest 资产字段。
// API 只负责“发现”；最终代码信任仍来自 manifest 的壳内 Ed25519 公钥验签。
function selectLatestCodeRelease(releases, repo) {
  assertRepoName(repo);
  if (!Array.isArray(releases)) throw new Error('GitHub Releases API 响应不是数组');
  const candidates = [];
  for (const release of releases) {
    if (!release || typeof release !== 'object' || Array.isArray(release) || typeof release.tag_name !== 'string') continue;
    const match = /^code-v(\d+\.\d+\.\d+)$/.exec(release.tag_name);
    if (!match) continue;
    if (typeof release.draft !== 'boolean' || typeof release.prerelease !== 'boolean') {
      throw new Error(`代码 Release ${safeForLog(release.tag_name)} 状态字段非法`);
    }
    if (release.draft || release.prerelease) continue;
    candidates.push({ release, tag: release.tag_name, version: match[1] });
  }
  if (!candidates.length) throw new Error('未找到正式的 code-vX.Y.Z Release');
  candidates.sort((a, b) => compareVersions(b.version, a.version));

  const chosen = candidates[0];
  if (!Array.isArray(chosen.release.assets)) throw new Error(`代码 Release ${chosen.tag} 的 assets 字段非法`);
  const assets = chosen.release.assets.filter((asset) => asset && asset.name === 'manifest.json');
  if (assets.length !== 1) throw new Error(`代码 Release ${chosen.tag} 必须且只能包含一个 manifest.json`);
  const asset = assets[0];
  if (asset.state !== 'uploaded'
      || !Number.isSafeInteger(asset.size) || asset.size <= 0 || asset.size > MANIFEST_MAX_BYTES
      || typeof asset.browser_download_url !== 'string') {
    throw new Error(`代码 Release ${chosen.tag} 的 manifest.json 资产字段非法`);
  }
  const expectedUrl = manifestUrl(repo, chosen.tag);
  assertGithubHttps(asset.browser_download_url);
  if (asset.browser_download_url !== expectedUrl) {
    throw new Error(`代码 Release ${chosen.tag} 的 manifest.json 下载地址不可信`);
  }
  return { tag: chosen.tag, version: chosen.version, manifestUrl: expectedUrl };
}

async function discoverLatestCodeRelease({ repo, log }) {
  const releases = [];
  let complete = false;
  for (let page = 1; page <= RELEASES_MAX_PAGES + 1; page++) {
    const url = releasesApiUrl(repo, page);
    assertGithubHttps(url);
    log && log(`[updater] 查询 GitHub 代码 Release（第 ${page} 页）`);
    const buf = await fetchBuffer(url, MANIFEST_TIMEOUT_MS, RELEASES_API_MAX_BYTES, assertGithubHttps, {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'AutoAttendance-Updater',
    });
    let pageItems;
    try { pageItems = JSON.parse(buf.toString('utf-8')); } catch (e) { throw new Error('GitHub Releases API 解析失败: ' + e.message); }
    if (!Array.isArray(pageItems) || pageItems.length > RELEASES_PER_PAGE) {
      throw new Error('GitHub Releases API 响应字段非法');
    }
    // 前 10 页刚好填满时再探测第 11 页：空页表示“恰好 1000 个”，非空则拒绝在不完整集合上猜版本。
    if (page > RELEASES_MAX_PAGES) {
      if (pageItems.length) {
        throw new Error(`GitHub Release 超过 ${RELEASES_PER_PAGE * RELEASES_MAX_PAGES} 个，无法可靠确定最新代码版本`);
      }
      complete = true;
      break;
    }
    releases.push(...pageItems);
    if (pageItems.length < RELEASES_PER_PAGE) { complete = true; break; }
  }
  if (!complete) throw new Error('GitHub Releases API 分页未完整结束');
  return selectLatestCodeRelease(releases, repo);
}

// 依次尝试镜像 + 直连，任一成功即返回 Buffer。rawUrl 必须已通过 assertGithubHttps。
async function fetchWithMirrors(rawUrl, mirrors, timeoutMs, maxBytes, log) {
  let lastErr;
  for (const m of mirrors) {
    const url = withMirror(m, rawUrl);
    try {
      log && log(`[updater] 下载: ${safeForLog(url)}`);
      return await fetchBuffer(url, timeoutMs, maxBytes, assertHttps);
    } catch (e) {
      lastErr = e;
      log && log(`[updater] 失败(${m || '直连'}): ${safeForLog(e.message)}`);
    }
  }
  throw lastErr || new Error('所有镜像与直连均失败');
}

// 查 manifest 并与当前版本比对。保留已验签信封，落地后写入版本目录供每次启动复验文件树。
async function checkForUpdate({ repo, currentVersion, log }) {
  const latestRelease = await discoverLatestCodeRelease({ repo, log });
  const raw = latestRelease.manifestUrl;
  assertGithubHttps(raw);
  log && log(`[updater] 获取最新代码 Release ${latestRelease.tag} 的签名 manifest`);
  const buf = await fetchBuffer(raw, MANIFEST_TIMEOUT_MS, MANIFEST_MAX_BYTES, assertGithubHttps);
  let envelope;
  try { envelope = JSON.parse(buf.toString('utf-8')); } catch (e) { throw new Error('manifest 解析失败: ' + e.message); }
  const manifest = verifyManifestEnvelope(envelope, repo);
  if (manifest.version !== latestRelease.version || manifest.tag !== latestRelease.tag) {
    throw new Error('签名 manifest 与最新代码 Release 标签不一致');
  }
  // 只接受严格更高版本，禁止 latest 配置错误、回滚 Release 或网络缓存导致客户端被静默降级。
  const available = compareVersions(manifest.version, currentVersion) > 0;
  return { available, manifest, envelope };
}

// 用 PowerShell Expand-Archive 解压（应用为 Windows-only；不引入 npm 解压依赖以保持壳子精简）。
function extractZip(zipPath, destDir) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(destDir, { recursive: true });
    const esc = (s) => s.replace(/'/g, "''"); // PowerShell 单引号转义
    const script = `
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipPath = '${esc(zipPath)}'
$dest = [IO.Path]::GetFullPath('${esc(destDir)}')
$root = $dest.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
  $total = [int64]0
  $count = 0
  foreach ($entry in $zip.Entries) {
    $count++
    if ($count -gt ${EXTRACTED_MAX_FILES}) { throw 'zip 文件数量超过上限' }
    if ([int64]$entry.Length -gt ${EXTRACTED_MAX_SINGLE_FILE}) { throw ('zip 单文件过大: ' + $entry.FullName) }
    $total += [int64]$entry.Length
    if ($total -gt ${EXTRACTED_MAX_BYTES}) { throw 'zip 解压后总大小超过上限' }
    $target = [IO.Path]::GetFullPath([IO.Path]::Combine($dest, $entry.FullName))
    if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw ('zip 路径穿越: ' + $entry.FullName) }
  }
} finally { $zip.Dispose() }
Expand-Archive -LiteralPath $zipPath -DestinationPath $dest -Force
`;
    const ps = spawn('powershell.exe', [
      '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command',
      script,
    ], { windowsHide: true });
    let err = '';
    ps.stderr.on('data', (d) => { err += d.toString(); });
    ps.on('error', reject);
    ps.on('exit', (code) => code === 0 ? resolve() : reject(new Error(`Expand-Archive 失败(code ${code}): ${err.slice(0, 500)}`)));
  });
}

function writePointerAtomic(currentPtr, ver) {
  fs.mkdirSync(path.dirname(currentPtr), { recursive: true });
  const tmp = `${currentPtr}.tmp`;
  fs.writeFileSync(tmp, ver, 'utf-8');
  fs.renameSync(tmp, currentPtr); // 同卷 rename 原子替换，杜绝写一半的指针
}

// 结构合法判定：与 main.cjs resolveCodeDir.isValidBundleDir 同口径
function bundleComplete(dir) {
  return fs.existsSync(path.join(dir, 'backend', 'main.py'))
    && fs.existsSync(path.join(dir, 'dist', 'index.html'));
}

function bundleMatchesManifest(dir, manifest) {
  try {
    const meta = JSON.parse(fs.readFileSync(path.join(dir, 'bundle.json'), 'utf-8'));
    return meta && meta.version === manifest.version
      && meta.minShellVersion === manifest.minShellVersion
      && typeof meta.requirementsHash === 'string'
      && meta.requirementsHash.toLowerCase() === manifest.requirementsHash.toLowerCase()
      && hashBundleTree(dir).toLowerCase() === manifest.treeSha256.toLowerCase();
  } catch { return false; }
}

function writeInstalledManifestAtomic(dir, envelope) {
  const finalPath = path.join(dir, INSTALLED_MANIFEST_FILE);
  const tmpPath = `${finalPath}.tmp-${process.pid}-${Date.now()}`;
  fs.writeFileSync(tmpPath, JSON.stringify(envelope), 'utf-8');
  try { fs.renameSync(tmpPath, finalPath); } finally { try { fs.rmSync(tmpPath, { force: true }); } catch { /* ignore */ } }
}

// 启动加载前重新验证：旁车信封的 Ed25519 签名、版本/壳/依赖门禁，以及磁盘实际文件树摘要。
// 因此已落地目录被损坏或篡改后不会被执行，也不会靠修改 bundle.json 绕过签名。
function verifyInstalledBundle({ dir, expectedVersion, repo, shellVersion }) {
  if (!bundleComplete(dir)) throw new Error('代码包结构不完整');
  const manifestPath = path.join(dir, INSTALLED_MANIFEST_FILE);
  const stat = fs.statSync(manifestPath);
  if (!stat.isFile() || stat.size <= 0 || stat.size > MANIFEST_MAX_BYTES) throw new Error('已安装 manifest 大小非法');
  const envelope = JSON.parse(fs.readFileSync(manifestPath, 'utf-8'));
  const manifest = verifyManifestEnvelope(envelope, repo);
  if (manifest.version !== expectedVersion) throw new Error('已安装 manifest 版本与目录名不一致');
  const blocker = getManifestCompatibilityBlocker({ manifest, shellVersion });
  if (blocker && blocker.status === 'shell-outdated') throw new Error(`需要客户端壳 ${blocker.requiredShell} 或更高版本`);
  if (blocker && blocker.status === 'dependencies-outdated') throw new Error('Python 依赖与当前客户端不兼容');
  if (!bundleMatchesManifest(dir, manifest)) throw new Error('代码包文件树与签名 manifest 不一致');
  return manifest;
}

function readVersionPointer(pointerPath) {
  try {
    const value = fs.readFileSync(pointerPath, 'utf-8').trim();
    return isSafeVersionName(value) ? value : null;
  } catch { return null; }
}

// 只在调用方已确认存在 last-good 后回收旧版本。保护集合覆盖：磁盘 current（含待验证版本）、
// last-good（回滚目标）和当前进程实际运行版本；未知目录、临时目录、符号链接/联接点一律不碰。
function cleanupOldVersions({ versionsDir, currentPtr, lastGoodPtr, runningVersion, log }) {
  const lastGood = readVersionPointer(lastGoodPtr);
  if (!lastGood || !bundleComplete(path.join(versionsDir, lastGood))) {
    return { removed: [], skipped: 'no-valid-last-good' };
  }
  let current = null;
  if (fs.existsSync(currentPtr)) {
    current = readVersionPointer(currentPtr);
    // current 文件存在却无法解析时，无法证明哪个目录是待验证版本，宁可完全不清理。
    if (!current) return { removed: [], skipped: 'invalid-current' };
  }
  const protectedVersions = new Set([lastGood]);
  if (current) protectedVersions.add(current);
  if (isSafeVersionName(runningVersion)) protectedVersions.add(runningVersion);

  const removed = [];
  let entries;
  try { entries = fs.readdirSync(versionsDir, { withFileTypes: true }); } catch { return { removed }; }
  for (const entry of entries) {
    if (!isSafeVersionName(entry.name) || protectedVersions.has(entry.name)) continue;
    const candidate = path.join(versionsDir, entry.name);
    try {
      const stat = fs.lstatSync(candidate);
      if (!entry.isDirectory() || stat.isSymbolicLink()) continue;
      fs.rmSync(candidate, { recursive: true, force: true });
      removed.push(entry.name);
      log && log(`[updater] 已清理旧代码版本 ${entry.name}`);
    } catch (e) {
      log && log(`[updater] 清理旧版本 ${entry.name} 失败: ${safeForLog(e.message)}`);
    }
  }
  return { removed };
}

// 下载 + 校验 + 解压 + 原子落位 versions/<ver> + 写 current 指针。
async function downloadAndStage({ manifest, envelope, repo, mirrors, versionsDir, currentPtr, log }) {
  const ver = manifest.version;
  if (!isSafeVersionName(ver)) throw new Error('非法版本号: ' + ver);
  const verifiedManifest = verifyManifestEnvelope(envelope, repo);
  if (canonicalJson(verifiedManifest) !== canonicalJson(manifest)) throw new Error('下载流程中的 manifest 信封不一致');
  fs.mkdirSync(versionsDir, { recursive: true });

  const finalDir = path.join(versionsDir, ver);
  // 幂等短路：该版本已落地且结构合法 → 仅(重)写指针即可，绝不进入「先 rmSync(finalDir) 再下载」的破坏性
  // 路径（否则重复 apply 同一已 staged 版本会先删掉 current 正指向的目录，留下「指针有效但目录缺失」空窗）。
  if (bundleComplete(finalDir) && bundleMatchesManifest(finalDir, manifest)) {
    writeInstalledManifestAtomic(finalDir, envelope);
    writePointerAtomic(currentPtr, ver);
    log && log(`[updater] 版本 ${ver} 已就位，跳过下载`);
    return { ok: true, version: ver, skipped: true };
  }

  // 清扫历史残留的临时目录/zip（此前异常中断遗留），避免长期堆积
  try {
    for (const e of fs.readdirSync(versionsDir)) {
      if (e.startsWith('.tmp-')) { try { fs.rmSync(path.join(versionsDir, e), { recursive: true, force: true }); } catch { /* ignore */ } }
    }
  } catch { /* ignore */ }

  // 地址完全由壳内可信 repo + 已验签且严格校验过的 tag/asset 拼出，不接受 manifest 任意 URL。
  const assetUrl = `https://github.com/${repo}/releases/download/${manifest.tag}/${manifest.asset}`;
  assertGithubHttps(assetUrl);

  // 资产字节上限：manifest.size 已知则取其 +1MB 余量，未知则用硬上限兜底，双防 OOM
  const assetMax = Math.min(ASSET_MAX_BYTES_HARD, manifest.size + (1 << 20));
  const zipBuf = await fetchWithMirrors(assetUrl, mirrors, ASSET_TIMEOUT_MS, assetMax, log);
  if (manifest.size && zipBuf.length !== manifest.size) {
    throw new Error(`下载大小不符: ${zipBuf.length} != ${manifest.size}`);
  }
  const got = crypto.createHash('sha256').update(zipBuf).digest('hex');
  if (got.toLowerCase() !== String(manifest.sha256).toLowerCase()) {
    throw new Error(`SHA256 校验失败: ${got} != ${manifest.sha256}`);
  }

  const tmpBase = path.join(versionsDir, `.tmp-${ver}-${Date.now()}-${process.pid}`);
  const tmpZip = `${tmpBase}.zip`;
  const stageDir = `${tmpBase}.dir`;
  fs.writeFileSync(tmpZip, zipBuf);
  try {
    fs.rmSync(stageDir, { recursive: true, force: true });
    await extractZip(tmpZip, stageDir);
    // 结构校验（与 resolveCodeDir.isValidBundleDir 同口径），缺任一即拒绝落地（绝不切到半截代码）。
    // zip-slip：Expand-Archive 自身拒绝含 .. 的穿越条目，且包内容已过 SHA256 强校验（来自我方 CI）；
    // 遍历 stageDir 也只能看到落在其内的文件、无法发现已逃逸到目录外的条目，故不再额外遍历。
    if (!bundleComplete(stageDir)) {
      throw new Error('代码包结构不完整（缺 backend/main.py 或 dist/index.html）');
    }
    if (!bundleMatchesManifest(stageDir, manifest)) {
      throw new Error('代码包 bundle.json 与签名 manifest 不一致');
    }
    writeInstalledManifestAtomic(stageDir, envelope);
    fs.rmSync(finalDir, { recursive: true, force: true });
    fs.renameSync(stageDir, finalDir); // 原子落位（同在 versionsDir 下，同卷）
    writePointerAtomic(currentPtr, ver);
    log && log(`[updater] 已落地版本 ${ver}，重启后生效`);
    return { ok: true, version: ver };
  } finally {
    // 清理失败绝不能顶替/掩盖 try 内的真实错误（Expand-Archive/结构/SHA256 等），各自吞掉
    try { fs.rmSync(tmpZip, { force: true }); } catch { /* ignore */ }
    try { fs.rmSync(stageDir, { recursive: true, force: true }); } catch { /* ignore */ } // rename 成功后已不存在
  }
}

// 一站式：查更新 → 壳/依赖/黑名单门禁 → 有则下载落地。失败一律吞掉（不影响当前运行），返回结构化状态。
async function runAutoUpdate({ repo, mirrors, currentVersion, shellVersion, versionsDir, currentPtr, blacklist, allowBlacklisted = false, log }) {
  try {
    const { available, manifest, envelope } = await checkForUpdate({ repo, currentVersion, log });
    if (!available) {
      log && log(`[updater] 已是最新 (${currentVersion})`);
      return { status: 'up-to-date', currentVersion };
    }
    const compatibilityBlocker = getManifestCompatibilityBlocker({ manifest, shellVersion });
    if (compatibilityBlocker) {
      if (compatibilityBlocker.status === 'shell-outdated') {
        log && log(`[updater] 新版本 ${manifest.version} 需客户端(壳)≥${compatibilityBlocker.requiredShell}（当前 ${shellVersion}），跳过更新`);
      } else {
        log && log(`[updater] 新版本 ${manifest.version} 修改了 Python 依赖，当前客户端不执行运行时 pip；请先升级客户端`);
      }
      return compatibilityBlocker;
    }
    // 黑名单门禁：该版本曾启动失败被回滚 → 不再自动重装，避免「装→崩→回滚→又装」跨重启反复翻车，
    // 直到上游发布更新的版本（version 不在黑名单）才会再尝试。
    if (!allowBlacklisted && Array.isArray(blacklist) && blacklist.includes(manifest.version)) {
      log && log(`[updater] 最新版本 ${manifest.version} 曾启动失败被回滚，跳过自动重装（等待更新的版本）`);
      return {
        status: 'error',
        error: `版本 ${manifest.version} 曾启动失败，已跳过自动更新；可手动下载重试`,
        skippedBad: manifest.version,
      };
    }
    if (allowBlacklisted && Array.isArray(blacklist) && blacklist.includes(manifest.version)) {
      log && log(`[updater] 用户手动重试已拉黑版本 ${manifest.version}`);
    }
    log && log(`[updater] 发现新版本 ${manifest.version}（当前 ${currentVersion}），开始下载`);
    const r = await downloadAndStage({ manifest, envelope, repo, mirrors, versionsDir, currentPtr, log });
    return { status: 'staged', version: r.version };
  } catch (e) {
    log && log(`[updater] 更新失败（不影响当前运行）: ${e.message}`);
    return { status: 'error', error: e.message };
  }
}

module.exports = {
  DEFAULT_REPO,
  DEFAULT_MIRRORS,
  SIGNING_KEY_ID,
  isSafeVersionName,
  compareVersions,
  canonicalJson,
  hashBundleTree,
  verifyManifestEnvelope,
  verifyInstalledBundle,
  getManifestCompatibilityBlocker,
  assertGithubHttps,
  selectLatestCodeRelease,
  discoverLatestCodeRelease,
  checkForUpdate,
  downloadAndStage,
  cleanupOldVersions,
  runAutoUpdate,
};
