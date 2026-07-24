@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" >nul
set "ARTHRA_ROOT=%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$script = Get-Content -LiteralPath '%~dp0start-lr-windows.ps1' -Raw -Encoding UTF8; & ([ScriptBlock]::Create($script)) %*"
if errorlevel 1 (
  echo.
  echo Arthra LR Windows 启动失败，请查看上方错误或 .local-dev\logs 下的日志。
  pause
)
popd >nul
