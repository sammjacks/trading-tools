@echo off
setlocal EnableExtensions
REM stage1_real_results_vs_backtest comparison driver
REM
REM Configuration:
REM   - Set real_statement: path to the primary real account HTML/CSV statement
REM   - Set backtest_report: path to the comparison source (backtest HTML or another live HTML/CSV file)
REM   - Set bar_dir: optional folder containing bar CSVs such as SYMBOL_GMT+N_US-DST_M5.csv
REM   - Set ticks_dir: optional folder containing SYMBOL_GMT+N_US-DST.csv
REM   - If both are set, stage1 maps equity with bars first and then refines with ticks
REM   - Set symbol: currency pair to compare (REQUIRED, e.g. "EURUSD")
REM              (used to filter out deposits, withdrawals, and other non-trading pairs)
REM   - Set broker_gmt: broker timezone offset (e.g. 2, -5, 0)
REM   - Set tick_gmt: tick data timezone offset
REM   - Set output_dir: where to save the comparison HTML report
REM
REM Adjust paths and run:
REM   run_stage1_comparison.cmd
REM

cd /d "%~dp0"

REM Keep console open after run when double-clicked.
REM Set to 0 if you run from an existing terminal and do not want pause.
set keep_window_open=1

set real_statement=michel.html
set backtest_report=ats.html
set real_magic=
set compare_magic=
set real_scale=
set compare_scale=
REM Optional start date override. Leave blank for shared overlap, or use YYYY.MM.DD (example: 2026.03.09)
set start_date=
set bar_dir=D:\SEIF_system_new\Michel_Start
set ticks_dir=D:\SEIF_system_new\Michel_Start
set symbol=EURGBP
set broker_gmt=2
set tick_gmt=2
set bar_gmt=2
set output_dir=.\results
set report_title=Results Comparison - Stage 1

if "%symbol%"=="" (
    call :die "ERROR: symbol must be set (e.g., EURUSD, GBPUSD)"
)

if not exist "%real_statement%" (
    set "alt_statement="
    if /I "%real_statement:~-5%"==".html" set "alt_statement=%real_statement:~0,-1%"
    if /I "%real_statement:~-4%"==".htm" set "alt_statement=%real_statement%l"
    if defined alt_statement if exist "%alt_statement%" (
        echo Using alternate real statement path: %alt_statement%
        set "real_statement=%alt_statement%"
    )
)
if not exist "%real_statement%" (
    call :die "ERROR: real statement file not found: %real_statement%"
)

if not exist "%backtest_report%" (
    call :die "ERROR: backtest report file not found: %backtest_report%"
)

if not "%bar_dir%"=="" if not exist "%bar_dir%" (
    call :die "ERROR: bars directory not found: %bar_dir%"
)

if not "%ticks_dir%"=="" if not exist "%ticks_dir%" (
    call :die "ERROR: ticks directory not found: %ticks_dir%"
)

if "%bar_dir%"=="" if "%ticks_dir%"=="" (
    echo WARNING: both bar_dir and ticks_dir are blank.
    echo The script will fall back to realised trade-event equity steps.
)

set "expected_tick_file="
if not "%ticks_dir%"=="" (
    set tick_sign=+
    if %tick_gmt% LSS 0 set tick_sign=
    set expected_tick_file=%ticks_dir%\%symbol%_GMT%tick_sign%%tick_gmt%_US-DST.csv
    if not exist "%expected_tick_file%" (
        echo WARNING: expected tick file not found:
        echo   %expected_tick_file%
        echo The comparison can still run with bar data or realised trade events.
    )
)

set PYTHON_CMD=
where python >nul 2>nul && set PYTHON_CMD=python
if "%PYTHON_CMD%"=="" (
    where py >nul 2>nul && set PYTHON_CMD=py -3
)
if "%PYTHON_CMD%"=="" (
    call :die "ERROR: Python not found in PATH. Install Python or add it to PATH."
)

echo Running comparison with:
echo   real_statement: %real_statement%
echo   comparison_source: %backtest_report%
if not "%bar_dir%"=="" echo   bar_dir: %bar_dir%
if not "%ticks_dir%"=="" echo   ticks_dir: %ticks_dir%
if defined expected_tick_file echo   expected_tick_file: %expected_tick_file%
echo   symbol: %symbol%
echo   broker_gmt: %broker_gmt%
echo   tick_gmt: %tick_gmt%
if not "%start_date%"=="" echo   start_date: %start_date%
if not "%real_magic%"=="" echo   real_magic: %real_magic%
if not "%compare_magic%"=="" echo   compare_magic: %compare_magic%
if not "%real_scale%"=="" echo   real_scale: %real_scale%
if not "%compare_scale%"=="" echo   compare_scale: %compare_scale%
echo.
echo Starting analysis...

set EXTRA_ARGS=
if not "%bar_dir%"=="" set EXTRA_ARGS=%EXTRA_ARGS% --bars-dir "%bar_dir%"
if not "%ticks_dir%"=="" set EXTRA_ARGS=%EXTRA_ARGS% --ticks-dir "%ticks_dir%"
if not "%real_magic%"=="" set EXTRA_ARGS=%EXTRA_ARGS% --magic "%real_magic%"
if not "%compare_magic%"=="" set EXTRA_ARGS=%EXTRA_ARGS% --backtest-magic "%compare_magic%"
if not "%real_scale%"=="" set EXTRA_ARGS=%EXTRA_ARGS% --real-scale "%real_scale%"
if not "%compare_scale%"=="" set EXTRA_ARGS=%EXTRA_ARGS% --backtest-scale "%compare_scale%"
if not "%start_date%"=="" set EXTRA_ARGS=%EXTRA_ARGS% --start-date "%start_date%"

%PYTHON_CMD% -u stage1_real_results_vs_backtest.py ^
    --real-statement "%real_statement%" ^
    --backtest "%backtest_report%" ^
    --symbol "%symbol%" ^
    --broker-gmt %broker_gmt% ^
    --tick-gmt %tick_gmt% ^
    --bar-gmt %bar_gmt% ^
    --out-dir "%output_dir%" ^
    --title "%report_title%" ^
    %EXTRA_ARGS%

if errorlevel 1 (
    echo.
    echo ERROR: Comparison failed. Check paths and file formats.
    call :die "Script returned non-zero exit code."
)

echo.
echo Comparison complete. Report: %output_dir%\real_vs_backtest_comparison.html
start "" "%output_dir%\real_vs_backtest_comparison.html"
if "%keep_window_open%"=="1" pause
exit /b 0

:die
echo %~1
if "%keep_window_open%"=="1" pause
exit /b 1
