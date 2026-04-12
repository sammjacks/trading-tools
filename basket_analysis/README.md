# Basket Analysis

Single-strategy analysis tool for MT4/MT5 live statements and backtests.

## Files in this folder
- `basket_analysis.py` — main analysis script
- `run_basket_analysis_1_compare.cmd` — Step 1: live vs backtest comparison or baseline stats
- `run_basket_analysis_2_bar.cmd` — Step 2: bar-based SL scan or final check
- `run_basket_analysis_3_tick.cmd` — Step 3: tick-precision SL scan or final check
- `run_basket_analysis_4_filter.cmd` — Step 4: filter optimization
- `run_combine.cmd` — combine saved curve JSON files across pairs

## What it does
- Parses MT4 live statements, MT4 strategy tester reports, and MT5 tester reports
- Builds balance and equity curves from bar data
- Clusters trades into baskets using close-time grouping
- Runs basket SL scans in bar mode or tick mode
- Compares live vs backtest performance
- Optimizes filters such as session, spread, and day-of-week
- Exports JSON curves for portfolio-style combining

## Normal workflow
1. Run `run_basket_analysis_1_compare.cmd` for baseline comparison or a single baseline report.
2. Run `run_basket_analysis_2_bar.cmd` for bar-based SL exploration.
3. Run `run_basket_analysis_3_tick.cmd` for tick-precision validation.
4. Run `run_basket_analysis_4_filter.cmd` for filter optimization.
5. Run `run_combine.cmd` if you want to combine saved final-check curves from multiple pairs.

## Notes
- The `.cmd` files in this folder are self-contained and now force their own working directory.
- Edit the path variables at the top of each `.cmd` file before running.
- Step 4 is the current latest work area. Stage 2 is expected to add basket SL and EOD close into the filter grid.
- The original imported snapshot is still preserved in `handover_files`.
