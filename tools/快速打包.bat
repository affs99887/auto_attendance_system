@echo off
chcp 65001 >nul
title 自动打卡系统 - 快速打包工具

echo.
echo ================================================================
echo                自动打卡系统 - 快速打包工具
echo ================================================================
echo.
echo 🚀 这个工具将把自动打卡系统打包成Windows可执行文件
echo 📦 打包后的程序可以在任何Windows电脑上运行，无需安装Python
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误: 未找到Python
    echo 💡 请先安装Python 3.8或更高版本
    echo 📥 下载地址: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo ✅ Python环境检查通过
echo.

REM 切换到项目根目录
cd /d "%~dp0\.."

REM 检查虚拟环境
if not exist "venv" (
    echo 📦 创建Python虚拟环境...
    python -m venv venv
    if errorlevel 1 (
        echo ❌ 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo ✅ 虚拟环境创建成功
)

echo 🔄 激活虚拟环境...
call venv\Scripts\activate.bat

echo 📦 安装/更新依赖包...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ 安装依赖失败
    echo 💡 请检查网络连接或requirements.txt文件
    pause
    exit /b 1
)

echo ✅ 依赖安装完成
echo.
echo 🔨 开始打包过程...
echo ⏰ 这可能需要5-10分钟，请耐心等待...
echo.

python tools\pack_pyinstaller.py

echo.
echo 🎉 打包流程完成！
echo 📁 请查看 dist 目录中的文件
echo.
pause