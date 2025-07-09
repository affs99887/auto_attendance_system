"""
仪表板页面
系统状态总览和快速操作
"""

import flet as ft
import asyncio
import sys
import os
from typing import Optional
from datetime import datetime

# 添加父目录到Python路径以支持打包后的模块导入
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 导入现代设计系统
try:
    from ..utils.design_tokens import tokens, colors, typography
    from ..utils.colors_compat import colors as compat_colors, icons
    from ..components.modern_card import create_modern_status_card
    from ..components.modern_button import create_modern_button, create_modern_action_button
except ImportError:
    try:
        from utils.design_tokens import tokens, colors, typography
        from utils.colors_compat import colors as compat_colors, icons
        from components.modern_card import create_modern_status_card
        from components.modern_button import create_modern_button, create_modern_action_button
    except ImportError:
        try:
            from flet_gui.utils.design_tokens import tokens, colors, typography
            from flet_gui.utils.colors_compat import colors as compat_colors, icons
            from flet_gui.components.modern_card import create_modern_status_card
            from flet_gui.components.modern_button import create_modern_button, create_modern_action_button
        except ImportError as e:
            print(f"Warning: Failed to import modern components: {e}")
            # 回退到兼容模式
            class MockTokens:
                COLORS = {
                    "primary": {"500": "#2196F3"}, 
                    "secondary": {"500": "#9C27B0"},
                    "success": "#4CAF50",
                    "error": "#F44336",
                    "warning": "#FF9800",
                    "neutral": {"900": "#212121", "600": "#757575", "50": "#F5F5F5"}
                }
                SPACING = {"md": 16, "lg": 24, "xl": 32}
                RADIUS = {"2xl": 24}
            class MockTypography:
                h4 = {"size": 20, "weight": "bold"}
                body2 = {"size": 14}
            tokens = MockTokens()
            colors = tokens.COLORS
            typography = {"h4": {"size": 20, "weight": "bold"}, "body2": {"size": 14}}
            
            # 使用兼容的图标
            class CompatIcons:
                COMPUTER = "computer"
                SCHEDULE = "schedule"
                SHIELD = "shield"
                TASK_ALT = "task_alt"
                LOGIN = "login"
                LOGOUT = "logout"
                ARTICLE = "article"
                POWER_SETTINGS_NEW = "power_settings_new"
            icons = CompatIcons()
            
            def create_modern_status_card(*args, **kwargs):
                return ft.Card(content=ft.Text("Status Card"))
            def create_modern_button(*args, **kwargs):
                return ft.ElevatedButton("Button")
            def create_modern_action_button(*args, **kwargs):
                return ft.ElevatedButton("Action Button")

class DashboardPage:
    """仪表板页面"""
    
    def __init__(self, system_adapter, state_manager):
        self.system_adapter = system_adapter
        self.state_manager = state_manager
        
        # UI组件
        self.status_cards = {}
        self.quick_buttons = {}
        self.content: Optional[ft.Column] = None
        
    def build(self) -> ft.Column:
        """构建页面内容"""
        self.content = ft.Column([
            # 页面标题
            ft.Text(
                "系统概览", 
                size=28, 
                weight=ft.FontWeight.BOLD,
                color=compat_colors.ON_SURFACE
            ),
            
            ft.Divider(height=20),
            
            # 状态卡片组
            self._create_status_cards_section(),
            
            ft.Divider(height=30),
            
            # 快速操作区域
            self._create_quick_actions_section(),
            
            ft.Divider(height=30),
            
            # 今日打卡状态
            self._create_today_status_section(),
            
        ], spacing=0, scroll=ft.ScrollMode.AUTO)
        
        return self.content
        
    def _create_status_cards_section(self) -> ft.Container:
        """创建现代化状态卡片区域"""
        # 🖥️ 系统状态卡片
        self.status_cards['system'] = create_modern_status_card(
            title="系统状态",
            value="运行中",
            icon=icons.COMPUTER,
            color=colors["success"],
            subtitle="运行时间: 0分钟",
            show_trend=True,
            trend_value="+5%",
            trend_positive=True,
            on_click=lambda _: self._on_status_card_click("system")
        )
        
        # 📅 打卡状态卡片
        self.status_cards['punch'] = create_modern_status_card(
            title="今日打卡",
            value="未打卡",
            icon=icons.SCHEDULE,
            color=colors["primary"]["500"],
            subtitle="上班: --:--  下班: --:--",
            on_click=lambda _: self._on_status_card_click("punch")
        )
        
        # 🛡️ 看门狗状态卡片
        self.status_cards['watchdog'] = create_modern_status_card(
            title="看门狗监控",
            value="正常",
            icon=icons.SHIELD,
            color=colors["warning"],
            subtitle="重启次数: 0/10",
            show_trend=True,
            trend_value="稳定",
            trend_positive=True,
            on_click=lambda _: self._on_status_card_click("watchdog")
        )
        
        # 📋 任务状态卡片
        self.status_cards['tasks'] = create_modern_status_card(
            title="活动任务",
            value="2个",
            icon=icons.TASK_ALT,
            color=colors["secondary"]["500"],
            subtitle="今日计划: 上班打卡, 下班打卡",
            on_click=lambda _: self._on_status_card_click("tasks")
        )
        
        return ft.Container(
            content=ft.Row([
                self.status_cards['system'],
                self.status_cards['punch'],
                self.status_cards['watchdog'],
                self.status_cards['tasks'],
            ], spacing=tokens.SPACING["lg"], wrap=True),
            margin=ft.margin.only(bottom=tokens.SPACING["xl"]),
        )
        
    def _create_quick_actions_section(self) -> ft.Container:
        """创建现代化快速操作区域"""
        # 🚀 主要操作按钮 - 使用大型操作按钮
        punch_in_btn = create_modern_action_button(
            title="上班打卡",
            subtitle="开始新的工作日",
            icon=icons.LOGIN,
            color=colors["success"],
            on_click=self._on_punch_in_click
        )
        
        punch_out_btn = create_modern_action_button(
            title="下班打卡",
            subtitle="结束今日工作",
            icon=icons.LOGOUT,
            color=colors["error"],
            on_click=self._on_punch_out_click
        )
        
        # 🔧 辅助操作按钮 - 使用常规按钮
        self.quick_buttons['view_logs'] = create_modern_button(
            text="查看日志",
            icon=icons.ARTICLE,
            variant="outline",
            size="md",
            on_click=self._on_view_logs_click
        )
        
        self.quick_buttons['system_control'] = create_modern_button(
            text="系统控制",
            icon=icons.POWER_SETTINGS_NEW,
            variant="secondary",
            size="md",
            on_click=self._on_system_control_click
        )
        
        return ft.Container(
            content=ft.Column([
                # 📍 区域标题
                ft.Row([
                    ft.Text(
                        "快速操作", 
                        size=typography["h4"]["size"], 
                        weight=typography["h4"]["weight"],
                        color=colors["neutral"]["900"]
                    ),
                    ft.Container(expand=True),
                    ft.Text(
                        "选择需要执行的操作",
                        size=typography["body2"]["size"],
                        color=colors["neutral"]["600"]
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                
                # 🎯 主要操作 - 大按钮
                ft.Row([
                    punch_in_btn,
                    punch_out_btn,
                ], spacing=tokens.SPACING["xl"], alignment=ft.MainAxisAlignment.CENTER),
                
                # 🔧 辅助操作 - 小按钮
                ft.Row([
                    self.quick_buttons['view_logs'],
                    self.quick_buttons['system_control'],
                ], spacing=tokens.SPACING["md"], alignment=ft.MainAxisAlignment.CENTER),
                
            ], spacing=tokens.SPACING["lg"]),
            padding=tokens.SPACING["xl"],
            bgcolor=colors["neutral"]["50"],
            border_radius=tokens.RADIUS["2xl"],
            margin=ft.margin.only(bottom=tokens.SPACING["xl"]),
        )
        
    def _create_today_status_section(self) -> ft.Container:
        """创建今日状态区域"""
        return ft.Container(
            content=ft.Column([
                ft.Text(
                    "今日打卡记录", 
                    size=20, 
                    weight=ft.FontWeight.W_600,
                    color=compat_colors.ON_SURFACE
                ),
                
                # 时间线式显示
                ft.Container(
                    content=ft.Column([
                        self._create_timeline_item("上班打卡", "--:--", compat_colors.GREY, False),
                        ft.Container(height=20),
                        self._create_timeline_item("下班打卡", "--:--", compat_colors.GREY, False),
                    ]),
                    padding=20,
                ),
                
                # 统计信息
                ft.Row([
                    self._create_stat_chip("工作时长", "--小时", compat_colors.BLUE),
                    self._create_stat_chip("状态", "未开始", compat_colors.ORANGE),
                    self._create_stat_chip("本月出勤", "20天", compat_colors.GREEN),
                ], spacing=10, wrap=True),
                
            ], spacing=15),
            padding=20,
            bgcolor=compat_colors.SURFACE_VARIANT,
            border_radius=12,
        )
        
    def _create_timeline_item(self, title: str, time: str, color: str, completed: bool) -> ft.Row:
        """创建时间线项目"""
        icon = icons.CHECK_CIRCLE if completed else icons.RADIO_BUTTON_UNCHECKED
        return ft.Row([
            ft.Icon(icon, color=color, size=24),
            ft.Column([
                ft.Text(title, weight=ft.FontWeight.W_500),
                ft.Text(time, size=12, color=compat_colors.ON_SURFACE_VARIANT),
            ], spacing=2, tight=True),
        ], spacing=15)
        
    def _create_stat_chip(self, label: str, value: str, color: str) -> ft.Container:
        """创建统计芯片"""
        return ft.Container(
            content=ft.Column([
                ft.Text(label, size=12, color=compat_colors.ON_SURFACE_VARIANT),
                ft.Text(value, size=16, weight=ft.FontWeight.BOLD),
            ], spacing=2, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=15, vertical=10),
            bgcolor=color + "1A",  # 添加透明度
            border_radius=8,
            border=ft.border.all(1, color),
        )
        
    async def _on_status_card_click(self, card_type: str):
        """处理状态卡片点击"""
        if card_type == "system":
            # 切换到系统监控页面
            await self.state_manager.navigate_to("monitoring")
        elif card_type == "punch":
            # 切换到打卡页面
            await self.state_manager.navigate_to("punch")
        elif card_type == "tasks":
            # 切换到任务管理页面
            await self.state_manager.navigate_to("tasks")
            
    async def _on_punch_in_click(self, e):
        """处理上班打卡点击"""
        try:
            # 设置按钮加载状态
            button = self.quick_buttons['punch_in']
            button.disabled = True
            button.text = "打卡中..."
            if button.page:
                button.page.update()
                
            # 调用打卡接口
            result = await self.system_adapter.punch_in()
            
            if result.get('success'):
                await self.state_manager.set_success(result.get('message', '上班打卡成功'))
                await self._update_punch_status("punch_in", "刚刚")
            else:
                await self.state_manager.set_error(result.get('message', '上班打卡失败'))
                
        except Exception as e:
            await self.state_manager.set_error(f"打卡操作失败: {str(e)}")
        finally:
            # 恢复按钮状态
            button = self.quick_buttons['punch_in']
            button.disabled = False
            button.text = "上班打卡"
            if button.page:
                button.page.update()
                
    async def _on_punch_out_click(self, e):
        """处理下班打卡点击"""
        try:
            # 设置按钮加载状态
            button = self.quick_buttons['punch_out']
            button.disabled = True
            button.text = "打卡中..."
            if button.page:
                button.page.update()
                
            # 调用打卡接口
            result = await self.system_adapter.punch_out()
            
            if result.get('success'):
                await self.state_manager.set_success(result.get('message', '下班打卡成功'))
                await self._update_punch_status("punch_out", "刚刚")
            else:
                await self.state_manager.set_error(result.get('message', '下班打卡失败'))
                
        except Exception as e:
            await self.state_manager.set_error(f"打卡操作失败: {str(e)}")
        finally:
            # 恢复按钮状态
            button = self.quick_buttons['punch_out']
            button.disabled = False
            button.text = "下班打卡"
            if button.page:
                button.page.update()
                
    async def _on_view_logs_click(self, e):
        """处理查看日志点击"""
        await self.state_manager.navigate_to("monitoring")
        
    async def _on_system_control_click(self, e):
        """处理系统控制点击"""
        # 显示系统控制对话框
        pass
        
    async def _update_punch_status(self, punch_type: str, time: str):
        """更新打卡状态显示"""
        if punch_type == "punch_in":
            self.status_cards['punch'].update_value("已打上班卡")
            self.status_cards['punch'].update_subtitle(f"上班: {time}  下班: --:--")
        elif punch_type == "punch_out":
            self.status_cards['punch'].update_value("已打下班卡")
            # 这里需要获取上班时间
            self.status_cards['punch'].update_subtitle(f"上班: 09:00  下班: {time}")
            
    async def refresh_data(self):
        """刷新页面数据"""
        try:
            # 获取最新状态
            status = self.system_adapter.get_status()
            
            # 更新状态卡片
            self.status_cards['system'].update_value("运行中" if status.is_running else "已停止")
            self.status_cards['system'].update_color(compat_colors.GREEN if status.is_running else compat_colors.RED)
            
            # 获取打卡记录
            records = await self.system_adapter.get_punch_records()
            if records:
                latest = records[0]  # 假设第一个是最新的
                self.status_cards['punch'].update_subtitle(
                    f"上班: {latest.get('punch_in', '--:--')}  下班: {latest.get('punch_out', '--:--')}"
                )
                
            # 获取任务数量
            tasks = await self.system_adapter.get_tasks()
            self.status_cards['tasks'].update_value(f"{len(tasks)}个")
            
        except Exception as e:
            await self.state_manager.set_error(f"刷新数据失败: {str(e)}")
            
    async def on_system_event(self, event_type: str, data=None):
        """处理系统事件"""
        if event_type == "punch_completed":
            punch_type = data.get('type') if data else None
            if punch_type:
                await self._update_punch_status(punch_type, "刚刚")
        elif event_type in ["system_started", "system_stopped"]:
            await self.refresh_data()