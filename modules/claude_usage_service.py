"""
Claude Code 额度服务模块

读取本机 Claude Code 登录凭据（~/.claude/.credentials.json 的 OAuth accessToken），
调用官方 usage 接口获取「5 小时会话窗口 / 周限额」用量与重置时间，供墨水屏信息站渲染。

设计与 exchange_rate_service 一致：
- TTL 内存缓存（默认 300 秒）+ force 跳过；失败回退旧缓存但有陈旧上限（超龄按不可用返回），
  失败后短时间内不重复发请求（负缓存），绝不外抛。
- 若内置网络加速（mihomo）已启用则优先走本地代理；代理连接失败时立即回退默认网络。
- 只读凭据文件，不做 token 刷新（Claude Code 自身会维护 token 有效性）；
  token 过期时返回 available=False + error 提示，不影响其他功能。
- 日志中绝不输出 token 本体。

对外暴露：
- get_claude_usage(force=False) -> 契约 dict：
  {
    'available': bool,            # 是否拿到有效数据
    'updated_at': int | None,     # 缓存刷新时刻（unix 秒）
    'five_hour': {'used_pct': float, 'resets_at': str | None} | None,
    'seven_day': {'used_pct': float, 'resets_at': str | None} | None,
    'error': str | None,          # 不可用时的人话原因
  }
"""

import os
import json
import time
import logging
import threading

from modules.proxy_manager import request_get_with_local_proxy_fallback

logger = logging.getLogger(__name__)

_USAGE_URL = 'https://api.anthropic.com/api/oauth/usage'

# OAuth 接口要求的 beta 标头（与 Claude Code 客户端一致）
_OAUTH_BETA = 'oauth-2025-04-20'

# 缓存惰性刷新 TTL（秒）
_TTL_SECONDS = 300

# 负缓存 TTL（秒）：一次刷新尝试（无论成败）后的这段时间内不再发起新请求，
# 避免网络故障时每个调用都硬吃一次 15 秒超时
_FAIL_TTL_SECONDS = 60

# 缓存陈旧上限（秒）：旧数据超龄后按不可用返回——5 小时窗口的 resets_at/用量
# 早已失真，继续当有效数据返回会让前端把冻结数据当真
_STALE_SECONDS = _TTL_SECONDS * 3

# 内存缓存（额度数据无需跨进程持久化）
_lock = threading.Lock()
_cache = {
    'updated_at': None,     # unix 秒（最近一次成功刷新）
    'data': None,           # 上次成功的契约 dict（不含 updated_at/available）
    'error': None,
    'last_attempt': None,   # 最近一次发起刷新的时刻（成功失败都记，用于负缓存）
}
# 是否已有线程在锁外做网络请求；置位期间其他调用直接返回现有缓存，不排队等待
_fetching = False


def _credentials_path():
    """凭据文件路径：~/.claude/.credentials.json（Windows 下即 %USERPROFILE%）。"""
    return os.path.join(os.path.expanduser('~'), '.claude', '.credentials.json')


def _read_access_token():
    """读取本机 Claude Code 的 OAuth accessToken。

    返回 (token, error)：失败时 token 为 None，error 为人话原因。
    """
    path = _credentials_path()
    if not os.path.exists(path):
        return None, '未找到 Claude Code 登录凭据（~/.claude/.credentials.json）'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        oauth = data.get('claudeAiOauth') or {}
        token = oauth.get('accessToken')
        if not token:
            return None, '凭据文件中没有 accessToken，请在 Claude Code 中重新登录'
        # 本地能预判的过期：expiresAt 为毫秒时间戳
        expires_at = oauth.get('expiresAt')
        if isinstance(expires_at, (int, float)) and expires_at / 1000.0 < time.time():
            return None, 'Claude Code 凭据已过期，请打开 Claude Code 触发刷新或重新登录'
        return token, None
    except Exception:
        logger.warning('[Claude额度] 读取凭据文件失败', exc_info=True)
        return None, '读取 Claude Code 凭据文件失败'


def _parse_window(obj):
    """把接口返回的单个限额窗口归一化为 {'used_pct', 'resets_at'}。

    兼容字段：utilization（0-100）；resets_at（ISO 字符串）。形状不符返回 None。
    """
    if not isinstance(obj, dict):
        return None
    util = obj.get('utilization')
    if not isinstance(util, (int, float)):
        return None
    resets_at = obj.get('resets_at')
    if resets_at is not None and not isinstance(resets_at, str):
        resets_at = None
    return {'used_pct': max(0.0, min(100.0, float(util))), 'resets_at': resets_at}


def _fetch_usage():
    """调用官方 usage 接口。返回 (data_dict, error)；data 为 {'five_hour','seven_day'}。"""
    token, err = _read_access_token()
    if token is None:
        return None, err
    headers = {
        'Authorization': f'Bearer {token}',
        'anthropic-beta': _OAUTH_BETA,
        'Accept': 'application/json',
    }
    try:
        resp = request_get_with_local_proxy_fallback(
            'claude_usage', _USAGE_URL, headers=headers, timeout=15)
    except Exception:
        logger.warning('[Claude额度] usage 接口请求失败', exc_info=True)
        return None, '请求 Claude usage 接口失败（网络不可达）'

    if resp.status_code == 401:
        return None, 'Claude 凭据未授权（401），请打开 Claude Code 触发 token 刷新'
    if resp.status_code != 200:
        logger.warning('[Claude额度] usage 接口返回 %s: %s', resp.status_code, resp.text[:200])
        return None, f'Claude usage 接口返回 HTTP {resp.status_code}'

    try:
        payload = resp.json()
    except Exception:
        logger.warning('[Claude额度] usage 响应非 JSON', exc_info=True)
        return None, 'Claude usage 接口响应解析失败'

    five_hour = _parse_window(payload.get('five_hour'))
    seven_day = _parse_window(payload.get('seven_day'))
    if five_hour is None and seven_day is None:
        # 形状对不上时记录键名帮助排障（不含数值与 token）
        logger.warning('[Claude额度] 响应中未找到限额字段，keys=%s', list(payload.keys()) if isinstance(payload, dict) else type(payload))
        return None, 'Claude usage 响应中没有限额数据'
    return {'five_hour': five_hour, 'seven_day': seven_day}, None


def get_claude_usage(force=False):
    """读取额度（TTL 惰性刷新 + 失败负缓存）。永不抛异常。

    网络请求（最长 15 秒超时）放在锁外执行，锁内只读写缓存；
    已有线程在拉取时其余调用不排队等待，直接返回现有缓存。
    """
    global _fetching
    with _lock:
        now = time.time()
        fresh = (
            _cache['updated_at'] is not None
            and now - _cache['updated_at'] < _TTL_SECONDS
            and _cache['data'] is not None
        )
        if fresh and not force:
            return _build_result()

        # 负缓存：上次尝试后的短时间内不再发请求（成功场景已被 fresh 拦住，
        # 这里主要拦失败），防止网络不通时每次调用都硬吃一次超时
        if (
            not force
            and _cache['last_attempt'] is not None
            and now - _cache['last_attempt'] < _FAIL_TTL_SECONDS
        ):
            return _build_result()

        if _fetching:
            # 别的线程正在锁外拉取：不重复请求，先用现有缓存应付本次调用
            return _build_result()
        _fetching = True
        _cache['last_attempt'] = now

    data, err = None, None
    try:
        try:
            data, err = _fetch_usage()
        except Exception:
            # _fetch_usage 内部已各自兜底，这里是最后保险
            logger.warning('[Claude额度] 刷新过程异常', exc_info=True)
            err = '刷新 Claude 额度时发生内部错误'
    finally:
        # 复位放 finally：即便冒出非 Exception 的异常，也不能让"正在拉取"标记
        # 永久卡 True（那会连 force 刷新都被短路，额度数据冻结到进程重启）
        with _lock:
            _fetching = False

    with _lock:
        if data is not None:
            _cache['updated_at'] = int(time.time())
            _cache['data'] = data
            _cache['error'] = None
        else:
            # 失败：保留旧缓存（若有），仅更新错误信息
            _cache['error'] = err
            logger.info('[Claude额度] 刷新失败：%s（沿用旧缓存=%s）', err, _cache['data'] is not None)
        return _build_result()


def _build_result():
    """由缓存组装对外契约（须在持有 _lock 时调用）。"""
    data = _cache['data']
    if data is None:
        return {
            'available': False,
            'updated_at': None,
            'five_hour': None,
            'seven_day': None,
            'error': _cache['error'] or '暂无数据',
        }
    # 陈旧上限：上游长期失败时旧数据的 resets_at/用量早已失真，
    # 按不可用返回，让前端走降级逻辑而不是拿冻结数据当真
    age = time.time() - _cache['updated_at']
    if age > _STALE_SECONDS:
        return {
            'available': False,
            'updated_at': _cache['updated_at'],
            'five_hour': None,
            'seven_day': None,
            'error': f'数据已过期，最后成功于 {int(age // 60)} 分钟前',
        }
    return {
        'available': True,
        'updated_at': _cache['updated_at'],
        'five_hour': data.get('five_hour'),
        'seven_day': data.get('seven_day'),
        'error': _cache['error'],  # 可能是「刷新失败但有旧缓存」的提示
    }
