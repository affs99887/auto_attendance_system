"""
操作按钮组件
大按钮设计，适合打卡等主要操作
"""

import flet as ft
from typing import Optional, Callable

# 导入颜色兼容性模块
try:
    from ..utils.colors_compat import colors as compat_colors
except ImportError:
    try:
        from utils.colors_compat import colors as compat_colors
    except ImportError:
        try:
            from flet_gui.utils.colors_compat import colors as compat_colors
        except ImportError:
            # 如果都导入失败，创建一个简单的兼容对象
            class Colors:
                BLUE = "#2196F3"
                WHITE = "#FFFFFF"
                SURFACE_VARIANT = "#F5F5F5"
                ON_SURFACE = "#212121"
                ON_SURFACE_VARIANT = "#757575"
                OUTLINE_VARIANT = "#E0E0E0"
            compat_colors = Colors()

class ActionButton(ft.Container):
    """大型操作按钮组件"""
    
    def __init__(
        self,
        title: str,
        subtitle: str,
        icon: str,
        color: str = compat_colors.BLUE,
        width: int = 250,
        height: int = 200,
        on_click: Optional[Callable] = None,
        disabled: bool = False,
        **kwargs
    ):
        # Initialize parent class first
        super().__init__(**kwargs)
        
        self.title = title
        self.subtitle = subtitle
        self.icon_name = icon
        self.color = color
        self._on_click = on_click
        self._loading = False
        
        # 创建图标
        self.icon_widget = ft.Icon(
            icon,
            size=60,
            color=color if not disabled else compat_colors.ON_SURFACE_VARIANT
        )
        
        # 创建标题文本
        self.title_text = ft.Text(
            title,
            size=24,
            weight=ft.FontWeight.BOLD,
            color=compat_colors.ON_SURFACE if not disabled else compat_colors.ON_SURFACE_VARIANT
        )
        
        # 创建副标题文本
        self.subtitle_text = ft.Text(
            subtitle,
            size=14,
            color=compat_colors.ON_SURFACE_VARIANT
        )
        
        # 构建内容
        content = ft.Column([
            self.icon_widget,
            self.title_text,
            self.subtitle_text,
        ], 
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=10)
        
        # 设置Container属性
        self.content = content
        self.width = width
        self.height = height
        self.bgcolor = compat_colors.SURFACE_VARIANT if not disabled else compat_colors.OUTLINE_VARIANT
        self.border_radius = 16
        self.ink = True if not disabled else False
        self.on_click = self._handle_click if not disabled else None
        self.padding = 20
        self.disabled = disabled
        
    def _handle_click(self, e):
        """处理点击事件"""
        if not self.disabled and not self._loading and self._on_click:
            self._on_click(e)
            
    def set_loading(self, loading: bool = True, message: str = "处理中..."):
        """设置加载状态"""
        self._loading = loading
        
        if loading:
            # 显示加载状态
            self.icon_widget = ft.ProgressRing(width=60, height=60)
            self.title_text.value = message
            self.subtitle_text.value = "请稍候"
            self.on_click = None
        else:
            # 恢复正常状态
            self.icon_widget = ft.Icon(
                self.icon_name,
                size=60,
                color=self.color if not self.disabled else compat_colors.ON_SURFACE_VARIANT
            )
            self.title_text.value = self.title
            self.subtitle_text.value = self.subtitle
            self.on_click = self._handle_click if not self.disabled else None
            
        # 重新构建内容
        self.content.controls = [
            self.icon_widget,
            self.title_text,
            self.subtitle_text,
        ]
        
        if self.page:
            self.page.update()
            
    def set_disabled(self, disabled: bool):
        """设置禁用状态"""
        self.disabled = disabled
        
        # 更新样式
        if disabled:
            self.bgcolor = compat_colors.OUTLINE_VARIANT
            self.ink = False
            self.on_click = None
            self.icon_widget.color = compat_colors.ON_SURFACE_VARIANT
            self.title_text.color = compat_colors.ON_SURFACE_VARIANT
        else:
            self.bgcolor = compat_colors.SURFACE_VARIANT
            self.ink = True
            self.on_click = self._handle_click
            self.icon_widget.color = self.color
            self.title_text.color = compat_colors.ON_SURFACE
            
        if self.page:
            self.page.update()
            
    def update_title(self, new_title: str):
        """更新标题"""
        self.title = new_title
        self.title_text.value = new_title
        if self.page:
            self.page.update()
            
    def update_subtitle(self, new_subtitle: str):
        """更新副标题"""
        self.subtitle = new_subtitle
        self.subtitle_text.value = new_subtitle
        if self.page:
            self.page.update()

class QuickActionButton(ft.ElevatedButton):
    """快速操作按钮组件"""
    
    def __init__(
        self,
        text: str,
        icon: str,
        color: str = compat_colors.BLUE,
        on_click: Optional[Callable] = None,
        width: Optional[int] = None,
        **kwargs
    ):
        super().__init__(
            content=ft.Row([
                ft.Icon(icon),
                ft.Text(text),
            ], tight=True),
            on_click=on_click,
            style=ft.ButtonStyle(
                color=compat_colors.WHITE,
                bgcolor=color,
                padding=ft.padding.all(15),
            ),
            width=width,
            **kwargs
        )

def create_action_button(
    title: str,
    subtitle: str,
    icon: str,
    color: str = compat_colors.BLUE,
    on_click: Optional[Callable] = None
) -> ActionButton:
    """创建操作按钮的便捷函数"""
    return ActionButton(
        title=title,
        subtitle=subtitle,
        icon=icon,
        color=color,
        on_click=on_click
    )

def create_quick_button(
    text: str,
    icon: str,
    color: str = compat_colors.BLUE,
    on_click: Optional[Callable] = None
) -> QuickActionButton:
    """创建快速按钮的便捷函数"""
    return QuickActionButton(
        text=text,
        icon=icon,
        color=color,
        on_click=on_click
    )