@echo off
setlocal

REM ==============================================================
REM  run_basket_analysis_4_filter.cmd
REM
REM  Step 4: FILTER OPTIMIZATION
REM
REM  Builds the baseline equity curve from the full backtest, then
REM  tests combinations of filters to find configurations that
REM  improve the risk-adjusted return (Ret/DD) by avoiding bad
REM  sessions, wide-spread entries, or certain days of the week.
REM
REM  Filters tested:
REM    - SESSION WINDOW: only open new baskets during certain
REM      broker-local hours (e.g. 06-18h).
REM    - SPREAD INITIAL: only open a NEW basket if the spread at
REM      the first trade's entry is <= X pips.
REM    - SPREAD ALL: only open ANY trade (including subsequent
REM      basket legs) if spread <= X pips.
REM    - DAY-OF-WEEK: skip baskets that would open on certain
REM      days (e.g. avoid Monday or Friday).
REM    - BASKET SL: optionally test one or more basket stop levels.
REM    - EOD CLOSE: optionally test forced end-of-day basket close.
REM
REM  The tool uses tick data for accurate spread measurement at
REM  each trade's exact entry timestamp. M1 bar data is used for
REM  equity curve construction.
REM
REM  Output: filter_optimize.html with a ranked table of all
REM  passing filter combos + equity chart overlay of benchmark
REM  vs the #1 best-performing filter.
REM ==============================================================

REM  Force cwd to the folder containing this cmd file.
cd /d "%~dp0"

REM --- Python and script ---
set PYTHON=python
set SCRIPT=.\basket_analysis.py

REM ═══════════════════════════════════════════════════════════════
REM  INPUTS — edit these to point at your files
REM ═══════════════════════════════════════════════════════════════

set STATEMENT=.\StrategyTester.htm
set BARS=.\EURUSD_GMT_2_US-DST_M1.csv
set TICKS=.\EURUSD_GMT_0_NO-DST.csv
set SYMBOL=EURUSD
set BROKER_GMT=2
set TICK_GMT=0
set OUT_DIR=.\FilterOptimize

REM ═══════════════════════════════════════════════════════════════
REM  SESSION WINDOW SEARCH
REM ═══════════════════════════════════════════════════════════════
REM  Test every (start, end) pair from 0-24h with SESSION_STEP
REM  hour granularity. Windows narrower than MIN_SESSION_WIDTH
REM  hours are skipped. "all hours" (no session filter) is always
REM  included as one of the trials.
REM
REM  Example: STEP=2, WIDTH=4 tests 67 session combos including
REM  00-04, 00-06, ..., 00-24, 02-06, 02-08, ..., 20-24, + all.

set SESSION_STEP=2
set MIN_SESSION_WIDTH=4

REM ═══════════════════════════════════════════════════════════════
REM  SPREAD FILTER SEARCH
REM ═══════════════════════════════════════════════════════════════
REM  Test these spread thresholds (in pips) for:
REM    SPREAD_INITIAL: basket's first trade must have spread <= X
REM    SPREAD_ALL:     every trade (including subsequent legs)
REM                    must have spread <= X
REM
REM  0 means "no filter for this axis". The optimizer tests all
REM  valid combinations: (init only), (all only), (both where
REM  all >= init). Space-separated list.

set SPREAD_VALUES=0 0.5 1.0 1.5 2.0 3.0

REM ═══════════════════════════════════════════════════════════════
REM  DAY-OF-WEEK FILTER SEARCH
REM ═══════════════════════════════════════════════════════════════
REM  Test these options. Space-separated.
REM  Available: none, no-mon, no-fri, no-mon-fri, no-fri-sun

set DAY_OPTIONS=none no-mon no-fri no-mon-fri

REM ═══════════════════════════════════════════════════════════════
REM  STAGE 2 OPTIONS — basket SL and EOD in the optimization grid
REM ═══════════════════════════════════════════════════════════════
REM  Basket SL values in pips. Use 0 to include the no-SL baseline.
REM  Keep this list fairly short so the search stays fast.

set FILTER_SL_VALUES=0 8 10 12 15

REM  EOD modes to test: 0=off, 1=on
set FILTER_EOD_OPTIONS=0 1

REM  Broker-local EOD close time used when EOD mode is on
set EOD_TIME=23:59

REM ═══════════════════════════════════════════════════════════════
REM  DISPLAY
REM ═══════════════════════════════════════════════════════════════

set TOP_RESULTS=20

REM ═══════════════════════════════════════════════════════════════
REM  OPTIONAL: fixed filters applied to ALL trials (not optimized)
REM ═══════════════════════════════════════════════════════════════

REM  Date range filter (leave empty for full backtest period)
set START_DATE=
set END_DATE=

REM  Hour filter for the hourly breakdown display (does not affect
REM  the optimization — the optimizer tests its own session combos)
set OPEN_START_HOUR=
set OPEN_END_HOUR=

REM  Lot size filter (leave empty for all lots)
set LOT_SIZE=

REM ==============================================================
REM  Build command — do not edit below
REM ==============================================================

set CMD=%PYTHON% "%SCRIPT%" --statement "%STATEMENT%"
set CMD=%CMD% --bars "%BARS%" --ticks "%TICKS%"
set CMD=%CMD% --broker-gmt %BROKER_GMT% --tick-gmt %TICK_GMT%
set CMD=%CMD% --out-dir "%OUT_DIR%"
set CMD=%CMD% --filter-optimize
set CMD=%CMD% --session-step %SESSION_STEP% --min-session-width %MIN_SESSION_WIDTH%
set CMD=%CMD% --spread-values %SPREAD_VALUES%
set CMD=%CMD% --day-options %DAY_OPTIONS%
set CMD=%CMD% --filter-sl-values %FILTER_SL_VALUES%
set CMD=%CMD% --filter-eod-options %FILTER_EOD_OPTIONS%
set CMD=%CMD% --eod-time %EOD_TIME%
set CMD=%CMD% --top-results %TOP_RESULTS%

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
endlocal
