@echo off
title Nova Launcher - Build Tool
echo =======================================
echo      Nova Launcher - EXE Builder
echo =======================================
echo.
echo This will compile NovaLauncher.exe (no Python needed to run it).
echo Requires Python installed on THIS machine to build.
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Install from https://python.org
    pause & exit /b 1
)

echo [1/3] Installing build dependencies...
pip install pyinstaller customtkinter minecraft-launcher-lib requests pillow --quiet --upgrade
if errorlevel 1 ( echo [ERROR] pip failed. & pause & exit /b 1 )

echo.
echo [2/3] Preparing icon...
if exist "%~dp0icon.ico" (
    echo [*] icon.ico found - rebuilding with all sizes...
    python "%~dp0fix_icon.py"
) else (
    echo [*] No icon.ico found - using default PyInstaller icon.
)

echo.
echo [3/3] Compiling to EXE (this takes 1-3 minutes)...
python -m PyInstaller --noconfirm NovaLauncher.spec

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Try running as Administrator.
    pause & exit /b 1
)

echo.
echo Done!
echo.
echo =======================================
echo  NovaLauncher.exe is in: dist\
echo  Copy that single file anywhere - no
echo  Python needed to run it!
echo =======================================
echo.

explorer dist
pause
