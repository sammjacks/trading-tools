@echo off
cd /d "%~dp0"
REM ============================================================
REM  Combine multiple final-check JSON files into one report
REM
REM  Run run_basket_analysis.cmd once per pair in FINAL CHECK
REM  mode first — each run produces a <symbol>_final.json file.
REM  Then list those files below and run this file to combine.
REM ============================================================

REM --- List the curve JSON files to combine, space-separated ---
REM  Use quotes around paths with spaces.
set FILES="C:\Trading\results\eurusd_final.json" "C:\Trading\results\usdcad_final.json"

REM --- Output folder for the combined HTML report ---
set OUT_DIR=.\combined

REM --- Path to Python and script ---
set PYTHON=python
set SCRIPT=.\basket_analysis.py

REM ============================================================
REM  Run — no need to edit below this line
REM ============================================================
%PYTHON% "%SCRIPT%" --combine %FILES% --out-dir "%OUT_DIR%"

echo.
pause
