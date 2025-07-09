"""
Flet GUI 主应用入口
自动打卡系统现代化界面
"""

import flet as ft
import asyncio
import logging
from typing import Optional

# 导入兼容性工具
try:
    from utils.compatibility import COMPAT_COLORS, COMPAT_SPACING, COMPAT_TYPOGRAPHY, safe_app_bar_create, safe_border_create
    from utils.colors_compat import colors as compat_colors, icons
except ImportError:
    try:
        from flet_gui.utils.compatibility import COMPAT_COLORS, COMPAT_SPACING, COMPAT_TYPOGRAPHY, safe_app_bar_create, safe_border_create
        from flet_gui.utils.colors_compat import colors as compat_colors, icons
    except ImportError:
        # 最后的回退
        COMPAT_COLORS = {
            "primary": "#2196F3",
            "success": "#4CAF50",
            "error": "#F44336",
            "surface": "#FFFFFF",
            "surface_variant": "#F5F5F5",
            "on_surface": "#212121",
            "outline": "#E0E0E0",
        }
        COMPAT_SPACING = {"md": 16, "lg": 24, "xl": 32}
        COMPAT_TYPOGRAPHY = {"h5": 18, "caption": 12}
        
        def safe_app_bar_create(*args, **kwargs):
            return ft.AppBar(*args, **kwargs)
        def safe_border_create(*args, **kwargs):
            return None
        
        class Icons:
            DASHBOARD = "dashboard"
            DASHBOARD_OUTLINED = "dashboard_outlined"
            SCHEDULE = "schedule"
            SCHEDULE_OUTLINED = "schedule_outlined"
            TASK_ALT = "task_alt"
            TASK_ALT_OUTLINED = "task_alt_outlined"
            SETTINGS = "settings"
            SETTINGS_OUTLINED = "settings_outlined"
            BRIGHTNESS_6 = "brightness_6"
            REFRESH = "refresh"
            CIRCLE = "circle"
            ERROR = "error"
        icons = Icons()
        compat_colors = type('MockColors', (), COMPAT_COLORS)()

# 导入自定义模块
import sys
import os

# 添加当前目录到Python路径以支持打包后的模块导入
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from adapters.system_adapter import SystemAdapter
    from utils.state_manager import app_state
    from utils.theme_manager import ThemeManager
    from pages.dashboard import DashboardPage
    from pages.punch_page import PunchPage  
    from pages.tasks_page import TasksPage
    from pages.settings_page import SettingsPage
except ImportError as e:
    # 尝试使用绝对导入作为后备方案
    try:
        from flet_gui.adapters.system_adapter import SystemAdapter
        from flet_gui.utils.state_manager import app_state
        from flet_gui.utils.theme_manager import ThemeManager
        from flet_gui.pages.dashboard import DashboardPage
        from flet_gui.pages.punch_page import PunchPage  
        from flet_gui.pages.tasks_page import TasksPage
        from flet_gui.pages.settings_page import SettingsPage
    except ImportError:
        logging.error(f"Failed to import modules: {e}")
        raise ImportError(f"无法导入必要模块: {e}") from e

# 配置日志
def setup_logging():
    """设置日志配置，确保日志目录存在"""
    import os
    
    # 获取当前执行目录
    if getattr(sys, 'frozen', False):
        # 如果是打包后的应用
        app_dir = os.path.dirname(sys.executable)
    else:
        # 如果是开发环境
        app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # 确保logs目录存在
    logs_dir = os.path.join(app_dir, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    
    # 配置日志文件路径
    log_file = os.path.join(logs_dir, 'flet_gui.log')
    
    # 设置日志配置
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    return log_file

# 初始化日志
try:
    log_file_path = setup_logging()
    logger = logging.getLogger(__name__)
    logger.info(f"日志系统初始化成功，日志文件: {log_file_path}")
except Exception as e:
    # 如果日志文件创建失败，至少保留控制台输出
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    logger = logging.getLogger(__name__)
    logger.warning(f"日志文件创建失败，仅使用控制台输出: {e}")

class AttendanceApp:
    """自动打卡系统主应用"""
    
    def __init__(self, page: ft.Page):
        self.page = page
        self.system_adapter = SystemAdapter()
        self.theme_manager = ThemeManager(page)
        self.current_page_index = 0
        
        # 页面实例
        self.dashboard_page: Optional[DashboardPage] = None
        self.punch_page: Optional[PunchPage] = None
        self.tasks_page: Optional[TasksPage] = None
        self.settings_page: Optional[SettingsPage] = None
        
        # UI组件
        self.navigation_rail: Optional[ft.NavigationRail] = None
        self.main_content: Optional[ft.Container] = None
        self.status_bar: Optional[ft.Container] = None
        
        self._setup_page()
        self._setup_system_adapter()
        
    def _setup_page(self):
        """配置页面基础设置"""
        self.page.title = "自动打卡系统"
        self.page.window_width = 1200
        self.page.window_height = 800
        self.page.window_min_width = 800
        self.page.window_min_height = 600
        self.page.padding = 0
        self.page.theme_mode = ft.ThemeMode.SYSTEM
        
        # 添加窗口大小变化事件监听
        self.page.on_resize = self._on_window_resize
        
        # 应用主题
        self.theme_manager.apply_theme("system")
        
    def _setup_system_adapter(self):
        """配置系统适配器"""
        self.system_adapter.set_page(self.page)
        
        # 订阅系统事件
        self.system_adapter.add_listener(self._on_system_event)
        
    async def _on_system_event(self, event_type: str, data=None):
        """处理系统事件"""
        logger.info(f"System event: {event_type}")
        
        # 更新状态栏
        if self.status_bar:
            await self._update_status_bar()
            
        # 通知页面更新
        if self.dashboard_page:
            await self.dashboard_page.on_system_event(event_type, data)
            
    def _create_navigation_rail(self) -> ft.NavigationRail:
        """创建现代化导航栏"""
        self.navigation_rail = ft.NavigationRail(
            selected_index=self.current_page_index,
            label_type=ft.NavigationRailLabelType.ALL,
            expand=True,
            destinations=[
                ft.NavigationRailDestination(
                    icon=icons.DASHBOARD_OUTLINED,
                    selected_icon=icons.DASHBOARD,
                    label="仪表板"
                ),
                ft.NavigationRailDestination(
                    icon=icons.SCHEDULE_OUTLINED,
                    selected_icon=icons.SCHEDULE,
                    label="打卡操作"
                ),
                ft.NavigationRailDestination(
                    icon=icons.TASK_ALT_OUTLINED,
                    selected_icon=icons.TASK_ALT,
                    label="任务管理"
                ),
                ft.NavigationRailDestination(
                    icon=icons.SETTINGS_OUTLINED,
                    selected_icon=icons.SETTINGS,
                    label="系统设置"
                ),
            ],
            on_change=self._on_navigation_change,
            bgcolor=COMPAT_COLORS["surface"],
        )
        return self.navigation_rail
        
    def _create_app_bar(self) -> ft.AppBar:
        """创建现代化应用栏"""
        return ft.AppBar(
            title=ft.Text(
                "自动打卡系统",
                size=COMPAT_TYPOGRAPHY["h5"],
                weight=ft.FontWeight.BOLD,
                color=COMPAT_COLORS["on_surface"]
            ),
            center_title=True,
            bgcolor=COMPAT_COLORS["surface"],
            actions=[
                ft.IconButton(
                    icons.BRIGHTNESS_6,
                    tooltip="切换主题",
                    on_click=lambda _: self.theme_manager.toggle_theme()
                ),
                ft.IconButton(
                    icons.REFRESH,
                    tooltip="刷新状态", 
                    on_click=self._refresh_status
                ),
            ]
        )
        
    def _create_main_content(self) -> ft.Container:
        """创建现代化主内容区域"""
        self.main_content = ft.Container(
            content=ft.Column([
                self._get_current_page()
            ], scroll=ft.ScrollMode.AUTO, expand=True),
            expand=True,
            padding=COMPAT_SPACING["xl"],
            bgcolor=COMPAT_COLORS["surface_variant"],
        )
        return self.main_content
        
    def _create_status_bar(self) -> ft.Container:
        """创建现代化状态栏"""
        self.status_bar = ft.Container(
            content=ft.Row([
                ft.Icon(icons.CIRCLE, color=COMPAT_COLORS["success"], size=12),
                ft.Text(
                    "系统状态: 运行中", 
                    size=COMPAT_TYPOGRAPHY["caption"],
                    color=COMPAT_COLORS["on_surface"]
                ),
                ft.Container(expand=True),
                ft.Text(
                    "最后更新: 刚刚", 
                    size=COMPAT_TYPOGRAPHY["caption"],
                    color=COMPAT_COLORS["on_surface"]
                ),
            ]),
            padding=ft.padding.symmetric(
                horizontal=COMPAT_SPACING["xl"], 
                vertical=COMPAT_SPACING["md"]
            ),
            bgcolor=COMPAT_COLORS["surface"],
            height=48,
            border=ft.border.only(
                top=ft.BorderSide(1, COMPAT_COLORS["outline"])
            ),
        )
        return self.status_bar
        
    def _get_current_page(self) -> ft.Control:
        """获取当前页面内容"""
        if self.current_page_index == 0:
            if not self.dashboard_page:
                self.dashboard_page = DashboardPage(self.system_adapter, app_state)
            return self.dashboard_page.build()
        elif self.current_page_index == 1:
            if not self.punch_page:
                self.punch_page = PunchPage(self.system_adapter, app_state)
            return self.punch_page.build()
        elif self.current_page_index == 2:
            if not self.tasks_page:
                self.tasks_page = TasksPage(self.system_adapter, app_state)
            return self.tasks_page.build()
        elif self.current_page_index == 3:
            if not self.settings_page:
                self.settings_page = SettingsPage(self.system_adapter, app_state, self.theme_manager)
            return self.settings_page.build()
        else:
            return ft.Text("页面未找到")
            
    async def _on_navigation_change(self, e):
        """处理导航变化"""
        self.current_page_index = e.control.selected_index
        
        # 更新主内容
        self.main_content.content = self._get_current_page()
        
        # 更新状态管理器
        page_names = ["dashboard", "punch", "tasks", "settings"]
        await app_state.navigate_to(page_names[self.current_page_index])
        
        self.page.update()
        
    async def _refresh_status(self, e):
        """刷新系统状态"""
        # 显示加载状态
        await app_state.set_loading(True, "刷新状态中...")
        
        try:
            # 获取最新状态
            status = self.system_adapter.get_status()
            
            # 更新状态栏
            await self._update_status_bar()
            
            # 通知页面更新
            if self.dashboard_page:
                await self.dashboard_page.refresh_data()
                
            await app_state.set_success("状态已刷新")
            
        except Exception as e:
            logger.error(f"Failed to refresh status: {e}")
            await app_state.set_error(f"刷新失败: {str(e)}")
        finally:
            await app_state.set_loading(False)
            
    async def _update_status_bar(self):
        """更新状态栏"""
        if not self.status_bar:
            return
            
        status = self.system_adapter.get_status()
        
        # 更新状态指示器
        status_color = COMPAT_COLORS["success"] if status.is_running else COMPAT_COLORS["error"]
        status_text = "运行中" if status.is_running else "已停止"
        
        self.status_bar.content.controls[0].color = status_color
        self.status_bar.content.controls[1].value = f"系统状态: {status_text}"
        self.status_bar.content.controls[3].value = f"最后更新: {status.last_punch_time or '无'}"
        
        self.page.update()
        
    def _on_window_resize(self, e):
        """处理窗口大小变化"""
        # 重新构建界面以适应新的窗口大小
        if hasattr(self, 'main_content') and self.main_content:
            # 重新计算导航栏高度
            min_height = 500
            appbar_height = 65
            statusbar_height = 40
            available_height = max(min_height, self.page.window_height - appbar_height - statusbar_height)
            
            # 更新导航栏容器高度
            nav_container = self.page.controls[0].content.content.controls[0]
            nav_container.height = available_height
            
            self.page.update()
        
    def build(self) -> ft.Column:
        """构建应用界面"""
        # 设置页面的AppBar
        self.page.appbar = self._create_app_bar()
        
        # 更健壮的高度计算，确保最小高度
        min_height = 500  # 最小高度
        appbar_height = 65  # AppBar高度
        statusbar_height = 40  # 状态栏高度
        available_height = max(min_height, self.page.window_height - appbar_height - statusbar_height)
        
        return ft.Column([
            # 主内容区域
            ft.Container(
                content=ft.Row([
                    # 左侧导航栏 - 现代化设计
                    ft.Container(
                        content=self._create_navigation_rail(),
                        width=120,
                        height=available_height,
                        alignment=ft.alignment.top_left,
                        border=ft.border.only(
                            right=ft.BorderSide(1, COMPAT_COLORS["outline"])
                        ),
                    ),
                    
                    # 主内容页面
                    self._create_main_content(),
                ]),
                expand=True,
            ),
            
            # 底部状态栏
            self._create_status_bar(),
        ], spacing=0)


async def main(page: ft.Page):
    """主函数"""
    try:
        # 创建应用实例
        app = AttendanceApp(page)
        
        # 构建界面
        page.add(app.build())
        
        # 初始刷新状态
        await app._refresh_status(None)
        
        logger.info("Flet GUI application started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        # 显示错误页面
        page.add(
            ft.Container(
                content=ft.Column([
                    ft.Icon(icons.ERROR, size=64, color=COMPAT_COLORS["error"]),
                    ft.Text("应用启动失败", size=24, weight=ft.FontWeight.BOLD),
                    ft.Text(f"错误信息: {str(e)}", size=14),
                    ft.ElevatedButton(
                        "重新启动",
                        on_click=lambda _: page.window.close()
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                alignment=ft.alignment.center,
                expand=True,
            )
        )


if __name__ == "__main__":
    # 启动Flet应用
    ft.app(target=main, assets_dir="assets")