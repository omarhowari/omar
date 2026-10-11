@echo off
REM Run TDA from source (no build needed)
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
start "" pythonw main.py
