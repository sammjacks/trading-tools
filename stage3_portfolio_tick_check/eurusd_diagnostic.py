#!/usr/bin/env python3
"""Diagnostic: Check EURUSD tick file and trade date ranges."""

import os
import csv
from datetime import datetime, timezone
import portfolio_backtest as pb

REPORT_DIR = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All"
TICKS_DIR = r"D:\Work\TickData_tillStartApril"

# Load EURUSD report and trades
report_path = os.path.join(REPORT_DIR, "EURUSD_M15.htm")
trades, fmt = pb.parse_backtest(report_path, 2, "EURUSD")

min_ts = min(t["ts"] for t in trades)
max_ts = max(t["close_ts"] for t in trades)

print(f"Trade date range:")
print(f"  Min: {datetime.fromtimestamp(min_ts, tz=timezone.utc)}")
print(f"  Max: {datetime.fromtimestamp(max_ts, tz=timezone.utc)}")

# Check tick file
tick_path = os.path.join(TICKS_DIR, "EURUSD_GMT+2_US-DST.csv")
print(f"\nTick file: {tick_path}")
print(f"  Exists: {os.path.exists(tick_path)}")

if os.path.exists(tick_path):
    print(f"  Size: {os.path.getsize(tick_path) / 1024 / 1024:.1f} MB")
    
    # Sample first and last few lines
    with open(tick_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()[:5]
    print(f"  First lines:")
    for line in lines:
        print(f"    {line.strip()}")
        
    # Find date range in file
    with open(tick_path, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        first_date = None
        last_date = None
        for row_num, row in enumerate(reader):
            if row_num == 0:
                continue  # skip header
            if len(row) < 1:
                continue
            try:
                dt_str = row[0].strip()
                # Parse DD.MM.YYYY HH:MM:SS[.mmm]
                if len(dt_str) > 10:
                    dt_part = dt_str.split('.')[0]
                    d = int(dt_str[:2])
                    m = int(dt_str[3:5])
                    y = int(dt_str[6:10])
                    hh = int(dt_str[11:13])
                    mm = int(dt_str[14:16])
                    ss = int(dt_str[17:19]) if len(dt_str) > 16 else 0
                    date_str = f"{y}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}:{ss:02d}"
                    if row_num < 100000:
                        first_date = date_str
                    last_date = date_str
            except:
                pass
    
    print(f"  First tick date in file: {first_date}")
    print(f"  Last tick date in file (at row 100k+): {last_date}")

print(f"\n✓ Check complete")
