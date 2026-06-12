"""
Claude Code 额度服务模块

读取本机 Claude Code 登录凭据（~/.claude/.credentials.json 的 OAuth accessToken），
调用官方 usage 接口获取「5 小时会话窗口 / 周限额」用量与重置时间，供墨水屏信息站渲染。

设计与 exchange_rate_service 一致：
- TTL 内存缓存（默认 300 秒）+ force 跳过；失败回退旧缓存，绝不外抛。
- 若内置网络加速（mihomo）已启用，requests 自动走 http://127.0.0.1:{local_port}；否则直连。
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

import requests

from modules.config import config

logger = logging.getLogger(__name__)

_USAGE_URL = 'https://api.anthropic.com/api/oauth/usage'

# OAuth 接口要求的 beta 标头（与 Claude Code 客户端一致）
_OAUTH_BETA = 'oauth-2025-04-20'

# 缓存惰性刷新 TTL（秒）
_TTL_SECONDS = 300

# 内存缓存（额度数据无需跨进程持久化）
_lock = threading.Lock()
_cache = {
    'updated_at': None,   # unix 秒
    'data': None,         # 上次成功的契约 dict（不含 updated_at/available）
    'error': None,
}


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


def _proxies():
    """若内置网络加速启用，返回走本地端口的 proxies dict；否则 None（直连）。"""
    try:
        if config.get_proxy_enabled():
            port = config.get_proxy_local_port()
            url = f'http://127.0.0.1:{port}'
            return {'http': url, 'https': url}
    except Exception:
        logger.warning('[Claude额度] 判断代理状态异常，转为直连', exc_info=True)
    return None


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
        resp = requests.get(_USAGE_URL, headers=headers, proxies=_proxies(), timeout=15)
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
    """读取额度（带 TTL 惰性刷新）。永不抛异常。"""
    with _lock:
        now = time.time()
        fresh = (
            _cache['updated_at'] is not None
            and now - _cache['updated_at'] < _TTL_SECONDS
            and _cache['data'] is not None
        )
        if fresh and not force:
            return _build_result()

        data, err = _fetch_usage()
        if data is not None:
            _cache['updated_at'] = int(now)
            _cache['data'] = data
            _cache['error'] = None
        else:
            # 失败：保留旧缓存（若有），仅更新错误信息
            _cache['error'] = err
            logger.info('[Claude额度] 刷新失败：%s（沿用旧缓存=%s）', err, _cache['data'] is not None)
        return _build_result()


def _build_result():
    """由缓存组装对外契约。"""
    data = _cache['data']
    if data is None:
        return {
            'available': False,
            'updated_at': None,
            'five_hour': None,
            'seven_day': None,
            'error': _cache['error'] or '暂无数据',
        }
    return {
        'available': True,
        'updated_at': _cache['updated_at'],
        'five_hour': data.get('five_hour'),
        'seven_day': data.get('seven_day'),
        'error': _cache['error'],  # 可能是「刷新失败但有旧缓存」的提示
    }
