@echo off
REM ArchEngine Build Script for Windows
REM Configures and builds the project using CMake

setlocal enabledelayedexpansion

set PROJECT_DIR=%~dp0..
set BUILD_DIR=%PROJECT_DIR%\build
set CONFIG=Release

REM Parse arguments
:parse_args
if "%1"=="" goto :done_args
if /i "%1"=="debug" set CONFIG=Debug
if /i "%1"=="release" set CONFIG=Release
if /i "%1"=="clean" goto :clean
shift
goto :parse_args
:done_args

echo ========================================
echo ArchEngine Build Script
echo ========================================
echo Configuration: %CONFIG%
echo.

REM Check for CMake
where cmake >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: CMake not found in PATH
    exit /b 1
)

REM Check for Vulkan SDK
if not defined VULKAN_SDK (
    echo ERROR: VULKAN_SDK environment variable not set
    exit /b 1
)

REM Compile shaders first
echo Compiling shaders...
call "%~dp0compile_shaders.bat"
if %ERRORLEVEL% neq 0 (
    echo ERROR: Shader compilation failed
    exit /b 1
)

REM Create build directory
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

REM Configure with CMake
echo.
echo Configuring project...
cd "%BUILD_DIR%"
cmake -G "Visual Studio 17 2022" -A x64 -DCMAKE_BUILD_TYPE=%CONFIG% ..
if %ERRORLEVEL% neq 0 (
    echo ERROR: CMake configuration failed
    exit /b 1
)

REM Build
echo.
echo Building project...
cmake --build . --config %CONFIG% --parallel
if %ERRORLEVEL% neq 0 (
    echo ERROR: Build failed
    exit /b 1
)

echo.
echo ========================================
echo Build successful!
echo Executable: %BUILD_DIR%\%CONFIG%\ArchEngine.exe
echo ========================================

goto :eof

:clean
echo Cleaning build directory...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
echo Clean complete.
goto :eof

endlocal
