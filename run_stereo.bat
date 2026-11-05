@echo off
rem Double-click me. Sets up Python once, then runs the stereo depth tools.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] creating .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo Python not found. Install Python 3.11 from python.org and tick "Add python.exe to PATH".
    pause
    exit /b 1
  )
)
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist ".venv\stereo_ready.txt" (
  echo [setup] installing packages, takes 1-3 minutes the first time ...
  "%PY%" -m pip install -q --upgrade pip
  "%PY%" -m pip install -q -r requirements.txt
  "%PY%" -m pip uninstall -y -q opencv-python-headless
  "%PY%" -m pip install -q --force-reinstall opencv-python
  if errorlevel 1 (
    echo Package install failed. Check the internet connection and run me again.
    pause
    exit /b 1
  )
  echo ok> ".venv\stereo_ready.txt"
)

cd backend
:menu
echo.
echo ================= STEREO DEPTH =================
echo  1  Preview      (see left/right image, no calibration needed)
echo  2  Calibrate    (checkerboard, 15-20 poses)
echo  3  Serve depth  (then open http://127.0.0.1:8720)
echo  4  Quit
echo ================================================
choice /c 1234 /n /m "Choose 1-4: "
if errorlevel 4 goto :eof
if errorlevel 3 goto serve
if errorlevel 2 goto calib
if errorlevel 1 goto preview

:preview
"%PY%" -m stereo_depth preview
goto menu

:calib
set "SQ="
set /p SQ="Measured size of ONE checkerboard square in mm (e.g. 24.8): "
if "%SQ%"=="" goto calib
"%PY%" -m stereo_depth calibrate --square-mm %SQ%
pause
goto menu

:serve
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start http://127.0.0.1:8720"
"%PY%" -m stereo_depth serve
pause
goto menu
