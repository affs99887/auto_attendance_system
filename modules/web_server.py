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
import tempfile
import re
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Optional, Set

from flask import Flask, request, jsonify, send_file
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

# 允许通过 PATCH /api/v1/config 写入 .env 的字段白名单
# （登录账号/Telegram token 等敏感字段也允许，但客户端需有 token 才能写）
ENV_WRITE_WHITELIST = {
    'LOGIN_USERNAME', 'LOGIN_PASSWORD', 'LOGIN_USERNAME2', 'LOGIN_PASSWORD2', 'LOGIN_URL',
    'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
    'EMAIL_SENDER', 'EMAIL_PASSWORD', 'EMAIL_SMTP_SERVER', 'EMAIL_SMTP_PORT', 'EMAIL_RECIPIENTS',
    'TESSERACT_PATH',
    'WORK_START_TIME', 'WORK_END_TIME', 'LATE_THRESHOLD', 'EARLY_LEAVE_THRESHOLD',
    'DAILY_STATUS_TIME',
}

# 返回给前端 GET /api/v1/config/all 时遮罩的敏感字段
ENV_SENSITIVE_FIELDS = {
    'LOGIN_PASSWORD', 'LOGIN_PASSWORD2', 'TELEGRAM_BOT_TOKEN', 'EMAIL_PASSWORD',
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
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def call(self, coro, timeout: float = 15.0):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeoutError:
            # 超时后必须取消 future，否则协程仍排在（可能被同步 Selenium 阻塞的）事件
            # 循环里等待执行：HTTP 已报错返回，几分钟后循环解锁却仍会真正打卡，
            # 形成用户不知情的"幽灵打卡"。打卡类不可幂等操作尤其需要在此切断。
            fut.cancel()
            raise


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
            # (1) Flask 线程内同步强停：立即 quit 活跃 driver，打断主循环里阻塞的 selenium 调用。
            #     不再 bridge.call(cancel_current_operation(),15s) —— 那会把协程排进已被阻塞的循环，干等超时。
            had_op, closed = attendance_system.force_stop_operation()
            # (2) 兜底：用线程安全方式设 asyncio 取消事件，覆盖 driver 尚未创建的窗口。
            ev = getattr(attendance_system, 'operation_cancel_event', None)
            if ev is not None:
                try:
                    bridge._loop.call_soon_threadsafe(ev.set)
                except Exception:
                    logging.exception("call_soon_threadsafe(ev.set) 失败")
            # (3) 排状态清理到主循环（driver quit 后循环很快解锁），不 .result() 干等。
            try:
                asyncio.run_coroutine_threadsafe(
                    attendance_system._cleanup_operation_state(), bridge._loop
                )
            except Exception:
                logging.exception("schedule _cleanup_operation_state 失败")
            msg = (f"已强制停止（关闭 {closed} 个 driver）" if had_op else "当前没有进行中的操作")
            return jsonify({'success': True, 'message': msg, 'closed': closed})
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
        # 删除前先取类型，用于同步取消对应 schedule job（仅删 JSON 记录的话，
        # 已注册的 job 仍会到点触发一次才靠存在性校验自删，期间可能在错误时间打卡）。
        task = attendance_system.task_manager.get_task_by_id(task_id)
        ptype = (task or {}).get('type')
        ok = attendance_system.task_manager.remove_task_by_id(task_id)
        # 按类型清除对应 tag 的 schedule job：调度器设计上同类至多一个（schedule_punch_in/out
        # 创建前都会清掉同类旧任务），故按 tag 清除是精确的。schedule 作业运行在主 loop，
        # 用 call_soon_threadsafe 投递清除，避免与 loop 迭代 jobs 竞态。
        tag = {'punch_in': 'punch_in_scheduled', 'punch_out': 'punch_out_scheduled'}.get(ptype)
        if ok and tag:
            import schedule
            try:
                bridge._loop.call_soon_threadsafe(lambda t=tag: schedule.clear(t))
            except Exception:
                logging.exception("del_task 取消 schedule job 失败")
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

    # ----- AI 资讯（AI HOT 精选）-----
    @app.get('/api/v1/ai-news')
    @require_token
    def get_ai_news():
        """返回 AI HOT 精选资讯契约（updated_at + count + items）。

        query: force=0|1（1 跳过 TTL 立即拉）。
        失败也返回 200 + 旧缓存；彻底无数据时 updated_at:null、count:0、items:[]。
        """
        force = request.args.get('force', '0') in ('1', 'true', 'True')
        try:
            from modules.ai_news_service import get_ai_news as _gan
            return jsonify(_gan(force=force))
        except Exception:
            logging.exception("get_ai_news failed")
            # 即便彻底异常也返回 200 + 空结构，避免前端报错
            return jsonify({'updated_at': None, 'count': 0, 'items': []})

    # ----- Claude Code 额度（墨水屏信息站）-----
    @app.get('/api/v1/claude-usage')
    @require_token
    def get_claude_usage():
        """返回本机 Claude Code 的 5h/周限额用量契约。

        query: force=0|1（1 跳过 TTL 立即拉）。
        失败也返回 200 + available:false（或旧缓存），绝不 500。
        """
        force = request.args.get('force', '0') in ('1', 'true', 'True')
        try:
            from modules.claude_usage_service import get_claude_usage as _gcu
            return jsonify(_gcu(force=force))
        except Exception:
            logging.exception("get_claude_usage failed")
            return jsonify({
                'available': False, 'updated_at': None,
                'five_hour': None, 'seven_day': None, 'error': '服务异常',
            })

    # ----- 日历信息（墨水屏信息站：休班标记/最近休息日/下一假期/调休补班）-----
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
                'workday_after': None,
            })

    # ----- Auto byebye -----
    @app.post('/api/v1/punch/auto_byebye/calc')
    @require_token
    def auto_byebye_calc():
        """根据上班打卡时间计算下班时间。

        body: ``{"username": "<可选>"}``
        - username 缺省时遍历所有 `today_punch_records`，按上班时间排序取最早的
        """
        body = request.get_json(silent=True) or {}
        username = body.get('username')
        recs = attendance_system.today_punch_records or {}

        target_user = None
        target_in = None
        if username:
            rec = recs.get(username) or {}
            target_in = rec.get('punch_in_time')
            target_user = username
        else:
            for u, r in recs.items():
                t = (r or {}).get('punch_in_time')
                if t and (target_in is None or t < target_in):
                    target_in = t
                    target_user = u

        from modules.config import config as cfg
        fallback_used = False
        if target_in:
            # 内存(today_punch_records)已有今日上班时间，直接用
            in_str = target_in.strftime('%H:%M:%S') if hasattr(target_in, 'strftime') else str(target_in)
        else:
            # 内存无记录 → 登录系统识别真实上班时间（对齐 Telegram /auto_byebye：Selenium 模式走
            # get_today_punch_in_time_via_selenium 的 DOM 解析、仅识别首个用户 users[0]；传统模式走 OCR）。
            # 登录识别耗时较长（与「获取打卡情况」量级一致），给足超时；超时/异常都不阻断，转兜底。
            ok_id, pin = False, None
            try:
                ok_id, pin, _id_msg = bridge.call(
                    attendance_system.get_today_punch_in_time_auto(),
                    timeout=240,
                )
            except Exception:
                logging.exception("auto_byebye_calc 登录识别上班时间失败")
            if ok_id and pin:
                in_str = pin
                if not target_user and attendance_system.users:
                    target_user = attendance_system.users[0].get('username')
            else:
                # 仍识别不到 → 用配置上班时间 WORK_START_TIME 兜底，保证「无上班记录也能自动下班」
                in_str = cfg.WORK_START_TIME
                fallback_used = True
        try:
            ok, out_str, msg = attendance_system.calculate_punch_out_time(in_str)
        except Exception as e:
            logging.exception("auto_byebye_calc failed")
            return jsonify({'success': False, 'error': str(e)}), 500
        if fallback_used:
            msg = f"今日无上班打卡记录、且登录识别未取到上班时间，已使用配置上班时间 {in_str} 兜底计算。{msg}"
        return jsonify({
            'success': bool(ok),
            'username': target_user,
            'punch_in_time': in_str,
            'punch_out_time': out_str,
            'message': msg,
            'fallback_used': fallback_used,
        })

    @app.post('/api/v1/punch/auto_byebye/confirm')
    @require_token
    def auto_byebye_confirm():
        """安排定时下班打卡任务。body: ``{hour, minute}``"""
        body = request.get_json(silent=True) or {}
        try:
            hour = int(body['hour'])
            minute = int(body['minute'])
        except (KeyError, ValueError, TypeError):
            return jsonify({'success': False, 'error': 'hour 和 minute 必填且为整数'}), 400
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return jsonify({'success': False, 'error': '时间超出范围'}), 400
        try:
            ok = bridge.call(
                attendance_system.schedule_punch_out(hour, minute), timeout=15
            )
            event_bus.publish_threadsafe('task:changed', {'op': 'add', 'type': 'punch_out'})
            return jsonify({'success': bool(ok), 'time': f'{hour:02d}:{minute:02d}'})
        except Exception as e:
            logging.exception("auto_byebye_confirm failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- 登录系统获取今日打卡情况 -----
    @app.post('/api/v1/punch/fetch_status')
    @require_token
    def fetch_punch_status():
        """登录考勤系统，读取所有已配置用户的今日上/下班时间（不触发打卡）。

        识别结果会回写今日记录，因此读取后推送一次 status:update 让概览/自动下班同步刷新。
        """
        try:
            if attendance_system.current_operation is not None:
                return jsonify({
                    'success': False,
                    'error': f'当前有 {attendance_system.current_operation} 操作进行中，请等待完成后再读取',
                }), 409
            results = bridge.call(attendance_system.fetch_today_punch_status(), timeout=180)
            try:
                event_bus.publish_threadsafe('status:update', {'reason': 'fetch_punch_status'})
            except Exception:
                logging.exception("publish status:update after fetch_punch_status failed")
            normalized = {}
            for uid, val in (results or {}).items():
                v = val if isinstance(val, dict) else {}
                normalized[uid] = {
                    'success': bool(v.get('success')),
                    'punch_in_time': v.get('punch_in_time'),
                    'punch_out_time': v.get('punch_out_time'),
                    'message': str(v.get('message', '')),
                }
            return jsonify({'success': True, 'count': len(normalized), 'results': normalized})
        except Exception as e:
            logging.exception("fetch_punch_status failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- Tasks (create) -----
    @app.post('/api/v1/tasks')
    @require_token
    def create_task():
        from modules.services.task_service import create_scheduled_punch_task
        body = request.get_json(silent=True) or {}
        punch_type = body.get('type')
        mode = body.get('mode')
        hour = body.get('hour')
        minute = body.get('minute')
        delay_minutes = body.get('delay_minutes')
        username = body.get('username')
        try:
            ok, msg, task_id = bridge.call(
                create_scheduled_punch_task(
                    attendance_system,
                    punch_type=punch_type,
                    mode=mode,
                    hour=hour,
                    minute=minute,
                    delay_minutes=delay_minutes,
                    username=username,
                ),
                timeout=15,
            )
            if ok:
                event_bus.publish_threadsafe('task:changed', {'op': 'add', 'id': task_id})
            return jsonify({'success': bool(ok), 'message': msg, 'task_id': task_id})
        except Exception as e:
            logging.exception("create_task failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- Screenshots -----
    @app.get('/api/v1/screenshots')
    @require_token
    def list_screenshots_api():
        from modules.services.screenshot_service import list_screenshots, list_users_with_screenshots
        username = request.args.get('username')
        ptype = request.args.get('type', 'punch_in')
        try:
            limit = max(1, min(int(request.args.get('limit', 5)), 20))
        except ValueError:
            limit = 5
        try:
            if username:
                items = list_screenshots(username, ptype, limit=limit)
                return jsonify({'username': username, 'type': ptype, 'items': items})
            else:
                users = list_users_with_screenshots()
                grouped = {u: list_screenshots(u, ptype, limit=limit) for u in users}
                return jsonify({'type': ptype, 'users': users, 'grouped': grouped})
        except Exception as e:
            logging.exception("list_screenshots failed")
            return jsonify({'error': str(e)}), 500

    @app.get('/api/v1/screenshots/file')
    @require_token
    def screenshot_file():
        from modules.services.screenshot_service import safe_screenshot_path
        path = request.args.get('path', '')
        safe = safe_screenshot_path(path)
        if not safe:
            return jsonify({'error': 'forbidden or not found'}), 404
        try:
            return send_file(safe, mimetype='image/png')
        except Exception as e:
            logging.exception("send_file failed")
            return jsonify({'error': str(e)}), 500

    # ----- Records -----
    @app.get('/api/v1/records')
    @require_token
    def get_records():
        """读取 punch_records/{username}/YYYY_MM.json。"""
        username = request.args.get('username')
        year = request.args.get('year')
        month = request.args.get('month')
        if not username or not year or not month:
            return jsonify({'error': 'username/year/month 必填'}), 400
        try:
            year_i = int(year); month_i = int(month)
            if not (1 <= month_i <= 12):
                raise ValueError('month range')
        except ValueError:
            return jsonify({'error': 'year/month 非法'}), 400
        # 防目录穿越：username 只允许包含合法字符
        if '/' in username or '\\' in username or '..' in username:
            return jsonify({'error': 'username 非法'}), 400
        ym = f'{year_i}_{month_i:02d}'
        path = os.path.join('punch_records', username, f'{ym}.json')
        if not os.path.exists(path):
            return jsonify({'username': username, 'year': year_i, 'month': month_i, 'records': {}})
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify({
                'username': username, 'year': year_i, 'month': month_i,
                'records': data, 'path': path,
            })
        except Exception as e:
            logging.exception("get_records failed")
            return jsonify({'error': str(e)}), 500

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
        # 附加 dynamic_config + 当前内存值方便前端展示
        from modules.config import config as cfg
        masked['_dynamic'] = {
            'USE_SELENIUM_LOGIN': cfg.get_use_selenium_login(),
            'SELENIUM_HEADLESS': cfg.get_selenium_headless(),
        }
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

    # ----- Email test -----
    @app.post('/api/v1/email/test')
    @require_token
    def test_email():
        try:
            from modules.email_service import email_service
            ok = bool(email_service.check_email_connection())
            return jsonify({'success': ok, 'message': '邮件服务器连接 OK' if ok else 'SMTP 连接失败'})
        except Exception as e:
            logging.exception("test_email failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- System control -----
    @app.post('/api/v1/system/restart')
    @require_token
    def system_restart():
        """请求重启 main.py — 当前仅记录意图并响应；真正重启由 Electron 主进程负责。"""
        event_bus.publish_threadsafe('system:restart_requested', {'ts': time.time()})
        return jsonify({'success': True, 'note': '已发出重启信号；Electron 主进程将在收到 system:restart_requested 时执行'})

    # ----- Bot reconnect -----
    @app.post('/api/v1/bot/reconnect')
    @require_token
    def bot_reconnect():
        """主动重连 Telegram Bot，并据结果回写 bot_available/bot_error、广播状态更新。"""
        try:
            ok, msg = bridge.call(attendance_system.bot.reconnect(), timeout=90)
            attendance_system.bot_available = bool(ok)
            attendance_system.bot_error = None if ok else msg
            event_bus.publish_threadsafe('status:update', {'reason': 'bot_reconnect', 'bot_available': bool(ok)})
            if ok:
                return jsonify({'success': True, 'message': msg})
            return jsonify({'success': False, 'error': msg}), 503
        except FuturesTimeoutError:
            attendance_system.bot_available = False
            attendance_system.bot_error = '重连超时'
            event_bus.publish_threadsafe('status:update', {'reason': 'bot_reconnect', 'bot_available': False})
            return jsonify({'success': False, 'error': '重连超时'}), 504
        except Exception as e:
            logging.exception("bot_reconnect failed")
            attendance_system.bot_available = False
            attendance_system.bot_error = str(e)
            event_bus.publish_threadsafe('status:update', {'reason': 'bot_reconnect', 'bot_available': False})
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- Daily reminder test -----
    @app.post('/api/v1/test/reminder')
    @require_token
    def test_reminder():
        try:
            ok = bool(attendance_system.bot.verify_daily_reminder_setup())
            return jsonify({'success': ok, 'message': '提醒任务已验证' if ok else '验证失败'})
        except Exception as e:
            logging.exception("test_reminder failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- Parallel login test -----
    @app.post('/api/v1/test/parallel_login')
    @require_token
    def parallel_login_test():
        try:
            users_config = attendance_system.prepare_users_config_from_env()
            if not users_config:
                return jsonify({'success': False, 'error': '未配置任何用户'}), 400
            results = bridge.call(
                attendance_system.parallel_punch_login(users_config), timeout=120
            )
            normalized = {}
            for uid, val in (results or {}).items():
                ok, msg = (val if isinstance(val, (list, tuple)) and len(val) >= 2 else (False, str(val)))
                normalized[uid] = {'success': bool(ok), 'message': str(msg)}
            return jsonify({
                'success': True,
                'count': len(normalized),
                'success_count': sum(1 for v in normalized.values() if v['success']),
                'results': normalized,
            })
        except Exception as e:
            logging.exception("parallel_login_test failed")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ----- 内置网络加速（mihomo）-----
    def _pm():
        return getattr(attendance_system, 'proxy_manager', None)

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
                note = ('内置加速已启动；重启程序后 Telegram 才会切到内置加速。'
                        if ok else f'启动失败：{msg}')
            elif toggling and not patch['enabled']:
                pm.stop()
                note = '内置加速已停止；重启程序后 Telegram 会回到系统代理/直连。'
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
            # threads 默认仅 4：auto_byebye_calc(240s)/fetch_punch_status(180s)/
            # parallel_login_test(120s)/bot_reconnect(90s) 这类长接口经 bridge.call 同步
            # 等待主 loop 时会长时间占住工作线程，4 个被占满后连无鉴权的 /ping 都排队无响应，
            # GUI 端表现为后端整体失联。提到 16 以缓解长接口对短接口（含打卡/状态/ping）的饥饿。
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
