@echo off
title J.A.R.V.I.S. (console)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First-time setup: installing Jarvis...
    python -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
".venv\Scripts\python.exe" run.py --console %*
pause
