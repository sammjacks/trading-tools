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
REM    STRATn_BT can point to either a Strategy Tester HTML report
REM    (.htm/.html) or a live trade export such as trades.csv.
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
set OUT_DIR=.\Portfolio_Tick_Check

REM --- Bars folder and filename pattern ---
REM  Each strategy's bars file is loaded from:
REM      %BARS_DIR%\{SYMBOL}%BARS_SUFFIX%
REM  Change BARS_DIR if your bars live somewhere else, and change
REM  BARS_SUFFIX if your naming convention is different.
set BARS_DIR=D:\SEIF_system_new\Michel_Start
set BARS_SUFFIX=_GMT+2_US-DST_M5.csv

REM --- Ticks folder and filename pattern ---
REM  Each strategy's tick file is auto-derived as:
REM      %TICKS_DIR%\{SYMBOL}%TICKS_SUFFIX%
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

REM === Strategy 9 (optional) ===
set STRAT9_SYMBOL=
set STRAT9_BT=
set STRAT9_SCALE=1.0
set STRAT9_GMT=2

REM === Strategy 10 (optional) ===
set STRAT10_SYMBOL=
set STRAT10_BT=
set STRAT10_SCALE=1.0
set STRAT10_GMT=2

REM === Strategy 11 (optional) ===
set STRAT11_SYMBOL=
set STRAT11_BT=
set STRAT11_SCALE=1.0
set STRAT11_GMT=2

REM === Strategy 12 (optional) ===
set STRAT12_SYMBOL=
set STRAT12_BT=
set STRAT12_SCALE=1.0
set STRAT12_GMT=2

REM === Strategy 13 (optional) ===
set STRAT13_SYMBOL=
set STRAT13_BT=
set STRAT13_SCALE=1.0
set STRAT13_GMT=2

REM === Strategy 14 (optional) ===
set STRAT14_SYMBOL=
set STRAT14_BT=
set STRAT14_SCALE=1.0
set STRAT14_GMT=2

REM === Strategy 15 (optional) ===
set STRAT15_SYMBOL=
set STRAT15_BT=
set STRAT15_SCALE=1.0
set STRAT15_GMT=2

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

REM  Stage 3 is a comparison tool: it builds separate outputs from bars
REM  and ticks for the same portfolio. No subset optimization is run here.

REM ==============================================================
REM  Build command — do not edit below unless you know what you're doing
REM ==============================================================

set CMD=%PYTHON% "%SCRIPT%" --out-dir "%OUT_DIR%" --title "%TITLE%"
set CMD=%CMD% --account-size %ACCOUNT_SIZE% --dd-tolerance %DD_TOLERANCE%
set CMD=%CMD% --curve-sources "%CURVE_SOURCES%"
if not "%TICKS_DIR%"=="" set CMD=%CMD% --ticks-dir "%TICKS_DIR%" --tick-suffix "%TICKS_SUFFIX%" --tick-gmt %TICK_GMT%
if not "%BACKTEST_MONTHS%"=="" set CMD=%CMD% --backtest-months %BACKTEST_MONTHS%

if not "%STRAT1_BT%"=="" set CMD=%CMD% --strategy "%STRAT1_SYMBOL%|%STRAT1_BT%|%BARS_DIR%\%STRAT1_SYMBOL%%BARS_SUFFIX%|%STRAT1_SCALE%|%STRAT1_GMT%"
if not "%STRAT2_BT%"=="" set CMD=%CMD% --strategy "%STRAT2_SYMBOL%|%STRAT2_BT%|%BARS_DIR%\%STRAT2_SYMBOL%%BARS_SUFFIX%|%STRAT2_SCALE%|%STRAT2_GMT%"
if not "%STRAT3_BT%"=="" set CMD=%CMD% --strategy "%STRAT3_SYMBOL%|%STRAT3_BT%|%BARS_DIR%\%STRAT3_SYMBOL%%BARS_SUFFIX%|%STRAT3_SCALE%|%STRAT3_GMT%"
if not "%STRAT4_BT%"=="" set CMD=%CMD% --strategy "%STRAT4_SYMBOL%|%STRAT4_BT%|%BARS_DIR%\%STRAT4_SYMBOL%%BARS_SUFFIX%|%STRAT4_SCALE%|%STRAT4_GMT%"
if not "%STRAT5_BT%"=="" set CMD=%CMD% --strategy "%STRAT5_SYMBOL%|%STRAT5_BT%|%BARS_DIR%\%STRAT5_SYMBOL%%BARS_SUFFIX%|%STRAT5_SCALE%|%STRAT5_GMT%"
if not "%STRAT6_BT%"=="" set CMD=%CMD% --strategy "%STRAT6_SYMBOL%|%STRAT6_BT%|%BARS_DIR%\%STRAT6_SYMBOL%%BARS_SUFFIX%|%STRAT6_SCALE%|%STRAT6_GMT%"
if not "%STRAT7_BT%"=="" set CMD=%CMD% --strategy "%STRAT7_SYMBOL%|%STRAT7_BT%|%BARS_DIR%\%STRAT7_SYMBOL%%BARS_SUFFIX%|%STRAT7_SCALE%|%STRAT7_GMT%"
if not "%STRAT8_BT%"=="" set CMD=%CMD% --strategy "%STRAT8_SYMBOL%|%STRAT8_BT%|%BARS_DIR%\%STRAT8_SYMBOL%%BARS_SUFFIX%|%STRAT8_SCALE%|%STRAT8_GMT%"
if not "%STRAT9_BT%"=="" set CMD=%CMD% --strategy "%STRAT9_SYMBOL%|%STRAT9_BT%|%BARS_DIR%\%STRAT9_SYMBOL%%BARS_SUFFIX%|%STRAT9_SCALE%|%STRAT9_GMT%"
if not "%STRAT10_BT%"=="" set CMD=%CMD% --strategy "%STRAT10_SYMBOL%|%STRAT10_BT%|%BARS_DIR%\%STRAT10_SYMBOL%%BARS_SUFFIX%|%STRAT10_SCALE%|%STRAT10_GMT%"
if not "%STRAT11_BT%"=="" set CMD=%CMD% --strategy "%STRAT11_SYMBOL%|%STRAT11_BT%|%BARS_DIR%\%STRAT11_SYMBOL%%BARS_SUFFIX%|%STRAT11_SCALE%|%STRAT11_GMT%"
if not "%STRAT12_BT%"=="" set CMD=%CMD% --strategy "%STRAT12_SYMBOL%|%STRAT12_BT%|%BARS_DIR%\%STRAT12_SYMBOL%%BARS_SUFFIX%|%STRAT12_SCALE%|%STRAT12_GMT%"
if not "%STRAT13_BT%"=="" set CMD=%CMD% --strategy "%STRAT13_SYMBOL%|%STRAT13_BT%|%BARS_DIR%\%STRAT13_SYMBOL%%BARS_SUFFIX%|%STRAT13_SCALE%|%STRAT13_GMT%"
if not "%STRAT14_BT%"=="" set CMD=%CMD% --strategy "%STRAT14_SYMBOL%|%STRAT14_BT%|%BARS_DIR%\%STRAT14_SYMBOL%%BARS_SUFFIX%|%STRAT14_SCALE%|%STRAT14_GMT%"
if not "%STRAT15_BT%"=="" set CMD=%CMD% --strategy "%STRAT15_SYMBOL%|%STRAT15_BT%|%BARS_DIR%\%STRAT15_SYMBOL%%BARS_SUFFIX%|%STRAT15_SCALE%|%STRAT15_GMT%"

echo.
echo Running: %CMD%
echo.
%CMD%

echo.
pause
endlocal
