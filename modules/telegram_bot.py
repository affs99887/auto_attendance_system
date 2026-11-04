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
from telegram.ext import Application, CommandHandler, MessageHandler, TypeHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import RetryAfter, BadRequest

# 图像处理
import cv2
import numpy as np

# 系统监控
import psutil

# 日历和调度
from modules.safe_calendar import is_workday, is_holiday
import schedule

# Windows API
import win32gui
import win32con

# 配置
from modules.config import config

from modules.selenium_login import SeleniumLoginController
from modules.email_service import email_service
from modules import wife_email


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
        # Telegram代理：按 config.TELEGRAM_PROXY_PORTS 顺序探测，失败则标记未就绪并交给恢复流程
        try:
            self.proxy_url = config.get_telegram_proxy()
        except Exception as exc:
            # 构造 AttendanceSystem 时不能因一次代理探测异常拖垮全部模块；初始化/重连会再次探测。
            self.proxy_url = None
            logging.warning(
                "首次读取 Telegram 代理失败，暂按未就绪处理（%s）",
                type(exc).__name__,
            )
        # 添加设置定时打卡的状态变量
        self.setting_time_state = {}  # 用于存储用户的设置状态
        self.setting_time_timer = {}  # 用于存储设置超时计时器
        # 添加初始化状态跟踪
        self._is_initialized = False
        self._initialization_lock = asyncio.Lock()
        # 重连/重启串行化锁（与 monitor_connection 自愈互斥；获取顺序：_reconnect_lock 在外、_initialization_lock 在内）
        self._reconnect_lock = asyncio.Lock()
        # settime配置持久化文件路径
        self.settime_history_file = 'settime_history.json'
        # 每日8:15提醒任务状态
        self.daily_reminder_pending = False
        self.daily_reminder_config = None
        self.daily_reminder_task_set = False  # 防止重复设置每日提醒任务
        self.daily_reminder_lock = asyncio.Lock()  # 防止并发执行每日提醒

    def _build_application(self, proxy_url=None):
        """构建 Telegram Application；存在可用代理则自动应用到普通请求与 getUpdates 两条通道。

        Args:
            proxy_url: 显式传入的代理 URL；为 None 时使用 self.proxy_url；传入 ""（空串）强制直连。
        """
        effective_proxy = self.proxy_url if proxy_url is None else proxy_url
        builder = (
            Application.builder()
            .token(self.token)
            # M19：PTB 默认串行处理更新（concurrent_updates=False），一旦某个 handler 内联
            # await 长耗时流程（Selenium 完整打卡可达数分钟、sleep(10)+punch、并行登录等），
            # 后续所有更新（含 /stop、/status）都会排队不处理，bot 表现为"假死"。
            # 启用并发更新让命令彼此独立调度，作为不改各 handler 的兜底修复。
            .concurrent_updates(True)
            .pool_timeout(self.pool_timeout)
            .connect_timeout(self.connect_timeout)
            .read_timeout(self.read_timeout)
            .write_timeout(self.write_timeout)
            .connection_pool_size(self.connection_pool_size)
            .get_updates_connection_pool_size(self.connection_pool_size)
        )
        if effective_proxy:
            # 显式 proxy 会覆盖 httpx 的系统环境代理（HTTP(S)_PROXY/ALL_PROXY），
            # 故启用内置加速时直连本程序自管理端口、不受系统 VPN/代理环境影响。
            builder = builder.proxy(effective_proxy).get_updates_proxy(effective_proxy)
        return builder.build()

    async def _ensure_app_initialized(self):
        """确保Application已正确初始化

        策略：必须走代理（中国大陆网络无法直连 Telegram）。
        启动时代理软件常出现"端口监听但 HTTP 隧道尚未就绪"的窗口期，因此对 initialize()
        失败做有限次重试（每次间隔递增），让代理有时间完成启动后再尝试。
        """
        max_init_retries = 4
        retry_delays = [2, 5, 10]  # 第 1/2/3 次失败后等待的秒数
        async with self._initialization_lock:
            if not self._is_initialized or not self.app:
                last_error = None

                for attempt_idx in range(max_init_retries):
                    # 每次重试前重新探测代理，避免使用一个早已不通的端口
                    try:
                        self.proxy_url = config.get_telegram_proxy()
                    except Exception as probe_error:
                        self.proxy_url = None
                        last_error = probe_error
                        logging.warning(
                            "探测 Telegram 代理失败（第 %d/%d 次，%s）",
                            attempt_idx + 1, max_init_retries, type(probe_error).__name__,
                        )
                    if not self.proxy_url:
                        last_error = RuntimeError(
                            f"未探测到可用 Telegram 代理（已尝试端口 {config.TELEGRAM_PROXY_PORTS}），"
                            f"请确认代理软件已启动"
                        )
                        logging.warning(str(last_error))
                        if attempt_idx < max_init_retries - 1:
                            delay = retry_delays[min(attempt_idx, len(retry_delays) - 1)]
                            logging.info(f"{delay} 秒后重试代理探测...")
                            await asyncio.sleep(delay)
                            continue
                        else:
                            break

                    try:
                        # 如果已有app实例，先清理
                        if self.app:
                            try:
                                await self.stop_polling()
                                await self.app.stop()
                                await self.app.shutdown()
                            except Exception as e:
                                logging.warning(f"清理旧应用实例时发生错误: {e!r}")

                        # 创建新的Application实例
                        self.app = self._build_application(proxy_url=self.proxy_url)

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
                        self.app.add_handler(CommandHandler('mode', self.mode_command))
                        self.app.add_handler(CommandHandler('test_reminder', self.test_reminder_command))
                        # Selenium完整流程命令
                        self.app.add_handler(CommandHandler('selenium_complete_punch_in', self.selenium_complete_punch_in_command))
                        self.app.add_handler(CommandHandler('selenium_complete_punch_out', self.selenium_complete_punch_out_command))
                        self.app.add_handler(CallbackQueryHandler(self.button_callback))
                        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

                        # 添加更新时间记录处理器
                        async def update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                            self.last_update_time = datetime.now()
                            self.connection_error_count = 0  # 重置错误计数

                        # M52/M92: PTB 同一 group 内一个 update 只会被第一个匹配的 handler 处理；
                        # 此前 update_handler 与命令/回调/文本 handler 同在 group 0 且注册靠后，
                        # 命令、按钮回调、文本消息全部被前面的 handler 消费，update_handler 仅对贴纸/图片等无人处理的消息生效，
                        # 导致 last_update_time 形同常量、监控误判超时。
                        # 改用 TypeHandler 注册到独立 group（各 group 独立分发），确保每个 update 都刷新心跳。
                        self.app.add_handler(TypeHandler(Update, update_handler), group=1)

                        # 注册全局错误处理器，统一记录 Telegram 更新处理过程中的未捕获异常
                        self.app.add_error_handler(self._on_error)

                        # 初始化每日提醒任务
                        self._setup_daily_reminder()

                        # 初始化应用
                        await self.app.initialize()
                        self._is_initialized = True
                        logging.info(
                            f"Telegram Bot Application 初始化完成（代理 {self.proxy_url}，"
                            f"第 {attempt_idx + 1} 次尝试）"
                        )
                        return

                    except Exception as e:
                        last_error = e
                        self._is_initialized = False
                        self.app = None
                        is_last_attempt = (attempt_idx == max_init_retries - 1)
                        if is_last_attempt:
                            logging.error(
                                f"初始化Telegram Bot Application失败（代理 {self.proxy_url}）"
                                f"，已重试 {max_init_retries} 次: {e!r}",
                                exc_info=True,
                            )
                        else:
                            delay = retry_delays[min(attempt_idx, len(retry_delays) - 1)]
                            logging.warning(
                                f"初始化Telegram Bot Application失败（代理 {self.proxy_url}）: {e!r}"
                                f"，{delay} 秒后重试（{attempt_idx + 2}/{max_init_retries}）"
                            )
                            await asyncio.sleep(delay)

                # 所有尝试都失败
                raise last_error

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/start命令"""
        await update.message.reply_text(
            "欢迎使用打卡机器人！\n"
            "支持的命令：\n"
            "/punch_in - 上班打卡\n"
            "/punch_out - 下班打卡\n"
            "/auto_byebye - 自动下班打卡（根据上班时间计算8小时15分钟 + 1-3分钟随机延迟后自动下班）\n"
            "/stop - 终止当前正在进行的打卡操作\n"
            "/status - 查看状态（包含当前操作状态）\n"
            "/errors - 查看最近错误日志\n"
            "/kill - 查看并管理定时任务\n"
            "/kill <任务ID> - 直接删除指定任务\n"
            "/check - 查看最新打卡图片\n"
            "/check <用户名> - 查看指定用户的打卡图片\n"
            "/parallel - 并行登录测试（仅验证多用户能并发登录，不打卡）\n"
            "/mode - 切换登录模式（Selenium无头/传统图像识别）\n"
            "/test_reminder - 测试8:15每日提醒功能\n\n"
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
            success, punch_in_time, message = await self.attendance_system.get_today_punch_in_time_auto()

            # 兜底：识别不到今日上班时间时，用配置上班时间 WORK_START_TIME 推算下班，
            # 使「即便没有上班记录也能自动下班」可用（仅作用于 /auto_byebye，不影响 16:35 自动触发的获取/手动输入交互）
            fallback_used = False
            if not success or not punch_in_time:
                punch_in_time = self.attendance_system.work_start_time
                fallback_used = True
                message = f"今日无上班打卡记录，已使用配置上班时间 {punch_in_time} 兜底计算下班时间"

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
            punch_in_line = (
                f"📍 上班时间：{punch_in_time}（⚠️ 今日无上班记录，按配置上班时间兜底）\n"
                if fallback_used else
                f"📍 上班时间：{punch_in_time}\n"
            )
            confirm_message = (
                f"🎯 自动下班打卡设置\n\n"
                f"{punch_in_line}"
                f"🕐 {calc_message}\n"
                f"⏰ 工作时长：8小时15分钟 + 1-3分钟随机延迟\n\n"
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
            await update.message.reply_text(
                "🧪 并行登录测试：此命令仅验证多用户能否并发登录，不会执行打卡。\n"
                "如需多账户并行打卡，直接发送 /punch_in 或 /punch_out（Selenium 模式自动启用并行）"
            )

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

    async def mode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理切换登录模式命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        try:
            # 检查系统是否已初始化
            if not self.attendance_system:
                await update.message.reply_text("❌ 系统未初始化")
                return

            # 获取当前模式状态
            current_use_selenium = self.attendance_system.use_selenium_login
            current_mode = "Selenium无头模式" if current_use_selenium else "传统图像识别模式"

            # 切换模式：USE_SELENIUM_LOGIN 和 SELENIUM_HEADLESS 同时切换
            new_use_selenium = not current_use_selenium
            new_headless = new_use_selenium  # Selenium开启时自动开启无头模式

            self.attendance_system.use_selenium_login = new_use_selenium
            self.attendance_system.selenium_headless = new_headless

            new_mode = "Selenium无头模式" if new_use_selenium else "传统图像识别模式"

            # 保存配置到动态配置文件（永久生效）
            from modules.config import config
            config.set_selenium_config('USE_SELENIUM_LOGIN', new_use_selenium)
            config.set_selenium_config('SELENIUM_HEADLESS', new_headless)

            response_msg = (
                f"🔄 登录模式已切换\n\n"
                f"🔹 原模式: {current_mode}\n"
                f"🔹 新模式: {new_mode}\n\n"
                f"📝 说明:\n"
                f"• ✅ 配置已永久保存，重启后仍然有效\n"
                f"• 🤖 Selenium无头模式: 稳定高效，后台运行\n"
                f"• 🖼️ 传统图像识别: 轻量级，适合简单界面\n"
                f"• 📄 配置保存在 dynamic_config.json 文件中\n\n"
                f"🚀 现在可以使用新的登录模式进行打卡了！"
            )

            await update.message.reply_text(response_msg)

        except Exception as e:
            error_msg = f"切换登录模式时发生错误: {str(e)}"
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

            # 获取今日打卡记录（按用户分桶，组成显示行）
            user_records = self.attendance_system.today_punch_records
            if user_records:
                punch_record_lines = []
                for uname, record in user_records.items():
                    in_t = record.get('punch_in_time')
                    out_t = record.get('punch_out_time')
                    in_str = ('✅ ' + in_t.strftime('%H:%M:%S')) if in_t else '❌ 未打卡'
                    out_str = ('✅ ' + out_t.strftime('%H:%M:%S')) if out_t else '❌ 未打卡'
                    punch_record_lines.append(f"[{uname}] 上班：{in_str} | 下班：{out_str}")
                punch_record_block = "\n".join(punch_record_lines)
            else:
                punch_record_block = "（无用户配置）"

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
                f"{punch_record_block}\n\n"

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
                f"登录模式：{'🤖 Selenium无头模式' if self.attendance_system.use_selenium_login else '🖼️ 传统图像识别'}\n"
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
                    elif task['type'] == 'selenium_punch_out':
                        # M16/M17：让 Selenium 自动下班任务在 /status 中可见
                        next_run = datetime.strptime(task['scheduled_time'], "%H:%M").replace(
                            year=current_time.year,
                            month=current_time.month,
                            day=current_time.day
                        )
                        if next_run < current_time:
                            next_run = next_run + timedelta(days=1)
                        status_text += f"➤ [任务 #{task['id']}] Selenium下班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
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
            # M51: 日志原文常含不成对的 _ * [ 字符（函数名/路径/异常 repr），Markdown 解析会 400 失败，
            # 导致 /errors 在最需要时（确有错误日志）反而不可用。捕获 BadRequest 后降级为无 parse_mode 重发一次。
            try:
                await update.message.reply_text(log_message, parse_mode='Markdown', reply_markup=reply_markup)
            except BadRequest as md_err:
                logging.warning(f"错误日志 Markdown 解析失败，降级为纯文本重发: {md_err!r}")
                await update.message.reply_text(log_message, reply_markup=reply_markup)
        except Exception as e:
            error_msg = f"获取错误日志时发生异常: {str(e)}"
            logging.error(error_msg)
            await update.message.reply_text(f"获取错误日志失败: {str(e)}")

    async def send_message(self, title, content):
        """发送Telegram消息"""
        if self.attendance_system and not getattr(
                self.attendance_system, 'bot_available', True):
            logging.debug("Telegram Bot 当前不可用，跳过直接消息发送: %s", title)
            return False

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

                # Flood control：服务器已明确告知需等待的秒数，遵从 retry_after（而非固定短延迟反复撞限流）
                if isinstance(e, RetryAfter):
                    wait = getattr(e, 'retry_after', self.retry_delay) + 1
                    logging.warning(
                        f"发送Telegram消息触发限流 (尝试 {retry + 1}/{self.max_retries})，{wait}秒后重试"
                    )
                    if retry < self.max_retries - 1:
                        await asyncio.sleep(wait)
                        continue
                    return False

                # 检查是否是HTTPXRequest初始化错误
                if "HTTPXRequest" in error_msg and "not initialized" in error_msg:
                    error_msg = f"发送Telegram消息时发生HTTPXRequest错误 (尝试 {retry + 1}/{self.max_retries}): {error_msg}"
                    if self.attendance_system:
                        self.attendance_system.bot_available = False
                        self.attendance_system.bot_error = error_msg[:500]
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

                # Telegram 连续网络失败只降级 Bot；AI、GUI、调度器等主程序不应被连带重启。
                if self.connection_error_count >= self.max_connection_errors:
                    error_msg = "Telegram 网络错误次数过多，已标记为不可用并等待后台重连"
                    print(error_msg)
                    logging.critical(error_msg)
                    if self.attendance_system:
                        self.attendance_system.bot_available = False
                        self.attendance_system.bot_error = error_msg
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
                elif task['type'] == 'selenium_punch_out':
                    # M16/M17：Selenium 自动下班任务此前不显示、无法通过 UI 删除，这里补上
                    next_run = datetime.strptime(task['scheduled_time'], "%H:%M").replace(
                        year=datetime.now().year,
                        month=datetime.now().month,
                        day=datetime.now().day
                    )
                    if next_run < datetime.now():
                        next_run = next_run + timedelta(days=1)
                    message_text += f"➤ [任务 #{task['id']}] Selenium下班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
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
            # M17：只精准取消被删任务对应的 schedule job（按 per-task tag=task_{id} 定位），
            # 不再裸 clear 全类型后重建——避免重建版丢失 username、缺工作日/创建日守卫、
            # 不返回 CancelJob 导致每日重复打卡、以及 selenium_punch_out 任务被静默漏掉。
            # 其余任务的 job 原封不动留在 schedule 中，无需重载。
            schedule.clear(f'task_{task_id}')

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

            # bot 降级/未初始化时 app 为 None，提前返回避免 NoneType 崩溃
            if not self.app:
                return
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

            # bot 降级/未初始化时 app 为 None，提前返回避免 NoneType 崩溃
            if not self.app:
                return
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
                    # M17：只精准取消被删任务对应的 schedule job（按 per-task tag=task_{id} 定位），
                    # 不再裸 clear 全类型后重建——避免重建版丢失 username、缺工作日/创建日守卫、
                    # 不返回 CancelJob 导致每日重复打卡、以及 selenium_punch_out 任务被静默漏掉。
                    schedule.clear(f'task_{task_id}')

                    # 重新读取剩余任务，仅用于刷新下方任务列表展示（不再重载 schedule）
                    saved_tasks = self.attendance_system.task_manager.get_tasks()

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
                        elif remaining_task['type'] == 'selenium_punch_out':
                            # M16/M17：刷新列表时同样展示 Selenium 自动下班任务
                            next_run = datetime.strptime(remaining_task['scheduled_time'], "%H:%M").replace(
                                year=datetime.now().year,
                                month=datetime.now().month,
                                day=datetime.now().day
                            )
                            if next_run < datetime.now():
                                next_run = next_run + timedelta(days=1)
                            message_text += f"➤ [任务 #{remaining_task['id']}] Selenium下班打卡：{next_run.strftime('%Y-%m-%d %H:%M')}\n"
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
            elif query.data.startswith('settime_use_last_'):
                # 处理使用上次配置的回调
                punch_type = query.data.split('_')[-1]
                # M53: 60 秒超时后 setting_time_state 已被清理，但旧按钮仍可点击，
                # 直接下标访问会 KeyError 并报泛化错误。改为 .get() 判空后提示重新 /set_time 并移除旧按钮。
                state = self.setting_time_state.get(self.chat_id)
                if state is None:
                    await query.message.edit_text("⏰ 设置已超时，请重新使用 /set_time 设置")
                    return
                last_config = state.get('last_config')

                if last_config:
                    # 获取上次配置的用户名
                    username = last_config.get('username', 'all')

                    if last_config['mode'] == 'delay':
                        # 延迟模式：重新计算目标时间
                        delay_minutes = last_config.get('delay_minutes', 1)
                        target_time = datetime.now() + timedelta(minutes=delay_minutes)
                        await self._schedule_punch(punch_type, target_time.hour, target_time.minute, username)

                        # 保存新的配置
                        config_data = {
                            'type': punch_type,
                            'mode': 'delay',
                            'delay_minutes': delay_minutes,
                            'username': username
                        }
                        self._save_settime_config(config_data)

                        await query.message.edit_text(f"✅ 已使用上次配置！\n设置{delay_minutes}分钟后执行{punch_type}打卡")

                    else:
                        # 指定时间模式：使用相同的时间
                        hour = last_config.get('hour')
                        minute = last_config.get('minute')
                        await self._schedule_punch(punch_type, hour, minute, username)

                        # 保存新的配置
                        config_data = {
                            'type': punch_type,
                            'mode': 'specific',
                            'hour': hour,
                            'minute': minute,
                            'username': username
                        }
                        self._save_settime_config(config_data)

                        await query.message.edit_text(f"✅ 已使用上次配置！\n设置在 {hour:02d}:{minute:02d} 执行{punch_type}打卡")

                    # 清理状态
                    if self.chat_id in self.setting_time_state:
                        del self.setting_time_state[self.chat_id]
                    if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
                        self.setting_time_timer[self.chat_id].cancel()
                else:
                    await query.message.edit_text("❌ 未找到上次配置")

            elif query.data.startswith('daily_reminder_confirm_'):
                # 处理每日提醒确认
                punch_type = query.data.split('_')[-1]

                if self.daily_reminder_pending and self.daily_reminder_config:
                    config = self.daily_reminder_config

                    # 获取配置中的用户名
                    username = config.get('username', 'all')

                    if config['mode'] == 'delay':
                        # 延迟模式：基于当前时间重新计算
                        delay_minutes = config.get('delay_minutes', 1)
                        target_time = datetime.now() + timedelta(minutes=delay_minutes)
                        await self._schedule_punch(punch_type, target_time.hour, target_time.minute, username)

                        # 保存新的配置
                        config_data = {
                            'type': punch_type,
                            'mode': 'delay',
                            'delay_minutes': delay_minutes,
                            'username': username
                        }
                        self._save_settime_config(config_data)

                        await query.message.edit_text(
                            f"✅ 已确认使用昨日配置！\n"
                            f"⏰ 设置{delay_minutes}分钟后执行{punch_type}打卡\n"
                            f"📅 执行时间：{target_time.strftime('%H:%M')}"
                        )

                    else:
                        # 指定时间模式：使用相同的时间
                        hour = config.get('hour')
                        minute = config.get('minute')

                        # 判断当前时间是否已超过预计打卡时间
                        now = datetime.now()
                        target_time = datetime(now.year, now.month, now.day, hour, minute)

                        if now >= target_time:
                            # 当前时间已超过预计打卡时间，立即执行打卡
                            await query.message.edit_text(
                                f"⚠️ 当前时间已超过预计打卡时间 {hour:02d}:{minute:02d}\n"
                                f"⏰ 等待10秒后立即执行{punch_type}打卡..."
                            )

                            # 等待10秒
                            await asyncio.sleep(10)

                            try:
                                # 根据打卡类型执行相应的操作
                                # punch_in/out 返回单值(True/False/'cancelled')，不能按二元组解包
                                if punch_type == 'in':
                                    result = await self.attendance_system.punch_in()
                                else:
                                    result = await self.attendance_system.punch_out()

                                if result == 'cancelled':
                                    await query.message.edit_text(f"⚠️ {punch_type}打卡已被取消")
                                elif result is True:
                                    await query.message.edit_text(f"✅ {punch_type}打卡执行完成")
                                else:
                                    await query.message.edit_text(f"❌ {punch_type}打卡执行失败")

                                # 保存配置
                                config_data = {
                                    'type': punch_type,
                                    'mode': 'specific',
                                    'hour': hour,
                                    'minute': minute,
                                    'username': username
                                }
                                self._save_settime_config(config_data)

                            except Exception as e:
                                error_msg = f"执行{punch_type}打卡时发生错误: {str(e)}"
                                logging.error(error_msg)
                                await query.message.edit_text(f"❌ {error_msg}")
                        else:
                            # 当前时间早于预计打卡时间，正常设置定时任务
                            await self._schedule_punch(punch_type, hour, minute, username)

                            # 保存新的配置
                            config_data = {
                                'type': punch_type,
                                'mode': 'specific',
                                'hour': hour,
                                'minute': minute,
                                'username': username
                            }
                            self._save_settime_config(config_data)

                            await query.message.edit_text(
                                f"✅ 已确认使用昨日配置！\n"
                                f"⏰ 设置在 {hour:02d}:{minute:02d} 执行{punch_type}打卡"
                            )

                    # 清理状态
                    self.daily_reminder_pending = False
                    self.daily_reminder_config = None

                else:
                    await query.message.edit_text("❌ 提醒已过期，请使用 /set_time 手动设置")

            elif query.data == 'daily_reminder_cancel':
                # 取消每日提醒
                self.daily_reminder_pending = False
                self.daily_reminder_config = None
                await query.message.edit_text("👍 已取消，您可以稍后使用 /set_time 手动设置")

            elif query.data.startswith('settime_type_'):
                punch_type = query.data.split('_')[-1]
                # M53: 超时清理后点旧按钮会 KeyError，先判空提示
                state = self.setting_time_state.get(self.chat_id)
                if state is None:
                    await query.message.edit_text("⏰ 设置已超时，请重新使用 /set_time 设置")
                    return
                state['type'] = punch_type

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

                # M53: 超时清理后点旧按钮会 KeyError，先判空提示
                state = self.setting_time_state.get(self.chat_id)
                if state is None:
                    await query.message.edit_text("⏰ 设置已超时，请重新使用 /set_time 设置")
                    return
                state.update({
                    'mode': mode,
                    'step': 'input_delay' if mode == 'delay' else 'input_hour'
                })

                if mode == 'delay':
                    # 创建快速选择按钮
                    keyboard = [
                        [
                            InlineKeyboardButton("1分钟", callback_data=f'delay_quick_1_{punch_type}'),
                            InlineKeyboardButton("2分钟", callback_data=f'delay_quick_2_{punch_type}'),
                            InlineKeyboardButton("3分钟", callback_data=f'delay_quick_3_{punch_type}')
                        ],
                        [
                            InlineKeyboardButton("4分钟", callback_data=f'delay_quick_4_{punch_type}'),
                            InlineKeyboardButton("5分钟", callback_data=f'delay_quick_5_{punch_type}')
                        ],
                        [
                            InlineKeyboardButton("手动输入", callback_data=f'delay_manual_{punch_type}')
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await query.message.edit_text(
                        "请选择延迟时间：",
                        reply_markup=reply_markup
                    )
                else:
                    await query.message.edit_text("请输入小时数（0-23）：")

            # 处理用户选择回调
            elif query.data.startswith('settime_user_'):
                parts = query.data.split('_')
                # settime_user_{username} 或 settime_user_all
                if parts[2] == 'all':
                    username = 'all'
                else:
                    username = parts[2]

                # 从状态中获取配置信息
                # M53: 超时清理后点旧按钮会 KeyError，先判空提示
                state = self.setting_time_state.get(self.chat_id)
                if state is None:
                    await query.message.edit_text("⏰ 设置已超时，请重新使用 /set_time 设置")
                    return
                punch_type = state['type']
                mode = state['mode']
                hour = state['hour']
                minute = state['minute']

                # 执行调度
                await self._schedule_punch(punch_type, hour, minute, username)

                # 保存配置到历史记录
                config_data = {
                    'type': punch_type,
                    'mode': mode,
                    'hour': hour,
                    'minute': minute,
                    'username': username
                }

                # 如果是延时模式，添加延迟分钟数
                if mode == 'delay':
                    config_data['delay_minutes'] = state.get('delay_minutes', 0)

                self._save_settime_config(config_data)

                # 清理状态
                if self.chat_id in self.setting_time_state:
                    del self.setting_time_state[self.chat_id]
                if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
                    self.setting_time_timer[self.chat_id].cancel()

                # 显示确认消息
                user_text = "全部用户" if username == 'all' else username
                await query.message.edit_text(f"✅ 已为{user_text}设置{punch_type}打卡任务！")

            # 处理快速延时选择回调
            elif query.data.startswith('delay_quick_'):
                parts = query.data.split('_')
                delay_minutes = int(parts[2])
                punch_type = parts[3]

                # 计算目标时间并保存到状态
                # M53: 超时清理后点旧按钮会 KeyError，先判空提示
                state = self.setting_time_state.get(self.chat_id)
                if state is None:
                    await query.message.edit_text("⏰ 设置已超时，请重新使用 /set_time 设置")
                    return
                target_time = datetime.now() + timedelta(minutes=delay_minutes)
                state.update({
                    'delay_minutes': delay_minutes,
                    'hour': target_time.hour,
                    'minute': target_time.minute,
                    'step': 'select_user'
                })

                # 显示用户选择界面
                from modules.config import Config
                user_configs = Config.get_user_configs()

                # 创建用户选择按钮
                keyboard = []

                # 添加单个用户按钮（两个一行）
                user_row = []
                for user_config in user_configs:
                    username = user_config['username']
                    if username:  # 确保用户名存在
                        user_row.append(
                            InlineKeyboardButton(
                                username,
                                callback_data=f'settime_user_{username}'
                            )
                        )
                        # 每两个用户一行
                        if len(user_row) == 2:
                            keyboard.append(user_row)
                            user_row = []

                # 添加剩余的用户按钮
                if user_row:
                    keyboard.append(user_row)

                # 添加"全部一起"按钮
                keyboard.append([
                    InlineKeyboardButton(
                        "👥 全部一起",
                        callback_data=f'settime_user_all'
                    )
                ])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text(
                    f"⏰ 将在{delay_minutes}分钟后（{target_time.strftime('%H:%M')}）执行{punch_type}打卡\n\n请选择要为哪个用户设置：",
                    reply_markup=reply_markup
                )

            # 处理手动输入延时回调
            elif query.data.startswith('delay_manual_'):
                punch_type = query.data.split('_')[2]
                # M53: 超时清理后点旧按钮会 KeyError，先判空提示
                state = self.setting_time_state.get(self.chat_id)
                if state is None:
                    await query.message.edit_text("⏰ 设置已超时，请重新使用 /set_time 设置")
                    return
                state['step'] = 'input_delay'
                await query.message.edit_text("请输入要延迟的分钟数：")

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

                    # 计算时间差
                    current_time = datetime.now()
                    punch_out_datetime = datetime.strptime(punch_out_time, '%H:%M:%S').time()
                    today_punch_out = datetime.combine(current_time.date(), punch_out_datetime)

                    # 判断是立即执行还是设置定时任务
                    if current_time >= today_punch_out:
                        # 情况2：用户点击时间已晚于预计打卡时间，立即执行
                        await query.message.edit_text("🚀 检测到当前时间已到达或超过预计打卡时间，正在立即执行下班打卡...")

                        # 立即执行下班打卡
                        success, message = await self.attendance_system.start_punch_operation("punch_out")

                        if success:
                            await query.message.edit_text(
                                f"✅ 下班打卡操作已启动\n\n"
                                f"🕐 预计下班时间：{punch_out_time}\n"
                                f"⏰ 执行时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"📍 您可以使用 /status 查看进度"
                            )
                        else:
                            await query.message.edit_text(f"❌ {message}")
                    else:
                        # 情况1：用户点击时间早于预计打卡时间，设置定时任务
                        await query.message.edit_text("⏳ 正在设置定时任务...")

                        delay_minutes = int((today_punch_out - current_time).total_seconds() / 60)

                        # 设置定时任务
                        retry_time = await self.attendance_system.schedule_retry_punch_out(delay_minutes, clear_existing=False)

                        if retry_time:
                            success_message = (
                                f"✅ 自动下班打卡设置成功！\n\n"
                                f"🕐 下班时间：{punch_out_time}\n"
                                f"⏰ 执行时间：{today_punch_out.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"⏱️ 距离执行还有：{delay_minutes}分钟\n"
                                f"📋 任务已添加到定时任务列表\n\n"
                                f"💡 您可以使用 /status 查看任务状态"
                            )
                            await query.message.edit_text(success_message)

                            # 发送邮件通知
                            self._send_scheduled_task_email_notification(
                                punch_type="下班",
                                scheduled_time=today_punch_out.strftime('%Y-%m-%d %H:%M'),
                                task_type="自动下班"
                            )
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

            # 处理Selenium完整下班流程的确认按钮
            elif query.data.startswith('confirm_auto_punch_out:'):
                # 提取下班时间
                estimated_time = query.data.replace('confirm_auto_punch_out:', '')

                try:
                    # 验证时间格式 (HH:MM)
                    time_obj = datetime.strptime(estimated_time, '%H:%M')

                    # 计算目标时间
                    current_time = datetime.now()
                    target_time = datetime.combine(current_time.date(), time_obj.time())

                    # 判断是立即执行还是设置定时任务
                    if current_time >= target_time:
                        # 情况2：用户点击时间已晚于预计打卡时间，立即执行
                        await query.message.edit_text("🚀 检测到当前时间已到达或超过预计打卡时间，正在立即执行Selenium完整下班流程...")

                        # 创建伪 Update 对象以调用 _execute_selenium_complete_flow
                        fake_update = Update(update_id=update.callback_query.id, message=query.message)

                        # 立即执行Selenium完整下班流程
                        await self._execute_selenium_complete_flow(
                            fake_update,
                            flow_type="punch_out",
                            special_handler=self._handle_punch_out_time_confirmation
                        )

                    else:
                        # 情况1：用户点击时间早于预计打卡时间，设置定时任务
                        await query.message.edit_text("⏳ 正在设置自动下班任务...")

                        # 使用专用的Selenium自动下班任务设置方法
                        await self._schedule_selenium_punch_out(
                            target_time.hour,
                            target_time.minute,
                            estimated_time
                        )

                        delay_minutes = int((target_time - current_time).total_seconds() / 60)
                        success_message = (
                            f"✅ Selenium自动下班打卡设置成功！\n\n"
                            f"🕐 预计下班时间：{estimated_time}\n"
                            f"⏰ 执行时间：{target_time.strftime('%Y-%m-%d %H:%M')}\n"
                            f"⏱️ 距离执行还有：{delay_minutes}分钟\n"
                            f"🔧 任务类型：Selenium完整下班流程\n"
                            f"📋 任务已添加到定时任务列表\n\n"
                            f"💡 您可以使用 /kill 查看和管理任务"
                        )
                        await query.message.edit_text(success_message)

                        # 发送邮件通知
                        self._send_scheduled_task_email_notification(
                            punch_type="下班",
                            scheduled_time=target_time.strftime('%Y-%m-%d %H:%M'),
                            task_type="Selenium自动下班"
                        )

                except ValueError:
                    await query.message.edit_text("❌ 时间格式错误，操作已取消")
                except Exception as e:
                    error_msg = f"设置自动下班任务时发生错误: {str(e)}"
                    logging.error(error_msg)
                    await query.message.edit_text(f"❌ {error_msg}")

            elif query.data == 'cancel_auto_punch_out':
                await query.message.edit_text("❌ 自动下班打卡设置已取消")

            # 处理获取上班时间的回调（打开浏览器）
            elif query.data == 'fetch_punch_in_time':
                await query.message.edit_text("🕐 正在通过浏览器获取当日上班打卡时间...")

                try:
                    # 通过浏览器获取当日上班打卡时间
                    success, punch_in_time, message = await self.attendance_system.get_today_punch_in_time_auto()

                    if not success:
                        await query.message.edit_text(f"❌ 获取上班时间失败：{message}")
                        return

                    # 使用辅助方法处理上班时间并显示确认
                    await self._process_punch_in_time_and_confirm(query, punch_in_time)

                except Exception as e:
                    error_msg = f"获取上班时间时发生错误: {str(e)}"
                    logging.error(error_msg)
                    await query.message.edit_text(f"❌ {error_msg}")

            # 处理手动输入上班时间的回调
            elif query.data == 'manual_input_punch_in_time':
                # 设置状态为等待输入上班时间
                self.setting_time_state[self.chat_id] = {
                    'step': 'input_punch_in_time',
                    'source': 'auto_trigger'  # 标记来源是自动触发
                }

                # 设置超时
                if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
                    self.setting_time_timer[self.chat_id].cancel()
                self.setting_time_timer[self.chat_id] = asyncio.create_task(self._cancel_settime_timeout(self.chat_id))

                await query.message.edit_text(
                    "⏰ 请输入上班打卡时间\n\n"
                    "格式：HH:MM（如 08:30 或 08：30）\n"
                    "支持中英文冒号"
                )

            elif query.data.startswith('auto_trigger_confirm_'):
                # 16:35自动触发确认设置任务
                punch_out_time = query.data.split('_')[-1]

                try:
                    # 解析时间，处理可能包含秒数的格式
                    time_parts = punch_out_time.split(':')
                    if len(time_parts) >= 2:
                        hour, minute = int(time_parts[0]), int(time_parts[1])
                        logging.info(f"解析16:35自动下班时间: {punch_out_time} -> {hour:02d}:{minute:02d}")
                    else:
                        raise ValueError(f"时间格式无效: {punch_out_time}")

                    # 计算时间差，判断是立即执行还是设置定时任务
                    current_time = datetime.now()
                    today_punch_out = datetime(current_time.year, current_time.month, current_time.day, hour, minute)

                    # 判断是立即执行还是设置定时任务
                    if current_time >= today_punch_out:
                        # 情况2：用户点击时间已晚于或等于预计打卡时间，立即执行
                        await query.message.edit_text("🚀 检测到当前时间已到达或超过预计打卡时间，正在立即执行下班打卡...")

                        # 立即执行下班打卡
                        success, message = await self.attendance_system.start_punch_operation("punch_out")

                        if success:
                            await query.message.edit_text(
                                f"✅ 下班打卡操作已启动\n\n"
                                f"🕐 预计下班时间：{punch_out_time}\n"
                                f"⏰ 执行时间：{current_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"📍 您可以使用 /status 查看进度"
                            )
                        else:
                            await query.message.edit_text(f"❌ {message}")
                    else:
                        # 情况1：用户点击时间早于预计打卡时间，设置定时任务
                        await query.message.edit_text("⏳ 正在设置定时任务...")

                        # 使用attendance_system设置定时任务
                        success = await self.attendance_system.schedule_punch_out(hour, minute)

                        if success:
                            delay_minutes = int((today_punch_out - current_time).total_seconds() / 60)
                            success_message = (
                                f"✅ 16:35自动下班任务设置成功！\n\n"
                                f"🎯 下班打卡时间：{punch_out_time}\n"
                                f"⏰ 执行时间：{today_punch_out.strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"⏱️ 距离执行还有：{delay_minutes}分钟\n"
                                f"📋 任务已添加到定时任务列表\n\n"
                                f"💡 您可以使用 /status 查看任务状态"
                            )
                            await query.message.edit_text(success_message)

                            # 发送邮件通知
                            self._send_scheduled_task_email_notification(
                                punch_type="下班",
                                scheduled_time=today_punch_out.strftime('%Y-%m-%d %H:%M'),
                                task_type="16:35自动下班"
                            )
                        else:
                            await query.message.edit_text("❌ 设置定时任务失败，请稍后重试")

                except ValueError:
                    await query.message.edit_text("❌ 时间格式错误，操作已取消")
                except Exception as e:
                    error_msg = f"设置16:35自动下班任务时发生错误: {str(e)}"
                    logging.error(error_msg)
                    await query.message.edit_text(f"❌ {error_msg}")

            elif query.data == 'auto_trigger_cancel':
                await query.message.edit_text("❌ 已取消16:35自动下班设置")

            elif query.data.startswith('auto_trigger_immediate_'):
                # 16:35自动触发立即执行
                punch_out_time = query.data.split('_')[-1]
                
                await query.message.edit_text("⏰ 等待10秒后开始执行下班打卡...")
                
                # 等待10秒
                await asyncio.sleep(10)
                
                try:
                    # 直接执行下班打卡；punch_out 返回单值(True/False/'cancelled')，不能按二元组解包
                    result = await self.attendance_system.punch_out()

                    if result == 'cancelled':
                        await query.message.edit_text("⚠️ 16:35自动下班打卡已被取消")
                    elif result is True:
                        await query.message.edit_text("✅ 16:35自动下班打卡执行完成")
                    else:
                        await query.message.edit_text("❌ 16:35自动下班打卡执行失败")

                except Exception as e:
                    error_msg = f"执行16:35自动下班打卡时发生错误: {str(e)}"
                    logging.error(error_msg)
                    await query.message.edit_text(f"❌ {error_msg}")

        except Exception as e:
            error_msg = f"处理按钮回调时发生错误: {str(e)}"
            logging.error(error_msg)
            await query.message.reply_text(error_msg)

    async def start_polling(self, drop_pending_updates=True):
        """启动消息轮询

        drop_pending_updates: 首次启动丢弃积压更新（默认 True）；
        重启场景（restart_polling）传 False，避免丢弃重启窗口内用户发出的打卡命令（见 M52）。
        """
        if self.is_polling:
            return

        self.is_polling = True
        try:
            # 使用更大的连接池和更长的超时时间
            await self.app.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=drop_pending_updates,
                # PTB 默认 -1 会在 bootstrap 阶段无限重试，导致启动/重连永久占锁；
                # 单次失败交给外层指数退避恢复循环处理。
                bootstrap_retries=0,
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
        updater = getattr(self.app, 'updater', None) if self.app is not None else None
        try:
            updater_running = bool(updater is not None and getattr(updater, 'running', False))
        except Exception:
            updater_running = self.is_polling
        if not self.is_polling and not updater_running:
            return

        try:
            # 检查updater是否存在且正在运行
            if updater is not None and updater_running:
                try:
                    await updater.stop()
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
        """重启消息轮询；成功返回 True，失败返回 False。"""
        # 与 reconnect 共用 _reconnect_lock，确保重启与重连互斥，避免并发清理同一 app
        async with self._reconnect_lock:
            logging.info("正在重启 Telegram Bot 轮询...")
            await self.stop_polling()

            # 置空前先停止并关闭旧应用，避免 update_fetcher 后台任务泄漏
            if self.app:
                try:
                    await self.app.stop()
                    await self.app.shutdown()
                except Exception as e:
                    logging.warning(f"重启前停止旧应用失败: {e!r}")

            # 标记需要重新初始化
            self._is_initialized = False
            self.app = None
            # 重置每日提醒任务标志，确保重新初始化时会重新设置任务
            self.daily_reminder_task_set = False

            await asyncio.sleep(5)  # 等待5秒后重启

            try:
                # 使用_ensure_app_initialized来重新创建应用
                await self._ensure_app_initialized()

                if self.app:
                    await self.app.start()
                    # M52: 重启窗口内用户可能已发出打卡命令，drop_pending_updates=False 避免被直接丢弃
                    await self.start_polling(drop_pending_updates=False)
                else:
                    logging.error("重启轮询失败：应用初始化失败")
                    return False

            except Exception as e:
                logging.error(f"重启轮询失败: {str(e)}")
                return False

            self.last_update_time = datetime.now()
            logging.info("Telegram Bot 轮询重启完成")
            return True

    async def _on_error(self, update, context):
        """Telegram 全局错误处理器：统一记录更新处理过程中的未捕获异常"""
        logging.error("Telegram 更新处理异常", exc_info=getattr(context, 'error', None))

    async def reconnect(self, force=True) -> tuple[bool, str]:
        """主动重连 Telegram Bot：停止旧轮询/应用，彻底重建后重新启动。

        供 GUI 重连端点调用；与 restart_polling 共用 _reconnect_lock 串行化，避免并发清理。
        force=False 供后台恢复/监控使用：等待锁期间若另一协程已恢复健康，则不重复拆建连接。
        """
        async with self._reconnect_lock:
            try:
                updater = getattr(self.app, 'updater', None) if self.app is not None else None
                already_healthy = bool(
                    self._is_initialized
                    and self.app is not None
                    and self.is_polling
                    and updater is not None
                    and getattr(updater, 'running', False)
                    and getattr(self.attendance_system, 'bot_available', False)
                )
                if not force and already_healthy:
                    return True, "Bot 已连接"

                await self.stop_polling()
                if self.app:
                    try:
                        await self.app.stop()
                        await self.app.shutdown()
                    except Exception as e:
                        logging.warning(f"重连：清理旧 app 失败 {e!r}")
                self._is_initialized = False
                self.app = None
                self.daily_reminder_task_set = False
                await self._ensure_app_initialized()
                if not self.app:
                    raise RuntimeError("Bot 初始化失败：应用未创建")
                await self.app.start()
                await self.start_polling()
                self.last_update_time = datetime.now()
                if self.attendance_system:
                    self.attendance_system.bot_available = True
                    self.attendance_system.bot_error = None
                logging.info("Telegram Bot 重连成功")
                return True, "Bot 重连成功"
            except Exception as e:
                logging.error(f"Bot 重连失败: {e!r}", exc_info=True)
                # 失败也按 updater -> Application -> initialize 状态的顺序彻底收口，
                # 避免半启动对象在下一轮重连时留下旧 getUpdates 任务。
                try:
                    await self.stop_polling()
                except Exception:
                    pass
                app = self.app
                if app is not None:
                    try:
                        await app.stop()
                    except Exception:
                        pass
                    try:
                        await app.shutdown()
                    except Exception:
                        pass
                self._is_initialized = False
                self.is_polling = False
                self.app = None
                self.daily_reminder_task_set = False
                message = f"Bot 重连失败: {e}"
                if self.attendance_system:
                    self.attendance_system.bot_available = False
                    self.attendance_system.bot_error = message[:500]
                return False, message

    async def monitor_connection(self):
        """监控连接状态。

        超时（update_timeout）只代表"长时间没有 incoming 更新"，单用户长时间不发命令时这属正常空闲，
        不能据此直接重启。故先用 get_me() 主动探测：探测成功=连接健康（仅刷新计时、不重启）；探测失败
        才完整重连。app 缺失、轮询停止或已标记降级时也会进入同一路径，并对连续失败做指数退避。
        """
        monitor_fail_count = 0  # 连续探测/重连失败计数，用于指数退避
        while True:
            try:
                updater = getattr(self.app, 'updater', None) if self.app is not None else None
                updater_running = bool(updater is not None and getattr(updater, 'running', False))
                bot_available = bool(getattr(self.attendance_system, 'bot_available', False))

                # 完整检查四层状态，避免 app=None / bot_available=False 后监控永久跳过恢复。
                if not bot_available or self.app is None or not self.is_polling or not updater_running:
                    monitor_fail_count += 1
                    logging.warning(
                        "Telegram Bot 状态不完整，尝试第 %d 次完整重连",
                        monitor_fail_count,
                    )
                    ok, msg = await self.reconnect(force=False)
                    if ok:
                        if self.attendance_system:
                            self.attendance_system.bot_available = True
                            self.attendance_system.bot_error = None
                        self.connection_error_count = 0
                        monitor_fail_count = 0
                        logging.info("Telegram Bot 连接监控已恢复轮询")
                    else:
                        if self.attendance_system:
                            self.attendance_system.bot_available = False
                            self.attendance_system.bot_error = str(msg)[:500]
                        backoff = min(60 * (2 ** (monitor_fail_count - 1)), 600)
                        logging.warning("Telegram Bot 重连失败，%d 秒后重试: %s", backoff, msg)
                        await asyncio.sleep(backoff)
                        continue

                elif self.last_update_time:
                    time_since_last_update = (datetime.now() - self.last_update_time).total_seconds()
                    if time_since_last_update > self.update_timeout:
                        try:
                            await self.app.bot.get_me()
                            self.last_update_time = datetime.now()
                            monitor_fail_count = 0
                        except Exception as probe_err:
                            monitor_fail_count += 1
                            logging.warning(
                                "已经 %.0f 秒没有收到更新且健康探测失败（第 %d 次）: %r",
                                time_since_last_update, monitor_fail_count, probe_err,
                            )
                            if self.attendance_system:
                                self.attendance_system.bot_available = False
                                self.attendance_system.bot_error = str(probe_err)[:500]
                            ok, msg = await self.reconnect(force=False)
                            if ok:
                                if self.attendance_system:
                                    self.attendance_system.bot_available = True
                                    self.attendance_system.bot_error = None
                                self.connection_error_count = 0
                                monitor_fail_count = 0
                            else:
                                if self.attendance_system:
                                    self.attendance_system.bot_error = str(msg)[:500]
                                backoff = min(60 * (2 ** (monitor_fail_count - 1)), 600)
                                await asyncio.sleep(backoff)
                                continue

                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logging.error(f"监控连接时发生错误: {str(e)}")
                await asyncio.sleep(60)

    def run(self, attendance_system):
        """运行机器人"""
        self.attendance_system = attendance_system

        # 配置应用程序，添加连接池和超时设置
        self.app = self._build_application()

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

    async def test_reminder_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/test_reminder命令 - 测试8:15每日提醒功能"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return
        
        try:
            await update.message.reply_text("🧪 开始测试8:15每日提醒功能...")
            
            # 1. 验证任务设置
            reminder_status = self.verify_daily_reminder_setup()
            status_text = "✅ 任务设置正确" if reminder_status else "❌ 任务设置异常"
            await update.message.reply_text(f"📋 任务设置检查: {status_text}")
            
            # 2. 显示当前任务信息
            all_jobs = schedule.get_jobs()
            reminder_jobs = [job for job in all_jobs if "daily_reminder_job" in str(job.job_func)]
            
            if reminder_jobs:
                for i, job in enumerate(reminder_jobs):
                    next_run = job.next_run.strftime('%Y-%m-%d %H:%M:%S') if job.next_run else "未知"
                    await update.message.reply_text(f"📅 提醒任务 #{i+1}: 下次执行时间: {next_run}")
            else:
                await update.message.reply_text("⚠️ 未找到8:15提醒任务")
            
            # 3. 测试提醒功能
            await update.message.reply_text("🔄 正在测试提醒功能...")
            
            try:
                await self._send_daily_reminder_with_retry(max_retries=1)
                await update.message.reply_text("✅ 提醒功能测试成功！")
            except Exception as e:
                await update.message.reply_text(f"❌ 提醒功能测试失败: {str(e)}")
            
            # 4. 显示系统状态
            total_jobs = len(all_jobs)
            await update.message.reply_text(f"📊 系统状态:\n- 总定时任务数: {total_jobs}\n- 8:15提醒任务: {'正常' if reminder_status else '异常'}")
            
        except Exception as e:
            logging.error(f"测试8:15提醒功能时发生错误: {e}")
            await update.message.reply_text(f"❌ 测试过程中发生错误: {str(e)}")

    async def settime_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """处理/settime命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        # 获取上次配置
        last_config = self._get_last_config()
        
        # 创建基础按钮
        keyboard = [
            [
                InlineKeyboardButton("设置上班时间", callback_data='settime_type_in'),
                InlineKeyboardButton("设置下班时间", callback_data='settime_type_out')
            ]
        ]
        
        # 构建消息文本
        message_text = "请选择要设置的打卡类型："
        
        # 如果有上次配置，添加快速设置选项
        if last_config:
            config_date = datetime.strptime(last_config['config_date'], '%Y-%m-%d').strftime('%m-%d')
            config_type_text = "上班打卡" if last_config['type'] == 'in' else "下班打卡"

            # 获取用户信息
            username = last_config.get('username', 'all')  # 默认为 'all' 以兼容旧配置
            if username == 'all':
                user_text = "全部一起打卡"
                user_detail = "👥 用户：全部一起"
            else:
                user_text = f"仅{username}"
                user_detail = f"👤 用户：{username}"

            # 构建详细的配置描述
            if last_config['mode'] == 'delay':
                delay_minutes = last_config.get('delay_minutes', '?')
                config_desc = f"延迟{delay_minutes}分钟{config_type_text}，{user_text}"
                detail_info = (
                    f"📅 日期：{config_date}\n"
                    f"📝 类型：{config_type_text}\n"
                    f"⏰ 模式：延时执行\n"
                    f"⏱️ 延迟：{delay_minutes}分钟\n"
                    f"{user_detail}"
                )
            else:
                hour = last_config.get('hour', '?')
                minute = last_config.get('minute', '?')
                config_desc = f"指定时间{hour:02d}:{minute:02d}{config_type_text}，{user_text}"
                detail_info = (
                    f"📅 日期：{config_date}\n"
                    f"📝 类型：{config_type_text}\n"
                    f"⏰ 模式：指定时间\n"
                    f"🕐 设定时间：{hour:02d}:{minute:02d}\n"
                    f"{user_detail}"
                )

            # 添加上次配置快速选择按钮
            keyboard.insert(0, [
                InlineKeyboardButton(
                    f"🔄 使用上次配置({config_desc})",
                    callback_data=f'settime_use_last_{last_config["type"]}'
                )
            ])

            message_text = f"🕐 检测到上次配置:\n{detail_info}\n\n{message_text}"
        
        reply_markup = InlineKeyboardMarkup(keyboard)

        # 初始化状态
        self.setting_time_state[self.chat_id] = {
            'step': 'select_type',
            'type': None,
            'mode': None,
            'hour': None,
            'minute': None,
            'last_config': last_config
        }

        # 设置1分钟超时
        if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
            self.setting_time_timer[self.chat_id].cancel()
        self.setting_time_timer[self.chat_id] = asyncio.create_task(self._cancel_settime_timeout(self.chat_id))

        await update.message.reply_text(
            message_text,
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

                # 计算目标时间并保存到状态
                target_time = datetime.now() + timedelta(minutes=delay_minutes)
                state.update({
                    'delay_minutes': delay_minutes,
                    'hour': target_time.hour,
                    'minute': target_time.minute,
                    'step': 'select_user'
                })

                # 显示用户选择界面
                from modules.config import Config
                user_configs = Config.get_user_configs()

                # 创建用户选择按钮
                keyboard = []

                # 添加单个用户按钮（两个一行）
                user_row = []
                for user_config in user_configs:
                    username = user_config['username']
                    if username:  # 确保用户名存在
                        user_row.append(
                            InlineKeyboardButton(
                                username,
                                callback_data=f'settime_user_{username}'
                            )
                        )
                        # 每两个用户一行
                        if len(user_row) == 2:
                            keyboard.append(user_row)
                            user_row = []

                # 添加剩余的用户按钮
                if user_row:
                    keyboard.append(user_row)

                # 添加"全部一起"按钮
                keyboard.append([
                    InlineKeyboardButton(
                        "👥 全部一起",
                        callback_data=f'settime_user_all'
                    )
                ])

                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"⏰ 将在{delay_minutes}分钟后（{target_time.strftime('%H:%M')}）执行{state['type']}打卡\n\n请选择要为哪个用户设置：",
                    reply_markup=reply_markup
                )

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
                    # 保存分钟数到状态
                    state.update({
                        'minute': minute,
                        'step': 'select_user'
                    })

                    # 显示用户选择界面
                    from modules.config import Config
                    user_configs = Config.get_user_configs()

                    # 创建用户选择按钮
                    keyboard = []

                    # 添加单个用户按钮（两个一行）
                    user_row = []
                    for user_config in user_configs:
                        username = user_config['username']
                        if username:  # 确保用户名存在
                            user_row.append(
                                InlineKeyboardButton(
                                    username,
                                    callback_data=f'settime_user_{username}'
                                )
                            )
                            # 每两个用户一行
                            if len(user_row) == 2:
                                keyboard.append(user_row)
                                user_row = []

                    # 添加剩余的用户按钮
                    if user_row:
                        keyboard.append(user_row)

                    # 添加"全部一起"按钮
                    keyboard.append([
                        InlineKeyboardButton(
                            "👥 全部一起",
                            callback_data=f'settime_user_all'
                        )
                    ])

                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(
                        f"⏰ 将在{state['hour']:02d}:{minute:02d}执行{state['type']}打卡\n\n请选择要为哪个用户设置：",
                        reply_markup=reply_markup
                    )
                else:
                    await update.message.reply_text("请输入0-59之间的数字")
            except ValueError:
                await update.message.reply_text("请输入有效的数字")

        elif state['step'] == 'input_punch_in_time':
            try:
                # 处理中英文冒号
                time_text = text.replace('：', ':').strip()

                # 验证时间格式 (HH:MM)
                try:
                    time_obj = datetime.strptime(time_text, '%H:%M')
                    punch_in_time = time_obj.strftime('%H:%M')

                    # 验证时间范围
                    hour = time_obj.hour
                    minute = time_obj.minute

                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        await update.message.reply_text("❌ 时间超出有效范围\n请输入有效的时间（00:00-23:59）")
                        return

                    # 清理状态
                    del self.setting_time_state[self.chat_id]
                    if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
                        self.setting_time_timer[self.chat_id].cancel()

                    # 使用辅助方法处理上班时间并显示确认
                    await self._process_punch_in_time_and_confirm(update, punch_in_time)

                except ValueError:
                    await update.message.reply_text(
                        "❌ 时间格式错误\n\n"
                        "请按照以下格式输入：\n"
                        "HH:MM（如 08:30 或 08：30）"
                    )

            except Exception as e:
                error_msg = f"处理上班时间输入时发生错误: {str(e)}"
                logging.error(error_msg)
                await update.message.reply_text(f"❌ {error_msg}")

                # 清理状态
                if self.chat_id in self.setting_time_state:
                    del self.setting_time_state[self.chat_id]
                if self.chat_id in self.setting_time_timer and self.setting_time_timer[self.chat_id] is not None:
                    self.setting_time_timer[self.chat_id].cancel()

    async def _schedule_selenium_punch_out(self, hour, minute, estimated_time):
        """设置Selenium自动下班打卡任务"""
        time_str = f"{hour:02d}:{minute:02d}"
        target_time = datetime.strptime(time_str, "%H:%M").replace(
            year=datetime.now().year,
            month=datetime.now().month,
            day=datetime.now().day
        )

        # 如果设置的时间已经过去，就设置为明天的这个时间
        if target_time < datetime.now():
            target_time = target_time + timedelta(days=1)

        # 删除已有的Selenium下班任务
        saved_tasks = self.attendance_system.task_manager.get_tasks()
        for task in saved_tasks:
            if task['type'] == 'selenium_punch_out':
                self.attendance_system.task_manager.remove_task_by_id(task['id'])

        # 添加新的Selenium下班任务
        task_id = self.attendance_system.task_manager.add_task(
            task_type="selenium_punch_out",
            scheduled_time=time_str
        )

        # 定义Selenium下班任务执行函数
        async def selenium_punch_out_job():
            try:
                await self.send_message(
                    "⏰ Selenium自动下班",
                    f"开始执行Selenium自动下班打卡（预计时间：{estimated_time}）"
                )

                # M16：原来到点调用 selenium_complete_punch_out_command(None)，
                # 该处理器签名为 (update, context)，少传一个参数必抛 TypeError；即便补上，
                # update=None 也会在 update.message.chat_id 处抛 AttributeError —— 定时
                # Selenium 自动下班从未成功过。改为直接调用与 update 无关的内部执行函数
                # _execute_selenium_complete_flow，并传入一个能向本聊天 reply/编辑消息的
                # 载体（_ScheduledMessageCarrier），与手动命令走同一套流程逻辑。
                await self._ensure_app_initialized()
                if not self.app:
                    raise RuntimeError("Telegram 应用未初始化，无法执行 Selenium 自动下班")
                carrier = self._ScheduledMessageCarrier(self, self.chat_id)
                await self._execute_selenium_complete_flow(
                    carrier,
                    flow_type="punch_out",
                    special_handler=self._handle_punch_out_time_confirmation
                )

            except Exception as e:
                error_msg = f"Selenium自动下班执行失败: {str(e)}"
                logging.error(error_msg)
                await self.send_message("❌ 自动下班失败", error_msg)
            finally:
                # 执行完后删除任务
                self.attendance_system.task_manager.remove_task_by_id(task_id)
                # M16：schedule.every().day 会每天重复触发，故执行后按 per-task tag 自清，
                # 避免每日同一时间重复执行失败/打卡（CancelJob 在本仓 create_task 包装下不生效）。
                schedule.clear(f'task_{task_id}')

        # 使用schedule库设置定时任务（打上类型 tag + per-task tag，使 /kill 可见可删，
        # 且 attendance_system 的按 tag 清理不会误伤——本任务用独立 tag selenium_punch_out_scheduled）
        schedule.every().day.at(time_str).do(lambda: asyncio.create_task(selenium_punch_out_job())).tag('selenium_punch_out_scheduled', f'task_{task_id}')

        logging.info(f"已设置Selenium自动下班任务: {target_time.strftime('%Y-%m-%d %H:%M')}")

    class _ScheduledMessageCarrier:
        """定时 Selenium 流程用的轻量消息载体（M16）。

        _execute_selenium_complete_flow 依赖 update.message.reply_text / reply_photo，
        且把 reply_text 的返回值当作可 edit_text 的消息使用。定时任务无 update 对象，
        故用本载体把这些调用转发到 self.app.bot，并让 reply_text 返回真实的 Telegram
        Message（其自带 edit_text），从而完全复用手动命令的流程。
        """

        def __init__(self, bot, chat_id):
            self._bot = bot
            self._chat_id = chat_id
            # 暴露 message 属性，行为与 Update.message 一致（reply_text/reply_photo）
            self.message = self

        async def reply_text(self, text, **kwargs):
            # 返回真实 Message 对象，后续 .edit_text(...) 可直接生效
            return await self._bot.app.bot.send_message(chat_id=self._chat_id, text=text, **kwargs)

        async def reply_photo(self, photo, **kwargs):
            return await self._bot.app.bot.send_photo(chat_id=self._chat_id, photo=photo, **kwargs)

    async def _schedule_punch(self, punch_type, hour, minute, username=None):
        """设置定时打卡任务

        Args:
            punch_type: 打卡类型 ('in', 'out', '上班', '下班')
            hour: 小时 (0-23)
            minute: 分钟 (0-59)
            username: 用户名（可选）。'all' 表示所有用户，具体用户名表示单个用户，None 表示默认用户
        """
        from modules.config import Config

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

        # 仅清除本类型(上班/下班)已注册的定时打卡 job，避免裸 schedule.clear() 误杀
        # daily_status / exchange_rate_update / ai_news_update / daily_reminder /
        # 以及另一类型(上班/下班)的定时打卡 job（否则会静默漏打卡）。
        # tag 命名与 attendance_system.init_schedule_tasks 保持一致。
        schedule.clear('punch_in_scheduled' if task_type == 'punch_in' else 'punch_out_scheduled')

        # 如果是"全部一起"，为每个用户创建独立任务
        if username == 'all':
            user_configs = Config.get_user_configs()
            task_ids = []

            for user_config in user_configs:
                user_name = user_config['username']
                if user_name:  # 确保用户名存在
                    # 为每个用户添加任务
                    task_id = self.attendance_system.task_manager.add_task(
                        task_type=task_type,
                        scheduled_time=time_str,
                        username=user_name
                    )
                    task_ids.append((task_id, user_name))

            # 创建统一的任务执行函数
            # 额外为该 job 打上每个用户任务的 per-task tag（task_{id}），
            # 使 /kill 删除单个任务时只需 schedule.clear(f'task_{id}') 精准取消本 job，
            # 不再裸 clear 全类型后重建（M17：重建会丢 username/守卫且漏 selenium 任务）。
            per_task_tags = [f'task_{tid}' for tid, _ in task_ids]
            if task_type == "punch_in":
                async def punch_in_job():
                    # 调用punch_in()不传username参数，表示为所有用户打卡
                    await self.attendance_system.punch_in()
                    # 执行完后删除所有任务
                    for task_id, _ in task_ids:
                        self.attendance_system.task_manager.remove_task_by_id(task_id)
                    # 一次性任务：执行后按本类型 tag 自删。注意 return schedule.CancelJob 在本仓
                    # do(lambda: asyncio.create_task(...)) 包装下不生效（scheduler 拿到的是 Task），
                    # 故用 schedule.clear(本类型 tag) 自清，既实现一次性语义又不误伤其它 job。
                    schedule.clear('punch_in_scheduled')
                schedule.every().day.at(time_str).do(lambda: asyncio.create_task(punch_in_job())).tag('punch_in_scheduled', *per_task_tags)
            else:
                async def punch_out_job():
                    # 调用punch_out()不传username参数，表示为所有用户打卡
                    await self.attendance_system.punch_out()
                    # 执行完后删除所有任务
                    for task_id, _ in task_ids:
                        self.attendance_system.task_manager.remove_task_by_id(task_id)
                    # 一次性任务：执行后按本类型 tag 自删。注意 return schedule.CancelJob 在本仓
                    # do(lambda: asyncio.create_task(...)) 包装下不生效（scheduler 拿到的是 Task），
                    # 故用 schedule.clear(本类型 tag) 自清，既实现一次性语义又不误伤其它 job。
                    schedule.clear('punch_out_scheduled')
                schedule.every().day.at(time_str).do(lambda: asyncio.create_task(punch_out_job())).tag('punch_out_scheduled', *per_task_tags)

            user_list = "、".join([name for _, name in task_ids])
            await self.send_message("设置成功", f"已为所有用户（{user_list}）设置在 {target_time.strftime('%Y-%m-%d %H:%M')} 自动{display_type}打卡")

            # 发送邮件通知
            self._send_scheduled_task_email_notification(
                punch_type=display_type,
                scheduled_time=target_time.strftime('%Y-%m-%d %H:%M'),
                username='all',
                task_type="定时打卡"
            )

        else:
            # 单个用户或默认用户
            task_id = self.attendance_system.task_manager.add_task(
                task_type=task_type,
                scheduled_time=time_str,
                username=username
            )

            # 同样打上 per-task tag（task_{id}），供 /kill 精准取消本 job（M17）。
            per_task_tag = f'task_{task_id}'
            if task_type == "punch_in":
                async def punch_in_job():
                    # 传递username参数，只为指定用户打卡
                    await self.attendance_system.punch_in(username)
                    # 执行完后删除任务
                    self.attendance_system.task_manager.remove_task_by_id(task_id)
                    # 一次性任务：执行后按本类型 tag 自删。注意 return schedule.CancelJob 在本仓
                    # do(lambda: asyncio.create_task(...)) 包装下不生效（scheduler 拿到的是 Task），
                    # 故用 schedule.clear(本类型 tag) 自清，既实现一次性语义又不误伤其它 job。
                    schedule.clear('punch_in_scheduled')
                schedule.every().day.at(time_str).do(lambda: asyncio.create_task(punch_in_job())).tag('punch_in_scheduled', per_task_tag)
            else:
                async def punch_out_job():
                    # 传递username参数，只为指定用户打卡
                    await self.attendance_system.punch_out(username)
                    # 执行完后删除任务
                    self.attendance_system.task_manager.remove_task_by_id(task_id)
                    # 一次性任务：执行后按本类型 tag 自删。注意 return schedule.CancelJob 在本仓
                    # do(lambda: asyncio.create_task(...)) 包装下不生效（scheduler 拿到的是 Task），
                    # 故用 schedule.clear(本类型 tag) 自清，既实现一次性语义又不误伤其它 job。
                    schedule.clear('punch_out_scheduled')
                schedule.every().day.at(time_str).do(lambda: asyncio.create_task(punch_out_job())).tag('punch_out_scheduled', per_task_tag)

            user_info = f"（{username}）" if username else ""
            await self.send_message("设置成功", f"已设置在 {target_time.strftime('%Y-%m-%d %H:%M')} 自动{display_type}打卡{user_info}")

            # 发送邮件通知
            self._send_scheduled_task_email_notification(
                punch_type=display_type,
                scheduled_time=target_time.strftime('%Y-%m-%d %H:%M'),
                username=username,
                task_type="定时打卡"
            )

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

    async def _execute_selenium_complete_flow(self, update, flow_type: str, special_handler=None):
        """执行Selenium完整打卡流程的通用方法"""
        flow_name = "上班" if flow_type == "punch_in" else "下班"

        # 发送初始消息
        status_message = await update.message.reply_text(f"🔧 Selenium完整{flow_name}打卡流程开始...")
        message_content = f"🔧 Selenium完整{flow_name}打卡流程开始...\n"

        try:
            # 更新状态：创建控制器
            message_content += "📋 正在创建Selenium控制器...\n"
            await status_message.edit_text(message_content)

            # 创建通知回调，用于更新消息
            async def notification_callback(context: str, msg: str):
                nonlocal message_content
                message_content += f"[{context}] {msg}\n"
                try:
                    await status_message.edit_text(message_content)
                except:
                    pass  # 忽略编辑失败

            selenium_controller = SeleniumLoginController(
                login_url=config.LOGIN_URL,
                headless=config.get_selenium_headless(),
                notification_callback=notification_callback
            )

            # 执行完整打卡流程
            message_content += f"🚀 开始执行完整{flow_name}打卡流程...\n"
            await status_message.edit_text(message_content)

            # 根据流程类型选择对应的方法
            if flow_type == "punch_in":
                success, message_result, flow_data = await selenium_controller.complete_punch_in_flow(
                    username=config.LOGIN_USERNAME,
                    password=config.LOGIN_PASSWORD
                )
            else:  # punch_out
                success, message_result, flow_data = await selenium_controller.complete_punch_out_flow(
                    username=config.LOGIN_USERNAME,
                    password=config.LOGIN_PASSWORD
                )

            # 更新状态：流程完成
            if success:
                message_content += f"✅ 完整{flow_name}流程成功: {message_result}\n"

                # 显示详细结果
                if flow_data:
                    punch_result = flow_data.get('punch_result', {})
                    if punch_result.get('punched'):
                        message_content += f"✅ {flow_name}打卡已执行\n"
                    elif punch_result.get('already_punched'):
                        message_content += f"ℹ️ 之前已打过{flow_name}卡\n"

                    # 调用特殊处理函数（如下班打卡的时间确认）
                    if special_handler:
                        message_content = await special_handler(update, message_content, flow_data)

                    # 显示考勤状态
                    attendance_status = flow_data.get('attendance_status', {})
                    if attendance_status.get('today'):
                        message_content += f"📅 今日状态: {attendance_status['today']}\n"
            else:
                message_content += f"❌ 完整{flow_name}流程失败: {message_result}\n"

            # 更新状态：获取截图
            message_content += "📸 正在获取页面截图...\n"
            await status_message.edit_text(message_content)

            # 截取最终状态截图
            screenshot = selenium_controller.take_screenshot()

            if screenshot:
                message_content += "✅ 截图获取成功\n"
                await status_message.edit_text(message_content)
                await update.message.reply_photo(photo=screenshot, caption=f"Selenium完整{flow_name}打卡流程结果截图")
            else:
                message_content += "⚠️ 无法获取截图\n"
                await status_message.edit_text(message_content)

            # 关闭浏览器（正常路径提示；真正的释放统一放到 finally 兜底，避免重复关闭副作用）
            message_content += "🔒 正在关闭浏览器...\n"
            await status_message.edit_text(message_content)

            message_content += "✅ 完整流程完成！"
            await status_message.edit_text(message_content)

        except Exception as e:
            message_content += f"❌ 发生错误: {str(e)}\n"
            try:
                await status_message.edit_text(message_content)
                if 'selenium_controller' in locals():
                    screenshot = selenium_controller.take_screenshot()
                    if screenshot:
                        await update.message.reply_photo(photo=screenshot, caption=f"Selenium完整{flow_name}流程异常截图")
            except:
                pass
        finally:
            # M50: 无论正常完成还是任意一步抛异常（流程失败/截图/reply_photo/edit_text 超长或网络错误等），
            # 都要释放 WebDriver，避免 msedgedriver/浏览器进程残留导致孤儿进程泄漏
            if 'selenium_controller' in locals():
                try:
                    selenium_controller.close()
                except Exception as close_err:
                    logging.warning(f"关闭Selenium控制器时发生错误: {close_err!r}")

    async def _handle_punch_out_time_confirmation(self, update, message_content: str, flow_data: dict) -> str:
        """处理下班打卡的时间确认逻辑"""
        time_calculation = flow_data.get('time_calculation')
        if time_calculation and time_calculation.get('confirmation_needed'):
            message_content += "⚠️ 检测到工作时间不足\n"
            message_content += f"⏰ 预计下班时间: {time_calculation['estimated_off_time']}\n"
            message_content += f"📊 已工作: {time_calculation['worked_minutes']}分钟\n"
            message_content += f"📊 还需: {time_calculation['remaining_minutes']}分钟\n"

            # 创建确认按钮
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [
                [
                    InlineKeyboardButton(
                        f"✅ 确认设置自动下班({time_calculation['estimated_off_time']})",
                        callback_data=f"confirm_auto_punch_out:{time_calculation['estimated_off_time']}"
                    )
                ],
                [
                    InlineKeyboardButton("❌ 取消", callback_data="cancel_auto_punch_out")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                f"🔔 检测到工作时间不足，是否设置自动下班？\n"
                f"⏰ 预计下班时间: {time_calculation['estimated_off_time']}\n"
                f"📊 当前已工作: {time_calculation['worked_minutes']}分钟\n"
                f"📊 还需工作: {time_calculation['remaining_minutes']}分钟",
                reply_markup=reply_markup
            )
        return message_content

    async def selenium_complete_punch_in_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Selenium完整上班打卡流程命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        await self._execute_selenium_complete_flow(
            update,
            flow_type="punch_in"
        )

    async def selenium_complete_punch_out_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Selenium完整下班打卡流程命令"""
        if str(update.message.chat_id) != self.chat_id:
            await update.message.reply_text("您没有权限使用此机器人")
            return

        await self._execute_selenium_complete_flow(
            update,
            flow_type="punch_out",
            special_handler=self._handle_punch_out_time_confirmation
        )

    def _save_settime_config(self, config_data):
        """保存settime配置到历史记录"""
        try:
            # 读取现有历史记录
            history = self._load_settime_history()
            
            # 添加今日配置
            today = datetime.now().strftime('%Y-%m-%d')
            history[today] = {
                'type': config_data['type'],
                'mode': config_data['mode'],
                'timestamp': datetime.now().isoformat(),
                **config_data
            }
            
            # 只保留最近30天的记录
            cutoff_date = datetime.now() - timedelta(days=30)
            history = {
                date: data for date, data in history.items()
                if datetime.strptime(date, '%Y-%m-%d') >= cutoff_date
            }
            
            # 保存到文件
            with open(self.settime_history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
                
            logging.info(f"已保存settime配置: {config_data}")
            
        except Exception as e:
            logging.error(f"保存settime配置失败: {e}")

    def _load_settime_history(self):
        """加载settime历史记录"""
        try:
            if os.path.exists(self.settime_history_file):
                with open(self.settime_history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logging.error(f"加载settime历史记录失败: {e}")
            return {}

    def _get_last_config(self):
        """获取上一次的settime配置"""
        try:
            history = self._load_settime_history()
            if not history:
                return None
            
            # 获取最近一次的配置（按日期排序）
            sorted_dates = sorted(history.keys(), reverse=True)
            if sorted_dates:
                last_date = sorted_dates[0]
                last_config = history[last_date].copy()
                last_config['config_date'] = last_date  # 添加配置日期信息
                return last_config
            return None
        except Exception as e:
            logging.error(f"获取上次配置失败: {e}")
            return None

    def _send_scheduled_task_email_notification(self, punch_type: str, scheduled_time: str,
                                                 username: str = None, task_type: str = "定时打卡"):
        """发送定时任务设置成功的邮件通知（只发给老婆，用趣味版文案）

        Args:
            punch_type: 打卡类型（"上班" 或 "下班"）
            scheduled_time: 计划执行时间
            username: 用户名（可选）
            task_type: 任务类型描述
        """
        try:
            # 文案里的"我的 / 你的 / 咱俩的"：'all' 只有在老婆账号也启用时才算两个人
            if username == config.WIFE_LOGIN_NAME:
                who = 'her'
            elif username == 'all' and any(
                    u.get('username') == config.WIFE_LOGIN_NAME for u in config.get_user_configs()):
                who = 'both'
            else:
                who = 'me'

            subject, body = wife_email.build_task_scheduled(punch_type, scheduled_time, task_type, who)
            if email_service.send_to_wife(subject, body):
                logging.info(f"已发送定时任务设置通知邮件: {punch_type}打卡 @ {scheduled_time}")

        except Exception as e:
            logging.error(f"发送定时任务设置通知邮件失败: {e}")

    def _setup_daily_reminder(self):
        """设置每日8:15提醒任务和16:35自动下班任务"""
        try:
            # 检查任务是否真实存在（不仅依赖标志）
            existing_reminder_jobs = [job for job in schedule.jobs if hasattr(job, 'job_func') and job.job_func.__name__ in ['daily_reminder_job', 'auto_trigger_autobyebye_job']]

            # 如果标志为True但任务不存在，说明任务丢失，需要重新设置
            if self.daily_reminder_task_set and existing_reminder_jobs:
                logging.debug("每日提醒任务已设置且存在，跳过重复设置")
                return

            # 如果标志为True但任务不存在，重置标志
            if self.daily_reminder_task_set and not existing_reminder_jobs:
                logging.warning("检测到每日提醒任务标志为True但任务不存在，重新设置任务")
                self.daily_reminder_task_set = False

            # 清理所有现有的每日提醒任务（避免累积）
            jobs_to_remove = []
            for job in schedule.jobs:
                if hasattr(job, 'job_func') and job.job_func.__name__ in ['daily_reminder_job', 'auto_trigger_autobyebye_job']:
                    jobs_to_remove.append(job)

            for job in jobs_to_remove:
                schedule.cancel_job(job)
                logging.debug("清理了重复的每日提醒/自动下班任务")
            
            # 检查是否为工作日的函数
            def is_work_day():
                try:
                    return is_workday(datetime.now().date())
                except NotImplementedError as e:
                    # 如果年份不支持（chinese_calendar库数据范围外），降级为简单的周末判断
                    logging.warning(f"chinese_calendar不支持当前年份: {e}, 降级使用周末判断")
                    weekday = datetime.now().weekday()
                    return weekday < 5  # 周一到周五(0-4)为工作日
            
            # 创建8:15提醒任务（增强版，支持重试）
            def daily_reminder_job():
                current_time = datetime.now()
                logging.info(f"8:15提醒任务触发 - 当前时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logging.info("8:15提醒任务触发 - 检查是否为工作日")
                work_day_result = is_work_day()
                logging.info(f"工作日判断结果: {work_day_result}")
                # M91: schedule 1.2.1 唤醒后会补跑错过的任务。睡过 08:15 下午唤醒会收到「早上好」+「确认使用上次配置」按钮，
                # 下午点击会按点击时间重算定时、排出无意义任务。此处加时间窗：偏离预定 08:15 超过 1 小时时只发提示、不触发可执行交互。
                scheduled_today = current_time.replace(hour=8, minute=15, second=0, microsecond=0)
                if abs((current_time - scheduled_today).total_seconds()) > 3600:
                    logging.info("当前时间已大幅偏离 08:15（疑似睡眠唤醒补跑），仅发送提示消息，不触发每日提醒交互")
                    if work_day_result:
                        asyncio.create_task(self.send_message(
                            "例行任务提示",
                            "⏰ 已错过 8:15 每日提醒（疑似睡眠唤醒后补跑）\n如需设置今日打卡，请手动使用 /set_time"
                        ))
                    return None
                if work_day_result:
                    logging.info("确认为工作日，启动每日提醒任务")
                    try:
                        task = asyncio.create_task(self._send_daily_reminder_with_retry())
                        logging.info("8:15每日提醒任务已创建并启动（带重试机制）")
                        return task
                    except Exception as e:
                        logging.error(f"创建8:15每日提醒任务失败: {e}")
                        # 记录失败但不抛出异常，避免影响其他任务
                        logging.error(f"将在5分钟后重试8:15提醒任务")
                        # 设置一个5分钟后的重试任务
                        retry_time = (current_time + timedelta(minutes=5)).strftime("%H:%M")
                        try:
                            schedule.every().day.at(retry_time).do(lambda: asyncio.create_task(self._send_daily_reminder_with_retry())).tag('daily_reminder_retry')
                            logging.info(f"已设置重试任务在 {retry_time} 执行")
                        except Exception as retry_e:
                            logging.error(f"设置重试任务失败: {retry_e}")
                        return None
                else:
                    logging.info("非工作日，跳过每日提醒任务")
                    return None
            
            # 创建16:35自动下班任务
            def auto_trigger_autobyebye_job():
                current_time = datetime.now()
                logging.info("16:35自动下班任务触发 - 检查是否为工作日")
                work_day_result = is_work_day()
                # M91: 睡过 16:35 深夜/次日唤醒会补跑本任务，若当日已有上班记录则给出「✅ 立即执行下班打卡」按钮，
                # 用户在错误时段一键点击会真实打卡。此处加时间窗：偏离预定 16:35 超过 1 小时时只发提示、不带可执行按钮。
                scheduled_today = current_time.replace(hour=16, minute=35, second=0, microsecond=0)
                if abs((current_time - scheduled_today).total_seconds()) > 3600:
                    logging.info("当前时间已大幅偏离 16:35（疑似睡眠唤醒补跑），仅发送提示消息，不触发自动下班检测")
                    if work_day_result:
                        asyncio.create_task(self.send_message(
                            "例行任务提示",
                            "⏰ 已错过 16:35 自动下班检测（疑似睡眠唤醒后补跑）\n如需下班打卡，请手动使用 /auto_byebye 或 /punch_out"
                        ))
                    return
                if work_day_result:
                    logging.info("确认为工作日，启动16:35自动下班任务")
                    asyncio.create_task(self._auto_trigger_autobyebye())
                else:
                    logging.info("非工作日，跳过16:35自动下班任务")

            # 每天8:15执行提醒任务
            reminder_job = schedule.every().day.at("08:15").do(daily_reminder_job)
            # 每天16:35执行自动下班任务
            autobyebye_job = schedule.every().day.at("16:35").do(auto_trigger_autobyebye_job)
            
            self.daily_reminder_task_set = True
            
            # 详细日志记录
            next_reminder_run = reminder_job.next_run
            next_autobyebye_run = autobyebye_job.next_run
            
            logging.info(f"已设置每日8:15提醒任务和16:35自动下班任务")
            logging.info(f"8:15提醒任务下次执行时间: {next_reminder_run}")
            logging.info(f"16:35自动下班任务下次执行时间: {next_autobyebye_run}")
            logging.info(f"当前schedule任务总数: {len(schedule.jobs)}")
            
        except Exception as e:
            logging.error(f"设置每日提醒任务失败: {e}")
    
    def verify_daily_reminder_setup(self):
        """验证每日提醒任务设置是否正确"""
        try:
            all_jobs = schedule.get_jobs()
            reminder_jobs = [job for job in all_jobs if "daily_reminder_job" in str(job.job_func)]

            if not reminder_jobs:
                logging.warning("未找到8:15每日提醒任务，重置标志并尝试重新设置...")
                # 重置标志以确保可以重新设置
                self.daily_reminder_task_set = False
                self._setup_daily_reminder()
                # 再次验证
                all_jobs = schedule.get_jobs()
                reminder_jobs = [job for job in all_jobs if "daily_reminder_job" in str(job.job_func)]
                if not reminder_jobs:
                    logging.error("重新设置后仍未找到8:15每日提醒任务")
                    return False
                else:
                    logging.info("8:15每日提醒任务重新设置成功")
                    return True
            
            # 检查8:15提醒任务的下次执行时间
            for job in reminder_jobs:
                next_run = job.next_run
                if next_run:
                    next_run_time = next_run.strftime("%H:%M")
                    if next_run_time == "08:15":
                        logging.info(f"✅ 8:15每日提醒任务设置正确，下次执行时间: {next_run}")
                        return True
                    else:
                        logging.warning(f"⚠️ 8:15提醒任务时间不正确: {next_run_time}")
            
            logging.warning("8:15每日提醒任务可能设置不正确")
            return False
            
        except Exception as e:
            logging.error(f"验证每日提醒任务设置时发生错误: {e}")
            return False

    async def _send_daily_reminder_with_retry(self, max_retries=3):
        """发送每日提醒（带重试机制）"""
        for attempt in range(max_retries):
            try:
                logging.info(f"尝试发送每日提醒 (第{attempt + 1}次尝试)")
                await self._send_daily_reminder()
                logging.info("每日提醒发送成功")
                # 清理可能存在的重试任务
                self._clear_retry_reminder_tasks()
                return
            except Exception as e:
                logging.error(f"发送每日提醒失败 (第{attempt + 1}次尝试): {e}")
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2  # 递增等待时间：2, 4, 6秒
                    logging.info(f"等待{wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    logging.error("所有重试尝试都失败，放弃发送每日提醒")
    
    def _clear_retry_reminder_tasks(self):
        """清理重试提醒任务"""
        try:
            # 移除所有带有 'daily_reminder_retry' 标签的任务
            schedule.clear('daily_reminder_retry')
            logging.info("已清理重试提醒任务")
        except Exception as e:
            logging.error(f"清理重试提醒任务失败: {e}")

    async def _send_daily_reminder(self):
        """发送每日提醒"""
        async with self.daily_reminder_lock:
            try:
                current_time = datetime.now()
                logging.info(f"开始执行每日提醒任务 - 当前时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                last_config = self._get_last_config()
                
                if last_config:
                    config_date = datetime.strptime(last_config['config_date'], '%Y-%m-%d').strftime('%m-%d')
                    config_type_text = "上班打卡" if last_config['type'] == 'in' else "下班打卡"
                    
                    # 构建详细的配置描述
                    if last_config['mode'] == 'delay':
                        delay_minutes = last_config.get('delay_minutes', '?')
                        config_desc = f"延迟{delay_minutes}分钟{config_type_text}"
                        detail_info = (
                            f"📅 日期：{config_date}\n"
                            f"📝 类型：{config_type_text}\n" 
                            f"⏰ 模式：延时执行\n"
                            f"⏱️ 延迟：{delay_minutes}分钟"
                        )
                    else:
                        hour = last_config.get('hour', '?')
                        minute = last_config.get('minute', '?')
                        config_desc = f"指定时间{hour:02d}:{minute:02d}{config_type_text}"
                        detail_info = (
                            f"📅 日期：{config_date}\n"
                            f"📝 类型：{config_type_text}\n"
                            f"⏰ 模式：指定时间\n"
                            f"🕐 设定时间：{hour:02d}:{minute:02d}"
                        )
                    
                    # 创建确认按钮
                    keyboard = [
                        [
                            InlineKeyboardButton(
                                f"✅ 确认使用上次配置",
                                callback_data=f'daily_reminder_confirm_{last_config["type"]}'
                            )
                        ],
                        [
                            InlineKeyboardButton("❌ 稍后手动设置", callback_data="daily_reminder_cancel")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    message_text = (
                        f"🌅 早上好！今天是工作日\n\n"
                        f"📋 检测到上次配置详情：\n"
                        f"{detail_info}\n\n"
                        f"是否使用上次配置进行定时设置？\n"
                        f"💡 您可以随时点击确认，系统将根据点击时间重新计算"
                    )
                    
                    # 设置状态，用于后续确认处理
                    self.daily_reminder_config = last_config
                    self.daily_reminder_pending = True
                    
                    await self.send_message_with_reply_markup("每日定时提醒", message_text, reply_markup)
                    
                else:
                    # 没有上次配置，发送常规提醒
                    await self.send_message(
                        "每日提醒", 
                        "🌅 早上好！今天是工作日\n\n请记得设置打卡时间 /set_time"
                    )
                
                logging.info("每日提醒发送完成")
                    
            except Exception as e:
                logging.error(f"发送每日提醒失败: {e}")

    async def _auto_trigger_autobyebye(self):
        """16:35自动触发autobyebye功能"""
        try:
            current_time = datetime.now()
            logging.info(f"开始执行16:35自动下班任务 - 当前时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 获取当日上班打卡时间，检查是否有早上打卡记录
            success, punch_in_time, message = await self.attendance_system.get_today_punch_in_time_auto()
            
            if not success:
                # 没有早上打卡记录，询问用户如何获取上班时间
                keyboard = [
                    [
                        InlineKeyboardButton("✅ 可以，打开浏览器获取", callback_data='fetch_punch_in_time')
                    ],
                    [
                        InlineKeyboardButton("⏰ 不可以，我手动输入时间", callback_data='manual_input_punch_in_time')
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)

                message_text = (
                    f"🕐 16:35自动下班检测\n\n"
                    f"❌ 本地无上班打卡记录\n\n"
                    f"📝 需要获取上班时间以计算下班时间\n\n"
                    f"💡 是否可以打开浏览器获取上班时间？"
                )

                await self.send_message_with_reply_markup("自动下班检测", message_text, reply_markup)
                logging.info("发送上班时间获取确认消息完成")
                return
            
            # 有早上打卡记录，计算下班时间并发送确认消息
            calc_success, punch_out_time, calc_message = self.attendance_system.calculate_punch_out_time(punch_in_time)
            
            if not calc_success:
                await self.send_message("自动下班检测", f"❌ 计算下班时间失败：{calc_message}")
                return
            
            # 检查当前时间与计算的下班时间的关系，实现动态确认逻辑
            current_time = datetime.now()
            
            # 处理不同的时间格式（可能包含秒数）
            try:
                if ':' in punch_out_time and len(punch_out_time.split(':')) == 3:
                    # 格式：HH:MM:SS
                    punch_out_datetime = datetime.strptime(f"{current_time.strftime('%Y-%m-%d')} {punch_out_time}", '%Y-%m-%d %H:%M:%S')
                else:
                    # 格式：HH:MM
                    punch_out_datetime = datetime.strptime(f"{current_time.strftime('%Y-%m-%d')} {punch_out_time}", '%Y-%m-%d %H:%M')
                
                logging.info(f"解析下班时间成功: {punch_out_time} -> {punch_out_datetime}")
                
            except ValueError as e:
                logging.error(f"解析下班时间失败: {punch_out_time}, 错误: {e}")
                await self.send_message("自动下班检测", f"❌ 下班时间格式解析失败：{punch_out_time}")
                return
            
            if current_time < punch_out_datetime:
                # 当前时间早于下班时间，显示确认按钮（任务安排模式）
                keyboard = [
                    [
                        InlineKeyboardButton("✅ 确认设置自动下班", callback_data=f'auto_trigger_confirm_{punch_out_time}'),
                        InlineKeyboardButton("❌ 取消", callback_data='auto_trigger_cancel')
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                confirm_message = (
                    f"🎯 16:35自动下班检测\n\n"
                    f"✅ 检测到今日早上打卡时间：{punch_in_time}\n"
                    f"🕐 {calc_message}\n"
                    f"⏰ 工作时长：8小时15分钟 + 1-3分钟随机延迟\n\n"
                    f"💡 确认后将自动设置定时任务，到时间后自动执行下班打卡。\n\n"
                    f"请选择操作："
                )
                
                await self.send_message_with_reply_markup("自动下班检测", confirm_message, reply_markup)
                
            else:
                # 当前时间已超过下班时间，显示倒计时并立即执行
                keyboard = [
                    [
                        InlineKeyboardButton("✅ 立即执行下班打卡", callback_data=f'auto_trigger_immediate_{punch_out_time}'),
                        InlineKeyboardButton("❌ 取消", callback_data='auto_trigger_cancel')
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                overtime_message = (
                    f"🎯 16:35自动下班检测\n\n"
                    f"✅ 检测到今日早上打卡时间：{punch_in_time}\n"
                    f"🕐 计算下班时间：{punch_out_time}\n"
                    f"⚠️ 当前已超过计算的下班时间\n\n"
                    f"💡 确认后将等待10秒开始执行下班打卡\n\n"
                    f"请选择操作："
                )
                
                await self.send_message_with_reply_markup("自动下班检测", overtime_message, reply_markup)
            
            end_time = datetime.now()
            logging.info(f"16:35自动下班任务执行完成 - 结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        except Exception as e:
            error_time = datetime.now()
            logging.error(f"执行16:35自动下班任务失败 - 错误时间: {error_time.strftime('%Y-%m-%d %H:%M:%S')}, 错误: {e}")
            await self.send_message("自动下班检测", f"❌ 16:35自动下班检测失败：{str(e)}")

    async def _process_punch_in_time_and_confirm(self, query_or_update, punch_in_time: str):
        """
        处理上班时间并显示下班打卡确认

        Args:
            query_or_update: CallbackQuery 或 Update 对象
            punch_in_time: 上班打卡时间字符串 (格式: HH:MM 或 HH:MM:SS)
        """
        try:
            # 计算下班时间
            calc_success, punch_out_time, calc_message = self.attendance_system.calculate_punch_out_time(punch_in_time)

            if not calc_success:
                error_msg = f"❌ 计算下班时间失败：{calc_message}"
                # M18：telegram.Update 同样有 message 属性，原 hasattr(x,'message') 对 Update
                # 也为 True，会误走 CallbackQuery 分支去 edit_text 用户自己发的文本消息（Telegram
                # 报 BadRequest），导致手动输入上班时间流程必然失败。改用 isinstance(x, Update) 区分：
                # Update（用户消息）走 reply_text，CallbackQuery（bot 自己的消息）走 edit_text。
                if isinstance(query_or_update, Update):
                    # Update
                    await query_or_update.message.reply_text(error_msg)
                else:
                    # CallbackQuery
                    await query_or_update.message.edit_text(error_msg)
                return

            # 创建确认按钮
            keyboard = [
                [
                    InlineKeyboardButton("✅ 确认设置", callback_data=f'auto_byebye_confirm_{punch_out_time}'),
                    InlineKeyboardButton("❌ 取消", callback_data='auto_byebye_cancel')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # 构建确认消息
            confirm_message = (
                f"🎯 自动下班打卡设置\n\n"
                f"📍 上班时间：{punch_in_time}\n"
                f"🕐 {calc_message}\n"
                f"⏰ 工作时长：8小时15分钟 + 1-3分钟随机延迟\n\n"
                f"💡 确认后将自动设置定时任务或立即执行（根据当前时间判断）\n\n"
                f"请选择操作："
            )

            # 发送确认消息（M18：同上，用 isinstance(x, Update) 区分用户消息/回调消息）
            if isinstance(query_or_update, Update):
                # Update
                await query_or_update.message.reply_text(confirm_message, reply_markup=reply_markup)
            else:
                # CallbackQuery
                await query_or_update.message.edit_text(confirm_message, reply_markup=reply_markup)

        except Exception as e:
            error_msg = f"❌ 处理上班时间时发生错误: {str(e)}"
            logging.error(f"_process_punch_in_time_and_confirm 错误: {e}")
            if isinstance(query_or_update, Update):
                await query_or_update.message.reply_text(error_msg)
            else:
                await query_or_update.message.edit_text(error_msg)

    async def send_message_with_reply_markup(self, title, content, reply_markup):
        """发送带有回复标记的消息"""
        try:
            # 确保应用已初始化；仍不可用则降级为不带按钮的普通消息（避免 NoneType 崩溃）
            await self._ensure_app_initialized()
            if not self.app:
                return await self.send_message(title, content)
            await self.app.bot.send_message(
                chat_id=self.chat_id,
                text=f"**{title}**\n\n{content}",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logging.error(f"发送消息失败: {e}")
            # 降级为普通消息
            await self.send_message(title, content)

    def clear_duplicate_reminder_tasks(self):
        """清理重复的每日提醒任务"""
        try:
            jobs_to_remove = []
            reminder_jobs_count = 0
            
            for job in schedule.jobs:
                if hasattr(job, 'job_func') and job.job_func.__name__ == 'daily_reminder_job':
                    reminder_jobs_count += 1
                    if reminder_jobs_count > 1:  # 保留第一个，删除其余的
                        jobs_to_remove.append(job)
            
            for job in jobs_to_remove:
                schedule.cancel_job(job)
                
            if jobs_to_remove:
                logging.warning(f"清理了 {len(jobs_to_remove)} 个重复的每日提醒任务")
                
            logging.info(f"当前活跃的每日提醒任务数量: {reminder_jobs_count - len(jobs_to_remove)}")
            
        except Exception as e:
            logging.error(f"清理重复提醒任务失败: {e}")

    def reset_daily_reminder_state(self):
        """重置每日提醒状态（紧急修复用）"""
        try:
            # 清理所有每日提醒任务
            jobs_to_remove = []
            for job in schedule.jobs:
                if hasattr(job, 'job_func') and job.job_func.__name__ == 'daily_reminder_job':
                    jobs_to_remove.append(job)
            
            for job in jobs_to_remove:
                schedule.cancel_job(job)
            
            # 重置状态
            self.daily_reminder_task_set = False
            self.daily_reminder_sent_date = None
            self.daily_reminder_pending = False
            self.daily_reminder_config = None
            
            logging.info(f"已重置每日提醒状态，清理了 {len(jobs_to_remove)} 个任务")
            
        except Exception as e:
            logging.error(f"重置每日提醒状态失败: {e}")
