@echo off
cd /d "%~dp0"
REM ============================================================
REM  Step 1 — Live vs Backtest Comparison
REM
REM  Three modes depending on what you provide:
REM
REM    BOTH STATEMENT and BACKTEST set (full comparison):
REM      Loads both, auto-constrains the backtest to the live
REM      period, overlays their equity/balance curves, prints
REM      side-by-side stats, and saves a curve JSON for each
REM      leg (for later combining).
REM
REM    Only STATEMENT set (live-only baseline):
REM      Parses the live statement, builds its baseline curve
REM      and saves it as a combine-ready JSON.
REM
REM    Only BACKTEST set (backtest-only baseline):
REM      Parses the backtest, builds its baseline curve and
REM      saves it as a combine-ready JSON. Useful when you
REM      have no live data yet.
REM
REM  In all three modes, TICKS is used to generate a
REM  per-hour spread profile (spread_profile.json) for use
REM  in later Step 2 bar-based runs.
REM ============================================================

REM --- Paths (set at least one of STATEMENT or BACKTEST) ---
set STATEMENT=C:\Trading\Statement.htm
set BACKTEST=C:\Trading\StrategyTester.htm
set BARS=C:\Trading\EURUSD_M1.csv
set TICKS=C:\Trading\EURUSD_ticks.csv

REM --- Optional: filter to a specific symbol (substring match) ---
set SYMBOL=EURUSD

REM --- Optional: override the date window applied to BOTH files ---
REM  Leave blank to auto-constrain backtest to live's period.
set START_DATE=
set END_DATE=

REM --- Optional: open-hours filter applied to both (broker-local) ---
REM  Leave both blank to disable.
set OPEN_START_HOUR=
set OPEN_END_HOUR=

REM --- Optional: only include positions of this exact lot size ---
set LOT_SIZE=

REM --- Starting balance for backtest-only mode ---
REM  When STATEMENT is empty and BACKTEST is set, synthesize this
REM  starting deposit so the baseline curve is on a meaningful
REM  dollar scale for later combining. Has no effect when a live
REM  STATEMENT is provided.
set BACKTEST_STARTING_BALANCE=1000

REM --- Timezones ---
set BROKER_GMT=2
set TICK_GMT=2

REM --- Output folder ---
set OUT_DIR=.\results_compare

REM --- Python and script ---
set PYTHON=python
set SCRIPT=.\basket_analysis.py

REM ============================================================
REM  Build command
REM ============================================================

REM  If STATEMENT is empty but BACKTEST is set, run in backtest-only
REM  mode: the backtest is analysed as the primary statement and a
REM  baseline curve JSON is saved for later combining. The spread
REM  profile and hourly breakdown still get generated from TICKS.
if "%STATEMENT%"=="" (
    if "%BACKTEST%"=="" (
        echo ERROR: Both STATEMENT and BACKTEST are empty. Set at least one.
        pause
        exit /b 1
    )
    echo No live STATEMENT provided - running Step 1 in backtest-only mode.
    set CMD=%PYTHON% "%SCRIPT%" --statement "%BACKTEST%" --save-curve --stats-only --initial-balance %BACKTEST_STARTING_BALANCE%
) else if "%BACKTEST%"=="" (
    echo No BACKTEST provided - running Step 1 on live statement only.
    set CMD=%PYTHON% "%SCRIPT%" --statement "%STATEMENT%" --save-curve
) else (
    set CMD=%PYTHON% "%SCRIPT%" --statement "%STATEMENT%" --backtest "%BACKTEST%"
)

set CMD=%CMD% --bars "%BARS%" --ticks "%TICKS%"
set CMD=%CMD% --broker-gmt %BROKER_GMT% --tick-gmt %TICK_GMT%
set CMD=%CMD% --out-dir "%OUT_DIR%"

if not "%SYMBOL%"=="" set CMD=%CMD% --symbol %SYMBOL%
if not "%START_DATE%"=="" set CMD=%CMD% --start %START_DATE%
if not "%END_DATE%"=="" set CMD=%CMD% --end %END_DATE%
if not "%OPEN_START_HOUR%"=="" if not "%OPEN_END_HOUR%"=="" set CMD=%CMD% --open-hours %OPEN_START_HOUR% %OPEN_END_HOUR%
if not "%LOT_SIZE%"=="" set CMD=%CMD% --lot-size %LOT_SIZE%

echo.
echo Running: %CMD%
echo.
%CMD%

echo.
pause
