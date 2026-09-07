@echo off
REM ArchEngine Shader Compilation Script
REM Compiles GLSL shaders to SPIR-V using glslc from the Vulkan SDK

setlocal enabledelayedexpansion

set SHADER_DIR=%~dp0..\shaders
set OUTPUT_DIR=%SHADER_DIR%

echo ========================================
echo ArchEngine Shader Compiler
echo ========================================

REM Check for Vulkan SDK
if not defined VULKAN_SDK (
    echo ERROR: VULKAN_SDK environment variable not set
    echo Please install the Vulkan SDK from https://vulkan.lunarg.com/
    exit /b 1
)

REM Find glslc compiler
set GLSLC=%VULKAN_SDK%\Bin\glslc.exe
if not exist "%GLSLC%" (
    echo ERROR: glslc not found at %GLSLC%
    exit /b 1
)

echo Using compiler: %GLSLC%
echo Shader directory: %SHADER_DIR%
echo.

set COMPILED=0
set FAILED=0

REM Include path for shared headers (ubo.glsl, etc.)
set INCLUDE_FLAGS=-I"%SHADER_DIR%"

REM Compile vertex shaders
for %%f in ("%SHADER_DIR%\*.vert") do (
    echo Compiling %%~nxf...
    "%GLSLC%" %INCLUDE_FLAGS% "%%f" -o "%%f.spv"
    if !ERRORLEVEL! equ 0 (
        echo   SUCCESS: %%~nxf.spv
        set /a COMPILED+=1
    ) else (
        echo   FAILED: %%~nxf
        set /a FAILED+=1
    )
)

REM Compile fragment shaders
for %%f in ("%SHADER_DIR%\*.frag") do (
    echo Compiling %%~nxf...
    "%GLSLC%" %INCLUDE_FLAGS% "%%f" -o "%%f.spv"
    if !ERRORLEVEL! equ 0 (
        echo   SUCCESS: %%~nxf.spv
        set /a COMPILED+=1
    ) else (
        echo   FAILED: %%~nxf
        set /a FAILED+=1
    )
)

REM Compile tessellation control shaders
for %%f in ("%SHADER_DIR%\*.tesc") do (
    echo Compiling %%~nxf...
    "%GLSLC%" %INCLUDE_FLAGS% "%%f" -o "%%f.spv"
    if !ERRORLEVEL! equ 0 (
        echo   SUCCESS: %%~nxf.spv
        set /a COMPILED+=1
    ) else (
        echo   FAILED: %%~nxf
        set /a FAILED+=1
    )
)

REM Compile tessellation evaluation shaders
for %%f in ("%SHADER_DIR%\*.tese") do (
    echo Compiling %%~nxf...
    "%GLSLC%" %INCLUDE_FLAGS% "%%f" -o "%%f.spv"
    if !ERRORLEVEL! equ 0 (
        echo   SUCCESS: %%~nxf.spv
        set /a COMPILED+=1
    ) else (
        echo   FAILED: %%~nxf
        set /a FAILED+=1
    )
)

REM Compile compute shaders (if any)
for %%f in ("%SHADER_DIR%\*.comp") do (
    echo Compiling %%~nxf...
    "%GLSLC%" %INCLUDE_FLAGS% "%%f" -o "%%f.spv"
    if !ERRORLEVEL! equ 0 (
        echo   SUCCESS: %%~nxf.spv
        set /a COMPILED+=1
    ) else (
        echo   FAILED: %%~nxf
        set /a FAILED+=1
    )
)

echo.
echo ========================================
echo Compilation complete!
echo   Compiled: %COMPILED% shaders
echo   Failed:   %FAILED% shaders
echo ========================================

if %FAILED% gtr 0 (
    exit /b 1
)

endlocal
