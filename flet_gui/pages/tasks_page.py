
# 导入兼容性模块
try:
    from ..utils.colors_compat import colors, icons
except ImportError:
    try:
        from utils.colors_compat import colors, icons
    except ImportError:
        try:
            from flet_gui.utils.colors_compat import colors, icons
        except ImportError:
            # 如果都导入失败，创建简单的兼容对象
            class Colors:
                BLUE = "#2196F3"
                GREEN = "#4CAF50"
                SURFACE_VARIANT = "#F5F5F5"
            colors = Colors()
            class Icons:
                CIRCLE = "circle"
                PLAY_ARROW = "play_arrow"
                STOP = "stop"
                ADD = "add"
                EDIT = "edit"
                DELETE = "delete"
                SAVE = "save"
                REFRESH = "refresh"
                SETTINGS = "settings"
                VISIBILITY = "visibility"
                VISIBILITY_OFF = "visibility_off"
            icons = Icons()

"""
任务管理页面
Kanban看板式任务管理界面
"""

import flet as ft
import asyncio
from typing import Optional, List, Dict, Callable
from datetime import datetime

class TaskCard(ft.Container):
    """任务卡片组件"""
    
    def __init__(self, task: Dict, on_edit: Callable = None, on_delete: Callable = None):
        self.task = task
        self.on_edit = on_edit
        self.on_delete = on_delete
        
        # 根据任务状态确定颜色
        status_colors = {
            "pending": compat_colors.ORANGE,
            "running": compat_colors.BLUE,
            "completed": compat_colors.GREEN,
            "failed": compat_colors.RED,
        }
        
        status_color = status_colors.get(task.get("status", "pending"), compat_colors.GREY)
        
        content = ft.Column([
            # 任务标题和菜单
            ft.Row([
                ft.Text(
                    task.get("title", "未知任务"),
                    weight=ft.FontWeight.W_500,
                    size=14,
                    expand=True
                ),
                ft.PopupMenuButton(
                    items=[
                        ft.PopupMenuItem(
                            text="编辑",
                            icon=icons.EDIT,
                            on_click=lambda _: self._on_edit() if self.on_edit else None
                        ),
                        ft.PopupMenuItem(
                            text="删除",
                            icon=icons.DELETE,
                            on_click=lambda _: self._on_delete() if self.on_delete else None
                        ),
                    ],
                    icon=icons.MORE_VERT,
                    icon_size=16,
                ),
            ]),
            
            # 任务详情
            ft.Column([
                ft.Row([
                    ft.Icon(icons.SCHEDULE, size=14, color=compat_colors.ON_SURFACE_VARIANT),
                    ft.Text(f"时间: {task.get('time', '--:--')}", size=12),
                ], spacing=5),
                ft.Row([
                    ft.Icon(icons.CATEGORY, size=14, color=compat_colors.ON_SURFACE_VARIANT),
                    ft.Text(f"类型: {task.get('type', '未知')}", size=12),
                ], spacing=5),
                ft.Row([
                    ft.Icon(icons.INFO, size=14, color=status_color),
                    ft.Text(f"状态: {task.get('status', '未知')}", size=12, color=status_color),
                ], spacing=5),
            ], spacing=5),
            
        ], spacing=10)
        
        super().__init__(
            content=content,
            padding=12,
            bgcolor=compat_colors.BACKGROUND,
            border_radius=8,
            border=ft.border.all(1, compat_colors.OUTLINE_VARIANT),
            ink=True,
        )
        
    def _on_edit(self):
        """编辑任务"""
        if self.on_edit:
            self.on_edit(self.task)
            
    def _on_delete(self):
        """删除任务"""
        if self.on_delete:
            self.on_delete(self.task)

class TaskColumn(ft.Container):
    """任务列组件"""
    
    def __init__(self, title: str, tasks: List[Dict], bg_color: str, on_task_edit: Callable = None, on_task_delete: Callable = None):
        self.title = title
        self.tasks = tasks
        self.bg_color = bg_color
        self.on_task_edit = on_task_edit
        self.on_task_delete = on_task_delete
        
        # 创建任务卡片列表
        task_cards = []
        for task in tasks:
            task_cards.append(
                TaskCard(
                    task=task,
                    on_edit=on_task_edit,
                    on_delete=on_task_delete
                )
            )
            
        content = ft.Column([
            # 列标题
            ft.Row([
                ft.Text(title, size=16, weight=ft.FontWeight.W_600),
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Text(str(len(tasks)), size=12),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    bgcolor=compat_colors.PRIMARY,
                    border_radius=12,
                ),
            ]),
            
            # 任务列表容器
            ft.Container(
                content=ft.Column(task_cards, spacing=8) if task_cards else ft.Container(
                    content=ft.Text(
                        "暂无任务",
                        color=compat_colors.ON_SURFACE_VARIANT,
                        size=12
                    ),
                    alignment=ft.alignment.center,
                    height=100,
                ),
                expand=True,
            ),
        ], spacing=10)
        
        super().__init__(
            content=content,
            width=300,
            padding=15,
            bgcolor=bg_color,
            border_radius=12,
        )

class TasksPage:
    """任务管理页面"""
    
    def __init__(self, system_adapter, state_manager):
        self.system_adapter = system_adapter
        self.state_manager = state_manager
        
        # 任务数据
        self.tasks = []
        
        # UI组件
        self.task_columns: Dict[str, TaskColumn] = {}
        self.content: Optional[ft.Column] = None
        
    def build(self) -> ft.Column:
        """构建页面内容"""
        self.content = ft.Column([
            # 页面标题和操作
            self._create_header(),
            
            ft.Divider(height=20),
            
            # Kanban看板
            self._create_kanban_board(),
            
        ], spacing=0, scroll=ft.ScrollMode.AUTO)
        
        # 初始加载数据
        asyncio.create_task(self._load_tasks())
        
        return self.content
        
    def _create_header(self) -> ft.Row:
        """创建页面头部"""
        return ft.Row([
            ft.Text(
                "任务管理", 
                size=28, 
                weight=ft.FontWeight.BOLD,
                color=compat_colors.ON_SURFACE
            ),
            ft.Container(expand=True),
            ft.ElevatedButton(
                "新建任务",
                icon=icons.ADD,
                on_click=self._on_new_task_click,
                style=ft.ButtonStyle(
                    bgcolor=compat_colors.PRIMARY,
                    color=colors.ON_PRIMARY,
                ),
            ),
            ft.IconButton(
                icons.REFRESH,
                tooltip="刷新任务",
                on_click=self._on_refresh_click,
            ),
        ])
        
    def _create_kanban_board(self) -> ft.Container:
        """创建Kanban看板"""
        # 按状态分组任务
        pending_tasks = [t for t in self.tasks if t.get("status") == "pending"]
        running_tasks = [t for t in self.tasks if t.get("status") == "running"]
        completed_tasks = [t for t in self.tasks if t.get("status") == "completed"]
        
        # 创建任务列
        self.task_columns["pending"] = TaskColumn(
            title="待执行",
            tasks=pending_tasks,
            bg_color=compat_colors.ORANGE + "20",
            on_task_edit=self._on_task_edit,
            on_task_delete=self._on_task_delete
        )
        
        self.task_columns["running"] = TaskColumn(
            title="执行中",
            tasks=running_tasks,
            bg_color=compat_colors.BLUE + "20",
            on_task_edit=self._on_task_edit,
            on_task_delete=self._on_task_delete
        )
        
        self.task_columns["completed"] = TaskColumn(
            title="已完成",
            tasks=completed_tasks,
            bg_color=compat_colors.GREEN + "20",
            on_task_edit=self._on_task_edit,
            on_task_delete=self._on_task_delete
        )
        
        return ft.Container(
            content=ft.Row([
                self.task_columns["pending"],
                self.task_columns["running"],
                self.task_columns["completed"],
            ], spacing=15, scroll=ft.ScrollMode.AUTO),
            height=500,
        )
        
    async def _load_tasks(self):
        """加载任务数据"""
        try:
            await self.state_manager.set_loading(True, "加载任务中...")
            
            # 从系统适配器获取任务
            self.tasks = await self.system_adapter.get_tasks()
            
            # 更新看板显示
            await self._refresh_kanban()
            
        except Exception as e:
            await self.state_manager.set_error(f"加载任务失败: {str(e)}")
        finally:
            await self.state_manager.set_loading(False)
            
    async def _refresh_kanban(self):
        """刷新看板显示"""
        if not self.content:
            return
            
        # 重新创建看板
        new_kanban = self._create_kanban_board()
        
        # 替换原有看板
        if len(self.content.controls) > 2:
            self.content.controls[2] = new_kanban
        else:
            self.content.controls.append(new_kanban)
            
        # 更新页面
        if self.content.page:
            self.content.page.update()
            
    async def _on_new_task_click(self, e):
        """新建任务点击处理"""
        await self._show_task_dialog()
        
    async def _on_refresh_click(self, e):
        """刷新按钮点击处理"""
        await self._load_tasks()
        
    async def _on_task_edit(self, task: Dict):
        """编辑任务"""
        await self._show_task_dialog(task)
        
    async def _on_task_delete(self, task: Dict):
        """删除任务"""
        await self._show_delete_confirmation(task)
        
    async def _show_task_dialog(self, task: Dict = None):
        """显示任务编辑对话框"""
        is_edit = task is not None
        
        # 表单字段
        title_field = ft.TextField(
            label="任务标题",
            value=task.get("title", "") if task else "",
            width=300,
        )
        
        type_dropdown = ft.Dropdown(
            label="任务类型",
            value=task.get("type", "punch_in") if task else "punch_in",
            options=[
                ft.dropdown.Option("punch_in", "上班打卡"),
                ft.dropdown.Option("punch_out", "下班打卡"),
                ft.dropdown.Option("system_check", "系统检查"),
                ft.dropdown.Option("custom", "自定义任务"),
            ],
            width=300,
        )
        
        time_field = ft.TextField(
            label="执行时间 (HH:MM)",
            value=task.get("time", "") if task else "",
            width=300,
            hint_text="例如: 09:00",
        )
        
        status_dropdown = ft.Dropdown(
            label="任务状态",
            value=task.get("status", "pending") if task else "pending",
            options=[
                ft.dropdown.Option("pending", "待执行"),
                ft.dropdown.Option("running", "执行中"),
                ft.dropdown.Option("completed", "已完成"),
            ],
            width=300,
        ) if is_edit else None
        
        # 对话框内容
        dialog_content = ft.Column([
            title_field,
            type_dropdown,
            time_field,
        ], spacing=15, tight=True)
        
        if status_dropdown:
            dialog_content.controls.append(status_dropdown)
            
        # 对话框
        dialog = ft.AlertDialog(
            title=ft.Text("编辑任务" if is_edit else "新建任务"),
            content=dialog_content,
            actions=[
                ft.TextButton("取消", on_click=lambda _: self._close_dialog()),
                ft.ElevatedButton(
                    "保存",
                    on_click=lambda _: self._save_task(
                        task.get("id") if task else None,
                        title_field.value,
                        type_dropdown.value,
                        time_field.value,
                        status_dropdown.value if status_dropdown else "pending"
                    )
                ),
            ],
            modal=True,
        )
        
        # 显示对话框
        if self.content and self.content.page:
            self.content.page.dialog = dialog
            dialog.open = True
            self.content.page.update()
            
    async def _show_delete_confirmation(self, task: Dict):
        """显示删除确认对话框"""
        dialog = ft.AlertDialog(
            title=ft.Text("确认删除"),
            content=ft.Text(f"确定要删除任务 \"{task.get('title', '未知任务')}\" 吗？"),
            actions=[
                ft.TextButton("取消", on_click=lambda _: self._close_dialog()),
                ft.ElevatedButton(
                    "删除",
                    color=compat_colors.WHITE,
                    bgcolor=compat_colors.RED,
                    on_click=lambda _: self._delete_task(task.get("id"))
                ),
            ],
            modal=True,
        )
        
        # 显示对话框
        if self.content and self.content.page:
            self.content.page.dialog = dialog
            dialog.open = True
            self.content.page.update()
            
    def _close_dialog(self):
        """关闭对话框"""
        if self.content and self.content.page and self.content.page.dialog:
            self.content.page.dialog.open = False
            self.content.page.update()
            
    async def _save_task(self, task_id: str, title: str, task_type: str, time: str, status: str):
        """保存任务"""
        try:
            # 验证输入
            if not title.strip():
                await self.state_manager.set_error("任务标题不能为空")
                return
                
            if not time.strip():
                await self.state_manager.set_error("执行时间不能为空")
                return
                
            # 构建任务数据
            task_data = {
                "title": title.strip(),
                "type": task_type,
                "time": time.strip(),
                "status": status,
                "created_at": datetime.now().isoformat(),
            }
            
            if task_id:
                task_data["id"] = task_id
                # 更新现有任务
                for i, task in enumerate(self.tasks):
                    if task.get("id") == task_id:
                        self.tasks[i] = task_data
                        break
            else:
                # 新建任务
                task_data["id"] = str(len(self.tasks) + 1)  # 简单的ID生成
                self.tasks.append(task_data)
                
            # 刷新看板
            await self._refresh_kanban()
            
            # 关闭对话框
            self._close_dialog()
            
            # 显示成功消息
            action = "更新" if task_id else "创建"
            await self.state_manager.set_success(f"任务{action}成功")
            
        except Exception as e:
            await self.state_manager.set_error(f"保存任务失败: {str(e)}")
            
    async def _delete_task(self, task_id: str):
        """删除任务"""
        try:
            # 从任务列表中移除
            self.tasks = [t for t in self.tasks if t.get("id") != task_id]
            
            # 刷新看板
            await self._refresh_kanban()
            
            # 关闭对话框
            self._close_dialog()
            
            # 显示成功消息
            await self.state_manager.set_success("任务删除成功")
            
        except Exception as e:
            await self.state_manager.set_error(f"删除任务失败: {str(e)}")