#!/usr/bin/env python3
"""
PyInstaller打包脚本
将Flet应用打包成Windows可执行文件
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path

def install_pyinstaller():
    """安装PyInstaller"""
    try:
        import PyInstaller
        print("✅ PyInstaller已安装")
        return True
    except ImportError:
        print("📦 安装PyInstaller...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'pyinstaller'], check=True)
            print("✅ PyInstaller安装成功")
            return True
        except subprocess.CalledProcessError:
            print("❌ PyInstaller安装失败")
            return False

def create_main_entry():
    """创建主入口文件"""
    entry_content = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
自动打卡系统 - Flet GUI版本
主入口文件
'''

import sys
import os
import logging

# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.join(current_dir, 'flet_gui'))

def setup_logging():
    '''设置日志'''
    # 获取当前执行目录
    if getattr(sys, 'frozen', False):
        # 如果是打包后的应用
        app_dir = os.path.dirname(sys.executable)
    else:
        # 如果是开发环境
        app_dir = current_dir
    
    log_dir = os.path.join(app_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, 'app.log')
    
    try:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        return log_file
    except Exception as e:
        # 如果日志文件创建失败，至少保留控制台输出
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        print(f"警告: 日志文件创建失败，仅使用控制台输出: {e}")
        return None

def main():
    '''主函数'''
    try:
        log_file = setup_logging()
        if log_file:
            print(f"日志文件: {log_file}")
        
        # 导入Flet应用
        try:
            from flet_gui.main import main as flet_main
        except ImportError:
            # 后备方案：直接从main导入
            from main import main as flet_main
        
        import flet as ft
        
        # 启动应用
        ft.app(target=flet_main, assets_dir="flet_gui/assets")
        
    except ImportError as e:
        print(f"导入错误: {e}")
        print("请确保所有依赖都已正确安装")
        input("按回车键退出...")
    except Exception as e:
        print(f"启动失败: {e}")
        logging.exception("应用启动失败")
        input("按回车键退出...")

if __name__ == "__main__":
    main()
"""
    
    with open('app_main.py', 'w', encoding='utf-8') as f:
        f.write(entry_content)
    
    print("📄 创建主入口文件: app_main.py")
    return True

def create_spec_file():
    """创建PyInstaller spec文件"""
    spec_content = """# -*- mode: python ; coding: utf-8 -*-
# 自动打卡系统 PyInstaller 配置文件

block_cipher = None

# 分析主脚本
a = Analysis(
    ['app_main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('flet_gui', 'flet_gui'),
        ('.env', '.'),
        ('templates', 'templates'),
        ('core', 'core'),
    ],
    hiddenimports=[
        'flet',
        'flet.fastapi', 
        'uvicorn',
        'PIL',
        'PIL.Image',
        'cv2',
        'pytesseract',
        'psutil',
        'schedule',
        'requests',
        'python_telegram_bot',
        'chinese_calendar',
        'pystray',
        'asyncio',
        'concurrent.futures',
        'multiprocessing',
        'threading',
        'json',
        'datetime',
        'pathlib',
        'logging',
        'dotenv',
        'flet_gui',
        'flet_gui.adapters',
        'flet_gui.adapters.system_adapter',
        'flet_gui.utils',
        'flet_gui.utils.state_manager',
        'flet_gui.utils.theme_manager',
        'flet_gui.pages',
        'flet_gui.pages.dashboard',
        'flet_gui.pages.punch_page',
        'flet_gui.pages.tasks_page',
        'flet_gui.pages.settings_page',
        'flet_gui.components',
        'flet_gui.components.status_card',
        'flet_gui.components.action_button',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy.testing',
        'scipy',
        'pandas',
        'jupyter',
        'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 创建PYZ归档
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 创建可执行文件
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='自动打卡系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 隐藏控制台窗口
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt'
)
"""
    
    with open('app.spec', 'w', encoding='utf-8') as f:
        f.write(spec_content)
    
    print("📄 创建spec文件: app.spec")
    return True

def create_version_info():
    """创建版本信息文件"""
    version_content = """# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
# filevers and prodvers should be always a tuple with four items: (1, 2, 3, 4)
# Set not needed items to zero 0.
filevers=(2,0,0,0),
prodvers=(2,0,0,0),
# Contains a bitmask that specifies the valid bits 'flags'r
mask=0x3f,
# Contains a bitmask that specifies the Boolean attributes of the file.
flags=0x0,
# The operating system for which this file was designed.
# 0x4 - NT and there is no need to change it.
OS=0x4,
# The general type of file.
# 0x1 - the file is an application.
fileType=0x1,
# The function of the file.
# 0x0 - the function is not defined for this fileType
subtype=0x0,
# Creation date and time stamp.
date=(0, 0)
),
  kids=[
StringFileInfo(
  [
  StringTable(
    u'080404B0',
    [StringStruct(u'CompanyName', u'Auto Attendance Team'),
    StringStruct(u'FileDescription', u'自动打卡系统 - 现代化界面版本'),
    StringStruct(u'FileVersion', u'2.0.0.0'),
    StringStruct(u'InternalName', u'AutoAttendance'),
    StringStruct(u'LegalCopyright', u'Copyright © 2025 Auto Attendance Team'),
    StringStruct(u'OriginalFilename', u'自动打卡系统.exe'),
    StringStruct(u'ProductName', u'自动打卡系统'),
    StringStruct(u'ProductVersion', u'2.0.0.0')])
  ]), 
VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
"""
    
    with open('version_info.txt', 'w', encoding='utf-8') as f:
        f.write(version_content)
    
    print("📄 创建版本信息文件: version_info.txt")
    return True

def clean_build():
    """清理构建文件"""
    dirs_to_clean = ['build', 'dist', '__pycache__']
    files_to_clean = ['app_main.py', 'app.spec', 'version_info.txt']
    
    print("🧹 清理旧的构建文件...")
    
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name)
    
    for file_name in files_to_clean:
        if os.path.exists(file_name):
            os.remove(file_name)

def build_executable():
    """构建可执行文件"""
    try:
        print("🔨 开始构建可执行文件...")
        print("这可能需要几分钟时间，请耐心等待...")
        
        # 运行PyInstaller
        cmd = [sys.executable, '-m', 'PyInstaller', 'app.spec', '--clean']
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ 构建成功！")
            return True
        else:
            print(f"❌ 构建失败:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ 构建过程出错: {e}")
        return False

def show_results():
    """显示构建结果"""
    dist_path = Path('dist')
    
    if not dist_path.exists():
        print("❌ 未找到输出目录")
        return
    
    exe_files = list(dist_path.glob('*.exe'))
    
    if not exe_files:
        print("❌ 未找到生成的exe文件")
        return
    
    print("\n" + "=" * 60)
    print("🎉 打包完成！")
    print("=" * 60)
    
    for exe_file in exe_files:
        size_mb = exe_file.stat().st_size / (1024 * 1024)
        print(f"🚀 可执行文件: {exe_file.name} ({size_mb:.1f} MB)")
        print(f"📁 位置: {exe_file.absolute()}")
    
    # 复制必要文件
    print("\n📋 复制配置文件...")
    files_to_copy = ['.env', 'templates', 'FLET_GUI_README.md', 'README.md']
    
    for item in files_to_copy:
        if os.path.exists(item):
            try:
                if os.path.isdir(item):
                    shutil.copytree(item, dist_path / item, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dist_path / item)
                print(f"✅ 复制: {item}")
            except Exception as e:
                print(f"⚠️  复制失败 {item}: {e}")
    
    # 创建启动脚本
    batch_content = """@echo off
chcp 65001 >nul
title 自动打卡系统

echo 正在启动自动打卡系统...
echo.

REM 检查配置文件
if not exist ".env" (
    echo [提示] 首次运行，请先配置 .env 文件
    echo [提示] 您可以参考 .env.example 文件
    echo.
    if exist ".env.example" (
        copy ".env.example" ".env"
        echo 已创建默认配置文件，请编辑 .env 文件
    )
    pause
    exit /b
)

REM 启动应用
"自动打卡系统.exe"

REM 如果程序异常退出，显示错误信息
if errorlevel 1 (
    echo.
    echo [错误] 程序异常退出
    echo [提示] 请检查配置文件或查看日志文件
    pause
)
"""
    
    try:
        with open(dist_path / '启动.bat', 'w', encoding='gbk') as f:
            f.write(batch_content)
        print("✅ 创建启动脚本: 启动.bat")
    except Exception as e:
        print(f"⚠️  创建启动脚本失败: {e}")
    
    print("\n💡 使用说明:")
    print("1. 双击 '自动打卡系统.exe' 或 '启动.bat' 运行程序")
    print("2. 首次运行时请配置 .env 文件")
    print("3. 可以将整个 dist 目录复制到其他Windows电脑上运行")
    print("4. 程序运行日志保存在 logs 目录中")

def main():
    """主函数"""
    print("🚀 自动打卡系统 - PyInstaller打包工具")
    print("=" * 50)
    
    # 检查环境
    if not install_pyinstaller():
        return False
    
    # 清理旧文件
    clean_build()
    
    # 创建必要文件
    if not create_main_entry():
        return False
    
    if not create_spec_file():
        return False
    
    if not create_version_info():
        return False
    
    # 构建
    if not build_executable():
        return False
    
    # 显示结果
    show_results()
    
    # 清理临时文件
    temp_files = ['app_main.py', 'version_info.txt']
    for file_name in temp_files:
        if os.path.exists(file_name):
            os.remove(file_name)
    
    return True

if __name__ == '__main__':
    try:
        success = main()
        if success:
            print("\n🎉 打包完成！")
        else:
            print("\n❌ 打包失败！")
    except KeyboardInterrupt:
        print("\n⚠️  用户取消操作")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
    
    # 在Windows环境下暂停
    if os.name == 'nt':
        try:
            input("\n按回车键退出...")
        except:
            pass