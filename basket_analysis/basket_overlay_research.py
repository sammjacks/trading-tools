#!/usr/bin/env python3
"""
Basket Overlay Research
=======================

Research helper for a separate overlay trade that watches the source
basket strategy and opens ONE standalone trade when price has moved
adversely, a large basket is already open, and price starts to
consolidate.

Workflow
--------
1. Parse the source strategy tester report.
2. Build basket groups from the original trades.
3. Optimise many overlay rules on bar data over the first N years.
4. Verify the top bar-based candidates using the raw tick file so
   actual bid/ask spread is accounted for.
5. Export an HTML report with ranked results and the equity curve of
   the best candidate.
"""
from __future__ import annotations

import argparse
import bisect
import html as html_lib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple


def _load_base_module():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "basket_analysis.py")
    spec = importlib.util.spec_from_file_location("basket_analysis_base", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load basket_analysis.py from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BASE = _load_base_module()


def _trade_net(t: Dict) -> float:
    return t["profit"] + t.get("commission", 0.0) + t.get("swap", 0.0)


def _fmt_pf(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def _fmt_retdd(v: float) -> str:
    return "inf" if v == float("inf") else f"{v:.2f}"


def _fmt_money(v: float) -> str:
    return f"${v:,.2f}"


def _utc_text(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y.%m.%d %H:%M:%S")


def filter_to_first_years(trades: List[Dict], years: float) -> List[Dict]:
    if not trades:
        return []
    cutoff = trades[0]["ts"] + int(365.25 * 24 * 3600 * years)
    return [t for t in trades if t["ts"] < cutoff and t["close_ts"] <= cutoff]


def build_overlay_trade_for_basket(
    basket: Dict,
    bars: List[Dict],
    bar_ts: List[int],
    pip_size: float,
    symbol: str,
    overlay_lot: float,
    min_positions: int,
    min_adverse_pips: float,
    consolidation_bars: int,
    consolidation_ratio: float,
    direction_mode: str,
    entry_mode: str,
    stop_mode: str,
    stop_value: float,
    rr: float,
    params_tp_mode: str,
) -> Optional[Dict]:
    """Return one synthetic overlay trade for this basket, or None.

    Entry logic:
    - basket already has at least N open positions
    - price has moved at least X pips against the first basket entry
    - the last K bars have compressed into a narrow range relative to
      that adverse move (simple consolidation proxy)

    Entry is placed at the NEXT bar's open to avoid look-ahead.
    """
    group = sorted(basket["group"], key=lambda x: x["ts"])
    if len(group) < min_positions:
        return None

    first_trade = group[0]
    first_ts = first_trade["ts"]
    basket_close_ts = max(t["close_ts"] for t in group)

    si = bisect.bisect_left(bar_ts, first_ts)
    ei = bisect.bisect_right(bar_ts, basket_close_ts)
    if ei - si <= consolidation_bars:
        return None

    first_price = first_trade["price"]
    open_idx = 0

    for i in range(si + consolidation_bars - 1, ei - 1):
        ts = bar_ts[i]
        while open_idx < len(group) and group[open_idx]["ts"] <= ts:
            open_idx += 1
        open_count = open_idx
        if open_count < min_positions:
            continue

        close = bars[i]["c"]
        if basket["direction"] == "sell":
            adverse_pips = (close - first_price) / pip_size
            with_move_dir = "buy"
            with_basket_dir = "sell"
        else:
            adverse_pips = (first_price - close) / pip_size
            with_move_dir = "sell"
            with_basket_dir = "buy"

        if adverse_pips < min_adverse_pips:
            continue

        lo = min(bars[j]["l"] for j in range(i - consolidation_bars + 1, i + 1))
        hi = max(bars[j]["h"] for j in range(i - consolidation_bars + 1, i + 1))
        range_pips = (hi - lo) / pip_size
        if range_pips > consolidation_ratio * adverse_pips:
            continue

        entry_i = i + 1
        if entry_i >= len(bars) or bar_ts[entry_i] > basket_close_ts:
            continue

        if direction_mode in ("with_basket", "reversion"):
            direction = with_basket_dir
        else:
            direction = with_move_dir

        next_bar = bars[entry_i]
        if entry_mode == "direction":
            if direction == "buy" and next_bar["c"] <= next_bar["o"]:
                continue
            if direction == "sell" and next_bar["c"] >= next_bar["o"]:
                continue
        elif entry_mode == "breakout":
            if direction == "buy" and next_bar["c"] <= hi:
                continue
            if direction == "sell" and next_bar["c"] >= lo:
                continue

        entry_ts = bar_ts[entry_i]
        entry_price = next_bar["o"]

        if stop_mode == "dynamic":
            stop_pips = max(5.0, adverse_pips * stop_value)
        else:
            stop_pips = stop_value

        if params_tp_mode == "fib":
            tp_pips = max(3.0, adverse_pips * rr)
        else:
            tp_pips = stop_pips * rr

        if direction == "buy":
            sl_price = entry_price - stop_pips * pip_size
            tp_price = entry_price + tp_pips * pip_size
        else:
            sl_price = entry_price + stop_pips * pip_size
            tp_price = entry_price - tp_pips * pip_size

        exit_ts = basket_close_ts
        exit_price = group[-1]["close_price"]
        exit_reason = "BASKET"

        for j in range(entry_i, ei):
            if bar_ts[j] > basket_close_ts:
                break
            high = bars[j]["h"]
            low = bars[j]["l"]
            if direction == "buy":
                if low <= sl_price:
                    exit_ts = bar_ts[j]
                    exit_price = sl_price
                    exit_reason = "SL"
                    break
                if high >= tp_price:
                    exit_ts = bar_ts[j]
                    exit_price = tp_price
                    exit_reason = "TP"
                    break
            else:
                if high >= sl_price:
                    exit_ts = bar_ts[j]
                    exit_price = sl_price
                    exit_reason = "SL"
                    break
                if low <= tp_price:
                    exit_ts = bar_ts[j]
                    exit_price = tp_price
                    exit_reason = "TP"
                    break

        profit = BASE._trade_pnl(direction, entry_price, exit_price, overlay_lot, pip_size)
        return {
            "type": direction,
            "ts": int(entry_ts),
            "close_ts": int(exit_ts),
            "price": float(entry_price),
            "close_price": float(exit_price),
            "lots": overlay_lot,
            "profit": float(profit),
            "commission": 0.0,
            "swap": 0.0,
            "time": _utc_text(int(entry_ts)),
            "close_time": _utc_text(int(exit_ts)),
            "symbol": symbol,
            "_stop_pips": float(stop_pips),
            "_tp_pips": float(tp_pips),
            "_tp_mode": params_tp_mode,
            "_fib_target": float(rr) if params_tp_mode == "fib" else None,
            "_rr": float(rr) if params_tp_mode != "fib" else None,
            "_deadline_ts": int(basket_close_ts),
            "_reason": exit_reason,
            "_open_count": open_count,
            "_signal_adverse_pips": float(adverse_pips),
            "_source_direction": basket["direction"],
        }

    return None


def build_overlay_trades(
    baskets: List[Dict],
    bars: List[Dict],
    bar_ts: List[int],
    pip_size: float,
    symbol: str,
    overlay_lot: float,
    params: Dict,
) -> List[Dict]:
    out: List[Dict] = []
    for b in baskets:
        trade = build_overlay_trade_for_basket(
            b, bars, bar_ts, pip_size, symbol, overlay_lot,
            params["min_positions"],
            params["min_adverse_pips"],
            params["consolidation_bars"],
            params["consolidation_ratio"],
            params["direction_mode"],
            params.get("entry_mode", "next_open"),
            params["stop_mode"],
            params["stop_value"],
            params["rr"],
            params.get("tp_mode", "rr"),
        )
        if trade is not None:
            out.append(trade)
    out.sort(key=lambda x: x["ts"])
    return out


def compute_overlay_metrics(trades: List[Dict], bars: List[Dict]) -> Tuple[Dict, List[Dict]]:
    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_win": 0.0,
            "gross_loss": 0.0,
            "pf": 0.0,
            "net": 0.0,
            "max_eq_dd": 0.0,
            "ret_dd": 0.0,
            "final_balance": 0.0,
        }, []

    vals = [_trade_net(t) for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    pf = abs(gross_win / gross_loss) if gross_loss < 0 else float("inf")
    curves = BASE.build_equity_curve(trades, [], bars, sample_every=15)
    eq = BASE.equity_stats(curves, trades[0]["ts"])
    max_dd = eq.get("max_dd", 0.0)
    net = gross_win + gross_loss
    ret_dd = net / max_dd if max_dd > 0 else (float("inf") if net > 0 else 0.0)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "pf": pf,
        "net": net,
        "max_eq_dd": max_dd,
        "ret_dd": ret_dd,
        "final_balance": eq.get("final_bal", 0.0),
    }, curves


def generate_param_grid(args) -> List[Dict]:
    grid: List[Dict] = []
    for min_positions in args.min_positions:
        for min_adverse_pips in args.min_adverse_pips:
            for consolidation_bars in args.consolidation_bars:
                for consolidation_ratio in args.consolidation_ratios:
                    for direction_mode in args.direction_modes:
                        for entry_mode in args.entry_modes:
                            for stop_value in args.fixed_sl_pips:
                                for rr in args.rr_values:
                                    grid.append({
                                        "min_positions": min_positions,
                                        "min_adverse_pips": min_adverse_pips,
                                        "consolidation_bars": consolidation_bars,
                                        "consolidation_ratio": consolidation_ratio,
                                        "direction_mode": direction_mode,
                                        "entry_mode": entry_mode,
                                        "stop_mode": "fixed",
                                        "stop_value": float(stop_value),
                                        "tp_mode": "rr",
                                        "rr": float(rr),
                                    })
                                for fib in args.fib_tp_levels:
                                    grid.append({
                                        "min_positions": min_positions,
                                        "min_adverse_pips": min_adverse_pips,
                                        "consolidation_bars": consolidation_bars,
                                        "consolidation_ratio": consolidation_ratio,
                                        "direction_mode": direction_mode,
                                        "entry_mode": entry_mode,
                                        "stop_mode": "fixed",
                                        "stop_value": float(stop_value),
                                        "tp_mode": "fib",
                                        "rr": float(fib),
                                    })
                            for stop_value in args.dynamic_stop_fracs:
                                for rr in args.rr_values:
                                    grid.append({
                                        "min_positions": min_positions,
                                        "min_adverse_pips": min_adverse_pips,
                                        "consolidation_bars": consolidation_bars,
                                        "consolidation_ratio": consolidation_ratio,
                                        "direction_mode": direction_mode,
                                        "entry_mode": entry_mode,
                                        "stop_mode": "dynamic",
                                        "stop_value": float(stop_value),
                                        "tp_mode": "rr",
                                        "rr": float(rr),
                                    })
                                for fib in args.fib_tp_levels:
                                    grid.append({
                                        "min_positions": min_positions,
                                        "min_adverse_pips": min_adverse_pips,
                                        "consolidation_bars": consolidation_bars,
                                        "consolidation_ratio": consolidation_ratio,
                                        "direction_mode": direction_mode,
                                        "entry_mode": entry_mode,
                                        "stop_mode": "dynamic",
                                        "stop_value": float(stop_value),
                                        "tp_mode": "fib",
                                        "rr": float(fib),
                                    })
    return grid


def run_bar_optimisation(
    baskets: List[Dict],
    bars: List[Dict],
    bar_ts: List[int],
    pip_size: float,
    symbol: str,
    overlay_lot: float,
    grid: List[Dict],
    min_signals: int,
    top_n: int,
) -> Tuple[List[Dict], Dict]:
    start = time.perf_counter()
    results: List[Dict] = []
    progress_step = max(1, len(grid) // 20)

    for idx, params in enumerate(grid, start=1):
        trades = build_overlay_trades(
            baskets, bars, bar_ts, pip_size, symbol, overlay_lot, params
        )
        metrics, curves = compute_overlay_metrics(trades, bars)
        if metrics["trades"] >= min_signals:
            results.append({**params, **metrics, "overlay_trades": trades, "curves": curves})

        if idx % progress_step == 0 or idx == len(grid):
            elapsed = time.perf_counter() - start
            rate = idx / elapsed if elapsed > 0 else 0.0
            remaining = (len(grid) - idx) / rate if rate > 0 else 0.0
            print(
                f"Progress: {idx:,}/{len(grid):,} ({idx / len(grid) * 100:.1f}%)  "
                f"rate={rate:.1f}/s  ETA={remaining / 60:.1f}m"
            )

    deduped: List[Dict] = []
    seen: set = set()
    for r in results:
        key = (
            r["direction_mode"],
            r.get("entry_mode", "next_open"),
            r["min_positions"],
            round(r["min_adverse_pips"], 3),
            r["consolidation_bars"],
            round(r["consolidation_ratio"], 4),
            r["stop_mode"],
            round(r["stop_value"], 4),
            r.get("tp_mode", "rr"),
            round(r["rr"], 4),
            r["trades"],
            round(r["net"], 2),
            round(r["max_eq_dd"], 2),
            round(r["pf"], 3),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    deduped.sort(key=lambda r: (-r["ret_dd"], -r["net"], -r["pf"], -r["win_rate"]))
    top = deduped[:top_n]

    summary = {
        "tested": len(grid),
        "kept": len(results),
        "unique": len(deduped),
        "elapsed_sec": time.perf_counter() - start,
    }
    return top, summary


def _epoch_to_tick_key(ts: int, tick_gmt: int) -> int:
    dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=tick_gmt)))
    return int(dt.strftime("%Y%m%d%H%M%S%f")[:17])


def _tick_string_to_key(s: str) -> int:
    return int(s[6:10] + s[3:5] + s[0:2] + s[11:13] + s[14:16] + s[17:19] + s[20:23])


def _tick_string_to_epoch(s: str, tick_gmt: int) -> int:
    tz_ = timezone(timedelta(hours=tick_gmt))
    dt = datetime(
        int(s[6:10]), int(s[3:5]), int(s[0:2]),
        int(s[11:13]), int(s[14:16]), int(s[17:19]),
        int(s[20:23]) * 1000,
        tzinfo=tz_,
    )
    return int(dt.timestamp())


def verify_top_results_with_ticks(
    results: List[Dict],
    tick_path: str,
    tick_gmt: int,
    pip_size: float,
    bars: List[Dict],
    top_n: int,
) -> List[Dict]:
    if not results or top_n <= 0:
        return []

    chosen = results[:top_n]
    pending: List[Dict] = []
    for res_idx, res in enumerate(chosen):
        for tr in res["overlay_trades"]:
            pending.append({
                "result_idx": res_idx,
                "trade": tr,
                "enter_key": _epoch_to_tick_key(tr["ts"], tick_gmt),
                "deadline_key": _epoch_to_tick_key(tr.get("_deadline_ts", tr["close_ts"]), tick_gmt),
                "type": tr["type"],
                "lots": tr["lots"],
                "stop_pips": tr.get("_stop_pips", 0.0),
                "tp_pips": tr.get("_tp_pips", 0.0),
            })

    pending.sort(key=lambda x: x["enter_key"])
    if not pending:
        return []

    first_key = pending[0]["enter_key"]
    last_key = max(p["deadline_key"] for p in pending)
    active: List[Dict] = []
    closed: List[List[Dict]] = [[] for _ in chosen]
    pending_idx = 0
    lines = 0
    last_report = time.perf_counter()

    print(f"Tick verification: streaming {os.path.basename(tick_path)} once for top {len(chosen)} result(s)…")
    with open(tick_path, "r", encoding="utf-8") as fh:
        for line in fh:
            lines += 1
            if "," not in line:
                continue
            parts = line.strip().split(",")
            if len(parts) < 3:
                continue
            ts_str = parts[0].strip()
            try:
                key = _tick_string_to_key(ts_str)
            except Exception:
                continue

            if key < first_key:
                continue
            if key > last_key and pending_idx >= len(pending) and not active:
                break

            try:
                ask = float(parts[1])
                bid = float(parts[2])
            except ValueError:
                continue

            while pending_idx < len(pending) and pending[pending_idx]["enter_key"] <= key:
                item = pending[pending_idx]
                pending_idx += 1
                entry = ask if item["type"] == "buy" else bid
                item["entry_price_actual"] = entry
                if item["type"] == "buy":
                    item["sl_price_actual"] = entry - item["stop_pips"] * pip_size
                    item["tp_price_actual"] = entry + item["tp_pips"] * pip_size
                else:
                    item["sl_price_actual"] = entry + item["stop_pips"] * pip_size
                    item["tp_price_actual"] = entry - item["tp_pips"] * pip_size
                active.append(item)

            if active:
                tick_epoch = None
                still: List[Dict] = []
                for item in active:
                    exit_now = False
                    reason = ""
                    exit_price = 0.0
                    if item["type"] == "buy":
                        if bid <= item["sl_price_actual"]:
                            exit_now = True
                            reason = "SL"
                            exit_price = bid
                        elif bid >= item["tp_price_actual"]:
                            exit_now = True
                            reason = "TP"
                            exit_price = bid
                    else:
                        if ask >= item["sl_price_actual"]:
                            exit_now = True
                            reason = "SL"
                            exit_price = ask
                        elif ask <= item["tp_price_actual"]:
                            exit_now = True
                            reason = "TP"
                            exit_price = ask

                    if not exit_now and key >= item["deadline_key"]:
                        exit_now = True
                        reason = "BASKET"
                        exit_price = bid if item["type"] == "buy" else ask

                    if exit_now:
                        if tick_epoch is None:
                            tick_epoch = _tick_string_to_epoch(ts_str, tick_gmt)
                        t = item["trade"]
                        profit = BASE._trade_pnl(
                            item["type"],
                            item["entry_price_actual"],
                            exit_price,
                            item["lots"],
                            pip_size,
                        )
                        closed[item["result_idx"]].append({
                            **t,
                            "price": float(item["entry_price_actual"]),
                            "close_price": float(exit_price),
                            "close_ts": int(tick_epoch),
                            "close_time": _utc_text(int(tick_epoch)),
                            "profit": float(profit),
                            "_reason": reason,
                        })
                    else:
                        still.append(item)
                active = still

            now = time.perf_counter()
            if now - last_report > 10:
                print(f"  streamed {lines:,} lines  active={len(active)}  pending={len(pending) - pending_idx}")
                last_report = now

    verified: List[Dict] = []
    for i, res in enumerate(chosen):
        vt = sorted(closed[i], key=lambda x: x["ts"])
        metrics, curves = compute_overlay_metrics(vt, bars)
        verified.append({**res, **{f"tick_{k}": v for k, v in metrics.items()}, "tick_curves": curves})
    return verified


def build_summary_lines(
    source_trades: List[Dict],
    source_baskets: List[Dict],
    years: float,
    grid_size: int,
    summary: Dict,
) -> List[str]:
    lines: List[str] = []
    lines.append("")
    lines.append("=" * 112)
    lines.append("BASKET OVERLAY RESEARCH")
    lines.append("=" * 112)
    lines.append("")
    lines.append(f"  Training window: first {years:g} years from the first trade")
    lines.append(f"  Source trades:   {len(source_trades):,}")
    lines.append(f"  Source baskets:  {len(source_baskets):,}")
    lines.append(f"  Grid tested:     {grid_size:,} parameter combos")
    lines.append(f"  Passing results: {summary['kept']:,} with the minimum signal count")
    lines.append(f"  Unique results:  {summary['unique']:,}")
    lines.append(f"  Runtime:         {summary['elapsed_sec']:.1f}s")
    lines.append("")
    lines.append("  Signal idea:")
    lines.append("    When a basket is already stretched and price compresses into a narrow")
    lines.append("    consolidation, open one standalone overlay trade either WITH the move")
    lines.append("    or WITH the basket, then manage it with a fixed or dynamic SL/TP.")
    return lines


def build_top_results_lines(top: List[Dict]) -> List[str]:
    lines: List[str] = []
    lines.append("")
    lines.append("=" * 156)
    lines.append("TOP BAR-BASED OVERLAY RESULTS")
    lines.append("=" * 156)
    lines.append("")
    if not top:
        lines.append("  No qualifying results.")
        return lines

    lines.append(
        f"  {'#':>3}  {'Dir':>11}  {'Entry':>9}  {'Pos>=':>5}  {'Adv>=':>6}  {'Bars':>4}  {'Cons%':>6}  "
        f"{'Stop':>7}  {'SL':>6}  {'TP':>8}  {'Trades':>7}  {'Win%':>6}  {'PF':>6}  "
        f"{'Net':>11}  {'EqDD':>11}  {'Ret/DD':>8}"
    )
    lines.append(f"  {'-' * 168}")

    for i, r in enumerate(top, start=1):
        sl_text = f"{r['stop_value']:.2f}" if r["stop_mode"] == "dynamic" else f"{r['stop_value']:.0f}p"
        tp_text = f"fib {r['rr']:.3f}" if r.get('tp_mode') == 'fib' else f"rr {r['rr']:.2f}"
        lines.append(
            f"  {i:>3}  {r['direction_mode']:>11}  {r.get('entry_mode', 'next_open'):>9}  {r['min_positions']:>5}  {r['min_adverse_pips']:>6.0f}  "
            f"{r['consolidation_bars']:>4}  {r['consolidation_ratio'] * 100:>5.0f}%  "
            f"{r['stop_mode']:>7}  {sl_text:>6}  {tp_text:>8}  {r['trades']:>7}  "
            f"{r['win_rate']:>5.1f}%  {_fmt_pf(r['pf']):>6}  {_fmt_money(r['net']):>11}  "
            f"{_fmt_money(r['max_eq_dd']):>11}  {_fmt_retdd(r['ret_dd']):>8}"
        )
    lines.append("")
    modes = {r.get("direction_mode", "") for r in top}
    if "with_move" in modes:
        lines.append("  Direction mode 'with_move' means the overlay joins the current move after")
        lines.append("  the basket has stretched and then compressed into a short consolidation.")
    if "with_basket" in modes:
        lines.append("  Direction mode 'with_basket' means the overlay joins the source basket after")
        lines.append("  a stretch and short consolidation, aiming for a Fibonacci-style retracement.")
    return lines


def build_tick_lines(verified: List[Dict]) -> List[str]:
    lines: List[str] = []
    lines.append("")
    lines.append("=" * 156)
    lines.append("TICK VERIFICATION OF TOP RESULTS")
    lines.append("=" * 156)
    lines.append("")
    if not verified:
        lines.append("  Tick verification not run.")
        return lines

    lines.append(
        f"  {'#':>3}  {'Trades':>7}  {'Win%':>6}  {'PF':>6}  {'Tick Net':>11}  {'Tick EqDD':>11}  {'Tick Ret/DD':>11}"
    )
    lines.append(f"  {'-' * 80}")
    for i, r in enumerate(verified, start=1):
        lines.append(
            f"  {i:>3}  {r.get('tick_trades', 0):>7}  {r.get('tick_win_rate', 0):>5.1f}%  "
            f"{_fmt_pf(r.get('tick_pf', 0.0)):>6}  {_fmt_money(r.get('tick_net', 0.0)):>11}  "
            f"{_fmt_money(r.get('tick_max_eq_dd', 0.0)):>11}  {_fmt_retdd(r.get('tick_ret_dd', 0.0)):>11}"
        )
    lines.append("")
    lines.append("  Tick verification replays the top candidates using actual bid/ask prices from")
    lines.append("  the tick file, so spread is accounted for on both entry and exit.")
    return lines


def write_overlay_html_report(
    out_path: str,
    title: str,
    bar_curves: List[Dict],
    tick_curves: Optional[List[Dict]],
    first_ts: int,
    text_sections: List[List[str]],
) -> None:
    bar_labels, bar_bal_data, bar_eq_data = BASE.curves_to_daily(bar_curves, first_ts)
    tick_source = tick_curves if tick_curves else bar_curves
    tick_labels, tick_bal_data, tick_eq_data = BASE.curves_to_daily(tick_source, first_ts)
    text_html = "".join(BASE._text_to_html_block(s) for s in text_sections)

    html_out = f"""<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>{html_lib.escape(title)}</title>
<script src=\"https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js\"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f7f7f7; color: #222; }}
  .container {{ max-width: 1300px; margin: auto; background: white; padding: 24px;
                border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  h2 {{ font-size: 18px; margin: 18px 0 8px; }}
  .chart-box {{ position: relative; height: 420px; margin-bottom: 24px; }}
  .note {{ color: #555; margin: 0 0 16px; }}
</style></head><body><div class=\"container\">
<h1>{html_lib.escape(title)}</h1>
<h2>Bar-based equity curve</h2>
<p class=\"note\">This chart reflects the bar simulation used for the optimisation table above.</p>
<div class=\"chart-box\"><canvas id=\"barChart\"></canvas></div>
{text_html}
<h2>Tick-verified equity curve</h2>
<p class=\"note\">This chart reflects the spread-aware tick replay of the selected result.</p>
<div class=\"chart-box\"><canvas id=\"tickChart\"></canvas></div>
<script>
function buildChart(canvasId, labels, bal, eq, balanceLabel, equityLabel) {{
  new Chart(document.getElementById(canvasId), {{
    type: 'line',
    data: {{ labels, datasets: [
      {{ label: balanceLabel, data: bal, borderColor: '#378ADD',
         backgroundColor: 'rgba(55,138,221,0.08)', fill: true,
         borderWidth: 2, pointRadius: 0, tension: 0.2 }},
      {{ label: equityLabel, data: eq, borderColor: '#1D9E75',
         backgroundColor: 'rgba(29,158,117,0.08)', fill: true,
         borderWidth: 2, pointRadius: 0, tension: 0.2 }}
    ]}},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ legend: {{ position: 'top' }},
        tooltip: {{ callbacks: {{ label: c => c.dataset.label + ': $' + c.parsed.y.toLocaleString() }} }} }},
      scales: {{
        x: {{ ticks: {{ maxTicksLimit: 20, maxRotation: 45 }} }},
        y: {{ ticks: {{ callback: v => '$' + v.toLocaleString() }} }}
      }}
    }}
  }});
}}

buildChart('barChart', {json.dumps(bar_labels)}, {json.dumps(bar_bal_data)}, {json.dumps(bar_eq_data)}, 'Bar balance', 'Bar equity');
buildChart('tickChart', {json.dumps(tick_labels)}, {json.dumps(tick_bal_data)}, {json.dumps(tick_eq_data)}, 'Tick balance', 'Tick equity');
</script></div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Overlay optimisation on top of a source basket strategy",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--statement", required=True, help="Source MT4/MT5 statement or tester report")
    ap.add_argument("--bars", required=True, help="Bars CSV used for signal generation and equity mapping")
    ap.add_argument("--ticks", default=None, help="Tick CSV for spread-aware verification of the top results")
    ap.add_argument("--symbol", default="EURUSD", help="Symbol filter")
    ap.add_argument("--broker-gmt", type=int, default=2, help="Broker GMT offset used by the statement")
    ap.add_argument("--tick-gmt", type=int, default=2, help="Tick file GMT offset")
    ap.add_argument("--train-years", type=float, default=4.0, help="Optimisation window length from the first trade")
    ap.add_argument("--overlay-lot", type=float, default=0.01, help="Overlay lot size for P&L scaling")
    ap.add_argument("--min-signals", type=int, default=40, help="Minimum number of overlay trades required to keep a result")
    ap.add_argument("--top-results", type=int, default=20, help="How many bar-based results to show")
    ap.add_argument("--tick-verify-top", type=int, default=3, help="How many top results to verify with the tick file")
    ap.add_argument("--min-positions", nargs="+", type=int, default=[6, 8, 10, 12], help="Basket size thresholds to test")
    ap.add_argument("--min-adverse-pips", nargs="+", type=float, default=[15, 20, 25, 30, 40], help="Adverse move thresholds to test")
    ap.add_argument("--consolidation-bars", nargs="+", type=int, default=[3, 4, 6], help="Number of recent bars defining consolidation")
    ap.add_argument("--consolidation-ratios", nargs="+", type=float, default=[0.20, 0.30, 0.40], help="Max recent-range / adverse-move ratio")
    ap.add_argument("--direction-modes", nargs="+", default=["with_basket"], help="Overlay direction modes to test")
    ap.add_argument("--entry-modes", nargs="+", default=["breakout", "direction", "next_open"], help="Entry trigger modes after consolidation")
    ap.add_argument("--fixed-sl-pips", nargs="+", type=float, default=[10, 15, 20], help="Fixed SL values in pips")
    ap.add_argument("--dynamic-stop-fracs", nargs="+", type=float, default=[0.25, 0.50], help="Dynamic SL as a fraction of the adverse move")
    ap.add_argument("--rr-values", nargs="+", type=float, default=[1.0, 1.25, 1.5], help="Risk/reward multiples to test when TP is stop-based")
    ap.add_argument("--fib-tp-levels", nargs="+", type=float, default=[0.236, 0.382, 0.500, 0.618, 0.786], help="Fibonacci retracement fractions of the adverse move used for dynamic TP")
    ap.add_argument("--out-dir", default=".", help="Output directory")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    print(f"Loading statement: {args.statement}")
    trades, _ = BASE.parse_statement(args.statement, args.broker_gmt, args.symbol)
    if not trades:
        print("No trades parsed.", file=sys.stderr)
        return 1

    print(f"Loading bars: {args.bars}")
    bars, bar_ts = BASE.load_bars(args.bars)
    if not bars:
        print("No bars loaded.", file=sys.stderr)
        return 1

    train_trades = filter_to_first_years(trades, args.train_years)
    if not train_trades:
        print("No trades remain in the training window.", file=sys.stderr)
        return 1

    baskets = BASE.make_baskets(train_trades, 10)
    pip_size = BASE.detect_pip_size(train_trades[0]["price"])
    symbol = args.symbol or train_trades[0].get("symbol", "")

    print(f"Training window trades: {len(train_trades):,}")
    print(f"Training window baskets: {len(baskets):,}")
    print(f"Detected pip size: {pip_size}")

    grid = generate_param_grid(args)
    print(f"\nRunning overlay optimisation ({len(grid):,} trials)…")
    top, summary = run_bar_optimisation(
        baskets, bars, bar_ts, pip_size, symbol, args.overlay_lot,
        grid, args.min_signals, args.top_results,
    )

    summary_lines = build_summary_lines(train_trades, baskets, args.train_years, len(grid), summary)
    top_lines = build_top_results_lines(top)
    for ln in summary_lines + top_lines:
        print(ln)

    verified = []
    if args.ticks and args.tick_verify_top > 0 and top:
        verified = verify_top_results_with_ticks(
            top, args.ticks, args.tick_gmt, pip_size, bars, args.tick_verify_top
        )
        tick_lines = build_tick_lines(verified)
        for ln in tick_lines:
            print(ln)
    else:
        tick_lines = build_tick_lines([])

    if not top:
        print("\nNo qualifying overlay results found.")
        return 0

    best = verified[0] if verified else top[0]
    best_bar_curves = top[0].get("curves") or []
    best_tick_curves = best.get("tick_curves") or None
    first_ts = best["overlay_trades"][0]["ts"] if best.get("overlay_trades") else train_trades[0]["ts"]

    html_path = os.path.join(args.out_dir, "overlay_research.html")
    title = f"{symbol} — Basket Overlay Research"
    write_overlay_html_report(html_path, title, best_bar_curves, best_tick_curves, first_ts, [summary_lines, top_lines, tick_lines])
    print(f"\nHTML report written: {html_path}")

    json_path = os.path.join(args.out_dir, "overlay_top_results.json")
    to_save = []
    for r in top:
        s = {k: v for k, v in r.items() if k not in {"overlay_trades", "curves", "tick_curves"}}
        to_save.append(s)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(to_save, fh, indent=2)
    print(f"Top results JSON written: {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
