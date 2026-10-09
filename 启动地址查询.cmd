@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto pylauncher
where python >nul 2>nul
if not errorlevel 1 goto pythonpath
echo Python 3.10+ is required. Download from https://www.python.org/downloads/
pause
exit /b 1
:pylauncher
py -3 -X utf8 "%~dp0web_app.py"
goto finished
:pythonpath
python -X utf8 "%~dp0web_app.py"
:finished
if errorlevel 1 pause
endlocal
