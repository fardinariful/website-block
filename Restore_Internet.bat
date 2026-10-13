@echo off
title FocusShield - Emergency Internet Restore
color 0A
echo ========================================================
echo        FocusShield - Emergency Internet Restore
echo ========================================================
echo Stopping FocusShield if active...
taskkill /f /im FocusShield.exe >nul 2>&1
echo Disabling Windows System Proxy...
echo.

reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable /t REG_DWORD /d 0 /f >nul 2>&1
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer /t REG_SZ /d "" /f >nul 2>&1

echo Refreshing Windows WinINet internet settings...
powershell -Command "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); [System.Runtime.InteropServices.Marshal]::GetLastWin32Error()" >nul 2>&1
rundll32.exe inetcpl.cpl,ClearMyTracksByProcess 8 >nul 2>&1

echo.
echo ========================================================
echo [SUCCESS] Windows proxy has been completely DISABLED!
echo Normal internet access is restored.
echo ========================================================
echo.
pause
