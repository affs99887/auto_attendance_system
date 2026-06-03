@echo off
REM 一键 PyInstaller 打包脚本
REM 输出: dist\main\main.exe + 所有依赖
REM
REM 使用前确认:
REM   1. 当前 Python 解释器装了项目所有依赖 (pip install -r requirements.txt)
REM   2. 装了 pyinstaller (pip install pyinstaller)
REM
REM 集成 Electron:
REM   生成 dist\main\ 后，把 electron-builder.yml 的 extraResources
REM   改为指向 dist\main\，并把 main.cjs 的 spawnPython 改为
REM   spawn(path.join(resources, 'backend', 'main.exe'))

setlocal
cd /d "%~dp0"

echo === Cleaning previous build ===
if exist build rmdir /S /Q build
if exist dist\main rmdir /S /Q dist\main

echo === Running PyInstaller ===
pyinstaller main.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [FAIL] PyInstaller failed
    exit /b 1
)

echo.
echo === Success ===
echo Output: %CD%\dist\main\main.exe
echo Size:
dir dist\main | findstr "File(s)"
echo.
echo Next: 双击 dist\main\main.exe 验证能跑起来 (会走 watchdog 模式)
echo 或者运行: dist\main\main.exe --gui  ^(GUI 模式^)

endlocal
