@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
if not exist "data.xml" (
  echo data.xml not found.
  pause
  exit /b 1
)
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto py_launcher
python -c "import sys" >nul 2>nul
if not errorlevel 1 goto python_command
echo Python 3 not found.
echo Install 64-bit Python 3 from python.org, enable Add Python to PATH,
echo then run this file again.
pause
exit /b 1

:py_launcher
py -3 viewer.py --open-browser
goto done

:python_command
python viewer.py --open-browser

:done
if errorlevel 1 pause
