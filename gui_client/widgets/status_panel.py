"""
系统状态显示面板
显示当前系统运行状态、打卡记录、系统资源等信息
"""

import tkinter as tk
from tkinter import ttk
from datetime import datetime
import psutil
from chinese_calendar import is_workday, is_holiday
import os

try:
    from ..utils.gui_utils import (
        create_labeled_frame, format_time_display, 
        format_datetime_display, StatusColors
    )
except ImportError:
    from gui_client.utils.gui_utils import (
        create_labeled_frame, format_time_display, 
        format_datetime_display, StatusColors
    )

class StatusPanel:
    """系统状态面板类"""
    
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        
        # 创建界面
        self.create_widgets()
        
        # 初始化数据
        self.refresh_data()
    
    def create_widgets(self):
        """创建状态面板的所有组件"""
        # 主框架
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 左侧面板
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        # 右侧面板
        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # 创建各个信息组
        self.create_time_info(left_frame)
        self.create_punch_info(left_frame)
        self.create_system_info(right_frame)
        self.create_config_info(right_frame)
    
    def create_time_info(self, parent):
        """创建时间信息组"""
        frame = create_labeled_frame(parent, "📅 日期时间信息")
        frame.pack(fill=tk.X, pady=(0, 10))
        
        # 当前时间
        self.current_time_label = ttk.Label(frame, text="当前时间: --")
        self.current_time_label.pack(anchor=tk.W, pady=2)
        
        # 日期类型
        self.date_type_label = ttk.Label(frame, text="日期类型: --")
        self.date_type_label.pack(anchor=tk.W, pady=2)
        
        # 工作状态
        self.work_status_label = ttk.Label(frame, text="工作状态: --")
        self.work_status_label.pack(anchor=tk.W, pady=2)
    
    def create_punch_info(self, parent):
        """创建打卡信息组"""
        frame = create_labeled_frame(parent, "📍 今日打卡记录")
        frame.pack(fill=tk.X, pady=(0, 10))
        
        # 上班打卡
        punch_in_frame = ttk.Frame(frame)
        punch_in_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(punch_in_frame, text="上班打卡:").pack(side=tk.LEFT)
        self.punch_in_status = ttk.Label(punch_in_frame, text="❌ 未打卡")
        self.punch_in_status.pack(side=tk.RIGHT)
        
        # 下班打卡
        punch_out_frame = ttk.Frame(frame)
        punch_out_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(punch_out_frame, text="下班打卡:").pack(side=tk.LEFT)
        self.punch_out_status = ttk.Label(punch_out_frame, text="❌ 未打卡")
        self.punch_out_status.pack(side=tk.RIGHT)
        
        # 工作时长
        work_time_frame = ttk.Frame(frame)
        work_time_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(work_time_frame, text="工作时长:").pack(side=tk.LEFT)
        self.work_duration_label = ttk.Label(work_time_frame, text="--")
        self.work_duration_label.pack(side=tk.RIGHT)
    
    def create_system_info(self, parent):
        """创建系统信息组"""
        frame = create_labeled_frame(parent, "⚙️ 系统信息")
        frame.pack(fill=tk.X, pady=(0, 10))
        
        # 系统运行状态
        status_frame = ttk.Frame(frame)
        status_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(status_frame, text="系统状态:").pack(side=tk.LEFT)
        self.system_status_label = ttk.Label(status_frame, text="未启动")
        self.system_status_label.pack(side=tk.RIGHT)
        
        # 运行时长
        uptime_frame = ttk.Frame(frame)
        uptime_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(uptime_frame, text="运行时长:").pack(side=tk.LEFT)
        self.uptime_label = ttk.Label(uptime_frame, text="--")
        self.uptime_label.pack(side=tk.RIGHT)
        
        # 内存使用
        memory_frame = ttk.Frame(frame)
        memory_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(memory_frame, text="内存使用:").pack(side=tk.LEFT)
        self.memory_label = ttk.Label(memory_frame, text="--")
        self.memory_label.pack(side=tk.RIGHT)
        
        # CPU使用
        cpu_frame = ttk.Frame(frame)
        cpu_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(cpu_frame, text="CPU使用:").pack(side=tk.LEFT)
        self.cpu_label = ttk.Label(cpu_frame, text="--")
        self.cpu_label.pack(side=tk.RIGHT)
        
        # 心跳状态
        heartbeat_frame = ttk.Frame(frame)
        heartbeat_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(heartbeat_frame, text="心跳状态:").pack(side=tk.LEFT)
        self.heartbeat_label = ttk.Label(heartbeat_frame, text="--")
        self.heartbeat_label.pack(side=tk.RIGHT)
    
    def create_config_info(self, parent):
        """创建配置信息组"""
        frame = create_labeled_frame(parent, "📋 配置信息")
        frame.pack(fill=tk.X)
        
        # 上班时间
        start_time_frame = ttk.Frame(frame)
        start_time_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(start_time_frame, text="上班时间:").pack(side=tk.LEFT)
        self.work_start_label = ttk.Label(start_time_frame, text="--")
        self.work_start_label.pack(side=tk.RIGHT)
        
        # 下班时间
        end_time_frame = ttk.Frame(frame)
        end_time_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(end_time_frame, text="下班时间:").pack(side=tk.LEFT)
        self.work_end_label = ttk.Label(end_time_frame, text="--")
        self.work_end_label.pack(side=tk.RIGHT)
        
        # 迟到阈值
        late_frame = ttk.Frame(frame)
        late_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(late_frame, text="迟到阈值:").pack(side=tk.LEFT)
        self.late_threshold_label = ttk.Label(late_frame, text="--")
        self.late_threshold_label.pack(side=tk.RIGHT)
        
        # 早退阈值
        early_frame = ttk.Frame(frame)
        early_frame.pack(fill=tk.X, pady=2)
        
        ttk.Label(early_frame, text="早退阈值:").pack(side=tk.LEFT)
        self.early_threshold_label = ttk.Label(early_frame, text="--")
        self.early_threshold_label.pack(side=tk.RIGHT)
    
    def refresh_data(self):
        """刷新状态数据"""
        try:
            # 更新时间信息
            self.update_time_info()
            
            # 更新系统信息
            self.update_system_info()
            
            # 更新打卡信息
            self.update_punch_info()
            
            # 更新配置信息
            self.update_config_info()
            
        except Exception as e:
            print(f"刷新状态数据时发生错误: {str(e)}")
    
    def update_time_info(self):
        """更新时间信息"""
        current_time = datetime.now()
        
        # 当前时间
        self.current_time_label.config(
            text=f"当前时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        # 日期类型
        current_date = current_time.date()
        if is_holiday(current_date):
            date_type = "🏖️ 节假日"
            date_color = StatusColors.WARNING
        elif is_workday(current_date):
            date_type = "💼 工作日"
            date_color = StatusColors.INFO
        else:
            date_type = "🎉 休息日"
            date_color = StatusColors.SECONDARY
        
        self.date_type_label.config(text=f"日期类型: {date_type}", foreground=date_color)
        
        # 工作状态
        if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
            try:
                is_work_time = self.app.attendance_system.is_work_time(current_time)
                work_status = "🟢 工作时间" if is_work_time else "🔴 非工作时间"
                work_color = StatusColors.SUCCESS if is_work_time else StatusColors.ERROR
            except:
                work_status = "❓ 未知"
                work_color = StatusColors.SECONDARY
        else:
            work_status = "❓ 系统未启动"
            work_color = StatusColors.SECONDARY
        
        self.work_status_label.config(text=f"工作状态: {work_status}", foreground=work_color)
    
    def update_system_info(self):
        """更新系统信息"""
        # 系统运行状态
        if self.app.system_running:
            self.system_status_label.config(text="🟢 运行中", foreground=StatusColors.SUCCESS)
        else:
            self.system_status_label.config(text="🔴 未运行", foreground=StatusColors.ERROR)
        
        # 获取系统资源信息
        try:
            # 内存使用
            memory = psutil.virtual_memory()
            memory_color = StatusColors.SUCCESS
            if memory.percent > 80:
                memory_color = StatusColors.ERROR
            elif memory.percent > 60:
                memory_color = StatusColors.WARNING
            
            self.memory_label.config(
                text=f"{memory.percent:.1f}%", 
                foreground=memory_color
            )
            
            # CPU使用
            cpu_percent = psutil.cpu_percent()
            cpu_color = StatusColors.SUCCESS
            if cpu_percent > 80:
                cpu_color = StatusColors.ERROR
            elif cpu_percent > 60:
                cpu_color = StatusColors.WARNING
            
            self.cpu_label.config(
                text=f"{cpu_percent:.1f}%", 
                foreground=cpu_color
            )
            
            # 运行时长
            try:
                process = psutil.Process()
                uptime = datetime.now() - datetime.fromtimestamp(process.create_time())
                hours, remainder = divmod(uptime.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                self.uptime_label.config(text=f"{int(hours)}h {int(minutes)}m")
            except:
                self.uptime_label.config(text="--")
            
            # 心跳状态
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                try:
                    heartbeat_count = getattr(self.app.attendance_system, 'heartbeat_miss_count', 0)
                    if heartbeat_count == 0:
                        self.heartbeat_label.config(text="🟢 正常", foreground=StatusColors.SUCCESS)
                    else:
                        self.heartbeat_label.config(text="🟡 警告", foreground=StatusColors.WARNING)
                except:
                    self.heartbeat_label.config(text="❓ 未知", foreground=StatusColors.SECONDARY)
            else:
                self.heartbeat_label.config(text="❓ 未知", foreground=StatusColors.SECONDARY)
                
        except Exception as e:
            self.memory_label.config(text="--")
            self.cpu_label.config(text="--")
            self.uptime_label.config(text="--")
            self.heartbeat_label.config(text="--")
    
    def update_punch_info(self):
        """更新打卡信息"""
        if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
            try:
                records = self.app.attendance_system.today_punch_records
                
                # 上班打卡
                punch_in_time = records.get('punch_in_time')
                if punch_in_time:
                    time_str = format_time_display(punch_in_time)
                    self.punch_in_status.config(
                        text=f"✅ {time_str}", 
                        foreground=StatusColors.SUCCESS
                    )
                else:
                    self.punch_in_status.config(
                        text="❌ 未打卡", 
                        foreground=StatusColors.ERROR
                    )
                
                # 下班打卡
                punch_out_time = records.get('punch_out_time')
                if punch_out_time:
                    time_str = format_time_display(punch_out_time)
                    self.punch_out_status.config(
                        text=f"✅ {time_str}", 
                        foreground=StatusColors.SUCCESS
                    )
                else:
                    self.punch_out_status.config(
                        text="❌ 未打卡", 
                        foreground=StatusColors.ERROR
                    )
                
                # 工作时长
                if punch_in_time and punch_out_time:
                    try:
                        # 计算工作时长
                        if isinstance(punch_in_time, str):
                            in_time = datetime.strptime(punch_in_time, "%H:%M:%S").time()
                        else:
                            in_time = punch_in_time.time() if hasattr(punch_in_time, 'time') else punch_in_time
                        
                        if isinstance(punch_out_time, str):
                            out_time = datetime.strptime(punch_out_time, "%H:%M:%S").time()
                        else:
                            out_time = punch_out_time.time() if hasattr(punch_out_time, 'time') else punch_out_time
                        
                        # 计算时长
                        today = datetime.now().date()
                        in_datetime = datetime.combine(today, in_time)
                        out_datetime = datetime.combine(today, out_time)
                        
                        if out_datetime > in_datetime:
                            duration = out_datetime - in_datetime
                            hours, remainder = divmod(duration.total_seconds(), 3600)
                            minutes, _ = divmod(remainder, 60)
                            duration_str = f"{int(hours)}h {int(minutes)}m"
                            
                            # 根据工作时长设置颜色
                            if hours >= 8:
                                color = StatusColors.SUCCESS
                            elif hours >= 6:
                                color = StatusColors.WARNING
                            else:
                                color = StatusColors.ERROR
                            
                            self.work_duration_label.config(text=duration_str, foreground=color)
                        else:
                            self.work_duration_label.config(text="计算错误")
                    except Exception:
                        self.work_duration_label.config(text="计算失败")
                else:
                    self.work_duration_label.config(text="--")
                
            except Exception as e:
                self.punch_in_status.config(text="❌ 获取失败", foreground=StatusColors.ERROR)
                self.punch_out_status.config(text="❌ 获取失败", foreground=StatusColors.ERROR)
                self.work_duration_label.config(text="--")
        else:
            self.punch_in_status.config(text="❌ 系统未启动", foreground=StatusColors.SECONDARY)
            self.punch_out_status.config(text="❌ 系统未启动", foreground=StatusColors.SECONDARY)
            self.work_duration_label.config(text="--")
    
    def update_config_info(self):
        """更新配置信息"""
        try:
            # 从环境变量获取配置信息
            work_start_time = os.getenv('WORK_START_TIME', '09:00')
            work_end_time = os.getenv('WORK_END_TIME', '17:30')
            
            self.work_start_label.config(text=work_start_time)
            self.work_end_label.config(text=work_end_time)
            
            # 如果系统已启动，从系统对象获取更详细的配置
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                try:
                    late_threshold = getattr(self.app.attendance_system, 'late_threshold', 30)
                    early_threshold = getattr(self.app.attendance_system, 'early_leave_threshold', 30)
                    
                    self.late_threshold_label.config(text=f"{late_threshold}分钟")
                    self.early_threshold_label.config(text=f"{early_threshold}分钟")
                except:
                    self.late_threshold_label.config(text="30分钟")
                    self.early_threshold_label.config(text="30分钟")
            else:
                self.late_threshold_label.config(text="30分钟")
                self.early_threshold_label.config(text="30分钟")
                
        except Exception as e:
            self.work_start_label.config(text="--")
            self.work_end_label.config(text="--")
            self.late_threshold_label.config(text="--")
            self.early_threshold_label.config(text="--")