@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-lr-windows.ps1" %*
if errorlevel 1 (
  echo.
  echo Arthra LR Windows 启动失败，请查看上方错误或 .local-dev\logs 下的日志。
  pause
)
