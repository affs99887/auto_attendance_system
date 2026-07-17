"""
Web 服务模块 — 为 GUI（Electron）提供 REST + WebSocket 接口

设计要点：
- Flask + waitress 在 daemon 线程运行（同步），处理 REST 请求
- websockets server 在主 asyncio 事件循环（异步），处理实时推送
- 共用 AppCore 单例（线程↔loop 通信走 run_coroutine_threadsafe）
- event_bus 是 pub/sub，每个 WS 连接订阅一个独立 asyncio.Queue
- Bearer token 鉴权（启动时生成、写入 logs/.gui_token）
- 仅监听 127.0.0.1
"""

import os
import sys
import json
import time
import asyncio
import logging
import threading
import secrets
import functools
import tempfile
import getpass
import subprocess
import re
import base64
import hashlib
import hmac
import math
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Optional, Set
from urllib.parse import quote, urlencode

from flask import Flask, request, jsonify
import waitress

try:
    import websockets
except ImportError as _e:  # pragma: no cover
    websockets = None
    _IMPORT_ERR = _e
else:
    _IMPORT_ERR = None


TOKEN_FILE = os.path.join('logs', '.gui_token')
LOG_FILE = os.path.join('logs', 'app.log')

# 允许通过 PATCH /api/v1/config 写入 .env 的字段白名单
# （敏感字段也允许写，但客户端需有 token 才能写；新业务的环境变量在这里登记后前端才可写）
ENV_WRITE_WHITELIST = {
    'CAIYUN_WEATHER_APP_KEY', 'CAIYUN_WEATHER_APP_SECRET', 'CAIYUN_WEATHER_TOKEN',
}

# 返回给前端 GET /api/v1/config/all 时遮罩的敏感字段
ENV_SENSITIVE_FIELDS = {
    'CAIYUN_WEATHER_APP_KEY', 'CAIYUN_WEATHER_APP_SECRET', 'CAIYUN_WEATHER_TOKEN',
}


# ----------------------------------------------------------------------------
# Event Bus
# ----------------------------------------------------------------------------

class EventBus:
    """简单 pub/sub：每个订阅者拥有独立 asyncio.Queue。

    - 主 loop 内调用 ``await publish(...)``
    - 任意线程调用 ``publish_threadsafe(...)``（内部投递回 loop）
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._subscribers: Set[asyncio.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self, maxsize: int = 500) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)

    async def publish(self, channel: str, data: Any) -> None:
        msg = {'channel': channel, 'data': data, 'ts': time.time()}
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                # 订阅者太慢，丢弃这条消息避免阻塞发布方
                pass

    def publish_threadsafe(self, channel: str, data: Any) -> None:
        asyncio.run_coroutine_threadsafe(self.publish(channel, data), self._loop)


# ----------------------------------------------------------------------------
# Async bridge — 把同步 Flask 路由投递到主 loop
# ----------------------------------------------------------------------------

class AsyncioBridge:
    """底座预留脚手架：同步 Flask 路由需要调主 loop 协程时用 bridge.call 投递。
    当前保留的路由都是纯同步实现，暂无调用方；定制新功能需要跨线程进事件循环时直接用它。
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def call(self, coro, timeout: float = 15.0):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeoutError:
            # 超时后必须取消 future，否则协程仍排在事件循环里等待执行：
            # HTTP 已报错返回，循环空闲后却仍会真正执行，形成调用方不知情的"幽灵操作"。
            # 不可幂等的写操作尤其需要在此切断。
            fut.cancel()
            raise


# ----------------------------------------------------------------------------
# Token auth
# ----------------------------------------------------------------------------

def _restrict_token_acl(path: str) -> None:
    """[M72 修复] 收紧 token 文件 ACL，使同机其它账户无法读取。

    os.chmod(path, 0o600) 在 Windows 上只切换只读位、完全不影响 ACL —— 项目目录若不在
    用户 profile 之下，logs\\.gui_token 继承的默认 ACL 通常允许
    本机所有用户读取，拿到 token 即可调 PATCH /api/v1/config 改写 .env 凭据。故在 Windows 下
    用内置 icacls 断继承并仅授予当前用户完全控制（icacls 始终随系统存在，不依赖 pywin32，
    与项目"无 pywin32 也能跑"的约束一致）。非 Windows 维持 chmod 0600 即可。
    """
    if sys.platform != 'win32':
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return
    # Windows：chmod 仅作只读位兜底，真正的访问控制交给 icacls
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    try:
        user = os.environ.get('USERNAME') or getpass.getuser()
        domain = os.environ.get('USERDOMAIN')
        principal = f'{domain}\\{user}' if domain else user
        # /inheritance:r 移除继承的 ACE（断掉默认放给本机用户组的读权限）；
        # /grant:r 重置并仅授予当前用户完全控制。失败不阻断启动，仅告警。
        subprocess.run(
            ['icacls', path, '/inheritance:r', '/grant:r', f'{principal}:F'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=10,
        )
    except Exception:
        logging.warning("收紧 token 文件 ACL 失败（icacls 不可用？），同机其它账户可能可读 %s", path)


def _ensure_token() -> str:
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    token = secrets.token_urlsafe(32)
    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        f.write(token)
    _restrict_token_acl(TOKEN_FILE)
    return token


def _make_require_token(expected: str):
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(*args, **kwargs):
            auth = request.headers.get('Authorization', '')
            token = auth[7:] if auth.startswith('Bearer ') else ''
            if not token:
                token = request.args.get('token', '')
            if not token or not secrets.compare_digest(token, expected):
                return jsonify({'error': 'unauthorized'}), 401
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


# ----------------------------------------------------------------------------
# Log tail helpers
# ----------------------------------------------------------------------------

def _read_env_file(path: str = '.env') -> dict:
    """读取 .env 文件为 dict（保留原值，不解析引号）。"""
    result: dict = {}
    if not os.path.exists(path):
        return result
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip()
                # 去除两端引号
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                result[k] = v
    except Exception:
        logging.exception(f"读 .env 失败: {path}")
    return result


_ENV_LOCK = threading.Lock()


def _write_env_atomic(patch: dict, path: str = '.env') -> dict:
    """把 patch 中的字段合并写回 .env，原子替换，备份原 .env 到 .env.bak。

    - 仅写入 ENV_WRITE_WHITELIST 中的字段
    - 已有 key 就地替换；新 key 追加到末尾
    - 返回应用后的 .env 全量字典（未遮罩）
    """
    cleaned: dict = {}
    for k, v in (patch or {}).items():
        if k not in ENV_WRITE_WHITELIST:
            continue
        if v is None:
            continue
        # 防止换行注入
        s = str(v).replace('\r', '').replace('\n', '')
        if not re.match(r'^[A-Z][A-Z0-9_]*$', k):
            continue
        cleaned[k] = s

    if not cleaned:
        return _read_env_file(path)

    with _ENV_LOCK:
        existing_lines: list = []
        existing_keys: set = set()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    existing_lines = f.readlines()
            except Exception:
                logging.exception("读 .env 失败")
                existing_lines = []
        else:
            existing_lines = []

        # 替换已有 key
        out_lines = []
        for raw in existing_lines:
            stripped = raw.strip()
            if not stripped or stripped.startswith('#') or '=' not in stripped:
                out_lines.append(raw if raw.endswith('\n') else raw + '\n')
                continue
            k = stripped.split('=', 1)[0].strip()
            if k in cleaned:
                existing_keys.add(k)
                out_lines.append(f'{k}={cleaned[k]}\n')
            else:
                out_lines.append(raw if raw.endswith('\n') else raw + '\n')
        # 追加新 key
        for k, v in cleaned.items():
            if k not in existing_keys:
                out_lines.append(f'{k}={v}\n')

        # 备份原 .env
        if os.path.exists(path):
            try:
                import shutil
                shutil.copy2(path, path + '.bak')
            except Exception:
                logging.exception(".env 备份失败")

        # 临时文件 + 原子替换
        tmp_fd, tmp_path = tempfile.mkstemp(prefix='.env.', dir=os.path.dirname(os.path.abspath(path)) or '.')
        try:
            with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
                f.writelines(out_lines)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            raise

    return _read_env_file(path)


# ----------------------------------------------------------------------------
# 彩云天气 helpers（GUI 定位后按经纬度拉取，凭据仅留在 Python 后端）
# ----------------------------------------------------------------------------

_WEATHER_CACHE_TTL = 600
_WEATHER_CACHE_MAX = 20
_WEATHER_HOURLY_STEPS = 72
_WEATHER_DAILY_STEPS = 7
_weather_cache: dict = {}
_weather_cache_lock = threading.Lock()


class _CaiyunConfigError(RuntimeError):
    """彩云天气凭据缺失或不完整。"""


def _caiyun_credentials():
    """返回 (app_key, app_secret, token)，优先使用官方推荐的 Key/Secret。"""
    app_key = (os.getenv('CAIYUN_WEATHER_APP_KEY') or '').strip()
    app_secret = (os.getenv('CAIYUN_WEATHER_APP_SECRET') or '').strip()
    token = (os.getenv('CAIYUN_WEATHER_TOKEN') or '').strip()
    if app_key and app_secret:
        return app_key, app_secret, token
    if token:
        return '', '', token
    if app_key or app_secret:
        raise _CaiyunConfigError('彩云 App Key / App Secret 需成对配置')
    raise _CaiyunConfigError('未配置彩云天气凭据，请前往“设置 → 天气”完成配置')


def _caiyun_signature_headers(path: str, query: dict, app_key: str,
                              app_secret: str, *, key_in_header: bool) -> dict:
    """按彩云官方规则生成 HMAC-SHA256 请求头。"""
    nonce = str(uuid.uuid4())
    timestamp = str(int(time.time()))
    normalized = {str(k): str(v) for k, v in query.items()}
    query_string = urlencode(sorted(normalized.items()))
    message = ':'.join(('GET', path, query_string, app_key, nonce, timestamp))
    digest = hmac.new(
        app_secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    headers = {
        'x-cy-nonce': nonce,
        'x-cy-timestamp': timestamp,
        'x-cy-signature': base64.urlsafe_b64encode(digest).decode('ascii'),
    }
    if key_in_header:
        headers['x-cy-app-key'] = app_key
    return headers


def _caiyun_http_get(base_url: str, path: str, query: dict, headers: dict) -> dict:
    """执行一次彩云 GET；异常中不包含带凭据的完整 URL。"""
    import requests
    from modules.proxy_manager import request_get_with_local_proxy_fallback

    try:
        response = request_get_with_local_proxy_fallback(
            'weather',
            base_url + path,
            params=query,
            headers={'Accept': 'application/json', **headers},
            timeout=(5, 10),
        )
        response.raise_for_status()
        data = response.json()
    except requests.HTTPError as exc:
        status = getattr(exc.response, 'status_code', 'unknown')
        # requests 异常 repr 会带完整 URL（v2.6 凭据位于 path），禁止让异常链进入日志。
        raise RuntimeError(f'彩云接口返回 HTTP {status}') from None
    except Exception:
        raise RuntimeError('彩云接口请求失败') from None
    if not isinstance(data, dict):
        raise RuntimeError('彩云接口返回格式异常')
    return data


def _fetch_caiyun_weather_raw(latitude: float, longitude: float) -> dict:
    """调用 v2.6 综合天气接口。"""
    app_key, app_secret, token = _caiyun_credentials()
    credential = app_key or token
    coordinate = f'{longitude:.6f},{latitude:.6f}'
    path = f'/v2.6/{quote(credential, safe="")}/{coordinate}/weather'
    query = {
        'alert': 'true',
        'dailysteps': str(_WEATHER_DAILY_STEPS),
        # 新套餐支持未来 3 天逐小时预报，完整保留给详情页与后续业务使用。
        'hourlysteps': str(_WEATHER_HOURLY_STEPS),
        # metric:v2 让实况/逐时降水统一为 mm/h，距离保持 km。
        'unit': 'metric:v2',
    }
    headers = (
        _caiyun_signature_headers(path, query, app_key, app_secret, key_in_header=False)
        if app_key and app_secret else {}
    )
    data = _caiyun_http_get('https://api.caiyunapp.com', path, query, headers)
    if data.get('status') != 'ok' or not isinstance(data.get('result'), dict):
        raise RuntimeError('彩云天气数据不可用')
    return data


def _fetch_caiyun_address(latitude: float, longitude: float) -> dict:
    """调用彩云 v3 逆地理编码；该接口无权限时由调用方降级为坐标展示。"""
    app_key, app_secret, token = _caiyun_credentials()
    path = '/v3/cartography/reverse_geocoding'
    query = {'latitude': f'{latitude:.6f}', 'longitude': f'{longitude:.6f}'}
    if app_key and app_secret:
        headers = _caiyun_signature_headers(
            path, query, app_key, app_secret, key_in_header=True,
        )
    else:
        headers = {'Authorization': f'Bearer {token}'}
    headers['Accept-Language'] = 'zh-CN'
    data = _caiyun_http_get('https://singer.caiyunhub.com', path, query, headers)
    address = str(data.get('address') or '').strip()
    name = str(data.get('name') or '').strip()
    if not address and not name:
        raise RuntimeError('彩云逆地理编码未返回地址')
    return {'name': name or address, 'address': address or name, 'resolved': True}


def _as_float(value, default=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _probability_percent(value):
    number = _as_float(value)
    if number is None:
        return None
    # 彩云 v2.6 probability 已是 0-100 的百分数，不能把 0.5/1 再放大百倍。
    return max(0, min(100, int(round(number))))


def _fraction_percent(value):
    """把彩云 0-1 比例字段转换为 0-100 百分数。"""
    number = _as_float(value)
    if number is None:
        return None
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, int(round(number))))


def _normalize_caiyun_weather(data: dict, latitude: float, longitude: float,
                              place: dict, address_warning: Optional[str] = None) -> dict:
    """把彩云上游大对象裁成 GUI 稳定契约。"""
    result = data.get('result') or {}
    realtime = result.get('realtime') or {}
    wind = realtime.get('wind') or {}
    air = realtime.get('air_quality') or {}
    aqi = air.get('aqi') or {}
    air_desc = air.get('description') or {}
    hourly = result.get('hourly') or {}
    daily = result.get('daily') or {}
    minutely = result.get('minutely') or {}
    alert = result.get('alert') or {}

    temperatures = daily.get('temperature') or []
    skycons = daily.get('skycon') or []
    precipitations = daily.get('precipitation') or []
    daily_rows = []
    for index, temp in enumerate(temperatures[:_WEATHER_DAILY_STEPS]):
        if not isinstance(temp, dict):
            continue
        sky = skycons[index] if index < len(skycons) and isinstance(skycons[index], dict) else {}
        precipitation = (
            precipitations[index]
            if index < len(precipitations) and isinstance(precipitations[index], dict)
            else {}
        )
        raw_date = temp.get('date') or sky.get('date') or ''
        daily_rows.append({
            'date': str(raw_date)[:10],
            'skycon': sky.get('value'),
            'temperature_min': _as_float(temp.get('min')),
            'temperature_max': _as_float(temp.get('max')),
            'precipitation_probability': _probability_percent(precipitation.get('probability')),
        })

    def hourly_map(series):
        values = series if isinstance(series, list) else []
        return {
            str(item.get('datetime')): item
            for item in values
            if isinstance(item, dict) and item.get('datetime')
        }

    hourly_temperatures = hourly.get('temperature') or []
    hourly_apparent = hourly.get('apparent_temperature') or []
    hourly_skycons = hourly.get('skycon') or []
    hourly_precipitations = hourly.get('precipitation') or []
    hourly_winds = hourly.get('wind') or []
    hourly_humidity = hourly.get('humidity') or []
    hourly_aqi = (hourly.get('air_quality') or {}).get('aqi') or []
    temperature_by_time = hourly_map(hourly_temperatures)
    apparent_by_time = hourly_map(hourly_apparent)
    skycon_by_time = hourly_map(hourly_skycons)
    precipitation_by_time = hourly_map(hourly_precipitations)
    wind_by_time = hourly_map(hourly_winds)
    humidity_by_time = hourly_map(hourly_humidity)
    aqi_by_time = hourly_map(hourly_aqi)
    hourly_datetimes = sorted(set().union(
        temperature_by_time,
        apparent_by_time,
        skycon_by_time,
        precipitation_by_time,
        wind_by_time,
        humidity_by_time,
        aqi_by_time,
    ))[:_WEATHER_HOURLY_STEPS]

    hourly_rows = []
    for datetime_value in hourly_datetimes:
        temp = temperature_by_time.get(datetime_value, {})
        apparent = apparent_by_time.get(datetime_value, {})
        sky = skycon_by_time.get(datetime_value, {})
        precipitation = precipitation_by_time.get(datetime_value, {})
        wind_row = wind_by_time.get(datetime_value, {})
        humidity_row = humidity_by_time.get(datetime_value, {})
        aqi_row = aqi_by_time.get(datetime_value, {})
        aqi_value = aqi_row.get('value')
        if isinstance(aqi_value, dict):
            aqi_value = aqi_value.get('chn')
        hourly_humidity_value = _as_float(humidity_row.get('value'))
        if hourly_humidity_value is not None:
            hourly_humidity_value = max(
                0,
                min(100, int(round(
                    hourly_humidity_value * 100
                    if hourly_humidity_value <= 1 else hourly_humidity_value
                ))),
            )
        hourly_rows.append({
            'datetime': datetime_value,
            'temperature': _as_float(temp.get('value')),
            'apparent_temperature': _as_float(apparent.get('value')),
            'skycon': sky.get('value'),
            'precipitation': _as_float(precipitation.get('value')),
            'precipitation_probability': _probability_percent(precipitation.get('probability')),
            'humidity': hourly_humidity_value,
            'wind_speed': _as_float(wind_row.get('speed')),
            'wind_direction': _as_float(wind_row.get('direction')),
            'aqi': _as_float(aqi_value),
        })

    alert_content = alert.get('content') if isinstance(alert, dict) else None
    alert_payload_ok = (
        isinstance(alert, dict)
        and alert.get('status') == 'ok'
        and isinstance(alert_content, list)
    )
    alert_rows = []
    for index, item in enumerate(alert_content if alert_payload_ok else []):
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        description = str(item.get('description') or '').strip()
        if not title and not description:
            continue
        alert_rows.append({
            'id': str(item.get('alertId') or '|'.join((
                str(item.get('code') or ''),
                str(item.get('location') or ''),
                str(item.get('pubtimestamp') or ''),
                str(index),
            ))),
            'title': title or '气象预警',
            'description': description,
            'code': str(item.get('code') or ''),
            'status': str(item.get('status') or ''),
            'location': str(item.get('location') or ''),
            'source': str(item.get('source') or ''),
            'published_at': int(_as_float(item.get('pubtimestamp'), 0) or 0),
        })
    # 明确空列表才代表“当前无预警”；若上游声称有内容但一条也无法解析，
    # 应落到“预警数据不可用”，不能给用户错误的安全结论。
    alerts_available = bool(
        alert_payload_ok and (not alert_content or alert_rows)
    )

    humidity = _as_float(realtime.get('humidity'))
    if humidity is not None:
        humidity = max(0, min(100, int(round(humidity * 100 if humidity <= 1 else humidity))))

    pressure = _as_float(realtime.get('pressure'))
    if pressure is not None and pressure > 2000:
        pressure = pressure / 100
    precipitation = realtime.get('precipitation') or {}
    local_precipitation = precipitation.get('local') or {}
    nearest_precipitation = precipitation.get('nearest') or {}
    life_index = realtime.get('life_index') or {}
    ultraviolet = life_index.get('ultraviolet') or {}
    comfort = life_index.get('comfort') or {}

    return {
        'success': True,
        'source': '彩云天气',
        'updated_at': int(data.get('server_time') or time.time()),
        'location': {
            'latitude': round(latitude, 6),
            'longitude': round(longitude, 6),
            **place,
        },
        'realtime': {
            'temperature': _as_float(realtime.get('temperature')),
            'apparent_temperature': _as_float(realtime.get('apparent_temperature')),
            'humidity': humidity,
            'skycon': realtime.get('skycon'),
            'wind_speed': _as_float(wind.get('speed')),
            'wind_direction': _as_float(wind.get('direction')),
            'visibility': _as_float(realtime.get('visibility')),
            'pressure': pressure,
            'cloudrate': _fraction_percent(realtime.get('cloudrate')),
            'precipitation_intensity': _as_float(local_precipitation.get('intensity')),
            'nearest_precipitation_distance': _as_float(nearest_precipitation.get('distance')),
            'aqi': _as_float(aqi.get('chn')),
            'aqi_description': air_desc.get('chn'),
            'pm25': _as_float(air.get('pm25')),
            'pm10': _as_float(air.get('pm10')),
            'uv_description': ultraviolet.get('desc'),
            'comfort_description': comfort.get('desc'),
        },
        'forecast_keypoint': result.get('forecast_keypoint'),
        'hourly_description': hourly.get('description'),
        'minutely_description': minutely.get('description'),
        'hourly': hourly_rows,
        'daily': daily_rows,
        'alerts': alert_rows,
        'alerts_available': alerts_available,
        'alerts_total': len(alert_rows),
        'address_warning': address_warning,
        'cached': False,
    }


def _get_caiyun_weather(latitude: float, longitude: float, force: bool = False,
                        fixed_address: Optional[str] = None) -> dict:
    """10 分钟内复用同一约 10 米坐标的结果，手动刷新可 force 跳过。"""
    key = (round(latitude, 4), round(longitude, 4), fixed_address or '')
    now = time.time()
    if not force:
        with _weather_cache_lock:
            entry = _weather_cache.get(key)
            if entry and now - entry['fetched_at'] < _WEATHER_CACHE_TTL:
                return {**entry['data'], 'cached': True}

    if fixed_address:
        raw = _fetch_caiyun_weather_raw(latitude, longitude)
        place = {
            'name': fixed_address,
            'address': fixed_address,
            'resolved': True,
        }
        address_warning = None
    else:
        # 天气与地址是彼此独立的上游接口，并发请求可把最坏等待从两次超时之和压到一次超时。
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='caiyun-weather') as executor:
            weather_future = executor.submit(_fetch_caiyun_weather_raw, latitude, longitude)
            address_future = executor.submit(_fetch_caiyun_address, latitude, longitude)
            raw = weather_future.result()
            address_warning = None
            try:
                place = address_future.result()
            except Exception as exc:
                logging.warning('彩云逆地理编码失败，天气仍正常返回: %s', exc)
                place = {
                    'name': '当前位置',
                    'address': f'{latitude:.4f}, {longitude:.4f}',
                    'resolved': False,
                }
                address_warning = '当前彩云套餐未返回地址，已显示定位坐标'

    contract = _normalize_caiyun_weather(raw, latitude, longitude, place, address_warning)
    with _weather_cache_lock:
        expired = [k for k, v in _weather_cache.items()
                   if now - v.get('fetched_at', 0) >= _WEATHER_CACHE_TTL]
        for expired_key in expired:
            _weather_cache.pop(expired_key, None)
        if len(_weather_cache) >= _WEATHER_CACHE_MAX:
            oldest = min(_weather_cache, key=lambda k: _weather_cache[k].get('fetched_at', 0))
            _weather_cache.pop(oldest, None)
        _weather_cache[key] = {'fetched_at': now, 'data': contract}
    return contract


def _tail_file(path: str, n: int):
    """读取文件最后 n 行（块读法，几 MB 日志够用）。"""
    n = max(1, n)
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        block = 8192
        data = b''
        while size > 0 and data.count(b'\n') <= n:
            read = min(block, size)
            f.seek(size - read)
            data = f.read(read) + data
            size -= read
        lines = data.splitlines()[-n:]
    out = []
    for line in lines:
        for enc in ('utf-8', 'gbk', 'gb18030', 'latin1'):
            try:
                out.append(line.decode(enc))
                break
            except UnicodeDecodeError:
                continue
        else:
            out.append(line.decode('utf-8', errors='replace'))
    return out


def _decode_log_line(raw: bytes) -> str:
    """把一行原始日志字节按多编码尝试解码（兜底 replace）。"""
    for enc in ('utf-8', 'gbk', 'gb18030', 'latin1'):
        try:
            return raw.decode(enc).rstrip('\r\n')
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace').rstrip('\r\n')


async def _log_follower(event_bus: EventBus, stop_event: asyncio.Event):
    """异步追踪日志文件末尾，新行推送到 ``log:stream`` 通道。

    轮询式 tail：每轮短暂 open→seek(offset)→read→close，绝不长期持有文件句柄。
    原因：Windows 下普通 open 不带 FILE_SHARE_DELETE，长持句柄会让同进程
    RotatingFileHandler 的 os.rename 轮转抛 PermissionError，导致日志达 5MB 后
    文件日志永久断流、GUI 日志流随之死掉。
    - 文件不存在/被删 → 继续等待而非 return；
    - 文件变小（被轮转/截断）→ offset 归零从头重读，跟上新文件。
    """
    offset = 0
    primed = False  # 首轮只定位到末尾、不回放历史
    while not stop_event.is_set():
        try:
            if not os.path.exists(LOG_FILE):
                # 文件尚未生成或刚被轮转替换的瞬间：重置游标，等待下一轮
                offset = 0
                primed = False
                await asyncio.sleep(0.5)
                continue

            size = os.path.getsize(LOG_FILE)
            if not primed:
                # 启动时不回放整段历史日志，仅从当前末尾开始跟踪
                offset = size
                primed = True
                await asyncio.sleep(0.5)
                continue

            if size < offset:
                # 文件变小：被 RotatingFileHandler 轮转或被清空 → 从头重读新文件
                offset = 0

            if size == offset:
                await asyncio.sleep(0.5)
                continue

            with open(LOG_FILE, 'rb') as f:
                f.seek(offset)
                chunk = f.read()
                offset = f.tell()

            for raw in chunk.splitlines():
                await event_bus.publish('log:stream', {'line': _decode_log_line(raw)})
        except Exception:
            logging.exception("log follower iteration failed")
            await asyncio.sleep(1.0)


# ----------------------------------------------------------------------------
# Flask app
# ----------------------------------------------------------------------------

def _build_flask_app(app_core, bridge: AsyncioBridge,
                     event_bus: EventBus, token: str) -> Flask:
    app = Flask(__name__)
    require_token = _make_require_token(token)

    # CORS（仅 localhost / file:// 白名单放行，便于 Electron 渲染进程跨源调用）
    # [M72 修复] 原先恒发 Access-Control-Allow-Origin: '*'（注释却写"仅 localhost 放行"，名实不符），
    # 任意外部网页 JS 都能跨源读取本机服务响应、探测服务存在。改为按 Origin 白名单回显：
    # 仅放行 Electron 渲染进程的来源——生产 file://（fetch 时 Origin 为字面量 'null'）、
    # 开发 Vite http://localhost:* / http://127.0.0.1:*。非白名单 Origin 不回显 ACAO，浏览器即拦下
    # 跨源读取。无 Origin 头的请求（同源资源加载、非浏览器调用）不受影响。
    def _origin_allowed(origin: str) -> bool:
        if not origin:
            return False
        if origin == 'null':  # file:// 页面发起的 fetch，Origin 为字面量 'null'
            return True
        return (
            origin.startswith('http://localhost')
            or origin.startswith('http://127.0.0.1')
            or origin.startswith('https://localhost')
            or origin.startswith('https://127.0.0.1')
            or origin.startswith('file://')
        )

    @app.after_request
    def _cors(resp):
        origin = request.headers.get('Origin', '')
        if _origin_allowed(origin):
            resp.headers['Access-Control-Allow-Origin'] = origin
            resp.headers['Vary'] = 'Origin'
        resp.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'
        return resp

    @app.before_request
    def _preflight():
        if request.method == 'OPTIONS':
            return '', 204

    # 健康探针，不需鉴权
    @app.get('/api/v1/ping')
    def ping():
        return jsonify({'ok': True, 'service': 'auto-attendance-gui-backend'})

    @app.get('/api/v1/status')
    @require_token
    def get_status():
        try:
            snap = app_core.get_status_snapshot()
            return jsonify(snap)
        except Exception as e:
            logging.exception("get_status failed")
            return jsonify({'error': str(e)}), 500

    @app.get('/api/v1/logs/tail')
    @require_token
    def get_logs_tail():
        try:
            lines = int(request.args.get('lines', 200))
        except ValueError:
            lines = 200
        lines = max(1, min(lines, 5000))
        if not os.path.exists(LOG_FILE):
            return jsonify({'lines': [], 'file': LOG_FILE})
        try:
            return jsonify({'lines': _tail_file(LOG_FILE, lines), 'file': LOG_FILE})
        except Exception as e:
            logging.exception("logs tail failed")
            return jsonify({'error': str(e)}), 500

    # ----- 彩云天气（固定地址可直接传入，避免额外调用逆地理编码）-----
    @app.post('/api/v1/weather')
    @require_token
    def get_weather():
        body = request.get_json(silent=True) or {}
        try:
            latitude = float(body.get('latitude'))
            longitude = float(body.get('longitude'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'latitude / longitude 必须是数字'}), 400
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return jsonify({'success': False, 'error': '经纬度超出合法范围'}), 400
        force = body.get('force') is True
        fixed_address = body.get('address')
        if fixed_address is not None and not isinstance(fixed_address, str):
            return jsonify({'success': False, 'error': 'address 必须是字符串'}), 400
        fixed_address = (fixed_address or '').strip()
        if len(fixed_address) > 120:
            return jsonify({'success': False, 'error': 'address 长度不能超过 120 个字符'}), 400
        try:
            return jsonify(_get_caiyun_weather(
                latitude,
                longitude,
                force=force,
                fixed_address=fixed_address or None,
            ))
        except _CaiyunConfigError as exc:
            return jsonify({
                'success': False,
                'code': 'missing_credentials',
                'error': str(exc),
            }), 503
        except Exception:
            logging.exception('get_weather failed')
            return jsonify({
                'success': False,
                'code': 'upstream_error',
                'error': '彩云天气请求失败，请稍后重试',
            }), 502

    # ----- 汇率（Yahoo CNY->JPY）-----
    @app.get('/api/v1/exchange-rate')
    @require_token
    def get_exchange_rate():
        """返回 CNY->JPY 汇率契约（最新价 + 历史序列）。

        query: range=7d|30d|quarter|year|3y（非法回退 30d）、force=0|1（1 跳过 TTL 立即拉）。
        失败也返回 200 + 旧缓存；彻底无数据时 latest:null、points:[]。
        """
        range_ = request.args.get('range', '30d')
        force = request.args.get('force', '0') in ('1', 'true', 'True')
        try:
            from modules.exchange_rate_service import get_exchange_rate as _ger
            data = _ger(range_, force=force)
            return jsonify(data)
        except Exception:
            logging.exception("get_exchange_rate failed")
            # 即便彻底异常也返回 200 + 空结构，避免前端报错
            return jsonify({
                'base': 'CNY', 'quote': 'JPY', 'range': range_,
                'updated_at': None, 'latest': None, 'points': [],
            })

    # ----- 日历信息（休班标记/最近休息日/下一假期/调休补班）-----
    @app.get('/api/v1/calendar-info')
    @require_token
    def get_calendar_info():
        """返回当月日历契约（chinese_calendar 数据缺失时回退仅双休）。

        query: after=YYYY-MM-DD（可选）—— 额外返回该日之后的首个工作日
        （workday_after，「请假中」状态计算销假上班日用）。
        """
        try:
            from modules.calendar_info_service import get_calendar_info as _gci
            return jsonify(_gci(after=request.args.get('after') or None))
        except Exception:
            logging.exception("get_calendar_info failed")
            import datetime as _dt
            _t = _dt.date.today()
            return jsonify({
                'available': False, 'today': _t.isoformat(),
                'year': _t.year, 'month': _t.month, 'days': [], 'week': [],
                'nearest_rest': None, 'next_holidays': [], 'next_makeup': [],
                'workday_after': None, 'coverage_end': None,
            })

    # ----- Error logs (分页) -----
    @app.get('/api/v1/logs/errors')
    @require_token
    def get_error_logs():
        from modules.services.log_service import get_recent_errors
        try:
            page = max(1, int(request.args.get('page', 1)))
            per_page = max(1, min(int(request.args.get('per_page', 5)), 20))
        except ValueError:
            page, per_page = 1, 5
        try:
            res = get_recent_errors(LOG_FILE, page=page, per_page=per_page)
            return jsonify(res)
        except Exception as e:
            logging.exception("get_error_logs failed")
            return jsonify({'error': str(e)}), 500

    # ----- Config full read / write -----
    @app.get('/api/v1/config/all')
    @require_token
    def get_config_all():
        env = _read_env_file('.env')
        masked = {}
        for k, v in env.items():
            if k in ENV_SENSITIVE_FIELDS:
                masked[k] = ('•' * 8) if v else ''
                masked[f'{k}__has'] = bool(v)
            else:
                masked[k] = v
        return jsonify({'env': masked, 'whitelist': sorted(ENV_WRITE_WHITELIST)})

    @app.patch('/api/v1/config')
    @require_token
    def patch_config():
        body = request.get_json(silent=True) or {}
        patch = body.get('patch') if isinstance(body.get('patch'), dict) else body
        if not isinstance(patch, dict):
            return jsonify({'success': False, 'error': '请求体应为字段字典或 {patch: {...}}'}), 400
        invalid = [k for k in patch.keys() if k not in ENV_WRITE_WHITELIST]
        if invalid:
            return jsonify({'success': False, 'error': f'以下字段不在白名单: {invalid}'}), 400
        try:
            new_env = _write_env_atomic(patch)
            # 遮罩敏感字段后返回
            masked = {k: ('•' * 8 if k in ENV_SENSITIVE_FIELDS and v else v) for k, v in new_env.items()}
            return jsonify({
                'success': True,
                'env': masked,
                'note': '已写入 .env（.env.bak 已备份）。**多数字段需重启 main.py 生效**。',
            })
        except Exception as e:
            logging.exception("patch_config failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- System control -----
    @app.post('/api/v1/system/restart')
    @require_token
    def system_restart():
        """记录重启请求并广播事件（扩展点）。当前桌面壳的实际重启走 Electron 的服务控制（AAS_SERVICE.restart），不消费此事件。"""
        event_bus.publish_threadsafe('system:restart_requested', {'ts': time.time()})
        return jsonify({'success': True, 'note': '已记录重启请求；桌面端实际重启由窗口内的服务控制按钮执行'})

    # ----- 微信 Bark 转发 -----
    def _wb():
        return getattr(app_core, 'wechat_bark', None)

    @app.get('/api/v1/wechat-bark/status')
    @require_token
    def wechat_bark_status():
        svc = _wb()
        if svc is None:
            return jsonify({'error': '微信 Bark 服务未初始化'}), 500
        return jsonify(svc.status())

    @app.get('/api/v1/wechat-bark/config')
    @require_token
    def wechat_bark_get_config():
        svc = _wb()
        if svc is None:
            return jsonify({'error': '微信 Bark 服务未初始化'}), 500
        try:
            return jsonify({'config': svc.load_config(), 'config_path': svc.config_path()})
        except Exception as e:
            logging.exception("wechat_bark_get_config failed")
            return jsonify({'error': str(e)}), 500

    @app.put('/api/v1/wechat-bark/config')
    @require_token
    def wechat_bark_save_config():
        svc = _wb()
        if svc is None:
            return jsonify({'success': False, 'error': '微信 Bark 服务未初始化'}), 500
        body = request.get_json(silent=True) or {}
        config = body.get('config') if isinstance(body.get('config'), dict) else body
        if not isinstance(config, dict):
            return jsonify({'success': False, 'error': '请求体应为配置字典或 {config: {...}}'}), 400
        try:
            saved = svc.save_config(config)
            return jsonify({
                'success': True,
                'config': saved,
                'config_path': svc.config_path(),
                'note': '配置已保存；正在运行的监听会在下次启动时使用新配置',
            })
        except ValueError as e:
            # 字段校验失败（如开始时间晚于结束时间），文案直接回给用户
            return jsonify({'success': False, 'error': str(e)}), 400
        except Exception as e:
            logging.exception("wechat_bark_save_config failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.post('/api/v1/wechat-bark/start')
    @require_token
    def wechat_bark_start():
        svc = _wb()
        if svc is None:
            return jsonify({'success': False, 'error': '微信 Bark 服务未初始化'}), 500
        return jsonify(svc.start())

    @app.post('/api/v1/wechat-bark/stop')
    @require_token
    def wechat_bark_stop():
        svc = _wb()
        if svc is None:
            return jsonify({'success': False, 'error': '微信 Bark 服务未初始化'}), 500
        return jsonify(svc.stop())

    @app.post('/api/v1/wechat-bark/test')
    @require_token
    def wechat_bark_test():
        svc = _wb()
        if svc is None:
            return jsonify({'success': False, 'error': '微信 Bark 服务未初始化'}), 500
        return jsonify(svc.test_bark())

    @app.get('/api/v1/wechat-bark/schedule')
    @require_token
    def wechat_bark_schedule():
        svc = _wb()
        if svc is None:
            return jsonify({'success': False, 'error': '微信 Bark 服务未初始化'}), 500
        return jsonify(svc.check_schedule())

    @app.get('/api/v1/wechat-bark/apps')
    @require_token
    def wechat_bark_apps():
        svc = _wb()
        if svc is None:
            return jsonify({'success': False, 'error': '微信 Bark 服务未初始化'}), 500
        return jsonify(svc.list_apps())

    # ----- 内置网络加速（mihomo）-----
    def _pm():
        return getattr(app_core, 'proxy_manager', None)

    @app.get('/api/v1/proxy/config')
    @require_token
    def get_proxy_config():
        pm = _pm()
        if pm is None:
            return jsonify({'error': '代理管理未初始化'}), 500
        try:
            return jsonify(pm.status())
        except Exception as e:
            logging.exception("get_proxy_config failed")
            return jsonify({'error': str(e)}), 500

    @app.put('/api/v1/proxy/config')
    @require_token
    def put_proxy_config():
        from modules.config import config as cfg
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        body = request.get_json(silent=True) or {}
        patch = {}
        for key in ('local_port', 'api_port'):
            if key in body:
                try:
                    patch[key] = int(body[key])
                except (TypeError, ValueError):
                    pass
        toggling = 'enabled' in body
        if toggling:
            patch['enabled'] = bool(body['enabled'])
        note = None
        try:
            cfg.set_proxy_config(patch)
            if toggling and patch['enabled']:
                ok, msg = pm.start()
                note = ('内置加速已启动。' if ok else f'启动失败：{msg}')
            elif toggling and not patch['enabled']:
                pm.stop()
                note = '内置加速已停止，后台请求回到直连。'
            elif pm.is_running():
                pm.reload()
            event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': True, 'config': pm.status(), 'note': note})
        except Exception as e:
            logging.exception("put_proxy_config failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.post('/api/v1/proxy/subscription')
    @require_token
    def set_proxy_subscription():
        from modules.config import config as cfg
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        body = request.get_json(silent=True) or {}
        url = (body.get('url') or '').strip()
        if not url:
            return jsonify({'success': False, 'error': '订阅 URL 为空'}), 400
        try:
            pm.set_subscription(url)
            node_count = None
            if cfg.get_proxy_enabled():
                ok, msg = pm.reload()
                if not ok:
                    return jsonify({'success': False, 'error': msg}), 500
                try:
                    node_count = len(pm.list_nodes().get('nodes', []))
                except Exception:
                    node_count = None
            event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': True, 'node_count': node_count, 'config': pm.status()})
        except Exception as e:
            logging.exception("set_proxy_subscription failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.post('/api/v1/proxy/config-text')
    @require_token
    def set_proxy_config_text():
        from modules.config import config as cfg
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        body = request.get_json(silent=True) or {}
        text = body.get('text') or ''
        if not text.strip():
            return jsonify({'success': False, 'error': '配置内容为空'}), 400
        try:
            pm.set_config_text(text)
            node_count = None
            if cfg.get_proxy_enabled():
                ok, msg = pm.reload()
                if not ok:
                    return jsonify({'success': False, 'error': msg}), 500
                try:
                    node_count = len(pm.list_nodes().get('nodes', []))
                except Exception:
                    node_count = None
            event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': True, 'node_count': node_count, 'config': pm.status()})
        except Exception as e:
            logging.exception("set_proxy_config_text failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.get('/api/v1/proxy/nodes')
    @require_token
    def get_proxy_nodes():
        pm = _pm()
        if pm is None:
            return jsonify({'error': '代理管理未初始化'}), 500
        try:
            if not pm.is_running():
                return jsonify({'group': None, 'selected': None, 'nodes': [], 'running': False})
            data = pm.list_nodes()
            data['running'] = True
            return jsonify(data)
        except Exception as e:
            logging.exception("get_proxy_nodes failed")
            return jsonify({'error': str(e)}), 500

    @app.post('/api/v1/proxy/select')
    @require_token
    def select_proxy_node():
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        body = request.get_json(silent=True) or {}
        name = body.get('name') or ''
        if not name:
            return jsonify({'success': False, 'error': '节点名为空'}), 400
        try:
            ok = pm.select_node(name)
            return jsonify({'success': bool(ok), 'selected': name})
        except Exception as e:
            logging.exception("select_proxy_node failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.post('/api/v1/proxy/test-delay')
    @require_token
    def test_proxy_delay():
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        body = request.get_json(silent=True) or {}
        name = body.get('name') or ''
        if not name:
            return jsonify({'success': False, 'error': '节点名为空'}), 400
        try:
            delay = pm.test_delay(name)
            return jsonify({'success': delay is not None, 'name': name, 'delay': delay})
        except Exception as e:
            logging.exception("test_proxy_delay failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.get('/api/v1/proxy/traffic')
    @require_token
    def get_proxy_traffic():
        pm = _pm()
        if pm is None or not pm.is_running():
            return jsonify({'up': 0, 'down': 0, 'up_total': 0, 'down_total': 0})
        try:
            return jsonify(pm.get_traffic())
        except Exception as e:
            logging.exception("get_proxy_traffic failed")
            return jsonify({'error': str(e)}), 500

    @app.post('/api/v1/proxy/fetch-core')
    @require_token
    def fetch_proxy_core():
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        body = request.get_json(silent=True) or {}
        mirror = (body.get('mirror') or '').strip() or None
        try:
            ok, msg = pm.fetch_core(mirror=mirror)
            if ok:
                event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': bool(ok), 'message': msg, 'config': pm.status()})
        except Exception as e:
            logging.exception("fetch_proxy_core failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- 内置网络加速：多配置文件管理 -----
    @app.get('/api/v1/proxy/profiles')
    @require_token
    def list_proxy_profiles():
        pm = _pm()
        if pm is None:
            return jsonify({'error': '代理管理未初始化'}), 500
        try:
            return jsonify(pm.list_profiles())
        except Exception as e:
            logging.exception("list_proxy_profiles failed")
            return jsonify({'error': str(e)}), 500

    @app.post('/api/v1/proxy/profiles')
    @require_token
    def add_proxy_profile():
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        body = request.get_json(silent=True) or {}
        type_ = (body.get('type') or '').strip()
        name = body.get('name')
        url = body.get('url')
        content = body.get('content')
        try:
            ok, prof, msg = pm.add_profile(type_, name=name, url=url, content=content)
            if not ok:
                return jsonify({'success': False, 'error': msg}), 400
            event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': True, 'profile': prof})
        except Exception as e:
            logging.exception("add_proxy_profile failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.post('/api/v1/proxy/profiles/<pid>/refresh')
    @require_token
    def refresh_proxy_profile(pid):
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        try:
            ok, prof, msg = pm.refresh_profile(pid)
            if not ok:
                return jsonify({'success': False, 'error': msg}), 400
            event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': True, 'profile': prof})
        except Exception as e:
            logging.exception("refresh_proxy_profile failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.post('/api/v1/proxy/profiles/<pid>/select')
    @require_token
    def select_proxy_profile(pid):
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        try:
            ok, msg = pm.select_profile(pid)
            if not ok:
                return jsonify({'success': False, 'error': msg}), 400
            event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': True, 'active_id': pid})
        except Exception as e:
            logging.exception("select_proxy_profile failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.delete('/api/v1/proxy/profiles/<pid>')
    @require_token
    def delete_proxy_profile(pid):
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        try:
            ok, msg = pm.delete_profile(pid)
            if not ok:
                return jsonify({'success': False, 'error': msg}), 400
            event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': True})
        except Exception as e:
            logging.exception("delete_proxy_profile failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.get('/api/v1/proxy/profiles/<pid>/content')
    @require_token
    def get_proxy_profile_content(pid):
        pm = _pm()
        if pm is None:
            return jsonify({'error': '代理管理未初始化'}), 500
        try:
            content = pm.get_profile_content(pid)
            return jsonify({'content': content})
        except Exception as e:
            logging.exception("get_proxy_profile_content failed")
            return jsonify({'content': '', 'error': str(e)}), 500

    @app.put('/api/v1/proxy/profiles/<pid>')
    @require_token
    def update_proxy_profile(pid):
        pm = _pm()
        if pm is None:
            return jsonify({'success': False, 'error': '代理管理未初始化'}), 500
        body = request.get_json(silent=True) or {}
        name = body.get('name')
        content = body.get('content')
        try:
            ok, prof, msg = pm.update_profile(pid, name=name, content=content)
            if not ok:
                return jsonify({'success': False, 'error': msg}), 400
            event_bus.publish_threadsafe('proxy:status', pm.status())
            return jsonify({'success': True, 'profile': prof})
        except Exception as e:
            logging.exception("update_proxy_profile failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    return app


# ----------------------------------------------------------------------------
# WebSocket
# ----------------------------------------------------------------------------

def _ws_extract_token(websocket) -> str:
    # websockets 11+: websocket.request.path / websocket.request.headers
    # 旧版本：websocket.path
    path = ''
    try:
        req = getattr(websocket, 'request', None)
        if req is not None:
            path = getattr(req, 'path', '') or ''
        if not path:
            path = getattr(websocket, 'path', '') or ''
    except Exception:
        path = ''
    if '?' in path:
        qs = path.split('?', 1)[1]
        for kv in qs.split('&'):
            if kv.startswith('token='):
                return kv[len('token='):]
    return ''


async def _ws_handler(event_bus: EventBus, token: str, websocket):
    given = _ws_extract_token(websocket)
    authorized = bool(given) and secrets.compare_digest(given, token)
    if not authorized:
        # 也允许首条消息携带 {"token":"..."}
        try:
            first = await asyncio.wait_for(websocket.recv(), timeout=5)
            msg = json.loads(first)
            if isinstance(msg, dict) and secrets.compare_digest(str(msg.get('token', '')), token):
                authorized = True
        except Exception:
            pass
    if not authorized:
        try:
            await websocket.close(code=1008, reason='unauthorized')
        except Exception:
            pass
        return

    queue = event_bus.subscribe(maxsize=500)
    try:
        await websocket.send(json.dumps({
            'channel': 'system:hello',
            'data': {'service': 'auto-attendance-gui-backend'},
            'ts': time.time(),
        }))
        while True:
            msg = await queue.get()
            try:
                await websocket.send(json.dumps(msg, ensure_ascii=False, default=str))
            except Exception:
                break
    except Exception:
        pass
    finally:
        event_bus.unsubscribe(queue)


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

async def start(app_core,
                loop: Optional[asyncio.AbstractEventLoop] = None,
                http_port: int = 8765,
                ws_port: int = 8766):
    """启动 GUI 后端服务（必须在主 asyncio loop 内 ``await`` 调用）。

    返回 dict：``{token, http_port, ws_port, event_bus, stop}``。
    ``stop`` 是普通函数（线程安全），可在任意上下文调用。
    """
    if websockets is None:
        raise RuntimeError(
            f"缺少 websockets 依赖，请 pip install websockets。原始错误: {_IMPORT_ERR}"
        )

    if loop is None:
        loop = asyncio.get_running_loop()

    token = _ensure_token()
    event_bus = EventBus(loop)
    bridge = AsyncioBridge(loop)

    # 注入 event_bus 到 app_core，供后台定时任务向 GUI 推送更新
    app_core._event_bus = event_bus
    wb = getattr(app_core, 'wechat_bark', None)
    if wb is not None:
        wb.attach_event_bus(event_bus)

    app = _build_flask_app(app_core, bridge, event_bus, token)

    def _serve_http():
        try:
            logging.info("GUI HTTP server listening on 127.0.0.1:%s", http_port)
            # threads 默认仅 4：耗时较长的接口（如上游网络请求慢）会占住工作线程，
            # 4 个被占满后连无鉴权的 /ping 都排队无响应，GUI 端表现为后端整体失联。
            # 提到 16 以缓解长接口对短接口（状态/ping）的饥饿。
            waitress.serve(app, host='127.0.0.1', port=http_port, ident='aas-gui', threads=16)
        except Exception:
            logging.exception("waitress server crashed")

    http_thread = threading.Thread(target=_serve_http, name='aas-gui-http', daemon=True)
    http_thread.start()

    stop_event = asyncio.Event()

    # WS server 与日志追踪都在主 loop 内启动，直接 await/create_task
    async def _ws_handler_wrap(websocket):
        await _ws_handler(event_bus, token, websocket)

    ws_server = await websockets.serve(_ws_handler_wrap, '127.0.0.1', ws_port)
    logging.info("GUI WebSocket server listening on 127.0.0.1:%s", ws_port)

    follower_task = asyncio.create_task(_log_follower(event_bus, stop_event))

    logging.info("GUI 后端就绪 — token 已写入 %s", TOKEN_FILE)

    def stop():
        """关停（线程安全）。"""
        async def _do():
            stop_event.set()
            ws_server.close()
            await ws_server.wait_closed()
        try:
            # 如果在主 loop 内调用，schedule 一下；否则用 threadsafe
            try:
                running = asyncio.get_running_loop()
                if running is loop:
                    loop.create_task(_do())
                    return
            except RuntimeError:
                pass
            asyncio.run_coroutine_threadsafe(_do(), loop).result(timeout=5)
        except Exception:
            logging.exception("stop GUI backend failed")

    return {
        'token': token,
        'http_port': http_port,
        'ws_port': ws_port,
        'event_bus': event_bus,
        'stop': stop,
        '_follower_task': follower_task,
        '_ws_server': ws_server,
    }
