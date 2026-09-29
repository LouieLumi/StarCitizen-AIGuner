@echo off
rem AI Gunner: start enabled with auto fire (auto lock, track, fire).
rem Control it with the floating panel (fire control / weapons switches).
rem Close this window to quit.
cd /d "%~dp0"
.venv\Scripts\python.exe host\main.py --enable --auto-fire
pause
