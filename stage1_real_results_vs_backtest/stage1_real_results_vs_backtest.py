"""
stage1_real_results_vs_backtest.py — compare real trading results against a reference source.

Standalone tool (no dependencies on basket_analysis.py). Takes a real account
statement and one or more comparison sources, builds equity curves from tick data,
and scores how closely the real trading matched those reference results. Each
comparison source can be either a tester report or another live HTML/CSV export.

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
        --backtest backtest_or_live_report.htm ^
        --ticks-dir C:/ticks ^
        --symbol EURUSD ^
        --start-date "" ^
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


def _build_bar_filename(symbol: str, bar_gmt: int, timeframe: str = "M5") -> str:
    base = build_tick_filename(symbol, bar_gmt)
    stem, ext = os.path.splitext(base)
    return f"{stem}_{timeframe.upper()}{ext or '.csv'}"


def _resolve_bar_file(bars_dir: str, symbol: str, bar_gmt: int, timeframe: str = "M5") -> str:
    filename = _build_bar_filename(symbol, bar_gmt, timeframe=timeframe)
    path = os.path.join(bars_dir, filename)
    if os.path.exists(path):
        return path

    if os.path.isdir(bars_dir):
        symbol_prefix = f"{symbol.upper()}_GMT"
        matches = [
            name for name in os.listdir(bars_dir)
            if name.upper().startswith(symbol_prefix) and name.upper().endswith(".CSV") and "_M" in name.upper()
        ]
        if matches:
            matches.sort(key=lambda name: (0 if f"_{timeframe.upper()}.CSV" in name.upper() else 1, name.upper()))
            return os.path.join(bars_dir, matches[0])

    raise FileNotFoundError(
        f"Expected bar file '{filename}' not found in '{bars_dir}'"
    )


def _load_bar_points(path: str,
                     min_ts: Optional[int] = None,
                     max_ts: Optional[int] = None) -> List[Dict]:
    points: List[Dict] = []
    processed = 0
    skipped_outside_window = 0

    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row_num, row in enumerate(reader):
            processed += 1
            if len(row) < 5:
                continue
            try:
                if row_num == 0 and row[0].strip().lower() in ("unix_ts", "time", "date", "datetime"):
                    continue

                ts = int(float(row[0]))
                if min_ts is not None and ts < min_ts:
                    skipped_outside_window += 1
                    continue
                if max_ts is not None and ts > max_ts:
                    break

                close_price = float(row[4])
                points.append({"ts": ts, "bid": close_price, "ask": close_price})
            except (ValueError, IndexError):
                continue

    print(
        f"  Bar load complete: {processed:,} rows scanned, {len(points):,} kept"
        f" ({skipped_outside_window:,} before window)",
        flush=True,
    )
    return points


# ────────────────────────────────────────────────────────────────────────────
# File reading with encoding auto-detection
# ────────────────────────────────────────────────────────────────────────────
def _display_source_name(path: str) -> str:
    base = os.path.basename((path or "").strip())
    if not base:
        return "Source"
    stem, _ext = os.path.splitext(base)
    return stem or base


def _resolve_statement_path(path: str) -> str:
    candidate = (path or "").strip()
    if os.path.exists(candidate):
        return candidate
    lower = candidate.lower()
    alt = ""
    if lower.endswith(".html"):
        alt = candidate[:-1]
    elif lower.endswith(".htm"):
        alt = candidate + "l"
    if alt and os.path.exists(alt):
        print(f"  Using alternate statement path: {alt}", flush=True)
        return alt
    return candidate


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
    """Return one of: 'mt5_live', 'mt5_tester', 'mt4_tester', 'mt4_live'."""
    for row in rows:
        normalized = {c.strip().lower().rstrip(":") for c in row if c.strip()}
        if {"time", "position", "symbol", "type", "commission", "swap", "profit"}.issubset(normalized):
            return "mt5_live"

    if re.search(r">\s*Deals\s*<", html_text, re.IGNORECASE) and re.search(r"Direction", html_text, re.IGNORECASE):
        for row in rows:
            normalized = {c.strip().lower().rstrip(":") for c in row if c.strip()}
            if {"time", "deal", "symbol", "type", "direction"}.issubset(normalized):
                return "mt5_tester"
        for row in rows:
            if len(row) >= 13 and row[4].strip().lower() in ("in", "out"):
                return "mt5_tester"

    has_tester_open = any(
        len(row) >= 6 and row[2].strip().lower() in ("buy", "sell")
        for row in rows
    )
    has_tester_close = any(
        len(row) >= 6 and _is_mt4_tester_close_type(row[2])
        for row in rows
    )
    has_tester_header = any(
        {"#", "time", "type", "order", "size", "price", "profit", "balance"}.issubset(
            {_normalize_header_name(c) for c in row if c.strip()}
        )
        for row in rows
    )
    if "strategy tester report" in html_text.lower() and (has_tester_header or has_tester_open or has_tester_close):
        return "mt4_tester"
    if has_tester_header or (has_tester_open and has_tester_close):
        return "mt4_tester"

    mt4_live_headers = {
        "ticket", "open time", "type", "size", "item", "price",
        "close time", "commission", "swap", "profit",
    }
    for row in rows:
        normalized = {c.strip().lower().rstrip(":") for c in row if c.strip()}
        if mt4_live_headers.issubset(normalized):
            return "mt4_live"

    has_live_trade = any(
        len(row) >= 13
        and row[2].strip().lower() in ("buy", "sell")
        and re.fullmatch(r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}(?::\d{2})?", row[1].strip())
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


def _parse_cli_date(s: str, offset: timezone) -> int:
    s = (s or "").strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=offset).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date: {s!r}. Use YYYY.MM.DD or YYYY-MM-DD.")


def _parse_scale_arg(value: str) -> Optional[float]:
    s = (value or "").strip()
    if not s:
        return None
    factor = float(s)
    if factor <= 0:
        raise ValueError(f"Scale factor must be > 0, got {value!r}")
    return factor


def _base_basket_lot_size(trades: List[Dict]) -> float:
    """Use the smallest non-zero lot as the basket-entry baseline for scaling."""
    lots = sorted(
        abs(float(t.get("lots", 0.0)))
        for t in trades
        if abs(float(t.get("lots", 0.0))) > 0
    )
    return float(lots[0]) if lots else 0.0


def _scale_trades(trades: List[Dict], factor: float) -> List[Dict]:
    if not trades:
        return []
    if abs(factor - 1.0) < 1e-12:
        return [dict(t) for t in trades]

    scaled: List[Dict] = []
    for t in trades:
        row = dict(t)
        row["lots"] = float(row.get("lots", 0.0)) * factor
        for key in ("profit", "commission", "swap"):
            row[key] = float(row.get(key, 0.0)) * factor
        scaled.append(row)
    return scaled


def _resolve_scale_plan(real_trades: List[Dict],
                        bt_trades_list: List[List[Dict]],
                        real_label: str,
                        bt_names: List[str],
                        real_scale_value: str,
                        bt_scale_values: Optional[List[str]]) -> Tuple[float, List[float], List[Dict[str, object]]]:
    labels = [real_label] + bt_names
    raw_typicals = [_base_basket_lot_size(real_trades)] + [_base_basket_lot_size(bt) for bt in bt_trades_list]

    manual_inputs = [real_scale_value] + list(bt_scale_values or [])
    while len(manual_inputs) < len(labels):
        manual_inputs.append("")

    manual_factors = [_parse_scale_arg(v) for v in manual_inputs[:len(labels)]]
    effective_typicals = [
        raw * (manual if manual is not None else 1.0)
        for raw, manual in zip(raw_typicals, manual_factors)
    ]
    positive_effective = [v for v in effective_typicals if v > 0]
    target_typical = max(positive_effective) if positive_effective else 0.0

    factors: List[float] = []
    scale_rows: List[Dict[str, object]] = []
    for label, raw_typical, manual in zip(labels, raw_typicals, manual_factors):
        if manual is not None:
            factor = manual
            mode = "manual"
        elif raw_typical > 0 and target_typical > 0:
            factor = target_typical / raw_typical
            if 0.95 <= factor <= 1.05:
                factor = 1.0
            mode = "auto"
        else:
            factor = 1.0
            mode = "auto"

        scaled_typical = raw_typical * factor
        note = "no change" if abs(factor - 1.0) < 1e-12 else ("scaled up to match the largest base basket lot" if mode == "auto" else "manual override")
        factors.append(factor)
        scale_rows.append({
            "label": label,
            "mode": mode,
            "factor": factor,
            "typical_before": raw_typical,
            "typical_after": scaled_typical,
            "note": note,
        })

    return factors[0], factors[1:], scale_rows


def _parse_num(s: str) -> float:
    """Parse a number that may use space as thousands separator."""
    return float(s.replace(" ", "").replace(",", ""))


def _normalize_magic(value: str) -> str:
    """Keep only digits for robust magic-number comparisons."""
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _parse_mt4_live(rows, offset, symbol_filter, magic_filter: Optional[str] = None):
    header_idx, header_map = _find_mt4_live_header(rows)

    ticket_idx = header_map.get("ticket", 0)
    open_time_idx = header_map.get("open time", 1)
    type_idx = header_map.get("type", 2)
    size_idx = header_map.get("size", 3)
    symbol_idx = header_map.get("item", 4)
    open_price_idx = header_map.get("price", 5)
    close_time_idx = header_map.get("close time", 8)
    close_price_idx = header_map.get("close price", 9 if header_idx is None else close_time_idx + 1)
    commission_idx = header_map.get("commission", 10)
    swap_idx = header_map.get("swap", 12)
    profit_idx = header_map.get("profit", 13)

    start_row = (header_idx + 1) if header_idx is not None else 0
    trades = []
    for i in range(start_row, len(rows)):
        row = rows[i]
        if len(row) < 13:
            continue
        if len(row) <= max(type_idx, symbol_idx, open_time_idx, close_time_idx, open_price_idx):
            continue

        ttype = row[type_idx].strip().lower()
        if ttype not in ("buy", "sell"):
            continue

        symbol = row[symbol_idx].strip().upper()
        if symbol_filter:
            symbol_filter_upper = symbol_filter.upper()
            if symbol_filter_upper not in symbol:
                continue

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
                "ts": _parse_dt(row[open_time_idx], offset),
                "close_ts": _parse_dt(row[close_time_idx], offset),
                "price": _parse_num(row[open_price_idx]),
                "close_price": _parse_num(row[close_price_idx]),
                "lots": _parse_num(row[size_idx]),
                "profit": _parse_num(row[profit_idx]),
                "commission": _parse_num(row[commission_idx]) if commission_idx < len(row) and row[commission_idx] else 0.0,
                "swap": _parse_num(row[swap_idx]) if swap_idx < len(row) and row[swap_idx] else 0.0,
                "magic": magic_val,
                "ticket": row[ticket_idx].strip() if ticket_idx < len(row) else "",
            })
        except (ValueError, IndexError):
            continue
    return trades


def _is_mt4_tester_close_type(value: str) -> bool:
    token = re.sub(r"\s+", " ", (value or "").strip().lower())
    if not token:
        return False
    if token in (
        "close",
        "t/p",
        "s/l",
        "tp",
        "sl",
        "stop loss",
        "take profit",
        "close at stop",
        "close at limit",
    ):
        return True
    return token.startswith("close")


def _parse_mt4_tester(rows, offset):
    opens: Dict[int, Dict] = {}
    trades = []
    ignored_types = {"modify", "delete", "balance", "credit"}

    for row in rows:
        if len(row) < 6:
            continue

        ttype = row[2].strip().lower()
        if ttype in ("buy", "sell"):
            try:
                order = int(float(row[3]))
                opens[order] = {
                    "type": ttype,
                    "ts": _parse_dt(row[1], offset),
                    "price": _parse_num(row[5]),
                    "lots": _parse_num(row[4]),
                }
            except (ValueError, IndexError):
                pass
            continue

        if ttype in ignored_types or not _is_mt4_tester_close_type(ttype):
            continue

        try:
            order = int(float(row[3]))
            if order not in opens:
                continue
            if len(row) <= 8 or not row[8].strip():
                continue

            o = opens.pop(order)
            trades.append({
                "type": o["type"],
                "ts": o["ts"],
                "close_ts": _parse_dt(row[1], offset),
                "price": o["price"],
                "close_price": _parse_num(row[5]),
                "lots": o["lots"],
                "profit": _parse_num(row[8]),
                "commission": 0.0,
                "swap": 0.0,
            })
        except (ValueError, IndexError):
            continue
    return trades


def _normalize_header_name(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower()).rstrip(":")


def _find_mt4_live_header(rows) -> Tuple[Optional[int], Dict[str, int]]:
    required = {"ticket", "open time", "type", "size", "item", "price", "close time", "profit"}
    aliases = {
        "tax": "taxes",
        "s/l": "s/l",
        "t/p": "t/p",
    }
    for idx, row in enumerate(rows):
        header_map: Dict[str, int] = {}
        for col_idx, cell in enumerate(row):
            key = _normalize_header_name(cell)
            key = aliases.get(key, key)
            if not key:
                continue
            if key == "price" and "price" in header_map:
                header_map.setdefault("close price", col_idx)
                continue
            header_map.setdefault(key, col_idx)
        if required.issubset(header_map):
            return idx, header_map
    return None, {}


def _find_mt5_positions_header(rows) -> Tuple[Optional[int], Dict[str, int]]:
    required = {"time", "position", "symbol", "type", "commission", "swap", "profit"}
    for idx, row in enumerate(rows):
        header_map: Dict[str, int] = {}
        for col_idx, cell in enumerate(row):
            key = _normalize_header_name(cell)
            if key:
                header_map[key] = col_idx
        if required.issubset(header_map):
            return idx, header_map
    return None, {}


def _parse_mt5_live(rows, offset, symbol_filter, magic_filter: Optional[str] = None):
    """Parse MT5 live HTML 'Positions' table with one row per closed position."""
    header_idx, _ = _find_mt5_positions_header(rows)
    if header_idx is None:
        return []

    trades: List[Dict] = []
    for row in rows[header_idx + 1:]:
        if len(row) < 13:
            continue
        ttype = row[3].strip().lower() if len(row) > 3 else ""
        if ttype not in ("buy", "sell"):
            continue

        symbol = row[2].strip().upper()
        if symbol_filter and symbol_filter.upper() not in symbol:
            continue

        comment_idx = 4 if len(row) >= 14 and not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", (row[4] or "").strip()) else None
        volume_idx = 5 if comment_idx is not None else 4
        open_price_idx = volume_idx + 1
        close_time_idx = volume_idx + 4
        close_price_idx = volume_idx + 5
        commission_idx = volume_idx + 6
        swap_idx = volume_idx + 7
        profit_idx = volume_idx + 8

        if len(row) <= profit_idx or not row[close_time_idx].strip():
            continue

        comment_val = row[comment_idx] if comment_idx is not None and comment_idx < len(row) else ""
        magic_val = _normalize_magic(comment_val)
        if magic_filter and magic_val and magic_val != magic_filter:
            continue

        try:
            trades.append({
                "type": ttype,
                "ts": _parse_dt(row[0], offset),
                "close_ts": _parse_dt(row[close_time_idx], offset),
                "price": _parse_num(row[open_price_idx]),
                "close_price": _parse_num(row[close_price_idx]),
                "lots": _parse_num(row[volume_idx]),
                "profit": _parse_num(row[profit_idx]),
                "commission": _parse_num(row[commission_idx]) if row[commission_idx] else 0.0,
                "swap": _parse_num(row[swap_idx]) if row[swap_idx] else 0.0,
                "magic": magic_val,
            })
        except (ValueError, IndexError):
            continue

    return trades


def _find_mt5_deals_header(rows) -> Tuple[Optional[int], Dict[str, int]]:
    required = {"time", "deal", "symbol", "type", "direction"}
    for idx, row in enumerate(rows):
        header_map: Dict[str, int] = {}
        for col_idx, cell in enumerate(row):
            key = _normalize_header_name(cell)
            if key:
                header_map[key] = col_idx
        if required.issubset(header_map):
            return idx, header_map
    return None, {}


def _parse_mt5_tester(rows, offset, symbol_filter, magic_filter: Optional[str] = None):
    """MT5 Deals table: FIFO-match 'in' to 'out' deals using header-aware columns."""
    header_idx, header_map = _find_mt5_deals_header(rows)
    if header_idx is None:
        return []

    time_idx = header_map.get("time", 0)
    symbol_idx = header_map.get("symbol", 2)
    type_idx = header_map.get("type", 3)
    direction_idx = header_map.get("direction", 4)
    volume_idx = header_map.get("volume", 5)
    price_idx = header_map.get("price", 6)
    commission_idx = header_map.get("commission", 8)
    swap_idx = header_map.get("swap", 9)
    profit_idx = header_map.get("profit", 10)
    comment_idx = header_map.get("comment")

    open_fifo: List[Dict] = []
    trades: List[Dict] = []

    for row in rows[header_idx + 1:]:
        needed = [time_idx, symbol_idx, type_idx, direction_idx, volume_idx, price_idx]
        if len(row) <= max(needed):
            continue

        direction = row[direction_idx].strip().lower()
        if direction not in ("in", "out"):
            continue
        ttype = row[type_idx].strip().lower()
        if ttype not in ("buy", "sell"):
            continue

        symbol = row[symbol_idx].strip().upper()
        if symbol_filter:
            symbol_filter_upper = symbol_filter.upper()
            if symbol_filter_upper not in symbol:
                continue

        comment_val = row[comment_idx] if comment_idx is not None and comment_idx < len(row) else ""
        magic_val = _normalize_magic(comment_val)
        if magic_filter and magic_val and magic_val != magic_filter:
            continue

        try:
            ts = _parse_dt(row[time_idx], offset)
            volume = _parse_num(row[volume_idx])
            price = _parse_num(row[price_idx])
            commission = _parse_num(row[commission_idx]) if commission_idx is not None and commission_idx < len(row) and row[commission_idx] else 0.0
            swap = _parse_num(row[swap_idx]) if swap_idx is not None and swap_idx < len(row) and row[swap_idx] else 0.0
            profit = _parse_num(row[profit_idx]) if profit_idx is not None and profit_idx < len(row) and row[profit_idx] else 0.0
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
                "magic": magic_val,
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
                "magic": o.get("magic", magic_val),
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
    path = _resolve_statement_path(path)
    if path.lower().endswith(".csv"):
        trades = _parse_live_csv(path, broker_gmt, symbol_filter, magic_filter)
        trades.sort(key=lambda t: t["ts"])
        return trades, "live_csv"

    html_text = read_text_file(path)
    rows = _extract_rows(html_text)
    fmt = _detect_format(html_text, rows)
    offset = timezone(timedelta(hours=broker_gmt))

    if fmt == "mt5_live":
        trades = _parse_mt5_live(rows, offset, symbol_filter, magic_filter)
    elif fmt == "mt5_tester":
        trades = _parse_mt5_tester(rows, offset, symbol_filter, magic_filter)
    elif fmt == "mt4_tester":
        trades = _parse_mt4_tester(rows, offset)
    else:
        trades = _parse_mt4_live(rows, offset, symbol_filter, magic_filter)

    trades.sort(key=lambda t: t["ts"])
    return trades, fmt


def _parse_summary_number(value: str) -> float:
    text = (value or "").replace("\xa0", " ").strip()
    m = re.search(r"-?[0-9][0-9\s,]*\.?[0-9]*", text)
    return _parse_num(m.group(0)) if m else 0.0


def _parse_amount_pct_pair(value: str) -> Tuple[float, float]:
    text = (value or "").replace("\xa0", " ").strip()
    m = re.search(r"([-0-9\s,]*\.?[0-9]+)\s*\(([-0-9\s,]*\.?[0-9]+)%\)", text)
    if m:
        return abs(_parse_num(m.group(1))), abs(_parse_num(m.group(2)))
    m = re.search(r"([-0-9\s,]*\.?[0-9]+)%\s*\(([-0-9\s,]*\.?[0-9]+)\)", text)
    if m:
        return abs(_parse_num(m.group(2))), abs(_parse_num(m.group(1)))
    return 0.0, 0.0


def extract_backtest_report_summary(path: str) -> Dict:
    """Extract key MT5/MT4 report summary metrics directly from HTML reports."""
    try:
        resolved = _resolve_statement_path(path)
        if resolved.lower().endswith(".csv"):
            return {}
        html_text = read_text_file(resolved)
    except OSError:
        return {}

    rows = _extract_rows(html_text)
    summary: Dict[str, float] = {}

    for row in rows:
        for i in range(0, len(row) - 1, 2):
            label = row[i].strip().rstrip(":").lower()
            value = row[i + 1].strip()
            if not label or not value:
                continue
            if label == "initial deposit":
                summary["initial_deposit"] = _parse_summary_number(value)
            elif label == "total net profit":
                summary["report_net"] = _parse_summary_number(value)
            elif label == "equity drawdown maximal":
                amt, pct = _parse_amount_pct_pair(value)
                if amt > 0:
                    summary["report_max_dd"] = amt
                if pct > 0:
                    summary["report_max_dd_pct"] = pct
            elif label == "equity drawdown relative":
                amt, pct = _parse_amount_pct_pair(value)
                if "report_max_dd" not in summary and amt > 0:
                    summary["report_max_dd"] = amt
                if "report_max_dd_pct" not in summary and pct > 0:
                    summary["report_max_dd_pct"] = pct

    return summary


# ────────────────────────────────────────────────────────────────────────────
# Tick CSV loading
# ────────────────────────────────────────────────────────────────────────────
def _parse_tick_timestamp(ts_str: str, offset: timezone) -> Optional[int]:
    ts_str = (ts_str or "").strip()
    for fmt in (
        "%d.%m.%Y %H:%M:%S.%f",
        "%d.%m.%Y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y.%m.%d %H:%M:%S",
    ):
        try:
            dt = datetime.strptime(ts_str, fmt)
            return int(dt.replace(tzinfo=offset).timestamp())
        except ValueError:
            continue
    return None


def _peek_tick_time_bounds(path: str, tick_gmt: int) -> Tuple[Optional[int], Optional[int]]:
    """Read a small head/tail slice of a tick CSV to estimate its date bounds."""
    offset = timezone(timedelta(hours=tick_gmt))
    first_ts: Optional[int] = None
    last_ts: Optional[int] = None

    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        for row_num, row in enumerate(reader):
            if len(row) < 3:
                continue
            if row_num == 0 and row[0].lower() in ("time", "date", "datetime"):
                continue
            first_ts = _parse_tick_timestamp(row[0], offset)
            if first_ts is not None:
                break

    with open(path, "rb") as fh:
        try:
            fh.seek(-65536, os.SEEK_END)
        except OSError:
            fh.seek(0)
        tail_text = fh.read().decode("utf-8", errors="ignore")

    for line in reversed(tail_text.splitlines()):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        last_ts = _parse_tick_timestamp(parts[0], offset)
        if last_ts is not None:
            break

    return first_ts, last_ts


def load_ticks(path: str, tick_gmt: int,
               min_ts: Optional[int] = None,
               max_ts: Optional[int] = None,
               progress_every: int = 1_000_000) -> List[Dict]:
    """Load ticks from CSV. Expected format varies; try common patterns."""
    ticks: List[Dict] = []
    offset = timezone(timedelta(hours=tick_gmt))
    processed = 0
    skipped_outside_window = 0

    if min_ts is not None or max_ts is not None:
        first_ts, last_ts = _peek_tick_time_bounds(path, tick_gmt)
        if last_ts is not None and min_ts is not None and last_ts < min_ts:
            print("  Tick file ends before requested window; skipping full scan.", flush=True)
            print("  Tick load complete: 0 rows scanned, 0 kept (window outside file range)", flush=True)
            return []
        if first_ts is not None and max_ts is not None and first_ts > max_ts:
            print("  Tick file starts after requested window; skipping full scan.", flush=True)
            print("  Tick load complete: 0 rows scanned, 0 kept (window outside file range)", flush=True)
            return []

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

                ts = _parse_tick_timestamp(row[0], offset)
                if ts is None:
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
def _infer_profit_per_price(ttype: str,
                           open_price: float,
                           close_price: float,
                           reported_profit: float) -> Optional[float]:
    move = (close_price - open_price)
    if ttype == "sell":
        move = -move
    if abs(move) <= 1e-12 or abs(reported_profit) <= 1e-12:
        return None
    return reported_profit / move


def _default_profit_per_price(trades: List[Dict]) -> Optional[float]:
    vals: List[float] = []
    for t in trades:
        coeff = _infer_profit_per_price(
            str(t.get("type", "buy")),
            float(t.get("price", 0.0)),
            float(t.get("close_price", 0.0)),
            float(t.get("profit", 0.0)),
        )
        if coeff is not None and coeff > 0:
            vals.append(coeff)
    if not vals:
        return None
    vals.sort()
    mid = len(vals) // 2
    if len(vals) % 2 == 1:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def _calc_trade_pnl_from_prices(ttype: str,
                                lots: float,
                                open_price: float,
                                close_price: float,
                                profit_per_price: Optional[float] = None) -> float:
    move = (close_price - open_price)
    if ttype == "sell":
        move = -move
    if profit_per_price is not None:
        return move * profit_per_price
    pip_size = 0.01 if open_price > 20 else 0.0001
    pip_move = move / pip_size
    return pip_move * lots * 10.0


def _mid_price_at_ts(ticks: List[Dict], ts: int) -> Optional[float]:
    if not ticks:
        return None
    lo, hi = 0, len(ticks) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if ticks[mid]["ts"] < ts:
            lo = mid + 1
        else:
            hi = mid
    idx = min(max(lo, 0), len(ticks) - 1)
    tick = ticks[idx]
    return (tick["bid"] + tick["ask"]) / 2.0


def clip_trades_to_window(trades: List[Dict],
                          start_ts: Optional[int],
                          end_ts: Optional[int],
                          ticks: Optional[List[Dict]] = None) -> List[Dict]:
    """Clip trades to the comparison window so pre-window baskets don't distort equity.

    Trades that overlap the start/end boundaries are truncated and repriced to the
    nearest available tick in that window, which keeps the equity curve focused on
    the selected comparison period.
    """
    if not trades:
        return []
    if start_ts is None and end_ts is None:
        return [dict(t) for t in trades]

    clipped: List[Dict] = []
    default_profit_per_price = _default_profit_per_price(trades)
    for t in trades:
        if start_ts is not None and t["close_ts"] < start_ts:
            continue
        if end_ts is not None and t["ts"] > end_ts:
            continue

        row = dict(t)
        adjusted = False

        if start_ts is not None and row["ts"] < start_ts:
            start_mid = _mid_price_at_ts(ticks or [], start_ts)
            if start_mid is not None:
                row["price"] = start_mid
            row["ts"] = start_ts
            adjusted = True

        if end_ts is not None and row["close_ts"] > end_ts:
            end_mid = _mid_price_at_ts(ticks or [], end_ts)
            if end_mid is not None:
                row["close_price"] = end_mid
            row["close_ts"] = end_ts
            adjusted = True

        if row["close_ts"] < row["ts"]:
            continue

        if adjusted:
            profit_per_price = _infer_profit_per_price(
                str(t.get("type", "buy")),
                float(t.get("price", 0.0)),
                float(t.get("close_price", 0.0)),
                float(t.get("profit", 0.0)),
            )
            row["profit"] = _calc_trade_pnl_from_prices(
                str(row.get("type", "buy")),
                float(row.get("lots", 0.0)),
                float(row.get("price", 0.0)),
                float(row.get("close_price", 0.0)),
                profit_per_price=(profit_per_price if profit_per_price is not None else default_profit_per_price),
            )
            row["commission"] = 0.0
            row["swap"] = 0.0

        clipped.append(row)

    return clipped


def build_equity_curve_from_trade_events(trades: List[Dict]) -> List[Dict]:
    """Fallback step curve using realised trade closes when tick coverage is unavailable."""
    if not trades:
        return []

    realised = 0.0
    curves: List[Dict] = [{
        "ts": min(t["ts"] for t in trades),
        "bal": 0.0,
        "eq": 0.0,
    }]

    for t in sorted(trades, key=lambda x: (x["close_ts"], x["ts"])):
        realised += t["profit"] + t["commission"] + t["swap"]
        curves.append({
            "ts": t["close_ts"],
            "bal": round(realised, 2),
            "eq": round(realised, 2),
        })

    return curves


def build_equity_curve_from_ticks(trades: List[Dict], ticks: List[Dict],
                                    sample_every: int = 100) -> List[Dict]:
    """Build mark-to-market equity from ticks/bars, with a realised fallback if data is unavailable."""
    if not trades:
        return []
    if not ticks:
        return build_equity_curve_from_trade_events(trades)

    curves: List[Dict] = []
    realised = 0.0
    default_profit_per_price = _default_profit_per_price(trades)

    trades_sorted = sorted(trades, key=lambda t: t["ts"])
    tick_idx = 0
    active: List[Dict] = []

    sample_step = max(1, int(sample_every or 1))
    preview = ticks[: min(len(ticks), 1000)]
    is_bar_like = bool(preview) and all(abs(float(t.get("ask", 0.0)) - float(t.get("bid", 0.0))) < 1e-12 for t in preview)
    if is_bar_like:
        sample_step = 1

    # Sample every Nth point for real tick files, but use every bar point.
    for ti in range(0, len(ticks), sample_step):
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
            profit_per_price = _infer_profit_per_price(
                str(t.get("type", "buy")),
                float(t.get("price", 0.0)),
                float(t.get("close_price", t.get("price", 0.0))),
                float(t.get("profit", 0.0)),
            )
            unreal += _calc_trade_pnl_from_prices(
                str(t.get("type", "buy")),
                float(t.get("lots", 0.0)),
                float(t.get("price", 0.0)),
                float(mid),
                profit_per_price=(profit_per_price if profit_per_price is not None else default_profit_per_price),
            )

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

    if not curves:
        return build_equity_curve_from_trade_events(trades)

    final_ts = max(curves[-1]["ts"], trades_sorted[-1]["close_ts"])
    if curves[-1]["bal"] != round(realised, 2):
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


def curves_to_daily(curves: List[Dict], display_tz: Optional[timezone] = None) -> Tuple[List[str], List[float], List[float]]:
    """Extract daily balance and equity from curve points."""
    tzinfo = display_tz or timezone.utc
    by_day: Dict[str, Dict] = {}
    for c in curves:
        d = datetime.fromtimestamp(c["ts"], tz=tzinfo).strftime("%Y-%m-%d")
        by_day[d] = c
    days = sorted(by_day)
    return days, [by_day[d]["bal"] for d in days], [by_day[d]["eq"] for d in days]


def curves_to_chart_series(curves: List[Dict],
                           display_tz: Optional[timezone] = None,
                           max_points: int = 600) -> Tuple[List[str], List[float]]:
    """Downsample the raw mark-to-market curve for chart display without hiding intraday dips."""
    if not curves:
        return [], []
    tzinfo = display_tz or timezone.utc
    if len(curves) <= max_points:
        sample = curves
    else:
        step = max(1, len(curves) // max_points)
        sample = curves[::step]
        if sample[-1] is not curves[-1]:
            sample = sample + [curves[-1]]

    labels = [datetime.fromtimestamp(c["ts"], tz=tzinfo).strftime("%Y-%m-%d %H:%M") for c in sample]
    eq = [float(c["eq"]) for c in sample]
    return labels, eq


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


def _align_curve_series(
    labels_a: List[str],
    values_a: List[float],
    labels_b: List[str],
    values_b: List[float],
) -> Tuple[List[float], List[float]]:
    """Forward-fill two daily series onto a shared date axis."""
    all_dates = sorted(set(labels_a) | set(labels_b))
    if not all_dates:
        return [], []

    a_by_date = dict(zip(labels_a, values_a))
    b_by_date = dict(zip(labels_b, values_b))
    out_a: List[float] = []
    out_b: List[float] = []
    last_a = 0.0
    last_b = 0.0

    for d in all_dates:
        if d in a_by_date:
            last_a = a_by_date[d]
        if d in b_by_date:
            last_b = b_by_date[d]
        out_a.append(last_a)
        out_b.append(last_b)

    return out_a, out_b


def score_equity_curve(
    labels_a: List[str],
    eq_a: List[float],
    labels_b: List[str],
    eq_b: List[float],
) -> float:
    """Score similarity of two equity-curve shapes on a shared daily axis."""
    if not eq_a and not eq_b:
        return 100.0
    if not eq_a or not eq_b:
        return 0.0

    a_vals, b_vals = _align_curve_series(labels_a, eq_a, labels_b, eq_b)
    if not a_vals or not b_vals:
        return 0.0

    a0 = a_vals[0]
    b0 = b_vals[0]
    norm_a = [v - a0 for v in a_vals]
    norm_b = [v - b0 for v in b_vals]
    scale = max(max(abs(v) for v in norm_a), max(abs(v) for v in norm_b), 1.0)
    mae = sum(abs(x - y) for x, y in zip(norm_a, norm_b)) / (len(norm_a) * scale)
    return max(0.0, min(100.0, 100.0 * (1.0 - mae)))


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
    """Score timing similarity using hour-of-day distribution.

    The comparison is intentionally tolerant of a fixed timezone shift between
    export formats (for example, live CSV vs MT5 HTML). We therefore score the
    best circular alignment across the 24 hourly buckets rather than requiring
    the raw UTC buckets to line up exactly.
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

    best_bc = 0.0
    for shift in range(24):
        shifted_back = back_p[shift:] + back_p[:shift]
        bc = sum((real_p[i] * shifted_back[i]) ** 0.5 for i in range(24))
        if bc > best_bc:
            best_bc = bc

    return max(0.0, min(100.0, 100.0 * best_bc))


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
    """Score how closely two metrics match using a symmetric percentage difference."""
    if real == 0 and backtest == 0:
        return 100.0
    if real == 0 or backtest == 0:
        return 0.0

    baseline = max(abs(real), abs(backtest), 1e-9)
    diff_pct = 100.0 * abs(real - backtest) / baseline
    return max(0.0, 100.0 - diff_pct)


def compute_comparison(real_stats: Dict, backtest_stats: Dict,
                        real_trades: List[Dict], backtest_trades: List[Dict],
                        real_labels: List[str], real_eq: List[float],
                        backtest_labels: List[str], backtest_eq: List[float],
                        real_curve_dd: Optional[float] = None,
                        backtest_curve_dd: Optional[float] = None,
                        real_daily_dd: Optional[float] = None,
                        backtest_daily_dd: Optional[float] = None,
                        real_full_stats: Optional[Dict] = None,
                        backtest_full_stats: Optional[Dict] = None,
                        backtest_report_summary: Optional[Dict] = None) -> Dict:
    """Compute all comparison scores and aggregate into overall score."""
    scores = {}

    # Trade count similarity
    scores["trade_count"] = score_trade_count(real_stats["count"], backtest_stats["count"])

    # Trade timing similarity
    scores["trade_timing"] = score_trade_timing(real_trades, backtest_trades)

    # Trade duration similarity
    scores["trade_duration"] = score_duration(real_trades, backtest_trades)

    # Equity-curve shape similarity using tick-based mark-to-market where available
    scores["equity_curve"] = score_equity_curve(real_labels, real_eq, backtest_labels, backtest_eq)

    scores["win_rate"] = score_metric(real_stats["win_rate"], backtest_stats["win_rate"])

    real_pf = real_stats["profit_factor"]
    backtest_pf = backtest_stats["profit_factor"]
    if real_pf == float("inf") or backtest_pf == float("inf"):
        scores["profit_factor"] = 100.0 if (real_pf == float("inf")) == (backtest_pf == float("inf")) else 0.0
    else:
        scores["profit_factor"] = score_metric(real_pf, backtest_pf)

    real_max_dd = real_curve_dd if real_curve_dd is not None else max_drawdown(real_eq)
    backtest_max_dd = backtest_curve_dd if backtest_curve_dd is not None else max_drawdown(backtest_eq)
    real_daily_dd = real_daily_dd if real_daily_dd is not None else max_drawdown(real_eq)
    backtest_daily_dd = backtest_daily_dd if backtest_daily_dd is not None else max_drawdown(backtest_eq)
    real_ret_dd = real_stats["net"] / real_max_dd if real_max_dd > 0 else 0.0
    backtest_ret_dd = backtest_stats["net"] / backtest_max_dd if backtest_max_dd > 0 else 0.0
    scores["return_dd"] = score_metric(real_ret_dd, backtest_ret_dd)
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

    overall = sum(scores.values()) / len(scores) if scores else 0.0

    return {
        "scores": scores,
        "overall": overall,
        "real_stats": real_stats,
        "backtest_stats": backtest_stats,
        "real_max_dd": real_max_dd,
        "backtest_max_dd": backtest_max_dd,
        "real_daily_dd": real_daily_dd,
        "backtest_daily_dd": backtest_daily_dd,
        "real_ret_dd": real_ret_dd,
        "backtest_ret_dd": backtest_ret_dd,
        "hour_real_pct": hour_real_pct,
        "hour_back_pct": hour_back_pct,
        "real_full_stats": real_full_stats or real_stats,
        "backtest_full_stats": backtest_full_stats or backtest_stats,
        "backtest_report_summary": backtest_report_summary or {},
    }


# ────────────────────────────────────────────────────────────────────────────
# HTML report generation
# ────────────────────────────────────────────────────────────────────────────
# Per-backtest chart colours: (border, fill-alpha)
_BACKTEST_CHART_COLORS = [
        ("#F44336", "rgba(244,67,54,0.07)"),
        ("#4CAF50", "rgba(76,175,80,0.07)"),
        ("#FF9800", "rgba(255,152,0,0.07)"),
        ("#9C27B0", "rgba(156,39,176,0.07)"),
        ("#00BCD4", "rgba(0,188,212,0.07)"),
]


def write_comparison_report(
        real_label: str,
        real_labels: List[str],
        real_eq: List[float],
        backtest_entries: List[Tuple[str, List[str], List[float]]],
        comparisons: List[Dict],
        summary_entries: List[Tuple[str, Dict]],
        out_path: str,
        title: str,
        curve_note: str = "",
        scaling_rows: Optional[List[Dict[str, object]]] = None,
) -> None:
        """Generate HTML comparison report — supports one or more backtest series."""
        # Align all equity curves on a unified timeline
        all_date_sets: List[List[str]] = [real_labels] + [dates for _, dates, _ in backtest_entries]
        all_dates: List[str] = sorted(set(d for ds in all_date_sets for d in ds))
        real_by_date = dict(zip(real_labels, real_eq))
        bt_by_dates = [dict(zip(dates, eq)) for _, dates, eq in backtest_entries]

        real_aligned: List[float] = []
        bt_aligned: List[List[float]] = [[] for _ in backtest_entries]
        last_real = 0.0
        last_bt = [0.0] * len(backtest_entries)

        for d in all_dates:
                if d in real_by_date:
                        last_real = real_by_date[d]
                real_aligned.append(last_real)
                for i, bd in enumerate(bt_by_dates):
                        if d in bd:
                                last_bt[i] = bd[d]
                        bt_aligned[i].append(last_bt[i])

        # ── Build Chart.js dataset objects as plain strings (no f-string escaping needed) ────
        def _line_dataset(label: str, data_json: str, lc: str, fc: str) -> str:
                return (
                        "{\n"
                        f"        label: {json.dumps(label)},\n"
                        f"        data: {data_json},\n"
                        f"        borderColor: \"{lc}\",\n"
                        f"        backgroundColor: \"{fc}\",\n"
                        "        borderWidth: 2.5,\n"
                        "        fill: true,\n"
                        "        pointRadius: 2,\n"
                        "        tension: 0.2\n"
                        "      }"
                )

        eq_dataset_parts = [_line_dataset(real_label, json.dumps(real_aligned), "#378ADD", "rgba(55,138,221,0.05)")]
        for i, (bt_name, _, _) in enumerate(backtest_entries):
                lc, fc = _BACKTEST_CHART_COLORS[i % len(_BACKTEST_CHART_COLORS)]
                eq_dataset_parts.append(_line_dataset(bt_name, json.dumps(bt_aligned[i]), lc, fc))
        eq_datasets_js = ",\n      ".join(eq_dataset_parts)

        # ── Hour distribution datasets ────────────────────────────────────────────
        hour_real_pct = comparisons[0].get("hour_real_pct", [0.0] * 24) if comparisons else [0.0] * 24

        def _bar_dataset(label: str, data_json: str, bg: str, bc: str) -> str:
                return (
                        "{\n"
                        f"        label: {json.dumps(label)},\n"
                        f"        data: {data_json},\n"
                        f"        backgroundColor: \"{bg}\",\n"
                        f"        borderColor: \"{bc}\",\n"
                        "        borderWidth: 1\n"
                        "      }"
                )

        hour_ds_parts = [_bar_dataset(f"{real_label} (%)", json.dumps(hour_real_pct), "rgba(55,138,221,0.7)", "#378ADD")]
        for i, (bt_name, _, _) in enumerate(backtest_entries):
                lc, fc = _BACKTEST_CHART_COLORS[i % len(_BACKTEST_CHART_COLORS)]
                bg_solid = fc.replace("0.07", "0.7")
                bt_hour_pct = comparisons[i].get("hour_back_pct", [0.0] * 24)
                hour_ds_parts.append(_bar_dataset(f"{bt_name} (%)", json.dumps(bt_hour_pct), bg_solid, lc))
        hour_datasets_js = ",\n      ".join(hour_ds_parts)

        # ── Per-backtest closeness score blocks ───────────────────────────────────
        metric_names = {
                "trade_count": "Trade Count Similarity",
                "trade_timing": "Trade Timing Similarity",
                "trade_duration": "Trade Duration Similarity",
                "equity_curve": "Equity Curve Similarity",
                "win_rate": "Win Rate Match",
                "profit_factor": "Profit Factor Match",
                "return_dd": "Return/DD Match",
                "max_dd": "Max Drawdown Match",
                "net_profit": "Net Profit Match",
        }

        def _sc(v: float) -> str:
                return "#4CAF50" if v >= 80 else ("#FFC107" if v >= 60 else "#F44336")

        score_blocks = ""
        display_summaries = summary_entries or [
                (bt_name, cmp) for (bt_name, _, _), cmp in zip(backtest_entries, comparisons)
        ]
        for idx, (summary_name, cmp) in enumerate(display_summaries):
                hdr_color, _ = _BACKTEST_CHART_COLORS[idx % len(_BACKTEST_CHART_COLORS)]
                rows_html = ""
                for key, lbl in metric_names.items():
                        val = cmp["scores"].get(key, 0.0)
                        rows_html += (
                                f"<tr><td style='border:1px solid #ddd;padding:6px 8px;'>{lbl}</td>"
                                f"<td style='border:1px solid #ddd;padding:6px 8px;background:{_sc(val)};color:white;"
                                f"text-align:center;font-weight:bold;'>{val:.1f}</td></tr>"
                        )
                overall = cmp["overall"]
                rows_html += (
                        f"<tr style='background:#E8EAF6;'><td style='border:1px solid #ddd;padding:6px 8px;"
                        f"font-weight:bold;'>Overall Closeness Score</td>"
                        f"<td style='border:1px solid #ddd;padding:6px 8px;background:{hdr_color};color:white;"
                        f"text-align:center;font-weight:bold;font-size:15px;'>{overall:.1f}</td></tr>"
                )
                score_blocks += (
                        f"<div style='flex:1;min-width:300px;'>"
                        f"<h3 style='margin:0 0 8px;color:{hdr_color};'>{html_lib.escape(summary_name)}</h3>"
                        f"<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
                        f"<thead><tr>"
                        f"<th style='border:1px solid #ddd;padding:6px 8px;background:#305496;color:white;text-align:left;'>Metric</th>"
                        f"<th style='border:1px solid #ddd;padding:6px 8px;background:#305496;color:white;'>Score</th>"
                        f"</tr></thead><tbody>{rows_html}</tbody></table></div>"
                )
        scores_html = f"<div style='display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start;'>{score_blocks}</div>"
        curve_note_html = (
                f"<p style='font-size:12px;color:#666;margin:0 0 12px;'>{html_lib.escape(curve_note)}</p>"
                if curve_note else ""
        )

        scaling_html = ""
        if scaling_rows:
                rows = ""
                for row in scaling_rows:
                        rows += (
                                "<tr>"
                                f"<td style='border:1px solid #ddd;padding:6px 8px;text-align:left;'>{html_lib.escape(str(row.get('label', '')))}</td>"
                                f"<td style='border:1px solid #ddd;padding:6px 8px;text-align:center;'>{html_lib.escape(str(row.get('mode', '')))}</td>"
                                f"<td style='border:1px solid #ddd;padding:6px 8px;text-align:right;'>{float(row.get('factor', 1.0)):.2f}x</td>"
                                f"<td style='border:1px solid #ddd;padding:6px 8px;text-align:right;'>{float(row.get('typical_before', 0.0)):.4f}</td>"
                                f"<td style='border:1px solid #ddd;padding:6px 8px;text-align:right;'>{float(row.get('typical_after', 0.0)):.4f}</td>"
                                f"<td style='border:1px solid #ddd;padding:6px 8px;text-align:left;'>{html_lib.escape(str(row.get('note', '')))}</td>"
                                "</tr>"
                        )
                scaling_html = (
                        "<h2>Scaling Applied</h2>"
                        "<p style='font-size:12px;color:#666;margin:0 0 12px;'>"
                        "Blank scale inputs auto-detect the base basket-entry lot for each source and scale the smaller one up to the largest.</p>"
                        "<table style='border-collapse:collapse;font-size:13px;margin-bottom:16px;'>"
                        "<thead><tr>"
                        "<th style='border:1px solid #ddd;padding:6px 8px;background:#305496;color:white;'>Source</th>"
                        "<th style='border:1px solid #ddd;padding:6px 8px;background:#305496;color:white;'>Mode</th>"
                        "<th style='border:1px solid #ddd;padding:6px 8px;background:#305496;color:white;'>Factor</th>"
                        "<th style='border:1px solid #ddd;padding:6px 8px;background:#305496;color:white;'>Base Basket Lot Before</th>"
                        "<th style='border:1px solid #ddd;padding:6px 8px;background:#305496;color:white;'>Base Basket Lot After</th>"
                        "<th style='border:1px solid #ddd;padding:6px 8px;background:#305496;color:white;'>Note</th>"
                        f"</tr></thead><tbody>{rows}</tbody></table>"
                )

        # ── Stats comparison table (N+1 columns) ─────────────────────────────────
        def _th(s: str, bg: str = "#305496") -> str:
                return f"<th style='border:1px solid #ddd;padding:6px 8px;background:{bg};color:white;'>{s}</th>"

        def _td(s: str, align: str = "right") -> str:
                return f"<td style='border:1px solid #ddd;padding:6px 8px;text-align:{align};'>{s}</td>"

        hdr = _th("Metric", "#305496") + _th(html_lib.escape(real_label), "#305496")
        for idx2, (bt_name2, _, _) in enumerate(backtest_entries):
                hc, _ = _BACKTEST_CHART_COLORS[idx2 % len(_BACKTEST_CHART_COLORS)]
                hdr += _th(html_lib.escape(bt_name2), hc)

        real_s = comparisons[0]["real_stats"] if comparisons else {
                "count": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "profit_factor": 0.0, "net": 0.0
        }
        real_full_s = comparisons[0].get("real_full_stats", real_s) if comparisons else real_s
        bt_stats_list = [c["backtest_stats"] for c in comparisons]
        bt_full_stats_list = [c.get("backtest_full_stats", c["backtest_stats"]) for c in comparisons]
        bt_report_summaries = [c.get("backtest_report_summary", {}) for c in comparisons]

        def _pf(s: Dict) -> str:
                return "inf" if s.get("profit_factor", 0.0) == float("inf") else f"{s.get('profit_factor', 0.0):.2f}"

        stat_rows = [
                ("Trade Count (window)", str(real_s["count"]), [str(s["count"]) for s in bt_stats_list]),
                ("Wins / Losses (window)", f"{real_s['wins']} / {real_s['losses']}",
                 [f"{s['wins']} / {s['losses']}" for s in bt_stats_list]),
                ("Win Rate (window)", f"{real_s['win_rate']:.1f}%", [f"{s['win_rate']:.1f}%" for s in bt_stats_list]),
                ("Profit Factor (window)", _pf(real_s), [_pf(s) for s in bt_stats_list]),
                ("Net Profit (window)", f"${real_s['net']:,.2f}", [f"${s['net']:,.2f}" for s in bt_stats_list]),
                ("Max DD (window intraday)",
                 f"${comparisons[0]['real_max_dd']:,.2f}" if comparisons else "$0.00",
                 [f"${c['backtest_max_dd']:,.2f}" for c in comparisons]),
                ("Max DD (window daily view)",
                 f"${comparisons[0].get('real_daily_dd', 0.0):,.2f}" if comparisons else "$0.00",
                 [f"${c.get('backtest_daily_dd', 0.0):,.2f}" for c in comparisons]),
                ("Return/DD (window intraday)",
                 f"{comparisons[0]['real_ret_dd']:.2f}" if comparisons else "0.00",
                 [f"{c['backtest_ret_dd']:.2f}" for c in comparisons]),
                ("Net Profit (full file)",
                 f"${real_full_s.get('net', real_s['net']):,.2f}",
                 [f"${(summary.get('report_net', full_s.get('net', 0.0))):,.2f}" for summary, full_s in zip(bt_report_summaries, bt_full_stats_list)]),
        ]
        if any(summary.get("report_max_dd", 0.0) > 0 for summary in bt_report_summaries):
                stat_rows.append(
                        ("Max DD (source report)",
                         "—",
                         [f"${summary.get('report_max_dd', 0.0):,.2f}" if summary.get("report_max_dd", 0.0) > 0 else "—"
                          for summary in bt_report_summaries])
                )
        data_rows_html = ""
        for metric, r_val, bt_vals in stat_rows:
                row = _td(metric, "left") + _td(r_val)
                for bv in bt_vals:
                        row += _td(bv)
                data_rows_html += f"<tr>{row}</tr>"

        stats_html = (
                "<h3>Trade Statistics Comparison</h3>"
                "<p style='font-size:12px;color:#666;margin:0 0 10px;'>"
                "Window rows use only the shared comparison period and active symbol/magic filters. "
                "Where available, full-file/source-report rows are also shown below for reference."
                "</p>"
                "<table style='border-collapse:collapse;font-size:13px;'>"
                f"<thead><tr>{hdr}</tr></thead>"
                f"<tbody>{data_rows_html}</tbody></table>"
        )

        # ── Full HTML page ────────────────────────────────────────────────────────
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

{scaling_html}

<h2>Closeness Score Summary</h2>
{scores_html}

<h2>Equity Curves Overlay</h2>
{curve_note_html}
<div class="chart-box"><canvas id="eq_chart"></canvas></div>

{stats_html}

<h2>Trade Entry Hour Distribution (UTC)</h2>
<p style='font-size:12px;color:#666;margin:0 0 12px;'>
Percentage of trades opened each hour. Closer bars = better timing similarity.</p>
<div class="chart-box" style="height:260px;"><canvas id="hour_chart"></canvas></div>

<script>
const eq_labels = {json.dumps(all_dates)};
new Chart(document.getElementById('eq_chart'), {{
    type: 'line',
    data: {{
        labels: eq_labels,
        datasets: [
            {eq_datasets_js}
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
            {hour_datasets_js}
        ]
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'top' }},
            tooltip: {{ callbacks: {{ label: c => c.dataset.label + ': ' + c.parsed.y.toFixed(1) + '%' }} }}
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
        description="Compare real trading results against one or more reference sources (tester reports or live statements).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--real-statement", required=True, metavar="PATH",
                    help="Real account statement (MT4 live, MT5 live, or trades CSV)")
    ap.add_argument("--backtest", "--compare-source", action="append", dest="backtests", required=True,
                    metavar="PATH",
                    help="Comparison source file (tester report or live HTML/CSV). Repeatable.")
    ap.add_argument("--backtest-label", "--compare-label", action="append", dest="backtest_names",
                    metavar="LABEL",
                    help="Display label for each comparison source (same order; optional)")
    ap.add_argument("--backtest-magic", "--compare-magic", action="append", dest="backtest_magics",
                    metavar="N",
                    help="Optional magic-number filter for each comparison source when that source is a live statement. Repeatable.")
    ap.add_argument("--real-scale", default="", metavar="X",
                    help="Optional scale factor for the real statement. Leave blank to auto-detect.")
    ap.add_argument("--backtest-scale", "--compare-scale", action="append", dest="backtest_scales",
                    metavar="X",
                    help="Optional scale factor for each comparison source. Leave blank to auto-detect. Repeatable.")
    ap.add_argument("--ticks-dir", default="", metavar="PATH",
                    help="Optional tick folder containing SYMBOL_GMT+N_US-DST.csv for higher-resolution equity mapping.")
    ap.add_argument("--bars-dir", "--bar-dir", dest="bars_dir", default="", metavar="PATH",
                    help="Optional bar folder used for bar-based equity mapping before tick refinement.")
    ap.add_argument("--symbol", required=True, metavar="SYMBOL",
                    help="Currency pair to compare (e.g., EURUSD, GBPUSD; required to filter deposits/withdrawals)")
    ap.add_argument("--magic", default="", metavar="N",
                    help="Optional magic-number filter for real/live statements (e.g., 170000).")
    ap.add_argument("--broker-gmt", type=int, default=2, metavar="N",
                    help="Broker timezone offset (default 2)")
    ap.add_argument("--tick-gmt", type=int, default=2, metavar="N",
                    help="Tick data timezone offset (default 2)")
    ap.add_argument("--bar-gmt", type=int, default=2, metavar="N",
                    help="Bar data timezone offset (default 2)")
    ap.add_argument("--start-date", default="", metavar="YYYY.MM.DD",
                    help="Optional comparison start date. Leave blank to use the shared overlap automatically.")
    ap.add_argument("--title", default="Real vs Comparison Results",
                    help="Report title")
    ap.add_argument("--out-dir", default=".", metavar="PATH",
                    help="Output directory")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    try:
        magic_filter = _normalize_magic(args.magic)

        real_label = _display_source_name(args.real_statement)
        n_backtests = len(args.backtests)
        bt_magic_filters: List[str] = []
        for i in range(n_backtests):
            if args.backtest_magics and i < len(args.backtest_magics):
                bt_magic_filters.append(_normalize_magic(args.backtest_magics[i]))
            else:
                bt_magic_filters.append("")

        # Build display names for each comparison source
        bt_names: List[str] = []
        for i in range(n_backtests):
            if args.backtest_names and i < len(args.backtest_names):
                bt_names.append(args.backtest_names[i])
            else:
                bt_names.append(_display_source_name(args.backtests[i]))

        print("Loading real results statement…")
        real_trades, real_fmt = parse_statement(
            args.real_statement, args.broker_gmt, args.symbol, magic_filter
        )
        real_trades_full = [dict(t) for t in real_trades]
        print(f"  {len(real_trades)} trades loaded ({real_fmt})")
        if not real_trades:
            print(f"  WARNING: No trades found for symbol {args.symbol}")

        # Load all comparison sources upfront to determine the shared tick window
        all_bt_trades: List[List[Dict]] = []
        all_bt_trades_full: List[List[Dict]] = []
        bt_report_summaries: List[Dict] = []
        for i, bt_path in enumerate(args.backtests):
            print(f"Loading comparison source [{i + 1}/{n_backtests}]: {bt_path}…")
            bt_magic = bt_magic_filters[i] or None
            bt_trades_raw, bt_fmt = parse_statement(bt_path, args.broker_gmt, args.symbol, bt_magic)
            print(f"  {len(bt_trades_raw)} trades loaded ({bt_fmt})")
            if not bt_trades_raw:
                print(f"  WARNING: No trades found in {bt_path}")
            all_bt_trades.append(bt_trades_raw)
            all_bt_trades_full.append([dict(t) for t in bt_trades_raw])
            bt_report_summaries.append(extract_backtest_report_summary(bt_path))

        # Determine shared tick loading window
        tick_window_min_ts: Optional[int] = None
        tick_window_max_ts: Optional[int] = None
        non_empty_bts = [t for t in all_bt_trades if t]
        manual_start_ts: Optional[int] = None
        if args.start_date.strip():
            manual_start_ts = _parse_cli_date(args.start_date, timezone(timedelta(hours=args.broker_gmt)))

        if real_trades and non_empty_bts:
            real_min = min(t["ts"] for t in real_trades)
            real_max = max(t["close_ts"] for t in real_trades)
            bt_all_min = min(min(t["ts"] for t in bt) for bt in non_empty_bts)
            bt_all_max = max(max(t["close_ts"] for t in bt) for bt in non_empty_bts)
            tick_window_min_ts = max(real_min, bt_all_min)
            tick_window_max_ts = min(real_max, bt_all_max)

            if manual_start_ts is not None:
                tick_window_min_ts = max(tick_window_min_ts, manual_start_ts)

            if tick_window_min_ts > tick_window_max_ts:
                raise ValueError("No overlapping date range remains after applying the shared-history window and optional start date.")

            display_tz = timezone(timedelta(hours=args.broker_gmt))
            w_s = datetime.fromtimestamp(tick_window_min_ts, tz=display_tz).strftime("%Y-%m-%d")
            w_e = datetime.fromtimestamp(tick_window_max_ts, tz=display_tz).strftime("%Y-%m-%d")
            if manual_start_ts is not None:
                print(f"  Comparison window: {w_s} to {w_e} (start override applied)", flush=True)
            else:
                print(f"  Comparison window: {w_s} to {w_e} (shared overlap)", flush=True)
        elif manual_start_ts is not None:
            tick_window_min_ts = manual_start_ts

        print("Loading market data…")
        bar_points: List[Dict] = []
        ticks: List[Dict] = []
        curve_source = "trade-event"
        curve_note = (
            "No overlapping bar or tick coverage was available for this trade window, "
            "so the overlay falls back to realised trade-event equity steps."
        )

        if args.bars_dir.strip():
            try:
                bar_file = _resolve_bar_file(args.bars_dir, args.symbol, args.bar_gmt)
                print(f"  Bar file: {bar_file}")
                bar_points = _load_bar_points(bar_file, tick_window_min_ts, tick_window_max_ts)
                print(f"  {len(bar_points)} bar points loaded")
                if bar_points:
                    curve_source = "bar"
                    curve_note = (
                        f"Equity overlay first mapped the window using {len(bar_points):,} bar points "
                        "from the local archive."
                    )
            except Exception as exc:
                print(f"  WARNING: bar load skipped: {exc}")

        if args.ticks_dir.strip():
            try:
                tick_file = resolve_tick_file(args.ticks_dir, args.symbol, args.tick_gmt)
                print(f"  Tick file: {tick_file}")
                ticks = load_ticks(tick_file, args.tick_gmt, tick_window_min_ts, tick_window_max_ts)
                print(f"  {len(ticks)} ticks loaded")
                if ticks:
                    if bar_points:
                        curve_source = "bar+tick"
                        curve_note = (
                            f"Bar data was loaded first ({len(bar_points):,} bar points), and tick data was then applied "
                            f"for the final higher-resolution mark-to-market overlay from {len(ticks):,} ticks."
                        )
                    else:
                        curve_source = "tick"
                        curve_note = (
                            f"Equity overlay shows a downsampled intraday mark-to-market view built from {len(ticks):,} ticks."
                        )
            except Exception as exc:
                print(f"  WARNING: tick load skipped: {exc}")

        curve_min_ts = tick_window_min_ts
        curve_max_ts = tick_window_max_ts
        if bar_points:
            curve_min_ts = bar_points[0]["ts"]
            curve_max_ts = bar_points[-1]["ts"]
        if ticks:
            curve_min_ts = ticks[0]["ts"]
            curve_max_ts = ticks[-1]["ts"]

        # Clip all trades to the best available comparison window so older baskets do not distort the overlap.
        base_points = bar_points if bar_points else None
        real_trades = clip_trades_to_window(real_trades, curve_min_ts, curve_max_ts, base_points)
        print(f"  Real trades in comparison window: {len(real_trades)}")

        filtered_bt_trades: List[List[Dict]] = []
        for bt_trades_raw in all_bt_trades:
            bt_trades = clip_trades_to_window(bt_trades_raw, curve_min_ts, curve_max_ts, base_points)
            filtered_bt_trades.append(bt_trades)

        if ticks:
            real_trades = clip_trades_to_window(real_trades, curve_min_ts, curve_max_ts, ticks)
            filtered_bt_trades = [
                clip_trades_to_window(bt_trades, curve_min_ts, curve_max_ts, ticks)
                for bt_trades in filtered_bt_trades
            ]

        curve_points = ticks if ticks else bar_points
        print(f"  Equity mapping: {curve_source}")

        real_scale_factor, bt_scale_factors, scaling_rows = _resolve_scale_plan(
            real_trades,
            filtered_bt_trades,
            real_label,
            bt_names,
            args.real_scale,
            args.backtest_scales,
        )
        print("Scaling plan:")
        for row in scaling_rows:
            print(
                f"  {row['label']}: factor={float(row['factor']):.2f}x "
                f"({row['mode']}, base basket lot {float(row['typical_before']):.4f} -> {float(row['typical_after']):.4f})"
            )

        scaled_real_trades = _scale_trades(real_trades, real_scale_factor)
        print("Building real equity curve…")
        display_tz = timezone(timedelta(hours=args.broker_gmt))
        real_curves = build_equity_curve_from_ticks(scaled_real_trades, curve_points)
        real_chart_labels, real_chart_eq = curves_to_chart_series(real_curves, display_tz)
        real_labels_d, _real_bal, real_eq = curves_to_daily(real_curves, display_tz)
        real_stats = compute_stats(scaled_real_trades)
        real_full_stats = compute_stats(_scale_trades(real_trades_full, real_scale_factor))
        real_curve_dd = max_drawdown([float(c["eq"]) for c in real_curves])
        real_daily_dd = max_drawdown(real_eq)

        metric_labels_list = [
            ("trade_count", "Trade Count Similarity"),
            ("trade_timing", "Trade Timing Similarity"),
            ("trade_duration", "Trade Duration Similarity"),
            ("equity_curve", "Equity Curve Similarity"),
            ("win_rate", "Win Rate Match"),
            ("profit_factor", "Profit Factor Match"),
            ("return_dd", "Return/DD Match"),
            ("max_dd", "Max Drawdown Match"),
            ("net_profit", "Net Profit Match"),
        ]

        # Process each backtest independently
        backtest_entries: List[Tuple[str, List[str], List[float]]] = []
        comparisons: List[Dict] = []
        summary_entries: List[Tuple[str, Dict]] = []
        bt_series: List[Dict] = []

        for idx, (bt_path, bt_name) in enumerate(zip(args.backtests, bt_names)):
            print(f"\n-- Comparison Source {idx + 1}/{n_backtests}: {bt_name} --")
            bt_trades = filtered_bt_trades[idx]
            print(f"  Source trades in comparison window: {len(bt_trades)}")
            if idx < len(bt_scale_factors) and abs(bt_scale_factors[idx] - 1.0) > 1e-12:
                print(f"  Applied scaling to {bt_name}: {bt_scale_factors[idx]:.2f}x")

            scaled_bt_trades = _scale_trades(bt_trades, bt_scale_factors[idx] if idx < len(bt_scale_factors) else 1.0)
            bt_curves = build_equity_curve_from_ticks(scaled_bt_trades, curve_points)
            bt_chart_labels, bt_chart_eq = curves_to_chart_series(bt_curves, display_tz)
            bt_labels_d, _bt_bal, bt_eq = curves_to_daily(bt_curves, display_tz)
            bt_stats = compute_stats(scaled_bt_trades)
            bt_full_stats = compute_stats(_scale_trades(
                all_bt_trades_full[idx],
                bt_scale_factors[idx] if idx < len(bt_scale_factors) else 1.0,
            ))
            bt_curve_dd = max_drawdown([float(c["eq"]) for c in bt_curves])
            bt_daily_dd = max_drawdown(bt_eq)
            bt_report_summary = bt_report_summaries[idx] if idx < len(bt_report_summaries) else {}

            comparison = compute_comparison(
                real_stats,
                bt_stats,
                scaled_real_trades,
                scaled_bt_trades,
                real_labels_d,
                real_eq,
                bt_labels_d,
                bt_eq,
                real_curve_dd=real_curve_dd,
                backtest_curve_dd=bt_curve_dd,
                real_daily_dd=real_daily_dd,
                backtest_daily_dd=bt_daily_dd,
                real_full_stats=real_full_stats,
                backtest_full_stats=bt_full_stats,
                backtest_report_summary=bt_report_summary,
            )
            print(f"  CLOSENESS SCORE: {comparison['overall']:.1f} / 100")
            for m_key, m_lbl in metric_labels_list:
                print(f"    {m_lbl:<30} {comparison['scores'].get(m_key, 0.0):>6.1f}")

            backtest_entries.append((bt_name, bt_chart_labels, bt_chart_eq))
            comparisons.append(comparison)
            summary_entries.append((f"{real_label} vs {bt_name}", comparison))
            bt_series.append({
                "name": bt_name,
                "trades": scaled_bt_trades,
                "stats": bt_stats,
                "labels": bt_labels_d,
                "eq": bt_eq,
            })

        if len(bt_series) >= 2:
            for i in range(len(bt_series)):
                for j in range(i + 1, len(bt_series)):
                    lhs = bt_series[i]
                    rhs = bt_series[j]
                    pair_cmp = compute_comparison(
                        lhs["stats"],
                        rhs["stats"],
                        lhs["trades"],
                        rhs["trades"],
                        lhs["labels"],
                        lhs["eq"],
                        rhs["labels"],
                        rhs["eq"],
                    )
                    print(f"\nPAIRWISE CLOSENESS: {lhs['name']} vs {rhs['name']} = {pair_cmp['overall']:.1f} / 100")
                    summary_entries.append((f"{lhs['name']} vs {rhs['name']}", pair_cmp))

        out_path = os.path.join(args.out_dir, "real_vs_backtest_comparison.html")
        write_comparison_report(
            real_label,
            real_chart_labels,
            real_chart_eq,
            backtest_entries,
            comparisons,
            summary_entries,
            out_path,
            args.title,
            curve_note=curve_note,
            scaling_rows=scaling_rows,
        )
        print(f"\nReport saved: {out_path}")

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
