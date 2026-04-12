"""
stage1_real_results_vs_backtest.py — compare real trading results against backtest.

Standalone tool (no dependencies on basket_analysis.py). Takes a real account
statement and a backtest report, builds equity curves from tick data, and scores
how closely the real trading matched the backtest expectations.

Scoring dimensions:
  - Trade count similarity
  - Trade timing similarity (entry/exit time distance)
  - Trade duration similarity
  - Win rate comparison
  - Profit factor comparison
  - Return/DD comparison
  - Max drawdown comparison
  - Net profit similarity

Outputs an HTML report with side-by-side equity curve overlay and detailed
closeness metrics.

Usage:
    python stage1_real_results_vs_backtest.py ^
        --real-statement real_account.htm ^
        --backtest backtest_report.htm ^
        --ticks-dir C:/ticks ^
        --symbol EURUSD ^
        --out-dir ./comparison_results

"""

import argparse
import csv
import html as html_lib
import html.parser as html_parser
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple


def build_tick_filename(symbol: str, tick_gmt: int) -> str:
    """Build expected tick CSV filename: SYMBOL_GMT+2_US-DST.csv."""
    sign = "+" if tick_gmt >= 0 else ""
    return f"{symbol.upper()}_GMT{sign}{tick_gmt}_US-DST.csv"


def resolve_tick_file(ticks_dir: str, symbol: str, tick_gmt: int) -> str:
    """Resolve tick file path from folder + symbol + gmt convention."""
    filename = build_tick_filename(symbol, tick_gmt)
    path = os.path.join(ticks_dir, filename)
    if os.path.exists(path):
        return path

    # Helpful fallback hint if filename convention differs slightly.
    if os.path.isdir(ticks_dir):
        symbol_prefix = f"{symbol.upper()}_GMT"
        matches = [
            name for name in os.listdir(ticks_dir)
            if name.upper().startswith(symbol_prefix) and name.upper().endswith("_US-DST.CSV")
        ]
        if matches:
            raise FileNotFoundError(
                f"Expected tick file '{filename}' not found in '{ticks_dir}'. "
                f"Found similar files: {', '.join(sorted(matches))}"
            )

    raise FileNotFoundError(
        f"Expected tick file '{filename}' not found in '{ticks_dir}'"
    )


# ────────────────────────────────────────────────────────────────────────────
# File reading with encoding auto-detection
# ────────────────────────────────────────────────────────────────────────────
def read_text_file(path: str) -> str:
    """Read a text file as str, handling UTF-8 and UTF-16 (BOM-sniffed)."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", errors="replace")
    if raw[:200].count(b"\x00") > 50:
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


# ────────────────────────────────────────────────────────────────────────────
# HTML table row extraction
# ────────────────────────────────────────────────────────────────────────────
class _RowParser(html_parser.HTMLParser):
    """Collects plain-text cells from every <tr>."""

    def __init__(self):
        super().__init__()
        self.rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            if self._row is not None:
                self.rows.append(self._row)
            self._row = []
            self._cell = None
        elif tag in ("td", "th"):
            if self._cell is not None and self._row is not None:
                self._row.append("".join(self._cell).strip())
            self._cell = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th"):
            if self._cell is not None and self._row is not None:
                self._row.append("".join(self._cell).strip())
                self._cell = None
        elif tag == "tr":
            if self._row is not None:
                if self._cell is not None:
                    self._row.append("".join(self._cell).strip())
                    self._cell = None
                self.rows.append(self._row)
                self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def close(self):
        if self._row is not None:
            if self._cell is not None:
                self._row.append("".join(self._cell).strip())
            self.rows.append(self._row)
            self._row = None
            self._cell = None
        super().close()


def _extract_rows(html_text: str) -> List[List[str]]:
    parser = _RowParser()
    parser.feed(html_text)
    parser.close()
    return [[c.replace("\xa0", " ").strip() for c in row] for row in parser.rows]


# ────────────────────────────────────────────────────────────────────────────
# Format detection
# ────────────────────────────────────────────────────────────────────────────
def _detect_format(html_text: str, rows: List[List[str]]) -> str:
    """Return one of: 'mt5_tester', 'mt4_tester', 'mt4_live'."""
    if re.search(r">\s*Deals\s*<", html_text) and "Direction" in html_text:
        for row in rows:
            if len(row) >= 13 and row[4].strip().lower() in ("in", "out"):
                return "mt5_tester"

    has_tester_open = any(
        len(row) == 9 and row[2].strip().lower() in ("buy", "sell")
        for row in rows
    )
    has_tester_close = any(
        len(row) == 10 and row[2].strip().lower() == "close"
        for row in rows
    )
    if has_tester_open and has_tester_close:
        return "mt4_tester"

    has_live_trade = any(
        len(row) == 14 and row[2].strip().lower() in ("buy", "sell")
        for row in rows
    )
    if has_live_trade:
        return "mt4_live"

    raise ValueError(
        "Could not detect statement format. Expected MT4/MT5 HTML statement/report "
        "or live CSV export with trade rows."
    )


# ────────────────────────────────────────────────────────────────────────────
# Trade parsers
# ────────────────────────────────────────────────────────────────────────────
def _parse_dt(s: str, offset: timezone) -> int:
    s = s.strip()
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=offset).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Unrecognised datetime: {s!r}")


def _parse_num(s: str) -> float:
    """Parse a number that may use space as thousands separator."""
    return float(s.replace(" ", "").replace(",", ""))


def _normalize_magic(value: str) -> str:
    """Keep only digits for robust magic-number comparisons."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _parse_mt4_live(rows, offset, symbol_filter, magic_filter: Optional[str] = None):
    trades = []
    for i, row in enumerate(rows):
        if len(row) != 14:
            continue
        ttype = row[2].strip().lower()
        # Only include buy/sell trades (filters out deposits, withdrawals, balance ops, etc.)
        if ttype not in ("buy", "sell"):
            continue
        
        symbol = row[4].strip().upper()
        if symbol_filter:
            symbol_filter_upper = symbol_filter.upper()
            if symbol_filter_upper not in symbol:
                continue

        # MT4 live statements often place magic number in a follow-up details row:
        # ['', '170000', '170000'] or ['', '11000401', '10000 #1[tp]']
        magic_val = ""
        if i + 1 < len(rows):
            next_row = rows[i + 1]
            if len(next_row) == 3 and (next_row[0].strip() == ""):
                magic_val = _normalize_magic(next_row[1])

        if magic_filter and magic_val != magic_filter:
            continue
        
        try:
            trades.append({
                "type": ttype,
                "ts": _parse_dt(row[1], offset),
                "close_ts": _parse_dt(row[8], offset),
                "price": float(row[5]),
                "close_price": float(row[9]),
                "lots": float(row[3]),
                "profit": _parse_num(row[13]),
                "commission": _parse_num(row[10]),
                "swap": _parse_num(row[12]),
                "magic": magic_val,
            })
        except (ValueError, IndexError):
            continue
    return trades


def _parse_mt4_tester(rows, offset):
    opens: Dict[int, Dict] = {}
    trades = []
    for row in rows:
        if len(row) == 9:
            ttype = row[2].strip().lower()
            if ttype in ("buy", "sell"):
                try:
                    order = int(row[3])
                    opens[order] = {
                        "type": ttype,
                        "ts": _parse_dt(row[1], offset),
                        "price": float(row[5]),
                        "lots": float(row[4]),
                    }
                except (ValueError, IndexError):
                    pass
            continue
        if len(row) == 10 and row[2].strip().lower() == "close":
            try:
                order = int(row[3])
                if order not in opens:
                    continue
                o = opens.pop(order)
                trades.append({
                    "type": o["type"],
                    "ts": o["ts"],
                    "close_ts": _parse_dt(row[1], offset),
                    "price": o["price"],
                    "close_price": float(row[5]),
                    "lots": o["lots"],
                    "profit": _parse_num(row[8]),
                    "commission": 0.0,
                    "swap": 0.0,
                })
            except (ValueError, IndexError):
                continue
    return trades


def _parse_mt5_tester(rows, offset, symbol_filter):
    """MT5 Deals table: FIFO-match 'in' to 'out' deals."""
    open_fifo: List[Dict] = []
    trades: List[Dict] = []

    for row in rows:
        if len(row) < 13:
            continue
        direction = row[4].strip().lower()
        if direction not in ("in", "out"):
            continue
        ttype = row[3].strip().lower()
        if ttype not in ("buy", "sell"):
            continue

        symbol = row[2].strip().upper()
        if symbol_filter:
            symbol_filter_upper = symbol_filter.upper()
            if symbol_filter_upper not in symbol:
                continue

        try:
            ts = _parse_dt(row[0], offset)
            volume = _parse_num(row[5])
            price = _parse_num(row[6])
            commission = _parse_num(row[8]) if row[8] else 0.0
            swap = _parse_num(row[9]) if row[9] else 0.0
            profit = _parse_num(row[10]) if row[10] else 0.0
        except (ValueError, IndexError):
            continue

        if direction == "in":
            open_fifo.append({
                "type": ttype,
                "ts": ts,
                "price": price,
                "lots": volume,
                "open_commission": commission,
                "open_swap": swap,
            })
        else:
            target_type = "buy" if ttype == "sell" else "sell"
            match_idx = next(
                (i for i, o in enumerate(open_fifo) if o["type"] == target_type),
                None
            )
            if match_idx is None:
                continue
            o = open_fifo.pop(match_idx)
            trades.append({
                "type": o["type"],
                "ts": o["ts"],
                "close_ts": ts,
                "price": o["price"],
                "close_price": price,
                "lots": o["lots"],
                "profit": profit,
                "commission": commission + o["open_commission"],
                "swap": swap + o["open_swap"],
            })

    return trades


def _parse_live_csv(path: str, broker_gmt: int,
                    symbol_filter: Optional[str],
                    magic_filter: Optional[str] = None) -> List[Dict]:
    """Parse live trade CSV export (Status, Symbol, Type, Open/Close Time, etc.)."""
    trades: List[Dict] = []
    offset = timezone(timedelta(hours=broker_gmt))

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row:
                continue

            status = (row.get("Status") or "").strip().lower()
            if status and status != "closed":
                continue

            ttype = (row.get("Type") or "").strip().lower()
            if ttype not in ("buy", "sell"):
                continue

            symbol = (row.get("Symbol") or "").strip().upper()
            if symbol_filter and symbol_filter.upper() not in symbol:
                continue

            magic_val = _normalize_magic((row.get("Magic") or "").strip())
            if magic_filter and magic_val != magic_filter:
                continue

            try:
                open_time = (row.get("Open Time") or "").strip()
                close_time = (row.get("Close Time") or "").strip()
                open_ts = int(datetime.strptime(open_time, "%Y.%m.%d %H:%M:%S").replace(tzinfo=offset).timestamp())
                close_ts = int(datetime.strptime(close_time, "%Y.%m.%d %H:%M:%S").replace(tzinfo=offset).timestamp())

                trades.append({
                    "type": ttype,
                    "ts": open_ts,
                    "close_ts": close_ts,
                    "price": _parse_num((row.get("Open Price") or "0").strip()),
                    "close_price": _parse_num((row.get("Close Price") or "0").strip()),
                    "lots": _parse_num((row.get("Volume") or "0").strip()),
                    "profit": _parse_num((row.get("Profit") or "0").strip()),
                    "commission": _parse_num((row.get("Commission") or "0").strip()),
                    "swap": _parse_num((row.get("Swap") or "0").strip()),
                    "magic": magic_val,
                })
            except (ValueError, TypeError):
                continue

    return trades


def parse_statement(path: str, broker_gmt: int,
                    symbol_filter: Optional[str],
                    magic_filter: Optional[str] = None) -> Tuple[List[Dict], str]:
    """Auto-detect format and return (trades, format_name)."""
    if path.lower().endswith(".csv"):
        trades = _parse_live_csv(path, broker_gmt, symbol_filter, magic_filter)
        trades.sort(key=lambda t: t["ts"])
        return trades, "live_csv"

    html_text = read_text_file(path)
    rows = _extract_rows(html_text)
    fmt = _detect_format(html_text, rows)
    offset = timezone(timedelta(hours=broker_gmt))

    if fmt == "mt5_tester":
        trades = _parse_mt5_tester(rows, offset, symbol_filter)
    elif fmt == "mt4_tester":
        trades = _parse_mt4_tester(rows, offset)
    else:
        trades = _parse_mt4_live(rows, offset, symbol_filter, magic_filter)

    trades.sort(key=lambda t: t["ts"])
    return trades, fmt


# ────────────────────────────────────────────────────────────────────────────
# Tick CSV loading
# ────────────────────────────────────────────────────────────────────────────
def load_ticks(path: str, tick_gmt: int,
               min_ts: Optional[int] = None,
               max_ts: Optional[int] = None,
               progress_every: int = 1_000_000) -> List[Dict]:
    """Load ticks from CSV. Expected format varies; try common patterns."""
    ticks: List[Dict] = []
    offset = timezone(timedelta(hours=tick_gmt))
    processed = 0
    skipped_outside_window = 0

    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row_num, row in enumerate(reader):
            processed += 1
            if progress_every > 0 and processed % progress_every == 0:
                print(f"  Tick load progress: {processed:,} rows scanned, {len(ticks):,} kept", flush=True)

            if len(row) < 3:
                continue
            try:
                if row_num == 0 and row[0].lower() in ("time", "date", "datetime"):
                    continue

                ts_str = row[0].strip()
                try:
                    for fmt in ("%d.%m.%Y %H:%M:%S.%f", "%d.%m.%Y %H:%M:%S",
                                "%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M:%S"):
                        try:
                            dt = datetime.strptime(ts_str, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        continue
                    ts = int(dt.replace(tzinfo=offset).timestamp())
                except ValueError:
                    continue

                if min_ts is not None and ts < min_ts:
                    skipped_outside_window += 1
                    continue
                if max_ts is not None and ts > max_ts:
                    # Darwinex tick files are time-ordered; stop once we pass the window.
                    break

                bid = float(row[1])
                ask = float(row[2])
                ticks.append({"ts": ts, "bid": bid, "ask": ask})
            except (ValueError, IndexError):
                continue

    if ticks and any(ticks[i]["ts"] > ticks[i + 1]["ts"] for i in range(min(len(ticks) - 1, 1000))):
        ticks.sort(key=lambda t: t["ts"])

    print(
        f"  Tick load complete: {processed:,} rows scanned, {len(ticks):,} kept"
        f" ({skipped_outside_window:,} before window)",
        flush=True,
    )
    return ticks


# ────────────────────────────────────────────────────────────────────────────
# Equity curve construction
# ────────────────────────────────────────────────────────────────────────────
def build_equity_curve_from_ticks(trades: List[Dict], ticks: List[Dict],
                                    sample_every: int = 100) -> List[Dict]:
    """Build equity curve from tick data by computing mark-to-market P&L."""
    curves: List[Dict] = []
    realised = 0.0

    trades_sorted = sorted(trades, key=lambda t: t["ts"])
    tick_idx = 0
    active: List[Dict] = []

    # Sample every Nth tick
    for ti in range(0, len(ticks), sample_every):
        tick = ticks[ti]
        tick_ts = tick["ts"]
        mid = (tick["bid"] + tick["ask"]) / 2.0

        # Activate any trades that opened before or at this tick
        while tick_idx < len(trades_sorted) and trades_sorted[tick_idx]["ts"] <= tick_ts:
            active.append(trades_sorted[tick_idx])
            tick_idx += 1

        # Remove closed trades and accumulate P&L
        still: List[Dict] = []
        for t in active:
            if t["close_ts"] <= tick_ts:
                realised += t["profit"] + t["commission"] + t["swap"]
            else:
                still.append(t)
        active = still

        # Compute unrealised P&L from open positions
        unreal = 0.0
        for t in active:
            pip_size = 0.01 if t["price"] > 20 else 0.0001
            pip_move = (mid - t["price"]) / pip_size
            if t["type"] == "sell":
                pip_move = -pip_move
            unreal += pip_move * t["lots"] * 10.0

        curves.append({
            "ts": tick_ts,
            "bal": round(realised, 2),
            "eq": round(realised + unreal, 2),
        })

    # Process any remaining trades
    while tick_idx < len(trades_sorted):
        active.append(trades_sorted[tick_idx])
        tick_idx += 1
    for t in active:
        realised += t["profit"] + t["commission"] + t["swap"]

    if trades_sorted:
        final_ts = max(
            curves[-1]["ts"] if curves else 0,
            trades_sorted[-1]["close_ts"],
        )
        if curves and curves[-1]["bal"] != round(realised, 2):
            curves.append({
                "ts": final_ts,
                "bal": round(realised, 2),
                "eq": round(realised, 2),
            })

    return curves


# ────────────────────────────────────────────────────────────────────────────
# Statistics computation
# ────────────────────────────────────────────────────────────────────────────
def compute_stats(trades: List[Dict]) -> Dict:
    """Compute trade-level statistics."""
    if not trades:
        return {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "net": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        }

    wins = [t for t in trades if t["profit"] + t["commission"] + t["swap"] > 0]
    losses = [t for t in trades if t["profit"] + t["commission"] + t["swap"] < 0]

    gross_profit = sum(t["profit"] + t["commission"] + t["swap"] for t in wins)
    gross_loss = sum(t["profit"] + t["commission"] + t["swap"] for t in losses)
    net = gross_profit + gross_loss

    pf = abs(gross_profit / gross_loss) if gross_loss != 0 else float("inf")

    return {
        "count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": 100.0 * len(wins) / len(trades) if trades else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": pf,
        "net": net,
        "avg_win": gross_profit / len(wins) if wins else 0.0,
        "avg_loss": gross_loss / len(losses) if losses else 0.0,
    }


def curves_to_daily(curves: List[Dict]) -> Tuple[List[str], List[float], List[float]]:
    """Extract daily balance and equity from curve points."""
    by_day: Dict[str, Dict] = {}
    for c in curves:
        d = datetime.fromtimestamp(c["ts"], tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[d] = c
    days = sorted(by_day)
    return days, [by_day[d]["bal"] for d in days], [by_day[d]["eq"] for d in days]


def max_drawdown(values: List[float]) -> float:
    """Return max drawdown from a value series."""
    if not values:
        return 0.0
    running_peak = max(values[0], 0.0)
    max_dd = 0.0
    for v in values:
        if v > running_peak:
            running_peak = v
        dd = running_peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ────────────────────────────────────────────────────────────────────────────
# Comparison and scoring
# ────────────────────────────────────────────────────────────────────────────
def score_trade_count(real_count: int, backtest_count: int) -> float:
    """Score trade count similarity: 100 if identical, 0 if completely different."""
    if real_count == 0 and backtest_count == 0:
        return 100.0
    if real_count == 0 or backtest_count == 0:
        return 0.0
    ratio = min(real_count, backtest_count) / max(real_count, backtest_count)
    return ratio * 100.0


def score_trade_timing(real_trades: List[Dict], backtest_trades: List[Dict]) -> float:
    """Score timing similarity using hour-of-day distribution (Bhattacharyya coefficient).

    Individual trade-by-trade time matching breaks down when the live account
    takes slightly more or fewer trades than the backtest (e.g. extra martingale
    layers).  Comparing the *distribution* of trade entries across the 24 hours
    of the day is robust to differing trade counts and correctly captures whether
    the EA fires at the same market sessions in both environments.
    """
    if not real_trades or not backtest_trades:
        return 0.0

    real_bins = [0.0] * 24
    back_bins = [0.0] * 24
    for t in real_trades:
        real_bins[(t["ts"] // 3600) % 24] += 1
    for t in backtest_trades:
        back_bins[(t["ts"] // 3600) % 24] += 1

    real_sum = sum(real_bins) or 1.0
    back_sum = sum(back_bins) or 1.0
    real_p = [x / real_sum for x in real_bins]
    back_p = [x / back_sum for x in back_bins]

    # Bhattacharyya coefficient: 1.0 = identical distributions, 0 = no overlap
    bc = sum((real_p[i] * back_p[i]) ** 0.5 for i in range(24))
    return max(0.0, min(100.0, 100.0 * bc))


def score_duration(real_trades: List[Dict], backtest_trades: List[Dict]) -> float:
    """Score how closely trade durations match."""
    if not real_trades or not backtest_trades:
        return 0.0

    real_durations = [t["close_ts"] - t["ts"] for t in real_trades]
    backtest_durations = [t["close_ts"] - t["ts"] for t in backtest_trades]

    if not real_durations or not backtest_durations:
        return 0.0

    real_avg = sum(real_durations) / len(real_durations)
    backtest_avg = sum(backtest_durations) / len(backtest_durations)

    if real_avg == 0 and backtest_avg == 0:
        return 100.0
    if real_avg == 0 or backtest_avg == 0:
        return 0.0

    ratio = min(real_avg, backtest_avg) / max(real_avg, backtest_avg)
    return ratio * 100.0


def score_metric(real: float, backtest: float) -> float:
    """Score how closely two metrics match (e.g. win rate, PF, net profit)."""
    if real == 0 and backtest == 0:
        return 100.0
    if real == 0 or backtest == 0:
        return 0.0

    if backtest == 0:
        return 0.0

    diff_pct = 100.0 * abs(real - backtest) / abs(backtest)
    return max(0.0, 100.0 - diff_pct)


def compute_comparison(real_stats: Dict, backtest_stats: Dict,
                        real_trades: List[Dict], backtest_trades: List[Dict],
                        real_eq: List[float], backtest_eq: List[float]) -> Dict:
    """Compute all comparison scores and aggregate into overall score."""
    scores = {}

    # Trade count similarity
    scores["trade_count"] = score_trade_count(real_stats["count"], backtest_stats["count"])

    # Trade timing similarity (within 1 hour is "good")
    scores["trade_timing"] = score_trade_timing(real_trades, backtest_trades)

    # Trade duration similarity
    scores["trade_duration"] = score_duration(real_trades, backtest_trades)

    scores["win_rate"] = score_metric(real_stats["win_rate"], backtest_stats["win_rate"])

    real_pf = real_stats["profit_factor"]
    backtest_pf = backtest_stats["profit_factor"]
    if real_pf == float("inf") or backtest_pf == float("inf"):
        scores["profit_factor"] = 50.0 if (real_pf == float("inf")) == (backtest_pf == float("inf")) else 0.0
    else:
        scores["profit_factor"] = score_metric(real_pf, backtest_pf)

    real_ret_dd = real_stats["net"] / max_drawdown(real_eq) if max_drawdown(real_eq) > 0 else 0.0
    backtest_ret_dd = backtest_stats["net"] / max_drawdown(backtest_eq) if max_drawdown(backtest_eq) > 0 else 0.0
    scores["return_dd"] = score_metric(real_ret_dd, backtest_ret_dd)

    real_max_dd = max_drawdown(real_eq)
    backtest_max_dd = max_drawdown(backtest_eq)
    scores["max_dd"] = score_metric(real_max_dd, backtest_max_dd)

    scores["net_profit"] = score_metric(real_stats["net"], backtest_stats["net"])

    # Hour-of-day distributions (for report chart)
    _real_bins = [0.0] * 24
    _back_bins = [0.0] * 24
    for t in real_trades:
        _real_bins[(t["ts"] // 3600) % 24] += 1
    for t in backtest_trades:
        _back_bins[(t["ts"] // 3600) % 24] += 1
    _rs = sum(_real_bins) or 1.0
    _bs = sum(_back_bins) or 1.0
    hour_real_pct  = [round(100.0 * x / _rs, 1) for x in _real_bins]
    hour_back_pct  = [round(100.0 * x / _bs, 1) for x in _back_bins]

    # Overall score (simple average of all components)
    overall = sum(scores.values()) / len(scores) if scores else 0.0

    return {
        "scores": scores,
        "overall": overall,
        "real_stats": real_stats,
        "backtest_stats": backtest_stats,
        "real_max_dd": real_max_dd,
        "backtest_max_dd": backtest_max_dd,
        "real_ret_dd": real_ret_dd,
        "backtest_ret_dd": backtest_ret_dd,
        "hour_real_pct": hour_real_pct,
        "hour_back_pct": hour_back_pct,
    }


# ────────────────────────────────────────────────────────────────────────────
# HTML report generation
# ────────────────────────────────────────────────────────────────────────────
def write_comparison_report(real_labels: List[str], real_eq: List[float],
                             backtest_labels: List[str], backtest_eq: List[float],
                             comparison: Dict, out_path: str, title: str):
    """Generate HTML report with comparison charts and scores."""
    # Align equity curves on unified timeline
    all_dates = sorted(set(real_labels + backtest_labels))
    real_by_date = dict(zip(real_labels, real_eq))
    backtest_by_date = dict(zip(backtest_labels, backtest_eq))

    real_aligned = []
    backtest_aligned = []
    last_real = 0.0
    last_backtest = 0.0

    for d in all_dates:
        if d in real_by_date:
            last_real = real_by_date[d]
        if d in backtest_by_date:
            last_backtest = backtest_by_date[d]
        real_aligned.append(last_real)
        backtest_aligned.append(last_backtest)

    scores = comparison["scores"]
    score_colors = {}
    for key, val in scores.items():
        if val >= 80:
            score_colors[key] = "#4CAF50"  # green
        elif val >= 60:
            score_colors[key] = "#FFC107"  # yellow
        else:
            score_colors[key] = "#F44336"  # red

    scores_html = "<table style='border-collapse: collapse; margin: 20px 0;'>"
    scores_html += "<tr><th style='border: 1px solid #ddd; padding: 8px; background: #305496; color: white; text-align: left;'>Metric</th>" \
                   "<th style='border: 1px solid #ddd; padding: 8px; background: #305496; color: white;'>Score</th></tr>"

    metric_names = {
        "trade_count": "Trade Count Similarity",
        "trade_timing": "Trade Timing Similarity",
        "trade_duration": "Trade Duration Similarity",
        "win_rate": "Win Rate Match",
        "profit_factor": "Profit Factor Match",
        "return_dd": "Return/DD Match",
        "max_dd": "Max Drawdown Match",
        "net_profit": "Net Profit Match",
    }

    for key, label in metric_names.items():
        val = scores.get(key, 0.0)
        color = score_colors.get(key, "#999")
        scores_html += f"<tr><td style='border: 1px solid #ddd; padding: 8px;'>{label}</td>" \
                       f"<td style='border: 1px solid #ddd; padding: 8px; background: {color}; color: white; text-align: center; font-weight: bold;'>{val:.1f}</td></tr>"

    scores_html += f"<tr style='background: #E8EAF6;'><td style='border: 1px solid #ddd; padding: 8px; font-weight: bold;'>Overall Closeness Score</td>" \
                   f"<td style='border: 1px solid #ddd; padding: 8px; background: #305496; color: white; text-align: center; font-weight: bold; font-size: 16px;'>{comparison['overall']:.1f}</td></tr>"
    scores_html += "</table>"

    stats_html = "<h3>Trade Statistics Comparison</h3>"
    stats_html += "<table style='border-collapse: collapse;'>"
    stats_html += "<tr><th style='border: 1px solid #ddd; padding: 8px; background: #305496; color: white;'>Metric</th>" \
                  "<th style='border: 1px solid #ddd; padding: 8px; background: #305496; color: white;'>Real</th>" \
                  "<th style='border: 1px solid #ddd; padding: 8px; background: #305496; color: white;'>Backtest</th></tr>"

    real_s = comparison["real_stats"]
    backtest_s = comparison["backtest_stats"]

    rows = [
        ("Trade Count", f"{real_s['count']}", f"{backtest_s['count']}"),
        ("Wins / Losses", f"{real_s['wins']} / {real_s['losses']}", f"{backtest_s['wins']} / {backtest_s['losses']}"),
        ("Win Rate", f"{real_s['win_rate']:.1f}%", f"{backtest_s['win_rate']:.1f}%"),
        ("Profit Factor", f"{real_s['profit_factor']:.2f}" if real_s['profit_factor'] != float('inf') else "inf",
                        f"{backtest_s['profit_factor']:.2f}" if backtest_s['profit_factor'] != float('inf') else "inf"),
        ("Net Profit", f"${real_s['net']:,.2f}", f"${backtest_s['net']:,.2f}"),
        ("Max Drawdown", f"${comparison['real_max_dd']:,.2f}", f"${comparison['backtest_max_dd']:,.2f}"),
        ("Return/DD", f"{comparison['real_ret_dd']:.2f}", f"{comparison['backtest_ret_dd']:.2f}"),
    ]

    for metric, real_val, backtest_val in rows:
        stats_html += f"<tr><td style='border: 1px solid #ddd; padding: 8px;'>{metric}</td>" \
                      f"<td style='border: 1px solid #ddd; padding: 8px; text-align: right;'>{real_val}</td>" \
                      f"<td style='border: 1px solid #ddd; padding: 8px; text-align: right;'>{backtest_val}</td></tr>"

    stats_html += "</table>"

    # ── Hour-of-day distribution chart ──────────────────────────────────────
    hour_real_pct = comparison.get("hour_real_pct", [0.0] * 24)
    hour_back_pct = comparison.get("hour_back_pct", [0.0] * 24)
    timing_html = (
        "<h2>Trade Entry Hour Distribution (UTC)</h2>"
        "<p style='font-size:12px;color:#666;margin:0 0 12px;'>"
        "Shows what percentage of trades were opened in each hour of the day (UTC). "
        "Closer bars = better timing similarity (Bhattacharyya coefficient).</p>"
        "<div class='chart-box' style='height:260px;'>"
        "<canvas id='hour_chart'></canvas></div>"
    )

    html_out = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html_lib.escape(title)}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f7f7f7; color: #222; }}
  .container {{ max-width: 1400px; margin: auto; background: white; padding: 24px;
                border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  h2 {{ font-size: 16px; margin: 24px 0 12px; color: #333; }}
  h3 {{ font-size: 14px; margin: 16px 0 8px; color: #555; }}
  .chart-box {{ position: relative; height: 400px; margin-bottom: 24px; }}
  table {{ font-size: 13px; }}
</style></head><body><div class="container">
<h1>{html_lib.escape(title)}</h1>

<h2>Closeness Score Summary</h2>
{scores_html}

<h2>Equity Curves Overlay</h2>
<div class="chart-box"><canvas id="eq_chart"></canvas></div>

{stats_html}

{timing_html}

<script>
const labels = {json.dumps(all_dates)};
const realData = {json.dumps(real_aligned)};
const backtestData = {json.dumps(backtest_aligned)};

new Chart(document.getElementById('eq_chart'), {{
  type: 'line',
  data: {{
    labels: labels,
    datasets: [
      {{
        label: 'Real Results',
        data: realData,
        borderColor: '#378ADD',
        backgroundColor: 'rgba(55, 138, 221, 0.05)',
        borderWidth: 2.5,
        fill: true,
        pointRadius: 2,
        pointHoverRadius: 5,
        tension: 0.2,
      }},
      {{
        label: 'Backtest',
        data: backtestData,
        borderColor: '#F44336',
        backgroundColor: 'rgba(244, 67, 54, 0.05)',
        borderWidth: 2.5,
        fill: true,
        pointRadius: 2,
        pointHoverRadius: 5,
        tension: 0.2,
      }},
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ position: 'top' }},
      tooltip: {{ 
        callbacks: {{ 
          label: c => c.dataset.label + ': $' + (c.parsed.y || 0).toLocaleString('en-US', {{ minimumFractionDigits: 2 }})
        }}
      }}
    }},
    scales: {{
      x: {{ ticks: {{ maxTicksLimit: 30, maxRotation: 45 }} }},
      y: {{ ticks: {{ callback: v => '$' + v.toLocaleString('en-US', {{ minimumFractionDigits: 0 }}) }} }}
    }}
  }}
}});

new Chart(document.getElementById('hour_chart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(list(range(24)))},
    datasets: [
      {{
        label: 'Real (%)',
        data: {json.dumps(hour_real_pct)},
        backgroundColor: 'rgba(55, 138, 221, 0.7)',
        borderColor: '#378ADD',
        borderWidth: 1,
      }},
      {{
        label: 'Backtest (%)',
        data: {json.dumps(hour_back_pct)},
        backgroundColor: 'rgba(244, 67, 54, 0.7)',
        borderColor: '#F44336',
        borderWidth: 1,
      }},
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'top' }},
      tooltip: {{
        callbacks: {{
          label: c => c.dataset.label + ': ' + c.parsed.y.toFixed(1) + '%'
        }}
      }}
    }},
    scales: {{
      x: {{ title: {{ display: true, text: 'Hour of Day (UTC)' }} }},
      y: {{ title: {{ display: true, text: '% of Trades' }}, beginAtZero: true,
             ticks: {{ callback: v => v + '%' }} }}
    }}
  }}
}});
</script></div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare real trading results against backtest expectations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--real-statement", required=True, metavar="PATH",
                    help="Real account statement (MT4 live or MT5 format)")
    ap.add_argument("--backtest", required=True, metavar="PATH",
                    help="Backtest report (MT4 tester or MT5 tester format)")
    ap.add_argument("--ticks-dir", required=True, metavar="PATH",
                    help="Folder containing tick CSV named SYMBOL_GMT+N_US-DST.csv")
    ap.add_argument("--symbol", required=True, metavar="SYMBOL",
                    help="Currency pair to compare (e.g., EURUSD, GBPUSD; required to filter deposits/withdrawals)")
    ap.add_argument("--magic", default="", metavar="N",
                    help="Optional magic-number filter for real/live statements (e.g., 170000).")
    ap.add_argument("--broker-gmt", type=int, default=2, metavar="N",
                    help="Broker timezone offset (default 2)")
    ap.add_argument("--tick-gmt", type=int, default=2, metavar="N",
                    help="Tick data timezone offset (default 2)")
    ap.add_argument("--title", default="Real vs Backtest Comparison",
                    help="Report title")
    ap.add_argument("--out-dir", default=".", metavar="PATH",
                    help="Output directory")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    try:
        magic_filter = _normalize_magic(args.magic)

        print("Loading real results statement…")
        real_trades, real_fmt = parse_statement(
            args.real_statement, args.broker_gmt, args.symbol, magic_filter
        )
        print(f"  {len(real_trades)} trades loaded ({real_fmt})")
        if not real_trades:
            print(f"  WARNING: No trades found for symbol {args.symbol}")

        print("Loading backtest report…")
        # Backtest formats typically do not carry magic numbers in this parser.
        backtest_trades, backtest_fmt = parse_statement(args.backtest, args.broker_gmt, args.symbol)
        print(f"  {len(backtest_trades)} trades loaded ({backtest_fmt})")

        tick_window_min_ts = None
        tick_window_max_ts = None
        if real_trades and backtest_trades:
            tick_window_min_ts = max(
                min(t["ts"] for t in real_trades),
                min(t["ts"] for t in backtest_trades),
            )
            tick_window_max_ts = min(
                max(t["close_ts"] for t in real_trades),
                max(t["close_ts"] for t in backtest_trades),
            )
            if tick_window_min_ts > tick_window_max_ts:
                print("ERROR: No overlapping date range between real and backtest trades.", flush=True)
                return 1

            window_start = datetime.fromtimestamp(tick_window_min_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            window_end = datetime.fromtimestamp(tick_window_max_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            print(f"  Requested tick window: {window_start} to {window_end}", flush=True)

        print("Loading tick data…")
        tick_file = resolve_tick_file(args.ticks_dir, args.symbol, args.tick_gmt)
        print(f"  Tick file: {tick_file}")
        ticks = load_ticks(tick_file, args.tick_gmt, tick_window_min_ts, tick_window_max_ts)
        print(f"  {len(ticks)} ticks loaded")

        # Find exact date range where all data is complete (tick data intersection)
        if ticks:
            tick_min_ts = ticks[0]["ts"]
            tick_max_ts = ticks[-1]["ts"]
        else:
            tick_min_ts = tick_max_ts = None

        if real_trades and backtest_trades and tick_min_ts is not None:
            real_min_ts = min(t["ts"] for t in real_trades)
            real_max_ts = max(t["close_ts"] for t in real_trades)
            backtest_min_ts = min(t["ts"] for t in backtest_trades)
            backtest_max_ts = max(t["close_ts"] for t in backtest_trades)

            # Determine intersection: latest start, earliest end
            compare_min_ts = max(real_min_ts, backtest_min_ts, tick_min_ts)
            compare_max_ts = min(real_max_ts, backtest_max_ts, tick_max_ts)

            if compare_min_ts > compare_max_ts:
                print("\nERROR: No overlapping date range between real, backtest, and tick data.")
                return 1

            # Filter to comparison window
            real_trades = [t for t in real_trades if t["close_ts"] >= compare_min_ts and t["ts"] <= compare_max_ts]
            backtest_trades = [t for t in backtest_trades if t["close_ts"] >= compare_min_ts and t["ts"] <= compare_max_ts]
            ticks = [t for t in ticks if compare_min_ts <= t["ts"] <= compare_max_ts]

            compare_start = datetime.fromtimestamp(compare_min_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            compare_end = datetime.fromtimestamp(compare_max_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            print(f"  Exact comparison window: {compare_start} to {compare_end}")
            print(f"  Real trades in window: {len(real_trades)}")
            print(f"  Backtest trades in window: {len(backtest_trades)}")
            print(f"  Ticks in window: {len(ticks)}")

        print("Building equity curves…")
        real_curves = build_equity_curve_from_ticks(real_trades, ticks)
        backtest_curves = build_equity_curve_from_ticks(backtest_trades, ticks)

        real_labels, real_bal, real_eq = curves_to_daily(real_curves)
        backtest_labels, backtest_bal, backtest_eq = curves_to_daily(backtest_curves)

        print("Computing statistics…")
        real_stats = compute_stats(real_trades)
        backtest_stats = compute_stats(backtest_trades)

        print("Computing comparison scores…")
        comparison = compute_comparison(real_stats, backtest_stats, real_trades, backtest_trades, real_eq, backtest_eq)

        print("\n" + "=" * 80)
        print(f"CLOSENESS SCORE: {comparison['overall']:.1f} / 100")
        print("=" * 80)
        for metric, label in [
            ("trade_count", "Trade Count Similarity"),
            ("trade_timing", "Trade Timing Similarity"),
            ("trade_duration", "Trade Duration Similarity"),
            ("win_rate", "Win Rate Match"),
            ("profit_factor", "Profit Factor Match"),
            ("return_dd", "Return/DD Match"),
            ("max_dd", "Max Drawdown Match"),
            ("net_profit", "Net Profit Match"),
        ]:
            print(f"  {label:<30} {comparison['scores'].get(metric, 0.0):>6.1f}")
        print("=" * 80)

        out_path = os.path.join(args.out_dir, "real_vs_backtest_comparison.html")
        write_comparison_report(real_labels, real_eq, backtest_labels, backtest_eq,
                                 comparison, out_path, args.title)
        print(f"\n✓ Report saved: {out_path}")

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
