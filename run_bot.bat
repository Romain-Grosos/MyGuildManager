@echo off
:: MyGuildManager Discord Bot - Windows Launcher

echo Starting MyGuildManager Discord Bot...
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.10 or higher
    pause
    exit /b 1
)

:: Check if .env file exists
if not exist "app\.env" (
    echo Error: app\.env file not found!
    echo Please copy .env.example to app\.env and configure it
    pause
    exit /b 1
)

:: Run the bot
python run_bot.py

:: Pause on error
if errorlevel 1 (
    echo.
    echo Bot exited with error
    pause
)