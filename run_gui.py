#!/usr/bin/env python3
"""
GUI客户端启动脚本
用于启动桌面GUI客户端
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
            sys.exit(1)
        
        # 启动GUI应用
        from gui_client.main_gui import main as gui_main
        gui_main()
        
    except KeyboardInterrupt:
        print("\n用户中断程序")
        sys.exit(0)
    except Exception as e:
        print(f"启动GUI客户端失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

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
    
    if missing_modules:
        print("缺少必要的依赖模块:")
        for module in missing_modules:
            print(f"  - {module}")
        print("\n请先安装缺少的依赖，然后再运行程序")
        return False
    
    return True

if __name__ == "__main__":
    main()