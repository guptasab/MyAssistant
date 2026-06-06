$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
.\.venv\Scripts\python.exe -m ram.service stop
.\.venv\Scripts\python.exe -m ram.service remove
Write-Host "Removed."
