@echo off
cd /d "%~dp0"
python "图片批量压缩工具.py"
if errorlevel 1 (
  echo.
  echo [Error] Failed to start. Please install dependencies first:
  echo   python -m pip install pywebview pillow
  pause
)
