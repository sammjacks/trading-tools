# Conversation History — Key Decisions and Bug Fixes

This is a chronological summary of the major work done across this
multi-turn conversation. Each entry explains what was added or fixed
and why.

## Stage 1: basket_analysis.py refinement (early conversation)

### Comparison report fixes
- **Trade-level stats added**: Originally the live-vs-backtest comparison
  showed only basket-level metrics, which produced 100% basket WR for
  the backtest (no SL → every basket eventually hits TP) and "infinity"
  PF. This made the comparison meaningless. Fix: split the comparison
  table into Trade-level and Basket-level sections. Trade-level rows
  show real PF, gross profit/loss, win rate from individual positions
  and produce the meaningful comparison (live PF 1.88 vs backtest PF 1.74).
- **4-panel chart layout**: Backtest dip on Jan 27 was invisible in the
  overlay chart because both curves dipped together. Tried multiple
  rendering tweaks (no smoothing, dashed lines, point markers, color
  changes) without success. Final solution: add separate "Backtest
  equity (alone)" and "Live equity (alone)" panels alongside the
  overlay so each curve can be inspected independently.
- **Backtest normalization**: When the backtest has no balance_ops
  (MT4 strategy tester), synthesize a deposit matching live's starting
  balance so both curves render on the same dollar scale.

### Basket clustering bug
- **Mass-close events**: User noticed live had max basket size 10 but
  the EA's daily DD protection had force-closed 33 positions on
  Jan 30 17:32. Original `make_baskets` grouped by exact `close_ts`,
  which kept those 33 trades as 11 separate baskets because broker
  closes propagate over several seconds.
- **Fix**: Per-direction time-window clustering with 10s default
  window. Tested windows 0-300s; data saturates at 10s (no more
  merging happens beyond that). Live max basket size now correctly
  shows 33, basket count gap with backtest dropped from 67% to 5%.
- **CLI flag**: Added `--basket-close-window SECONDS` for tuning.

### Windows batch delayed-expansion bug
- **Symptom**: `FINAL_EOD=1` in the cmd files for Steps 2 and 3
  silently dropped the `--final-sl` flag, causing the script to
  run scan mode instead of final check.
- **Root cause**: Nested `set CMD=%CMD% ...` statements inside an
  `if (...)` block all expand `%CMD%` at parse time using the
  pre-block value, so the second `set` overwrites the first.
- **Fix**: Flat conditionals — each `set` is a top-level statement:
  ```batch
  if not "%FINAL_SL%"=="" set CMD=%CMD% --final-sl %FINAL_SL%
  if not "%FINAL_SL%"=="" if "%FINAL_EOD%"=="1" set CMD=%CMD% --final-eod
  if "%FINAL_SL%"=="" set CMD=%CMD% --sl-range %SL_MIN% %SL_MAX%
  ```

### Stats-only mode
- **Use case**: User wanted a quick baseline report on a backtest
  alone without running the full SL scan (which is the slow part).
- **Implementation**: New `--stats-only` flag short-circuits the
  main flow after the hourly breakdown, computes the same trade/
  basket/equity stats as the comparison mode but in single-column
  format, and writes a simplified HTML report. Wired into
  `run_basket_analysis_1_compare.cmd` for the backtest-only branch.

## Stage 2: portfolio_backtest.py development

### Initial design
- **Purpose**: Combine multiple fixed-lot backtests into a single
  portfolio equity view to see what trading them all side-by-side
  would have looked like, with optional per-strategy scaling.
- **Initial implementation**: Imported `parse_statement`, `load_bars`,
  `build_equity_curve` from `basket_analysis.py` via `sys.path`
  manipulation.
- **First failure**: User got `ModuleNotFoundError: No module named
  'basket_analysis'` when running from a different cwd despite both
  files being in the same folder. Fix: switched to `importlib.util`
  with explicit absolute path resolution from the script's location.
- **Second decision**: User asked for it to be fully standalone with
  no dependency on basket_analysis.py. Rewrote the file to include
  its own copies of the parser, bar loader, and curve builder. The
  parser was extended to also handle MT5 tester reports (Deals table
  with in/out direction pairs, FIFO-matched).

### Encoding handling
- **Problem**: MT5 reports are UTF-16 LE with BOM, MT4 reports are
  UTF-8.
- **Fix**: `read_text_file()` sniffs the first 2 bytes for BOM (UTF-16
  LE/BE), then UTF-8 BOM, then a NUL-byte heuristic for BOMless
  UTF-16, then falls back to UTF-8.

### Scaling bug
- **Problem**: Initial scaling implementation multiplied only
  `profit`, `commission`, `swap`. Net P&L scaled correctly but
  Max DD did NOT.
- **Root cause**: `build_equity_curve` computes mark-to-market
  floating P&L from `lots × price_movement`. With unscaled lots,
  the floating P&L stayed at 1x even though closed P&L was 2x.
- **Fix**: Scale `lots` too. Verified: 1x + 2x produces exactly 3x
  net AND 3x DD, with Ret/DD preserved across all rows.

### GBPUSD lot size bug
- **Symptom**: GBPUSD strategy showed lot size 0.03 in the table even
  though the user's EA was configured for 0.01.
- **Root cause**: `base_lot = trades[0]["lots"]` picked up the very
  first trade in the GBPUSD Deals table, which happened to be 0.03
  (anomalous EA initialization). 73% of trades were actually 0.01.
- **Fix**: Use `Counter.most_common(1)` to find the mode of all
  trade lot sizes. This correctly identifies 0.01 even when the
  first few trades are anomalous.

### Risk metrics added
- **Inputs**: User wanted to specify an account size and DD tolerance
  percentage, then see derived metrics matching their existing
  Trading.xlsx workbook.
- **Formulas**:
  - `Allowable DD = Account Size × DD Tolerance`
  - `Safety Factor = Allowable DD / Max DD` (>1 = within budget)
  - `Monthly % = (Net P&L / Account Size) / Backtest Months`
- **CLI**: `--account-size`, `--dd-tolerance`, `--backtest-months`

### Backtest months filter (bug fix)
- **Initial bug**: `--backtest-months N` only changed the denominator
  in the monthly % calculation. The Net P&L and DD were still
  computed from the full backtest period — nonsense.
- **Fix**: New `filter_trades_to_recent_months()` actually drops
  trades outside the most-recent-N-months window before any other
  calculation runs. Console shows `Filtered to most recent N months:
  kept X/Y trades (dropped Z)`.

### XLSX output
- **Use case**: User wanted a downloadable Excel workbook with the
  same per-strategy + portfolio table, with live formulas so they
  could tweak account size or DD tolerance and see updated values.
- **Implementation**: `write_portfolio_xlsx()` using openpyxl. Input
  cells (yellow fill, blue font) at the top, table rows below with
  formulas referencing `$B$3`/`$B$4` for account/tolerance. Verified
  with `recalc.py` to ensure 0 formula errors.
- **User edit**: Removed the Scale column and the formula definitions
  notes section per request.

### Optimization mode
- **Phase 1**: Subset search testing every non-empty combination of
  loaded strategies. Found combinations whose combined SF and
  Monthly % both met user-defined thresholds.
- **Phase 2 (scaled)**: User wanted to also test integer scale
  multipliers per strategy. New `combine_curves_scaled()` applies
  per-strategy multipliers without rebuilding strategy dicts.
  Search space: subsets of size [MIN, MAX] × scales [1, MAX_SCALE]
  per strategy. Default 1-3 strategies, scales 1-5 = ~7700 trials
  for 8 strategies, runs in seconds.
- **CLI**: `--optimize`, `--min-safety-factor`, `--min-monthly-pct`,
  `--min-strategies`, `--max-strategies`, `--max-scale`, `--top-n`

### Diverse top-N selection
- **Use case**: User wants 3 portfolios that are as different from
  each other as possible (use overlapping strategies as little as
  possible) so the trading risk is decorrelated.
- **Algorithm**: Greedy. Pick #1 = best passing combination. For
  each subsequent pick, score remaining candidates by
  `(-overlap, monthly_pct, safety_factor)` and pick the highest.
  Heuristic but works well in practice.
- **Output**: Each top portfolio gets its own subfolder named like
  `TopPortfolio_1_EURUSD-x5_GBPUSD-x1_EURMT4-x3/` containing a mini
  `portfolio_summary.xlsx` plus copies of every strategy's backtest
  HTM/HTML and all sibling PNG charts (matched via `{stem}*` glob).

### Duplicate symbol bug
- **Symptom**: User reported a top portfolio that listed GBPUSD twice
  with different scales (`AUDUSD-x2 GBPUSD-x4 EURUSD-x2` had a
  `GBPUSD-x1 GBPUSD-x5` variant somewhere).
- **Root cause**: Couldn't reproduce in test — `itertools.combinations`
  cannot produce duplicate indices. Suspected possibility: user data
  somehow contained two strategies that mapped to the same internal
  index (perhaps via a stale config or duplicate STRATn entry).
- **Fix**: Three layers of defense:
  1. Optimizer: skip any subset where `len(set(symbols)) != len(symbols)`
  2. Diverse selector: pre-filter passing results with the same check
  3. Export-time: verify symbols match indices, print warning if not
  Plus diagnostic prints showing strategy index mapping and per-portfolio
  indices/symbols/scales for next-time debugging.

### CMD file design iterations
The portfolio cmd file went through several design iterations as the
user gave feedback:
1. **First**: Used `N_STRATEGIES=3` counter that had to match how many
   strategy blocks were uncommented. User accidentally bumped the
   counter without uncommenting, got `||||` in the command. Fix:
   removed counter, use `if not "%STRATn_BT%"==""` for inclusion.
2. **Second**: User wanted relative paths (`.\filename`) instead of
   full paths everywhere. Added `cd /d "%~dp0"` at the top so
   relative paths always resolve correctly.
3. **Third**: User wanted bars files auto-derived from symbol name.
   Added `BARS_DIR` and `BARS_SUFFIX` variables; build-command line
   constructs `%BARS_DIR%\%STRAT1_SYMBOL%%BARS_SUFFIX%` automatically.
4. **Fourth**: User uncommented strategy blocks but stripped `REM`
   from the comment header lines too, getting `--- is not recognized`
   errors. Fix: switched header style from `REM ---` to `REM ===`
   and added explicit instructions in the file header explaining
   that `REM` must stay on comment lines.
5. **Fifth**: `.htm` vs `.html` mismatch — user's files were .htm
   but cmd file said .html. Tool now auto-falls back to the other
   variant if the specified extension doesn't exist.

## Stage 3: Step 4 filter optimization (most recent)

### Goal
User wants to improve the original strategy by finding filters that
reduce drawdown more than they reduce profit, optimizing for
Ret/DD. The filter dimensions are session windows, spread thresholds
(initial trade and all trades), and day-of-week skips. Basket SL and
EOD close are explicitly NOT being optimized at this stage — they'll
be added in stage 2 of this work later.

### Implementation
- **Precompute step**: At load time, attach `open_spread_pips` (from
  nearest tick), `open_hour`, `open_dow` to every trade dict. Also
  tag each trade with `basket_idx` so filters can act per-basket.
- **Fast screening loop**: For each filter combo in the grid, filter
  trades and compute realized P&L + balance DD with `fast_realized_stats()`.
  This is O(N) per trial, microseconds. Full equity curve only built
  for the #1 result for the chart overlay.
- **Filter logic**: Session/spread_initial/day filters gate on the
  basket's first trade — if it fails, the whole basket is dropped.
  spread_all filter also drops individual subsequent legs within an
  allowed basket.
- **Deduplication**: Many filter combos produce identical outcomes
  (e.g., 04-10h session has tight spreads anyway, so layering a
  spread filter on top doesn't change anything). Group results by
  `(trades, baskets, net, max_dd)` fingerprint and keep the entry
  with the fewest active filters. Top 20 list now shows 20 genuinely
  different strategies.
- **Output**: Ranked text table + HTML chart with benchmark equity
  (grey) overlaid on best filter equity (green).

### CLI args added
```
--filter-optimize             enable filter optimization mode
--session-step H              hour granularity (default 2)
--min-session-width H         min window width (default 4)
--spread-values X X X         pip thresholds (default 0 0.5 1 1.5 2 3)
--day-options OPT OPT         day filters
--top-results N               default 20
```

### CMD file
`run_basket_analysis_4_filter.cmd` created with all the new
parameters clearly documented at the top.

### Verified working
Tested with EURUSD MT4 strategy tester data: 6,968 trials in seconds,
deduplication produces ~200 unique outcomes, top-20 table shows
genuinely different filter combos. The #1 filter (04-10h session,
no Mon/Fri) retained 11% of benchmark profit but reduced DD to 0.2%
of benchmark, giving Ret/DD 55× improvement.

## Things to be aware of

### Test data limitations
- The available tick file in /mnt/user-data/uploads is only 1 week
  of EURUSD data. The user has full backtest tick files locally that
  cover the entire backtest period and would show much more meaningful
  spread filter differentiation.
- The available `EURUSD_GMT_2_US-DST_M1.csv` is M1 bars; the user
  typically uses M5 in production for the portfolio tool.
- The available statement files are `Statement.htm` (live MT4) and
  `StrategyTester.htm` (MT4 tester) plus `Market_Master_EURUSD_H1.html`
  (MT5 tester) and `Hexaflow8_settingsgbpusdh1.htm` (MT5 tester).

### Stage 2 work pending (filter optimization)
The user mentioned this is stage 1 of the filter optimization work.
Stage 2 will likely add basket SL and EOD close to the filter grid.
That's not started yet.

### Untested in production
The filter optimization tool was tested on the available 1-week tick
file which doesn't cover the full backtest period. With real full
tick data the spread filter dimension will produce very different
(and more meaningful) results.
