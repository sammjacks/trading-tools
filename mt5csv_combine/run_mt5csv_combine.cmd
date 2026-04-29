@echo off
setlocal

REM ==============================================================
REM  run_mt5csv_combine.cmd
REM
REM  Combines MT5 equity CSV exports (the tab-delimited UTF-16
REM  files with <DATE> <BALANCE> <EQUITY> <DEPOSIT LOAD> columns)
REM  into a single portfolio HTML report and xlsx spreadsheet.
REM
REM  No bars or tick files needed — equity is read directly from
REM  the CSV.
REM
REM  HOW TO ADD / REMOVE A STRATEGY:
REM    Each strategy is one --csv line in the STRATEGIES block.
REM    Format:  LABEL|PATH_TO_CSV[|SCALE]
REM      LABEL  - display name shown in the report (e.g. symbol)
REM      PATH   - full path to the MT5 equity CSV file
REM      SCALE  - optional P&L multiplier, default 1.0
REM
REM    To disable a strategy, prefix its line with REM.
REM ==============================================================

cd /d "%~dp0"

set PYTHON=python
set SCRIPT=.\mt5csv_combine.py

REM --- Output ---
set OUT_DIR=.\Portfolio_Output

REM --- Report title ---
set TITLE=NightForex Portfolio

REM --- Account / risk settings ---
set ACCOUNT_SIZE=15000
set DD_TOLERANCE=10

REM --- Optional: fix backtest months (leave blank for auto) ---
set BACKTEST_MONTHS=

REM ============================================================
REM  STRATEGIES
REM  One --csv line per file.  Comment out with REM to disable.
REM ============================================================

set STRATEGIES=
set STRATEGIES=%STRATEGIES% --csv "AUDUSD|C:\Users\sammj\Projects\trading-tools\mt5csv_combine\INSTANT_NightForex_AUDUSD_H1_20_400134.csv"
set STRATEGIES=%STRATEGIES% --csv "USDCAD|C:\Users\sammj\Projects\trading-tools\mt5csv_combine\INSTANT_NightForex_USDCAD_H1_20_400134.csv"
set STRATEGIES=%STRATEGIES% --csv "USDJPY|C:\Users\sammj\Projects\trading-tools\mt5csv_combine\INSTANT_NightForex_USDJPY_H1_20_400134.csv"

REM ============================================================

set MONTHS_ARG=
if not "%BACKTEST_MONTHS%"=="" set MONTHS_ARG=--backtest-months %BACKTEST_MONTHS%

%PYTHON% %SCRIPT% ^
    %STRATEGIES% ^
    --out-dir "%OUT_DIR%" ^
    --title "%TITLE%" ^
    --account-size %ACCOUNT_SIZE% ^
    --dd-tolerance %DD_TOLERANCE% ^
    %MONTHS_ARG%

if errorlevel 1 (
    echo.
    echo ERROR: script exited with errors.  See output above.
    pause
    exit /b 1
)

echo.
echo Done.  Opening report...
start "" "%OUT_DIR%\portfolio_report.html"
pause
