"""
微信 Bark 转发服务 — 包装 wechat_bark_listener 监听核心，提供 GUI 需要的全部操作。

职责（对应原独立应用里 Electron 主进程做的事）：
- 配置管理：wechat_bark_config.json（程序运行根目录，与 dynamic_config.json 同根），
  读取时与默认值深合并，保存前做字段清洗与校验；
- 监听生命周期：后台线程跑 run_listener（stop_event 控制停止），启动前校验 device_key；
- 运行日志：最近 600 行环形缓冲（带时间戳），供状态接口返回、变化时经事件总线推 GUI；
- 一次性操作：测试 Bark 推送、检查当前转发时段判定、列出通知中心里的应用来源。

线程模型：所有方法都是同步实现，直接在 waitress 的 HTTP 线程里调用即可；
监听线程独立运行，与 GUI 只通过事件总线交互（频道 wechat_bark:status / wechat_bark:log）。
监听本身只在 macOS 生效（读 macOS 通知中心数据库）；其它平台可以正常改配置/看界面，
启动监听会返回明确的平台提示。
"""

import os
import sys
import json
import copy
import logging
import re
import threading
from collections import deque
from datetime import datetime
from types import SimpleNamespace

from modules.wechat_bark_listener import (
    DEFAULT_CONFIG,
    BarkClient,
    NotificationStore,
    SchedulePolicy,
    deep_merge,
    normalize_legacy_config,
    run_listener,
)

CONFIG_FILE = 'wechat_bark_config.json'
_LISTENER_THREAD_NAME = 'wechat-bark-listener'

# 监听核心的 DEFAULT_CONFIG 没有 desktop 段（那是桌面壳的行为开关），这里补上
_SERVICE_DEFAULTS = deep_merge(DEFAULT_CONFIG, {
    'desktop': {
        'auto_start_listener': True,
        'launch_at_login': False,
    },
})


# ----------------------------------------------------------------------------
# 配置清洗（保存前调用；校验失败抛 ValueError，错误文案直接展示给用户）
# ----------------------------------------------------------------------------

def _clean_string_list(value):
    """把 '一行一条' 的字符串或列表统一成去空白后的字符串列表。"""
    if isinstance(value, str):
        items = value.splitlines()
    elif isinstance(value, list):
        items = value
    else:
        items = []
    return [str(item).strip() for item in items if str(item).strip()]


def _number_or(value, fallback):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return fallback
    return n if n == n else fallback  # NaN 回退


def _normalize_clock(value, fallback_hour, label, allow_24=False):
    """校验 HH:MM 并补零；allow_24 允许 24:00 作为'到当天结束'。"""
    fallback = f'{int(fallback_hour):02d}:00'
    text = str(value or fallback).strip()
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', text)
    if not match:
        raise ValueError(f'{label}格式应为 HH:MM')
    hour, minute = int(match.group(1)), int(match.group(2))
    valid_hour = 0 <= hour <= 23
    valid_midnight_end = allow_24 and hour == 24 and minute == 0
    if (not valid_hour and not valid_midnight_end) or not (0 <= minute <= 59):
        raise ValueError(f'{label}不是有效时间')
    return f'{hour:02d}:{minute:02d}'


def _clock_minutes(value):
    hour, minute = value.split(':')
    return int(hour) * 60 + int(minute)


def sanitize_config(config):
    """字段级清洗：类型归一、默认值兜底、时间窗校验。未知字段原样保留。"""
    result = deep_merge({}, copy.deepcopy(config or {}))

    bark = result.setdefault('bark', {})
    bark['server'] = str(bark.get('server') or 'https://api.day.app').strip()
    bark['device_key'] = str(bark.get('device_key') or '').strip()
    bark['group'] = str(bark.get('group') or '').strip()
    bark['sound'] = str(bark.get('sound') or '')
    bark['level'] = str(bark.get('level') or 'active')
    bark['url'] = str(bark.get('url') or '')
    bark['icon'] = str(bark.get('icon') or '')
    bark['use_post'] = bark.get('use_post') is not False

    wechat = result.setdefault('wechat', {})
    wechat['bundle_ids'] = _clean_string_list(wechat.get('bundle_ids'))
    wechat['title_prefix'] = str(wechat.get('title_prefix') or '').strip()
    wechat['show_sender_in_body'] = bool(wechat.get('show_sender_in_body'))
    wechat['sender_label'] = str(wechat.get('sender_label') or '发送人').strip()
    wechat['ignore_title_patterns'] = _clean_string_list(wechat.get('ignore_title_patterns'))
    wechat['ignore_body_patterns'] = _clean_string_list(wechat.get('ignore_body_patterns'))

    listener = result.setdefault('listener', {})
    listener['poll_interval_seconds'] = max(0.5, _number_or(listener.get('poll_interval_seconds'), 2))
    listener['send_existing_on_start'] = bool(listener.get('send_existing_on_start'))
    listener['state_file'] = str(listener.get('state_file') or '~/.wechat-bark-listener/state.json')
    listener['db_path'] = str(listener.get('db_path') or '')
    listener['max_body_chars'] = max(1, int(_number_or(listener.get('max_body_chars'), 800)))

    desktop = result.setdefault('desktop', {})
    desktop['auto_start_listener'] = desktop.get('auto_start_listener') is not False
    desktop['launch_at_login'] = bool(desktop.get('launch_at_login'))

    schedule = result.setdefault('schedule', {})
    schedule['enabled'] = schedule.get('enabled') is not False
    schedule['timezone'] = str(schedule.get('timezone') or 'Asia/Shanghai').strip()
    schedule['start_time'] = _normalize_clock(schedule.get('start_time'), 7, '开始时间')
    schedule['end_time'] = _normalize_clock(schedule.get('end_time'), 12, '结束时间', allow_24=True)
    if _clock_minutes(schedule['start_time']) >= _clock_minutes(schedule['end_time']):
        raise ValueError('开始时间必须早于结束时间')
    schedule.pop('start_hour', None)
    schedule.pop('end_hour', None)
    schedule['weekends_are_holidays'] = schedule.get('weekends_are_holidays') is not False
    schedule['holiday_source_urls'] = _clean_string_list(schedule.get('holiday_source_urls'))
    schedule['holiday_cache_dir'] = str(schedule.get('holiday_cache_dir') or '~/.wechat-bark-listener/holidays')
    schedule['holiday_cache_ttl_hours'] = max(1, _number_or(schedule.get('holiday_cache_ttl_hours'), 168))
    schedule['allow_on_holiday_fetch_error'] = bool(schedule.get('allow_on_holiday_fetch_error'))

    return result


class _ListenerLogHandler(logging.Handler):
    """把监听线程里的 logging 输出抓进服务日志环（按线程名过滤，不影响其它日志）。"""

    def __init__(self, service):
        super().__init__(level=logging.INFO)
        self._service = service

    def emit(self, record):
        if record.threadName != _LISTENER_THREAD_NAME:
            return
        try:
            self._service._add_log(record.getMessage())
        except Exception:
            pass


class WechatBarkService:
    """微信 Bark 转发的后端服务单例（挂在 app_core.wechat_bark 上）。"""

    def __init__(self):
        # GUI 事件总线，web_server.start() 启动后注入；未注入时只是不推送，不影响功能
        self._event_bus = None
        self._logs = deque(maxlen=600)
        self._state_lock = threading.RLock()
        self._config_lock = threading.RLock()
        self._thread = None
        self._stop_event = threading.Event()
        self._stopping = False

    # ------------------------------------------------------------------ 事件总线
    def attach_event_bus(self, event_bus):
        self._event_bus = event_bus

    # ------------------------------------------------------------------ 配置
    def config_path(self):
        return os.path.abspath(CONFIG_FILE)

    def load_config(self):
        """读配置文件并与默认值深合并；文件缺失/损坏时按默认值走（损坏只告警不覆盖原文件）。"""
        with self._config_lock:
            user_config = {}
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        user_config = loaded
                except Exception:
                    logging.exception('[微信Bark] 读取配置失败，按默认配置处理')
            merged = deep_merge(_SERVICE_DEFAULTS, normalize_legacy_config(user_config))
            return sanitize_config(merged)

    def save_config(self, config):
        """清洗校验后原子写入；校验失败抛 ValueError（文案直接给前端展示）。"""
        sanitized = sanitize_config(config)
        with self._config_lock:
            tmp_path = CONFIG_FILE + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(sanitized, f, ensure_ascii=False, indent=2)
                f.write('\n')
            os.replace(tmp_path, CONFIG_FILE)
        self._publish_status()
        return sanitized

    # ------------------------------------------------------------------ 日志环
    def _add_log(self, text):
        lines = [line.rstrip() for line in str(text or '').splitlines() if line.strip()]
        if not lines:
            return
        stamped = [f"{datetime.now().strftime('%H:%M:%S')} {line}" for line in lines]
        with self._state_lock:
            self._logs.extend(stamped)
        bus = self._event_bus
        if bus is not None:
            bus.publish_threadsafe('wechat_bark:log', {'lines': stamped})

    # ------------------------------------------------------------------ 状态
    def is_running(self):
        thread = self._thread
        return bool(thread and thread.is_alive())

    def status(self):
        with self._state_lock:
            logs = list(self._logs)
            stopping = self._stopping
        return {
            'running': self.is_running(),
            'stopping': stopping,
            'platform_supported': sys.platform == 'darwin',
            'config_path': self.config_path(),
            'logs': logs,
        }

    def _publish_status(self):
        bus = self._event_bus
        if bus is not None:
            snapshot = self.status()
            snapshot.pop('logs', None)  # 状态推送不带日志，日志走 wechat_bark:log 增量
            bus.publish_threadsafe('wechat_bark:status', snapshot)

    # ------------------------------------------------------------------ 监听生命周期
    def start(self):
        with self._state_lock:
            if self.is_running():
                return {'success': True, 'message': '监听已经在运行'}
            if sys.platform != 'darwin':
                return {'success': False, 'error': '微信通知监听仅支持 macOS（需要读取系统通知中心数据库）'}
            try:
                config = self.load_config()
            except ValueError as exc:
                return {'success': False, 'error': str(exc)}
            device_key = config['bark']['device_key']
            if not device_key or device_key == 'YOUR_BARK_DEVICE_KEY':
                return {'success': False, 'error': '请先填写 Bark Device Key 并保存'}
            self._stop_event = threading.Event()
            self._stopping = False
            self._thread = threading.Thread(
                target=self._run,
                args=(config, self._stop_event),
                name=_LISTENER_THREAD_NAME,
                daemon=True,
            )
            self._thread.start()
        self._add_log('监听已启动')
        self._publish_status()
        return {'success': True, 'message': '监听已启动'}

    def _run(self, config, stop_event):
        handler = _ListenerLogHandler(self)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            args = SimpleNamespace(
                test=False, check_schedule=False, list_apps=False,
                dry_run=False, once=False, send_existing=False,
            )
            run_listener(config, args, stop_event=stop_event)
        except Exception as exc:
            self._add_log(f'监听器异常退出：{exc}')
        finally:
            root_logger.removeHandler(handler)
            with self._state_lock:
                self._stopping = False
                self._thread = None
            self._add_log('监听已停止')
            self._publish_status()

    def stop(self):
        with self._state_lock:
            if not self.is_running():
                self._stopping = False
                return {'success': True, 'message': '监听未运行'}
            self._stopping = True
            self._stop_event.set()
        self._add_log('正在停止监听')
        self._publish_status()
        return {'success': True, 'message': '正在停止监听'}

    def shutdown(self):
        """进程退出清理：置停止事件即可，监听线程是 daemon 不会拖住退出。"""
        try:
            self._stop_event.set()
        except Exception:
            pass

    def auto_start_if_configured(self):
        """按配置在启动时自动开始监听（仅 macOS；失败只记日志不抛）。"""
        if sys.platform != 'darwin':
            return
        try:
            config = self.load_config()
        except Exception:
            logging.exception('[微信Bark] 自动启动读取配置失败')
            return
        if config['desktop'].get('auto_start_listener'):
            result = self.start()
            if not result.get('success'):
                self._add_log(result.get('error') or '自动启动监听失败')

    # ------------------------------------------------------------------ 一次性操作
    def test_bark(self):
        """发一条测试推送验证 Bark 配置（任意平台可用）。"""
        try:
            config = self.load_config()
            client = BarkClient(config)
            client.push('微信监听测试', 'Bark 推送配置正常')
            return {'success': True, 'message': 'Bark 测试通知已发送'}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def check_schedule(self):
        """返回当前时刻的转发时段判定（允许/阻止 + 原因），与监听运行与否无关。"""
        try:
            config = self.load_config()
            policy = SchedulePolicy(config)
            decision = policy.decide()
            return {
                'success': True,
                'schedule': {
                    'allowed': decision.allowed,
                    'reason': decision.reason,
                    'now': decision.now.isoformat(),
                    'timezone': policy.timezone_name,
                    'start_time': policy.start_time_label,
                    'end_time': policy.end_time_label,
                },
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def list_apps(self):
        """列出通知中心里出现过的应用及通知数量（仅 macOS 且有完全磁盘访问权限时可用）。"""
        try:
            config = self.load_config()
            store = NotificationStore.from_config(config)
            return {
                'success': True,
                'apps': [{'identifier': identifier, 'count': count}
                         for identifier, count in store.list_apps()],
            }
        except Exception as exc:
            return {'success': False, 'error': str(exc)}
