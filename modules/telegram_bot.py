"""
Telegram Bot 模块

处理Telegram机器人的所有功能，包括命令处理、消息发送、回调处理等
"""

import os
import time
import asyncio
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict

# Telegram相关
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# 图像处理
import cv2
import numpy as np

# 系统监控
import psutil

# 日历和调度
from chinese_calendar import is_workday, is_holiday
import schedule

# Windows API
import win32gui
import win32con

# 配置
from modules.config import config


class TelegramBot:
    def __init__(self, chat_id):
        self.token = config.TELEGRAM_BOT_TOKEN
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
        # 添加连接池配置 - 减少连接池大小和超时时间以提高稳定性
        self.connection_pool_size = 20  # 减少连接池大小
        self.connection_timeout = 20   # 减少连接超时
        self.pool_timeout = 20
        self.read_timeout = 20
        self.write_timeout = 20
        self.connect_timeout = 20
        # 添加设置定时打卡的状态变量
        self.setting_time_state = {}  # 用于存储用户的设置状态
        self.setting_time_timer = {}  # 用于存储设置超时计时器
        # 添加初始化状态跟踪
        self._is_initialized = False
        self._initialization_lock = asyncio.Lock()

    async def _ensure_app_initialized(self):
        """确保Application已正确初始化"""
        async with self._initialization_lock:
            if not self._is_initialized or not self.app:
                try:
                    # 如果已有app实例，先清理
                    if self.app:
                        try:
                            await self.app.stop()
                            await self.app.shutdown()
                        except Exception as e:
                            logging.warning(f"清理旧应用实例时发生错误: {e}")

                    # 创建新的Application实例
                    self.app = Application.builder().token(self.token).pool_timeout(self.pool_timeout).connect_timeout(self.connect_timeout).read_timeout(self.read_timeout).write_timeout(self.write_timeout).connection_pool_size(self.connection_pool_size).get_updates_connection_pool_size(self.connection_pool_size).build()

                    # 注册处理器
                    self.app.add_handler(CommandHandler('start', self.start_command))
                    self.app.add_handler(CommandHandler('punch_in', self.punch_in_command))
                    self.app.add_handler(CommandHandler('punch_out', self.punch_out_command))
                    self.app.add_handler(CommandHandler('stop', self.stop_command))
                    self.app.add_handler(CommandHandler('status', self.status_command))
                    self.app.add_handler(CommandHandler('errors', self.get_recent_errors))
                    self.app.add_handler(CommandHandler('kill', self.kill_command))
                    self.app.add_handler(CommandHandler('set_time', self.settime_command))
                    self.app.add_handler(CommandHandler('check', self.check_command))
                    self.app.add_handler(CommandHandler('auto_byebye', self.auto_byebye_command))
                    self.app.add_handler(CommandHandler('parallel', self.parallel_login_command))
                    self.app.add_handler(CallbackQueryHandler(self.button_callback))
                    self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

                    # 添加更新时间记录处理器
                    async def update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                        self.last_update_time = datetime.now()
                        self.connection_error_count = 0  # 重置错误计数

                    self.app.add_handler(MessageHandler(filters.ALL, update_handler))

                    # 初始化应用
                    await self.app.initialize()
                    self._is_initialized = True
                    logging.info("Telegram Bot Application 初始化完成")

                except Exception as e:
                    self._is_initialized = False
                    self.app = None
                    logging.error(f"初始化Telegram Bot Application失败: {e}")
                    raise

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/start命令"""
        await update.message.reply_text(
            "欢迎使用打卡机器人！\n"
            "支持的命令：\n"
            "/punch_in - 上班打卡\n"
            "/punch_out - 下班打卡\n"
            "/auto_byebye - 自动下班打卡（根据上班时间计算8小时16分钟后自动下班）\n"
            "/stop - 终止当前正在进行的打卡操作\n"
            "/status - 查看状态（包含当前操作状态）\n"
            "/errors - 查看最近错误日志\n"
            "/kill - 查看并管理定时任务\n"
            "/kill <任务ID> - 直接删除指定任务\n"
            "/check - 查看最新打卡图片\n"
            "/check <用户名> - 查看指定用户的打卡图片\n"
            "/parallel - 并行登录多个用户\n\n"
            "🛡️ 看门狗功能已内置启用\n"
            "🔄 打卡操作现在支持后台运行，可随时使用 /stop 终止"
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

        # 尝试启动打卡操作
        success, message = await self.attendance_system.start_punch_operation("punch_in")
        
        if success:
            await update.message.reply_text(f"✅ 上班打卡操作已启动\n📍 您可以使用 /status 查看进度\n🛑 您可以使用 /stop 终止操作")
        else:
            await update.message.reply_text(f"❌ {message}")

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

        # 尝试启动打卡操作
        success, message = await self.attendance_system.start_punch_operation("punch_out")
        
        if success:
            await update.message.reply_text(f"✅ 下班打卡操作已启动\n📍 您可以使用 /status 查看进度\n🛑 您可以使用 /stop 终止操作")
        else:
            await update.message.reply_text(f"❌ {message}")

    async def auto_byebye_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理自动下班打卡命令"""
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

        try:
            await update.message.reply_text("🕐 正在获取当日上班打卡时间...")
            
            # 获取当日上班打卡时间
            success, punch_in_time, message = await self.attendance_system.get_today_punch_in_time()
            
            if not success:
                await update.message.reply_text(f"❌ 获取上班时间失败：{message}")
                return
            
            # 计算下班时间
            calc_success, punch_out_time, calc_message = self.attendance_system.calculate_punch_out_time(punch_in_time)
            
            if not calc_success:
                await update.message.reply_text(f"❌ 计算下班时间失败：{calc_message}")
                return
            
            # 创建确认按钮
            keyboard = [
                [
                    InlineKeyboardButton("✅ 确认设置", callback_data=f'auto_byebye_confirm_{punch_out_time}'),
                    InlineKeyboardButton("❌ 取消", callback_data='auto_byebye_cancel')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # 发送确认消息
            confirm_message = (
                f"🎯 自动下班打卡设置\n\n"
                f"📍 上班时间：{punch_in_time}\n"
                f"🕐 计算下班时间：{punch_out_time}\n"
                f"⏰ 工作时长：8小时16分钟\n\n"
                f"💡 确认后将自动设置定时任务，到时间后自动执行下班打卡。\n\n"
                f"请选择操作："
            )
            
            await update.message.reply_text(confirm_message, reply_markup=reply_markup)
            
        except Exception as e:
            error_msg = f"执行auto_byebye命令时发生错误: {str(e)}"
            logging.error(error_msg)
            await update.message.reply_text(f"❌ {error_msg}")

    async def parallel_login_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理并行登录命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        try:
            await update.message.reply_text("🚀 开始并行登录...")
            
            # 检查系统是否已初始化
            if not self.attendance_system:
                await update.message.reply_text("❌ 系统未初始化，无法执行并行登录")
                return
            
            # 准备用户配置
            users_config = self.attendance_system.prepare_users_config_from_env()
            
            if not users_config or len(users_config) < 1:
                await update.message.reply_text(f"❌ 需要至少1个用户才能执行并行登录\n当前用户数: {len(users_config)}")
                return
            
            await update.message.reply_text(f"👥 准备并行登录 {len(users_config)} 个用户...")
            
            # 执行并行登录
            start_time = time.time()
            results = await self.attendance_system.parallel_punch_login(
                users_config=users_config,
                max_concurrent=3  # 最大并发数
            )
            end_time = time.time()
            
            # 统计结果
            total_users = len(results)
            successful_users = sum(1 for success, _ in results.values() if success)
            failed_users = total_users - successful_users
            elapsed_time = end_time - start_time
            
            # 发送结果汇总
            result_msg = (
                f"🚀 并行登录完成\n\n"
                f"👥 总用户数: {total_users}\n"
                f"✅ 成功: {successful_users}\n"
                f"❌ 失败: {failed_users}\n"
                f"⏱️ 用时: {elapsed_time:.2f}秒\n\n"
                f"📊 详细结果:\n"
            )
            
            for user_id, (success, message) in results.items():
                status_icon = "✅" if success else "❌"
                result_msg += f"{status_icon} {user_id}: {message[:50]}{'...' if len(message) > 50 else ''}\n"
            
            await update.message.reply_text(result_msg)
            
            # 如果有失败的用户，提供详细错误信息
            if failed_users > 0:
                error_details = "❌ 失败详情:\n"
                for user_id, (success, message) in results.items():
                    if not success:
                        error_details += f"• {user_id}: {message}\n"
                
                if len(error_details) > 4000:  # Telegram消息长度限制
                    error_details = error_details[:4000] + "\n..."
                
                await update.message.reply_text(error_details)
            
            # 性能对比信息
            estimated_sequential_time = len(users_config) * 15  # 假设每个用户串行需要15秒
            performance_msg = (
                f"⚡ 性能对比:\n"
                f"并行模式: {elapsed_time:.2f}秒\n"
                f"串行模式(预估): {estimated_sequential_time}秒\n"
                f"提升倍数: {estimated_sequential_time / elapsed_time:.1f}x"
            )
            await update.message.reply_text(performance_msg)
            
        except Exception as e:
            error_msg = f"执行并行登录时发生错误: {str(e)}"
            logging.error(error_msg, exc_info=True)
            await update.message.reply_text(f"❌ {error_msg}")

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
            )

            # 添加当前操作状态显示
            if self.attendance_system.current_operation is not None:
                operation_display = "上班打卡" if self.attendance_system.current_operation == "punch_in" else "下班打卡"
                elapsed_time = ""
                if self.attendance_system.operation_start_time:
                    elapsed = current_time - self.attendance_system.operation_start_time
                    elapsed_minutes = int(elapsed.total_seconds() / 60)
                    elapsed_seconds = int(elapsed.total_seconds() % 60)
                    elapsed_time = f"（已运行 {elapsed_minutes}分{elapsed_seconds}秒）"
                
                status_text += (
                    "🔄 当前操作状态\n"
                    f"正在执行：{operation_display} {elapsed_time}\n"
                    f"使用 /stop 命令可终止当前操作\n\n"
                )
            else:
                status_text += "🔄 当前操作状态\n无正在进行的操作\n\n"

            status_text += (
                "📍 今日打卡记录\n"
                f"上班打卡：{'✅ ' + punch_in_time.strftime('%H:%M:%S') if punch_in_time else '❌ 未打卡'}\n"
                f"下班打卡：{'✅ ' + punch_out_time.strftime('%H:%M:%S') if punch_out_time else '❌ 未打卡'}\n\n"

                "⚙️ 系统信息\n"
                f"运行时长：{int(hours)}小时{int(minutes)}分钟\n"
                f"内存使用：{memory.percent}%\n"
                f"CPU使用：{cpu_percent}%\n"
                f"心跳状态：{'🟢 正常' if self.attendance_system.heartbeat_miss_count == 0 else '🟡 警告'}\n\n"

                "📋 配置信息\n"
                f"上班时间：{config.WORK_START_TIME}\n"
                f"下班时间：{config.WORK_END_TIME}\n"
                f"迟到阈值：{config.LATE_THRESHOLD}分钟\n"
                f"早退阈值：{config.EARLY_LEAVE_THRESHOLD}分钟\n"
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

    async def stop_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/stop命令，终止当前操作"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        try:
            # 检查是否有正在进行的操作
            if self.attendance_system.current_operation is None:
                await update.message.reply_text("当前没有进行中的操作需要终止")
                return

            operation_type = self.attendance_system.current_operation
            operation_display = "上班打卡" if operation_type == "punch_in" else "下班打卡"
            
            # 通知用户正在终止操作
            await update.message.reply_text(f"正在终止{operation_display}操作...")
            
            # 调用取消操作方法
            success, message = await self.attendance_system.cancel_current_operation()
            
            if success:
                await update.message.reply_text(f"✅ {message}")
            else:
                await update.message.reply_text(f"❌ {message}")
                
        except Exception as e:
            error_msg = f"处理/stop命令时发生错误: {str(e)}"
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
        for retry in range(self.max_retries):
            try:
                # 确保应用已初始化
                await self._ensure_app_initialized()

                if not self.app:
                    error_msg = "Telegram Bot应用未初始化"
                    logging.error(error_msg)
                    return False

                message = f"{title}\n\n{content}"
                await self.app.bot.send_message(chat_id=self.chat_id, text=message)
                # 成功发送后重置错误计数
                self.connection_error_count = 0
                self.last_connection_error = None
                return True

            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)

                # 检查是否是HTTPXRequest初始化错误
                if "HTTPXRequest" in error_msg and "not initialized" in error_msg:
                    self._is_initialized = False  # 标记需要重新初始化
                    error_msg = f"发送Telegram消息时发生HTTPXRequest错误 (尝试 {retry + 1}/{self.max_retries}): {error_msg}"
                elif "NetworkError" in error_type or "TimedOut" in error_type:
                    self.connection_error_count += 1
                    self.last_connection_error = datetime.now()
                    error_msg = f"发送Telegram消息时发生网络错误 (尝试 {retry + 1}/{self.max_retries}): {error_msg}"
                else:
                    error_msg = f"发送Telegram消息时发生其他错误 (尝试 {retry + 1}/{self.max_retries}): {error_msg}"

                print(error_msg)
                logging.error(error_msg)

                # 如果不是最后一次重试，等待后继续
                if retry < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (retry + 1))
                    continue

                # 最后一次重试失败，检查是否需要重启程序
                if self.connection_error_count >= self.max_connection_errors:
                    error_msg = "网络错误次数过多，准备重启程序..."
                    print(error_msg)
                    logging.critical(error_msg)
                    if self.attendance_system:
                        await self.attendance_system.restart_program()
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

    async def check_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/check命令 - 查看最新的打卡图片"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        try:
            # 解析命令参数
            args = context.args

            # 获取所有用户列表
            if not self.attendance_system or not self.attendance_system.users:
                await update.message.reply_text("❌ 系统未初始化或无用户配置")
                return

            all_users = [user['username'] for user in self.attendance_system.users]

            # 如果没有参数，显示交互式按钮界面
            if not args:
                keyboard = [
                    [
                        InlineKeyboardButton("📅 查看上班图片", callback_data='check_punch_in'),
                        InlineKeyboardButton("🌅 查看下班图片", callback_data='check_punch_out')
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"📸 请选择要查看的打卡类型：\n\n"
                    f"💡 可用用户: {', '.join(all_users)}\n"
                    f"将显示所有用户的相关打卡图片",
                    reply_markup=reply_markup
                )
                return

            # 解析用户名和类型
            username = args[0]
            punch_type = args[1] if len(args) > 1 else 'all'

            # 验证用户名
            if username not in all_users:
                await update.message.reply_text(f"❌ 用户 '{username}' 不存在\n可用用户: {', '.join(all_users)}")
                return

            # 验证打卡类型
            if punch_type not in ['all', 'punch_in', 'punch_out']:
                await update.message.reply_text("❌ 无效的打卡类型，请使用：all、punch_in 或 punch_out")
                return

            # 获取截图目录
            screenshot_base_dir = 'screenshots'
            user_screenshot_dir = os.path.join(screenshot_base_dir, username)

            if not os.path.exists(user_screenshot_dir):
                await update.message.reply_text(f"❌ 用户 '{username}' 还没有打卡记录")
                return

            # 收集图片文件
            images_to_send = []

            # 根据类型收集图片
            if punch_type == 'all' or punch_type == 'punch_in':
                punch_in_dir = os.path.join(user_screenshot_dir, 'punch_in')
                if os.path.exists(punch_in_dir):
                    images_to_send.extend(self._get_recent_images(punch_in_dir, 'punch_in', 5))

            if punch_type == 'all' or punch_type == 'punch_out':
                punch_out_dir = os.path.join(user_screenshot_dir, 'punch_out')
                if os.path.exists(punch_out_dir):
                    images_to_send.extend(self._get_recent_images(punch_out_dir, 'punch_out', 5))

            # 按时间排序
            images_to_send.sort(key=lambda x: x['time'], reverse=True)

            # 限制最多10张图片
            if len(images_to_send) > 10:
                images_to_send = images_to_send[:10]

            if not images_to_send:
                await update.message.reply_text(f"❌ 用户 '{username}' 没有找到相关的打卡图片")
                return

            # 发送图片
            await update.message.reply_text(f"📸 正在发送 {username} 的最新打卡图片...")

            for i, image_info in enumerate(images_to_send):
                try:
                    with open(image_info['path'], 'rb') as photo:
                        caption = f"👤 用户: {username}\n📅 时间: {image_info['time_str']}\n🔄 类型: {image_info['type']}"
                        await self.app.bot.send_photo(
                            chat_id=self.chat_id,
                            photo=photo,
                            caption=caption
                        )

                    # 避免发送过快被限制
                    if i < len(images_to_send) - 1:
                        await asyncio.sleep(0.5)

                except Exception as e:
                    logging.error(f"发送图片 {image_info['path']} 失败: {e}")
                    await update.message.reply_text(f"❌ 发送图片失败: {os.path.basename(image_info['path'])}")

            await update.message.reply_text(f"✅ 已发送 {len(images_to_send)} 张图片")

        except Exception as e:
            logging.error(f"处理/check命令时发生错误: {e}")
            await update.message.reply_text(f"❌ 处理命令时发生错误: {str(e)}")

    def _get_recent_images(self, directory, punch_type, limit=5):
        """获取目录中最近的图片文件"""
        images = []
        try:
            if not os.path.exists(directory):
                return images

            # 获取所有图片文件
            for filename in os.listdir(directory):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    filepath = os.path.join(directory, filename)
                    try:
                        # 获取文件修改时间
                        mtime = os.path.getmtime(filepath)
                        time_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

                        images.append({
                            'path': filepath,
                            'time': mtime,
                            'time_str': time_str,
                            'type': '上班打卡' if punch_type == 'punch_in' else '下班打卡',
                            'filename': filename
                        })
                    except Exception as e:
                        logging.warning(f"获取文件 {filepath} 信息失败: {e}")
                        continue

            # 按修改时间排序，最新的在前
            images.sort(key=lambda x: x['time'], reverse=True)

            # 限制数量
            return images[:limit]

        except Exception as e:
            logging.error(f"获取目录 {directory} 中的图片失败: {e}")
            return images

    def _save_screenshot_with_rotation(self, screen, username, punch_type, success=True):
        """
        使用滚动保存机制保存截图，确保每个用户每种类型最多保留3张图片
        
        Args:
            screen: cv2截图数据
            username: 用户名
            punch_type: 'punch_in' 或 'punch_out'
            success: 是否成功打卡，用于文件名标识
        
        Returns:
            str: 保存的文件路径，如果失败返回None
        """
        try:
            if not username:
                logging.warning("用户名为空，跳过滚动保存")
                return None
            
            # 确定目录和文件名
            # 清理用户名，移除可能导致文件系统问题的字符
            safe_username = "".join(c for c in username if c.isalnum() or c in (' ', '-', '_')).strip()
            if not safe_username:
                safe_username = "unknown_user"
            
            user_screenshot_dir = os.path.join('screenshots', safe_username, punch_type)
            os.makedirs(user_screenshot_dir, exist_ok=True)
            
            # 生成带时间戳和状态标识的文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            status_suffix = "success" if success else "fail"
            filename = f'{punch_type}_{timestamp}_{status_suffix}.png'
            filepath = os.path.join(user_screenshot_dir, filename)
            
            # 保存新截图
            # 尝试使用绝对路径来解决WSL路径问题
            abs_filepath = os.path.abspath(filepath)
            logging.debug(f"尝试使用绝对路径保存: {repr(abs_filepath)}")
            
            save_result = cv2.imwrite(abs_filepath, screen)
            if save_result:
                logging.info(f"已保存用户 {username} 的{punch_type}打卡截图到: {abs_filepath}")
                # 验证文件是否真的存在
                if os.path.exists(abs_filepath):
                    file_size = os.path.getsize(abs_filepath)
                    logging.info(f"截图文件大小: {file_size} bytes")
                else:
                    logging.error(f"截图文件保存后不存在: {abs_filepath}")
            else:
                logging.error(f"保存截图失败: {abs_filepath}")
                logging.error(f"截图数据为空: {screen is None}")
                if screen is not None:
                    logging.error(f"截图数据形状: {screen.shape}")
                return None
            
            # 获取目录中所有图片文件并按修改时间排序
            image_files = []
            for file in os.listdir(user_screenshot_dir):
                if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                    file_path = os.path.join(user_screenshot_dir, file)
                    try:
                        mtime = os.path.getmtime(file_path)
                        image_files.append((file_path, mtime))
                    except Exception as e:
                        logging.warning(f"获取文件 {file_path} 修改时间失败: {e}")
                        continue
            
            # 按修改时间排序，最新的在前
            image_files.sort(key=lambda x: x[1], reverse=True)
            
            # 如果超过3张，删除最旧的图片
            if len(image_files) > 3:
                files_to_remove = image_files[3:]  # 保留前3张，删除其余的
                for file_path, _ in files_to_remove:
                    try:
                        os.remove(file_path)
                        logging.info(f"已删除旧截图文件: {file_path}")
                    except Exception as e:
                        logging.error(f"删除旧截图文件 {file_path} 失败: {e}")
            
            return abs_filepath
            
        except Exception as e:
            logging.error(f"滚动保存截图失败 (用户: {username}, 类型: {punch_type}): {e}")
            return None

    async def _handle_check_callback(self, query, punch_type):
        """处理查看打卡图片的回调"""
        try:
            # 更新消息状态
            type_name = "上班" if punch_type == "punch_in" else "下班"
            await query.message.edit_text(f"🔍 正在搜索所有用户的{type_name}打卡图片...")

            # 获取所有用户列表
            if not self.attendance_system or not self.attendance_system.users:
                await query.message.edit_text("❌ 系统未初始化或无用户配置")
                return

            all_users = [user['username'] for user in self.attendance_system.users]
            all_images = []

            # 遍历所有用户收集图片
            for username in all_users:
                user_screenshot_dir = os.path.join('screenshots', username, punch_type)
                if os.path.exists(user_screenshot_dir):
                    user_images = self._get_recent_images(user_screenshot_dir, punch_type, 1)  # 每个用户只返回最新1张
                    # 为每张图片添加用户信息
                    for img in user_images:
                        img['username'] = username
                    all_images.extend(user_images)

            if not all_images:
                await query.message.edit_text(f"❌ 没有找到任何用户的{type_name}打卡图片")
                return

            # 按时间排序，最新的在前
            all_images.sort(key=lambda x: x['time'], reverse=True)

            # 限制最多显示10张图片
            if len(all_images) > 10:
                all_images = all_images[:10]

            # 更新消息显示找到的图片数量
            await query.message.edit_text(f"📸 找到 {len(all_images)} 张{type_name}打卡图片，正在发送...")

            # 发送图片
            for i, image_info in enumerate(all_images):
                try:
                    with open(image_info['path'], 'rb') as photo:
                        caption = f"👤 用户: {image_info['username']}\n📅 时间: {image_info['time_str']}\n🔄 类型: {image_info['type']}"
                        await self.app.bot.send_photo(
                            chat_id=query.message.chat_id,
                            photo=photo,
                            caption=caption
                        )

                    # 避免发送过快被限制
                    if i < len(all_images) - 1:
                        await asyncio.sleep(0.5)

                except Exception as e:
                    logging.error(f"发送图片 {image_info['path']} 失败: {e}")
                    await self.app.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"❌ 发送图片失败: {os.path.basename(image_info['path'])}"
                    )

            # 最终状态更新
            await query.message.edit_text(f"✅ 已发送 {len(all_images)} 张{type_name}打卡图片")

        except Exception as e:
            logging.error(f"处理查看{punch_type}图片回调时发生错误: {e}")
            await query.message.edit_text(f"❌ 处理请求时发生错误: {str(e)}")

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

            # 处理查看打卡图片的回调
            elif query.data == 'check_punch_in':
                await self._handle_check_callback(query, 'punch_in')

            elif query.data == 'check_punch_out':
                await self._handle_check_callback(query, 'punch_out')

            # 处理错误日志翻页
            elif query.data.startswith('errors_page_'):
                page = int(query.data.split('_')[-1])
                # 使用命令处理器重新获取指定页的错误日志
                context.args = [str(page)]
                await self.get_recent_errors(Update(update_id=update.callback_query.id, message=query.message), context)
                # 删除原消息
                await query.message.delete()

            # 处理 auto_byebye 按钮回调
            elif query.data.startswith('auto_byebye_confirm_'):
                # 提取下班时间
                punch_out_time = query.data.replace('auto_byebye_confirm_', '')
                
                try:
                    # 验证时间格式
                    datetime.strptime(punch_out_time, '%H:%M:%S')
                    
                    # 设置定时任务
                    await query.message.edit_text("⏳ 正在设置定时任务...")
                    
                    # 计算延迟时间（分钟）
                    current_time = datetime.now()
                    punch_out_datetime = datetime.strptime(punch_out_time, '%H:%M:%S').time()
                    today_punch_out = datetime.combine(current_time.date(), punch_out_datetime)
                    
                    # 如果设定时间已过，则设置为明天
                    if today_punch_out <= current_time:
                        today_punch_out = today_punch_out + timedelta(days=1)
                    
                    delay_minutes = int((today_punch_out - current_time).total_seconds() / 60)
                    
                    # 设置定时任务
                    retry_time = await self.attendance_system.schedule_retry_punch_out(delay_minutes, clear_existing=False)
                    
                    if retry_time:
                        success_message = (
                            f"✅ 自动下班打卡设置成功！\n\n"
                            f"🕐 下班时间：{punch_out_time}\n"
                            f"⏰ 执行时间：{today_punch_out.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"📋 任务已添加到定时任务列表\n\n"
                            f"💡 您可以使用 /status 查看任务状态"
                        )
                        await query.message.edit_text(success_message)
                    else:
                        await query.message.edit_text("❌ 设置定时任务失败，请稍后重试")
                        
                except ValueError:
                    await query.message.edit_text("❌ 时间格式错误，操作已取消")
                except Exception as e:
                    error_msg = f"设置定时任务时发生错误: {str(e)}"
                    logging.error(error_msg)
                    await query.message.edit_text(f"❌ {error_msg}")

            elif query.data == 'auto_byebye_cancel':
                await query.message.edit_text("❌ 自动下班打卡设置已取消")

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

        # 标记需要重新初始化
        self._is_initialized = False
        self.app = None

        await asyncio.sleep(5)  # 等待5秒后重启

        try:
            # 使用_ensure_app_initialized来重新创建应用
            await self._ensure_app_initialized()

            if self.app:
                await self.app.start()
                await self.start_polling()
            else:
                logging.error("重启轮询失败：应用初始化失败")

        except Exception as e:
            logging.error(f"重启轮询失败: {str(e)}")

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
                            # 如果重启失败，标记需要重新初始化
                            self._is_initialized = False
                            self.app = None

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
        self.app.add_handler(CommandHandler("stop", self.stop_command))
        self.app.add_handler(CommandHandler("status", self.status_command))
        self.app.add_handler(CommandHandler("errors", self.get_recent_errors))
        self.app.add_handler(CommandHandler("kill", self.kill_command))
        self.app.add_handler(CommandHandler("set_time", self.settime_command))  # 修改命令名称
        self.app.add_handler(CommandHandler("auto_byebye", self.auto_byebye_command))

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
        if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
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
        if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
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
                if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
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
                    if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
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