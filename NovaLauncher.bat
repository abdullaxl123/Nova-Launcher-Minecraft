@echo off
title Nova Launcher

:: ── DPI fix for Win 11 (must happen before any window spawns) ──────────────
reg add "HKCU\Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers" ^
    /v "%~dp0launcher.py" /t REG_SZ /d "~ HIGHDPIAWARE" /f >nul 2>&1

:: ── Check Python is available ───────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Install Python 3.10+ from https://python.org
    echo Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

:: ── Install deps only when the marker file is missing or requirements changed ─
set MARKER=%~dp0.deps_installed
set REQS=%~dp0requirements.txt

:: Hash requirements into marker so re-installs happen if reqs change
for /f "tokens=*" %%i in ('python -c "import hashlib,sys; print(hashlib.md5(open(sys.argv[1],'rb').read()).hexdigest())" "%REQS%" 2^>nul') do set REQS_HASH=%%i

set MARKER_HASH=
if exist "%MARKER%" (
    set /p MARKER_HASH=<"%MARKER%"
)

if "%REQS_HASH%"=="%MARKER_HASH%" (
    :: Deps already installed for this exact requirements.txt - skip pip entirely
    goto launch
)

echo [*] Installing dependencies (first run or requirements changed)...
pip install -r "%REQS%" --quiet
if errorlevel 1 (
    echo [ERROR] pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo %REQS_HASH%>"%MARKER%"
echo [*] Dependencies installed.

:launch
:: ── Launch with pythonw so no console window flickers/blocks ────────────────
start "" pythonw "%~dp0launcher.py"
