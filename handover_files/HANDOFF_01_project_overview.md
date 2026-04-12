# Trading Tools Project — Handoff Document

## Who I am and what I do

I'm an algorithmic trader who develops and analyzes basket/grid trading
strategies (averaging EAs) across multiple Forex pairs. I work primarily
in MT4 and MT5, run backtests through their Strategy Tester, then bring
the results into Python tools for deeper analysis than the built-in
reports allow.

My ultimate goal on every strategy is **return / drawdown** — I care
much more about risk-adjusted return than raw profit. I run live
accounts (currently on darwinex) and use the tools to:

1. Compare live performance against backtest to verify the EA is
   behaving as expected
2. Find ways to improve existing strategies (filters, basket SL, EOD
   close, session restrictions)
3. Combine multiple strategies into portfolios and find diversified
   subsets that hit safety + profitability targets
4. Run backtests on a wide pool of strategies and pick the best
   non-overlapping combinations

## What I've built so far (with Claude's help over many sessions)

Two main tools, both in Python, both fully working:

### 1. `basket_analysis.py` — single-strategy deep analysis
- Parses MT4 live statements, MT4 strategy tester reports, and MT5
  strategy tester reports (auto-detected, handles UTF-16)
- Builds equity curves from M1/M5 bars + tick data
- Basket clustering with configurable time window (default 10s)
- Trade-level AND basket-level statistics
- Live-vs-backtest comparison mode with 4-panel chart layout
- Bar-based and tick-precision SL scans
- Hourly breakdown with spread statistics
- Final-check mode for a specific SL value
- Filter optimization (session/spread/day-of-week grid search)
- Stats-only mode for quick reports
- HTML reports with Chart.js
- JSON curve export for portfolio combining

Driven by 4 cmd files numbered 1-4 for the main workflow:
- `run_basket_analysis_1_compare.cmd` — comparison or baseline
- `run_basket_analysis_2_bar.cmd` — bar SL scan or final check
- `run_basket_analysis_3_tick.cmd` — tick SL scan or final check
- `run_basket_analysis_4_filter.cmd` — filter optimization (NEW)

Plus `run_combine.cmd` for multi-pair combining via saved JSON curves.

### 2. `portfolio_backtest.py` — multi-strategy portfolio combining
- Standalone (no dependency on basket_analysis.py)
- Same MT4/MT5 format auto-detection as the main tool
- Combines N fixed-lot backtests on a unified daily timeline
- Per-strategy scaling factor (multiplies trade P&L AND lot sizes
  so DD scales correctly)
- Risk metrics: Safety Factor, Monthly %, Allowable DD
- Optimization mode: tests every subset combination at every integer
  scale 1-MAX_SCALE per strategy
- Top-N diverse selection: greedy algorithm picks N portfolios that
  share strategies as little as possible
- Per-portfolio subfolder export: copies the backtest HTML + all
  associated PNG charts via stem-glob, generates a mini summary xlsx
- Outputs both HTML and xlsx reports with live formulas

Driven by `run_portfolio_backtest.cmd`.

## My setup

- Windows machine
- Python 3 with `openpyxl` installed
- I work in folders like `D:\Work\market_master_test\` or
  `D:\Work\hexaflow_test\` with the script + cmd file at the root,
  backtest HTMs alongside, and bars CSVs sometimes in a separate
  folder (`D:\Work\M5_tillStartApril\`)
- Backtest exports are typically named like
  `Hexaflow8_settingseurusdh1.htm` (8th iteration of the Hexaflow EA
  on EURUSD H1) and come with sibling PNG files like `*-hst.png`,
  `*-mfemae.png`, `*-holding.png` from MT5's report
- Bars files typically named `EURUSD_GMT+2_US-DST_M5.csv` etc

## How I prefer to work

- I describe what I want, the assistant builds it
- I run it locally and report bugs or issues with screenshots
- I value clear cmd file design — each variable should have a comment
  explaining what it does, paths should be short and editable, and
  enabling/disabling options should be obvious
- I push back when something doesn't work and expect the assistant
  to actually root-cause, not patch symptoms
- I often request iterative improvements ("now add X", "now also do
  Y") rather than huge feature sets at once
- I appreciate honest "untested" disclaimers when the assistant
  ships something it couldn't fully verify

## Where we are right now

Just finished implementing the filter optimization feature (Step 4 of
the basket_analysis workflow). It tests combinations of session
windows, spread thresholds, and day-of-week filters to find the
filter set that maximizes Ret/DD without using basket SL or EOD
close (those will be added in stage 2 later).

The tool dedupes results that produce identical outcomes so the
top-N table shows genuinely different filter strategies, not
variations of the same one with redundant filters.

Both `basket_analysis.py` and `run_basket_analysis_4_filter.cmd` are
ready to use. The other files in the basket_analysis suite are at a
stable state and don't need changes unless I report issues.

The portfolio_backtest tool is also in a stable, working state. The
last fix in that tool was a duplicate-symbol guard in the optimizer
plus a base_lot bug fix where it now uses the mode of all trade lot
sizes instead of the first trade's lots (fixed the GBPUSD 0.03 issue).
