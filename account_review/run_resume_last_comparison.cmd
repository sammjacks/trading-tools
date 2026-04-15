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

set "REAL_STATEMENT=%~dp0Portfolio4.html"
set "OUT_ROOT=%~dp0runs"
set "BARS_DIR=D:\SEIF_system_new\Michel_Start"
set "TICKS_DIR=D:\SEIF_system_new\Michel_Start"
set "BROKER_LABEL=Darwinex"
set "BROKER_LOGIN="
set "BROKER_PASSWORD="
set "BROKER_SERVER="
set "BROKER_LOGIN_FILE=%~dp0broker_login.txt"
set "BROKER_PASSWORD_FILE=%~dp0broker_password.txt"
set "BROKER_SERVER_FILE=%~dp0broker_server.txt"
if exist "%BROKER_LOGIN_FILE%" set /p BROKER_LOGIN=<"%BROKER_LOGIN_FILE%"
if exist "%BROKER_PASSWORD_FILE%" set /p BROKER_PASSWORD=<"%BROKER_PASSWORD_FILE%"
if exist "%BROKER_SERVER_FILE%" set /p BROKER_SERVER=<"%BROKER_SERVER_FILE%"
set "REAL_MAGIC_FILTER="
set "LAST_RUN="

for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-ChildItem -Directory ''%OUT_ROOT%'' | Sort-Object LastWriteTime -Descending | Select-Object -ExpandProperty FullName -First 1"') do set "LAST_RUN=%%I"

if "%LAST_RUN%"=="" (
  echo ERROR: Could not find a previous run folder under %OUT_ROOT%
  pause
  exit /b 1
)

echo.
echo ============================================================
echo  RESUMING LAST RUN: comparison + 5-year review
echo  Run folder : %LAST_RUN%
echo  Tick data  : %TICKS_DIR%
echo  Broker     : %BROKER_LABEL% - %BROKER_LOGIN% @ %BROKER_SERVER%
echo ============================================================
echo.

set RESUME_CMD=python ".\account_review_flow.py"
set RESUME_CMD=!RESUME_CMD! --statement-file "%REAL_STATEMENT%"
set RESUME_CMD=!RESUME_CMD! --account-label "%BROKER_LABEL%"
set RESUME_CMD=!RESUME_CMD! --out-root "%OUT_ROOT%"
set RESUME_CMD=!RESUME_CMD! --mt5-terminal-dir "%MT5_TERMINAL_DIR%"
set RESUME_CMD=!RESUME_CMD! --broker-login "%BROKER_LOGIN%"
set RESUME_CMD=!RESUME_CMD! --broker-password "%BROKER_PASSWORD%"
set RESUME_CMD=!RESUME_CMD! --broker-server "%BROKER_SERVER%"
set RESUME_CMD=!RESUME_CMD! --bars-dir "%BARS_DIR%"
set RESUME_CMD=!RESUME_CMD! --ticks-dir "%TICKS_DIR%"
set RESUME_CMD=!RESUME_CMD! --broker-gmt 2
set RESUME_CMD=!RESUME_CMD! --compare-broker-gmt 2
set RESUME_CMD=!RESUME_CMD! --compare-tick-gmt 2
set RESUME_CMD=!RESUME_CMD! --resume-run-dir "%LAST_RUN%"
set RESUME_CMD=!RESUME_CMD! --run-review-now --run-portfolio-now
if not "%REAL_MAGIC_FILTER%"=="" set RESUME_CMD=!RESUME_CMD! --magic-filter "%REAL_MAGIC_FILTER%"

echo Running: !RESUME_CMD!
echo.
!RESUME_CMD!

if errorlevel 1 (
  echo.
  echo ERROR: Resume comparison failed. Review output above.
  pause
  exit /b 1
)

echo.
echo Resume comparison completed.
pause
