"""
Web 服务模块 — 为 GUI（Electron）提供 REST + WebSocket 接口

设计要点：
- Flask + waitress 在 daemon 线程运行（同步），处理 REST 请求
- websockets server 在主 asyncio 事件循环（异步），处理实时推送
- 共用 AttendanceSystem 单例（线程↔loop 通信走 run_coroutine_threadsafe）
- event_bus 是 pub/sub，每个 WS 连接订阅一个独立 asyncio.Queue
- Bearer token 鉴权（启动时生成、写入 logs/.gui_token）
- 仅监听 127.0.0.1
"""

import os
import json
import time
import asyncio
import logging
import threading
import secrets
import functools
from typing import Any, Optional, Set

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
LOG_FILE = os.path.join('logs', 'attendance_system.log')


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
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def call(self, coro, timeout: float = 15.0):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)


# ----------------------------------------------------------------------------
# Token auth
# ----------------------------------------------------------------------------

def _ensure_token() -> str:
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    token = secrets.token_urlsafe(32)
    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        f.write(token)
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
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


async def _log_follower(event_bus: EventBus, stop_event: asyncio.Event):
    """异步追踪日志文件末尾，新行推送到 ``log:stream`` 通道。"""
    if not os.path.exists(LOG_FILE):
        logging.warning("log file not found, follower will idle: %s", LOG_FILE)
        return
    try:
        with open(LOG_FILE, 'rb') as f:
            f.seek(0, os.SEEK_END)
            while not stop_event.is_set():
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                text = None
                for enc in ('utf-8', 'gbk', 'gb18030', 'latin1'):
                    try:
                        text = line.decode(enc).rstrip('\r\n')
                        break
                    except UnicodeDecodeError:
                        continue
                if text is None:
                    text = line.decode('utf-8', errors='replace').rstrip('\r\n')
                await event_bus.publish('log:stream', {'line': text})
    except Exception:
        logging.exception("log follower crashed")


# ----------------------------------------------------------------------------
# Flask app
# ----------------------------------------------------------------------------

def _build_flask_app(attendance_system, bridge: AsyncioBridge,
                     event_bus: EventBus, token: str) -> Flask:
    app = Flask(__name__)
    require_token = _make_require_token(token)

    # CORS（仅 localhost 自由放行，便于 Electron 渲染进程跨源调用）
    @app.after_request
    def _cors(resp):
        resp.headers['Access-Control-Allow-Origin'] = '*'
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
            snap = attendance_system.get_status_snapshot()
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

    @app.post('/api/v1/punch/in')
    @require_token
    def punch_in():
        body = request.get_json(silent=True) or {}
        username = body.get('username')
        try:
            ok, msg = bridge.call(
                attendance_system.start_punch_operation('punch_in', username),
                timeout=15,
            )
            return jsonify({'success': bool(ok), 'message': msg})
        except Exception as e:
            logging.exception("punch_in failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.post('/api/v1/punch/out')
    @require_token
    def punch_out():
        body = request.get_json(silent=True) or {}
        username = body.get('username')
        try:
            ok, msg = bridge.call(
                attendance_system.start_punch_operation('punch_out', username),
                timeout=15,
            )
            return jsonify({'success': bool(ok), 'message': msg})
        except Exception as e:
            logging.exception("punch_out failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.post('/api/v1/operation/stop')
    @require_token
    def operation_stop():
        try:
            ok, msg = bridge.call(
                attendance_system.cancel_current_operation(), timeout=15
            )
            return jsonify({'success': bool(ok), 'message': msg})
        except Exception as e:
            logging.exception("operation_stop failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.get('/api/v1/config/mode')
    @require_token
    def get_mode():
        from modules.config import config as cfg
        return jsonify({
            'use_selenium_login': cfg.get_use_selenium_login(),
            'selenium_headless': cfg.get_selenium_headless(),
        })

    @app.put('/api/v1/config/mode')
    @require_token
    def put_mode():
        body = request.get_json(silent=True) or {}
        patch = {}
        if 'use_selenium_login' in body:
            patch['USE_SELENIUM_LOGIN'] = bool(body['use_selenium_login'])
        if 'selenium_headless' in body:
            patch['SELENIUM_HEADLESS'] = bool(body['selenium_headless'])
        try:
            updated = attendance_system.update_dynamic_config(patch)
            return jsonify({'success': True, 'config': updated})
        except Exception as e:
            logging.exception("put_mode failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.get('/api/v1/tasks')
    @require_token
    def list_tasks():
        return jsonify({'tasks': attendance_system.task_manager.get_tasks()})

    @app.delete('/api/v1/tasks/<int:task_id>')
    @require_token
    def del_task(task_id):
        ok = attendance_system.task_manager.remove_task_by_id(task_id)
        event_bus.publish_threadsafe('task:changed', {'op': 'delete', 'id': task_id})
        return jsonify({'success': bool(ok), 'task_id': task_id})

    @app.get('/api/v1/users')
    @require_token
    def list_users():
        users = []
        for u in attendance_system.users:
            users.append({
                'username': u.get('username'),
                'env_key': u.get('env_key'),
            })
        return jsonify({'users': users})

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

async def start(attendance_system,
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

    # 注入 event_bus 到 attendance_system，供 send_notification 头部 publish
    attendance_system._event_bus = event_bus

    app = _build_flask_app(attendance_system, bridge, event_bus, token)

    def _serve_http():
        try:
            logging.info("GUI HTTP server listening on 127.0.0.1:%s", http_port)
            waitress.serve(app, host='127.0.0.1', port=http_port, ident='aas-gui')
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
