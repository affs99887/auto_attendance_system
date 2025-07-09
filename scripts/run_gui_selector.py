#!/usr/bin/env python3
"""
GUI选择器启动脚本
让用户选择使用Tkinter还是Flet界面
"""

import sys
import os
import subprocess

def print_banner():
    """显示横幅"""
    print("=" * 60)
    print("       自动打卡系统 - GUI界面选择器")
    print("=" * 60)
    print()

def print_options():
    """显示选项"""
    print("请选择要启动的GUI界面:")
    print()
    print("1. Flet现代化界面 (推荐)")
    print("   - 基于Flutter引擎")
    print("   - Material Design 3设计")
    print("   - 流畅动画和现代化体验")
    print("   - 支持Web版本")
    print()
    print("2. Tkinter经典界面")
    print("   - 传统桌面界面")
    print("   - 稳定可靠")
    print("   - 资源占用较少")
    print()
    print("3. Web版本 (Flet)")
    print("   - 在浏览器中运行")
    print("   - 跨平台访问")
    print("   - 移动设备友好")
    print()
    print("4. 退出")
    print()

def get_user_choice():
    """获取用户选择"""
    while True:
        try:
            choice = input("请输入选项编号 (1-4): ").strip()
            if choice in ['1', '2', '3', '4']:
                return int(choice)
            else:
                print("请输入有效的选项编号 (1-4)")
        except (ValueError, KeyboardInterrupt):
            print("\n用户取消操作")
            return 4

def check_environment():
    """检查环境"""
    if not os.path.exists('venv'):
        print("❌ 未找到虚拟环境，请先运行: python -m venv venv")
        return False
    
    if not os.path.exists('requirements.txt'):
        print("❌ 未找到requirements.txt文件")
        return False
    
    return True

def run_flet_gui():
    """运行Flet GUI"""
    print("🚀 启动Flet现代化界面...")
    print("📱 如果您是首次使用，请查看 FLET_GUI_README.md 了解详细功能")
    print()
    
    try:
        # 在Windows上使用不同的激活命令
        if os.name == 'nt':
            cmd = ['venv\\Scripts\\python.exe', 'run_flet_gui.py']
        else:
            cmd = ['bash', '-c', 'source venv/bin/activate && python run_flet_gui.py']
        
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ 启动失败: {e}")
        print("💡 提示: 请确保已安装所有依赖: pip install -r requirements.txt")
    except FileNotFoundError:
        print("❌ 未找到启动文件 run_flet_gui.py")

def run_tkinter_gui():
    """运行Tkinter GUI"""
    print("🚀 启动Tkinter经典界面...")
    
    try:
        # 在Windows上使用不同的激活命令
        if os.name == 'nt':
            cmd = ['venv\\Scripts\\python.exe', 'run_gui.py']
        else:
            cmd = ['bash', '-c', 'source venv/bin/activate && python run_gui.py']
        
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ 启动失败: {e}")
    except FileNotFoundError:
        print("❌ 未找到启动文件 run_gui.py")

def run_web_gui():
    """运行Web版GUI"""
    print("🌐 启动Web版本界面...")
    print("📖 浏览器将自动打开，或手动访问 http://localhost:8000")
    print()
    
    try:
        # 在Windows上使用不同的激活命令
        if os.name == 'nt':
            cmd = ['venv\\Scripts\\python.exe', 'flet_web_test.py']
        else:
            cmd = ['bash', '-c', 'source venv/bin/activate && python flet_web_test.py']
        
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ 启动失败: {e}")
    except FileNotFoundError:
        print("❌ 未找到启动文件 flet_web_test.py")

def main():
    """主函数"""
    print_banner()
    
    # 检查环境
    if not check_environment():
        print("🔧 请先设置好开发环境")
        return
    
    while True:
        print_options()
        choice = get_user_choice()
        
        if choice == 1:
            run_flet_gui()
            break
        elif choice == 2:
            run_tkinter_gui()
            break
        elif choice == 3:
            run_web_gui()
            break
        elif choice == 4:
            print("👋 再见！")
            break
        
        print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    main()