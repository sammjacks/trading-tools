@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not defined TRADING_TOOLS_PROJECT_ROOT set "TRADING_TOOLS_PROJECT_ROOT=C:\Users\sammj\Projects\trading-tools"

set "MT5_TERMINAL_DIR="
for /d %%D in (*) do (
  if exist "%%~fD\terminal64.exe" (
    if not defined MT5_TERMINAL_DIR set "MT5_TERMINAL_DIR=%%~fD"
  )
)

if "%MT5_TERMINAL_DIR%"=="" (
  echo ERROR: Could not auto-detect MT5 terminal folder.
  pause
  exit /b 1
)

python ".\account_review_flow.py" ^
  --statement-file "%~dp0Portfolio4.html" ^
  --account-label "AccountReview" ^
  --out-root "%~dp0runs" ^
  --mt5-terminal-dir "%MT5_TERMINAL_DIR%" ^
  --bars-dir "D:\SEIF_system_new\5year\Data\darwinex" ^
  --ticks-dir "D:\SEIF_system_new\5year\Data\darwinex" ^
  --broker-gmt 2 ^
  --compare-broker-gmt 2 ^
  --compare-tick-gmt 2 ^
  --preview-plan

pause
