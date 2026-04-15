@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Fallback repo root for shared portfolio/comparison scripts when this launcher
REM is copied to an external MT5 folder.
if not defined TRADING_TOOLS_PROJECT_ROOT set "TRADING_TOOLS_PROJECT_ROOT=C:\Users\sammj\Projects\trading-tools"

REM Set to 1 only if you want pause prompts when double-clicking the .cmd.
if not defined KEEP_WINDOW_OPEN set KEEP_WINDOW_OPEN=1

cd /d "%~dp0"

REM =============================================================================
REM  Full flow: trades-period comparison + 1-year portfolio
REM
REM  Phase 1 — Short backtest (trades CSV date range) on BOTH brokers, then
REM             compare both broker backtests against your real trades to see
REM             which broker's data quality matches live trading more closely.
REM
REM  Phase 2 — Full 1-year backtest on the SECOND broker (e.g. Darwinex), then
REM             run the portfolio risk analysis.
REM =============================================================================

REM ─────────────────────────────────────────────────────────────────────────────
REM  Required: ONE MT5 portable terminal folder INSIDE THIS PROJECT FOLDER.
REM  This launcher is intended to be run from this project folder only.
REM  Broker A/B account switching is done via Login/Password/Server in generated
REM  tester INI files, so both runs use the same terminal installation.
REM ─────────────────────────────────────────────────────────────────────────────

set "MT5_TERMINAL_DIR="

REM Auto-detect the FIRST terminal64.exe in any subfolder:
if "%MT5_TERMINAL_DIR%"=="" (
  for /d %%D in (*) do (
    if exist "%%~fD\terminal64.exe" (
      if not defined MT5_TERMINAL_DIR set "MT5_TERMINAL_DIR=%%~fD"
    )
  )
)

if "%MT5_TERMINAL_DIR%"=="" (
  echo ERROR: Could not auto-detect MT5 terminal folder.
  echo Set MT5_TERMINAL_DIR manually above.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)

REM ─────────────────────────────────────────────────────────────────────────────
REM  Labels (used in report headings and file names)
REM ─────────────────────────────────────────────────────────────────────────────

set BROKER_A_LABEL=BlackBull
set BROKER_B_LABEL=Darwinex

REM Broker A account credentials (only required when RUN_COMPARISON=1).
set "BROKER_A_LOGIN=501167"
set "BROKER_A_PASSWORD=??P2zhdA"
set "BROKER_A_SERVER=iFunds-Server"

REM Broker B account credentials are prompted before running.
set "BROKER_B_LOGIN=4000074342"
set "BROKER_B_PASSWORD=!yW9$Cb$8"
set "BROKER_B_SERVER=Darwinex-Live"

REM Default behavior: skip comparison unless explicitly enabled.
REM EA_OVERRIDE is OPTIONAL only. Leave it blank to auto-detect the actual
REM trading EA(s) from the MT5 chart/log activity. Helper EAs such as
REM SpaceTracker, Update-Robots, and FxBlue are ignored.
set RUN_COMPARISON=0
set "EA_OVERRIDE="
set PROMPT_BROKER_DETAILS=1
set PREVIEW_BEFORE_RUN=1

if "%PROMPT_BROKER_DETAILS%"=="1" (
  echo.
  echo ============================================================
  echo  Enter broker details before any MT5 run begins
  echo ============================================================
  echo.
  if "%RUN_COMPARISON%"=="1" (
    if "%BROKER_A_LOGIN%"=="" set /p BROKER_A_LOGIN=Broker A login: 
    if "%BROKER_A_PASSWORD%"=="" set /p BROKER_A_PASSWORD=Broker A password: 
    if "%BROKER_A_SERVER%"=="" set /p BROKER_A_SERVER=Broker A server: 
  )
  if "%BROKER_B_LOGIN%"=="" set /p BROKER_B_LOGIN=Broker B login: 
  if "%BROKER_B_PASSWORD%"=="" set /p BROKER_B_PASSWORD=Broker B password: 
  if "%BROKER_B_SERVER%"=="" set /p BROKER_B_SERVER=Broker B server: 
)

if "%RUN_COMPARISON%"=="1" (
  if "%BROKER_A_LOGIN%"=="" (
    echo ERROR: BROKER_A_LOGIN is empty.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )
  if "%BROKER_A_PASSWORD%"=="" (
    echo ERROR: BROKER_A_PASSWORD is empty.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )
  if "%BROKER_A_SERVER%"=="" (
    echo ERROR: BROKER_A_SERVER is empty.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )
  if "%BROKER_B_LOGIN%"=="" (
    echo ERROR: BROKER_B_LOGIN is empty.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )
  if "%BROKER_B_PASSWORD%"=="" (
    echo ERROR: BROKER_B_PASSWORD is empty.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )
  if "%BROKER_B_SERVER%"=="" (
    echo ERROR: BROKER_B_SERVER is empty.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )
)
if not "%BROKER_B_LOGIN%"=="" if "%BROKER_B_PASSWORD%"=="" (
  echo ERROR: BROKER_B_PASSWORD is empty.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)
if not "%BROKER_B_LOGIN%"=="" if "%BROKER_B_SERVER%"=="" (
  echo ERROR: BROKER_B_SERVER is empty.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)
if not "%BROKER_B_PASSWORD%"=="" if "%BROKER_B_LOGIN%"=="" (
  echo ERROR: BROKER_B_LOGIN is empty.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)

REM ─────────────────────────────────────────────────────────────────────────────
REM  Data directories
REM ─────────────────────────────────────────────────────────────────────────────

REM Bars and tick data directory (for portfolio equity-curve building):
set BARS_DIR=D:\SEIF_system_new\5year\Data\darwinex
set TICKS_DIR=D:\SEIF_system_new\5year\Data\darwinex

REM Tick data for the stage1 comparison (may be the same folder, or a shorter
REM 1-year dataset if you have one):
set COMPARE_TICKS_DIR=D:\SEIF_system_new\3months\dukas

REM ─────────────────────────────────────────────────────────────────────────────
REM  Real trades CSV (the file containing your actual live account trades)
REM ─────────────────────────────────────────────────────────────────────────────

set "TRADES_CSV=%~dp0trades.csv"
REM Default to live chart detection from MT5 terminal logs so preflight shows
REM the charts/EAs that were actually loaded after login.
set "DETECT_SOURCE=terminal_logs"
set MIN_DETECTED_TRADES=1

REM Stage1 comparison symbol mapping.
REM Default behavior is automatic: leave COMPARE_SYMBOL blank.
REM Mapping strips broker suffix/punctuation and uses clean 6-letter pairs.
REM Examples:
REM   EURJPYp  -> EURJPY
REM   EURJPY.i -> EURJPY
REM   EURUSDp  -> EURUSD
REM   USDJPYp  -> USDJPY
REM Set COMPARE_SYMBOL only if you want to force one symbol for all strategies.
set COMPARE_SYMBOL=

REM ─────────────────────────────────────────────────────────────────────────────
REM  File naming
REM ─────────────────────────────────────────────────────────────────────────────

set BACKTEST_SUFFIX=.htm
set BARS_SUFFIX=_GMT+2_US-DST_M5.csv
set TICKS_SUFFIX=_GMT+2_US-DST.csv
set TICK_GMT=2

REM ─────────────────────────────────────────────────────────────────────────────
REM  Risk and account settings
REM ─────────────────────────────────────────────────────────────────────────────

set ACCOUNT_SIZE=10000
set DD_TOLERANCE=10
set BROKER_GMT=2
set DEFAULT_SCALE=1.0

REM ─────────────────────────────────────────────────────────────────────────────
REM  MT5 tester settings (used for BOTH the short-period and 5-year backtests)
REM ─────────────────────────────────────────────────────────────────────────────

set TESTER_PERIOD=
set TESTER_MODEL=4
set TESTER_DELAY_MS=50
set TESTER_ORDER_FILLING=AUTO
set TESTER_DEPOSIT=%ACCOUNT_SIZE%
set TESTER_LEVERAGE=100
set TESTER_USE_LOCAL=1
set USE_LIVE_EA_SETTINGS=1

REM 1-year backtest window (used for Phase 2):
set TESTER_FROM=
set TESTER_TO=

if "%TESTER_FROM%"=="" for /f %%I in ('powershell -NoProfile -Command "(Get-Date).AddYears(-1).ToString('yyyy.MM.dd')"') do set "TESTER_FROM=%%I"
if "%TESTER_TO%"==""   for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy.MM.dd')"')            do set "TESTER_TO=%%I"

REM ─────────────────────────────────────────────────────────────────────────────
REM  Output
REM ─────────────────────────────────────────────────────────────────────────────

set "OUT_ROOT=%~dp0runs"
set CLEAN_OLD_RUNS=1
set CURVE_SOURCES=bars

REM =============================================================================
REM  PHASE 1 — Short-period backtest on both brokers + stage1 comparison
REM
REM  Uses the date range extracted from TRADES_CSV.
REM  Runs: Broker A period backtest → Broker B period backtest → comparison.
REM =============================================================================

if "%CLEAN_OLD_RUNS%"=="1" (
  if exist "%OUT_ROOT%" rmdir /s /q "%OUT_ROOT%"
)
if not exist "%OUT_ROOT%" mkdir "%OUT_ROOT%"

if "%PREVIEW_BEFORE_RUN%"=="1" (
  echo.
  echo ============================================================
  echo  PREFLIGHT CHECK: planned backtests for this portfolio
  echo ============================================================
  echo.

  set PREVIEW_CMD=python ".\mt5_account_risk_flow.py"
  set PREVIEW_CMD=!PREVIEW_CMD! --account-label "%BROKER_B_LABEL%"
  set PREVIEW_CMD=!PREVIEW_CMD! --out-root "%OUT_ROOT%"
  set PREVIEW_CMD=!PREVIEW_CMD! --detect-source %DETECT_SOURCE%
  set PREVIEW_CMD=!PREVIEW_CMD! --min-trades %MIN_DETECTED_TRADES%
  if exist "%TRADES_CSV%" set PREVIEW_CMD=!PREVIEW_CMD! --mt5-csv "%TRADES_CSV%"
  set PREVIEW_CMD=!PREVIEW_CMD! --mt5-terminal-dir "%MT5_TERMINAL_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --bars-dir "%BARS_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --ticks-dir "%TICKS_DIR%"
  set PREVIEW_CMD=!PREVIEW_CMD! --preview-plan
  if not "%TESTER_PERIOD%"=="" set PREVIEW_CMD=!PREVIEW_CMD! --tester-period %TESTER_PERIOD%
  if not "%EA_OVERRIDE%"=="" set PREVIEW_CMD=!PREVIEW_CMD! --default-ea "%EA_OVERRIDE%"

  echo Running preflight: !PREVIEW_CMD!
  echo.
  !PREVIEW_CMD!

  if errorlevel 1 (
    echo.
    echo ERROR: Preflight check failed. Review output above.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )

  choice /m "Proceed with the MT5 run"
  if errorlevel 2 exit /b 0
)

if "%RUN_COMPARISON%"=="1" (
  echo.
  echo ============================================================
  echo  PHASE 1: Trades-period backtests on both brokers plus comparison
  echo  Terminal : %MT5_TERMINAL_DIR%
  echo  Broker A : %BROKER_A_LABEL% - %BROKER_A_LOGIN% @ %BROKER_A_SERVER%
  echo  Broker B : %BROKER_B_LABEL% - %BROKER_B_LOGIN% @ %BROKER_B_SERVER%
  echo  Trades   : %TRADES_CSV%
  echo ============================================================
  echo.

  set P1_CMD=python ".\mt5_account_risk_flow.py"
  set P1_CMD=!P1_CMD! --account-label "%BROKER_A_LABEL%"
  set P1_CMD=!P1_CMD! --out-root "%OUT_ROOT%"
  set P1_CMD=!P1_CMD! --detect-source %DETECT_SOURCE%
  set P1_CMD=!P1_CMD! --min-trades %MIN_DETECTED_TRADES%
  if exist "%TRADES_CSV%" set P1_CMD=!P1_CMD! --mt5-csv "%TRADES_CSV%"
  if exist "%TRADES_CSV%" set P1_CMD=!P1_CMD! --trades-csv "%TRADES_CSV%"
  set P1_CMD=!P1_CMD! --mt5-terminal-dir "%MT5_TERMINAL_DIR%"
  set P1_CMD=!P1_CMD! --second-broker-label "%BROKER_B_LABEL%"
  set P1_CMD=!P1_CMD! --broker-a-login "%BROKER_A_LOGIN%"
  set P1_CMD=!P1_CMD! --broker-a-password "%BROKER_A_PASSWORD%"
  set P1_CMD=!P1_CMD! --broker-a-server "%BROKER_A_SERVER%"
  set P1_CMD=!P1_CMD! --broker-b-login "%BROKER_B_LOGIN%"
  set P1_CMD=!P1_CMD! --broker-b-password "%BROKER_B_PASSWORD%"
  set P1_CMD=!P1_CMD! --broker-b-server "%BROKER_B_SERVER%"
  set P1_CMD=!P1_CMD! --run-trades-period-backtests
  set P1_CMD=!P1_CMD! --run-comparison-now
  set P1_CMD=!P1_CMD! --compare-ticks-dir "%COMPARE_TICKS_DIR%"
  set P1_CMD=!P1_CMD! --compare-broker-gmt %BROKER_GMT%
  set P1_CMD=!P1_CMD! --compare-tick-gmt %TICK_GMT%
  set P1_CMD=!P1_CMD! --bars-dir "%BARS_DIR%"
  set P1_CMD=!P1_CMD! --ticks-dir "%TICKS_DIR%"
  set P1_CMD=!P1_CMD! --backtest-suffix "%BACKTEST_SUFFIX%"
  set P1_CMD=!P1_CMD! --bars-suffix "%BARS_SUFFIX%"
  set P1_CMD=!P1_CMD! --tick-suffix "%TICKS_SUFFIX%"
  set P1_CMD=!P1_CMD! --tick-gmt %TICK_GMT%
  set P1_CMD=!P1_CMD! --curve-sources "%CURVE_SOURCES%"
  set P1_CMD=!P1_CMD! --account-size %ACCOUNT_SIZE%
  set P1_CMD=!P1_CMD! --dd-tolerance %DD_TOLERANCE%
  set P1_CMD=!P1_CMD! --broker-gmt %BROKER_GMT%
  set P1_CMD=!P1_CMD! --default-scale %DEFAULT_SCALE%
  set P1_CMD=!P1_CMD! --tester-model %TESTER_MODEL%
  set P1_CMD=!P1_CMD! --tester-delay-ms %TESTER_DELAY_MS%
  set P1_CMD=!P1_CMD! --tester-order-filling %TESTER_ORDER_FILLING%
  set P1_CMD=!P1_CMD! --tester-deposit %TESTER_DEPOSIT%
  set P1_CMD=!P1_CMD! --tester-leverage %TESTER_LEVERAGE%
  set P1_CMD=!P1_CMD! --title "Trades-Period Backtest — %BROKER_A_LABEL% vs %BROKER_B_LABEL%"

  if not "%TESTER_PERIOD%"=="" set P1_CMD=!P1_CMD! --tester-period %TESTER_PERIOD%
  if not "%COMPARE_SYMBOL%"=="" set P1_CMD=!P1_CMD! --compare-symbol "%COMPARE_SYMBOL%"
  if not "%EA_OVERRIDE%"=="" set P1_CMD=!P1_CMD! --default-ea "%EA_OVERRIDE%"
  if "%TESTER_USE_LOCAL%"=="1" set P1_CMD=!P1_CMD! --tester-use-local
  if not "%USE_LIVE_EA_SETTINGS%"=="1" set P1_CMD=!P1_CMD! --skip-live-ea-settings

  echo Running Phase 1: !P1_CMD!
  echo.
  !P1_CMD!

  if errorlevel 1 (
    echo.
    echo ERROR: Phase 1 failed. Review output above.
    if "%KEEP_WINDOW_OPEN%"=="1" pause
    exit /b 1
  )

  echo.
  echo Phase 1 complete.
  echo.
) else (
  echo.
  echo ============================================================
  echo  PHASE 1 skipped ^(RUN_COMPARISON=0^)
  echo ============================================================
  echo.
)

REM =============================================================================
REM  PHASE 2 — 1-year backtest on Broker B + portfolio risk analysis
REM
REM  Uses the full TESTER_FROM / TESTER_TO window (default: last 1 year).
REM  Only the second broker (Darwinex) terminal is used here.
REM =============================================================================

echo ============================================================
echo  PHASE 2: 1-year backtest on %BROKER_B_LABEL% + portfolio
echo  Terminal : %MT5_TERMINAL_DIR%
echo  Account  : %BROKER_B_LOGIN% @ %BROKER_B_SERVER%
echo  Period   : %TESTER_FROM% to %TESTER_TO%
echo ============================================================
echo.

set P2_CMD=python ".\mt5_account_risk_flow.py"
set P2_CMD=%P2_CMD% --account-label "%BROKER_B_LABEL%"
set P2_CMD=%P2_CMD% --out-root "%OUT_ROOT%"
set P2_CMD=%P2_CMD% --detect-source %DETECT_SOURCE%
set P2_CMD=%P2_CMD% --min-trades %MIN_DETECTED_TRADES%
if exist "%TRADES_CSV%" set P2_CMD=%P2_CMD% --mt5-csv "%TRADES_CSV%"
set P2_CMD=%P2_CMD% --mt5-terminal-dir "%MT5_TERMINAL_DIR%"
set P2_CMD=%P2_CMD% --run-backtests-now
set P2_CMD=%P2_CMD% --run-portfolio-now
if not "%BROKER_B_LOGIN%"=="" set P2_CMD=%P2_CMD% --tester-login "%BROKER_B_LOGIN%"
if not "%BROKER_B_PASSWORD%"=="" set P2_CMD=%P2_CMD% --tester-password "%BROKER_B_PASSWORD%"
if not "%BROKER_B_SERVER%"=="" set P2_CMD=%P2_CMD% --tester-server "%BROKER_B_SERVER%"
set P2_CMD=%P2_CMD% --tester-from %TESTER_FROM%
set P2_CMD=%P2_CMD% --tester-to %TESTER_TO%
set P2_CMD=%P2_CMD% --bars-dir "%BARS_DIR%"
set P2_CMD=%P2_CMD% --ticks-dir "%TICKS_DIR%"
set P2_CMD=%P2_CMD% --backtest-suffix "%BACKTEST_SUFFIX%"
set P2_CMD=%P2_CMD% --bars-suffix "%BARS_SUFFIX%"
set P2_CMD=%P2_CMD% --tick-suffix "%TICKS_SUFFIX%"
set P2_CMD=%P2_CMD% --tick-gmt %TICK_GMT%
set P2_CMD=%P2_CMD% --curve-sources "%CURVE_SOURCES%"
set P2_CMD=%P2_CMD% --account-size %ACCOUNT_SIZE%
set P2_CMD=%P2_CMD% --dd-tolerance %DD_TOLERANCE%
set P2_CMD=%P2_CMD% --broker-gmt %BROKER_GMT%
set P2_CMD=%P2_CMD% --default-scale %DEFAULT_SCALE%
set P2_CMD=%P2_CMD% --tester-model %TESTER_MODEL%
set P2_CMD=%P2_CMD% --tester-delay-ms %TESTER_DELAY_MS%
set P2_CMD=%P2_CMD% --tester-order-filling %TESTER_ORDER_FILLING%
set P2_CMD=%P2_CMD% --tester-deposit %TESTER_DEPOSIT%
set P2_CMD=%P2_CMD% --tester-leverage %TESTER_LEVERAGE%
set P2_CMD=%P2_CMD% --title "1-Year Portfolio Risk — %BROKER_B_LABEL%"

if not "%TESTER_PERIOD%"=="" set P2_CMD=%P2_CMD% --tester-period %TESTER_PERIOD%
if not "%EA_OVERRIDE%"=="" set P2_CMD=%P2_CMD% --default-ea "%EA_OVERRIDE%"
if "%TESTER_USE_LOCAL%"=="1" set P2_CMD=%P2_CMD% --tester-use-local
if not "%USE_LIVE_EA_SETTINGS%"=="1" set P2_CMD=%P2_CMD% --skip-live-ea-settings

echo Running Phase 2: %P2_CMD%
echo.
%P2_CMD%

if errorlevel 1 (
  echo.
  echo ERROR: Phase 2 failed. Review output above.
  if "%KEEP_WINDOW_OPEN%"=="1" pause
  exit /b 1
)

set "PHASE1_RUN="
for /f "delims=" %%D in ('dir /b /ad /o-n "%OUT_ROOT%\*_BlackBull" 2^>nul') do (
  if not defined PHASE1_RUN set "PHASE1_RUN=%OUT_ROOT%\%%D"
)
set "PHASE2_RUN="
for /f "delims=" %%D in ('dir /b /ad /o-n "%OUT_ROOT%\*_Darwinex" 2^>nul') do (
  if not defined PHASE2_RUN set "PHASE2_RUN=%OUT_ROOT%\%%D"
)

set "FINAL_REVIEW_DIR=%OUT_ROOT%\FINAL_REVIEW_BUNDLE"
if exist "%FINAL_REVIEW_DIR%" rmdir /s /q "%FINAL_REVIEW_DIR%"
mkdir "%FINAL_REVIEW_DIR%"
if defined PHASE1_RUN if exist "%PHASE1_RUN%\review_bundle" xcopy /y /i /s "%PHASE1_RUN%\review_bundle\*" "%FINAL_REVIEW_DIR%\" >nul
if defined PHASE2_RUN if exist "%PHASE2_RUN%\review_bundle" xcopy /y /i /s "%PHASE2_RUN%\review_bundle\*" "%FINAL_REVIEW_DIR%\" >nul

echo.
echo ============================================================
echo  ALL PHASES COMPLETE
echo.
echo  Final review bundle: %FINAL_REVIEW_DIR%
echo  Phase 1 output       : %PHASE1_RUN%
echo  Phase 2 output       : %PHASE2_RUN%
echo ============================================================
echo.
if "%KEEP_WINDOW_OPEN%"=="1" pause
endlocal
