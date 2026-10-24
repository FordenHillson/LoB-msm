@echo off
cd /d "%~dp0"
python -c "import faster_whisper, numpy" 2>nul
if errorlevel 1 (
    echo Installing requirements for this Python...
    python -m pip install -r requirements.txt
    if errorlevel 1 pause
)
python gui.py
if errorlevel 1 pause
