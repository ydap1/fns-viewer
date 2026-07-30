@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if "%VIEWER_SKIP_UPDATE%"=="1" goto after_update

rem Updates arrive by git pull, so a copy that cannot pull is stuck on whatever
rem version it was made from. Say so instead of starting up as if all is well.
where git >nul 2>nul
if errorlevel 1 (
  echo.
  echo [!] Git is not installed, so this copy cannot receive updates.
  echo     Install Git from https://git-scm.com and run this file again.
  echo.
  pause
  goto after_update
)
if not exist ".git" (
  echo.
  echo [!] This folder is not a Git clone, so it will never update.
  echo     It was probably downloaded as a ZIP. Replace it with:
  echo         git clone https://github.com/ydap1/fns-viewer.git
  echo     then move data.xml into the new folder.
  echo.
  pause
  goto after_update
)
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do set "REV_BEFORE=%%i"
echo Checking for updates...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [!] Update failed - starting the version already on disk.
  echo     Usually this means local edits or a diverged branch; `git status` says which.
  echo.
)
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do set "REV_AFTER=%%i"
if "%REV_BEFORE%"=="%REV_AFTER%" goto after_update
rem This file may have just been replaced, and cmd.exe reads it by byte offset,
rem so hand off to a fresh copy instead of continuing through stale lines.
set "VIEWER_SKIP_UPDATE=1"
cmd /c "%~f0"
exit /b %errorlevel%

:after_update
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
