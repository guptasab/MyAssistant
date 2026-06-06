# Install MyAssistant as a Windows service. Run as Administrator.
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
.\.venv\Scripts\python.exe -m myassistant.service install
.\.venv\Scripts\python.exe -m myassistant.service --startup auto update
.\.venv\Scripts\python.exe -m myassistant.service start

Write-Host ""
Write-Host "MyAssistant is installed. Useful commands:"
Write-Host "  net start MyAssistantService"
Write-Host "  net stop  MyAssistantService"
Write-Host "  Get-EventLog -LogName Application -Source MyAssistantService -Newest 20"
