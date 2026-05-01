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


def load_ticks(min_ts: int, max_ts: int):
    tz_offset_sec = TICK_GMT * 3600
    ts_arr = []
    bid_arr = []
    ask_arr = []
    scanned = 0
    with open(TICK, "r", encoding="utf-8") as fh:
        r = csv.reader(fh)
        for row_num, row in enumerate(r):
            scanned += 1
            if len(row) < 3:
                continue
            if row_num == 0 and row[0].strip().lower() in ("time", "date", "datetime", "timestamp"):
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
                a = float(row[1])
                b = float(row[2])
            except Exception:
                continue
            # Detect side ordering once: ask should usually be >= bid.
            # In this dataset col1 appears to be ask and col2 bid.
            ask_val = max(a, b)
            bid_val = min(a, b)
            ts_arr.append(ts)
            bid_arr.append(bid_val)
            ask_arr.append(ask_val)
    return ts_arr, bid_arr, ask_arr, scanned


def trade_mtm(trade, mid):
    ps = pb._pip_size(trade["price"])
    return pb._trade_mtm(trade["type"], trade["price"], mid, trade["lots"], ps)


def assign_baskets(trades):
    st = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    baskets = {}
    current_basket = -1
    current_end = None
    for t in st:
        if current_end is None or t["ts"] > current_end:
            current_basket += 1
            current_end = t["close_ts"]
            baskets[current_basket] = {
                "id": current_basket,
                "start_ts": t["ts"],
                "end_ts": t["close_ts"],
                "trade_count": 0,
                "realized": 0.0,
                "direction": t["type"],
                "first_price": t["price"],
                "pip_size": pb._pip_size(t["price"]),
            }
        else:
            if t["close_ts"] > current_end:
                current_end = t["close_ts"]
            if t["close_ts"] > baskets[current_basket]["end_ts"]:
                baskets[current_basket]["end_ts"] = t["close_ts"]
        t["basket_id"] = current_basket
        t["trade_pl"] = float(t.get("profit", 0.0)) + float(t.get("commission", 0.0)) + float(t.get("swap", 0.0))
        baskets[current_basket]["trade_count"] += 1
        baskets[current_basket]["realized"] += t["trade_pl"]
    return st, baskets


def compute_from_ticks(trades, baskets, ts_arr, bid_arr, ask_arr):
    open_idx = 0
    st = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    active = []
    total_realized = 0.0
    peak = 0.0
    max_dd = 0.0

    for ts, bid, ask in zip(ts_arr, bid_arr, ask_arr):
        mid = (bid + ask) / 2.0
        while open_idx < len(st) and st[open_idx]["ts"] <= ts:
            active.append(st[open_idx])
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
            unreal += trade_mtm(t, mid)

        eq = total_realized + unreal
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd

    total_profit = round(sum(t["trade_pl"] for t in st), 2)
    return round(max_dd, 2), total_profit


if __name__ == "__main__":
    trades, fmt = pb.parse_backtest(REPORT, BROKER_GMT, "EURUSD")
    trades, baskets = assign_baskets(trades)
    min_ts = min(t["ts"] for t in trades)
    max_ts = max(t["close_ts"] for t in trades)

    print("EURUSD trades:", len(trades), "format:", fmt)
    print("trade range utc:", datetime.fromtimestamp(min_ts, tz=timezone.utc), "->", datetime.fromtimestamp(max_ts, tz=timezone.utc))

    ts_arr, bid_arr, ask_arr, scanned = load_ticks(min_ts, max_ts)
    print("tick rows scanned:", scanned)
    print("tick rows kept:", len(ts_arr))
    if ts_arr:
        print("tick kept range utc:", datetime.fromtimestamp(ts_arr[0], tz=timezone.utc), "->", datetime.fromtimestamp(ts_arr[-1], tz=timezone.utc))

    dd, profit = compute_from_ticks(trades, baskets, ts_arr, bid_arr, ask_arr)
    print("tick-only max_dd:", dd)
    print("tick-only total_profit:", profit)
    print("htm expected max_dd: 2399.18")
