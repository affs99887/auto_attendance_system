# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an automated attendance system (自动打卡系统) that uses computer vision and OCR to automatically log into a timecard system and punch in/out. The system integrates with Telegram for remote control and monitoring.

## GUI主导迁移计划

### Overview
本项目正在逐步从CLI模式过渡到GUI为主要使用界面，以提供更好的用户体验和可视化管理功能。

### 迁移阶段

#### 阶段1：GUI功能完善 (立即执行)
**目标**: 确保GUI具备完整的系统管理功能
- **完善GUI配置管理**: 添加完整的环境变量配置界面，支持所有.env参数的图形化编辑
- **增强任务管理**: 在GUI中添加定时任务的可视化管理，包括任务创建、编辑、删除和状态监控
- **优化启动流程**: 简化GUI启动过程，确保系统稳定性和自动恢复能力
- **完善状态监控**: 扩展实时状态面板，显示更多系统健康指标

#### 阶段2：CLI功能迁移 (短期)
**目标**: 将CLI独有功能完全迁移到GUI界面
- **独立CLI组件识别**: 分析main.py和watchdog.py中GUI尚未覆盖的功能点
- **统一配置系统**: 确保GUI和CLI使用相同的配置源和存储格式
- **保留CLI兼容性**: 作为备用方案保留关键CLI功能，但不再是主要使用方式
- **功能对等验证**: 确保GUI版本涵盖所有CLI核心功能

#### 阶段3：用户引导过渡 (中期)
**目标**: 引导用户从CLI过渡到GUI使用
- **更新启动脚本**: 将默认启动方式指向GUI版本(`run_gui.py`)
- **添加迁移提示**: 在CLI启动时提示用户优先使用GUI界面
- **创建便捷启动**: 添加桌面快捷方式、开始菜单项等便民功能
- **用户文档更新**: 重写使用指南以GUI操作为主要说明

#### 阶段4：CLI弃用准备 (长期)
**目标**: 为最终弃用CLI做准备
- **依赖关系整理**: 清理CLI专用代码和不必要的依赖项
- **文档全面更新**: 更新所有技术文档以GUI为主要操作界面
- **测试验证**: 全面测试确保GUI版本的稳定性和功能完整性
- **遗留代码清理**: 移除过时的CLI相关代码和配置

### 优先级定义
- **High Priority**: 阶段1 (GUI功能完善) - 立即开始执行
- **Medium Priority**: 阶段2 (CLI功能迁移) - 阶段1完成后启动
- **Low Priority**: 阶段3-4 (逐步过渡和弃用) - 长期规划

### 预期结果
- **主要界面**: GUI成为默认和推荐的使用方式
- **备用方案**: CLI作为备用/调试工具保留核心功能
- **用户体验**: 显著提升易用性和可视化管理能力
- **维护成本**: 减少双重维护的复杂性，专注GUI开发

### 当前状态
✅ **已完成**: 集成看门狗系统、状态管理、系统托盘集成  
🔄 **进行中**: GUI功能完善阶段  
⏳ **待开始**: CLI功能迁移和用户引导

## Architecture

The system consists of several key components:

### Core Python Components
- **main.py** - Main application with TelegramBot class and AttendanceSystem class
- **tasks.py** - TaskManager class for scheduling and managing timed tasks
- **punch_records.py** - PunchRecordManager class for tracking attendance records
- **watchdog.py** - Process monitor that restarts main.py if it crashes

### Refactored Modules (2025-06-24)
- **email_service.py** - EmailService class for email notifications with retry mechanism
- **browser_automation.py** - BrowserController class for browser automation and window control
- **image_recognition.py** - ImageRecognizer class for OCR and template matching

### Desktop GUI Client
- **gui_client/** - Tkinter-based desktop application providing complete graphical interface
- **gui_client/main_gui.py** - Main GUI application with system tray integration and integrated watchdog
- **gui_client/integrated_watchdog.py** - 集成到GUI中的看门狗类，自动启动和监控
- **gui_client/widgets/** - GUI components (MainWindow, StatusPanel, PunchPanel, TaskPanel, LogPanel, ConfigPanel)
- **gui_client/utils/** - GUI utilities for window management and icons
- **gui_watchdog.py** - 独立的GUI看门狗进程（现已集成到GUI中）
- **run_gui_with_watchdog.py** - 带独立看门狗保护的GUI启动脚本

### Key Technologies
- **Computer Vision**: OpenCV, PyAutoGUI, Tesseract OCR for screen automation
- **Telegram Bot**: python-telegram-bot for remote control
- **Scheduling**: schedule library with chinese-calendar for workday detection
- **Desktop GUI**: Tkinter with pystray for system tray integration

## Common Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/WSL
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Running the System
```bash
# Activate virtual environment first
source venv/bin/activate

# Run main attendance system (CLI mode)
python main.py

# Run with watchdog (recommended for production)
python watchdog.py

# Run desktop GUI application (now includes integrated watchdog)
python run_gui.py

# Run GUI with external watchdog protection (legacy)
python run_gui_with_watchdog.py

# Run GUI in background (Windows)
python run_gui.pyw
```

### Development
```bash
# Activate virtual environment first
source venv/bin/activate
```

## Configuration

### Environment Variables (.env)
- LOGIN_USERNAME, LOGIN_PASSWORD, LOGIN_URL - Login credentials
- LOGIN_USERNAME2, LOGIN_PASSWORD2 - Second user credentials (multi-user support)
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID - Telegram bot configuration
- TESSERACT_PATH - Path to Tesseract OCR executable
- WORK_START_TIME, WORK_END_TIME - Punch in/out times
- LATE_THRESHOLD, EARLY_LEAVE_THRESHOLD - Threshold settings for alerts
- DAILY_STATUS_TIME - Time for daily status reports
- EMAIL_SENDER, EMAIL_PASSWORD - Email notification credentials
- EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT - SMTP server configuration

### Template Images
The system uses template matching with images in `templates/` directory:
- username_field.png, password_field.png - Login form elements
- login_button.png, punch_button.png - Action buttons
- alert.png, continue.png - System dialogs

## Multi-User Support

The system supports multiple users with separate:
- Punch records stored in `punch_records/{username}/`
- Screenshots stored in `screenshots/{username}/`
- User-specific settings in settings.json

## Data Storage

- **punch_records/** - JSON files with monthly attendance data
- **scheduled_tasks.json** - Pending scheduled tasks
- **settings.json** - User preferences and configuration
- **logs/** - Rotating log files for system monitoring

## Key Features

- Image recognition-based UI automation
- Telegram bot for remote control (/punch_in, /punch_out, /status, /log)
- Automatic retry mechanisms for network issues
- Email notifications with screenshots
- Workday detection using Chinese calendar
- Task scheduling and management
- Process monitoring and auto-restart

## System Operation Modes

### CLI Mode (main.py)
- Full system with Telegram bot integration
- Runs in background with console logging
- Suitable for server deployments

### GUI Mode (run_gui.py)
- Desktop application with graphical interface
- System tray integration for background operation
- Real-time monitoring and manual controls
- Configuration management interface

### Watchdog Mode (watchdog.py)
- Process monitoring and automatic restart
- Resource usage monitoring with alerts
- Standalone operation with configurable restart limits

## Key Integration Points

### Data Flow Architecture
1. **Punch Operation**: BrowserController → ImageRecognizer → BrowserController → PunchRecordManager → EmailService → TelegramBot
2. **Task Scheduling**: TaskManager → AttendanceSystem → (punch operation flow)
3. **GUI Updates**: AttendanceSystem → MainWindow → GUI Components (real-time status)

### Module Dependencies
- **AttendanceSystem**: Core orchestrator using all service modules
- **TelegramBot**: Remote control interface with comprehensive command handling
- **Service Modules**: EmailService, BrowserController, ImageRecognizer (loosely coupled)
- **GUI Client**: Integrates with AttendanceSystem via background threading

### Error Handling Strategy
- **Network Issues**: Automatic retry with exponential backoff in EmailService and TelegramBot
- **Process Crashes**: Integrated watchdog monitoring with automatic restart and rate limiting  
- **UI Recognition Failures**: Template matching fallbacks with threshold adjustments
- **Connection Monitoring**: Health checks and reconnection logic for external services

## Enhanced Status Management System (Latest)

### Overview
The GUI client now features a comprehensive status management system with intermediate states for better user experience:

### System Status States
- **🔴 Stopped** - System is not running
- **🟡 Starting** - System is in the process of starting up
- **🟢 Running** - System is fully operational
- **🟡 Stopping** - System is in the process of shutting down

### Watchdog Status States
- **🔴 Disabled** - Watchdog is not active
- **🟡 Starting** - Watchdog is initializing
- **🟢 Running** - Watchdog is actively monitoring
- **🟡 Stopping** - Watchdog is shutting down
- **🔴 Error** - Watchdog encountered an error

### State Transition Flow
```
System: stopped → starting → running → stopping → stopped
Watchdog: disabled → starting → running → stopping → disabled
                      ↓         ↑
                    error ------+
```

## Integrated Watchdog Feature

### Overview
The GUI client includes an integrated watchdog system that automatically monitors and maintains system health:

### Key Features
- **Auto-Start**: Watchdog automatically starts when GUI launches (2-second delay)
- **Internal Monitoring**: Monitors GUI components, system resources, and error logs
- **Smart Restart**: Automatically restarts system components when issues are detected
- **Real-time Status**: Live status display with intermediate states
- **Configuration**: JSON-based configuration with persistent settings

### Configuration
- **Config File**: `gui_integrated_watchdog_config.json`
- **Default Settings**:
  - Monitor interval: 30 seconds
  - Max restarts: 10 attempts
  - Memory threshold: 85%
  - CPU threshold: 90%

### Enhanced Status Display
The GUI status panel shows detailed system and watchdog status with intermediate states:

**System Status:**
- 🔴 已停止 - System stopped
- 🟡 启动中... - System starting
- 🟢 运行中 - System running
- 🟡 关闭中... - System stopping

**Watchdog Status:**
- 🔴 已禁用 - Watchdog disabled
- 🟡 启动中... - Watchdog starting
- 🟢 运行中 (健康) - Watchdog running normally
- 🟡 关闭中... - Watchdog stopping
- 🔴 错误状态 - Watchdog error

### Benefits
- **Real-time feedback**: Users see exactly what the system is doing
- **Better UX**: No confusion about system state during transitions
- **Improved debugging**: Easier to identify where issues occur
- **Resource efficient**: No additional process overhead
- **Backwards compatible**: Maintains compatibility with existing code

## Development Environment Notes

### WSL/Linux Considerations
- GUI applications require X11 server or run in CLI mode only
- Virtual environment activation required: `source venv/bin/activate`
- Some Windows-specific packages (pywin32) will not install but system works without them

### Multi-User Development
- User-specific data stored in `punch_records/{username}/` and `screenshots/{username}/`
- Environment variables support multiple user credentials (LOGIN_USERNAME2, etc.)
- Settings and configurations isolated per user
