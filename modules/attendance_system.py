"""
AttendanceSystem Class - 自动打卡系统核心类

This module contains the main AttendanceSystem class that orchestrates all attendance operations.
"""

import os
import time
import logging
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List
import re
import json

# Third-party imports
import schedule
import pyperclip
import pytesseract
from PIL import Image
import cv2
import numpy as np
import pyautogui
import psutil
from modules.safe_calendar import is_workday, is_holiday
import sys

# Windows API imports
import win32gui
import win32con
import win32api

# Project imports
from modules.config import config
from modules.browser_controller import browser_controller
from modules.email_service import email_service
from modules.image_recognizer import image_recognizer
from modules.record_manager import punch_record_manager
from modules.task_manager import task_manager
from modules.telegram_bot import TelegramBot
from modules.selenium_login import SeleniumLoginController, ParallelSeleniumLogin


class AttendanceSystem:
    """自动打卡系统主类"""

    def __init__(self):
        # 静默初始化模式，避免启动时输出过多信息
        self._silent_init = True

        # 设置pytesseract路径
        pytesseract.pytesseract.tesseract_cmd = os.getenv('TESSERACT_PATH', r'C:\Program Files\Tesseract-OCR\tesseract.exe')

        # 配置多用户信息（使用config模块）
        self.users = config.get_user_configs()

        # 登录URL
        self.login_url = config.LOGIN_URL

        # 创建Telegram机器人实例
        self.bot = TelegramBot(config.TELEGRAM_CHAT_ID)
        # 设置bot的attendance_system引用
        self.bot.attendance_system = self
        # 只有 Application + 轮询完整启动后才算可用；启动期间/失败时核心业务继续运行。
        self.bot_available = False
        self.bot_error = '正在初始化'

        # 截图保存路径
        self.screenshot_path = 'logs/temp_screenshot.png'

        # 添加重试次数配置
        self.max_retries = config.MAX_RETRIES
        self.retry_interval = config.RETRY_INTERVAL

        # 浏览器窗口标题
        self.browser_title = "Microsoft Edge"

        # 安全位置图片路径
        self.safe_place_path = config.SAFE_PLACE_PATH
        self.safe_place_path2 = config.SAFE_PLACE_PATH2

        # 用于存储当前进度消息
        self.current_message = ""
        self.message_id = None

        # 添加心跳检测相关属性
        self.last_heartbeat = datetime.now()
        self.heartbeat_interval = config.HEARTBEAT_INTERVAL
        self.max_heartbeat_miss = config.MAX_HEARTBEAT_MISS
        self.heartbeat_miss_count = 0

        # 配置日志记录
        self.setup_logging()

        # 添加错误恢复相关属性
        self.error_count = 0
        self.max_errors = config.MAX_ERRORS
        self.error_reset_interval = config.ERROR_RESET_INTERVAL
        self.last_error_reset = datetime.now()

        # 添加打卡时间配置
        self.work_start_time = config.WORK_START_TIME
        self.work_end_time = config.WORK_END_TIME
        self.late_threshold = config.LATE_THRESHOLD
        self.early_leave_threshold = config.EARLY_LEAVE_THRESHOLD

        # 添加打卡提醒状态跟踪（按用户分桶，避免并行场景下相互污染）
        self.notification_sent_today = {
            user['username']: {
                'punch_in_reminder': False,
                'punch_out_reminder': False,
                'last_check_date': None
            }
            for user in (self.users if hasattr(self, 'users') and self.users else [])
            if user.get('username')
        }

        # 初始化任务管理器和打卡记录管理器（使用新的导入模块）
        self.task_manager = task_manager
        self.punch_record_manager = punch_record_manager

        # 加载今日打卡记录 —— 改为 dict[username] 嵌套，支持并行场景下按用户隔离
        # 初始值来自全局 punch_record_manager 单条记录（历史设计无用户区分），各用户共享起点；
        # 运行时各自更新自己的桶，不再相互覆盖。
        today_record = self.punch_record_manager.get_today_record()
        initial_in = datetime.strptime(today_record['punch_in_time'], '%H:%M:%S') if today_record['punch_in_time'] else None
        initial_out = datetime.strptime(today_record['punch_out_time'], '%H:%M:%S') if today_record['punch_out_time'] else None
        # date 字段为该桶记录的归属日期，作为"是否今天"的权威判断（解决跨天/周末/假日永不重置问题）。
        # 这里 get_today_record 读到的就是今天的记录，故初始归属日期 = 今天。
        self.today_punch_records = {
            user['username']: {
                'punch_in_time': initial_in,
                'punch_out_time': initial_out,
                'date': datetime.now().date()
            }
            for user in self.users
            if user.get('username')
        }

        # 设置每日状态推送时间
        self.daily_status_time = config.DAILY_STATUS_TIME  # 每日状态推送时间

        # GUI 后端事件总线占位。仅在 main.py --gui 模式下由 web_server.start() 注入；
        # 默认 None，对纯 bot 部署 send_notification 等代码无任何影响。
        # 必须赋值在 init_schedule_tasks() 之前：里面起的首刷后台线程会读 self._event_bus，
        # 快网络下可能赶在 __init__ 走完之前访问。
        self._event_bus = None

        # 初始化定时任务
        self.init_schedule_tasks()

        # 添加虚拟鼠标控制
        self.use_virtual_mouse = True

        # Selenium登录配置
        self.use_selenium_login = config.get_use_selenium_login()
        self.selenium_headless = config.get_selenium_headless()

        # 初始化所有服务实例（使用新的导入模块）
        self.email_service = email_service
        self.browser_controller = browser_controller
        self.image_recognizer = image_recognizer

        # 确保logs目录存在，用于保存截图
        os.makedirs('logs', exist_ok=True)

        # 添加操作状态管理变量
        self.current_operation = None  # 当前操作类型 ("punch_in", "punch_out", None)
        self.operation_task = None  # 当前操作的asyncio.Task对象
        self.operation_cancel_event = None  # 用于取消操作的asyncio.Event
        self.operation_lock = asyncio.Lock()  # 确保互斥的锁
        self.operation_start_time = None  # 操作开始时间
        # [M11 修复] 最近一次派出的打卡 task 引用：不被 _cleanup_operation_state 清空（web 强停会把
        # operation_task 直接置 None 而不等待旧任务结束）。新操作启动前用它确认旧任务确实已结束，
        # 否则旧任务可能仍阻塞在 await 中、被新操作 clear 掉取消信号后"复活"误打卡。
        self._last_operation_task = None

        # send_daily_status 并发去重（并行打卡场景下 N 个用户成功后会同时触发）
        self._last_daily_status_send = None  # type: Optional[datetime]
        self._daily_status_lock = asyncio.Lock()

        # 浏览器资源跟踪：活跃 SeleniumLoginController 集合 + 同步锁
        # 用 threading.Lock 而非 asyncio.Lock，因为 atexit/signal 处理时事件循环可能已关
        import threading as _threading
        self._active_controllers = set()
        self._controllers_lock = _threading.Lock()
        # 跨线程强停标志：Flask 请求线程可安全 set（asyncio.Event 跨线程不安全），
        # 主循环里的同步检查点 / 可打断 sleep 都读它，配合 force_stop_operation 实现"真正能停"
        self._cancel_flag = _threading.Event()

        # 启动时清理上次崩溃残留的孤儿 driver 进程（用户机器无手工 driver，无误杀风险）
        self._kill_orphan_msedgedrivers()

        # 安装进程退出钩子（atexit + SIGINT/SIGTERM），无论怎样退出都尽力清掉活跃 driver
        self._install_exit_handlers()

        # 初始化完成，取消静默模式
        self._silent_init = False

    def _kill_orphan_msedgedrivers(self):
        """启动时清理上次崩溃残留的 msedgedriver.exe / chromedriver 进程"""
        try:
            killed = []
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    name = (proc.info.get('name') or '').lower()
                    if name in ('msedgedriver.exe', 'chromedriver.exe', 'msedgedriver', 'chromedriver'):
                        proc.kill()
                        killed.append((proc.info['pid'], name))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception as inner_e:
                    logging.debug(f"扫描进程时跳过单个项: {inner_e}")
                    continue
            if killed:
                logging.info(f"启动时清理了 {len(killed)} 个残留 driver 进程: {killed}")
            else:
                logging.debug("启动时未发现残留 driver 进程")
        except Exception as e:
            logging.error(f"清理孤儿 driver 进程时异常: {e}")

    def _install_exit_handlers(self):
        """注册 atexit + signal 钩子，确保进程退出时关闭所有活跃 selenium driver"""
        import atexit
        import signal as _signal
        try:
            atexit.register(self._sync_cleanup_on_exit)
        except Exception as e:
            logging.warning(f"注册 atexit 钩子失败: {e}")
        try:
            _signal.signal(_signal.SIGINT, self._signal_handler)
        except Exception as e:
            logging.warning(f"注册 SIGINT 钩子失败: {e}")
        try:
            _signal.signal(_signal.SIGTERM, self._signal_handler)
        except Exception as e:
            logging.warning(f"注册 SIGTERM 钩子失败: {e}")

    def _sync_cleanup_on_exit(self):
        """同步清理所有活跃 driver（atexit/signal 路径用，event loop 可能已关）"""
        # 退出钩子先停内置网络加速（mihomo）——必须放在下方 driver early-return 之前，
        # 否则无活跃 driver 时这段不会执行。仅覆盖优雅落幕/SIGINT/SIGTERM；硬杀由 Job Object 兜底。
        pm = getattr(self, 'proxy_manager', None)
        if pm is not None:
            try:
                pm.stop()
            except Exception:
                logging.error("退出钩子停止内置网络加速失败", exc_info=True)
        if not getattr(self, '_active_controllers', None):
            return
        with self._controllers_lock:
            controllers = list(self._active_controllers)
            self._active_controllers.clear()
        if not controllers:
            return
        logging.info(f"退出钩子：清理 {len(controllers)} 个活跃 selenium controller")
        for ctrl in controllers:
            try:
                ctrl.close()
            except Exception as e:
                logging.error(f"退出钩子关闭 controller 失败: {e}")

    def _signal_handler(self, signum, frame):
        """SIGINT/SIGTERM 信号处理器：清理 driver 后退出"""
        try:
            logging.info(f"收到信号 {signum}，开始清理活跃 driver...")
            self._sync_cleanup_on_exit()
        finally:
            # 让 atexit 钩子也能跑（_sync_cleanup_on_exit 已幂等，二次调用无害）
            import sys
            sys.exit(0)

    def _get_user_today_record(self, username):
        """获取指定用户的今日打卡记录字典。
        如该用户不在初始字典中（理论不会发生），懒初始化一条空记录。
        """
        if not username:
            username = 'default'
        if username not in self.today_punch_records:
            self.today_punch_records[username] = {
                'punch_in_time': None,
                'punch_out_time': None,
                'date': None
            }
        return self.today_punch_records[username]

    def _set_user_punch_time(self, username, kind, time):
        """设置指定用户的打卡时间。
        kind 取值: 'punch_in_time' / 'punch_out_time'
        """
        record = self._get_user_today_record(username)
        record[kind] = time
        # 每次写入都刷新归属日期为今天，作为"是否今天"的权威判断
        record['date'] = datetime.now().date()

    def _reset_today_punch_records(self):
        """重置所有用户的今日打卡记录（用于跨日重置）"""
        for username in list(self.today_punch_records.keys()):
            self.today_punch_records[username] = {
                'punch_in_time': None,
                'punch_out_time': None,
                'date': None
            }

    def _get_user_notification_state(self, username):
        """获取指定用户的提醒状态字典（懒初始化）"""
        if not username:
            username = 'default'
        if username not in self.notification_sent_today:
            self.notification_sent_today[username] = {
                'punch_in_reminder': False,
                'punch_out_reminder': False,
                'last_check_date': None
            }
        return self.notification_sent_today[username]

    def _set_user_notification_flag(self, username, flag, value):
        """设置指定用户的提醒状态标志。
        flag 取值: 'punch_in_reminder' / 'punch_out_reminder' / 'last_check_date'
        """
        state = self._get_user_notification_state(username)
        state[flag] = value

    def _register_controller(self, controller):
        """注册一个活跃的 SeleniumLoginController（创建成功后立即调用）"""
        if controller is None:
            return
        with self._controllers_lock:
            self._active_controllers.add(controller)
            logging.debug(f"已注册 selenium controller，当前活跃数: {len(self._active_controllers)}")

    def _unregister_controller(self, controller):
        """从活跃集合中移除一个 controller（close 后立即调用）"""
        if controller is None:
            return
        with self._controllers_lock:
            self._active_controllers.discard(controller)
            logging.debug(f"已注销 selenium controller，当前活跃数: {len(self._active_controllers)}")

    def get_surname_honorific(self, username):
        """根据用户名获取姓氏和合适的敬语称谓"""
        if not username:
            return "用户"

        # 提取姓氏（通常是第一个字符）
        surname = username[0] if len(username) > 0 else "用户"

        # 根据性别和姓氏添加敬语
        # 这里可以根据实际需要调整敬语规则
        common_male_surnames = ['王', '李', '张', '刘', '陈', '杨', '赵', '黄', '周', '吴']
        common_female_surnames = ['王', '李', '张', '刘', '陈', '杨', '赵', '黄', '周', '吴']

        # 简单处理，都使用通用敬语
        return f"{surname}先生/女士"

    def _save_screenshot_data(self, screen_data, filepath):
        """保存截图数据到文件

        Args:
            screen_data: 截图数据，可能是numpy数组(传统方式)或bytes(Selenium)
            filepath: 保存路径

        Returns:
            bool: 是否保存成功
        """
        try:
            if isinstance(screen_data, bytes):
                # Selenium截图数据 (PNG bytes)
                with open(filepath, 'wb') as f:
                    f.write(screen_data)
                return True
            elif isinstance(screen_data, np.ndarray):
                # OpenCV截图数据 (numpy数组)
                # cv2.imwrite在Windows下可能无法处理中文路径，使用imencode+write方式
                try:
                    # 先尝试直接使用cv2.imwrite
                    result = cv2.imwrite(filepath, screen_data)
                    if result:
                        return True
                    else:
                        # 如果失败，使用备用方法：imencode + write
                        _, img_encoded = cv2.imencode('.png', screen_data)
                        with open(filepath, 'wb') as f:
                            f.write(img_encoded.tobytes())
                        return True
                except Exception as e:
                    # 最后的备用方法：使用numpy和PIL
                    logging.warning(f"cv2.imwrite失败，尝试备用方法: {e}")
                    _, img_encoded = cv2.imencode('.png', screen_data)
                    with open(filepath, 'wb') as f:
                        f.write(img_encoded.tobytes())
                    return True
            else:
                logging.error(f"不支持的截图数据类型: {type(screen_data)}")
                return False
        except Exception as e:
            logging.error(f"保存截图失败: {e}")
            return False

    def _convert_screen_data_to_numpy(self, screen_data):
        """将截图数据转换为numpy数组格式

        Args:
            screen_data: 截图数据

        Returns:
            numpy.ndarray or None: numpy格式的截图数据
        """
        try:
            if isinstance(screen_data, np.ndarray):
                return screen_data
            elif isinstance(screen_data, bytes):
                # 将bytes数据转换为numpy数组
                nparr = np.frombuffer(screen_data, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                return img
            else:
                logging.error(f"无法转换截图数据类型: {type(screen_data)}")
                return None
        except Exception as e:
            logging.error(f"转换截图数据失败: {e}")
            return None

    def save_user_screenshot(self, screen, username, punch_type, success=True):
        """
        统一的用户截图保存方法，确保每个用户每种类型最多保留3张图片

        Args:
            screen: 截图数据，可能是cv2截图数据(numpy数组)或Selenium截图数据(bytes)
            username: 用户名
            punch_type: 打卡类型 "上班" 或 "下班"
            success: 是否成功打卡，用于文件名标识

        Returns:
            str: 保存的文件路径，如果失败返回None
        """
        try:
            if not username or screen is None:
                logging.warning(f"用户名为空或截图数据为空，跳过保存 (username: {username}, screen: {screen is not None})")
                return None

            # 转换打卡类型为目录名
            punch_dir = "punch_in" if punch_type == "上班" else "punch_out"

            # 处理用户名，支持中文字符但移除文件系统不安全的字符
            # 移除可能导致文件系统问题的字符，但保留中文字符
            unsafe_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
            safe_username = username
            for char in unsafe_chars:
                safe_username = safe_username.replace(char, '_')
            safe_username = safe_username.strip()
            if not safe_username:
                safe_username = "unknown_user"

            # 创建用户截图目录
            user_screenshot_dir = os.path.join('screenshots', safe_username, punch_dir)
            os.makedirs(user_screenshot_dir, exist_ok=True)

            # 生成带时间戳和状态标识的文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            status_suffix = "success" if success else "fail"
            filename = f'{punch_dir}_{timestamp}_{status_suffix}.png'
            filepath = os.path.join(user_screenshot_dir, filename)

            # 保存新截图，使用支持中文路径的方法
            abs_filepath = os.path.abspath(filepath)
            logging.debug(f"尝试保存用户截图到: {abs_filepath}")

            # 使用统一的截图保存方法
            save_result = self._save_screenshot_data(screen, abs_filepath)

            if save_result:
                logging.info(f"已保存用户 {username} 的{punch_type}打卡截图到: {abs_filepath}")

                # 验证文件是否存在
                if os.path.exists(abs_filepath):
                    file_size = os.path.getsize(abs_filepath)
                    logging.info(f"截图文件大小: {file_size} bytes")
                    logging.info(f"截图成功保存到用户目录: screenshots/{safe_username}/{punch_dir}/{filename}")
                else:
                    logging.error(f"截图文件保存后不存在: {abs_filepath}")
                    return None
            else:
                logging.error(f"保存用户截图失败: {abs_filepath}")
                logging.error(f"原始用户名: {username}")
                logging.error(f"安全用户名: {safe_username}")
                logging.error(f"文件路径: {abs_filepath}")
                if screen is not None and hasattr(screen, 'shape'):
                    logging.error(f"截图数据形状: {screen.shape}")
                    logging.error(f"截图数据类型: {screen.dtype}")
                return None

            # 清理旧截图，只保留最新3张
            try:
                import glob
                pattern = os.path.join(user_screenshot_dir, '*.png')
                files = glob.glob(pattern)

                # 按修改时间排序，最新的在前
                files.sort(key=os.path.getmtime, reverse=True)

                # 如果超过3张，删除最旧的图片
                if len(files) > 3:
                    files_to_remove = files[3:]  # 保留前3张，删除其余的
                    for old_file in files_to_remove:
                        try:
                            os.remove(old_file)
                            logging.info(f"已删除旧截图文件: {old_file}")
                        except Exception as e:
                            logging.error(f"删除旧截图文件 {old_file} 失败: {e}")
            except Exception as e:
                logging.warning(f"清理旧截图文件时发生错误: {e}")

            return abs_filepath

        except Exception as e:
            logging.error(f"保存用户截图失败 (用户: {username}, 类型: {punch_type}): {e}")
            return None

    @staticmethod
    def _safe_filename_token(username):
        """[M48 修复] 把用户名清洗成可安全嵌入文件名的 token（仅保留字母数字下划线连字符）。

        并行多账户共用固定截图名会互相覆盖，临时文件名需带用户名区分；但用户名可能含中文/空格/
        路径分隔符等不适合做文件名的字符，这里统一替换为下划线，空值退化为 'default'。
        """
        token = str(username) if username else 'default'
        return re.sub(r'[^0-9A-Za-z_-]', '_', token)

    async def _send_punch_failure_screenshot(self, screen, username, punch_type, error_msg):
        """发送打卡失败截图的辅助方法

        Args:
            screen: 截图数据
            username: 用户名
            punch_type: 打卡类型 "上班" 或 "下班"
            error_msg: 错误消息
        """
        screenshot_path = None  # Telegram 临时截图，发送异常时也要在 finally 清理
        try:
            # [M48 修复] 并行多账户下班失败时多用户同时进本方法，原先写 CWD/logs 下固定文件名
            # （punch_{type}_fail_uncertain.png / punch_{type}_fail_email.png）会互相覆盖：
            # A 写 → B 覆盖 → A 发出去/邮件附件读到的是 B 的截图，且 finally 删共享文件时与
            # 另一用户的 open/后台邮件 cleanup 竞争。改为文件名加入安全用户名 + 微秒时间戳，
            # 使每个用户每次失败都落到唯一路径，彻底消除并发覆盖与删除竞态。
            safe_username = self._safe_filename_token(username)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            # 保存并发送当前的浏览器窗口截图
            screenshot_path = f'punch_{punch_type}_fail_uncertain_{safe_username}_{ts}.png'
            cv2.imwrite(screenshot_path, screen)

            # 保存失败截图到用户目录
            self.save_user_screenshot(screen, username, punch_type, success=False)

            # 发送Telegram消息
            with open(screenshot_path, 'rb') as photo:
                await self.bot.app.bot.send_photo(
                    chat_id=self.bot.chat_id,
                    photo=photo,
                    caption=f"{punch_type}打卡失败 - {error_msg}"
                )

            # 发送电子邮件通知
            surname = self.get_surname_honorific(username)
            email_subject = f"{punch_type}打卡失败通知 - {surname} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            # [M49 修复] 去掉无条件的"系统会在适当时间自动重试"承诺——本方法被多种失败场景复用，
            # 其中 unable_escape 但 OCR 取不到剩余时间且处于收集（多账户）模式时根本不会调度重试，
            # 原文案会误导用户漏打下班卡。调用方已把真实结果（是否已调度重试 / 请手动补卡）写进 error_msg，
            # 邮件正文直接以 error_msg 为准。
            email_body = f"{surname}您好，\n\n您的{punch_type}打卡尝试失败。\n\n原因：{error_msg}\n\n此邮件由自动打卡系统发送，请勿回复。"

            # 复制截图用于邮件发送（唯一文件名，交后台邮件线程读取后清理，绝不与他人共享）
            email_screenshot_path = f'logs/punch_{punch_type}_fail_email_{safe_username}_{ts}.png'
            with open(screenshot_path, 'rb') as f_in:
                img_data = f_in.read()
                with open(email_screenshot_path, 'wb') as f_out:
                    f_out.write(img_data)

            # 发送邮件（email_screenshot_path 的删除已交给后台发送线程 cleanup_path，主流程不再删）
            await self.send_email_with_attachment(email_subject, email_body, email_screenshot_path, f"{punch_type}(失败)")

        except Exception as e:
            error_type = type(e).__name__
            error_msg_detail = str(e)

            # 检查是否是HTTPXRequest初始化错误
            if "HTTPXRequest" in error_msg_detail and "not initialized" in error_msg_detail:
                self.bot._is_initialized = False
                await self.send_notification("打卡流程", f"通知发送失败 (HTTPXRequest错误): {error_msg_detail}")
            else:
                await self.send_notification("打卡流程", f"通知发送失败: {error_msg_detail}")
        finally:
            # Telegram 临时截图不传后台线程，主流程删除无竞态；放 finally 保证发送异常也清理
            if screenshot_path and os.path.exists(screenshot_path):
                try:
                    os.remove(screenshot_path)
                except Exception:
                    pass

    def setup_logging(self):
        """配置日志记录"""
        # 确保logs目录存在
        os.makedirs('logs', exist_ok=True)

        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        # 创建日志过滤器
        class TelegramFilter(logging.Filter):
            def filter(self, record):
                # 过滤掉 getUpdates 请求的日志
                return not (record.levelname == 'INFO' and 'getUpdates' in record.getMessage())

        # 配置文件处理器
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(
            'logs/attendance_system.log',
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3,
            encoding='utf-8'  # 指定编码为UTF-8
        )
        file_handler.setFormatter(log_formatter)
        file_handler.addFilter(TelegramFilter())

        # 配置控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(log_formatter)
        console_handler.addFilter(TelegramFilter())

        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # 移除所有现有的处理器
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    def update_progress(self, new_line):
        """更新进度消息"""
        self.current_message += f"\n{new_line}"
        return self.current_message

    async def _force_reinitialize_bot(self):
        """强制重新初始化bot，解决HTTPXRequest错误"""
        try:
            logging.info("开始强制重新初始化Telegram Bot...")

            # 停止当前应用
            if self.bot.app:
                try:
                    await self.bot.app.stop()
                    await self.bot.app.shutdown()
                except Exception as e:
                    logging.warning(f"停止旧bot应用时发生错误: {e}")

                # 等待一段时间确保连接完全关闭
                await asyncio.sleep(3)

            # 重置状态
            self.bot.app = None
            self.bot._is_initialized = False

            # 重新初始化
            await self.bot._ensure_app_initialized()

            # 验证初始化是否成功
            if self.bot.app and self.bot._is_initialized:
                logging.info("Telegram Bot强制重新初始化成功")
            else:
                logging.error("Telegram Bot强制重新初始化失败")

        except Exception as e:
            logging.error(f"强制重新初始化bot时发生错误: {e}")

    async def send_notification(self, title, content):
        """发送/更新Telegram消息"""
        message = self.update_progress(f"{title}: {content}")

        # 把事件转推到 GUI（如果挂载了 event_bus）。非阻塞，失败不影响后续 bot 流程。
        if self._event_bus is not None:
            try:
                await self._event_bus.publish('punch:progress', {
                    'title': title,
                    'content': content,
                    'message': message,
                })
            except Exception:
                logging.exception("event_bus publish failed for punch:progress")

        # 确保bot已初始化
        if not self.bot:
            logging.warning(f"无法发送通知，Telegram bot实例不存在: {title} - {content}")
            return

        # Telegram 降级时不在业务流程里同步初始化/重试；事件总线已在上方照常推给 GUI，
        # Bot 恢复由启动恢复任务或连接监控独立负责。
        if not getattr(self, 'bot_available', False):
            logging.debug("Telegram Bot 当前不可用，跳过通知发送: %s", title)
            return

        # 使用bot的send_message方法，它会自动处理初始化
        try:
            if self.message_id:
                # 尝试更新现有消息
                try:
                    await self.bot._ensure_app_initialized()
                    if self.bot.app:
                        await self.bot.app.bot.edit_message_text(
                            chat_id=self.bot.chat_id,
                            message_id=self.message_id,
                            text=message
                        )
                except Exception as e:
                    logging.warning(f"更新消息失败: {str(e)}")
                    # 如果更新失败，发送新消息
                    success = await self.bot.send_message(title, content)
                    if success:
                        # 由于无法获取新消息ID，重置message_id
                        self.message_id = None
            else:
                # 发送新消息
                try:
                    await self.bot._ensure_app_initialized()
                    if self.bot.app:
                        message_obj = await self.bot.app.bot.send_message(
                            chat_id=self.bot.chat_id,
                            text=message
                        )
                        if message_obj:
                            self.message_id = message_obj.message_id
                except Exception as e:
                    logging.warning(f"发送新消息失败: {str(e)}")
                    # 使用备用方法发送
                    await self.bot.send_message(title, content)
        except Exception as e:
            logging.error(f"发送通知时发生错误: {str(e)}")
            # 最后的备用方法
            try:
                await self.bot.send_message(title, content)
            except Exception as backup_e:
                logging.error(f"备用通知发送也失败: {str(backup_e)}")

    def get_browser_window(self):
        """获取浏览器窗口句柄"""
        def callback(hwnd, windows):
            if not win32gui.IsWindowVisible(hwnd):
                return True

            title = win32gui.GetWindowText(hwnd)
            # Edge浏览器的各种可能标题
            edge_titles = [
                "Microsoft Edge",
                "InPrivate",
                "新建标签页",
                "New Tab",
                self.login_url  # 登录页面的URL
            ]

            if any(edge_title in title for edge_title in edge_titles):
                # 确保窗口不是最小化的
                placement = win32gui.GetWindowPlacement(hwnd)
                if placement[1] != win32con.SW_SHOWMINIMIZED:
                    windows.append(hwnd)
            return True

        windows = []
        win32gui.EnumWindows(callback, windows)

        if not windows:
            logging.error("未找到Edge浏览器窗口，已搜索的标题包括：Microsoft Edge, InPrivate, 新建标签页, New Tab")
            return None

        # 返回最后打开的窗口（通常是最新的）
        return windows[-1]

    def take_screenshot(self):
        """截取浏览器窗口"""
        try:
            # 获取浏览器窗口句柄
            hwnd = self.get_browser_window()
            if not hwnd:
                logging.error("未找到浏览器窗口，无法进行截图")
                return None

            try:
                # 获取窗口位置和大小
                rect = win32gui.GetWindowRect(hwnd)
                x, y, width, height = rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]

                if width <= 0 or height <= 0:
                    logging.error(f"窗口大小异常 - 宽: {width}, 高: {height}")
                    return None

                # 获取屏幕尺寸
                screen_width, screen_height = pyautogui.size()

                # 调整坐标确保在屏幕范围内
                x = max(0, min(x, screen_width - width))
                y = max(0, min(y, screen_height - height))
                width = min(width, screen_width - x)
                height = min(height, screen_height - y)

                # 截取指定区域
                screenshot = pyautogui.screenshot(region=(x, y, width, height))

                # 转换为OpenCV格式
                screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

                return screenshot_cv

            except Exception as e:
                logging.error(f"获取窗口信息或截图时发生错误: {str(e)}")
                return None

        except Exception as e:
            logging.error(f"截图过程发生错误: {str(e)}")
            return None

    def find_element_by_image(self, template_path, threshold=0.8):
        """通过图像模板匹配找到元素位置，增加重试机制和多阈值尝试"""
        # 对于关键模板，使用多个阈值进行尝试
        if 'unable_escape.png' in template_path or 'left_time.png' in template_path:
            thresholds = [0.7, 0.6, 0.5, 0.4]
        else:
            thresholds = [threshold]

        for attempt in range(self.max_retries):
            if self._cancel_flag.is_set():  # 强停：中断图像识别重试循环
                return None
            screen = self.take_screenshot()
            if screen is None:
                print(f"截图失败，{attempt + 1} 次重试...")
                self._interruptible_sleep(self.retry_interval)
                continue

            template = cv2.imread(template_path)
            if template is None:
                raise FileNotFoundError(f"模板图片未找到: {template_path}")

            # 获取模板尺寸
            template_height, template_width = template.shape[:2]

            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

            # 尝试多个阈值
            for thresh in thresholds:
                if max_val >= thresh:
                    # 获取浏览器窗口位置
                    hwnd = self.get_browser_window()
                    if hwnd:
                        window_x, window_y = win32gui.GetWindowRect(hwnd)[:2]
                        # 返回相对于屏幕的绝对坐标
                        center_x = window_x + max_loc[0] + template_width // 2
                        center_y = window_y + max_loc[1] + template_height // 2

                        # 记录匹配结果和阈值，便于调试
                        if 'unable_escape.png' in template_path or 'left_time.png' in template_path:
                            logging.info(f"模板匹配成功 {template_path}：置信度={max_val:.3f}, 使用阈值={thresh}")

                        return (center_x, center_y)

            if attempt < self.max_retries - 1:
                logging.info(f"未找到元素 {template_path}（最高匹配度：{max_val:.3f}），{attempt + 1} 次重试...")
                self._interruptible_sleep(self.retry_interval)

        # 记录最终匹配失败的详细信息
        if 'unable_escape.png' in template_path or 'left_time.png' in template_path:
            logging.warning(f"关键模板匹配失败 {template_path}：最高置信度={max_val:.3f}, 尝试次数={self.max_retries}")

        return None

    def find_element_with_label(self, template_path, label_template_path, threshold=0.8):
        """通过标签和输入框的组合来定位元素"""
        for attempt in range(self.max_retries):
            if self._cancel_flag.is_set():  # 强停：中断图像识别重试循环
                return None
            screen = self.take_screenshot()
            if screen is None:
                print(f"截图失败，{attempt + 1} 次重试...")
                self._interruptible_sleep(self.retry_interval)
                continue

            # 先找标签位置
            label_template = cv2.imread(label_template_path)
            if label_template is None:
                raise FileNotFoundError(f"标签模板图片未找到: {label_template_path}")

            label_result = cv2.matchTemplate(screen, label_template, cv2.TM_CCOEFF_NORMED)
            label_min_val, label_max_val, label_min_loc, label_max_loc = cv2.minMaxLoc(label_result)

            if label_max_val >= threshold:
                # 找到标签后，在其右侧区域查找输入框
                input_template = cv2.imread(template_path)
                if input_template is None:
                    raise FileNotFoundError(f"输入框模板图片未找到: {template_path}")

                # 获取输入框模板尺寸
                input_height, input_width = input_template.shape[:2]

                # 计算查找区域（标签右侧）
                label_width = label_template.shape[1]
                search_region = screen[
                    max(0, label_max_loc[1] - 10):min(screen.shape[0], label_max_loc[1] + input_template.shape[0] + 10),
                    label_max_loc[0] + label_width:min(screen.shape[1], label_max_loc[0] + label_width + 300)
                ]

                if search_region.size > 0:
                    result = cv2.matchTemplate(search_region, input_template, cv2.TM_CCOEFF_NORMED)
                    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

                    if max_val >= threshold:
                        # 获取浏览器窗口位置
                        hwnd = self.get_browser_window()
                        if hwnd:
                            window_x, window_y = win32gui.GetWindowRect(hwnd)[:2]
                            # 返回相对于屏幕的绝对坐标
                            center_x = window_x + label_max_loc[0] + label_width + max_loc[0] + input_width // 2
                            center_y = window_y + label_max_loc[1] + max_loc[1] + input_height // 2
                            return (center_x, center_y)

            if attempt < self.max_retries - 1:
                print(f"未找到元素组合（匹配度：{label_max_val:.2f}），{attempt + 1} 次重试...")
                self._interruptible_sleep(self.retry_interval)

        return None

    def input_text(self, text):
        """使用剪贴板输入文本"""
        pyperclip.copy(text)  # 复制文本到剪贴板
        pyautogui.hotkey('ctrl', 'v')  # 粘贴
        time.sleep(0.5)  # 等待粘贴完成

    def virtual_mouse_click(self, x, y):
        """使用虚拟鼠标进行点击"""
        try:
            # 获取目标窗口句柄
            hwnd = self.get_browser_window()
            if not hwnd:
                logging.error("未找到浏览器窗口")
                return False

            # 将屏幕坐标转换为窗口客户区坐标
            client_point = win32gui.ScreenToClient(hwnd, (x, y))

            # 发送鼠标左键点击消息
            win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, win32api.MAKELONG(*client_point))
            time.sleep(0.1)  # 短暂延迟确保消息被处理
            win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, win32api.MAKELONG(*client_point))
            time.sleep(0.1)

            return True
        except Exception as e:
            logging.error(f"虚拟鼠标点击失败: {str(e)}")
            return False

    def click_position(self, x, y):
        """统一的点击接口"""
        if self.use_virtual_mouse:
            return self.virtual_mouse_click(x, y)
        else:
            pyautogui.click(x, y)
            return True

    async def click_safe_place(self):
        """点击安全位置"""
        await self.send_notification("安全位置", "查找第一个安全位置...")
        safe_loc = self.find_element_by_image(self.safe_place_path)
        if safe_loc:
            await self.send_notification("安全位置", "找到第一个安全位置，进行点击...")
            self.click_position(*safe_loc)
            time.sleep(0.5)
            return True

        await self.send_notification("安全位置", "未找到第一个安全位置，尝试第二个安全位置...")
        safe_loc2 = self.find_element_by_image(self.safe_place_path2)
        if safe_loc2:
            await self.send_notification("安全位置", "找到第二个安全位置，进行点击...")
            self.click_position(*safe_loc2)
            time.sleep(0.5)
            return True

        await self.send_notification("安全位置", "两个安全位置都未找到")
        return False

    async def _login_to_system(self, username, password, context="打卡流程"):
        """完整的登录流程，包括打开浏览器、处理警告弹窗和登录

        Args:
            username: 用户名
            password: 密码
            context: 操作上下文，用于日志记录

        Returns:
            tuple: (success: bool, screen: numpy.ndarray or None)
        """
        screen = None

        try:
            # 使用 Edge InPrivate 模式打开新窗口
            await self.send_notification(context, "开始打开浏览器...")
            os.system('start msedge --inprivate --new-window "{}"'.format(self.login_url))
            time.sleep(3)  # 增加等待时间，确保页面完全加载

            # 获取当前窗口截图用于错误处理
            screen = self.take_screenshot()

            # 检查是否有警告弹窗
            await self.send_notification(context, "检查是否存在警告弹窗...")

            # 使用OCR识别文本
            custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
            screen_text = pytesseract.image_to_string(
                Image.fromarray(cv2.cvtColor(screen, cv2.COLOR_BGR2RGB)),
                lang='chi_sim',
                config=custom_config
            )

            # 检查是否包含警告文本
            warning_texts = [
                "连接不是专用连接",
                "此网站的安全证书",
                "不安全的连接"
            ]
            has_alert = any(warning_text in screen_text for warning_text in warning_texts)

            if has_alert:
                await self.send_notification(context, "检测到警告弹窗，处理中...")
                # 查找并点击更多按钮
                await self.send_notification(context, "尝试查找更多按钮...")
                more_button_loc = self.find_element_by_image('templates/more_button.png', threshold=0.5)
                if not more_button_loc:
                    error_msg = "检测到警告弹窗但未找到更多按钮，终止流程"
                    await self.send_notification(context, error_msg)
                    return (False, screen)

                await self.send_notification(context, "找到更多按钮，点击中...")
                self.click_position(*more_button_loc)
                time.sleep(1)

                # 更新截图
                screen = self.take_screenshot()

                # 查找并点击继续按钮
                await self.send_notification(context, "尝试查找继续按钮...")
                continue_button_loc = self.find_element_by_image('templates/continue2.png', threshold=0.5)
                if not continue_button_loc:
                    error_msg = "点击更多按钮后未找到继续按钮，终止流程"
                    await self.send_notification(context, error_msg)
                    return (False, screen)

                await self.send_notification(context, "点击继续按钮...")
                self.click_position(*continue_button_loc)
                time.sleep(1)
            else:
                await self.send_notification(context, "未检测到警告弹窗，继续执行...")

            # 更新截图
            screen = self.take_screenshot()

            # 执行登录
            if await self.login(username, password):
                await self.send_notification(context, "登录成功，等待系统加载...")
                time.sleep(3)
                # 更新截图
                screen = self.take_screenshot()
                return (True, screen)
            else:
                error_msg = "登录失败"
                await self.send_notification(context, error_msg)
                return (False, screen)

        except Exception as e:
            error_msg = f"登录流程发生错误: {str(e)}"
            await self.send_notification(context, error_msg)
            logging.error(f"登录流程异常: {str(e)}")
            return (False, screen)


    async def _unified_login_to_system(self, username, password, context="登录流程"):
        """统一的登录流程，根据配置选择Selenium或传统方式

        Args:
            username: 用户名
            password: 密码
            context: 操作上下文，用于日志记录

        Returns:
            tuple: (success: bool, screen_data: numpy.ndarray or bytes or None)
        """
        if self.use_selenium_login:
            # Selenium模式现在通过_do_selenium_punch完整处理，不应该调用到这里
            error_msg = "Selenium模式应该使用_do_selenium_punch方法，而不是统一登录流程"
            await self.send_notification(context, error_msg)
            logging.error(f"错误的调用路径: {context}")
            return (False, None)
        else:
            await self.send_notification(context, "使用传统PyAutoGUI登录模式")
            return await self._login_to_system(username, password, context)

    async def login(self, username, password):
        """登录系统"""
        try:
            await self.send_notification("登录流程", "开始登录流程...")

            # 输入用户名
            await self.send_notification("登录流程", "开始查找用户名输入框...")
            username_loc = self.find_element_with_label(
                'templates/input_field.png',
                'templates/username_label.png'
            )
            if username_loc:
                await self.send_notification("登录流程", "找到用户名输入框，开始输入...")
                self.click_position(*username_loc)
                self.input_text(username)  # 使用传入的用户名
                await self.send_notification("登录流程", f"用户名 {username} 输入完成")
            else:
                await self.send_notification("登录流程", "未找到用户名输入框")
                return False

            # 点击安全位置
            await self.send_notification("登录流程", "用户名输入完成，点击安全位置...")
            if not await self.click_safe_place():
                await self.send_notification("登录流程", "无法找到安全位置，继续执行...")

            time.sleep(1)

            # 输入密码
            await self.send_notification("登录流程", "开始查找密码输入框...")
            password_loc = self.find_element_with_label(
                'templates/input_field.png',
                'templates/password_label.png'
            )
            if password_loc:
                await self.send_notification("登录流程", "找到密码输入框，开始输入...")
                self.click_position(*password_loc)
                self.input_text(password)  # 使用传入的密码
                await self.send_notification("登录流程", "密码输入完成")
            else:
                await self.send_notification("登录流程", "未找到密码输入框")
                return False

            # 点击安全位置
            await self.send_notification("登录流程", "密码输入完成，点击安全位置...")
            if not await self.click_safe_place():
                await self.send_notification("登录流程", "无法找到安全位置，继续执行...")

            time.sleep(1)

            # 点击登录按钮
            await self.send_notification("登录流程", "开始查找登录按钮...")
            login_button_loc = self.find_element_by_image('templates/login_button.png')
            if login_button_loc:
                await self.send_notification("登录流程", "找到登录按钮，点击登录...")
                self.click_position(*login_button_loc)
                await self.send_notification("登录流程", "登录按钮点击完成")
            else:
                await self.send_notification("登录流程", "未找到登录按钮")
                return False

            time.sleep(5)  # 等待登录完成
            await self.send_notification("登录流程", "登录流程完成")
            return True

        except Exception as e:
            error_msg = f"登录过程发生错误: {str(e)}"
            await self.send_notification("登录流程", error_msg)
            return False

    async def get_remaining_time(self):
        """获取剩余时间并计算还需工作时间，增强OCR识别准确性"""
        try:
            # 查找剩余时间模板
            await self.send_notification("时间识别", "开始查找剩余时间...")
            left_time_loc = self.find_element_by_image('templates/left_time.png')
            if left_time_loc:
                await self.send_notification("时间识别", "找到剩余时间位置，开始截取区域...")

                # 获取浏览器窗口截图
                screen = self.take_screenshot()
                if screen is None:
                    await self.send_notification("时间识别", "截图失败")
                    return None

                # 获取浏览器窗口位置
                hwnd = self.get_browser_window()
                if not hwnd:
                    await self.send_notification("时间识别", "未找到浏览器窗口")
                    return None

                window_x, window_y = win32gui.GetWindowRect(hwnd)[:2]

                # 计算相对于浏览器窗口的坐标
                relative_x = left_time_loc[0] - window_x
                relative_y = left_time_loc[1] - window_y

                # 扩大截取区域，确保能完整捕获时间文本
                time_region = screen[
                    max(0, relative_y - 15):min(screen.shape[0], relative_y + 35),
                    relative_x:min(screen.shape[1], relative_x + 200)
                ]

                # 临时保存用于OCR

                # 增强图像预处理提高OCR准确性
                # 转换为灰度
                gray = cv2.cvtColor(time_region, cv2.COLOR_BGR2GRAY)
                # 二值化
                _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                # 去噪
                denoised = cv2.medianBlur(binary, 3)

                # 保存临时文件用于OCR
                temp_path = 'temp_time_region.png'
                cv2.imwrite(temp_path, denoised)

                await self.send_notification("时间识别", "开始OCR识别...")

                # 尝试多种OCR配置
                ocr_configs = [
                    r'--oem 3 --psm 6 -c preserve_interword_spaces=1',
                    r'--oem 3 --psm 7 -c preserve_interword_spaces=1',
                    r'--oem 3 --psm 8',
                    r'--oem 1 --psm 6'
                ]

                time_text = None
                for i, config in enumerate(ocr_configs):
                    try:
                        # 先尝试处理后的图像
                        text = pytesseract.image_to_string(
                            Image.open(temp_path),
                            lang='chi_sim',
                            config=config
                        ).strip()

                        if text and any(char in text for char in ['时', '分', '小', '钟']):
                            time_text = text
                            logging.info(f"OCR配置{i+1}识别成功: {text}")
                            break

                        # 如果预处理图像失败，尝试原始图像
                        temp_original_path = 'temp_time_region_original.png'
                        cv2.imwrite(temp_original_path, time_region)
                        text = pytesseract.image_to_string(
                            Image.open(temp_original_path),
                            lang='chi_sim',
                            config=config
                        ).strip()

                        if text and any(char in text for char in ['时', '分', '小', '钟']):
                            time_text = text
                            logging.info(f"OCR配置{i+1}（原始图像）识别成功: {text}")
                            os.remove(temp_original_path)
                            break

                        os.remove(temp_original_path)

                    except Exception as e:
                        logging.warning(f"OCR配置{i+1}失败: {e}")
                        continue

                # 删除临时文件
                try:
                    os.remove(temp_path)
                except:
                    pass

                if not time_text:
                    await self.send_notification("时间识别", "所有OCR配置都无法识别时间文本")
                    return None

                await self.send_notification("时间识别", f"OCR识别结果: {time_text}")

                # 使用更强大的正则表达式匹配
                time_patterns = [
                    r'[仅仅]?(\d+)\s*[小时時].*?(\d+)\s*分[钟鐘]',  # 原有模式
                    r'(\d+)\s*[小时時].*?(\d+)\s*分[钟鐘]',        # 不包含"仅"字
                    r'(\d+).*?(\d+)\s*分',                       # 简化模式
                    r'(\d+)[时時].*?(\d+)[分鐘]'                  # 更紧凑的模式
                ]

                time_match = None
                for pattern in time_patterns:
                    time_match = re.search(pattern, time_text)
                    if time_match:
                        logging.info(f"时间匹配成功，使用模式: {pattern}")
                        break

                if time_match:
                    hours = int(time_match.group(1))
                    minutes = int(time_match.group(2))
                    await self.send_notification("时间识别", f"已工作时间: {hours}小时{minutes}分钟")

                    # 计算还需工作的时间（8小时16分钟 - 已工作时间）
                    total_minutes = 8 * 60 + 16  # 8小时16分钟转换为分钟
                    worked_minutes = hours * 60 + minutes
                    remaining_minutes = total_minutes - worked_minutes

                    if remaining_minutes <= 0:
                        result = "0小时0分钟"  # 已满足工作时间要求
                    else:
                        remaining_hours = remaining_minutes // 60
                        remaining_mins = remaining_minutes % 60
                        result = f"{remaining_hours}小时{remaining_mins}分钟"

                    await self.send_notification("时间识别", f"计算结果 - 还需工作: {result}")
                    return result
                else:
                    await self.send_notification("时间识别", f"无法从文本中提取时间信息: {time_text}")
                    logging.warning(f"时间提取失败，OCR结果: {time_text}")
            else:
                await self.send_notification("时间识别", "未找到剩余时间位置")
                logging.warning("left_time模板匹配失败")
            return None
        except Exception as e:
            await self.send_notification("时间识别", f"获取剩余时间失败: {str(e)}")
            logging.error(f"get_remaining_time异常: {e}")
            return None

    def _register_self_canceling_job(self, time_str, coro_factory, tag):
        """[M46 修复] 注册一个"执行完能把自己从 schedule 真正移除"的每日定时任务。

        根因：schedule 库只在 job_func 的返回值是 schedule.CancelJob 时才移除任务，而本项目
        所有定时打卡任务注册的 job_func 都是 `lambda: asyncio.create_task(coro())`——它永远返回
        Task 对象，协程内部 `return schedule.CancelJob` 只是协程的返回值，scheduler 根本看不到。
        结果：已执行完 / 任务已删除的定时 job 永久留在 scheduler 里，每天同一时刻空转触发一次，
        靠 get_task_by_id 返回 None 的守卫跳过执行并刷"任务 #N 不存在，跳过执行"警告，长期运行下
        任务列表持续膨胀、日志噪声放大。
        这里改为：把注册得到的 job 对象通过 cancel_self 回调闭包给协程；协程在原本 `return
        schedule.CancelJob` 的位置改调 cancel_self()，由它按 job 引用执行 schedule.cancel_job(job)
        真正出队。同时显式传入 coro_factory（每次调用都新建）从根上规避 lambda 晚绑定（见 M86）。

        Args:
            time_str: 'HH:MM'
            coro_factory: callable(cancel_self) -> coroutine，传入"取消自身"回调，返回待执行协程
            tag: schedule tag，便于按类清理
        Returns:
            注册的 job 对象
        """
        job_box = {}

        def cancel_self():
            job = job_box.get('job')
            if job is not None:
                try:
                    schedule.cancel_job(job)
                except Exception as e:
                    logging.error(f"取消定时任务失败（tag={tag}）: {e}")

        job = schedule.every().day.at(time_str).do(
            lambda: asyncio.create_task(coro_factory(cancel_self))
        ).tag(tag)
        job_box['job'] = job
        return job

    async def schedule_retry_punch_out(self, delay_minutes, clear_existing=True):
        """设置定时重试下班打卡

        参数:
            delay_minutes: 延迟多少分钟后打卡
            clear_existing: 是否清除已有任务，默认为True
        """
        try:
            logging.info(f"开始设置定时下班打卡，延迟{delay_minutes}分钟")
            # 下限保护：delay_minutes 可能被钳为 0（is_overtime 但 confirmation_needed 仍 True），
            # 此时 now+0 取整到 HH:MM:00 通常 <= now，schedule 会把任务排到次日，当天重试落空。
            delay_minutes = max(1, int(delay_minutes))
            retry_time = datetime.now() + timedelta(minutes=delay_minutes)
            time_str = retry_time.strftime("%H:%M")

            if clear_existing:
                # 仅清除"下班重试"类型任务，不再清空全局 schedule（避免误清日报、其他用户的定时）
                schedule.clear('punch_out_retry')
                logging.info("清除了之前的所有 punch_out_retry 定时任务")
            else:
                # 仅替换 punch_out_retry tag 下的任务；不再启发式扫描 str(job.job_func)
                schedule.clear('punch_out_retry')
                logging.info("已替换 punch_out_retry tag 下所有定时任务")

            # [M9 修复] 把"保存任务记录到文件"提前到 job 定义之前，使 job 能闭包捕获自己的 task_id，
            # 从而在成功后只删除"自己这条"任务，绝不再 clear_tasks() 全清（否则会连带抹掉重试失败时
            # 新调度的下一轮重试任务和所有 punch_in 任务，导致重试链断裂、漏打下班卡）。
            # 保存定时任务到文件
            # [M90 修复] 两个分支都只删除已有的 punch_out 类型任务，绝不再 clear_tasks() 全清持久化任务。
            # 原 clear_existing=True 分支调用 clear_tasks()（task_manager.py 中是整文件清空），会连带抹掉
            # 用户的次日 punch_in 定时任务记录——当前进程里 punch_in 的 schedule job 还在但查 task_info 为
            # None 直接跳过，重启后也不再加载，上班定时悄无声息消失。与注释承诺"仅删自己 tag"一致，改为按
            # 类型逐条删除，与下方（原 else）已有逻辑保持一致。
            saved_tasks = list(self.task_manager.get_tasks())
            for task in saved_tasks:
                if task['type'] == 'punch_out':
                    self.task_manager.remove_task_by_id(task['id'])
                    logging.info(f"已从任务管理器中移除下班打卡任务 #{task['id']}")

            # 添加新的定时任务
            task_id = self.task_manager.add_task('punch_out', time_str)
            logging.info(f"保存定时任务到文件，任务ID: {task_id}")

            # [M7 修复] 把完整 retry_datetime 闭包进 job，用于在执行入口校验日期/时间偏差。
            # 否则 schedule.every().day 在睡过重试时刻后唤醒会立即补跑，导致次日早晨打出下班卡。
            retry_datetime = retry_time

            async def punch_out_job(cancel_self, retry_dt=retry_datetime, tid=task_id):
                try:
                    # [M7 修复] 入口三重守卫：偏差过大（跨天/睡过头）则清 tag、发通知并放弃，绝不跨天补打。
                    now = datetime.now()
                    drift = (now - retry_dt).total_seconds()
                    # 容差 30 分钟：超过即视为已错过（含次日唤醒首 tick 触发的场景）
                    if drift > 30 * 60:
                        logging.warning(
                            f"下班重试任务已过期（预定 {retry_dt.strftime('%Y-%m-%d %H:%M')}，"
                            f"现在 {now.strftime('%Y-%m-%d %H:%M')}，偏差 {drift/60:.0f} 分钟），跳过并清除"
                        )
                        # [M9 修复] 任务已过期：仅删除自己这条任务记录并取消本 job，
                        # 不再 clear_tasks() 全清，避免误删其他用户/类型的定时任务
                        # [M46 修复] 用 cancel_self() 按 job 引用真正出队（原 return CancelJob 在协程里失效）
                        self.task_manager.remove_task_by_id(tid)
                        await self.send_notification(
                            "下班打卡", f"⚠️ 下班重试时刻（{retry_dt.strftime('%H:%M')}）已过期超过容差，已取消该重试任务，请手动处理"
                        )
                        cancel_self()
                        return

                    logging.info("执行定时下班打卡任务")
                    # [M9 修复] 用 punch_out() 返回值判断：只有确认成功（True 且非 'cancelled'）才清理。
                    # 否则（工时不足返回 False / 被互斥拒绝返回 False / 被取消返回 'cancelled'）保留任务，
                    # 让 _do_selenium_punch/_schedule_unified_retry 新调度的下一轮重试得以存活。
                    result = await self.punch_out()
                    # 打卡完成后发送状态信息
                    await self.send_daily_status()
                    if result is True:
                        # [M9 修复] 仅删除自己这条任务记录 + 取消本 job（cancel_self 只移除当前运行的 job，
                        # 不会动到重试失败时新注册到 punch_out_retry tag 下的下一轮 job）。
                        # [M46 修复] cancel_self() 真正出队，替代失效的 return CancelJob。
                        self.task_manager.remove_task_by_id(tid)
                        logging.info(f"定时下班打卡任务执行完成（成功），已删除任务 #{tid}")
                        cancel_self()
                        return
                    else:
                        # 失败/取消：保留本任务与新调度的重试，不做任何清理
                        logging.info(f"定时下班打卡任务未成功（result={result!r}），保留重试任务 #{tid} 不清理")
                except Exception as e:
                    logging.error(f"执行定时下班打卡任务时发生错误: {str(e)}")

            # 设置定时任务（加 tag，便于后续按 tag 清除）
            # [M46 修复] 经 _register_self_canceling_job 注册，使协程内 cancel_self() 能真正从 scheduler 出队
            time_str = retry_time.strftime("%H:%M")
            self._register_self_canceling_job(
                time_str,
                lambda cancel_self: punch_out_job(cancel_self),
                'punch_out_retry'
            )
            logging.info(f"已设置定时任务: 每天{time_str}执行下班打卡 (tag=punch_out_retry)")

            if clear_existing:
                # [M90 修复] 实际只清除了已有的下班重试/下班打卡任务，文案随之修正，不再误称"所有定时任务"
                await self.send_notification("定时设置", f"已清除之前的下班打卡定时任务")
            else:
                await self.send_notification("定时设置", f"已替换已有的下班打卡任务")
            await self.send_notification("定时设置", f"设置新的下班打卡任务 #{task_id}: {time_str}")

            return time_str
        except Exception as e:
            error_msg = f"设置定时任务失败: {str(e)}"
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            await self.send_notification("定时设置", f"设置定时任务失败: {str(e)}")
            return None

    async def _schedule_unified_retry(self, remaining_times):
        """收集多用户剩余时间，按最长时间统一调度下班打卡定时任务（串行/并行路径共用）。

        Args:
            remaining_times: List[Dict[str, str]] 形如 [{'username': ..., 'remaining_time': 'X小时Y分钟'}, ...]
        Returns:
            Optional[str]: 调度的 'HH:MM' 时间字符串；无可调度时间则返回 None。
        """
        if not remaining_times:
            return None

        await self.send_notification("下班打卡", f"检测到{len(remaining_times)}个用户未满足下班条件")
        logging.info(f"统一定时调度：检测到{len(remaining_times)}个用户未满足下班条件，开始处理")

        max_remaining_time = None
        max_time_user = None

        for item in remaining_times:
            time_match = re.match(r'(\d+)小时(\d+)分钟', item.get('remaining_time', '') or '')
            if time_match:
                hours = int(time_match.group(1))
                minutes = int(time_match.group(2))
                total_minutes = hours * 60 + minutes
                logging.info(f"处理用户 {item.get('username')} 剩余时间: {total_minutes}分钟")

                if max_remaining_time is None or total_minutes > max_remaining_time:
                    max_remaining_time = total_minutes
                    max_time_user = item.get('username')

        if max_remaining_time is None:
            logging.warning("无法确定最长剩余时间，定时打卡设置失败")
            await self.send_notification("定时打卡", "⚠️ 无法确定最长剩余时间，定时打卡设置失败")
            return None

        logging.info(f"确定最长剩余时间: {max_remaining_time}分钟，来自用户: {max_time_user}")
        await self.send_notification(
            "定时打卡",
            f"将为所有用户设置统一的下班打卡时间，基于用户 {max_time_user} 的剩余时间：{max_remaining_time}分钟后"
        )

        try:
            # 只清除已有的下班打卡任务，保留其他类型任务
            saved_tasks = self.task_manager.get_tasks()
            for task in saved_tasks:
                if task['type'] == 'punch_out':
                    self.task_manager.remove_task_by_id(task['id'])
                    logging.info(f"已移除旧的下班打卡任务 #{task['id']}")

            retry_time = await self.schedule_retry_punch_out(max_remaining_time, clear_existing=False)
            if retry_time:
                logging.info(f"成功设置定时打卡时间: {retry_time}")
                await self.send_notification("定时打卡", f"✅ 已成功设置在 {retry_time} 为所有用户执行自动下班打卡")
                return retry_time
            else:
                logging.error("设置定时打卡失败，返回的时间为空")
                await self.send_notification("定时打卡", "❌ 设置定时打卡失败，返回的时间为空")
                return None
        except Exception as e:
            error_msg = f"设置定时打卡时发生错误: {str(e)}"
            logging.error(error_msg)
            await self.send_notification("定时打卡", f"❌ {error_msg}")
            return None

    async def schedule_punch_out(self, hour, minute):
        """设置指定时间的下班打卡任务
        
        参数:
            hour: 小时 (0-23)
            minute: 分钟 (0-59)
        
        返回:
            bool: 设置成功返回True，失败返回False
        """
        try:
            # 验证时间参数
            if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                raise ValueError(f"无效的时间参数: {hour:02d}:{minute:02d}")
            
            time_str = f"{hour:02d}:{minute:02d}"
            logging.info(f"开始设置定时下班打卡，时间：{time_str}")
            
            # 清除已有的下班打卡任务
            # [M46 修复] 原先用 `"punch_out" in str(job.job_func)` 启发式匹配——但注册的 job_func 是
            # `lambda: asyncio.create_task(...)`，str() 里根本不含 "punch_out"，从来匹配不到、清不掉旧任务
            # （新版经 _register_self_canceling_job 注册后更不含该字样）。改为与上班版对称的按 tag 清除。
            schedule.clear('punch_out_scheduled')
            logging.info("已移除已有的下班打卡定时任务 (tag=punch_out_scheduled)")

            # 删除已有的下班打卡任务记录
            saved_tasks = self.task_manager.get_tasks()
            for task in saved_tasks:
                if task['type'] == 'punch_out':
                    self.task_manager.remove_task_by_id(task['id'])
                    logging.info(f"已从任务管理器中移除下班打卡任务 #{task['id']}")

            # 添加新的定时任务记录（在定义函数之前创建，以便函数可以引用task_id）
            task_id = self.task_manager.add_task('punch_out', time_str)
            logging.info(f"保存定时任务到文件，任务ID: {task_id}")

            async def punch_out_job(cancel_self):
                try:
                    # 获取任务信息，检查是否应该执行
                    task_info = self.task_manager.get_task_by_id(task_id)
                    if not task_info:
                        logging.warning(f"任务 #{task_id} 不存在，跳过执行")
                        # [M46 修复] 任务记录已不在：cancel_self() 真正出队（原 return CancelJob 在协程里失效）
                        cancel_self()
                        return

                    # [M38 修复] 时间偏差守卫（双向，容差 30 分钟）：与 init_schedule_tasks 中同构。
                    # 防止长睡眠唤醒后 next_run 停留过去时刻、本 job 在错误时间（如周一早晨补跑周五的
                    # 17:30 任务，或当晚 23:50 补跑）打出下班卡污染考勤。偏差过大即视为错过，发通知请人工处理。
                    now = datetime.now()
                    try:
                        sched_h, sched_m = (int(x) for x in time_str.split(':'))
                        scheduled_today = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
                        drift = (now - scheduled_today).total_seconds()
                        if abs(drift) > 30 * 60:
                            logging.warning(
                                f"错过定时下班打卡（预定今日 {time_str}，现在 {now.strftime('%H:%M')}，"
                                f"偏差 {drift/60:.0f} 分钟），跳过下班打卡任务 #{task_id}（疑似唤醒补跑错时）"
                            )
                            await self.send_notification(
                                "下班打卡", f"⚠️ 错过定时下班打卡（预定 {time_str}，疑似休眠唤醒错时），请手动处理"
                            )
                            return
                    except Exception as drift_err:
                        logging.error(f"下班打卡时间偏差校验异常（任务 #{task_id}）: {drift_err}")

                    # 检查当前日期是否为任务创建日期
                    created_date = datetime.strptime(task_info['created_at'], '%Y-%m-%d %H:%M:%S').date()
                    current_date = now.date()

                    if current_date != created_date:
                        # 如果不是创建当天，检查是否为工作日
                        if not is_workday(current_date):
                            logging.info(f"非创建日期且非工作日（创建于{created_date}），跳过下班打卡任务 #{task_id}")
                            return
                        else:
                            logging.info(f"非创建日期但是工作日（创建于{created_date}），继续执行下班打卡任务 #{task_id}")
                    else:
                        logging.info(f"任务创建当天，执行定时下班打卡任务 ({time_str})")

                    # [M39 修复] 互斥占用检查：唤醒突发时多个错过任务同 tick 并发，若已有打卡操作进行中，
                    # 直接 punch_out() 会被 start_punch_operation 拒绝并静默返回 False → 当天下班卡丢失。
                    # 改为先探测 current_operation：被占用则发告警 + 5 分钟后一次性重试，不静默吞掉。
                    if self.current_operation is not None:
                        await self._handle_timed_punch_rejected('下班', time_str)
                        return
                    # 执行打卡
                    await self.punch_out()
                    # 打卡完成后发送状态信息
                    await self.send_daily_status()
                    logging.info(f"定时下班打卡任务 ({time_str}) 执行完成")

                    # 执行成功后删除任务
                    self.task_manager.remove_task_by_id(task_id)
                    logging.info(f"已删除已执行的下班打卡任务 #{task_id}")

                    # [M46 修复] cancel_self() 真正从 schedule 移除该任务（替代失效的 return CancelJob）
                    cancel_self()

                except Exception as e:
                    logging.error(f"执行定时下班打卡任务时发生错误: {str(e)}")

            # 设置定时任务（加 tag 便于按类清除）
            # [M46 修复] 经 _register_self_canceling_job 注册，使协程内 cancel_self() 能真正从 scheduler 出队
            self._register_self_canceling_job(
                time_str,
                lambda cancel_self: punch_out_job(cancel_self),
                'punch_out_scheduled'
            )
            logging.info(f"已设置定时任务: 每天{time_str}执行下班打卡（仅在创建当天或工作日执行，tag=punch_out_scheduled）")

            await self.send_notification("定时设置", f"设置下班打卡任务 #{task_id}: {time_str}\n任务将在今天执行，次日仅在工作日执行")
            
            return True
        except Exception as e:
            error_msg = f"设置定时下班打卡任务失败: {str(e)}"
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            await self.send_notification("定时设置错误", error_msg)
            return False

    async def schedule_punch_in(self, hour, minute):
        """设置指定时间的上班打卡任务（与 schedule_punch_out 完全对称，供 task_service 调用）

        新增动机：task_service 此前只把上班任务写入 scheduled_tasks.json，依赖
        "schedule_manager 下次循环拾起"——但运行期 schedule_manager 不会重扫文件，
        只有 init_schedule_tasks 在启动时加载，导致 GUI 设置的上班定时打卡根本没注册进 schedule。
        这里补一个对称方法真正把上班任务挂进 schedule，并复用与下班版一致的守卫（时间偏差/工作日/创建日）。

        参数:
            hour: 小时 (0-23)
            minute: 分钟 (0-59)

        返回:
            bool: 设置成功返回True，失败返回False
        """
        try:
            # 验证时间参数
            if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                raise ValueError(f"无效的时间参数: {hour:02d}:{minute:02d}")

            time_str = f"{hour:02d}:{minute:02d}"
            logging.info(f"开始设置定时上班打卡，时间：{time_str}")

            # 清除已有的上班打卡任务（仅 punch_in_scheduled tag，不误清下班/日报）
            schedule.clear('punch_in_scheduled')
            logging.info("已移除已有的上班打卡定时任务 (tag=punch_in_scheduled)")

            # 删除已有的上班打卡任务记录
            saved_tasks = self.task_manager.get_tasks()
            for task in saved_tasks:
                if task['type'] == 'punch_in':
                    self.task_manager.remove_task_by_id(task['id'])
                    logging.info(f"已从任务管理器中移除上班打卡任务 #{task['id']}")

            # 添加新的定时任务记录（在定义函数之前创建，以便函数可以引用task_id）
            task_id = self.task_manager.add_task('punch_in', time_str)
            logging.info(f"保存定时任务到文件，任务ID: {task_id}")

            # 用默认参数捕获 task_id/time_str，避免共享最后一次循环值（与 init 中加载逻辑同款守卫）
            async def punch_in_job(cancel_self, tid=task_id, ttime=time_str):
                try:
                    # 获取任务信息，检查是否应该执行
                    task_info = self.task_manager.get_task_by_id(tid)
                    if not task_info:
                        logging.warning(f"任务 #{tid} 不存在，跳过执行")
                        # [M46 修复] 任务记录已不在：cancel_self() 真正出队（原 return CancelJob 在协程里失效）
                        cancel_self()
                        return

                    # 时间偏差守卫：睡过头/唤醒补跑导致偏差过大（容差 15 分钟）则跳过，避免错时上班打卡
                    now = datetime.now()
                    try:
                        sched_h, sched_m = (int(x) for x in ttime.split(':'))
                        scheduled_today = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
                        drift = (now - scheduled_today).total_seconds()
                        if drift > 15 * 60:
                            logging.warning(
                                f"错过定时上班打卡（预定今日 {ttime}，现在 {now.strftime('%H:%M')}，"
                                f"偏差 {drift/60:.0f} 分钟），跳过上班打卡任务 #{tid}"
                            )
                            await self.send_notification(
                                "上班打卡", f"⚠️ 错过定时上班打卡（预定 {ttime}），请手动处理"
                            )
                            return
                    except Exception as drift_err:
                        logging.error(f"上班打卡时间偏差校验异常（任务 #{tid}）: {drift_err}")

                    # 工作日守卫：非创建日且非工作日跳过
                    current_date = now.date()
                    created_date = datetime.strptime(task_info['created_at'], '%Y-%m-%d %H:%M:%S').date()
                    if current_date != created_date:
                        if not is_workday(current_date):
                            logging.info(f"非创建日期且非工作日（创建于{created_date}），跳过上班打卡任务 #{tid}")
                            return
                        else:
                            logging.info(f"非创建日期但是工作日（创建于{created_date}），继续执行上班打卡任务 #{tid}")
                    else:
                        logging.info(f"任务创建当天，执行定时上班打卡任务 ({ttime})")

                    # [M39 修复] 互斥占用检查：被其他打卡操作占用时不再静默丢卡，改为告警 + 一次性短延迟重试
                    if self.current_operation is not None:
                        await self._handle_timed_punch_rejected('上班', ttime)
                        return
                    # 执行打卡
                    await self.punch_in()
                    # 打卡完成后发送状态信息
                    await self.send_daily_status()
                    logging.info(f"定时上班打卡任务 ({ttime}) 执行完成")

                    # 执行成功后删除任务
                    self.task_manager.remove_task_by_id(tid)
                    logging.info(f"已删除已执行的上班打卡任务 #{tid}")

                    # [M46 修复] cancel_self() 真正从 schedule 移除该任务（替代失效的 return CancelJob）
                    cancel_self()

                except Exception as e:
                    logging.error(f"执行定时上班打卡任务时发生错误: {str(e)}")

            # 设置定时任务（加 tag 便于按类清除）
            # [M46 修复] 经 _register_self_canceling_job 注册，使协程内 cancel_self() 能真正从 scheduler 出队
            self._register_self_canceling_job(
                time_str,
                lambda cancel_self: punch_in_job(cancel_self),
                'punch_in_scheduled'
            )
            logging.info(f"已设置定时任务: 每天{time_str}执行上班打卡（仅在创建当天或工作日执行，tag=punch_in_scheduled）")

            await self.send_notification("定时设置", f"设置上班打卡任务 #{task_id}: {time_str}\n任务将在今天执行，次日仅在工作日执行")

            return True
        except Exception as e:
            error_msg = f"设置定时上班打卡任务失败: {str(e)}"
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            await self.send_notification("定时设置错误", error_msg)
            return False

    # [M39 补全] 定时打卡互斥拒绝后的最大重试次数：避免极端连续占用下无限重排，
    # 同时把"只重试一次"扩成有界多次重试，杜绝 5 分钟后仍被占用时的二次静默丢卡。
    _TIMED_PUNCH_MAX_RETRY = 3

    # [M49 修复] 下班 unable_escape 但 OCR/计算拿不到剩余时间时的保守默认重试间隔（分钟）。
    # 原先这种情况不调度任何重试，失败邮件却写"系统会在适当时间自动重试"——用户信了就漏打下班卡。
    # 改为按此固定间隔兜底调度一次重试，使文案与行为一致。
    _PUNCH_OUT_FALLBACK_RETRY_MINUTES = 45

    async def _handle_timed_punch_rejected(self, punch_type, scheduled_time, attempt=1):
        """[M39 修复] 定时打卡被互斥拒绝（current_operation 已被占用）时的补偿：发告警 + 短延迟重排。

        场景：长睡眠唤醒后多个错过任务在同一 tick 并发争抢 current_operation 锁，后到的定时打卡
        拿到 (False, '当前已有...操作正在进行中') 后原先 punch_in_job/punch_out_job 不检查返回值、
        静默吞掉 → 当天上班/下班卡彻底丢失且无任何通知。这里改为：通知用户 + 5 分钟后重试
        （内存级一次性 job，return CancelJob 自动移除；不写 scheduled_tasks.json，避免跨天残留）。

        [M39 补全] 残留缺口修复：原 _one_shot_retry 直接 await punch_in/out 而不复探 current_operation，
        且无论成败都只重试一次——若 5 分钟后仍被占用，punch_*() 经 start_punch_operation 返回 False 后
        又被静默吞掉，极端连续占用下仍丢一次卡。现改为有界重试链（上限 _TIMED_PUNCH_MAX_RETRY）：
        重试触发时先复探 current_operation，仍被占用 / punch_*() 返回 False 即视为失败并重排下一次；
        仅在成功、偏差过期、或重试次数耗尽时停止，且耗尽时显式发失败告警，确保任何放弃都有通知不再静默。

        Args:
            punch_type: '上班' 或 '下班'
            scheduled_time: 原定 'HH:MM'，仅用于通知文案
            attempt: 本次属于第几次重试（从 1 计），用于有界控制与文案
        """
        retry_delay_min = 5
        retry_time = datetime.now() + timedelta(minutes=retry_delay_min)
        retry_str = retry_time.strftime("%H:%M")
        # 用专属 tag，与工时不足的 punch_out_retry / GUI 的 punch_*_scheduled 隔离，互不误清
        tag = 'punch_in_oneshot_retry' if punch_type == '上班' else 'punch_out_oneshot_retry'

        await self.send_notification(
            "定时打卡",
            f"⚠️ 定时{punch_type}打卡（{scheduled_time}）因有其他打卡操作进行中被跳过，"
            f"将于约 {retry_str} 自动重试（第 {attempt}/{self._TIMED_PUNCH_MAX_RETRY} 次）"
        )
        logging.warning(
            f"定时{punch_type}打卡被互斥拒绝，安排 {retry_delay_min} 分钟后（{retry_str}）"
            f"重试（第 {attempt}/{self._TIMED_PUNCH_MAX_RETRY} 次）"
        )

        async def _one_shot_retry(cancel_self, dt=retry_time, pt=punch_type, orig=scheduled_time, att=attempt):
            try:
                # 重试也加偏差守卫：若这条 job 本身又被睡眠拖到很久之后才触发，则放弃不补打
                drift = (datetime.now() - dt).total_seconds()
                if drift > 30 * 60:
                    logging.warning(f"{pt}打卡重试已过期（偏差 {drift/60:.0f} 分钟），放弃")
                    await self.send_notification(
                        "定时打卡", f"⚠️ 定时{pt}打卡（原定 {orig}）重试已过期，已放弃补打，请手动处理"
                    )
                    # [M46 修复] cancel_self() 真正出队（原 return CancelJob 在协程里失效，会让一次性重试退化为每日重复）
                    cancel_self()
                    return

                logging.info(f"执行{pt}打卡重试（原定 {orig}，第 {att}/{self._TIMED_PUNCH_MAX_RETRY} 次）")

                # [M39 补全] 复探互斥：重试触发时仍被占用，则不去硬调 punch_*()（避免被静默拒绝丢卡），
                # 而是按有界规则重排下一次或耗尽告警
                still_busy = self.current_operation is not None
                punch_ok = False
                if not still_busy:
                    # punch_in/out 经 start_punch_operation：成功返回 operation_task 结果，被拒/失败返回 False
                    if pt == '上班':
                        punch_ok = bool(await self.punch_in())
                    else:
                        punch_ok = bool(await self.punch_out())
                    if punch_ok:
                        await self.send_daily_status()
                        logging.info(f"{pt}打卡重试成功（原定 {orig}，第 {att} 次）")
                        # [M46 修复] cancel_self() 真正出队
                        cancel_self()
                        return

                # 走到这里：要么仍被占用，要么 punch_*() 返回 False（被拒/失败）——按有界规则处理
                if att >= self._TIMED_PUNCH_MAX_RETRY:
                    reason = "仍有其他打卡操作进行中" if still_busy else "打卡未成功"
                    logging.warning(f"{pt}打卡重试已达上限（{self._TIMED_PUNCH_MAX_RETRY} 次，{reason}），放弃")
                    await self.send_notification(
                        "定时打卡",
                        f"❌ 定时{pt}打卡（原定 {orig}）已重试 {self._TIMED_PUNCH_MAX_RETRY} 次仍失败"
                        f"（{reason}），已放弃自动补打，请手动处理"
                    )
                else:
                    # 重排下一次：复用本方法（attempt+1），仍走告警 + 短延迟的有界重试链，绝不静默吞掉
                    await self._handle_timed_punch_rejected(pt, orig, attempt=att + 1)
            except Exception as e:
                logging.error(f"{pt}打卡重试发生错误: {str(e)}")
            # 本条一次性 job 任务完成（无论结果），cancel_self() 从 schedule 移除自身
            # [M46 修复] 原 return CancelJob 在 `lambda: asyncio.create_task(...)` 下永远到不了 scheduler，
            # 会让"一次性重试"退化为每日固定重复执行；改用 cancel_self() 按 job 引用真正出队。
            cancel_self()

        self._register_self_canceling_job(
            retry_str,
            lambda cancel_self: _one_shot_retry(cancel_self),
            tag
        )

    def init_schedule_tasks(self):
        """初始化定时任务"""
        # 启动时清除所有现有任务（合理：首次初始化场景）
        # 注：运行期间的其他 schedule.clear 都改为按 tag 过滤，不会回到这里
        schedule.clear()

        # 设置每天早上的状态推送（加 tag）
        async def daily_status_job():
            await self.send_daily_status()
        schedule.every().day.at(self.daily_status_time).do(lambda: asyncio.create_task(daily_status_job())).tag('daily_status')

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

        # AI 资讯定时刷新（每 30 分钟）：阻塞 requests 放线程执行，避免卡事件循环；
        # 刷新成功且 GUI 模式（_event_bus 非 None）时通过 WS 推送更新摘要（更新时间 + 条数）。
        async def ai_news_job():
            try:
                from modules.ai_news_service import refresh as _refresh_news
                loop = asyncio.get_running_loop()
                started = int(time.time())
                contract = await loop.run_in_executor(None, _refresh_news)
                # 成功守卫（与 exchange_rate_job 同口径）：refresh 失败时返回的是旧缓存契约
                # （updated_at 是旧值或 None），只有 updated_at >= 本轮发起时刻才说明真拉到了新数据；
                # 失败也推送只会诱使前端再发一次必败请求陪跑 loading
                updated_at = (contract or {}).get('updated_at')
                if updated_at and updated_at >= started and self._event_bus is not None:
                    self._event_bus.publish_threadsafe('ai_news:update', {
                        'updated_at': updated_at,
                        'count': (contract or {}).get('count'),
                    })
            except Exception as e:
                logging.error(f"定时刷新 AI 资讯任务时发生错误: {str(e)}")
        schedule.every(30).minutes.do(lambda: asyncio.create_task(ai_news_job())).tag('ai_news_update')

        # 从文件加载保存的定时任务
        saved_tasks = self.task_manager.get_tasks()
        for task in saved_tasks:
            if task['type'] == 'punch_out':
                task_id = task['id']
                task_time = task['scheduled_time']

                async def punch_out_job(cancel_self, tid=task_id, ttime=task_time):
                    try:
                        # 获取任务信息，检查是否应该执行
                        task_info = self.task_manager.get_task_by_id(tid)
                        if not task_info:
                            logging.warning(f"任务 #{tid} 不存在，跳过执行")
                            # [M46 修复] 任务记录已不在：cancel_self() 真正出队（原 return CancelJob 在协程里失效）
                            cancel_self()
                            return

                        # [M38 修复] 时间偏差守卫（双向，容差 30 分钟）：长睡眠唤醒后 schedule 的 next_run
                        # 可能停留在过去时刻，导致本 job 在错误时间补跑——典型为周五 17:30 任务在周一 09:00 唤醒
                        # 首 tick 触发（now 远早于今日 17:30，drift 大负值），或当日 17:25 睡到 23:50 唤醒补跑
                        # （drift 大正值）。两种都会污染考勤，统一拦截：偏差过大即视为错过，发通知请人工处理，
                        # 不自动打卡。今日预定时刻与 now 同日比较（下班是固定每日时刻，按今天的 HH:MM 锚定）。
                        now = datetime.now()
                        try:
                            sched_h, sched_m = (int(x) for x in ttime.split(':'))
                            scheduled_today = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
                            drift = (now - scheduled_today).total_seconds()
                            if abs(drift) > 30 * 60:
                                logging.warning(
                                    f"错过定时下班打卡（预定今日 {ttime}，现在 {now.strftime('%H:%M')}，"
                                    f"偏差 {drift/60:.0f} 分钟），跳过下班打卡任务 #{tid}（疑似唤醒补跑错时）"
                                )
                                await self.send_notification(
                                    "下班打卡", f"⚠️ 错过定时下班打卡（预定 {ttime}，疑似休眠唤醒错时），请手动处理"
                                )
                                return
                        except Exception as drift_err:
                            logging.error(f"下班打卡时间偏差校验异常（任务 #{tid}）: {drift_err}")

                        # 检查当前日期是否为任务创建日期
                        created_date = datetime.strptime(task_info['created_at'], '%Y-%m-%d %H:%M:%S').date()
                        current_date = now.date()

                        if current_date != created_date:
                            # 如果不是创建当天，检查是否为工作日
                            if not is_workday(current_date):
                                logging.info(f"非创建日期且非工作日（创建于{created_date}），跳过下班打卡任务 #{tid}")
                                return
                            else:
                                logging.info(f"非创建日期但是工作日（创建于{created_date}），继续执行下班打卡任务 #{tid}")
                        else:
                            logging.info(f"任务创建当天，执行定时下班打卡任务 ({ttime})")

                        # [M39 修复] 互斥占用检查：被其他打卡操作占用时不再静默丢卡，改为告警 + 一次性短延迟重试
                        if self.current_operation is not None:
                            await self._handle_timed_punch_rejected('下班', ttime)
                            return
                        # 执行打卡
                        await self.punch_out()
                        # 打卡完成后发送状态信息
                        await self.send_daily_status()
                        logging.info(f"定时下班打卡任务 ({ttime}) 执行完成")

                        # 执行成功后删除任务
                        self.task_manager.remove_task_by_id(tid)
                        logging.info(f"已删除已执行的下班打卡任务 #{tid}")

                        # [M46 修复] cancel_self() 真正从 schedule 移除该任务（替代失效的 return CancelJob）
                        cancel_self()

                    except Exception as e:
                        logging.error(f"执行定时下班打卡任务时发生错误: {str(e)}")

                # [M46+M86 修复] 经 _register_self_canceling_job 注册：协程内 cancel_self() 才能真正出队；
                # 用默认参数 _f=punch_out_job 显式绑定本轮循环的协程函数，根除原 `lambda: ...punch_out_job()`
                # 按名字晚绑定导致"所有 job 都执行最后一个 punch_out_job"的缺陷。
                self._register_self_canceling_job(
                    task['scheduled_time'],
                    lambda cancel_self, _f=punch_out_job: _f(cancel_self),
                    'punch_out_scheduled'
                )
            elif task['type'] == 'punch_in':
                task_id = task['id']
                task_time = task['scheduled_time']

                # [M6 修复] 原 punch_in_job 完全裸奔：不校验时间偏差/工作日/创建日，
                # 睡过 08:30 后唤醒首 tick 会立即补打上班卡（考勤记录成下午上班），
                # 且 schedule.every().day 会含周末每天重复执行。这里补齐与 punch_out_job 对称的三重守卫。
                async def punch_in_job(cancel_self, tid=task_id, ttime=task_time):
                    try:
                        # 获取任务信息，检查是否应该执行
                        task_info = self.task_manager.get_task_by_id(tid)
                        if not task_info:
                            logging.warning(f"任务 #{tid} 不存在，跳过执行")
                            # [M46 修复] 任务记录已不在：cancel_self() 真正出队（原 return CancelJob 在协程里失效）
                            cancel_self()
                            return

                        # [M6 修复 a] 时间偏差守卫：当前时间与今日预定时刻偏差过大（睡过头/唤醒补跑）则跳过，
                        # 避免在午后唤醒瞬间真实打出错时上班卡。容差 15 分钟。
                        now = datetime.now()
                        try:
                            sched_h, sched_m = (int(x) for x in ttime.split(':'))
                            scheduled_today = now.replace(hour=sched_h, minute=sched_m, second=0, microsecond=0)
                            drift = (now - scheduled_today).total_seconds()
                            if drift > 15 * 60:
                                logging.warning(
                                    f"错过定时上班打卡（预定今日 {ttime}，现在 {now.strftime('%H:%M')}，"
                                    f"偏差 {drift/60:.0f} 分钟），跳过上班打卡任务 #{tid}"
                                )
                                await self.send_notification(
                                    "上班打卡", f"⚠️ 错过定时上班打卡（预定 {ttime}），请手动处理"
                                )
                                return
                        except Exception as drift_err:
                            logging.error(f"上班打卡时间偏差校验异常（任务 #{tid}）: {drift_err}")

                        # [M6 修复 b] 工作日守卫：非工作日（周末/节假日）跳过，避免每天固定打上班卡
                        current_date = now.date()
                        created_date = datetime.strptime(task_info['created_at'], '%Y-%m-%d %H:%M:%S').date()
                        if current_date != created_date:
                            if not is_workday(current_date):
                                logging.info(f"非创建日期且非工作日（创建于{created_date}），跳过上班打卡任务 #{tid}")
                                return
                            else:
                                logging.info(f"非创建日期但是工作日（创建于{created_date}），继续执行上班打卡任务 #{tid}")
                        else:
                            logging.info(f"任务创建当天，执行定时上班打卡任务 ({ttime})")

                        # [M39 修复] 互斥占用检查：唤醒突发时若已有打卡操作进行中（如先到的下班补跑占了锁），
                        # 上班打卡会被静默拒绝 → 当天上班卡彻底丢失。改为告警 + 5 分钟后一次性重试。
                        if self.current_operation is not None:
                            await self._handle_timed_punch_rejected('上班', ttime)
                            return
                        # 执行打卡
                        await self.punch_in()
                        # 打卡完成后发送状态信息
                        await self.send_daily_status()
                        logging.info(f"定时上班打卡任务 ({ttime}) 执行完成")

                        # [M6 修复 c] 执行成功后删除任务记录
                        self.task_manager.remove_task_by_id(tid)
                        logging.info(f"已删除已执行的上班打卡任务 #{tid}")

                        # [M46 修复] cancel_self() 真正从 schedule 移除该任务（替代失效的 return CancelJob）
                        cancel_self()

                    except Exception as e:
                        logging.error(f"执行定时上班打卡任务时发生错误: {str(e)}")

                # [M46+M86 修复] 经 _register_self_canceling_job 注册：协程内 cancel_self() 才能真正出队；
                # 用默认参数 _f=punch_in_job 显式绑定本轮循环的协程函数，根除原 `lambda: ...punch_in_job()`
                # 按名字晚绑定导致"所有 job 都执行最后一个 punch_in_job"的缺陷。
                self._register_self_canceling_job(
                    task['scheduled_time'],
                    lambda cancel_self, _f=punch_in_job: _f(cancel_self),
                    'punch_in_scheduled'
                )

        # 启动时触发一次汇率首刷（容错、不阻塞启动）：放 daemon 线程，避免阻塞 __init__ 与事件循环。
        # 每个服务请求会在本地代理连接失败时立即回退默认网络，不再等待统一健康 URL。
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

        # 启动时触发一次 AI 资讯首刷（容错、不阻塞启动）：放 daemon 线程，避免阻塞 __init__ 与事件循环。
        def _first_ai_news_refresh():
            try:
                from modules.ai_news_service import refresh as _refresh_news
                started = int(time.time())
                contract = _refresh_news()
                updated_at = (contract or {}).get('updated_at')
                # 首刷可能撞上前端在途的必败请求：refresh 的 single-flight 会直接回旧缓存，
                # updated_at 没前进。首刷是一次性的，这里等几秒再补试一次，别让补发落空。
                if not (updated_at and updated_at >= started):
                    time.sleep(5)
                    contract = _refresh_news()
                    updated_at = (contract or {}).get('updated_at')
                # 首刷成功后补一次 WS 推送（payload 与 ai_news_job 一致）：冷启动时前端首拉
                # 若发生在代理就绪前会拿到空数据、记为失败态，不推送就只能等前端轮询兜底
                # （最长约 15 分钟）。守卫口径同 ai_news_job：只有 updated_at 为本轮新写入才推。
                if updated_at and updated_at >= started and self._event_bus is not None:
                    self._event_bus.publish_threadsafe('ai_news:update', {
                        'updated_at': updated_at,
                        'count': (contract or {}).get('count'),
                    })
            except Exception as e:
                logging.error(f"启动 AI 资讯首刷失败（忽略）: {str(e)}")
        try:
            import threading as _threading
            _threading.Thread(target=_first_ai_news_refresh,
                              name='aas-ai-news-first', daemon=True).start()
        except Exception as e:
            logging.error(f"启动 AI 资讯首刷线程失败（忽略）: {str(e)}")

    async def send_daily_status(self):
        """发送每日状态信息"""
        # 5 秒去重：并行打卡多用户成功时会同时触发，避免重复发出 N 份日报
        async with self._daily_status_lock:
            now = datetime.now()
            if self._last_daily_status_send is not None:
                elapsed = (now - self._last_daily_status_send).total_seconds()
                if elapsed < 5:
                    logging.info(f"send_daily_status 5 秒内重复触发（间隔 {elapsed:.2f}s），跳过")
                    return
            self._last_daily_status_send = now

        try:
            # 构建与 /status 命令相同的状态信息
            current_time = datetime.now()

            # 获取系统资源使用情况
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent()

            # 获取程序运行时间
            process = psutil.Process()
            uptime = datetime.now() - datetime.fromtimestamp(process.create_time())
            hours, remainder = divmod(uptime.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)

            # 检查是否在工作时间内和日期类型
            is_work_time = self.is_work_time(current_time)
            current_date = current_time.date()
            is_holiday_today = is_holiday(current_date)
            is_workday_today = is_workday(current_date)

            # 格式化状态消息
            status_text = (
                "🤖 打卡系统状态\n"
                "━━━━━━━━━━━━━━━\n"
                f"📅 当前时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📌 今日类型：{'🏖️ 节假日' if is_holiday_today else '💼 工作日' if is_workday_today else '🎉 休息日'}\n"
                f"⏰ 工作状态：{'🟢 工作时间' if is_work_time else '🔴 非工作时间'}\n\n"
            )

            # 添加每个用户的打卡记录
            # 读取运行态打卡桶 today_punch_records（由 _set_user_punch_time 写入），而非
            # config 静态 user['punch_records']（恒为 None、从无写入），否则日报永远显示"未打卡"。
            # [M47 修复] 与 get_status_snapshot 同款日期校验：归属日期 record['date'] 不是今天
            # （含周末/假日次日尚未触发跨天重置）一律视为"未打卡"。否则连续运行跨周末时，周六/日
            # 的日报会把周五的上下班时间当"今日打卡"展示，标题日期却是当天，误导用户以为今天打过卡。
            status_text += "📍 今日打卡记录\n"
            for uname, record in self.today_punch_records.items():
                if record.get('date') != current_date:
                    in_t = None
                    out_t = None
                else:
                    in_t = record.get('punch_in_time')
                    out_t = record.get('punch_out_time')
                status_text += f"\n用户: {uname}\n"
                status_text += f"上班打卡：{'✅ ' + in_t.strftime('%H:%M:%S') if in_t else '❌ 未打卡'}\n"
                status_text += f"下班打卡：{'✅ ' + out_t.strftime('%H:%M:%S') if out_t else '❌ 未打卡'}\n"

            status_text += (
                "\n⚙️ 系统信息\n"
                f"运行时长：{int(hours)}小时{int(minutes)}分钟\n"
                f"内存使用：{memory.percent}%\n"
                f"CPU使用：{cpu_percent}%\n"
                f"心跳状态：{'🟢 正常' if self.heartbeat_miss_count == 0 else '🟡 警告'}\n\n"

                "📋 配置信息\n"
                f"上班时间：{self.work_start_time}\n"
                f"下班时间：{self.work_end_time}\n"
                f"迟到阈值：{self.late_threshold}分钟\n"
                f"早退阈值：{self.early_leave_threshold}分钟\n"
            )

            # 获取定时任务列表
            saved_tasks = self.task_manager.get_tasks()
            if saved_tasks:
                status_text += "\n⏱ 定时任务列表\n"
                for task in saved_tasks:
                    if task['type'] == 'punch_out':
                        next_run = datetime.strptime(task['scheduled_time'], "%H:%M").replace(
                            year=current_time.year,
                            month=current_time.month,
                            day=current_time.day
                        )
                        # 如果时间已过，显示明天的时间
                        if next_run < current_time:
                            next_run = next_run + timedelta(days=1)
                        status_text += f"➤ [任务 #{task['id']}] 下班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
                    elif task['type'] == 'punch_in':
                        next_run = datetime.strptime(task['scheduled_time'], "%H:%M").replace(
                            year=current_time.year,
                            month=current_time.month,
                            day=current_time.day
                        )
                        # 如果时间已过，显示明天的时间
                        if next_run < current_time:
                            next_run = next_run + timedelta(days=1)
                        status_text += f"➤ [任务 #{task['id']}] 上班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
            else:
                status_text += "\n⏱ 暂无定时任务\n"

            await self.bot.send_message("系统状态", status_text)

        except Exception as e:
            logging.error(f"发送每日状态信息时发生错误: {str(e)}")


    async def _do_punch(self, punch_type="上班", username=None, password=None, collect_remaining_time=False, cancel_event=None):
        """通用打卡方法

        Args:
            cancel_event: [M11 修复] 本次操作专属取消事件，串行 Selenium 路径透传给 _do_selenium_punch，
                使其取消检查点能感知精确取消（详见 _do_selenium_punch 文档）。
        """
        screen = None
        remaining_time_info = None  # 用于存储剩余工作时间信息

        try:
            # 重置消息
            self.current_message = f"开始{punch_type}打卡流程 - 用户: {username}"
            self.message_id = None

            # 根据配置选择打卡模式
            if self.use_selenium_login:
                # [M10 修复] 去掉原先位于此处的"bot.app 未初始化即 return (False, None)"硬门槛：
                # main.py 支持 Telegram Bot 初始化失败后降级运行（bot_available=False），Selenium 打卡
                # 本身不依赖 bot（_do_selenium_punch 内所有 bot 调用都有 try/except，通知会经
                # send_notification 转推 GUI event_bus + 邮件）。原门槛会让降级状态下 GUI/定时打卡全部秒失败
                # 且不发任何通知，与降级运行设计矛盾，故此处不再拦截，照常进入 Selenium 分支。
                await self.send_notification("打卡流程", f"使用Selenium模式执行{punch_type}打卡")
                return await self._do_selenium_punch(punch_type, username, password, collect_remaining_time, cancel_event=cancel_event)
            else:
                # [M10 修复] PyAutoGUI 传统模式的通知/截图强依赖 bot（下方多处直接用 self.bot.app.bot），
                # bot 缺失时无法完成传统流程，这里做软降级：仅传统模式下校验 bot，缺失则记录并返回。
                if not self.bot or not hasattr(self.bot, 'app') or not self.bot.app:
                    error_msg = f"Telegram bot未正确初始化，PyAutoGUI模式无法执行{punch_type}打卡"
                    logging.error(error_msg)
                    return (False, None)
                await self.send_notification("打卡流程", f"使用PyAutoGUI模式执行{punch_type}打卡")

            # 使用统一的登录流程方法（PyAutoGUI模式）
            login_success, screen = await self._unified_login_to_system(username, password, "打卡流程")
            if not login_success:
                error_msg = "登录流程失败，无法进行打卡"
                await self.send_notification("打卡流程", error_msg)
                # 发送失败截图
                if screen is not None:
                    screenshot_path = 'punch_error.png'
                    self._save_screenshot_data(screen, screenshot_path)

                    # 保存失败截图到用户目录
                    self.save_user_screenshot(screen, username, punch_type, success=False)
                    try:
                        # 发送Telegram截图
                        with open(screenshot_path, 'rb') as photo:
                            await self.bot.app.bot.send_photo(
                                chat_id=self.bot.chat_id,
                                photo=photo,
                                caption=f"{punch_type}打卡失败 - {error_msg}"
                            )

                        # 发送邮件通知
                        surname = self.get_surname_honorific(username)
                        email_subject = f"{punch_type}打卡失败通知 - {surname} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        email_body = f"{surname}您好，\n\n您的{punch_type}打卡尝试失败。\n\n原因：{error_msg}\n\n请管理员检查系统状态。\n\n此邮件由自动打卡系统发送，请勿回复。"

                        # 复制截图用于邮件发送
                        email_screenshot_path = f'logs/punch_error_email.png'
                        with open(screenshot_path, 'rb') as f_in:
                            img_data = f_in.read()
                            with open(email_screenshot_path, 'wb') as f_out:
                                f_out.write(img_data)

                        # 发送邮件
                        await self.send_email_with_attachment(email_subject, email_body, email_screenshot_path, f"{punch_type}(登录失败)")

                        # 删除临时文件（邮件截图由后台发送线程清理，主流程仅删 Telegram 临时截图）
                        os.remove(screenshot_path)
                    except Exception as e:
                        await self.send_notification("打卡流程", f"通知发送失败: {str(e)}")

                # 关闭浏览器窗口
                await self.send_notification("打卡流程", "正在关闭浏览器窗口...")
                if self.bot.close_browser():
                    await self.send_notification("打卡流程", "浏览器窗口已关闭")
                else:
                    await self.send_notification("打卡流程", "关闭浏览器窗口失败")

                return (False, None)

            # 登录成功，继续打卡流程
            # 根据打卡类型选择不同的按钮模板
            button_template = 'templates/punch_button.png' if punch_type == "上班" else 'templates/punch_out_button.png'
            await self.send_notification("打卡流程", "开始查找打卡按钮...")
            punch_button_loc = self.find_element_by_image(button_template)
            if punch_button_loc:
                await self.send_notification("打卡流程", "找到打卡按钮，开始打卡...")
                self.click_position(*punch_button_loc)
                time.sleep(2)  # 等待打卡结果显示

                # 更新截图
                screen = self.take_screenshot()
                if screen is None:
                    await self.send_notification("打卡流程", "截图失败")
                    return (False, None)

                current_time = datetime.now()
                punch_success = False

                # 检查异常打卡情况
                if punch_type == "上班":
                    if self._is_late_punch_in(current_time):
                        await self.send_notification(
                            "打卡异常",
                            f"⚠️ 检测到迟到打卡！打卡时间：{current_time.strftime('%H:%M')}"
                        )
                    self._set_user_punch_time(username, 'punch_in_time', current_time)
                    # 保存打卡记录
                    self.punch_record_manager.update_record(
                        current_time.strftime('%Y-%m-%d'),
                        "上班",
                        current_time.strftime('%H:%M:%S')
                    )
                    punch_success = True
                else:  # 下班打卡
                    # 检查是否存在unable_escape情况
                    await self.send_notification("打卡流程", "检查是否满足下班条件...")

                    unable_escape_loc = self.find_element_by_image('templates/unable_escape.png')

                    # 获取模板匹配的置信度信息（通过重新匹配）
                    unable_escape_confidence = 0.0
                    try:
                        template = cv2.imread('templates/unable_escape.png')
                        if template is not None:
                            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                            _, max_val, _, _ = cv2.minMaxLoc(result)
                            unable_escape_confidence = max_val
                            logging.info(f"unable_escape模板匹配置信度: {unable_escape_confidence:.3f}")
                    except Exception as e:
                        logging.warning(f"无法获取unable_escape置信度: {e}")

                    if unable_escape_loc:
                        await self.send_notification("打卡流程", f"检测到下班限制（置信度: {unable_escape_confidence:.3f}）")
                        # 获取剩余工作时间
                        remaining_time = await self.get_remaining_time()
                        if remaining_time:
                            error_msg = f"未满足下班条件，还需工作: {remaining_time}"
                            remaining_time_info = remaining_time  # 保存剩余时间信息

                            # 从剩余时间中提取分钟数
                            time_match = re.match(r'(\d+)小时(\d+)分钟', remaining_time)
                            if time_match:
                                hours = int(time_match.group(1))
                                minutes = int(time_match.group(2))
                                total_minutes = hours * 60 + minutes

                                # 当不是收集模式时，直接设置定时任务
                                if not collect_remaining_time:
                                    logging.info(f"单账户模式：直接设置定时打卡，剩余时间：{total_minutes}分钟")
                                    # 设置定时重试，直接使用计算出的时间，保留之前的非下班打卡任务
                                    retry_time = await self.schedule_retry_punch_out(total_minutes, clear_existing=False)
                                    error_msg += f"\n已设置在 {retry_time} 自动重试下班打卡"
                                else:
                                    logging.info(f"多账户模式：收集剩余时间信息：{total_minutes}分钟")
                        else:
                            # [M49 修复] unable_escape 但 OCR 拿不到剩余时间：原先不调度任何重试，
                            # 失败邮件却承诺"系统会在适当时间自动重试" → 用户漏打下班卡。
                            # 单账户模式下按保守默认间隔兜底调度一次重试，使文案与行为一致；
                            # 收集（多账户）模式无可回传的剩余时间字符串，无法纳入统一调度，
                            # 故明确告知请人工补卡，不再给出虚假的自动重试承诺。
                            error_msg = "未满足下班条件，无法获取剩余时间"
                            if not collect_remaining_time:
                                logging.warning(
                                    f"OCR 未取到剩余时间，按保守默认 {self._PUNCH_OUT_FALLBACK_RETRY_MINUTES} 分钟兜底调度下班重试"
                                )
                                retry_time = await self.schedule_retry_punch_out(
                                    self._PUNCH_OUT_FALLBACK_RETRY_MINUTES, clear_existing=False
                                )
                                if retry_time:
                                    error_msg += f"\n已按保守默认设置在 {retry_time} 自动重试下班打卡"
                            else:
                                error_msg += "\n⚠️ 无法自动重试，请手动补卡"
                        await self.send_notification("打卡流程", error_msg)

                        # 保存并发送当前的浏览器窗口截图
                        screenshot_path = 'punch_out_unable.png'
                        cv2.imwrite(screenshot_path, screen)

                        # 保存失败截图到用户目录
                        self.save_user_screenshot(screen, username, punch_type, success=False)

                        try:
                            # 发送Telegram消息
                            with open(screenshot_path, 'rb') as photo:
                                await self.bot.app.bot.send_photo(
                                    chat_id=self.bot.chat_id,
                                    photo=photo,
                                    caption=f"下班打卡失败 - {error_msg}"
                                )

                            # 发送电子邮件通知
                            # 获取用户姓氏称谓
                            surname = self.get_surname_honorific(username)
                            email_subject = f"{punch_type}打卡失败通知 - {surname} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            # [M49 修复] 去掉无条件的"系统会在适当时间自动重试"承诺——OCR 拿不到剩余时间且
                            # 处于收集（多账户）模式时根本不会调度重试，原文案会误导用户漏打下班卡。
                            # error_msg 已携带真实结果（"已设置在 X 自动重试" 或 "请手动补卡"），直接以其为准。
                            email_body = f"{surname}您好，\n\n您的{punch_type}打卡尝试失败。\n\n原因：{error_msg}\n\n此邮件由自动打卡系统发送，请勿回复。"

                            # 复制截图用于邮件发送
                            email_screenshot_path = f'logs/punch_out_fail_email.png'
                            with open(screenshot_path, 'rb') as f_in:
                                img_data = f_in.read()
                                with open(email_screenshot_path, 'wb') as f_out:
                                    f_out.write(img_data)

                            # 发送邮件
                            await self.send_email_with_attachment(email_subject, email_body, email_screenshot_path, f"{punch_type}(失败)")

                            # 删除临时文件（邮件截图由后台发送线程清理，主流程仅删 Telegram 临时截图）
                            os.remove(screenshot_path)

                        except Exception as e:
                            error_type = type(e).__name__
                            error_msg_detail = str(e)

                            # 检查是否是HTTPXRequest初始化错误
                            if "HTTPXRequest" in error_msg_detail and "not initialized" in error_msg_detail:
                                self.bot._is_initialized = False  # 标记需要重新初始化
                                await self.send_notification("打卡流程", f"通知发送失败 (HTTPXRequest错误): {error_msg_detail}")
                            else:
                                await self.send_notification("打卡流程", f"通知发送失败: {error_msg_detail}")
                        return (False, remaining_time_info)
                    else:
                        # 【关键修复】采用保守策略：仅在明确验证可以下班时才认为成功
                        # 如果unable_escape置信度较低，可能是匹配失败，需要进一步验证

                        # 保守策略判断：如果置信度太低，认为状态不确定
                        if unable_escape_confidence > 0.3:  # 存在一定的unable_escape特征
                            error_msg = f"下班状态不确定（unable_escape置信度: {unable_escape_confidence:.3f}），通过页面记录进一步验证"
                            await self.send_notification("打卡流程", error_msg)
                            logging.warning(f"下班打卡状态不确定，置信度: {unable_escape_confidence:.3f}，检查页面记录")
                            
                            # 尝试从页面获取今日打卡记录来验证下班状态
                            await self.send_notification("打卡流程", "检查页面上的今日下班打卡记录...")
                            try:
                                # 复用现有的get_punch_records_from_page方法
                                await self.get_punch_records_from_page(username=username)
                                
                                # 检查今日是否已有下班记录
                                today_record = self.punch_record_manager.get_today_record()
                                has_punch_out_today = bool(today_record and today_record.get('punch_out_time'))
                                
                                if has_punch_out_today:
                                    # 今日已有下班记录，说明已经完成下班打卡
                                    await self.send_notification("打卡流程", f"页面显示今日已完成下班打卡: {today_record.get('punch_out_time')}")
                                    logging.info("通过页面记录确认今日已下班打卡")
                                    
                                    # 更新内存中的记录
                                    self._set_user_punch_time(username, 'punch_out_time', current_time)
                                    punch_success = True
                                else:
                                    # 未找到下班记录，确认无法下班
                                    error_msg = f"页面未显示今日下班记录，确认未满足下班条件（置信度: {unable_escape_confidence:.3f}）"
                                    await self.send_notification("打卡流程", error_msg)
                                    logging.warning("通过页面记录确认未满足下班条件")
                                    
                                    # 发送截图 - 状态不确定的情况
                                    await self._send_punch_failure_screenshot(screen, username, punch_type, error_msg)
                                    
                                    return (False, f"状态不确定，置信度{unable_escape_confidence:.3f}，页面无下班记录")
                                    
                            except Exception as e:
                                logging.error(f"检查页面打卡记录时出错: {e}")
                                error_msg = f"页面记录检查失败: {str(e)}，采用保守策略（置信度: {unable_escape_confidence:.3f}）"
                                await self.send_notification("打卡流程", error_msg)
                                
                                # 发送截图 - 记录检查失败的情况
                                await self._send_punch_failure_screenshot(screen, username, punch_type, error_msg)
                                
                                return (False, f"状态不确定，置信度{unable_escape_confidence:.3f}，记录检查失败")
                        else:
                            # 置信度很低，认为确实没有unable_escape，可以下班
                            await self.send_notification("打卡流程", f"确认可以下班（置信度: {unable_escape_confidence:.3f}）")
                            logging.info(f"确认可以下班，unable_escape置信度很低: {unable_escape_confidence:.3f}")

                            # 进行下班成功的处理
                            if self._is_early_leave(current_time):
                                await self.send_notification(
                                    "打卡异常",
                                    f"⚠️ 检测到早退打卡！打卡时间：{current_time.strftime('%H:%M')}"
                                )
                            self._set_user_punch_time(username, 'punch_out_time', current_time)
                            # 保存打卡记录
                            self.punch_record_manager.update_record(
                                current_time.strftime('%Y-%m-%d'),
                                "下班",
                                current_time.strftime('%H:%M:%S')
                            )
                            punch_success = True

                if punch_success:
                    # 识别并更新打卡记录
                    await self.get_punch_records_from_page(username=username)

                    # 重置相应的提醒状态（按用户分桶）
                    if punch_type == "上班":
                        self._set_user_notification_flag(username, 'punch_in_reminder', False)
                        logging.info(f"用户 {username} 上班打卡成功，重置该用户上班打卡提醒状态")
                    else:
                        self._set_user_notification_flag(username, 'punch_out_reminder', False)
                        logging.info(f"用户 {username} 下班打卡成功，重置该用户下班打卡提醒状态")

                    # 打卡完成后发送状态信息
                    await self.send_daily_status()

                    # 保存并发送当前的浏览器窗口截图
                    # 重新获取一次最新的截图，确保数据有效
                    # 打卡成功后获取最终截图
                    final_screen = self.take_screenshot()
                    screenshot_data = final_screen if final_screen is not None else screen

                    if screenshot_data is not None:
                        # 生成logs文件夹中的结果图片
                        screenshot_path = f'logs/punch_{"in" if punch_type == "上班" else "out"}_result.png'
                        cv2.imwrite(screenshot_path, screenshot_data)

                        # 保存成功截图到用户目录
                        self.save_user_screenshot(screenshot_data, username, punch_type, success=True)
                    else:
                        logging.error("截图数据为空，无法保存截图")

                    success_msg = f"{punch_type}打卡成功 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    await self.send_notification("打卡流程", success_msg)

                    # 发送截图，增加重试机制
                    max_retries = 3
                    retry_delay = 5
                    for retry in range(max_retries):
                        try:
                            if os.path.exists(screenshot_path):
                                # 确保bot应用已初始化
                                await self.bot._ensure_app_initialized()

                                if not self.bot.app:
                                    await self.send_notification("打卡流程", "无法发送截图：Telegram Bot未正确初始化")
                                    break

                                with open(screenshot_path, 'rb') as photo:
                                    await self.bot.app.bot.send_photo(
                                        chat_id=self.bot.chat_id,
                                        photo=photo,
                                        caption=f"{punch_type}打卡结果截图"
                                    )

                                # 获取用户姓氏称谓
                                surname = self.get_surname_honorific(username)

                                # 发送电子邮件
                                current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                subject = f"{punch_type}打卡成功 - {surname} - {current_time}"
                                body = f"{surname}您好，\n\n您的{punch_type}打卡已于 {current_time} 成功完成。\n\n详情请查看附件截图。\n\n此邮件由自动打卡系统发送，请勿回复。"

                                # 复制一份截图用于邮件发送
                                # [M48 修复] 邮件截图交后台线程读取后 cleanup 删除，共享固定名在并发下会被
                                # 另一用户覆盖/提前删除。加用户名 + 微秒时间戳生成唯一路径（与 Selenium 路径一致）。
                                safe_username = self._safe_filename_token(username)
                                ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                                email_screenshot_path = f'logs/punch_{"in" if punch_type == "上班" else "out"}_email_{safe_username}_{ts}.png'
                                with open(screenshot_path, 'rb') as f_in:
                                    img_data = f_in.read()
                                    with open(email_screenshot_path, 'wb') as f_out:
                                        f_out.write(img_data)

                                # 发送邮件
                                await self.send_email_with_attachment(subject, body, email_screenshot_path, punch_type)

                                os.remove(screenshot_path)  # 删除Telegram发送的临时截图（邮件截图由后台发送线程清理）
                                break
                            else:
                                await self.send_notification("打卡流程", f"截图文件不存在: {screenshot_path}")
                                break
                        except Exception as e:
                            error_type = type(e).__name__
                            error_msg = str(e)

                            # 检查是否是HTTPXRequest初始化错误
                            if "HTTPXRequest" in error_msg and "not initialized" in error_msg:
                                self.bot._is_initialized = False  # 标记需要重新初始化
                                error_msg = f"发送截图时发生HTTPXRequest错误，{retry + 1}/{max_retries} 次重试: {error_msg}"

                                # 强制清理并重新初始化bot
                                if retry < max_retries - 1:
                                    await self._force_reinitialize_bot()

                            elif "NetworkError" in error_type or "TimedOut" in error_type:
                                error_msg = f"发送截图时发生网络错误，{retry + 1}/{max_retries} 次重试: {error_msg}"
                            else:
                                error_msg = f"发送截图时发生其他错误，{retry + 1}/{max_retries} 次重试: {error_msg}"

                            if retry < max_retries - 1:
                                await self.send_notification("打卡流程", error_msg)
                                # 对于HTTPXRequest错误，使用渐进式延迟
                                if "HTTPXRequest" in error_msg:
                                    # 渐进式延迟：第1次1秒，第2次5秒，第3次15秒
                                    delay = [1, 5, 15][retry]
                                else:
                                    delay = retry_delay * (retry + 1)
                                await asyncio.sleep(delay)
                            else:
                                await self.send_notification("打卡流程", f"发送截图失败，网络错误: {error_msg}")
                                break

                    # 关闭浏览器窗口
                    await self.send_notification("打卡流程", "正在关闭浏览器窗口...")
                    if self.bot.close_browser():
                        await self.send_notification("打卡流程", "浏览器窗口已关闭")
                    else:
                        await self.send_notification("打卡流程", "关闭浏览器窗口失败")

                    return (True, None)
                else:
                    error_msg = "未找到打卡按钮"
                    await self.send_notification("打卡流程", error_msg)
                    # 发送失败截图
                    if screen is not None:
                        screenshot_path = 'punch_error.png'
                        cv2.imwrite(screenshot_path, screen)

                        # 保存失败截图到用户目录
                        self.save_user_screenshot(screen, username, punch_type, success=False)

                        try:
                            with open(screenshot_path, 'rb') as photo:
                                await self.bot.app.bot.send_photo(
                                    chat_id=self.bot.chat_id,
                                    photo=photo,
                                    caption=f"{punch_type}打卡失败 - {error_msg}"
                                )
                            os.remove(screenshot_path)
                        except Exception as e:
                            await self.send_notification("打卡流程", f"截图发送失败: {str(e)}")

                    # 关闭浏览器窗口
                    await self.send_notification("打卡流程", "正在关闭浏览器窗口...")
                    if self.bot.close_browser():
                        await self.send_notification("打卡流程", "浏览器窗口已关闭")
                    else:
                        await self.send_notification("打卡流程", "关闭浏览器窗口失败")

                    return (False, None)
            else:
                error_msg = "登录失败，无法进行打卡"
                await self.send_notification("打卡流程", error_msg)
                # 发送失败截图
                if screen is not None:
                    screenshot_path = 'punch_error.png'
                    cv2.imwrite(screenshot_path, screen)

                    # 保存失败截图到用户目录
                    self.save_user_screenshot(screen, username, punch_type, success=False)
                    try:
                        # 发送Telegram截图
                        with open(screenshot_path, 'rb') as photo:
                            await self.bot.app.bot.send_photo(
                                chat_id=self.bot.chat_id,
                                photo=photo,
                                caption=f"{punch_type}打卡失败 - {error_msg}"
                            )

                        # 发送邮件通知
                        surname = self.get_surname_honorific(username)
                        email_subject = f"{punch_type}打卡失败通知 - {surname} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        email_body = f"{surname}您好，\n\n您的{punch_type}打卡尝试失败。\n\n原因：{error_msg}\n\n请管理员检查系统状态。\n\n此邮件由自动打卡系统发送，请勿回复。"

                        # 复制截图用于邮件发送
                        email_screenshot_path = f'logs/punch_error_email.png'
                        with open(screenshot_path, 'rb') as f_in:
                            img_data = f_in.read()
                            with open(email_screenshot_path, 'wb') as f_out:
                                f_out.write(img_data)

                        # 发送邮件
                        await self.send_email_with_attachment(email_subject, email_body, email_screenshot_path, f"{punch_type}(登录失败)")

                        # 删除临时文件（邮件截图由后台发送线程清理，主流程仅删 Telegram 临时截图）
                        os.remove(screenshot_path)
                    except Exception as e:
                        await self.send_notification("打卡流程", f"通知发送失败: {str(e)}")

                # 关闭浏览器窗口
                await self.send_notification("打卡流程", "正在关闭浏览器窗口...")
                if self.bot.close_browser():
                    await self.send_notification("打卡流程", "浏览器窗口已关闭")
                else:
                    await self.send_notification("打卡流程", "关闭浏览器窗口失败")

                return (False, None)
        except Exception as e:
            error_msg = f"{punch_type}打卡流程发生错误: {str(e)}"
            await self.send_notification("打卡流程", error_msg)
            # 发送失败截图
            if screen is not None:
                screenshot_path = 'punch_error.png'
                cv2.imwrite(screenshot_path, screen)

                # 保存失败截图到用户目录
                self.save_user_screenshot(screen, username, punch_type, success=False)
                try:
                    # 发送Telegram消息
                    with open(screenshot_path, 'rb') as photo:
                        await self.bot.app.bot.send_photo(
                            chat_id=self.bot.chat_id,
                            photo=photo,
                            caption=f"{punch_type}打卡失败 - {error_msg}"
                        )

                    # 发送邮件通知
                    surname = self.get_surname_honorific(username)
                    email_subject = f"{punch_type}打卡失败通知 - {surname} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    email_body = f"{surname}您好，\n\n您的{punch_type}打卡过程中发生系统错误。\n\n错误信息：{error_msg}\n\n请管理员检查系统日志。\n\n此邮件由自动打卡系统发送，请勿回复。"

                    # 复制截图用于邮件发送
                    email_screenshot_path = f'logs/punch_error_system_email.png'
                    with open(screenshot_path, 'rb') as f_in:
                        img_data = f_in.read()
                        with open(email_screenshot_path, 'wb') as f_out:
                            f_out.write(img_data)

                    # 发送邮件
                    await self.send_email_with_attachment(email_subject, email_body, email_screenshot_path, f"{punch_type}(系统错误)")

                    # 删除临时文件（邮件截图由后台发送线程清理，主流程仅删 Telegram 临时截图）
                    os.remove(screenshot_path)
                except Exception as e:
                    await self.send_notification("打卡流程", f"通知发送失败: {str(e)}")

            await self.handle_error(e, f"{punch_type}打卡流程")

            # 关闭浏览器窗口
            await self.send_notification("打卡流程", "正在关闭浏览器窗口...")
            if self.bot.close_browser():
                await self.send_notification("打卡流程", "浏览器窗口已关闭")
            else:
                await self.send_notification("打卡流程", "关闭浏览器窗口失败")

            return (False, None)

    async def _do_selenium_punch(self, punch_type="上班", username=None, password=None, collect_remaining_time=False, cancel_event=None):
        """使用Selenium模式的打卡方法（移植传统模式全部功能）

        Args:
            cancel_event: [M11 修复] 本次操作专属的 asyncio.Event（由 start_punch_operation 建立、
                经 punch_*_internal / _do_selenium_punch_for_user 透传）。取消判断带上它后，
                即使 web 强停后 self.operation_cancel_event 被新操作替换，本（旧）任务仍能凭
                自己捕获的 cancel_event 感知取消并退出，不会"复活"误打卡。

        Returns:
            Tuple[bool, str|None]: (是否成功, 剩余时间字符串"X小时Y分钟"或None)
                与 _do_punch 协议一致；第二项仅在下班 unable_escape 场景下非 None。
        """
        from modules.selenium_login import SeleniumLoginController

        flow_type = "punch_in" if punch_type == "上班" else "punch_out"
        flow_name = punch_type
        # 兜底来源用 self.users 首元素（与 3478/3550 等处一致），而非从未赋值的
        # self.login_username/self.login_password（会抛 AttributeError）。用 .get 防缺键。
        effective_username = username or (self.users[0].get('username') if self.users else None)
        effective_password = password or (self.users[0].get('password') if self.users else None)

        def _decode_screenshot_bytes(b):
            """selenium 截图 bytes → numpy 数组，供 cv2.imwrite 使用"""
            if not b:
                return None
            try:
                arr = np.frombuffer(b, np.uint8)
                return cv2.imdecode(arr, cv2.IMREAD_COLOR)
            except Exception as decode_err:
                logging.warning(f"截图bytes解码失败: {decode_err}")
                return None

        def _safe_message(content):
            """防止 Telegram 4096 字符上限"""
            if len(content) > 3800:
                return content[:200] + "\n...(已截断)...\n" + content[-3500:]
            return content

        async def _send_tg_photo_with_retry(photo_bytes, caption, max_retries=3):
            """发送 Telegram 截图：3 次重试 + bot 初始化检查 + HTTPXRequest 自动恢复 + 渐进式延迟。
            与传统模式 _do_punch 1709-1785 行的容错策略对齐。
            """
            for retry in range(max_retries):
                try:
                    await self.bot._ensure_app_initialized()
                    if not self.bot.app:
                        await self.send_notification(
                            "打卡流程", "无法发送截图：Telegram Bot未正确初始化"
                        )
                        return False
                    await self.bot.app.bot.send_photo(
                        chat_id=self.bot.chat_id,
                        photo=photo_bytes,
                        caption=caption
                    )
                    return True
                except Exception as e:
                    error_type = type(e).__name__
                    error_msg_detail = str(e)

                    if "HTTPXRequest" in error_msg_detail and "not initialized" in error_msg_detail:
                        self.bot._is_initialized = False
                        kind = "HTTPXRequest"
                        if retry < max_retries - 1:
                            await self._force_reinitialize_bot()
                    elif "NetworkError" in error_type or "TimedOut" in error_type:
                        kind = "网络"
                    else:
                        kind = "其他"

                    if retry < max_retries - 1:
                        await self.send_notification(
                            "打卡流程",
                            f"发送截图时发生{kind}错误 ({retry+1}/{max_retries})，准备重试: {error_msg_detail}"
                        )
                        # 渐进式延迟：HTTPXRequest 走 [1,5,15]，其他走 [5,10,15]
                        if kind == "HTTPXRequest":
                            delay = [1, 5, 15][retry]
                        else:
                            delay = 5 * (retry + 1)
                        await asyncio.sleep(delay)
                    else:
                        await self.send_notification(
                            "打卡流程",
                            f"发送截图失败 ({kind}): {error_msg_detail}"
                        )
                        return False
            return False

        message_content = f"🔧 Selenium完整{flow_name}打卡流程开始 - 用户: {effective_username}\n"
        status_message = None
        selenium_controller = None
        screenshot_bytes = None
        # 逐步进度编辑节流：同一条 status_message 在 _STEP_EDIT_MIN_INTERVAL 秒内最多编辑一次，
        # 防止 Selenium 流程数秒内数十次 edit_text 触发 Telegram Flood control。被跳过的步骤内容
        # 已累积在 message_content 里，流程结束时的无条件 edit（2493/2555）会带出全文，不丢信息。
        last_step_edit_ts = 0.0
        _STEP_EDIT_MIN_INTERVAL = 2.0

        # 取消事件读取助手：统一判断（含 Flask 线程强停的 _cancel_flag + 本次操作专属 cancel_event）
        # [M11 修复] 带上本次捕获的 cancel_event：web 强停替换 self.operation_cancel_event 后，
        # 旧任务的 4 个检查点仍能凭自己的 cancel_event 感知取消，避免旧任务复活并真实打卡。
        def _cancel_triggered():
            return self._is_cancelled(cancel_event)

        try:
            # 取消检查点 1/4：进入 try 块即检查，driver 未启动可零成本短路
            if _cancel_triggered():
                logging.info(f"_do_selenium_punch ({effective_username}/{punch_type}) 入口即被取消")
                return (False, None)

            # 发送初始状态消息
            try:
                status_message = await self.bot.app.bot.send_message(
                    chat_id=self.bot.chat_id,
                    text=message_content
                )
            except Exception:
                await self.send_notification("Selenium打卡", f"开始{flow_name}流程...")

            async def enhanced_notification_callback(context: str, msg: str):
                nonlocal message_content, last_step_edit_ts
                message_content += f"[{context}] {msg}\n"
                # 把"带用户名"的逐步进度独立补推到 GUI（WS punch:progress）。
                # 原因：默认逐步通知只 edit Telegram 的 status_message、不进 WS，且不带用户名，
                # 导致前端按用户的步骤卡片无法还原真实进度（只能靠假定时器流转）。这里按真实事件
                # 推送，前端据此推进步骤、后端卡住即停。与下面的 status_message 编辑互不影响。
                if self._event_bus is not None:
                    try:
                        await self._event_bus.publish('punch:progress', {
                            'user': effective_username,
                            'title': context,
                            'content': msg,
                        })
                    except Exception:
                        logging.exception("event_bus publish failed for punch:progress (per-user)")
                try:
                    if status_message:
                        # 节流：距上次编辑不足最小间隔则跳过本次 edit（内容已进 message_content，
                        # 由流程结束时的无条件 edit 收尾带出），避免高频编辑触发 Flood control。
                        now_ts = time.monotonic()
                        if now_ts - last_step_edit_ts >= _STEP_EDIT_MIN_INTERVAL:
                            await status_message.edit_text(_safe_message(message_content))
                            last_step_edit_ts = now_ts
                    else:
                        await self.send_notification(context, msg)
                except Exception:
                    pass

            # 创建 SeleniumLoginController（传入 username 让 SeleniumRecordManager 隔离）
            message_content += "📋 正在创建Selenium控制器...\n"
            try:
                if status_message:
                    await status_message.edit_text(_safe_message(message_content))
            except Exception:
                pass

            # 取消检查点 2/4：创建 controller 前，driver 仍未启动
            if _cancel_triggered():
                logging.info(f"_do_selenium_punch ({effective_username}/{punch_type}) 创建controller前被取消")
                return (False, None)

            selenium_controller = SeleniumLoginController(
                login_url=self.login_url,
                headless=self.selenium_headless,
                notification_callback=enhanced_notification_callback,
                username=effective_username or "default"
            )
            # 立即注册到活跃集合，便于 atexit/signal/cancel 路径统一兜底关闭
            self._register_controller(selenium_controller)

            # 执行完整打卡流程
            message_content += f"🚀 开始执行完整{flow_name}打卡流程...\n"
            try:
                if status_message:
                    await status_message.edit_text(_safe_message(message_content))
            except Exception:
                pass

            # 取消检查点 3/4：driver 已启但还未触发登录+打卡，可避免一次完整登录浪费
            if _cancel_triggered():
                logging.info(f"_do_selenium_punch ({effective_username}/{punch_type}) 调用 complete_*_flow 前被取消")
                return (False, None)

            if flow_type == "punch_in":
                success, message_result, flow_data = await selenium_controller.complete_punch_in_flow(
                    username=effective_username,
                    password=effective_password
                )
            else:
                success, message_result, flow_data = await selenium_controller.complete_punch_out_flow(
                    username=effective_username,
                    password=effective_password
                )

            # 取消检查点 4/4：拿到 success/message_result 但还未写记录/发邮件
            # 此时若打卡按钮已点过，记录已落到 SeleniumRecordManager（complete_*_flow 内部），
            # 跳过外层日报/截图归档/Telegram 推送是相对干净的退出
            if _cancel_triggered():
                logging.info(f"_do_selenium_punch ({effective_username}/{punch_type}) complete_*_flow 返回后被取消")
                return (False, None)

            # 获取最终截图（bytes）
            try:
                screenshot_bytes = selenium_controller.take_screenshot()
            except Exception as e:
                logging.warning(f"获取最终截图失败: {e}")
                screenshot_bytes = None

            punch_result = (flow_data or {}).get('punch_result', {})
            was_punched = bool(punch_result.get('punched'))
            was_already_punched = bool(punch_result.get('already_punched'))
            time_calculation = (flow_data or {}).get('time_calculation') or {}
            confirmation_needed = bool(time_calculation.get('confirmation_needed'))
            remaining_time_str = time_calculation.get('remaining_time_str')
            remaining_minutes = time_calculation.get('remaining_minutes')

            # ===== 成功分支（含 punched 和 already_punched）=====
            if success:
                message_content += f"✅ 完整{flow_name}流程成功: {message_result}\n"

                if was_punched:
                    message_content += f"✅ {flow_name}打卡已执行\n"
                elif was_already_punched:
                    message_content += f"ℹ️ 之前已打过{flow_name}卡\n"

                if flow_type == "punch_out":
                    message_content = await self._display_punch_out_time_info(
                        message_content, flow_data or {}
                    )

                attendance_status = (flow_data or {}).get('attendance_status', {})
                if attendance_status.get('today'):
                    message_content += f"📅 今日状态: {attendance_status['today']}\n"

                # 仅 was_punched=True 才走完整业务流程（与传统模式对齐）
                if was_punched:
                    real_punch_time = datetime.now()
                    date_str = real_punch_time.strftime('%Y-%m-%d')
                    time_str = real_punch_time.strftime('%H:%M:%S')

                    # 迟到/早退检测
                    if punch_type == "上班" and self._is_late_punch_in(real_punch_time):
                        await self.send_notification(
                            "打卡异常",
                            f"⚠️ 检测到迟到打卡！打卡时间：{real_punch_time.strftime('%H:%M')}"
                        )
                    elif punch_type == "下班" and self._is_early_leave(real_punch_time):
                        await self.send_notification(
                            "打卡异常",
                            f"⚠️ 检测到早退打卡！打卡时间：{real_punch_time.strftime('%H:%M')}"
                        )

                    # 内存记录同步（按用户隔离，并行打卡场景下不再相互覆盖）
                    if punch_type == "上班":
                        self._set_user_punch_time(effective_username, 'punch_in_time', real_punch_time)
                    else:
                        self._set_user_punch_time(effective_username, 'punch_out_time', real_punch_time)

                    # 全局 punch_record_manager 写入（与 SeleniumRecordManager 双写）
                    try:
                        self.punch_record_manager.update_record(date_str, punch_type, time_str)
                    except Exception as record_err:
                        logging.error(f"全局punch_record_manager写入失败: {record_err}")

                    # 重置对应提醒状态（按用户分桶）
                    if punch_type == "上班":
                        self._set_user_notification_flag(effective_username, 'punch_in_reminder', False)
                    else:
                        self._set_user_notification_flag(effective_username, 'punch_out_reminder', False)

                    # 用户截图归档（save_user_screenshot 已支持 bytes）
                    if screenshot_bytes:
                        try:
                            self.save_user_screenshot(
                                screenshot_bytes,
                                effective_username,
                                punch_type,
                                success=True
                            )
                        except Exception as save_err:
                            logging.error(f"save_user_screenshot 失败: {save_err}")

                    # 发送成功邮件（含截图附件） —— 与传统模式 1745 行对齐
                    if screenshot_bytes:
                        try:
                            surname = self.get_surname_honorific(effective_username)
                            current_time_str = real_punch_time.strftime('%Y-%m-%d %H:%M:%S')
                            subject = f"{punch_type}打卡成功 - {surname} - {current_time_str}"
                            body = (
                                f"{surname}您好，\n\n"
                                f"您的{punch_type}打卡已于 {current_time_str} 成功完成。\n\n"
                                f"详情请查看附件截图。\n\n"
                                f"此邮件由自动打卡系统发送，请勿回复。"
                            )

                            os.makedirs('logs', exist_ok=True)
                            # [M48 修复] 并行多账户成功路径同样不能共用 logs/punch_{in,out}_email.png：
                            # 后台邮件线程读取后 cleanup 删除共享路径，会让另一用户的邮件读不到附件。
                            # 加用户名 + 微秒时间戳生成唯一路径。
                            safe_username = self._safe_filename_token(effective_username)
                            ts = real_punch_time.strftime('%Y%m%d_%H%M%S_%f')
                            email_screenshot_path = f'logs/punch_{"in" if punch_type == "上班" else "out"}_email_{safe_username}_{ts}.png'
                            with open(email_screenshot_path, 'wb') as f:
                                f.write(screenshot_bytes)

                            # 邮件截图由后台发送线程读取后清理（cleanup_path），主流程不再提前删除，
                            # 避免与后台读取竞争导致 WinError 32（即日志中"发送成功邮件失败"的根因）。
                            await self.send_email_with_attachment(
                                subject, body, email_screenshot_path, punch_type
                            )
                        except Exception as email_err:
                            logging.error(f"发送{punch_type}成功邮件失败: {email_err}")

                    # 发送日报
                    try:
                        await self.send_daily_status()
                    except Exception as daily_err:
                        logging.error(f"send_daily_status 失败: {daily_err}")

                # 发 Telegram 截图（成功路径，含 already_punched）—— 走 3 次重试容错
                if screenshot_bytes:
                    sent_ok = await _send_tg_photo_with_retry(
                        screenshot_bytes,
                        f"{punch_type}打卡结果截图"
                    )
                    if not sent_ok:
                        message_content += "⚠️ 截图发送最终失败（已重试3次）\n"

                message_content += "✅ 完整流程完成！"
                try:
                    if status_message:
                        await status_message.edit_text(_safe_message(message_content))
                except Exception:
                    pass

                return (True, None)

            # ===== 失败分支 =====
            message_content += f"❌ 完整{flow_name}流程失败: {message_result}\n"

            # 下班 unable_escape 子分支（工作时间不足）
            if flow_type == "punch_out" and confirmation_needed and remaining_minutes is not None:
                error_msg = f"未满足下班条件，还需工作: {remaining_time_str}"

                # 单账户场景：直接调度定时重试
                if not collect_remaining_time:
                    try:
                        retry_time = await self.schedule_retry_punch_out(
                            int(remaining_minutes),
                            clear_existing=False
                        )
                        if retry_time:
                            error_msg += f"\n已设置在 {retry_time} 自动重试下班打卡"
                    except Exception as schedule_err:
                        logging.error(f"调度下班重试失败: {schedule_err}")
                        error_msg += f"\n⚠️ 设置定时重试失败: {str(schedule_err)}"
                # 多账户场景：把 remaining_time_str 通过返回值传给 punch_out_internal 统一调度

                await self.send_notification("打卡流程", error_msg)

                # 失败通知三连发（Telegram + 邮件 + 用户归档）
                screen_numpy = _decode_screenshot_bytes(screenshot_bytes)
                if screen_numpy is not None:
                    await self._send_punch_failure_screenshot(
                        screen_numpy, effective_username, punch_type, error_msg
                    )
                else:
                    logging.warning("截图解码失败，跳过 _send_punch_failure_screenshot")

                return (False, remaining_time_str)

            # [M49 修复] 下班 confirmation_needed=True 但拿不到 remaining_minutes（计算/解析失败）：
            # 原先直接落到下方"其他失败"分支 → 不调度任何重试，但 _send_punch_failure_screenshot 的邮件
            # 仍写"系统会在适当时间自动重试" → 用户漏打下班卡。这里与传统模式对齐：单账户按保守默认间隔
            # 兜底调度一次重试；收集（多账户）模式无可回传的剩余时间字符串，明确告知请人工补卡。
            if flow_type == "punch_out" and confirmation_needed and remaining_minutes is None:
                error_msg = "未满足下班条件，无法获取剩余时间"
                if not collect_remaining_time:
                    try:
                        logging.warning(
                            f"Selenium 下班未取到剩余时间，按保守默认 {self._PUNCH_OUT_FALLBACK_RETRY_MINUTES} 分钟兜底调度重试"
                        )
                        retry_time = await self.schedule_retry_punch_out(
                            self._PUNCH_OUT_FALLBACK_RETRY_MINUTES, clear_existing=False
                        )
                        if retry_time:
                            error_msg += f"\n已按保守默认设置在 {retry_time} 自动重试下班打卡"
                    except Exception as schedule_err:
                        logging.error(f"调度下班兜底重试失败: {schedule_err}")
                        error_msg += f"\n⚠️ 设置定时重试失败: {str(schedule_err)}"
                else:
                    error_msg += "\n⚠️ 无法自动重试，请手动补卡"

                await self.send_notification("打卡流程", error_msg)

                screen_numpy = _decode_screenshot_bytes(screenshot_bytes)
                if screen_numpy is not None:
                    await self._send_punch_failure_screenshot(
                        screen_numpy, effective_username, punch_type, error_msg
                    )
                else:
                    logging.warning("截图解码失败，跳过 _send_punch_failure_screenshot")

                # remaining_time_str 此时为 None，返回 None 不参与多账户统一调度
                return (False, None)

            # 其他失败（登录失败、按钮异常、等）
            error_msg = message_result or f"{flow_name}流程失败"
            screen_numpy = _decode_screenshot_bytes(screenshot_bytes)
            if screen_numpy is not None:
                await self._send_punch_failure_screenshot(
                    screen_numpy, effective_username, punch_type, error_msg
                )
            else:
                await self.send_notification(
                    "打卡失败",
                    f"{punch_type}打卡失败 - {error_msg}（无截图）"
                )

            return (False, None)

        except Exception as e:
            error_msg = f"Selenium{flow_name}打卡流程异常: {str(e)}"
            logging.error(error_msg, exc_info=True)
            message_content += f"❌ 发生错误: {str(e)}\n"

            try:
                if status_message:
                    await status_message.edit_text(_safe_message(message_content))
            except Exception:
                pass

            # 异常路径下尝试用最新截图走完整失败通知
            try:
                if selenium_controller is not None:
                    try:
                        exc_screenshot = selenium_controller.take_screenshot()
                    except Exception:
                        exc_screenshot = None
                    screen_numpy = _decode_screenshot_bytes(exc_screenshot)
                    if screen_numpy is not None:
                        await self._send_punch_failure_screenshot(
                            screen_numpy, effective_username, punch_type, error_msg
                        )
            except Exception as cleanup_error:
                logging.error(f"异常路径发送失败截图失败: {cleanup_error}")

            # 走全局错误归集
            try:
                await self.handle_error(e, f"{punch_type}打卡(Selenium)")
            except Exception:
                pass

            return (False, None)

        finally:
            # 资源清理兜底（先 close 再从活跃集合移除）
            if selenium_controller is not None:
                try:
                    selenium_controller.close()
                except Exception as cleanup_error:
                    logging.error(f"关闭 selenium_controller 失败: {cleanup_error}")
                finally:
                    self._unregister_controller(selenium_controller)

    async def _do_selenium_punch_for_user(self, user, punch_type, cancel_event, semaphore, collect_remaining_time=True):
        """Selenium 模式下"单用户打卡"的并行包装协程。

        多账户并行打卡时，每个用户在自己的协程任务里执行；用信号量限制并发，
        用 try/except 把单用户异常隔离，避免一个用户崩溃拖累 asyncio.gather 整批。

        Args:
            user: 用户配置 dict，含 'username' / 'password'
            punch_type: "上班" 或 "下班"
            cancel_event: asyncio.Event，由外层 start_punch_operation 建立
            semaphore: asyncio.Semaphore 限制并发数
            collect_remaining_time: True 时把 unable_escape 的剩余时间回传给外层统一调度
        Returns:
            dict: {'username': str, 'success': bool, 'remaining_time': str|None, 'exception': Exception|None}
        """
        username = user.get('username') if isinstance(user, dict) else None
        password = user.get('password') if isinstance(user, dict) else None
        result = {
            'username': username,
            'success': False,
            'remaining_time': None,
            'exception': None,
        }

        # 把"每用户终态"补推到 GUI（WS punch:progress, done=True）。这是前端给步骤卡片定稿
        # 成功/失败的权威信号——比"今日是否有本地记录"更可靠（already_punched 也算成功，但未必
        # 回写本地记录）。无论正常完成 / 取消 / 异常，都在退出前推一次。
        async def _publish_terminal():
            if self._event_bus is None or not username:
                return
            try:
                await self._event_bus.publish('punch:progress', {
                    'user': username,
                    'title': '打卡结果',
                    'content': '成功' if result['success'] else '失败',
                    'done': True,
                    'success': bool(result['success']),
                })
            except Exception:
                logging.exception("event_bus publish failed for punch:progress (terminal)")

        try:
            # 提前短路：cancel_event 已触发就不再启动 driver
            if cancel_event is not None and self._is_cancelled(cancel_event):
                result['exception'] = asyncio.CancelledError("操作已被取消")
                return result

            try:
                async with semaphore:
                    # 进入信号量前再次确认 cancel 状态，避免排队等待期间被取消
                    if cancel_event is not None and self._is_cancelled(cancel_event):
                        result['exception'] = asyncio.CancelledError("操作已被取消")
                        return result

                    await self.send_notification(
                        "并行打卡",
                        f"[{username}] 开始 {punch_type} 流程"
                    )
                    # [M11 修复] 透传本次操作的 cancel_event，使单用户并行子流程也能感知精确取消
                    success, remaining_time_info = await self._do_selenium_punch(
                        punch_type, username, password, collect_remaining_time, cancel_event=cancel_event
                    )
                    result['success'] = bool(success)
                    result['remaining_time'] = remaining_time_info
            except asyncio.CancelledError as ce:
                result['exception'] = ce
                await self.send_notification("并行打卡", f"[{username}] 任务被取消")
            except Exception as e:
                result['exception'] = e
                logging.error(f"并行打卡用户 {username} 异常: {e}", exc_info=True)
                await self.send_notification("并行打卡", f"[{username}] 任务异常: {str(e)}")

            return result
        finally:
            await _publish_terminal()

    async def _display_punch_out_time_info(self, message_content: str, flow_data: dict) -> str:
        """显示下班打卡的时间信息（基于selenium_login的计算结果）"""
        time_calculation = flow_data.get('time_calculation')
        if time_calculation:
            if time_calculation.get('error'):
                message_content += f"⚠️ 时间计算异常: {time_calculation['error']}\n"
            elif time_calculation.get('confirmation_needed'):
                message_content += "⚠️ 检测到工作时间不足\n"
                message_content += f"⏰ 预计下班时间: {time_calculation['estimated_off_time']}\n"
                message_content += f"📊 已工作: {time_calculation['worked_minutes']}分钟\n"
                message_content += f"📊 还需: {time_calculation['remaining_minutes']}分钟\n"

                # 注意：时间确认逻辑已在selenium_login中处理，这里只显示信息
                message_content += "ℹ️ 时间确认已在打卡流程中处理\n"

        return message_content

    async def start_punch_operation(self, operation_type, username=None):
        """启动打卡操作（公共接口）

        Args:
            operation_type: 操作类型 ('punch_in' 或 'punch_out')
            username: 可选，指定要打卡的用户名。如果为None，则为所有用户打卡
        """
        async with self.operation_lock:
            if self.current_operation is not None:
                return False, f"当前已有{self.current_operation}操作正在进行中，请等待完成或使用/stop命令取消"

            # [M11 修复] current_operation 为 None 不代表上一轮 task 真的退出了：web 强停的
            # _cleanup_operation_state(None) 会立即把 operation_task 置 None 而不等待旧任务收尾。
            # 若此刻旧任务仍卡在 await（TG 发送慢/信号量排队/sleep），直接清 _cancel_flag + 换 cancel_event
            # 会让它的取消信号全部失效而"复活"。故启动新操作前确认上一轮 task 已结束；未结束则拒绝启动，
            # 让上层稍后重试，避免新旧两个打卡流程并行。
            prev_task = getattr(self, '_last_operation_task', None)
            if prev_task is not None and not prev_task.done():
                return False, "上一次打卡操作正在收尾，请稍后重试"

            # 设置操作状态
            self.current_operation = operation_type
            self.operation_start_time = datetime.now()
            self.operation_cancel_event = asyncio.Event()
            self._cancel_flag.clear()  # 关键：清掉上次强停遗留状态，否则新操作会被秒退

            # 启动后台任务
            if operation_type == "punch_in":
                self.operation_task = asyncio.create_task(self.punch_in_internal(self.operation_cancel_event, username))
            elif operation_type == "punch_out":
                self.operation_task = asyncio.create_task(self.punch_out_internal(self.operation_cancel_event, username))
            else:
                self.current_operation = None
                self.operation_start_time = None
                self.operation_cancel_event = None
                return False, "无效的操作类型"

            # [M11 修复] 记录最近一次派出的 task；该引用不会被 _cleanup_operation_state 清空
            self._last_operation_task = self.operation_task

            # 添加任务完成回调
            self.operation_task.add_done_callback(self._operation_completed_callback)

            return True, f"{operation_type}操作已启动"

    def _operation_completed_callback(self, task):
        """操作完成时的回调函数"""
        asyncio.create_task(self._cleanup_operation_state(task))

    async def _cleanup_operation_state(self, task=None):
        """清理操作状态。

        task 非 None 时做归属校验：若它已不是当前 self.operation_task，说明已有新一轮操作
        覆盖（或已被清空），跳过本次清理，避免滞后的旧清理把刚建立的新操作状态误清为 None。
        task=None（如 web force_stop 全局强停）维持无条件清理语义。
        """
        if task is not None and task is not self.operation_task:
            return
        self.current_operation = None
        self.operation_task = None
        self.operation_cancel_event = None
        self.operation_start_time = None

    def _is_cancelled(self, cancel_event=None):
        """统一取消判断：跨线程强停标志 / 传入的 cancel_event / 当前 operation_cancel_event 任一触发即取消。"""
        if getattr(self, '_cancel_flag', None) is not None and self._cancel_flag.is_set():
            return True
        if cancel_event is not None and cancel_event.is_set():
            return True
        ev = getattr(self, 'operation_cancel_event', None)
        return ev is not None and ev.is_set()

    def _interruptible_sleep(self, seconds):
        """可被强停打断的同步 sleep：分片轮询 _cancel_flag（传统/PyAutoGUI 模式的阻塞等待用）。"""
        remaining = max(0.0, float(seconds))
        while remaining > 0:
            if getattr(self, '_cancel_flag', None) is not None and self._cancel_flag.is_set():
                return
            chunk = 0.5 if remaining > 0.5 else remaining
            time.sleep(chunk)
            remaining -= chunk

    def force_stop_operation(self):
        """同步强制停止（可在任意线程调用，含 Flask 请求线程）。

        立即 quit 所有活跃 selenium driver —— driver.quit() 会让主事件循环里阻塞的
        WebDriverWait/命令立刻抛错中断，打破"selenium 同步阻塞循环 → 取消协程排不进来"的死结。
        不 await、不直接操作 asyncio.Event（线程不安全，由调用方用 call_soon_threadsafe 兜底）。
        返回 (had_operation, closed_count)。
        """
        had_op = self.current_operation
        try:
            self._cancel_flag.set()
        except Exception:
            logging.exception("设置 _cancel_flag 失败")
        # 复制活跃集合后在锁外逐个关闭（_unregister_controller 自带加锁，避免重入死锁）
        with self._controllers_lock:
            controllers = list(self._active_controllers)
        closed = 0
        for ctrl in controllers:
            try:
                ctrl.close()
                closed += 1
            except Exception as e:
                logging.error(f"force_stop 关闭 selenium driver 失败: {e}")
            finally:
                self._unregister_controller(ctrl)
        logging.info(f"force_stop_operation: had_op={had_op}, quit {closed}/{len(controllers)} driver(s)")
        return had_op, closed

    async def cancel_current_operation(self):
        """取消当前操作"""
        if self.current_operation is None:
            return False, "当前没有进行中的操作"

        operation_type = self.current_operation
        # 捕获本次要取消的 task 引用，供清理时做归属校验（防止误清后续新操作的状态）
        op_task = self.operation_task

        # 设置取消事件
        if self.operation_cancel_event:
            self.operation_cancel_event.set()

        # 等待任务完成（取消）
        if self.operation_task and not self.operation_task.done():
            try:
                await asyncio.wait_for(self.operation_task, timeout=10)
            except asyncio.TimeoutError:
                # 如果任务没有响应取消，强制取消
                if self.operation_task and not self.operation_task.done():
                    self.operation_task.cancel()
                    try:
                        await self.operation_task
                    except asyncio.CancelledError:
                        pass

        # 确保浏览器被关闭
        await self.cleanup_browser()

        # 清理状态（带归属校验：仅当 operation_task 仍是本次取消的 op_task 时才清）
        await self._cleanup_operation_state(op_task)

        return True, f"{operation_type}操作已取消"

    async def cleanup_browser(self):
        """清理浏览器资源（按当前打卡模式分流）

        - Selenium 模式：遍历活跃 controllers 集合逐个关闭（覆盖多并发 driver 场景）
        - 传统模式：调 bot.close_browser() 用 PyAutoGUI 找关闭按钮
        """
        try:
            if self.use_selenium_login:
                # Selenium 路径：跳过 PyAutoGUI 找关闭按钮的虚假尝试（对 headless 无效）
                with self._controllers_lock:
                    controllers = list(self._active_controllers)
                if controllers:
                    await self.send_notification("系统清理", f"关闭 {len(controllers)} 个活跃 selenium driver...")
                    for ctrl in controllers:
                        try:
                            ctrl.close()
                        except Exception as e:
                            logging.error(f"关闭 selenium driver 失败: {e}")
                        finally:
                            self._unregister_controller(ctrl)
                    await self.send_notification("系统清理", "selenium driver 已全部关闭")
                else:
                    await self.send_notification("系统清理", "无活跃 selenium driver 待关闭")
                return

            # 传统模式（PyAutoGUI）
            await self.send_notification("系统清理", "正在关闭浏览器...")
            browser_closed = self.bot.close_browser()
            if browser_closed:
                await self.send_notification("系统清理", "传统浏览器已关闭")
            else:
                await self.send_notification("系统清理", "传统浏览器关闭失败，可能需要手动关闭")

        except Exception as e:
            logging.error(f"清理浏览器时发生错误: {e}")

    async def punch_in_internal(self, cancel_event, username=None):
        """执行上班打卡（内部方法，支持取消）

        Args:
            cancel_event: 取消事件
            username: 可选，指定要打卡的用户名。如果为None，则为所有用户打卡
        """
        try:
            # 检查取消
            if self._is_cancelled(cancel_event):
                await self.send_notification("操作取消", "上班打卡操作已被取消")
                return "cancelled"

            if not self.users or len(self.users) == 0:
                await self.send_notification("打卡错误", "未配置用户信息，无法执行打卡")
                return False

            # 如果指定了用户名，只为该用户打卡
            if username:
                users_to_process = [user for user in self.users if user.get('username') == username]
                if not users_to_process:
                    await self.send_notification("打卡错误", f"未找到用户 {username} 的配置信息")
                    return False
            else:
                users_to_process = self.users

            # Selenium 模式 + 多用户 → 走并行分支
            if self.use_selenium_login and len(users_to_process) > 1:
                max_concurrent = min(3, len(users_to_process))
                semaphore = asyncio.Semaphore(max_concurrent)
                await self.send_notification(
                    "并行打卡",
                    f"启动 {len(users_to_process)} 个用户并行上班打卡（并发上限 {max_concurrent}）"
                )

                tasks = [
                    self._do_selenium_punch_for_user(u, "上班", cancel_event, semaphore, collect_remaining_time=False)
                    for u in users_to_process
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 归一化（gather 中的裸异常 → 字典形态）
                normalized = []
                for r in results:
                    if isinstance(r, dict):
                        normalized.append(r)
                    elif isinstance(r, BaseException):
                        normalized.append({'username': None, 'success': False, 'remaining_time': None, 'exception': r})

                if self._is_cancelled(cancel_event):
                    await self.send_notification("操作取消", "并行上班打卡过程中被取消")
                    return "cancelled"

                success_count = sum(1 for r in normalized if r.get('success'))
                fail_users = [r.get('username') or '?' for r in normalized if not r.get('success')]
                detail = f"成功: {success_count}/{len(users_to_process)}"
                if fail_users:
                    detail += f"；失败用户: {', '.join(fail_users)}"
                await self.send_notification("打卡完成", f"并行上班打卡完成 - {detail}")
                return success_count > 0

            success_count = 0
            for i, user in enumerate(users_to_process):
                # 检查取消
                if self._is_cancelled(cancel_event):
                    await self.send_notification("操作取消", f"用户 {user.get('username')} 的上班打卡操作已被取消")
                    await self.cleanup_browser()
                    return "cancelled"

                username = user.get('username')
                password = user.get('password')

                # 为每个用户发送单独的开始消息
                await self.send_notification("多用户打卡", f"开始为用户 {username} 执行上班打卡 ({i+1}/{len(users_to_process)})")

                # 执行打卡（[M11 修复] 透传本次操作的 cancel_event）
                result, _ = await self._do_punch("上班", username, password, cancel_event=cancel_event)

                # 检查取消
                if self._is_cancelled(cancel_event):
                    await self.send_notification("操作取消", f"用户 {username} 打卡完成后操作被取消")
                    await self.cleanup_browser()
                    return "cancelled"

                if result:
                    success_count += 1
                    # 为每个用户发送单独的成功消息
                    await self.send_notification("打卡成功", f"用户 {username} 上班打卡成功")
                else:
                    # 为每个用户发送单独的失败消息
                    await self.send_notification("打卡失败", f"用户 {username} 上班打卡失败")

                # 确保浏览器已关闭
                await self.send_notification("打卡流程", f"确认用户 {username} 的浏览器已关闭")
                # 使用 bot 对象的 close_browser 方法
                browser_closed = self.bot.close_browser()
                if not browser_closed:
                    # 如果关闭失败，再尝试一次
                    await self.send_notification("打卡流程", "首次关闭浏览器失败，再次尝试...")
                    time.sleep(2)
                    browser_closed = self.bot.close_browser()
                    if not browser_closed:
                        await self.send_notification("打卡流程", "浏览器关闭失败，可能需要手动关闭")

                # 如果还有下一个用户，等待一段时间再继续
                if i < len(self.users) - 1:
                    await self.send_notification("打卡流程", f"等待5秒后开始下一个用户的打卡...")
                    # 在等待期间也检查取消
                    for _ in range(5):
                        if self._is_cancelled(cancel_event):
                            await self.send_notification("操作取消", "在等待期间操作被取消")
                            await self.cleanup_browser()
                            return "cancelled"
                        await asyncio.sleep(1)

            # 所有用户打卡完成后发送总结消息
            await self.send_notification("打卡完成", f"上班打卡完成，成功: {success_count}/{len(self.users)}")
            return success_count > 0
        except Exception as e:
            await self.cleanup_browser()
            await self.handle_error(e, "上班打卡")
            return False

    async def punch_in(self, username=None):
        """执行上班打卡（兼容性方法）

        Args:
            username: 可选，指定要打卡的用户名。如果为None，则为所有用户打卡
        """
        success, message = await self.start_punch_operation("punch_in", username)
        if success:
            # 等待操作完成
            if self.operation_task:
                return await self.operation_task
        return False

    async def punch_out_internal(self, cancel_event, username=None):
        """执行下班打卡（内部方法，支持取消）

        Args:
            cancel_event: 取消事件
            username: 可选，指定要打卡的用户名。如果为None，则为所有用户打卡
        """
        try:
            # 检查取消
            if self._is_cancelled(cancel_event):
                await self.send_notification("操作取消", "下班打卡操作已被取消")
                return "cancelled"

            if not self.users or len(self.users) == 0:
                await self.send_notification("打卡错误", "未配置用户信息，无法执行打卡")
                return False

            # 如果指定了用户名，只为该用户打卡
            if username:
                users_to_process = [user for user in self.users if user.get('username') == username]
                if not users_to_process:
                    await self.send_notification("打卡错误", f"未找到用户 {username} 的配置信息")
                    return False
            else:
                users_to_process = self.users

            # Selenium 模式 + 多用户 → 走并行分支
            if self.use_selenium_login and len(users_to_process) > 1:
                max_concurrent = min(3, len(users_to_process))
                semaphore = asyncio.Semaphore(max_concurrent)
                await self.send_notification(
                    "并行打卡",
                    f"启动 {len(users_to_process)} 个用户并行下班打卡（并发上限 {max_concurrent}）"
                )

                tasks = [
                    self._do_selenium_punch_for_user(u, "下班", cancel_event, semaphore, collect_remaining_time=True)
                    for u in users_to_process
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # 归一化结果
                normalized = []
                for r in results:
                    if isinstance(r, dict):
                        normalized.append(r)
                    elif isinstance(r, BaseException):
                        normalized.append({'username': None, 'success': False, 'remaining_time': None, 'exception': r})

                if self._is_cancelled(cancel_event):
                    await self.send_notification("操作取消", "并行下班打卡过程中被取消")
                    return "cancelled"

                success_count = sum(1 for r in normalized if r.get('success'))
                # 失败且有剩余时间的用户 → 统一定时重试
                remaining_times = [
                    {'username': r.get('username'), 'remaining_time': r.get('remaining_time')}
                    for r in normalized
                    if not r.get('success') and r.get('remaining_time')
                ]
                await self._schedule_unified_retry(remaining_times)

                fail_users = [r.get('username') or '?' for r in normalized if not r.get('success')]
                detail = f"成功: {success_count}/{len(users_to_process)}"
                if fail_users:
                    detail += f"；失败用户: {', '.join(fail_users)}"
                await self.send_notification("打卡完成", f"并行下班打卡完成 - {detail}")
                return success_count > 0

            success_count = 0
            remaining_times = []  # 用于存储每个用户的剩余工作时间

            for i, user in enumerate(users_to_process):
                # 检查取消
                if self._is_cancelled(cancel_event):
                    await self.send_notification("操作取消", f"用户 {user.get('username')} 的下班打卡操作已被取消")
                    await self.cleanup_browser()
                    return "cancelled"

                username = user.get('username')
                password = user.get('password')

                # 为每个用户发送单独的开始消息
                await self.send_notification("多用户打卡", f"开始为用户 {username} 执行下班打卡 ({i+1}/{len(users_to_process)})")

                # 执行打卡，并捕获剩余工作时间（[M11 修复] 透传本次操作的 cancel_event）
                result, remaining_time_info = await self._do_punch("下班", username, password, collect_remaining_time=True, cancel_event=cancel_event)

                # 检查取消
                if self._is_cancelled(cancel_event):
                    await self.send_notification("操作取消", f"用户 {username} 打卡完成后操作被取消")
                    await self.cleanup_browser()
                    return "cancelled"

                if result:
                    success_count += 1
                    # 为每个用户发送单独的成功消息
                    await self.send_notification("打卡成功", f"用户 {username} 下班打卡成功")
                else:
                    # 为每个用户发送单独的失败消息
                    await self.send_notification("打卡失败", f"用户 {username} 下班打卡失败")

                    # 如果失败是因为未满足下班条件，则记录剩余时间
                    if remaining_time_info:
                        remaining_times.append({
                            'username': username,
                            'remaining_time': remaining_time_info
                        })

                # 确保浏览器已关闭
                await self.send_notification("打卡流程", f"确认用户 {username} 的浏览器已关闭")
                # 使用 bot 对象的 close_browser 方法
                browser_closed = self.bot.close_browser()
                if not browser_closed:
                    # 如果关闭失败，再尝试一次
                    await self.send_notification("打卡流程", "首次关闭浏览器失败，再次尝试...")
                    time.sleep(2)
                    browser_closed = self.bot.close_browser()
                    if not browser_closed:
                        await self.send_notification("打卡流程", "浏览器关闭失败，可能需要手动关闭")

                # 如果还有下一个用户，等待一段时间再继续
                if i < len(users_to_process) - 1:
                    await self.send_notification("打卡流程", f"等待5秒后开始下一个用户的打卡...")
                    # 在等待期间也检查取消
                    for _ in range(5):
                        if self._is_cancelled(cancel_event):
                            await self.send_notification("操作取消", "在等待期间操作被取消")
                            await self.cleanup_browser()
                            return "cancelled"
                        await asyncio.sleep(1)

            # 检查取消
            if self._is_cancelled(cancel_event):
                await self.send_notification("操作取消", "在处理定时任务前操作被取消")
                return "cancelled"

            # 所有用户打卡完成后，处理统一的定时任务（抽出为 _schedule_unified_retry，串行/并行共用）
            await self._schedule_unified_retry(remaining_times)

            # 所有用户打卡完成后发送总结消息
            await self.send_notification("打卡完成", f"下班打卡完成，成功: {success_count}/{len(users_to_process)}")
            return success_count > 0
        except Exception as e:
            await self.cleanup_browser()
            await self.handle_error(e, "下班打卡")
            return False

    async def punch_out(self, username=None):
        """执行下班打卡（兼容性方法）

        Args:
            username: 可选，指定要打卡的用户名。如果为None，则为所有用户打卡
        """
        success, message = await self.start_punch_operation("punch_out", username)
        if success:
            # 等待操作完成
            if self.operation_task:
                return await self.operation_task
        return False


    def cleanup(self):
        """清理资源

        [M14 修复] 原实现先 task_manager.clear_tasks() 全清任务文件，再仅按
        `"punch_out" in str(job.job_func)` 启发式回存 punch_out 类 job——但：
        (1) init_schedule_tasks 恢复的 job qualname 不含 'punch_out'、punch_in 类根本无回存分支，
            回存匹配不到 → 重启后定时上班任务和恢复的下班任务静默蒸发，次日漏卡；
        (2) 任务本就持久化在 scheduled_tasks.json，重启后 init_schedule_tasks 会原样恢复，
            cleanup 这套 clear+回存反而是净损害。
        故整段删除"动任务文件"的逻辑，cleanup 只负责关闭活跃 selenium driver（避免 driver 泄漏成孤儿）。
        """
        try:
            self._sync_cleanup_on_exit()
        except Exception as e:
            logging.error(f"cleanup 关闭活跃 driver 失败: {e}")

    def _is_supervised(self):
        """[M37 修复] 是否运行在外层监管者（watchdog / Electron）之下。

        受管模式下进程退出会被监管者重新拉起，进程内再 os.execl 自重启会与监管者的拉起逻辑
        撞车产生双实例（双 Telegram getUpdates 409 / 重复打卡 / 端口冲突）。
        识别信号：
        - Electron 始终以 `main.py --gui` 启动，故 sys.argv 含 '--gui'；
        - watchdog.py 启动子进程前设置 AAS_SUPERVISED=1（见 watchdog.py）。
        """
        try:
            if '--gui' in sys.argv:
                return True
        except Exception:
            pass
        return os.environ.get('AAS_SUPERVISED') == '1'

    async def restart_program(self):
        """重启程序"""
        try:
            await self.send_notification("系统状态", "开始执行程序重启...")

            # 清理资源（关闭活跃 driver；os.execl 不触发 atexit，故必须在重启前主动关闭，避免孤儿 driver）
            self.cleanup()

            if self._is_supervised():
                # [M37 修复] 受管模式（watchdog/Electron）：用非零退出码让外层监管者拉起新实例，
                # 不在进程内 os.execl 自重启，杜绝双实例。退出前已 cleanup 关闭 driver。
                logging.critical("受管模式下请求重启：以退出码 1 退出，交由监管者（watchdog/Electron）拉起新实例")
                await self.send_notification("系统状态", "受管模式：进程将退出并由监管者自动重启")
                sys.exit(1)
            else:
                # 独立运行（直接 python main.py）：无外层监管者，仍用 os.execl 替换进程映像自重启。
                python_executable = sys.executable
                os.execl(python_executable, python_executable, *sys.argv)

        except SystemExit:
            # sys.exit 抛出的 SystemExit 不应被下方通用 except 吞掉，原样向上传播以真正退出
            raise
        except Exception as e:
            await self.send_notification("系统状态", f"程序重启失败: {str(e)}")

    def _is_late_punch_in(self, punch_time):
        """检查是否迟到"""
        work_start = datetime.strptime(self.work_start_time, "%H:%M").time()
        late_threshold = timedelta(minutes=self.late_threshold)
        punch_datetime = datetime.strptime(punch_time.strftime("%H:%M"), "%H:%M").time()

        # 计算时间差
        start_minutes = work_start.hour * 60 + work_start.minute
        punch_minutes = punch_datetime.hour * 60 + punch_datetime.minute

        return punch_minutes > (start_minutes + self.late_threshold)

    def _is_early_leave(self, punch_time):
        """检查是否早退"""
        work_end = datetime.strptime(self.work_end_time, "%H:%M").time()
        early_threshold = timedelta(minutes=self.early_leave_threshold)
        punch_datetime = datetime.strptime(punch_time.strftime("%H:%M"), "%H:%M").time()

        # 计算时间差
        end_minutes = work_end.hour * 60 + work_end.minute
        punch_minutes = punch_datetime.hour * 60 + punch_datetime.minute

        return punch_minutes < (end_minutes - self.early_leave_threshold)

    def is_work_time(self, current_time=None):
        """判断是否是工作时间"""
        if current_time is None:
            current_time = datetime.now()

        # 首先判断是否是工作日
        if not is_workday(current_time.date()):
            return False

        # 然后判断是否在工作时间范围内
        current_minutes = current_time.hour * 60 + current_time.minute
        work_start_time = datetime.strptime(self.work_start_time, "%H:%M")
        work_end_time = datetime.strptime(self.work_end_time, "%H:%M")
        work_start_minutes = work_start_time.hour * 60 + work_start_time.minute
        work_end_minutes = work_end_time.hour * 60 + work_end_time.minute

        return work_start_minutes <= current_minutes <= work_end_minutes

    async def check_punch_status(self):
        """检查打卡状态"""
        try:
            current_time = datetime.now()
            current_date = current_time.date()

            # [M47 修复] 跨日重置必须在 is_workday 早退之前执行，否则非工作日（周末/假日）直接 return
            # 永不重置 today_punch_records → 连续运行跨周末时，周六/日的日报/快照仍带着周五的旧打卡时间。
            # 重置本身与"今天是否工作日"无关（只看归属日期是否过期），故提到工作日守卫之前。
            # 跨日重置：按用户分桶，每个用户独立判断是否需要重置
            for uname in list(self.notification_sent_today.keys()):
                state = self.notification_sent_today[uname]
                if state.get('last_check_date') != current_date:
                    self.notification_sent_today[uname] = {
                        'punch_in_reminder': False,
                        'punch_out_reminder': False,
                        'last_check_date': current_date
                    }
                    logging.info(f"用户 {uname} 跨日，重置打卡提醒状态: {current_date}")

            # 重置昨天的打卡记录（基于归属日期 date 判断：任一用户桶的 date 早于今天即触发重置所有用户）。
            # 用 date 字段而非 punch_in_time.date()：实时打卡含今天、DOM/OCR/启动加载日期为 1900-01-01，
            # 语义不统一会导致次日遇周末/假日永不重置。date 字段是写入时记录的权威归属日期。
            needs_reset = any(
                record.get('date') and record['date'] < current_date
                for record in self.today_punch_records.values()
            )
            if needs_reset:
                self._reset_today_punch_records()
                logging.info(f"重置昨天的打卡记录（所有用户）")

            # 如果不是工作日，重置已完成、但后续打卡提醒只在工作日发送，故此处早退
            if not is_workday(current_date):
                return

            # 按用户独立判断上下班提醒（用户分桶 → 各自独立状态机）
            work_start_t = datetime.strptime(self.work_start_time, "%H:%M").time()
            punch_out_remind_t = datetime.strptime("18:00", "%H:%M").time()

            for uname, record in self.today_punch_records.items():
                state = self._get_user_notification_state(uname)
                in_t = record.get('punch_in_time')
                out_t = record.get('punch_out_time')

                # 上班提醒：该用户未打卡 + 未发过提醒 + 已过上班时间
                if (not in_t and
                    not state['punch_in_reminder'] and
                    current_time.time() > work_start_t):
                    await self.send_notification(
                        "打卡提醒",
                        f"⚠️ [{uname}] 今日未检测到上班打卡记录，请及时补卡！"
                    )
                    state['punch_in_reminder'] = True
                    logging.info(f"已发送用户 {uname} 上班打卡提醒")

                # 下班提醒：该用户已上班 + 未下班 + 未发过提醒 + 已过下班提醒时间
                if (in_t and not out_t and
                    not state['punch_out_reminder'] and
                    current_time.time() > punch_out_remind_t):
                    await self.send_notification(
                        "打卡提醒",
                        f"⚠️ [{uname}] 今日未检测到下班打卡记录，请及时补卡！"
                    )
                    state['punch_out_reminder'] = True
                    logging.info(f"已发送用户 {uname} 下班打卡提醒")

        except Exception as e:
            logging.error(f"检查打卡状态时发生错误: {str(e)}")

    async def handle_error(self, error, context="未知"):
        """统一错误处理"""
        try:
            current_time = datetime.now()
            time_diff = (current_time - self.last_error_reset).total_seconds()

            # 重置错误计数
            if time_diff > self.error_reset_interval:
                self.error_count = 0
                self.last_error_reset = current_time

            self.error_count += 1
            error_msg = f"发生错误 ({self.error_count}/{self.max_errors}) - 上下文: {context}\n错误信息: {str(error)}\n{traceback.format_exc()}"

            # 记录错误日志
            logging.error(error_msg)

            # 发送错误通知
            await self.send_notification("错误警告", error_msg)

            # 如果错误次数过多，尝试重启程序
            if self.error_count >= self.max_errors:
                logging.critical("错误次数过多，准备重启程序...")
                await self.restart_program()

        except Exception as e:
            logging.critical(f"错误处理器本身发生错误: {str(e)}")

    async def get_punch_records_from_page(self, username=None):
        """从页面识别今日打卡记录（OCR 路径，传统模式专用）

        Args:
            username: 当前归属用户，决定回写到 today_punch_records 的哪个桶；None 时退化为 'default'
        """
        try:
            # 获取浏览器窗口截图
            screen = self.take_screenshot()
            if screen is None:
                logging.error("获取截图失败，无法识别打卡记录")
                return None

            # 保存临时文件用于OCR识别
            cv2.imwrite('logs/temp_ocr.png', screen)

            # 使用OCR识别文本
            custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
            text = pytesseract.image_to_string(
                Image.open('logs/temp_ocr.png'),
                lang='chi_sim',
                config=custom_config
            )
            os.remove('logs/temp_ocr.png')  # 删除临时文件

            # 输出完整的OCR识别结果
            print("\n=== OCR识别完整结果 ===")
            print(text)
            print("=====================\n")
            logging.info(f"\n=== OCR识别完整结果 ===\n{text}\n=====================")

            # 查找今日打卡记录
            lines = text.split('\n')
            today_str = datetime.now().strftime('%Y-%m-%d')
            today_str_short = datetime.now().strftime('%m-%d')  # 短日期格式
            punch_in_time = None
            punch_out_time = None
            is_today_record = False

            # 定义日期匹配模式
            date_patterns = [
                r'\d{4}-\d{2}-\d{2}',  # 完整日期格式 YYYY-MM-DD
                r'\d{2}-\d{2}'         # 短日期格式 MM-DD
            ]

            # 定义多个时间匹配模式
            time_patterns = [
                (r'(\d{2}:\d{2})\s*上班', '上班'),
                (r'(\d{2}[:：]\d{2})\s*上班', '上班'),  # 处理中文冒号
                (r'上班\s*(\d{2}[:：]\d{2})', '上班'),  # 处理时间在后面的情况
                (r'(\d{2}:\d{2})\s*下班', '下班'),
                (r'(\d{2}[:：]\d{2})\s*下班', '下班'),  # 处理中文冒号
                (r'下班\s*(\d{2}[:：]\d{2})', '下班'),  # 处理时间在后面的情况
            ]

            # 遍历所有行寻找打卡记录
            for i, line in enumerate(lines):
                logging.debug(f"处理第{i+1}行: {line}")

                # 首先检查是否包含日期
                for date_pattern in date_patterns:
                    date_match = re.search(date_pattern, line)
                    if date_match:
                        date_str = date_match.group(0)
                        # 如果是短日期格式，添加年份
                        if len(date_str) == 5:  # MM-DD格式
                            is_today_record = date_str == today_str_short
                        else:  # YYYY-MM-DD格式
                            is_today_record = date_str == today_str
                        logging.debug(f"找到日期: {date_str}, 是否今天: {is_today_record}")
                        break  # 找到日期后跳出内层循环

                # 检查打卡时间
                # 如果已经确认是今天的记录，或者在同一行找到日期和时间
                if is_today_record or any(today_str in line for date_pattern in date_patterns):
                    # 检查所有匹配模式
                    for pattern, punch_type in time_patterns:
                        time_match = re.search(pattern, line)
                        if time_match:
                            time_str = time_match.group(1).replace('：', ':')  # 统一冒号格式
                            if punch_type == '上班' and not punch_in_time:
                                punch_in_time = time_str + ':00'
                                logging.info(f"识别到今日上班打卡时间: {punch_in_time}")
                            elif punch_type == '下班' and not punch_out_time:
                                punch_out_time = time_str + ':00'
                                logging.info(f"识别到今日下班打卡时间: {punch_out_time}")

            if punch_in_time or punch_out_time:
                # 更新打卡记录
                if punch_in_time:
                    try:
                        self._set_user_punch_time(username, 'punch_in_time', datetime.strptime(punch_in_time, '%H:%M:%S'))
                        self.punch_record_manager.update_record(today_str, "上班", punch_in_time)
                        logging.info(f"成功更新今日上班打卡记录: {punch_in_time}")
                    except Exception as e:
                        logging.error(f"更新上班打卡记录时出错: {str(e)}")

                if punch_out_time:
                    try:
                        self._set_user_punch_time(username, 'punch_out_time', datetime.strptime(punch_out_time, '%H:%M:%S'))
                        self.punch_record_manager.update_record(today_str, "下班", punch_out_time)
                        logging.info(f"成功更新今日下班打卡记录: {punch_out_time}")
                    except Exception as e:
                        logging.error(f"更新下班打卡记录时出错: {str(e)}")

                await self.send_notification("打卡记录",
                    f"已更新今日打卡记录:\n"
                    f"上班时间: {punch_in_time if punch_in_time else '未识别'}\n"
                    f"下班时间: {punch_out_time if punch_out_time else '未识别'}"
                )
                return True
            else:
                logging.warning("未能从页面识别到今日打卡记录")
                return False

        except Exception as e:
            logging.error(f"识别打卡记录时发生错误: {str(e)}\n{traceback.format_exc()}")
            return False

    async def send_email_with_attachment(self, subject, body, attachment_path, punch_type):
        """发送带附件的电子邮件（异步，不阻塞打卡流程）"""
        try:
            await self.send_notification("邮件发送", f"准备发送{punch_type}打卡截图邮件...")

            # 使用异步方式发送邮件，不阻塞打卡流程
            # 简化callback，只记录日志，避免事件循环问题
            def email_callback(success: bool, email_subject: str):
                if success:
                    logging.info(f"邮件发送成功: {email_subject}")
                else:
                    logging.error(f"邮件发送失败: {email_subject}")

            # 根据打卡结果决定是否发送给所有用户
            # 如果是失败、错误相关的打卡，发送给所有用户
            send_to_all = any(keyword in punch_type for keyword in ["失败", "错误", "异常"])

            # 异步发送邮件；把临时截图的删除交给后台发送线程（cleanup_path），
            # 避免主流程提前 os.remove 与后台读取附件竞争（WinError 32）。
            self.email_service.send_email_async(
                subject=subject,
                body=body,
                image_path=attachment_path,
                send_to_all=send_to_all,
                callback=email_callback,
                cleanup_path=attachment_path
            )

            # 立即返回True，不等待邮件发送完成
            return True

        except Exception as e:
            error_msg = f"邮件发送异常: {str(e)}"
            logging.error(error_msg)
            await self.send_notification("邮件发送", error_msg)
            return False

    async def get_today_punch_in_time(self):
        """获取当日上班打卡时间，支持从记录和页面识别两种方式

        Returns:
            tuple: (success: bool, punch_in_time: str or None, message: str)
        """
        try:
            # 方法1：从本地记录获取
            today_record = self.punch_record_manager.get_today_record()
            if today_record and today_record.get('punch_in_time'):
                punch_in_time = today_record['punch_in_time']
                return (True, punch_in_time, f"从本地记录获取到上班时间: {punch_in_time}")

            # 方法2：如果本地没有记录，登录系统页面识别
            logging.info("本地没有上班打卡记录，尝试从系统页面识别")
            await self.send_notification("时间识别", "本地没有上班打卡记录，正在登录系统页面识别...")

            # 使用第一个用户的凭据登录
            if not self.users or len(self.users) == 0:
                return (False, None, "未配置用户信息，无法登录系统")

            user = self.users[0]  # 使用第一个用户
            username = user.get('username')
            password = user.get('password')

            # 执行登录流程
            login_success, screen = await self._login_to_system(username, password, "时间识别")
            if not login_success:
                return (False, None, "登录系统失败，无法识别页面打卡记录")

            # 从页面识别打卡记录
            records_found = await self.get_punch_records_from_page(username=username)
            if records_found:
                # 重新检查本地记录
                updated_record = self.punch_record_manager.get_today_record()
                if updated_record and updated_record.get('punch_in_time'):
                    punch_in_time = updated_record['punch_in_time']

                    # 关闭浏览器
                    if self.bot.close_browser():
                        await self.send_notification("时间识别", "页面识别完成，浏览器已关闭")

                    return (True, punch_in_time, f"从系统页面识别到上班时间: {punch_in_time}")

            # 关闭浏览器
            if self.bot.close_browser():
                await self.send_notification("时间识别", "页面识别未成功，浏览器已关闭")

            return (False, None, "系统页面未找到今日上班打卡记录")

        except Exception as e:
            error_msg = f"获取上班打卡时间时发生错误: {str(e)}"
            logging.error(error_msg)
            await self.send_notification("时间识别", error_msg)
            return (False, None, error_msg)

    async def get_today_punch_in_time_auto(self):
        """获取今日上班时间（模式分派包装，新增方法，不改动传统 get_today_punch_in_time）。

        - 传统模式：调用原有 get_today_punch_in_time（PyAutoGUI 登录 + OCR 页面识别），逻辑一字不动。
        - Selenium 模式：调用 get_today_punch_in_time_via_selenium（WebDriver 登录 + DOM 解析）。

        Returns:
            tuple: (success: bool, punch_in_time: str|None, message: str)
        """
        if self.use_selenium_login:
            return await self.get_today_punch_in_time_via_selenium()
        return await self.get_today_punch_in_time()

    async def get_today_punch_in_time_via_selenium(self):
        """Selenium 版获取今日上班时间（新增方法，复刻传统页面识别能力，不依赖 OCR/PyAutoGUI）。

        步骤：先查本地记录（模式无关）→ 无则用 SeleniumLoginController 登录并从页面 DOM 解析，
        识别成功后回写记录。替代传统 _login_to_system + get_punch_records_from_page + bot.close_browser，
        使 selenium（含无头）模式下 /auto_byebye、16:35 自动下班在无本地记录时也能识别页面上班时间。

        Returns:
            tuple: (success: bool, punch_in_time: str|None, message: str)
        """
        # 方法1：从本地记录获取（与传统一致，模式无关）
        try:
            today_record = self.punch_record_manager.get_today_record()
            if today_record and today_record.get('punch_in_time'):
                punch_in_time = today_record['punch_in_time']
                return (True, punch_in_time, f"从本地记录获取到上班时间: {punch_in_time}")
        except Exception as e:
            logging.warning(f"读取本地上班记录失败: {e}")

        # 方法2：Selenium 登录系统页面识别（DOM 解析）
        if not self.users or len(self.users) == 0:
            return (False, None, "未配置用户信息，无法登录系统")

        from modules.selenium_login import SeleniumLoginController
        user = self.users[0]  # 使用第一个用户
        username = user.get('username')
        password = user.get('password')
        controller = None
        try:
            await self.send_notification("时间识别", "Selenium 模式：登录系统页面识别今日上班时间...")
            controller = SeleniumLoginController(
                login_url=self.login_url,
                headless=self.selenium_headless,
                notification_callback=None,
                username=username or "default"
            )
            # 注册到活跃集合，便于 atexit/signal/cancel 路径统一兜底关闭
            self._register_controller(controller)

            login_ok, login_msg = await controller.login(username, password)
            if not login_ok:
                return (False, None, f"Selenium 登录系统失败，无法识别页面打卡记录: {login_msg}")

            # 登录提交后页面已导航，需经 _switch_to_main_frame 重新切 mainFrame，故 skip_frame_switch=False
            page_times = await controller.get_today_punch_times_from_page(skip_frame_switch=False)
            punch_in_time = (page_times or {}).get('punch_in_time')
            punch_out_time = (page_times or {}).get('punch_out_time')

            if punch_in_time:
                today_str = datetime.now().strftime('%Y-%m-%d')
                # 回写记录：与传统 OCR get_punch_records_from_page 对齐——内存分桶 +
                # 共享 PunchRecordManager（上面"方法1"正是读它，保证后续调用缓存命中、避免重复登录识别）
                try:
                    self._set_user_punch_time(
                        username, 'punch_in_time',
                        datetime.strptime(punch_in_time, '%H:%M:%S')
                    )
                    self.punch_record_manager.update_record(today_str, "上班", punch_in_time)
                except Exception as set_err:
                    logging.warning(f"回写上班记录失败: {set_err}")
                if punch_out_time:
                    try:
                        self._set_user_punch_time(
                            username, 'punch_out_time',
                            datetime.strptime(punch_out_time, '%H:%M:%S')
                        )
                        self.punch_record_manager.update_record(today_str, "下班", punch_out_time)
                    except Exception as set_err:
                        logging.warning(f"回写下班记录失败: {set_err}")
                # 同步写入 Selenium 用户隔离记录（与 _do_selenium_punch 记录系统一致）
                try:
                    controller.record_manager.update_punch_record('punch_in', punch_in_time)
                    if punch_out_time:
                        controller.record_manager.update_punch_record('punch_out', punch_out_time)
                except Exception as rec_err:
                    logging.warning(f"回写 Selenium 月度记录失败: {rec_err}")

                await self.send_notification("时间识别", "页面识别完成，浏览器已关闭")
                return (True, punch_in_time, f"从系统页面识别到上班时间: {punch_in_time}")

            return (False, None, "系统页面未找到今日上班打卡记录")

        except Exception as e:
            error_msg = f"Selenium 页面识别上班时间失败: {str(e)}"
            logging.error(error_msg)
            return (False, None, error_msg)
        finally:
            if controller is not None:
                try:
                    controller.close()
                except Exception as close_err:
                    logging.warning(f"关闭 Selenium 控制器失败: {close_err}")
                self._unregister_controller(controller)

    async def fetch_today_punch_status(self, max_concurrent: int = 3) -> Dict[str, Dict]:
        """登录考勤系统，读取**所有已配置用户**的今日上/下班打卡时间（强制访问系统页面，不读本地缓存）。

        与 ``get_today_punch_in_time_via_selenium`` 的区别：覆盖全部用户、强制从系统页面读取、
        同时返回上/下班时间。复用 SeleniumLoginController.login + get_today_punch_times_from_page，
        识别成功后回写 today_punch_records / 全局月度记录 / Selenium 用户隔离记录，供概览和自动下班复用。
        不点击任何打卡按钮。

        Returns:
            Dict[username, {'success': bool, 'punch_in_time': str|None, 'punch_out_time': str|None, 'message': str}]
        """
        from modules.selenium_login import SeleniumLoginController
        users = [u for u in (self.users or []) if u.get('username') and u.get('password')]
        if not users:
            return {}

        semaphore = asyncio.Semaphore(max_concurrent)
        today_str = datetime.now().strftime('%Y-%m-%d')

        async def _fetch_one(user):
            username = user.get('username')
            password = user.get('password')
            async with semaphore:
                controller = None
                try:
                    await self.send_notification("获取打卡情况", f"{username}：登录系统读取今日打卡...")
                    controller = SeleniumLoginController(
                        login_url=self.login_url,
                        headless=self.selenium_headless,
                        notification_callback=None,
                        username=username or "default"
                    )
                    self._register_controller(controller)

                    login_ok, login_msg = await controller.login(username, password)
                    if not login_ok:
                        return username, {
                            'success': False, 'punch_in_time': None, 'punch_out_time': None,
                            'message': f'登录失败: {login_msg}'
                        }

                    # 登录提交后页面已导航，需重新切 mainFrame，故 skip_frame_switch=False
                    page_times = await controller.get_today_punch_times_from_page(skip_frame_switch=False)
                    pin = (page_times or {}).get('punch_in_time')
                    pout = (page_times or {}).get('punch_out_time')

                    # 回写记录（与 get_today_punch_in_time_via_selenium 对齐：内存分桶 + 全局月度 + Selenium 月度）
                    try:
                        if pin:
                            self._set_user_punch_time(username, 'punch_in_time', datetime.strptime(pin, '%H:%M:%S'))
                            self.punch_record_manager.update_record(today_str, "上班", pin)
                            controller.record_manager.update_punch_record('punch_in', pin)
                        if pout:
                            self._set_user_punch_time(username, 'punch_out_time', datetime.strptime(pout, '%H:%M:%S'))
                            self.punch_record_manager.update_record(today_str, "下班", pout)
                            controller.record_manager.update_punch_record('punch_out', pout)
                    except Exception as wb_err:
                        logging.warning(f"回写今日打卡记录失败({username}): {wb_err}")

                    return username, {
                        'success': True,
                        'punch_in_time': pin,
                        'punch_out_time': pout,
                        'message': f"上班={pin or '未识别'} 下班={pout or '未识别'}"
                    }
                except Exception as e:
                    logging.error(f"获取今日打卡情况失败({username}): {str(e)}")
                    return username, {
                        'success': False, 'punch_in_time': None, 'punch_out_time': None,
                        'message': str(e)
                    }
                finally:
                    if controller is not None:
                        try:
                            controller.close()
                        except Exception as close_err:
                            logging.warning(f"关闭 Selenium 控制器失败({username}): {close_err}")
                        self._unregister_controller(controller)

        pairs = await asyncio.gather(*[_fetch_one(u) for u in users], return_exceptions=True)
        results: Dict[str, Dict] = {}
        for p in pairs:
            if isinstance(p, Exception):
                logging.error(f"fetch_today_punch_status 子任务异常: {p}")
                continue
            uid, val = p
            results[uid] = val
        return results

    def calculate_punch_out_time(self, punch_in_time_str):
        """根据上班时间计算下班时间（8小时15分钟后 + 1-3分钟随机延迟）

        Args:
            punch_in_time_str: 上班时间字符串，格式如 "08:30:00" 或 "08:30"

        Returns:
            tuple: (success: bool, punch_out_time_str: str, message: str)
        """
        try:
            import random
            
            # 处理时间格式
            if len(punch_in_time_str.split(':')) == 2:
                punch_in_time_str += ':00'  # 补充秒数

            # 解析上班时间
            punch_in_time = datetime.strptime(punch_in_time_str, '%H:%M:%S').time()

            # 生成1-3分钟的随机延迟（精确到秒）
            random_delay_seconds = random.randint(60, 180)  # 60-180秒（1-3分钟）
            
            # 计算下班时间（8小时15分钟后 + 随机延迟）
            today = datetime.now().date()
            punch_in_datetime = datetime.combine(today, punch_in_time)
            punch_out_datetime = punch_in_datetime + timedelta(hours=8, minutes=15, seconds=random_delay_seconds)

            punch_out_time_str = punch_out_datetime.strftime('%H:%M:%S')

            # 将秒数转换为分钟和秒的格式
            delay_minutes = random_delay_seconds // 60
            delay_seconds = random_delay_seconds % 60
            delay_display = f"{delay_minutes}分{delay_seconds}秒" if delay_seconds > 0 else f"{delay_minutes}分钟"
            
            message = f"根据上班时间 {punch_in_time_str} 计算得出下班时间: {punch_out_time_str}（已加{delay_display}随机延迟）"
            logging.info(message)

            return (True, punch_out_time_str, message)

        except Exception as e:
            error_msg = f"计算下班时间时发生错误: {str(e)}"
            logging.error(error_msg)
            return (False, None, error_msg)

    async def check_email_connection(self):
        """检查与邮件服务器的连接"""
        try:
            # 在静默初始化期间不输出控制台信息
            if not getattr(self, '_silent_init', False):
                status_msg = "正在检查邮件服务器连接..."
                logging.info(status_msg)
                print(status_msg)

            # 使用EmailService检查连接
            if self.email_service.check_email_connection():
                success_msg = "邮件服务器连接测试成功"
                logging.info(success_msg)
                if not getattr(self, '_silent_init', False):
                    print(success_msg)
                return True
            else:
                error_msg = "邮件服务器连接失败"
                logging.error(error_msg)
                if not getattr(self, '_silent_init', False):
                    print(error_msg)
                    await self.send_notification("邮箱连接", f"❌ {error_msg}")
                return False

        except Exception as e:
            error_msg = f"邮件服务器连接异常: {str(e)}"
            logging.error(error_msg)
            if not getattr(self, '_silent_init', False):
                print(error_msg)
                await self.send_notification("邮箱连接", f"❌ {error_msg}")
            return False

    async def parallel_punch_login(self, users_config: List[Dict[str, str]], max_concurrent: int = 3) -> Dict[str, Tuple[bool, str]]:
        """
        并行执行多用户登录

        Args:
            users_config: 用户配置列表，格式: [{'user_id': '', 'username': '', 'password': ''}, ...]
            max_concurrent: 最大并发数，默认3个

        Returns:
            Dict[str, Tuple[bool, str]]: 每个用户的登录结果
        """
        try:
            await self.send_notification("并行登录", f"开始并行登录 {len(users_config)} 个用户")

            # 创建并行登录管理器
            parallel_login = ParallelSeleniumLogin(
                login_url=self.login_url,
                headless=self.selenium_headless,
                notification_callback=self.send_notification,
                browser_type="edge"
            )

            # 执行并行登录
            results = await parallel_login.parallel_login(
                users=users_config,
                max_concurrent=max_concurrent
            )

            # 记录结果
            success_users = [user_id for user_id, (success, _) in results.items() if success]
            failed_users = [user_id for user_id, (success, _) in results.items() if not success]

            await self.send_notification(
                "并行登录完成",
                f"✅ 成功: {len(success_users)} 个\n❌ 失败: {len(failed_users)} 个"
            )

            if failed_users:
                failed_details = []
                for user_id in failed_users:
                    _, error_msg = results[user_id]
                    failed_details.append(f"• {user_id}: {error_msg}")

                await self.send_notification(
                    "登录失败详情",
                    "\n".join(failed_details[:5])  # 只显示前5个失败详情
                )

            return results

        except Exception as e:
            error_msg = f"并行登录异常: {str(e)}"
            logging.error(error_msg, exc_info=True)
            await self.send_notification("并行登录异常", error_msg)
            return {user['user_id']: (False, error_msg) for user in users_config}

    def prepare_users_config_from_env(self) -> List[Dict[str, str]]:
        """
        从环境变量中准备用户配置

        Returns:
            List[Dict[str, str]]: 用户配置列表
        """
        users = []

        # 直接使用现有的用户配置
        for i, user in enumerate(self.users):
            if user.get('username') and user.get('password'):
                users.append({
                    'user_id': f'user{i+1}',
                    'username': user['username'],
                    'password': user['password']
                })

        return users

    # ------------------------------------------------------------------
    # GUI-facing helpers — 只读快照 + 动态配置写入
    # 这些方法供 modules/web_server.py 的 Flask 路由调用，需保持非阻塞且线程安全。
    # ------------------------------------------------------------------

    def get_status_snapshot(self) -> Dict:
        """返回系统当前状态的 JSON 友好快照。"""

        def _fmt_dt(dt):
            if not dt:
                return None
            try:
                return dt.isoformat()
            except Exception:
                return str(dt)

        today_records = {}
        _today = datetime.now().date()
        for username, rec in (self.today_punch_records or {}).items():
            # 归属日期不是今天（含周末/假日次日尚未触发重置）一律视为"未打卡"，避免展示昨天的旧时间
            if rec.get('date') != _today:
                today_records[username] = {
                    'punch_in_time': None,
                    'punch_out_time': None,
                }
            else:
                today_records[username] = {
                    'punch_in_time': _fmt_dt(rec.get('punch_in_time')),
                    'punch_out_time': _fmt_dt(rec.get('punch_out_time')),
                }

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
            'is_workday': workday,
            'is_holiday': holiday,
            'is_work_time': self.is_work_time(),
            'current_operation': self.current_operation,
            'operation_started_at': _fmt_dt(self.operation_start_time),
            'today_records': today_records,
            'config': {
                'work_start_time': self.work_start_time,
                'work_end_time': self.work_end_time,
                'late_threshold': self.late_threshold,
                'early_leave_threshold': self.early_leave_threshold,
                'use_selenium_login': self.use_selenium_login,
                'selenium_headless': self.selenium_headless,
                'daily_status_time': self.daily_status_time,
            },
            'scheduled_tasks': list(self.task_manager.get_tasks()),
            'heartbeat': {
                'last': _fmt_dt(self.last_heartbeat),
                'miss_count': self.heartbeat_miss_count,
            },
            'active_controllers': len(self._active_controllers),
            'bot_available': bool(getattr(self, 'bot_available', True)),
            'bot_error': getattr(self, 'bot_error', None),
            'users': [u.get('username') for u in self.users if u.get('username')],
            'resources': resources,
        }

    def get_running_operations(self) -> Dict:
        """返回当前正在进行的操作详情（精简版，不阻塞）。"""
        return {
            'current_operation': self.current_operation,
            'started_at': self.operation_start_time.isoformat() if self.operation_start_time else None,
            'active_controllers': len(self._active_controllers),
        }

    def update_dynamic_config(self, patch: Dict) -> Dict:
        """更新 dynamic_config.json 并同步实例内布尔标志。

        - ``USE_SELENIUM_LOGIN`` 立刻生效（下次打卡走新模式）
        - ``SELENIUM_HEADLESS`` 写入文件，**仅下次新建 SeleniumLoginController 时生效**
          （进行中的浏览器实例不会重启，由调用方在 UI 中提示用户）
        """
        if 'USE_SELENIUM_LOGIN' in patch:
            val = bool(patch['USE_SELENIUM_LOGIN'])
            config.set_selenium_config('USE_SELENIUM_LOGIN', val)
            self.use_selenium_login = val
        if 'SELENIUM_HEADLESS' in patch:
            val = bool(patch['SELENIUM_HEADLESS'])
            config.set_selenium_config('SELENIUM_HEADLESS', val)
            self.selenium_headless = val
        return {
            'USE_SELENIUM_LOGIN': self.use_selenium_login,
            'SELENIUM_HEADLESS': self.selenium_headless,
        }
