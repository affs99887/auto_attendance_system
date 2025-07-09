"""
Flet版本兼容性检查和回退机制
"""

import flet as ft


def check_flet_features():
    """检查Flet版本支持的功能"""
    features = {
        "visual_density": hasattr(ft, "ThemeVisualDensity"),
        "material3": True,  # 大部分版本都支持
        "surface_tint": True,  # 假设支持
        "box_shadow": True,   # 假设支持
    }
    return features


def safe_theme_create(color_scheme_seed: str, use_material3: bool = True) -> ft.Theme:
    """安全创建主题，处理版本兼容性"""
    theme_kwargs = {
        "color_scheme_seed": color_scheme_seed,
        "use_material3": use_material3,
    }
    
    # 检查是否支持visual_density
    try:
        theme_kwargs["visual_density"] = ft.ThemeVisualDensity.COMPACT
    except AttributeError:
        pass  # 旧版本不支持，忽略
    
    return ft.Theme(**theme_kwargs)


def safe_app_bar_create(
    title,
    center_title=True,
    bgcolor=None,
    surface_tint_color=None,
    actions=None
) -> ft.AppBar:
    """安全创建AppBar，处理不支持的属性"""
    appbar_kwargs = {
        "title": title,
        "center_title": center_title,
        "actions": actions or [],
    }
    
    if bgcolor:
        appbar_kwargs["bgcolor"] = bgcolor
    
    # 检查是否支持surface_tint_color
    try:
        if surface_tint_color:
            appbar_kwargs["surface_tint_color"] = surface_tint_color
    except:
        pass  # 不支持则忽略
    
    return ft.AppBar(**appbar_kwargs)


def safe_border_create(width=1, color="#E0E0E0"):
    """安全创建边框"""
    try:
        return ft.border.all(width=width, color=color)
    except:
        return None


def safe_box_shadow_create(
    spread_radius=0,
    blur_radius=8,
    color="rgba(0,0,0,0.1)",
    offset=None
):
    """安全创建阴影"""
    try:
        shadow_kwargs = {
            "spread_radius": spread_radius,
            "blur_radius": blur_radius,
            "color": color,
        }
        if offset:
            shadow_kwargs["offset"] = offset
        return ft.BoxShadow(**shadow_kwargs)
    except:
        return None


# 兼容的颜色常量
COMPAT_COLORS = {
    "primary": "#2196F3",
    "secondary": "#9C27B0", 
    "success": "#4CAF50",
    "error": "#F44336",
    "warning": "#FF9800",
    "info": "#2196F3",
    "surface": "#FFFFFF",
    "surface_variant": "#F5F5F5",
    "background": "#FFFFFF",
    "on_surface": "#212121",
    "on_surface_variant": "#757575",
    "outline": "#E0E0E0",
}


# 兼容的间距常量
COMPAT_SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 16,
    "lg": 24,
    "xl": 32,
}


# 兼容的字体大小
COMPAT_TYPOGRAPHY = {
    "h1": 32,
    "h2": 28,
    "h3": 24,
    "h4": 20,
    "h5": 18,
    "h6": 16,
    "body1": 16,
    "body2": 14,
    "caption": 12,
    "button": 14,
}