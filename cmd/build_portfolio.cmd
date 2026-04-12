@echo off
:: build_portfolio.cmd
:: Construct a risk-managed portfolio from a set of strategies.
::
:: Usage:
::   build_portfolio.cmd [config]
::
:: Arguments:
::   config   Path to YAML config file (default: config\portfolio.yaml)

setlocal

set CONFIG=%~1
if "%CONFIG%"=="" set CONFIG=config\portfolio.yaml

python -m tools.portfolio.build_portfolio --config "%CONFIG%"
endlocal
