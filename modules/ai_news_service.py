"""
AI 资讯服务模块（AI HOT）

通过 aihot.virxact.com 公开接口拉取精选 AI 资讯，带本地缓存与惰性刷新：
- 网络请求统一带浏览器 User-Agent（默认 UA 会被 403）+ Accept: application/json。
- 若内置网络加速（mihomo）已启用，requests 自动走 http://127.0.0.1:{local_port}；否则直连。
- 所有网络/解析异常 try/except 捕获，绝不外抛；失败时回退旧缓存。
- 缓存文件 ai_news_cache.json，定位方式与 scheduled_tasks.json 一致（程序运行根目录）。
- 不内置任何假数据/快照——只用真实拉取或缓存或空。

对外暴露：
- get_ai_news(force=False, cursor=None, take=None, category=None, mode=None) -> 契约 dict（含 next_cursor/has_next）；
  cursor 非空时为"加载更多"游标续拉（实时、不缓存）；
  category 非空时按版块服务端过滤，mode='selected' 时只取主编精选（"只看精选"），
  mode+category 可组合，各视图独立一份列表/游标/缓存。
- refresh(category=None, mode=None) -> 供定时任务调用，强制拉取该视图首屏并写缓存
"""

import os
import json
import time
import logging
import threading

import requests

from modules.config import config

logger = logging.getLogger(__name__)

# AI HOT 公开接口（category 服务端过滤，take 控制每页条数，cursor 游标翻页）
_API_URL = 'https://aihot.virxact.com/api/public/items'
# 拉取口径：all=全量（约 1900+ 条，内容最全），每条自带 selected 标记编辑精选。
# selected=仅主编精选（约 112 条，量少质高）。当前用 all 保内容量，精选靠 item.selected 标出。
_MODE = 'all'
# 每页/首屏条数（游标分页逐页加载）
_PAGE_TAKE = 30

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
    """内置加速启用且本地端口在监听时走本地代理，否则直连。

    端口不通（mihomo 未就绪/已崩/确定性失败）时返回 None 直连，不再硬打死端口报 ProxyError。
    判定集中在 config.get_local_proxy()，与 汇率/Claude额度/Telegram 口径一致。
    """
    return config.get_local_proxy()


def _cache_path():
    """缓存文件路径，与 scheduled_tasks.json 同样落在运行根目录。"""
    return _CACHE_FILE


def _load_cache():
    """读取缓存文件，失败返回空 dict（不抛）。

    缓存结构为 {'buckets': {<视图key>: {updated_at,items,fetched,next_cursor,has_next}}}，
    视图 key = f"{mode}:{category or 'all'}"（如 all:all / all:ai-models / selected:all）。
    兼容旧版结构（无 buckets 的扁平缓存忽略即可，TTL 内自动重拉，无副作用）。
    """
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


def _bucket_key(mode, category):
    """视图缓存 key：mode + category 组合（无 category 归为 'all'）。"""
    return '%s:%s' % (mode, category or 'all')


def _get_bucket(cache, mode, category):
    """从缓存取指定视图的子结构，缺失返回空 dict。"""
    buckets = cache.get('buckets')
    if isinstance(buckets, dict):
        bucket = buckets.get(_bucket_key(mode, category))
        if isinstance(bucket, dict):
            return bucket
    return {}


def _set_bucket(cache, mode, category, bucket):
    """把指定视图的子结构写回缓存（原地更新 cache['buckets']）。"""
    buckets = cache.get('buckets')
    if not isinstance(buckets, dict):
        buckets = {}
        cache['buckets'] = buckets
    buckets[_bucket_key(mode, category)] = bucket


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

    必有字段 id/title/url/source；可选 title_en/summary/publishedAt/category/selected。
    category 取值应为 ai-models|ai-products|industry|paper|tip 之一，否则原样保留或 None。
    selected=True 表示该条是上游主编精选（前端据此打「精选」标）。
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
        'selected': bool(raw.get('selected')),
    }


def _fetch_from_aihot(cursor=None, take=None, category=None, mode=None):
    """调用 AI HOT 接口，返回 (items, next_cursor, has_next)。

    - mode 缺省 _MODE(all 全量)，'selected' 时仅主编精选（供"只看精选"筛选）；
      take 控制每页条数；cursor 非空时翻下一页。
    - category 非空时按版块服务端过滤（各版块游标独立，可与 mode 组合）。
    - 每条返回带 selected 标记（是否主编精选），归一化后透传给前端。
    - 任何网络/解析异常都捕获并向上返回 (None, None, None)，由调用方回退旧缓存或上抛。
    """
    params = {
        'mode': mode or _MODE,
        'take': take or _PAGE_TAKE,
    }
    if category:
        params['category'] = category
    if cursor:
        params['cursor'] = cursor
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
        return None, None, None

    try:
        raw_items = data.get('items') or []
        items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            items.append(_normalize_item(raw))
        next_cursor = data.get('nextCursor')
        has_next = bool(data.get('hasNext'))
        return items, next_cursor, has_next
    except Exception:
        logger.warning('[AI资讯] 解析 AI HOT 数据失败', exc_info=True)
        return None, None, None


def _build_contract(bucket):
    """从版块缓存子结构提取契约 dict（供 HTTP/WS 消费）。"""
    items = bucket.get('items') or []
    return {
        'updated_at': bucket.get('updated_at'),
        'count': len(items),
        'items': items,
        'next_cursor': bucket.get('next_cursor'),
        'has_next': bool(bucket.get('has_next')),
    }


def refresh(category=None, mode=None):
    """强制拉取指定视图(mode+category)首屏并写缓存，供定时任务调用。

    mode 缺省 _MODE(all)；category 为空即"全部"。
    返回最新契约 dict（含 next_cursor/has_next）；拉取彻底失败时回退该视图旧缓存；
    彻底无数据时 updated_at:null、count:0、items:[]、has_next:false。
    """
    mode = mode or _MODE
    # 网络请求挪到锁外执行：_fetch_from_aihot 只做网络拉取+解析，不触碰共享缓存，
    # 因此最长 ~20s 的慢网络不会持锁阻塞 get_ai_news 的 TTL 快速读路径，
    # 避免 waitress 工作线程被一并卡死（M66，与 exchange_rate_service 同款改造）。
    items, next_cursor, has_next = _fetch_from_aihot(category=category, mode=mode)

    with _lock:
        cache = _load_cache()

        if items is None:
            # 本次彻底失败：回退该视图旧缓存
            logger.warning('[AI资讯] 刷新失败，回退旧缓存 view=%s', _bucket_key(mode, category))
            return _build_contract(_get_bucket(cache, mode, category))

        # 写入/更新该视图缓存（含首屏游标，作为"加载更多"续拉起点）
        bucket = {
            'updated_at': int(time.time()),
            'items': items,
            'fetched': int(time.time()),
            'next_cursor': next_cursor,
            'has_next': bool(has_next),
        }
        _set_bucket(cache, mode, category, bucket)

        _save_cache(cache)
        logger.info('[AI资讯] 刷新成功 view=%s 条数=%d has_next=%s',
                    _bucket_key(mode, category), len(items), has_next)
        return _build_contract(bucket)


def get_ai_news(force=False, cursor=None, take=None, category=None, mode=None):
    """返回 AI 资讯契约 dict（含 next_cursor/has_next）。

    - mode 缺省 _MODE(all 全量)，'selected' 时仅主编精选（"只看精选"筛选）。
    - category 非空：按版块服务端过滤（可与 mode 组合，各视图独立一份列表/游标/缓存）。
    - cursor 非空（"加载更多"续拉）：实时拉取该页（沿用同视图 mode+category），不读写缓存；
      本次拉取失败时抛 RuntimeError，由 HTTP 层转成错误响应（前端可重试，不伪装成到底）。
    - cursor 为空（首屏）：
        - force=True：跳过 TTL 立即拉取。
        - force=False：该视图缓存在 TTL(≈600s) 内则直接复用，否则惰性刷新。
        - 任何失败均回退该视图旧缓存；彻底无数据时 updated_at:null、count:0、items:[]。
    """
    mode = mode or _MODE
    if cursor:
        # 加载更多：游标续拉（带 mode+category 过滤），实时返回，不进缓存（避免污染首屏缓存）
        items, next_cursor, has_next = _fetch_from_aihot(
            cursor=cursor, take=take, category=category, mode=mode)
        if items is None:
            raise RuntimeError('ai-news load_more failed')
        return {
            'updated_at': int(time.time()),
            'count': len(items),
            'items': items,
            'next_cursor': next_cursor,
            'has_next': bool(has_next),
        }

    if not force:
        # 惰性判断：在锁外读一次缓存，该视图命中 TTL 直接返回，避免无谓网络请求
        with _lock:
            cache = _load_cache()
        bucket = _get_bucket(cache, mode, category)
        fetched = bucket.get('fetched')
        if fetched and (time.time() - fetched) < _TTL_SECONDS:
            return _build_contract(bucket)

    # 未命中 TTL 或强制刷新
    return refresh(category=category, mode=mode)
