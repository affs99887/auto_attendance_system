# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an automated attendance system (自动打卡系统) that uses computer vision and OCR to automatically log into a timecard system and punch in/out. The system integrates with Telegram for remote control and monitoring.

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

### Key Technologies
- **Computer Vision**: OpenCV, PyAutoGUI, Tesseract OCR for screen automation
- **Telegram Bot**: python-telegram-bot for remote control
- **Scheduling**: schedule library with chinese-calendar for workday detection

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

### Watchdog Mode (watchdog.py)
- Process monitoring and automatic restart
- Resource usage monitoring with alerts
- Standalone operation with configurable restart limits

## Key Integration Points

### Data Flow Architecture
1. **Punch Operation**: BrowserController → ImageRecognizer → BrowserController → PunchRecordManager → EmailService → TelegramBot
2. **Task Scheduling**: TaskManager → AttendanceSystem → (punch operation flow)

### Module Dependencies
- **AttendanceSystem**: Core orchestrator using all service modules
- **TelegramBot**: Remote control interface with comprehensive command handling
- **Service Modules**: EmailService, BrowserController, ImageRecognizer (loosely coupled)

### Error Handling Strategy
- **Network Issues**: Automatic retry with exponential backoff in EmailService and TelegramBot
- **Process Crashes**: Watchdog monitoring with automatic restart and rate limiting  
- **UI Recognition Failures**: Template matching fallbacks with threshold adjustments
- **Connection Monitoring**: Health checks and reconnection logic for external services

## Development Environment Notes

### WSL/Linux Considerations
- Virtual environment activation required: `source venv/bin/activate`
- Some Windows-specific packages (pywin32) will not install but system works without them

### Multi-User Development
- User-specific data stored in `punch_records/{username}/` and `screenshots/{username}/`
- Environment variables support multiple user credentials (LOGIN_USERNAME2, etc.)
- Settings and configurations isolated per user

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.