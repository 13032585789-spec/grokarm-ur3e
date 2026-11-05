@echo off
rem One click: ELP stereo camera service in its own window, then the app on the REAL robot using that camera.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo .venv missing: run run_stereo.bat once first.
  pause
  exit /b 1
)
echo [1/2] starting the ELP stereo camera service (window "ELP camera") ...
start "ELP camera" cmd /k "cd /d %~dp0backend && "%PY%" -m stereo_depth serve"
timeout /t 6 /nobreak >nul
set CAMERA_SOURCE=url
set CAMERA_URL=http://127.0.0.1:8720/frame.jpg
set STEREO_URL=http://127.0.0.1:8720
echo [2/2] starting the app on the real robot ...
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1" real
