import schedule
import time
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import pyperclip
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import sys
import logging
from logging.handlers import RotatingFileHandler
import traceback
import psutil
import subprocess
from chinese_calendar import is_workday, is_holiday
from tasks import TaskManager
from punch_records import PunchRecordManager
import telegram
import re
import pytesseract
from PIL import Image

# 图像处理和计算机视觉
import cv2
import numpy as np

# GUI自动化
import pyautogui

# Windows API
import win32gui
import win32con
import win32api

# 导入重构后的模块
from email_service import email_service
from browser_automation import browser_controller
from image_recognition import image_recognizer

# 加载环境变量
load_dotenv()

class WatchdogManager:
    """看门狗管理器，负责进程监控和自动重启"""
    
    def __init__(self):
        self.restart_count = 0
        self.max_restarts = 5
        self.restart_interval = 3600  # 1小时
        self.last_restart = datetime.now()
        self.monitoring = False
        self.monitor_task = None
        
    def is_process_running(self, process_name="python"):
        """检查指定进程是否在运行"""
        current_pid = os.getpid()
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # 跳过当前进程
                if proc.info['pid'] == current_pid:
                    continue
                    
                if proc.info['name'] == process_name or \
                   (proc.info['cmdline'] and 'main.py' in proc.info['cmdline']):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return False
    
    def start_main_program(self):
        """启动主程序"""
        try:
            # 使用 Python 解释器启动主程序
            subprocess.Popen([sys.executable, 'main.py'])
            logging.info("主程序已启动")
            return True
        except Exception as e:
            logging.error(f"启动主程序失败: {str(e)}")
            return False
    
    async def monitor_system_resources(self):
        """监控系统资源使用情况"""
        while self.monitoring:
            try:
                # 检查系统资源使用情况
                memory_percent = psutil.virtual_memory().percent
                cpu_percent = psutil.cpu_percent()
                
                if memory_percent > 90 or cpu_percent > 90:
                    logging.warning(f"系统资源使用率过高 (内存: {memory_percent}%, CPU: {cpu_percent}%)")
                
                await asyncio.sleep(60)  # 每分钟检查一次
                
            except Exception as e:
                logging.error(f"资源监控发生错误: {str(e)}")
                await asyncio.sleep(5)
    
    def start_monitoring(self):
        """启动监控"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_task = asyncio.create_task(self.monitor_system_resources())
            logging.info("看门狗监控已启动")
    
    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            logging.info("看门狗监控已停止")

class TelegramBot:
    def __init__(self, chat_id):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id
        self.app = None
        self.log_file = 'attendance_system.log'
        self.attendance_system = None
        # 添加重试相关配置
        self.max_retries = 3
        self.retry_delay = 5  # 秒
        self.connection_error_count = 0
        self.max_connection_errors = 10
        self.last_connection_error = None
        # 添加轮询监控
        self.last_update_time = datetime.now()
        self.update_timeout = 600  # 10分钟无更新则重启轮询
        self.polling_task = None
        self.is_polling = False
        # 添加连接池配置
        self.connection_pool_size = 100  # 增加连接池大小
        self.connection_timeout = 30
        self.pool_timeout = 30
        self.read_timeout = 30
        self.write_timeout = 30
        self.connect_timeout = 30
        # 添加设置定时打卡的状态变量
        self.setting_time_state = {}  # 用于存储用户的设置状态
        self.setting_time_timer = {}  # 用于存储设置超时计时器


    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/start命令"""
        await update.message.reply_text(
            "欢迎使用打卡机器人！\n"
            "支持的命令：\n"
            "/punch_in - 上班打卡\n"
            "/punch_out - 下班打卡\n"
            "/status - 查看状态（包含看门狗状态）\n"
            "/errors - 查看最近错误日志\n"
            "/kill - 查看并管理定时任务\n"
            "/kill <任务ID> - 直接删除指定任务\n\n"
            "🛡️ 看门狗功能已内置启用"
        )

    async def punch_in_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理上班打卡命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return
        
        # 检查命令发送时间是否超过5分钟
        command_time = update.message.date
        current_time = datetime.now(command_time.tzinfo)  # 使用相同时区
        time_diff = (current_time - command_time).total_seconds() / 60  # 转换为分钟
        
        if time_diff > 5:
            await update.message.reply_text(f"命令已过期（发送时间：{command_time.strftime('%H:%M:%S')}）\n为确保安全，超过5分钟的命令将不会执行。")
            return
        
        await update.message.reply_text("正在执行上班打卡...")
        await self.attendance_system.punch_in()
        # 打卡完成后返回状态
        await self.status_command(update, context)

    async def punch_out_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理下班打卡命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return
        
        # 检查命令发送时间是否超过5分钟
        command_time = update.message.date
        current_time = datetime.now(command_time.tzinfo)  # 使用相同时区
        time_diff = (current_time - command_time).total_seconds() / 60  # 转换为分钟
        
        if time_diff > 5:
            await update.message.reply_text(f"命令已过期（发送时间：{command_time.strftime('%H:%M:%S')}）\n为确保安全，超过5分钟的命令将不会执行。")
            return
        
        await update.message.reply_text("正在执行下班打卡...")
        await self.attendance_system.punch_out()
        # 打卡完成后返回状态
        await self.status_command(update, context)

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理状态查询命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return
        
        try:
            # 获取系统状态信息
            current_time = datetime.now()
            
            # 获取今日打卡记录
            punch_in_time = self.attendance_system.today_punch_records['punch_in_time']
            punch_out_time = self.attendance_system.today_punch_records['punch_out_time']
            
            # 获取系统资源使用情况
            memory = psutil.virtual_memory()
            cpu_percent = psutil.cpu_percent()
            
            # 获取程序运行时间
            process = psutil.Process()
            uptime = datetime.now() - datetime.fromtimestamp(process.create_time())
            hours, remainder = divmod(uptime.total_seconds(), 3600)
            minutes, seconds = divmod(remainder, 60)
            
            # 检查是否在工作时间内和日期类型
            is_work_time = self.attendance_system.is_work_time(current_time)
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
                
                "📍 今日打卡记录\n"
                f"上班打卡：{'✅ ' + punch_in_time.strftime('%H:%M:%S') if punch_in_time else '❌ 未打卡'}\n"
                f"下班打卡：{'✅ ' + punch_out_time.strftime('%H:%M:%S') if punch_out_time else '❌ 未打卡'}\n\n"
                
                "⚙️ 系统信息\n"
                f"运行时长：{int(hours)}小时{int(minutes)}分钟\n"
                f"内存使用：{memory.percent}%\n"
                f"CPU使用：{cpu_percent}%\n"
                f"心跳状态：{'🟢 正常' if self.attendance_system.heartbeat_miss_count == 0 else '🟡 警告'}\n\n"
                
                "📋 配置信息\n"
                f"上班时间：{self.attendance_system.work_start_time}\n"
                f"下班时间：{self.attendance_system.work_end_time}\n"
                f"迟到阈值：{self.attendance_system.late_threshold}分钟\n"
                f"早退阈值：{self.attendance_system.early_leave_threshold}分钟\n"
                f"看门狗状态：{'🟢 运行中' if hasattr(self.attendance_system, 'watchdog') and self.attendance_system.watchdog.monitoring else '🔴 未启用'}\n"
            )
            
            # 获取定时任务列表
            saved_tasks = self.attendance_system.task_manager.get_tasks()
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
            
            await update.message.reply_text(status_text)
            
        except Exception as e:
            error_msg = f"获取状态信息时发生错误: {str(e)}"
            logging.error(error_msg)
            await update.message.reply_text(error_msg)

    async def get_recent_errors(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/errors命令，获取最近的错误日志"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return
            
        try:
            # 获取页码参数，默认为第1页
            page = 1
            if context.args and len(context.args) > 0:
                try:
                    page = int(context.args[0])
                except ValueError:
                    page = 1
            
            # 确保日志文件路径正确
            log_file = 'attendance_system.log'
            if not os.path.exists(log_file):
                log_file = os.path.join('logs', 'attendance_system.log')
                if not os.path.exists(log_file):
                    await update.message.reply_text("找不到日志文件，请检查文件是否存在")
                    return
            
            # 尝试不同的编码方式读取日志
            encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1']
            logs = []
            
            for encoding in encodings:
                try:
                    with open(log_file, 'r', encoding=encoding) as f:
                        logs = f.readlines()
                    break  # 如果成功读取，跳出循环
                except UnicodeDecodeError:
                    continue  # 如果当前编码失败，尝试下一个
                except Exception as e:
                    logging.error(f"读取日志文件时出错: {str(e)}")
                    continue
            
            if not logs:
                await update.message.reply_text("无法读取日志文件，请检查文件是否存在或权限是否正确")
                return
                
            # 筛选出ERROR和CRITICAL级别的日志
            error_logs = [log for log in logs if 'ERROR' in log or 'CRITICAL' in log]
            
            if not error_logs:
                await update.message.reply_text("没有发现错误日志")
                return
                
            # 只保留最近的50条错误日志（按时间正序）
            recent_logs = error_logs[-50:]
            
            # 对日志进行分类和格式化
            formatted_logs = []
            current_error_group = None
            current_error_lines = []
            
            for log_line in recent_logs:
                # 检查是否是新的错误开始
                if ('ERROR' in log_line or 'CRITICAL' in log_line) and (' - ERROR - ' in log_line or ' - CRITICAL - ' in log_line):
                    # 如果有之前的错误组，先添加到结果中
                    if current_error_group and current_error_lines:
                        formatted_logs.append({
                            'timestamp': current_error_group,
                            'content': current_error_lines
                        })
                    
                    # 提取时间戳作为新的错误组
                    timestamp_part = log_line.split(' - ERROR')[0].strip()
                    if ' - CRITICAL' in log_line:
                        timestamp_part = log_line.split(' - CRITICAL')[0].strip()
                    
                    current_error_group = timestamp_part
                    current_error_lines = [log_line.split(' - ERROR - ')[-1].strip() if ' - ERROR - ' in log_line 
                                          else log_line.split(' - CRITICAL - ')[-1].strip()]
                else:
                    # 继续添加到当前错误组
                    if current_error_lines:
                        current_error_lines.append(log_line.strip())
            
            # 添加最后一组
            if current_error_group and current_error_lines:
                formatted_logs.append({
                    'timestamp': current_error_group,
                    'content': current_error_lines
                })
            
            # 反转列表，使最近的错误显示在最前面
            formatted_logs.reverse()
            
            # 分页处理
            items_per_page = 5  # 每页显示5个错误组
            total_pages = (len(formatted_logs) + items_per_page - 1) // items_per_page
            
            # 确保页码在有效范围内
            if page < 1:
                page = 1
            if page > total_pages:
                page = total_pages
            
            # 计算当前页的数据范围
            start_idx = (page - 1) * items_per_page
            end_idx = min(start_idx + items_per_page, len(formatted_logs))
            current_page_logs = formatted_logs[start_idx:end_idx]
            
            # 构建格式化的消息
            log_message = f"📋 *最近的错误日志* (第{page}/{total_pages}页)\n\n"
            
            for i, log_group in enumerate(current_page_logs):
                # 添加分隔线（除了第一组）
                if i > 0:
                    log_message += "\n" + "—" * 30 + "\n\n"
                
                # 添加时间戳和错误内容
                log_message += f"⏱️ *{log_group['timestamp']}*\n"
                log_message += f"❌ {log_group['content'][0]}\n"
                
                # 添加额外的错误详情（如果有）
                if len(log_group['content']) > 1:
                    for detail in log_group['content'][1:]:
                        if detail.strip():  # 只添加非空行
                            log_message += f"   {detail}\n"
            
            # 创建翻页按钮
            keyboard = []
            buttons = []
            
            # 添加上一页按钮
            if page > 1:
                buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"errors_page_{page-1}"))
            
            # 添加下一页按钮
            if page < total_pages:
                buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"errors_page_{page+1}"))
            
            if buttons:
                keyboard.append(buttons)
            
            reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
            
            # 发送消息
            await update.message.reply_text(log_message, parse_mode='Markdown', reply_markup=reply_markup)
        except Exception as e:
            error_msg = f"获取错误日志时发生异常: {str(e)}"
            logging.error(error_msg)
            await update.message.reply_text(f"获取错误日志失败: {str(e)}")

    async def send_message(self, title, content):
        """发送Telegram消息"""
        if not self.app:
            return False
            
        for retry in range(self.max_retries):
            try:
                message = f"{title}\n\n{content}"
                await self.app.bot.send_message(chat_id=self.chat_id, text=message)
                # 成功发送后重置错误计数
                self.connection_error_count = 0
                self.last_connection_error = None
                return True
            except telegram.error.NetworkError as e:
                self.connection_error_count += 1
                self.last_connection_error = datetime.now()
                error_msg = f"发送Telegram消息时发生网络错误 (尝试 {retry + 1}/{self.max_retries}): {str(e)}"
                print(error_msg)
                logging.error(error_msg)
                
                # 如果不是最后一次重试，等待后继续
                if retry < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (retry + 1))
                    continue
                    
                # 如果错误次数过多，可能需要重启程序
                if self.connection_error_count >= self.max_connection_errors:
                    error_msg = "网络错误次数过多，准备重启程序..."
                    print(error_msg)
                    logging.critical(error_msg)
                    if self.attendance_system:
                        await self.attendance_system.restart_program()
                    return False
            except Exception as e:
                error_msg = f"发送Telegram消息时发生其他错误: {str(e)}"
                print(error_msg)
                logging.error(error_msg)
                if retry < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (retry + 1))
                    continue
                return False
                
        return False

    async def kill_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/kill命令，用于删除定时任务"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        try:
            # 检查是否有参数
            if context.args:
                # 直接删除指定ID的任务
                try:
                    task_id = int(context.args[0])
                    await self._delete_task(task_id, update.message)
                except ValueError:
                    await update.message.reply_text("任务ID必须是数字")
                return

            # 如果没有参数，显示所有任务和删除按钮
            saved_tasks = self.attendance_system.task_manager.get_tasks()
            if not saved_tasks:
                await update.message.reply_text(
                    "暂无定时任务\n"
                    "您可以通过以下方式创建定时任务：\n"
                    "1. 执行下班打卡时，如果未满足工作时长，系统会自动创建定时任务\n"
                    "2. 等待系统自动检测并创建定时任务"
                )
                return

            # 创建任务列表和按钮
            keyboard = []
            message_text = "当前的定时任务列表：\n\n"
            for task in saved_tasks:
                if task['type'] == 'punch_out':
                    next_run = datetime.strptime(task['scheduled_time'], "%H:%M").replace(
                        year=datetime.now().year,
                        month=datetime.now().month,
                        day=datetime.now().day
                    )
                    # 如果时间已过，显示明天的时间
                    if next_run < datetime.now():
                        next_run = next_run + timedelta(days=1)
                    message_text += f"➤ [任务 #{task['id']}] 下班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
                    keyboard.append([
                        InlineKeyboardButton(
                            f"删除任务 #{task['id']}",
                            callback_data=f"kill_{task['id']}"
                        )
                    ])
                elif task['type'] == 'punch_in':
                    next_run = datetime.strptime(task['scheduled_time'], "%H:%M").replace(
                        year=datetime.now().year,
                        month=datetime.now().month,
                        day=datetime.now().day
                    )
                    # 如果时间已过，显示明天的时间
                    if next_run < datetime.now():
                        next_run = next_run + timedelta(days=1)
                    message_text += f"➤ [任务 #{task['id']}] 上班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
                    keyboard.append([
                        InlineKeyboardButton(
                            f"删除任务 #{task['id']}",
                            callback_data=f"kill_{task['id']}"
                        )
                    ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(message_text, reply_markup=reply_markup)

        except Exception as e:
            error_msg = f"处理删除任务命令时发生错误: {str(e)}"
            logging.error(error_msg)
            await update.message.reply_text(error_msg)

    async def _delete_task(self, task_id, message):
        """删除指定ID的任务"""
        task = self.attendance_system.task_manager.get_task_by_id(task_id)
        if not task:
            await message.reply_text(f"未找到ID为 {task_id} 的任务")
            return

        if self.attendance_system.task_manager.remove_task_by_id(task_id):
            # 清除schedule中的任务
            schedule.clear()
            
            # 重新加载剩余的任务
            saved_tasks = self.attendance_system.task_manager.get_tasks()
            for saved_task in saved_tasks:
                if saved_task['type'] == 'punch_out':
                    async def retry_punch_out_job():
                        await self.attendance_system.punch_out()
                    schedule.every().day.at(saved_task['scheduled_time']).do(retry_punch_out_job)
                elif saved_task['type'] == 'punch_in':
                    async def retry_punch_in_job():
                        await self.attendance_system.punch_in()
                    schedule.every().day.at(saved_task['scheduled_time']).do(retry_punch_in_job)
            
            await message.reply_text(
                f"已删除任务:\n"
                f"ID: {task['id']}\n"
                f"类型: {task['type']}\n"
                f"计划时间: {task['scheduled_time']}\n"
                f"创建时间: {task['created_at']}"
            )
        else:
            await message.reply_text("删除任务失败")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理按钮回调"""
        query = update.callback_query
        await query.answer()  # 响应按钮点击

        try:
            if str(query.message.chat_id) != self.chat_id:
                await query.message.reply_text("您没有权限使用此机器人")
                return

            # 解析回调数据
            if query.data.startswith('kill_'):
                task_id = int(query.data.split('_')[1])
                task = self.attendance_system.task_manager.get_task_by_id(task_id)
                
                if not task:
                    await query.message.reply_text(f"未找到ID为 {task_id} 的任务")
                    return

                if self.attendance_system.task_manager.remove_task_by_id(task_id):
                    # 清除schedule中的任务
                    schedule.clear()
                    
                    # 重新加载剩余的任务
                    saved_tasks = self.attendance_system.task_manager.get_tasks()
                    for saved_task in saved_tasks:
                        if saved_task['type'] == 'punch_out':
                            async def retry_punch_out_job():
                                await self.attendance_system.punch_out()
                            schedule.every().day.at(saved_task['scheduled_time']).do(retry_punch_out_job)
                        elif saved_task['type'] == 'punch_in':
                            async def retry_punch_in_job():
                                await self.attendance_system.punch_in()
                            schedule.every().day.at(saved_task['scheduled_time']).do(retry_punch_in_job)

                    # 发送删除成功的消息
                    await query.message.reply_text(
                        f"✅ 已删除任务:\n"
                        f"ID: {task['id']}\n"
                        f"类型: {task['type']}\n"
                        f"计划时间: {task['scheduled_time']}\n"
                        f"创建时间: {task['created_at']}"
                    )
                    
                    # 更新任务列表消息
                    if not saved_tasks:
                        await query.message.edit_text("所有任务已删除")
                        return

                    keyboard = []
                    message_text = "当前的定时任务列表：\n\n"
                    for remaining_task in saved_tasks:
                        if remaining_task['type'] == 'punch_out':
                            next_run = datetime.strptime(remaining_task['scheduled_time'], "%H:%M").replace(
                                year=datetime.now().year,
                                month=datetime.now().month,
                                day=datetime.now().day
                            )
                            # 如果时间已过，显示明天的时间
                            if next_run < datetime.now():
                                next_run = next_run + timedelta(days=1)
                            message_text += f"➤ [任务 #{remaining_task['id']}] 下班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
                            keyboard.append([
                                InlineKeyboardButton(
                                    f"删除任务 #{remaining_task['id']}",
                                    callback_data=f"kill_{remaining_task['id']}"
                                )
                            ])
                        elif remaining_task['type'] == 'punch_in':
                            next_run = datetime.strptime(remaining_task['scheduled_time'], "%H:%M").replace(
                                year=datetime.now().year,
                                month=datetime.now().month,
                                day=datetime.now().day
                            )
                            # 如果时间已过，显示明天的时间
                            if next_run < datetime.now():
                                next_run = next_run + timedelta(days=1)
                            message_text += f"➤ [任务 #{remaining_task['id']}] 上班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
                            keyboard.append([
                                InlineKeyboardButton(
                                    f"删除任务 #{remaining_task['id']}",
                                    callback_data=f"kill_{remaining_task['id']}"
                                )
                            ])

                    if keyboard:
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await query.message.edit_text(message_text, reply_markup=reply_markup)
                    else:
                        await query.message.edit_text("所有任务已删除")
                else:
                    await query.message.reply_text("❌ 删除任务失败")
            elif query.data.startswith('settime_type_'):
                punch_type = query.data.split('_')[-1]
                self.setting_time_state[self.chat_id]['type'] = punch_type
                
                # 创建设置模式选择按钮
                keyboard = [
                    [
                        InlineKeyboardButton("延时执行", callback_data=f'settime_mode_delay_{punch_type}'),
                        InlineKeyboardButton("指定时间", callback_data=f'settime_mode_specific_{punch_type}')
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.message.edit_text(
                    f"请选择设置模式：",
                    reply_markup=reply_markup
                )
                
            elif query.data.startswith('settime_mode_'):
                parts = query.data.split('_')
                mode = parts[2]
                punch_type = parts[3]
                
                self.setting_time_state[self.chat_id].update({
                    'mode': mode,
                    'step': 'input_delay' if mode == 'delay' else 'input_hour'
                })
                
                if mode == 'delay':
                    await query.message.edit_text("请输入要延迟的分钟数：")
                else:
                    await query.message.edit_text("请输入小时数（0-23）：")

            # 处理错误日志翻页
            elif query.data.startswith('errors_page_'):
                page = int(query.data.split('_')[-1])
                # 使用命令处理器重新获取指定页的错误日志
                context.args = [str(page)]
                await self.get_recent_errors(Update(update_id=update.callback_query.id, message=query.message), context)
                # 删除原消息
                await query.message.delete()
                
        except Exception as e:
            error_msg = f"处理按钮回调时发生错误: {str(e)}"
            logging.error(error_msg)
            await query.message.reply_text(error_msg)

    async def start_polling(self):
        """启动消息轮询"""
        if self.is_polling:
            return
            
        self.is_polling = True
        try:
            # 使用更大的连接池和更长的超时时间
            await self.app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                poll_interval=1.0,
                timeout=self.connection_timeout,
                read_timeout=self.read_timeout,
                write_timeout=self.write_timeout,
                connect_timeout=self.connect_timeout,
                pool_timeout=self.pool_timeout
            )
            logging.info("Telegram Bot 轮询已启动")
        except Exception as e:
            self.is_polling = False
            logging.error(f"启动轮询时发生错误: {str(e)}")
            # 尝试清理连接池
            try:
                await self.cleanup_connections()
            except Exception as cleanup_error:
                logging.error(f"清理连接池时发生错误: {str(cleanup_error)}")
            raise

    async def cleanup_connections(self):
        """清理连接池"""
        try:
            if self.app and hasattr(self.app, 'bot') and hasattr(self.app.bot, 'request'):
                if hasattr(self.app.bot.request, '_client'):
                    try:
                        await self.app.bot.request._client.aclose()
                    except Exception as e:
                        logging.warning(f"关闭客户端连接时发生错误: {str(e)}")
            
            if self.app and hasattr(self.app, 'updater'):
                if hasattr(self.app.updater, '_last_update_id'):
                    try:
                        self.app.updater._last_update_id = None
                    except Exception as e:
                        logging.warning(f"重置last_update_id时发生错误: {str(e)}")
        except Exception as e:
            logging.error(f"清理连接时发生错误: {str(e)}")

    async def stop_polling(self):
        """停止消息轮询"""
        if not self.is_polling:
            return
            
        try:
            # 检查updater是否存在且正在运行
            if self.app and self.app.updater:
                try:
                    await self.app.updater.stop()
                except Exception as e:
                    logging.warning(f"停止updater时发生异常，可能已经不在运行状态: {str(e)}")
            
            self.is_polling = False
            # 清理连接
            await self.cleanup_connections()
            logging.info("Telegram Bot 轮询已停止")
        except Exception as e:
            self.is_polling = False  # 确保状态正确
            logging.error(f"停止轮询时发生错误: {str(e)}")

    async def restart_polling(self):
        """重启消息轮询"""
        logging.info("正在重启 Telegram Bot 轮询...")
        await self.stop_polling()
        
        # 完全关闭和清理旧的应用实例
        try:
            if self.app:
                # 停止和关闭应用
                try:
                    await self.app.stop()
                except Exception as e:
                    logging.warning(f"停止应用时发生错误，将继续执行: {str(e)}")
                    
                try:
                    await self.app.shutdown()
                except Exception as e:
                    logging.warning(f"关闭应用时发生错误，将继续执行: {str(e)}")
                
                # 清理连接
                await self.cleanup_connections()
                
                # 清空引用
                self.app = None
                
            await asyncio.sleep(5)  # 等待5秒后重启
            
            # 重新创建应用实例
            self.app = Application.builder().token(self.token).pool_timeout(self.pool_timeout).connect_timeout(self.connect_timeout).read_timeout(self.read_timeout).write_timeout(self.write_timeout).connection_pool_size(self.connection_pool_size).get_updates_connection_pool_size(self.connection_pool_size).build()
            
            # 重新注册处理器
            self.app.add_handler(CommandHandler('start', self.start_command))
            self.app.add_handler(CommandHandler('punch_in', self.punch_in_command))
            self.app.add_handler(CommandHandler('punch_out', self.punch_out_command))
            self.app.add_handler(CommandHandler('status', self.status_command))
            self.app.add_handler(CommandHandler('errors', self.get_recent_errors))
            self.app.add_handler(CommandHandler('kill', self.kill_command))
            self.app.add_handler(CommandHandler('set_time', self.settime_command))
            self.app.add_handler(CallbackQueryHandler(self.button_callback))
            # 注册消息处理器，必须在其他处理器之后添加
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
            
            # 添加更新时间记录处理器
            async def update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                self.last_update_time = datetime.now()
                self.connection_error_count = 0  # 重置错误计数
            
            self.app.add_handler(MessageHandler(filters.ALL, update_handler))
            
            # 初始化并启动
            await self.app.initialize()
            await self.app.start()
            await self.start_polling()
            
        except Exception as e:
            logging.error(f"重新创建应用实例时发生错误: {str(e)}")
            # 不抛出异常，允许程序继续运行
            
        self.last_update_time = datetime.now()
        logging.info("Telegram Bot 轮询重启完成")

    async def monitor_connection(self):
        """监控连接状态"""
        while True:
            try:
                current_time = datetime.now()
                
                # 检查最后更新时间
                if self.last_update_time:
                    time_since_last_update = (current_time - self.last_update_time).total_seconds()
                    
                    if time_since_last_update > self.update_timeout:
                        logging.warning(f"已经 {time_since_last_update:.0f} 秒没有收到更新，尝试重启轮询...")
                        
                        # 尝试重启轮询
                        try:
                            await self.restart_polling()
                        except Exception as e:
                            logging.error(f"重启轮询失败: {str(e)}")
                            
                            # 如果重启失败，尝试完全重新创建应用实例
                            try:
                                if self.app:
                                    try:
                                        await self.app.stop()
                                        await self.app.shutdown()
                                    except Exception as stop_e:
                                        logging.warning(f"停止旧应用实例时发生错误: {str(stop_e)}")
                                    
                                    await self.cleanup_connections()
                                    self.app = None
                                
                                await asyncio.sleep(5)  # 等待5秒
                                
                                # 尝试创建新的应用实例
                                self.app = Application.builder().token(self.token).pool_timeout(self.pool_timeout).connect_timeout(self.connect_timeout).read_timeout(self.read_timeout).write_timeout(self.write_timeout).connection_pool_size(self.connection_pool_size).get_updates_connection_pool_size(self.connection_pool_size).build()
                                
                                # 重新注册处理器
                                self.app.add_handler(CommandHandler('start', self.start_command))
                                self.app.add_handler(CommandHandler('punch_in', self.punch_in_command))
                                self.app.add_handler(CommandHandler('punch_out', self.punch_out_command))
                                self.app.add_handler(CommandHandler('status', self.status_command))
                                self.app.add_handler(CommandHandler('errors', self.get_recent_errors))
                                self.app.add_handler(CommandHandler('kill', self.kill_command))
                                self.app.add_handler(CommandHandler('set_time', self.settime_command))
                                self.app.add_handler(CallbackQueryHandler(self.button_callback))
                                # 注册消息处理器，必须在其他处理器之后添加
                                self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
                                
                                # 添加更新时间记录处理器
                                async def update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                                    self.last_update_time = datetime.now()
                                    self.connection_error_count = 0  # 重置错误计数
                                
                                self.app.add_handler(MessageHandler(filters.ALL, update_handler))
                                
                                # 初始化并启动
                                await self.app.initialize()
                                await self.app.start()
                                await self.start_polling()
                            except Exception as init_e:
                                logging.error(f"初始化应用实例失败: {str(init_e)}")
                
                await asyncio.sleep(60)
            except Exception as e:
                logging.error(f"监控连接时发生错误: {str(e)}")
                await asyncio.sleep(60)

    def run(self, attendance_system):
        """运行机器人"""
        self.attendance_system = attendance_system
        
        # 配置应用程序，添加连接池和超时设置
        self.app = Application.builder().token(self.token).pool_timeout(self.pool_timeout).connect_timeout(self.connect_timeout).read_timeout(self.read_timeout).write_timeout(self.write_timeout).connection_pool_size(self.connection_pool_size).get_updates_connection_pool_size(self.connection_pool_size).build()
        
        # 注册命令处理器
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("punch_in", self.punch_in_command))
        self.app.add_handler(CommandHandler("punch_out", self.punch_out_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("errors", self.get_recent_errors))
        self.app.add_handler(CommandHandler("kill", self.kill_command))
        self.app.add_handler(CommandHandler("set_time", self.settime_command))  # 修改命令名称
        
        # 注册按钮回调处理器
        self.app.add_handler(CallbackQueryHandler(self.button_callback))
        
        # 注册消息处理器
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))  # 添加消息处理器
        
        # 添加更新时间记录
        async def update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            self.last_update_time = datetime.now()
            self.connection_error_count = 0  # 重置错误计数
            
        self.app.add_handler(MessageHandler(filters.ALL, update_handler))
        
        # 启动机器人
        self.app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            poll_interval=1.0,
            timeout=self.connection_timeout,
            read_timeout=self.read_timeout,
            write_timeout=self.write_timeout,
            connect_timeout=self.connect_timeout,
            pool_timeout=self.pool_timeout
        )

    async def settime_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/settime命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        # 创建打卡类型选择按钮
        keyboard = [
            [
                InlineKeyboardButton("设置上班时间", callback_data='settime_type_in'),
                InlineKeyboardButton("设置下班时间", callback_data='settime_type_out')
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # 初始化状态
        self.setting_time_state[self.chat_id] = {
            'step': 'select_type',
            'type': None,
            'mode': None,
            'hour': None,
            'minute': None
        }
        
        # 设置1分钟超时
        if self.chat_id in self.setting_time_timer:
            self.setting_time_timer[self.chat_id].cancel()
        self.setting_time_timer[self.chat_id] = asyncio.create_task(self._cancel_settime_timeout(self.chat_id))

        await update.message.reply_text(
            "请选择要设置的打卡类型：",
            reply_markup=reply_markup
        )

    async def _cancel_settime_timeout(self, chat_id):
        """一分钟后取消设置时间的状态"""
        await asyncio.sleep(60)
        if chat_id in self.setting_time_state:
            del self.setting_time_state[chat_id]
            await self.send_message("设置超时", "由于超过1分钟没有操作，设置已取消")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理文本消息"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        if self.chat_id not in self.setting_time_state:
            return

        # 重置超时计时器
        if self.chat_id in self.setting_time_timer:
            self.setting_time_timer[self.chat_id].cancel()
        self.setting_time_timer[self.chat_id] = asyncio.create_task(self._cancel_settime_timeout(self.chat_id))

        state = self.setting_time_state[self.chat_id]
        text = update.message.text

        if state['step'] == 'input_delay':
            try:
                delay_minutes = int(text)
                if delay_minutes <= 0:
                    await update.message.reply_text("请输入大于0的数字")
                    return
                
                # 计算目标时间
                target_time = datetime.now() + timedelta(minutes=delay_minutes)
                await self._schedule_punch(state['type'], target_time.hour, target_time.minute)
                del self.setting_time_state[self.chat_id]
                self.setting_time_timer[self.chat_id].cancel()
                
            except ValueError:
                await update.message.reply_text("请输入有效的数字")
                
        elif state['step'] == 'input_hour':
            try:
                hour = int(text)
                if 0 <= hour <= 23:
                    state['hour'] = hour
                    state['step'] = 'input_minute'
                    await update.message.reply_text("请输入分钟数（0-59）：")
                else:
                    await update.message.reply_text("请输入0-23之间的数字")
            except ValueError:
                await update.message.reply_text("请输入有效的数字")
                
        elif state['step'] == 'input_minute':
            try:
                minute = int(text)
                if 0 <= minute <= 59:
                    await self._schedule_punch(state['type'], state['hour'], minute)
                    del self.setting_time_state[self.chat_id]
                    self.setting_time_timer[self.chat_id].cancel()
                else:
                    await update.message.reply_text("请输入0-59之间的数字")
            except ValueError:
                await update.message.reply_text("请输入有效的数字")

    async def _schedule_punch(self, punch_type, hour, minute):
        """设置定时打卡任务"""
        time_str = f"{hour:02d}:{minute:02d}"
        target_time = datetime.strptime(time_str, "%H:%M").replace(
            year=datetime.now().year,
            month=datetime.now().month,
            day=datetime.now().day
        )
        
        # 如果设置的时间已经过去，就设置为明天的这个时间
        if target_time < datetime.now():
            target_time = target_time + timedelta(days=1)
        
        # 标准化punch_type
        if punch_type == "上班" or punch_type == "in":
            task_type = "punch_in"
            display_type = "上班"
        elif punch_type == "下班" or punch_type == "out":
            task_type = "punch_out"
            display_type = "下班"
        else:
            raise ValueError(f"无效的打卡类型: {punch_type}")
        
        # 删除已有的相同类型的定时任务
        saved_tasks = self.attendance_system.task_manager.get_tasks()
        for task in saved_tasks:
            if task['type'] == task_type:
                self.attendance_system.task_manager.remove_task_by_id(task['id'])
        
        # 清除schedule中的任务并重新加载
        schedule.clear()
        
        # 添加新任务
        task_id = self.attendance_system.task_manager.add_task(
            task_type=task_type,
            scheduled_time=time_str
        )
        
        if task_type == "punch_in":
            async def punch_in_job():
                await self.attendance_system.punch_in()
                # 执行完后删除任务
                self.attendance_system.task_manager.remove_task_by_id(task_id)
                schedule.clear()
            schedule.every().day.at(time_str).do(lambda: asyncio.create_task(punch_in_job()))
            await self.send_message("设置成功", f"已设置在 {target_time.strftime('%Y-%m-%d %H:%M')} 自动{display_type}打卡")
        else:
            async def punch_out_job():
                await self.attendance_system.punch_out()
                # 执行完后删除任务
                self.attendance_system.task_manager.remove_task_by_id(task_id)
                schedule.clear()
            schedule.every().day.at(time_str).do(lambda: asyncio.create_task(punch_out_job()))
            await self.send_message("设置成功", f"已设置在 {target_time.strftime('%Y-%m-%d %H:%M')} 自动{display_type}打卡")

    def close_browser(self):
        """通过识别关闭按钮关闭浏览器窗口"""
        try:
            # 检查attendance_system是否已初始化
            if not self.attendance_system:
                logging.error("AttendanceSystem未初始化，无法关闭浏览器")
                return False
                
            # 获取当前屏幕截图
            screen = self.attendance_system.take_screenshot()
            if screen is None:
                logging.error("关闭浏览器时无法获取屏幕截图")
                return False
            
            # 使用模板匹配查找关闭按钮
            logging.info("使用模板匹配查找关闭按钮")
            close_button_loc = self.attendance_system.find_element_by_image('templates/close_button.png', threshold=0.7)
            if close_button_loc:
                logging.info(f"找到关闭按钮，位置: {close_button_loc}")
                self.attendance_system.click_position(*close_button_loc)
                time.sleep(1)  # 等待窗口关闭
                
                # 验证浏览器是否已关闭
                new_screen = self.attendance_system.take_screenshot()
                if new_screen is not None:
                    # 比较两个截图，检查是否有变化
                    diff = cv2.absdiff(screen, new_screen)
                    non_zero_count = np.count_nonzero(diff)
                    if non_zero_count > 10000:  # 如果有足够的差异，认为浏览器已关闭
                        logging.info("浏览器窗口已关闭")
                        return True
                else:
                    logging.info("浏览器窗口已关闭")
                    return True
            else:
                logging.info("未找到关闭按钮，尝试备选方法")
                
                # 备选方法1：尝试点击右上角固定位置
                height, width = screen.shape[:2]
                logging.info("尝试点击浏览器右上角固定位置")
                self.attendance_system.click_position(width - 20, 20)
                time.sleep(1)  # 等待窗口关闭
                
                # 验证浏览器是否已关闭
                new_screen = self.attendance_system.take_screenshot()
                if new_screen is not None:
                    diff = cv2.absdiff(screen, new_screen)
                    non_zero_count = np.count_nonzero(diff)
                    if non_zero_count > 10000:
                        logging.info("浏览器窗口已关闭")
                        return True
                else:
                    logging.info("浏览器窗口已关闭")
                    return True
                
                # 备选方法2：使用win32gui关闭
                logging.info("尝试使用win32gui关闭浏览器")
                if self.attendance_system:
                    hwnd = self.attendance_system.get_browser_window()
                    if hwnd:
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        time.sleep(1)  # 等待窗口关闭
                        return True
            
            # 如果所有方法都失败，返回失败
            logging.error("所有关闭浏览器的方法都失败")
            return False
        except Exception as e:
            logging.error(f"关闭浏览器窗口时发生错误: {str(e)}")
            # 尝试使用win32gui作为最后的备选方案
            try:
                if self.attendance_system:
                    hwnd = self.attendance_system.get_browser_window()
                    if hwnd:
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        time.sleep(1)  # 等待窗口关闭
                        return True
                return False
            except Exception as e2:
                logging.error(f"备选关闭方法也失败: {str(e2)}")
                return False

class AttendanceSystem:
    def __init__(self):
        # 设置pytesseract路径
        pytesseract.pytesseract.tesseract_cmd = os.getenv('TESSERACT_PATH', r'C:\Program Files\Tesseract-OCR\tesseract.exe')
        
        # 配置多用户信息
        self.users = [
            {
                'username': os.getenv('LOGIN_USERNAME'),
                'password': os.getenv('LOGIN_PASSWORD'),
                'punch_records': {
                    'punch_in_time': None,
                    'punch_out_time': None
                }
            },
            {
                'username': os.getenv('LOGIN_USERNAME2'),
                'password': os.getenv('LOGIN_PASSWORD2'),
                'punch_records': {
                    'punch_in_time': None,
                    'punch_out_time': None
                }
            }
        ]
        
        # 登录URL
        self.login_url = os.getenv('LOGIN_URL')
        
        # 创建Telegram机器人实例
        self.bot = TelegramBot(os.getenv('TELEGRAM_CHAT_ID'))
        
        # 创建看门狗管理器实例
        self.watchdog = WatchdogManager()
        
        # 截图保存路径
        self.screenshot_path = 'logs/temp_screenshot.png'
        
        # 添加重试次数配置
        self.max_retries = 3
        self.retry_interval = 5  # 秒
        
        # 浏览器窗口标题
        self.browser_title = "Microsoft Edge"
        
        # 安全位置图片路径
        self.safe_place_path = 'templates/safe_place.png'
        self.safe_place_path2 = 'templates/safe_place2.png'
        
        # 用于存储当前进度消息
        self.current_message = ""
        self.message_id = None
        
        # 添加心跳检测相关属性
        self.last_heartbeat = datetime.now()
        self.heartbeat_interval = 300  # 5分钟检测一次
        self.max_heartbeat_miss = 3    # 最多允许连续失败3次
        self.heartbeat_miss_count = 0
        
        # 配置日志记录
        self.setup_logging()
        
        # 添加错误恢复相关属性
        self.error_count = 0
        self.max_errors = 5
        self.error_reset_interval = 3600  # 1小时重置错误计数
        self.last_error_reset = datetime.now()
        
        # 添加打卡时间配置
        self.work_start_time = os.getenv('WORK_START_TIME', "09:00")  # 正常上班时间
        self.work_end_time = os.getenv('WORK_END_TIME', "17:30")      # 正常下班时间
        self.late_threshold = int(os.getenv('LATE_THRESHOLD', "15"))   # 晚到阈值（分钟）
        self.early_leave_threshold = int(os.getenv('EARLY_LEAVE_THRESHOLD', "15"))  # 早退阈值（分钟）
        
        # 初始化任务管理器和打卡记录管理器
        self.task_manager = TaskManager()
        self.punch_record_manager = PunchRecordManager()
        
        # 加载今日打卡记录
        today_record = self.punch_record_manager.get_today_record()
        self.today_punch_records = {
            'punch_in_time': datetime.strptime(today_record['punch_in_time'], '%H:%M:%S') if today_record['punch_in_time'] else None,
            'punch_out_time': datetime.strptime(today_record['punch_out_time'], '%H:%M:%S') if today_record['punch_out_time'] else None
        }
        
        # 设置每日状态推送时间
        self.daily_status_time = os.getenv('DAILY_STATUS_TIME', "08:20")  # 每日状态推送时间
        
        # 初始化定时任务
        self.init_schedule_tasks()
        
        # 添加虚拟鼠标控制
        self.use_virtual_mouse = True
        
        # 邮件服务（使用重构后的EmailService）
        self.email_service = email_service
        
        # 确保logs目录存在，用于保存截图
        os.makedirs('logs', exist_ok=True)
        
    def get_surname_honorific(self, username):
        """从用户名中提取姓氏并添加先生/女士称谓
        
        根据中文姓名习惯，通常第一个字为姓氏。如果无法确定，则返回默认称谓。
        """
        try:
            if not username or not isinstance(username, str):
                return "用户"
                
            # 对于中文用户名，取第一个字作为姓氏
            if any('\u4e00' <= char <= '\u9fff' for char in username):
                surname = username[0] if username else "用户"
                # 这里可以根据用户名判断性别，但这不准确，所以默认使用"先生/女士"
                return f"{surname}先生/女士"
            else:
                # 对于非中文用户名，返回完整用户名
                return username
                
        except Exception as e:
            logging.error(f"获取用户姓氏称谓时出错: {str(e)}")
            return "用户"  # 发生错误时返回默认称谓

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

    async def send_notification(self, title, content):
        """发送/更新Telegram消息"""
        message = self.update_progress(f"{title}: {content}")
        
        # 确保bot和app已初始化
        if not hasattr(self.bot, 'app') or self.bot.app is None:
            logging.warning(f"无法发送通知，Telegram bot应用尚未初始化: {title} - {content}")
            return
            
        if self.message_id:
            try:
                await self.bot.app.bot.edit_message_text(
                    chat_id=self.bot.chat_id,
                    message_id=self.message_id,
                    text=message
                )
            except Exception as e:
                print(f"更新消息失败: {str(e)}")
        else:
            try:
                message = await self.bot.app.bot.send_message(
                    chat_id=self.bot.chat_id,
                    text=message
                )
                self.message_id = message.message_id
            except Exception as e:
                print(f"发送消息失败: {str(e)}")

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
        """通过图像模板匹配找到元素位置，增加重试机制"""
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
            
            if max_val >= threshold:
                # 获取浏览器窗口位置
                hwnd = self.get_browser_window()
                if hwnd:
                    window_x, window_y = win32gui.GetWindowRect(hwnd)[:2]
                    # 返回相对于屏幕的绝对坐标
                    center_x = window_x + max_loc[0] + template_width // 2
                    center_y = window_y + max_loc[1] + template_height // 2
                    return (center_x, center_y)
                
            if attempt < self.max_retries - 1:
                print(f"未找到元素 {template_path}（匹配度：{max_val:.2f}），{attempt + 1} 次重试...")
                time.sleep(self.retry_interval)
                
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
        """获取剩余时间并计算还需工作时间"""
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
                
                # 保存临时文件用于OCR识别
                cv2.imwrite('time_region.png', time_region)
                
                await self.send_notification("时间识别", "开始OCR识别...")
                # 使用OCR识别时间文本，添加配置参数
                custom_config = r'--oem 3 --psm 6 -c preserve_interword_spaces=1'
                time_text = pytesseract.image_to_string(
                    Image.open('time_region.png'),
                    lang='chi_sim',  # 使用中文简体识别
                    config=custom_config
                )
                os.remove('time_region.png')  # 删除临时文件
                
                await self.send_notification("时间识别", f"OCR识别结果: {time_text}")
                
                # 提取小时和分钟，使用更灵活的正则表达式
                # 匹配"仅"字后面的数字和时间单位
                time_pattern = r'[仅仅]?(\d+)\s*[小时時].*?(\d+)\s*分[钟鐘]'
                time_match = re.search(time_pattern, time_text)
                
                if time_match:
                    hours = int(time_match.group(1))
                    minutes = int(time_match.group(2))
                    await self.send_notification("时间识别", f"已工作时间: {hours}小时{minutes}分钟")
                    
                    # 计算还需工作的时间（8小时16分钟 - 已工作时间）
                    total_minutes = 8 * 60 + 16  # 8小时16分钟转换为分钟
                    worked_minutes = hours * 60 + minutes
                    remaining_minutes = total_minutes - worked_minutes
                    
                    remaining_hours = remaining_minutes // 60
                    remaining_mins = remaining_minutes % 60
                    
                    result = f"{remaining_hours}小时{remaining_mins}分钟"
                    await self.send_notification("时间识别", f"计算结果 - 还需工作: {result}")
                    return result
                else:
                    await self.send_notification("时间识别", f"无法从文本中提取时间: {time_text}")
            else:
                await self.send_notification("时间识别", "未找到剩余时间位置")
            return None
        except Exception as e:
            await self.send_notification("时间识别", f"获取剩余时间失败: {str(e)}")
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
            
            # 使用 Edge InPrivate 模式打开新窗口
            await self.send_notification("打卡流程", "开始打开浏览器...")
            os.system('start msedge --inprivate --new-window "{}"'.format(self.login_url))
            time.sleep(3)  # 增加等待时间，确保页面完全加载
            
            # 获取当前窗口截图用于错误处理
            screen = self.take_screenshot()
            
            # 检查是否有警告弹窗
            await self.send_notification("打卡流程", "检查是否存在警告弹窗...")
            
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
                await self.send_notification("打卡流程", "检测到警告弹窗，处理中...")
                # 查找并点击更多按钮
                await self.send_notification("打卡流程", "尝试查找更多按钮...")
                more_button_loc = self.find_element_by_image('templates/more_button.png', threshold=0.5)
                if not more_button_loc:
                    error_msg = "检测到警告弹窗但未找到更多按钮，终止打卡流程"
                    await self.send_notification("打卡流程", error_msg)
                    # 发送失败截图
                    if screen is not None:
                        screenshot_path = 'punch_error.png'
                        cv2.imwrite(screenshot_path, screen)
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
                    return (False, None)
                
                await self.send_notification("打卡流程", "找到更多按钮，点击中...")
                self.click_position(*more_button_loc)
                time.sleep(1)
                
                # 更新截图
                screen = self.take_screenshot()
                
                # 查找并点击继续按钮
                await self.send_notification("打卡流程", "尝试查找继续按钮...")
                continue_button_loc = self.find_element_by_image('templates/continue2.png', threshold=0.5)
                if not continue_button_loc:
                    error_msg = "点击更多按钮后未找到继续按钮，终止打卡流程"
                    await self.send_notification("打卡流程", error_msg)
                    # 发送失败截图
                    if screen is not None:
                        screenshot_path = 'punch_error.png'
                        cv2.imwrite(screenshot_path, screen)
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
                    return (False, None)
                
                await self.send_notification("打卡流程", "点击继续按钮...")
                self.click_position(*continue_button_loc)
                time.sleep(1)
            else:
                await self.send_notification("打卡流程", "未检测到警告弹窗，继续执行...")
            
            # 更新截图
            screen = self.take_screenshot()
            
            if await self.login(username, password):
                await self.send_notification("打卡流程", "登录成功，等待系统加载...")
                time.sleep(3)
                
                # 更新截图
                screen = self.take_screenshot()
                
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
                        if unable_escape_loc:
                            # 获取剩余工作时间
                            remaining_time = await self.get_remaining_time()
                            if remaining_time:
                                error_msg = f"未满足下班条件，还需工作: {remaining_time}"
                                remaining_time_info = remaining_time  # 保存剩余时间信息
                                
                                # 从剩余时间中提取分钟数
                                import re
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
                                await self.send_notification("打卡流程", f"通知发送失败: {str(e)}")
                            return (False, remaining_time_info)
                        else:
                            # 只有在没有unable_escape时才记录下班时间
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
                        
                        # 打卡完成后发送状态信息
                        await self.send_daily_status()
                        
                        # 保存并发送当前的浏览器窗口截图
                        screenshot_path = f'logs/punch_{"in" if punch_type == "上班" else "out"}_result.png'
                        cv2.imwrite(screenshot_path, screen)
                        
                        success_msg = f"{punch_type}打卡成功 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        await self.send_notification("打卡流程", success_msg)
                        
                        # 发送截图，增加重试机制
                        max_retries = 3
                        retry_delay = 5
                        for retry in range(max_retries):
                            try:
                                if os.path.exists(screenshot_path):
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
                            except telegram.error.NetworkError as e:
                                if retry < max_retries - 1:
                                    await self.send_notification("打卡流程", f"发送截图时发生网络错误，{retry + 1}/{max_retries} 次重试: {str(e)}")
                                    await asyncio.sleep(retry_delay * (retry + 1))
                                else:
                                    await self.send_notification("打卡流程", f"发送截图失败，网络错误: {str(e)}")
                            except Exception as e:
                                await self.send_notification("打卡流程", f"发送截图失败: {str(e)}")
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

    async def punch_in(self):
        """执行上班打卡"""
        try:
            if not self.users or len(self.users) == 0:
                await self.send_notification("打卡错误", "未配置用户信息，无法执行打卡")
                return False
            
            success_count = 0
            for i, user in enumerate(self.users):
                username = user.get('username')
                password = user.get('password')
                
                # 为每个用户发送单独的开始消息
                await self.send_notification("多用户打卡", f"开始为用户 {username} 执行上班打卡 ({i+1}/{len(self.users)})")
                
                # 执行打卡
                result, _ = await self._do_punch("上班", username, password)
                
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
                    await asyncio.sleep(5)
            
            # 所有用户打卡完成后发送总结消息
            await self.send_notification("打卡完成", f"上班打卡完成，成功: {success_count}/{len(self.users)}")
            return success_count > 0
        except Exception as e:
            await self.handle_error(e, "上班打卡")
            return False

    async def punch_out(self):
        """执行下班打卡"""
        try:
            if not self.users or len(self.users) == 0:
                await self.send_notification("打卡错误", "未配置用户信息，无法执行打卡")
                return False
            
            success_count = 0
            remaining_times = []  # 用于存储每个用户的剩余工作时间
            
            for i, user in enumerate(self.users):
                username = user.get('username')
                password = user.get('password')
                
                # 为每个用户发送单独的开始消息
                await self.send_notification("多用户打卡", f"开始为用户 {username} 执行下班打卡 ({i+1}/{len(self.users)})")
                
                # 执行打卡，并捕获剩余工作时间
                result, remaining_time_info = await self._do_punch("下班", username, password, collect_remaining_time=True)
                
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
                    await asyncio.sleep(5)
            
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
            await self.handle_error(e, "下班打卡")
            return False

    def start_watchdog(self):
        """启动看门狗监控"""
        if hasattr(self, 'watchdog'):
            self.watchdog.start_monitoring()
            logging.info("看门狗监控已启动")
    
    def stop_watchdog(self):
        """停止看门狗监控"""
        if hasattr(self, 'watchdog'):
            self.watchdog.stop_monitoring()
            logging.info("看门狗监控已停止")
    
    def cleanup(self):
        """清理资源"""
        # 停止watchdog监控
        self.stop_watchdog()
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
                
            # 重置昨天的打卡记录
            if self.today_punch_records['punch_in_time'] and \
               self.today_punch_records['punch_in_time'].date() < current_date:
                self.today_punch_records = {
                    'punch_in_time': None,
                    'punch_out_time': None
                }
            
            # 检查上班打卡
            if not self.today_punch_records['punch_in_time'] and \
               current_time.time() > datetime.strptime(self.work_start_time, "%H:%M").time():
                await self.send_notification(
                    "打卡提醒",
                    "⚠️ 今日未检测到上班打卡记录，请及时补卡！"
                )
            
            # 检查下班打卡
            if self.today_punch_records['punch_in_time'] and \
               not self.today_punch_records['punch_out_time'] and \
               current_time.time() > datetime.strptime("18:00", "%H:%M").time():
                await self.send_notification(
                    "打卡提醒",
                    "⚠️ 今日未检测到下班打卡记录，请及时补卡！"
                )
                
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
            
            # 异步发送邮件
            self.email_service.send_email_async(
                subject=subject,
                body=body,
                image_path=attachment_path,
                callback=email_callback
            )
            
            # 立即返回True，不等待邮件发送完成
            return True
            
        except Exception as e:
            error_msg = f"邮件发送异常: {str(e)}"
            logging.error(error_msg)
            await self.send_notification("邮件发送", error_msg)
            return False
            
    async def check_email_connection(self):
        """检查与邮件服务器的连接"""
        try:
            status_msg = "正在检查邮件服务器连接..."
            logging.info(status_msg)
            print(status_msg)
            
            # 使用EmailService检查连接
            if self.email_service.check_email_connection():
                success_msg = "邮件服务器连接测试成功"
                logging.info(success_msg)
                print(success_msg)
                return True
            else:
                error_msg = "邮件服务器连接失败"
                logging.error(error_msg)
                print(error_msg)
                await self.send_notification("邮箱连接", f"❌ {error_msg}")
                return False
            
        except Exception as e:
            error_msg = f"邮件服务器连接异常: {str(e)}"
            logging.error(error_msg)
            print(error_msg)
            await self.send_notification("邮箱连接", f"❌ {error_msg}")
            return False

# 定义全局变量
attendance_system_global = None
last_job_check = None
last_job_count = 0
job_log_interval = 60  # 至少间隔60秒输出一次任务日志

async def run_schedule():
    global attendance_system_global, last_job_check, last_job_count
    
    while True:
        try:
            # 获取当前定时任务列表
            jobs = schedule.get_jobs()
            current_time = datetime.now()
            
            # 只在任务数量变化或者每隔一段时间输出一次日志
            if (jobs and (last_job_check is None or 
                         (current_time - last_job_check).total_seconds() > job_log_interval or 
                         len(jobs) != last_job_count)):
                logging.info(f"当前定时任务数量: {len(jobs)}")
                for i, job in enumerate(jobs):
                    logging.info(f"任务 #{i+1}: 下次运行时间: {job.next_run}, 任务函数: {job.job_func}")
                last_job_check = current_time
                last_job_count = len(jobs)
            
            # 运行待处理的定时任务
            for job in jobs:
                if job.should_run:
                    try:
                        # 只在任务实际执行时记录日志
                        current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        logging.info(f"[{current_time_str}] 开始执行定时任务")
                        # 执行任务并等待其完成
                        result = job.run()
                        if asyncio.iscoroutine(result):
                            await result
                        logging.info(f"[{current_time_str}] 定时任务执行完成")
                    except Exception as e:
                        error_msg = f"执行定时任务时发生错误: {str(e)}"
                        print(error_msg)
                        logging.error(error_msg)
                        logging.error(traceback.format_exc())
            
            # 执行心跳检测
            if attendance_system_global:
                # 每小时检查一次打卡状态
                if datetime.now().minute == 0:
                    await attendance_system_global.check_punch_status()
                
            await asyncio.sleep(1)
        except Exception as e:
            error_msg = f"调度任务发生错误: {str(e)}"
            print(error_msg)
            logging.error(error_msg)
            logging.error(traceback.format_exc())
            await asyncio.sleep(5)  # 发生错误时等待一段时间后继续

async def main():
    attendance_system = None
    try:
        attendance_system = AttendanceSystem()
        logging.info("自动打卡系统已启动...")
        
        print("自动打卡系统已启动...")
        print("\n您可以通过Telegram机器人控制打卡：")
        print("/punch_in - 执行上班打卡")
        print("/punch_out - 执行下班打卡")
        print("/status - 查看系统状态（包含看门狗状态）")
        print("/errors - 查看最近错误日志")
        print("/kill - 查看并管理定时任务")
        print("/kill <任务ID> - 直接删除指定任务")
        
        # 显示看门狗状态
        print("\n🛡️ 看门狗模式已启用 - 系统将自动监控进程状态和资源使用情况")
        
        # 初始化 Telegram 机器人
        app = Application.builder().token(attendance_system.bot.token).build()
        attendance_system.bot.app = app
        attendance_system.bot.attendance_system = attendance_system
        
        # 在Telegram机器人初始化之后检查邮箱连接
        await attendance_system.check_email_connection()
        
        # 启动看门狗监控（如果启用）
        attendance_system.start_watchdog()
        
        # 注册命令处理器
        app.add_handler(CommandHandler('start', attendance_system.bot.start_command))
        app.add_handler(CommandHandler('punch_in', attendance_system.bot.punch_in_command))
        app.add_handler(CommandHandler('punch_out', attendance_system.bot.punch_out_command))
        app.add_handler(CommandHandler('status', attendance_system.bot.status_command))
        app.add_handler(CommandHandler('errors', attendance_system.bot.get_recent_errors))
        app.add_handler(CommandHandler('kill', attendance_system.bot.kill_command))
        app.add_handler(CommandHandler('set_time', attendance_system.bot.settime_command))
        # 注册按钮回调处理器
        app.add_handler(CallbackQueryHandler(attendance_system.bot.button_callback))
        # 注册消息处理器，必须在其他处理器之后添加
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, attendance_system.bot.handle_message))
        
        # 添加更新时间记录处理器
        async def update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            attendance_system.bot.last_update_time = datetime.now()
            
        app.add_handler(MessageHandler(filters.ALL, update_handler))

        # 设置全局的attendance_system变量，供run_schedule函数使用
        global attendance_system_global
        attendance_system_global = attendance_system
        
        # 创建调度任务
        schedule_task = asyncio.create_task(run_schedule())
        
        try:
            # 启动机器人
            await app.initialize()
            await app.start()
            
            # 启动轮询
            await attendance_system.bot.start_polling()
            
            # 启动连接监控
            monitor_task = asyncio.create_task(attendance_system.bot.monitor_connection())
            
            # 保持程序运行
            await asyncio.gather(
                asyncio.Event().wait(),
                monitor_task,
                return_exceptions=True
            )
        finally:
            # 清理资源
            schedule_task.cancel()
            await attendance_system.bot.stop_polling()
            await app.stop()
            await app.shutdown()
    except Exception as e:
        logging.critical(f"程序启动失败: {str(e)}")
        if attendance_system:
            await attendance_system.handle_error(e, "程序启动")
    finally:
        # 清理资源
        if attendance_system:
            attendance_system.cleanup()
            logging.info("程序已停止，资源已清理")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已停止")
