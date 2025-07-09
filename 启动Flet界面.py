#!/usr/bin/env python3
"""
Flet GUI启动器 - 根目录快捷启动脚本
"""

import sys
import os

# 添加scripts目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

# 导入并运行Flet GUI
try:
    import subprocess
    
    # 使用subprocess运行以避免路径问题
    script_path = os.path.join(os.path.dirname(__file__), 'scripts', 'run_flet_gui.py')
    subprocess.run([sys.executable, script_path])
    
except Exception as e:
    print(f"启动失败: {e}")
    input("按回车键退出...")