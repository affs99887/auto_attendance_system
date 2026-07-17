"""
应用核心模块

GUI 底座的运行核心，职责只有四件事：
1. 初始化全局日志（滚动文件 + 控制台）；
2. 注册后台定时任务（目前只有汇率刷新，作为"周期任务"写法的参考示例）；
3. 提供系统状态快照，供 web_server 的 /api/v1/status 使用；
4. 进程退出时停掉内置网络加速（mihomo）子进程。

给客户定制新功能时，周期刷新类任务照 init_schedule_tasks 里的写法加，
一次性数据接口直接在 web_server.py 加路由即可，不必经过本类。
"""

import os
import sys
import signal
import atexit
import asyncio
import logging
import schedule
import psutil
from datetime import datetime
from typing import Dict

from modules.safe_calendar import is_workday, is_holiday


class AppCore:
    """应用核心：日志、定时任务、状态快照、退出清理。"""

    def __init__(self):
        self.setup_logging()

        # GUI 事件总线（WebSocket 推送用），由 web_server.start() 启动后注入；
        # 控制台模式下保持 None，定时任务里推送前都要判空。
        self._event_bus = None

        # 内置网络加速（mihomo）管理器，由 main.py 创建后注入；退出钩子用它做清理
        self.proxy_manager = None

        # 微信 Bark 转发服务（监听 macOS 微信通知转推 iPhone），web_server 的
        # /api/v1/wechat-bark/* 路由直接调用它
        from modules.wechat_bark_service import WechatBarkService
        self.wechat_bark = WechatBarkService()

        # 进程启动时刻，供状态快照计算运行时长
        self._started_at = datetime.now()

        self.init_schedule_tasks()

        self._install_exit_handlers()

        # 按配置自动开始微信通知监听（仅 macOS 生效，失败只记日志）
        self.wechat_bark.auto_start_if_configured()

    def setup_logging(self):
        """配置日志记录"""
        os.makedirs('logs', exist_ok=True)

        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        # 配置文件处理器
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            'logs/app.log',
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setFormatter(log_formatter)

        # 配置控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(log_formatter)

        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # 移除所有现有的处理器
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    def init_schedule_tasks(self):
        """初始化后台定时任务（全局 schedule 单例，由 schedule_manager.run_schedule 循环驱动）"""
        # 启动时清除所有现有任务（首次初始化场景）
        schedule.clear()

        # 汇率定时刷新（每 20 分钟）：阻塞 requests 放线程执行，避免卡事件循环；
        # 刷新成功且 GUI 模式（_event_bus 非 None）时通过 WS 推送最新价。
        async def exchange_rate_job():
            try:
                from modules.exchange_rate_service import refresh as _refresh
                loop = asyncio.get_running_loop()
                contract = await loop.run_in_executor(None, _refresh, None)
                latest = (contract or {}).get('latest')
                if latest and self._event_bus is not None:
                    self._event_bus.publish_threadsafe('exchange_rate:update', {
                        'price': latest.get('price'),
                        'time': latest.get('time'),
                        'base': 'CNY',
                        'quote': 'JPY',
                    })
            except Exception as e:
                logging.error(f"定时刷新汇率任务时发生错误: {str(e)}")
        schedule.every(20).minutes.do(lambda: asyncio.create_task(exchange_rate_job())).tag('exchange_rate_update')

        # 启动时触发一次汇率首刷（容错、不阻塞启动）：放 daemon 线程，避免阻塞 __init__ 与事件循环。
        # 请求会在本地代理连接失败时立即回退默认网络，不再等待统一健康 URL。
        def _first_exchange_rate_refresh():
            try:
                from modules.exchange_rate_service import refresh as _refresh
                _refresh(None)
            except Exception as e:
                logging.error(f"启动汇率首刷失败（忽略）: {str(e)}")
        try:
            import threading as _threading
            _threading.Thread(target=_first_exchange_rate_refresh,
                              name='aas-exchange-rate-first', daemon=True).start()
        except Exception as e:
            logging.error(f"启动汇率首刷线程失败（忽略）: {str(e)}")

    def _install_exit_handlers(self):
        """注册进程退出钩子：正常退出（atexit）与 SIGINT/SIGTERM 都停掉 mihomo 子进程，
        避免主进程退出后残留孤儿代理进程占着端口。"""
        atexit.register(self._sync_cleanup_on_exit)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._signal_handler)
            except (ValueError, OSError):
                # 非主线程或平台不支持时跳过，仍有 atexit 兜底
                pass

    def _sync_cleanup_on_exit(self):
        """同步清理：停止内置网络加速子进程与微信通知监听（可重复调用，幂等）。"""
        pm = getattr(self, 'proxy_manager', None)
        if pm is not None:
            try:
                pm.stop()
            except Exception:
                # 退出路径不再抛错，尽力而为
                pass
        wb = getattr(self, 'wechat_bark', None)
        if wb is not None:
            try:
                wb.shutdown()
            except Exception:
                pass

    def _signal_handler(self, signum, frame):
        """信号处理：清理后按默认行为退出。"""
        self._sync_cleanup_on_exit()
        sys.exit(0)

    def get_status_snapshot(self) -> Dict:
        """返回系统当前状态的 JSON 友好快照。"""
        try:
            cpu_percent = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            resources = {
                'cpu_percent': cpu_percent,
                'memory_percent': mem.percent,
            }
        except Exception:
            resources = {}

        try:
            workday = bool(is_workday(datetime.now().date()))
            holiday = bool(is_holiday(datetime.now().date()))
        except Exception:
            workday, holiday = None, None

        return {
            'current_time': datetime.now().isoformat(),
            'started_at': self._started_at.isoformat(),
            'uptime_seconds': int((datetime.now() - self._started_at).total_seconds()),
            'is_workday': workday,
            'is_holiday': holiday,
            'resources': resources,
            'config': {},
        }
