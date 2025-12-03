## Project Overview

This is an automated attendance system (自动打卡系统) that supports dual automation modes: traditional computer vision/OCR and modern Selenium WebDriver automation for logging into timecard systems and punch in/out. The system integrates with Telegram for remote control and monitoring.

## Architecture

The system consists of several key components:

### Core Python Components
- **main.py** - Main application entry point
- **start.py** - Unified launcher with mode selection and status monitoring
- **watchdog.py** - Process monitor that restarts main.py if it crashes

### Modular Architecture (modules/)
- **attendance_system.py** - Core AttendanceSystem class orchestrating all operations
- **telegram_bot.py** - TelegramBot class for remote control interface
- **selenium_login.py** - SeleniumLoginController for WebDriver-based automation
- **browser_controller.py** - Traditional browser automation using PyAutoGUI
- **image_recognizer.py** - OCR and template matching for UI recognition
- **email_service.py** - EmailService class for notifications with retry logic
- **record_manager.py** - PunchRecordManager for attendance data persistence
- **task_manager.py** - TaskManager for scheduling operations
- **schedule_manager.py** - Schedule management and workday detection
- **config.py** - Centralized configuration management

### Key Technologies
- **Browser Automation**: Selenium WebDriver with Edge/Chrome support, automatic driver management
- **Computer Vision**: OpenCV, PyAutoGUI, Tesseract OCR for traditional screen automation
- **Telegram Bot**: python-telegram-bot for remote control and monitoring
- **Scheduling**: schedule library with chinese-calendar for workday detection
- **Data Persistence**: JSON-based storage with user isolation

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

# Run with unified launcher (recommended)
python start.py                    # Default watchdog mode
python start.py --interactive       # Interactive mode selection
python start.py --mode main         # Direct main.py execution
python start.py --mode watchdog     # Watchdog mode
python start.py --mode status       # Check running status

# Direct execution (alternative)
python main.py                      # CLI mode with Telegram integration
python watchdog.py                  # Watchdog mode with process monitoring
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

### Dynamic Configuration (dynamic_config.json)
- USE_SELENIUM_LOGIN - Enable/disable Selenium automation mode
- SELENIUM_HEADLESS - Run Selenium in headless mode
- Current automation mode settings (excluded from version control)

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

- **Dual Automation Modes**: Selenium WebDriver and traditional computer vision
- **Multi-User Support**: Parallel login and data isolation for multiple users
- **Intelligent Time Management**: Automatic punch-out scheduling with work time calculation
- **Telegram Integration**: Comprehensive remote control (/punch_in, /punch_out, /status, /log)
- **Robust Error Handling**: Automatic retry mechanisms and fallback strategies
- **Email Notifications**: Screenshots and status reports with SMTP integration
- **Smart Scheduling**: Workday detection using Chinese calendar integration
- **Process Monitoring**: Watchdog system with resource monitoring and auto-restart

## System Operation Modes

### Unified Launcher Mode (start.py)
- **Interactive Mode**: Menu-driven mode selection
- **Direct Mode**: Specify execution mode via command line arguments
- **Status Mode**: Monitor running processes and system health

### Automation Modes
- **Selenium Mode**: WebDriver-based automation (more reliable)
- **Traditional Mode**: Computer vision + PyAutoGUI (fallback option)
- **Hybrid Mode**: Automatic fallback between modes

### Process Modes
- **Main Process**: Full system with Telegram integration
- **Watchdog Mode**: Process monitoring with automatic restart and resource alerts

## Key Integration Points

### Data Flow Architecture
1. **Selenium Mode**: SeleniumLoginController → SeleniumRecordManager → EmailService → TelegramBot
2. **Traditional Mode**: BrowserController → ImageRecognizer → RecordManager → EmailService → TelegramBot
3. **Task Scheduling**: TaskManager → AttendanceSystem → (automation flow selection)

### Module Dependencies
- **AttendanceSystem**: Core orchestrator with mode-aware automation routing
- **TelegramBot**: Remote control with Selenium and traditional command support
- **Automation Modules**: SeleniumLoginController, BrowserController (mode-specific)
- **Service Modules**: EmailService, RecordManager, ConfigManager (shared infrastructure)

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

## Important Coding Guidelines
- 当我提和重构相关的需求的时候，需要严格基于原本的代码以及功能进行重构，避免节外生枝

## Memory Notes
- 始终使用中文回复

# important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
