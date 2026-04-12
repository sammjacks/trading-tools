#!/usr/bin/env python3
"""
Basket Strategy Analysis Tool
==============================

Performs three analyses on a trading statement:

  1. BAR ANALYSIS — parses statement, builds baskets, reconstructs
     balance/equity curve from bar data, and scans basket SL levels
     showing BOTH EOD and no-EOD modes side by side with max equity DD.

  2. TICK ANALYSIS (optional, --ticks) — compares bar-based SL hits
     against tick-based hits to reveal spread kills. Has its own
     SL range (--tick-sl-range) so you can run fewer iterations.

  3. HTML REPORT — writes an interactive chart AND all the text tables
     into a single standalone HTML file.

Usage
-----
    python basket_analysis.py \\
        --statement /path/to/statement.htm \\
        --bars /path/to/EURUSD_M1.csv \\
        --sl-range 6 20 \\
        [--ticks /path/to/ticks.csv] \\
        [--tick-sl-range 8 14] \\
        [--symbol EURUSD] \\
        [--start 2026-01-01] [--end 2026-04-01] \\
        [--broker-gmt 2] [--tick-gmt 2] \\
        [--out-dir ./results]

Lot sizes
---------
Profit and drawdown are reported in dollars at the ACTUAL lot sizes
used in the statement — not scaled to any particular size. If you want
to model a different lot size, multiply the numbers by your ratio.
"""
from __future__ import annotations

import argparse
import bisect
import html as html_lib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import List, Dict, Optional, Tuple


# ────────────────────────────────────────────────────────────────────────────
# HTML statement parsing
# ────────────────────────────────────────────────────────────────────────────
class _RowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._in_row = False
        self._in_td = False
        self._current_row: List[str] = []
        self._current_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._in_row = True
            self._current_row = []
        elif tag == "td" and self._in_row:
            self._in_td = True
            self._current_text = ""

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td:
            self._in_td = False
            self._current_row.append(self._current_text.strip())
        elif tag == "tr" and self._in_row:
            self._in_row = False
            self.rows.append(self._current_row)

    def handle_data(self, data):
        if self._in_td:
            self._current_text += data


def parse_statement(path: str, broker_gmt: int, symbol_filter: Optional[str]
                    ) -> Tuple[List[Dict], List[Dict]]:
    """Parse live statement OR MT4 strategy tester report."""
    with open(path, "r", encoding="utf-8") as fh:
        parser = _RowParser()
        parser.feed(fh.read())

    offset = timezone(timedelta(hours=broker_gmt))

    def _parse_dt(s: str) -> int:
        s = s.strip()
        for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
            try:
                return int(datetime.strptime(s, fmt).replace(tzinfo=offset).timestamp())
            except ValueError:
                continue
        raise ValueError(f"Unrecognised datetime: {s!r}")

    trades: List[Dict] = []
    balance_ops: List[Dict] = []
    tester_opens: Dict[int, Dict] = {}

    for row in parser.rows:
        if not row:
            continue

        if len(row) >= 3 and row[2].strip().lower() == "balance":
            try:
                amt = float(row[-1].replace(" ", "").replace(",", ""))
                ts = _parse_dt(row[1])
                balance_ops.append({
                    "ts": ts, "amt": amt, "time": row[1],
                    "type": "deposit" if amt >= 0 else "withdrawal",
                })
            except (ValueError, IndexError):
                pass
            continue

        if len(row) == 14:
            ttype = row[2].strip().lower()
            if ttype not in ("buy", "sell"):
                continue
            if symbol_filter and symbol_filter.lower() not in row[4].strip().lower():
                continue
            try:
                trades.append({
                    "type": ttype,
                    "ts": _parse_dt(row[1]),
                    "close_ts": _parse_dt(row[8]),
                    "price": float(row[5]),
                    "close_price": float(row[9]),
                    "lots": float(row[3]),
                    "profit": float(row[13]),
                    "commission": float(row[10]),
                    "swap": float(row[12]),
                    "time": row[1],
                    "close_time": row[8],
                    "symbol": row[4].strip(),
                })
            except (ValueError, IndexError):
                continue
            continue

        if len(row) == 9:
            ttype = row[2].strip().lower()
            if ttype in ("buy", "sell"):
                try:
                    order = int(row[3])
                    tester_opens[order] = {
                        "type": ttype,
                        "ts": _parse_dt(row[1]),
                        "price": float(row[5]),
                        "lots": float(row[4]),
                        "time": row[1],
                    }
                except (ValueError, IndexError):
                    pass
            continue

        if len(row) == 10 and row[2].strip().lower() == "close":
            try:
                order = int(row[3])
                if order not in tester_opens:
                    continue
                o = tester_opens.pop(order)
                trades.append({
                    "type": o["type"],
                    "ts": o["ts"],
                    "close_ts": _parse_dt(row[1]),
                    "price": o["price"],
                    "close_price": float(row[5]),
                    "lots": o["lots"],
                    "profit": float(row[8]),
                    "commission": 0.0,
                    "swap": 0.0,
                    "time": o["time"],
                    "close_time": row[1],
                    "symbol": symbol_filter or "",
                })
            except (ValueError, IndexError):
                continue

    trades.sort(key=lambda x: x["ts"])
    return trades, balance_ops


# ────────────────────────────────────────────────────────────────────────────
# Data loaders
# ────────────────────────────────────────────────────────────────────────────
def load_bars(path: str) -> Tuple[List[Dict], List[int]]:
    bars: List[Dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            try:
                bars.append({
                    "ts": int(parts[0]),
                    "o": float(parts[1]),
                    "h": float(parts[2]),
                    "l": float(parts[3]),
                    "c": float(parts[4]),
                })
            except ValueError:
                continue
    bars.sort(key=lambda b: b["ts"])
    return bars, [b["ts"] for b in bars]


def load_ticks(path: str, tick_gmt: int) -> Tuple[List[Dict], List[float]]:
    offset = timezone(timedelta(hours=tick_gmt))
    ticks: List[Dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue
            try:
                dt = datetime.strptime(parts[0].strip(), "%d.%m.%Y %H:%M:%S.%f")
                ts = dt.replace(tzinfo=offset).timestamp()
                ticks.append({
                    "ts": ts,
                    "ask": float(parts[1]),
                    "bid": float(parts[2]),
                })
            except (ValueError, IndexError):
                continue
    ticks.sort(key=lambda t: t["ts"])
    return ticks, [t["ts"] for t in ticks]


# ────────────────────────────────────────────────────────────────────────────
# Basket grouping
# ────────────────────────────────────────────────────────────────────────────
def make_baskets(trades: List[Dict], close_window_seconds: int = 10) -> List[Dict]:
    """Group trades into baskets using close-time clustering per direction.

    A basket is a group of same-direction trades whose close timestamps
    fall within `close_window_seconds` of the first close in the group.
    This handles two scenarios correctly:

    1. Normal basket TP/SL: all trades close at the same tick (backtest)
       or within a second or two (live, sequential broker-side closes).

    2. Mass-close events (EA daily DD protection, manual close-all, etc.)
       where the broker takes several seconds to sequentially close every
       open position across multiple logical baskets. These look like a
       single risk event and the user typically wants them grouped.

    Using per-direction clustering means a mass-close that affects both
    long and short positions produces two baskets (one buy, one sell)
    which keeps the SL simulation math correct — SL is always relative
    to a single direction.
    """
    if not trades:
        return []

    baskets: List[Dict] = []

    for direction in ("buy", "sell"):
        dir_trades = sorted(
            [t for t in trades if t["type"] == direction],
            key=lambda t: t["close_ts"],
        )
        if not dir_trades:
            continue

        current: List[Dict] = []
        anchor_ts = 0
        for t in dir_trades:
            if not current:
                current = [t]
                anchor_ts = t["close_ts"]
            elif t["close_ts"] - anchor_ts <= close_window_seconds:
                current.append(t)
            else:
                baskets.append(_build_basket_from_group(current))
                current = [t]
                anchor_ts = t["close_ts"]
        if current:
            baskets.append(_build_basket_from_group(current))

    baskets.sort(key=lambda b: b["close_ts"])
    return baskets


def _build_basket_from_group(group: List[Dict]) -> Dict:
    first = min(group, key=lambda x: x["ts"])
    close_ts = max(t["close_ts"] for t in group)
    pnl = sum(t["profit"] + t["commission"] + t["swap"] for t in group)
    return {
        "pnl": pnl,
        "count": len(group),
        "direction": first["type"],
        "first_ts": first["ts"],
        "close_ts": close_ts,
        "first_price": first["price"],
        "time": first["time"],
        "group": group,
    }


def detect_pip_size(first_price: float) -> float:
    return 0.01 if first_price > 20 else 0.0001


def _trade_pnl(direction: str, entry: float, exit_price: float, lots: float,
               pip_size: float) -> float:
    """P&L in account currency. Assumes USD account; JPY pair needs /price."""
    diff = (exit_price - entry) if direction == "buy" else (entry - exit_price)
    if pip_size == 0.01:
        return diff * lots * 100000 / exit_price
    return diff * lots * 100000


# ────────────────────────────────────────────────────────────────────────────
# Equity curve (active-list sweep, O(N_bars + N_trades))
# ────────────────────────────────────────────────────────────────────────────
def build_equity_curve(trades: List[Dict], balance_ops: List[Dict],
                       bars: List[Dict], sample_every: int = 15) -> List[Dict]:
    curves: List[Dict] = []
    realised = 0.0
    cash = 0.0

    open_sorted = sorted(trades, key=lambda t: t["ts"])
    bal_sorted = sorted(balance_ops, key=lambda x: x["ts"])

    open_idx = 0
    bal_idx = 0
    active: List[Dict] = []

    for bi in range(0, len(bars), sample_every):
        bar = bars[bi]
        bar_ts = bar["ts"]
        bar_c = bar["c"]

        while bal_idx < len(bal_sorted) and bal_sorted[bal_idx]["ts"] <= bar_ts:
            cash += bal_sorted[bal_idx]["amt"]
            bal_idx += 1

        while open_idx < len(open_sorted) and open_sorted[open_idx]["ts"] <= bar_ts:
            active.append(open_sorted[open_idx])
            open_idx += 1

        still = []
        for t in active:
            if t["close_ts"] <= bar_ts:
                realised += t["profit"] + t["commission"] + t["swap"]
            else:
                still.append(t)
        active = still

        balance = cash + realised

        unreal = 0.0
        for t in active:
            pip_size = detect_pip_size(t["price"])
            unreal += _trade_pnl(t["type"], t["price"], bar_c, t["lots"], pip_size)

        curves.append({"ts": bar_ts, "bal": round(balance, 2),
                       "eq": round(balance + unreal, 2)})

    # Append a final curve point that reflects all closed trades and balance
    # operations, even those that happened after the last bar in the data.
    # Otherwise any trades that close past the end of the bar file get
    # silently dropped and the curve understates the final balance.
    while bal_idx < len(bal_sorted):
        cash += bal_sorted[bal_idx]["amt"]
        bal_idx += 1
    while open_idx < len(open_sorted):
        active.append(open_sorted[open_idx])
        open_idx += 1
    for t in active:
        realised += t["profit"] + t["commission"] + t["swap"]

    true_final_bal = round(cash + realised, 2)
    if trades:
        final_ts = max(
            curves[-1]["ts"] if curves else 0,
            trades[-1]["close_ts"],
        )
    else:
        final_ts = curves[-1]["ts"] if curves else 0

    if curves and curves[-1]["bal"] != true_final_bal:
        curves.append({"ts": final_ts, "bal": true_final_bal, "eq": true_final_bal})

    return curves


def equity_stats(curves: List[Dict], start_ts: int) -> Dict:
    series = [p for p in curves if p["ts"] >= start_ts]
    if not series:
        return {}
    peak = 0.0
    max_dd = 0.0
    low = float("inf")
    for p in series:
        if p["eq"] > peak:
            peak = p["eq"]
        dd = peak - p["eq"]
        if dd > max_dd:
            max_dd = dd
        if 0 < p["eq"] < low:
            low = p["eq"]
    return {
        "peak": peak,
        "low": low if low != float("inf") else 0.0,
        "max_dd": max_dd,
        "final_bal": series[-1]["bal"],
        "final_eq": series[-1]["eq"],
    }


# ────────────────────────────────────────────────────────────────────────────
# Build synthetic trade list under an SL/EOD scenario
# ────────────────────────────────────────────────────────────────────────────
def _get_eod_ts(ts: int, broker_gmt: int, eod_hour: int = 23,
                eod_minute: int = 59) -> int:
    """Next 'end of day' timestamp at eod_hour:eod_minute broker time."""
    dt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=broker_gmt)))
    eod = dt.replace(hour=eod_hour, minute=eod_minute, second=0, microsecond=0)
    if eod.timestamp() <= ts:
        eod += timedelta(days=1)
    return int(eod.timestamp())


def filter_baskets_by_open_time(baskets: List[Dict], broker_gmt: int,
                                  start_hour: Optional[int],
                                  end_hour: Optional[int]) -> List[Dict]:
    """Keep only baskets whose FIRST trade opened within [start_hour, end_hour)
    broker-local. Supports wrap past midnight (e.g. 22 → 6)."""
    if start_hour is None and end_hour is None:
        return baskets
    if start_hour is None:
        start_hour = 0
    if end_hour is None:
        end_hour = 24
    tz_ = timezone(timedelta(hours=broker_gmt))
    kept = []
    for b in baskets:
        h = datetime.fromtimestamp(b["first_ts"], tz=tz_).hour
        if start_hour <= end_hour:
            if start_hour <= h < end_hour:
                kept.append(b)
        else:  # wraps midnight
            if h >= start_hour or h < end_hour:
                kept.append(b)
    return kept


def build_synthetic_trades(baskets: List[Dict], bars: List[Dict], bar_ts: List[int],
                            sl_pips: float, use_eod: bool, broker_gmt: int,
                            pip_size: float, eod_hour: int = 23,
                            eod_minute: int = 59,
                            spread_profile: Optional[Dict[int, float]] = None
                            ) -> Tuple[List[Dict], List[Dict]]:
    """Apply SL (+ optional EOD close) to every basket using bar data.

    When a spread_profile is given, the effective SL trigger is adjusted
    by half the median spread of the basket's open hour. This approximates
    how a tick-based SL trigger would behave (where bid reaches SL for buys,
    ask reaches SL for sells) using mid-based bar data.
    """
    synth: List[Dict] = []
    outcomes: List[Dict] = []
    tz_ = timezone(timedelta(hours=broker_gmt))

    for b in baskets:
        direction = b["direction"]
        if direction == "sell":
            sl_price = b["first_price"] + sl_pips * pip_size
        else:
            sl_price = b["first_price"] - sl_pips * pip_size

        # Apply spread adjustment if profile available — effective trigger
        # level is closer to entry by half the hourly median spread, so the
        # bar (mid) will hit it sooner, matching what the broker would do
        # when the bid/ask reaches the actual SL.
        sl_trigger = sl_price
        if spread_profile:
            hour = datetime.fromtimestamp(b["first_ts"], tz=tz_).hour
            half_spread_price = (spread_profile.get(hour, 0.0) / 2.0) * pip_size
            if direction == "sell":
                sl_trigger = sl_price - half_spread_price
            else:
                sl_trigger = sl_price + half_spread_price

        eod_ts = _get_eod_ts(b["first_ts"], broker_gmt, eod_hour, eod_minute) \
            if use_eod else b["close_ts"] + 10 ** 9
        limit_ts = min(b["close_ts"], eod_ts)

        si = bisect.bisect_left(bar_ts, b["first_ts"])
        ei = min(bisect.bisect_left(bar_ts, limit_ts + 60), len(bars))

        hit_ts = None
        for i in range(si, ei):
            if bar_ts[i] > limit_ts:
                break
            if direction == "sell" and bars[i]["h"] >= sl_trigger:
                hit_ts = bar_ts[i]
                break
            elif direction == "buy" and bars[i]["l"] <= sl_trigger:
                hit_ts = bar_ts[i]
                break

        if hit_ts is not None:
            basket_pnl = 0.0
            for t in b["group"]:
                if t["ts"] <= hit_ts:
                    pnl = _trade_pnl(direction, t["price"], sl_price, t["lots"], pip_size)
                    pnl += t["commission"]
                    basket_pnl += pnl
                    synth.append({**t, "close_ts": hit_ts, "close_price": sl_price,
                                  "profit": pnl, "commission": 0.0, "swap": 0.0})
            outcomes.append({"outcome": "SL", "pnl": basket_pnl, "won": basket_pnl > 0})
        elif use_eod and b["close_ts"] > eod_ts:
            eod_idx = bisect.bisect_right(bar_ts, eod_ts) - 1
            if eod_idx >= 0:
                eod_price = bars[eod_idx]["c"]
                basket_pnl = 0.0
                for t in b["group"]:
                    if t["ts"] <= eod_ts:
                        pnl = _trade_pnl(direction, t["price"], eod_price, t["lots"], pip_size)
                        pnl += t["commission"]
                        basket_pnl += pnl
                        synth.append({**t, "close_ts": eod_ts, "close_price": eod_price,
                                      "profit": pnl, "commission": 0.0, "swap": 0.0})
                outcomes.append({"outcome": "EOD", "pnl": basket_pnl, "won": basket_pnl > 0})
            else:
                for t in b["group"]:
                    synth.append(dict(t))
                outcomes.append({"outcome": "TP", "pnl": b["pnl"], "won": b["pnl"] > 0})
        else:
            for t in b["group"]:
                synth.append(dict(t))
            outcomes.append({"outcome": "TP", "pnl": b["pnl"], "won": b["pnl"] > 0})

    synth.sort(key=lambda x: x["ts"])
    return synth, outcomes


def simulate_sl_full(baskets: List[Dict], bars: List[Dict], bar_ts: List[int],
                     sl_pips: float, use_eod: bool, broker_gmt: int,
                     pip_size: float, balance_ops: List[Dict],
                     eod_hour: int = 23, eod_minute: int = 59,
                     spread_profile: Optional[Dict[int, float]] = None) -> Dict:
    """Full SL sim: synthetic trades → basket stats + equity DD via curve."""
    synth, outcomes = build_synthetic_trades(
        baskets, bars, bar_ts, sl_pips, use_eod, broker_gmt, pip_size,
        eod_hour, eod_minute, spread_profile
    )

    total = len(outcomes)
    wins = sum(1 for o in outcomes if o["won"])
    losses = total - wins

    tp_won = sum(1 for o in outcomes if o["outcome"] == "TP" and o["won"])
    tp_lost = sum(1 for o in outcomes if o["outcome"] == "TP" and not o["won"])
    sl_won = sum(1 for o in outcomes if o["outcome"] == "SL" and o["won"])
    sl_lost = sum(1 for o in outcomes if o["outcome"] == "SL" and not o["won"])
    eod_won = sum(1 for o in outcomes if o["outcome"] == "EOD" and o["won"])
    eod_lost = sum(1 for o in outcomes if o["outcome"] == "EOD" and not o["won"])

    gw = sum(o["pnl"] for o in outcomes if o["won"])
    gl = sum(o["pnl"] for o in outcomes if not o["won"])
    net = gw + gl
    pf = abs(gw / gl) if gl else float("inf")

    # Equity DD via curve rebuild (sparse sample for speed)
    curves = build_equity_curve(synth, balance_ops, bars, sample_every=30)
    first_ts = synth[0]["ts"] if synth else 0
    eq = equity_stats(curves, first_ts)
    eq_dd = eq.get("max_dd", 0.0)

    return {
        "sl": sl_pips, "use_eod": use_eod,
        "total": total, "wins": wins, "losses": losses,
        "tp": tp_won + tp_lost, "sl_exits": sl_won + sl_lost,
        "eod_exits": eod_won + eod_lost,
        "tp_won": tp_won, "tp_lost": tp_lost,
        "sl_won": sl_won, "sl_lost": sl_lost,
        "eod_won": eod_won, "eod_lost": eod_lost,
        "pf": pf, "net": net, "eq_dd": eq_dd,
        "ret_dd": net / eq_dd if eq_dd > 0 else (float("inf") if net >= 0 else -float("inf")),
    }


# ────────────────────────────────────────────────────────────────────────────
# Tick-based SL simulation
# ────────────────────────────────────────────────────────────────────────────
def simulate_sl_ticks(baskets: List[Dict], ticks: List[Dict], tick_ts: List[float],
                      sl_pips: float, use_eod: bool, broker_gmt: int,
                      pip_size: float, eod_hour: int = 23,
                      eod_minute: int = 59) -> Dict:
    stops = 0
    spread_kills = 0
    net = 0.0

    for b in baskets:
        direction = b["direction"]
        if direction == "sell":
            sl_price = b["first_price"] + sl_pips * pip_size
        else:
            sl_price = b["first_price"] - sl_pips * pip_size

        eod_ts = _get_eod_ts(b["first_ts"], broker_gmt, eod_hour, eod_minute) \
            if use_eod else b["close_ts"] + 10 ** 9
        limit_ts = min(b["close_ts"], eod_ts)

        ti_s = bisect.bisect_left(tick_ts, b["first_ts"])
        ti_e = min(bisect.bisect_left(tick_ts, limit_ts + 1), len(ticks))

        hit_tick = None
        for i in range(ti_s, ti_e):
            if direction == "sell" and ticks[i]["ask"] >= sl_price:
                hit_tick = ticks[i]
                break
            elif direction == "buy" and ticks[i]["bid"] <= sl_price:
                hit_tick = ticks[i]
                break

        if hit_tick is not None:
            stops += 1
            mid = (hit_tick["ask"] + hit_tick["bid"]) / 2
            if direction == "buy":
                mid_dist = (b["first_price"] - mid) / pip_size
            else:
                mid_dist = (mid - b["first_price"]) / pip_size
            if mid_dist < sl_pips:
                spread_kills += 1

            basket_pnl = 0.0
            for t in b["group"]:
                if t["ts"] <= hit_tick["ts"]:
                    pnl = _trade_pnl(direction, t["price"], sl_price, t["lots"], pip_size)
                    pnl += t["commission"]
                    basket_pnl += pnl
            net += basket_pnl
        elif use_eod and b["close_ts"] > eod_ts:
            ti_eod = bisect.bisect_right(tick_ts, eod_ts) - 1
            if ti_eod >= 0:
                mid = (ticks[ti_eod]["ask"] + ticks[ti_eod]["bid"]) / 2
                basket_pnl = 0.0
                for t in b["group"]:
                    if t["ts"] <= eod_ts:
                        pnl = _trade_pnl(direction, t["price"], mid, t["lots"], pip_size)
                        pnl += t["commission"]
                        basket_pnl += pnl
                net += basket_pnl
            else:
                net += b["pnl"]
        else:
            net += b["pnl"]

    return {"sl": sl_pips, "net": net, "stops": stops,
            "spread_kills": spread_kills, "total": len(baskets)}


def simulate_sl_full_ticks(baskets: List[Dict], bars: List[Dict], bar_ts: List[int],
                            ticks: List[Dict], tick_ts: List[float],
                            sl_pips: float, use_eod: bool, broker_gmt: int,
                            pip_size: float, balance_ops: List[Dict],
                            eod_hour: int = 23, eod_minute: int = 59) -> Dict:
    """Tick-precision SL sim: uses ask/bid for SL detection and tick mids
    for EOD prices. Falls back to bars for baskets outside tick coverage.
    Returns the same stats shape as simulate_sl_full.
    """
    synth, outcomes, tick_verified, bar_fallback = build_synthetic_trades_ticks(
        baskets, bars, bar_ts, ticks, tick_ts, sl_pips, use_eod,
        broker_gmt, pip_size, eod_hour, eod_minute
    )

    total = len(outcomes)
    wins = sum(1 for o in outcomes if o["won"])
    losses = total - wins

    tp_won = sum(1 for o in outcomes if o["outcome"] == "TP" and o["won"])
    tp_lost = sum(1 for o in outcomes if o["outcome"] == "TP" and not o["won"])
    sl_won = sum(1 for o in outcomes if o["outcome"] == "SL" and o["won"])
    sl_lost = sum(1 for o in outcomes if o["outcome"] == "SL" and not o["won"])
    eod_won = sum(1 for o in outcomes if o["outcome"] == "EOD" and o["won"])
    eod_lost = sum(1 for o in outcomes if o["outcome"] == "EOD" and not o["won"])

    gw = sum(o["pnl"] for o in outcomes if o["won"])
    gl = sum(o["pnl"] for o in outcomes if not o["won"])
    net = gw + gl
    pf = abs(gw / gl) if gl else float("inf")

    curves = build_equity_curve(synth, balance_ops, bars, sample_every=30)
    first_ts = synth[0]["ts"] if synth else 0
    eq = equity_stats(curves, first_ts)
    eq_dd = eq.get("max_dd", 0.0)

    return {
        "sl": sl_pips, "use_eod": use_eod,
        "total": total, "wins": wins, "losses": losses,
        "tp": tp_won + tp_lost, "sl_exits": sl_won + sl_lost,
        "eod_exits": eod_won + eod_lost,
        "tp_won": tp_won, "tp_lost": tp_lost,
        "sl_won": sl_won, "sl_lost": sl_lost,
        "eod_won": eod_won, "eod_lost": eod_lost,
        "pf": pf, "net": net, "eq_dd": eq_dd,
        "ret_dd": net / eq_dd if eq_dd > 0 else (float("inf") if net >= 0 else -float("inf")),
        "tick_verified": tick_verified, "bar_fallback": bar_fallback,
    }


# ────────────────────────────────────────────────────────────────────────────
# Tick-precision synthetic trades (for final check)
# ────────────────────────────────────────────────────────────────────────────
def build_synthetic_trades_ticks(baskets: List[Dict], bars: List[Dict],
                                   bar_ts: List[int], ticks: List[Dict],
                                   tick_ts: List[float], sl_pips: float,
                                   use_eod: bool, broker_gmt: int,
                                   pip_size: float, eod_hour: int = 23,
                                   eod_minute: int = 59
                                   ) -> Tuple[List[Dict], List[Dict], int, int]:
    """Tick-precision version: uses tick ask/bid for SL detection and tick
    mid for EOD close prices. Falls back to bars for baskets outside tick
    coverage. Returns (synth_trades, outcomes, tick_verified, bar_fallback).
    """
    synth: List[Dict] = []
    outcomes: List[Dict] = []
    tick_verified = 0
    fallback = 0

    tick_start = ticks[0]["ts"] if ticks else 0
    tick_end = ticks[-1]["ts"] if ticks else 0

    for b in baskets:
        direction = b["direction"]
        if direction == "sell":
            sl_price = b["first_price"] + sl_pips * pip_size
        else:
            sl_price = b["first_price"] - sl_pips * pip_size

        eod_ts = _get_eod_ts(b["first_ts"], broker_gmt, eod_hour, eod_minute) \
            if use_eod else b["close_ts"] + 10 ** 9
        limit_ts = min(b["close_ts"], eod_ts)

        in_ticks = (ticks and b["first_ts"] >= tick_start
                    and limit_ts <= tick_end + 1)

        hit_ts = None
        if in_ticks:
            tick_verified += 1
            ti_s = bisect.bisect_left(tick_ts, b["first_ts"])
            ti_e = min(bisect.bisect_left(tick_ts, limit_ts + 1), len(ticks))
            for i in range(ti_s, ti_e):
                if direction == "sell" and ticks[i]["ask"] >= sl_price:
                    hit_ts = int(ticks[i]["ts"])
                    break
                elif direction == "buy" and ticks[i]["bid"] <= sl_price:
                    hit_ts = int(ticks[i]["ts"])
                    break
        else:
            fallback += 1
            si = bisect.bisect_left(bar_ts, b["first_ts"])
            ei = min(bisect.bisect_left(bar_ts, limit_ts + 60), len(bars))
            for i in range(si, ei):
                if bar_ts[i] > limit_ts:
                    break
                if direction == "sell" and bars[i]["h"] >= sl_price:
                    hit_ts = bar_ts[i]
                    break
                elif direction == "buy" and bars[i]["l"] <= sl_price:
                    hit_ts = bar_ts[i]
                    break

        if hit_ts is not None:
            basket_pnl = 0.0
            for t in b["group"]:
                if t["ts"] <= hit_ts:
                    pnl = _trade_pnl(direction, t["price"], sl_price, t["lots"], pip_size)
                    pnl += t["commission"]
                    basket_pnl += pnl
                    synth.append({**t, "close_ts": hit_ts, "close_price": sl_price,
                                  "profit": pnl, "commission": 0.0, "swap": 0.0})
            outcomes.append({"outcome": "SL", "pnl": basket_pnl, "won": basket_pnl > 0})
        elif use_eod and b["close_ts"] > eod_ts:
            eod_price = None
            if in_ticks:
                ti_eod = bisect.bisect_right(tick_ts, eod_ts) - 1
                if ti_eod >= 0 and ticks[ti_eod]["ts"] >= b["first_ts"]:
                    eod_price = (ticks[ti_eod]["ask"] + ticks[ti_eod]["bid"]) / 2
            else:
                eod_idx = bisect.bisect_right(bar_ts, eod_ts) - 1
                if eod_idx >= 0:
                    eod_price = bars[eod_idx]["c"]

            if eod_price is not None:
                basket_pnl = 0.0
                for t in b["group"]:
                    if t["ts"] <= eod_ts:
                        pnl = _trade_pnl(direction, t["price"], eod_price, t["lots"], pip_size)
                        pnl += t["commission"]
                        basket_pnl += pnl
                        synth.append({**t, "close_ts": int(eod_ts),
                                      "close_price": eod_price,
                                      "profit": pnl, "commission": 0.0, "swap": 0.0})
                outcomes.append({"outcome": "EOD", "pnl": basket_pnl,
                                 "won": basket_pnl > 0})
            else:
                for t in b["group"]:
                    synth.append(dict(t))
                outcomes.append({"outcome": "TP", "pnl": b["pnl"],
                                 "won": b["pnl"] > 0})
        else:
            for t in b["group"]:
                synth.append(dict(t))
            outcomes.append({"outcome": "TP", "pnl": b["pnl"], "won": b["pnl"] > 0})

    synth.sort(key=lambda x: x["ts"])
    return synth, outcomes, tick_verified, fallback


# ────────────────────────────────────────────────────────────────────────────
# Text report builders
# ────────────────────────────────────────────────────────────────────────────
def _fmt_pf(pf: float) -> str:
    return f"{pf:.2f}" if pf != float("inf") else "  inf"


def _fmt_retdd(r: float) -> str:
    if abs(r) == float("inf"):
        return "  inf"
    return f"{r:.2f}"


def build_summary_text(trades: List[Dict], baskets: List[Dict],
                        balance_ops: List[Dict], curves: List[Dict]) -> List[str]:
    lines = []
    deposits = sum(op["amt"] for op in balance_ops if op["amt"] >= 0)
    withdrawals = sum(op["amt"] for op in balance_ops if op["amt"] < 0)

    lines.append("=" * 70)
    lines.append("STATEMENT SUMMARY")
    lines.append("=" * 70)
    lines.append(f"  Deposits:     ${deposits:>12,.2f}")
    lines.append(f"  Withdrawals:  ${withdrawals:>12,.2f}")
    lines.append(f"  Net funded:   ${deposits + withdrawals:>12,.2f}")
    lines.append(f"  Trades:       {len(trades):>12}")
    if trades:
        lines.append(f"  Period:       {trades[0]['time']} → {trades[-1]['close_time']}")
    total_pnl = sum(t["profit"] + t["commission"] + t["swap"] for t in trades)
    lines.append(f"  Realised P&L: ${total_pnl:>12,.2f}")
    lines.append("")

    wins = [b for b in baskets if b["pnl"] > 0]
    losses = [b for b in baskets if b["pnl"] <= 0]
    gw = sum(b["pnl"] for b in wins)
    gl = sum(b["pnl"] for b in losses)
    pf = abs(gw / gl) if gl else float("inf")

    lines.append("=" * 70)
    lines.append("BASKET STATS (original, no SL)")
    lines.append("=" * 70)
    lines.append(f"  Baskets:       {len(baskets)}")
    if baskets:
        lines.append(f"  Winners:       {len(wins)} ({len(wins) / len(baskets) * 100:.1f}%)")
        lines.append(f"  Losers:        {len(losses)}")
        lines.append(f"  Profit factor: {_fmt_pf(pf)}")
        if wins:
            lines.append(f"  Avg winner:    ${gw / len(wins):,.2f}")
        if losses:
            lines.append(f"  Avg loser:     ${gl / len(losses):,.2f}")
        sizes = [b["count"] for b in baskets]
        durs = [(b["close_ts"] - b["first_ts"]) / 3600 for b in baskets]
        lines.append(f"  Basket sizes:  avg {sum(sizes) / len(sizes):.1f} / max {max(sizes)}")
        lines.append(f"  Duration:      avg {sum(durs) / len(durs):.1f}h / max {max(durs):.1f}h")
    lines.append("")

    if curves:
        first_ts = trades[0]["ts"] if trades else curves[0]["ts"]
        stats = equity_stats(curves, first_ts)
        if stats:
            lines.append("=" * 70)
            lines.append("EQUITY CURVE (original, no SL)")
            lines.append("=" * 70)
            lines.append(f"  Peak equity:   ${stats['peak']:>12,.2f}")
            lines.append(f"  Low equity:    ${stats['low']:>12,.2f}")
            lines.append(f"  Max equity DD: ${stats['max_dd']:>12,.2f}")
            lines.append(f"  Final balance: ${stats['final_bal']:>12,.2f}")
    return lines


def build_mae_text(baskets: List[Dict], bars: List[Dict], bar_ts: List[int],
                    pip_size: float) -> List[str]:
    lines = []
    if not baskets or not bars:
        return lines

    maes = []
    for b in baskets:
        si = bisect.bisect_left(bar_ts, b["first_ts"])
        ei = min(bisect.bisect_left(bar_ts, b["close_ts"] + 60), len(bars))
        max_adv = 0.0
        for i in range(si, ei):
            if bar_ts[i] > b["close_ts"]:
                break
            if b["direction"] == "buy":
                adv = (b["first_price"] - bars[i]["l"]) / pip_size
            else:
                adv = (bars[i]["h"] - b["first_price"]) / pip_size
            if adv > max_adv:
                max_adv = adv
        maes.append(max_adv)

    if not maes:
        return lines
    maes.sort()
    n = len(maes)
    lines.append("")
    lines.append("=" * 70)
    lines.append("MAE (pips adverse from first entry)")
    lines.append("=" * 70)
    lines.append(f"  Avg:    {sum(maes) / n:>6.1f}")
    lines.append(f"  Median: {maes[n // 2]:>6.1f}")
    lines.append(f"  P75:    {maes[int(n * 0.75)]:>6.1f}")
    lines.append(f"  P90:    {maes[int(n * 0.90)]:>6.1f}")
    lines.append(f"  P95:    {maes[int(n * 0.95)]:>6.1f}")
    lines.append(f"  Max:    {maes[-1]:>6.1f}")
    return lines


def _format_scan_row(sl: int, r: Dict) -> str:
    return (
        f"  {sl:>3}p {r['wins']:>5} {r['losses']:>5} "
        f"{r['tp']:>5} {r['sl_exits']:>5} {r['eod_exits']:>5} "
        f"{_fmt_pf(r['pf']):>7} ${r['net']:>8.2f} ${r['eq_dd']:>8.2f} "
        f"{_fmt_retdd(r['ret_dd']):>8}"
    )


def build_spread_profile(ticks: List[Dict], broker_gmt: int,
                          pip_size: float) -> Dict[int, float]:
    """Return {hour: median_spread_pips} from tick data."""
    tz_ = timezone(timedelta(hours=broker_gmt))
    by_hour: Dict[int, List[float]] = {h: [] for h in range(24)}

    sample_every = max(1, len(ticks) // 200000)
    for i in range(0, len(ticks), sample_every):
        t = ticks[i]
        h = datetime.fromtimestamp(t["ts"], tz=tz_).hour
        sp = (t["ask"] - t["bid"]) / pip_size
        if sp >= 0:
            by_hour[h].append(sp)

    profile: Dict[int, float] = {}
    for h in range(24):
        if by_hour[h]:
            spr = sorted(by_hour[h])
            profile[h] = spr[len(spr) // 2]
    return profile


def save_spread_profile(profile: Dict[int, float], symbol: str, source: str,
                          out_path: str) -> None:
    """Save spread profile as a human-readable JSON file."""
    data = {
        "symbol": symbol,
        "source": source,
        "median_spread_pips_by_hour": {str(h): round(profile[h], 3)
                                         for h in sorted(profile)},
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def load_spread_profile(path: str) -> Dict[int, float]:
    """Load spread profile from JSON, returning {hour: median_spread_pips}."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    spreads = data.get("median_spread_pips_by_hour", {})
    return {int(h): float(v) for h, v in spreads.items()}


def build_hourly_breakdown_text(baskets: List[Dict], ticks: List[Dict],
                                  broker_gmt: int, pip_size: float) -> List[str]:
    """Hourly breakdown of basket activity and (if ticks available) spreads.

    For each broker-local hour shows: baskets opened in that hour, wins,
    win rate, net profit, and max drawdown of those baskets when replayed
    in their original order. If tick data is provided, also shows spread
    statistics (min, median, max) observed during each hour across the
    entire tick window.
    """
    tz_ = timezone(timedelta(hours=broker_gmt))

    # Hourly basket stats
    hours: Dict[int, Dict] = {
        h: {'count': 0, 'wins': 0, 'net': 0.0, 'pnls': []}
        for h in range(24)
    }
    for b in baskets:
        h = datetime.fromtimestamp(b["first_ts"], tz=tz_).hour
        hours[h]['count'] += 1
        if b["pnl"] > 0:
            hours[h]['wins'] += 1
        hours[h]['net'] += b["pnl"]
        hours[h]['pnls'].append(b["pnl"])

    # Max drawdown of sequentially-ordered baskets opened in that hour
    for h in range(24):
        bal = peak = mdd = 0.0
        for p in hours[h]['pnls']:
            bal += p
            if bal > peak:
                peak = bal
            if peak - bal > mdd:
                mdd = peak - bal
        hours[h]['mdd'] = mdd

    # Spread per hour from ticks (sampled to avoid huge memory use on big files)
    spread_hours: Dict[int, List[float]] = {h: [] for h in range(24)}
    if ticks:
        sample_every = max(1, len(ticks) // 200000)
        for i in range(0, len(ticks), sample_every):
            t = ticks[i]
            h = datetime.fromtimestamp(t["ts"], tz=tz_).hour
            sp = (t["ask"] - t["bid"]) / pip_size
            if sp >= 0:
                spread_hours[h].append(sp)

    lines = []
    lines.append("")
    lines.append("=" * 96)
    lines.append("HOURLY BREAKDOWN — baskets opened each hour (broker-local)")
    lines.append("=" * 96)
    if ticks:
        lines.append("  Spread columns show min/median/max spread in pips during each broker")
        lines.append("  hour across the entire tick-data window.")
    else:
        lines.append("  (Provide --ticks for per-hour spread statistics)")
    lines.append("")

    if ticks:
        header = (f"  {'Hour':>5} {'Baskets':>9} {'Won':>5} {'Win%':>7} "
                  f"{'Net':>10} {'MaxDD':>10} {'Spr min':>9} {'Spr med':>9} {'Spr max':>9}")
    else:
        header = (f"  {'Hour':>5} {'Baskets':>9} {'Won':>5} {'Win%':>7} "
                  f"{'Net':>10} {'MaxDD':>10}")
    lines.append(header)
    lines.append(f"  {'-' * (len(header) - 2)}")

    for h in range(24):
        s = hours[h]
        has_spread = bool(ticks) and len(spread_hours[h]) > 0
        if s['count'] == 0 and not has_spread:
            continue

        wr = s['wins'] / s['count'] * 100 if s['count'] > 0 else 0
        row = (f"  {h:02d}:00 {s['count']:>9} {s['wins']:>5} {wr:>6.1f}% "
               f"${s['net']:>8.2f} ${s['mdd']:>8.2f}")

        if ticks:
            if has_spread:
                spr = sorted(spread_hours[h])
                row += (f" {spr[0]:>9.2f} {spr[len(spr) // 2]:>9.2f} "
                        f"{spr[-1]:>9.2f}")
            else:
                row += f" {'—':>9} {'—':>9} {'—':>9}"
        lines.append(row)

    return lines


def build_sl_scan_text(baskets: List[Dict], bars: List[Dict], bar_ts: List[int],
                        sl_min: int, sl_max: int, broker_gmt: int,
                        pip_size: float, balance_ops: List[Dict],
                        eod_hour: int = 23, eod_minute: int = 59,
                        spread_profile: Optional[Dict[int, float]] = None,
                        spread_source: str = "",
                        engine: str = "bar",
                        ticks: Optional[List[Dict]] = None,
                        tick_ts: Optional[List[float]] = None) -> List[str]:
    lines = []
    lines.append("")
    lines.append("=" * 84)
    if engine == "tick":
        lines.append("SL SCAN — tick-precision, both EOD modes")
    elif spread_profile:
        lines.append("SL SCAN — bar data WITH spread model, both EOD modes")
    else:
        lines.append("SL SCAN — bar data (no spread model), both EOD modes")
    lines.append("=" * 84)
    lines.append("")
    if engine == "tick":
        lines.append("  Tick-precision engine: SL triggers when bid (buy) or ask (sell)")
        lines.append("  reaches the SL price. Baskets outside tick coverage fall back to bars.")
        lines.append("")
    elif spread_profile:
        lines.append(f"  Spread model: per-hour median spreads {spread_source}")
        lines.append("  Effective SL is adjusted toward entry by half the hour's median")
        lines.append("  spread, approximating the real bid/ask trigger rule.")
        lines.append("")
    lines.append("  Won / Lost  = basket outcome (P&L positive or not)")
    lines.append("  TP / SL / EOD = exit reason counts (how the basket closed)")
    lines.append("                  Won+Lost = TP+SL+EOD = Total baskets")
    lines.append("  EqDD        = max equity drawdown (including floating losses)")
    lines.append("  Ret/DD      = net profit / max equity drawdown")
    lines.append("")

    header = (f"  {'SL':>4} {'Won':>5} {'Lost':>5} {'TP':>5} {'SL':>5} {'EOD':>5} "
              f"{'PF':>7} {'Net':>9} {'EqDD':>9} {'Ret/DD':>8}")

    def _run_sim(sl: int, use_eod: bool) -> Dict:
        if engine == "tick" and ticks is not None and tick_ts is not None:
            return simulate_sl_full_ticks(
                baskets, bars, bar_ts, ticks, tick_ts, sl, use_eod,
                broker_gmt, pip_size, balance_ops, eod_hour, eod_minute
            )
        return simulate_sl_full(
            baskets, bars, bar_ts, sl, use_eod, broker_gmt, pip_size,
            balance_ops, eod_hour, eod_minute, spread_profile
        )

    # No EOD
    lines.append("  ── WITHOUT end-of-day close " + "─" * 52)
    lines.append(header)
    lines.append(f"  {'-' * 80}")
    for sl in range(sl_min, sl_max + 1):
        r = _run_sim(sl, False)
        lines.append(_format_scan_row(sl, r))

    lines.append("")

    # With EOD
    lines.append("  ── WITH end-of-day close " + "─" * 55)
    lines.append(header)
    lines.append(f"  {'-' * 80}")
    for sl in range(sl_min, sl_max + 1):
        r = _run_sim(sl, True)
        lines.append(_format_scan_row(sl, r))

    return lines


def build_tick_text(baskets: List[Dict], bars: List[Dict], bar_ts: List[int],
                     ticks: List[Dict], tick_ts: List[float],
                     sl_min: int, sl_max: int, broker_gmt: int,
                     pip_size: float, eod_hour: int = 23,
                     eod_minute: int = 59) -> List[str]:
    lines = []
    if not ticks:
        return lines

    tick_start = ticks[0]["ts"]
    tick_end = ticks[-1]["ts"]
    covered = [b for b in baskets
               if b["first_ts"] >= tick_start and b["close_ts"] <= tick_end + 60]

    lines.append("")
    lines.append("=" * 84)
    lines.append(f"TICK COMPARISON — {len(covered)} baskets in tick data window")
    lines.append("=" * 84)
    if not covered:
        lines.append("  No baskets within tick data coverage period.")
        return lines

    lines.append("")
    lines.append("  Same SL simulation using tick-level ask/bid data. 'Spread kills' =")
    lines.append("  stops where the mid-price didn't reach the SL but the spread did.")
    lines.append("")

    header = (f"  {'SL':>4} {'Bar Net':>10} {'Bar Stops':>11} "
              f"{'Tick Net':>10} {'Tick Stops':>12} {'Spread Kills':>14}")

    # No EOD
    lines.append("  ── WITHOUT end-of-day close " + "─" * 52)
    lines.append(header)
    lines.append(f"  {'-' * 76}")
    for sl in range(sl_min, sl_max + 1):
        bar_r = simulate_sl_full(covered, bars, bar_ts, sl, False,
                                   broker_gmt, pip_size, [],
                                   eod_hour, eod_minute)
        tick_r = simulate_sl_ticks(covered, ticks, tick_ts, sl, False,
                                     broker_gmt, pip_size, eod_hour, eod_minute)
        lines.append(
            f"  {sl:>3}p ${bar_r['net']:>8.2f} {bar_r['sl_exits']:>11} "
            f"${tick_r['net']:>8.2f} {tick_r['stops']:>12} {tick_r['spread_kills']:>14}"
        )

    lines.append("")

    # With EOD
    lines.append("  ── WITH end-of-day close " + "─" * 55)
    lines.append(header)
    lines.append(f"  {'-' * 76}")
    for sl in range(sl_min, sl_max + 1):
        bar_r = simulate_sl_full(covered, bars, bar_ts, sl, True,
                                   broker_gmt, pip_size, [],
                                   eod_hour, eod_minute)
        tick_r = simulate_sl_ticks(covered, ticks, tick_ts, sl, True,
                                     broker_gmt, pip_size, eod_hour, eod_minute)
        lines.append(
            f"  {sl:>3}p ${bar_r['net']:>8.2f} {bar_r['sl_exits']:>11} "
            f"${tick_r['net']:>8.2f} {tick_r['stops']:>12} {tick_r['spread_kills']:>14}"
        )

    return lines


# ────────────────────────────────────────────────────────────────────────────
# HTML report (chart + embedded text tables)
# ────────────────────────────────────────────────────────────────────────────
def _text_to_html_block(lines: List[str]) -> str:
    if not lines:
        return ""
    text = "\n".join(lines)
    return ('<pre style="font-family: Menlo, Consolas, monospace; font-size: 12px; '
            'background: #f8f8f8; padding: 16px; border-radius: 6px; '
            'white-space: pre; overflow-x: auto; border: 1px solid #e0e0e0;">' +
            html_lib.escape(text) + "</pre>")


def curves_to_daily(curves: List[Dict], first_trade_ts: int
                    ) -> Tuple[List[str], List[float], List[float]]:
    """Convert sampled curve points into (dates, balance, equity) lists
    with one entry per calendar day (last sample of the day wins)."""
    by_day: Dict[str, Dict] = {}
    for p in curves:
        if p["ts"] < first_trade_ts:
            continue
        day = datetime.fromtimestamp(p["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[day] = p
    labels = sorted(by_day.keys())
    bal_data = [by_day[d]["bal"] for d in labels]
    eq_data = [by_day[d]["eq"] for d in labels]
    return labels, bal_data, eq_data


def export_curve_json(out_path: str, symbol: str, sl_pips: int, use_eod: bool,
                       eod_time: str, open_hours: Optional[List[int]],
                       lot_size: Optional[float],
                       summary_stats: Dict, labels: List[str],
                       balance: List[float], equity: List[float]) -> None:
    """Save curve data for later combining with other pairs."""
    data = {
        "symbol": symbol,
        "sl_pips": sl_pips,
        "use_eod": use_eod,
        "eod_time": eod_time,
        "open_hours": open_hours,
        "lot_size": lot_size,
        "summary": summary_stats,
        "daily": [
            {"date": labels[i], "bal": balance[i], "eq": equity[i]}
            for i in range(len(labels))
        ],
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def build_final_check_text(symbol: str, sl_pips: int, use_eod: bool,
                             eod_time: str, open_hours: Optional[List[int]],
                             lot_size: Optional[float],
                             outcomes: List[Dict], tick_verified: int,
                             bar_fallback: int, eq_stats: Dict) -> List[str]:
    """Text summary for a single final-check simulation."""
    lines = []
    total = len(outcomes)
    won = sum(1 for o in outcomes if o["won"])
    lost = total - won
    tp = sum(1 for o in outcomes if o["outcome"] == "TP")
    sl_ex = sum(1 for o in outcomes if o["outcome"] == "SL")
    eod_ex = sum(1 for o in outcomes if o["outcome"] == "EOD")
    gw = sum(o["pnl"] for o in outcomes if o["won"])
    gl = sum(o["pnl"] for o in outcomes if not o["won"])
    net = gw + gl
    pf = abs(gw / gl) if gl else float("inf")

    lines.append("")
    lines.append("=" * 70)
    lines.append(f"FINAL TICK CHECK — {symbol}")
    lines.append("=" * 70)
    lines.append(f"  Settings:")
    lines.append(f"    Basket SL:    {sl_pips} pips")
    lines.append(f"    EOD close:    {'ON at ' + eod_time if use_eod else 'OFF'}")
    if open_hours:
        lines.append(f"    Open hours:   {open_hours[0]:02d}:00 – {open_hours[1]:02d}:00 broker-local")
    else:
        lines.append(f"    Open hours:   any")
    if lot_size is not None:
        lines.append(f"    Lot filter:   only {lot_size:g} lot positions")
    lines.append("")
    lines.append(f"  Tick coverage:  {tick_verified}/{tick_verified + bar_fallback} baskets")
    if bar_fallback:
        lines.append(f"    ({bar_fallback} baskets used bar fallback — outside tick window)")
    lines.append("")
    lines.append(f"  Baskets:        {total}")
    lines.append(f"    Won:          {won} ({won / total * 100:.1f}%)" if total else "")
    lines.append(f"    Lost:         {lost}")
    lines.append(f"    TP exits:     {tp}")
    lines.append(f"    SL exits:     {sl_ex}")
    lines.append(f"    EOD exits:    {eod_ex}")
    lines.append("")
    lines.append(f"  Profit factor:  {_fmt_pf(pf)}")
    lines.append(f"  Net profit:     ${net:,.2f}")
    lines.append("")
    if eq_stats:
        lines.append(f"  Peak equity:    ${eq_stats.get('peak', 0):,.2f}")
        lines.append(f"  Low equity:     ${eq_stats.get('low', 0):,.2f}")
        lines.append(f"  Max equity DD:  ${eq_stats.get('max_dd', 0):,.2f}")
        lines.append(f"  Final balance:  ${eq_stats.get('final_bal', 0):,.2f}")
        if eq_stats.get('max_dd', 0) > 0:
            lines.append(f"  Net / Eq DD:    {net / eq_stats['max_dd']:.2f}")
    return lines


def combine_reports(json_paths: List[str], out_path: str,
                     title: str = "Combined Portfolio") -> None:
    """Load multiple curve JSON files and produce a combined HTML report
    with correlation matrix and combined equity drawdown."""
    reports = []
    for p in json_paths:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["_path"] = p
        reports.append(data)

    # Union of all dates
    all_dates = sorted({d["date"] for r in reports for d in r["daily"]})

    # Align each report with carry-forward
    aligned: List[Dict] = []
    for r in reports:
        by_date = {d["date"]: d for d in r["daily"]}
        bal: List[float] = []
        eq: List[float] = []
        last_bal = 0.0
        last_eq = 0.0
        started = False
        for date in all_dates:
            if date in by_date:
                last_bal = by_date[date]["bal"]
                last_eq = by_date[date]["eq"]
                started = True
            bal.append(last_bal if started else 0.0)
            eq.append(last_eq if started else 0.0)
        aligned.append({
            "symbol": r.get("symbol", "?"),
            "bal": bal,
            "eq": eq,
            "sl_pips": r.get("sl_pips"),
            "use_eod": r.get("use_eod"),
            "lot_size": r.get("lot_size"),
            "summary": r.get("summary", {}),
        })

    # Combined sums
    n = len(all_dates)
    comb_bal = [sum(a["bal"][i] for a in aligned) for i in range(n)]
    comb_eq = [sum(a["eq"][i] for a in aligned) for i in range(n)]

    # Combined equity stats
    comb_peak = 0.0
    comb_max_dd = 0.0
    for v in comb_eq:
        if v > comb_peak:
            comb_peak = v
        dd = comb_peak - v
        if dd > comb_max_dd:
            comb_max_dd = dd
    comb_final = comb_bal[-1] if comb_bal else 0.0
    sum_individual_dd = sum(a["summary"].get("max_dd", 0) for a in aligned)

    # Pearson correlation of daily equity changes
    def pearson(a: List[float], b: List[float]) -> float:
        if len(a) < 2 or len(a) != len(b):
            return 0.0
        ma = sum(a) / len(a)
        mb = sum(b) / len(b)
        num = sum((a[i] - ma) * (b[i] - mb) for i in range(len(a)))
        da = (sum((a[i] - ma) ** 2 for i in range(len(a)))) ** 0.5
        db = (sum((b[i] - mb) ** 2 for i in range(len(b)))) ** 0.5
        return num / (da * db) if da * db > 0 else 0.0

    deltas = []
    for a in aligned:
        d = [a["eq"][i] - a["eq"][i - 1] for i in range(1, len(a["eq"]))]
        deltas.append(d)

    k = len(aligned)
    corr = [[pearson(deltas[i], deltas[j]) for j in range(k)] for i in range(k)]

    # Build text summary
    text: List[str] = []
    text.append("=" * 70)
    text.append("COMBINED PORTFOLIO")
    text.append("=" * 70)
    text.append("")
    text.append("  Pairs:")
    for a in aligned:
        eod_str = "EOD on" if a["use_eod"] else "EOD off"
        lot_str = f"lots={a['lot_size']:g}" if a.get("lot_size") else "all lots"
        sl_str = "no SL" if a.get("sl_pips") is None else f"SL={a['sl_pips']}p"
        text.append(f"    {a['symbol']:<12} {sl_str}  {eod_str}  {lot_str}  "
                    f"final=${a['summary'].get('final_bal', 0):,.2f}  "
                    f"peak=${a['summary'].get('peak', 0):,.2f}  "
                    f"maxDD=${a['summary'].get('max_dd', 0):,.2f}")
    text.append("")
    text.append(f"  Combined final balance:  ${comb_final:,.2f}")
    text.append(f"  Combined peak equity:    ${comb_peak:,.2f}")
    text.append(f"  Combined max equity DD:  ${comb_max_dd:,.2f}")
    text.append(f"  Sum of individual DDs:   ${sum_individual_dd:,.2f}")
    if sum_individual_dd > 0:
        diversification = (1 - comb_max_dd / sum_individual_dd) * 100
        text.append(f"  Diversification benefit: {diversification:.1f}% "
                    f"(combined DD vs. sum of individuals)")
    text.append("")
    text.append("  Daily-equity-change correlation matrix:")
    header = "              " + "  ".join(f"{a['symbol'][:8]:>8}" for a in aligned)
    text.append(header)
    for i, ai in enumerate(aligned):
        row = f"    {ai['symbol'][:10]:<10}" + "  ".join(
            f"{corr[i][j]:>+8.3f}" for j in range(k)
        )
        text.append(row)

    # Build HTML with multi-series chart
    colors = ["#378ADD", "#1D9E75", "#D85A30", "#9B4DCA", "#E8A33D",
              "#37B5C5", "#D85A90", "#5F4BB6"]
    datasets_js = []
    for i, a in enumerate(aligned):
        col = colors[i % len(colors)]
        datasets_js.append(
            f"{{ label: {json.dumps(a['symbol'] + ' equity')}, "
            f"data: {json.dumps(a['eq'])}, borderColor: '{col}', "
            f"backgroundColor: 'transparent', fill: false, borderWidth: 1.5, "
            f"pointRadius: 0, tension: 0.2 }}"
        )
    # Combined line on top
    datasets_js.append(
        f"{{ label: 'Combined equity', data: {json.dumps(comb_eq)}, "
        f"borderColor: '#000', backgroundColor: 'rgba(0,0,0,0.05)', "
        f"fill: true, borderWidth: 2.5, pointRadius: 0, tension: 0.2 }}"
    )
    datasets_str = "[" + ",".join(datasets_js) + "]"

    text_html = _text_to_html_block(text)

    html_out = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html_lib.escape(title)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f7f7f7; color: #222; }}
  .container {{ max-width: 1300px; margin: auto; background: white; padding: 24px;
                border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  .chart-box {{ position: relative; height: 520px; margin-bottom: 24px; }}
</style></head><body><div class="container">
<h1>{html_lib.escape(title)}</h1>
<div class="chart-box"><canvas id="c"></canvas></div>
{text_html}
<script>
const labels = {json.dumps(all_dates)};
new Chart(document.getElementById('c'), {{
  type: 'line',
  data: {{ labels, datasets: {datasets_str} }},
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
</script></div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)


def compute_stats(trades: List[Dict], baskets: List[Dict],
                   curves: List[Dict]) -> Dict:
    """Return a dict of basket/trade/equity statistics for comparison."""
    w = [b for b in baskets if b["pnl"] > 0]
    l = [b for b in baskets if b["pnl"] <= 0]
    gw = sum(b["pnl"] for b in w)
    gl = sum(b["pnl"] for b in l)
    pf = abs(gw / gl) if gl else float("inf")

    # Trade-level breakdown (individual positions, not baskets)
    # Use profit+commission+swap to match basket-level totals
    trade_net_values = [(t["profit"] + t["commission"] + t["swap"]) for t in trades]
    trade_wins = [t for t, n in zip(trades, trade_net_values) if n > 0]
    trade_losses = [t for t, n in zip(trades, trade_net_values) if n < 0]
    trade_gw = sum(n for n in trade_net_values if n > 0)
    trade_gl = sum(n for n in trade_net_values if n < 0)
    trade_pf = abs(trade_gw / trade_gl) if trade_gl else float("inf")

    sizes = [b["count"] for b in baskets] if baskets else [0]
    durs = [(b["close_ts"] - b["first_ts"]) / 3600 for b in baskets] if baskets else [0]

    first_ts = trades[0]["ts"] if trades else (curves[0]["ts"] if curves else 0)
    eq = equity_stats(curves, first_ts)

    return {
        "trades": len(trades),
        "trade_wins": len(trade_wins),
        "trade_losses": len(trade_losses),
        "trade_win_rate": len(trade_wins) / len(trades) * 100 if trades else 0,
        "trade_pf": trade_pf,
        "trade_gross_win": trade_gw,
        "trade_gross_loss": trade_gl,
        "trade_net": trade_gw + trade_gl,
        "trade_avg_winner": trade_gw / len(trade_wins) if trade_wins else 0,
        "trade_avg_loser": trade_gl / len(trade_losses) if trade_losses else 0,
        "baskets": len(baskets),
        "wins": len(w),
        "losses": len(l),
        "win_rate": len(w) / len(baskets) * 100 if baskets else 0,
        "pf": pf,
        "net": gw + gl,
        "gross_win": gw,
        "gross_loss": gl,
        "avg_winner": gw / len(w) if w else 0,
        "avg_loser": gl / len(l) if l else 0,
        "avg_size": sum(sizes) / len(sizes),
        "max_size": max(sizes),
        "avg_duration_hrs": sum(durs) / len(durs),
        "max_duration_hrs": max(durs),
        "peak_equity": eq.get("peak", 0),
        "low_equity": eq.get("low", 0),
        "max_eq_dd": eq.get("max_dd", 0),
        "final_balance": eq.get("final_bal", 0),
        "period_start": trades[0]["time"] if trades else "",
        "period_end": trades[-1]["close_time"] if trades else "",
    }


def build_single_stats_text(stats: Dict, label: str = "STRATEGY") -> List[str]:
    """Single-column stats summary using the same section layout as the
    live-vs-backtest comparison. Used in --stats-only mode to skip SL
    scanning entirely and just report what the trades look like."""
    lines = []
    lines.append("")
    lines.append("=" * 84)
    lines.append(f"{label.upper()} STATS SUMMARY")
    lines.append("=" * 84)
    lines.append("")
    lines.append(f"  {'Metric':<28} {'VALUE':>20}")
    lines.append(f"  {'-' * 50}")

    def _fmt(v, kind="num"):
        if kind == "money":
            return f"${v:,.2f}"
        if kind == "pct":
            return f"{v:.1f}%"
        if kind == "pf":
            return "inf" if v == float("inf") else f"{v:.2f}"
        if kind == "hours":
            return f"{v:.1f}h"
        if kind == "float":
            return f"{v:.2f}"
        return f"{v}"

    def _row(label, key, kind="num"):
        lines.append(f"  {label:<28} {_fmt(stats[key], kind):>20}")

    lines.append(f"  {'Period start':<28} {stats['period_start'][:16]:>20}")
    lines.append(f"  {'Period end':<28} {stats['period_end'][:16]:>20}")
    lines.append("")
    lines.append("  ── Trade-level (individual positions) ─────────────────")
    _row("Total trades", "trades")
    _row("Winning trades", "trade_wins")
    _row("Losing trades", "trade_losses")
    _row("Trade win rate", "trade_win_rate", "pct")
    _row("Profit factor", "trade_pf", "pf")
    _row("Gross profit", "trade_gross_win", "money")
    _row("Gross loss", "trade_gross_loss", "money")
    _row("Net profit", "trade_net", "money")
    _row("Avg winner", "trade_avg_winner", "money")
    _row("Avg loser", "trade_avg_loser", "money")
    lines.append("")
    lines.append("  ── Basket-level (grouped by close-time clustering) ────")
    _row("Baskets", "baskets")
    _row("Winning baskets", "wins")
    _row("Losing baskets", "losses")
    _row("Basket win rate", "win_rate", "pct")
    _row("Basket PF", "pf", "pf")
    _row("Basket net", "net", "money")
    _row("Avg basket size", "avg_size", "float")
    _row("Max basket size", "max_size")
    _row("Avg duration", "avg_duration_hrs", "hours")
    _row("Max duration", "max_duration_hrs", "hours")
    lines.append("")
    lines.append("  ── Equity curve ───────────────────────────────────────")
    _row("Peak equity", "peak_equity", "money")
    _row("Low equity", "low_equity", "money")
    _row("Max equity DD", "max_eq_dd", "money")
    _row("Final balance", "final_balance", "money")

    return lines


def build_comparison_text(live_stats: Dict, bt_stats: Dict) -> List[str]:
    """Side-by-side stat comparison of live vs backtest."""
    lines = []
    lines.append("")
    lines.append("=" * 84)
    lines.append("LIVE vs BACKTEST COMPARISON")
    lines.append("=" * 84)
    lines.append("")
    lines.append(f"  {'Metric':<24} {'LIVE':>18} {'BACKTEST':>18} {'Diff':>14}")
    lines.append(f"  {'-' * 78}")

    def _fmt(v, kind="num"):
        if kind == "money":
            return f"${v:,.2f}"
        if kind == "pct":
            return f"{v:.1f}%"
        if kind == "pf":
            return "inf" if v == float("inf") else f"{v:.2f}"
        if kind == "hours":
            return f"{v:.1f}h"
        if kind == "float":
            return f"{v:.2f}"
        return f"{v}"

    def _diff(a, b, kind="num"):
        if kind in ("pf",) and (a == float("inf") or b == float("inf")):
            return "—"
        d = a - b
        if kind == "money":
            return f"${d:+,.2f}"
        if kind == "pct":
            return f"{d:+.1f}%"
        if kind == "hours":
            return f"{d:+.1f}h"
        if kind == "float":
            return f"{d:+.2f}"
        if isinstance(d, float):
            return f"{d:+.2f}"
        return f"{d:+d}"

    def _row(label, key, kind="num"):
        a, b = live_stats[key], bt_stats[key]
        lines.append(
            f"  {label:<24} {_fmt(a, kind):>18} {_fmt(b, kind):>18} {_diff(a, b, kind):>14}"
        )

    lines.append(f"  {'Period (live)':<24} {live_stats['period_start'][:16]:>18}")
    lines.append(f"  {'Period (bt)':<24} {bt_stats['period_start'][:16]:>18}")
    lines.append("")
    lines.append("  ── Trade-level (individual positions) ─────────────────────────────────────")
    _row("Total trades", "trades")
    _row("Winning trades", "trade_wins")
    _row("Losing trades", "trade_losses")
    _row("Trade win rate", "trade_win_rate", "pct")
    _row("Profit factor", "trade_pf", "pf")
    _row("Gross profit", "trade_gross_win", "money")
    _row("Gross loss", "trade_gross_loss", "money")
    _row("Net profit", "trade_net", "money")
    _row("Avg winner", "trade_avg_winner", "money")
    _row("Avg loser", "trade_avg_loser", "money")
    lines.append("")
    lines.append("  ── Basket-level (grouped by close-time clustering) ────────────────────────")
    _row("Baskets", "baskets")
    _row("Winning baskets", "wins")
    _row("Losing baskets", "losses")
    _row("Basket win rate", "win_rate", "pct")
    _row("Basket PF", "pf", "pf")
    _row("Basket net", "net", "money")
    _row("Avg basket size", "avg_size", "float")
    _row("Max basket size", "max_size")
    _row("Avg duration", "avg_duration_hrs", "hours")
    _row("Max duration", "max_duration_hrs", "hours")
    lines.append("")
    lines.append("  ── Equity curve ────────────────────────────────────────────────────────────")
    _row("Peak equity", "peak_equity", "money")
    _row("Low equity", "low_equity", "money")
    _row("Max equity DD", "max_eq_dd", "money")
    _row("Final balance", "final_balance", "money")

    # Explanatory note if basket WR differs a lot
    if bt_stats["losses"] == 0 and live_stats["losses"] > 0:
        lines.append("")
        lines.append("  NOTE: The backtest shows 0 losing baskets because it runs the pure")
        lines.append("  strategy without any basket stop-loss. Every basket eventually hits")
        lines.append("  its take-profit target. The live account has basket SL applied, so")
        lines.append("  some baskets get cut short at a loss. The trade-level profit factor")
        lines.append("  and gross win/loss numbers above are the most meaningful for direct")
        lines.append("  comparison since they reflect individual position outcomes.")

    # Match assessment
    lines.append("")
    lines.append("  Match assessment:")
    net_diff = abs(live_stats["net"] - bt_stats["net"])
    net_ref = max(abs(live_stats["net"]), abs(bt_stats["net"]), 1)
    net_match = 100 * (1 - min(net_diff / net_ref, 1))

    pf_diff_pct = 100 * abs(live_stats["pf"] - bt_stats["pf"]) / max(bt_stats["pf"], 1) \
        if bt_stats["pf"] != float("inf") and live_stats["pf"] != float("inf") else None

    lines.append(f"    Net profit match:   {net_match:.1f}% (diff ${net_diff:.2f})")
    if pf_diff_pct is not None:
        lines.append(f"    Profit factor gap:  {pf_diff_pct:.1f}%")
    lines.append(f"    Basket-count gap:   {abs(live_stats['baskets'] - bt_stats['baskets'])} "
                 f"({abs(live_stats['baskets'] - bt_stats['baskets']) / max(bt_stats['baskets'], 1) * 100:.0f}%)")

    if abs(live_stats["max_eq_dd"] - bt_stats["max_eq_dd"]) > max(bt_stats["max_eq_dd"] * 0.5, 10):
        lines.append(f"    ⚠ Max equity DD differs significantly — review the equity curves.")

    return lines


def write_comparison_html_report(
        live_curves: List[Dict], live_first_ts: int,
        bt_curves: List[Dict], bt_first_ts: int,
        out_path: str, title: str,
        text_sections: List[List[str]]) -> None:
    """HTML report with live and backtest equity+balance curves overlaid."""
    live_labels, live_bal, live_eq = curves_to_daily(live_curves, live_first_ts)
    bt_labels, bt_bal, bt_eq = curves_to_daily(bt_curves, bt_first_ts)

    # Unified date axis
    all_dates = sorted(set(live_labels) | set(bt_labels))

    def align(source_labels, source_vals):
        by_date = dict(zip(source_labels, source_vals))
        result = []
        last = None
        for d in all_dates:
            if d in by_date:
                last = by_date[d]
            result.append(last)
        return result

    live_bal_aligned = align(live_labels, live_bal)
    live_eq_aligned = align(live_labels, live_eq)
    bt_bal_aligned = align(bt_labels, bt_bal)
    bt_eq_aligned = align(bt_labels, bt_eq)

    text_html = "".join(_text_to_html_block(s) for s in text_sections)

    html_out = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html_lib.escape(title)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f7f7f7; color: #222; }}
  .container {{ max-width: 1300px; margin: auto; background: white; padding: 24px;
                border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  h2 {{ font-size: 15px; margin: 24px 0 8px; color: #555; font-weight: 500; }}
  .chart-box {{ position: relative; height: 380px; margin-bottom: 24px; }}
</style></head><body><div class="container">
<h1>{html_lib.escape(title)}</h1>
<h2>Equity curves (overlay)</h2>
<div class="chart-box"><canvas id="eq_chart"></canvas></div>
<h2>Backtest equity (alone)</h2>
<div class="chart-box"><canvas id="bt_eq_chart"></canvas></div>
<h2>Live equity (alone)</h2>
<div class="chart-box"><canvas id="live_eq_chart"></canvas></div>
<h2>Balance curves (overlay)</h2>
<div class="chart-box"><canvas id="bal_chart"></canvas></div>
{text_html}
<script>
const labels = {json.dumps(all_dates)};
const liveEq = {json.dumps(live_eq_aligned)};
const btEq = {json.dumps(bt_eq_aligned)};
const liveBal = {json.dumps(live_bal_aligned)};
const btBal = {json.dumps(bt_bal_aligned)};

function mkChart(canvasId, datasets) {{
  new Chart(document.getElementById(canvasId), {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ legend: {{ position: 'top' }},
        tooltip: {{ callbacks: {{ label: c => c.dataset.label + ': $' + (c.parsed.y || 0).toLocaleString() }} }} }},
      scales: {{
        x: {{ ticks: {{ maxTicksLimit: 20, maxRotation: 45 }} }},
        y: {{ ticks: {{ callback: v => '$' + v.toLocaleString() }} }}
      }}
    }}
  }});
}}

mkChart('eq_chart', [
  {{ label: 'Live equity', data: liveEq, borderColor: '#378ADD',
     backgroundColor: '#378ADD', fill: false, borderWidth: 2,
     pointRadius: 2.5, pointHoverRadius: 6, tension: 0, spanGaps: true }},
  {{ label: 'Backtest equity', data: btEq, borderColor: '#E89611',
     backgroundColor: '#E89611', fill: false, borderWidth: 2,
     pointRadius: 2.5, pointHoverRadius: 6, tension: 0, spanGaps: true }}
]);
mkChart('bt_eq_chart', [
  {{ label: 'Backtest equity', data: btEq, borderColor: '#E89611',
     backgroundColor: 'rgba(232,150,17,0.1)', fill: true, borderWidth: 2,
     pointRadius: 2.5, pointHoverRadius: 6, tension: 0, spanGaps: true }}
]);
mkChart('live_eq_chart', [
  {{ label: 'Live equity', data: liveEq, borderColor: '#378ADD',
     backgroundColor: 'rgba(55,138,221,0.1)', fill: true, borderWidth: 2,
     pointRadius: 2.5, pointHoverRadius: 6, tension: 0, spanGaps: true }}
]);
mkChart('bal_chart', [
  {{ label: 'Live balance', data: liveBal, borderColor: '#378ADD',
     backgroundColor: '#378ADD', fill: false, borderWidth: 2,
     pointRadius: 2.5, pointHoverRadius: 6, tension: 0, spanGaps: true }},
  {{ label: 'Backtest balance', data: btBal, borderColor: '#E89611',
     backgroundColor: '#E89611', fill: false, borderWidth: 2,
     pointRadius: 2.5, pointHoverRadius: 6, tension: 0, spanGaps: true }}
]);
</script></div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)


def write_html_report(curves: List[Dict], balance_ops: List[Dict],
                       first_trade_ts: int, out_path: str, title: str,
                       text_sections: List[List[str]]) -> None:
    labels, bal_data, eq_data = curves_to_daily(curves, first_trade_ts)

    text_html = "".join(_text_to_html_block(s) for s in text_sections)

    html_out = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html_lib.escape(title)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f7f7f7; color: #222; }}
  .container {{ max-width: 1300px; margin: auto; background: white; padding: 24px;
                border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  .chart-box {{ position: relative; height: 460px; margin-bottom: 24px; }}
</style></head><body><div class="container">
<h1>{html_lib.escape(title)}</h1>
<div class="chart-box"><canvas id="c"></canvas></div>
{text_html}
<script>
const labels = {json.dumps(labels)};
const bal = {json.dumps(bal_data)};
const eq = {json.dumps(eq_data)};
new Chart(document.getElementById('c'), {{
  type: 'line',
  data: {{ labels, datasets: [
    {{ label: 'Balance', data: bal, borderColor: '#378ADD',
       backgroundColor: 'rgba(55,138,221,0.08)', fill: true,
       borderWidth: 2, pointRadius: 0, tension: 0.2 }},
    {{ label: 'Equity', data: eq, borderColor: '#D85A30',
       backgroundColor: 'rgba(216,90,48,0.08)', fill: true,
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
</script></div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)


# ────────────────────────────────────────────────────────────────────────────
# FILTER OPTIMIZATION
# ────────────────────────────────────────────────────────────────────────────

import bisect as _bisect


def precompute_trade_context(trades: List[Dict], ticks: List[Dict],
                              tick_ts: List[float], broker_gmt: int,
                              pip_size: float) -> None:
    """Attach open_spread_pips, open_hour, open_dow to each trade dict.
    Mutates trades in place (called once during setup)."""
    offset = timezone(timedelta(hours=broker_gmt))
    tick_ts_f = [float(t) for t in tick_ts]

    for t in trades:
        dt = datetime.fromtimestamp(t["ts"], tz=offset)
        t["open_hour"] = dt.hour
        t["open_dow"] = dt.weekday()  # 0=Mon, 4=Fri, 6=Sun

        idx = _bisect.bisect_right(tick_ts_f, float(t["ts"])) - 1
        if 0 <= idx < len(ticks):
            t["open_spread_pips"] = round(
                (ticks[idx]["ask"] - ticks[idx]["bid"]) / pip_size, 2
            )
        else:
            t["open_spread_pips"] = None


def tag_trades_with_baskets(trades: List[Dict],
                             baskets: List[Dict]) -> None:
    """Add basket_idx and is_basket_first to each trade.  Mutates in place."""
    trade_to_basket: Dict[int, int] = {}
    basket_first_ts: Dict[int, float] = {}
    for bi, b in enumerate(baskets):
        first_ts = min(tr["ts"] for tr in b["group"])
        basket_first_ts[bi] = first_ts
        for tr in b["group"]:
            trade_to_basket[id(tr)] = bi
    for t in trades:
        bi = trade_to_basket.get(id(t))
        if bi is not None:
            t["basket_idx"] = bi
            t["is_basket_first"] = (t["ts"] == basket_first_ts[bi])
        else:
            t["basket_idx"] = -1
            t["is_basket_first"] = False


def apply_trade_filters(trades: List[Dict], baskets: List[Dict],
                         session_start: Optional[int] = None,
                         session_end: Optional[int] = None,
                         max_spread_initial: Optional[float] = None,
                         max_spread_all: Optional[float] = None,
                         skip_days: Optional[set] = None) -> List[Dict]:
    """Filter trades by session, spread, day-of-week.

    Session/spread_initial/day filters gate on the basket's FIRST
    trade: if the first trade fails, the ENTIRE basket is dropped.
    spread_all filters every individual trade: trades exceeding the
    threshold are dropped even if the basket was allowed to start.

    Returns a new list (no mutation).
    """
    n_baskets = len(baskets)
    basket_allowed = [True] * n_baskets

    for bi, b in enumerate(baskets):
        first = min(b["group"], key=lambda tr: tr["ts"])

        # Session hours
        if session_start is not None and session_end is not None:
            h = first.get("open_hour", 0)
            if session_start <= session_end:
                if not (session_start <= h < session_end):
                    basket_allowed[bi] = False; continue
            else:
                if not (h >= session_start or h < session_end):
                    basket_allowed[bi] = False; continue

        # Day-of-week
        if skip_days and first.get("open_dow", -1) in skip_days:
            basket_allowed[bi] = False; continue

        # Spread on initial trade
        if max_spread_initial is not None:
            sp = first.get("open_spread_pips")
            if sp is not None and sp > max_spread_initial:
                basket_allowed[bi] = False; continue

    filtered: List[Dict] = []
    for t in trades:
        bi = t.get("basket_idx", -1)
        if bi < 0 or bi >= n_baskets or not basket_allowed[bi]:
            continue
        if max_spread_all is not None:
            sp = t.get("open_spread_pips")
            if sp is not None and sp > max_spread_all:
                continue
        filtered.append(t)
    return filtered


def fast_realized_stats(trades: List[Dict]) -> Dict:
    """Net P&L and max balance drawdown from realized trade P&Ls.
    O(N) — no bar data needed."""
    if not trades:
        return {"net": 0.0, "max_dd": 0.0, "trades": 0, "baskets": 0}
    sorted_t = sorted(trades, key=lambda t: t["close_ts"])
    cumul = 0.0; peak = 0.0; max_dd = 0.0
    basket_set: set = set()
    for t in sorted_t:
        cumul += t["profit"] + t["commission"] + t["swap"]
        if cumul > peak: peak = cumul
        dd = peak - cumul
        if dd > max_dd: max_dd = dd
        basket_set.add(t.get("basket_idx", -1))
    return {"net": round(cumul, 2), "max_dd": round(max_dd, 2),
            "trades": len(trades), "baskets": len(basket_set)}


_DAY_FILTER_MAP = {
    "none": set(),
    "no-mon": {0},
    "no-fri": {4},
    "no-mon-fri": {0, 4},
    "no-mon-sun": {0, 6},
    "no-fri-sun": {4, 6},
}


def generate_filter_grid(session_step: int, min_session_width: int,
                          spread_values: List[float],
                          day_options: List[str]) -> List[Dict]:
    """Build the list of filter parameter dicts to test."""
    # Session windows
    session_combos: List[Tuple[Optional[int], Optional[int]]] = [(None, None)]
    for start in range(0, 24, session_step):
        for end in range(start + min_session_width, 25, session_step):
            if end > 24: break
            session_combos.append((start, end))

    # Spread pairs: (initial, all). None = no filter. 0 in input = None.
    nz = sorted(v for v in spread_values if v > 0)
    spread_combos: List[Tuple[Optional[float], Optional[float]]] = [(None, None)]
    for si in nz: spread_combos.append((si, None))
    for sa in nz: spread_combos.append((None, sa))
    for si in nz:
        for sa in nz:
            if sa >= si: spread_combos.append((si, sa))

    day_combos = []
    for d in day_options:
        k = d.strip().lower()
        if k in _DAY_FILTER_MAP: day_combos.append((k, _DAY_FILTER_MAP[k]))
    if not day_combos: day_combos = [("none", set())]

    grid: List[Dict] = []
    for ss, se in session_combos:
        for spr_i, spr_a in spread_combos:
            for day_lbl, day_set in day_combos:
                grid.append({
                    "session_start": ss, "session_end": se,
                    "max_spread_initial": spr_i, "max_spread_all": spr_a,
                    "skip_days": day_set, "day_label": day_lbl,
                })
    return grid


def _fmt_session(s, e):
    return "all" if s is None else f"{s:02d}-{e:02d}h"

def _fmt_spread(v):
    return "—" if v is None else f"{v:.1f}p"


def run_filter_optimization(
        trades: List[Dict], baskets: List[Dict],
        bars: List[Dict], balance_ops: List[Dict],
        grid: List[Dict],
        benchmark_net: float, benchmark_dd: float,
        top_n: int = 20) -> Tuple[List[Dict], Dict]:
    """Run the filter grid search.  Returns (top_results, summary).

    Deduplicates results that produce identical outcomes (same trades,
    net, DD) — keeps the simplest filter combo (fewest active filters)
    so the top-N list shows genuinely different strategies.
    """
    results: List[Dict] = []
    for params in grid:
        filt = apply_trade_filters(
            trades, baskets,
            params["session_start"], params["session_end"],
            params["max_spread_initial"], params["max_spread_all"],
            params["skip_days"],
        )
        stats = fast_realized_stats(filt)
        net = stats["net"]; dd = stats["max_dd"]
        ret_dd = net / dd if dd > 0 else (float("inf") if net > 0 else 0.0)
        # Count how many filters are actually active (for simplicity ranking)
        n_active = 0
        if params["session_start"] is not None: n_active += 1
        if params["max_spread_initial"] is not None: n_active += 1
        if params["max_spread_all"] is not None: n_active += 1
        if params["skip_days"]: n_active += 1
        results.append({**params,
            "net": net, "max_dd": dd, "ret_dd": ret_dd,
            "trades": stats["trades"], "baskets": stats["baskets"],
            "net_pct": 100 * net / benchmark_net if benchmark_net else 0,
            "dd_pct": 100 * dd / benchmark_dd if benchmark_dd else 0,
            "n_active_filters": n_active,
            "filtered_trades": filt,
        })

    # Deduplicate: group by (trades, baskets, net, max_dd) fingerprint.
    # Keep the entry with the fewest active filters (simplest explanation).
    seen: Dict[Tuple, int] = {}
    deduped: List[Dict] = []
    for r in results:
        key = (r["trades"], r["baskets"], r["net"], r["max_dd"])
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append(r)
        else:
            existing_idx = seen[key]
            if r["n_active_filters"] < deduped[existing_idx]["n_active_filters"]:
                deduped[existing_idx] = r

    # Sort by Ret/DD descending, tiebreak by net descending
    deduped.sort(key=lambda r: (-r["ret_dd"], -r["net"]))

    top = deduped[:top_n]
    for r in deduped[top_n:]:
        r.pop("filtered_trades", None)

    summary = {"total_trials": len(grid),
               "unique_outcomes": len(deduped),
               "positive_net": sum(1 for r in deduped if r["net"] > 0),
               "best_ret_dd": deduped[0]["ret_dd"] if deduped else 0}
    return top, summary


def build_filter_results_text(
        top: List[Dict], summary: Dict,
        benchmark_net: float, benchmark_dd: float,
        benchmark_trades: int, benchmark_baskets: int) -> List[str]:
    lines: List[str] = []
    lines.append("")
    lines.append("=" * 110)
    lines.append("FILTER OPTIMIZATION RESULTS")
    lines.append("=" * 110)
    lines.append("")
    bm_retdd = benchmark_net / benchmark_dd if benchmark_dd > 0 else 0
    lines.append(f"  Benchmark (no filters): "
                 f"{benchmark_trades} trades, {benchmark_baskets} baskets, "
                 f"Net ${benchmark_net:,.2f}, Max DD ${benchmark_dd:,.2f}, "
                 f"Ret/DD {bm_retdd:.2f}")
    lines.append(f"  Trials tested: {summary['total_trials']:,}  |  "
                 f"Unique outcomes: {summary['unique_outcomes']:,}  |  "
                 f"Positive net: {summary['positive_net']:,}")
    lines.append("")
    if not top:
        lines.append("  No results to show."); return lines

    lines.append(
        f"  {'Rank':>4}  {'Session':>8}  {'Spr.Init':>8}  {'Spr.All':>8}  "
        f"{'Days':>10}  {'Trades':>7}  {'Bskts':>6}  "
        f"{'Net':>11}  {'Net%':>6}  {'MaxDD':>11}  {'DD%':>6}  {'Ret/DD':>8}")
    lines.append(f"  {'-' * 108}")

    for i, r in enumerate(top, start=1):
        rd = f"{r['ret_dd']:.2f}" if r["ret_dd"] != float("inf") else "inf"
        lines.append(
            f"  {i:>4}  {_fmt_session(r['session_start'], r['session_end']):>8}  "
            f"{_fmt_spread(r['max_spread_initial']):>8}  "
            f"{_fmt_spread(r['max_spread_all']):>8}  "
            f"{r['day_label']:>10}  "
            f"{r['trades']:>7}  {r['baskets']:>6}  "
            f"${r['net']:>9,.2f}  {r['net_pct']:>5.0f}%  "
            f"${r['max_dd']:>9,.2f}  {r['dd_pct']:>5.0f}%  {rd:>8}")

    lines.append("")
    lines.append("  Net% = % of benchmark net kept.  DD% = % of benchmark max DD.")
    lines.append("  Ranked by Ret/DD descending (highest risk-adjusted return first).")
    return lines


def write_filter_html_report(
        benchmark_curves: List[Dict], benchmark_ts: int,
        top_result_curves: Optional[List[Dict]], top_result_ts: Optional[int],
        out_path: str, title: str,
        text_sections: List[List[str]],
        top_result_label: str = "Best filter") -> None:
    """HTML with benchmark + best-filter equity overlay."""
    bm_labels, bm_bal, bm_eq = curves_to_daily(benchmark_curves, benchmark_ts)
    text_html = "".join(_text_to_html_block(s) for s in text_sections)

    if top_result_curves:
        tr_labels, tr_bal, tr_eq = curves_to_daily(top_result_curves, top_result_ts)
        all_dates = sorted(set(bm_labels) | set(tr_labels))
        def _align(sl, sv):
            d = dict(zip(sl, sv)); o = []; last = None
            for dd in all_dates:
                if dd in d: last = d[dd]
                o.append(last)
            return o
        bm_eq_a = _align(bm_labels, bm_eq);   tr_eq_a = _align(tr_labels, tr_eq)
        bm_bal_a = _align(bm_labels, bm_bal);  tr_bal_a = _align(tr_labels, tr_bal)
        ds = f"""
const labels={json.dumps(all_dates)};
mkChart('eq_chart',[
  {{label:'Benchmark equity',data:{json.dumps(bm_eq_a)},borderColor:'#999',backgroundColor:'#999',fill:false,borderWidth:2,pointRadius:1.5,tension:0,spanGaps:true}},
  {{label:'{top_result_label} equity',data:{json.dumps(tr_eq_a)},borderColor:'#2E9E5A',backgroundColor:'#2E9E5A',fill:false,borderWidth:2.5,pointRadius:2,tension:0,spanGaps:true}}
]);
mkChart('bal_chart',[
  {{label:'Benchmark balance',data:{json.dumps(bm_bal_a)},borderColor:'#999',backgroundColor:'#999',fill:false,borderWidth:2,pointRadius:1.5,tension:0,spanGaps:true}},
  {{label:'{top_result_label} balance',data:{json.dumps(tr_bal_a)},borderColor:'#2E9E5A',backgroundColor:'#2E9E5A',fill:false,borderWidth:2.5,pointRadius:2,tension:0,spanGaps:true}}
]);"""
    else:
        all_dates = bm_labels
        ds = f"""
const labels={json.dumps(bm_labels)};
mkChart('eq_chart',[
  {{label:'Benchmark equity',data:{json.dumps(bm_eq)},borderColor:'#378ADD',backgroundColor:'#378ADD',fill:false,borderWidth:2,pointRadius:1.5,tension:0,spanGaps:true}}
]);
mkChart('bal_chart',[
  {{label:'Benchmark balance',data:{json.dumps(bm_bal)},borderColor:'#378ADD',backgroundColor:'#378ADD',fill:false,borderWidth:2,pointRadius:1.5,tension:0,spanGaps:true}}
]);"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html_lib.escape(title)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  body{{font-family:-apple-system,sans-serif;margin:20px;background:#f7f7f7;color:#222}}
  .container{{max-width:1300px;margin:auto;background:white;padding:24px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
  h1{{font-size:22px;margin:0 0 16px}} h2{{font-size:15px;margin:24px 0 8px;color:#555;font-weight:500}}
  .chart-box{{position:relative;height:380px;margin-bottom:24px}}
</style></head><body><div class="container">
<h1>{html_lib.escape(title)}</h1>
<h2>Equity curves (benchmark vs best filter)</h2>
<div class="chart-box"><canvas id="eq_chart"></canvas></div>
<h2>Balance curves</h2>
<div class="chart-box"><canvas id="bal_chart"></canvas></div>
{text_html}
<script>
function mkChart(id,ds){{new Chart(document.getElementById(id),{{type:'line',data:{{labels,datasets:ds}},options:{{responsive:true,maintainAspectRatio:false,interaction:{{mode:'index',intersect:false}},plugins:{{legend:{{position:'top'}},tooltip:{{callbacks:{{label:c=>c.dataset.label+': $'+(c.parsed.y||0).toLocaleString()}}}}}},scales:{{x:{{ticks:{{maxTicksLimit:20,maxRotation:45}}}},y:{{ticks:{{callback:v=>'$'+v.toLocaleString()}}}}}}}}}})}}
{ds}
</script></div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Basket strategy analysis: equity curve + SL scan + tick comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--statement", help="Statement.htm or tester .htm (required unless --combine)")
    ap.add_argument("--bars", help="M1/M15 bar CSV (required unless --combine)")
    ap.add_argument("--backtest", help="Second statement (strategy-tester report) "
                    "to compare against --statement. Switches the script to "
                    "LIVE-vs-BACKTEST comparison mode.")
    ap.add_argument("--engine", choices=["bar", "tick"], default="bar",
                    help="SL simulation engine for scan mode: 'bar' (fast, with "
                         "optional spread model) or 'tick' (accurate, requires "
                         "--ticks). Default: bar.")
    ap.add_argument("--ticks", help="Optional tick CSV for spread-kill analysis")
    ap.add_argument("--symbol", help="Filter trades to this symbol (substring match)")
    ap.add_argument("--start", help="Period start date YYYY-MM-DD")
    ap.add_argument("--end", help="Period end date YYYY-MM-DD")
    ap.add_argument("--sl-range", nargs=2, type=int, default=[6, 20],
                    metavar=("MIN", "MAX"), help="Bar SL range (default 6 20)")
    ap.add_argument("--tick-sl-range", nargs=2, type=int, default=None,
                    metavar=("MIN", "MAX"),
                    help="Tick SL range (defaults to --sl-range when omitted)")
    ap.add_argument("--broker-gmt", type=int, default=2, help="Broker GMT (default 2)")
    ap.add_argument("--tick-gmt", type=int, default=2, help="Tick data GMT (default 2)")
    ap.add_argument("--open-hours", nargs=2, type=int, default=None,
                    metavar=("START", "END"),
                    help="Only analyse baskets opened between START and END "
                         "broker-local hours (0-24). Supports midnight wrap, "
                         "e.g. 22 6 for 10pm-6am.")
    ap.add_argument("--eod-time", default="23:59", metavar="HH:MM",
                    help="Broker-local time for end-of-day close (default 23:59)")
    ap.add_argument("--final-sl", type=int, default=None, metavar="PIPS",
                    help="Run a single tick-precision 'final check' at this "
                         "SL value. Requires --ticks. Also writes a JSON curve "
                         "file for later combining.")
    ap.add_argument("--final-eod", action="store_true",
                    help="Enable EOD close in the final check (default off)")
    ap.add_argument("--lot-size", type=float, default=None, metavar="LOTS",
                    help="Only include positions with this exact lot size "
                         "(e.g. 0.02). Baskets are rebuilt from the filtered "
                         "positions only.")
    ap.add_argument("--spread-profile", metavar="PATH",
                    help="Load a spread-profile JSON file (previously exported "
                         "when --ticks was used) and apply it to bar-based SL "
                         "simulations. When --ticks is also provided, the "
                         "newly-computed profile takes precedence.")
    ap.add_argument("--save-curve", action="store_true",
                    help="Also save the unmodified baseline equity curve as "
                         "a JSON file ready for --combine. Useful in Step 1 "
                         "when you want a combine-ready file without running "
                         "a final-check simulation.")
    ap.add_argument("--initial-balance", type=float, default=None, metavar="AMOUNT",
                    help="Synthesize a starting-balance deposit before the "
                         "first trade when the source has no balance ops "
                         "(e.g. MT4 strategy tester reports). Lets you put "
                         "a backtest on the same dollar scale as a live "
                         "account for comparison or combining.")
    ap.add_argument("--basket-close-window", type=int, default=10, metavar="SECONDS",
                    help="Time window (seconds) used to cluster trades into "
                         "baskets by close time. Trades of the same direction "
                         "closing within this window of each other are treated "
                         "as one basket. Default 10s handles normal basket "
                         "TPs AND mass-close events (daily DD, manual close) "
                         "that take several seconds to propagate.")
    ap.add_argument("--stats-only", action="store_true",
                    help="Skip MAE, SL scan, and tick comparison sections. "
                         "Just output the statement summary, hourly "
                         "breakdown, and comparison-format stats (trade-level, "
                         "basket-level, equity curve). Useful for getting a "
                         "quick baseline report on a backtest alone without "
                         "running the full SL exploration.")
    ap.add_argument("--filter-optimize", action="store_true",
                    help="Run filter optimization: test combinations of "
                         "session windows, spread thresholds, and day-of-week "
                         "filters to find the best risk-adjusted return. "
                         "Requires --ticks for spread data.")
    ap.add_argument("--session-step", type=int, default=2, metavar="H",
                    help="Hour granularity for session window testing "
                         "(default 2).")
    ap.add_argument("--min-session-width", type=int, default=4, metavar="H",
                    help="Minimum session window width in hours (default 4).")
    ap.add_argument("--spread-values", type=float, nargs="+",
                    default=[0, 0.5, 1.0, 1.5, 2.0, 3.0],
                    metavar="X",
                    help="Spread thresholds to test (pips). 0 = no filter. "
                         "Default: 0 0.5 1.0 1.5 2.0 3.0")
    ap.add_argument("--day-options", nargs="+",
                    default=["none", "no-mon", "no-fri", "no-mon-fri"],
                    help="Day-of-week filter options to test. "
                         "Default: none no-mon no-fri no-mon-fri")
    ap.add_argument("--top-results", type=int, default=20, metavar="N",
                    help="How many top filter results to show (default 20).")
    ap.add_argument("--combine", nargs="+", default=None, metavar="FILE",
                    help="Combine N previously-exported curve JSON files into "
                         "a single report. Ignores other flags.")
    ap.add_argument("--out-dir", default=".", help="Output directory")
    args = ap.parse_args()

    # Combine mode — handle early, ignore everything else
    if args.combine:
        os.makedirs(args.out_dir, exist_ok=True)
        out_path = os.path.join(args.out_dir, "combined_report.html")
        combine_reports(args.combine, out_path)
        print(f"Loaded {len(args.combine)} curve files")
        print(f"✓ Combined report: {out_path}")
        return 0

    if not args.statement or not args.bars:
        print("--statement and --bars are required (or use --combine).", file=sys.stderr)
        return 1

    # Parse --eod-time
    try:
        eod_h_str, eod_m_str = args.eod_time.split(":")
        eod_hour = int(eod_h_str)
        eod_minute = int(eod_m_str)
        if not (0 <= eod_hour <= 23 and 0 <= eod_minute <= 59):
            raise ValueError
    except ValueError:
        print(f"Invalid --eod-time {args.eod_time!r} — use HH:MM format.", file=sys.stderr)
        return 1

    if args.final_sl is not None and args.engine == "tick" and not args.ticks:
        print("--final-sl with --engine tick requires --ticks", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)

    print(f"Loading statement: {args.statement}")
    trades, balance_ops = parse_statement(args.statement, args.broker_gmt, args.symbol)
    if not trades:
        print("No trades parsed — check --symbol filter or file format.", file=sys.stderr)
        return 1

    if args.lot_size is not None:
        before = len(trades)
        trades = [t for t in trades if abs(t["lots"] - args.lot_size) < 1e-6]
        print(f"Lot-size filter {args.lot_size:g}: {before} → {len(trades)} positions")
        if not trades:
            print(f"No positions match lot size {args.lot_size:g}.", file=sys.stderr)
            return 1

    # Synthesize a starting-balance deposit if --initial-balance was given
    # and the source has no real balance ops (typical for MT4 strategy
    # tester reports)
    if args.initial_balance is not None and not balance_ops and trades:
        balance_ops = [{
            "ts": trades[0]["ts"] - 1,
            "amt": args.initial_balance,
            "time": "synthetic",
            "type": "deposit",
        }]
        print(f"Synthesized ${args.initial_balance:,.0f} starting balance "
              "(source has no deposits)")

    offset = timezone(timedelta(hours=args.broker_gmt))
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None
    if args.start:
        start_ts = int(datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=offset).timestamp())
        trades = [t for t in trades if t["ts"] >= start_ts]
    if args.end:
        end_ts = int(datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=offset).timestamp())
        trades = [t for t in trades if t["close_ts"] <= end_ts]
    if not trades:
        print("No trades in filtered period.", file=sys.stderr)
        return 1

    print(f"Loading bars: {args.bars}")
    bars, bar_ts = load_bars(args.bars)
    if not bars:
        print("No bars loaded.", file=sys.stderr)
        return 1

    baskets = make_baskets(trades, args.basket_close_window)
    pip_size = detect_pip_size(trades[0]["price"])
    print(f"Detected pip size: {pip_size} ({'JPY' if pip_size == 0.01 else 'major'})")
    print(f"Parsed: {len(trades)} trades in {len(baskets)} baskets")

    if args.open_hours:
        start_h, end_h = args.open_hours
        before = len(baskets)
        baskets = filter_baskets_by_open_time(baskets, args.broker_gmt, start_h, end_h)
        print(f"Open-hours filter {start_h:02d}:00–{end_h:02d}:00 broker time: "
              f"{before} → {len(baskets)} baskets")
    if args.eod_time != "23:59":
        print(f"EOD close time: {args.eod_time} broker time")
    print()

    print("Building equity curve…")
    curves = build_equity_curve(trades, balance_ops, bars)

    summary_lines = build_summary_text(trades, baskets, balance_ops, curves)
    for ln in summary_lines:
        print(ln)

    # Load ticks once up front if provided — used for hourly spread stats,
    # scan-mode tick comparison, and final check mode.
    ticks: List[Dict] = []
    tick_ts: List[float] = []
    if args.ticks:
        print(f"\nLoading ticks: {args.ticks}")
        ticks, tick_ts = load_ticks(args.ticks, args.tick_gmt)
        print(f"  Loaded {len(ticks):,} ticks")

    # Spread profile: either computed from ticks now, or loaded from a
    # previously-saved JSON file. Ticks win if both are provided.
    spread_profile: Dict[int, float] = {}
    spread_source = ""
    if ticks:
        spread_profile = build_spread_profile(ticks, args.broker_gmt, pip_size)
        spread_source = f"computed from {len(ticks):,} ticks"
        profile_path = os.path.join(args.out_dir, "spread_profile.json")
        save_spread_profile(spread_profile, args.symbol or "", spread_source, profile_path)
        print(f"  Spread profile saved: {profile_path}")
    elif args.spread_profile:
        spread_profile = load_spread_profile(args.spread_profile)
        spread_source = f"loaded from {os.path.basename(args.spread_profile)}"
        print(f"\nLoaded spread profile: {args.spread_profile}")

    hourly_lines = build_hourly_breakdown_text(baskets, ticks, args.broker_gmt, pip_size)
    for ln in hourly_lines:
        print(ln)

    # ─── Filter optimization mode ─────────────────────────────────────
    if args.filter_optimize:
        if not ticks:
            print("ERROR: --filter-optimize requires --ticks for spread data.",
                  file=sys.stderr)
            return 1

        print("\nPrecomputing trade context (spread, hour, dow)…")
        precompute_trade_context(trades, ticks, tick_ts, args.broker_gmt, pip_size)
        tag_trades_with_baskets(trades, baskets)

        # Benchmark: full equity curve with all trades, no filters
        print("Building benchmark equity curve…")
        benchmark_curves = build_equity_curve(trades, balance_ops, bars)
        bm_stats = fast_realized_stats(trades)
        bm_net = bm_stats["net"]
        bm_dd = bm_stats["max_dd"]
        bm_eq = equity_stats(benchmark_curves, trades[0]["ts"])
        print(f"  Benchmark: {bm_stats['trades']} trades, "
              f"{bm_stats['baskets']} baskets, "
              f"Net ${bm_net:,.2f}, Balance DD ${bm_dd:,.2f}, "
              f"Equity DD ${bm_eq.get('max_dd', 0):,.2f}")

        # Build grid and run optimization
        grid = generate_filter_grid(
            args.session_step, args.min_session_width,
            args.spread_values, args.day_options,
        )
        print(f"\nRunning filter optimization ({len(grid):,} trials)…")

        top, summary = run_filter_optimization(
            trades, baskets, bars, balance_ops, grid,
            bm_net, bm_dd, args.top_results,
        )

        result_lines = build_filter_results_text(
            top, summary, bm_net, bm_dd,
            bm_stats["trades"], bm_stats["baskets"],
        )
        for ln in result_lines:
            print(ln)

        # Build full equity curve for the #1 result
        top1_curves = None
        top1_ts = None
        top1_label = "Benchmark"
        if top and top[0].get("filtered_trades"):
            filt_trades = top[0]["filtered_trades"]
            top1_curves = build_equity_curve(filt_trades, balance_ops, bars)
            top1_ts = filt_trades[0]["ts"] if filt_trades else trades[0]["ts"]
            parts = []
            parts.append(_fmt_session(top[0]["session_start"], top[0]["session_end"]))
            if top[0]["max_spread_initial"] is not None:
                parts.append(f"spr.init {top[0]['max_spread_initial']:.1f}p")
            if top[0]["max_spread_all"] is not None:
                parts.append(f"spr.all {top[0]['max_spread_all']:.1f}p")
            if top[0]["day_label"] != "none":
                parts.append(top[0]["day_label"])
            top1_label = "#1: " + ", ".join(parts)

        chart_path = os.path.join(args.out_dir, "filter_optimize.html")
        title = f"{args.symbol or 'Strategy'} — Filter Optimization"
        write_filter_html_report(
            benchmark_curves, trades[0]["ts"],
            top1_curves, top1_ts,
            chart_path, title,
            [summary_lines, hourly_lines, result_lines],
            top1_label,
        )
        print(f"\n✓ Filter optimization HTML: {chart_path}")
        return 0

    # ─── Comparison mode (live vs backtest) ─────────────────────────────
    if args.backtest:
        print(f"\nLoading backtest: {args.backtest}")
        bt_trades, bt_balance_ops = parse_statement(
            args.backtest, args.broker_gmt, args.symbol
        )
        if not bt_trades:
            print("No backtest trades parsed — check --symbol filter or file format.",
                  file=sys.stderr)
            return 1

        # If explicit dates given, apply them. Otherwise auto-constrain the
        # backtest to the live statement's period (makes a fair comparison
        # when the backtest spans a wider range than live).
        if start_ts is not None:
            bt_trades = [t for t in bt_trades if t["ts"] >= start_ts]
        else:
            live_start_ts = trades[0]["ts"]
            bt_trades = [t for t in bt_trades if t["ts"] >= live_start_ts]
        if end_ts is not None:
            bt_trades = [t for t in bt_trades if t["close_ts"] <= end_ts]
        else:
            live_end_ts = trades[-1]["close_ts"]
            bt_trades = [t for t in bt_trades if t["close_ts"] <= live_end_ts]
        if args.lot_size is not None:
            bt_trades = [t for t in bt_trades
                         if abs(t["lots"] - args.lot_size) < 1e-6]

        if not bt_trades:
            print("Backtest has no trades in the live statement's period — "
                  "the files don't overlap in time. Aborting comparison.",
                  file=sys.stderr)
            return 1

        bt_baskets = make_baskets(bt_trades, args.basket_close_window)
        if args.open_hours:
            bt_baskets = filter_baskets_by_open_time(
                bt_baskets, args.broker_gmt,
                args.open_hours[0], args.open_hours[1]
            )

        print(f"  Backtest filtered to live period: "
              f"{bt_trades[0]['time']} → {bt_trades[-1]['close_time']}")
        print(f"  Backtest parsed: {len(bt_trades)} trades in {len(bt_baskets)} baskets")

        # Normalize backtest to start at the same balance as live. Strategy
        # tester reports have no deposit records, so without this the curves
        # start at very different dollar levels and the chart becomes
        # impossible to compare visually.
        live_start_balance = sum(op["amt"] for op in balance_ops) if balance_ops else 0.0
        if live_start_balance > 0 and not bt_balance_ops:
            bt_balance_ops = [{
                "ts": bt_trades[0]["ts"] - 1,
                "amt": live_start_balance,
                "time": "synthetic",
                "type": "deposit"
            }]
            print(f"  Synthesized ${live_start_balance:,.0f} starting balance for backtest "
                  "(matches live deposit)")

        print("Building backtest equity curve…")
        bt_curves = build_equity_curve(bt_trades, bt_balance_ops, bars)

        live_stats = compute_stats(trades, baskets, curves)
        bt_stats = compute_stats(bt_trades, bt_baskets, bt_curves)

        comparison_lines = build_comparison_text(live_stats, bt_stats)
        for ln in comparison_lines:
            print(ln)

        chart_path = os.path.join(args.out_dir, "comparison_report.html")
        title = f"{args.symbol or 'Strategy'} — Live vs Backtest Comparison"
        write_comparison_html_report(
            curves, trades[0]["ts"],
            bt_curves, bt_trades[0]["ts"],
            chart_path, title,
            [summary_lines, hourly_lines, comparison_lines]
        )

        # Always save curve JSONs for both legs so they can be combined
        # with other pairs later via --combine
        sym_name = (args.symbol or os.path.splitext(os.path.basename(args.statement))[0]).lower()

        live_labels, live_bal_j, live_eq_j = curves_to_daily(curves, trades[0]["ts"])
        live_eq_stats = equity_stats(curves, trades[0]["ts"])
        live_json = os.path.join(args.out_dir, f"{sym_name}_live_baseline.json")
        export_curve_json(
            live_json, (args.symbol or sym_name) + "_live", None, False,
            args.eod_time, args.open_hours, args.lot_size,
            live_eq_stats, live_labels, live_bal_j, live_eq_j
        )

        bt_labels, bt_bal_j, bt_eq_j = curves_to_daily(bt_curves, bt_trades[0]["ts"])
        bt_eq_stats = equity_stats(bt_curves, bt_trades[0]["ts"])
        bt_json = os.path.join(args.out_dir, f"{sym_name}_backtest_baseline.json")
        export_curve_json(
            bt_json, (args.symbol or sym_name) + "_backtest", None, False,
            args.eod_time, args.open_hours, args.lot_size,
            bt_eq_stats, bt_labels, bt_bal_j, bt_eq_j
        )

        print(f"\n✓ Comparison HTML report: {chart_path}")
        print(f"✓ Live curve (for combining): {live_json}")
        print(f"✓ Backtest curve (for combining): {bt_json}")
        if spread_profile:
            print(f"✓ Spread profile saved: "
                  f"{os.path.join(args.out_dir, 'spread_profile.json')}")
        return 0

    mae_lines = build_mae_text(baskets, bars, bar_ts, pip_size)

    # ─── Stats-only mode: skip MAE/SL scan, just report the stats ─────
    if args.stats_only:
        stats = compute_stats(trades, baskets, curves)
        label = args.symbol or os.path.splitext(os.path.basename(args.statement))[0]
        stats_lines = build_single_stats_text(stats, label)
        for ln in stats_lines:
            print(ln)

        chart_path = os.path.join(args.out_dir, "equity_curve.html")
        title = f"{args.symbol or 'Strategy'} — Stats Summary"
        write_html_report(
            curves, balance_ops, trades[0]["ts"], chart_path, title,
            [summary_lines, hourly_lines, stats_lines]
        )
        print(f"\n✓ Stats HTML report: {chart_path}")

        if args.save_curve:
            sym_name = (args.symbol or
                        os.path.splitext(os.path.basename(args.statement))[0]).lower()
            labels_j, bal_j, eq_j = curves_to_daily(curves, trades[0]["ts"])
            stats_j = equity_stats(curves, trades[0]["ts"])
            json_path = os.path.join(args.out_dir, f"{sym_name}_baseline.json")
            export_curve_json(
                json_path, args.symbol or sym_name, None, False,
                args.eod_time, args.open_hours, args.lot_size,
                stats_j, labels_j, bal_j, eq_j
            )
            print(f"✓ Baseline curve (for combining): {json_path}")
        return 0

    for ln in mae_lines:
        print(ln)

    # ─── Final check mode (single SL, bar or tick engine) ──────────────
    if args.final_sl is not None:
        use_tick_engine = args.engine == "tick" or bool(ticks)
        # If --engine bar is explicitly set, force bar path even if ticks loaded
        if args.engine == "bar":
            use_tick_engine = False

        engine_label = "TICK" if use_tick_engine else "BAR"
        print(f"\nRunning final check — {args.final_sl}-pip SL, "
              f"EOD {'ON' if args.final_eod else 'OFF'}, {engine_label} engine…")

        if use_tick_engine:
            if not ticks:
                print("No ticks loaded — --engine tick requires --ticks.",
                      file=sys.stderr)
                return 1
            synth, outcomes, tick_verified, bar_fallback = build_synthetic_trades_ticks(
                baskets, bars, bar_ts, ticks, tick_ts,
                args.final_sl, args.final_eod, args.broker_gmt, pip_size,
                eod_hour, eod_minute
            )
        else:
            # Bar-based final check (optionally with spread profile)
            synth, outcomes = build_synthetic_trades(
                baskets, bars, bar_ts, args.final_sl, args.final_eod,
                args.broker_gmt, pip_size, eod_hour, eod_minute,
                spread_profile if spread_profile else None
            )
            tick_verified = 0
            bar_fallback = len(baskets)

        final_curves = build_equity_curve(synth, balance_ops, bars)
        first_ts_final = synth[0]["ts"] if synth else trades[0]["ts"]
        eq_stats = equity_stats(final_curves, first_ts_final)

        final_lines = build_final_check_text(
            args.symbol or "strategy", args.final_sl, args.final_eod,
            args.eod_time, args.open_hours, args.lot_size,
            outcomes, tick_verified, bar_fallback, eq_stats
        )
        # Tweak header for bar engine so it says BAR not TICK
        if not use_tick_engine and final_lines:
            for i, ln in enumerate(final_lines):
                if "FINAL TICK CHECK" in ln:
                    final_lines[i] = ln.replace("FINAL TICK CHECK", "FINAL BAR CHECK")
                    if spread_profile:
                        final_lines[i] += " (with spread model)"

        for ln in final_lines:
            print(ln)

        labels, bal_data, eq_data = curves_to_daily(final_curves, first_ts_final)

        name = (args.symbol or os.path.splitext(os.path.basename(args.statement))[0]).lower()
        suffix = "final_tick" if use_tick_engine else "final_bar"
        chart_path = os.path.join(args.out_dir, f"{name}_{suffix}.html")
        json_path = os.path.join(args.out_dir, f"{name}_{suffix}.json")

        title_engine = "Tick" if use_tick_engine else "Bar"
        title = f"{args.symbol or 'Strategy'} — Final {title_engine} Check ({args.final_sl}p)"
        write_html_report(
            final_curves, balance_ops, first_ts_final, chart_path, title,
            [summary_lines, hourly_lines, final_lines]
        )
        export_curve_json(
            json_path, args.symbol or name, args.final_sl, args.final_eod,
            args.eod_time, args.open_hours, args.lot_size,
            eq_stats, labels, bal_data, eq_data
        )
        print(f"\n✓ Final HTML report: {chart_path}")
        print(f"✓ Curve data (for combining): {json_path}")
        return 0

    # ─── Normal scan mode ─────────────────────────────────────────────────
    if args.engine == "tick" and not ticks:
        print("--engine tick requires --ticks.", file=sys.stderr)
        return 1

    print(f"\nRunning SL scan ({args.engine} engine)…")
    scan_lines = build_sl_scan_text(
        baskets, bars, bar_ts, args.sl_range[0], args.sl_range[1],
        args.broker_gmt, pip_size, balance_ops, eod_hour, eod_minute,
        spread_profile if spread_profile and args.engine == "bar" else None,
        spread_source if args.engine == "bar" else "",
        args.engine,
        ticks if args.engine == "tick" else None,
        tick_ts if args.engine == "tick" else None,
    )
    for ln in scan_lines:
        print(ln)

    tick_lines: List[str] = []
    if ticks and args.engine == "bar":
        tmin, tmax = args.tick_sl_range or args.sl_range
        print(f"\nRunning tick SL comparison ({tmin}-{tmax} pips)…")
        tick_lines = build_tick_text(
            baskets, bars, bar_ts, ticks, tick_ts,
            tmin, tmax, args.broker_gmt, pip_size, eod_hour, eod_minute
        )
        for ln in tick_lines:
            print(ln)

    chart_path = os.path.join(args.out_dir, "equity_curve.html")
    title = f"{args.symbol or 'Strategy'} — Analysis Report"
    write_html_report(
        curves, balance_ops, trades[0]["ts"], chart_path, title,
        [summary_lines, hourly_lines, mae_lines, scan_lines, tick_lines]
    )
    print(f"\n✓ Full HTML report: {chart_path}")

    if args.save_curve:
        sym_name = (args.symbol or
                    os.path.splitext(os.path.basename(args.statement))[0]).lower()
        labels_j, bal_j, eq_j = curves_to_daily(curves, trades[0]["ts"])
        stats_j = equity_stats(curves, trades[0]["ts"])
        json_path = os.path.join(args.out_dir, f"{sym_name}_baseline.json")
        export_curve_json(
            json_path, args.symbol or sym_name, None, False,
            args.eod_time, args.open_hours, args.lot_size,
            stats_j, labels_j, bal_j, eq_j
        )
        print(f"✓ Baseline curve (for combining): {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
