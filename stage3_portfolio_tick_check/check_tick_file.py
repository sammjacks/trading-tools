#!/usr/bin/env python3
"""Check EURUSD tick file format and date range."""

import csv

tick_path = r"D:\Work\TickData_tillStartApril\EURUSD_GMT+2_US-DST.csv"

print("Reading first 100 lines to understand format:")
with open(tick_path, "r", encoding="utf-8", errors="ignore") as f:
    for i, line in enumerate(f):
        if i >= 100:
            break
        print(f"{i:4d}: {line.rstrip()[:100]}")

print("\n\nReading to find last date (this will take a while)...")
with open(tick_path, "r", encoding="utf-8", errors="ignore") as f:
    reader = csv.reader(f)
    last_date = None
    last_row = None
    row_count = 0
    for row_num, row in enumerate(reader):
        if row_num % 1000000 == 0:
            print(f"  Processing row {row_num:,}...")
        if row_num < 100000:
            continue
        if len(row) >= 1:
            last_date = row[0].strip()
            last_row = row
        row_count = row_num

print(f"\nTick file stats:")
print(f"  Total rows: {row_count:,}")
print(f"  Last date: {last_date}")
print(f"  Last row sample: {last_row[:3] if last_row else None}")
