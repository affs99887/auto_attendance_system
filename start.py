#!/usr/bin/env python3
"""
GUI 底座启动器
一键启动脚本，支持直接启动和看门狗模式
"""

import os
import sys
import argparse
import subprocess
import time
import logging


def configure_console_encoding():
    """保留当前终端编码，并替换无法编码的字符。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(errors="replace")
                continue
            except (TypeError, ValueError, OSError):
                pass

        buffer = getattr(stream, "buffer", None)
        if buffer is None:
            continue
        try:
            import io
            encoding = getattr(stream, "encoding", None) or "utf-8"
            setattr(sys, stream_name, io.TextIOWrapper(
                buffer,
                encoding=encoding,
                errors="replace",
                line_buffering=True
            ))
        except (TypeError, ValueError, OSError):
            pass


def python_subprocess_env():
    """子进程继承当前输出编码，并替换无法编码的字符。"""
    env = os.environ.copy()
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        env['PYTHONIOENCODING'] = f'{encoding}:replace'
    return env


def gui_subprocess_env():
    """GUI 后端使用朴素输出，避免 Electron 终端出现 ANSI/特殊字符。"""
    env = python_subprocess_env()
    env['AAS_PLAIN_CONSOLE'] = '1'
    return env


configure_console_encoding()

def setup_logging():
    """配置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def check_environment():
    """检查运行环境"""
    # 检查Python版本
    # 与 electron-builder.yml 声明的用户机器要求（Python 3.10+）保持一致
    if sys.version_info < (3, 10):
        print("错误: 需要Python 3.10或更高版本")
        return False
    
    # 检查必要文件
    required_files = ['main.py', 'watchdog.py', 'requirements.txt']
    for file in required_files:
        if not os.path.exists(file):
            print(f"错误: 缺少必要文件: {file}")
            return False
    
    return True

def start_main():
    """直接启动主程序"""
    try:
        print("正在启动 GUI 底座...")
        print("模式: 直接启动")
        print("按 Ctrl+C 可停止程序")
        print("-" * 50)
        
        # 启动主程序
        subprocess.run([sys.executable, 'main.py'], env=python_subprocess_env())
        
    except KeyboardInterrupt:
        print("\n程序已停止")
    except Exception as e:
        print(f"启动失败: {e}")
        return False
    
    return True

def start_watchdog():
    """启动看门狗模式"""
    try:
        print("正在启动 GUI 底座...")
        print("模式: 看门狗监控")
        print("看门狗将监控主程序运行状态并自动重启")
        print("按 Ctrl+C 可停止程序")
        print("-" * 50)

        # 启动看门狗
        subprocess.run([sys.executable, 'watchdog.py'], env=python_subprocess_env())

    except KeyboardInterrupt:
        print("\n程序已停止")
    except Exception as e:
        print(f"启动失败: {e}")
        return False

    return True

def start_gui():
    """启动 GUI 模式（main.py 附带 --gui 标志，无看门狗）。

    Electron 主进程会以同样的方式拉起 Python 后端；watchdog 与 GUI 互斥，
    崩溃重启由 Electron 接管。
    """
    try:
        print("正在启动 GUI 底座...")
        print("模式: GUI 后端")
        print("HTTP 监听 127.0.0.1:8765，WebSocket 监听 127.0.0.1:8766")
        print("token 文件: logs/.gui_token（仅当前用户可读）")
        print("按 Ctrl+C 可停止程序")
        print("-" * 50)

        subprocess.run([sys.executable, 'main.py', '--gui'], env=gui_subprocess_env())

    except KeyboardInterrupt:
        print("\n程序已停止")
    except Exception as e:
        print(f"启动失败: {e}")
        return False

    return True

def show_status():
    """显示当前运行状态"""
    import psutil
    
    print("=== 系统运行状态 ===")
    
    # 检查主程序进程
    main_running = False
    watchdog_running = False
    
    # [M89 补全] 进程归属判断与 watchdog.is_process_running 对齐：
    # 用 basename 命中 + 归一化绝对路径校验脚本属于本项目目录，避免把机器上任意
    # 含 'main.py'/'watchdog.py' 参数的无关 python 进程误报为本系统在运行。
    project_root = os.path.dirname(os.path.abspath(__file__))

    def _belongs_to_project(cmdline, script_name):
        """判断该进程的 cmdline 是否在运行本项目根目录下的指定脚本。

        - 仅 main.py 的 GUI 形态（--gui）放宽为按 basename 命中即认定，
          兼容打包态后端脚本位于不同绝对路径（resources\\backend\\main.py）的情形；
        - 其余一律按归一化绝对路径比对，确保归属本项目。
        """
        target = os.path.normcase(os.path.normpath(os.path.join(project_root, script_name)))
        if script_name == 'main.py' and '--gui' in cmdline:
            return any(arg and os.path.basename(arg).lower() == 'main.py' for arg in cmdline)
        for arg in cmdline:
            if not arg or os.path.basename(arg).lower() != script_name.lower():
                continue
            arg_path = os.path.normcase(os.path.normpath(
                os.path.join(project_root, arg) if not os.path.isabs(arg) else arg
            ))
            if arg_path == target:
                return True
        return False

    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            name = (proc.info['name'] or '').lower()
            # 仅看 python 解释器进程（兼容 Windows 的 python.exe）
            if not name.startswith('python'):
                continue
            cmdline = proc.info['cmdline'] or []
            if _belongs_to_project(cmdline, 'main.py'):
                main_running = True
                print(f"主程序正在运行 (PID: {proc.info['pid']})")
            elif _belongs_to_project(cmdline, 'watchdog.py'):
                watchdog_running = True
                print(f"看门狗正在运行 (PID: {proc.info['pid']})")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    
    if not main_running and not watchdog_running:
        print("未检测到正在运行的程序")
    
    # 显示系统资源
    memory = psutil.virtual_memory()
    cpu = psutil.cpu_percent()
    print(f"系统内存使用: {memory.percent:.1f}%")
    print(f"系统CPU使用: {cpu:.1f}%")

def interactive_mode():
    """交互模式"""
    print("=== GUI 底座启动器 ===")
    print("请选择启动模式:")
    print("1. 直接启动 (main.py)")
    print("2. 看门狗模式 (watchdog.py) [推荐]")
    print("3. 查看运行状态")
    print("4. GUI 模式 (Electron 后端，需另启 GUI)")
    print("5. 退出")

    while True:
        try:
            choice = input("\n请输入选择 (1-5): ").strip()

            if choice == '1':
                return start_main()
            elif choice == '2':
                return start_watchdog()
            elif choice == '3':
                show_status()
                continue
            elif choice == '4':
                return start_gui()
            elif choice == '5':
                print("退出启动器")
                return True
            else:
                print("无效选择，请输入1-5")
        except KeyboardInterrupt:
            print("\n退出启动器")
            return True

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='GUI 底座启动器')
    parser.add_argument('--mode', choices=['main', 'watchdog', 'status', 'gui'],
                       help='启动模式: main(直接启动), watchdog(看门狗模式), status(查看状态), gui(后端供 Electron 调用)')
    parser.add_argument('--interactive', action='store_true',
                       help='交互模式选择')

    args = parser.parse_args()

    # 设置日志
    setup_logging()

    # 检查环境
    if not check_environment():
        return 1

    # 根据参数选择启动模式
    if args.mode == 'main':
        success = start_main()
    elif args.mode == 'watchdog':
        success = start_watchdog()
    elif args.mode == 'gui':
        success = start_gui()
    elif args.mode == 'status':
        show_status()
        return 0
    elif args.interactive:
        success = interactive_mode()
    else:
        # 默认启动看门狗模式
        print("未指定启动模式，默认使用看门狗模式")
        print("使用 --help 查看更多选项")
        time.sleep(1)
        success = start_watchdog()

    return 0 if success else 1

if __name__ == "__main__":
    exit(main())
