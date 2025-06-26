#!/usr/bin/env python3
"""
自动打卡系统 - 桌面GUI客户端主程序
提供完整的图形化界面，替代Web界面
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import asyncio
import sys
import os
import logging
import time
from datetime import datetime
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 导入系统模块
from main import AttendanceSystem, TelegramBot
from tasks import TaskManager
from punch_records import PunchRecordManager
try:
    from .widgets.main_window import MainWindow
    from .utils.gui_utils import set_window_icon, center_window
    from .integrated_watchdog import IntegratedWatchdog
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    from gui_client.widgets.main_window import MainWindow
    from gui_client.utils.gui_utils import set_window_icon, center_window
    from gui_client.integrated_watchdog import IntegratedWatchdog

class AttendanceGUIApp:
    """自动打卡系统GUI应用主类"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("自动打卡系统")
        self.root.geometry("1000x700")
        
        # 设置窗口图标和居中显示
        set_window_icon(self.root, "templates/logo/mm.png")
        center_window(self.root, 1000, 700)
        
        # 初始化系统组件
        self.attendance_system = None
        self.telegram_bot = None
        self.event_loop = None
        self.system_thread = None
        
        # 系统运行状态：stopped, starting, running, stopping
        self.system_status = "stopped"
        self.system_running = False  # 保持向后兼容
        
        # 系统托盘相关
        self.tray_icon = None
        self.is_hidden = False
        # 双击检测相关
        self.last_click_time = 0
        self.double_click_threshold = 0.5  # 双击时间阈值（秒）
        
        # 集成看门狗
        self.integrated_watchdog = None
        # 看门狗状态：disabled, starting, running, stopping, error
        self.watchdog_status = "disabled"
        
        # 创建主窗口
        self.main_window = MainWindow(self.root, self)
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        
        # 启动时自动开始系统
        self.root.after(1000, self.auto_start_system)
        
        # 配置日志
        self.setup_logging()
        
        # 初始化集成看门狗
        self.init_integrated_watchdog()
        
    def setup_logging(self):
        """配置日志系统"""
        # 确保日志目录存在
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 配置日志格式 (仅文件输出，避免命令行输出)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(log_dir, 'gui_client.log'), encoding='utf-8')
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("GUI客户端启动")
        
        # 创建系统托盘
        if TRAY_AVAILABLE:
            self.create_tray_icon()
        else:
            self.logger.warning("pystray未安装，无法使用系统托盘功能")
    
    def init_integrated_watchdog(self):
        """初始化集成看门狗"""
        try:
            self.integrated_watchdog = IntegratedWatchdog(self)
            self.logger.info("集成看门狗已初始化")
            
            # 延迟启动看门狗，等待GUI完全初始化
            self.root.after(2000, self.start_integrated_watchdog)
            
        except Exception as e:
            self.logger.error(f"初始化集成看门狗失败: {e}")
    
    def start_integrated_watchdog(self):
        """启动集成看门狗"""
        try:
            if self.watchdog_status in ["starting", "running"]:
                self.logger.warning(f"看门狗已在运行或启动中，当前状态: {self.watchdog_status}")
                return
                
            # 设置启动中状态
            self.set_watchdog_status("starting")
            
            if self.integrated_watchdog:
                success = self.integrated_watchdog.start()
                if success:
                    self.logger.info("集成看门狗已启动")
                    self.set_watchdog_status("running")
                else:
                    self.logger.warning("集成看门狗启动失败")
                    self.set_watchdog_status("error")
            else:
                self.logger.error("集成看门狗对象不存在")
                self.set_watchdog_status("error")
        except Exception as e:
            self.logger.error(f"启动集成看门狗失败: {e}")
            self.set_watchdog_status("error")
    
    def set_system_status(self, status):
        """设置系统运行状态"""
        old_status = self.system_status
        self.system_status = status
        
        # 更新system_running以保持向后兼容
        self.system_running = (status == "running")
        
        self.logger.info(f"系统状态变更: {old_status} -> {status}")
        
        # 更新GUI显示
        if hasattr(self.main_window, 'set_system_running'):
            self.main_window.set_system_running(self.system_running)
            
        # 更新状态文本显示
        status_text = {
            "stopped": "系统已停止",
            "starting": "系统启动中...",
            "running": "系统运行中",
            "stopping": "系统关闭中..."
        }.get(status, f"未知状态: {status}")
        
        if hasattr(self.main_window, 'update_status'):
            self.main_window.update_status(status_text)
    
    def set_watchdog_status(self, status):
        """设置看门狗状态"""
        old_status = self.watchdog_status
        self.watchdog_status = status
        
        self.logger.info(f"看门狗状态变更: {old_status} -> {status}")
        
        # 更新GUI显示
        if hasattr(self.main_window, 'update_watchdog_status'):
            # 创建状态对象用于显示
            watchdog_display_status = {
                'enabled': status not in ['disabled', 'error'],
                'running': status == 'running',
                'status_text': status,
                'restart_count': getattr(self.integrated_watchdog, 'restart_count', 0) if self.integrated_watchdog else 0,
                'max_restarts': getattr(self.integrated_watchdog, 'max_restarts', 10) if self.integrated_watchdog else 10,
                'health_status': getattr(self.integrated_watchdog, 'health_status', {}) if self.integrated_watchdog else {}
            }
            self.main_window.update_watchdog_status(watchdog_display_status)
    
    def get_system_status(self):
        """获取当前系统状态"""
        return {
            'status': self.system_status,
            'running': self.system_running,
            'attendance_system': self.attendance_system is not None,
            'telegram_bot': self.telegram_bot is not None,
            'event_loop_running': self.event_loop and self.event_loop.is_running() if self.event_loop else False
        }
    
    def stop_integrated_watchdog(self):
        """停止集成看门狗"""
        try:
            if self.watchdog_status in ["stopping", "disabled"]:
                self.logger.warning(f"看门狗已停止或停止中，当前状态: {self.watchdog_status}")
                return
                
            # 设置停止中状态
            self.set_watchdog_status("stopping")
            
            if self.integrated_watchdog:
                self.integrated_watchdog.stop()
                self.logger.info("集成看门狗已停止")
                self.set_watchdog_status("disabled")
            else:
                self.set_watchdog_status("disabled")
        except Exception as e:
            self.logger.error(f"停止集成看门狗失败: {e}")
            self.set_watchdog_status("error")
    
    def restart_system(self):
        """重启系统（供看门狗调用）"""
        try:
            self.logger.info("正在重启系统...")
            
            # 停止当前系统
            self.stop_system()
            
            # 等待停止完成
            time.sleep(2)
            
            # 重新启动系统
            self.start_system()
            
            self.logger.info("系统重启完成")
            
        except Exception as e:
            self.logger.error(f"重启系统失败: {e}")
    
    def get_watchdog_status(self):
        """获取看门狗状态"""
        if self.integrated_watchdog:
            return self.integrated_watchdog.get_status()
        else:
            return {
                'enabled': False,
                'running': False,
                'restart_count': 0,
                'max_restarts': 0,
                'health_status': {},
                'config': {}
            }
    
    def start_system(self):
        """启动打卡系统"""
        try:
            # 检查当前状态
            if self.system_status in ["starting", "running"]:
                self.logger.warning(f"系统已在运行或启动中，当前状态: {self.system_status}")
                return
            
            # 设置启动中状态
            self.set_system_status("starting")
            
            # 在新线程中启动系统
            self.system_thread = threading.Thread(target=self._run_system, daemon=True)
            self.system_thread.start()
            
            self.logger.info("打卡系统启动中...")
            
        except Exception as e:
            error_msg = f"启动系统失败: {str(e)}"
            self.logger.error(error_msg)
            self.set_system_status("stopped")
            messagebox.showerror("错误", error_msg)
    
    def _run_system(self):
        """在独立线程中运行打卡系统"""
        try:
            # 创建新的事件循环
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            
            # 运行异步初始化
            self.event_loop.run_until_complete(self._async_init_system())
            
            # 启动定期更新
            self.schedule_updates()
            
            # 运行事件循环
            self.event_loop.run_forever()
            
        except Exception as e:
            error_msg = f"系统运行错误: {str(e)}"
            self.logger.error(error_msg)
            self.root.after(0, lambda: self.set_system_status("stopped"))
            self.root.after(0, lambda: messagebox.showerror("系统错误", error_msg))
    
    async def _async_init_system(self):
        """异步初始化系统组件"""
        try:
            # 初始化系统组件
            self.attendance_system = AttendanceSystem()
            
            # 获取Telegram配置并启动bot
            chat_id = os.getenv('TELEGRAM_CHAT_ID')
            bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
            
            if chat_id and bot_token:
                self.logger.info("初始化Telegram Bot...")
                self.telegram_bot = TelegramBot(chat_id)
                self.telegram_bot.attendance_system = self.attendance_system
                
                # 初始化Telegram应用程序
                from telegram.ext import Application
                app = Application.builder().token(bot_token).build()
                self.telegram_bot.app = app
                self.attendance_system.bot = self.telegram_bot
                
                # 注册命令处理器
                await self._register_bot_handlers()
                
                # 启动Telegram bot
                await app.initialize()
                await app.start()
                await self.telegram_bot.start_polling()
                
                # 启动连接监控
                asyncio.create_task(self.telegram_bot.monitor_connection())
                
                self.logger.info("Telegram Bot启动成功")
                self.root.after(0, lambda: self.main_window.update_status("系统运行中 (包含Telegram Bot)"))
            else:
                self.logger.warning("未配置Telegram Bot参数，仅启动核心功能")
                self.root.after(0, lambda: self.main_window.update_status("系统运行中 (无Telegram Bot)"))
            
            # 加载现有的定时任务到调度器
            self.load_existing_tasks_to_scheduler()
            
            # 启动调度器监控
            self.start_scheduler_monitor()
            
            # 更新GUI状态为运行中
            self.root.after(0, lambda: self.set_system_status("running"))
            
        except Exception as e:
            self.logger.error(f"异步初始化系统失败: {str(e)}")
            raise
    
    async def _register_bot_handlers(self):
        """注册Telegram bot命令处理器"""
        try:
            from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters
            
            # 添加命令处理器（使用实际存在的方法名）
            self.telegram_bot.app.add_handler(CommandHandler("start", self.telegram_bot.start_command))
            self.telegram_bot.app.add_handler(CommandHandler("punch_in", self.telegram_bot.punch_in_command))
            self.telegram_bot.app.add_handler(CommandHandler("punch_out", self.telegram_bot.punch_out_command))
            self.telegram_bot.app.add_handler(CommandHandler("status", self.telegram_bot.status_command))
            self.telegram_bot.app.add_handler(CommandHandler("errors", self.telegram_bot.get_recent_errors))
            self.telegram_bot.app.add_handler(CommandHandler("kill", self.telegram_bot.kill_command))
            self.telegram_bot.app.add_handler(CommandHandler("set_time", self.telegram_bot.settime_command))
            
            # 添加回调处理器
            self.telegram_bot.app.add_handler(CallbackQueryHandler(self.telegram_bot.button_callback))
            
            # 添加消息处理器（用于处理设置时间等交互）
            self.telegram_bot.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.telegram_bot.handle_message))
            
            self.logger.info("Telegram Bot命令处理器注册完成")
            
        except Exception as e:
            self.logger.error(f"注册Bot命令处理器失败: {str(e)}")
            raise
    
    def stop_system(self):
        """停止打卡系统"""
        try:
            # 检查当前状态
            if self.system_status in ["stopping", "stopped"]:
                self.logger.warning(f"系统已停止或停止中，当前状态: {self.system_status}")
                return
            
            # 设置停止中状态
            self.set_system_status("stopping")
            
            # 异步停止Telegram bot
            if self.event_loop and self.event_loop.is_running() and self.telegram_bot:
                self.event_loop.call_soon_threadsafe(
                    asyncio.create_task, self._async_stop_bot()
                )
            
            # 停止事件循环
            if self.event_loop and self.event_loop.is_running():
                self.event_loop.call_soon_threadsafe(self.event_loop.stop)
            
            # 等待一小段时间后设置为已停止
            self.root.after(1000, lambda: self.set_system_status("stopped"))
            
            self.logger.info("打卡系统已停止")
            
        except Exception as e:
            error_msg = f"停止系统失败: {str(e)}"
            self.logger.error(error_msg)
            self.set_system_status("stopped")
            messagebox.showerror("错误", error_msg)
    
    async def _async_stop_bot(self):
        """异步停止Telegram bot"""
        try:
            if self.telegram_bot and self.telegram_bot.app:
                self.logger.info("正在停止Telegram Bot...")
                await self.telegram_bot.stop_polling()
                await self.telegram_bot.app.stop()
                await self.telegram_bot.app.shutdown()
                self.logger.info("Telegram Bot已停止")
        except Exception as e:
            self.logger.error(f"停止Telegram Bot失败: {str(e)}")
    
    def load_existing_tasks_to_scheduler(self):
        """将现有任务加载到调度器"""
        try:
            if self.attendance_system and self.attendance_system.task_manager:
                import schedule
                import asyncio
                
                tasks = self.attendance_system.task_manager.get_tasks()
                self.logger.info(f"开始加载 {len(tasks)} 个现有任务到调度器")
                
                for task in tasks:
                    task_type = task['type']
                    scheduled_time = task['scheduled_time']
                    task_id = task.get('id', 'unknown')
                    
                    try:
                        if task_type == 'punch_in':
                            def punch_in_job():
                                if self.event_loop and self.event_loop.is_running():
                                    asyncio.run_coroutine_threadsafe(
                                        self.attendance_system.punch_in(),
                                        self.event_loop
                                    )
                            schedule.every().day.at(scheduled_time).do(punch_in_job).tag(f'punch_in_{scheduled_time}_{task_id}')
                            
                        elif task_type == 'punch_out':
                            def punch_out_job():
                                if self.event_loop and self.event_loop.is_running():
                                    asyncio.run_coroutine_threadsafe(
                                        self.attendance_system.punch_out(),
                                        self.event_loop
                                    )
                            schedule.every().day.at(scheduled_time).do(punch_out_job).tag(f'punch_out_{scheduled_time}_{task_id}')
                        
                        self.logger.info(f"任务加载成功: ID {task_id}, 类型 {task_type}, 时间 {scheduled_time}")
                        
                    except Exception as task_error:
                        self.logger.error(f"加载任务 {task_id} 失败: {task_error}")
                
                self.logger.info(f"任务加载完成，调度器中共有 {len(schedule.jobs)} 个任务")
                
        except Exception as e:
            self.logger.error(f"加载现有任务到调度器失败: {str(e)}")
    
    def start_scheduler_monitor(self):
        """启动调度器监控任务"""
        try:
            import schedule
            
            async def scheduler_monitor():
                """调度器监控循环"""
                while self.event_loop and self.event_loop.is_running():
                    try:
                        schedule.run_pending()  # 运行到期的任务
                        await asyncio.sleep(1)  # 每秒检查一次
                    except Exception as e:
                        self.logger.error(f"调度器运行错误: {e}")
                        await asyncio.sleep(5)  # 出错后等待5秒
            
            # 在事件循环中启动调度器监控
            if self.event_loop:
                asyncio.create_task(scheduler_monitor())
                self.logger.info("调度器监控已启动")
            
        except Exception as e:
            self.logger.error(f"启动调度器监控失败: {str(e)}")
    
    def schedule_updates(self):
        """安排定期更新GUI内容"""
        # 每5秒更新一次状态信息
        def update_loop():
            if self.attendance_system:
                self.root.after(0, self.main_window.refresh_all_data)
            # 继续调度下次更新
            if self.event_loop and self.event_loop.is_running():
                self.event_loop.call_later(5, update_loop)
        
        # 启动更新循环
        if self.event_loop:
            self.event_loop.call_soon(update_loop)
    
    def manual_punch_in(self):
        """手动上班打卡"""
        if not self.attendance_system:
            messagebox.showwarning("警告", "系统未启动")
            return
            
        def punch_in_async():
            try:
                if self.event_loop:
                    asyncio.run_coroutine_threadsafe(
                        self.attendance_system.punch_in(), 
                        self.event_loop
                    )
            except Exception as e:
                self.logger.error(f"手动上班打卡失败: {str(e)}")
                self.root.after(0, lambda: messagebox.showerror("打卡失败", str(e)))
        
        threading.Thread(target=punch_in_async, daemon=True).start()
    
    def manual_punch_out(self):
        """手动下班打卡"""
        if not self.attendance_system:
            messagebox.showwarning("警告", "系统未启动")
            return
            
        def punch_out_async():
            try:
                if self.event_loop:
                    asyncio.run_coroutine_threadsafe(
                        self.attendance_system.punch_out(), 
                        self.event_loop
                    )
            except Exception as e:
                self.logger.error(f"手动下班打卡失败: {str(e)}")
                self.root.after(0, lambda: messagebox.showerror("打卡失败", str(e)))
        
        threading.Thread(target=punch_out_async, daemon=True).start()
    
    def get_system_status(self):
        """获取系统状态信息"""
        if not self.attendance_system:
            return None
            
        try:
            status = {
                'current_time': datetime.now(),
                'punch_records': self.attendance_system.today_punch_records,
                'is_running': self.event_loop and self.event_loop.is_running(),
                'tasks': self.attendance_system.task_manager.get_tasks() if self.attendance_system.task_manager else []
            }
            return status
        except Exception as e:
            self.logger.error(f"获取系统状态失败: {str(e)}")
            return None
    
    def auto_start_system(self):
        """自动启动系统"""
        try:
            self.logger.info("自动启动系统...")
            self.start_system()
        except Exception as e:
            self.logger.error(f"自动启动系统失败: {str(e)}")
    
    def create_tray_icon(self):
        """创建系统托盘图标"""
        try:
            # 使用项目logo作为托盘图标
            logo_path = "templates/logo/mm.png"
            if os.path.exists(logo_path):
                image = Image.open(logo_path)
                # 调整大小为托盘图标的标准尺寸
                image = image.resize((64, 64), Image.Resampling.LANCZOS)
            else:
                # 如果logo不存在，使用默认的蓝色圆点
                image = Image.new('RGB', (64, 64), color='white')
                draw = ImageDraw.Draw(image)
                draw.ellipse([8, 8, 56, 56], fill='#007ACC', outline='#005A9E', width=2)
            
            # 创建菜单，恢复default=True便于右键菜单使用
            menu = pystray.Menu(
                pystray.MenuItem("🏠 显示窗口", self.show_window, default=True),
                pystray.MenuItem("📖 隐藏窗口", self.hide_window),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("⏰ 上班打卡", self.manual_punch_in),
                pystray.MenuItem("🏁 下班打卡", self.manual_punch_out),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ 退出程序", self.quit_app)
            )
            
            # 创建托盘图标，不设置default_action避免单击触发
            self.tray_icon = pystray.Icon(
                "自动打卡系统",
                image,
                menu=menu
            )
            
            # 只设置双击事件
            try:
                self.tray_icon.on_double_click = self.on_tray_double_click
                self.logger.info("双击事件设置成功")
            except Exception as e:
                self.logger.warning(f"双击事件设置失败: {e}")
            
            self.logger.info("系统托盘图标创建成功")
            
            # 测试托盘功能是否正常
            self.test_tray_functionality()
            
        except Exception as e:
            self.logger.error(f"创建系统托盘失败: {str(e)}")
    
    def test_tray_functionality(self):
        """测试托盘功能"""
        try:
            self.logger.info("开始测试托盘功能...")
            self.logger.info(f"托盘图标对象: {self.tray_icon}")
            self.logger.info(f"default_action: {getattr(self.tray_icon, 'default_action', 'None')}")
            self.logger.info(f"on_double_click: {getattr(self.tray_icon, 'on_double_click', 'None')}")
            self.logger.info(f"on_activate: {getattr(self.tray_icon, 'on_activate', 'None')}")
            
            # 检查pystray版本
            import pystray
            self.logger.info(f"pystray版本: {getattr(pystray, '__version__', '未知')}")
            
        except Exception as e:
            self.logger.error(f"测试托盘功能时发生错误: {str(e)}")
    
    def minimize_to_tray(self):
        """最小化到系统托盘"""
        if TRAY_AVAILABLE and self.tray_icon:
            self.root.withdraw()  # 隐藏窗口
            self.is_hidden = True
            
            # 在后台线程启动托盘图标 (如果还没启动)
            if not hasattr(self, '_tray_started'):
                self._tray_started = True
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
        else:
            # 如果没有托盘支持，询问是否退出
            result = messagebox.askyesno(
                "确认退出",
                "系统托盘功能不可用。\n是否确定要退出程序？",
                icon='question'
            )
            if result:
                self.on_closing()
    
    def on_tray_default_action(self, icon):
        """托盘默认动作（通常是双击或单击）"""
        try:
            print("DEBUG: 托盘默认动作被触发！")  # 添加print调试
            self.logger.info("检测到托盘默认动作事件（双击/单击）")
            self.root.after(0, self._show_window_safe)
        except Exception as e:
            print(f"DEBUG: 托盘默认动作错误: {e}")  # 添加print调试
            self.logger.error(f"处理托盘默认动作时发生错误: {str(e)}")
    
    def on_tray_click(self, icon):
        """托盘单击事件处理（用于双击检测）"""
        try:
            print("DEBUG: 托盘单击事件被触发！")  # 添加print调试
            current_time = time.time()
            
            # 检测是否为双击
            if current_time - self.last_click_time < self.double_click_threshold:
                print("DEBUG: 检测到双击！")  # 添加print调试
                self.logger.info("检测到托盘双击事件（通过单击间隔判断）")
                self.root.after(0, self._show_window_safe)
            else:
                print("DEBUG: 单击事件")  # 添加print调试
                self.logger.debug("托盘单击事件")
            
            self.last_click_time = current_time
            
        except Exception as e:
            print(f"DEBUG: 托盘单击错误: {e}")  # 添加print调试
            self.logger.error(f"处理托盘单击事件时发生错误: {str(e)}")
    
    def on_tray_double_click(self, icon):
        """托盘双击事件处理（跨线程安全）"""
        try:
            print("DEBUG: 托盘双击事件被触发！")  # 添加print调试
            self.logger.info("检测到托盘双击事件（直接双击）")
            # 使用after方法确保在主线程中执行GUI操作
            self.root.after(0, self._show_window_safe)
        except Exception as e:
            print(f"DEBUG: 托盘双击错误: {e}")  # 添加print调试
            self.logger.error(f"处理托盘双击事件时发生错误: {str(e)}")
    
    def _show_window_safe(self):
        """安全地显示窗口（主线程中执行）"""
        try:
            self.root.deiconify()  # 显示窗口
            self.root.lift()  # 置于顶层
            self.root.focus_force()  # 获取焦点
            self.root.attributes('-topmost', True)  # 强制置顶
            self.root.attributes('-topmost', False)  # 取消置顶但保持在前台
            self.is_hidden = False
            self.logger.info("通过双击托盘图标显示窗口")
        except Exception as e:
            self.logger.error(f"显示窗口时发生错误: {str(e)}")
    
    def show_window(self, icon=None, item=None):
        """显示窗口（菜单调用）"""
        # 对于菜单调用，也使用安全的跨线程方式
        self.root.after(0, self._show_window_safe)
    
    def hide_window(self, icon=None, item=None):
        """隐藏窗口"""
        self.root.withdraw()
        self.is_hidden = True
    
    def quit_app(self, icon=None, item=None):
        """退出应用程序"""
        try:
            # 停止托盘图标
            if self.tray_icon:
                self.tray_icon.stop()
            
            # 调用原始关闭处理
            self.on_closing()
            
        except Exception as e:
            self.logger.error(f"退出应用程序时发生错误: {str(e)}")
            self.root.quit()
    
    def on_closing(self):
        """处理窗口关闭事件"""
        try:
            # 停止集成看门狗
            self.stop_integrated_watchdog()
            
            # 停止系统
            self.stop_system()
            
            # 等待线程结束
            if self.system_thread and self.system_thread.is_alive():
                self.system_thread.join(timeout=3)
            
            # 销毁窗口
            self.root.destroy()
            
        except Exception as e:
            self.logger.error(f"关闭应用程序时发生错误: {str(e)}")
            self.root.destroy()
    
    def run(self):
        """运行GUI应用"""
        try:
            self.logger.info("启动GUI客户端")
            self.root.mainloop()
        except Exception as e:
            self.logger.error(f"GUI应用运行失败: {str(e)}")
            messagebox.showerror("严重错误", f"应用程序崩溃: {str(e)}")

def main():
    """主函数"""
    try:
        app = AttendanceGUIApp()
        app.run()
    except Exception as e:
        print(f"应用程序启动失败: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()