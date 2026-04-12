# Portfolio

Multi-strategy portfolio backtest combiner for fixed-lot MT4/MT5 backtests.

## Files in this folder
- `portfolio_backtest.py` — main portfolio analysis script
- `run_portfolio_backtest.cmd` — driver with strategy blocks and optimization settings

## What it does
- Loads multiple backtests and their bar files
- Builds per-strategy daily balance and equity curves
- Combines strategies on a unified daily timeline
- Computes portfolio net profit, drawdown, safety factor, and monthly return
- Supports subset optimization with per-strategy integer scale testing
- Exports HTML and xlsx reports
- Exports top diverse portfolios into their own subfolders with copied backtest artifacts

## Normal workflow
1. Edit `run_portfolio_backtest.cmd`.
2. Set `BARS_DIR` and `BARS_SUFFIX` once.
3. Enable the strategy blocks you want included.
4. Set account size, drawdown tolerance, and optional optimization thresholds.
5. Run the `.cmd` file.

## Notes
- This tool is standalone and does not import `basket_analysis.py`.
- Scaling applies to both P&L and lot sizes so drawdown scales correctly.
- The original imported snapshot is still preserved in `handover_files`.
