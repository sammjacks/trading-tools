#!/usr/bin/env python3
"""Quick verification: Do tick and trade dates overlap?"""

import csv
from datetime import datetime, timezone, timedelta
import calendar
import portfolio_backtest as pb
import os

def parse_tick_ts(ts_str: str) -> tuple:
    """Parse DD.MM.YYYY HH:MM:SS format, return (year, month, day, hour, min, sec)"""
    s = ts_str.strip()
    if s[2] == '.':
        d = int(s[0:2])
        m = int(s[3:5])
        y = int(s[6:10])
        hh = int(s[11:13])
        mm = int(s[14:16])
        ss = int(s[17:19]) if len(s) > 17 else 0
        return (y, m, d, hh, mm, ss)
    raise ValueError(f"Unknown format: {s}")

print("=" * 80)
print("DATE RANGE VERIFICATION: Ticks vs Trades")
print("=" * 80)

# Get trade date range
print("\n1. TRADE DATE RANGE (from HTM):")
htm_path = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All\EURUSD_M15.htm"
trades, _ = pb.parse_backtest(htm_path, 2, "EURUSD")
min_ts_trades = min(t["ts"] for t in trades)
max_ts_trades = max(t["close_ts"] for t in trades)
min_dt_trades = datetime.fromtimestamp(min_ts_trades, tz=timezone.utc)
max_dt_trades = datetime.fromtimestamp(max_ts_trades, tz=timezone.utc)

print(f"   Min trade: {min_dt_trades.isoformat()} (epoch: {min_ts_trades})")
print(f"   Max trade: {max_dt_trades.isoformat()} (epoch: {max_ts_trades})")
print(f"   Span: {(max_ts_trades - min_ts_trades) / 86400:.0f} days")

# Get tick file date range
print("\n2. TICK FILE DATE RANGE (from EURUSD tick CSV):")
tick_path = r"D:\Work\TickData_tillStartApril\EURUSD_GMT+2_US-DST.csv"

first_tick_dt = None
last_tick_dt = None
tz_offset_sec = 2 * 3600  # GMT+2

with open(tick_path, "r", encoding="utf-8", errors="ignore") as f:
    reader = csv.reader(f)
    for row_num, row in enumerate(reader):
        if len(row) < 3:
            continue
        if row_num == 0:
            continue
        
        try:
            y, m, d, hh, mm, ss = parse_tick_ts(row[0])
            ts = calendar.timegm((y, m, d, hh, mm, ss, 0, 0, 0)) - tz_offset_sec
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            
            if first_tick_dt is None:
                first_tick_dt = dt
                first_tick_ts = ts
            
            if row_num >= 1000000:  # Sample more efficiently
                last_tick_dt = dt
                last_tick_ts = ts
                break
                
            if row_num % 1000000 == 0 and row_num > 0:
                print(f"   Scanned {row_num:,} rows... current date: {dt.date()}")
                if row_num > 2000000:  # Don't scan too long
                    break
        except Exception as e:
            if row_num < 10:
                print(f"   Row {row_num}: parse error: {e}")
            continue

print(f"   First tick: {first_tick_dt.isoformat()} (epoch: {first_tick_ts})")
print(f"   Last tick:  {last_tick_dt.isoformat()} (epoch: {last_tick_ts})")

# Analyze overlap
print("\n3. DATE RANGE OVERLAP ANALYSIS:")
overlap_start = max(min_ts_trades, first_tick_ts)
overlap_end = min(max_ts_trades, last_tick_ts)

if overlap_start < overlap_end:
    overlap_days = (overlap_end - overlap_start) / 86400
    print(f"   ✓ OVERLAP EXISTS: {overlap_days:.0f} days")
    print(f"     From: {datetime.fromtimestamp(overlap_start, tz=timezone.utc).isoformat()}")
    print(f"     To:   {datetime.fromtimestamp(overlap_end, tz=timezone.utc).isoformat()}")
else:
    print(f"   ✗ NO OVERLAP - This is the problem!")
    print(f"     Trades:  {min_dt_trades.date()} to {max_dt_trades.date()}")
    print(f"     Ticks:   {first_tick_dt.date()} to {last_tick_dt.date()}")
    if last_tick_ts < min_ts_trades:
        gap_days = (min_ts_trades - last_tick_ts) / 86400
        print(f"     Gap: Ticks end {gap_days:.0f} days BEFORE trades start")
    if first_tick_ts > max_ts_trades:
        gap_days = (first_tick_ts - max_ts_trades) / 86400
        print(f"     Gap: Ticks start {gap_days:.0f} days AFTER trades end")

print("\n" + "=" * 80)
