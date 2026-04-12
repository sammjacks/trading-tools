# Stage 3 Portfolio Tick Check

Multi-strategy portfolio backtest combiner that runs the same portfolio twice:
once using bar data and once using tick data, then writes separate outputs for comparison.

## Files in this folder
- `portfolio_backtest.py` — main portfolio analysis script
- `run_portfolio_backtest.cmd` — driver with strategy blocks plus bar/tick data paths

## What it does
- Loads multiple backtests and their bar files
- Loads matching tick files for the same symbols
- Builds per-strategy daily balance and equity curves from bars
- Builds per-strategy daily balance and equity curves from ticks
- Combines strategies on a unified daily timeline
- Computes portfolio net profit, drawdown, safety factor, and monthly return
- Exports separate HTML and xlsx reports under `bars/` and `ticks/`

## Normal workflow
1. Edit `run_portfolio_backtest.cmd`.
2. Set `BARS_DIR`, `BARS_SUFFIX`, `TICKS_DIR`, and `TICKS_SUFFIX`.
3. Enable the strategy blocks you want included.
4. Set account size and drawdown tolerance.
5. Run the `.cmd` file.

## Notes
- This tool is standalone and does not import `basket_analysis.py`.
- Scaling applies to both P&L and lot sizes so drawdown scales correctly.
- Stage 3 does not run the Stage 2 subset optimizer; it is focused on bar-vs-tick comparison.
