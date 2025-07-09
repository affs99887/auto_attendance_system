"""
现代化主题管理器
管理应用主题和现代设计系统
"""

import flet as ft
import json
import os
from typing import Dict, Any, Optional
import logging

# 导入设计系统
try:
    from .design_tokens import tokens, colors, theme, ModernTheme
    from .colors_compat import colors as compat_colors
except ImportError:
    try:
        from design_tokens import tokens, colors, theme, ModernTheme
        from colors_compat import colors as compat_colors
    except ImportError:
        try:
            from flet_gui.utils.design_tokens import tokens, colors, theme, ModernTheme
            from flet_gui.utils.colors_compat import colors as compat_colors
        except ImportError:
            # 回退兼容
            class MockTokens:
                COLORS = {"primary": {"500": "#2196F3"}, "neutral": {"0": "#FFFFFF"}}
                SPACING = {"md": 16}
            class MockTheme:
                @staticmethod
                def create_light_theme(): return ft.Theme(use_material3=True)
                @staticmethod 
                def create_dark_theme(): return ft.Theme(use_material3=True)
                @staticmethod
                def get_surface_colors(is_dark=False): return {}
            tokens = MockTokens()
            colors = tokens.COLORS
            theme = MockTheme()
            compat_colors = MockTokens()

logger = logging.getLogger(__name__)

class ThemeManager:
    """现代化主题管理器"""
    
    def __init__(self, page: ft.Page):
        self.page = page
        self.current_theme = "system"
        self.config_file = "flet_gui_theme.json"
        self.is_dark_mode = False
        
        # 🎨 使用新的设计令牌（兼容模式）
        try:
            self.theme_colors = {
                "primary": colors["primary"]["500"],
                "secondary": colors["secondary"]["500"], 
                "surface": colors["neutral"]["0"],
                "error": colors["error"],
                "success": colors["success"],
                "warning": colors["warning"],
            }
        except (KeyError, TypeError):
            # 回退到兼容色彩
            self.theme_colors = {
                "primary": compat_colors.BLUE,
                "secondary": compat_colors.BLUE_GREY,
                "surface": compat_colors.SURFACE_VARIANT,
                "error": compat_colors.RED,
                "success": compat_colors.GREEN,
                "warning": compat_colors.ORANGE,
            }
        
        # 加载配置
        self.load_theme_preferences()
        
        # 监听系统主题变化
        self.page.on_window_event = self._handle_window_event
        
    def _handle_window_event(self, e):
        """处理窗口事件"""
        if e.data == "blur":
            # 窗口失去焦点时保存配置
            self.save_theme_preferences()

    def load_theme_preferences(self):
        """加载主题偏好设置"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.current_theme = config.get("theme", "system")
                    self.theme_colors.update(config.get("theme_colors", {}))
        except Exception as e:
            logger.error(f"Failed to load theme preferences: {e}")
            
    def save_theme_preferences(self):
        """保存主题偏好设置"""
        try:
            config = {
                "theme": self.current_theme,
                "theme_colors": self.theme_colors,
                "design_version": "2.0"  # 标记新版本设计系统
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save theme preferences: {e}")
            
    def apply_theme(self, theme_name: str):
        """应用现代主题"""
        self.current_theme = theme_name
        self.is_dark_mode = theme_name == "dark" or (
            theme_name == "system" and self._is_system_dark()
        )
        
        # 🎨 应用现代主题
        if theme_name == "light":
            self.page.theme_mode = ft.ThemeMode.LIGHT
            self.page.theme = theme.create_light_theme()
        elif theme_name == "dark":
            self.page.theme_mode = ft.ThemeMode.DARK
            self.page.theme = theme.create_dark_theme()
        else:  # system
            self.page.theme_mode = ft.ThemeMode.SYSTEM
            self.page.theme = theme.create_light_theme()  # 默认浅色
            
        # 更新页面
        self.page.update()
        self.save_theme_preferences()
        
        # 触发主题变化事件
        self._notify_theme_change()
    
    def _is_system_dark(self) -> bool:
        """检测系统是否为深色模式"""
        # 这里可以添加系统深色模式检测逻辑
        # 暂时返回False，依赖Flet的系统检测
        return False
    
    def _notify_theme_change(self):
        """通知主题变化"""
        # 可以在这里添加主题变化的回调
        logger.info(f"Theme changed to: {self.current_theme}")
        
    def get_surface_colors(self) -> Dict[str, str]:
        """获取当前主题的表面颜色"""
        return theme.get_surface_colors(self.is_dark_mode)
        
    def toggle_theme(self):
        """切换主题"""
        if self.current_theme == "light":
            self.apply_theme("dark")
        elif self.current_theme == "dark":
            self.apply_theme("system")
        else:
            self.apply_theme("light")
            
    def update_primary_color(self, color: str):
        """更新主色调"""
        self.custom_colors["primary"] = color
        self.apply_theme(self.current_theme)
        
    def get_theme_config(self) -> Dict[str, Any]:
        """获取主题配置"""
        return {
            "current_theme": self.current_theme,
            "custom_colors": self.custom_colors,
            "available_themes": ["light", "dark", "system"]
        }
        
    def create_theme_selector(self) -> ft.Dropdown:
        """创建主题选择器"""
        return ft.Dropdown(
            value=self.current_theme,
            options=[
                ft.dropdown.Option("light", "浅色主题"),
                ft.dropdown.Option("dark", "深色主题"),
                ft.dropdown.Option("system", "跟随系统"),
            ],
            on_change=lambda e: self.apply_theme(e.control.value),
            width=150,
        )
        
    def create_color_picker(self) -> ft.Container:
        """创建颜色选择器"""
        color_options = [
            ("蓝色", compat_colors.BLUE),
            ("绿色", compat_colors.GREEN),
            ("紫色", colors.PURPLE),
            ("橙色", compat_colors.ORANGE),
            ("红色", compat_colors.RED),
            ("青色", colors.CYAN),
        ]
        
        color_buttons = []
        for name, color in color_options:
            color_buttons.append(
                ft.Container(
                    content=ft.Text(name, size=12, color=compat_colors.WHITE),
                    bgcolor=color,
                    width=60,
                    height=40,
                    border_radius=8,
                    alignment=ft.alignment.center,
                    on_click=lambda e, c=color: self.update_primary_color(c),
                    ink=True,
                )
            )
            
        return ft.Container(
            content=ft.Column([
                ft.Text("选择主色调", size=14, weight=ft.FontWeight.W_500),
                ft.Row(color_buttons, wrap=True, spacing=8),
            ], spacing=10),
            padding=15,
        )