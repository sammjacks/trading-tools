import csv
import calendar
from datetime import datetime, timezone
import sys

sys.path.insert(0, r"c:\Users\sammj\Projects\trading-tools\stage3_portfolio_tick_check")
import portfolio_backtest as pb

REPORT = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All\EURUSD_M15.htm"
TICK = r"D:\Work\TickData_tillStartApril\EURUSD_GMT+2_US-DST.csv"
BROKER_GMT = 2
TICK_GMT = 2


def parse_tick_ts_to_epoch(ts: str, tz_offset_sec: int) -> int:
    s = ts.strip()
    if len(s) < 19:
        raise ValueError("short timestamp")
    if s[4] == '.':
        y = int(s[0:4]); m = int(s[5:7]); d = int(s[8:10]); hh = int(s[11:13]); mm = int(s[14:16]); ss = int(s[17:19])
    elif s[2] == '.':
        d = int(s[0:2]); m = int(s[3:5]); y = int(s[6:10]); hh = int(s[11:13]); mm = int(s[14:16]); ss = int(s[17:19])
    else:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return calendar.timegm(dt.timetuple()) - tz_offset_sec
    return calendar.timegm((y, m, d, hh, mm, ss, 0, 0, 0)) - tz_offset_sec


def assign_baskets(trades):
    sorted_trades = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    current_basket = -1
    current_end = None
    for t in sorted_trades:
        if current_end is None or t["ts"] > current_end:
            current_basket += 1
            current_end = t["close_ts"]
        else:
            if t["close_ts"] > current_end:
                current_end = t["close_ts"]
        t["basket_id"] = current_basket
        t["trade_pl"] = float(t.get("profit", 0.0)) + float(t.get("commission", 0.0)) + float(t.get("swap", 0.0))
    return sorted_trades


def mtm_at_tick(trade, bid, ask):
    ps = pb._pip_size(trade["price"])
    if trade["type"] == "buy":
        return pb._trade_mtm("buy", trade["price"], bid, trade["lots"], ps)
    return pb._trade_mtm("sell", trade["price"], ask, trade["lots"], ps)


if __name__ == "__main__":
    trades, fmt = pb.parse_backtest(REPORT, BROKER_GMT, "EURUSD")
    trades = assign_baskets(trades)

    min_ts = min(t["ts"] for t in trades)
    max_ts = max(t["close_ts"] for t in trades)

    print("trades:", len(trades), "format:", fmt, flush=True)
    print("trade range utc:", datetime.fromtimestamp(min_ts, tz=timezone.utc), "->", datetime.fromtimestamp(max_ts, tz=timezone.utc), flush=True)

    open_idx = 0
    active = []
    total_realized = 0.0
    peak = 0.0
    max_dd = 0.0
    max_dd_ts = None

    scanned = 0
    kept = 0
    progress_every = 5_000_000
    tz_offset_sec = TICK_GMT * 3600

    with open(TICK, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row_num, row in enumerate(reader):
            scanned += 1
            if len(row) < 3:
                continue
            if row_num == 0:
                h = row[0].strip().lower()
                if h in ("time", "date", "datetime", "timestamp"):
                    continue
            try:
                ts = parse_tick_ts_to_epoch(row[0], tz_offset_sec)
            except Exception:
                continue

            if ts < min_ts:
                continue
            if ts > max_ts:
                break

            try:
                c1 = float(row[1])
                c2 = float(row[2])
            except Exception:
                continue

            # Dataset has ask,bid ordering; normalize so spread is non-negative.
            bid = min(c1, c2)
            ask = max(c1, c2)

            kept += 1
            if kept % progress_every == 0:
                print("progress kept=", kept, "scanned=", scanned, "active=", len(active), flush=True)

            while open_idx < len(trades) and trades[open_idx]["ts"] <= ts:
                active.append(trades[open_idx])
                open_idx += 1

            still = []
            for t in active:
                if t["close_ts"] <= ts:
                    total_realized += t["trade_pl"]
                else:
                    still.append(t)
            active = still

            unreal = 0.0
            for t in active:
                unreal += mtm_at_tick(t, bid, ask)

            eq = total_realized + unreal
            if eq > peak:
                peak = eq
            dd = peak - eq
            if dd > max_dd:
                max_dd = dd
                max_dd_ts = ts

    print("tick scanned:", scanned, flush=True)
    print("tick kept:", kept, flush=True)
    if max_dd_ts is not None:
        print("max dd time utc:", datetime.fromtimestamp(max_dd_ts, tz=timezone.utc), flush=True)
    print("max dd tick-stream:", round(max_dd, 2), flush=True)
    print("total profit parsed:", round(sum(t["trade_pl"] for t in trades), 2), flush=True)
    print("htm max dd ref:", 2399.18, flush=True)
