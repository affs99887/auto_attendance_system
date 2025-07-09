#!/usr/bin/env python3
"""
Flet GUI 启动脚本
启动现代化的自动打卡系统界面
"""

import sys
import os
import logging

# 添加项目根目录和flet_gui目录到Python路径
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'flet_gui'))

try:
    # 导入并运行Flet应用
    import flet as ft
    
    # 直接从flet_gui目录导入
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'flet_gui'))
    from main import main
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/flet_gui.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    print("正在启动Flet GUI...")
    print("这是自动打卡系统的现代化界面")
    print("如果遇到问题，请检查logs/flet_gui.log文件")
    
    # 启动应用
    ft.app(target=main, assets_dir="flet_gui/assets")
    
except ImportError as e:
    print(f"导入错误: {e}")
    print("请确保已安装所有依赖: pip install flet")
    sys.exit(1)
except Exception as e:
    print(f"启动失败: {e}")
    logging.error(f"Failed to start Flet GUI: {e}")
    sys.exit(1)