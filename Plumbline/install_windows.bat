@echo off
rem ====================================================================
rem  Plumbline - one-time setup for Windows.
rem  Double-click this file. It builds a private Python environment in
rem  the .venv folder next to it and installs everything Plumbline needs.
rem  It is safe to run again if something went wrong.
rem  Full instructions: docs\WINDOWS_SETUP.md
rem ====================================================================
setlocal
pushd "%~dp0"
title Plumbline setup

rem  Other GIS programs sometimes set these for the whole PC. Plumbline brings its own copies.
set "PROJ_LIB="
set "PROJ_DATA="
set "GDAL_DATA="
set "GDAL_DRIVER_PATH="

echo.
echo  Plumbline setup
echo  ===============
echo.

rem --- 1. Which Python? 3.14 is preferred, 3.13 also works. ---
set "PYVER="
py -3.14 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYVER=3.14"
if not defined PYVER (
  py -3.13 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYVER=3.13"
)
if not defined PYVER goto nopython
for /f "delims=" %%v in ('py -%PYVER% --version') do echo  Found %%v

rem --- 2. A private environment: the .venv folder ---
if exist ".venv\Scripts\python.exe" goto havevenv
echo  Creating a private Python environment ...
py -%PYVER% -m venv .venv
if errorlevel 1 goto failed
:havevenv

rem --- 3. The libraries ---
echo.
echo  Installing the libraries Plumbline needs.
echo  This downloads about 250 MB, so it can take several minutes.
echo  Please leave this window open until it says All done.
echo.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --default-timeout 100 -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --default-timeout 100 --no-deps -e .
if errorlevel 1 goto failed

rem --- 4. Health check ---
echo.
echo  Checking the install ...
echo.
".venv\Scripts\python.exe" -m plumbline doctor
if errorlevel 1 goto failed

echo.
echo  ======================================================
echo   All done. To start Plumbline, double-click Plumbline.bat
echo  ======================================================
echo.
pause
exit /b 0

:nopython
echo  Python 3.13 or 3.14 was not found on this computer.
echo.
echo    1. Download the 64-bit installer from
echo         https://www.python.org/downloads/release/python-3148/
echo       (Python 3.13 also works; 3.14 is the version Plumbline is tested on.)
echo       Scroll down to Files and pick: Windows installer 64-bit
echo    2. Run it. Tick the box Add python.exe to PATH, then click Install Now.
echo    3. Double-click install_windows.bat again.
echo.
echo  Using the Python install manager instead? Open PowerShell and type: py install 3.14
echo  Prefer to type the setup steps yourself? See Step 3 in docs\WINDOWS_SETUP.md
echo.
pause
exit /b 1

:failed
echo.
echo  ------------------------------------------------------------
echo   Something went wrong. Scroll up and read the last messages.
echo   Copy the last 20 lines or so and send them to me.
echo   Common fixes are listed in docs\WINDOWS_SETUP.md
echo  ------------------------------------------------------------
echo.
pause
exit /b 1
