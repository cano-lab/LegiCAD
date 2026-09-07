@echo off
REM RevitMCP AI Enhancer Server Launcher
REM
REM This script starts the AI enhancer server for architectural visualization.
REM The server provides image enhancement, upscaling, and environment generation.

setlocal

REM === Configuration ===
set VENV_PATH=C:\RevitMCP\.venv-sd
set SERVER_SCRIPT=%~dp0enhancer_server.py
set SETUP_SCRIPT=%~dp0setup_render_env.bat
set PORT=5000

REM === Check virtual environment ===
if not exist "%VENV_PATH%\Scripts\python.exe" (
    echo.
    echo AI Enhancer environment not found.
    echo.

    if exist "%SETUP_SCRIPT%" (
        echo Running first-time setup...
        echo This will download and install required AI packages (~5GB).
        echo.
        choice /C YN /M "Continue with setup?"
        if errorlevel 2 (
            echo Setup cancelled.
            pause
            exit /b 1
        )
        call "%SETUP_SCRIPT%"
        if errorlevel 1 (
            echo Setup failed.
            pause
            exit /b 1
        )
    ) else (
        echo ERROR: Setup script not found at %SETUP_SCRIPT%
        echo Please run setup_render_env.bat first.
        pause
        exit /b 1
    )
)

REM === Start server ===
echo.
echo Starting RevitMCP AI Enhancer Server...
echo.
echo Server will be available at: http://localhost:%PORT%
echo Press Ctrl+C to stop.
echo.

cd /d "%~dp0"
"%VENV_PATH%\Scripts\python.exe" "%SERVER_SCRIPT%"

pause
