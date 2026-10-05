@echo off
rem  Starts Plumbline. Double-click it, or run it from a terminal:
rem      Plumbline.bat                           opens the program
rem      Plumbline.bat job.plb                   opens that project
rem      Plumbline.bat doctor                    checks the installation
rem      Plumbline.bat info job.plb              prints a project summary
rem      Plumbline.bat export-dxf job.plb out.dxf
rem  You can also drag a .plb file onto this file.
setlocal
set "PLB_PY=%~dp0.venv\Scripts\python.exe"
if exist "%PLB_PY%" goto ready
echo.
echo  Plumbline is not set up yet.
echo  Double-click install_windows.bat first, then try again.
echo.
pause
exit /b 1

:ready
rem  Other GIS programs sometimes set these for the whole PC. Plumbline brings its own copies.
set "PROJ_LIB="
set "PROJ_DATA="
set "GDAL_DATA="
set "GDAL_DRIVER_PATH="
"%PLB_PY%" -m plumbline %*
set "PLB_EXIT=%ERRORLEVEL%"
if "%PLB_EXIT%"=="0" exit /b 0
echo.
echo  Plumbline stopped with an error. The code was %PLB_EXIT%.
echo  Scroll up to read the message, and send me the text.
echo.
pause
exit /b %PLB_EXIT%
