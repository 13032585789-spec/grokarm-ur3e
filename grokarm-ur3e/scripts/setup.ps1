# Run from the project folder:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv venv --python 3.12 .venv
    uv pip install --python .venv\Scripts\python.exe -r requirements.txt
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3.12 --version
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12 is required (ur_rtde has no Windows build for 3.13). Run: winget install Python.Python.3.12" }
    py -3.12 -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt
} else {
    throw "Install Python 3.12 first: winget install Python.Python.3.12"
}

if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env. Add XAI_API_KEY to it." }

.venv\Scripts\python.exe -c "import rtde_control, rtde_receive; print('ur_rtde OK')"
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m eval.run_eval baseline
Write-Host "Setup done. Start with: powershell -ExecutionPolicy Bypass -File scripts\run.ps1"
