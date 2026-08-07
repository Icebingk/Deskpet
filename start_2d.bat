@echo off
cd /d "%~dp0"
python -c "import pygame, PIL" >nul 2>&1
if errorlevel 1 (
    echo Missing dependencies. Run: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
python deskpet2d.py
if errorlevel 1 pause
