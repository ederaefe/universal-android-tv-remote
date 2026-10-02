@echo off
setlocal enabledelayedexpansion

title HY300 Master Remote Launcher

echo ============================================================
echo   Universal Android TV ^& Projector Remote Launcher
echo ============================================================

:: 1. Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    echo Make sure to check "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

:: 2. Check ADB
set ADB_FOUND=0
if exist "adb.exe" set ADB_FOUND=1
if exist "platform-tools\adb.exe" set ADB_FOUND=1
where adb >nul 2>nul
if %errorlevel% equ 0 set ADB_FOUND=1

if %ADB_FOUND% equ 0 (
    echo [WARNING] Android Debug Bridge (adb.exe) was not found.
    echo Download Google Platform-Tools from:
    echo   https://dl.google.com/android/repository/platform-tools-latest-windows.zip
    echo Extract the zip and place adb.exe in this folder.
    echo.
    set /p DL="Would you like to open the download page now? (Y/N): "
    if /i "!DL!"=="Y" (
        start https://dl.google.com/android/repository/platform-tools-latest-windows.zip
    )
    pause
    exit /b 1
)

:: 3. Launch Server
echo [LAUNCH] Starting Master Remote Cockpit...
python projector.py %*

if %errorlevel% neq 0 (
    echo.
    echo [INFO] Server stopped or encountered an issue.
    pause
)
