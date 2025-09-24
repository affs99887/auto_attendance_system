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
from chinese_calendar import is_workday, is_holiday
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

        # 添加打卡提醒状态跟踪（用于防止重复提醒）
        self.notification_sent_today = {
            'punch_in_reminder': False,
            'punch_out_reminder': False,
            'last_check_date': None
        }

        # 初始化任务管理器和打卡记录管理器（使用新的导入模块）
        self.task_manager = task_manager
        self.punch_record_manager = punch_record_manager

        # 加载今日打卡记录
        today_record = self.punch_record_manager.get_today_record()
        self.today_punch_records = {
            'punch_in_time': datetime.strptime(today_record['punch_in_time'], '%H:%M:%S') if today_record['punch_in_time'] else None,
            'punch_out_time': datetime.strptime(today_record['punch_out_time'], '%H:%M:%S') if today_record['punch_out_time'] else None
        }

        # 设置每日状态推送时间
        self.daily_status_time = config.DAILY_STATUS_TIME  # 每日状态推送时间

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

        # 初始化完成，取消静默模式
        self._silent_init = False

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

    async def _send_punch_failure_screenshot(self, screen, username, punch_type, error_msg):
        """发送打卡失败截图的辅助方法
        
        Args:
            screen: 截图数据
            username: 用户名
            punch_type: 打卡类型 "上班" 或 "下班"
            error_msg: 错误消息
        """
        try:
            # 保存并发送当前的浏览器窗口截图
            screenshot_path = f'punch_{punch_type}_fail_uncertain.png'
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
            email_body = f"{surname}您好，\n\n您的{punch_type}打卡尝试失败。\n\n原因：{error_msg}\n\n系统会在适当时间自动重试。\n\n此邮件由自动打卡系统发送，请勿回复。"

            # 复制截图用于邮件发送
            email_screenshot_path = f'logs/punch_{punch_type}_fail_email.png'
            with open(screenshot_path, 'rb') as f_in:
                img_data = f_in.read()
                with open(email_screenshot_path, 'wb') as f_out:
                    f_out.write(img_data)

            # 发送邮件
            await self.send_email_with_attachment(email_subject, email_body, email_screenshot_path, f"{punch_type}(失败)")

            # 删除临时文件
            os.remove(screenshot_path)
            if os.path.exists(email_screenshot_path):
                os.remove(email_screenshot_path)

        except Exception as e:
            error_type = type(e).__name__
            error_msg_detail = str(e)

            # 检查是否是HTTPXRequest初始化错误
            if "HTTPXRequest" in error_msg_detail and "not initialized" in error_msg_detail:
                self.bot._is_initialized = False
                await self.send_notification("打卡流程", f"通知发送失败 (HTTPXRequest错误): {error_msg_detail}")
            else:
                await self.send_notification("打卡流程", f"通知发送失败: {error_msg_detail}")

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

        # 确保bot已初始化
        if not self.bot:
            logging.warning(f"无法发送通知，Telegram bot实例不存在: {title} - {content}")
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
            screen = self.take_screenshot()
            if screen is None:
                print(f"截图失败，{attempt + 1} 次重试...")
                time.sleep(self.retry_interval)
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
                time.sleep(self.retry_interval)

        # 记录最终匹配失败的详细信息
        if 'unable_escape.png' in template_path or 'left_time.png' in template_path:
            logging.warning(f"关键模板匹配失败 {template_path}：最高置信度={max_val:.3f}, 尝试次数={self.max_retries}")

        return None

    def find_element_with_label(self, template_path, label_template_path, threshold=0.8):
        """通过标签和输入框的组合来定位元素"""
        for attempt in range(self.max_retries):
            screen = self.take_screenshot()
            if screen is None:
                print(f"截图失败，{attempt + 1} 次重试...")
                time.sleep(self.retry_interval)
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
                time.sleep(self.retry_interval)

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

    async def schedule_retry_punch_out(self, delay_minutes, clear_existing=True):
        """设置定时重试下班打卡

        参数:
            delay_minutes: 延迟多少分钟后打卡
            clear_existing: 是否清除已有任务，默认为True
        """
        try:
            logging.info(f"开始设置定时下班打卡，延迟{delay_minutes}分钟")
            retry_time = datetime.now() + timedelta(minutes=delay_minutes)
            time_str = retry_time.strftime("%H:%M")

            if clear_existing:
                # 只有在明确指定时才清除所有任务
                schedule.clear()
                logging.info("清除了之前的所有定时任务")
            else:
                # 如果不清除所有任务，则只移除同一时间的下班打卡任务
                # 由于schedule库的限制，我们需要通过遍历查找同一时间的任务
                all_jobs = schedule.get_jobs()
                punch_out_jobs = [job for job in all_jobs if "punch_out" in str(job.job_func)]
                for job in punch_out_jobs:
                    schedule.cancel_job(job)
                logging.info(f"已移除{len(punch_out_jobs)}个已有的下班打卡定时任务")

            async def punch_out_job():
                try:
                    logging.info("执行定时下班打卡任务")
                    await self.punch_out()
                    # 打卡完成后发送状态信息
                    await self.send_daily_status()
                    # 删除已执行的任务
                    self.task_manager.clear_tasks()
                    schedule.clear()
                    logging.info("定时下班打卡任务执行完成")
                except Exception as e:
                    logging.error(f"执行定时下班打卡任务时发生错误: {str(e)}")

            # 设置定时任务
            time_str = retry_time.strftime("%H:%M")
            schedule.every().day.at(time_str).do(lambda: asyncio.create_task(punch_out_job()))
            logging.info(f"已设置定时任务: 每天{time_str}执行下班打卡")

            # 保存定时任务到文件
            if clear_existing:
                self.task_manager.clear_tasks()  # 只有在明确指定时才清除所有任务
                logging.info("已清除任务管理器中的所有任务")
            else:
                # 删除已有的下班打卡任务
                saved_tasks = self.task_manager.get_tasks()
                for task in saved_tasks:
                    if task['type'] == 'punch_out':
                        self.task_manager.remove_task_by_id(task['id'])
                        logging.info(f"已从任务管理器中移除下班打卡任务 #{task['id']}")

            # 添加新的定时任务
            task_id = self.task_manager.add_task('punch_out', time_str)
            logging.info(f"保存定时任务到文件，任务ID: {task_id}")

            if clear_existing:
                await self.send_notification("定时设置", f"已清除之前所有的定时任务")
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
            all_jobs = schedule.get_jobs()
            punch_out_jobs = [job for job in all_jobs if "punch_out" in str(job.job_func)]
            for job in punch_out_jobs:
                schedule.cancel_job(job)
            logging.info(f"已移除{len(punch_out_jobs)}个已有的下班打卡定时任务")
            
            async def punch_out_job():
                try:
                    logging.info(f"执行定时下班打卡任务 ({time_str})")
                    await self.punch_out()
                    # 打卡完成后发送状态信息
                    await self.send_daily_status()
                    logging.info(f"定时下班打卡任务 ({time_str}) 执行完成")
                except Exception as e:
                    logging.error(f"执行定时下班打卡任务时发生错误: {str(e)}")
            
            # 设置定时任务
            schedule.every().day.at(time_str).do(lambda: asyncio.create_task(punch_out_job()))
            logging.info(f"已设置定时任务: 每天{time_str}执行下班打卡")
            
            # 删除已有的下班打卡任务记录
            saved_tasks = self.task_manager.get_tasks()
            for task in saved_tasks:
                if task['type'] == 'punch_out':
                    self.task_manager.remove_task_by_id(task['id'])
                    logging.info(f"已从任务管理器中移除下班打卡任务 #{task['id']}")
            
            # 添加新的定时任务记录
            task_id = self.task_manager.add_task('punch_out', time_str)
            logging.info(f"保存定时任务到文件，任务ID: {task_id}")
            
            await self.send_notification("定时设置", f"设置下班打卡任务 #{task_id}: {time_str}")
            
            return True
        except Exception as e:
            error_msg = f"设置定时下班打卡任务失败: {str(e)}"
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            await self.send_notification("定时设置错误", error_msg)
            return False

    def init_schedule_tasks(self):
        """初始化定时任务"""
        # 清除所有现有任务
        schedule.clear()

        # 设置每天早上的状态推送
        async def daily_status_job():
            await self.send_daily_status()
        schedule.every().day.at(self.daily_status_time).do(lambda: asyncio.create_task(daily_status_job()))

        # 从文件加载保存的定时任务
        saved_tasks = self.task_manager.get_tasks()
        for task in saved_tasks:
            if task['type'] == 'punch_out':
                async def punch_out_job():
                    try:
                        await self.punch_out()
                        # 打卡完成后发送状态信息
                        await self.send_daily_status()
                        # 删除已执行的任务
                        self.task_manager.clear_tasks()
                        schedule.clear()
                        # 重新初始化每日状态推送任务
                        schedule.every().day.at(self.daily_status_time).do(lambda: asyncio.create_task(daily_status_job()))
                    except Exception as e:
                        logging.error(f"执行定时下班打卡任务时发生错误: {str(e)}")
                schedule.every().day.at(task['scheduled_time']).do(lambda: asyncio.create_task(punch_out_job()))
            elif task['type'] == 'punch_in':
                async def punch_in_job():
                    try:
                        await self.punch_in()
                        # 打卡完成后发送状态信息
                        await self.send_daily_status()
                    except Exception as e:
                        logging.error(f"执行定时上班打卡任务时发生错误: {str(e)}")
                schedule.every().day.at(task['scheduled_time']).do(lambda: asyncio.create_task(punch_in_job()))

    async def send_daily_status(self):
        """发送每日状态信息"""
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
            status_text += "📍 今日打卡记录\n"
            for user in self.users:
                status_text += f"\n用户: {user['username']}\n"
                status_text += f"上班打卡：{'✅ ' + user['punch_records']['punch_in_time'].strftime('%H:%M:%S') if user['punch_records']['punch_in_time'] else '❌ 未打卡'}\n"
                status_text += f"下班打卡：{'✅ ' + user['punch_records']['punch_out_time'].strftime('%H:%M:%S') if user['punch_records']['punch_out_time'] else '❌ 未打卡'}\n"

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


    async def _do_punch(self, punch_type="上班", username=None, password=None, collect_remaining_time=False):
        """通用打卡方法"""
        screen = None
        remaining_time_info = None  # 用于存储剩余工作时间信息

        # 确保bot已初始化
        if not self.bot or not hasattr(self.bot, 'app') or not self.bot.app:
            error_msg = f"Telegram bot未正确初始化，无法执行{punch_type}打卡"
            logging.error(error_msg)
            return (False, None)

        try:
            # 重置消息
            self.current_message = f"开始{punch_type}打卡流程 - 用户: {username}"
            self.message_id = None

            # 根据配置选择打卡模式
            if self.use_selenium_login:
                await self.send_notification("打卡流程", f"使用Selenium模式执行{punch_type}打卡")
                return await self._do_selenium_punch(punch_type, username, password, collect_remaining_time)
            else:
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

                        # 删除临时文件
                        os.remove(screenshot_path)
                        if os.path.exists(email_screenshot_path):
                            os.remove(email_screenshot_path)
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
                    self.today_punch_records['punch_in_time'] = current_time
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
                            error_msg = "未满足下班条件，无法获取剩余时间"
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
                            email_body = f"{surname}您好，\n\n您的{punch_type}打卡尝试失败。\n\n原因：{error_msg}\n\n系统会在适当时间自动重试。\n\n此邮件由自动打卡系统发送，请勿回复。"

                            # 复制截图用于邮件发送
                            email_screenshot_path = f'logs/punch_out_fail_email.png'
                            with open(screenshot_path, 'rb') as f_in:
                                img_data = f_in.read()
                                with open(email_screenshot_path, 'wb') as f_out:
                                    f_out.write(img_data)

                            # 发送邮件
                            await self.send_email_with_attachment(email_subject, email_body, email_screenshot_path, f"{punch_type}(失败)")

                            # 删除临时文件
                            os.remove(screenshot_path)
                            if os.path.exists(email_screenshot_path):
                                os.remove(email_screenshot_path)

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
                                await self.get_punch_records_from_page()
                                
                                # 检查今日是否已有下班记录
                                today_record = self.punch_record_manager.get_today_record()
                                has_punch_out_today = bool(today_record and today_record.get('punch_out_time'))
                                
                                if has_punch_out_today:
                                    # 今日已有下班记录，说明已经完成下班打卡
                                    await self.send_notification("打卡流程", f"页面显示今日已完成下班打卡: {today_record.get('punch_out_time')}")
                                    logging.info("通过页面记录确认今日已下班打卡")
                                    
                                    # 更新内存中的记录
                                    self.today_punch_records['punch_out_time'] = current_time
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
                            self.today_punch_records['punch_out_time'] = current_time
                            # 保存打卡记录
                            self.punch_record_manager.update_record(
                                current_time.strftime('%Y-%m-%d'),
                                "下班",
                                current_time.strftime('%H:%M:%S')
                            )
                            punch_success = True

                if punch_success:
                    # 识别并更新打卡记录
                    await self.get_punch_records_from_page()

                    # 重置相应的提醒状态（如果用户补打卡了）
                    if punch_type == "上班":
                        self.notification_sent_today['punch_in_reminder'] = False
                        logging.info("上班打卡成功，重置上班打卡提醒状态")
                    else:
                        self.notification_sent_today['punch_out_reminder'] = False
                        logging.info("下班打卡成功，重置下班打卡提醒状态")

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
                                email_screenshot_path = f'logs/punch_{"in" if punch_type == "上班" else "out"}_email.png'
                                with open(screenshot_path, 'rb') as f_in:
                                    img_data = f_in.read()
                                    with open(email_screenshot_path, 'wb') as f_out:
                                        f_out.write(img_data)

                                # 发送邮件
                                await self.send_email_with_attachment(subject, body, email_screenshot_path, punch_type)

                                os.remove(screenshot_path)  # 删除Telegram发送的临时截图

                                # 邮件发送完成后删除邮件截图
                                if os.path.exists(email_screenshot_path):
                                    os.remove(email_screenshot_path)
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

                        # 删除临时文件
                        os.remove(screenshot_path)
                        if os.path.exists(email_screenshot_path):
                            os.remove(email_screenshot_path)
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

                    # 删除临时文件
                    os.remove(screenshot_path)
                    if os.path.exists(email_screenshot_path):
                        os.remove(email_screenshot_path)
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

    async def _do_selenium_punch(self, punch_type="上班", username=None, password=None, collect_remaining_time=False):
        """使用Selenium模式的打卡方法（增强版，支持完整功能）"""
        from modules.selenium_login import SeleniumLoginController, SeleniumRecordManager

        flow_type = "punch_in" if punch_type == "上班" else "punch_out"
        flow_name = punch_type

        # 创建消息内容追踪
        message_content = f"🔧 Selenium完整{flow_name}打卡流程开始...\n"
        status_message = None

        try:
            # 发送初始消息
            try:
                from telegram import Update
                # 尝试发送初始状态消息
                status_message = await self.bot.app.bot.send_message(
                    chat_id=self.bot.chat_id,
                    text=message_content
                )
            except:
                # 如果无法发送消息，则使用普通通知
                await self.send_notification("Selenium打卡", f"开始{flow_name}流程...")

            # 创建增强的通知回调，支持实时消息更新
            async def enhanced_notification_callback(context: str, msg: str):
                nonlocal message_content
                message_content += f"[{context}] {msg}\n"
                try:
                    if status_message:
                        await status_message.edit_text(message_content)
                    else:
                        await self.send_notification(context, msg)
                except:
                    pass  # 忽略编辑失败

            # 创建SeleniumLoginController实例
            message_content += "📋 正在创建Selenium控制器...\n"
            if status_message:
                await status_message.edit_text(message_content)

            selenium_controller = SeleniumLoginController(
                login_url=self.login_url,
                headless=self.selenium_headless,
                notification_callback=enhanced_notification_callback
            )

            # 执行完整打卡流程
            message_content += f"🚀 开始执行完整{flow_name}打卡流程...\n"
            if status_message:
                await status_message.edit_text(message_content)

            # 根据流程类型选择对应的方法
            if flow_type == "punch_in":
                success, message_result, flow_data = await selenium_controller.complete_punch_in_flow(
                    username=username or self.login_username,
                    password=password or self.login_password
                )
            else:  # punch_out
                success, message_result, flow_data = await selenium_controller.complete_punch_out_flow(
                    username=username or self.login_username,
                    password=password or self.login_password
                )

            # 处理流程结果（增强版）
            if success:
                message_content += f"✅ 完整{flow_name}流程成功: {message_result}\n"

                # 显示详细结果
                if flow_data:
                    punch_result = flow_data.get('punch_result', {})
                    if punch_result.get('punched'):
                        message_content += f"✅ {flow_name}打卡已执行\n"
                    elif punch_result.get('already_punched'):
                        message_content += f"ℹ️ 之前已打过{flow_name}卡\n"

                    # 显示下班时间确认信息（如果有）
                    if flow_type == "punch_out":
                        message_content = await self._display_punch_out_time_info(
                            message_content, flow_data
                        )

                    # 显示考勤状态
                    attendance_status = flow_data.get('attendance_status', {})
                    if attendance_status.get('today'):
                        message_content += f"📅 今日状态: {attendance_status['today']}\n"

                # 使用SeleniumRecordManager更新记录
                record_manager = SeleniumRecordManager(username or "default")
                current_time = datetime.now()
                time_str = current_time.strftime('%H:%M:%S')

                # 更新打卡记录
                additional_info = {}
                if flow_data:
                    additional_info.update(flow_data)

                record_manager.update_punch_record(
                    punch_type=flow_type,
                    time_str=time_str,
                    status_data={"success": True, "message": message_result},
                    additional_info=additional_info
                )

                message_content += f"📝 {flow_name}记录已保存\n"
            else:
                message_content += f"❌ 完整{flow_name}流程失败: {message_result}\n"

            # 更新状态：获取截图
            message_content += "📸 正在获取页面截图...\n"
            if status_message:
                await status_message.edit_text(message_content)

            # 截取最终状态截图
            screenshot = selenium_controller.take_screenshot()
            screenshot_data = None

            if screenshot:
                message_content += "✅ 截图获取成功\n"
                if status_message:
                    await status_message.edit_text(message_content)
                try:
                    await self.bot.app.bot.send_photo(
                        chat_id=self.bot.chat_id,
                        photo=screenshot,
                        caption=f"Selenium完整{flow_name}打卡流程结果截图"
                    )
                    screenshot_data = screenshot.read() if hasattr(screenshot, 'read') else screenshot
                except Exception as e:
                    message_content += f"⚠️ 截图发送失败: {str(e)}\n"
            else:
                message_content += "⚠️ 无法获取截图\n"

            # 关闭浏览器
            message_content += "🔒 正在关闭浏览器...\n"
            if status_message:
                await status_message.edit_text(message_content)
            selenium_controller.close()

            message_content += "✅ 完整流程完成！"
            if status_message:
                await status_message.edit_text(message_content)

            return (success, screenshot_data)

        except Exception as e:
            error_msg = f"Selenium{flow_name}打卡流程异常: {str(e)}"
            logging.error(error_msg)
            message_content += f"❌ 发生错误: {str(e)}\n"

            # 尝试获取异常截图
            try:
                if status_message:
                    await status_message.edit_text(message_content)
                if 'selenium_controller' in locals():
                    screenshot = selenium_controller.take_screenshot()
                    if screenshot:
                        await self.bot.app.bot.send_photo(
                            chat_id=self.bot.chat_id,
                            photo=screenshot,
                            caption=f"Selenium完整{flow_name}流程异常截图"
                        )
                    selenium_controller.close()
            except Exception as cleanup_error:
                logging.error(f"清理Selenium资源时发生错误: {str(cleanup_error)}")

            return (False, None)

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

    async def start_punch_operation(self, operation_type):
        """启动打卡操作（公共接口）"""
        async with self.operation_lock:
            if self.current_operation is not None:
                return False, f"当前已有{self.current_operation}操作正在进行中，请等待完成或使用/stop命令取消"

            # 设置操作状态
            self.current_operation = operation_type
            self.operation_start_time = datetime.now()
            self.operation_cancel_event = asyncio.Event()

            # 启动后台任务
            if operation_type == "punch_in":
                self.operation_task = asyncio.create_task(self.punch_in_internal(self.operation_cancel_event))
            elif operation_type == "punch_out":
                self.operation_task = asyncio.create_task(self.punch_out_internal(self.operation_cancel_event))
            else:
                self.current_operation = None
                self.operation_start_time = None
                self.operation_cancel_event = None
                return False, "无效的操作类型"

            # 添加任务完成回调
            self.operation_task.add_done_callback(self._operation_completed_callback)

            return True, f"{operation_type}操作已启动"

    def _operation_completed_callback(self, task):
        """操作完成时的回调函数"""
        asyncio.create_task(self._cleanup_operation_state())

    async def _cleanup_operation_state(self):
        """清理操作状态"""
        self.current_operation = None
        self.operation_task = None
        self.operation_cancel_event = None
        self.operation_start_time = None

    async def cancel_current_operation(self):
        """取消当前操作"""
        if self.current_operation is None:
            return False, "当前没有进行中的操作"

        operation_type = self.current_operation

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

        # 清理状态
        await self._cleanup_operation_state()

        return True, f"{operation_type}操作已取消"

    async def cleanup_browser(self):
        """清理浏览器资源"""
        try:
            await self.send_notification("系统清理", "正在关闭浏览器...")

            # 关闭浏览器（新的Selenium实现在各自的方法中管理，无需统一清理）
            browser_closed = self.bot.close_browser()
            if browser_closed:
                await self.send_notification("系统清理", "传统浏览器已关闭")
            else:
                await self.send_notification("系统清理", "传统浏览器关闭失败，可能需要手动关闭")

        except Exception as e:
            logging.error(f"清理浏览器时发生错误: {e}")

    async def punch_in_internal(self, cancel_event):
        """执行上班打卡（内部方法，支持取消）"""
        try:
            # 检查取消
            if cancel_event.is_set():
                await self.send_notification("操作取消", "上班打卡操作已被取消")
                return "cancelled"

            if not self.users or len(self.users) == 0:
                await self.send_notification("打卡错误", "未配置用户信息，无法执行打卡")
                return False

            success_count = 0
            for i, user in enumerate(self.users):
                # 检查取消
                if cancel_event.is_set():
                    await self.send_notification("操作取消", f"用户 {user.get('username')} 的上班打卡操作已被取消")
                    await self.cleanup_browser()
                    return "cancelled"

                username = user.get('username')
                password = user.get('password')

                # 为每个用户发送单独的开始消息
                await self.send_notification("多用户打卡", f"开始为用户 {username} 执行上班打卡 ({i+1}/{len(self.users)})")

                # 执行打卡
                result, _ = await self._do_punch("上班", username, password)

                # 检查取消
                if cancel_event.is_set():
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
                        if cancel_event.is_set():
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

    async def punch_in(self):
        """执行上班打卡（兼容性方法）"""
        success, message = await self.start_punch_operation("punch_in")
        if success:
            # 等待操作完成
            if self.operation_task:
                return await self.operation_task
        return False

    async def punch_out_internal(self, cancel_event):
        """执行下班打卡（内部方法，支持取消）"""
        try:
            # 检查取消
            if cancel_event.is_set():
                await self.send_notification("操作取消", "下班打卡操作已被取消")
                return "cancelled"

            if not self.users or len(self.users) == 0:
                await self.send_notification("打卡错误", "未配置用户信息，无法执行打卡")
                return False

            success_count = 0
            remaining_times = []  # 用于存储每个用户的剩余工作时间

            for i, user in enumerate(self.users):
                # 检查取消
                if cancel_event.is_set():
                    await self.send_notification("操作取消", f"用户 {user.get('username')} 的下班打卡操作已被取消")
                    await self.cleanup_browser()
                    return "cancelled"

                username = user.get('username')
                password = user.get('password')

                # 为每个用户发送单独的开始消息
                await self.send_notification("多用户打卡", f"开始为用户 {username} 执行下班打卡 ({i+1}/{len(self.users)})")

                # 执行打卡，并捕获剩余工作时间
                result, remaining_time_info = await self._do_punch("下班", username, password, collect_remaining_time=True)

                # 检查取消
                if cancel_event.is_set():
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
                if i < len(self.users) - 1:
                    await self.send_notification("打卡流程", f"等待5秒后开始下一个用户的打卡...")
                    # 在等待期间也检查取消
                    for _ in range(5):
                        if cancel_event.is_set():
                            await self.send_notification("操作取消", "在等待期间操作被取消")
                            await self.cleanup_browser()
                            return "cancelled"
                        await asyncio.sleep(1)

            # 检查取消
            if cancel_event.is_set():
                await self.send_notification("操作取消", "在处理定时任务前操作被取消")
                return "cancelled"

            # 所有用户打卡完成后，处理统一的定时任务
            if remaining_times:
                await self.send_notification("下班打卡", f"检测到{len(remaining_times)}个用户未满足下班条件")
                logging.info(f"多账户模式：检测到{len(remaining_times)}个用户未满足下班条件，开始处理统一定时任务")

                # 找出最长的剩余时间
                max_remaining_time = None
                max_time_user = None

                for item in remaining_times:
                    time_match = re.match(r'(\d+)小时(\d+)分钟', item['remaining_time'])
                    if time_match:
                        hours = int(time_match.group(1))
                        minutes = int(time_match.group(2))
                        total_minutes = hours * 60 + minutes
                        logging.info(f"处理用户 {item['username']} 剩余时间: {total_minutes}分钟")

                        if max_remaining_time is None or total_minutes > max_remaining_time:
                            max_remaining_time = total_minutes
                            max_time_user = item['username']

                if max_remaining_time is not None:
                    logging.info(f"确定最长剩余时间: {max_remaining_time}分钟，来自用户: {max_time_user}")
                    await self.send_notification("定时打卡", f"将为所有用户设置统一的下班打卡时间，基于用户 {max_time_user} 的剩余时间：{max_remaining_time}分钟后")

                    # 设置统一的定时打卡 - 确保这里的代码被执行
                    try:
                        # 只清除已有的下班打卡任务，保留其他类型任务
                        saved_tasks = self.task_manager.get_tasks()
                        for task in saved_tasks:
                            if task['type'] == 'punch_out':
                                self.task_manager.remove_task_by_id(task['id'])
                                logging.info(f"已移除旧的下班打卡任务 #{task['id']}")

                        # 不直接清空schedule，而是在设置新任务时覆盖同类型任务
                        retry_time = await self.schedule_retry_punch_out(max_remaining_time, clear_existing=False)
                        if retry_time:
                            logging.info(f"成功设置定时打卡时间: {retry_time}")
                            await self.send_notification("定时打卡", f"✅ 已成功设置在 {retry_time} 为所有用户执行自动下班打卡")
                        else:
                            logging.error("设置定时打卡失败，返回的时间为空")
                            await self.send_notification("定时打卡", "❌ 设置定时打卡失败，返回的时间为空")
                    except Exception as e:
                        error_msg = f"设置定时打卡时发生错误: {str(e)}"
                        logging.error(error_msg)
                        await self.send_notification("定时打卡", f"❌ {error_msg}")
                else:
                    logging.warning("无法确定最长剩余时间，定时打卡设置失败")
                    await self.send_notification("定时打卡", "⚠️ 无法确定最长剩余时间，定时打卡设置失败")

            # 所有用户打卡完成后发送总结消息
            await self.send_notification("打卡完成", f"下班打卡完成，成功: {success_count}/{len(self.users)}")
            return success_count > 0
        except Exception as e:
            await self.cleanup_browser()
            await self.handle_error(e, "下班打卡")
            return False

    async def punch_out(self):
        """执行下班打卡（兼容性方法）"""
        success, message = await self.start_punch_operation("punch_out")
        if success:
            # 等待操作完成
            if self.operation_task:
                return await self.operation_task
        return False


    def cleanup(self):
        """清理资源"""
        # 保存当前的定时任务到文件
        scheduled_jobs = schedule.get_jobs()
        self.task_manager.clear_tasks()
        for job in scheduled_jobs:
            if "punch_out" in str(job.job_func):
                next_run = job.next_run
                if next_run:
                    time_str = next_run.strftime("%H:%M")
                    self.task_manager.add_task('punch_out', time_str)

    async def restart_program(self):
        """重启程序"""
        try:
            await self.send_notification("系统状态", "开始执行程序重启...")

            # 清理资源
            self.cleanup()

            # 使用 Python 执行新的程序实例
            python_executable = sys.executable
            os.execl(python_executable, python_executable, *sys.argv)

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

            # 如果不是工作日，不进行检查
            if not is_workday(current_date):
                return

            # 检查是否是新的一天，如果是则重置提醒状态
            if self.notification_sent_today['last_check_date'] != current_date:
                self.notification_sent_today = {
                    'punch_in_reminder': False,
                    'punch_out_reminder': False,
                    'last_check_date': current_date
                }
                logging.info(f"新的一天开始，重置打卡提醒状态: {current_date}")

            # 重置昨天的打卡记录
            if self.today_punch_records['punch_in_time'] and \
               self.today_punch_records['punch_in_time'].date() < current_date:
                self.today_punch_records = {
                    'punch_in_time': None,
                    'punch_out_time': None
                }
                logging.info(f"重置昨天的打卡记录")

            # 检查上班打卡（只在未发送过提醒时发送）
            if (not self.today_punch_records['punch_in_time'] and
                not self.notification_sent_today['punch_in_reminder'] and
                current_time.time() > datetime.strptime(self.work_start_time, "%H:%M").time()):

                await self.send_notification(
                    "打卡提醒",
                    "⚠️ 今日未检测到上班打卡记录，请及时补卡！"
                )
                self.notification_sent_today['punch_in_reminder'] = True
                logging.info(f"已发送上班打卡提醒，标记为已发送")

            # 检查下班打卡（只在未发送过提醒时发送）
            if (self.today_punch_records['punch_in_time'] and
                not self.today_punch_records['punch_out_time'] and
                not self.notification_sent_today['punch_out_reminder'] and
                current_time.time() > datetime.strptime("18:00", "%H:%M").time()):

                await self.send_notification(
                    "打卡提醒",
                    "⚠️ 今日未检测到下班打卡记录，请及时补卡！"
                )
                self.notification_sent_today['punch_out_reminder'] = True
                logging.info(f"已发送下班打卡提醒，标记为已发送")

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

    async def get_punch_records_from_page(self):
        """从页面识别今日打卡记录"""
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
                        self.today_punch_records['punch_in_time'] = datetime.strptime(punch_in_time, '%H:%M:%S')
                        self.punch_record_manager.update_record(today_str, "上班", punch_in_time)
                        logging.info(f"成功更新今日上班打卡记录: {punch_in_time}")
                    except Exception as e:
                        logging.error(f"更新上班打卡记录时出错: {str(e)}")

                if punch_out_time:
                    try:
                        self.today_punch_records['punch_out_time'] = datetime.strptime(punch_out_time, '%H:%M:%S')
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

            # 异步发送邮件
            self.email_service.send_email_async(
                subject=subject,
                body=body,
                image_path=attachment_path,
                send_to_all=send_to_all,
                callback=email_callback
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
            records_found = await self.get_punch_records_from_page()
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
