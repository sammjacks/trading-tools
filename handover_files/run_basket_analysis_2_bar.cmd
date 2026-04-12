@echo off
REM ============================================================
REM  Step 2 — Bar-based Analysis (scan or final check)
REM
REM  Runs SL simulation using M1/M15 bar data. If you point
REM  SPREAD_PROFILE at a spread_profile.json file produced by
REM  Step 1, the bar simulation applies a per-hour spread model
REM  to approximate real bid/ask trigger behaviour.
REM
REM  TWO MODES:
REM    SCAN MODE (default): leave FINAL_SL blank. Scans SL
REM    values from SL_MIN to SL_MAX, showing both EOD and
REM    no-EOD results side by side.
REM
REM    FINAL CHECK MODE: set FINAL_SL to a single value. Runs
REM    one simulation with those exact settings, outputs HTML
REM    report and a JSON curve file for later combining.
REM ============================================================

REM --- Required paths ---
set STATEMENT=C:\Trading\Statement.htm
set BARS=C:\Trading\EURUSD_M1.csv

REM --- Optional: spread profile from Step 1 ---
REM  Set this to .\results_compare\spread_profile.json (or wherever
REM  Step 1 put it) to model per-hour spreads in the bar simulation.
REM  Leave blank for no spread adjustment.
set SPREAD_PROFILE=

REM --- Optional: filter to a specific symbol (substring match) ---
set SYMBOL=EURUSD

REM --- Optional: date range (YYYY-MM-DD) ---
set START_DATE=
set END_DATE=

REM --- Optional: open-hours filter (broker-local 0-24) ---
set OPEN_START_HOUR=
set OPEN_END_HOUR=

REM --- Optional: only include positions of this exact lot size ---
set LOT_SIZE=

REM --- Broker-local EOD close time (HH:MM) ---
set EOD_TIME=23:59

REM ============================================================
REM  SCAN MODE settings (used when FINAL_SL is blank)
REM ============================================================
set SL_MIN=6
set SL_MAX=20

REM ============================================================
REM  FINAL CHECK MODE (triggered when FINAL_SL is set)
REM ============================================================
set FINAL_SL=
set FINAL_EOD=0

REM --- Timezones ---
set BROKER_GMT=2

REM --- Output folder ---
set OUT_DIR=.\results_bar

REM --- Python and script ---
set PYTHON=python
set SCRIPT=basket_analysis.py

REM ============================================================
REM  Build command
REM ============================================================
set CMD=%PYTHON% "%SCRIPT%" --statement "%STATEMENT%" --bars "%BARS%"
set CMD=%CMD% --broker-gmt %BROKER_GMT% --eod-time %EOD_TIME%
set CMD=%CMD% --out-dir "%OUT_DIR%"

if not "%SYMBOL%"=="" set CMD=%CMD% --symbol %SYMBOL%
if not "%START_DATE%"=="" set CMD=%CMD% --start %START_DATE%
if not "%END_DATE%"=="" set CMD=%CMD% --end %END_DATE%
if not "%OPEN_START_HOUR%"=="" if not "%OPEN_END_HOUR%"=="" set CMD=%CMD% --open-hours %OPEN_START_HOUR% %OPEN_END_HOUR%
if not "%LOT_SIZE%"=="" set CMD=%CMD% --lot-size %LOT_SIZE%
if not "%SPREAD_PROFILE%"=="" set CMD=%CMD% --spread-profile "%SPREAD_PROFILE%"

REM  Flat conditionals avoid the batch delayed-expansion trap where
REM  nested "set CMD=%CMD% ..." inside an if-block uses the pre-block
REM  value of CMD for every assignment and loses earlier appends.
if not "%FINAL_SL%"=="" set CMD=%CMD% --final-sl %FINAL_SL%
if not "%FINAL_SL%"=="" if "%FINAL_EOD%"=="1" set CMD=%CMD% --final-eod
if "%FINAL_SL%"=="" set CMD=%CMD% --sl-range %SL_MIN% %SL_MAX%

echo.
echo Running: %CMD%
echo.
%CMD%

echo.
pause
