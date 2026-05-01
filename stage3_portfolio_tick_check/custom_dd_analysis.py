import csv
import json
import math
import os
import calendar
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple

import portfolio_backtest as pb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

REPORT_DIR = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All"
TICKS_DIR = r"D:\Work\TickData_tillStartApril"
FILES = [
    "AUDUSD_M15.htm",
    "EURUSD_M15.htm",
    "GBPUSD_M15.htm",
    "USDCAD_M15.htm",
    "USDCHF_M30.htm",
]
TICK_SUFFIX = "_GMT+2_US-DST.csv"
BROKER_GMT = 2
TICK_GMT = 2
TICK_SAMPLE_EVERY = 1


def parse_tick_ts_to_epoch(ts: str, tz_offset_sec: int) -> int:
    s = ts.strip()
    if len(s) < 19:
        raise ValueError("short timestamp")

    # Formats seen in these exports:
    # YYYY.MM.DD HH:MM:SS[.fff]
    # DD.MM.YYYY HH:MM:SS[.fff]
    if s[4] == '.':
        y = int(s[0:4])
        m = int(s[5:7])
        d = int(s[8:10])
        hh = int(s[11:13])
        mm = int(s[14:16])
        ss = int(s[17:19])
    elif s[2] == '.':
        d = int(s[0:2])
        m = int(s[3:5])
        y = int(s[6:10])
        hh = int(s[11:13])
        mm = int(s[14:16])
        ss = int(s[17:19])
    else:
        # Fallback to Python parser
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
        return calendar.timegm(dt.timetuple()) - tz_offset_sec

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
        t["trade_pl"] = float(t.get("profit", 0.0)) + float(t.get("commission", 0.0)) + float(t.get("swap", 0.0))
        baskets[current_basket]["trade_count"] += 1
        baskets[current_basket]["realized"] += t["trade_pl"]

    return sorted_trades, baskets


def trade_mtm(trade: Dict, mid: float) -> float:
    ps = pb._pip_size(trade["price"])
    return pb._trade_mtm(trade["type"], trade["price"], mid, trade["lots"], ps)


def compute_metrics_from_trade_events(trades: List[Dict], baskets: Dict[int, Dict]) -> Dict:
    """Fallback when no tick data is available for the trade date range.
    Evaluates equity at every trade-close event, using the closing trade's
    close_price as a proxy market mid for all still-open trades (same symbol).
    """
    if not trades:
        return {
            "total_profit": 0.0,
            "max_equity_dd": 0.0,
            "rd_ratio": math.inf,
            "basket_dds": [],
            "equity_curve": [],
            "source": "trade_events",
        }

    trades_sorted = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    # Events: (ts, trade_index, 'open'/'close')
    events = []
    for i, t in enumerate(trades_sorted):
        events.append((t["ts"], i, "open"))
        events.append((t["close_ts"], i, "close"))
    events.sort(key=lambda e: (e[0], 0 if e[2] == "open" else 1))

    active_set = set()
    total_realized = 0.0
    running_peak = 0.0
    max_dd = 0.0
    equity_curve = []

    basket_realized_running = {bid: 0.0 for bid in baskets}
    basket_min_pnl = {bid: 0.0 for bid in baskets}
    basket_max_adverse_pips = {bid: 0.0 for bid in baskets}

    for ts, idx, etype in events:
        t = trades_sorted[idx]
        if etype == "open":
            active_set.add(idx)
        else:
            # trade closing — close_price is the market price at this moment
            active_set.discard(idx)
            total_realized += t["trade_pl"]
            basket_realized_running[t["basket_id"]] += t["trade_pl"]
            mid = t["close_price"]

            # MTM all still-open trades at this price
            unreal = 0.0
            basket_unreal: Dict[int, float] = {}
            for oi in active_set:
                ot = trades_sorted[oi]
                u = trade_mtm(ot, mid)
                unreal += u
                bid_ = ot["basket_id"]
                basket_unreal[bid_] = basket_unreal.get(bid_, 0.0) + u

                binfo = baskets[bid_]
                ps = binfo["pip_size"]
                if binfo["direction"] == "buy":
                    adverse_pips = (binfo["first_price"] - mid) / ps
                else:
                    adverse_pips = (mid - binfo["first_price"]) / ps
                if adverse_pips > basket_max_adverse_pips[bid_]:
                    basket_max_adverse_pips[bid_] = adverse_pips

            eq = total_realized + unreal
            equity_curve.append([ts, round(eq, 4)])

            if eq > running_peak:
                running_peak = eq
            dd = running_peak - eq
            if dd > max_dd:
                max_dd = dd

            for bid_, bunreal in basket_unreal.items():
                basket_pnl = basket_realized_running[bid_] + bunreal
                if basket_pnl < basket_min_pnl[bid_]:
                    basket_min_pnl[bid_] = basket_pnl

            # Also update basket for the just-closed trade's basket
            closed_bid = t["basket_id"]
            if closed_bid not in basket_unreal:
                basket_pnl = basket_realized_running[closed_bid]
                if basket_pnl < basket_min_pnl[closed_bid]:
                    basket_min_pnl[closed_bid] = basket_pnl

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

    total_profit = round(sum(t["trade_pl"] for t in trades_sorted), 2)
    rd_ratio = (total_profit / max_dd) if max_dd > 0 else math.inf

    return {
        "total_profit": total_profit,
        "max_equity_dd": round(max_dd, 2),
        "rd_ratio": rd_ratio,
        "basket_dds": basket_dds,
        "equity_curve": equity_curve,
        "source": "trade_events",
    }


EQUITY_SAMPLE_SECS = 3600  # 1 equity curve point per hour (keeps ~44K pts over 5 years)


def stream_metrics_from_ticks(tick_path: str, trades: List[Dict],
                               baskets: Dict[int, Dict]) -> Dict:
    """Stream tick CSV without loading into RAM. Equity curve sampled every EQUITY_SAMPLE_SECS."""
    if not trades:
        return {
            "total_profit": 0.0,
            "max_equity_dd": 0.0,
            "rd_ratio": math.inf,
            "basket_dds": [],
            "equity_curve": [],
            "source": "ticks",
        }

    min_ts = min(t["ts"] for t in trades)
    max_ts = max(t["close_ts"] for t in trades)
    tz_offset_sec = TICK_GMT * 3600

    trades_sorted = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    open_idx = 0
    active: List[Dict] = []

    total_realized = 0.0
    running_peak = 0.0
    max_dd = 0.0
    equity_curve = []
    last_sample_ts = 0

    basket_realized_running: Dict[int, float] = {bid: 0.0 for bid in baskets}
    basket_min_pnl: Dict[int, float] = {bid: 0.0 for bid in baskets}
    basket_max_adverse_pips: Dict[int, float] = {bid: 0.0 for bid in baskets}

    scanned = 0
    kept = 0
    progress_every = 10_000_000

    with open(tick_path, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row_num, row in enumerate(reader):
            scanned += 1
            if scanned % progress_every == 0:
                print(f"    tick progress: scanned={scanned:,} kept={kept:,}", flush=True)
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
                bid_val = min(c1, c2)
                ask_val = max(c1, c2)
            except Exception:
                continue

            kept += 1
            mid = (bid_val + ask_val) / 2.0

            while open_idx < len(trades_sorted) and trades_sorted[open_idx]["ts"] <= ts:
                active.append(trades_sorted[open_idx])
                open_idx += 1

            still = []
            for t in active:
                if t["close_ts"] <= ts:
                    total_realized += t["trade_pl"]
                    basket_realized_running[t["basket_id"]] += t["trade_pl"]
                else:
                    still.append(t)
            active = still

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
                    adverse_pips = (binfo["first_price"] - bid_val) / ps
                else:
                    adverse_pips = (ask_val - binfo["first_price"]) / ps
                if adverse_pips > basket_max_adverse_pips[bid_]:
                    basket_max_adverse_pips[bid_] = adverse_pips

            eq = total_realized + unreal

            if ts - last_sample_ts >= EQUITY_SAMPLE_SECS:
                equity_curve.append([ts, round(eq, 4)])
                last_sample_ts = ts

            if eq > running_peak:
                running_peak = eq
            dd = running_peak - eq
            if dd > max_dd:
                max_dd = dd

            for bid_ in basket_unreal.keys():
                basket_pnl = basket_realized_running[bid_] + basket_unreal.get(bid_, 0.0)
                if basket_pnl < basket_min_pnl[bid_]:
                    basket_min_pnl[bid_] = basket_pnl

    print(f"    tick stream done: scanned={scanned:,} kept={kept:,} equity_pts={len(equity_curve):,}", flush=True)

    if kept == 0:
        print(f"    WARNING: 0 tick rows matched trade date range. Falling back to trade-events method.", flush=True)
        return compute_metrics_from_trade_events(trades, baskets)

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

    total_profit = round(sum(t["trade_pl"] for t in trades_sorted), 2)
    rd_ratio = (total_profit / max_dd) if max_dd > 0 else math.inf

    return {
        "total_profit": total_profit,
        "max_equity_dd": round(max_dd, 2),
        "rd_ratio": rd_ratio,
        "basket_dds": basket_dds,
        "equity_curve": equity_curve,
        "source": "ticks",
    }


def symbol_from_report_name(name: str) -> str:
    return name.split("_")[0].upper()


def fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def analyze_one(report_name: str) -> Dict:
    report_path = os.path.join(REPORT_DIR, report_name)
    symbol = symbol_from_report_name(report_name)
    tick_path = os.path.join(TICKS_DIR, f"{symbol}{TICK_SUFFIX}")

    trades, fmt = pb.parse_backtest(report_path, BROKER_GMT, symbol)
    trades, baskets = assign_baskets(trades)

    print(f"    base pass ...", flush=True)
    base = stream_metrics_from_ticks(tick_path, trades, baskets)

    worst3_ids = [b["basket_id"] for b in base["basket_dds"][:3]]
    filtered_trades = [t for t in trades if t["basket_id"] not in worst3_ids]
    filtered_trades, filtered_baskets = assign_baskets(filtered_trades)
    print(f"    filtered pass (ignore worst 3 baskets) ...", flush=True)
    filtered = stream_metrics_from_ticks(tick_path, filtered_trades, filtered_baskets)

    summary = pb.extract_backtest_report_summary(report_path)

    basket_sl_usd_original = base["basket_dds"][0]["max_drawdown"] if base["basket_dds"] else 0.0
    basket_sl_usd_after3 = filtered["basket_dds"][0]["max_drawdown"] if filtered["basket_dds"] else 0.0
    basket_sl_pips_original = max((b.get("max_adverse_pips", 0.0) for b in base["basket_dds"]), default=0.0)
    basket_sl_pips_after3 = max((b.get("max_adverse_pips", 0.0) for b in filtered["basket_dds"]), default=0.0)

    result = {
        "file": report_name,
        "symbol": symbol,
        "format": fmt,
        "initial_deposit": summary.get("initial_deposit"),
        "base": {
            "total_profit": base["total_profit"],
            "max_equity_dd": base["max_equity_dd"],
            "rd_ratio": base["rd_ratio"],
            "worst3_baskets": base["basket_dds"][:3],
        },
        "filtered_ignore_worst3": {
            "total_profit": filtered["total_profit"],
            "max_equity_dd": filtered["max_equity_dd"],
            "rd_ratio": filtered["rd_ratio"],
            "ignored_original_basket_ids": worst3_ids,
            "remaining_worst3_baskets": filtered["basket_dds"][:3],
        },
        "basket_sl_required_original": basket_sl_usd_original,
        "basket_sl_required_after_ignoring3": basket_sl_usd_after3,
        "basket_sl_required_original_usd": basket_sl_usd_original,
        "basket_sl_required_after_ignoring3_usd": basket_sl_usd_after3,
        "dynamic_basket_sl_pips_required_original": round(basket_sl_pips_original, 2),
        "dynamic_basket_sl_pips_required_after_ignoring3": round(basket_sl_pips_after3, 2),
    }
    result["equity_curve"] = base.get("equity_curve", [])
    result["equity_source"] = base.get("source", "ticks")
    return result


def main() -> None:
    all_results = []
    for name in FILES:
        print(f"Analyzing {name} ...", flush=True)
        all_results.append(analyze_one(name))

    portfolio_sl_original = max((r["basket_sl_required_original_usd"] for r in all_results), default=0.0)
    portfolio_sl_after_ignore3 = max((r["basket_sl_required_after_ignoring3_usd"] for r in all_results), default=0.0)
    portfolio_sl_pips_original = max((r["dynamic_basket_sl_pips_required_original"] for r in all_results), default=0.0)
    portfolio_sl_pips_after3 = max((r["dynamic_basket_sl_pips_required_after_ignoring3"] for r in all_results), default=0.0)

    out = {
        "results": all_results,
        "portfolio_basket_sl_required_original": round(portfolio_sl_original, 2),
        "portfolio_basket_sl_required_after_ignoring3": round(portfolio_sl_after_ignore3, 2),
        "portfolio_dynamic_basket_sl_pips_required_original": round(portfolio_sl_pips_original, 2),
        "portfolio_dynamic_basket_sl_pips_required_after_ignoring3": round(portfolio_sl_pips_after3, 2),
        "tick_sampling_every": TICK_SAMPLE_EVERY,
    }

    out_path = os.path.join(os.path.dirname(__file__), "custom_dd_analysis_output.json")
    with open(out_path, "w", encoding="utf-8") as f:
        # Don't write equity_curve to JSON (too large); strip it before saving
        import copy
        out_save = copy.deepcopy(out)
        for r in out_save["results"]:
            r.pop("equity_curve", None)
        json.dump(out_save, f, indent=2)

    print(f"Wrote {out_path}")

    print("\nTABLE 1: Full strategy (no baskets removed)")
    print("SYMBOL   MAX_EQUITY_DD_$   TOTAL_PROFIT_$   R_D_RATIO   DYNAMIC_BASKET_SL_PIPS(first-order anchor)")
    for r in all_results:
        rd = r["base"]["rd_ratio"]
        rd_txt = "inf" if math.isinf(rd) else f"{rd:.2f}"
        print(
            f"{r['symbol']:7}  {r['base']['max_equity_dd']:16.2f}  {r['base']['total_profit']:15.2f}  "
            f"{rd_txt:8}  {r['dynamic_basket_sl_pips_required_original']:10.2f}"
        )
    print(
        f"PORTFOLIO  {'-':>16}  {'-':>15}  {'-':>8}  {portfolio_sl_pips_original:10.2f}"
    )

    print("\nTABLE 2: Ignore worst 3 DD baskets")
    print("SYMBOL   MAX_EQUITY_DD_$   TOTAL_PROFIT_$   R_D_RATIO   DYNAMIC_BASKET_SL_PIPS(first-order anchor)")
    for r in all_results:
        rd = r["filtered_ignore_worst3"]["rd_ratio"]
        rd_txt = "inf" if math.isinf(rd) else f"{rd:.2f}"
        print(
            f"{r['symbol']:7}  {r['filtered_ignore_worst3']['max_equity_dd']:16.2f}  "
            f"{r['filtered_ignore_worst3']['total_profit']:15.2f}  {rd_txt:8}  "
            f"{r['dynamic_basket_sl_pips_required_after_ignoring3']:10.2f}"
        )
    print(
        f"PORTFOLIO  {'-':>16}  {'-':>15}  {'-':>8}  {portfolio_sl_pips_after3:10.2f}"
    )

    # Generate equity graphs
    fig, axes = plt.subplots(5, 1, figsize=(14, 20), sharex=False)
    fig.suptitle("Equity Curves by Symbol", fontsize=14, fontweight="bold")

    for ax, result in zip(axes, all_results):
        symbol = result["symbol"]
        curve = result.get("equity_curve", [])
        source = result.get("equity_source", "ticks")
        ax.set_title(
            f"{symbol}  |  Profit: ${result['base']['total_profit']:,.2f}  |  "
            f"Max DD: ${result['base']['max_equity_dd']:,.2f}  |  "
            f"R/D: {result['base']['rd_ratio']:.2f}  |  Source: {source}",
            fontsize=9,
        )
        if curve:
            ts_list = [datetime.fromtimestamp(pt[0], tz=timezone.utc) for pt in curve]
            eq_list = [pt[1] for pt in curve]
            ax.plot(ts_list, eq_list, linewidth=0.8, color="steelblue")
            ax.axhline(0, color="black", linewidth=0.5, linestyle="--")
            ax.fill_between(ts_list, eq_list, 0,
                            where=[e < 0 for e in eq_list],
                            alpha=0.3, color="red", label="Below zero")
            # Mark max drawdown trough
            min_eq = min(eq_list)
            min_idx = eq_list.index(min_eq)
            ax.scatter([ts_list[min_idx]], [min_eq], color="red", s=30, zorder=5)
        else:
            ax.text(0.5, 0.5, "No equity data", transform=ax.transAxes, ha="center")
        ax.set_ylabel("Equity ($)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right", fontsize=7)
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    graph_path = os.path.join(os.path.dirname(__file__), "equity_curves.png")
    plt.savefig(graph_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved equity graph: {graph_path}")


if __name__ == "__main__":
    main()
