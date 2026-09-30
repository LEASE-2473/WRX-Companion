@echo off
setlocal
cd /d "%~dp0"
title WRX Companion V2.0

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "BUNDLED_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if not exist "%PYTHON_EXE%" (
    if exist "%BUNDLED_PYTHON%" (
        echo [1/3] Creating virtual environment...
        "%BUNDLED_PYTHON%" -m venv .venv
        if errorlevel 1 goto :error
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo Python was not found. Install Python 3.11+ and try again.
            goto :error
        )
        echo [1/3] Creating virtual environment...
        python -m venv .venv
        if errorlevel 1 goto :error
    )
)

if not exist "%PYTHON_EXE%" goto :error

if not exist "%~dp0.venv\.companion_deps_installed" (
    echo [2/3] Installing dependencies...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
    type nul > "%~dp0.venv\.companion_deps_installed"
)

echo [3/3] Starting Companion...
echo Open http://127.0.0.1:2473 in your browser.
echo Press Ctrl+C to stop the server.
echo.
"%PYTHON_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 2473 --reload
goto :end

:error
echo.
echo Startup failed. Please copy this window's error and send it to Codex.
pause

:end
endlocal
