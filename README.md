# trading-tools

Suite of Python trading tools for analyzing single-strategy backtests, live results, and multi-strategy portfolios.

## Structure

- `basket_analysis/` — single-strategy trading analysis tool
- `portfolio/` — multi-strategy portfolio backtester and combiner
- `stage1_real_results_vs_backtest/` — backtest validation tool (new)
- `handover_files/` — original snapshot and handoff documents (reference)

## Tools

### basket_analysis
Single-strategy deep analysis for live-vs-backtest comparison, bar/tick stop-loss testing, filter optimization, and equity curve export for combining.

**Key features:**
- Live results comparison (real vs backtest side-by-side)
- Bar and tick-level stop-loss backtesting
- Daily SL filter grid optimization (session, spread, day-of-week)
- Multi-pair combining on unified timeline
- Chart.js HTML reports with 4-panel layouts

**Workflow:**
1. `run_basket_analysis_1_compare.cmd` — compare real vs backtest
2. `run_basket_analysis_2_bar.cmd` — test SL placement at bar level
3. `run_basket_analysis_3_tick.cmd` — test SL placement at tick level
4. `run_basket_analysis_4_filter.cmd` — optimize entry filters
5. `run_combine.cmd` — combine multiple pairs into portfolio

### portfolio
Multi-strategy portfolio combiner supporting strategy subset selection, per-strategy scaling, diversity constraints, and optimization mode for exploring scale combinations.

**Key features:**
- Per-strategy lot scaling with live formula export (xlsx)
- Diverse top-N selection (minimize correlation)
- Optimization mode: grid search across strategy subsets and scales
- Multi-timeframe combining
- Profit factor and return/DD metrics

**Workflow:**
```
python portfolio_backtest.py \
    --strategy "EA_Name:backtest_report.htm:ticks.csv" \
    --strategy "EA_Name2:backtest_report2.htm:ticks2.csv" \
    --scale 0.5 0.75 1.0 \
    --diverse 5 --min-strategies 2 \
    --out-dir ./results
```

### stage1_real_results_vs_backtest (NEW)
Validates backtest accuracy by comparing real trading results against MT4/MT5 backtest expectations. Generates a multi-dimensional closeness score (0–100) across 8 metrics:

**Scoring dimensions:**
- Trade count similarity
- Trade timing similarity (entry/exit time alignment)
- Trade duration matching
- Win rate comparison
- Profit factor comparison
- Return/DD comparison
- Max drawdown comparison
- Net profit similarity

**Workflow:**
```
python stage1_real_results_vs_backtest.py \
    --real-statement real_account.htm \
    --backtest backtest_report.htm \
    --ticks eurusd_ticks.csv \
    --symbol EURUSD \
    --out-dir ./comparison_results
```

**Output:** Interactive HTML report with equity curve overlay and detailed metrics. Score ≥80 indicates high backtest-vs-reality fidelity.

---

*All working versions live in separate folders for independent maintenance. Original imports preserved in `handover_files/`.*
