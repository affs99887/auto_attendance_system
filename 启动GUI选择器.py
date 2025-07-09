#!/usr/bin/env python3
"""
GUI启动器 - 根目录快捷启动脚本
"""

import sys
import os

# 添加scripts目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

# 导入并运行GUI选择器
from run_gui_selector import main

if __name__ == "__main__":
    main()