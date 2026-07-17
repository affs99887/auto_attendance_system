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
    """安全解析整型环境变量：缺失/空串回退默认值，非法值告警后回退（避免 import 阶段崩溃）。

    底座工具：当前无调用方，定制新功能要读数值型环境变量时用它，别手写 int(os.getenv(...))。
    """
    v = os.getenv(name)
    if v is None or v.strip() == '':
        return default
    try:
        return int(v.strip())
    except ValueError:
        logging.warning(f"环境变量 {name}={v!r} 不是合法整数，使用默认值 {default}")
        return default


def _float_env(name, default):
    """安全解析浮点型环境变量：缺失/空串回退默认值，非法值告警后回退。

    底座工具：当前无调用方，用途同 _int_env。
    """
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

    # 看门狗配置
    WATCHDOG_MAX_RESTARTS = 5
    WATCHDOG_RESTART_INTERVAL = 3600  # 1小时

    # 文件路径配置
    LOGS_DIR = 'logs'

    # 动态配置文件路径
    DYNAMIC_CONFIG_FILE = 'dynamic_config.json'
    
    _dynamic_config = None
    # [M58/M64] dynamic_config.json 跨线程读改写保护：waitress HTTP 线程、asyncio 主循环、
    # 汇率 executor 线程都可能并发触发写入，必须串行化 _load/_save 与所有 set_*，
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

    # ========================================================================
    # 内置网络加速（mihomo）配置 —— 存于 dynamic_config.json 的 PROXY 子对象
    # 设计：专属私有回环端口（避开系统 Clash 默认 7890/7897），仅代理本程序，
    # 与系统 VPN/代理状态解耦。
    # ========================================================================
    PROXY_DEFAULTS = {
        'enabled': False,
        'local_port': 7899,          # mixed-port（http+socks5），本程序的境外请求走这里
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

    # get_local_proxy 探测结果短缓存：(结果, 失效时刻)。该函数在汇率等后台服务的
    # 每次请求路径上都被调用，TCP 探测最坏要 1 秒，5 秒内直接复用上次结果摊薄成本。
    # 多线程并发写最坏也只是多探测一次（结果一致），无需加锁。
    _local_proxy_cache = (None, 0.0)

    @classmethod
    def get_local_proxy(cls):
        """供 requests 类后台服务（汇率等周期拉取）使用的本地代理 dict，或 None（直连）。

        仅当内置加速已启用且本地端口"确实在监听"时才返回 {'http':url,'https':url}；端口无人监听
        （未启用 / mihomo 未就绪 / 已崩溃 / 确定性失败永远起不来）一律返回 None 走直连，避免把请求
        打到无人监听的回环端口而抛 ProxyError（[WinError 10061] 目标计算机积极拒绝）——这正是 mihomo
        不可用时这些周期拉取"全军覆没"的直接根因。用即时端口探测而非死等：它们是一次性周期拉取，
        端口不通时直连/回退旧缓存即可，下个周期 mihomo 复活后自然恢复。
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
    def ensure_directories(cls):
        """确保必要的目录存在"""
        os.makedirs(cls.LOGS_DIR, exist_ok=True)


# 全局配置实例
config = Config()
