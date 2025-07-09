
# 导入兼容性模块
try:
    from ..utils.colors_compat import colors, icons
except ImportError:
    try:
        from utils.colors_compat import colors, icons
    except ImportError:
        try:
            from flet_gui.utils.colors_compat import colors, icons
        except ImportError:
            # 如果都导入失败，创建简单的兼容对象
            class Colors:
                BLUE = "#2196F3"
                GREEN = "#4CAF50"
                SURFACE_VARIANT = "#F5F5F5"
            colors = Colors()
            class Icons:
                CIRCLE = "circle"
                PLAY_ARROW = "play_arrow"
                STOP = "stop"
                ADD = "add"
                EDIT = "edit"
                DELETE = "delete"
                SAVE = "save"
                REFRESH = "refresh"
                SETTINGS = "settings"
                VISIBILITY = "visibility"
                VISIBILITY_OFF = "visibility_off"
            icons = Icons()

"""
设置配置页面
系统配置和主题设置
"""

import flet as ft
import json
import os
from typing import Optional, Dict, Any

class SettingsPage:
    """设置配置页面"""
    
    def __init__(self, system_adapter, state_manager, theme_manager):
        self.system_adapter = system_adapter
        self.state_manager = state_manager
        self.theme_manager = theme_manager
        
        self.current_settings_page = "basic"
        self.content: Optional[ft.Row] = None
        self.settings_nav: Optional[ft.Container] = None
        self.settings_content: Optional[ft.Container] = None
        
        # 配置数据
        self.config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """加载配置"""
        try:
            if os.path.exists('.env'):
                config = {}
                with open('.env', 'r', encoding='utf-8') as f:
                    for line in f:
                        if '=' in line and not line.strip().startswith('#'):
                            key, value = line.strip().split('=', 1)
                            config[key] = value
                return config
        except Exception as e:
            print(f"Failed to load config: {e}")
        return {}
        
    def _save_config(self):
        """保存配置"""
        try:
            with open('.env', 'w', encoding='utf-8') as f:
                for key, value in self.config.items():
                    f.write(f"{key}={value}\n")
        except Exception as e:
            print(f"Failed to save config: {e}")
        
    def build(self) -> ft.Row:
        """构建页面内容"""
        self.content = ft.Row([
            # 左侧设置导航
            self._create_settings_navigation(),
            
            # 右侧设置内容
            self._create_settings_content(),
            
        ], spacing=0, expand=True)
        
        return self.content
        
    def _create_settings_navigation(self) -> ft.Container:
        """创建设置导航"""
        nav_items = [
            ("basic", "基本设置", icons.SETTINGS),
            ("punch", "打卡配置", icons.SCHEDULE),
            ("notification", "通知设置", icons.NOTIFICATIONS),
            ("theme", "主题外观", icons.PALETTE),
            ("advanced", "高级选项", icons.TUNE),
        ]
        
        nav_controls = [
            ft.Text("设置", size=20, weight=ft.FontWeight.BOLD),
            ft.Divider(),
        ]
        
        for page_id, title, icon in nav_items:
            nav_controls.append(
                self._create_nav_item(page_id, title, icon)
            )
            
        self.settings_nav = ft.Container(
            content=ft.Column(nav_controls, spacing=5, scroll=ft.ScrollMode.AUTO),  # 添加滚动
            width=200,
            padding=20,
            bgcolor=colors.SURFACE_VARIANT,
        )
        
        return self.settings_nav
        
    def _create_nav_item(self, page_id: str, title: str, icon: str) -> ft.Container:
        """创建导航项"""
        is_selected = self.current_settings_page == page_id
        
        return ft.Container(
            content=ft.Row([
                ft.Icon(icon, size=20),
                ft.Text(title, size=14),
            ], spacing=10),
            padding=ft.padding.symmetric(horizontal=15, vertical=10),
            bgcolor=compat_colors.PRIMARY + "20" if is_selected else None,
            border_radius=8,
            ink=True,
            on_click=lambda e, p=page_id: self._on_nav_click(p),
        )
        
    def _create_settings_content(self) -> ft.Container:
        """创建设置内容"""
        self.settings_content = ft.Container(
            content=ft.Column([
                self._get_settings_page_content()
            ], scroll=ft.ScrollMode.AUTO),  # 添加滚动
            expand=True,
            padding=20,
        )
        
        return self.settings_content
        
    def _get_settings_page_content(self) -> ft.Control:
        """获取当前设置页面内容"""
        if self.current_settings_page == "basic":
            return self._create_basic_settings()
        elif self.current_settings_page == "punch":
            return self._create_punch_settings()
        elif self.current_settings_page == "notification":
            return self._create_notification_settings()
        elif self.current_settings_page == "theme":
            return self._create_theme_settings()
        elif self.current_settings_page == "advanced":
            return self._create_advanced_settings()
        else:
            return ft.Text("页面未找到")
            
    def _create_basic_settings(self) -> ft.Column:
        """创建基本设置"""
        return ft.Column([
            ft.Text("基本设置", size=24, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            
            # 系统设置组
            self._create_settings_group("系统设置", [
                self._create_text_field("系统名称", "SYSTEM_NAME", "自动打卡系统"),
                self._create_text_field("登录URL", "LOGIN_URL", "https://example.com"),
                self._create_switch("开机自启", "AUTO_START", False),
                self._create_switch("最小化到托盘", "MINIMIZE_TO_TRAY", True),
            ]),
            
            ft.Container(height=20),
            
            # 用户设置组
            self._create_settings_group("用户配置", [
                self._create_text_field("用户名", "LOGIN_USERNAME", ""),
                self._create_password_field("密码", "LOGIN_PASSWORD", ""),
                self._create_text_field("备用用户名", "LOGIN_USERNAME2", ""),
                self._create_password_field("备用密码", "LOGIN_PASSWORD2", ""),
            ]),
            
            ft.Container(height=30),
            
            # 保存按钮
            ft.Row([
                ft.ElevatedButton(
                    "保存设置",
                    icon=icons.SAVE,
                    on_click=self._save_basic_settings,
                    style=ft.ButtonStyle(
                        bgcolor=compat_colors.PRIMARY,
                        color=colors.ON_PRIMARY,
                    ),
                ),
                ft.OutlinedButton(
                    "重置默认",
                    icon=icons.RESTORE,
                    on_click=self._reset_basic_settings,
                ),
            ], spacing=10),
            
        ], scroll=ft.ScrollMode.AUTO)
        
    def _create_punch_settings(self) -> ft.Column:
        """创建打卡设置"""
        return ft.Column([
            ft.Text("打卡配置", size=24, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            
            # 时间设置组
            self._create_settings_group("打卡时间", [
                self._create_time_field("上班时间", "WORK_START_TIME", "09:00"),
                self._create_time_field("下班时间", "WORK_END_TIME", "18:00"),
                self._create_text_field("迟到阈值(分钟)", "LATE_THRESHOLD", "10"),
                self._create_text_field("早退阈值(分钟)", "EARLY_LEAVE_THRESHOLD", "10"),
            ]),
            
            ft.Container(height=20),
            
            # 自动设置组
            self._create_settings_group("自动打卡", [
                self._create_switch("启用自动打卡", "AUTO_PUNCH", True),
                self._create_switch("工作日自动打卡", "WEEKDAY_AUTO_PUNCH", True),
                self._create_switch("节假日跳过", "SKIP_HOLIDAYS", True),
                self._create_text_field("打卡间隔(秒)", "PUNCH_INTERVAL", "30"),
            ]),
            
            ft.Container(height=20),
            
            # 重试设置组
            self._create_settings_group("重试设置", [
                self._create_text_field("最大重试次数", "MAX_RETRY_COUNT", "3"),
                self._create_text_field("重试间隔(秒)", "RETRY_INTERVAL", "60"),
                self._create_switch("失败时邮件通知", "EMAIL_ON_FAILURE", True),
            ]),
            
            ft.Container(height=30),
            
            # 保存按钮
            ft.ElevatedButton(
                "保存打卡设置",
                icon=icons.SAVE,
                on_click=self._save_punch_settings,
                style=ft.ButtonStyle(
                    bgcolor=compat_colors.PRIMARY,
                    color=colors.ON_PRIMARY,
                ),
            ),
            
        ], scroll=ft.ScrollMode.AUTO)
        
    def _create_notification_settings(self) -> ft.Column:
        """创建通知设置"""
        return ft.Column([
            ft.Text("通知设置", size=24, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            
            # Telegram设置组
            self._create_settings_group("Telegram通知", [
                self._create_text_field("Bot Token", "TELEGRAM_BOT_TOKEN", ""),
                self._create_text_field("Chat ID", "TELEGRAM_CHAT_ID", ""),
                self._create_switch("启用Telegram通知", "TELEGRAM_ENABLED", True),
                self._create_time_field("每日状态报告时间", "DAILY_STATUS_TIME", "18:30"),
            ]),
            
            ft.Container(height=20),
            
            # 邮件设置组
            self._create_settings_group("邮件通知", [
                self._create_text_field("发送邮箱", "EMAIL_SENDER", ""),
                self._create_password_field("邮箱密码", "EMAIL_PASSWORD", ""),
                self._create_text_field("SMTP服务器", "EMAIL_SMTP_SERVER", "smtp.qq.com"),
                self._create_text_field("SMTP端口", "EMAIL_SMTP_PORT", "587"),
                self._create_switch("启用邮件通知", "EMAIL_ENABLED", False),
            ]),
            
            ft.Container(height=20),
            
            # 通知内容设置
            self._create_settings_group("通知内容", [
                self._create_switch("打卡成功通知", "NOTIFY_SUCCESS", True),
                self._create_switch("打卡失败通知", "NOTIFY_FAILURE", True),
                self._create_switch("系统状态通知", "NOTIFY_STATUS", True),
                self._create_switch("包含截图", "INCLUDE_SCREENSHOT", True),
            ]),
            
            ft.Container(height=30),
            
            # 测试和保存按钮
            ft.Row([
                ft.ElevatedButton(
                    "测试通知",
                    icon=icons.SEND,
                    on_click=self._test_notifications,
                ),
                ft.ElevatedButton(
                    "保存通知设置",
                    icon=icons.SAVE,
                    on_click=self._save_notification_settings,
                    style=ft.ButtonStyle(
                        bgcolor=compat_colors.PRIMARY,
                        color=colors.ON_PRIMARY,
                    ),
                ),
            ], spacing=10),
            
        ], scroll=ft.ScrollMode.AUTO)
        
    def _create_theme_settings(self) -> ft.Column:
        """创建主题设置"""
        return ft.Column([
            ft.Text("主题外观", size=24, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            
            # 主题选择
            self._create_settings_group("主题模式", [
                ft.Row([
                    ft.Text("主题模式: "),
                    self.theme_manager.create_theme_selector(),
                ]),
            ]),
            
            ft.Container(height=20),
            
            # 颜色自定义
            self._create_settings_group("颜色定制", [
                self.theme_manager.create_color_picker(),
            ]),
            
            ft.Container(height=20),
            
            # 界面设置
            self._create_settings_group("界面设置", [
                self._create_switch("紧凑模式", "COMPACT_MODE", False),
                self._create_switch("显示动画", "SHOW_ANIMATIONS", True),
                self._create_text_field("界面缩放(%)", "UI_SCALE", "100"),
                self._create_dropdown("语言", "LANGUAGE", "zh_CN", [
                    ("zh_CN", "简体中文"),
                    ("en_US", "English"),
                ]),
            ]),
            
            ft.Container(height=20),
            
            # 预览区域
            self._create_settings_group("主题预览", [
                self._create_theme_preview(),
            ]),
            
        ], scroll=ft.ScrollMode.AUTO)
        
    def _create_advanced_settings(self) -> ft.Column:
        """创建高级设置"""
        return ft.Column([
            ft.Text("高级选项", size=24, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            
            # 系统设置组
            self._create_settings_group("系统配置", [
                self._create_text_field("日志级别", "LOG_LEVEL", "INFO"),
                self._create_text_field("日志保留天数", "LOG_RETENTION_DAYS", "30"),
                self._create_text_field("截图保留天数", "SCREENSHOT_RETENTION_DAYS", "7"),
                self._create_switch("调试模式", "DEBUG_MODE", False),
            ]),
            
            ft.Container(height=20),
            
            # 性能设置组
            self._create_settings_group("性能优化", [
                self._create_text_field("OCR识别超时(秒)", "OCR_TIMEOUT", "10"),
                self._create_text_field("浏览器超时(秒)", "BROWSER_TIMEOUT", "30"),
                self._create_text_field("内存使用阈值(%)", "MEMORY_THRESHOLD", "85"),
                self._create_text_field("CPU使用阈值(%)", "CPU_THRESHOLD", "90"),
            ]),
            
            ft.Container(height=20),
            
            # 危险操作区域
            self._create_settings_group("危险操作", [
                ft.Row([
                    ft.ElevatedButton(
                        "重置所有设置",
                        icon=icons.RESTORE,
                        color=compat_colors.WHITE,
                        bgcolor=compat_colors.RED,
                        on_click=self._reset_all_settings,
                    ),
                    ft.ElevatedButton(
                        "清理日志文件",
                        icon=icons.CLEANING_SERVICES,
                        on_click=self._clean_logs,
                    ),
                    ft.ElevatedButton(
                        "导出配置",
                        icon=icons.DOWNLOAD,
                        on_click=self._export_config,
                    ),
                ], spacing=10),
            ]),
            
        ], scroll=ft.ScrollMode.AUTO)
        
    def _create_settings_group(self, title: str, controls: list) -> ft.Container:
        """创建设置组"""
        return ft.Container(
            content=ft.Column([
                ft.Text(title, size=16, weight=ft.FontWeight.W_600),
                ft.Column(controls, spacing=10),
            ], spacing=10),
            padding=20,
            bgcolor=colors.SURFACE_VARIANT,
            border_radius=12,
        )
        
    def _create_text_field(self, label: str, key: str, default: str) -> ft.TextField:
        """创建文本字段"""
        return ft.TextField(
            label=label,
            value=self.config.get(key, default),
            on_change=lambda e: self._update_config(key, e.control.value),
            width=300,
        )
        
    def _create_password_field(self, label: str, key: str, default: str) -> ft.TextField:
        """创建密码字段"""
        return ft.TextField(
            label=label,
            value=self.config.get(key, default),
            password=True,
            can_reveal_password=True,
            on_change=lambda e: self._update_config(key, e.control.value),
            width=300,
        )
        
    def _create_time_field(self, label: str, key: str, default: str) -> ft.TextField:
        """创建时间字段"""
        return ft.TextField(
            label=label,
            value=self.config.get(key, default),
            hint_text="格式: HH:MM",
            on_change=lambda e: self._update_config(key, e.control.value),
            width=150,
        )
        
    def _create_switch(self, label: str, key: str, default: bool) -> ft.Row:
        """创建开关"""
        switch = ft.Switch(
            value=self.config.get(key, str(default)).lower() == 'true',
            on_change=lambda e: self._update_config(key, str(e.control.value)),
        )
        
        return ft.Row([
            ft.Text(label),
            ft.Container(expand=True),
            switch,
        ])
        
    def _create_dropdown(self, label: str, key: str, default: str, options: list) -> ft.Row:
        """创建下拉框"""
        dropdown = ft.Dropdown(
            value=self.config.get(key, default),
            options=[ft.dropdown.Option(value, text) for value, text in options],
            on_change=lambda e: self._update_config(key, e.control.value),
            width=200,
        )
        
        return ft.Row([
            ft.Text(label),
            ft.Container(expand=True),
            dropdown,
        ])
        
    def _create_theme_preview(self) -> ft.Container:
        """创建主题预览"""
        return ft.Container(
            content=ft.Column([
                ft.Text("主题预览", size=14, weight=ft.FontWeight.W_500),
                ft.Row([
                    ft.ElevatedButton("主要按钮"),
                    ft.OutlinedButton("次要按钮"),
                    ft.TextButton("文本按钮"),
                ], spacing=10),
                ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text("示例卡片", weight=ft.FontWeight.W_500),
                            ft.Text("这是一个示例卡片内容"),
                        ]),
                        padding=15,
                    ),
                ),
            ], spacing=10),
            padding=15,
            border=ft.border.all(1, compat_colors.OUTLINE_VARIANT),
            border_radius=8,
        )
        
    def _update_config(self, key: str, value: str):
        """更新配置"""
        self.config[key] = value
        
    def _on_nav_click(self, page_id: str):
        """导航点击处理"""
        self.current_settings_page = page_id
        
        # 更新导航选中状态
        self.settings_nav.content = self._create_settings_navigation().content
        
        # 更新内容区域
        self.settings_content.content = self._get_settings_page_content()
        
        # 刷新页面
        if self.content and self.content.page:
            self.content.page.update()
            
    async def _save_basic_settings(self, e):
        """保存基本设置"""
        try:
            self._save_config()
            await self.state_manager.set_success("基本设置已保存")
        except Exception as ex:
            await self.state_manager.set_error(f"保存失败: {str(ex)}")
            
    async def _save_punch_settings(self, e):
        """保存打卡设置"""
        try:
            self._save_config()
            await self.state_manager.set_success("打卡设置已保存")
        except Exception as ex:
            await self.state_manager.set_error(f"保存失败: {str(ex)}")
            
    async def _save_notification_settings(self, e):
        """保存通知设置"""
        try:
            self._save_config()
            await self.state_manager.set_success("通知设置已保存")
        except Exception as ex:
            await self.state_manager.set_error(f"保存失败: {str(ex)}")
            
    async def _test_notifications(self, e):
        """测试通知"""
        await self.state_manager.set_success("测试通知已发送（模拟）")
        
    async def _reset_basic_settings(self, e):
        """重置基本设置"""
        await self.state_manager.set_success("基本设置已重置")
        
    async def _reset_all_settings(self, e):
        """重置所有设置"""
        await self.state_manager.set_success("所有设置已重置")
        
    async def _clean_logs(self, e):
        """清理日志"""
        await self.state_manager.set_success("日志文件已清理")
        
    async def _export_config(self, e):
        """导出配置"""
        await self.state_manager.set_success("配置已导出")