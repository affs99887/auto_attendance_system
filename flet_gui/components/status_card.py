"""
状态卡片组件
可复用的状态显示卡片
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
                SURFACE_VARIANT = "#F5F5F5"
                ON_SURFACE_VARIANT = "#757575"
            compat_colors = Colors()

class StatusCard(ft.Container):
    """状态卡片组件"""
    
    def __init__(
        self,
        title: str,
        value: str,
        icon: str,
        color: str = compat_colors.BLUE,
        subtitle: str = "",
        width: int = 300,
        height: int = 120,
        on_click: Optional[Callable] = None,
        **kwargs
    ):
        self.title = title
        self.value = value
        self.icon_name = icon
        self.color = color
        self.subtitle = subtitle
        
        # 创建图标
        self.icon_widget = ft.Icon(
            icon, 
            color=color, 
            size=40
        )
        
        # 创建标题文本
        self.title_text = ft.Text(
            title, 
            size=14, 
            color=compat_colors.ON_SURFACE_VARIANT
        )
        
        # 创建数值文本
        self.value_text = ft.Text(
            value, 
            size=24, 
            weight=ft.FontWeight.BOLD
        )
        
        # 创建副标题文本
        self.subtitle_text = ft.Text(
            subtitle, 
            size=12, 
            color=compat_colors.ON_SURFACE_VARIANT
        ) if subtitle else None
        
        # 构建内容
        text_column_children = [self.title_text, self.value_text]
        if self.subtitle_text:
            text_column_children.append(self.subtitle_text)
            
        content = ft.Column([
            ft.Row([
                self.icon_widget,
                ft.Column(
                    text_column_children,
                    spacing=2,
                    tight=True
                ),
            ], alignment=ft.MainAxisAlignment.START),
        ], spacing=8)
        
        super().__init__(
            content=content,
            width=width,
            height=height,
            padding=20,
            bgcolor=compat_colors.SURFACE_VARIANT,
            border_radius=12,
            ink=True,
            on_click=on_click,
            **kwargs
        )
        
    def update_value(self, new_value: str):
        """更新数值"""
        self.value = new_value
        self.value_text.value = new_value
        if self.page:
            self.page.update()
            
    def update_subtitle(self, new_subtitle: str):
        """更新副标题"""
        self.subtitle = new_subtitle
        if self.subtitle_text:
            self.subtitle_text.value = new_subtitle
        else:
            self.subtitle_text = ft.Text(
                new_subtitle,
                size=12,
                color=compat_colors.ON_SURFACE_VARIANT
            )
            # 重新构建内容
            text_column_children = [self.title_text, self.value_text, self.subtitle_text]
            self.content.controls[0].controls[1].controls = text_column_children
            
        if self.page:
            self.page.update()
            
    def update_color(self, new_color: str):
        """更新颜色"""
        self.color = new_color
        self.icon_widget.color = new_color
        if self.page:
            self.page.update()
            
    def set_loading(self, loading: bool = True):
        """设置加载状态"""
        if loading:
            self.value_text.value = "..."
            self.icon_widget = ft.ProgressRing(width=30, height=30)
        else:
            self.value_text.value = self.value
            self.icon_widget = ft.Icon(self.icon_name, color=self.color, size=40)
            
        # 重新构建内容
        text_column_children = [self.title_text, self.value_text]
        if self.subtitle_text:
            text_column_children.append(self.subtitle_text)
            
        self.content.controls[0].controls[0] = self.icon_widget
        self.content.controls[0].controls[1].controls = text_column_children
        
        if self.page:
            self.page.update()

def create_status_card(
    title: str,
    value: str, 
    icon: str,
    color: str = compat_colors.BLUE,
    subtitle: str = "",
    on_click: Optional[Callable] = None
) -> StatusCard:
    """创建状态卡片的便捷函数"""
    return StatusCard(
        title=title,
        value=value,
        icon=icon,
        color=color,
        subtitle=subtitle,
        on_click=on_click
    )