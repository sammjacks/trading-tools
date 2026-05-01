import csv
import calendar
from datetime import datetime, timezone
import sys
sys.path.insert(0, r"c:\Users\sammj\Projects\trading-tools\stage3_portfolio_tick_check")
import portfolio_backtest as pb

REPORT = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All\EURUSD_M15.htm"
TICK = r"D:\Work\TickData_tillStartApril\EURUSD_GMT+2_US-DST.csv"


def parse_tick_ts_to_epoch(s: str, tz_offset_sec: int) -> int:
    s = s.strip()
    if s[4] == '.':
        y = int(s[0:4]); m = int(s[5:7]); d = int(s[8:10]); hh = int(s[11:13]); mm = int(s[14:16]); ss = int(s[17:19])
    else:
        d = int(s[0:2]); m = int(s[3:5]); y = int(s[6:10]); hh = int(s[11:13]); mm = int(s[14:16]); ss = int(s[17:19])
    return calendar.timegm((y, m, d, hh, mm, ss, 0, 0, 0)) - tz_offset_sec


trades, _ = pb.parse_backtest(REPORT, 2, "EURUSD")
min_ts = min(t["ts"] for t in trades)
max_ts = max(t["close_ts"] for t in trades)
print("trade range:", datetime.fromtimestamp(min_ts, tz=timezone.utc), "->", datetime.fromtimestamp(max_ts, tz=timezone.utc))

kept = 0
scanned = 0
first_kept = None
last_kept = None
for row in csv.reader(open(TICK, "r", encoding="utf-8")):
    scanned += 1
    if len(row) < 3:
        continue
    try:
        ts = parse_tick_ts_to_epoch(row[0], 2 * 3600)
    except Exception:
        continue
    if ts < min_ts:
        continue
    if ts > max_ts:
        break
    kept += 1
    if first_kept is None:
        first_kept = ts
    last_kept = ts
    if kept % 5000000 == 0:
        print("kept:", kept, "scanned:", scanned)

print("scanned:", scanned)
print("kept:", kept)
if first_kept is not None:
    print("first kept:", datetime.fromtimestamp(first_kept, tz=timezone.utc))
    print("last kept:", datetime.fromtimestamp(last_kept, tz=timezone.utc))
