@echo off
setlocal EnableExtensions
REM stage1_real_results_vs_backtest comparison driver
REM
REM Configuration:
REM   - Set real_statement: path to real account HTML statement from broker
REM   - Set backtest_report: path to backtest HTML report from MT4/MT5 tester
REM   - Set ticks_dir: folder containing SYMBOL_GMT+N_US-DST.csv
REM   - Set symbol: currency pair to compare (REQUIRED, e.g. "EURUSD")
REM              (used to filter out deposits, withdrawals, and other non-trading pairs)
REM   - Set magic_number: optional filter (empty = all magic numbers)
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

set real_statement=trades.csv
set backtest_report=Backtest.html
set ticks_dir=D:\SEIF_system_new\1year\Data\darwinex
set symbol=EURUSD
set magic_number=
set broker_gmt=2
set tick_gmt=2
set output_dir=.\results
set report_title=Real vs Backtest - Stage 1

if "%symbol%"=="" (
    call :die "ERROR: symbol must be set (e.g., EURUSD, GBPUSD)"
)

if not exist "%real_statement%" (
    call :die "ERROR: real statement file not found: %real_statement%"
)

if not exist "%backtest_report%" (
    call :die "ERROR: backtest report file not found: %backtest_report%"
)

if not exist "%ticks_dir%" (
    call :die "ERROR: ticks directory not found: %ticks_dir%"
)

set tick_sign=+
if %tick_gmt% LSS 0 set tick_sign=
set expected_tick_file=%ticks_dir%\%symbol%_GMT%tick_sign%%tick_gmt%_US-DST.csv
if not exist "%expected_tick_file%" (
    echo ERROR: expected tick file not found:
    echo   %expected_tick_file%
    echo.
    echo Looking for: SYMBOL_GMT+N_US-DST.csv
    echo Example for current settings: %symbol%_GMT%tick_sign%%tick_gmt%_US-DST.csv
    call :die "Please fix tick file name or ticks_dir"
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
echo   backtest_report: %backtest_report%
echo   ticks_dir: %ticks_dir%
echo   expected_tick_file: %expected_tick_file%
echo   symbol: %symbol%
echo   magic_number: %magic_number%
echo   broker_gmt: %broker_gmt%
echo   tick_gmt: %tick_gmt%
echo.
echo Starting analysis...

%PYTHON_CMD% -u stage1_real_results_vs_backtest.py ^
    --real-statement "%real_statement%" ^
    --backtest "%backtest_report%" ^
    --ticks-dir "%ticks_dir%" ^
    --symbol "%symbol%" ^
    --magic "%magic_number%" ^
    --broker-gmt %broker_gmt% ^
    --tick-gmt %tick_gmt% ^
    --out-dir "%output_dir%" ^
    --title "%report_title%"

if errorlevel 1 (
    echo.
    echo ERROR: Comparison failed. Check paths and file formats.
    call :die "Script returned non-zero exit code."
)

echo.
echo ✓ Comparison complete. Report: %output_dir%\real_vs_backtest_comparison.html
start "" "%output_dir%\real_vs_backtest_comparison.html"
if "%keep_window_open%"=="1" pause
exit /b 0

:die
echo %~1
if "%keep_window_open%"=="1" pause
exit /b 1
