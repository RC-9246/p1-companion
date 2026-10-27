@echo off
chcp 65001 >nul
setlocal
if not exist "%~dp0deploy\windows-setup.ps1" (
  echo 请先解压完整项目，再双击这个文件。
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows-setup.ps1"
if errorlevel 1 pause
endlocal
