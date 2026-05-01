"""
Diagnostic: EURUSD max DD from M5 bar data vs tick data
Compare to HTM report value of $2399
"""
import csv
from datetime import datetime, timezone, timedelta
import math
import portfolio_backtest as pb

# Load HTM trades
htm_path = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All\EURUSD_M15.htm"
print("="*80)
print("EURUSD MAX DRAWDOWN DIAGNOSTIC")
print("="*80)
print(f"\n1. Loading HTM backtest: {htm_path}")

report = pb.parse_mt4_tester_report(htm_path)
summary = pb.extract_backtest_report_summary(report)
print(f"   Initial deposit: {summary.get('initial_deposit')}")

trades = pb.parse_trades_from_report(report)
print(f"   Trade count: {len(trades)}")
if trades:
    min_ts = min(t["ts"] for t in trades)
    max_ts = max(t["close_ts"] for t in trades)
    min_date = datetime.fromtimestamp(min_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    max_date = datetime.fromtimestamp(max_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    print(f"   Date range: {min_date} to {max_date}")

# Load M5 bars
bar_path = r"D:\Work\M5_2021to20260415dukas\EURUSD_GMT+2_US-DST_M5.csv"
print(f"\n2. Loading M5 bar data: {bar_path}")

tz_offset_sec = 2 * 3600
bars = []
scanned = 0
with open(bar_path, "r", encoding="utf-8") as fh:
    reader = csv.reader(fh)
    for row in reader:
        scanned += 1
        if len(row) < 5:
            continue
        # Parse: DD.MM.YYYY HH:MM, Open, High, Low, Close
        try:
            dt_str = row[0].strip()
            dt_obj = datetime.strptime(dt_str, "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)
            ts = int(dt_obj.timestamp()) - tz_offset_sec  # Convert from GMT+2 to UTC
            open_val = float(row[1])
            high_val = float(row[2])
            low_val = float(row[3])
            close_val = float(row[4])
            bars.append((ts, open_val, high_val, low_val, close_val))
        except Exception as e:
            continue

print(f"   Scanned: {scanned:,} rows")
print(f"   Loaded: {len(bars):,} bars")
if bars:
    bar_min_ts = min(b[0] for b in bars)
    bar_max_ts = max(b[0] for b in bars)
    bar_min_date = datetime.fromtimestamp(bar_min_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    bar_max_date = datetime.fromtimestamp(bar_max_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    print(f"   Date range: {bar_min_date} to {bar_max_date}")

# Compute equity curve from bars
print(f"\n3. Computing equity from M5 bars...")
initial_deposit = summary.get("initial_deposit", 100000.0)
equity = initial_deposit
equity_curve = [(trades[0]["ts"], equity) if trades else (0, equity)]
max_dd = 0.0
peak_equity = equity

for trade in trades:
    # Between trade open and close, iterate through bars to compute MTM
    bar_min = trade["ts"]
    bar_max = trade["close_ts"]
    
    for ts, open_, high, low, close in bars:
        if ts < bar_min or ts > bar_max:
            continue
        
        # Trade is active; compute unrealized P&L using this bar's low (worst case)
        entry_price = trade["entry_price"]
        direction = 1 if trade["direction"] == "BUY" else -1
        pip_size = trade["pip_size"]
        volume = trade["volume"]
        
        # Unrealized using bar low during trade
        mtm_price = low if direction == 1 else high
        unrealized_pips = (mtm_price - entry_price) * direction / pip_size
        unrealized_val = unrealized_pips * pip_size * volume * 100  # Rough conversion
        
        temp_equity = initial_deposit + unrealized_val + sum(
            t.get("realized_profit", 0) for t in trades if t["close_ts"] <= ts
        )
        
        if temp_equity < equity:
            equity = temp_equity
        
        # Track drawdown
        if equity > peak_equity:
            peak_equity = equity
        dd = peak_equity - equity
        if dd > max_dd:
            max_dd = dd
            max_dd_ts = ts
            max_dd_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

# Also compute from trade realized profits
print(f"\n4. Simpler: Track equity from trade close prices...")
equity = initial_deposit
max_dd_simple = 0.0
peak = equity

for trade in sorted(trades, key=lambda t: t["close_ts"]):
    realized = trade.get("realized_profit", 0)
    equity += realized
    
    if equity < peak:
        dd = peak - equity
        max_dd_simple = max(max_dd_simple, dd)
    peak = max(peak, equity)

print(f"   Final equity: ${equity:,.2f}")
print(f"   Max DD (trade-event method): ${max_dd_simple:,.2f}")
print(f"   Total profit: ${equity - initial_deposit:,.2f}")

# Check a few key bars around trade times
print(f"\n5. Sample bars around trade activity...")
if trades and bars:
    sample_ts = trades[len(trades)//2]["ts"]
    print(f"   Looking for bars near trade at {datetime.fromtimestamp(sample_ts, tz=timezone.utc)}")
    for ts, o, h, l, c in bars[-100:]:
        if abs(ts - sample_ts) < 3600:
            ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            print(f"     {ts_str}: O={o:.5f} H={h:.5f} L={l:.5f} C={c:.5f}")

print("\n" + "="*80)
print("COMPARISON:")
print(f"  HTM report max DD:                ~$2399 (expected)")
print(f"  Tick-based computation (current): $117.72")
print(f"  Trade-event based:                ${max_dd_simple:,.2f}")
print("="*80)
