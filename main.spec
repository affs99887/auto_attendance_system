# PyInstaller spec — 打包 main.py 为 dist/main/main.exe
#
# 用法：
#   pyinstaller main.spec --clean --noconfirm
#
# 输出：dist/main/  (含 main.exe + 所有依赖)
#
# 集成 Electron：把 dist/main/ 作为 electron-builder.yml extraResources
# 替换源码 extraResources，main.cjs 改 spawn(resources/backend/main.exe)

# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

# 项目根（spec 文件所在目录）
ROOT = os.getcwd()

# 动态/隐藏依赖：很多库 PyInstaller 静态分析抓不到
hiddenimports = [
    'chinese_calendar',
    'schedule',
    'websockets',
    'websockets.legacy',
    'websockets.legacy.server',
    'flask',
    'waitress',
    'selenium',
    'selenium.webdriver',
    'selenium.webdriver.edge',
    'selenium.webdriver.edge.service',
    'selenium.webdriver.edge.options',
    'webdriver_manager',
    'webdriver_manager.microsoft',
    'colorama',
    'psutil',
    'win32api',
    'win32con',
    'win32gui',
    'pyautogui',
    'pytesseract',
    'cv2',
    'PIL',
    'PIL.Image',
    'numpy',
    'dotenv',
    'telegram',
    'telegram.ext',
    'pyperclip',
    'requests',
]

# 资源文件：templates 目录的 PNG 模板，运行时图像匹配用
datas = [
    ('templates', 'templates'),  # 整个 templates/ 目录复制进去
    ('.env.example', '.') if os.path.exists('.env.example') else None,
]
datas = [d for d in datas if d is not None]

a = Analysis(
    ['main.py'],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',  # 不用
        'matplotlib',
        'pytest',
        'sphinx',
        'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # 别 UPX 压缩，避免误报病毒
    console=True,        # 保留控制台，main.py 有 ANSI 欢迎界面 + 日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='main',
)
