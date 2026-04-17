@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "PYTHON_EXE=c:/python313/python.exe"
set "SCRIPT=%~dp0account_review_flow.py"
set "TERMINAL_DIR=%~dp0BlackBull MT5 - 3"
set "STATEMENT_FILE=%~dp0trades.csv"
set "BARS_DIR=D:\SEIF_system_new\Michel_Start"
set "TICKS_DIR=D:\SEIF_system_new\Michel_Start"
set "STAGE1_ROOT=%~dp0stage1_results"
set "STAGE1_RUN_DIR=%STAGE1_ROOT%\stage1_same_period"
set "EXCLUDED_SYMBOLS_FILE=%~dp0excluded_symbols.txt"

set "BROKER_LOGIN_FILE_A=%~dp0broker_loginA.txt"
set "BROKER_PASSWORD_FILE_A=%~dp0broker_passwordA.txt"
set "BROKER_SERVER_FILE_A=%~dp0broker_serverA.txt"
set "BROKER_LOGIN_FILE_B=%~dp0broker_loginB.txt"
set "BROKER_PASSWORD_FILE_B=%~dp0broker_passwordB.txt"
set "BROKER_SERVER_FILE_B=%~dp0broker_serverB.txt"

if not exist "%PYTHON_EXE%" (
  echo ERROR: Python not found at %PYTHON_EXE%
  pause
  exit /b 1
)
if not exist "%SCRIPT%" (
  echo ERROR: Script not found: %SCRIPT%
  pause
  exit /b 1
)
if not exist "%TERMINAL_DIR%\terminal64.exe" (
  echo ERROR: MT5 terminal not found: %TERMINAL_DIR%
  pause
  exit /b 1
)
if not exist "%STATEMENT_FILE%" (
  echo ERROR: trades.csv not found: %STATEMENT_FILE%
  pause
  exit /b 1
)

for %%F in (
  "%BROKER_LOGIN_FILE_A%"
  "%BROKER_PASSWORD_FILE_A%"
  "%BROKER_SERVER_FILE_A%"
  "%BROKER_LOGIN_FILE_B%"
  "%BROKER_PASSWORD_FILE_B%"
  "%BROKER_SERVER_FILE_B%"
) do (
  if not exist "%%~F" (
    echo ERROR: Missing credential file %%~F
    pause
    exit /b 1
  )
)

set /p BROKER_LOGIN_A=<"%BROKER_LOGIN_FILE_A%"
set /p BROKER_PASSWORD_A=<"%BROKER_PASSWORD_FILE_A%"
set /p BROKER_SERVER_A=<"%BROKER_SERVER_FILE_A%"
set /p BROKER_LOGIN_B=<"%BROKER_LOGIN_FILE_B%"
set /p BROKER_PASSWORD_B=<"%BROKER_PASSWORD_FILE_B%"
set /p BROKER_SERVER_B=<"%BROKER_SERVER_FILE_B%"

if "%BROKER_LOGIN_A%"=="" goto :missingA
if "%BROKER_PASSWORD_A%"=="" goto :missingA
if "%BROKER_SERVER_A%"=="" goto :missingA
if "%BROKER_LOGIN_B%"=="" goto :missingB
if "%BROKER_PASSWORD_B%"=="" goto :missingB
if "%BROKER_SERVER_B%"=="" goto :missingB

mkdir "%STAGE1_ROOT%" 2>nul
mkdir "%STAGE1_ROOT%\00_preflight" 2>nul
mkdir "%STAGE1_RUN_DIR%" 2>nul

if not exist "%EXCLUDED_SYMBOLS_FILE%" (
  >"%EXCLUDED_SYMBOLS_FILE%" echo # One symbol per line to skip in Stage 1, e.g. EURUSD
)

echo.
echo ============================================================
echo  STAGE 1 - MT5 PREFLIGHT AND BACKTESTS
echo ============================================================
echo  Terminal   : %TERMINAL_DIR%
echo  Statement  : %STATEMENT_FILE%
echo  Output root: %STAGE1_ROOT%
echo ============================================================
echo.

echo [1/3] Running MT5 preflight...
"%PYTHON_EXE%" "%SCRIPT%" ^
  --statement-file "%STATEMENT_FILE%" ^
  --account-label "Stage1_Preflight" ^
  --out-root "%STAGE1_ROOT%\00_preflight" ^
  --mt5-terminal-dir "%TERMINAL_DIR%" ^
  --bars-dir "%BARS_DIR%" ^
  --ticks-dir "%TICKS_DIR%" ^
  --broker-gmt 2 ^
  --compare-broker-gmt 2 ^
  --compare-tick-gmt 2 ^
  --tester-period H1 ^
  --excluded-symbols-file "%EXCLUDED_SYMBOLS_FILE%" ^
  --preview-plan
if errorlevel 1 goto :failed

echo.
echo [2/3] Running Broker A same-period backtests...
"%PYTHON_EXE%" "%SCRIPT%" ^
  --statement-file "%STATEMENT_FILE%" ^
  --account-label "BrokerA_Stage1" ^
  --out-root "%STAGE1_ROOT%" ^
  --resume-run-dir "%STAGE1_RUN_DIR%" ^
  --mt5-terminal-dir "%TERMINAL_DIR%" ^
  --broker-login "%BROKER_LOGIN_A%" ^
  --broker-password "%BROKER_PASSWORD_A%" ^
  --broker-server "%BROKER_SERVER_A%" ^
  --bars-dir "%BARS_DIR%" ^
  --ticks-dir "%TICKS_DIR%" ^
  --account-size 10000 ^
  --dd-tolerance 10 ^
  --broker-gmt 2 ^
  --compare-broker-gmt 2 ^
  --compare-tick-gmt 2 ^
  --default-scale 1.0 ^
  --tester-period H1 ^
  --tester-model 4 ^
  --tester-delay-ms 50 ^
  --tester-order-filling AUTO ^
  --tester-deposit 10000 ^
  --tester-leverage 100 ^
  --tester-use-local ^
  --excluded-symbols-file "%EXCLUDED_SYMBOLS_FILE%" ^
  --run-review-now ^
  --real-period-backtests-only
if errorlevel 1 goto :failed

echo.
echo [3/3] Running Broker B same-period backtests...
"%PYTHON_EXE%" "%SCRIPT%" ^
  --statement-file "%STATEMENT_FILE%" ^
  --account-label "BrokerB_Stage1" ^
  --out-root "%STAGE1_ROOT%" ^
  --resume-run-dir "%STAGE1_RUN_DIR%" ^
  --mt5-terminal-dir "%TERMINAL_DIR%" ^
  --broker-login "%BROKER_LOGIN_B%" ^
  --broker-password "%BROKER_PASSWORD_B%" ^
  --broker-server "%BROKER_SERVER_B%" ^
  --bars-dir "%BARS_DIR%" ^
  --ticks-dir "%TICKS_DIR%" ^
  --account-size 10000 ^
  --dd-tolerance 10 ^
  --broker-gmt 2 ^
  --compare-broker-gmt 2 ^
  --compare-tick-gmt 2 ^
  --default-scale 1.0 ^
  --tester-period H1 ^
  --tester-model 4 ^
  --tester-delay-ms 50 ^
  --tester-order-filling AUTO ^
  --tester-deposit 10000 ^
  --tester-leverage 100 ^
  --tester-use-local ^
  --excluded-symbols-file "%EXCLUDED_SYMBOLS_FILE%" ^
  --run-review-now ^
  --real-period-backtests-only
if errorlevel 1 goto :failed

echo.
echo Stage 1 complete.
echo Same-period backtests saved under: %STAGE1_RUN_DIR%\backtests\real_period
pause
exit /b 0

:missingA
echo ERROR: Broker A credential files are empty.
pause
exit /b 1

:missingB
echo ERROR: Broker B credential files are empty.
pause
exit /b 1

:failed
echo.
echo ERROR: Stage 1 stopped because one of the runs failed.
pause
exit /b 1
