@echo off
setlocal

REM ==============================================================
REM  run_portfolio_backtest.cmd
REM
REM  Combines multiple fixed-lot backtests into a portfolio equity
REM  view. Each strategy contributes its raw dollar P&L curve on a
REM  unified daily timeline — no normalization.
REM
REM  HOW TO ENABLE/DISABLE A STRATEGY:
REM    To DISABLE a strategy, clear its STRATn_BT value like:
REM        set STRAT5_BT=
REM    or comment out its 4 "set" lines by prefixing each with REM.
REM    A strategy is included if and only if its STRATn_BT variable
REM    is non-empty.
REM
REM  DO NOT strip "REM" from header comment lines — only from "set"
REM  lines. Lines that start with REM are comments; everything else
REM  is executed by cmd and will error out if it isn't a command.
REM
REM  The bars file is auto-derived as:
REM      %BARS_DIR%\{SYMBOL}%BARS_SUFFIX%
REM  so no STRATn_BARS line is needed. Set BARS_DIR once at the
REM  top and every strategy picks its bars from there.
REM ==============================================================

REM  Force cwd to the folder containing this cmd file, so all the
REM  .\filename references below resolve correctly regardless of
REM  how the script was launched (double-click, command line, etc).
cd /d "%~dp0"

REM --- Paths (all relative to this cmd file's folder) ---
set PYTHON=python
set SCRIPT=.\portfolio_backtest.py
set OUT_DIR=.\Portfolio

REM --- Bars folder and filename pattern ---
REM  Each strategy's bars file is loaded from:
REM      %BARS_DIR%\{SYMBOL}%BARS_SUFFIX%
REM  Change BARS_DIR if your bars live somewhere else, and change
REM  BARS_SUFFIX if your naming convention is different.
set BARS_DIR=D:\SEIF_system_new\Michel_Start
set BARS_SUFFIX=_GMT+2_US-DST_M5.csv

REM --- Ticks folder and filename pattern ---
set TICKS_DIR=D:\SEIF_system_new\Michel_Start
set TICKS_SUFFIX=_GMT+2_US-DST.csv
set TICK_GMT=2
set CURVE_SOURCES=auto

REM === Strategy 1 ===
set STRAT1_SYMBOL=AUDUSD
set STRAT1_BT=.\Hexaflow8_settingsaudusdh1.htm
set STRAT1_SCALE=1.0
set STRAT1_GMT=2

REM === Strategy 2 ===
set STRAT2_SYMBOL=EURGBP
set STRAT2_BT=.\Hexaflow8_settingseurgbph1.htm
set STRAT2_SCALE=1.0
set STRAT2_GMT=2

REM === Strategy 3 ===
set STRAT3_SYMBOL=EURJPY
set STRAT3_BT=.\Hexaflow8_settingseurjpyh1.htm
set STRAT3_SCALE=1.0
set STRAT3_GMT=2

REM === Strategy 4 ===
set STRAT4_SYMBOL=EURUSD
set STRAT4_BT=.\Hexaflow8_settingseurusdh1.htm
set STRAT4_SCALE=1.0
set STRAT4_GMT=2

REM === Strategy 5 ===
set STRAT5_SYMBOL=GBPUSD
set STRAT5_BT=.\Hexaflow8_settingsgbpusdh1.htm
set STRAT5_SCALE=1.0
set STRAT5_GMT=2

REM === Strategy 6 ===
set STRAT6_SYMBOL=USDCAD
set STRAT6_BT=.\Hexaflow8_settingsusdcadh1.htm
set STRAT6_SCALE=1.0
set STRAT6_GMT=2

REM === Strategy 7 ===
set STRAT7_SYMBOL=USDCHF
set STRAT7_BT=.\Hexaflow8_settingsusdchfh1.htm
set STRAT7_SCALE=1.0
set STRAT7_GMT=2

REM === Strategy 8 ===
set STRAT8_SYMBOL=USDJPY
set STRAT8_BT=.\Hexaflow8_settingsusdjpyh1.htm
set STRAT8_SCALE=1.0
set STRAT8_GMT=2

REM --- Report title (optional) ---
set TITLE=Portfolio Backtest

REM --- Risk metrics (shown in HTML stats and xlsx output) ---
REM  ACCOUNT_SIZE:     notional account in $ used for safety factor
REM                    and monthly % calculations.
REM  DD_TOLERANCE:     max allowable drawdown as a percentage (e.g. 10
REM                    for 10 percent). Safety factor = (account*tol)/max DD.
REM  BACKTEST_MONTHS:  filter each backtest to the most recent N months
REM                    before computing any metrics. Leave empty to use
REM                    the full available date range.
set ACCOUNT_SIZE=15000
set DD_TOLERANCE=10
set BACKTEST_MONTHS=

REM --- Optimization: find combos meeting safety + profit criteria ---
REM  OPTIMIZE:           set to 1 to run the subset search, 0 to skip.
REM                      For N strategies this tests every subset of
REM                      size MIN_STRATEGIES..MAX_STRATEGIES at every
REM                      integer scale from 1 to MAX_SCALE per strategy,
REM                      and lists the combos whose COMBINED safety
REM                      factor and monthly % both meet the thresholds.
REM  MIN_SAFETY_FACTOR:  minimum safety factor for a combo to qualify.
REM  MIN_MONTHLY_PCT:    minimum monthly % return for a combo to qualify.
REM  MIN_STRATEGIES:     smallest subset size to test (default 1).
REM  MAX_STRATEGIES:     largest subset size to test (default 3).
REM                      Keep this small — search space grows quickly.
REM  MAX_SCALE:          each strategy is tried at integer scales
REM                      1, 2, ..., MAX_SCALE (default 5).
REM  TOP_N:              how many "maximally different" top portfolios
REM                      to pick from the passing list (default 3).
REM                      Each gets its own subfolder containing a mini
REM                      xlsx summary plus copies of every strategy's
REM                      backtest file and associated chart PNGs.
set OPTIMIZE=1
set MIN_SAFETY_FACTOR=1.5
set MIN_MONTHLY_PCT=1.5
set MIN_STRATEGIES=1
set MAX_STRATEGIES=3
set MAX_SCALE=5
set TOP_N=3

REM ==============================================================
REM  Build command — do not edit below unless you know what you're doing
REM ==============================================================

set CMD=%PYTHON% "%SCRIPT%" --out-dir "%OUT_DIR%" --title "%TITLE%"
set CMD=%CMD% --account-size %ACCOUNT_SIZE% --dd-tolerance %DD_TOLERANCE%
set CMD=%CMD% --curve-sources "%CURVE_SOURCES%"
if not "%TICKS_DIR%"=="" set CMD=%CMD% --ticks-dir "%TICKS_DIR%" --tick-suffix "%TICKS_SUFFIX%" --tick-gmt %TICK_GMT%
if not "%BACKTEST_MONTHS%"=="" set CMD=%CMD% --backtest-months %BACKTEST_MONTHS%
if "%OPTIMIZE%"=="1" set CMD=%CMD% --optimize --min-safety-factor %MIN_SAFETY_FACTOR% --min-monthly-pct %MIN_MONTHLY_PCT% --min-strategies %MIN_STRATEGIES% --max-strategies %MAX_STRATEGIES% --max-scale %MAX_SCALE% --top-n %TOP_N%

if not "%STRAT1_BT%"=="" set CMD=%CMD% --strategy "%STRAT1_SYMBOL%|%STRAT1_BT%|%BARS_DIR%\%STRAT1_SYMBOL%%BARS_SUFFIX%|%STRAT1_SCALE%|%STRAT1_GMT%"
if not "%STRAT2_BT%"=="" set CMD=%CMD% --strategy "%STRAT2_SYMBOL%|%STRAT2_BT%|%BARS_DIR%\%STRAT2_SYMBOL%%BARS_SUFFIX%|%STRAT2_SCALE%|%STRAT2_GMT%"
if not "%STRAT3_BT%"=="" set CMD=%CMD% --strategy "%STRAT3_SYMBOL%|%STRAT3_BT%|%BARS_DIR%\%STRAT3_SYMBOL%%BARS_SUFFIX%|%STRAT3_SCALE%|%STRAT3_GMT%"
if not "%STRAT4_BT%"=="" set CMD=%CMD% --strategy "%STRAT4_SYMBOL%|%STRAT4_BT%|%BARS_DIR%\%STRAT4_SYMBOL%%BARS_SUFFIX%|%STRAT4_SCALE%|%STRAT4_GMT%"
if not "%STRAT5_BT%"=="" set CMD=%CMD% --strategy "%STRAT5_SYMBOL%|%STRAT5_BT%|%BARS_DIR%\%STRAT5_SYMBOL%%BARS_SUFFIX%|%STRAT5_SCALE%|%STRAT5_GMT%"
if not "%STRAT6_BT%"=="" set CMD=%CMD% --strategy "%STRAT6_SYMBOL%|%STRAT6_BT%|%BARS_DIR%\%STRAT6_SYMBOL%%BARS_SUFFIX%|%STRAT6_SCALE%|%STRAT6_GMT%"
if not "%STRAT7_BT%"=="" set CMD=%CMD% --strategy "%STRAT7_SYMBOL%|%STRAT7_BT%|%BARS_DIR%\%STRAT7_SYMBOL%%BARS_SUFFIX%|%STRAT7_SCALE%|%STRAT7_GMT%"
if not "%STRAT8_BT%"=="" set CMD=%CMD% --strategy "%STRAT8_SYMBOL%|%STRAT8_BT%|%BARS_DIR%\%STRAT8_SYMBOL%%BARS_SUFFIX%|%STRAT8_SCALE%|%STRAT8_GMT%"

echo.
echo Running: %CMD%
echo.
%CMD%

echo.
pause
endlocal
