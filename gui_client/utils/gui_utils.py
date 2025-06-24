"""
GUI工具函数模块
提供通用的GUI辅助功能
"""

import tkinter as tk
from tkinter import ttk
import os
from PIL import Image, ImageTk
import base64
import io

def set_window_icon(window, icon_path=None):
    """设置窗口图标"""
    try:
        if icon_path and os.path.exists(icon_path):
            # 如果提供了图标路径且文件存在，使用该图标
            icon = Image.open(icon_path)
            icon = icon.resize((32, 32), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(icon)
            window.iconphoto(True, photo)
        else:
            # 使用默认图标（简单的文本图标）
            # 这里可以创建一个简单的默认图标
            pass
    except Exception:
        # 如果设置图标失败，继续运行不受影响
        pass

def center_window(window, width, height):
    """将窗口居中显示"""
    try:
        # 获取屏幕尺寸
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        
        # 计算居中位置
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        
        # 设置窗口位置和大小
        window.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        # 如果居中失败，使用默认位置
        window.geometry(f"{width}x{height}")

def create_labeled_frame(parent, text, padding=10):
    """创建带标签的框架"""
    frame = ttk.LabelFrame(parent, text=text, padding=padding)
    return frame

def create_status_label(parent, text="状态: 未知", style=None):
    """创建状态标签"""
    if style is None:
        label = ttk.Label(parent, text=text)
    else:
        label = ttk.Label(parent, text=text, style=style)
    return label

def create_button_with_icon(parent, text, command, state="normal", style=None):
    """创建带图标的按钮"""
    if style is None:
        button = ttk.Button(parent, text=text, command=command, state=state)
    else:
        button = ttk.Button(parent, text=text, command=command, state=state, style=style)
    return button

def format_time_display(dt):
    """格式化时间显示"""
    if dt is None:
        return "未记录"
    if isinstance(dt, str):
        return dt
    return dt.strftime("%H:%M:%S")

def format_date_display(dt):
    """格式化日期显示"""
    if dt is None:
        return "未知日期"
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d")

def format_datetime_display(dt):
    """格式化日期时间显示"""
    if dt is None:
        return "未记录"
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def show_error_dialog(parent, title, message):
    """显示错误对话框"""
    from tkinter import messagebox
    messagebox.showerror(title, message, parent=parent)

def show_info_dialog(parent, title, message):
    """显示信息对话框"""
    from tkinter import messagebox
    messagebox.showinfo(title, message, parent=parent)

def show_warning_dialog(parent, title, message):
    """显示警告对话框"""
    from tkinter import messagebox
    messagebox.showwarning(title, message, parent=parent)

def ask_yes_no(parent, title, message):
    """显示是/否确认对话框"""
    from tkinter import messagebox
    return messagebox.askyesno(title, message, parent=parent)

class StatusColors:
    """状态颜色常量"""
    SUCCESS = "#28a745"  # 绿色
    WARNING = "#ffc107"  # 黄色
    ERROR = "#dc3545"    # 红色
    INFO = "#17a2b8"     # 蓝色
    SECONDARY = "#6c757d" # 灰色

def setup_styles():
    """设置自定义样式"""
    style = ttk.Style()
    
    # 成功状态样式
    style.configure("Success.TLabel", foreground=StatusColors.SUCCESS)
    style.configure("Success.TButton", foreground=StatusColors.SUCCESS)
    
    # 警告状态样式
    style.configure("Warning.TLabel", foreground=StatusColors.WARNING)
    style.configure("Warning.TButton", foreground=StatusColors.WARNING)
    
    # 错误状态样式
    style.configure("Error.TLabel", foreground=StatusColors.ERROR)
    style.configure("Error.TButton", foreground=StatusColors.ERROR)
    
    # 信息状态样式
    style.configure("Info.TLabel", foreground=StatusColors.INFO)
    style.configure("Info.TButton", foreground=StatusColors.INFO)
    
    return style

class ScrollableFrame(ttk.Frame):
    """可滚动的框架组件"""
    
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        
        # 创建Canvas和Scrollbar
        self.canvas = tk.Canvas(self)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)
        
        # 配置滚动
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        # 布局
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮事件
        self.bind_mousewheel()
    
    def bind_mousewheel(self):
        """绑定鼠标滚轮事件"""
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_to_mousewheel(event):
            self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        def _unbind_from_mousewheel(event):
            self.canvas.unbind_all("<MouseWheel>")
        
        self.canvas.bind('<Enter>', _bind_to_mousewheel)
        self.canvas.bind('<Leave>', _unbind_from_mousewheel)

def create_tooltip(widget, text):
    """为控件创建工具提示"""
    def show_tooltip(event):
        tooltip = tk.Toplevel()
        tooltip.wm_overrideredirect(True)
        tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
        
        label = tk.Label(tooltip, text=text, background="lightyellow",
                        relief="solid", borderwidth=1, font=("Arial", 8))
        label.pack()
        
        def hide_tooltip():
            tooltip.destroy()
        
        tooltip.after(3000, hide_tooltip)  # 3秒后自动隐藏
        widget.tooltip = tooltip
    
    def hide_tooltip(event):
        if hasattr(widget, 'tooltip'):
            widget.tooltip.destroy()
    
    widget.bind("<Enter>", show_tooltip)
    widget.bind("<Leave>", hide_tooltip)