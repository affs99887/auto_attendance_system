"""
系统配置面板
提供系统配置的查看和修改功能
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
from dotenv import load_dotenv, set_key

try:
    from ..utils.gui_utils import (
        create_labeled_frame, StatusColors, ask_yes_no
    )
except ImportError:
    from gui_client.utils.gui_utils import (
        create_labeled_frame, StatusColors, ask_yes_no
    )

class ConfigPanel:
    """系统配置面板类"""
    
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        
        # 配置变量
        self.config_vars = {}
        
        # 创建界面
        self.create_widgets()
        
        # 加载配置
        self.load_config()
    
    def create_widgets(self):
        """创建配置面板的所有组件"""
        # 主框架
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 创建标签页
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # 基本设置标签页
        self.create_basic_config_tab()
        
        # 打卡设置标签页
        self.create_punch_config_tab()
        
        # Telegram设置标签页
        self.create_telegram_config_tab()
        
        # 邮件设置标签页
        self.create_email_config_tab()
        
        # 高级设置标签页
        self.create_advanced_config_tab()
        
        # 操作按钮
        self.create_action_buttons(main_frame)
    
    def create_basic_config_tab(self):
        """创建基本设置标签页"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="基本设置")
        
        # 滚动框架
        canvas = tk.Canvas(frame)
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 登录设置组
        login_frame = create_labeled_frame(scrollable_frame, "🔐 登录设置")
        login_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 登录URL
        self.add_config_field(login_frame, "LOGIN_URL", "登录URL:", "登录系统的URL地址")
        
        # 用户名
        self.add_config_field(login_frame, "LOGIN_USERNAME", "用户名:", "登录用户名")
        
        # 密码
        self.add_config_field(login_frame, "LOGIN_PASSWORD", "密码:", "登录密码", show="*")
        
        # 系统设置组
        system_frame = create_labeled_frame(scrollable_frame, "⚙️ 系统设置")
        system_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Tesseract路径
        self.add_config_field(system_frame, "TESSERACT_PATH", "Tesseract路径:", "OCR程序路径")
        
        # 用户名设置
        self.add_config_field(system_frame, "USER_NAME", "用户名:", "显示用户名")
        
        # 布局
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def create_punch_config_tab(self):
        """创建打卡设置标签页"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="打卡设置")
        
        # 时间设置组
        time_frame = create_labeled_frame(frame, "⏰ 时间设置")
        time_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 上班时间
        self.add_config_field(time_frame, "WORK_START_TIME", "上班时间:", "格式: HH:MM")
        
        # 下班时间
        self.add_config_field(time_frame, "WORK_END_TIME", "下班时间:", "格式: HH:MM")
        
        # 阈值设置组
        threshold_frame = create_labeled_frame(frame, "📏 阈值设置")
        threshold_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 迟到阈值
        self.add_config_field(threshold_frame, "LATE_THRESHOLD", "迟到阈值(分钟):", "超过此时间算迟到")
        
        # 早退阈值
        self.add_config_field(threshold_frame, "EARLY_LEAVE_THRESHOLD", "早退阈值(分钟):", "提前此时间算早退")
        
        # 重试设置组
        retry_frame = create_labeled_frame(frame, "🔄 重试设置")
        retry_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 最大重试次数
        self.add_config_field(retry_frame, "MAX_RETRY_COUNT", "最大重试次数:", "打卡失败时的重试次数")
        
        # 重试间隔
        self.add_config_field(retry_frame, "RETRY_INTERVAL", "重试间隔(秒):", "重试之间的等待时间")
    
    def create_telegram_config_tab(self):
        """创建Telegram设置标签页"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="Telegram设置")
        
        # 基本设置组
        basic_frame = create_labeled_frame(frame, "🤖 机器人设置")
        basic_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Bot Token
        self.add_config_field(basic_frame, "TELEGRAM_BOT_TOKEN", "Bot Token:", "从BotFather获取的Token", show="*")
        
        # Chat ID
        self.add_config_field(basic_frame, "TELEGRAM_CHAT_ID", "Chat ID:", "接收消息的聊天ID")
        
        # 测试连接按钮
        test_frame = ttk.Frame(basic_frame)
        test_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            test_frame,
            text="测试Telegram连接",
            command=self.test_telegram_connection
        ).pack(side=tk.LEFT)
        
        # 连接设置组
        conn_frame = create_labeled_frame(frame, "🌐 连接设置")
        conn_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 连接超时
        self.add_config_field(conn_frame, "TELEGRAM_TIMEOUT", "连接超时(秒):", "网络请求超时时间")
        
        # 重试次数
        self.add_config_field(conn_frame, "TELEGRAM_RETRY_COUNT", "重试次数:", "连接失败时的重试次数")
    
    def create_email_config_tab(self):
        """创建邮件设置标签页"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="邮件设置")
        
        # 基本设置组
        basic_frame = create_labeled_frame(frame, "📧 邮件基本设置")
        basic_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 发件人邮箱
        self.add_config_field(basic_frame, "EMAIL_SENDER", "发件人邮箱:", "发送邮件的邮箱地址")
        
        # 邮箱密码
        self.add_config_field(basic_frame, "EMAIL_PASSWORD", "邮箱密码:", "邮箱密码或授权码", show="*")
        
        # SMTP设置组
        smtp_frame = create_labeled_frame(frame, "🌐 SMTP设置")
        smtp_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # SMTP服务器
        self.add_config_field(smtp_frame, "EMAIL_SMTP_SERVER", "SMTP服务器:", "如: smtp.qq.com")
        
        # SMTP端口
        self.add_config_field(smtp_frame, "EMAIL_SMTP_PORT", "SMTP端口:", "如: 465或587")
        
        # 测试邮件按钮
        test_frame = ttk.Frame(smtp_frame)
        test_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            test_frame,
            text="发送测试邮件",
            command=self.send_test_email
        ).pack(side=tk.LEFT)
    
    def create_advanced_config_tab(self):
        """创建高级设置标签页"""
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text="高级设置")
        
        # 日志设置组
        log_frame = create_labeled_frame(frame, "📝 日志设置")
        log_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 日志级别
        log_level_frame = ttk.Frame(log_frame)
        log_level_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(log_level_frame, text="日志级别:").pack(side=tk.LEFT)
        
        self.log_level_var = tk.StringVar(value="INFO")
        log_level_combo = ttk.Combobox(
            log_level_frame,
            textvariable=self.log_level_var,
            values=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            state="readonly",
            width=10
        )
        log_level_combo.pack(side=tk.LEFT, padx=(10, 0))
        
        # 性能设置组
        perf_frame = create_labeled_frame(frame, "⚡ 性能设置")
        perf_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 图像识别超时
        self.add_config_field(perf_frame, "IMAGE_TIMEOUT", "图像识别超时(秒):", "图像识别操作超时时间")
        
        # 网络超时
        self.add_config_field(perf_frame, "NETWORK_TIMEOUT", "网络超时(秒):", "网络操作超时时间")
        
        # 开发者选项组
        dev_frame = create_labeled_frame(frame, "🔧 开发者选项")
        dev_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 调试模式
        debug_frame = ttk.Frame(dev_frame)
        debug_frame.pack(fill=tk.X, pady=2)
        
        self.debug_var = tk.BooleanVar()
        ttk.Checkbutton(
            debug_frame,
            text="启用调试模式",
            variable=self.debug_var
        ).pack(side=tk.LEFT)
        
        # 保存截图
        screenshot_frame = ttk.Frame(dev_frame)
        screenshot_frame.pack(fill=tk.X, pady=2)
        
        self.save_screenshot_var = tk.BooleanVar()
        ttk.Checkbutton(
            screenshot_frame,
            text="保存操作截图",
            variable=self.save_screenshot_var
        ).pack(side=tk.LEFT)
    
    def create_action_buttons(self, parent):
        """创建操作按钮"""
        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        # 保存配置按钮
        ttk.Button(
            button_frame,
            text="保存配置",
            command=self.save_config
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        # 重新加载按钮
        ttk.Button(
            button_frame,
            text="重新加载",
            command=self.load_config
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        # 重置为默认值按钮
        ttk.Button(
            button_frame,
            text="重置默认",
            command=self.reset_to_default
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        # 导入配置按钮
        ttk.Button(
            button_frame,
            text="导入配置",
            command=self.import_config
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        # 导出配置按钮
        ttk.Button(
            button_frame,
            text="导出配置",
            command=self.export_config
        ).pack(side=tk.LEFT)
    
    def add_config_field(self, parent, key, label, tooltip="", show=None):
        """添加配置字段"""
        field_frame = ttk.Frame(parent)
        field_frame.pack(fill=tk.X, pady=2)
        
        # 标签
        label_widget = ttk.Label(field_frame, text=label, width=20)
        label_widget.pack(side=tk.LEFT)
        
        # 输入框
        var = tk.StringVar()
        entry = ttk.Entry(field_frame, textvariable=var, show=show, width=40)
        entry.pack(side=tk.LEFT, padx=(10, 0), fill=tk.X, expand=True)
        
        # 保存变量引用
        self.config_vars[key] = var
        
        # 添加工具提示
        if tooltip:
            self.create_tooltip(entry, tooltip)
    
    def create_tooltip(self, widget, text):
        """创建工具提示"""
        def show_tooltip(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
            label = tk.Label(tooltip, text=text, background="lightyellow",
                           relief="solid", borderwidth=1, font=("Arial", 8))
            label.pack()
            
            def hide_tooltip():
                tooltip.destroy()
            
            tooltip.after(3000, hide_tooltip)
            widget.tooltip = tooltip
        
        def hide_tooltip(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()
        
        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)
    
    def load_config(self):
        """加载配置"""
        try:
            # 重新加载.env文件
            load_dotenv(override=True)
            
            # 更新所有配置字段
            for key, var in self.config_vars.items():
                value = os.getenv(key, "")
                var.set(value)
            
            # 更新特殊字段
            self.log_level_var.set(os.getenv("LOG_LEVEL", "INFO"))
            self.debug_var.set(os.getenv("DEBUG", "False").lower() == "true")
            self.save_screenshot_var.set(os.getenv("SAVE_SCREENSHOT", "False").lower() == "true")
            
            # 注释掉自动弹窗，避免启动时干扰
            # messagebox.showinfo("成功", "配置已重新加载")
            
        except Exception as e:
            messagebox.showerror("错误", f"加载配置失败: {str(e)}")
    
    def save_config(self):
        """保存配置"""
        try:
            env_file = ".env"
            
            # 保存所有配置字段
            for key, var in self.config_vars.items():
                value = var.get().strip()
                if value:  # 只保存非空值
                    set_key(env_file, key, value)
            
            # 保存特殊字段
            set_key(env_file, "LOG_LEVEL", self.log_level_var.get())
            set_key(env_file, "DEBUG", str(self.debug_var.get()))
            set_key(env_file, "SAVE_SCREENSHOT", str(self.save_screenshot_var.get()))
            
            messagebox.showinfo("成功", "配置已保存到 .env 文件")
            
        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")
    
    def reset_to_default(self):
        """重置为默认值"""
        if not ask_yes_no(self.parent, "确认重置", "确定要重置所有配置为默认值吗？"):
            return
        
        try:
            # 默认配置值
            defaults = {
                "LOGIN_URL": "",
                "LOGIN_USERNAME": "",
                "LOGIN_PASSWORD": "",
                "TESSERACT_PATH": "tesseract",
                "USER_NAME": "用户",
                "WORK_START_TIME": "09:00",
                "WORK_END_TIME": "17:30",
                "LATE_THRESHOLD": "30",
                "EARLY_LEAVE_THRESHOLD": "30",
                "MAX_RETRY_COUNT": "3",
                "RETRY_INTERVAL": "5",
                "TELEGRAM_BOT_TOKEN": "",
                "TELEGRAM_CHAT_ID": "",
                "TELEGRAM_TIMEOUT": "30",
                "TELEGRAM_RETRY_COUNT": "3",
                "EMAIL_SENDER": "",
                "EMAIL_PASSWORD": "",
                "EMAIL_SMTP_SERVER": "smtp.qq.com",
                "EMAIL_SMTP_PORT": "465",
                "IMAGE_TIMEOUT": "30",
                "NETWORK_TIMEOUT": "30"
            }
            
            # 设置默认值
            for key, default_value in defaults.items():
                if key in self.config_vars:
                    self.config_vars[key].set(default_value)
            
            # 设置特殊字段默认值
            self.log_level_var.set("INFO")
            self.debug_var.set(False)
            self.save_screenshot_var.set(False)
            
            messagebox.showinfo("成功", "配置已重置为默认值")
            
        except Exception as e:
            messagebox.showerror("错误", f"重置配置失败: {str(e)}")
    
    def import_config(self):
        """导入配置"""
        try:
            filename = filedialog.askopenfilename(
                title="导入配置文件",
                filetypes=[("环境变量文件", "*.env"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
            )
            
            if filename:
                # 备份当前配置
                if os.path.exists(".env"):
                    import shutil
                    shutil.copy2(".env", ".env.backup")
                
                # 复制导入的文件
                import shutil
                shutil.copy2(filename, ".env")
                
                # 重新加载配置
                self.load_config()
                
                messagebox.showinfo("成功", f"配置已从 {filename} 导入")
                
        except Exception as e:
            messagebox.showerror("错误", f"导入配置失败: {str(e)}")
    
    def export_config(self):
        """导出配置"""
        try:
            filename = filedialog.asksaveasfilename(
                title="导出配置文件",
                defaultextension=".env",
                filetypes=[("环境变量文件", "*.env"), ("文本文件", "*.txt"), ("所有文件", "*.*")]
            )
            
            if filename:
                if os.path.exists(".env"):
                    import shutil
                    shutil.copy2(".env", filename)
                    messagebox.showinfo("成功", f"配置已导出到 {filename}")
                else:
                    messagebox.showerror("错误", "未找到配置文件 .env")
                
        except Exception as e:
            messagebox.showerror("错误", f"导出配置失败: {str(e)}")
    
    def test_telegram_connection(self):
        """测试Telegram连接"""
        try:
            token = self.config_vars.get("TELEGRAM_BOT_TOKEN", tk.StringVar()).get().strip()
            chat_id = self.config_vars.get("TELEGRAM_CHAT_ID", tk.StringVar()).get().strip()
            
            if not token or not chat_id:
                messagebox.showwarning("警告", "请先填写Bot Token和Chat ID")
                return
            
            # 这里应该实现实际的Telegram连接测试
            # 由于需要异步操作，这里只是显示提示
            messagebox.showinfo("测试", "Telegram连接测试功能待实现")
            
        except Exception as e:
            messagebox.showerror("错误", f"测试Telegram连接失败: {str(e)}")
    
    def send_test_email(self):
        """发送测试邮件"""
        try:
            sender = self.config_vars.get("EMAIL_SENDER", tk.StringVar()).get().strip()
            password = self.config_vars.get("EMAIL_PASSWORD", tk.StringVar()).get().strip()
            
            if not sender or not password:
                messagebox.showwarning("警告", "请先填写邮箱和密码")
                return
            
            # 这里应该实现实际的邮件发送测试
            # 由于需要导入邮件服务，这里只是显示提示
            messagebox.showinfo("测试", "测试邮件发送功能待实现")
            
        except Exception as e:
            messagebox.showerror("错误", f"发送测试邮件失败: {str(e)}")
    
    def refresh_data(self):
        """刷新配置数据"""
        self.load_config()