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

### Web GUI (Next.js)
- **gui/** - Next.js application providing web interface
- **gui/lib/server.js** - Express server for API endpoints
- **gui/components/** - React components for dashboard, settings, logs, etc.

### Key Technologies
- **Computer Vision**: OpenCV, PyAutoGUI, Tesseract OCR for screen automation
- **Telegram Bot**: python-telegram-bot for remote control
- **Scheduling**: schedule library with chinese-calendar for workday detection
- **Frontend**: Next.js, React, Tailwind CSS, shadcn/ui components

## Common Development Commands

### Python Backend
```bash
# Install dependencies
pip install -r requirements.txt

# Run main attendance system
python main.py

# Run with watchdog (recommended)
python watchdog.py

# Run tests
python test_startup.py
python test_alert_detection.py
python test_network_recovery.py
```

### Web GUI
```bash
# Navigate to gui directory first
cd gui

# Install dependencies
npm install
# or
pnpm install

# Development server
npm run dev
# or
pnpm dev

# Development with backend
npm run dev:all
# or
pnpm dev:all

# Build for production
npm run build
npm run start

# Lint
npm run lint
```

## Configuration

### Environment Variables (.env)
- LOGIN_USERNAME, LOGIN_PASSWORD, LOGIN_URL - Login credentials
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID - Telegram bot configuration
- TESSERACT_PATH - Path to Tesseract OCR executable
- WORK_START_TIME, WORK_END_TIME - Punch in/out times
- EMAIL_* - Email notification settings

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

## Testing

Run individual test files to verify specific functionality:
- test_startup.py - System initialization tests
- test_alert_detection.py - UI recognition tests  
- test_network_recovery.py - Network resilience tests

### Refactored Module Tests (2025-06-24)
- test_email_service.py - Complete email functionality testing with retry mechanisms
- test_imports.py - Module import and dependency verification
- test_refactor_basic.py - Basic refactoring validation and syntax checking