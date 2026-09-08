param(
    [string]$PidFile = (Join-Path $PSScriptRoot "render_server.pid")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host "No PID file found at $PidFile"
    exit 0
}

$pid = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue
if (-not $pid) {
    Write-Host "PID file is empty"
    exit 1
}

$proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Host "No process found for PID $pid"
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    exit 0
}

Write-Host "Stopping render server (PID $pid)"
Stop-Process -Id $pid -Force
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "Render server stopped"
