# Start the Reflecta backend (serves the frontend at http://localhost:8000)
# Usage:  .\scripts\run_api.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& "$root\.venv\Scripts\python.exe" -m uvicorn api.main:app --reload --port 8000
