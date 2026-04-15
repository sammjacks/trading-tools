@echo off
setlocal EnableExtensions

REM ==============================================================
REM  real_results_review - single-source review + optional portfolio
REM ==============================================================
cd /d "%~dp0"

set keep_window_open=1

REM --- Primary review file ---
set statement_file=.\JapanStrike_USDJPY_M15.htm
set symbol=USDJPY
set magic_filter=
set scale=1.0
REM Optional date filters. Leave blank to use all available history.
REM Format: YYYY.MM.DD   Example: 2026.03.04
set start_date=2026.03.29
set end_date=

REM --- Tick data for mark-to-market equity ---
set ticks_dir=D:\SEIF_system_new\Michel_Start
set broker_gmt=2
set tick_gmt=2

REM --- Output ---
set output_dir=.
set title=Real Results Review
set portfolio_title=Real Results Portfolio Review

REM --- Portfolio risk settings ---
set account_size=10000
set dd_tolerance=10
set no_xlsx=0

REM ==============================================================
REM  Optional portfolio strategies (same stage3-style feel)
REM
REM  Enable a strategy by setting STRATn_FILE. Supports STRAT1..STRAT10
REM  NOTE: the main review statement at the top of this file is already
REM  included as the first portfolio row. STRATn entries are ADDITIONAL.
REM  STRATn_FILE   = the CSV / HTM / HTML statement file to read
REM  STRATn_SYMBOL = the symbol filter inside that file, e.g. EURUSD
REM  Format passed through: SYMBOL|FILE||SCALE|BROKER_GMT|MAGIC|LABEL
REM
REM  Examples:
REM    set STRAT1_FILE=.\michel.htm
REM    set STRAT1_SYMBOL=EURUSD
REM    set STRAT1_MAGIC=12000
REM ==============================================================
set STRAT1_SYMBOL=EURUSD
set STRAT1_FILE=.\Eurostable_EURUSD_M15.htm
set STRAT1_SCALE=1.0
set STRAT1_GMT=2
set STRAT1_MAGIC=12000
set STRAT1_LABEL=

set STRAT2_SYMBOL=EURUSD
set STRAT2_FILE=.\Multipair_EURUSD_M15.htm
set STRAT2_SCALE=1.0
set STRAT2_GMT=2
set STRAT2_MAGIC=10000
set STRAT2_LABEL=

set STRAT3_SYMBOL=GBPUSD
set STRAT3_FILE=.\Multipair_GBPUSD_M15.htm
set STRAT3_SCALE=1.0
set STRAT3_GMT=2
set STRAT3_MAGIC=
set STRAT3_LABEL=

set STRAT4_SYMBOL=EURJPY
set STRAT4_FILE=.\Multipair_EURJPY_M15.htm
set STRAT4_SCALE=1.0
set STRAT4_GMT=2
set STRAT4_MAGIC=
set STRAT4_LABEL=

set STRAT5_SYMBOL=
set STRAT5_FILE=
set STRAT5_SCALE=1.0
set STRAT5_GMT=2
set STRAT5_MAGIC=
set STRAT5_LABEL=

set STRAT6_SYMBOL=
set STRAT6_FILE=
set STRAT6_SCALE=1.0
set STRAT6_GMT=2
set STRAT6_MAGIC=
set STRAT6_LABEL=

set STRAT7_SYMBOL=
set STRAT7_FILE=
set STRAT7_SCALE=1.0
set STRAT7_GMT=2
set STRAT7_MAGIC=
set STRAT7_LABEL=

set STRAT8_SYMBOL=
set STRAT8_FILE=
set STRAT8_SCALE=1.0
set STRAT8_GMT=2
set STRAT8_MAGIC=
set STRAT8_LABEL=

set STRAT9_SYMBOL=
set STRAT9_FILE=
set STRAT9_SCALE=1.0
set STRAT9_GMT=2
set STRAT9_MAGIC=
set STRAT9_LABEL=

set STRAT10_SYMBOL=
set STRAT10_FILE=
set STRAT10_SCALE=1.0
set STRAT10_GMT=2
set STRAT10_MAGIC=
set STRAT10_LABEL=

set found_statement=
if "%statement_file%"=="." (
    for %%F in (*.csv *.htm *.html) do if not defined found_statement set "found_statement=.\%%F"
    if defined found_statement set "statement_file=%found_statement%"
)

if "%statement_file%"=="." (
    echo ERROR: set statement_file to your CSV / HTM / HTML export first.
    if "%keep_window_open%"=="1" pause
    exit /b 1
)

REM Optional: if this folder is copied elsewhere, point back to the main repo helpers.
set TRADING_TOOLS_ROOT=C:\Users\sammj\Projects\trading-tools

set PYTHON_CMD=
where python >nul 2>nul && set PYTHON_CMD=python
if "%PYTHON_CMD%"=="" (
    where py >nul 2>nul && set PYTHON_CMD=py -3
)
if "%PYTHON_CMD%"=="" (
    echo ERROR: Python not found in PATH.
    if "%keep_window_open%"=="1" pause
    exit /b 1
)

set CMD=%PYTHON_CMD% -u real_results_review.py --statement "%statement_file%" --symbol "%symbol%" --ticks-dir "%ticks_dir%" --broker-gmt %broker_gmt% --tick-gmt %tick_gmt% --out-dir "%output_dir%" --title "%title%" --portfolio-title "%portfolio_title%" --account-size %account_size% --dd-tolerance %dd_tolerance% --scale %scale%
if not "%magic_filter%"=="" set CMD=%CMD% --magic "%magic_filter%"
if not "%start_date%"=="" set CMD=%CMD% --start-date "%start_date%"
if not "%end_date%"=="" set CMD=%CMD% --end-date "%end_date%"
if "%no_xlsx%"=="1" set CMD=%CMD% --no-xlsx

if not "%STRAT1_FILE%"=="" set CMD=%CMD% --strategy "%STRAT1_SYMBOL%|%STRAT1_FILE%||%STRAT1_SCALE%|%STRAT1_GMT%|%STRAT1_MAGIC%|%STRAT1_LABEL%"
if not "%STRAT2_FILE%"=="" set CMD=%CMD% --strategy "%STRAT2_SYMBOL%|%STRAT2_FILE%||%STRAT2_SCALE%|%STRAT2_GMT%|%STRAT2_MAGIC%|%STRAT2_LABEL%"
if not "%STRAT3_FILE%"=="" set CMD=%CMD% --strategy "%STRAT3_SYMBOL%|%STRAT3_FILE%||%STRAT3_SCALE%|%STRAT3_GMT%|%STRAT3_MAGIC%|%STRAT3_LABEL%"
if not "%STRAT4_FILE%"=="" set CMD=%CMD% --strategy "%STRAT4_SYMBOL%|%STRAT4_FILE%||%STRAT4_SCALE%|%STRAT4_GMT%|%STRAT4_MAGIC%|%STRAT4_LABEL%"
if not "%STRAT5_FILE%"=="" set CMD=%CMD% --strategy "%STRAT5_SYMBOL%|%STRAT5_FILE%||%STRAT5_SCALE%|%STRAT5_GMT%|%STRAT5_MAGIC%|%STRAT5_LABEL%"
if not "%STRAT6_FILE%"=="" set CMD=%CMD% --strategy "%STRAT6_SYMBOL%|%STRAT6_FILE%||%STRAT6_SCALE%|%STRAT6_GMT%|%STRAT6_MAGIC%|%STRAT6_LABEL%"
if not "%STRAT7_FILE%"=="" set CMD=%CMD% --strategy "%STRAT7_SYMBOL%|%STRAT7_FILE%||%STRAT7_SCALE%|%STRAT7_GMT%|%STRAT7_MAGIC%|%STRAT7_LABEL%"
if not "%STRAT8_FILE%"=="" set CMD=%CMD% --strategy "%STRAT8_SYMBOL%|%STRAT8_FILE%||%STRAT8_SCALE%|%STRAT8_GMT%|%STRAT8_MAGIC%|%STRAT8_LABEL%"
if not "%STRAT9_FILE%"=="" set CMD=%CMD% --strategy "%STRAT9_SYMBOL%|%STRAT9_FILE%||%STRAT9_SCALE%|%STRAT9_GMT%|%STRAT9_MAGIC%|%STRAT9_LABEL%"
if not "%STRAT10_FILE%"=="" set CMD=%CMD% --strategy "%STRAT10_SYMBOL%|%STRAT10_FILE%||%STRAT10_SCALE%|%STRAT10_GMT%|%STRAT10_MAGIC%|%STRAT10_LABEL%"

echo.
echo Running: %CMD%
echo.
%CMD%

if errorlevel 1 (
    echo.
    echo ERROR: real_results_review failed.
    if "%keep_window_open%"=="1" pause
    exit /b 1
)

echo.
echo Review complete. Main HTML: %output_dir%\real_results_review.html
if exist "%output_dir%\real_results_review.html" start "" "%output_dir%\real_results_review.html"
if "%keep_window_open%"=="1" pause
exit /b 0
