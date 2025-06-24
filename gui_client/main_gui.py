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
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入系统模块
from main import AttendanceSystem, TelegramBot
from tasks import TaskManager
from punch_records import PunchRecordManager
try:
    from .widgets.main_window import MainWindow
    from .utils.gui_utils import set_window_icon, center_window
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    from gui_client.widgets.main_window import MainWindow
    from gui_client.utils.gui_utils import set_window_icon, center_window

class AttendanceGUIApp:
    """自动打卡系统GUI应用主类"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("自动打卡系统")
        self.root.geometry("1000x700")
        
        # 设置窗口图标和居中显示
        set_window_icon(self.root)
        center_window(self.root, 1000, 700)
        
        # 初始化系统组件
        self.attendance_system = None
        self.telegram_bot = None
        self.event_loop = None
        self.system_thread = None
        
        # 创建主窗口
        self.main_window = MainWindow(self.root, self)
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 配置日志
        self.setup_logging()
        
    def setup_logging(self):
        """配置日志系统"""
        # 确保日志目录存在
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        # 配置日志格式
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(log_dir, 'gui_client.log'), encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("GUI客户端启动")
    
    def start_system(self):
        """启动打卡系统"""
        try:
            self.main_window.update_status("正在启动系统...")
            
            # 在新线程中启动系统
            self.system_thread = threading.Thread(target=self._run_system, daemon=True)
            self.system_thread.start()
            
            self.logger.info("打卡系统启动中...")
            
        except Exception as e:
            error_msg = f"启动系统失败: {str(e)}"
            self.logger.error(error_msg)
            messagebox.showerror("错误", error_msg)
    
    def _run_system(self):
        """在独立线程中运行打卡系统"""
        try:
            # 创建新的事件循环
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            
            # 初始化系统组件
            self.attendance_system = AttendanceSystem()
            
            # 获取Telegram配置
            chat_id = os.getenv('TELEGRAM_CHAT_ID')
            if chat_id:
                self.telegram_bot = TelegramBot(chat_id)
                self.telegram_bot.attendance_system = self.attendance_system
            
            # 更新GUI状态
            self.root.after(0, lambda: self.main_window.update_status("系统运行中"))
            self.root.after(0, lambda: self.main_window.set_system_running(True))
            
            # 启动定期更新
            self.schedule_updates()
            
            # 运行事件循环
            self.event_loop.run_forever()
            
        except Exception as e:
            error_msg = f"系统运行错误: {str(e)}"
            self.logger.error(error_msg)
            self.root.after(0, lambda: messagebox.showerror("系统错误", error_msg))
            self.root.after(0, lambda: self.main_window.set_system_running(False))
    
    def stop_system(self):
        """停止打卡系统"""
        try:
            self.main_window.update_status("正在停止系统...")
            
            if self.event_loop and self.event_loop.is_running():
                self.event_loop.call_soon_threadsafe(self.event_loop.stop)
            
            self.main_window.set_system_running(False)
            self.main_window.update_status("系统已停止")
            
            self.logger.info("打卡系统已停止")
            
        except Exception as e:
            error_msg = f"停止系统失败: {str(e)}"
            self.logger.error(error_msg)
            messagebox.showerror("错误", error_msg)
    
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
    
    def on_closing(self):
        """处理窗口关闭事件"""
        try:
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