@echo off
rem Saved as UTF-8 without BOM: chcp 65001 below makes cmd.exe read the Cyrillic
rem in the messages correctly. A BOM would break the first line of the script.
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

if "%VIEWER_SKIP_UPDATE%"=="1" goto after_update

rem Updates arrive by git pull, so a copy that cannot pull is stuck on whatever
rem version it was made from. Say so instead of starting up as if all is well.
where git >nul 2>nul
if errorlevel 1 (
  echo.
  echo [!] Git не установлен, поэтому эта копия не будет обновляться.
  echo     Установите Git с https://git-scm.com и запустите файл заново.
  echo.
  pause
  goto after_update
)
if not exist ".git" (
  echo.
  echo [!] Эта папка не является клоном Git, обновления приходить не будут.
  echo     Скорее всего, репозиторий скачали архивом. Замените папку на клон:
  echo         git clone https://github.com/ydap1/fns-viewer.git
  echo     и перенесите в неё data.xml.
  echo.
  pause
  goto after_update
)
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do set "REV_BEFORE=%%i"
echo Проверка обновлений...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [!] Обновиться не удалось — запускается версия, которая уже на диске.
  echo     Обычно причина в локальных правках или разошедшейся ветке,
  echo     точную покажет команда git status.
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
  echo.
  echo [!] Файл data.xml не найден в %CD%
  echo     База в репозиторий не входит — положите её в эту папку.
  echo.
  pause
  exit /b 1
)
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 goto py_launcher
python -c "import sys" >nul 2>nul
if not errorlevel 1 goto python_command
echo.
echo [!] Python 3 не найден.
echo     Установите 64-разрядный Python 3 с https://python.org,
echo     отметьте «Add Python to PATH» и запустите файл заново.
echo.
pause
exit /b 1

:py_launcher
py -3 viewer.py --open-browser
goto done

:python_command
python viewer.py --open-browser

:done
if errorlevel 1 pause
