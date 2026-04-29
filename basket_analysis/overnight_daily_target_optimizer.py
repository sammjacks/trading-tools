#!/usr/bin/env python3
"""
Overnight optimizer for basket-style strategy reports.

Goal:
- Find robust parameter sets that increase probability of hitting
  daily return target while keeping daily equity drawdown bounded.

This script reuses basket_analysis internals directly to avoid repeated
process startup and to run large searches unattended.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Dict, List, Optional, Tuple

import basket_analysis as ba


@dataclass
class Dataset:
    trades: List[Dict]
    baskets: List[Dict]
    bars: List[Dict]
    bar_ts: List[int]
    balance_ops: List[Dict]


def _subset_bars(bars: List[Dict], start_ts: int, end_ts: int) -> Tuple[List[Dict], List[int]]:
    s = start_ts - 86400
    e = end_ts + 86400
    out = [b for b in bars if s <= int(b["ts"]) <= e]
    return out, [int(b["ts"]) for b in out]


def _split_train_test(trades: List[Dict], ratio: float) -> Tuple[List[Dict], List[Dict], int]:
    if not trades:
        return [], [], 0
    sorted_trades = sorted(trades, key=lambda t: t["close_ts"])
    idx = max(1, min(len(sorted_trades) - 1, int(len(sorted_trades) * ratio)))
    split_ts = int(sorted_trades[idx]["close_ts"])
    train = [t for t in sorted_trades if int(t["close_ts"]) <= split_ts]
    test = [t for t in sorted_trades if int(t["close_ts"]) > split_ts]
    return train, test, split_ts


def _daily_metrics(curves: List[Dict], broker_gmt: int, target_pct: float, max_dd_pct: float) -> Dict:
    if not curves:
        return {
            "days": 0,
            "target_hit_rate": 0.0,
            "dd_ok_rate": 0.0,
            "joint_pass_rate": 0.0,
            "avg_daily_return_pct": 0.0,
            "p95_daily_dd_pct": 0.0,
            "max_daily_dd_pct": 0.0,
        }

    tz = timezone(timedelta(hours=broker_gmt))
    by_day: Dict[str, List[Dict]] = {}
    for p in curves:
        day = datetime.fromtimestamp(int(p["ts"]), tz=tz).strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append(p)

    daily_returns: List[float] = []
    daily_dds: List[float] = []
    n_hit = 0
    n_dd_ok = 0
    n_joint = 0

    for _, pts in sorted(by_day.items()):
        pts = sorted(pts, key=lambda x: x["ts"])
        start_eq = float(pts[0]["eq"])
        if start_eq <= 0:
            continue
        end_eq = float(pts[-1]["eq"])
        peak = start_eq
        worst_from_start = 0.0
        worst_peak_drop = 0.0

        for p in pts:
            eq = float(p["eq"])
            if eq > peak:
                peak = eq
            worst_from_start = min(worst_from_start, eq - start_eq)
            worst_peak_drop = max(worst_peak_drop, peak - eq)

        ret_pct = (end_eq - start_eq) / start_eq * 100.0
        dd_pct_start = abs(worst_from_start) / start_eq * 100.0
        dd_pct_peak = worst_peak_drop / start_eq * 100.0
        dd_pct = max(dd_pct_start, dd_pct_peak)

        daily_returns.append(ret_pct)
        daily_dds.append(dd_pct)

        hit = ret_pct >= target_pct
        dd_ok = dd_pct <= max_dd_pct
        if hit:
            n_hit += 1
        if dd_ok:
            n_dd_ok += 1
        if hit and dd_ok:
            n_joint += 1

    n_days = len(daily_returns)
    if n_days == 0:
        return {
            "days": 0,
            "target_hit_rate": 0.0,
            "dd_ok_rate": 0.0,
            "joint_pass_rate": 0.0,
            "avg_daily_return_pct": 0.0,
            "p95_daily_dd_pct": 0.0,
            "max_daily_dd_pct": 0.0,
        }

    dds_sorted = sorted(daily_dds)
    p95_idx = min(len(dds_sorted) - 1, int(math.ceil(0.95 * len(dds_sorted))) - 1)

    return {
        "days": n_days,
        "target_hit_rate": n_hit / n_days,
        "dd_ok_rate": n_dd_ok / n_days,
        "joint_pass_rate": n_joint / n_days,
        "avg_daily_return_pct": mean(daily_returns),
        "p95_daily_dd_pct": dds_sorted[p95_idx],
        "max_daily_dd_pct": max(daily_dds),
    }


def _evaluate_params(
    ds: Dataset,
    params: Dict,
    ticks: List[Dict],
    tick_ts: List[float],
    broker_gmt: int,
    pip_size: float,
    eod_hour: int,
    eod_minute: int,
    daily_target_pct: float,
    daily_dd_limit_pct: float,
) -> Dict:
    filt = ba.apply_trade_filters(
        ds.trades,
        ds.baskets,
        params.get("session_start"),
        params.get("session_end"),
        params.get("max_spread_initial"),
        params.get("max_spread_all"),
        params.get("skip_days"),
    )

    if not filt:
        return {
            "trades": 0,
            "baskets": 0,
            "net": 0.0,
            "eq_dd": 0.0,
            "ret_dd": 0.0,
            "daily": _daily_metrics([], broker_gmt, daily_target_pct, daily_dd_limit_pct),
        }

    filt_baskets = ba.make_baskets(filt, close_window_seconds=10)

    if params.get("sl_pips") is not None or params.get("use_eod"):
        sl = float(params.get("sl_pips") or 1e9)
        synth, _, tick_verified, bar_fallback = ba.build_synthetic_trades_ticks(
            filt_baskets,
            ds.bars,
            ds.bar_ts,
            ticks,
            tick_ts,
            sl,
            bool(params.get("use_eod")),
            broker_gmt,
            pip_size,
            eod_hour,
            eod_minute,
        )
        use_trades = synth
    else:
        tick_verified = 0
        bar_fallback = 0
        use_trades = filt

    curves = ba.build_equity_curve(use_trades, ds.balance_ops, ds.bars, sample_every=1)
    stats = ba.compute_stats(use_trades, ba.make_baskets(use_trades, 10), curves)
    daily = _daily_metrics(curves, broker_gmt, daily_target_pct, daily_dd_limit_pct)

    return {
        "trades": len(use_trades),
        "baskets": len(filt_baskets),
        "net": float(stats.get("net", 0.0)),
        "eq_dd": float(stats.get("max_eq_dd", 0.0)),
        "ret_dd": float(stats.get("net", 0.0)) / float(stats.get("max_eq_dd", 0.0)) if float(stats.get("max_eq_dd", 0.0)) > 0 else 0.0,
        "tick_verified": tick_verified,
        "bar_fallback": bar_fallback,
        "daily": daily,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Overnight robust optimizer for daily target vs daily DD")
    ap.add_argument("--statement", required=True)
    ap.add_argument("--bars", required=True)
    ap.add_argument("--ticks", required=True)
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--out-dir", default="./overnight_research_output")
    ap.add_argument("--broker-gmt", type=int, default=2)
    ap.add_argument("--tick-gmt", type=int, default=2)
    ap.add_argument("--daily-target-pct", type=float, default=0.5)
    ap.add_argument("--daily-dd-limit-pct", type=float, default=1.0)
    ap.add_argument("--train-ratio", type=float, default=0.7)
    ap.add_argument("--top-coarse", type=int, default=400)
    ap.add_argument("--top-final", type=int, default=50)
    ap.add_argument("--session-step", type=int, default=3)
    ap.add_argument("--min-session-width", type=int, default=6)
    ap.add_argument("--spread-values", nargs="*", type=float, default=[0, 0.5, 1.0, 1.5, 2.0])
    ap.add_argument("--day-options", nargs="*", default=["none", "no-mon", "no-fri", "no-mon-fri", "no-mon-sun", "no-fri-sun"])
    ap.add_argument("--sl-values", nargs="*", type=float, default=[10, 15, 20, 25, 30, 40, 50, 60, 80])
    ap.add_argument("--eod-options", nargs="*", default=["0", "1"])
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    print("[1/7] Loading statement/trades...")
    trades, balance_ops = ba.parse_statement(args.statement, args.broker_gmt, args.symbol)
    if not trades:
        raise SystemExit("No trades parsed from statement")

    print("[2/7] Loading bars...")
    bars, bar_ts = ba.load_bars(args.bars)

    print("[3/7] Loading ticks...")
    ticks, tick_ts = ba.load_ticks(args.ticks, args.tick_gmt)

    print("[4/7] Preparing baskets and context...")
    trades = sorted(trades, key=lambda t: t["ts"])
    train_trades, test_trades, split_ts = _split_train_test(trades, args.train_ratio)

    train_baskets = ba.make_baskets(train_trades, close_window_seconds=10)
    test_baskets = ba.make_baskets(test_trades, close_window_seconds=10)

    pip_size = ba._pip_size(trades[0]["price"] if trades else 1.2)
    ba.precompute_trade_context(train_trades, ticks, tick_ts, args.broker_gmt, pip_size)
    ba.precompute_trade_context(test_trades, ticks, tick_ts, args.broker_gmt, pip_size)
    ba.tag_trades_with_baskets(train_trades, train_baskets)
    ba.tag_trades_with_baskets(test_trades, test_baskets)

    train_start = min(int(t["ts"]) for t in train_trades)
    train_end = max(int(t["close_ts"]) for t in train_trades)
    test_start = min(int(t["ts"]) for t in test_trades)
    test_end = max(int(t["close_ts"]) for t in test_trades)
    train_bars, train_bar_ts = _subset_bars(bars, train_start, train_end)
    test_bars, test_bar_ts = _subset_bars(bars, test_start, test_end)

    ds_train = Dataset(train_trades, train_baskets, train_bars, train_bar_ts, [])
    ds_test = Dataset(test_trades, test_baskets, test_bars, test_bar_ts, [])

    print("[5/7] Coarse search (fast realized ranking)...")
    grid = ba.generate_filter_grid(
        session_step=args.session_step,
        min_session_width=args.min_session_width,
        spread_values=args.spread_values,
        day_options=args.day_options,
        sl_values=args.sl_values,
        eod_options=args.eod_options,
    )

    bm = ba.fast_realized_stats(train_trades)
    coarse_top, coarse_summary = ba.run_filter_optimization(
        trades=train_trades,
        baskets=train_baskets,
        bars=train_bars,
        balance_ops=[],
        grid=grid,
        benchmark_net=bm["net"],
        benchmark_dd=max(bm["max_dd"], 1e-9),
        top_n=args.top_coarse,
        broker_gmt=args.broker_gmt,
        pip_size=pip_size,
        eod_hour=23,
        eod_minute=59,
        spread_profile=None,
        close_window_seconds=10,
    )

    print(f"Coarse tested: {coarse_summary['total_trials']:,} | unique outcomes: {coarse_summary['unique_outcomes']:,}")

    print("[6/7] Tick-precise validation on train+test...")
    evaluated: List[Dict] = []
    for i, row in enumerate(coarse_top, start=1):
        params = {
            "session_start": row.get("session_start"),
            "session_end": row.get("session_end"),
            "max_spread_initial": row.get("max_spread_initial"),
            "max_spread_all": row.get("max_spread_all"),
            "skip_days": row.get("skip_days"),
            "day_label": row.get("day_label"),
            "sl_pips": row.get("sl_pips"),
            "use_eod": bool(row.get("use_eod")),
        }

        tr = _evaluate_params(
            ds_train,
            params,
            ticks,
            tick_ts,
            args.broker_gmt,
            pip_size,
            23,
            59,
            args.daily_target_pct,
            args.daily_dd_limit_pct,
        )
        te = _evaluate_params(
            ds_test,
            params,
            ticks,
            tick_ts,
            args.broker_gmt,
            pip_size,
            23,
            59,
            args.daily_target_pct,
            args.daily_dd_limit_pct,
        )

        # Robustness score prioritizes out-of-sample daily constraint behavior.
        score = (
            100.0 * te["daily"]["joint_pass_rate"]
            + 15.0 * te["daily"]["dd_ok_rate"]
            + 10.0 * max(0.0, te["daily"]["avg_daily_return_pct"])
            + 2.0 * max(0.0, te["ret_dd"])
        )

        evaluated.append({
            "rank_coarse": i,
            "params": params,
            "train": tr,
            "test": te,
            "score": score,
        })

        if i % 25 == 0:
            print(f"  validated {i}/{len(coarse_top)} candidates")

    evaluated.sort(
        key=lambda r: (
            -r["score"],
            -r["test"]["daily"]["joint_pass_rate"],
            -r["test"]["daily"]["dd_ok_rate"],
            -r["test"]["ret_dd"],
            -r["test"]["net"],
        )
    )

    top = evaluated[: args.top_final]

    print("[7/7] Writing outputs...")
    out_json = os.path.join(args.out_dir, "overnight_top_results.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump({
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "statement": args.statement,
            "bars": args.bars,
            "ticks": args.ticks,
            "symbol": args.symbol,
            "split_ts": split_ts,
            "coarse_summary": coarse_summary,
            "daily_target_pct": args.daily_target_pct,
            "daily_dd_limit_pct": args.daily_dd_limit_pct,
            "top_results": top,
        }, fh, indent=2)

    out_csv = os.path.join(args.out_dir, "overnight_top_results.csv")
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "rank", "score", "session", "spread_initial", "spread_all", "sl_pips", "eod", "days",
            "test_joint_pass_rate", "test_target_hit_rate", "test_dd_ok_rate", "test_avg_daily_return_pct",
            "test_p95_daily_dd_pct", "test_max_daily_dd_pct", "test_net", "test_eq_dd", "test_ret_dd",
            "train_joint_pass_rate", "train_avg_daily_return_pct", "train_max_daily_dd_pct",
        ])
        for rank, r in enumerate(top, start=1):
            p = r["params"]
            te = r["test"]["daily"]
            tr = r["train"]["daily"]
            sess = "all" if p["session_start"] is None else f"{p['session_start']:02d}-{p['session_end']:02d}"
            w.writerow([
                rank,
                f"{r['score']:.4f}",
                sess,
                p["max_spread_initial"],
                p["max_spread_all"],
                p["sl_pips"],
                int(bool(p["use_eod"])),
                te["days"],
                f"{te['joint_pass_rate'] * 100:.2f}",
                f"{te['target_hit_rate'] * 100:.2f}",
                f"{te['dd_ok_rate'] * 100:.2f}",
                f"{te['avg_daily_return_pct']:.4f}",
                f"{te['p95_daily_dd_pct']:.4f}",
                f"{te['max_daily_dd_pct']:.4f}",
                f"{r['test']['net']:.2f}",
                f"{r['test']['eq_dd']:.2f}",
                f"{r['test']['ret_dd']:.4f}",
                f"{tr['joint_pass_rate'] * 100:.2f}",
                f"{tr['avg_daily_return_pct']:.4f}",
                f"{tr['max_daily_dd_pct']:.4f}",
            ])

    out_md = os.path.join(args.out_dir, "overnight_summary.md")
    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write("# Overnight Basket Optimization Summary\n\n")
        fh.write(f"- Generated: {datetime.utcnow().isoformat()}Z\n")
        fh.write(f"- Symbol: {args.symbol}\n")
        fh.write(f"- Daily target: {args.daily_target_pct:.2f}%\n")
        fh.write(f"- Daily DD limit: {args.daily_dd_limit_pct:.2f}%\n")
        fh.write(f"- Coarse trials: {coarse_summary['total_trials']:,}\n")
        fh.write(f"- Unique coarse outcomes: {coarse_summary['unique_outcomes']:,}\n\n")
        fh.write("## Top 10 (out-of-sample priority)\n\n")
        fh.write("| Rank | Session | Spread Init | Spread All | SL | EOD | Test Joint Pass % | Test DD OK % | Test Avg Daily % | Test Max Daily DD % | Test Ret/DD |\n")
        fh.write("|---:|:---:|---:|---:|---:|:---:|---:|---:|---:|---:|---:|\n")
        for rank, r in enumerate(top[:10], start=1):
            p = r["params"]
            te = r["test"]["daily"]
            sess = "all" if p["session_start"] is None else f"{p['session_start']:02d}-{p['session_end']:02d}"
            fh.write(
                f"| {rank} | {sess} | {p['max_spread_initial']} | {p['max_spread_all']} | {p['sl_pips']} | {int(bool(p['use_eod']))} "
                f"| {te['joint_pass_rate']*100:.2f} | {te['dd_ok_rate']*100:.2f} | {te['avg_daily_return_pct']:.3f} | {te['max_daily_dd_pct']:.3f} | {r['test']['ret_dd']:.2f} |\n"
            )

    print("Done.")
    print(f"Results JSON: {out_json}")
    print(f"Results CSV:  {out_csv}")
    print(f"Summary MD:   {out_md}")


if __name__ == "__main__":
    main()
