#!/usr/bin/env python3
"""Focused diagnostic: trace EURUSD timestamp mismatch."""

import portfolio_backtest as pb
import os
import csv
from datetime import datetime, timezone, timedelta
import calendar

REPORT_DIR = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All"
TICKS_DIR = r"D:\Work\TickData_tillStartApril"
BROKER_GMT = 2
TICK_GMT = 2

def parse_tick_ts_to_epoch(ts_str: str, tz_offset_sec: int) -> int:
    """Match the parsing logic from custom_dd_analysis.py"""
    s = ts_str.strip()
    if len(s) < 19:
        raise ValueError("short timestamp")

    # Try DD.MM.YYYY HH:MM:SS format
    if s[2] == '.':
        d = int(s[0:2])
        m = int(s[3:5])
        y = int(s[6:10])
        hh = int(s[11:13])
        mm = int(s[14:16])
        ss = int(s[17:19])
    else:
        raise ValueError(f"unknown format: {s}")

    return calendar.timegm((y, m, d, hh, mm, ss, 0, 0, 0)) - tz_offset_sec

# Load EURUSD trades from report
print("=" * 80)
print("STEP 1: Load EURUSD trades from HTM report")
print("=" * 80)
report_path = os.path.join(REPORT_DIR, "EURUSD_M15.htm")
trades, fmt = pb.parse_backtest(report_path, BROKER_GMT, "EURUSD")

min_ts_trades = min(t["ts"] for t in trades)
max_ts_trades = max(t["close_ts"] for t in trades)

print(f"Report says trades from 2021.10.04 08:00 to 2026.04.06")
print(f"\nParsed trade date range (epoch seconds):")
print(f"  min_ts (first trade open):  {min_ts_trades}")
print(f"  max_ts (last trade close):  {max_ts_trades}")
print(f"\nConverted to human readable:")
print(f"  min_ts: {datetime.fromtimestamp(min_ts_trades, tz=timezone.utc)}")
print(f"  max_ts: {datetime.fromtimestamp(max_ts_trades, tz=timezone.utc)}")

# Load first few ticks from file
print("\n" + "=" * 80)
print("STEP 2: Read and parse first ticks from EURUSD tick file")
print("=" * 80)

tick_path = os.path.join(TICKS_DIR, "EURUSD_GMT+2_US-DST.csv")
tz_offset_sec = TICK_GMT * 3600

tick_dates = []
with open(tick_path, "r", encoding="utf-8", errors="ignore") as f:
    reader = csv.reader(f)
    for row_num, row in enumerate(reader):
        if row_num >= 100:
            break
        if len(row) < 3:
            continue
        if row_num == 0:
            print(f"Header: {row}")
            continue
        try:
            ts_str = row[0].strip()
            ts_epoch = parse_tick_ts_to_epoch(ts_str, tz_offset_sec)
            print(f"  Row {row_num}: '{ts_str}' → epoch {ts_epoch} → {datetime.fromtimestamp(ts_epoch, tz=timezone.utc)}")
            tick_dates.append(ts_epoch)
            if ts_epoch >= min_ts_trades:
                print(f"    ✓ This tick is >= min_ts_trades!")
                break
        except Exception as e:
            print(f"  Row {row_num}: ERROR: {e} (row={row[:3]})")
            break

print("\n" + "=" * 80)
print("STEP 3: Comparison")
print("=" * 80)
if tick_dates:
    first_tick = tick_dates[0]
    print(f"First tick epoch:     {first_tick}")
    print(f"Min trade epoch:      {min_ts_trades}")
    print(f"Difference:           {first_tick - min_ts_trades} seconds")
    print(f"                      ({(first_tick - min_ts_trades) / 86400:.1f} days)")
    
    if first_tick > max_ts_trades:
        print(f"\n❌ PROBLEM: All tick timestamps are AFTER all trade timestamps!")
        print(f"   This explains why 0 ticks are matched!")
