#!/usr/bin/env python3
"""Compute EURUSD max DD from M5 bars as diagnostic."""

import csv
from datetime import datetime, timezone
import portfolio_backtest as pb
import os

print("="*80)
print("EURUSD M5 BAR DATA DIAGNOSTIC")
print("="*80)

# Load EURUSD trades
htm_path = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All\EURUSD_M15.htm"
trades, _ = pb.parse_backtest(htm_path, 2, "EURUSD")
summary = pb.extract_backtest_report_summary(htm_path)

print(f"\nHTM Report:")
print(f"  Initial: ${summary.get('initial_deposit'):,.2f}")
print(f"  Total profit: ${summary.get('net_profit', 'N/A')}")
print(f"  Max DD (from HTM): $2399.18 (reference)")
print(f"  Trades parsed: {len(trades)}")

# Calculate using trade close prices (trade-events method for comparison)
initial = 100000.0
equity = initial
peak = equity
max_dd_trade_events = 0.0
for t in sorted(trades, key=lambda x: x['close_ts']):
    profit = t.get('realized_profit', t.get('profit', 0))
    equity += profit
    if equity < peak:
        dd = peak - equity
        max_dd_trade_events = max(max_dd_trade_events, dd)
    peak = max(peak, equity)

print(f"\nTrade-Events Method:")
print(f"  Final equity: ${equity:,.2f}")
print(f"  Max DD: ${max_dd_trade_events:,.2f}")
print(f"  (This is what our analysis currently shows)")

# Now analyze using M5 bar data
print(f"\nLoading M5 Bar Data...")
bar_path = r"D:\Work\M5_2021to20260415dukas\EURUSD_GMT+2_US-DST_M5.csv"

if not os.path.exists(bar_path):
    print(f"  ERROR: Bar file not found: {bar_path}")
    exit(1)

# Load bars
bars = []
bar_count = 0
with open(bar_path, "r", encoding="utf-8", errors="ignore") as f:
    for row in csv.reader(f):
        if len(row) < 5:
            continue
        try:
            dt_str = row[0].strip()
            # Parse DD.MM.YYYY HH:MM
            d = int(dt_str[:2])
            m = int(dt_str[3:5])
            y = int(dt_str[6:10])
            hh = int(dt_str[11:13])
            mm = int(dt_str[14:16])
            # Convert to UTC (subtract 2 hours from GMT+2)
            from datetime import timedelta
            dt = datetime(y, m, d, hh, mm, 0, tzinfo=timezone.utc)
            ts = int(dt.timestamp()) - 2*3600
            
            o = float(row[1])
            h = float(row[2])
            l = float(row[3])
            c = float(row[4])
            bars.append((ts, o, h, l, c))
            bar_count += 1
        except:
            continue

print(f"  Loaded: {bar_count:,} bars")
if bars:
    first_dt = datetime.fromtimestamp(bars[0][0], tz=timezone.utc)
    last_dt = datetime.fromtimestamp(bars[-1][0], tz=timezone.utc)
    print(f"  Date range: {first_dt.strftime('%Y-%m-%d')} to {last_dt.strftime('%Y-%m-%d')}")

# Compute MTM using bar data (using bar low as worst case)
print(f"\nComputing max DD from bars (using bar lows as worst case)...")

# Group trades and compute equity using bars
trade_list = sorted(trades, key=lambda t: (t['ts'], t['close_ts']))

# For each bar, compute equity at that time
equity = initial
peak = equity
max_dd_bars = 0.0
equity_samples = 0

# Create a simple bar iterator
bar_idx = 0
for trade_ts_idx, trade_close_ts_idx in [(t['ts'], t['close_ts']) for t in trade_list]:
    # Simple approach: when trade closes, compute equity at bar close prices
    for bar in bars:
        ts, o, h, l, c = bar
        # At each bar, check equity
        total_realized = sum(t['realized_profit'] for t in trades if t['close_ts'] <= ts)
        
        # Compute unrealized for open trades
        unreal = 0.0
        for t in trades:
            if t['ts'] <= ts < t['close_ts']:
                # Trade is open at this bar
                mid = c  # Use bar close as mid price
                ps = pb._pip_size(t['price'])
                if t['type'] == 'buy':
                    unreal += (mid - t['price']) / ps * ps * t['lots'] * 10
                else:
                    unreal += (t['price'] - mid) / ps * ps * t['lots'] * 10
        
        equity = initial + total_realized + unreal
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd_bars:
            max_dd_bars = dd
        
        equity_samples += 1
        if equity_samples % 100000 == 0:
            print(f"    Processed {equity_samples:,} bar samples...")

print(f"  Final equity (bar-based): ${equity:,.2f}")
print(f"  Max DD (bar-based): ${max_dd_bars:,.2f}")

# Summary comparison
print(f"\n" + "="*80)
print(f"RESULTS SUMMARY")
print(f"="*80)
print(f"  HTM Report max DD:           ${2399.18:>10.2f}  (reference)")
print(f"  Tick-based max DD (current): ${117.72:>10.2f}  (from our analysis)")
print(f"  Trade-events max DD:         ${max_dd_trade_events:>10.2f}  (simple fallback)")
print(f"  Bar-based max DD:            ${max_dd_bars:>10.2f}  (M5 bars - diagnostic)")

if max_dd_bars > 1000:
    print(f"\n✓ Bar data shows high max DD - suggests tick data was not being loaded!")
    print(f"  Root cause: custom_dd_analysis.py is falling back to trade_events for ALL symbols")
elif abs(max_dd_bars - 117.72) < 50:
    print(f"\n✗ Bar data also shows low max DD - suggests MTM logic issue, not data loading")
else:
    print(f"\n? Bar data shows intermediate max DD - suggests partial data issue")
