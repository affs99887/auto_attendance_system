"""
现代化设计令牌系统
定义统一的视觉设计语言
"""

import flet as ft
from typing import Dict, Any


class DesignTokens:
    """设计令牌 - 定义整个应用的设计系统"""
    
    # 🎨 **现代配色方案**
    COLORS = {
        # 主要颜色 - 使用更现代的蓝色调色板
        "primary": {
            "50": "#E3F2FD",
            "100": "#BBDEFB", 
            "200": "#90CAF9",
            "300": "#64B5F6",
            "400": "#42A5F5",
            "500": "#2196F3",  # 主色
            "600": "#1E88E5",
            "700": "#1976D2",
            "800": "#1565C0",
            "900": "#0D47A1",
        },
        
        # 次要颜色 - 渐变紫色
        "secondary": {
            "50": "#F3E5F5",
            "100": "#E1BEE7",
            "200": "#CE93D8", 
            "300": "#BA68C8",
            "400": "#AB47BC",
            "500": "#9C27B0",  # 次色
            "600": "#8E24AA",
            "700": "#7B1FA2",
            "800": "#6A1B9A",
            "900": "#4A148C",
        },
        
        # 功能色彩
        "success": "#00C853",
        "warning": "#FF8F00", 
        "error": "#D32F2F",
        "info": "#0288D1",
        
        # 中性色彩 - 更现代的灰色系统
        "neutral": {
            "0": "#FFFFFF",
            "50": "#FAFAFA",
            "100": "#F5F5F5",
            "200": "#EEEEEE",
            "300": "#E0E0E0",
            "400": "#BDBDBD", 
            "500": "#9E9E9E",
            "600": "#757575",
            "700": "#616161",
            "800": "#424242",
            "900": "#212121",
            "950": "#0A0A0A",
        },
        
        # 渐变色
        "gradients": {
            "primary": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
            "success": "linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)",
            "warning": "linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%)",
            "card": "linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%)",
        }
    }
    
    # 📏 **间距系统** - 8pt网格系统
    SPACING = {
        "xs": 4,    # 0.25rem
        "sm": 8,    # 0.5rem  
        "md": 16,   # 1rem
        "lg": 24,   # 1.5rem
        "xl": 32,   # 2rem
        "2xl": 48,  # 3rem
        "3xl": 64,  # 4rem
        "4xl": 96,  # 6rem
    }
    
    # ✍️ **字体系统**
    TYPOGRAPHY = {
        "h1": {"size": 32, "weight": ft.FontWeight.BOLD, "height": 1.2},
        "h2": {"size": 28, "weight": ft.FontWeight.BOLD, "height": 1.3},
        "h3": {"size": 24, "weight": ft.FontWeight.W_600, "height": 1.4},
        "h4": {"size": 20, "weight": ft.FontWeight.W_600, "height": 1.4},
        "h5": {"size": 18, "weight": ft.FontWeight.W_500, "height": 1.5},
        "h6": {"size": 16, "weight": ft.FontWeight.W_500, "height": 1.5},
        
        "body1": {"size": 16, "weight": ft.FontWeight.NORMAL, "height": 1.6},
        "body2": {"size": 14, "weight": ft.FontWeight.NORMAL, "height": 1.6},
        "caption": {"size": 12, "weight": ft.FontWeight.NORMAL, "height": 1.5},
        "overline": {"size": 10, "weight": ft.FontWeight.W_500, "height": 1.5},
        
        "button": {"size": 14, "weight": ft.FontWeight.W_500, "height": 1.2},
    }
    
    # 🔳 **边框半径**
    RADIUS = {
        "none": 0,
        "sm": 4,
        "md": 8,
        "lg": 12,
        "xl": 16,
        "2xl": 24,
        "full": 9999,
    }
    
    # 🌑 **阴影系统**
    SHADOWS = {
        "none": "none",
        "sm": "0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        "md": "0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
        "lg": "0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)",
        "xl": "0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)",
        "2xl": "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
        "card": "0 8px 32px rgba(0, 0, 0, 0.12)",
    }
    
    # 🎭 **动画时长**
    ANIMATION = {
        "fast": 150,     # 快速动画
        "normal": 300,   # 正常动画  
        "slow": 500,     # 慢速动画
        "page": 400,     # 页面切换
    }
    
    # 📱 **断点系统**
    BREAKPOINTS = {
        "xs": 0,
        "sm": 640,
        "md": 768, 
        "lg": 1024,
        "xl": 1280,
        "2xl": 1536,
    }


class ModernTheme:
    """现代主题配置"""
    
    @staticmethod
    def create_light_theme() -> ft.Theme:
        """创建浅色主题"""
        theme_kwargs = {
            "color_scheme_seed": DesignTokens.COLORS["primary"]["500"],
            "use_material3": True,
        }
        
        # 检查是否支持visual_density
        try:
            theme_kwargs["visual_density"] = ft.ThemeVisualDensity.COMPACT
        except AttributeError:
            pass  # 旧版本不支持，忽略
            
        return ft.Theme(**theme_kwargs)
    
    @staticmethod 
    def create_dark_theme() -> ft.Theme:
        """创建深色主题"""
        theme_kwargs = {
            "color_scheme_seed": DesignTokens.COLORS["primary"]["400"],
            "use_material3": True,
        }
        
        # 检查是否支持visual_density
        try:
            theme_kwargs["visual_density"] = ft.ThemeVisualDensity.COMPACT
        except AttributeError:
            pass  # 旧版本不支持，忽略
            
        return ft.Theme(**theme_kwargs)
    
    @staticmethod
    def get_surface_colors(is_dark: bool = False) -> Dict[str, str]:
        """获取表面颜色配置"""
        if is_dark:
            return {
                "surface": DesignTokens.COLORS["neutral"]["900"],
                "surface_variant": DesignTokens.COLORS["neutral"]["800"],
                "surface_container": DesignTokens.COLORS["neutral"]["850"],
                "on_surface": DesignTokens.COLORS["neutral"]["100"],
                "on_surface_variant": DesignTokens.COLORS["neutral"]["400"],
            }
        else:
            return {
                "surface": DesignTokens.COLORS["neutral"]["0"],
                "surface_variant": DesignTokens.COLORS["neutral"]["50"],
                "surface_container": DesignTokens.COLORS["neutral"]["100"],
                "on_surface": DesignTokens.COLORS["neutral"]["900"],
                "on_surface_variant": DesignTokens.COLORS["neutral"]["600"],
            }


# 🎨 **便捷访问器**
tokens = DesignTokens()
theme = ModernTheme()

# 快速访问常用值
colors = tokens.COLORS
spacing = tokens.SPACING  
typography = tokens.TYPOGRAPHY
radius = tokens.RADIUS
shadows = tokens.SHADOWS
animation = tokens.ANIMATION