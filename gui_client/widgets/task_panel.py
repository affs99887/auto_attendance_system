"""
任务管理面板
显示和管理定时任务
"""

import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta

try:
    from ..utils.gui_utils import (
        create_labeled_frame, format_datetime_display, 
        StatusColors, ask_yes_no
    )
except ImportError:
    from gui_client.utils.gui_utils import (
        create_labeled_frame, format_datetime_display, 
        StatusColors, ask_yes_no
    )

class TaskPanel:
    """任务管理面板类"""
    
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        
        # 创建界面
        self.create_widgets()
        
        # 初始化数据
        self.refresh_data()
    
    def create_widgets(self):
        """创建任务管理面板的所有组件"""
        # 主框架
        main_frame = ttk.Frame(self.parent)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 任务列表区域
        self.create_task_list_section(main_frame)
        
        # 任务操作区域
        self.create_task_operations_section(main_frame)
    
    def create_task_list_section(self, parent):
        """创建任务列表区域"""
        frame = create_labeled_frame(parent, "📋 定时任务列表")
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 控制按钮
        control_frame = ttk.Frame(frame)
        control_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            control_frame,
            text="刷新任务",
            command=self.refresh_data
        ).pack(side=tk.LEFT)
        
        ttk.Button(
            control_frame,
            text="删除选中",
            command=self.delete_selected_task
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(
            control_frame,
            text="清空所有",
            command=self.clear_all_tasks
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        # 任务列表树形视图
        columns = ("id", "type", "time", "next_run", "created")
        self.task_tree = ttk.Treeview(frame, columns=columns, show='headings')
        
        # 设置列标题
        self.task_tree.heading("id", text="ID")
        self.task_tree.heading("type", text="类型")
        self.task_tree.heading("time", text="执行时间")
        self.task_tree.heading("next_run", text="下次执行")
        self.task_tree.heading("created", text="创建时间")
        
        # 设置列宽
        self.task_tree.column("id", width=50)
        self.task_tree.column("type", width=100)
        self.task_tree.column("time", width=100)
        self.task_tree.column("next_run", width=150)
        self.task_tree.column("created", width=150)
        
        # 添加滚动条
        tree_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.task_tree.yview)
        self.task_tree.configure(yscrollcommand=tree_scroll.set)
        
        # 布局
        self.task_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 绑定选择事件
        self.task_tree.bind('<<TreeviewSelect>>', self.on_task_select)
    
    def create_task_operations_section(self, parent):
        """创建任务操作区域"""
        frame = create_labeled_frame(parent, "⚙️ 任务操作")
        frame.pack(fill=tk.X)
        
        # 任务详情显示
        details_frame = ttk.Frame(frame)
        details_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 选中任务信息
        self.selected_task_label = ttk.Label(
            details_frame, 
            text="选中任务: 无"
        )
        self.selected_task_label.pack(anchor=tk.W)
        
        # 任务状态
        self.task_status_label = ttk.Label(
            details_frame,
            text="状态: --"
        )
        self.task_status_label.pack(anchor=tk.W, pady=(2, 0))
        
        # 操作按钮区域
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X)
        
        # 删除任务按钮
        self.delete_task_btn = ttk.Button(
            button_frame,
            text="删除选中任务",
            command=self.delete_selected_task,
            state=tk.DISABLED
        )
        self.delete_task_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # 立即执行按钮
        self.execute_task_btn = ttk.Button(
            button_frame,
            text="立即执行",
            command=self.execute_selected_task,
            state=tk.DISABLED
        )
        self.execute_task_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # 任务统计信息
        stats_frame = ttk.Frame(frame)
        stats_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.stats_label = ttk.Label(
            stats_frame,
            text="任务统计: 总共 0 个任务"
        )
        self.stats_label.pack(anchor=tk.W)
    
    def refresh_data(self):
        """刷新任务数据"""
        try:
            # 清空现有任务
            for item in self.task_tree.get_children():
                self.task_tree.delete(item)
            
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                tasks = self.app.attendance_system.task_manager.get_tasks()
                current_time = datetime.now()
                
                for task in tasks:
                    task_id = task.get('id', '')
                    task_type = task.get('type', '')
                    scheduled_time = task.get('scheduled_time', '')
                    created_at = task.get('created_at', '')
                    
                    # 任务类型显示名称
                    type_display = "上班打卡" if task_type == 'punch_in' else "下班打卡"
                    
                    # 计算下次执行时间
                    next_run = self.calculate_next_run(scheduled_time, current_time)
                    
                    self.task_tree.insert(
                        "",
                        tk.END,
                        values=(
                            task_id,
                            type_display,
                            scheduled_time,
                            next_run,
                            created_at
                        )
                    )
                
                # 更新统计信息
                self.stats_label.config(text=f"任务统计: 总共 {len(tasks)} 个任务")
            else:
                self.stats_label.config(text="任务统计: 系统未启动")
                
        except Exception as e:
            messagebox.showerror("错误", f"刷新任务数据失败: {str(e)}")
    
    def calculate_next_run(self, scheduled_time, current_time):
        """计算下次执行时间"""
        try:
            # 解析时间
            time_parts = scheduled_time.split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1])
            
            # 今天的执行时间
            today_run = current_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            if today_run > current_time:
                # 今天还没执行
                return today_run.strftime('%Y-%m-%d %H:%M')
            else:
                # 今天已过，明天执行
                tomorrow_run = today_run + timedelta(days=1)
                return tomorrow_run.strftime('%Y-%m-%d %H:%M')
                
        except Exception:
            return "计算失败"
    
    def on_task_select(self, event):
        """任务选择事件处理"""
        selection = self.task_tree.selection()
        
        if selection:
            item = self.task_tree.item(selection[0])
            values = item['values']
            
            if values:
                task_id = values[0]
                task_type = values[1]
                scheduled_time = values[2]
                
                # 更新选中任务信息
                self.selected_task_label.config(
                    text=f"选中任务: ID {task_id} - {task_type} ({scheduled_time})"
                )
                
                # 启用操作按钮
                self.delete_task_btn.config(state=tk.NORMAL)
                self.execute_task_btn.config(state=tk.NORMAL)
                
                # 更新任务状态
                self.update_task_status(task_id)
        else:
            # 没有选中任务
            self.selected_task_label.config(text="选中任务: 无")
            self.task_status_label.config(text="状态: --")
            self.delete_task_btn.config(state=tk.DISABLED)
            self.execute_task_btn.config(state=tk.DISABLED)
    
    def update_task_status(self, task_id):
        """更新任务状态显示"""
        try:
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                task = self.app.attendance_system.task_manager.get_task_by_id(int(task_id))
                if task:
                    # 检查任务是否在调度器中
                    import schedule
                    active_jobs = len(schedule.jobs)
                    
                    if active_jobs > 0:
                        self.task_status_label.config(
                            text="状态: 🟢 已调度",
                            foreground=StatusColors.SUCCESS
                        )
                    else:
                        self.task_status_label.config(
                            text="状态: 🟡 未调度",
                            foreground=StatusColors.WARNING
                        )
                else:
                    self.task_status_label.config(
                        text="状态: ❌ 任务不存在",
                        foreground=StatusColors.ERROR
                    )
            else:
                self.task_status_label.config(
                    text="状态: ❓ 系统未启动",
                    foreground=StatusColors.SECONDARY
                )
        except Exception:
            self.task_status_label.config(
                text="状态: ❓ 获取失败",
                foreground=StatusColors.SECONDARY
            )
    
    def delete_selected_task(self):
        """删除选中的任务"""
        selection = self.task_tree.selection()
        
        if not selection:
            messagebox.showwarning("警告", "请先选择要删除的任务")
            return
        
        item = self.task_tree.item(selection[0])
        values = item['values']
        
        if not values:
            return
        
        task_id = values[0]
        task_type = values[1]
        
        if not ask_yes_no(
            self.parent, 
            "确认删除", 
            f"确定要删除任务 ID {task_id} ({task_type}) 吗？"
        ):
            return
        
        try:
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                success = self.app.attendance_system.task_manager.remove_task_by_id(int(task_id))
                
                if success:
                    messagebox.showinfo("成功", f"任务 ID {task_id} 已删除")
                    
                    # 清除调度器中的任务
                    import schedule
                    schedule.clear()
                    
                    # 重新加载剩余任务到调度器
                    self.reload_scheduler_tasks()
                    
                    # 刷新显示
                    self.refresh_data()
                else:
                    messagebox.showerror("错误", f"删除任务 ID {task_id} 失败")
            else:
                messagebox.showerror("错误", "系统未启动，无法删除任务")
                
        except Exception as e:
            messagebox.showerror("错误", f"删除任务失败: {str(e)}")
    
    def clear_all_tasks(self):
        """清空所有任务"""
        if not ask_yes_no(
            self.parent,
            "确认清空",
            "确定要删除所有定时任务吗？此操作不可撤销！"
        ):
            return
        
        try:
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                # 清除所有任务
                self.app.attendance_system.task_manager.clear_tasks()
                
                # 清除调度器
                import schedule
                schedule.clear()
                
                messagebox.showinfo("成功", "所有定时任务已清除")
                self.refresh_data()
            else:
                messagebox.showerror("错误", "系统未启动，无法清空任务")
                
        except Exception as e:
            messagebox.showerror("错误", f"清空任务失败: {str(e)}")
    
    def execute_selected_task(self):
        """立即执行选中的任务"""
        selection = self.task_tree.selection()
        
        if not selection:
            messagebox.showwarning("警告", "请先选择要执行的任务")
            return
        
        item = self.task_tree.item(selection[0])
        values = item['values']
        
        if not values:
            return
        
        task_id = values[0]
        task_type = values[1]
        
        if not ask_yes_no(
            self.parent,
            "确认执行",
            f"确定要立即执行任务 ID {task_id} ({task_type}) 吗？"
        ):
            return
        
        try:
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                task = self.app.attendance_system.task_manager.get_task_by_id(int(task_id))
                
                if task:
                    task_type_code = task['type']
                    
                    if task_type_code == 'punch_in':
                        self.app.manual_punch_in()
                        messagebox.showinfo("执行", "上班打卡任务已提交执行")
                    elif task_type_code == 'punch_out':
                        self.app.manual_punch_out()
                        messagebox.showinfo("执行", "下班打卡任务已提交执行")
                    else:
                        messagebox.showerror("错误", f"未知的任务类型: {task_type_code}")
                else:
                    messagebox.showerror("错误", f"任务 ID {task_id} 不存在")
            else:
                messagebox.showerror("错误", "系统未启动，无法执行任务")
                
        except Exception as e:
            messagebox.showerror("错误", f"执行任务失败: {str(e)}")
    
    def reload_scheduler_tasks(self):
        """重新加载调度器中的任务"""
        try:
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                import schedule
                import asyncio
                
                tasks = self.app.attendance_system.task_manager.get_tasks()
                
                for task in tasks:
                    task_type = task['type']
                    scheduled_time = task['scheduled_time']
                    
                    if task_type == 'punch_in':
                        async def punch_in_job():
                            await self.app.attendance_system.punch_in()
                        schedule.every().day.at(scheduled_time).do(
                            lambda: asyncio.create_task(punch_in_job())
                        )
                    elif task_type == 'punch_out':
                        async def punch_out_job():
                            await self.app.attendance_system.punch_out()
                        schedule.every().day.at(scheduled_time).do(
                            lambda: asyncio.create_task(punch_out_job())
                        )
                        
        except Exception as e:
            print(f"重新加载调度器任务失败: {str(e)}")