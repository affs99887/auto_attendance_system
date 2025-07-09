"""
现代化按钮组件
支持多种样式和动画效果的按钮
"""

import flet as ft
from typing import Optional, Callable, Literal
import asyncio

try:
    from ..utils.design_tokens import tokens, colors, typography
except ImportError:
    try:
        from utils.design_tokens import tokens, colors, typography
    except ImportError:
        # 回退到基础配置
        class MockTokens:
            COLORS = {"primary": {"500": "#2196F3"}, "neutral": {"0": "#FFFFFF"}}
            SPACING = {"md": 16}
            RADIUS = {"lg": 12}
        class MockTypography:
            button = {"size": 14, "weight": "w_500"}
        tokens = MockTokens()
        colors = tokens.COLORS
        typography = {"button": {"size": 14, "weight": ft.FontWeight.W_500}}


class ModernButton(ft.Container):
    """现代化按钮组件"""
    
    def __init__(
        self,
        text: str,
        icon: Optional[str] = None,
        variant: Literal["primary", "secondary", "outline", "ghost"] = "primary",
        size: Literal["sm", "md", "lg"] = "md",
        loading: bool = False,
        disabled: bool = False,
        width: Optional[int] = None,
        on_click: Optional[Callable] = None,
        **kwargs
    ):
        self.text = text
        self.icon = icon
        self.variant = variant
        self.size = size
        self.loading = loading
        self.disabled = disabled
        self._on_click = on_click
        self._is_pressed = False
        
        super().__init__(**kwargs)
        self.width = width
        self._build_button()
    
    def _get_size_config(self):
        """获取尺寸配置"""
        size_configs = {
            "sm": {"height": 32, "padding": tokens.SPACING["sm"], "font_size": 12},
            "md": {"height": 40, "padding": tokens.SPACING["md"], "font_size": 14},
            "lg": {"height": 48, "padding": tokens.SPACING["lg"], "font_size": 16},
        }
        return size_configs.get(self.size, size_configs["md"])
    
    def _get_variant_style(self):
        """获取变体样式"""
        if self.disabled:
            return {
                "bgcolor": colors["neutral"]["200"],
                "text_color": colors["neutral"]["400"],
                "border_color": colors["neutral"]["200"],
            }
        
        variant_styles = {
            "primary": {
                "bgcolor": colors["primary"]["500"],
                "text_color": colors["neutral"]["0"],
                "hover_bgcolor": colors["primary"]["600"],
                "border_color": colors["primary"]["500"],
            },
            "secondary": {
                "bgcolor": colors["secondary"]["500"],
                "text_color": colors["neutral"]["0"], 
                "hover_bgcolor": colors["secondary"]["600"],
                "border_color": colors["secondary"]["500"],
            },
            "outline": {
                "bgcolor": "transparent",
                "text_color": colors["primary"]["500"],
                "hover_bgcolor": f"{colors['primary']['500']}10",
                "border_color": colors["primary"]["500"],
            },
            "ghost": {
                "bgcolor": "transparent",
                "text_color": colors["primary"]["500"],
                "hover_bgcolor": f"{colors['primary']['500']}10",
                "border_color": "transparent",
            },
        }
        return variant_styles.get(self.variant, variant_styles["primary"])
    
    def _build_button(self):
        """构建按钮"""
        size_config = self._get_size_config()
        style = self._get_variant_style()
        
        # 🔄 加载状态或图标
        leading_widget = None
        if self.loading:
            leading_widget = ft.ProgressRing(
                width=16,
                height=16,
                stroke_width=2,
                color=style["text_color"],
            )
        elif self.icon:
            leading_widget = ft.Icon(
                self.icon,
                size=16,
                color=style["text_color"],
            )
        
        # 📝 按钮内容
        content_controls = []
        if leading_widget:
            content_controls.append(leading_widget)
        
        content_controls.append(
            ft.Text(
                "处理中..." if self.loading else self.text,
                size=size_config["font_size"],
                weight=typography["button"]["weight"],
                color=style["text_color"],
            )
        )
        
        button_content = ft.Row(
            content_controls,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=tokens.SPACING["xs"],
            tight=True,
        )
        
        # 🎨 设置容器属性
        self.content = button_content
        self.height = size_config["height"]
        self.padding = ft.padding.symmetric(
            horizontal=size_config["padding"],
            vertical=tokens.SPACING["xs"],
        )
        self.border_radius = tokens.RADIUS["lg"]
        self.bgcolor = style["bgcolor"]
        self.ink = not self.disabled
        self.on_click = self._handle_click
        self.on_hover = self._handle_hover
        
        # 🔲 边框设置
        if style["border_color"] != "transparent":
            self.border = ft.border.all(
                width=1,
                color=style["border_color"],
            )
        
        # 🌟 阴影效果（仅主要按钮）
        if self.variant in ["primary", "secondary"] and not self.disabled:
            self.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=8,
                color=f"{style['bgcolor']}30",
                offset=ft.Offset(0, 2),
            )
    
    async def _handle_hover(self, e):
        """处理悬停效果"""
        if self.disabled:
            return
            
        is_hovered = e.data == "true"
        style = self._get_variant_style()
        
        if is_hovered:
            self.bgcolor = style.get("hover_bgcolor", style["bgcolor"])
            if self.variant in ["primary", "secondary"]:
                self.shadow = ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=12,
                    color=f"{style['bgcolor']}40",
                    offset=ft.Offset(0, 4),
                )
        else:
            self.bgcolor = style["bgcolor"]
            if self.variant in ["primary", "secondary"]:
                self.shadow = ft.BoxShadow(
                    spread_radius=0,
                    blur_radius=8,
                    color=f"{style['bgcolor']}30",
                    offset=ft.Offset(0, 2),
                )
        
        if self.page:
            self.page.update()
    
    def _handle_click(self, e):
        """处理点击事件"""
        if self.disabled or self.loading:
            return
            
        asyncio.create_task(self._click_animation())
        if self._on_click:
            self._on_click(e)
    
    async def _click_animation(self):
        """点击动画"""
        if self.page:
            # 按下效果
            self.scale = 0.98
            self.page.update()
            
            await asyncio.sleep(0.1)
            
            # 恢复
            self.scale = 1.0
            self.page.update()
    
    def set_loading(self, loading: bool):
        """设置加载状态"""
        self.loading = loading
        self._build_button()
        if self.page:
            self.page.update()
    
    def set_disabled(self, disabled: bool):
        """设置禁用状态"""
        self.disabled = disabled
        self._build_button()
        if self.page:
            self.page.update()


class ModernActionButton(ft.Container):
    """现代化大型操作按钮（用于打卡等主要操作）"""
    
    def __init__(
        self,
        title: str,
        subtitle: str,
        icon: str,
        color: str = colors["primary"]["500"],
        width: int = 240,
        height: int = 180,
        on_click: Optional[Callable] = None,
        disabled: bool = False,
        loading: bool = False,
        **kwargs
    ):
        self.title = title
        self.subtitle = subtitle
        self.icon_name = icon
        self.color = color
        self.loading = loading
        self.disabled = disabled
        self._on_click = on_click
        
        super().__init__(**kwargs)
        self.width = width
        self.height = height
        self._build_action_button()
    
    def _build_action_button(self):
        """构建大型操作按钮"""
        # 🎨 状态相关的样式
        if self.disabled:
            bg_color = colors["neutral"]["100"]
            text_color = colors["neutral"]["400"]
            icon_color = colors["neutral"]["400"]
        else:
            bg_color = self.color
            text_color = colors["neutral"]["0"]
            icon_color = colors["neutral"]["0"]
        
        # 🔄 图标或加载状态
        icon_widget = ft.ProgressRing(
            width=48,
            height=48,
            stroke_width=4,
            color=icon_color,
        ) if self.loading else ft.Icon(
            self.icon_name,
            size=48,
            color=icon_color,
        )
        
        # 📝 内容布局
        button_content = ft.Column([
            icon_widget,
            ft.Text(
                "处理中..." if self.loading else self.title,
                size=typography["h5"]["size"],
                weight=typography["h5"]["weight"],
                color=text_color,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Text(
                "请稍候" if self.loading else self.subtitle,
                size=typography["body2"]["size"],
                color=f"{text_color}CC",  # 80% 透明度
                text_align=ft.TextAlign.CENTER,
            ),
        ], 
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=tokens.SPACING["md"])
        
        # 🎨 容器设置
        self.content = button_content
        self.padding = tokens.SPACING["xl"]
        self.border_radius = tokens.RADIUS["2xl"]
        self.bgcolor = bg_color
        self.ink = not self.disabled
        self.on_click = self._handle_click
        self.on_hover = self._handle_hover
        
        # 🌟 渐变阴影效果
        if not self.disabled:
            self.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=f"{self.color}40",
                offset=ft.Offset(0, 8),
            )
    
    async def _handle_hover(self, e):
        """悬停效果"""
        if self.disabled:
            return
            
        is_hovered = e.data == "true"
        
        if is_hovered:
            self.scale = 1.05
            self.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=32,
                color=f"{self.color}50",
                offset=ft.Offset(0, 12),
            )
        else:
            self.scale = 1.0
            self.shadow = ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=f"{self.color}40",
                offset=ft.Offset(0, 8),
            )
        
        if self.page:
            self.page.update()
    
    def _handle_click(self, e):
        """点击处理"""
        if self.disabled or self.loading:
            return
            
        asyncio.create_task(self._click_animation())
        if self._on_click:
            self._on_click(e)
    
    async def _click_animation(self):
        """点击动画"""
        if self.page:
            self.scale = 0.95
            self.page.update()
            
            await asyncio.sleep(0.15)
            
            self.scale = 1.0
            self.page.update()
    
    def set_loading(self, loading: bool):
        """设置加载状态"""
        self.loading = loading
        self._build_action_button()
        if self.page:
            self.page.update()


# 🎯 便捷创建函数
def create_modern_button(
    text: str,
    icon: Optional[str] = None,
    variant: Literal["primary", "secondary", "outline", "ghost"] = "primary",
    size: Literal["sm", "md", "lg"] = "md",
    on_click: Optional[Callable] = None,
    **kwargs
) -> ModernButton:
    """创建现代按钮的便捷函数"""
    return ModernButton(
        text=text,
        icon=icon,
        variant=variant,
        size=size,
        on_click=on_click,
        **kwargs
    )


def create_modern_action_button(
    title: str,
    subtitle: str,
    icon: str,
    color: str = colors["primary"]["500"],
    on_click: Optional[Callable] = None,
    **kwargs
) -> ModernActionButton:
    """创建现代操作按钮的便捷函数"""
    return ModernActionButton(
        title=title,
        subtitle=subtitle,
        icon=icon,
        color=color,
        on_click=on_click,
        **kwargs
    )