@echo off
setlocal

cd /d "%~dp0"

REM ===== Required inputs =====
set ACCOUNT_LABEL=BuildMarkets_BlackBull
set BARS_DIR=D:\SEIF_system_new\5year\Data\darwinex
set TICKS_DIR=D:\SEIF_system_new\5year\Data\darwinex
set DETECT_SOURCE=terminal_logs

REM ===== MT5 terminal detection =====
REM Leave these blank to auto-detect a terminal folder next to this .cmd.
set MT5_TERMINAL_DIR=
set MT5_TERMINAL_EXE=

if "%MT5_TERMINAL_DIR%"=="" (
  for /d %%D in (*) do (
    if exist "%%~fD\terminal64.exe" (
      set "MT5_TERMINAL_DIR=%%~fD"
      goto :mt5_found
    )
  )
)

:mt5_found
if "%MT5_TERMINAL_DIR%"=="" (
  echo ERROR: Could not auto-detect MT5 terminal folder in %CD%
  echo Set MT5_TERMINAL_DIR manually to the folder that contains terminal64.exe
  echo.
  pause
  exit /b 1
)

if "%MT5_TERMINAL_EXE%"=="" if exist "%MT5_TERMINAL_DIR%\terminal64.exe" set "MT5_TERMINAL_EXE=%MT5_TERMINAL_DIR%\terminal64.exe"

REM ===== File naming conventions =====
set BACKTEST_SUFFIX=.html
set BARS_SUFFIX=_GMT+2_US-DST_M5.csv
set TICKS_SUFFIX=_GMT+2_US-DST.csv
set TICK_GMT=2
set DEFAULT_EA=

REM ===== Risk settings =====
set ACCOUNT_SIZE=10000
set DD_TOLERANCE=10
set BACKTEST_MONTHS=
set BROKER_GMT=2
set DEFAULT_SCALE=1.0

REM ===== MT5 tester settings =====
REM TESTER_PERIOD is auto-detected from the live EA logs (e.g. H1, M15).
REM Override here only if you need to force a specific timeframe.
set TESTER_PERIOD=
set TESTER_MODEL=4
set TESTER_DELAY_MS=50
set TESTER_ORDER_FILLING=AUTO

REM Leave blank to auto-fill: TESTER_FROM=today-5y, TESTER_TO=today
set TESTER_FROM=
set TESTER_TO=

if "%TESTER_FROM%"=="" for /f %%I in ('powershell -NoProfile -Command "(Get-Date).AddYears(-5).ToString('yyyy.MM.dd')"') do set "TESTER_FROM=%%I"
if "%TESTER_TO%"=="" for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy.MM.dd')"') do set "TESTER_TO=%%I"

set TESTER_DEPOSIT=10000
set TESTER_LEVERAGE=100
set TESTER_USE_LOCAL=1
set USE_LIVE_EA_SETTINGS=1

REM ===== Output =====
set OUT_ROOT=.\runs
set TITLE=MT5 Running Account Risk Check
set RUN_BACKTESTS_NOW=1
set RUN_NOW=0
set RUN_TICKS=0

set CURVE_SOURCES=bars
if "%RUN_TICKS%"=="1" set CURVE_SOURCES=bars,ticks

set CMD=python ".\mt5_account_risk_flow.py" --account-label "%ACCOUNT_LABEL%" --out-root "%OUT_ROOT%" --detect-source %DETECT_SOURCE% --bars-dir "%BARS_DIR%" --ticks-dir "%TICKS_DIR%" --backtest-suffix "%BACKTEST_SUFFIX%" --bars-suffix "%BARS_SUFFIX%" --tick-suffix "%TICKS_SUFFIX%" --tick-gmt %TICK_GMT% --curve-sources "%CURVE_SOURCES%" --account-size %ACCOUNT_SIZE% --dd-tolerance %DD_TOLERANCE% --broker-gmt %BROKER_GMT% --default-scale %DEFAULT_SCALE% --title "%TITLE%" --mt5-terminal-dir "%MT5_TERMINAL_DIR%" --tester-model %TESTER_MODEL% --tester-delay-ms %TESTER_DELAY_MS% --tester-order-filling %TESTER_ORDER_FILLING% --tester-from %TESTER_FROM% --tester-to %TESTER_TO% --tester-deposit %TESTER_DEPOSIT% --tester-leverage %TESTER_LEVERAGE%

if not "%TESTER_PERIOD%"=="" set CMD=%CMD% --tester-period %TESTER_PERIOD%

if not "%BACKTEST_MONTHS%"=="" set CMD=%CMD% --backtest-months %BACKTEST_MONTHS%
if not "%DEFAULT_EA%"=="" set CMD=%CMD% --default-ea "%DEFAULT_EA%"
if not "%MT5_TERMINAL_EXE%"=="" set CMD=%CMD% --mt5-terminal-exe "%MT5_TERMINAL_EXE%"
if "%TESTER_USE_LOCAL%"=="1" set CMD=%CMD% --tester-use-local
if not "%USE_LIVE_EA_SETTINGS%"=="1" set CMD=%CMD% --skip-live-ea-settings
if "%RUN_BACKTESTS_NOW%"=="1" set CMD=%CMD% --run-backtests-now
if "%RUN_NOW%"=="1" set CMD=%CMD% --run-portfolio-now

echo.
echo Using MT5_TERMINAL_DIR=%MT5_TERMINAL_DIR%
echo Using TESTER_FROM=%TESTER_FROM% TESTER_TO=%TESTER_TO%
echo Using CURVE_SOURCES=%CURVE_SOURCES% (set RUN_TICKS=1 to enable ticks)
echo Running: %CMD%
echo.
%CMD%

echo.
pause
endlocal
