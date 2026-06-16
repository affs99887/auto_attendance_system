"""
汇率服务模块（Yahoo Finance）

通过 Yahoo chart 接口拉取 CNY->JPY 汇率（最新价 + 历史序列），带本地缓存与惰性刷新：
- 网络请求统一带 User-Agent，避免 Yahoo 返回 429。
- 若内置网络加速（mihomo）已启用，requests 自动走 http://127.0.0.1:{local_port}；否则直连。
- 所有网络/解析异常 try/except 捕获，绝不外抛；失败时回退旧缓存。
- 缓存文件 exchange_rate_cache.json，定位方式与 scheduled_tasks.json 一致（程序运行根目录）。
- 方向固定产出 CNY->JPY；JPY->CNY 由前端对 value/price 取 1/x。

对外暴露：
- get_exchange_rate(range, force=False) -> 契约 dict（带 TTL≈600 秒惰性刷新）
- refresh(range=None) -> 供定时任务调用，强制拉取并写缓存
"""

import os
import json
import time
import logging
import threading

import requests

from modules.config import config

logger = logging.getLogger(__name__)

# Yahoo chart 接口（CNYJPY=X 即 1 CNY 兑换多少 JPY）
_BASE = 'CNY'
_QUOTE = 'JPY'
_SYMBOL = 'CNYJPY=X'
_CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/' + _SYMBOL

# 伪装浏览器 UA，避免 Yahoo 对脚本类请求返回 429
_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

# 缓存惰性刷新 TTL（秒）
_TTL_SECONDS = 600

# 缓存文件名（与 scheduled_tasks.json 一致，落在程序运行根目录）
_CACHE_FILE = 'exchange_rate_cache.json'

# range -> (回溯天数, Yahoo interval)
_RANGE_MAP = {
    '7d': (7, '60m'),
    '30d': (30, '60m'),
    'quarter': (90, '1d'),
    'year': (365, '1d'),
    '3y': (1095, '1d'),
}
_DEFAULT_RANGE = '30d'

# 缓存读写互斥（参考 record_manager 的 _lock）
_lock = threading.Lock()


def _normalize_range(range_):
    """非法 range 回退到默认 30d。"""
    if range_ in _RANGE_MAP:
        return range_
    return _DEFAULT_RANGE


def _proxies():
    """内置加速启用且本地端口在监听时走本地代理，否则直连。

    端口不通（mihomo 未就绪/已崩/确定性失败）时返回 None 直连，不再硬打死端口报 ProxyError。
    判定集中在 config.get_local_proxy()，与 AI资讯/Claude额度/Telegram 口径一致。
    """
    return config.get_local_proxy()


def _cache_path():
    """缓存文件绝对/相对路径，与 scheduled_tasks.json 同样落在运行根目录。"""
    return _CACHE_FILE


def _load_cache():
    """读取缓存文件，失败返回空 dict（不抛）。"""
    path = _cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        logger.warning('[汇率] 读取缓存失败，忽略旧缓存', exc_info=True)
    return {}


def _save_cache(cache):
    """写入缓存文件（失败仅记日志，不抛）。"""
    path = _cache_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.warning('[汇率] 写入缓存失败', exc_info=True)


def _fetch_from_yahoo(range_):
    """调用 Yahoo chart 接口，返回 (latest_dict|None, points_list)。

    latest_dict: {'price': <CNY->JPY>, 'time': <unix秒>}
    points_list: [{'t': <unix秒>, 'value': <CNY->JPY>}, ...]（按时间升序，跳过 None）
    任何网络/解析异常都捕获并向上返回 (None, [])，由调用方回退旧缓存。
    """
    days, interval = _RANGE_MAP[range_]
    now = time.time()
    period1 = int(now - days * 86400)
    period2 = int(now)
    params = {
        'period1': period1,
        'period2': period2,
        'interval': interval,
    }
    try:
        resp = requests.get(
            _CHART_URL,
            params=params,
            headers={'User-Agent': _USER_AGENT},
            proxies=_proxies(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.warning('[汇率] 拉取 Yahoo 数据失败（range=%s）', range_, exc_info=True)
        return None, []

    try:
        result = data['chart']['result'][0]
        meta = result.get('meta') or {}
        latest = None
        price = meta.get('regularMarketPrice')
        mtime = meta.get('regularMarketTime')
        if price is not None and mtime is not None:
            latest = {'price': float(price), 'time': int(mtime)}

        points = []
        timestamps = result.get('timestamp') or []
        quote = (result.get('indicators') or {}).get('quote') or [{}]
        closes = (quote[0] or {}).get('close') or []
        for t, value in zip(timestamps, closes):
            if value is None:
                continue
            try:
                points.append({'t': int(t), 'value': float(value)})
            except (TypeError, ValueError):
                continue
        points.sort(key=lambda p: p['t'])
        return latest, points
    except Exception:
        logger.warning('[汇率] 解析 Yahoo 数据失败（range=%s）', range_, exc_info=True)
        return None, []


def _build_contract(cache, range_):
    """从缓存结构提取指定 range 的契约 dict（供 HTTP/WS 消费）。"""
    range_data = (cache.get('ranges') or {}).get(range_) or {}
    latest = cache.get('latest')
    return {
        'base': cache.get('base', _BASE),
        'quote': cache.get('quote', _QUOTE),
        'range': range_,
        'updated_at': cache.get('updated_at'),
        'latest': latest if latest else None,
        'points': range_data.get('points') or [],
    }


def refresh(range_=None):
    """强制拉取指定 range（None 表示默认 30d）并写缓存，供定时任务调用。

    返回最新契约 dict；失败时返回回退后的旧缓存契约（彻底无数据则 latest:null、points:[]）。
    """
    range_ = _normalize_range(range_)

    # 网络请求挪到锁外执行：_fetch_from_yahoo 只做网络拉取+解析，不触碰共享缓存，
    # 因此最长 ~20s 的慢网络不会持锁阻塞 get_exchange_rate 的 TTL 快速读路径，
    # 避免 waitress 工作线程被一并卡死（M66）。
    latest, points = _fetch_from_yahoo(range_)

    with _lock:
        cache = _load_cache()

        if latest is None and not points:
            # 本次彻底失败：回退旧缓存
            logger.warning('[汇率] 刷新失败（range=%s），回退旧缓存', range_)
            return _build_contract(cache, range_)

        # 写入/更新缓存结构
        cache.setdefault('base', _BASE)
        cache.setdefault('quote', _QUOTE)
        cache['updated_at'] = int(time.time())
        if latest is not None:
            cache['latest'] = latest

        ranges = cache.get('ranges')
        if not isinstance(ranges, dict):
            ranges = {}
        days, interval = _RANGE_MAP[range_]
        ranges[range_] = {
            'interval': interval,
            'fetched': int(time.time()),
            'points': points,
        }
        cache['ranges'] = ranges

        _save_cache(cache)
        logger.info('[汇率] 刷新成功 range=%s 点数=%d latest=%s',
                    range_, len(points), (latest or {}).get('price'))
        return _build_contract(cache, range_)


def get_exchange_rate(range_=None, force=False):
    """返回指定 range 的汇率契约 dict。

    - force=True：跳过 TTL 立即拉取。
    - force=False：若该 range 缓存在 TTL(≈600s) 内则直接复用，否则惰性刷新。
    - 任何失败均回退旧缓存；彻底无数据时 latest:null、points:[]。
    """
    range_ = _normalize_range(range_)

    if not force:
        # 惰性判断：在锁外读一次缓存，命中 TTL 直接返回，避免无谓网络请求
        with _lock:
            cache = _load_cache()
        range_data = (cache.get('ranges') or {}).get(range_) or {}
        fetched = range_data.get('fetched')
        if fetched and (time.time() - fetched) < _TTL_SECONDS:
            return _build_contract(cache, range_)

    # 未命中 TTL 或强制刷新
    return refresh(range_)
