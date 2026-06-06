$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
.\.venv\Scripts\python.exe -m myassistant.service stop
.\.venv\Scripts\python.exe -m myassistant.service remove
Write-Host "Removed."
