# Install Ram as a Windows service. Run as Administrator.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\install_service.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Install + start
.\.venv\Scripts\python.exe -m ram.service install
.\.venv\Scripts\python.exe -m ram.service --startup auto update
.\.venv\Scripts\python.exe -m ram.service start

Write-Host ""
Write-Host "Ram is installed. Useful commands:"
Write-Host "  net start RamAssistant"
Write-Host "  net stop  RamAssistant"
Write-Host "  Get-EventLog -LogName Application -Source RamAssistant -Newest 20"
