@echo off
REM ============================================================
REM RevitMCP AI Render Environment Setup
REM
REM This script automatically creates and configures the virtual
REM environment needed for AI rendering features.
REM
REM Run this ONCE after installing RevitMCP.
REM ============================================================

setlocal EnableDelayedExpansion

echo.
echo ============================================================
echo   RevitMCP AI Render Environment Setup
echo ============================================================
echo.

REM === Configuration ===
set VENV_PATH=C:\RevitMCP\.venv-sd
set SCRIPT_DIR=%~dp0
set REQUIREMENTS=%SCRIPT_DIR%requirements-render.txt
set REVITMCP_DIR=C:\RevitMCP
set EMBEDDED_PYTHON=%REVITMCP_DIR%\python\python.exe

REM === Check for Python ===
echo [1/5] Checking for Python...

REM First check for embedded Python (bundled with installer)
if exist "%EMBEDDED_PYTHON%" (
    set PYTHON_CMD=%EMBEDDED_PYTHON%
    for /f "tokens=2" %%i in ('"%EMBEDDED_PYTHON%" --version 2^>^&1') do set PYTHON_VERSION=%%i
    echo    Found embedded Python !PYTHON_VERSION!
    goto :python_found
)

REM Fall back to system Python
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python not found.
    echo.
    echo Please either:
    echo   1. Run the RevitMCP installer (includes Python), or
    echo   2. Install Python 3.10+ from https://www.python.org/downloads/
    echo      (Make sure to check "Add Python to PATH")
    echo.
    pause
    exit /b 1
)

set PYTHON_CMD=python
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo    Found system Python %PYTHON_VERSION%

:python_found

REM === Check for NVIDIA GPU ===
echo.
echo [2/5] Checking for NVIDIA GPU...
nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo    WARNING: nvidia-smi not found. CUDA may not be available.
    echo    AI features will be slower without GPU acceleration.
    set CUDA_AVAILABLE=0
) else (
    echo    NVIDIA GPU detected
    set CUDA_AVAILABLE=1
)

REM === Create virtual environment ===
echo.
echo [3/5] Creating virtual environment at %VENV_PATH%...
if exist "%VENV_PATH%" (
    echo    Virtual environment already exists.
    choice /C YN /M "    Recreate it? (This will delete existing packages)"
    if errorlevel 2 goto :skip_venv
    echo    Removing old environment...
    rmdir /s /q "%VENV_PATH%"
)

"%PYTHON_CMD%" -m venv "%VENV_PATH%"
if errorlevel 1 (
    echo    ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)
echo    Virtual environment created.

:skip_venv

REM === Activate and install PyTorch ===
echo.
echo [4/5] Installing PyTorch with CUDA support...
echo    This may take several minutes (downloading ~2GB)...
call "%VENV_PATH%\Scripts\activate.bat"

if %CUDA_AVAILABLE%==1 (
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118 --quiet
) else (
    pip install torch torchvision --quiet
)

if errorlevel 1 (
    echo    ERROR: Failed to install PyTorch.
    pause
    exit /b 1
)
echo    PyTorch installed.

REM === Install requirements ===
echo.
echo [5/5] Installing AI packages...
echo    This may take several minutes...

if not exist "%REQUIREMENTS%" (
    echo    ERROR: requirements-render.txt not found at %REQUIREMENTS%
    pause
    exit /b 1
)

pip install -r "%REQUIREMENTS%" --quiet
if errorlevel 1 (
    echo    WARNING: Some packages may have failed to install.
    echo    The render server may still work with reduced functionality.
)

REM === Verify installation ===
echo.
echo ============================================================
echo   Verifying installation...
echo ============================================================
echo.

python -c "import torch; print(f'PyTorch: {torch.__version__}')"
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
python -c "import diffusers; print(f'Diffusers: {diffusers.__version__}')"
python -c "import transformers; print(f'Transformers: {transformers.__version__}')"

echo.
echo ============================================================
echo   Setup Complete!
echo ============================================================
echo.
echo The AI render environment is ready.
echo.
echo To start the render server:
echo   %SCRIPT_DIR%start_render_server.bat
echo.
echo Or use the "AI Enhancer" button in Revit.
echo.

pause
