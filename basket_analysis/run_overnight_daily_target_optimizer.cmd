@echo off
cd /d "%~dp0"

REM ============================================================
REM  Overnight optimizer for daily target vs daily drawdown
REM ============================================================

set PYTHON=c:\python313\python.exe
set SCRIPT=.
overnight_daily_target_optimizer.py

REM --- Inputs ---
set STATEMENT=D:\SEIF_system_new\5year\M15\EURUSD\StrategyTester.htm
set BARS=D:\SEIF_system_new\5year\Data\darwinex\EURUSD_GMT+2_US-DST_M5.csv
set TICKS=D:\Work\TICK_2026to20260415dukas\EURUSD_GMT+2_US-DST.csv
set SYMBOL=EURUSD

REM --- Objective ---
set DAILY_TARGET_PCT=0.5
set DAILY_DD_LIMIT_PCT=1.0

REM --- Search size ---
set TOP_COARSE=400
set TOP_FINAL=50
set SESSION_STEP=3
set MIN_SESSION_WIDTH=6

REM --- Output ---
set OUT_DIR=.\overnight_research_output

%PYTHON% %SCRIPT% ^
  --statement "%STATEMENT%" ^
  --bars "%BARS%" ^
  --ticks "%TICKS%" ^
  --symbol %SYMBOL% ^
  --out-dir "%OUT_DIR%" ^
  --broker-gmt 2 ^
  --tick-gmt 2 ^
  --daily-target-pct %DAILY_TARGET_PCT% ^
  --daily-dd-limit-pct %DAILY_DD_LIMIT_PCT% ^
  --top-coarse %TOP_COARSE% ^
  --top-final %TOP_FINAL% ^
  --session-step %SESSION_STEP% ^
  --min-session-width %MIN_SESSION_WIDTH%

echo.
echo Overnight optimizer finished.
echo Output folder: %OUT_DIR%
pause
