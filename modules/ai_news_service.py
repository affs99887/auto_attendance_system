"""
AI 资讯服务模块（AI HOT）

通过 aihot.virxact.com 公开接口拉取精选 AI 资讯，带本地缓存与惰性刷新：
- 网络请求统一带浏览器 User-Agent（默认 UA 会被 403）+ Accept: application/json。
- 若内置网络加速（mihomo）已启用，requests 自动走 http://127.0.0.1:{local_port}；否则直连。
- 所有网络/解析异常 try/except 捕获，绝不外抛；失败时回退旧缓存。
- 缓存文件 ai_news_cache.json，定位方式与 scheduled_tasks.json 一致（程序运行根目录）。
- 不内置任何假数据/快照——只用真实拉取或缓存或空。

对外暴露：
- get_ai_news(force=False) -> 契约 dict（带 TTL≈600 秒惰性刷新）
- refresh() -> 供定时任务调用，强制拉取并写缓存
"""

import os
import json
import time
import logging
import threading

import requests

from modules.config import config

logger = logging.getLogger(__name__)

# AI HOT 公开精选接口（mode=selected 仅取主编精选，take 控制条数）
_API_URL = 'https://aihot.virxact.com/api/public/items'
_TAKE = 50

# 伪装浏览器 UA：默认 requests UA 会被该站点 403，必须带浏览器 UA
_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)

# 缓存惰性刷新 TTL（秒）
_TTL_SECONDS = 600

# 缓存文件名（与 scheduled_tasks.json 一致，落在程序运行根目录）
_CACHE_FILE = 'ai_news_cache.json'

# 合法版块取值（其余原样保留或 None）
_VALID_CATEGORIES = {'ai-models', 'ai-products', 'industry', 'paper', 'tip'}

# 缓存读写互斥（参考 record_manager 的 _lock）
_lock = threading.Lock()


def _proxies():
    """若内置网络加速启用，返回走本地端口的 proxies dict；否则 None（直连）。"""
    try:
        if config.get_proxy_enabled():
            port = config.get_proxy_local_port()
            url = f'http://127.0.0.1:{port}'
            return {'http': url, 'https': url}
    except Exception:
        logger.warning('[AI资讯] 判断代理状态异常，转为直连', exc_info=True)
    return None


def _cache_path():
    """缓存文件路径，与 scheduled_tasks.json 同样落在运行根目录。"""
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
        logger.warning('[AI资讯] 读取缓存失败，忽略旧缓存', exc_info=True)
    return {}


def _save_cache(cache):
    """写入缓存文件（失败仅记日志，不抛）。"""
    path = _cache_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.warning('[AI资讯] 写入缓存失败', exc_info=True)


def _normalize_item(raw):
    """把 API 原始 item 归一化为统一结构 dict。

    必有字段 id/title/url/source；可选 title_en/summary/publishedAt/category。
    category 取值应为 ai-models|ai-products|industry|paper|tip 之一，否则原样保留或 None。
    """
    category = raw.get('category')
    if category is not None and category not in _VALID_CATEGORIES:
        # 非合法取值原样保留（前端兜底处理）
        category = category
    return {
        'id': raw.get('id'),
        'title': raw.get('title'),
        'title_en': raw.get('title_en'),
        'url': raw.get('url'),
        'source': raw.get('source'),
        'publishedAt': raw.get('publishedAt'),
        'summary': raw.get('summary'),
        'category': category,
    }


def _fetch_from_aihot():
    """调用 AI HOT 接口，返回 items 列表（已归一化）。

    任何网络/解析异常都捕获并向上返回 None，由调用方回退旧缓存。
    """
    params = {
        'mode': 'selected',
        'take': _TAKE,
    }
    try:
        resp = requests.get(
            _API_URL,
            params=params,
            headers={
                'User-Agent': _USER_AGENT,
                'Accept': 'application/json',
            },
            proxies=_proxies(),
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.warning('[AI资讯] 拉取 AI HOT 数据失败', exc_info=True)
        return None

    try:
        raw_items = data.get('items') or []
        items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            items.append(_normalize_item(raw))
        return items
    except Exception:
        logger.warning('[AI资讯] 解析 AI HOT 数据失败', exc_info=True)
        return None


def _build_contract(cache):
    """从缓存结构提取契约 dict（供 HTTP/WS 消费）。"""
    items = cache.get('items') or []
    return {
        'updated_at': cache.get('updated_at'),
        'count': len(items),
        'items': items,
    }


def refresh():
    """强制拉取并写缓存，供定时任务调用。

    返回最新契约 dict；拉取彻底失败时回退旧缓存的 items（count 同步）；
    彻底无数据时 updated_at:null、count:0、items:[]。
    """
    # 网络请求挪到锁外执行：_fetch_from_aihot 只做网络拉取+解析，不触碰共享缓存，
    # 因此最长 ~20s 的慢网络不会持锁阻塞 get_ai_news 的 TTL 快速读路径，
    # 避免 waitress 工作线程被一并卡死（M66，与 exchange_rate_service 同款改造）。
    items = _fetch_from_aihot()

    with _lock:
        cache = _load_cache()

        if items is None:
            # 本次彻底失败：回退旧缓存
            logger.warning('[AI资讯] 刷新失败，回退旧缓存')
            return _build_contract(cache)

        # 写入/更新缓存结构
        cache['updated_at'] = int(time.time())
        cache['items'] = items
        cache['fetched'] = int(time.time())

        _save_cache(cache)
        logger.info('[AI资讯] 刷新成功 条数=%d', len(items))
        return _build_contract(cache)


def get_ai_news(force=False):
    """返回 AI 资讯契约 dict。

    - force=True：跳过 TTL 立即拉取。
    - force=False：若缓存在 TTL(≈600s) 内则直接复用，否则惰性刷新。
    - 任何失败均回退旧缓存；彻底无数据时 updated_at:null、count:0、items:[]。
    """
    if not force:
        # 惰性判断：在锁外读一次缓存，命中 TTL 直接返回，避免无谓网络请求
        with _lock:
            cache = _load_cache()
        fetched = cache.get('fetched')
        if fetched and (time.time() - fetched) < _TTL_SECONDS:
            return _build_contract(cache)

    # 未命中 TTL 或强制刷新
    return refresh()
