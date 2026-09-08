@echo off
REM ArchEngine Dependency Setup Script for Windows
REM This script downloads and sets up third-party dependencies

setlocal enabledelayedexpansion

set THIRD_PARTY_DIR=%~dp0..\third_party
set BUILD_DIR=%~dp0..\build

echo ========================================
echo ArchEngine Dependency Setup
echo ========================================

REM Create directories
if not exist "%THIRD_PARTY_DIR%" mkdir "%THIRD_PARTY_DIR%"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

REM Check for required tools
where cmake >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: CMake not found in PATH
    echo Please install CMake from https://cmake.org/download/
    exit /b 1
)

where git >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Git not found in PATH
    echo Please install Git from https://git-scm.com/
    exit /b 1
)

REM Check for Vulkan SDK
if not defined VULKAN_SDK (
    echo ERROR: VULKAN_SDK environment variable not set
    echo Please install the Vulkan SDK from https://vulkan.lunarg.com/
    exit /b 1
)
echo Found Vulkan SDK at: %VULKAN_SDK%

echo.
echo Downloading dependencies...
echo.

REM Download GLFW
echo [1/3] Setting up GLFW...
if not exist "%THIRD_PARTY_DIR%\glfw" (
    git clone --depth 1 --branch 3.3.8 https://github.com/glfw/glfw.git "%THIRD_PARTY_DIR%\glfw"
) else (
    echo GLFW already exists, skipping...
)

REM Download GLM
echo [2/3] Setting up GLM...
if not exist "%THIRD_PARTY_DIR%\glm" (
    git clone --depth 1 --branch 0.9.9.8 https://github.com/g-truc/glm.git "%THIRD_PARTY_DIR%\glm"
) else (
    echo GLM already exists, skipping...
)

REM Download nlohmann/json
echo [3/3] Setting up nlohmann/json...
if not exist "%THIRD_PARTY_DIR%\json" (
    git clone --depth 1 --branch v3.11.2 https://github.com/nlohmann/json.git "%THIRD_PARTY_DIR%\json"
) else (
    echo nlohmann/json already exists, skipping...
)

echo.
echo ========================================
echo Dependencies downloaded successfully!
echo ========================================
echo.
echo Next steps:
echo   1. Run compile_shaders.bat to compile GLSL shaders
echo   2. Run build.bat to build the project
echo.

endlocal
