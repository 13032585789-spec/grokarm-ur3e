# Start VOCE on Windows:  .\start.ps1 [sim|ursim|real]   (default: ROBOT_MODE from .env, else sim)
# If PowerShell blocks scripts:  powershell -ExecutionPolicy Bypass -File .\start.ps1 sim
param([ValidateSet("sim", "ursim", "real")][string]$Mode = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $Mode) { $Mode = if ($env:ROBOT_MODE) { $env:ROBOT_MODE } else { "sim" } }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
}
& $py -m pip install -q -r requirements.txt -e .
if (-not (Test-Path "frontend\dist\index.html")) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Push-Location frontend; npm install --no-audit --no-fund; npm run build; Pop-Location
    } else {
        throw "frontend\dist is missing and Node.js is not installed. Run 'git pull' to get the prebuilt UI."
    }
}
if (-not (Test-Path ".env")) {
    Write-Host "No .env: copy .env.example to .env and set XAI_API_KEY for voice and Grok Vision. Text mode and the mock inspector work without it."
}
& $py -m app.launcher --mode $Mode
