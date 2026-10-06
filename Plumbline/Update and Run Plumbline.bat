@echo off
rem ====================================================================
rem  Plumbline - one-click update and run for Windows.
rem  Double-click this file. It:
rem    1. pulls the latest code with git (politely skips the update
rem       when this folder did not come from git, or git is missing);
rem    2. reuses the .venv folder - creating it only if it is missing;
rem    3. installs the libraries only when requirements.txt changed.
rem       It compares against a copy of the last-installed requirements
rem       saved inside .venv, so an ordinary start takes seconds;
rem    4. starts Plumbline.
rem  You can also drag a .plb file onto this file: it updates first,
rem  then opens that project.
rem  First time on this computer? install_windows.bat does the same
rem  setup with more explanation. Full instructions: docs\WINDOWS_SETUP.md
rem ====================================================================
setlocal
pushd "%~dp0"
title Plumbline - update and run

rem  Other GIS programs sometimes set these for the whole PC. Plumbline brings its own copies.
set "PROJ_LIB="
set "PROJ_DATA="
set "GDAL_DATA="
set "GDAL_DRIVER_PATH="

echo.
echo  Plumbline update and run
echo  ========================
echo.

rem --- 1. Update the code. Needs git; skip politely without it. ---
set "GIT_TERMINAL_PROMPT=0"
where git >nul 2>&1
if errorlevel 1 goto nogit
git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 goto notrepo
echo  Checking for updates ...
git pull --ff-only
if errorlevel 1 goto pullfailed
goto venv

:pullfailed
echo.
echo  Could not update. Using the copy on this computer:
echo  either there is no internet right now, or files you changed
echo  get in the way of the update. Plumbline will still start.
goto venv

:nogit
echo  git is not installed on this computer, so I cannot check for updates.
echo  Starting Plumbline with the files as they are.
goto venv

:notrepo
echo  This folder was not downloaded with git, so I cannot check for updates.
echo  Starting Plumbline with the files as they are.
goto venv

rem --- 2. The private environment: reuse .venv, build only if missing ---
:venv
set "PLB_PY=%~dp0.venv\Scripts\python.exe"
if exist "%PLB_PY%" goto havevenv
echo.
echo  No .venv folder yet, so the one-time setup runs now.
set "PYVER="
py -3.14 -c "import sys" >nul 2>&1
if not errorlevel 1 set "PYVER=3.14"
if not defined PYVER (
  py -3.13 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PYVER=3.13"
)
if not defined PYVER goto nopython
for /f "delims=" %%v in ('py -%PYVER% --version') do echo  Found %%v
echo  Creating a private Python environment ...
py -%PYVER% -m venv "%~dp0.venv"
if errorlevel 1 goto failed
:havevenv

rem --- 3. The libraries: install only when requirements.txt changed ---
set "NEEDINSTALL="
if not exist ".venv\requirements.installed.txt" set "NEEDINSTALL=1"
if defined NEEDINSTALL goto install
fc /b "requirements.txt" ".venv\requirements.installed.txt" >nul 2>&1
if errorlevel 1 goto install
echo  requirements.txt has not changed since the last install -
echo  keeping the libraries that are already in .venv.
goto launch

:install
echo.
echo  Installing the libraries Plumbline needs.
echo  The first time this downloads about 250 MB and can take several
echo  minutes; afterwards it only runs when requirements.txt changes.
echo  Please leave this window open until it finishes.
echo.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --default-timeout 100 -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --default-timeout 100 --no-deps -e .
if errorlevel 1 goto failed
copy /y "requirements.txt" ".venv\requirements.installed.txt" >nul
if errorlevel 1 goto failed
echo.
echo  Checking the updated install ...
echo.
".venv\Scripts\python.exe" -m plumbline doctor
if errorlevel 1 goto failed

rem --- 4. Start Plumbline ---
:launch
echo.
echo  Starting Plumbline ...
"%PLB_PY%" -m plumbline %*
set "PLB_EXIT=%ERRORLEVEL%"
if "%PLB_EXIT%"=="0" exit /b 0
echo.
echo  Plumbline stopped with an error. The code was %PLB_EXIT%.
echo  Scroll up to read the message, and send me the text.
echo.
pause
exit /b %PLB_EXIT%

:nopython
echo  Python 3.13 or 3.14 was not found on this computer.
echo.
echo    1. Download the 64-bit installer from
echo         https://www.python.org/downloads/release/python-3148/
echo       (3.14 is the version Plumbline is tested on; 3.13 also works.)
echo       Scroll down to Files and pick: Windows installer 64-bit
echo    2. Run it. Tick the box Add python.exe to PATH, then click Install Now.
echo    3. Double-click this file again.
echo.
echo  Using the Python install manager instead? Open PowerShell and type: py install 3.14
echo  The step-by-step guide is docs\WINDOWS_SETUP.md
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
