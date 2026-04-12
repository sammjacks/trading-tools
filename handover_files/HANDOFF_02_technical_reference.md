# Tools Technical Reference

## basket_analysis.py

### Core architecture

**Data flow:**
```
statement.htm  →  parse_statement()  →  trades + balance_ops
bars.csv       →  load_bars()        →  bars + bar_ts
ticks.csv      →  load_ticks()       →  ticks + tick_ts

trades  →  make_baskets(window=10s)  →  baskets (clustered by close-time)
                                         per direction)

trades + balance_ops + bars  →  build_equity_curve()  →  curves [{ts,bal,eq}]
curves  →  curves_to_daily()  →  ([dates], [bal], [eq])
```

**Key functions and their signatures:**
- `parse_statement(path, broker_gmt, symbol_filter)` → `(trades, balance_ops)`
  - Auto-detects MT4 live, MT4 tester, MT5 tester
  - Handles UTF-8, UTF-16 LE/BE, UTF-8 BOM
  - Returns trade dicts with `type, ts, close_ts, price, close_price,
    lots, profit, commission, swap, time, close_time, symbol`
- `load_bars(path)` → `(bars, bar_ts)` — CSV with `unix_ts,o,h,l,c`
- `load_ticks(path, tick_gmt)` → `(ticks, tick_ts)` — CSV with
  `"DD.MM.YYYY HH:MM:SS.mmm",ask,bid,...`
- `make_baskets(trades, close_window_seconds=10)` → `baskets`
  - Per-direction time-window clustering (handles mass-close events)
  - Each basket: `{pnl, count, direction, first_ts, close_ts,
    first_price, time, group}`
- `build_equity_curve(trades, balance_ops, bars, sample_every=15)`
  - O(N_bars + N_trades) sweep with active-list tracking
  - Returns sampled curve points + terminal point reflecting all
    trades that closed past the last bar
- `compute_stats(trades, baskets, curves)` → big stats dict with
  trade-level AND basket-level breakdowns + equity stats
- `build_synthetic_trades()` and `build_synthetic_trades_ticks()` for
  SL simulation
- `simulate_sl_full()` and `simulate_sl_full_ticks()` for full
  SL stat wrappers
- `build_sl_scan_text(engine="bar"|"tick")` for scan tables
- `build_filter_results_text()` and `run_filter_optimization()` for
  Step 4

### Important implementation details

**Basket clustering rule (line ~250):**
Trades of the same direction whose close_ts values fall within
`close_window_seconds` of the running anchor are merged into one
basket. The 10s default handles both normal basket TPs (close
within 1-2s) and EA daily-DD mass closes (take 5-10s to
sequentially close all positions). Data saturates at 10s — beyond
that no more merging happens.

**Equity curve terminal point (line ~370):**
The sweep loop samples bars at fixed stride. After the loop, any
trades/balance_ops that haven't been processed yet (because they're
past the last bar) are processed in a final pass and a terminal
curve point is appended. Without this, baskets that close after the
last bar in the data would silently be dropped from the final balance.

**Trade-level vs basket-level stats:**
Both are computed in `compute_stats()`. Use trade-level metrics
(PF, gross profit/loss, win rate) when comparing live vs backtest
because basket-level basket-WR will always be 100% for a backtest
without basket SL (every basket eventually hits TP). Trade-level
shows the meaningful difference.

**Comparison report 4-panel chart layout:**
The HTML comparison report has FOUR canvases:
1. Equity curves (overlay) — both lines together
2. Backtest equity (alone) — full-width view of backtest's V dip
3. Live equity (alone) — full-width view of live's W dip
4. Balance curves (overlay)

This layout exists because when both equity curves dip together
they visually compress into one shape and the user can't see
individual dips. The "alone" panels solve this.

**Filter optimization (Step 4):**
- `precompute_trade_context()` attaches `open_spread_pips`,
  `open_hour`, `open_dow` to each trade by binary-searching the
  tick array for the nearest tick at the trade's entry timestamp
- `tag_trades_with_baskets()` attaches `basket_idx` and
  `is_basket_first` flags
- `apply_trade_filters()` does the actual gating: session/spread_initial/
  day filters drop the WHOLE basket if the first trade fails;
  spread_all filter drops individual trades within an allowed basket
- `fast_realized_stats()` computes net + balance DD by sweeping
  realized P&L sorted by close_ts (no bar data needed) — this is
  what makes 7000 trials run in seconds
- `run_filter_optimization()` runs the grid, then **deduplicates**
  by `(trades, baskets, net, max_dd)` fingerprint, keeping the
  combo with the fewest active filters
- The full equity curve is rebuilt only for the #1 result for the
  HTML chart overlay

### CLI arguments (full list)

```
--statement PATH         (required) MT4/MT5 HTML statement
--bars PATH              (required) bars CSV
--ticks PATH             optional tick CSV
--symbol SYMBOL          symbol filter
--start YYYY-MM-DD       date range start
--end YYYY-MM-DD         date range end
--broker-gmt N           default 2
--tick-gmt N             default 2
--sl-range MIN MAX       SL scan range (pips)
--tick-sl-range MIN MAX  separate range for tick comparison
--final-sl PIPS          single-SL final check mode
--final-eod              enable EOD close in final check
--eod-time HH:MM         default 23:59
--open-hours START END   restrict baskets opened in this hour range
--lot-size N             filter trades by lot size
--initial-balance AMT    synthesize a deposit (for tester reports)
--lot-size N             filter by lot size
--spread-profile PATH    load saved spread profile JSON
--save-curve             export curve JSON for combining
--basket-close-window S  cluster window (default 10)
--engine bar|tick        force engine for final check
--backtest PATH          comparison mode (live vs backtest)
--combine FILE...        portfolio combining mode
--out-dir PATH           output directory

# Filter optimization (Step 4):
--filter-optimize             enable filter optimization mode
--session-step H              hour granularity (default 2)
--min-session-width H         min window width (default 4)
--spread-values X X X         pip thresholds to test (default 0 0.5 1 1.5 2 3)
--day-options OPT OPT         day filters: none|no-mon|no-fri|no-mon-fri|
                              no-mon-sun|no-fri-sun
--top-results N               how many to show (default 20)

# Stats-only:
--stats-only                  skip MAE/SL scan, just stats summary
```

## portfolio_backtest.py

### Core architecture

Standalone tool — does NOT import basket_analysis.py. Has its own
copies of `parse_statement` (renamed `parse_backtest`), `load_bars`,
`build_equity_curve`, `curves_to_daily`. The two tools share a lot
of logic conceptually but no code.

**Data flow:**
```
strategy_args  →  parse_strategy_arg()  →  configs
configs        →  load_strategy()       →  strategies (per-symbol curves)
strategies     →  combine_curves()      →  combined (sum on unified timeline)

If --optimize:
  strategies → find_optimal_combinations() → results (filtered by SF/Monthly%)
  results    → select_diverse_top_n()      → top portfolios
  top        → export_top_portfolios()     → subfolders with mini xlsx + files
```

### Key functions

- `read_text_file(path)` — encoding sniffer (UTF-8, UTF-16 BOM, BOMless UTF-16)
- `parse_backtest(path, broker_gmt, symbol_filter)` → `(trades, format_name)`
- `_parse_mt5_tester()` — handles the Deals table with in/out direction
  pairs, FIFO-matched by opposite type
- `_parse_mt4_tester()` — separate open/close rows matched by order ID
- `_parse_mt4_live()` — 14-column trade rows
- `load_bars()` — same CSV format as basket_analysis.py
- `_pip_size(price)` — 0.01 for JPY pairs (price > 20), 0.0001 otherwise
- `_trade_mtm()` — approximate $10/pip P&L
- `build_equity_curve()` — sampled equity sweep, returns curves
- `curves_to_daily()` — last sample per UTC day
- `max_drawdown()` — running peak starts at max(values[0], 0)
- `months_between()` — uses 30.44 days/month
- `filter_trades_to_recent_months()` — windows the trade list to the
  last N months (used by --backtest-months)
- `compute_risk_metrics()` — Safety Factor + Monthly %
- `combine_curves()` — sums per-strategy curves on unified daily timeline
- `combine_curves_scaled()` — same but with per-strategy multipliers
- `rescale_strategy()` — returns a copy with all money values × ratio
- `find_optimal_combinations()` — enumerates subsets × scales, filters
  by SF and monthly thresholds, returns ranked list. Has a duplicate-
  symbol guard.
- `select_diverse_top_n()` — greedy: pick best, then pick the candidate
  with fewest overlapping symbols, repeat. Has duplicate-symbol filter.
- `export_top_portfolios()` — creates subfolders, generates mini xlsx
  per portfolio, copies backtest files via stem-glob (picks up the
  .htm + all sibling PNGs)
- `write_portfolio_xlsx()` — main + Optimization sheet, all live formulas
- `_sanitize_filename()` — Windows-safe folder names, capped at 100 chars

### Important implementation details

**base_lot uses MODE not first trade:**
Some backtests (especially basket EAs) have anomalous first trades
where the EA opens with a non-standard lot size before settling
into its base unit. Using `trades[0]["lots"]` gives wrong results.
The fix uses `Counter(round(t["lots"], 4) for t in trades).most_common(1)[0][0]`
which is robust against initial anomalies.

**Scaling applies to BOTH profit AND lots:**
A strategy at scale=2.0 has its `profit`, `commission`, `swap`, AND
`lots` all multiplied by 2. Scaling only the profit fields produces
correct net P&L but wrong DD because `build_equity_curve` computes
floating P&L from `lots × price_movement`. This was a bug caught
during testing of the scaled optimizer.

**Diverse top-N selection algorithm:**
Pick #1 = best passing combination (already sorted by monthly %).
For each subsequent pick, score remaining candidates by
`(-overlap, monthly_pct, safety_factor)` and pick the highest.
This is a greedy heuristic, not global optimum, but works well in
practice on small search spaces.

**Subfolder file copying via stem-glob:**
For each strategy in a top portfolio, takes the BT path's stem and
globs `{stem}*` in the source folder, copies all matches. This
catches the main .htm/.html plus MT5's sibling PNG charts
(`*-hst.png`, `*-mfemae.png`, `*-holding.png`) automatically.

### CLI arguments

```
--strategy "SYMBOL|BT|BARS|SCALE|GMT|FILTER"  (required, repeat per strategy)
                                              SCALE default 1.0, GMT default 2
                                              FILTER overrides symbol for
                                              parsing — empty = no filter
--out-dir PATH               output directory (default .)
--title TEXT                 HTML title
--account-size AMT           default 10000
--dd-tolerance PCT           default 10 (= 10%)
--backtest-months N          filter to last N months (no override = full data)
--no-xlsx                    skip xlsx output

# Optimization:
--optimize                   enable subset search
--min-safety-factor X        default 1.5
--min-monthly-pct PCT        default 1.5
--min-strategies N           default 1
--max-strategies N           default 3
--max-scale N                each strategy tested at 1, 2, ..., N (default 5)
--top-n N                    diverse top portfolios to export (default 3)
```

## Common debugging patterns

**Wrong-bars-file detection:**
If equity curve looks completely wrong (huge DD, nonsense MAE, SL
scan locked at identical Won/Lost), check that the bars CSV matches
the statement's symbol. Passing EURUSD bars with a USDCAD statement
gives this kind of wreckage.

**`is not recognized as an internal or external command`:**
The user stripped `REM` from a comment header line in a cmd file.
Comment lines must keep `REM`; only the `set` lines should have
the prefix removed when enabling a strategy block.

**`||||` in --strategy argument:**
The cmd file's STRATn variables are unset but the build-command
line still expanded them. Old design used a counter (`N_STRATEGIES`)
that could fall out of sync with actual variable definitions. New
design uses `if not "%STRATn_BT%"==""` to test inclusion.

**Backtest dip not visible in chart:**
The 4-panel layout solves this. Both curves dipping in the same
region get visually compressed. The "alone" panels show each curve
independently.

**Files don't exist with `.html` but do with `.htm`:**
`portfolio_backtest.py` has a fallback that tries swapping `.html`
↔ `.htm` if the specified path doesn't exist. The user's actual
files are sometimes one or the other depending on MT4/MT5 version.

## Skill files used

- `xlsx` skill for spreadsheet creation. The `recalc.py` script at
  `/mnt/skills/public/xlsx/scripts/recalc.py` validates that no
  formula errors exist after writing — always run after creating
  xlsx files.
