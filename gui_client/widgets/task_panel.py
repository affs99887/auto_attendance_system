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
        
        # 第一行按钮
        button_row1 = ttk.Frame(control_frame)
        button_row1.pack(fill=tk.X, pady=(0, 2))
        
        ttk.Button(
            button_row1,
            text="刷新任务",
            command=self.refresh_data
        ).pack(side=tk.LEFT)
        
        ttk.Button(
            button_row1,
            text="删除选中",
            command=self.delete_selected_tasks
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(
            button_row1,
            text="清空所有",
            command=self.clear_all_tasks
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        # 第二行按钮
        button_row2 = ttk.Frame(control_frame)
        button_row2.pack(fill=tk.X)
        
        ttk.Button(
            button_row2,
            text="全选",
            command=self.select_all_tasks
        ).pack(side=tk.LEFT)
        
        ttk.Button(
            button_row2,
            text="取消全选",
            command=self.deselect_all_tasks
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        ttk.Button(
            button_row2,
            text="反选",
            command=self.invert_selection
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        # 任务列表树形视图
        columns = ("id", "type", "time", "next_run", "created")
        self.task_tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='extended')
        
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
        
        # 绑定键盘快捷键
        self.task_tree.bind('<Delete>', lambda e: self.delete_selected_tasks())
        self.task_tree.bind('<Control-a>', lambda e: self.select_all_tasks())
        self.task_tree.bind('<Control-d>', lambda e: self.deselect_all_tasks())
        self.task_tree.bind('<Control-i>', lambda e: self.invert_selection())
        self.task_tree.bind('<F5>', lambda e: self.refresh_data())
        
        # 设置焦点，使键盘快捷键生效
        self.task_tree.focus_set()
    
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
        
        # 快捷键提示
        shortcuts_frame = ttk.Frame(frame)
        shortcuts_frame.pack(fill=tk.X, pady=(5, 0))
        
        shortcuts_text = "快捷键: Del-删除 | Ctrl+A-全选 | Ctrl+D-取消全选 | Ctrl+I-反选 | F5-刷新"
        ttk.Label(
            shortcuts_frame,
            text=shortcuts_text,
            font=("Arial", 8),
            foreground="#666666"
        ).pack(anchor=tk.W)
    
    def refresh_data(self):
        """刷新任务数据"""
        try:
            # 清空现有任务
            for item in self.task_tree.get_children():
                self.task_tree.delete(item)
            
            # 首先尝试从任务管理器获取任务
            tasks = []
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                tasks = self.app.attendance_system.task_manager.get_tasks()
            else:
                # 如果系统未启动，直接从文件读取任务
                try:
                    from tasks import TaskManager
                    temp_task_manager = TaskManager()
                    tasks = temp_task_manager.get_tasks()
                except Exception as e:
                    print(f"从文件读取任务失败: {e}")
                    tasks = []
            
            if tasks:
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
                self.stats_label.config(text="任务统计: 无任务")
                
        except Exception as e:
            print(f"刷新任务数据失败: {str(e)}")  # 使用print而不是messagebox，避免频繁弹窗
            self.stats_label.config(text="任务统计: 获取失败")
    
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
            if len(selection) == 1:
                # 单选时显示详细信息
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
                    
                    # 更新任务状态
                    self.update_task_status(task_id)
                    
                    # 启用单任务操作按钮
                    self.execute_task_btn.config(state=tk.NORMAL)
            else:
                # 多选时显示选中数量
                selected_ids = []
                for item_id in selection:
                    item = self.task_tree.item(item_id)
                    values = item['values']
                    if values:
                        selected_ids.append(values[0])
                
                self.selected_task_label.config(
                    text=f"已选中 {len(selection)} 个任务: {', '.join(map(str, selected_ids))}"
                )
                self.task_status_label.config(text="状态: 多任务选中")
                
                # 多选时禁用单任务操作按钮
                self.execute_task_btn.config(state=tk.DISABLED)
            
            # 有选中项时启用删除按钮
            self.delete_task_btn.config(state=tk.NORMAL)
            
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
    
    def delete_selected_tasks(self):
        """删除选中的任务（支持多选）"""
        selection = self.task_tree.selection()
        
        if not selection:
            messagebox.showwarning("警告", "请先选择要删除的任务")
            return
        
        # 收集选中的任务信息
        selected_tasks = []
        for item_id in selection:
            item = self.task_tree.item(item_id)
            values = item['values']
            if values:
                selected_tasks.append({
                    'id': values[0],
                    'type': values[1],
                    'time': values[2]
                })
        
        if not selected_tasks:
            messagebox.showwarning("警告", "没有有效的任务可删除")
            return
        
        # 构建确认消息
        if len(selected_tasks) == 1:
            task = selected_tasks[0]
            confirm_msg = f"确定要删除任务 ID {task['id']} ({task['type']}) 吗？"
        else:
            task_list = []
            for task in selected_tasks:
                task_list.append(f"ID {task['id']} ({task['type']})")
            confirm_msg = f"确定要删除以下 {len(selected_tasks)} 个任务吗？\n\n" + "\n".join(task_list)
        
        if not ask_yes_no(self.parent, "确认删除", confirm_msg):
            return
        
        try:
            if hasattr(self.app, 'attendance_system') and self.app.attendance_system:
                success_count = 0
                failed_tasks = []
                
                # 逐个删除任务
                for task in selected_tasks:
                    try:
                        task_id = int(task['id'])
                        success = self.app.attendance_system.task_manager.remove_task_by_id(task_id)
                        if success:
                            success_count += 1
                        else:
                            failed_tasks.append(f"ID {task_id}")
                    except Exception as e:
                        failed_tasks.append(f"ID {task['id']} (错误: {str(e)})")
                
                # 重新加载调度器
                if success_count > 0:
                    import schedule
                    schedule.clear()
                    self.reload_scheduler_tasks()
                
                # 显示结果
                if success_count == len(selected_tasks):
                    messagebox.showinfo("成功", f"成功删除 {success_count} 个任务")
                elif success_count > 0:
                    messagebox.showwarning("部分成功", 
                        f"成功删除 {success_count} 个任务\n失败的任务: {', '.join(failed_tasks)}")
                else:
                    messagebox.showerror("失败", f"所有任务删除失败\n失败的任务: {', '.join(failed_tasks)}")
                
                # 刷新显示
                self.refresh_data()
                
            else:
                messagebox.showerror("错误", "系统未启动，无法删除任务")
                
        except Exception as e:
            messagebox.showerror("错误", f"删除任务失败: {str(e)}")
    
    def delete_selected_task(self):
        """兼容旧方法名，调用新的多选删除方法"""
        self.delete_selected_tasks()
    
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
    
    def select_all_tasks(self):
        """全选所有任务"""
        try:
            all_items = self.task_tree.get_children()
            if all_items:
                self.task_tree.selection_set(all_items)
                # 手动触发选择事件
                self.on_task_select(None)
        except Exception as e:
            print(f"全选任务失败: {str(e)}")
    
    def deselect_all_tasks(self):
        """取消全选"""
        try:
            self.task_tree.selection_remove(self.task_tree.selection())
            # 手动触发选择事件
            self.on_task_select(None)
        except Exception as e:
            print(f"取消全选失败: {str(e)}")
    
    def invert_selection(self):
        """反选"""
        try:
            all_items = self.task_tree.get_children()
            current_selection = set(self.task_tree.selection())
            all_items_set = set(all_items)
            
            # 计算反选项目
            new_selection = all_items_set - current_selection
            
            # 清除当前选择并设置新选择
            self.task_tree.selection_remove(self.task_tree.selection())
            if new_selection:
                self.task_tree.selection_set(list(new_selection))
            
            # 手动触发选择事件
            self.on_task_select(None)
        except Exception as e:
            print(f"反选失败: {str(e)}")
    
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
                        def punch_in_job():
                            if self.app.event_loop and self.app.event_loop.is_running():
                                asyncio.run_coroutine_threadsafe(
                                    self.app.attendance_system.punch_in(),
                                    self.app.event_loop
                                )
                        schedule.every().day.at(scheduled_time).do(punch_in_job)
                    elif task_type == 'punch_out':
                        def punch_out_job():
                            if self.app.event_loop and self.app.event_loop.is_running():
                                asyncio.run_coroutine_threadsafe(
                                    self.app.attendance_system.punch_out(),
                                    self.app.event_loop
                                )
                        schedule.every().day.at(scheduled_time).do(punch_out_job)
                        
        except Exception as e:
            print(f"重新加载调度器任务失败: {str(e)}")