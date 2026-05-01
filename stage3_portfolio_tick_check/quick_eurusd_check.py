import csv
from datetime import datetime, timezone
import portfolio_backtest as pb

# Quick check
htm_path = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All\EURUSD_M15.htm"
report = pb.parse_mt4_tester_report(htm_path)
summary = pb.extract_backtest_report_summary(report)
trades = pb.parse_trades_from_report(report)

print("HTM Analysis:")
print(f"  Initial: ${summary.get('initial_deposit')}")
print(f"  Trades: {len(trades)}")

# Simple equity curve
initial = summary.get('initial_deposit', 100000.0)
equity = initial
peak = equity
max_dd = 0.0

for t in sorted(trades, key=lambda x: x['close_ts']):
    profit = t.get('realized_profit', 0)
    equity += profit
    if equity < peak:
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            max_dd_trade = t
    peak = max(peak, equity)

print(f"  Final equity: ${equity:,.2f}")
print(f"  Total profit: ${equity - initial:,.2f}")
print(f"  Max DD (trade-event): ${max_dd:,.2f}")

# Now check bars
bar_path = r"D:\Work\M5_2021to20260415dukas\EURUSD_GMT+2_US-DST_M5.csv"
bars = []
with open(bar_path, "r", encoding="utf-8") as f:
    for row in csv.reader(f):
        if len(row) < 5:
            continue
        try:
            dt_str = row[0].strip()
            dt_obj = datetime.strptime(dt_str, "%d.%m.%Y %H:%M").replace(tzinfo=timezone.utc)
            ts = int(dt_obj.timestamp()) - 2*3600
            bars.append((ts, float(row[1]), float(row[2]), float(row[3]), float(row[4])))
        except:
            pass

print(f"\nBar Analysis:")
print(f"  Bars loaded: {len(bars)}")
if bars:
    print(f"  Date range: {datetime.fromtimestamp(bars[0][0], tz=timezone.utc).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(bars[-1][0], tz=timezone.utc).strftime('%Y-%m-%d')}")

print(f"\n**TARGET: HTM report shows max DD ~ $2399**")
print(f"**CURRENT TICK RESULT: $117.72**")
print(f"**TRADE-EVENT RESULT: ${max_dd:,.2f}**")
