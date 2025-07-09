"""
加载遮罩组件
提供现代化的加载状态反馈
"""

import flet as ft
import asyncio
from typing import Optional

try:
    from ..utils.design_tokens import tokens, colors, typography
except ImportError:
    try:
        from utils.design_tokens import tokens, colors, typography
    except ImportError:
        # 回退模式
        class MockTokens:
            COLORS = {"neutral": {"0": "#FFFFFF", "900": "#212121"}}
            SPACING = {"md": 16}
            RADIUS = {"lg": 12}
        tokens = MockTokens()
        colors = tokens.COLORS
        typography = {"body1": {"size": 16}}


class LoadingOverlay(ft.Container):
    """现代化加载遮罩"""
    
    def __init__(
        self,
        message: str = "加载中...",
        show_progress: bool = True,
        blur_background: bool = True,
        **kwargs
    ):
        self.message = message
        self.show_progress = show_progress
        self.blur_background = blur_background
        
        super().__init__(**kwargs)
        self._build_overlay()
    
    def _build_overlay(self):
        """构建遮罩内容"""
        # 🔄 进度指示器
        progress_widget = ft.ProgressRing(
            width=40,
            height=40,
            stroke_width=4,
            color=colors["primary"]["500"],
        ) if self.show_progress else ft.Container()
        
        # 📝 加载内容
        loading_content = ft.Container(
            content=ft.Column([
                progress_widget,
                ft.Text(
                    self.message,
                    size=typography["body1"]["size"],
                    color=colors["neutral"]["700"],
                    text_align=ft.TextAlign.CENTER,
                ),
            ], 
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=tokens.SPACING["md"]),
            
            padding=tokens.SPACING["xl"],
            bgcolor=colors["neutral"]["0"],
            border_radius=tokens.RADIUS["lg"],
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=f"{colors['neutral']['900']}20",
                offset=ft.Offset(0, 8),
            ),
        )
        
        # 🎨 设置遮罩属性
        self.content = ft.Container(
            content=loading_content,
            alignment=ft.alignment.center,
            expand=True,
        )
        self.bgcolor = f"{colors['neutral']['900']}40"  # 40% 透明度
        self.expand = True
        self.visible = False  # 默认隐藏
    
    async def show(self, message: Optional[str] = None):
        """显示加载遮罩"""
        if message:
            self.message = message
            # 更新消息文本
            loading_container = self.content.content
            text_widget = loading_container.content.controls[1]
            text_widget.value = message
        
        self.visible = True
        if self.page:
            self.page.update()
    
    async def hide(self):
        """隐藏加载遮罩"""
        self.visible = False
        if self.page:
            self.page.update()
    
    async def show_with_delay(self, message: str, delay: float = 2.0):
        """显示加载遮罩并在指定时间后自动隐藏"""
        await self.show(message)
        await asyncio.sleep(delay)
        await self.hide()


class ProgressIndicator(ft.Container):
    """进度指示器组件"""
    
    def __init__(
        self,
        title: str = "处理中",
        progress: float = 0.0,
        show_percentage: bool = True,
        **kwargs
    ):
        self.title = title
        self.progress = max(0.0, min(1.0, progress))  # 限制在0-1之间
        self.show_percentage = show_percentage
        
        super().__init__(**kwargs)
        self._build_indicator()
    
    def _build_indicator(self):
        """构建进度指示器"""
        # 📊 进度条
        progress_bar = ft.ProgressBar(
            value=self.progress,
            bgcolor=colors["neutral"]["200"],
            color=colors["primary"]["500"],
            height=8,
        )
        
        # 📝 标题和百分比
        header_controls = [
            ft.Text(
                self.title,
                size=typography["body1"]["size"],
                weight=ft.FontWeight.W_500,
                color=colors["neutral"]["900"],
            )
        ]
        
        if self.show_percentage:
            header_controls.append(
                ft.Text(
                    f"{int(self.progress * 100)}%",
                    size=typography["body2"]["size"],
                    color=colors["neutral"]["600"],
                )
            )
        
        # 🎨 布局
        self.content = ft.Column([
            ft.Row(
                header_controls,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            progress_bar,
        ], spacing=tokens.SPACING["xs"])
        
        self.padding = tokens.SPACING["md"]
        self.border_radius = tokens.RADIUS["lg"]
        self.bgcolor = colors["neutral"]["50"]
    
    def update_progress(self, progress: float, title: Optional[str] = None):
        """更新进度"""
        self.progress = max(0.0, min(1.0, progress))
        
        if title:
            self.title = title
        
        # 更新UI
        header_row = self.content.controls[0]
        progress_bar = self.content.controls[1]
        
        # 更新标题
        if title:
            header_row.controls[0].value = title
        
        # 更新百分比
        if self.show_percentage and len(header_row.controls) > 1:
            header_row.controls[1].value = f"{int(self.progress * 100)}%"
        
        # 更新进度条
        progress_bar.value = self.progress
        
        if self.page:
            self.page.update()


class Toast(ft.Container):
    """Toast 通知组件"""
    
    def __init__(
        self,
        message: str,
        toast_type: str = "info",  # "success", "warning", "error", "info"
        duration: float = 3.0,
        **kwargs
    ):
        self.message = message
        self.toast_type = toast_type
        self.duration = duration
        
        super().__init__(**kwargs)
        self._build_toast()
    
    def _get_toast_style(self):
        """获取Toast样式"""
        styles = {
            "success": {
                "bgcolor": colors["success"],
                "icon": ft.icons.CHECK_CIRCLE,
                "text_color": colors["neutral"]["0"],
            },
            "warning": {
                "bgcolor": colors["warning"],
                "icon": ft.icons.WARNING,
                "text_color": colors["neutral"]["0"],
            },
            "error": {
                "bgcolor": colors["error"],
                "icon": ft.icons.ERROR,
                "text_color": colors["neutral"]["0"],
            },
            "info": {
                "bgcolor": colors["primary"]["500"],
                "icon": ft.icons.INFO,
                "text_color": colors["neutral"]["0"],
            },
        }
        return styles.get(self.toast_type, styles["info"])
    
    def _build_toast(self):
        """构建Toast"""
        style = self._get_toast_style()
        
        self.content = ft.Row([
            ft.Icon(
                style["icon"],
                color=style["text_color"],
                size=20,
            ),
            ft.Text(
                self.message,
                color=style["text_color"],
                size=typography["body2"]["size"],
                expand=True,
            ),
        ], spacing=tokens.SPACING["sm"])
        
        self.bgcolor = style["bgcolor"]
        self.padding = tokens.SPACING["md"]
        self.border_radius = tokens.RADIUS["lg"]
        self.margin = ft.margin.only(bottom=tokens.SPACING["sm"])
        self.shadow = ft.BoxShadow(
            spread_radius=0,
            blur_radius=8,
            color=f"{colors['neutral']['900']}20",
            offset=ft.Offset(0, 2),
        )
        self.visible = False
    
    async def show(self):
        """显示Toast"""
        self.visible = True
        if self.page:
            self.page.update()
        
        # 自动隐藏
        await asyncio.sleep(self.duration)
        await self.hide()
    
    async def hide(self):
        """隐藏Toast"""
        self.visible = False
        if self.page:
            self.page.update()


# 🎯 便捷函数
def create_loading_overlay(message: str = "加载中...") -> LoadingOverlay:
    """创建加载遮罩"""
    return LoadingOverlay(message=message)


def create_progress_indicator(title: str, progress: float = 0.0) -> ProgressIndicator:
    """创建进度指示器"""
    return ProgressIndicator(title=title, progress=progress)


def create_toast(message: str, toast_type: str = "info") -> Toast:
    """创建Toast通知"""
    return Toast(message=message, toast_type=toast_type)