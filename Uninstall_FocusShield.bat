@echo off
title FocusShield - Uninstaller
color 0C
echo ========================================================
echo             FocusShield - Complete Uninstall
echo ========================================================
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Please right-click this file and select:
    echo         "Run as administrator"
    echo.
    pause
    exit /b
)

echo 1. Stopping running processes...
taskkill /f /im FocusShield.exe >nul 2>&1

echo 2. Removing Auto-Start Task...
schtasks /delete /tn "FocusShield_AutoStart" /f >nul 2>&1

echo 3. Restoring Windows Proxy...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "" /f >nul 2>&1
rundll32.exe inetcpl.cpl,ClearMyTracksByProcess 8 >nul 2>&1

echo 4. Removing Program Files folder...
rd /s /q "C:\Program Files\FocusShield" >nul 2>&1

echo.
echo ========================================================
echo [SUCCESS] FocusShield completely removed and internet restored!
echo ========================================================
echo.
pause
