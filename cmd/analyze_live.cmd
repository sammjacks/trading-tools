@echo off
:: analyze_live.cmd
:: Analyse live trading results and compare them against a backtest baseline.
::
:: Usage:
::   analyze_live.cmd [config]
::
:: Arguments:
::   config   Path to YAML config file (default: config\analyze_live.yaml)

setlocal

set CONFIG=%~1
if "%CONFIG%"=="" set CONFIG=config\analyze_live.yaml

python -m tools.live_results.analyze_live --config "%CONFIG%"
endlocal
