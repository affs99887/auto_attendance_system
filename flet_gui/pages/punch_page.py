
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
打卡操作页面
专门的打卡界面，大按钮设计
"""

import flet as ft
import asyncio
import sys
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict

# 添加父目录到Python路径以支持打包后的模块导入
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from components.action_button import create_action_button
    from components.status_card import create_status_card
except ImportError:
    # 尝试使用绝对导入作为后备方案
    try:
        from flet_gui.components.action_button import create_action_button
        from flet_gui.components.status_card import create_status_card
    except ImportError as e:
        print(f"Warning: Failed to import components: {e}")
        # 创建简化的替代函数
        def create_action_button(*args, **kwargs):
            return ft.ElevatedButton("Action Button")
        def create_status_card(*args, **kwargs):
            return ft.Card(content=ft.Text("Status Card"))

class PunchPage:
    """打卡操作页面"""
    
    def __init__(self, system_adapter, state_manager):
        self.system_adapter = system_adapter
        self.state_manager = state_manager
        
        # UI组件
        self.punch_in_button: Optional[ft.Container] = None
        self.punch_out_button: Optional[ft.Container] = None
        self.status_timeline: Optional[ft.Container] = None
        self.recent_records: Optional[ft.Container] = None
        self.content: Optional[ft.Column] = None
        
    def build(self) -> ft.Column:
        """构建页面内容"""
        self.content = ft.Column([
            # 页面标题
            ft.Text(
                "打卡操作", 
                size=28, 
                weight=ft.FontWeight.BOLD,
                color=compat_colors.ON_SURFACE
            ),
            
            ft.Divider(height=20),
            
            # 大号打卡按钮区域
            self._create_punch_buttons_section(),
            
            ft.Divider(height=30),
            
            # 当前状态显示
            self._create_status_section(),
            
            ft.Divider(height=30),
            
            # 最近打卡记录
            self._create_recent_records_section(),
            
        ], spacing=0, scroll=ft.ScrollMode.AUTO)
        
        return self.content
        
    def _create_punch_buttons_section(self) -> ft.Container:
        """创建打卡按钮区域"""
        # 上班打卡按钮
        self.punch_in_button = create_action_button(
            title="上班打卡",
            subtitle="点击进行上班打卡",
            icon=icons.WB_SUNNY,
            color=compat_colors.ORANGE,
            on_click=self._on_punch_in_click
        )
        
        # 下班打卡按钮  
        self.punch_out_button = create_action_button(
            title="下班打卡",
            subtitle="点击进行下班打卡",
            icon=icons.NIGHTS_STAY,
            color=compat_colors.INDIGO,
            on_click=self._on_punch_out_click
        )
        
        return ft.Container(
            content=ft.Row([
                self.punch_in_button,
                self.punch_out_button,
            ], alignment=ft.MainAxisAlignment.SPACE_EVENLY),
            margin=ft.margin.only(bottom=30),
        )
        
    def _create_status_section(self) -> ft.Container:
        """创建状态显示区域"""
        self.status_timeline = ft.Container(
            content=ft.Column([
                ft.Text("今日打卡状态", size=18, weight=ft.FontWeight.W_600),
                
                ft.Container(height=20),
                
                # 打卡时间线
                self._create_punch_timeline(),
                
                ft.Container(height=20),
                
                # 统计信息
                ft.Row([
                    self._create_time_stat("计划上班", "09:00", compat_colors.BLUE),
                    self._create_time_stat("实际上班", "--:--", compat_colors.ORANGE),
                    self._create_time_stat("计划下班", "18:00", compat_colors.BLUE),
                    self._create_time_stat("实际下班", "--:--", compat_colors.ORANGE),
                ], spacing=15, wrap=True),
                
                ft.Container(height=20),
                
                # 工作时长统计
                self._create_work_duration_display(),
                
            ], spacing=15),
            padding=20,
            bgcolor=compat_colors.SURFACE_VARIANT,
            border_radius=12,
            margin=ft.margin.only(bottom=20),
        )
        
        return self.status_timeline
        
    def _create_punch_timeline(self) -> ft.Column:
        """创建打卡时间线"""
        return ft.Column([
            # 上班打卡项
            ft.Row([
                ft.Container(
                    content=ft.Icon(
                        icons.RADIO_BUTTON_UNCHECKED,
                        color=compat_colors.GREY,
                        size=28
                    ),
                    width=40,
                ),
                ft.Column([
                    ft.Text("上班打卡", size=16, weight=ft.FontWeight.W_500),
                    ft.Text("还未打卡", size=12, color=compat_colors.ON_SURFACE_VARIANT),
                ], spacing=2),
                ft.Container(expand=True),
                ft.Text("--:--", size=16, weight=ft.FontWeight.BOLD),
            ], alignment=ft.MainAxisAlignment.START),
            
            # 连接线
            ft.Container(
                content=ft.Container(
                    bgcolor=compat_colors.OUTLINE_VARIANT,
                    width=2,
                    height=30,
                ),
                margin=ft.margin.only(left=19),
            ),
            
            # 下班打卡项
            ft.Row([
                ft.Container(
                    content=ft.Icon(
                        icons.RADIO_BUTTON_UNCHECKED,
                        color=compat_colors.GREY,
                        size=28
                    ),
                    width=40,
                ),
                ft.Column([
                    ft.Text("下班打卡", size=16, weight=ft.FontWeight.W_500),
                    ft.Text("还未打卡", size=12, color=compat_colors.ON_SURFACE_VARIANT),
                ], spacing=2),
                ft.Container(expand=True),
                ft.Text("--:--", size=16, weight=ft.FontWeight.BOLD),
            ], alignment=ft.MainAxisAlignment.START),
            
        ], spacing=10)
        
    def _create_time_stat(self, label: str, time: str, color: str) -> ft.Container:
        """创建时间统计组件"""
        return ft.Container(
            content=ft.Column([
                ft.Text(label, size=12, color=compat_colors.ON_SURFACE_VARIANT),
                ft.Text(time, size=18, weight=ft.FontWeight.BOLD, color=color),
            ], spacing=5, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=15,
            bgcolor=color + "1A",  # 添加透明度
            border_radius=8,
            border=ft.border.all(1, color + "80"),
            width=120,
        )
        
    def _create_work_duration_display(self) -> ft.Container:
        """创建工作时长显示"""
        return ft.Container(
            content=ft.Row([
                ft.Icon(icons.ACCESS_TIME, size=24, color=compat_colors.BLUE),
                ft.Column([
                    ft.Text("今日工作时长", size=14, color=compat_colors.ON_SURFACE_VARIANT),
                    ft.Text("0小时0分钟", size=20, weight=ft.FontWeight.BOLD),
                ], spacing=2),
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Text("8.0", size=18, weight=ft.FontWeight.BOLD),
                    padding=ft.padding.symmetric(horizontal=12, vertical=6),
                    bgcolor=compat_colors.PRIMARY + "20",
                    border_radius=6,
                ),
                ft.Text("/ 8小时", size=14, color=compat_colors.ON_SURFACE_VARIANT),
            ], alignment=ft.MainAxisAlignment.START),
            padding=20,
            bgcolor=compat_colors.PRIMARY + "10",
            border_radius=8,
            border=ft.border.all(1, compat_colors.PRIMARY + "40"),
        )
        
    def _create_recent_records_section(self) -> ft.Container:
        """创建最近记录区域"""
        self.recent_records = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("最近打卡记录", size=18, weight=ft.FontWeight.W_600),
                    ft.Container(expand=True),
                    ft.TextButton(
                        "查看全部",
                        icon=icons.ARROW_FORWARD,
                        on_click=self._on_view_all_records
                    ),
                ]),
                
                ft.Container(height=10),
                
                # 记录列表
                self._create_records_list(),
                
            ], spacing=15),
            padding=20,
            bgcolor=compat_colors.SURFACE_VARIANT,
            border_radius=12,
        )
        
        return self.recent_records
        
    def _create_records_list(self) -> ft.Column:
        """创建记录列表"""
        # 模拟数据，实际应该从system_adapter获取
        records = [
            {"date": "2025-06-26", "punch_in": "09:02", "punch_out": "18:05", "duration": "9小时3分"},
            {"date": "2025-06-25", "punch_in": "08:58", "punch_out": "17:58", "duration": "9小时0分"},
            {"date": "2025-06-24", "punch_in": "09:05", "punch_out": "18:02", "duration": "8小时57分"},
        ]
        
        record_items = []
        for record in records:
            record_items.append(self._create_record_item(record))
            
        return ft.Column(record_items, spacing=10)
        
    def _create_record_item(self, record: Dict) -> ft.Container:
        """创建单个记录项"""
        return ft.Container(
            content=ft.Row([
                # 日期
                ft.Container(
                    content=ft.Text(
                        record["date"],
                        size=14,
                        weight=ft.FontWeight.W_500
                    ),
                    width=100,
                ),
                
                # 上班时间
                ft.Column([
                    ft.Text("上班", size=12, color=compat_colors.ON_SURFACE_VARIANT),
                    ft.Text(record["punch_in"], size=14, weight=ft.FontWeight.W_500),
                ], spacing=2, tight=True),
                
                # 下班时间
                ft.Column([
                    ft.Text("下班", size=12, color=compat_colors.ON_SURFACE_VARIANT),
                    ft.Text(record["punch_out"], size=14, weight=ft.FontWeight.W_500),
                ], spacing=2, tight=True),
                
                ft.Container(expand=True),
                
                # 工作时长
                ft.Container(
                    content=ft.Text(
                        record["duration"],
                        size=14,
                        weight=ft.FontWeight.W_500,
                        color=compat_colors.GREEN
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    bgcolor=compat_colors.GREEN + "20",
                    border_radius=4,
                ),
                
            ], alignment=ft.MainAxisAlignment.START),
            padding=15,
            bgcolor=compat_colors.BACKGROUND,
            border_radius=8,
            border=ft.border.all(1, compat_colors.OUTLINE_VARIANT),
        )
        
    async def _on_punch_in_click(self, e):
        """处理上班打卡"""
        try:
            # 设置加载状态
            self.punch_in_button.set_loading(True, "打卡中")
            
            # 调用打卡接口
            result = await self.system_adapter.punch_in()
            
            if result.get('success'):
                await self.state_manager.set_success(result.get('message', '上班打卡成功'))
                await self._update_timeline("punch_in", datetime.now().strftime("%H:%M"))
            else:
                await self.state_manager.set_error(result.get('message', '上班打卡失败'))
                
        except Exception as e:
            await self.state_manager.set_error(f"打卡操作失败: {str(e)}")
        finally:
            self.punch_in_button.set_loading(False)
            
    async def _on_punch_out_click(self, e):
        """处理下班打卡"""
        try:
            # 设置加载状态
            self.punch_out_button.set_loading(True, "打卡中")
            
            # 调用打卡接口
            result = await self.system_adapter.punch_out()
            
            if result.get('success'):
                await self.state_manager.set_success(result.get('message', '下班打卡成功'))
                await self._update_timeline("punch_out", datetime.now().strftime("%H:%M"))
            else:
                await self.state_manager.set_error(result.get('message', '下班打卡失败'))
                
        except Exception as e:
            await self.state_manager.set_error(f"打卡操作失败: {str(e)}")
        finally:
            self.punch_out_button.set_loading(False)
            
    async def _update_timeline(self, punch_type: str, time: str):
        """更新时间线显示"""
        # 这里需要更新时间线中的对应项目
        # 实际实现中需要保存时间线组件的引用并更新它们
        pass
        
    async def _on_view_all_records(self, e):
        """查看所有记录"""
        # 可以导航到专门的记录页面或显示对话框
        pass