@echo off
REM Pe3k launcher for Windows. Creates a virtual environment on first run.
REM Pe3k by heyziq05 - https://github.com/heyziq05
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtual environment...
  py -3 -m venv .venv || python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
python app.py
pause
