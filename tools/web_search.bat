@echo off
REM Wrapper script for web_research.py using Python virtual environment (Windows)

setlocal EnableDelayedExpansion

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"
REM Remove trailing backslash
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Project dir is parent of tools dir
for %%I in ("%SCRIPT_DIR%\..") do set "PROJECT_DIR=%%~fI"

REM Path to the virtual environment
set "VENV_PATH=%PROJECT_DIR%\env-ai"

REM Check if venv exists
if not exist "%VENV_PATH%\Scripts\python.exe" (
    echo Creating Python virtual environment...
    python -m venv "%VENV_PATH%"
    echo Installing required packages (httpx, ddgs)...
    "%VENV_PATH%\Scripts\pip.exe" install -q httpx ddgs
)

REM Set UTF-8 encoding for proper Unicode handling
set PYTHONIOENCODING=utf-8

REM Run web_research.py with the virtual environment Python
"%VENV_PATH%\Scripts\python.exe" "%SCRIPT_DIR%\web_research.py" %*
