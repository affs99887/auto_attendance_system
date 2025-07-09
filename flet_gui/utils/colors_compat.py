"""
Flet 兼容性模块
处理不同版本的Flet中colors和icons属性的访问差异
"""

import flet as ft

# 兼容不同版本的Flet，处理colors属性
try:
    # 尝试使用新版本的colors
    colors = ft.colors
except AttributeError:
    # 如果colors属性不存在，创建一个兼容对象
    class Colors:
        # 主要颜色
        PRIMARY = "#2196F3"  # 主要颜色
        SECONDARY = "#607D8B"  # 次要颜色
        BLUE = "#2196F3"
        BLUE_GREY = "#607D8B"
        RED = "#F44336"
        GREEN = "#4CAF50"
        ORANGE = "#FF9800"
        PURPLE = "#9C27B0"
        TEAL = "#009688"
        AMBER = "#FFC107"
        INDIGO = "#3F51B5"
        PINK = "#E91E63"
        CYAN = "#00BCD4"
        LIME = "#CDDC39"
        YELLOW = "#FFEB3B"
        
        # 基础颜色
        WHITE = "#FFFFFF"
        BLACK = "#000000"
        GREY = "#9E9E9E"
        GRAY = "#9E9E9E"  # 别名
        
        # 表面颜色
        SURFACE_VARIANT = "#F5F5F5"
        SURFACE = "#FAFAFA"
        BACKGROUND = "#FFFFFF"
        
        # 文本颜色
        ON_SURFACE = "#212121"
        ON_SURFACE_VARIANT = "#757575"
        ON_PRIMARY = "#FFFFFF"
        ON_SECONDARY = "#FFFFFF"
        
        # 边界颜色
        OUTLINE = "#79747E"
        OUTLINE_VARIANT = "#E0E0E0"
        
        # 状态颜色
        ERROR = "#B3261E"
        SUCCESS = "#4CAF50"
        WARNING = "#FF9800"
        INFO = "#2196F3"
        
        # 添加缺失的颜色属性 - 向后兼容
        RED = "#F44336"
        GREEN = "#4CAF50"
        BLUE = "#2196F3"
        ORANGE = "#FF9800"
        PURPLE = "#9C27B0"
        
    colors = Colors()

# 兼容不同版本的Flet，处理icons属性
try:
    # 尝试使用新版本的icons
    icons = ft.icons
except AttributeError:
    # 如果icons属性不存在，创建一个兼容对象
    class Icons:
        # 导航和界面图标
        DASHBOARD = "dashboard"
        DASHBOARD_OUTLINED = "dashboard_outlined"
        SCHEDULE = "schedule"
        SCHEDULE_OUTLINED = "schedule_outlined" 
        TASK_ALT = "task_alt"
        TASK_ALT_OUTLINED = "task_alt_outlined"
        SETTINGS = "settings"
        SETTINGS_OUTLINED = "settings_outlined"
        
        # 操作图标
        ADD = "add"
        EDIT = "edit"
        DELETE = "delete"
        SAVE = "save"
        REFRESH = "refresh"
        CLOSE = "close"
        SEND = "send"
        DOWNLOAD = "download"
        RESTORE = "restore"
        TUNE = "tune"
        MORE_VERT = "more_vert"
        
        # 状态图标
        CIRCLE = "circle"
        CHECK_CIRCLE = "check_circle"
        ERROR = "error"
        INFO = "info"
        RADIO_BUTTON_UNCHECKED = "radio_button_unchecked"
        
        # 时间和日期图标
        ACCESS_TIME = "access_time"
        WB_SUNNY = "wb_sunny"
        NIGHTS_STAY = "nights_stay"
        
        # 系统图标
        POWER_SETTINGS_NEW = "power_settings_new"
        COMPUTER = "computer"
        NOTIFICATIONS = "notifications"
        SHIELD = "shield"
        CLEANING_SERVICES = "cleaning_services"
        
        # 导航图标
        ARROW_FORWARD = "arrow_forward"
        LOGIN = "login"
        LOGOUT = "logout"
        
        # 界面元素图标
        BRIGHTNESS_6 = "brightness_6"
        PALETTE = "palette"
        VISIBILITY = "visibility"
        VISIBILITY_OFF = "visibility_off"
        CATEGORY = "category"
        ARTICLE = "article"
        
        # 控制图标
        PLAY_ARROW = "play_arrow"
        STOP = "stop"
        PAUSE = "pause"
        CANCEL = "cancel"
        
        # 其他常用图标
        HOME = "home"
        PERSON = "person"
        WORK = "work"
        ALARM = "alarm"
        HISTORY = "history"
        ANALYTICS = "analytics"
        
    icons = Icons()

# 导出对象
__all__ = ['colors', 'icons']