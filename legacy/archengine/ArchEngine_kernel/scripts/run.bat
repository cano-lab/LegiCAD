@echo off
REM ArchEngine Run Script
REM Runs the compiled executable

setlocal

set PROJECT_DIR=%~dp0..
set BUILD_DIR=%PROJECT_DIR%\build
set CONFIG=Release

REM Parse arguments
if /i "%1"=="debug" set CONFIG=Debug

set EXE=%BUILD_DIR%\%CONFIG%\ArchEngine.exe

if not exist "%EXE%" (
    echo ERROR: Executable not found at %EXE%
    echo Please build the project first using build.bat
    exit /b 1
)

echo Running ArchEngine (%CONFIG%)...
echo.

cd "%PROJECT_DIR%"
"%EXE%"

endlocal
