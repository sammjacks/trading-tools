# Stage 1 Real vs Backtest Comparison Tool

## Purpose

Validate backtest accuracy by comparing live trading results against MT4/MT5 backtest expectations. Generates a **closeness score** (0–100) and detailed metrics showing how faithfully the backtest predicted the real trading outcome across 8 key dimensions:

- **Trade count similarity** — Did backtest predict the same number of trades?
- **Trade timing similarity** — How close were entry/exit times?
- **Trade duration** — Did trades last as long as backtest expected?
- **Win rate** — Did real wins match backtest win rate?
- **Profit factor** — Did gross profit / gross loss ratio hold up?
- **Return/DD ratio** — Was profitability relative to drawdown as expected?
- **Max drawdown** — Did equity drawdown match expectations?
- **Net profit** — How close was final profit to backtest target?

*Score interpretation:*
- **80–100** → Excellent backtest fit; real trading closely matched predictions
- **60–80** → Good fit; minor discrepancies (slippage, execution, timing)
- **40–60** → Moderate fit; some divergence in strategy behavior
- **<40** → Poor fit; backtest may not reflect real market conditions

## Files

| File | Purpose |
|------|---------|
| `stage1_real_results_vs_backtest.py` | Main comparison engine (standalone, no imports) |
| `run_stage1_comparison.cmd` | Windows batch driver with configuration |
| `README.md` | This file |

## Inputs Required

### 1. Real Account Statement
HTML or CSV export from your broker's live trading account (MT4/MT5 terminal or trade export):
- **MT4 live**: Right-click Account History → Save As → `real_[pair].htm`
- **MT5 live**: History tab → Export → `real_[pair].htm`
- **Live CSV export** (supported): file with columns like
   `Status,Symbol,Type,Volume,Open Price,Close Price,Swap,Commission,Profit,Open Time,Close Time`

File format auto-detected; path configured in `.cmd` file.

**Deposits and withdrawals are automatically filtered out.** Only actual trades (buy/sell) are included in the comparison.

For CSV input:
- `Status` must be `Closed` (open positions are ignored)
- `Type` must be `BUY` or `SELL`
- Datetime format: `YYYY.MM.DD HH:MM:SS`
- Symbols with suffixes are supported (example: `EURUSD.i` still matches `--symbol EURUSD`)

### 2. Backtest Report
HTML report exported from MT4/MT5 strategy tester after backtest run:
- **MT4 tester**: Generate backtest → Report → Save As → `backtest_[strategy].htm`
- **MT5 tester**: Results → Report → Save As → `backtest_[strategy].htm`

File format auto-detected; path configured in `.cmd` file.

### 3. Symbol (REQUIRED)
The currency pair to compare, e.g., `EURUSD`, `GBPUSD`, `USDJPY`. This parameter:
- **Filters the real statement** to only include trades from the specified pair
- **Automatically excludes** deposits, withdrawals, and trades from other pairs
- **Must be specified** — there is no auto-detection
- Example: `--symbol EURUSD`

### 4. Tick Data Folder (REQUIRED)
Provide only the folder path. The tool auto-resolves the tick file using this exact naming format:

`SYMBOL_GMT+N_US-DST.csv`

Examples:
- `AUDUSD_GMT+2_US-DST.csv`
- `EURUSD_GMT+2_US-DST.csv`
- `GBPUSD_GMT-5_US-DST.csv`

If `--symbol AUDUSD` and `--tick-gmt 2`, the tool expects:
- `AUDUSD_GMT+2_US-DST.csv` in your ticks folder

CSV content format:
```
2024.01.15 10:30:45.123,1.0850,1.0851
2024.01.15 10:30:46.234,1.0850,1.0852
...
```

Expected columns (minimum):
- **Column 1**: Timestamp (format: `YYYY.MM.DD HH:MM:SS` or `YYYY-MM-DD HH:MM:SS`)
- **Column 2**: Bid price
- **Column 3**: Ask price

## Usage

### Quick Start

1. **Edit `run_stage1_comparison.cmd`:**
   ```batch
   set real_statement=path\to\real_trading.htm
   set backtest_report=path\to\backtest.htm
   set ticks_dir=path\to\ticks_folder
   set symbol=EURUSD             <-- required
   set broker_gmt=2              <-- broker timezone offset
   set tick_gmt=2                <-- tick data timezone offset
   set output_dir=.\results      <-- where to save report
   ```

2. **Run the batch file:**
   ```bash
   run_stage1_comparison.cmd
   ```

3. **Open the HTML report:**
   - Automatically opens in default browser after completion
   - Or manually: `results\real_vs_backtest_comparison.html`

### Command-Line Usage (Advanced)

```bash
python stage1_real_results_vs_backtest.py ^
    --real-statement real_account.htm ^
    --backtest backtest_report.htm ^
   --ticks-dir ./ticks ^
    --symbol EURUSD ^
    --broker-gmt 2 ^
    --tick-gmt 2 ^
    --out-dir ./comparison_results ^
    --title "My Comparison"
```

## Configuration

### Timezone Offsets

### Symbol (Required)

The `--symbol` parameter is **required** and specifies the currency pair to compare:

```bash
--symbol EURUSD
```

**Purpose:**
- Filters the real account statement to **only include trades from this pair**
- **Automatically excludes**:
   - Deposits and withdrawals (non-trading transactions)
   - Trades from other currency pairs (if multi-pair account)
   - Balance operations, interest payments, etc.
- Ensures apples-to-apples comparison: real pair vs backtest pair

**Example:**
If your real account statement contains trades in EURUSD, GBPUSD, and has 2 deposits:
- `--symbol EURUSD` → compares only 15 EURUSD trades
- Deposits, GBPUSD trades are ignored

### Timezone Offsets

The tool parses timestamps in the statement and tick data using timezone offsets to convert to Unix timestamps (coordinated UTC).

- **`--broker-gmt N`** — Offset of broker's stated times (e.g., `2` for EET, `-5` for EST)
- **`--tick-gmt N`** — Offset of tick CSV timestamps (usually same as broker)

Tick filename is generated from `--symbol` and `--tick-gmt` as:
- `SYMBOL_GMT+N_US-DST.csv`
- Example: `--symbol AUDUSD --tick-gmt 2` → `AUDUSD_GMT+2_US-DST.csv`

Example:
```bash
--broker-gmt 2 --tick-gmt 2     # EET (Europe/Athens winter)
--broker-gmt 1 --tick-gmt 1     # CET (Europe/London winter)
--broker-gmt -5 --tick-gmt -5   # EST (US/Eastern winter)
```

### Other Options

- **`--title`** — Custom report title (default: "Real vs Backtest Comparison")
- **`--out-dir`** — Output directory for HTML report (default: current directory)

## Date Range Alignment

The tool automatically determines the **exact comparison window** where all three data sources are complete and available:

## Transaction Filtering

The tool automatically filters the real account statement to include **only actual trades**:

**Included:**
- Buy/sell trades for the specified symbol (e.g., `--symbol EURUSD`)

**Excluded:**
- Deposits and withdrawals (balance operations)
- Interest payments
- Fees and charges
- Trades from other currency pairs (if multi-pair account)
- Any non-trading transactions

**How it works:**
The tool recognizes that only transactions with type "buy" or "sell" are actual trades. All other transaction types (including balance operations that brokers use for deposits/withdrawals) are automatically excluded from the comparison. This ensures the real results are fairly compared against the backtest, which also contains only buy/sell trades.

**Example:**
```
Real account statement contains:
   - 120 trades in EURUSD
   - 15 trades in GBPUSD
   - 2 deposits
   - 1 withdrawal
   - 3 fees/commissions

After filtering with --symbol EURUSD:
   - 120 trades included ✓
   - 15 GBPUSD trades excluded
   - 2 deposits excluded
   - 1 withdrawal excluded
   - Fees already accounted for in trade commission field
```

## Date Range Alignment

The tool automatically determines the **exact comparison window** where all three data sources are complete and available:

1. Find tick data range (earliest tick to latest tick)
2. Find real trading range (first trade entry to last trade close)
3. Find backtest range (first trade entry to last trade close)
4. **Intersection** = Latest start date, earliest end date across all three
5. Filter all trades and tick data to this window
6. Compare within this complete window only

This ensures no partial data is included in the comparison. The console output reports the exact date range being compared and the number of trades surviving the window filter.

**Example:**
- Real trades: 2024-01-01 to 2024-03-15 (but last ticks only until 2024-03-12)
- Backtest trades: 2024-01-05 to 2024-03-20 (earlier start, later end)
- Tick data: 2024-01-10 to 2024-03-12
- **Comparison window**: 2024-01-10 to 2024-03-12 (all three data sources complete)

## Output

### HTML Report

Saved to `<output_dir>/real_vs_backtest_comparison.html`

Contains:
- **Closeness score summary** — Overall score (0–100) and 8 individual metric scores with color coding
- **Trade statistics table** — Side-by-side comparison of trade counts, win rates, profit factor, drawdown, etc.
- **Equity curves overlay chart** — Interactive Chart.js plot showing real results vs backtest curves on a unified timeline

### Console Output

Prints during execution:
```
Loading real results statement…
  123 trades loaded (mt4_live)
Loading backtest report…
  125 trades loaded (mt4_tester)
Loading tick data…
   Tick file: C:\data\ticks\EURUSD_GMT+2_US-DST.csv
  45,782 ticks loaded
  Exact comparison window: 2024-01-10 to 2024-03-12
  Real trades in window: 120
  Backtest trades in window: 122
  Ticks in window: 43,215

Note: deposits, withdrawals, and non-EURUSD trades excluded from count above.
Building equity curves…
Computing statistics…
Computing comparison scores…

================================================================================
CLOSENESS SCORE: 87.3 / 100
================================================================================
  Trade Count Similarity         87.2
  Trade Timing Similarity        91.5
  Trade Duration Similarity      84.3
  Win Rate Match                 92.1
  Profit Factor Match            81.9
  Return/DD Match                85.2
  Max Drawdown Match             86.7
  Net Profit Match               88.9
================================================================================

✓ Report saved: results\real_vs_backtest_comparison.html
```

## Typical Workflow

### For Single-Pair Analysis

1. Trade a pair (e.g., EURUSD) using your EA for a defined period (e.g., 1 month)
2. Export both real account statement and backtest report for the same period
3. Gather tick data for EURUSD during that period
4. Run Stage 1 comparison
5. Review HTML report:
   - If score > 80: Backtest is highly predictive; proceed with confidence
   - If 60–80: Backtest reasonably accurate; check for slippage/commissions
   - If < 60: Backtest may not reflect real market dynamics; review pairs, commission, spreads

### For Portfolio Analysis (Multi-Pair)

If combining results from multiple pairs:
1. Run Stage 1 separately for each pair
2. Review individual scores to identify which pairs backtest reliably
3. Use high-confidence pairs for portfolio combining (Stage 2 / portfolio_backtest.py)

## Scoring Details

Each metric uses a tolerance window to score similarity:

| Metric | Tolerance | Notes |
|--------|-----------|-------|
| Trade count | ±N trades | Needs >80% match |
| Trade timing | ±1 hour | Allows for slippage, execution delays |
| Trade duration | ±N seconds avg | Averaged across all trades |
| Win rate | ±10% | e.g., 55% ± 10% = 45–65% acceptable |
| Profit factor | ±15% | e.g., 1.50 ± 15% = 1.28–1.73 acceptable |
| Return/DD | ±20% | Allows for volatility differences |
| Max DD | ±15% | e.g., $500 ± 15% = $425–$575 acceptable |
| Net profit | ±15% | e.g., $5000 ± 15% = $4250–$5750 acceptable |

*Overall score* = Simple average of all 8 metric scores.

## Limitations

- **No per-hour or per-spread profiling** — Stage 1 focuses on aggregate matching only
- **Assumes matched trade order** — Real and backtest trades must occur in similar sequence
- **Daily curve alignment** — Non-trading days filled forward with last known balance
- **Slippage not modeled explicitly** — Captured in the timing and profit metrics
- **Manual calibration** — Tolerances are fixed; can be edited in Python source if needed

## Troubleshooting

### Error: "Could not detect backtest format"
- Ensure statement is in MT4/MT5 HTML format or supported live CSV format
- Check that table rows contain expected columns
- Try exporting from terminal again if file seems corrupted

### Error: "Unrecognised datetime"
- Check timezone offsets (`--broker-gmt`, `--tick-gmt`)
- Verify CSV tick data has timestamps in `YYYY.MM.DD HH:MM:SS` or `YYYY-MM-DD HH:MM:SS` format

### Closeness score is low (< 50)
- Verify backtest and real statements are for the same pair/strategy/period
- Check for large commission/spread differences (use `--symbol` to focus on single pair)
- Ensure tick data covers the full trading period and has no gaps
- Compare visually: if equity curves diverge early, backtest may not match market conditions

### Report HTML won't open
- Ensure output directory is writable
- Check Windows firewall/browser security settings
- Manually open the file by path in browser

### CMD only shows "Press any key to continue"
- This means preflight checks failed before running analysis
- Confirm these paths in `run_stage1_comparison.cmd`:
   - `real_statement` (default `trades.csv`) exists in the script folder
   - `backtest_report` (default `backtest.html`) exists in the script folder
   - `ticks_dir` exists
- Confirm expected tick filename exists in `ticks_dir`:
   - `SYMBOL_GMT+N_US-DST.csv`
   - Example: `EURUSD_GMT+2_US-DST.csv`
- If Python is not installed/in PATH, install Python or use `py -3`

## Next Steps

After validating backtest accuracy with Stage 1:
1. **Single-pair optimization** (if using basket_analysis.py):
   - Run Stage 3 (bar/tick SL testing)
   - Run Stage 4 (filter optimization) against real data
2. **Multi-pair portfolio combining** (if building portfolio):
   - Use [portfolio_backtest.py](../portfolio/) to combine high-confidence pairs
   - Select diversity and scaling for final portfolio
