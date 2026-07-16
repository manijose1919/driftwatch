# Start DriftWatch locally. Usage:  .\start.ps1 [-Port 8080]
param([int]$Port = 8080)
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    python -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}
Write-Host "DriftWatch dashboard: http://127.0.0.1:$Port/" -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port $Port
