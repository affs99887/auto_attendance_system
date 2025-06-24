"""
日志查看面板
实时显示系统日志，支持筛选和搜索
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import threading
import time
from datetime import datetime

try:
    from ..utils.gui_utils import (
        create_labeled_frame, StatusColors, ScrollableFrame
    )
except ImportError:
    from gui_client.utils.gui_utils import (
        create_labeled_frame, StatusColors, ScrollableFrame
    )

class LogPanel:
    """日志查看面板类"""
    
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        
        # 日志监控控制
        self.log_monitoring = False
        self.monitor_thread = None
        self.last_log_size = 0
        
        # 创建界面
        self.create_widgets()
        
        # 初始化数据
        self.refresh_data()
    
    def create_widgets(self):
        """创建日志面板的所有组件"""
        # 主框架
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 控制区域
        self.create_control_section(main_frame)
        
        # 日志显示区域
        self.create_log_display_section(main_frame)
        
        # 状态区域
        self.create_status_section(main_frame)
    
    def create_control_section(self, parent):
        """创建控制区域"""
        frame = create_labeled_frame(parent, "🔧 日志控制")
        frame.pack(fill=tk.X, pady=(0, 10))
        
        # 上方控制按钮
        top_controls = ttk.Frame(frame)
        top_controls.pack(fill=tk.X, pady=(0, 5))
        
        # 刷新按钮
        ttk.Button(
            top_controls,
            text="刷新日志",
            command=self.refresh_logs
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        # 清空按钮
        ttk.Button(
            top_controls,
            text="清空显示",
            command=self.clear_display
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        # 导出按钮
        ttk.Button(
            top_controls,
            text="导出日志",
            command=self.export_logs
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        # 实时监控开关
        self.monitor_var = tk.BooleanVar()
        self.monitor_check = ttk.Checkbutton(
            top_controls,
            text="实时监控",
            variable=self.monitor_var,
            command=self.toggle_monitoring
        )
        self.monitor_check.pack(side=tk.LEFT, padx=(10, 0))
        
        # 下方筛选控制
        filter_frame = ttk.Frame(frame)
        filter_frame.pack(fill=tk.X)
        
        # 日志级别筛选
        ttk.Label(filter_frame, text="级别:").pack(side=tk.LEFT)
        
        self.level_var = tk.StringVar(value="ALL")
        level_combo = ttk.Combobox(
            filter_frame,
            textvariable=self.level_var,
            values=["ALL", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            state="readonly",
            width=10
        )
        level_combo.pack(side=tk.LEFT, padx=(5, 10))
        level_combo.bind('<<ComboboxSelected>>', self.filter_logs)
        
        # 搜索框
        ttk.Label(filter_frame, text="搜索:").pack(side=tk.LEFT)
        
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(
            filter_frame,
            textvariable=self.search_var,
            width=20
        )
        search_entry.pack(side=tk.LEFT, padx=(5, 5))
        search_entry.bind('<KeyRelease>', self.search_logs)
        
        # 搜索按钮
        ttk.Button(
            filter_frame,
            text="搜索",
            command=self.search_logs
        ).pack(side=tk.LEFT)
    
    def create_log_display_section(self, parent):
        """创建日志显示区域"""
        frame = create_labeled_frame(parent, "📜 日志内容")
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 创建文本显示区域
        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        # 日志文本控件
        self.log_text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#ffffff",
            insertbackground="white"
        )
        
        # 垂直滚动条
        v_scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=v_scrollbar.set)
        
        # 水平滚动条
        h_scrollbar = ttk.Scrollbar(text_frame, orient=tk.HORIZONTAL, command=self.log_text.xview)
        self.log_text.configure(xscrollcommand=h_scrollbar.set)
        
        # 布局
        self.log_text.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        
        text_frame.grid_columnconfigure(0, weight=1)
        text_frame.grid_rowconfigure(0, weight=1)
        
        # 配置日志颜色标签
        self.setup_log_tags()
        
        # 右键菜单
        self.create_context_menu()
    
    def create_status_section(self, parent):
        """创建状态区域"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X)
        
        # 日志文件路径
        self.log_file_label = ttk.Label(frame, text="日志文件: --")
        self.log_file_label.pack(side=tk.LEFT)
        
        # 日志行数
        self.log_lines_label = ttk.Label(frame, text="行数: 0")
        self.log_lines_label.pack(side=tk.RIGHT)
        
        # 监控状态
        self.monitor_status_label = ttk.Label(frame, text="监控: 未启动")
        self.monitor_status_label.pack(side=tk.RIGHT, padx=(0, 10))
    
    def setup_log_tags(self):
        """设置日志颜色标签"""
        # DEBUG - 灰色
        self.log_text.tag_configure("DEBUG", foreground="#888888")
        
        # INFO - 白色（默认）
        self.log_text.tag_configure("INFO", foreground="#ffffff")
        
        # WARNING - 黄色
        self.log_text.tag_configure("WARNING", foreground="#ffcc00")
        
        # ERROR - 红色
        self.log_text.tag_configure("ERROR", foreground="#ff6666")
        
        # CRITICAL - 亮红色
        self.log_text.tag_configure("CRITICAL", foreground="#ff0000", font=("Consolas", 9, "bold"))
        
        # 时间戳 - 蓝色
        self.log_text.tag_configure("TIMESTAMP", foreground="#66ccff")
        
        # 模块名 - 绿色
        self.log_text.tag_configure("MODULE", foreground="#66ff66")
    
    def create_context_menu(self):
        """创建右键菜单"""
        self.context_menu = tk.Menu(self.log_text, tearoff=0)
        self.context_menu.add_command(label="复制", command=self.copy_selection)
        self.context_menu.add_command(label="全选", command=self.select_all)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="清空", command=self.clear_display)
        self.context_menu.add_command(label="查找", command=self.show_find_dialog)
        
        self.log_text.bind("<Button-3>", self.show_context_menu)
    
    def show_context_menu(self, event):
        """显示右键菜单"""
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
    
    def copy_selection(self):
        """复制选中文本"""
        try:
            selected_text = self.log_text.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.log_text.clipboard_clear()
            self.log_text.clipboard_append(selected_text)
        except tk.TclError:
            pass  # 没有选中文本
    
    def select_all(self):
        """全选文本"""
        self.log_text.tag_add(tk.SEL, "1.0", tk.END)
        self.log_text.mark_set(tk.INSERT, "1.0")
        self.log_text.see(tk.INSERT)
    
    def show_find_dialog(self):
        """显示查找对话框"""
        # 简单的查找实现
        search_text = self.search_var.get()
        if search_text:
            self.search_in_text(search_text)
        else:
            messagebox.showinfo("查找", "请在搜索框中输入要查找的内容")
    
    def refresh_data(self):
        """刷新日志数据"""
        self.refresh_logs()
        self.update_status_info()
    
    def refresh_logs(self):
        """刷新日志显示"""
        try:
            # 查找日志文件
            log_file = self.find_log_file()
            
            if log_file and os.path.exists(log_file):
                self.load_log_file(log_file)
                self.log_file_label.config(text=f"日志文件: {os.path.basename(log_file)}")
            else:
                self.log_text.delete(1.0, tk.END)
                self.log_text.insert(tk.END, "未找到日志文件\n")
                self.log_file_label.config(text="日志文件: 未找到")
                
        except Exception as e:
            messagebox.showerror("错误", f"刷新日志失败: {str(e)}")
    
    def find_log_file(self):
        """查找日志文件"""
        # 可能的日志文件位置
        possible_files = [
            "attendance_system.log",
            "logs/attendance_system.log",
            "logs/gui_client.log",
            "gui_client.log"
        ]
        
        for file_path in possible_files:
            if os.path.exists(file_path):
                return file_path
        
        return None
    
    def load_log_file(self, file_path):
        """加载日志文件"""
        try:
            # 尝试不同的编码
            encodings = ['utf-8', 'gbk', 'gb2312', 'latin1']
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                # 所有编码都失败
                self.log_text.delete(1.0, tk.END)
                self.log_text.insert(tk.END, "无法读取日志文件，编码不支持\n")
                return
            
            # 显示日志内容
            self.display_log_content(content)
            
            # 更新文件大小
            self.last_log_size = os.path.getsize(file_path)
            
        except Exception as e:
            self.log_text.delete(1.0, tk.END)
            self.log_text.insert(tk.END, f"读取日志文件失败: {str(e)}\n")
    
    def display_log_content(self, content):
        """显示日志内容并应用颜色"""
        self.log_text.delete(1.0, tk.END)
        
        lines = content.split('\n')
        line_count = 0
        
        for line in lines:
            if line.strip():  # 跳过空行
                self.insert_colored_line(line)
                line_count += 1
        
        # 滚动到底部
        self.log_text.see(tk.END)
        
        # 更新行数
        self.log_lines_label.config(text=f"行数: {line_count}")
    
    def insert_colored_line(self, line):
        """插入带颜色的日志行"""
        # 解析日志行格式: 时间戳 - 模块 - 级别 - 消息
        parts = line.split(' - ', 3)
        
        if len(parts) >= 4:
            timestamp, module, level, message = parts
            
            # 插入时间戳
            start_pos = self.log_text.index(tk.INSERT)
            self.log_text.insert(tk.END, timestamp)
            end_pos = self.log_text.index(tk.INSERT)
            self.log_text.tag_add("TIMESTAMP", start_pos, end_pos)
            
            self.log_text.insert(tk.END, " - ")
            
            # 插入模块名
            start_pos = self.log_text.index(tk.INSERT)
            self.log_text.insert(tk.END, module)
            end_pos = self.log_text.index(tk.INSERT)
            self.log_text.tag_add("MODULE", start_pos, end_pos)
            
            self.log_text.insert(tk.END, " - ")
            
            # 插入级别和消息
            start_pos = self.log_text.index(tk.INSERT)
            self.log_text.insert(tk.END, f"{level} - {message}")
            end_pos = self.log_text.index(tk.INSERT)
            
            # 根据级别应用颜色
            if level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                self.log_text.tag_add(level, start_pos, end_pos)
            
        else:
            # 无法解析的行，使用默认颜色
            self.log_text.insert(tk.END, line)
        
        self.log_text.insert(tk.END, "\n")
    
    def toggle_monitoring(self):
        """切换实时监控"""
        if self.monitor_var.get():
            self.start_monitoring()
        else:
            self.stop_monitoring()
    
    def start_monitoring(self):
        """开始实时监控"""
        if not self.log_monitoring:
            self.log_monitoring = True
            self.monitor_thread = threading.Thread(target=self.monitor_log_file, daemon=True)
            self.monitor_thread.start()
            
            self.monitor_status_label.config(
                text="监控: 运行中", 
                foreground=StatusColors.SUCCESS
            )
    
    def stop_monitoring(self):
        """停止实时监控"""
        self.log_monitoring = False
        
        self.monitor_status_label.config(
            text="监控: 已停止", 
            foreground=StatusColors.ERROR
        )
    
    def monitor_log_file(self):
        """监控日志文件变化"""
        while self.log_monitoring:
            try:
                log_file = self.find_log_file()
                
                if log_file and os.path.exists(log_file):
                    current_size = os.path.getsize(log_file)
                    
                    if current_size > self.last_log_size:
                        # 文件有新内容
                        self.parent.after(0, self.refresh_logs)
                        self.last_log_size = current_size
                
                time.sleep(2)  # 每2秒检查一次
                
            except Exception:
                pass  # 忽略监控过程中的错误
    
    def filter_logs(self, event=None):
        """根据级别筛选日志"""
        # 重新加载并筛选日志
        self.refresh_logs()
    
    def search_logs(self, event=None):
        """搜索日志"""
        search_text = self.search_var.get().strip()
        
        if search_text:
            self.search_in_text(search_text)
    
    def search_in_text(self, search_text):
        """在文本中搜索"""
        # 清除之前的搜索标记
        self.log_text.tag_remove("search", "1.0", tk.END)
        
        if search_text:
            # 配置搜索标记样式
            self.log_text.tag_configure("search", background="yellow", foreground="black")
            
            # 搜索所有匹配项
            start_pos = "1.0"
            match_count = 0
            
            while True:
                start_pos = self.log_text.search(search_text, start_pos, tk.END)
                if not start_pos:
                    break
                
                end_pos = f"{start_pos}+{len(search_text)}c"
                self.log_text.tag_add("search", start_pos, end_pos)
                start_pos = end_pos
                match_count += 1
            
            if match_count > 0:
                # 跳转到第一个匹配项
                first_match = self.log_text.search(search_text, "1.0", tk.END)
                if first_match:
                    self.log_text.see(first_match)
                    
                messagebox.showinfo("搜索结果", f"找到 {match_count} 个匹配项")
            else:
                messagebox.showinfo("搜索结果", "未找到匹配项")
    
    def clear_display(self):
        """清空显示"""
        self.log_text.delete(1.0, tk.END)
        self.log_lines_label.config(text="行数: 0")
    
    def export_logs(self):
        """导出日志"""
        try:
            # 选择保存文件
            filename = filedialog.asksaveasfilename(
                title="导出日志",
                defaultextension=".txt",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
            )
            
            if filename:
                content = self.log_text.get(1.0, tk.END)
                
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                messagebox.showinfo("成功", f"日志已导出到: {filename}")
                
        except Exception as e:
            messagebox.showerror("错误", f"导出日志失败: {str(e)}")
    
    def update_status_info(self):
        """更新状态信息"""
        try:
            log_file = self.find_log_file()
            if log_file:
                self.log_file_label.config(text=f"日志文件: {os.path.basename(log_file)}")
            else:
                self.log_file_label.config(text="日志文件: 未找到")
        except Exception:
            self.log_file_label.config(text="日志文件: 获取失败")