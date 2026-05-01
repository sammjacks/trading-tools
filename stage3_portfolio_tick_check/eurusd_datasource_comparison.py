"""
EURUSD Data-Source Comparison
==============================
Runs the Table-1 equity drawdown analysis for EURUSD against four data sources:
  1. D:\Work\TickData_tillStartApril           (tick, DD.MM.YYYY format, Oct 2021 – Apr 2026)
  2. D:\Work\TICK_2026to20260415dukas          (tick, DD.MM.YYYY format, Jan 2026 – Apr 2026)
  3. D:\SEIF_system_new\5year\Data\darwinex   (tick, DD.MM.YYYY format, Oct 2021 – Mar 2026)
  4. D:\SEIF_system_new\5year\Data\darwinex   (M5 OHLCV, unix-ts UTC, Oct 2021 – Mar 2026)

For each source it prints:
  - Total Profit
  - Max Dollar Equity Drawdown
  - R/D Ratio
  - Dynamic Basket SL (pips of first order)
  - Tick/bar rows matched to trade date range
  - Date range of that source
"""

import csv
import math
import os
import calendar
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import portfolio_backtest as pb
import sys

# ─────────────────────────────── Configuration ──────────────────────────────
REPORT_PATH   = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All\EURUSD_M15.htm"
BROKER_GMT    = 2       # broker timestamps in HTM are GMT+2
TICK_GMT      = 2       # tick/bar data timestamps are GMT+2  (M5 UTC handled separately)

SOURCES = [
    {
        "label":  "TickData_tillStartApril (Oct 2021 – Apr 2026)",
        "path":   r"D:\Work\TickData_tillStartApril\EURUSD_GMT+2_US-DST.csv",
        "kind":   "tick",
    },
    {
        "label":  "TICK_2026to20260415dukas (Jan 2026 – Apr 2026)  [CURRENT]",
        "path":   r"D:\Work\TICK_2026to20260415dukas\EURUSD_GMT+2_US-DST.csv",
        "kind":   "tick",
    },
    {
        "label":  "darwinex tick (Oct 2021 – Mar 2026)",
        "path":   r"D:\SEIF_system_new\5year\Data\darwinex\EURUSD_GMT+2_US-DST.csv",
        "kind":   "tick",
    },
    {
        "label":  "darwinex M5 bars (Oct 2021 – Mar 2026)",
        "path":   r"D:\SEIF_system_new\5year\Data\darwinex\EURUSD_GMT+2_US-DST_M5.csv",
        "kind":   "m5",
    },
]
# ─────────────────────────────────────────────────────────────────────────────


def parse_tick_ts_to_epoch(ts: str, tz_offset_sec: int) -> int:
    s = ts.strip()
    if len(s) < 19:
        raise ValueError("short timestamp")
    if s[4] == '.':
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
    elif s[2] == '.':
        d, m, y = int(s[0:2]), int(s[3:5]), int(s[6:10])
    else:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return calendar.timegm(dt.timetuple()) - tz_offset_sec
    hh, mm, ss = int(s[11:13]), int(s[14:16]), int(s[17:19])
    return calendar.timegm((y, m, d, hh, mm, ss, 0, 0, 0)) - tz_offset_sec


def assign_baskets(trades: List[Dict]) -> Tuple[List[Dict], Dict[int, Dict]]:
    sorted_trades = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    baskets: Dict[int, Dict] = {}
    current_basket = -1
    current_end = None
    for t in sorted_trades:
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
        t["trade_pl"] = (float(t.get("profit", 0.0))
                         + float(t.get("commission", 0.0))
                         + float(t.get("swap", 0.0)))
        baskets[current_basket]["trade_count"] += 1
        baskets[current_basket]["realized"] += t["trade_pl"]
    return sorted_trades, baskets


def trade_mtm(trade: Dict, mid: float) -> float:
    ps = pb._pip_size(trade["price"])
    return pb._trade_mtm(trade["type"], trade["price"], mid, trade["lots"], ps)


def _process_tick_at(
    ts: int,
    bid_price: float,
    ask_price: float,
    mid: float,
    trades_sorted: List[Dict],
    open_idx_ref: List[int],
    active: List[Dict],
    basket_realized_running: Dict[int, float],
    basket_min_pnl: Dict[int, float],
    basket_max_adverse_pips: Dict[int, float],
    baskets: Dict[int, Dict],
    total_realized_ref: List[float],
    running_peak_ref: List[float],
    max_dd_ref: List[float],
    equity_curve: List,
):
    """Core equity update used by both tick and M5 processors."""
    open_idx = open_idx_ref[0]
    while open_idx < len(trades_sorted) and trades_sorted[open_idx]["ts"] <= ts:
        active.append(trades_sorted[open_idx])
        open_idx += 1
    open_idx_ref[0] = open_idx

    still = []
    for t in active:
        if t["close_ts"] <= ts:
            total_realized_ref[0] += t["trade_pl"]
            basket_realized_running[t["basket_id"]] += t["trade_pl"]
        else:
            still.append(t)
    active[:] = still

    unreal = 0.0
    basket_unreal: Dict[int, float] = {}
    for t in active:
        u = trade_mtm(t, mid)
        unreal += u
        bid_ = t["basket_id"]
        basket_unreal[bid_] = basket_unreal.get(bid_, 0.0) + u

        binfo = baskets[bid_]
        ps = binfo["pip_size"]
        if binfo["direction"] == "buy":
            adverse_pips = (binfo["first_price"] - bid_price) / ps
        else:
            adverse_pips = (ask_price - binfo["first_price"]) / ps
        if adverse_pips > basket_max_adverse_pips[bid_]:
            basket_max_adverse_pips[bid_] = adverse_pips

    eq = total_realized_ref[0] + unreal
    equity_curve.append([ts, round(eq, 4)])
    if eq > running_peak_ref[0]:
        running_peak_ref[0] = eq
    dd = running_peak_ref[0] - eq
    if dd > max_dd_ref[0]:
        max_dd_ref[0] = dd

    for bid_ in basket_unreal:
        basket_pnl = basket_realized_running[bid_] + basket_unreal.get(bid_, 0.0)
        if basket_pnl < basket_min_pnl[bid_]:
            basket_min_pnl[bid_] = basket_pnl


def compute_metrics_tick(trades: List[Dict], baskets: Dict[int, Dict], tick_path: str) -> Dict:
    if not trades:
        return _empty_result("ticks")

    min_ts = min(t["ts"] for t in trades)
    max_ts = max(t["close_ts"] for t in trades)
    tz_offset_sec = TICK_GMT * 3600

    trades_sorted = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    active: List[Dict] = []
    open_idx_ref = [0]
    total_realized_ref = [0.0]
    running_peak_ref = [0.0]
    max_dd_ref = [0.0]
    basket_realized_running = {bid: 0.0 for bid in baskets}
    basket_min_pnl = {bid: 0.0 for bid in baskets}
    basket_max_adverse_pips = {bid: 0.0 for bid in baskets}
    equity_curve = []
    scanned = kept = 0
    progress_every = 2_000_000

    print(f"  Reading ticks from: {tick_path}", flush=True)
    first_ts = last_ts = None

    with open(tick_path, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row_num, row in enumerate(reader):
            scanned += 1
            if scanned % progress_every == 0:
                print(f"    progress: scanned={scanned:,} kept={kept:,}", flush=True)
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

            if first_ts is None:
                first_ts = ts
            last_ts = ts

            if ts < min_ts:
                continue
            if ts > max_ts:
                break

            kept += 1
            try:
                bid_p = float(row[1])
                ask_p = float(row[2])
            except Exception:
                continue
            mid = (bid_p + ask_p) / 2.0
            _process_tick_at(
                ts, bid_p, ask_p, mid,
                trades_sorted, open_idx_ref, active,
                basket_realized_running, basket_min_pnl, basket_max_adverse_pips,
                baskets, total_realized_ref, running_peak_ref, max_dd_ref, equity_curve,
            )

    print(f"    done: scanned={scanned:,} kept={kept:,}", flush=True)
    if first_ts and last_ts:
        print(f"    file date range: {fmt_ts(first_ts)} → {fmt_ts(last_ts)}", flush=True)

    if kept == 0:
        print("    WARNING: 0 ticks matched trade date range.", flush=True)
        return _empty_result("ticks", matched=0)

    return _build_result(
        trades, baskets, basket_min_pnl, basket_max_adverse_pips,
        max_dd_ref[0], equity_curve, kept, "ticks",
    )


def compute_metrics_m5(trades: List[Dict], baskets: Dict[int, Dict], m5_path: str) -> Dict:
    """
    M5 bar format: unix_timestamp_utc, open, high, low, close, volume
    For each bar we evaluate equity at: open, low, high, close (in that order).
    This produces 4 equity readings per bar, giving a conservative intra-bar DD.
    """
    if not trades:
        return _empty_result("m5")

    min_ts = min(t["ts"] for t in trades)
    max_ts = max(t["close_ts"] for t in trades)

    trades_sorted = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    active: List[Dict] = []
    open_idx_ref = [0]
    total_realized_ref = [0.0]
    running_peak_ref = [0.0]
    max_dd_ref = [0.0]
    basket_realized_running = {bid: 0.0 for bid in baskets}
    basket_min_pnl = {bid: 0.0 for bid in baskets}
    basket_max_adverse_pips = {bid: 0.0 for bid in baskets}
    equity_curve = []
    scanned = kept = 0
    progress_every = 100_000

    print(f"  Reading M5 bars from: {m5_path}", flush=True)
    first_ts = last_ts = None

    with open(m5_path, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row_num, row in enumerate(reader):
            scanned += 1
            if scanned % progress_every == 0:
                print(f"    progress: scanned={scanned:,} kept={kept:,}", flush=True)
            if len(row) < 5:
                continue
            if row_num == 0:
                h = row[0].strip().lower()
                if not h.lstrip("-").isdigit():
                    continue  # header row
            try:
                bar_ts  = int(row[0])        # UTC unix timestamp (bar open)
                bar_open  = float(row[1])
                bar_high  = float(row[2])
                bar_low   = float(row[3])
                bar_close = float(row[4])
            except Exception:
                continue

            if first_ts is None:
                first_ts = bar_ts
            last_ts = bar_ts

            bar_end_ts = bar_ts + 300  # 5-minute bar end

            if bar_end_ts < min_ts:
                continue
            if bar_ts > max_ts:
                break

            kept += 1

            # Evaluate at 4 price points within the bar
            # For each sub-tick we use the same value for bid and ask (spread=0 at bar level)
            for sub_offset, price in enumerate([bar_open, bar_low, bar_high, bar_close]):
                sub_ts = bar_ts + sub_offset  # small offset so ordering is deterministic
                _process_tick_at(
                    sub_ts, price, price, price,
                    trades_sorted, open_idx_ref, active,
                    basket_realized_running, basket_min_pnl, basket_max_adverse_pips,
                    baskets, total_realized_ref, running_peak_ref, max_dd_ref, equity_curve,
                )

    print(f"    done: scanned={scanned:,} kept={kept:,}", flush=True)
    if first_ts and last_ts:
        print(f"    file date range: {fmt_ts(first_ts)} → {fmt_ts(last_ts)}", flush=True)

    if kept == 0:
        print("    WARNING: 0 bars matched trade date range.", flush=True)
        return _empty_result("m5", matched=0)

    return _build_result(
        trades, baskets, basket_min_pnl, basket_max_adverse_pips,
        max_dd_ref[0], equity_curve, kept, "m5",
    )


def _empty_result(source: str, matched: int = 0) -> Dict:
    return {
        "total_profit": 0.0,
        "max_equity_dd": 0.0,
        "rd_ratio": math.inf,
        "basket_dds": [],
        "equity_curve": [],
        "source": source,
        "rows_matched": matched,
    }


def _build_result(
    trades, baskets, basket_min_pnl, basket_max_adverse_pips,
    max_dd, equity_curve, rows_matched, source,
) -> Dict:
    basket_dds = []
    for bid_, b in baskets.items():
        dd_amt = max(0.0, -basket_min_pnl.get(bid_, 0.0))
        basket_dds.append({
            "basket_id": bid_,
            "start_ts": b["start_ts"],
            "end_ts": b["end_ts"],
            "trade_count": b["trade_count"],
            "realized": round(b["realized"], 2),
            "max_drawdown": round(dd_amt, 2),
            "max_adverse_pips": round(max(0.0, basket_max_adverse_pips.get(bid_, 0.0)), 2),
        })
    basket_dds.sort(key=lambda x: x["max_drawdown"], reverse=True)

    total_profit = round(sum(t["trade_pl"] for t in trades), 2)
    rd_ratio = (total_profit / max_dd) if max_dd > 0 else math.inf

    return {
        "total_profit": total_profit,
        "max_equity_dd": round(max_dd, 2),
        "rd_ratio": round(rd_ratio, 2),
        "basket_dds": basket_dds,
        "equity_curve": equity_curve,
        "rows_matched": rows_matched,
        "source": source,
    }


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main():
    print(f"Parsing EURUSD trades from: {REPORT_PATH}", flush=True)
    trades, fmt = pb.parse_backtest(REPORT_PATH, BROKER_GMT, "EURUSD")
    trades, baskets = assign_baskets(trades)

    trade_start = fmt_ts(min(t["ts"] for t in trades))
    trade_end   = fmt_ts(max(t["close_ts"] for t in trades))
    print(f"  Trades: {len(trades)} | Baskets: {len(baskets)}", flush=True)
    print(f"  Trade date range: {trade_start} → {trade_end}", flush=True)
    print(f"  Total realized P&L: ${sum(t['trade_pl'] for t in trades):.2f}", flush=True)
    print(flush=True)

    results = []
    for src in SOURCES:
        print(f"\n{'='*70}", flush=True)
        print(f"SOURCE: {src['label']}", flush=True)
        print(f"{'='*70}", flush=True)
        if not os.path.exists(src["path"]):
            print(f"  FILE NOT FOUND: {src['path']}", flush=True)
            results.append({"label": src["label"], "result": None})
            continue

        if src["kind"] == "tick":
            r = compute_metrics_tick(trades, baskets, src["path"])
        else:
            r = compute_metrics_m5(trades, baskets, src["path"])

        results.append({"label": src["label"], "result": r})

    # ── Summary Table ──────────────────────────────────────────────────────
    print(f"\n\n{'='*80}", flush=True)
    print("EURUSD TABLE 1 COMPARISON — Max $ Equity DD by Data Source", flush=True)
    print(f"(HTM file max DD reported: $2,399.18)", flush=True)
    print(f"{'='*80}", flush=True)
    hdr = f"{'SOURCE':<45}  {'Total P&L':>12}  {'Max DD ($)':>12}  {'R/D':>8}  {'Dyn SL (pips)':>14}  {'Rows matched':>13}"
    print(hdr, flush=True)
    print("-" * len(hdr), flush=True)
    for item in results:
        lbl = item["label"][:44]
        r   = item["result"]
        if r is None:
            print(f"{lbl:<45}  {'FILE NOT FOUND':>52}", flush=True)
            continue
        dyn_sl = max((b.get("max_adverse_pips", 0.0) for b in r["basket_dds"]), default=0.0)
        print(
            f"{lbl:<45}  {r['total_profit']:>12.2f}  {r['max_equity_dd']:>12.2f}  "
            f"{r['rd_ratio']:>8.2f}  {dyn_sl:>14.2f}  {r['rows_matched']:>13,}",
            flush=True,
        )
    print(f"{'='*80}", flush=True)


if __name__ == "__main__":
    main()
