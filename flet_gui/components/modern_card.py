"""
现代化卡片组件
使用新设计系统的状态卡片
"""

import flet as ft
from typing import Optional, Callable, Union
import asyncio

try:
    from ..utils.design_tokens import tokens, colors
except ImportError:
    try:
        from utils.design_tokens import tokens, colors
    except ImportError:
        # 回退到基础颜色
        class MockTokens:
            COLORS = {"primary": {"500": "#2196F3"}, "neutral": {"100": "#F5F5F5"}}
            SPACING = {"md": 16, "lg": 24}
            RADIUS = {"lg": 12}
        tokens = MockTokens()
        colors = tokens.COLORS


class ModernCard(ft.Container):
    """现代化状态卡片"""
    
    def __init__(
        self,
        title: str,
        value: str,
        icon: str,
        color: str = colors["primary"]["500"],
        subtitle: str = "",
        width: int = 280,
        height: int = 140,
        on_click: Optional[Callable] = None,
        show_trend: bool = False,
        trend_value: str = "",
        trend_positive: bool = True,
        **kwargs
    ):
        self.title = title
        self.value = value
        self.icon_name = icon
        self.color = color
        self.subtitle = subtitle
        self.show_trend = show_trend
        self.trend_value = trend_value
        self.trend_positive = trend_positive
        self._on_click = on_click
        
        # 初始化动画状态
        self._is_hovered = False
        self._original_scale = 1.0
        self._hover_scale = 1.02
        
        super().__init__(**kwargs)
        self._build_card()
    
    def _build_card(self):
        """构建卡片内容"""
        # 🎨 创建图标容器，带渐变背景
        icon_container = ft.Container(
            content=ft.Icon(
                self.icon_name,
                size=28,
                color="#FFFFFF",
            ),
            width=56,
            height=56,
            border_radius=tokens.RADIUS["lg"],
            bgcolor=self.color,
            alignment=ft.alignment.center,
            # 添加轻微的阴影
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=8,
                color=f"{self.color}40",  # 40% 透明度
                offset=ft.Offset(0, 2),
            )
        )
        
        # 📊 趋势指示器
        trend_widget = None
        if self.show_trend and self.trend_value:
            trend_icon = ft.icons.TRENDING_UP if self.trend_positive else ft.icons.TRENDING_DOWN
            trend_color = colors["success"] if self.trend_positive else colors["error"]
            
            trend_widget = ft.Row([
                ft.Icon(trend_icon, size=16, color=trend_color),
                ft.Text(
                    self.trend_value,
                    size=typography["caption"]["size"],
                    color=trend_color,
                    weight=ft.FontWeight.W_500,
                )
            ], spacing=4, tight=True)
        
        # 📝 文本内容区域
        text_content = ft.Column([
            # 标题
            ft.Text(
                self.title,
                size=typography["caption"]["size"],
                color=colors["neutral"]["600"],
                weight=typography["caption"]["weight"],
            ),
            
            # 数值
            ft.Text(
                self.value,
                size=typography["h4"]["size"],
                weight=typography["h4"]["weight"],
                color=colors["neutral"]["900"],
            ),
            
            # 副标题和趋势
            ft.Row([
                ft.Text(
                    self.subtitle,
                    size=typography["caption"]["size"],
                    color=colors["neutral"]["500"],
                    expand=True,
                ),
                trend_widget if trend_widget else ft.Container(),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN) if self.subtitle or trend_widget else ft.Container(),
            
        ], spacing=tokens.SPACING["xs"], tight=True)
        
        # 🎴 主内容布局
        card_content = ft.Row([
            icon_container,
            ft.Container(expand=True),  # 弹性空间
            text_content,
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        
        # 🎨 设置容器属性
        self.content = card_content
        self.width = width
        self.height = height
        self.padding = tokens.SPACING["lg"]
        self.border_radius = tokens.RADIUS["xl"]
        self.bgcolor = colors["neutral"]["0"]
        self.ink = True
        self.on_click = self._handle_click
        self.on_hover = self._handle_hover
        
        # 🌟 现代阴影效果
        self.shadow = ft.BoxShadow(
            spread_radius=0,
            blur_radius=16,
            color=f"{colors['neutral']['900']}08",  # 8% 透明度
            offset=ft.Offset(0, 4),
        )
        
        # 🔲 边框效果（可选）
        self.border = ft.border.all(
            width=1,
            color=f"{colors['neutral']['200']}",
        )
    
    async def _handle_hover(self, e):
        """处理悬停效果"""
        self._is_hovered = e.data == "true"
        
        if self._is_hovered:
            # 悬停时的效果
            self.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=24,
                color=f"{colors['neutral']['900']}12",  # 12% 透明度
                offset=ft.Offset(0, 8),
            )
            # 轻微提升效果
            self.scale = self._hover_scale
        else:
            # 恢复原状
            self.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=16,
                color=f"{colors['neutral']['900']}08",
                offset=ft.Offset(0, 4),
            )
            self.scale = self._original_scale
        
        if self.page:
            self.page.update()
    
    def _handle_click(self, e):
        """处理点击事件"""
        if self._on_click:
            # 添加点击动画效果
            asyncio.create_task(self._click_animation())
            self._on_click(e)
    
    async def _click_animation(self):
        """点击动画效果"""
        if self.page:
            # 快速缩小
            self.scale = 0.98
            self.page.update()
            
            await asyncio.sleep(0.1)
            
            # 恢复大小
            self.scale = self._hover_scale if self._is_hovered else self._original_scale
            self.page.update()
    
    def update_value(self, new_value: str, animate: bool = True):
        """更新数值"""
        self.value = new_value
        # 找到数值文本组件并更新
        text_content = self.content.controls[2]  # 文本内容区域
        value_text = text_content.controls[1]    # 数值文本
        value_text.value = new_value
        
        if animate and self.page:
            # 添加更新动画
            asyncio.create_task(self._update_animation())
    
    async def _update_animation(self):
        """数值更新动画"""
        if self.page:
            # 轻微闪烁效果
            original_color = self.bgcolor
            self.bgcolor = f"{self.color}10"  # 10% 透明度的主色
            self.page.update()
            
            await asyncio.sleep(0.3)
            
            self.bgcolor = original_color
            self.page.update()


def create_modern_status_card(
    title: str,
    value: str, 
    icon: str,
    color: str = colors["primary"]["500"],
    subtitle: str = "",
    width: int = 280,
    height: int = 140,
    on_click: Optional[Callable] = None,
    show_trend: bool = False,
    trend_value: str = "",
    trend_positive: bool = True,
) -> ModernCard:
    """创建现代状态卡片的便捷函数"""
    return ModernCard(
        title=title,
        value=value,
        icon=icon,
        color=color,
        subtitle=subtitle,
        width=width,
        height=height,
        on_click=on_click,
        show_trend=show_trend,
        trend_value=trend_value,
        trend_positive=trend_positive,
    )