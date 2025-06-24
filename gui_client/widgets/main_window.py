"""
主窗口模块
包含所有主要的GUI组件和布局
"""

import tkinter as tk
from tkinter import ttk
import threading
from datetime import datetime
import os

from .status_panel import StatusPanel
from .punch_panel import PunchPanel
from .task_panel import TaskPanel
from .log_panel import LogPanel
from .config_panel import ConfigPanel
from ..utils.gui_utils import setup_styles, create_labeled_frame

class MainWindow:
    """主窗口类"""
    
    def __init__(self, root, app):
        self.root = root
        self.app = app
        self.current_status = "系统未启动"
        self.system_running = False
        
        # 设置样式
        self.style = setup_styles()
        
        # 创建主界面
        self.create_widgets()
        
        # 初始化状态
        self.update_status("准备就绪")
    
    def create_widgets(self):
        """创建所有GUI组件"""
        # 创建主菜单
        self.create_menu()
        
        # 创建工具栏
        self.create_toolbar()
        
        # 创建主内容区域
        self.create_main_content()
        
        # 创建状态栏
        self.create_status_bar()
    
    def create_menu(self):
        """创建菜单栏"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # 系统菜单
        system_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="系统", menu=system_menu)
        system_menu.add_command(label="启动系统", command=self.app.start_system)
        system_menu.add_command(label="停止系统", command=self.app.stop_system)
        system_menu.add_separator()
        system_menu.add_command(label="退出", command=self.app.on_closing)
        
        # 打卡菜单
        punch_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="打卡", menu=punch_menu)
        punch_menu.add_command(label="上班打卡", command=self.app.manual_punch_in)
        punch_menu.add_command(label="下班打卡", command=self.app.manual_punch_out)
        
        # 工具菜单
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="工具", menu=tools_menu)
        tools_menu.add_command(label="打开日志目录", command=self.open_log_directory)
        tools_menu.add_command(label="打开配置目录", command=self.open_config_directory)
        
        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="关于", command=self.show_about)
    
    def create_toolbar(self):
        """创建工具栏"""
        toolbar = ttk.Frame(self.root)
        toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=2)
        
        # 系统控制按钮
        self.start_btn = ttk.Button(toolbar, text="启动系统", 
                                   command=self.app.start_system)
        self.start_btn.pack(side=tk.LEFT, padx=2)
        
        self.stop_btn = ttk.Button(toolbar, text="停止系统", 
                                  command=self.app.stop_system, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=2)
        
        # 分隔符
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill=tk.Y)
        
        # 打卡按钮
        self.punch_in_btn = ttk.Button(toolbar, text="上班打卡", 
                                      command=self.app.manual_punch_in,
                                      state=tk.DISABLED)
        self.punch_in_btn.pack(side=tk.LEFT, padx=2)
        
        self.punch_out_btn = ttk.Button(toolbar, text="下班打卡", 
                                       command=self.app.manual_punch_out,
                                       state=tk.DISABLED)
        self.punch_out_btn.pack(side=tk.LEFT, padx=2)
        
        # 分隔符
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, padx=5, fill=tk.Y)
        
        # 刷新按钮
        self.refresh_btn = ttk.Button(toolbar, text="刷新", 
                                     command=self.refresh_all_data)
        self.refresh_btn.pack(side=tk.LEFT, padx=2)
        
        # 右侧系统时间显示
        self.time_label = ttk.Label(toolbar, text="")
        self.time_label.pack(side=tk.RIGHT, padx=10)
        
        # 启动时间更新
        self.update_time()
    
    def create_main_content(self):
        """创建主内容区域"""
        # 创建标签页控件
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 状态面板标签页
        self.status_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.status_frame, text="系统状态")
        self.status_panel = StatusPanel(self.status_frame, self.app)
        
        # 打卡面板标签页
        self.punch_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.punch_frame, text="打卡操作")
        self.punch_panel = PunchPanel(self.punch_frame, self.app)
        
        # 任务管理标签页
        self.task_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.task_frame, text="任务管理")
        self.task_panel = TaskPanel(self.task_frame, self.app)
        
        # 日志查看标签页
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, text="日志查看")
        self.log_panel = LogPanel(self.log_frame, self.app)
        
        # 系统配置标签页
        self.config_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.config_frame, text="系统配置")
        self.config_panel = ConfigPanel(self.config_frame, self.app)
    
    def create_status_bar(self):
        """创建状态栏"""
        self.status_bar = ttk.Frame(self.root)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 状态标签
        self.status_label = ttk.Label(self.status_bar, text=self.current_status)
        self.status_label.pack(side=tk.LEFT, padx=5)
        
        # 系统运行指示器
        self.running_indicator = ttk.Label(self.status_bar, text="●", 
                                          foreground="red")
        self.running_indicator.pack(side=tk.RIGHT, padx=5)
        
        self.running_label = ttk.Label(self.status_bar, text="未运行")
        self.running_label.pack(side=tk.RIGHT)
    
    def update_status(self, status):
        """更新状态显示"""
        self.current_status = status
        if hasattr(self, 'status_label'):
            self.status_label.config(text=status)
    
    def set_system_running(self, running):
        """设置系统运行状态"""
        self.system_running = running
        
        if running:
            # 系统运行中
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.punch_in_btn.config(state=tk.NORMAL)
            self.punch_out_btn.config(state=tk.NORMAL)
            self.running_indicator.config(foreground="green")
            self.running_label.config(text="运行中")
        else:
            # 系统停止
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.punch_in_btn.config(state=tk.DISABLED)
            self.punch_out_btn.config(state=tk.DISABLED)
            self.running_indicator.config(foreground="red")
            self.running_label.config(text="未运行")
    
    def update_time(self):
        """更新时间显示"""
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.time_label.config(text=current_time)
        # 每秒更新一次
        self.root.after(1000, self.update_time)
    
    def refresh_all_data(self):
        """刷新所有数据"""
        try:
            # 刷新各个面板的数据
            if hasattr(self, 'status_panel'):
                self.status_panel.refresh_data()
            if hasattr(self, 'punch_panel'):
                self.punch_panel.refresh_data()
            if hasattr(self, 'task_panel'):
                self.task_panel.refresh_data()
            if hasattr(self, 'log_panel'):
                self.log_panel.refresh_data()
                
        except Exception as e:
            print(f"刷新数据时发生错误: {str(e)}")
    
    def open_log_directory(self):
        """打开日志目录"""
        import subprocess
        import platform
        
        log_dir = os.path.abspath("logs")
        
        try:
            if platform.system() == "Windows":
                os.startfile(log_dir)
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", log_dir])
            else:  # Linux
                subprocess.Popen(["xdg-open", log_dir])
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("错误", f"无法打开日志目录: {str(e)}")
    
    def open_config_directory(self):
        """打开配置目录"""
        import subprocess
        import platform
        
        config_dir = os.path.abspath(".")
        
        try:
            if platform.system() == "Windows":
                os.startfile(config_dir)
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", config_dir])
            else:  # Linux
                subprocess.Popen(["xdg-open", config_dir])
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("错误", f"无法打开配置目录: {str(e)}")
    
    def show_about(self):
        """显示关于对话框"""
        from tkinter import messagebox
        
        about_text = """自动打卡系统 v2.0
        
基于Python开发的自动打卡系统
支持图像识别、定时任务、Telegram机器人控制

开发团队: 赖得鑫
版本: 2.0.0
更新日期: 2025-06-24

功能特性:
• 自动打卡识别
• 定时任务管理
• Telegram远程控制
• 邮件通知
• 日志记录
• 图形化界面"""
        
        messagebox.showinfo("关于", about_text)