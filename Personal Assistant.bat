@echo off
rem Personal Assistant: installs itself on the first run, then starts.
title Personal Assistant
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First-time setup: installing the Personal Assistant...
    python -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
if not exist "assets\jarvis.ico" ".venv\Scripts\python.exe" run.py --install
start "" ".venv\Scripts\pythonw.exe" run.py --app %*
