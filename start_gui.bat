@echo off
REM 启动自动打卡系统GUI客户端 (无命令行窗口)
REM 使用pythonw.exe避免显示命令行窗口

cd /d "%~dp0"
pythonw.exe run_gui.pyw