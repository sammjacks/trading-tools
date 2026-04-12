# trading-tools

A suite of Python tools for comparing backtests and live trading results, setting risk parameters, and building risk-managed portfolios. Each tool is invoked via a `.cmd` launcher script.

## Project Structure

```
trading-tools/
├── tools/                        # Core Python tool packages
│   ├── backtest_comparison/      # Compare backtest runs against each other
│   ├── live_results/             # Analyse and compare live trading results
│   ├── risk_management/          # Set and evaluate per-strategy risk limits
│   └── portfolio/                # Build and manage risk-managed portfolios
├── cmd/                          # Windows .cmd launchers for each tool
├── config/                       # YAML configuration templates
├── data/                         # Input/output data files (excluded from git)
└── tests/                        # Unit and integration tests
```

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt`

## Installation

```bash
pip install -r requirements.txt
```

Or install the package in editable mode:

```bash
pip install -e .
```

## Usage

Each tool is run via its corresponding `.cmd` file in the `cmd/` directory.  
Edit the relevant YAML config in `config/` before running.

| CMD file | Description |
|---|---|
| `cmd/compare_backtests.cmd` | Compare multiple backtest result files |
| `cmd/analyze_live.cmd` | Analyse live trading results |
| `cmd/set_risk.cmd` | Apply risk limits to a strategy or set of strategies |
| `cmd/build_portfolio.cmd` | Construct a risk-managed portfolio |

## Development

Run tests:

```bash
pytest
```
