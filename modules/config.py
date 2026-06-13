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

# 加载环境变量
load_dotenv()


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
        与 modules.proxy_manager 的循环导入）。路径派生与 ProxyManager.mihomo_path() 保持一致：
        <project_root>/bin/mihomo(.exe)，二者同在 modules/ 下故 __file__ 推导出的根目录相同。
        """
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            name = 'mihomo.exe' if os.name == 'nt' else 'mihomo'
            return not os.path.isfile(os.path.join(project_root, 'bin', name))
        except Exception:
            # 探测自身异常时保守认为"未缺失"，沿用原有"等待 mihomo 启动"的行为，避免误回退。
            return False

    @classmethod
    def get_telegram_proxy(cls):
        """返回 Telegram 使用的代理 URL。

        - 启用内置加速：默认直连本程序自管理的 mihomo 本地端口，完全不依赖系统代理。
          端口暂未就绪时仍返回内置 URL（由 Telegram 初始化的有限次重试等待 mihomo 启动完成），
          不回退到系统 Clash/VPN 端口（7897 等）——避免误用与本程序无关的系统代理。
          [M60] 例外：当检测到确定性失败（mihomo 二进制缺失）时，mihomo 永远无法就绪，
          继续返回内置死端口会让打卡通知/远程控制/状态上报永久失效，故此时回退到下方
          系统代理探测路径（探测不到再走直连），而非死等。
        - 未启用：按顺序探测 TELEGRAM_PROXY_PORTS（系统 Clash 等），返回首个可连通的；都不通则 None。
        """
        if cls.get_proxy_enabled() and not cls._mihomo_binary_missing():
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
        # [M60] 启用了内置加速但二进制缺失（确定性失败）：落入此分支，回退系统代理探测/直连，
        # 以免 Telegram 永久指向无人监听的回环端口。
        if cls.get_proxy_enabled():
            logging.warning(
                "已启用内置网络加速但未找到 mihomo 二进制（bin/ 缺失），"
                "回退系统代理探测/直连，请检查 bin/ 是否已打包或在 GUI 关闭内置加速开关"
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
