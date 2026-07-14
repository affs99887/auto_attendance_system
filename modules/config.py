"""
配置管理模块

集中管理系统配置、环境变量和常量定义
"""

import os
import json
import socket
import secrets
import logging
import threading
import time
from dotenv import load_dotenv

# 配置属于稳定数据根，不属于可替换的 OTA 代码目录。Electron 壳显式传 AAS_DATA_DIR；
# 源码/看门狗模式回退 cwd，二者都确保读取用户实际维护的 .env，而不是按 config.py 所在目录向上找。
_data_dir = os.environ.get('AAS_DATA_DIR') or os.getcwd()
load_dotenv(os.path.join(_data_dir, '.env'))


def _int_env(name, default):
    """安全解析整型环境变量：缺失/空串回退默认值，非法值告警后回退（避免 import 阶段崩溃）。"""
    v = os.getenv(name)
    if v is None or v.strip() == '':
        return default
    try:
        return int(v.strip())
    except ValueError:
        logging.warning(f"环境变量 {name}={v!r} 不是合法整数，使用默认值 {default}")
        return default


def _float_env(name, default):
    """安全解析浮点型环境变量：缺失/空串回退默认值，非法值告警后回退。"""
    v = os.getenv(name)
    if v is None or v.strip() == '':
        return default
    try:
        return float(v.strip())
    except ValueError:
        logging.warning(f"环境变量 {name}={v!r} 不是合法数字，使用默认值 {default}")
        return default


class Config:
    """配置管理类"""

    # 登录配置
    LOGIN_USERNAME = os.getenv('LOGIN_USERNAME')
    LOGIN_PASSWORD = os.getenv('LOGIN_PASSWORD')
    LOGIN_USERNAME2 = os.getenv('LOGIN_USERNAME2')
    LOGIN_PASSWORD2 = os.getenv('LOGIN_PASSWORD2')
    LOGIN_URL = os.getenv('LOGIN_URL')

    # Telegram配置
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

    # 邮件配置
    EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
    EMAIL_SMTP_SERVER = os.getenv('EMAIL_SMTP_SERVER', 'smtp.qq.com')
    EMAIL_SMTP_PORT = _int_env('EMAIL_SMTP_PORT', 465)
    EMAIL_RECIPIENTS = os.getenv('EMAIL_RECIPIENTS', '').split(',') if os.getenv('EMAIL_RECIPIENTS') else []

    # Tesseract配置
    TESSERACT_PATH = os.getenv('TESSERACT_PATH', r'C:\Program Files\Tesseract-OCR\tesseract.exe')

    # 工作时间配置
    WORK_START_TIME = os.getenv('WORK_START_TIME', "09:00")
    WORK_END_TIME = os.getenv('WORK_END_TIME', "17:30")
    LATE_THRESHOLD = _int_env('LATE_THRESHOLD', 15)  # 分钟
    EARLY_LEAVE_THRESHOLD = _int_env('EARLY_LEAVE_THRESHOLD', 15)  # 分钟
    DAILY_STATUS_TIME = os.getenv('DAILY_STATUS_TIME', "08:20")

    # 系统配置
    MAX_RETRIES = 3
    RETRY_INTERVAL = 5  # 秒
    HEARTBEAT_INTERVAL = 300  # 5分钟
    MAX_HEARTBEAT_MISS = 3
    ERROR_RESET_INTERVAL = 3600  # 1小时
    MAX_ERRORS = 5

    # 看门狗配置
    WATCHDOG_MAX_RESTARTS = 5
    WATCHDOG_RESTART_INTERVAL = 3600  # 1小时

    # 文件路径配置
    LOGS_DIR = 'logs'
    PUNCH_RECORDS_DIR = 'punch_records'
    SCREENSHOTS_DIR = 'screenshots'
    TEMPLATES_DIR = 'templates'

    # 模板文件路径
    SAFE_PLACE_PATH = 'templates/safe_place.png'
    SAFE_PLACE_PATH2 = 'templates/safe_place2.png'
    USERNAME_FIELD_PATH = 'templates/username_field.png'
    PASSWORD_FIELD_PATH = 'templates/password_field.png'
    LOGIN_BUTTON_PATH = 'templates/login_button.png'
    PUNCH_BUTTON_PATH = 'templates/punch_button.png'


    # Telegram连接配置
    CONNECTION_POOL_SIZE = 20
    CONNECTION_TIMEOUT = 20
    POOL_TIMEOUT = 20
    READ_TIMEOUT = 20
    WRITE_TIMEOUT = 20
    UPDATE_TIMEOUT = 600  # 10分钟
    MAX_CONNECTION_ERRORS = 10

    # Telegram代理配置（按顺序探测，第一个可连通的端口被采用；都不通则直连）
    TELEGRAM_PROXY_HOST = os.getenv('TELEGRAM_PROXY_HOST', '127.0.0.1')
    TELEGRAM_PROXY_PORTS = [
        int(p.strip()) for p in os.getenv('TELEGRAM_PROXY_PORTS', '7897,7890').split(',')
        if p.strip().isdigit()
    ]
    TELEGRAM_PROXY_SCHEME = os.getenv('TELEGRAM_PROXY_SCHEME', 'http')
    TELEGRAM_PROXY_PROBE_TIMEOUT = _float_env('TELEGRAM_PROXY_PROBE_TIMEOUT', 1.0)

    # 图像识别配置
    MATCH_THRESHOLD = 0.8
    OCR_CONFIG = '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789:'
    
    # 动态配置文件路径
    DYNAMIC_CONFIG_FILE = 'dynamic_config.json'
    
    # Selenium配置 - 支持动态配置
    _dynamic_config = None
    # [M58/M64] dynamic_config.json 跨线程读改写保护：waitress HTTP 线程、asyncio 主循环、
    # 汇率/AI 资讯 executor 线程都可能并发触发写入，必须串行化 _load/_save 与所有 set_*，
    # 避免两线程同时 json.dump 同一文件或迭代字典时被改而产出截断/残破 JSON。
    _config_lock = threading.RLock()

    @classmethod
    def _load_dynamic_config(cls):
        """加载动态配置"""
        with cls._config_lock:
            if cls._dynamic_config is None:
                if os.path.exists(cls.DYNAMIC_CONFIG_FILE):
                    try:
                        with open(cls.DYNAMIC_CONFIG_FILE, 'r', encoding='utf-8') as f:
                            cls._dynamic_config = json.load(f)
                    except Exception as e:
                        # [M58/M64] 解析失败时把损坏文件改名留档（.corrupt-时间戳），便于人工恢复 secret /
                        # 代理 profiles；不静默丢弃后让后续 set_* 用空配置覆盖掉可手工修复的原文件。
                        print(f"加载动态配置失败: {e}")
                        try:
                            backup = f"{cls.DYNAMIC_CONFIG_FILE}.corrupt-{int(time.time())}"
                            os.replace(cls.DYNAMIC_CONFIG_FILE, backup)
                            logging.warning(f"动态配置损坏，已备份为 {backup}")
                        except Exception as be:
                            print(f"备份损坏动态配置失败: {be}")
                        cls._dynamic_config = {}
                else:
                    cls._dynamic_config = {}
            return cls._dynamic_config

    @classmethod
    def _save_dynamic_config(cls):
        """保存动态配置（先写临时文件再 os.replace 原子替换，避免写入中途崩溃留下截断 JSON）"""
        with cls._config_lock:
            try:
                tmp_path = f"{cls.DYNAMIC_CONFIG_FILE}.tmp"
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(cls._dynamic_config, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, cls.DYNAMIC_CONFIG_FILE)
            except Exception as e:
                print(f"保存动态配置失败: {e}")

    @classmethod
    def get_selenium_config(cls, key, default_value):
        """获取Selenium配置，优先使用动态配置"""
        dynamic_config = cls._load_dynamic_config()
        if key in dynamic_config:
            return dynamic_config[key]
        # 回退到环境变量
        env_value = os.getenv(key, str(default_value)).lower()
        return env_value == 'true' if isinstance(default_value, bool) else env_value

    @classmethod
    def set_selenium_config(cls, key, value):
        """设置Selenium配置"""
        with cls._config_lock:
            dynamic_config = cls._load_dynamic_config()
            dynamic_config[key] = value
            cls._save_dynamic_config()
    
    @classmethod
    def get_use_selenium_login(cls):
        """是否使用Selenium登录"""
        return cls.get_selenium_config('USE_SELENIUM_LOGIN', False)
    
    @classmethod
    def get_selenium_headless(cls):
        """是否使用无头模式"""
        return cls.get_selenium_config('SELENIUM_HEADLESS', False)

    # ========================================================================
    # 内置网络加速（mihomo）配置 —— 存于 dynamic_config.json 的 PROXY 子对象
    # 设计：专属私有回环端口（避开系统 Clash 默认 7890/7897），仅代理本程序，
    # 与系统 VPN/代理状态解耦。
    # ========================================================================
    PROXY_DEFAULTS = {
        'enabled': False,
        'local_port': 7899,          # mixed-port（http+socks5），本程序 Telegram 走这里
        'api_port': 9899,            # mihomo external-controller（本地 RESTful API）
        'secret': '',                # external-controller 鉴权（首次随机生成并持久化）
        'source': 'subscription',    # 'subscription' | 'config'（旧字段，仅用于迁移）
        'subscription_url': '',      # 旧字段，仅用于迁移
        'selected_node': '',
        'group': 'AAS-Proxy',        # select 分组名（供 GUI 切换节点）
        'profiles': [],              # 多配置文件列表（见 _migrate_proxy_profiles 注释）
        'active_profile_id': '',     # 当前激活的 profile id
    }

    @classmethod
    def _migrate_proxy_profiles(cls, cfg):
        """向后兼容：profiles 为空但旧字段有值时，迁移成 1 个 profile 并设为 active。

        每个 profile = {
            'id': str,                # secrets.token_hex(4) 生成的稳定短 id
            'name': str,              # 展示名
            'type': 'subscription' | 'local',
            'url': str,               # 订阅 URL；local 为 ''
            'content': str,           # local 配置原文（持久化，跨重装不丢）；subscription 为 ''
            'updated_at': int|None,   # 最近抓取/导入的 epoch 秒
            'traffic': {...}|None,    # 仅订阅，来自 subscription-userinfo 头
            'node_count': int|None,
        }
        返回 (cfg, changed)；changed 为 True 表示需要持久化。
        """
        profiles = cfg.get('profiles')
        if isinstance(profiles, list) and profiles:
            return cfg, False  # 已有 profiles，无需迁移

        source = cfg.get('source', 'subscription')
        sub_url = (cfg.get('subscription_url') or '').strip()
        prof = None
        if source == 'subscription' and sub_url:
            prof = {
                'id': secrets.token_hex(4),
                'name': '订阅配置',
                'type': 'subscription',
                'url': sub_url,
                'content': '',
                'updated_at': None,
                'traffic': None,
                'node_count': None,
            }
        elif source == 'config':
            # 旧的粘贴配置原文存于 proxy_runtime/source_config.yaml，读出落入 content
            content = ''
            try:
                src_path = os.path.join('proxy_runtime', 'source_config.yaml')
                if os.path.isfile(src_path):
                    with open(src_path, 'r', encoding='utf-8') as f:
                        content = f.read()
            except Exception as e:
                print(f"迁移本地代理配置原文失败: {e}")
            if content.strip():
                prof = {
                    'id': secrets.token_hex(4),
                    'name': '本地配置',
                    'type': 'local',
                    'url': '',
                    'content': content,
                    'updated_at': None,
                    'traffic': None,
                    'node_count': None,
                }

        if prof is None:
            return cfg, False
        cfg['profiles'] = [prof]
        cfg['active_profile_id'] = prof['id']
        return cfg, True

    @classmethod
    def get_proxy_config(cls):
        """获取内置加速配置（补默认值；secret 缺失则生成并持久化；首次迁移旧字段为 profiles）。"""
        # [M64] 整段读改写加锁：避免首次并发调用时两线程各自生成不同 secret、后写者覆盖。
        with cls._config_lock:
            dynamic = cls._load_dynamic_config()
            cfg = dict(cls.PROXY_DEFAULTS)
            stored = dynamic.get('PROXY')
            if isinstance(stored, dict):
                cfg.update(stored)
            patch = {}
            if not cfg.get('secret'):
                cfg['secret'] = secrets.token_hex(16)
                patch['secret'] = cfg['secret']
            cfg, migrated = cls._migrate_proxy_profiles(cfg)
            if migrated:
                patch['profiles'] = cfg['profiles']
                patch['active_profile_id'] = cfg['active_profile_id']
            if patch:
                cls.set_proxy_config(patch)
            return cfg

    @classmethod
    def set_proxy_config(cls, patch):
        """合并更新 PROXY 子对象并持久化，返回最新配置。"""
        if not isinstance(patch, dict):
            return cls.get_proxy_config()
        # [M58/M64] 读-改-写串行化，防止并发 cur.update 与 json.dump 撕裂文件。
        with cls._config_lock:
            dynamic = cls._load_dynamic_config()
            cur = dynamic.get('PROXY')
            if not isinstance(cur, dict):
                cur = {}
            cur.update(patch)
            dynamic['PROXY'] = cur
            cls._save_dynamic_config()
            # 代理配置变了（启停/换端口）就作废探测缓存，避免开关后最长 5 秒仍按旧结果走
            cls._local_proxy_cache = (None, 0.0)
            return cls.get_proxy_config()

    @classmethod
    def get_proxy_enabled(cls):
        return bool(cls.get_proxy_config().get('enabled', False))

    @classmethod
    def get_proxy_local_port(cls):
        try:
            return int(cls.get_proxy_config().get('local_port', 7899))
        except (TypeError, ValueError):
            return 7899

    @classmethod
    def get_proxy_api_port(cls):
        try:
            return int(cls.get_proxy_config().get('api_port', 9899))
        except (TypeError, ValueError):
            return 9899

    @classmethod
    def _mihomo_binary_missing(cls):
        """检测 mihomo 二进制是否缺失（确定性失败信号）。

        [M60] 二进制不存在属"重试多少次都不会好"的确定性失败——此时 mihomo 永远不会就绪，
        若 get_telegram_proxy 仍返回内置死端口，Telegram 全链路会永久不可用。这里只做纯文件
        存在性判断（无副作用），不导入/实例化 ProxyManager（其 __init__ 有迁移副作用，且会引入
        与 modules.proxy_manager 的循环导入）。路径派生与 ProxyManager._bin_dir() 严格一致：
        优先 AAS_BIN_DIR（瘦壳方案下壳子指向其固定 bin），未设时回退 <project_root>/bin（二者同在
        modules/ 下故 __file__ 推导出的根目录相同）。两处必须同口径，否则误判二进制缺失会错误触发回退。
        """
        try:
            env_bin = os.environ.get('AAS_BIN_DIR')
            bin_dir = env_bin if env_bin else os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bin')
            name = 'mihomo.exe' if os.name == 'nt' else 'mihomo'
            return not os.path.isfile(os.path.join(bin_dir, name))
        except Exception:
            # 探测自身异常时保守认为"未缺失"，沿用原有"等待 mihomo 启动"的行为，避免误回退。
            return False

    @classmethod
    def _active_local_profile_content(cls, cfg):
        """返回当前激活 local profile 的正文（str），非 local / 无激活 profile 时返回 None（无副作用）。

        [M60] 判定口径与 ProxyManager._get_active_profile / _read_local_content 严格一致：
        - active profile = 按 active_profile_id 查找，失效则兜底取 profiles[0]；
        - local 正文优先读 proxy_runtime/profiles/<id>.yaml，缺失则回退内联 content（兼容未迁移旧数据）。
        proxy_runtime 属可写用户数据，路径以 cwd（运行时工作目录/数据根）为基准，与
        ProxyManager.runtime_dir(os.getcwd()+/proxy_runtime) 及 dynamic_config.json 同根——
        打包后 cwd=DATA_DIR，不能用 __file__（会落到只读的 resources/backend，profiles/ 为空导致误判）。
        仅做纯文件读取，不导入/实例化 ProxyManager，避免迁移副作用与循环导入。
        """
        profiles = cfg.get('profiles')
        if not (isinstance(profiles, list) and profiles):
            return None
        active_id = cfg.get('active_profile_id') or ''
        prof = next((p for p in profiles if isinstance(p, dict) and p.get('id') == active_id), None)
        if prof is None:
            prof = profiles[0] if isinstance(profiles[0], dict) else None
        if prof is None or prof.get('type') != 'local':
            return None
        pid = prof.get('id')
        if pid:
            cache = os.path.join(os.getcwd(), 'proxy_runtime', 'profiles', f'{pid}.yaml')
            if os.path.isfile(cache):
                try:
                    with open(cache, 'r', encoding='utf-8') as f:
                        return f.read()
                except OSError:
                    # 读缓存失败时回退内联 content，与 _read_local_content 行为一致。
                    pass
        return prof.get('content') or ''

    @classmethod
    def _proxy_deterministic_failure(cls):
        """检测内置加速是否处于"重试多少次都不会就绪"的确定性失败，返回原因字符串或 None（无副作用）。

        [M60] 仅靠 _mihomo_binary_missing 不够：审计指出除二进制缺失外，"active profile 配置损坏 /
        根本没有配置任何 profile"同样是确定性失败——ProxyManager.start() 会在 _write_config 抛
        "尚未配置任何代理订阅/配置文件"或在 _build_config_from_text 抛 YAML 解析错误而永远启动
        不了 mihomo。此时若 get_telegram_proxy 仍返回内置死端口，Telegram 全链路（打卡通知 /
        远程控制 / 状态上报）会永久失效。故把这类无法靠等待恢复的情形统一识别出来，让
        get_telegram_proxy 回退系统代理探测/直连。

        这里只读自身配置（profiles 列表 + 激活 local profile 正文），不导入/实例化 ProxyManager
        （其 __init__ 有迁移副作用且会引入循环导入），判定口径与 ProxyManager._get_active_profile/
        _write_config/_build_config_from_text 保持一致：
        - profiles 为空 → _write_config 必抛"尚未配置..."；
        - 激活的是 local profile 且正文空白/YAML 不可解析/根节点非映射 → _build_config_from_text 必抛。
        订阅 profile 的 URL 是否可达需联网才知（瞬时网络问题非确定性失败），故不在此判定；端口被占
        等情形也无法在不连接的前提下无副作用地判定，均交由进程响应/Telegram 有限次重试兜底，不误判。
        """
        if cls._mihomo_binary_missing():
            return 'mihomo 二进制缺失（bin/ 未打包）'
        try:
            cfg = cls.get_proxy_config()
            profiles = cfg.get('profiles')
            if not (isinstance(profiles, list) and profiles):
                return '未配置任何代理订阅/配置文件'
            # 激活的是 local profile 时，提前校验其正文能否被 mihomo 解析——
            # 空白 / YAML 语法错误 / 根节点非映射都会让 _build_config_from_text 永久失败。
            content = cls._active_local_profile_content(cfg)
            if content is not None:
                if not content.strip():
                    return '激活的本地代理配置为空'
                try:
                    import yaml  # 懒导入：与 _build_config_from_text 一致，仅 local 模式需要
                except ImportError:
                    # 无 PyYAML 同样使 _build_config_from_text 直接抛错而永远启动不了。
                    return '解析本地代理配置需要 PyYAML（未安装）'
                try:
                    data = yaml.safe_load(content)
                except Exception:
                    return '激活的本地代理配置 YAML 解析失败（已损坏）'
                if not isinstance(data, dict):
                    return '激活的本地代理配置根节点不是映射（已损坏）'
        except Exception:
            # 读配置自身异常时保守认为"非确定性失败"，沿用原有"等待 mihomo 启动"行为，避免误回退。
            return None
        return None

    @classmethod
    def get_telegram_proxy(cls):
        """返回 Telegram 使用的代理 URL。

        - 启用内置加速：默认直连本程序自管理的 mihomo 本地端口，完全不依赖系统代理。
          端口暂未就绪时仍返回内置 URL（由 Telegram 初始化的有限次重试等待 mihomo 启动完成），
          不回退到系统 Clash/VPN 端口（7897 等）——避免误用与本程序无关的系统代理。
          [M60] 例外：当检测到确定性失败（mihomo 二进制缺失、或未配置任何 profile 导致 start() 必失败）
          时，mihomo 永远无法就绪，继续返回内置死端口会让打卡通知/远程控制/状态上报永久失效，故此时
          回退到下方系统代理探测路径（探测不到再走直连），而非死等。
        - 未启用：按顺序探测 TELEGRAM_PROXY_PORTS（系统 Clash 等），返回首个可连通的；都不通则 None。
        """
        _det_fail = cls._proxy_deterministic_failure() if cls.get_proxy_enabled() else None
        if cls.get_proxy_enabled() and _det_fail is None:
            port = cls.get_proxy_local_port()
            url = f"http://127.0.0.1:{port}"
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=1.0):
                    pass
                logging.info(f"使用内置网络加速代理: {url}")
            except (OSError, socket.timeout):
                logging.warning(
                    f"内置加速端口 127.0.0.1:{port} 未就绪，等待 mihomo 启动（不回退系统代理）"
                )
            return url
        # [M60] 启用了内置加速但属确定性失败（二进制缺失 / 未配置 profile）：落入此分支，
        # 回退系统代理探测/直连，以免 Telegram 永久指向无人监听的回环端口。
        if cls.get_proxy_enabled():
            logging.warning(
                f"已启用内置网络加速但无法就绪（{_det_fail}），回退系统代理探测/直连，"
                "请检查 bin/ 是否已打包、是否已添加代理配置，或在 GUI 关闭内置加速开关"
            )
        host = cls.TELEGRAM_PROXY_HOST
        scheme = cls.TELEGRAM_PROXY_SCHEME
        timeout = cls.TELEGRAM_PROXY_PROBE_TIMEOUT
        for port in cls.TELEGRAM_PROXY_PORTS:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    proxy_url = f"{scheme}://{host}:{port}"
                    logging.info(f"Telegram代理探测成功，使用: {proxy_url}")
                    return proxy_url
            except (OSError, socket.timeout):
                continue
        logging.warning(
            f"Telegram代理探测失败（已尝试端口 {cls.TELEGRAM_PROXY_PORTS}），将走直连"
        )
        return None

    # get_local_proxy 探测结果短缓存：(结果, 失效时刻)。该函数在汇率/AI资讯/Claude额度的
    # 每次请求路径上都被调用，TCP 探测最坏要 1 秒，5 秒内直接复用上次结果摊薄成本。
    # 多线程并发写最坏也只是多探测一次（结果一致），无需加锁。
    _local_proxy_cache = (None, 0.0)

    @classmethod
    def get_local_proxy(cls):
        """供 requests 类后台服务（汇率/AI资讯/Claude额度）使用的本地代理 dict，或 None（直连）。

        仅当内置加速已启用且本地端口"确实在监听"时才返回 {'http':url,'https':url}；端口无人监听
        （未启用 / mihomo 未就绪 / 已崩溃 / 确定性失败永远起不来）一律返回 None 走直连，避免把请求
        打到无人监听的回环端口而抛 ProxyError（[WinError 10061] 目标计算机积极拒绝）——这正是 mihomo
        不可用时这些周期拉取"全军覆没"的直接根因。与 get_telegram_proxy 的回退理念一致；区别是这里用
        即时端口探测而非死等：它们是一次性周期拉取，端口不通时直连/回退旧缓存即可，下个周期 mihomo
        复活后自然恢复，无需像 Telegram 长连接那样等待。
        探测结果缓存 5 秒（见 _local_proxy_cache），代理刚启停最坏 5 秒后才被感知，可接受。
        """
        now = time.time()
        cached_value, cached_until = cls._local_proxy_cache
        if now < cached_until:
            return cached_value
        result = None
        try:
            if cls.get_proxy_enabled():
                port = cls.get_proxy_local_port()
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=1.0):
                        url = f"http://127.0.0.1:{port}"
                        result = {'http': url, 'https': url}
                except (OSError, socket.timeout):
                    result = None
        except Exception:
            logging.warning('判断本地代理状态异常，转为直连', exc_info=True)
            result = None
        cls._local_proxy_cache = (result, now + 5.0)
        return result

    @classmethod
    def get_user_configs(cls):
        """获取多用户配置"""
        users = [
            {
                'username': cls.LOGIN_USERNAME,
                'password': cls.LOGIN_PASSWORD,
                'punch_records': {
                    'punch_in_time': None,
                    'punch_out_time': None
                }
            }
        ]
        # 第二用户（邓蕴哲，2026-06 离职后已在 .env 注释）：仅当用户名/密码都配置时才纳入，
        # 避免注释后产生 username=None 的脏条目，导致并行打卡误判、Telegram /check 等命令崩溃。
        if cls.LOGIN_USERNAME2 and cls.LOGIN_PASSWORD2:
            users.append({
                'username': cls.LOGIN_USERNAME2,
                'password': cls.LOGIN_PASSWORD2,
                'punch_records': {
                    'punch_in_time': None,
                    'punch_out_time': None
                }
            })
        return users

    @classmethod
    def ensure_directories(cls):
        """确保必要的目录存在"""
        directories = [
            cls.LOGS_DIR,
            cls.PUNCH_RECORDS_DIR,
            cls.SCREENSHOTS_DIR,
            cls.TEMPLATES_DIR
        ]

        for directory in directories:
            os.makedirs(directory, exist_ok=True)


# 全局配置实例
config = Config()
