@echo off
title FocusShield - Protected Auto-Start Installer
color 0B
echo ========================================================
echo       FocusShield - Protected Auto-Start Setup
echo ========================================================
echo.

:: Check for Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please right-click this file and select:
    echo         "Run as administrator" (অ্যাডমিনিস্ট্রেটর হিসেবে চালান)
    echo.
    pause
    exit /b
)

set "TARGET_DIR=C:\Program Files\FocusShield"

echo 1. Creating protected folder in Program Files...
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

echo 2. Copying application files to protected location...
copy /Y "dist\FocusShield.exe" "%TARGET_DIR%\FocusShield.exe" >nul 2>&1
if not exist "%TARGET_DIR%\FocusShield.exe" (
    copy /Y "FocusShield.exe" "%TARGET_DIR%\FocusShield.exe" >nul 2>&1
)
copy /Y "whitelist_config.json" "%TARGET_DIR%\whitelist_config.json" >nul 2>&1
copy /Y "Restore_Internet.bat" "%TARGET_DIR%\Restore_Internet.bat" >nul 2>&1
copy /Y "app_icon.ico" "%TARGET_DIR%\app_icon.ico" >nul 2>&1

echo 3. Creating Windows Scheduled Task for Auto-Start on PC Boot...
schtasks /create /tn "FocusShield_AutoStart" /tr "\"%TARGET_DIR%\FocusShield.exe\"" /sc onlogon /rl highest /f >nul 2>&1

echo.
echo ========================================================
echo [SUCCESS] FocusShield successfully installed and protected!
echo.
echo * File Location: %TARGET_DIR%
echo   (Standard Users cannot delete or modify files in Program Files)
echo.
echo * Auto-Start: Enabled via Windows Task Scheduler
echo   (FocusShield will automatically start every time PC turns on)
echo ========================================================
echo.
pause
