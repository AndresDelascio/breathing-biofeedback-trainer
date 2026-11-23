@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" app\trainer.py
  goto done
)
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 app\trainer.py
goto done
:use_python
python app\trainer.py
:done
if errorlevel 1 pause
