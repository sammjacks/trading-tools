@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not defined TRADING_TOOLS_PROJECT_ROOT set "TRADING_TOOLS_PROJECT_ROOT=C:\Users\sammj\Projects\trading-tools"
if not defined KEEP_WINDOW_OPEN set KEEP_WINDOW_OPEN=1

set "MT5_TERMINAL_DIR="
for /d %%D in (*) do (
  if exist "%%~fD\terminal64.exe" (
    if not defined MT5_TERMINAL_DIR set "MT5_TERMINAL_DIR=%%~fD"
  )
)

if "%MT5_TERMINAL_DIR%"=="" (
  echo ERROR: Could not auto-detect MT5 terminal folder.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)

REM ============================================================
REM  Minimal inputs for the backtests-only run
REM ============================================================
set BROKER_LABEL=Darwinex
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
set "EA_OVERRIDE="
set PROMPT_BROKER_DETAILS=1
set PREVIEW_BEFORE_RUN=1

if "%PROMPT_BROKER_DETAILS%"=="1" (
  echo.
  echo ============================================================
  echo  Enter broker details for backtests-only run
  echo ============================================================
  echo.
  if "%BROKER_LOGIN%"=="" set /p BROKER_LOGIN=Broker login: 
  if "%BROKER_PASSWORD%"=="" set /p BROKER_PASSWORD=Broker password: 
  if "%BROKER_SERVER%"=="" set /p BROKER_SERVER=Broker server: 
)

if "%BROKER_LOGIN%"=="" (
  echo ERROR: BROKER_LOGIN is empty.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)
if "%BROKER_PASSWORD%"=="" (
  echo ERROR: BROKER_PASSWORD is empty.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)
if "%BROKER_SERVER%"=="" (
  echo ERROR: BROKER_SERVER is empty.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)
REM Internal defaults used by the tool.
set "BARS_DIR=D:\SEIF_system_new\Michel_Start"
set "TICKS_DIR=D:\SEIF_system_new\Michel_Start"
set "OUT_ROOT=%~dp0saved_backtests"
set BROKER_GMT=2

if "%PREVIEW_BEFORE_RUN%"=="1" (
  echo.
  echo ============================================================
  echo  PREFLIGHT CHECK: backtests-only run
  echo ============================================================
  echo.

  set PREVIEW_CMD=python ".\account_review_flow.py"
  set PREVIEW_CMD=!PREVIEW_CMD! --account-label "%BROKER_LABEL%"
  set PREVIEW_CMD=!PREVIEW_CMD! --out-root "%OUT_ROOT%"
  set PREVIEW_CMD=!PREVIEW_CMD! --mt5-terminal-dir "%MT5_TERMINAL_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --bars-dir "%BARS_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --ticks-dir "%TICKS_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --broker-gmt %BROKER_GMT%
  set PREVIEW_CMD=!PREVIEW_CMD! --backtests-only --preview-plan
  if not "%REAL_MAGIC_FILTER%"=="" set PREVIEW_CMD=!PREVIEW_CMD! --magic-filter "%REAL_MAGIC_FILTER%"
  if not "%EA_OVERRIDE%"=="" set PREVIEW_CMD=!PREVIEW_CMD! --default-ea "%EA_OVERRIDE%"

  echo Running preflight: !PREVIEW_CMD!
  echo.
  !PREVIEW_CMD!

  if errorlevel 1 (
    echo.
    echo ERROR: Preflight failed. Review output above.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )

  choice /m "Proceed with the backtests-only run"
  if errorlevel 2 exit /b 0
)

echo.
echo ============================================================
echo  RUNNING BACKTESTS ONLY
echo  Terminal  : %MT5_TERMINAL_DIR%
echo  Broker    : %BROKER_LABEL% - %BROKER_LOGIN% @ %BROKER_SERVER%
echo  Output    : %OUT_ROOT%
echo ============================================================
echo.

set RUN_CMD=python ".\account_review_flow.py"
set RUN_CMD=!RUN_CMD! --account-label "%BROKER_LABEL%"
set RUN_CMD=!RUN_CMD! --out-root "%OUT_ROOT%"
set RUN_CMD=!RUN_CMD! --mt5-terminal-dir "%MT5_TERMINAL_DIR%"
set RUN_CMD=!RUN_CMD! --broker-login "%BROKER_LOGIN%"
set RUN_CMD=!RUN_CMD! --broker-password "%BROKER_PASSWORD%"
set RUN_CMD=!RUN_CMD! --broker-server "%BROKER_SERVER%"
set RUN_CMD=!RUN_CMD! --bars-dir "%BARS_DIR%"
set RUN_CMD=!RUN_CMD! --ticks-dir "%TICKS_DIR%"
set RUN_CMD=!RUN_CMD! --broker-gmt %BROKER_GMT%
set RUN_CMD=!RUN_CMD! --run-review-now --backtests-only --tester-use-local
if not "%REAL_MAGIC_FILTER%"=="" set RUN_CMD=!RUN_CMD! --magic-filter "%REAL_MAGIC_FILTER%"
if not "%EA_OVERRIDE%"=="" set RUN_CMD=!RUN_CMD! --default-ea "%EA_OVERRIDE%"

echo Running: !RUN_CMD!
echo.
!RUN_CMD!

if errorlevel 1 (
  echo.
  echo ERROR: Backtests-only run failed. Review output above.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)

echo.
echo Backtests-only run completed.
if "%KEEP_WINDOW_OPEN%"=="1" pause
exit /b 0
