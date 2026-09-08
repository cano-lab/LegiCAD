param(
    [string]$VenvPath = "",
    [string]$Port = "5000"
)

$ErrorActionPreference = "Stop"

# Default venv path - check common locations
if ([string]::IsNullOrEmpty($VenvPath)) {
    # First check for existing stable diffusion venv at RevitMCP
    $revitVenv = "C:\RevitMCP\.venv-sd"
    if (Test-Path $revitVenv) {
        $VenvPath = $revitVenv
    } else {
        # Fallback to parent directory's .venv-sd
        $VenvPath = Join-Path (Split-Path $PSScriptRoot -Parent) ".venv-sd"
    }
}

# Try to resolve the path
if (Test-Path $VenvPath) {
    $venvFull = (Get-Item $VenvPath).FullName
} else {
    $venvFull = $VenvPath
}

$venvPython = Join-Path (Join-Path $venvFull "Scripts") "python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Venv python not found at $venvPython. Run bootstrap_render_server.ps1 first."
}

$serverScript = Join-Path $PSScriptRoot "render_server.py"
if (-not (Test-Path -LiteralPath $serverScript)) {
    throw "render_server.py not found at $serverScript"
}

$pidFile = Join-Path $PSScriptRoot "render_server.pid"
if (Test-Path -LiteralPath $pidFile) {
    $existingPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
    if ($existingPid -and (Get-Process -Id $existingPid -ErrorAction SilentlyContinue)) {
        Write-Host "Render server already running (PID $existingPid)"
        exit 0
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Starting render server with $venvPython on port $Port"
$env:PORT = $Port
$proc = Start-Process -FilePath $venvPython -ArgumentList $serverScript -WorkingDirectory $PSScriptRoot -PassThru -WindowStyle Hidden
$proc.Id | Set-Content -LiteralPath $pidFile -Encoding ASCII
Write-Host "Render server started (PID $($proc.Id))"
