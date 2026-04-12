@echo off
:: compare_backtests.cmd
:: Compare two or more backtest result files.
::
:: Usage:
::   compare_backtests.cmd [config]
::
:: Arguments:
::   config   Path to YAML config file (default: config\compare_backtests.yaml)

setlocal

set CONFIG=%~1
if "%CONFIG%"=="" set CONFIG=config\compare_backtests.yaml

python -m tools.backtest_comparison.compare_backtests --config "%CONFIG%"
endlocal
