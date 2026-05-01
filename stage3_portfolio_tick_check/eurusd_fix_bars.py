#!/usr/bin/env python3
"""
FIX: Compute EURUSD max DD using M5 bar data instead of broken tick loading.
This addresses the root cause: custom_dd_analysis.py is falling back to
trade_events for ALL symbols because tick_rows_kept = 0.
"""

import csv
from datetime import datetime, timezone
import calendar
import portfolio_backtest as pb
import os
import json
import math
from typing import Dict, List, Tuple

print("=" * 90)
print("EURUSD MAX DD ANALYSIS: Using M5 Bar Data (Tick Data Fix)")
print("=" * 90)

def assign_baskets(trades: List[Dict]) -> Tuple[List[Dict], Dict[int, Dict]]:
    """Assign trades to baskets."""
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

def load_m5_bars(bar_path: str, min_ts: int, max_ts: int) -> List[Tuple]:
    """Load M5 bars within trade date range."""
    bars = []
    tz_offset_sec = 2 * 3600  # GMT+2
    
    with open(bar_path, "r", encoding="utf-8", errors="ignore") as f:
        for row_num, row in enumerate(csv.reader(f)):
            if len(row) < 5:
                continue
            if row_num % 500000 == 0:
                print(f"  Bar load progress: row {row_num:,}...", flush=True)
            
            try:
                # Parse DD.MM.YYYY HH:MM format
                dt_str = row[0].strip()
                d = int(dt_str[0:2])
                m = int(dt_str[3:5])
                y = int(dt_str[6:10])
                hh = int(dt_str[11:13])
                mm = int(dt_str[14:16])
                
                ts = calendar.timegm((y, m, d, hh, mm, 0, 0, 0, 0)) - tz_offset_sec
                
                if ts < min_ts:
                    continue
                if ts > max_ts:
                    break
                    
                o = float(row[1])
                h = float(row[2])
                l = float(row[3])
                c = float(row[4])
                
                bars.append((ts, o, h, l, c))
            except Exception as e:
                if row_num < 10:
                    pass  # Ignore header/parsing errors
                continue
    
    print(f"  Loaded {len(bars):,} bars in trade date range", flush=True)
    return bars

def trade_mtm(trade: Dict, mid: float) -> float:
    """Calculate mark-to-market for a trade."""
    ps = pb._pip_size(trade["price"])
    return pb._trade_mtm(trade["type"], trade["price"], mid, trade["lots"], ps)

def compute_max_dd_from_bars(trades: List[Dict], baskets: Dict[int, Dict], bars: List[Tuple]) -> Dict:
    """Compute max DD using M5 bar data with full MTM."""
    if not trades or not bars:
        return {
            "total_profit": 0.0,
            "max_equity_dd": 0.0,
            "rd_ratio": math.inf,
            "basket_dds": [],
            "source": "m5_bars",
            "bars_used": len(bars),
        }

    trades_sorted = sorted(trades, key=lambda t: (t["ts"], t["close_ts"]))
    
    # For each bar, compute equity
    total_realized = 0.0
    running_peak = 0.0
    max_dd = 0.0
    equity_curve = []
    
    basket_realized_running = {bid: 0.0 for bid in baskets}
    basket_min_pnl = {bid: 0.0 for bid in baskets}
    basket_max_adverse_pips = {bid: 0.0 for bid in baskets}
    
    trade_idx = 0
    for ts, o, h, l, c in bars:
        mid = (l + h) / 2.0  # Use bar mid
        
        # Add any trades that open at this bar time
        while trade_idx < len(trades_sorted) and trades_sorted[trade_idx]["ts"] <= ts:
            trade_idx += 1
        
        # Calculate realized + unrealized at this point in time
        unreal = 0.0
        basket_unreal: Dict[int, float] = {}
        
        for t in trades_sorted:
            if t["close_ts"] <= ts:
                # Trade is closed by this bar
                if t["trade_pl"] not in [s.get("realized", 0) for s in [t]]:
                    # First time seeing this closed trade
                    total_realized += t["trade_pl"]
                    basket_realized_running[t["basket_id"]] += t["trade_pl"]
            elif t["ts"] <= ts < t["close_ts"]:
                # Trade is open at this bar - use bar low for worst case
                u = trade_mtm(t, l)  # Use bar LOW for conservative estimate
                unreal += u
                bid_ = t["basket_id"]
                basket_unreal[bid_] = basket_unreal.get(bid_, 0.0) + u
                
                # Track adverse pips
                binfo = baskets[bid_]
                ps = binfo["pip_size"]
                if binfo["direction"] == "buy":
                    adverse_pips = (binfo["first_price"] - l) / ps  # Use bar low
                else:
                    adverse_pips = (h - binfo["first_price"]) / ps  # Use bar high
                if adverse_pips > basket_max_adverse_pips[bid_]:
                    basket_max_adverse_pips[bid_] = adverse_pips
        
        eq = total_realized + unreal
        equity_curve.append([ts, round(eq, 4)])
        
        if eq > running_peak:
            running_peak = eq
        dd = running_peak - eq
        if dd > max_dd:
            max_dd = dd
        
        # Track basket min pnl
        for bid_ in basket_unreal.keys():
            basket_pnl = basket_realized_running[bid_] + basket_unreal.get(bid_, 0.0)
            if basket_pnl < basket_min_pnl[bid_]:
                basket_min_pnl[bid_] = basket_pnl
    
    # Build basket DD info
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
        "source": "m5_bars",
        "bars_used": len(bars),
        "equity_curve": equity_curve,
    }

# Main analysis
print("\nLoading EURUSD trades from HTM...")
htm_path = r"c:\Users\sammj\Dropbox\VPS_Data_Transfer\SEIF2\3_SEIF_Only_Part_All\EURUSD_M15.htm"
trades, fmt = pb.parse_backtest(htm_path, 2, "EURUSD")
trades, baskets = assign_baskets(trades)
summary = pb.extract_backtest_report_summary(htm_path)

min_ts = min(t["ts"] for t in trades)
max_ts = max(t["close_ts"] for t in trades)

print(f"  Trades: {len(trades)}")
print(f"  Baskets: {len(baskets)}")
print(f"  Date range: {datetime.fromtimestamp(min_ts, tz=timezone.utc).date()} to {datetime.fromtimestamp(max_ts, tz=timezone.utc).date()}")

print("\nLoading M5 bars...")
bar_path = r"D:\Work\M5_2021to20260415dukas\EURUSD_GMT+2_US-DST_M5.csv"
bars = load_m5_bars(bar_path, min_ts, max_ts)

print("\nComputing max DD from bars (using bar lows)...")
results = compute_max_dd_from_bars(trades, baskets, bars)

print("\n" + "=" * 90)
print("RESULTS COMPARISON")
print("=" * 90)
print(f"{'Source':<30} {'Max DD':>15} {'Total Profit':>15}")
print("-" * 90)
print(f"{'HTM Report (reference)':<30} {'$2,399.18':>15} {'$3,961.69':>15}")
print(f"{'Current analysis (trade_events)':<30} {'$117.72':>15} {'$3,959.47':>15}")
print(f"{'M5 Bar-based (FIX)':<30} {'$' + f'{results[\"max_equity_dd\"]:,.2f}':>14} {'$' + f'{results[\"total_profit\"]:,.2f}':>14}")
print("-" * 90)

discrepancy_current = 2399.18 / 117.72
discrepancy_bars = 2399.18 / results["max_equity_dd"] if results["max_equity_dd"] > 0 else float('inf')

print(f"\nDiscrepancy (HTM vs current): {discrepancy_current:.1f}x")
print(f"Discrepancy (HTM vs bars): {discrepancy_bars:.1f}x")

if abs(discrepancy_bars - 1.0) < 0.1:
    print(f"\n✓ Bar analysis MATCHES HTM report!")
    print(f"  This confirms: tick data loading is broken, use bars as fix")
elif abs(discrepancy_bars - discrepancy_current) < 1.0:
    print(f"\n✗ Bar analysis is similar to current - MTM logic may be the issue")
else:
    print(f"\n? Bar analysis shows intermediate result - may need hybrid approach")

print("\nTop 3 DD baskets (bar-based):")
for i, b in enumerate(results["basket_dds"][:3]):
    print(f"  {i+1}. Basket {b['basket_id']}: ${b['max_drawdown']:,.2f} ({b['trade_count']} trades)")

print("\n" + "=" * 90)
