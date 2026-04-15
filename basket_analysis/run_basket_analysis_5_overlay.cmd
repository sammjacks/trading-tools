@echo off
setlocal

REM ==============================================================
REM  run_basket_analysis_5_overlay.cmd
REM
REM  Research a standalone overlay trade that watches the source
REM  basket strategy and opens one extra position WITH the basket when:
REM    - many positions are already open,
REM    - price has moved against the basket,
REM    - price then compresses into consolidation.
REM
REM  Dynamic TP testing includes Fibonacci retracement targets.
REM
REM  The tool tests many rule combinations on the first 4 years of
REM  history using M5 bars, then verifies the top results using the
REM  raw tick file so spread is included.
REM ==============================================================

cd /d "%~dp0"

set PYTHON=python
set SCRIPT=.\basket_overlay_research.py

REM ═══════════════════════════════════════════════════════════════
REM  INPUT FILES
REM ═══════════════════════════════════════════════════════════════

set STATEMENT=D:\SEIF_system_new\5year\M15\EURUSD\StrategyTester.htm
set BARS=D:\SEIF_system_new\5year\Data\darwinex\EURUSD_GMT+2_US-DST_M5.csv
set TICKS=D:\SEIF_system_new\5year\Data\darwinex\EURUSD_GMT+2_US-DST.csv
set SYMBOL=EURUSD
set BROKER_GMT=2
set TICK_GMT=2
set OUT_DIR=.\OverlayResearch

REM ═══════════════════════════════════════════════════════════════
REM  RESEARCH WINDOW AND OUTPUT SIZE
REM ═══════════════════════════════════════════════════════════════

set TRAIN_YEARS=4
set OVERLAY_LOT=0.01
set MIN_SIGNALS=40
set TOP_RESULTS=20
set TICK_VERIFY_TOP=3

REM ═══════════════════════════════════════════════════════════════
REM  RULE GRID — edit these lists to widen or narrow the search
REM ═══════════════════════════════════════════════════════════════

set MIN_POSITIONS=6 8 10 12
set MIN_ADVERSE_PIPS=15 20 25 30 40
set CONSOLIDATION_BARS=3 4 6
set CONSOLIDATION_RATIOS=0.20 0.30 0.40
set DIRECTION_MODES=with_basket
set ENTRY_MODES=breakout direction
set FIXED_SL_PIPS=10 15 20
set DYNAMIC_STOP_FRACS=0.25 0.50
set RR_VALUES=1.0 1.25 1.5
set FIB_TP_LEVELS=0.236 0.382 0.500 0.618 0.786

set CMD=%PYTHON% "%SCRIPT%" --statement "%STATEMENT%"
set CMD=%CMD% --bars "%BARS%" --ticks "%TICKS%"
set CMD=%CMD% --symbol %SYMBOL% --broker-gmt %BROKER_GMT% --tick-gmt %TICK_GMT%
set CMD=%CMD% --train-years %TRAIN_YEARS% --overlay-lot %OVERLAY_LOT%
set CMD=%CMD% --min-signals %MIN_SIGNALS% --top-results %TOP_RESULTS%
set CMD=%CMD% --tick-verify-top %TICK_VERIFY_TOP% --out-dir "%OUT_DIR%"
set CMD=%CMD% --min-positions %MIN_POSITIONS%
set CMD=%CMD% --min-adverse-pips %MIN_ADVERSE_PIPS%
set CMD=%CMD% --consolidation-bars %CONSOLIDATION_BARS%
set CMD=%CMD% --consolidation-ratios %CONSOLIDATION_RATIOS%
set CMD=%CMD% --direction-modes %DIRECTION_MODES%
set CMD=%CMD% --entry-modes %ENTRY_MODES%
set CMD=%CMD% --fixed-sl-pips %FIXED_SL_PIPS%
set CMD=%CMD% --dynamic-stop-fracs %DYNAMIC_STOP_FRACS%
set CMD=%CMD% --rr-values %RR_VALUES%
set CMD=%CMD% --fib-tp-levels %FIB_TP_LEVELS%

echo.
echo Running: %CMD%
echo.
%CMD%

echo.
pause
endlocal
