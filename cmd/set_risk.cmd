@echo off
:: set_risk.cmd
:: Apply risk limits to one or more strategies.
::
:: Usage:
::   set_risk.cmd [config]
::
:: Arguments:
::   config   Path to YAML config file (default: config\risk_management.yaml)

setlocal

set CONFIG=%~1
if "%CONFIG%"=="" set CONFIG=config\risk_management.yaml

python -m tools.risk_management.set_risk --config "%CONFIG%"
endlocal
