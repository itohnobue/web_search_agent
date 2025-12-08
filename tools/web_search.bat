@echo off
REM Wrapper script for web_research.py using uv (Windows)

setlocal EnableDelayedExpansion

REM Get the directory where this script is located
set "SCRIPT_DIR=%~dp0"
REM Remove trailing backslash
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM Check if uv is available
where uv >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Installing uv... >&2
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    REM Add uv to PATH for this session
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)

REM Set UTF-8 encoding for proper Unicode handling
set PYTHONIOENCODING=utf-8

REM Run with inline dependencies (defined in web_research.py)
uv run "%SCRIPT_DIR%\web_research.py" %*
