Set-Location (Join-Path $PSScriptRoot "..")
Write-Host "Open http://localhost:8000 in Chrome or Edge"
.venv\Scripts\python.exe -m uvicorn backend.asgi:app --host 127.0.0.1 --port 8000
