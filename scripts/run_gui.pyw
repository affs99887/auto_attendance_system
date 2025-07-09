#!/usr/bin/env python3
"""
GUI客户端启动脚本 (无命令行窗口版本)
用于启动桌面GUI客户端，不显示命令行窗口
"""

import sys
import os

# 添加当前目录到Python路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

def main():
    """主函数"""
    try:
        # 检查必要的依赖
        if not check_dependencies():
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()  # 隐藏主窗口
            messagebox.showerror("依赖错误", "缺少必要的依赖模块，请先安装")
            return
        
        # 启动GUI应用
        from gui_client.main_gui import AttendanceGUIApp
        app = AttendanceGUIApp()
        app.run()
        
    except KeyboardInterrupt:
        pass
    except Exception as e:
        # 在出错时显示错误对话框而不是打印到控制台
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()  # 隐藏主窗口
        messagebox.showerror("启动错误", f"启动GUI客户端失败: {str(e)}")

def check_dependencies():
    """检查必要的依赖"""
    missing_modules = []
    
    # 检查tkinter (可能的名称变体)
    tkinter_available = False
    for tkinter_name in ['tkinter', 'Tkinter']:
        try:
            __import__(tkinter_name)
            tkinter_available = True
            break
        except ImportError:
            continue
    
    if not tkinter_available:
        missing_modules.append('tkinter')
    
    # 检查其他必要模块
    other_modules = {
        'PIL': 'Pillow',
        'psutil': 'psutil', 
        'chinese_calendar': 'chinese-calendar',
        'dotenv': 'python-dotenv'
    }
    
    for module, package in other_modules.items():
        try:
            __import__(module)
        except ImportError:
            missing_modules.append(f"{module} (install: pip install {package})")
    
    return len(missing_modules) == 0

if __name__ == "__main__":
    main()