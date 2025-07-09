#!/usr/bin/env python3
"""
Flet Web GUI 测试
在Web浏览器中运行的Flet测试
"""

import flet as ft

# 简单的颜色兼容性处理
try:
    colors = ft.colors
except AttributeError:
    class Colors:
        GREEN = "#4CAF50"
        BLUE = "#2196F3"
        RED = "#F44336"
    colors = Colors()

def main(page: ft.Page):
    """测试主函数"""
    page.title = "自动打卡系统 - Flet Web测试"
    page.theme_mode = ft.ThemeMode.SYSTEM
    
    def on_test_click(e):
        result_text.value = "✅ Flet Web版本运行正常！"
        result_text.color = colors.GREEN
        page.update()
    
    def on_theme_click(e):
        if page.theme_mode == ft.ThemeMode.LIGHT:
            page.theme_mode = ft.ThemeMode.DARK
            theme_button.text = "切换到浅色主题"
        else:
            page.theme_mode = ft.ThemeMode.LIGHT
            theme_button.text = "切换到深色主题"
        page.update()
    
    # 主要内容
    title = ft.Text(
        "自动打卡系统 - Flet现代化界面测试",
        size=28,
        weight=ft.FontWeight.BOLD,
        text_align=ft.TextAlign.CENTER
    )
    
    subtitle = ft.Text(
        "这是Flet框架的Web版本测试页面",
        size=16,
        color=colors.ON_SURFACE_VARIANT,
        text_align=ft.TextAlign.CENTER
    )
    
    test_button = ft.ElevatedButton(
        "测试功能",
        icon=ft.icons.PLAY_ARROW,
        on_click=on_test_click,
        style=ft.ButtonStyle(
            bgcolor=colors.PRIMARY,
            color=colors.ON_PRIMARY,
        )
    )
    
    theme_button = ft.OutlinedButton(
        "切换到深色主题",
        icon=ft.icons.BRIGHTNESS_6,
        on_click=on_theme_click
    )
    
    result_text = ft.Text(
        "点击上方按钮进行测试",
        size=14,
        text_align=ft.TextAlign.CENTER
    )
    
    # 功能演示卡片
    demo_card = ft.Card(
        content=ft.Container(
            content=ft.Column([
                ft.Text("功能演示", size=18, weight=ft.FontWeight.W_600),
                ft.Row([
                    ft.Icon(ft.icons.COMPUTER, color=colors.BLUE),
                    ft.Text("系统状态: 正常"),
                ]),
                ft.Row([
                    ft.Icon(ft.icons.SCHEDULE, color=colors.GREEN),
                    ft.Text("打卡状态: 未打卡"),
                ]),
                ft.Row([
                    ft.Icon(ft.icons.TASK_ALT, color=colors.ORANGE),
                    ft.Text("任务数量: 2个"),
                ]),
            ], spacing=10),
            padding=20,
        ),
        width=300,
    )
    
    # 页面布局
    page.add(
        ft.Container(
            content=ft.Column([
                title,
                subtitle,
                ft.Divider(height=20),
                ft.Row([
                    test_button,
                    theme_button,
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=20),
                ft.Divider(height=20),
                result_text,
                ft.Divider(height=30),
                demo_card,
                ft.Divider(height=20),
                ft.Text(
                    "如果您看到这个页面，说明Flet框架已成功安装并可以正常运行！",
                    size=12,
                    color=colors.ON_SURFACE_VARIANT,
                    text_align=ft.TextAlign.CENTER
                ),
            ], 
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10),
            padding=40,
            alignment=ft.alignment.center,
        )
    )

if __name__ == "__main__":
    print("启动Flet Web测试...")
    print("请在浏览器中访问显示的URL来查看界面")
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=8000)