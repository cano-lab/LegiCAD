param(
    [string]$PythonExe = "python",
    [string]$VenvPath = ""
)

$ErrorActionPreference = "Stop"

# Default venv path is parent directory's .venv-sd
if ([string]::IsNullOrEmpty($VenvPath)) {
    $VenvPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv-sd"
}

# Resolve path if it exists, otherwise use as-is
if (Test-Path $VenvPath) {
    $venvFull = (Get-Item $VenvPath).FullName
} else {
    $venvFull = $VenvPath
}

$requirements = Join-Path $PSScriptRoot "requirements.txt"
if (-not (Test-Path -LiteralPath $requirements)) {
    throw "Missing requirements.txt at $requirements"
}

Write-Host "Creating venv at $venvFull"
& $PythonExe -m venv $venvFull

$venvPython = Join-Path (Join-Path $venvFull "Scripts") "python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Venv python not found at $venvPython"
}

Write-Host "Installing dependencies from $requirements"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r $requirements

Write-Host "Done. Venv ready: $venvPython"
