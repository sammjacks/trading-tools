@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not defined TRADING_TOOLS_PROJECT_ROOT set "TRADING_TOOLS_PROJECT_ROOT=C:\Users\sammj\Projects\trading-tools"
if not defined KEEP_WINDOW_OPEN set KEEP_WINDOW_OPEN=1

REM Auto-detect the first MT5 portable terminal folder inside this project.
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
REM  Single-broker account review settings
REM ============================================================
set BROKER_LABEL=Darwinex
set "BROKER_LOGIN="
set "BROKER_PASSWORD="
set "BROKER_SERVER="

REM Safe credential override files. Use these for passwords with CMD special
REM characters such as %%%% or ! so the MT5 login is passed correctly.
set "BROKER_LOGIN_FILE=%~dp0broker_login.txt"
set "BROKER_PASSWORD_FILE=%~dp0broker_password.txt"
set "BROKER_SERVER_FILE=%~dp0broker_server.txt"
if exist "%BROKER_LOGIN_FILE%" set /p BROKER_LOGIN=<"%BROKER_LOGIN_FILE%"
if exist "%BROKER_PASSWORD_FILE%" set /p BROKER_PASSWORD=<"%BROKER_PASSWORD_FILE%"
if exist "%BROKER_SERVER_FILE%" set /p BROKER_SERVER=<"%BROKER_SERVER_FILE%"

REM Real account history statement (HTML or CSV). The current sample is Portfolio4.html.
set "REAL_STATEMENT=%~dp0Portfolio4.html"

REM Optional filter if you want to constrain the real statement further.
REM Leave blank unless you specifically want one magic number only.
set "REAL_MAGIC_FILTER="

REM Optional EA override only. Leave blank to auto-detect from live MT5 charts.
set "EA_OVERRIDE="

set PROMPT_BROKER_DETAILS=1
set PREVIEW_BEFORE_RUN=1

if "%PROMPT_BROKER_DETAILS%"=="1" (
  echo.
  echo ============================================================
  echo  Enter the single broker details for this review
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
if not exist "%REAL_STATEMENT%" (
  set "ALT_STATEMENT="
  if /I "!REAL_STATEMENT:~-5!"==".html" set "ALT_STATEMENT=!REAL_STATEMENT:~0,-1!"
  if /I "!REAL_STATEMENT:~-4!"==".htm" set "ALT_STATEMENT=!REAL_STATEMENT!l"
  if defined ALT_STATEMENT if exist "!ALT_STATEMENT!" (
    echo Using alternate real statement path: !ALT_STATEMENT!
    set "REAL_STATEMENT=!ALT_STATEMENT!"
  )
)
if not exist "%REAL_STATEMENT%" (
  echo ERROR: Real statement file not found: %REAL_STATEMENT%
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)

REM ============================================================
REM  Data and risk settings
REM ============================================================
set "BARS_DIR=D:\SEIF_system_new\Michel_Start"
set "TICKS_DIR=D:\SEIF_system_new\Michel_Start"
set "OUT_ROOT=%~dp0runs"

set ACCOUNT_SIZE=10000
set DD_TOLERANCE=10
set BROKER_GMT=2
set DEFAULT_SCALE=1.0

set TESTER_PERIOD=H1
set TESTER_MODEL=4
set TESTER_DELAY_MS=50
set TESTER_ORDER_FILLING=AUTO
set TESTER_DEPOSIT=%ACCOUNT_SIZE%
set TESTER_LEVERAGE=100
set TESTER_USE_LOCAL=1
set USE_LIVE_EA_SETTINGS=1

if "%PREVIEW_BEFORE_RUN%"=="1" (
  echo.
  echo ============================================================
  echo  PREFLIGHT CHECK: planned single-broker account review
  echo ============================================================
  echo.

  set PREVIEW_CMD=python ".\account_review_flow.py"
  set PREVIEW_CMD=!PREVIEW_CMD! --statement-file "%REAL_STATEMENT%"
  set PREVIEW_CMD=!PREVIEW_CMD! --account-label "%BROKER_LABEL%"
  set PREVIEW_CMD=!PREVIEW_CMD! --out-root "%OUT_ROOT%"
  set PREVIEW_CMD=!PREVIEW_CMD! --mt5-terminal-dir "%MT5_TERMINAL_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --bars-dir "%BARS_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --ticks-dir "%TICKS_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --broker-gmt %BROKER_GMT%
  set PREVIEW_CMD=!PREVIEW_CMD! --compare-broker-gmt %BROKER_GMT%
  set PREVIEW_CMD=!PREVIEW_CMD! --compare-tick-gmt %BROKER_GMT%
  set PREVIEW_CMD=!PREVIEW_CMD! --tester-period %TESTER_PERIOD%
  set PREVIEW_CMD=!PREVIEW_CMD! --preview-plan
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

  choice /m "Proceed with the full account review"
  if errorlevel 2 exit /b 0
)

echo.
echo ============================================================
echo  RUNNING SINGLE-BROKER ACCOUNT REVIEW
echo  Terminal  : %MT5_TERMINAL_DIR%
echo  Statement : %REAL_STATEMENT%
echo  Broker    : %BROKER_LABEL% - %BROKER_LOGIN% @ %BROKER_SERVER%
echo ============================================================
echo.

set RUN_CMD=python ".\account_review_flow.py"
set RUN_CMD=!RUN_CMD! --statement-file "%REAL_STATEMENT%"
set RUN_CMD=!RUN_CMD! --account-label "%BROKER_LABEL%"
set RUN_CMD=!RUN_CMD! --out-root "%OUT_ROOT%"
set RUN_CMD=!RUN_CMD! --mt5-terminal-dir "%MT5_TERMINAL_DIR%"
set RUN_CMD=!RUN_CMD! --broker-login "%BROKER_LOGIN%"
set RUN_CMD=!RUN_CMD! --broker-password "%BROKER_PASSWORD%"
set RUN_CMD=!RUN_CMD! --broker-server "%BROKER_SERVER%"
set RUN_CMD=!RUN_CMD! --bars-dir "%BARS_DIR%"
set RUN_CMD=!RUN_CMD! --ticks-dir "%TICKS_DIR%"
set RUN_CMD=!RUN_CMD! --account-size %ACCOUNT_SIZE%
set RUN_CMD=!RUN_CMD! --dd-tolerance %DD_TOLERANCE%
set RUN_CMD=!RUN_CMD! --broker-gmt %BROKER_GMT%
set RUN_CMD=!RUN_CMD! --compare-broker-gmt %BROKER_GMT%
set RUN_CMD=!RUN_CMD! --compare-tick-gmt %BROKER_GMT%
set RUN_CMD=!RUN_CMD! --default-scale %DEFAULT_SCALE%
set RUN_CMD=!RUN_CMD! --tester-period %TESTER_PERIOD%
set RUN_CMD=!RUN_CMD! --tester-model %TESTER_MODEL%
set RUN_CMD=!RUN_CMD! --tester-delay-ms %TESTER_DELAY_MS%
set RUN_CMD=!RUN_CMD! --tester-order-filling %TESTER_ORDER_FILLING%
set RUN_CMD=!RUN_CMD! --tester-deposit %TESTER_DEPOSIT%
set RUN_CMD=!RUN_CMD! --tester-leverage %TESTER_LEVERAGE%
set RUN_CMD=!RUN_CMD! --run-review-now --run-portfolio-now
if "%TESTER_USE_LOCAL%"=="1" set RUN_CMD=!RUN_CMD! --tester-use-local
if not "%USE_LIVE_EA_SETTINGS%"=="1" set RUN_CMD=!RUN_CMD! --skip-live-ea-settings
if not "%REAL_MAGIC_FILTER%"=="" set RUN_CMD=!RUN_CMD! --magic-filter "%REAL_MAGIC_FILTER%"
if not "%EA_OVERRIDE%"=="" set RUN_CMD=!RUN_CMD! --default-ea "%EA_OVERRIDE%"

echo Running: !RUN_CMD!
echo.
!RUN_CMD!

if errorlevel 1 (
  echo.
  echo ERROR: Account review failed. Review output above.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)

echo.
echo Account review completed.
if "%KEEP_WINDOW_OPEN%"=="1" pause
exit /b 0
