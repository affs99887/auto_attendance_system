"""
内置网络加速管理（mihomo / Clash.Meta）

把一个 mihomo 核心当子进程拉起，监听本地专属端口（默认 7899），**只代理本程序**：
- 不设系统代理、不走 TUN/全局 —— 与系统 VPN/代理状态解耦。
- 本程序只连 127.0.0.1:<port>（回环永不经系统 VPN）。
- 由 Python 侧管理，GUI / 控制台 / watchdog 三种模式下都生效。

诚实边界：mihomo 自身连机场节点的出站仍走 OS 网络栈；若系统是全局 TUN VPN 会双跳。

二进制随安装包打包于项目根 bin/ （国内无代理时无法运行时下载）。
"""

import os
import re
import json
import time
import shutil
import secrets
import logging
import asyncio
import zipfile
import platform
import subprocess
import threading

import requests

from modules.config import config

logger = logging.getLogger(__name__)

# 业务接口共用的本地代理快速回退。端口可连接只说明 mihomo 进程已监听，不能证明当前
# 节点/DNS/上游已可用；按服务隔离熔断，避免一个目标站故障影响其他目标站。
_PROXY_FALLBACK_COOLDOWN_SECONDS = 60.0
_proxy_request_circuits = {}
_proxy_request_circuit_lock = threading.Lock()
_proxy_request_generation = 0


def reset_proxy_request_circuits():
    """清空业务请求的代理熔断状态（代理启动、重载或切换节点后调用）。"""
    global _proxy_request_generation
    with _proxy_request_circuit_lock:
        _proxy_request_generation += 1
        _proxy_request_circuits.clear()


def _claim_local_proxy_attempt(service_key, now):
    """返回 (是否尝试本地代理, 是否为冷却后的单次探测, 当前代次)。"""
    with _proxy_request_circuit_lock:
        generation = _proxy_request_generation
        state = _proxy_request_circuits.get(service_key)
        if state is None:
            return True, False, generation
        if now < state['open_until']:
            return False, False, generation
        if state['probe_inflight']:
            return False, False, generation
        state['probe_inflight'] = True
        return True, True, generation


def _open_proxy_request_circuit(service_key, generation):
    with _proxy_request_circuit_lock:
        # 切换节点/重载后的旧在途请求不能重新熔断新配置。
        if generation != _proxy_request_generation:
            return
        _proxy_request_circuits[service_key] = {
            'open_until': time.monotonic() + _PROXY_FALLBACK_COOLDOWN_SECONDS,
            'probe_inflight': False,
        }


def _close_proxy_request_circuit(service_key, generation):
    with _proxy_request_circuit_lock:
        # 同理，旧请求成功也不能清掉新代次刚建立的熔断。
        if generation == _proxy_request_generation:
            _proxy_request_circuits.pop(service_key, None)


def _release_proxy_probe(service_key, generation):
    with _proxy_request_circuit_lock:
        if generation != _proxy_request_generation:
            return
        state = _proxy_request_circuits.get(service_key)
        if state is not None:
            state['probe_inflight'] = False


def request_get_with_local_proxy_fallback(service_key, url, **kwargs):
    """优先经本地 mihomo 发 GET；连接/超时失败时立即改走默认网络。

    熔断按 service_key 隔离，冷却期间不再撞故障代理；HTTP 状态码和响应解析错误
    不属于代理连通性问题，由调用方按原逻辑处理。日志不输出 URL，避免泄露路径凭据。
    """
    try:
        local_proxy = config.get_local_proxy()
    except Exception as exc:
        logger.warning(
            '读取本地代理配置失败，服务 %s 改走默认网络（%s）',
            service_key, type(exc).__name__,
        )
        return requests.get(url, **kwargs)

    if not local_proxy:
        return requests.get(url, **kwargs)

    should_try_proxy, half_open_probe, generation = _claim_local_proxy_attempt(
        service_key, time.monotonic())
    if not should_try_proxy:
        return requests.get(url, **kwargs)

    try:
        response = requests.get(url, proxies=local_proxy, **kwargs)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        _open_proxy_request_circuit(service_key, generation)
        logger.warning(
            '本地代理请求失败，服务 %s 在 %.0f 秒内改走默认网络（%s）',
            service_key, _PROXY_FALLBACK_COOLDOWN_SECONDS, type(exc).__name__,
        )
        return requests.get(url, **kwargs)
    except Exception:
        if half_open_probe:
            _release_proxy_probe(service_key, generation)
        raise
    else:
        _close_proxy_request_circuit(service_key, generation)
        return response

# Telegram 走代理的规则（订阅模式自生成；仅域名/IP，不依赖 geo 数据库）
_TELEGRAM_RULES = [
    'DOMAIN-SUFFIX,telegram.org,{group}',
    'DOMAIN-SUFFIX,t.me,{group}',
    'DOMAIN-SUFFIX,telegram.me,{group}',
    'DOMAIN-SUFFIX,telegram.dog,{group}',
    'DOMAIN-SUFFIX,tdesktop.com,{group}',
    'IP-CIDR,149.154.160.0/20,{group},no-resolve',
    'IP-CIDR,91.108.4.0/22,{group},no-resolve',
    'IP-CIDR,91.108.8.0/22,{group},no-resolve',
    'IP-CIDR,91.108.12.0/22,{group},no-resolve',
    'IP-CIDR,91.108.16.0/22,{group},no-resolve',
    'IP-CIDR,91.108.56.0/22,{group},no-resolve',
    'IP-CIDR,95.161.64.0/20,{group},no-resolve',
    'MATCH,DIRECT',
]

_HEALTH_URL = 'https://www.gstatic.com/generate_204'

# 抓订阅时伪装的 UA（多数机场按此返回 Clash.Meta 格式 + subscription-userinfo 头）
_SUB_USER_AGENT = 'clash.meta'


# ---------------------------------------------------------------------------
# Windows Job Object（KILL_ON_JOB_CLOSE）——让 mihomo 随 Python 进程"任意方式"退出
# 被 OS 当场连带回收（含硬杀 taskkill /F、任务管理器结束、崩溃、os._exit、os.execl）。
# 纯 ctypes 实现，不引入 pywin32 依赖；非 Windows 全部跳过。
# ---------------------------------------------------------------------------
_JOB_SUPPORTED = (os.name == 'nt')

if _JOB_SUPPORTED:
    import ctypes
    from ctypes import wintypes

    JobObjectExtendedLimitInformation = 9          # JOBOBJECTINFOCLASS
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit",     wintypes.LARGE_INTEGER),
            ("LimitFlags",              wintypes.DWORD),
            ("MinimumWorkingSetSize",   ctypes.c_size_t),
            ("MaximumWorkingSetSize",   ctypes.c_size_t),
            ("ActiveProcessLimit",      wintypes.DWORD),
            ("Affinity",                ctypes.c_size_t),   # ULONG_PTR
            ("PriorityClass",           wintypes.DWORD),
            ("SchedulingClass",         wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount",  ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount",   ctypes.c_ulonglong),
            ("WriteTransferCount",  ctypes.c_ulonglong),
            ("OtherTransferCount",  ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo",                IO_COUNTERS),
            ("ProcessMemoryLimit",    ctypes.c_size_t),
            ("JobMemoryLimit",        ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed",     ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _create_kill_on_close_job():
    """创建设置了 KILL_ON_JOB_CLOSE 的匿名 Job。成功返回 job 句柄(int)，失败返回 None（记日志不抛）。"""
    if not _JOB_SUPPORTED:
        return None
    try:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            logger.warning('CreateJobObjectW 失败 (err=%s)，跳过 Job 防护', ctypes.get_last_error())
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            logger.warning('SetInformationJobObject 失败 (err=%s)，关闭 Job 并降级', ctypes.get_last_error())
            _kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        logger.warning('创建 Job 对象异常，降级到 pidfile/stop 兜底', exc_info=True)
        return None


def _assign_proc_to_job(job, proc):
    """把 Popen 子进程加入 Job。成功 True；失败 False（调用方据此降级）。借用 _handle 句柄值，不接管所有权。"""
    if not _JOB_SUPPORTED or not job or proc is None:
        return False
    try:
        handle = int(proc._handle)   # Windows 下 Popen._handle 即进程 HANDLE
    except Exception:
        logger.warning('获取 mihomo 进程句柄失败，跳过 Job 赋值', exc_info=True)
        return False
    try:
        ok = _kernel32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(handle))
    except Exception:
        logger.warning('AssignProcessToJobObject 异常，降级', exc_info=True)
        return False
    if not ok:
        logger.warning('AssignProcessToJobObject 失败 (err=%s)，降级到 pidfile/stop 兜底', ctypes.get_last_error())
        return False
    return True


class ProxyManager:
    """mihomo 子进程 + external-controller API 客户端。"""

    def __init__(self, project_root=None):
        # 代码根（modules/..）：dev=项目根；打包=resources/backend。随安装包附带的 bin/（mihomo
        # 二进制 + geo 源库）在此，跟代码走，故用 __file__ 推导。
        self.code_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # 数据根：proxy_runtime（config.yaml / profiles 用户粘贴的配置 / mihomo.log / pid / 缓存）
        # 属"可写用户数据"，必须与 config.py 读 dynamic_config.json、punch_records/logs 等同根 → 用 cwd。
        # 打包后 main.cjs 以 cwd=DATA_DIR(真实数据树) 拉起后端；若这里仍用 __file__ 落到只读的
        # resources/backend/proxy_runtime（其 profiles/ 为空），打包版会读不到用户的本地代理配置而抛
        # "尚未提供 Clash 配置文本"，导致 mihomo 永远起不来、本地代理端口无人监听 → 全程"断网"。
        self.project_root = project_root or os.getcwd()
        self.runtime_dir = os.path.join(self.project_root, 'proxy_runtime')
        self.proc = None
        self._job = None  # Windows Job Object 句柄（KILL_ON_JOB_CLOSE）；非 Windows/降级时为 None
        self._last_traffic = None  # (ts, up_total, down_total)
        # [M41] watchdog 协程的停止开关：main.py 在关停时置 True，让巡检循环优雅退出
        self._watchdog_stop = False
        # [M26] 启动即把存量 local 正文迁出 dynamic_config.json（幂等；失败不致命，不阻断构造）
        try:
            self._migrate_local_content_out()
        except Exception:
            logger.warning('迁出本地代理配置正文失败（忽略，不影响运行）', exc_info=True)

    # ------------------------------------------------------------------ 路径
    def _bin_dir(self):
        # bin/ 随代码打包（resources/backend/bin），与可写数据根 proxy_runtime 解耦。
        return os.path.join(self.code_root, 'bin')

    def mihomo_path(self):
        name = 'mihomo.exe' if os.name == 'nt' else 'mihomo'
        return os.path.join(self._bin_dir(), name)

    def binary_available(self):
        return os.path.isfile(self.mihomo_path())

    def _config_path(self):
        return os.path.join(self.runtime_dir, 'config.yaml')

    def _source_config_path(self):
        # 用户"粘贴的完整 Clash 配置"原文（旧字段；保留以兼容迁移）
        return os.path.join(self.runtime_dir, 'source_config.yaml')

    def _profiles_dir(self):
        # 每个 profile 的 yaml 缓存目录（订阅 yaml 可再生；local 落地后供 mihomo 解析）
        return os.path.join(self.runtime_dir, 'profiles')

    def _profile_cache_path(self, profile_id):
        return os.path.join(self._profiles_dir(), f'{profile_id}.yaml')

    # ------------------------------------------------------------------ local 正文落盘
    # [M26] local profile 正文（用户粘贴的整份 Clash 配置，常达数百 KB）只存 profiles/<id>.yaml，
    # 绝不再写进 dynamic_config.json —— 避免每次切节点/改端口都全量重写约 500KB JSON、放大损坏窗口。
    def _read_local_content(self, prof):
        """读取 local profile 正文：优先 profiles/<id>.yaml，缺失则回退内联 content（兼容未迁移的旧数据）。"""
        pid = prof.get('id') if isinstance(prof, dict) else None
        if pid:
            cache = self._profile_cache_path(pid)
            if os.path.isfile(cache):
                try:
                    with open(cache, 'r', encoding='utf-8') as f:
                        return f.read()
                except OSError:
                    logger.warning('读取本地 profile 缓存失败: %s', pid, exc_info=True)
        return (prof.get('content') if isinstance(prof, dict) else None) or ''

    def _write_local_content(self, profile_id, content):
        """把 local profile 正文落到 profiles/<id>.yaml。失败记日志不抛（与既有缓存写入风格一致）。"""
        os.makedirs(self._profiles_dir(), exist_ok=True)
        try:
            with open(self._profile_cache_path(profile_id), 'w', encoding='utf-8') as f:
                f.write(content or '')
        except OSError:
            logger.warning('落地本地 profile 失败: %s', profile_id, exc_info=True)

    def _migrate_local_content_out(self):
        """一次性迁移：把存量 local profile 的内联 content 搬到 profiles/<id>.yaml 并从 JSON 删除，
        立即把 dynamic_config.json 收缩回 KB 级。幂等：无 content 字段时不写盘。"""
        profiles, _ = self._get_profiles()
        changed = False
        for p in profiles:
            if not isinstance(p, dict) or p.get('type') != 'local':
                continue
            content = p.get('content')
            if content:  # 仅当 JSON 里仍带正文时才搬迁
                self._write_local_content(p['id'], content)
            if 'content' in p:
                p.pop('content', None)
                changed = True
        if changed:
            config.set_proxy_config({'profiles': profiles})
            logger.info('已将本地代理配置正文迁出 dynamic_config.json（仅保留元数据）')

    def _pid_path(self):
        return os.path.join(self.runtime_dir, 'mihomo.pid')

    def _log_path(self):
        return os.path.join(self.runtime_dir, 'mihomo.log')

    # ------------------------------------------------------------------ 配置生成
    def _ensure_runtime(self):
        os.makedirs(self.runtime_dir, exist_ok=True)
        # 若打包附带 geo 数据库，复制到运行目录（mihomo 在 -d 目录查找），仅一次
        for fn in ('geoip.metadb', 'geoip.dat', 'geosite.dat', 'GeoIP.dat', 'GeoSite.dat', 'Country.mmdb'):
            src = os.path.join(self._bin_dir(), fn)
            dst = os.path.join(self.runtime_dir, fn)
            if os.path.isfile(src) and not os.path.isfile(dst):
                try:
                    shutil.copy2(src, dst)
                except Exception:
                    logger.warning('复制 geo 数据库失败: %s', fn, exc_info=True)

    # ------------------------------------------------------------------ profile 工具
    def _get_profiles(self):
        """返回 (profiles 列表, active_id)。"""
        cfg = config.get_proxy_config()
        profiles = cfg.get('profiles')
        if not isinstance(profiles, list):
            profiles = []
        return profiles, cfg.get('active_profile_id') or ''

    def _find_profile(self, profiles, profile_id):
        for p in profiles:
            if isinstance(p, dict) and p.get('id') == profile_id:
                return p
        return None

    def _get_active_profile(self):
        """返回当前激活 profile（dict）或 None。"""
        profiles, active_id = self._get_profiles()
        prof = self._find_profile(profiles, active_id)
        if prof is None and profiles:
            prof = profiles[0]  # active 失效时兜底取第一个
        return prof

    def _public_profile(self, prof, active_id):
        """剥离内部细节，返回给 GUI 的 Profile JSON（附带 active 布尔）。"""
        return {
            'id': prof.get('id'),
            'name': prof.get('name'),
            'type': prof.get('type'),
            'url': prof.get('url') or '',
            'updated_at': prof.get('updated_at'),
            'traffic': prof.get('traffic'),
            'node_count': prof.get('node_count'),
            'active': prof.get('id') == active_id,
        }

    def _count_nodes(self, yaml_text):
        """尽力而为地统计 proxies: 条目数（正则，不依赖 PyYAML）。"""
        if not yaml_text:
            return None
        m = re.search(r'(?m)^proxies:\s*$', yaml_text)
        if not m:
            # 形如 "proxies: []" 之类的内联写法
            return None
        # 统计 proxies: 之后、下一个顶格键之前，以 "  - " 起始的列表项
        body = yaml_text[m.end():]
        count = 0
        for line in body.splitlines():
            if re.match(r'^\S', line):  # 顶格键，proxies 段结束
                break
            if re.match(r'^\s+-\s', line):
                count += 1
        return count or None

    def _parse_userinfo(self, header_value):
        """解析 subscription-userinfo 头："upload=..; download=..; total=..; expire=.."。"""
        if not header_value:
            return None
        info = {'upload': 0, 'download': 0, 'total': 0, 'expire': None}
        for part in str(header_value).split(';'):
            part = part.strip()
            if '=' not in part:
                continue
            k, v = part.split('=', 1)
            k = k.strip().lower()
            v = v.strip()
            if k in ('upload', 'download', 'total'):
                try:
                    info[k] = int(float(v))
                except ValueError:
                    pass
            elif k == 'expire':
                try:
                    info['expire'] = int(float(v)) if v else None
                except ValueError:
                    info['expire'] = None
        return info

    def _fetch_subscription(self, url):
        """抓取订阅 URL，返回 (yaml_text, userinfo|None, node_count|None)。失败抛异常。

        同步 requests；trust_env 让其可走系统代理；带 clash.meta UA。
        """
        if not url:
            raise RuntimeError('订阅 URL 为空')
        resp = requests.get(
            url,
            headers={'User-Agent': _SUB_USER_AGENT},
            timeout=(10, 60),
        )
        resp.raise_for_status()
        text = resp.text or ''
        if not text.strip():
            raise RuntimeError('订阅返回内容为空')
        userinfo = self._parse_userinfo(resp.headers.get('subscription-userinfo'))
        node_count = self._count_nodes(text)
        return text, userinfo, node_count

    def _build_subscription_config(self, cfg, sub_url):
        """订阅模式：手工拼 YAML（用 json.dumps 安全地引用字符串，无需 PyYAML）。"""
        group = cfg['group']
        sub_url = sub_url or ''
        lines = [
            f"mixed-port: {int(cfg['local_port'])}",
            "allow-lan: false",
            "bind-address: 127.0.0.1",
            "mode: rule",
            "log-level: warning",
            "ipv6: false",
            f"external-controller: 127.0.0.1:{int(cfg['api_port'])}",
            f"secret: {json.dumps(cfg['secret'])}",
            "proxy-providers:",
            "  AAS:",
            "    type: http",
            f"    url: {json.dumps(sub_url)}",
            "    interval: 86400",
            "    path: ./providers/AAS.yaml",
            "    health-check:",
            "      enable: true",
            f"      url: {json.dumps(_HEALTH_URL)}",
            "      interval: 300",
            "proxy-groups:",
            f"  - name: {json.dumps(group)}",
            "    type: select",
            "    use:",
            "      - AAS",
            "rules:",
        ]
        for r in _TELEGRAM_RULES:
            lines.append(f"  - {r.format(group=group)}")
        return "\n".join(lines) + "\n"

    def _build_config_from_text(self, cfg, content):
        """粘贴模式：解析用户 Clash 配置，强制覆盖关键字段；返回 (yaml_text, group_name)。

        数据源为 active profile 的 content（已由 _write_config 落到 profiles/<id>.yaml）。
        """
        try:
            import yaml  # 懒导入：仅粘贴模式需要 PyYAML
        except ImportError as e:
            raise RuntimeError("粘贴配置需要 PyYAML（pip install pyyaml），或改用订阅 URL 模式") from e

        if not (content or '').strip():
            raise RuntimeError("尚未提供 Clash 配置文本")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            raise RuntimeError("Clash 配置解析失败：根节点不是映射")

        # 强制覆盖本程序需要的控制字段
        data['mixed-port'] = int(cfg['local_port'])
        data['allow-lan'] = False
        data['bind-address'] = '127.0.0.1'
        data['external-controller'] = f"127.0.0.1:{int(cfg['api_port'])}"
        data['secret'] = cfg['secret']
        data.pop('socks-port', None)
        data.pop('port', None)
        data.pop('tun', None)  # 禁用 TUN（不接管系统）

        # 找一个可切换节点的 select 分组供 GUI 使用
        group = 'GLOBAL'
        groups = data.get('proxy-groups')
        if isinstance(groups, list):
            for g in groups:
                if isinstance(g, dict) and g.get('type') == 'select' and g.get('name'):
                    group = g['name']
                    break
            else:
                for g in groups:
                    if isinstance(g, dict) and g.get('name'):
                        group = g['name']
                        break
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False), group

    def _write_config(self):
        """根据 active profile 生成 config.yaml，返回最新（可能更新了 group 的）配置 dict。"""
        self._ensure_runtime()
        cfg = config.get_proxy_config()
        prof = self._get_active_profile()
        if prof is None:
            raise RuntimeError('尚未配置任何代理订阅/配置文件')

        if prof.get('type') == 'local':
            # [M26] 数据源持久来自 profiles/<id>.yaml（不再依赖 JSON 内联 content）
            content = self._read_local_content(prof)
            text, group = self._build_config_from_text(cfg, content)
            if group != cfg.get('group'):
                cfg = config.set_proxy_config({'group': group})
        else:
            text = self._build_subscription_config(cfg, prof.get('url') or '')
        with open(self._config_path(), 'w', encoding='utf-8') as f:
            f.write(text)
        return cfg

    # ------------------------------------------------------------------ 进程
    def _pid_is_mihomo(self, pid):
        """[M59] 杀前校验：确认该 PID 当前进程映像确实是 mihomo（防 Windows PID 复用误杀无辜进程树）。
        无法判定时保守返回 False（宁可漏杀也不误杀）。"""
        exe = 'mihomo.exe' if os.name == 'nt' else 'mihomo'
        try:
            if os.name == 'nt':
                # tasklist 输出 CSV；首列为 ImageName。无该 PID 时输出 "INFO: No tasks..."（不含进程名）
                out = subprocess.run(
                    ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
                    capture_output=True, timeout=8,
                )
                text = (out.stdout or b'').decode('utf-8', errors='replace').lower()
                return exe.lower() in text
            else:
                # 用 /proc/<pid>/comm 读进程名（comm 可能被截断，故用 startswith 容错）
                with open(f'/proc/{pid}/comm', 'r') as f:
                    return f.read().strip().startswith(exe)
        except Exception:
            return False

    def _kill_orphan(self):
        """按 pid 文件清理上一次遗留的 mihomo（watchdog 重启等场景）。"""
        pid_file = self._pid_path()
        if not os.path.isfile(pid_file):
            return
        try:
            with open(pid_file, 'r') as f:
                pid = int((f.read() or '').strip())
        except Exception:
            pid = 0
        # [M59] 仅当该 PID 当前确实是 mihomo 时才强杀（taskkill /T /F 会连带杀子树，
        # PID 复用下盲杀会误伤用户浏览器/IDE/系统进程）；不匹配则只删陈旧 pidfile。
        if pid > 0 and self._pid_is_mihomo(pid):
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'],
                                   capture_output=True, timeout=8)
                else:
                    os.kill(pid, 9)
            except Exception:
                pass
        try:
            os.remove(pid_file)
        except OSError:
            pass

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, ready_timeout=12.0):
        """生成配置 + 拉起 mihomo + 等 external-controller 就绪。返回 (ok, message)。

        同步方法（subprocess 即时 + time.sleep 轮询）；从 async 处调用建议 asyncio.to_thread。
        """
        if not config.get_proxy_enabled():
            # 即便本次禁用代理，也清掉上次启用时遗留的孤儿 mihomo + 陈旧 pidfile
            # （覆盖"上次启用留孤儿 → 这次禁用 → start 提前 return 永不清理"的盲区）
            self._kill_orphan()
            return False, '内置加速未启用'
        if not self.binary_available():
            return False, f'未找到 mihomo 二进制：{self.mihomo_path()}（请确认 bin/ 已打包）'
        if self.is_running():
            reset_proxy_request_circuits()
            return True, '已在运行'

        try:
            self._write_config()
        except Exception as e:
            logger.error('生成 mihomo 配置失败: %s', e, exc_info=True)
            return False, f'生成代理配置失败：{e}'

        self._kill_orphan()

        creationflags = 0
        if os.name == 'nt':
            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        logf = None
        try:
            logf = open(self._log_path(), 'a', encoding='utf-8', errors='replace')
            self.proc = subprocess.Popen(
                [self.mihomo_path(), '-d', self.runtime_dir, '-f', self._config_path()],
                cwd=self.runtime_dir,
                stdout=logf, stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        except Exception as e:
            logger.error('启动 mihomo 失败: %s', e, exc_info=True)
            return False, f'启动 mihomo 失败：{e}'
        finally:
            # 子进程已继承独立句柄；父端副本无需保留，确定性关闭：
            # 失败路径修复句柄泄漏，成功路径避免父端写句柄长期占用 mihomo.log（Windows 删/轮转 WinError 32）。
            if logf is not None:
                try:
                    logf.close()
                except Exception:
                    pass

        try:
            with open(self._pid_path(), 'w') as f:
                f.write(str(self.proc.pid))
        except OSError:
            pass

        # 套 Windows Job Object（KILL_ON_JOB_CLOSE）：Python 进程以任意方式消失时 OS 连带杀 mihomo。
        # 失败（旧系统/权限/取句柄失败）只记日志、不影响 mihomo 运行，退回 pidfile/stop 兜底。
        if getattr(self, '_job', None):                       # 防御：先关掉残留旧 job
            try:
                _kernel32.CloseHandle(wintypes.HANDLE(self._job))
            except Exception:
                pass
            self._job = None
        self._job = _create_kill_on_close_job()
        if self._job and not _assign_proc_to_job(self._job, self.proc):
            try:
                _kernel32.CloseHandle(wintypes.HANDLE(self._job))  # 赋值失败：关空 job，避免句柄长期悬挂
            except Exception:
                pass
            self._job = None

        # 等 external-controller 就绪
        deadline = time.time() + ready_timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False, f'mihomo 进程提前退出（code={self.proc.returncode}），请查看 {self._log_path()}'
            try:
                r = requests.get(f'{self._api_base()}/version', headers=self._headers(), timeout=1.5)
                if r.status_code == 200:
                    logger.info('mihomo 已就绪：本地端口 %s', config.get_proxy_local_port())
                    self._reselect_node_if_needed()
                    reset_proxy_request_circuits()
                    return True, '已启动'
            except Exception:
                pass
            time.sleep(0.3)
        return False, 'mihomo 启动超时（external-controller 未响应），请查看日志'

    def _reselect_node_if_needed(self):
        """external-controller 就绪后：若用户曾选过节点且仍存在于当前分组，自动选回。

        幂等（重复调用无副作用）；失败只告警不致命（重启后默认会回到分组首个节点）。
        """
        try:
            cfg = config.get_proxy_config()
            want = cfg.get('selected_node') or ''
            if not want:
                return
            data = self.list_nodes()
            names = [n.get('name') for n in (data.get('nodes') or [])]
            if want not in names:
                return
            if data.get('selected') == want:
                return  # 已是目标节点，幂等返回
            group = data.get('group') or cfg.get('group') or 'AAS-Proxy'
            r = requests.put(
                f'{self._api_base()}/proxies/{group}',
                headers=self._headers(),
                json={'name': want},
                timeout=5,
            )
            if r.status_code in (200, 204):
                logger.info('重启后已自动选回节点: %s', want)
            else:
                logger.warning('自动选回节点失败（HTTP %s）: %s', r.status_code, want)
        except Exception:
            logger.warning('自动选回节点异常（忽略）', exc_info=True)

    def stop(self):
        if self.proc is not None:
            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(self.proc.pid), '/T', '/F'],
                                   capture_output=True, timeout=8)
                else:
                    self.proc.terminate()
            except Exception:
                logger.warning('停止 mihomo 失败', exc_info=True)
            self.proc = None
        # 关闭 Job 句柄（释放 KILL_ON_JOB_CLOSE 持有；mihomo 已被 taskkill，这里仅清理资源）
        if getattr(self, '_job', None):
            try:
                _kernel32.CloseHandle(wintypes.HANDLE(self._job))
            except Exception:
                logger.warning('关闭 Job 句柄失败', exc_info=True)
            self._job = None
        try:
            os.remove(self._pid_path())
        except OSError:
            pass

    def reload(self):
        """重写配置并热重载（失败则重启）。"""
        try:
            self._write_config()
        except Exception as e:
            return False, f'生成配置失败：{e}'
        if not self.is_running():
            return self.start()
        try:
            r = requests.put(
                f'{self._api_base()}/configs',
                headers=self._headers(),
                params={'force': 'true'},
                json={'path': self._config_path()},
                timeout=5,
            )
            if r.status_code in (200, 204):
                self._reselect_node_if_needed()
                reset_proxy_request_circuits()
                return True, '已重载'
        except Exception:
            logger.warning('热重载失败，改为重启', exc_info=True)
        self.stop()
        return self.start()

    # ------------------------------------------------------------------ 健康巡检 / 自动重启
    # [M41] mihomo 子进程无健康监控时，进程一旦退出（崩溃/被安全软件杀/唤醒后异常），
    # config.get_telegram_proxy() 仍"绝不回退"地返回死端口 URL，telegram_bot.monitor_connection
    # 探测失败→restart_polling→重新 build 仍指向死端口的 app→指数退避永久失败循环，
    # 打卡通知/远程控制/截图推送全部瘫痪。这里加一个周期性巡检协程，启用代理时主动发现进程
    # 死亡并限频自动重启 mihomo，使 Telegram 全链路能随之恢复。
    async def watchdog(self, interval=30):
        """周期性巡检 mihomo 进程，启用代理且进程已死时限频自动重启。

        由 main.py 在启动内置加速后挂为后台任务；关停时置 self._watchdog_stop=True 使其退出。
        - 仅在 config.get_proxy_enabled() 为真时介入（禁用代理时不重启，交还系统代理/直连）。
        - start() 为同步阻塞方法，放进 asyncio.to_thread 执行，避免阻塞事件循环。
        - 连续重启失败做指数退避（最长 600 秒），与 monitor_connection 的退避一致，避免刷屏。
        """
        fail_count = 0  # 连续自动重启失败计数，用于指数退避
        while not self._watchdog_stop:
            try:
                # 未启用代理：不巡检（恢复计数即可），按基础间隔轮询配置变化
                if not config.get_proxy_enabled():
                    fail_count = 0
                    await asyncio.sleep(interval)
                    continue
                if self.is_running():
                    fail_count = 0
                    await asyncio.sleep(interval)
                    continue
                # 启用代理但进程已死：自动重启（同步 start 丢到线程池，不卡事件循环）
                logger.warning('巡检发现 mihomo 已退出，尝试自动重启（第 %d 次）', fail_count + 1)
                try:
                    ok, msg = await asyncio.to_thread(self.start)
                except Exception:
                    ok, msg = False, '自动重启异常'
                    logger.error('mihomo 自动重启异常', exc_info=True)
                if ok:
                    fail_count = 0
                    logger.info('mihomo 已自动重启：%s', msg)
                    await asyncio.sleep(interval)
                else:
                    fail_count += 1
                    logger.warning('mihomo 自动重启失败：%s', msg)
                    backoff = min(interval * (2 ** fail_count), 600)
                    await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error('mihomo 巡检循环异常', exc_info=True)
                await asyncio.sleep(interval)

    # ------------------------------------------------------------------ API 客户端
    def _api_base(self):
        return f'http://127.0.0.1:{config.get_proxy_api_port()}'

    def _headers(self):
        secret = config.get_proxy_config().get('secret') or ''
        return {'Authorization': f'Bearer {secret}'} if secret else {}

    def list_nodes(self):
        """返回控制分组内的节点列表 + 当前选中。"""
        cfg = config.get_proxy_config()
        group = cfg.get('group') or 'AAS-Proxy'
        r = requests.get(f'{self._api_base()}/proxies', headers=self._headers(), timeout=5)
        r.raise_for_status()
        proxies = (r.json() or {}).get('proxies', {})
        g = proxies.get(group) or {}
        names = g.get('all') or []
        selected = g.get('now')
        nodes = []
        for name in names:
            info = proxies.get(name) or {}
            history = info.get('history') or []
            delay = history[-1].get('delay') if history else None
            nodes.append({
                'name': name,
                'type': info.get('type', ''),
                'delay': delay if delay else None,
            })
        return {'group': group, 'selected': selected, 'nodes': nodes}

    def select_node(self, name):
        cfg = config.get_proxy_config()
        group = cfg.get('group') or 'AAS-Proxy'
        r = requests.put(
            f'{self._api_base()}/proxies/{group}',
            headers=self._headers(),
            json={'name': name},
            timeout=5,
        )
        if r.status_code in (200, 204):
            config.set_proxy_config({'selected_node': name})
            reset_proxy_request_circuits()
            return True
        r.raise_for_status()
        return False

    def test_delay(self, name, url=_HEALTH_URL, timeout_ms=5000):
        r = requests.get(
            f'{self._api_base()}/proxies/{name}/delay',
            headers=self._headers(),
            params={'url': url, 'timeout': timeout_ms},
            timeout=(timeout_ms / 1000.0) + 3,
        )
        if r.status_code == 200:
            return (r.json() or {}).get('delay')
        return None

    def get_traffic(self):
        """用 /connections 的累计上下行计算速率（bytes/s）。"""
        try:
            r = requests.get(f'{self._api_base()}/connections', headers=self._headers(), timeout=3)
            r.raise_for_status()
            data = r.json() or {}
        except Exception:
            return {'up': 0, 'down': 0, 'up_total': 0, 'down_total': 0}
        up_total = int(data.get('uploadTotal', 0) or 0)
        down_total = int(data.get('downloadTotal', 0) or 0)
        now = time.time()
        up = down = 0
        if self._last_traffic:
            lt, lu, ld = self._last_traffic
            dt = max(0.001, now - lt)
            up = max(0, int((up_total - lu) / dt))
            down = max(0, int((down_total - ld) / dt))
        self._last_traffic = (now, up_total, down_total)
        return {'up': up, 'down': down, 'up_total': up_total, 'down_total': down_total}

    def status(self):
        """供 GUI 展示的状态快照（不含 secret 明文）。"""
        cfg = config.get_proxy_config()
        sub = cfg.get('subscription_url') or ''
        return {
            'enabled': bool(cfg.get('enabled')),
            'running': self.is_running(),
            'binary_available': self.binary_available(),
            'source': cfg.get('source', 'subscription'),
            'local_port': cfg.get('local_port'),
            'api_port': cfg.get('api_port'),
            'group': cfg.get('group'),
            'selected_node': cfg.get('selected_node'),
            'subscription_url': sub,
            'has_config_text': os.path.isfile(self._source_config_path()),
            'active_profile_id': cfg.get('active_profile_id') or '',
        }

    # ------------------------------------------------------------------ 多配置文件管理
    def list_profiles(self):
        """返回 {'profiles': [Profile(带 active 布尔)...], 'active_id': str|None}。"""
        profiles, active_id = self._get_profiles()
        return {
            'profiles': [self._public_profile(p, active_id) for p in profiles if isinstance(p, dict)],
            'active_id': active_id or None,
        }

    def add_profile(self, type_, name=None, url=None, content=None):
        """新增 profile。subscription 则抓取+解析 userinfo；local 则存 content。

        返回 (ok, profile_dict|None, msg)。新增后若当前无 active，则设为 active。
        """
        type_ = (type_ or '').strip()
        if type_ not in ('subscription', 'local'):
            return False, None, '未知配置类型'

        prof = {
            'id': secrets.token_hex(4),
            'name': (name or '').strip(),
            'type': type_,
            'url': '',
            'content': '',
            'updated_at': None,
            'traffic': None,
            'node_count': None,
        }
        if type_ == 'subscription':
            url = (url or '').strip()
            if not url:
                return False, None, '订阅 URL 为空'
            prof['url'] = url
            if not prof['name']:
                prof['name'] = '订阅配置'
            try:
                text, userinfo, node_count = self._fetch_subscription(url)
            except requests.exceptions.RequestException as e:
                return False, None, f'订阅下载失败（网络错误）：{e}'
            except Exception as e:
                return False, None, f'订阅下载失败：{e}'
            os.makedirs(self._profiles_dir(), exist_ok=True)
            try:
                with open(self._profile_cache_path(prof['id']), 'w', encoding='utf-8') as f:
                    f.write(text)
            except OSError:
                logger.warning('缓存订阅 yaml 失败: %s', prof['id'], exc_info=True)
            prof['updated_at'] = int(time.time())
            prof['traffic'] = userinfo
            prof['node_count'] = node_count
        else:  # local
            if not prof['name']:
                return False, None, '本地配置需提供名称'
            if not (content or '').strip():
                return False, None, '配置内容为空'
            # [M26] 正文只落 profiles/<id>.yaml，JSON 不存 content（仅元数据）
            self._write_local_content(prof['id'], content)
            prof['node_count'] = self._count_nodes(content)
            prof['updated_at'] = int(time.time())

        profiles, active_id = self._get_profiles()
        profiles = list(profiles) + [prof]
        patch = {'profiles': profiles}
        if not active_id or self._find_profile(profiles, active_id) is None:
            patch['active_profile_id'] = prof['id']
            active_id = prof['id']
        config.set_proxy_config(patch)
        return True, self._public_profile(prof, active_id), '已添加'

    def refresh_profile(self, profile_id):
        """重抓订阅、更新缓存/traffic/updated_at/node_count。返回 (ok, profile_dict|None, msg)。"""
        profiles, active_id = self._get_profiles()
        prof = self._find_profile(profiles, profile_id)
        if prof is None:
            return False, None, '配置不存在'
        if prof.get('type') != 'subscription':
            return False, None, '仅订阅配置可刷新'
        try:
            text, userinfo, node_count = self._fetch_subscription(prof.get('url') or '')
        except requests.exceptions.RequestException as e:
            return False, None, f'订阅刷新失败（网络错误）：{e}'
        except Exception as e:
            return False, None, f'订阅刷新失败：{e}'
        os.makedirs(self._profiles_dir(), exist_ok=True)
        try:
            with open(self._profile_cache_path(prof['id']), 'w', encoding='utf-8') as f:
                f.write(text)
        except OSError:
            logger.warning('缓存订阅 yaml 失败: %s', prof['id'], exc_info=True)
        prof['updated_at'] = int(time.time())
        prof['traffic'] = userinfo
        prof['node_count'] = node_count
        config.set_proxy_config({'profiles': profiles})
        # 若刷新的是 active 且正在运行，热重载使新节点生效
        if prof['id'] == active_id and self.is_running():
            try:
                self.reload()
            except Exception:
                logger.warning('刷新后重载失败（忽略）', exc_info=True)
        return True, self._public_profile(prof, active_id), '已刷新'

    def select_profile(self, profile_id):
        """设 active_profile_id、重写配置、reload（运行中）或仅持久化（未运行）。返回 (ok, msg)。"""
        profiles, _ = self._get_profiles()
        prof = self._find_profile(profiles, profile_id)
        if prof is None:
            return False, '配置不存在'
        config.set_proxy_config({'active_profile_id': profile_id})
        if self.is_running():
            ok, msg = self.reload()
            return ok, msg
        try:
            self._write_config()
        except Exception as e:
            return False, f'生成配置失败：{e}'
        return True, '已切换'

    def delete_profile(self, profile_id):
        """删条目 + 删缓存文件；若删的是 active，则切到剩余第一个（无则置空）。返回 (ok, msg)。"""
        profiles, active_id = self._get_profiles()
        prof = self._find_profile(profiles, profile_id)
        if prof is None:
            return False, '配置不存在'
        new_profiles = [p for p in profiles if p.get('id') != profile_id]
        patch = {'profiles': new_profiles}
        new_active = active_id
        if active_id == profile_id:
            new_active = new_profiles[0]['id'] if new_profiles else ''
            patch['active_profile_id'] = new_active
        config.set_proxy_config(patch)
        # 删缓存文件
        try:
            cache = self._profile_cache_path(profile_id)
            if os.path.isfile(cache):
                os.remove(cache)
        except OSError:
            logger.warning('删除 profile 缓存失败: %s', profile_id, exc_info=True)
        # 若切换了 active 且运行中，重载使新 active 生效
        if active_id == profile_id and self.is_running() and new_active:
            try:
                self.reload()
            except Exception:
                logger.warning('删除后重载失败（忽略）', exc_info=True)
        return True, '已删除'

    def update_profile(self, profile_id, name=None, content=None):
        """编辑本地 profile 的名字/内容（仅 local 可改 content）。返回 (ok, profile_dict|None, msg)。"""
        profiles, active_id = self._get_profiles()
        prof = self._find_profile(profiles, profile_id)
        if prof is None:
            return False, None, '配置不存在'
        if name is not None:
            name = name.strip()
            if name:
                prof['name'] = name
        if content is not None:
            if prof.get('type') != 'local':
                return False, None, '仅本地配置可编辑内容'
            if not content.strip():
                return False, None, '配置内容为空'
            # [M26] 正文只落 profiles/<id>.yaml，JSON 不再内联 content（避免全量重写约 500KB）
            self._write_local_content(prof['id'], content)
            prof.pop('content', None)  # 清掉可能残留的旧内联正文
            prof['node_count'] = self._count_nodes(content)
            prof['updated_at'] = int(time.time())
        config.set_proxy_config({'profiles': profiles})
        # 若编辑的是 active 且运行中，重载使改动生效
        if prof['id'] == active_id and content is not None and self.is_running():
            try:
                self.reload()
            except Exception:
                logger.warning('编辑后重载失败（忽略）', exc_info=True)
        return True, self._public_profile(prof, active_id), '已更新'

    def get_profile_content(self, profile_id):
        """local 返回 content；subscription 返回缓存 yaml（缺失则尝试抓取）。"""
        profiles, _ = self._get_profiles()
        prof = self._find_profile(profiles, profile_id)
        if prof is None:
            return ''
        if prof.get('type') == 'local':
            # [M26] 正文从 profiles/<id>.yaml 读，回退内联 content（兼容未迁移旧数据）
            return self._read_local_content(prof)
        # subscription：优先缓存，缺失则抓取并落盘
        cache = self._profile_cache_path(profile_id)
        if os.path.isfile(cache):
            try:
                with open(cache, 'r', encoding='utf-8') as f:
                    return f.read()
            except OSError:
                pass
        try:
            text, userinfo, node_count = self._fetch_subscription(prof.get('url') or '')
        except Exception:
            logger.warning('按需抓取订阅 yaml 失败: %s', profile_id, exc_info=True)
            return ''
        os.makedirs(self._profiles_dir(), exist_ok=True)
        try:
            with open(cache, 'w', encoding='utf-8') as f:
                f.write(text)
        except OSError:
            pass
        # 顺手更新 traffic/node_count/updated_at
        prof['updated_at'] = int(time.time())
        prof['traffic'] = userinfo
        prof['node_count'] = node_count
        config.set_proxy_config({'profiles': profiles})
        return text

    # ------------------------------------------------------------------ 配置写入（供 web_server 调用；旧端点兼容）
    def set_subscription(self, url):
        """旧端点兼容：新增/复用一个订阅 profile 并设为 active。"""
        url = (url or '').strip()
        profiles, _ = self._get_profiles()
        # 若已有同 URL 的订阅 profile，则直接选中它，避免重复
        for p in profiles:
            if p.get('type') == 'subscription' and (p.get('url') or '') == url:
                config.set_proxy_config({'active_profile_id': p['id']})
                return
        ok, prof, _msg = self.add_profile('subscription', url=url)
        if ok and prof:
            config.set_proxy_config({'active_profile_id': prof['id']})

    def set_config_text(self, text):
        """旧端点兼容：新增一个本地 profile 并设为 active。"""
        ok, prof, _msg = self.add_profile('local', name='本地配置', content=text or '')
        if ok and prof:
            config.set_proxy_config({'active_profile_id': prof['id']})

    # ------------------------------------------------------------------ 内核下载
    _MIHOMO_VERSION = 'v1.19.25'  # 与 scripts/fetch-mihomo.ps1 默认版本保持一致

    def _core_asset(self):
        """按当前平台返回 (release 资源名, 解压后可执行名)。"""
        sysname = platform.system().lower()
        machine = platform.machine().lower()
        arch = 'arm64' if machine in ('arm64', 'aarch64') else 'amd64'
        ver = self._MIHOMO_VERSION
        if sysname == 'windows':
            return f'mihomo-windows-{arch}-compatible-{ver}.zip', 'mihomo.exe'
        if sysname == 'darwin':
            return f'mihomo-darwin-{arch}-{ver}.gz', 'mihomo'
        return f'mihomo-linux-{arch}-compatible-{ver}.gz', 'mihomo'

    def fetch_core(self, mirror=None):
        """下载 mihomo 内核到 bin/。返回 (ok, message)。同步阻塞。

        与 scripts/fetch-mihomo.ps1 等价的运行时版本（打包后 scripts/ 不随包，
        故用 requests 直接下载）。mirror 为 GitHub 加速前缀（拼在完整 URL 前），
        中国网络无代理时可用；requests 默认 trust_env，机器配了系统代理会自动走。
        """
        if self.binary_available():
            return True, '内核已存在'
        asset, _exe = self._core_asset()
        url = f'https://github.com/MetaCubeX/mihomo/releases/download/{self._MIHOMO_VERSION}/{asset}'
        if mirror:
            url = mirror.rstrip('/') + '/' + url
        os.makedirs(self._bin_dir(), exist_ok=True)
        dst = self.mihomo_path()
        tmp = dst + '.download'
        try:
            logger.info('下载 mihomo 内核: %s', url)
            with requests.get(url, stream=True, timeout=(10, 120)) as r:
                r.raise_for_status()
                if asset.endswith('.zip'):
                    tmp_zip = os.path.join(self._bin_dir(), 'mihomo_dl.zip')
                    with open(tmp_zip, 'wb') as f:
                        for chunk in r.iter_content(65536):
                            f.write(chunk)
                    try:
                        with zipfile.ZipFile(tmp_zip) as z:
                            member = next(
                                (n for n in z.namelist()
                                 if not n.endswith('/')
                                 and (n.lower().endswith('.exe') or os.path.basename(n).lower() == 'mihomo')),
                                None,
                            )
                            if not member:
                                raise RuntimeError('压缩包内未找到 mihomo 可执行文件')
                            with z.open(member) as src, open(tmp, 'wb') as out:
                                shutil.copyfileobj(src, out)
                    finally:
                        try:
                            os.remove(tmp_zip)
                        except OSError:
                            pass
                else:
                    import gzip
                    with gzip.GzipFile(fileobj=r.raw) as gz, open(tmp, 'wb') as out:
                        shutil.copyfileobj(gz, out)
            os.replace(tmp, dst)
            if os.name != 'nt':
                os.chmod(dst, 0o755)
            logger.info('mihomo 内核已就绪: %s', dst)
            return True, '内核下载完成'
        except Exception as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            logger.error('下载 mihomo 内核失败: %s', e, exc_info=True)
            msg = str(e)
            if isinstance(e, requests.exceptions.RequestException):
                msg = f'网络错误：{e}（中国网络可带 mirror 镜像前缀重试）'
            return False, f'内核下载失败：{msg}'
