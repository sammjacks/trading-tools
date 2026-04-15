#!/usr/bin/env python3
"""
MT5 running-account risk flow (v2)

Flow:
1) Detect active strategy groups from MT5 deals/history CSV or MT5 terminal logs.
2) Ignore helper/non-trading EAs such as FxBlue, SpaceTracker, and Update-Robots.
3) Optionally inspect an MT5 terminal folder, detect candidate EAs, and
    auto-run Strategy Tester backtests for detected strategies.
4) Compile detected/generate backtests into a portfolio risk report
    (HTML + xlsx via stage2 portfolio compiler).

This is MT5-first and designed for later MT4 adaptation.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


IGNORE_EA_TOKENS = (
    "fxblue", "fx blue", "publisher",
    "spacetracker", "space tracker",
    "update-robot", "update robot", "update-robots", "update robots",
)
TIME_FORMATS = (
    "%Y.%m.%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y-%m-%d %H:%M",
)


@dataclass
class TradeRow:
    ts: datetime
    symbol: str
    magic: str
    comment: str
    volume: float
    profit: float
    side: str


@dataclass
class StrategyAggregate:
    symbol: str
    magic: str
    comment_hint: str
    trades: int = 0
    lots_sum: float = 0.0
    profit_sum: float = 0.0
    first_ts: Optional[datetime] = None
    last_ts: Optional[datetime] = None
    assigned_ea: str = ""
    backtest_html: str = ""
    period: str = ""  # detected MT5 timeframe, e.g. H1, M15
    live_inputs: Dict[str, str] = field(default_factory=dict)

    def ingest(self, row: TradeRow) -> None:
        self.trades += 1
        self.lots_sum += row.volume
        self.profit_sum += row.profit
        if self.first_ts is None or row.ts < self.first_ts:
            self.first_ts = row.ts
        if self.last_ts is None or row.ts > self.last_ts:
            self.last_ts = row.ts
        if not self.comment_hint and row.comment:
            self.comment_hint = row.comment


class UserInputError(Exception):
    pass


def _clean_header(h: str) -> str:
    return " ".join((h or "").strip().lower().replace("_", " ").split())


def _pick_field(headers: Dict[str, str], candidates: Iterable[str]) -> Optional[str]:
    for c in candidates:
        if c in headers:
            return headers[c]
    return None


def _parse_time(value: str) -> Optional[datetime]:
    s = (value or "").strip()
    if not s:
        return None
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _contains_any_token(text: str, tokens: Tuple[str, ...]) -> bool:
    t = (text or "").lower()
    return any(tok in t for tok in tokens)


def _normalize_magic(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _safe_name(value: str) -> str:
    out = []
    for ch in value:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    cleaned = "".join(out).strip("_")
    return cleaned or "unknown"


def _find_terminal_exe(mt5_terminal_dir: Path, explicit: str) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.exists():
            return p
        raise UserInputError(f"terminal exe not found: {p}")

    direct = mt5_terminal_dir / "terminal64.exe"
    if direct.exists():
        return direct

    nested = list(mt5_terminal_dir.rglob("terminal64.exe"))
    if nested:
        return nested[0]

    raise UserInputError(
        f"Could not find terminal64.exe inside MT5 folder: {mt5_terminal_dir}"
    )


def _find_expert_root(mt5_terminal_dir: Path) -> Path:
    direct = mt5_terminal_dir / "MQL5" / "Experts"
    if direct.exists():
        return direct

    candidates = list(mt5_terminal_dir.rglob("MQL5/Experts"))
    if candidates:
        return candidates[0]

    raise UserInputError(
        "Could not find MQL5/Experts under the MT5 terminal folder."
    )


def _find_tester_profile_dir(mt5_terminal_dir: Path) -> Path:
    # MT5 usually resolves ExpertParameters files from MQL5\Profiles\Tester.
    p = mt5_terminal_dir / "MQL5" / "Profiles" / "Tester"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ea_candidates(expert_root: Path) -> List[Path]:
    all_ex5 = sorted(expert_root.rglob("*.ex5"))
    clean = []
    for p in all_ex5:
        name = p.stem.lower()
        rel = str(p).lower()
        if _contains_any_token(name, IGNORE_EA_TOKENS):
            continue
        if _contains_any_token(rel, IGNORE_EA_TOKENS):
            continue
        clean.append(p)
    return clean


def _magic_from_comment(comment: str) -> str:
    # Useful for comments like "EAName MAGIC 170000".
    s = (comment or "").lower()
    m = re.search(r"magic\s*[:=]?\s*(\d{3,})", s)
    return m.group(1) if m else ""


def _comment_group_key(comment: str) -> str:
    """Collapse per-trade comment noise into a stable EA/group key.

    Examples:
      FXHexaFlow_1,2 -> fxhexaflow
      FXHexaFlow_2,5 -> fxhexaflow
      MyEA MAGIC 170000 -> myea_magic_170000
    """
    s = (comment or "").strip()
    if not s:
        return "nocomment"
    # Drop basket-layer suffix after comma, then trim trailing _<number> blocks.
    s = s.split(",", 1)[0].strip()
    s = re.sub(r"(?:[_\-\s]*\d+)+$", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s.lower() or "nocomment"


def _match_name_key(value: str) -> str:
    """Normalize EA/comment names for fuzzy matching."""
    s = (value or "").strip()
    if not s:
        return ""
    s = s.split(",", 1)[0].strip()
    s = re.sub(r"(?:[_\-\s]*\d+)+$", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "", s)
    return s.lower()


def _canonical_input_key(raw_key: str) -> str:
    key = " ".join((raw_key or "").strip().lower().split())
    mapped = {
        "autorisk": "Auto_Risk",
        "risklimit": "RiskLimit",
        "startlot": "StartLot",
        "drawdown control": "DD_Control",
        "nfa": "NFA_Hide",
        "order_filling_type": "Order_Filling_Type",
        "order filling type": "Order_Filling_Type",
        "slippage": "Slippage",
    }
    if key in mapped:
        return mapped[key]
    # Keep a safe key for unknown inputs.
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", raw_key.strip())
    return cleaned.strip("_")


def _parse_live_inputs_blob(payload: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for token in payload.split(","):
        piece = token.strip()
        if not piece or ":" not in piece:
            continue
        k, v = piece.split(":", 1)
        key = _canonical_input_key(k)
        val = v.strip()
        if val.lower() in ("true", "false"):
            val = val.lower()
        out[key] = val
    return out


def _normalize_order_filling_value(v: str) -> str:
    s = (v or "").strip()
    u = s.upper()
    # Keep numeric values for MT5 .set compatibility with enum inputs.
    if u in ("0", "ORDER_FILLING_FOK", "FOK"):
        return "0"
    if u in ("1", "ORDER_FILLING_IOC", "IOC"):
        return "1"
    if u in ("2", "ORDER_FILLING_RETURN", "RETURN"):
        return "2"
    return s


def _detect_columns(fieldnames: List[str]) -> Dict[str, str]:
    canonical: Dict[str, str] = {}
    normalized = {_clean_header(h): h for h in fieldnames if h}

    canonical["time"] = _pick_field(
        normalized,
        ("time", "date", "open time", "close time", "time msc"),
    ) or ""
    canonical["symbol"] = _pick_field(normalized, ("symbol", "instrument")) or ""
    canonical["type"] = _pick_field(normalized, ("type", "deal type", "order type")) or ""
    canonical["volume"] = _pick_field(normalized, ("volume", "lots", "lot")) or ""
    canonical["profit"] = _pick_field(normalized, ("profit", "p/l", "net profit")) or ""
    canonical["comment"] = _pick_field(normalized, ("comment", "comments", "reason")) or ""
    canonical["magic"] = _pick_field(normalized, ("magic", "magic number", "expert id")) or ""

    missing = [k for k in ("time", "symbol", "type", "volume", "profit") if not canonical[k]]
    if missing:
        raise UserInputError(
            "Could not auto-detect required columns in MT5 CSV. "
            f"Missing: {', '.join(missing)}. Detected headers: {fieldnames}"
        )
    return canonical


def parse_mt5_terminal_logs(
    mt5_terminal_dir: Path,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    min_events: int,
) -> List[StrategyAggregate]:
    """Detect active strategies from MT5 terminal/MQL5 logs.

    We prioritize lines that include EA and symbol context, such as:
      - Experts: expert FXHexaFlow 8 (EURJPYp,H1) loaded successfully
      - MQL5:   FXHexaFlow 8 (EURJPYp,H1) OrderSend ...
    """
    logs_roots = [
        mt5_terminal_dir / "logs",
        mt5_terminal_dir / "MQL5" / "Logs",
    ]

    grouped: Dict[Tuple[str, str], StrategyAggregate] = {}
    latest_inputs: Dict[Tuple[str, str], Dict[str, str]] = {}
    scanned_files = 0
    scanned_lines = 0

    # Date-prefixed MT5 log files: YYYYMMDD.log
    date_name_re = re.compile(r"^(\d{8})\.log$", re.IGNORECASE)
    # Greedy EA-name capture is intentional here so we bind to the FINAL
    # (symbol,period) tuple even when the EA name itself contains brackets.
    experts_re = re.compile(r"expert\s+(.+)\s+\(([^,]+),([^\)]+)\)\s+loaded successfully", re.IGNORECASE)
    mql5_re = re.compile(r"\t([^\t]+)\s+\(([^,\)]+),([^\)]+)\)\t")
    inputs_re = re.compile(r"\t([^\t]+)\s+\(([^,\)]+),([^\)]+)\)\tEA version:.*", re.IGNORECASE)
    detected_periods: Dict[Tuple[str, str], List[str]] = {}

    def _file_in_range(p: Path) -> bool:
        m = date_name_re.match(p.name)
        if not m:
            return True
        try:
            fdt = datetime.strptime(m.group(1), "%Y%m%d")
        except ValueError:
            return True
        if start_dt and fdt < start_dt:
            return False
        if end_dt and fdt > end_dt:
            return False
        return True

    def _touch(ea_name: str, symbol: str, period_hint: str, ts_hint: Optional[datetime]) -> None:
        ea = (ea_name or "").strip()
        sym = (symbol or "").strip()
        if not ea or not sym:
            return
        if _contains_any_token(ea, IGNORE_EA_TOKENS):
            return
        key = (sym.upper(), ea.lower())
        row_ts = ts_hint or datetime.now()
        tr = TradeRow(
            ts=row_ts,
            symbol=sym,
            magic="",
            comment=ea,
            volume=0.01,
            profit=0.0,
            side="buy",
        )
        if key not in grouped:
            grouped[key] = StrategyAggregate(
                symbol=sym,
                magic="",
                comment_hint=ea,
            )
        grouped[key].ingest(tr)
        # Track period occurrences; we'll pick the most common at the end.
        if period_hint:
            detected_periods.setdefault(key, []).append(period_hint.strip())

    def _read_lines_with_fallback(path: Path) -> Iterable[str]:
        for enc in ("utf-16", "utf-8-sig", "cp1252", "latin-1"):
            try:
                with path.open("r", encoding=enc, errors="strict") as fh:
                    return fh.readlines()
            except UnicodeError:
                continue
            except OSError:
                return []
        with path.open("r", encoding="latin-1", errors="ignore") as fh:
            return fh.readlines()

    for root in logs_roots:
        if not root.exists():
            continue
        for lf in sorted(root.glob("*.log")):
            if not _file_in_range(lf):
                continue
            scanned_files += 1
            file_dt = None
            m = date_name_re.match(lf.name)
            if m:
                try:
                    file_dt = datetime.strptime(m.group(1), "%Y%m%d")
                except ValueError:
                    file_dt = None

            for line in _read_lines_with_fallback(lf):
                scanned_lines += 1
                mm = experts_re.search(line)
                if mm:
                    ea_name = mm.group(1).strip()
                    symbol = mm.group(2).strip()
                    period_hint = mm.group(3).strip()
                    _touch(ea_name, symbol, period_hint, file_dt)
                    continue

                mm2 = mql5_re.search(line)
                if mm2:
                    ea_name = mm2.group(1).strip()
                    symbol = mm2.group(2).strip()
                    period_hint = mm2.group(3).strip()
                    _touch(ea_name, symbol, period_hint, file_dt)

                mm3 = inputs_re.search(line)
                if mm3:
                    ea_name = mm3.group(1).strip()
                    symbol = mm3.group(2).strip()
                    period_hint = mm3.group(3).strip()
                    if not _contains_any_token(ea_name, IGNORE_EA_TOKENS):
                        key = (symbol.upper(), ea_name.lower())
                        payload = line.split("\t")[-1]
                        parsed = _parse_live_inputs_blob(payload)
                        if parsed:
                            latest_inputs[key] = parsed
                        if period_hint:
                            detected_periods.setdefault(key, []).append(period_hint.strip())

    detected = [s for s in grouped.values() if s.trades >= min_events]
    detected.sort(key=lambda s: (s.symbol, s.comment_hint.lower()))

    for s in detected:
        key = (s.symbol.upper(), s.comment_hint.lower())
        s.live_inputs = latest_inputs.get(key, {})
        periods_seen = detected_periods.get(key, [])
        if periods_seen:
            # Pick the most frequently seen period for this strategy.
            s.period = max(set(periods_seen), key=periods_seen.count)

    print(f"Scanned log files: {scanned_files}")
    print(f"Scanned log lines: {scanned_lines:,}")
    print(f"Detected strategy groups from logs (min_events={min_events}): {len(detected)}")
    with_inputs = sum(1 for s in detected if s.live_inputs)
    print(f"Detected groups with live EA input snapshots: {with_inputs}")
    return detected


def _row_to_trade(row: Dict[str, str], cols: Dict[str, str]) -> Optional[TradeRow]:
    ts = _parse_time(row.get(cols["time"], ""))
    if ts is None:
        return None

    symbol = (row.get(cols["symbol"], "") or "").strip()
    if not symbol:
        return None

    side = (row.get(cols["type"], "") or "").strip().lower()
    if "buy" not in side and "sell" not in side:
        return None

    try:
        volume = float((row.get(cols["volume"], "") or "0").strip())
    except ValueError:
        volume = 0.0

    try:
        profit = float((row.get(cols["profit"], "") or "0").strip())
    except ValueError:
        profit = 0.0

    comment = (row.get(cols["comment"], "") or "").strip() if cols["comment"] else ""
    magic = _normalize_magic((row.get(cols["magic"], "") or "").strip()) if cols["magic"] else ""

    return TradeRow(
        ts=ts,
        symbol=symbol,
        magic=magic,
        comment=comment,
        volume=volume,
        profit=profit,
        side=side,
    )


def parse_mt5_deals_csv(
    csv_path: Path,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    min_trades: int,
    grouping_mode: str = "auto",
) -> List[StrategyAggregate]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise UserInputError("MT5 CSV appears empty or missing headers.")

        cols = _detect_columns(reader.fieldnames)
        grouped_by_magic: Dict[Tuple[str, str], StrategyAggregate] = {}
        grouped_by_comment: Dict[Tuple[str, str], StrategyAggregate] = {}
        grouped_by_symbol: Dict[str, StrategyAggregate] = {}

        scanned = 0
        kept = 0
        skipped_ignored = 0

        for row in reader:
            scanned += 1
            tr = _row_to_trade(row, cols)
            if tr is None:
                continue

            if start_dt and tr.ts < start_dt:
                continue
            if end_dt and tr.ts > end_dt:
                continue

            if _contains_any_token(tr.comment, IGNORE_EA_TOKENS):
                skipped_ignored += 1
                continue

            magic_key = (tr.symbol, tr.magic or "nomagic")
            if magic_key not in grouped_by_magic:
                grouped_by_magic[magic_key] = StrategyAggregate(
                    symbol=tr.symbol,
                    magic=tr.magic,
                    comment_hint=tr.comment,
                )
            grouped_by_magic[magic_key].ingest(tr)

            comment_key = (tr.symbol, _comment_group_key(tr.comment))
            if comment_key not in grouped_by_comment:
                grouped_by_comment[comment_key] = StrategyAggregate(
                    symbol=tr.symbol,
                    magic="",
                    comment_hint=tr.comment,
                )
            grouped_by_comment[comment_key].ingest(tr)

            if tr.symbol not in grouped_by_symbol:
                grouped_by_symbol[tr.symbol] = StrategyAggregate(
                    symbol=tr.symbol,
                    magic="",
                    comment_hint=tr.comment,
                )
            grouped_by_symbol[tr.symbol].ingest(tr)
            kept += 1

    mode = (grouping_mode or "auto").strip().lower()
    if mode not in {"auto", "magic", "comment", "symbol"}:
        raise UserInputError(f"Unsupported grouping mode: {grouping_mode}")

    grouping_used = "magic"
    if mode == "magic":
        strategies = [s for s in grouped_by_magic.values() if s.trades >= min_trades]
    elif mode == "comment":
        grouping_used = "comment"
        strategies = [s for s in grouped_by_comment.values() if s.trades >= min_trades]
    elif mode == "symbol":
        grouping_used = "symbol"
        strategies = [s for s in grouped_by_symbol.values() if s.trades >= min_trades]
    else:
        strategies = [s for s in grouped_by_magic.values() if s.trades >= min_trades]
        if not strategies:
            grouping_used = "comment"
            strategies = [s for s in grouped_by_comment.values() if s.trades >= min_trades]
        if not strategies:
            grouping_used = "symbol"
            strategies = [s for s in grouped_by_symbol.values() if s.trades >= min_trades]

    strategies.sort(key=lambda s: (s.symbol, s.magic, -s.trades))

    print(f"Scanned rows: {scanned:,}")
    print(f"Kept trading rows: {kept:,}")
    print(f"Ignored helper rows (FxBlue/SpaceTracker/Update-Robots): {skipped_ignored:,}")
    print(
        f"Detected strategy groups (min_trades={min_trades}, grouping={grouping_used}): {len(strategies)}"
    )

    return strategies


def make_run_folder(out_root: Path, account_label: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / f"{stamp}_{_safe_name(account_label)}"
    for sub in (
        "inputs",
        "detected_strategies",
        "backtests",
        "portfolio",
        "portfolio/results",
        "comparison",
    ):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    return run_dir


def _find_repo_root(script_path: Path) -> Path:
    """Locate the trading-tools repo root even when this file is copied elsewhere."""
    env_root = (os.environ.get("TRADING_TOOLS_PROJECT_ROOT", "") or "").strip()
    if env_root:
        p = Path(env_root).expanduser().resolve()
        if (p / "stage3_portfolio_tick_check" / "portfolio_backtest.py").exists():
            return p

    start = script_path.resolve().parent
    for p in [start, *start.parents]:
        if (p / "stage3_portfolio_tick_check" / "portfolio_backtest.py").exists():
            return p

    return start


def _get_date_range_from_strategies(strategies: List[StrategyAggregate]) -> Tuple[str, str]:
    """Return (from_date, to_date) as 'YYYY.MM.DD' strings using earliest/latest trade times."""
    firsts = [s.first_ts for s in strategies if s.first_ts is not None]
    lasts = [s.last_ts for s in strategies if s.last_ts is not None]
    if not firsts or not lasts:
        raise UserInputError(
            "Cannot determine backtest date range: no strategies have trade timestamps."
        )
    return min(firsts).strftime("%Y.%m.%d"), max(lasts).strftime("%Y.%m.%d")


def _symbol_candidates(symbol: str) -> List[str]:
    s = (symbol or "").strip()
    if not s:
        return []
    out: List[str] = []

    def add(v: str) -> None:
        vv = v.strip()
        if vv and vv not in out:
            out.append(vv)

    add(s)
    add(re.sub(r"[^A-Za-z0-9]", "", s))
    # Common broker suffix variants (e.g. EURJPYp -> EURJPY).
    add(re.sub(r"[a-z]+$", "", s))
    add(re.sub(r"[^A-Z]+$", "", s.upper()))
    if len(s) >= 6 and s[:6].isalpha():
        add(s[:6])
        add(s[:6].upper())
    return [c for c in out if c]


def _resolve_symbol_data_file(base_dir: Path, symbol: str, suffix: str) -> Tuple[Path, str]:
    """Resolve a symbol file with fallback variants.

    Returns: (resolved_path, market_symbol_used_for_filename)
    """
    suffix = suffix or ""
    candidates = _symbol_candidates(symbol)

    for c in candidates:
        p = base_dir / f"{c}{suffix}"
        if p.exists():
            return p, c

    # Fallback scan: look for files ending with suffix that start with a candidate.
    if base_dir.exists():
        files = sorted(base_dir.glob(f"*{suffix}")) if suffix else sorted(base_dir.glob("*"))
        for c in candidates:
            for f in files:
                stem = f.name[:-len(suffix)] if suffix and f.name.endswith(suffix) else f.stem
                if stem.lower().startswith(c.lower()):
                    return f, stem

        # Last-resort: any CSV starting with the candidate symbol.
        csv_files = sorted(base_dir.glob("*.csv"))
        for c in candidates:
            for f in csv_files:
                if f.stem.lower().startswith(c.lower()):
                    return f, f.stem

    # No match found; return the direct expected path.
    return base_dir / f"{symbol}{suffix}", symbol


def write_detected_csv(
    path: Path,
    strategies: List[StrategyAggregate],
    backtest_dir: Optional[Path],
    backtest_suffix: str,
    bars_dir: Path,
    bars_suffix: str,
    default_scale: float,
    broker_gmt: int,
) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "strategy_id",
                "symbol",
                "market_symbol",
                "magic",
                "comment_hint",
                "trades",
                "lots_sum",
                "profit_sum",
                "first_trade",
                "last_trade",
                "scale",
                "broker_gmt",
                "assigned_ea",
                "live_inputs",
                "backtest_html",
                "bars_csv",
            ]
        )
        for s in strategies:
            strategy_id = f"{s.symbol}_MAGIC_{s.magic or 'NA'}"
            bt = Path(s.backtest_html) if s.backtest_html else (
                backtest_dir / f"{s.symbol}{backtest_suffix}" if backtest_dir else Path("")
            )
            bars, market_symbol = _resolve_symbol_data_file(bars_dir, s.symbol, bars_suffix)
            w.writerow(
                [
                    strategy_id,
                    s.symbol,
                    market_symbol,
                    s.magic,
                    s.comment_hint,
                    s.trades,
                    f"{s.lots_sum:.2f}",
                    f"{s.profit_sum:.2f}",
                    s.first_ts.strftime("%Y-%m-%d %H:%M:%S") if s.first_ts else "",
                    s.last_ts.strftime("%Y-%m-%d %H:%M:%S") if s.last_ts else "",
                    f"{default_scale:.4f}",
                    broker_gmt,
                    s.assigned_ea,
                    "; ".join(f"{k}={v}" for k, v in sorted(s.live_inputs.items())),
                    str(bt),
                    str(bars),
                ]
            )


def write_detected_html(path: Path, strategies: List[StrategyAggregate]) -> None:
    rows = []
    for s in strategies:
        rows.append(
            "<tr>"
            f"<td>{s.symbol}</td>"
            f"<td>{s.magic or ''}</td>"
            f"<td>{s.comment_hint}</td>"
            f"<td>{s.trades}</td>"
            f"<td>{s.lots_sum:.2f}</td>"
            f"<td>{s.profit_sum:.2f}</td>"
            f"<td>{s.assigned_ea}</td>"
            f"<td>{'; '.join(f'{k}={v}' for k, v in sorted(s.live_inputs.items()))}</td>"
            "</tr>"
        )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Detected Strategies</title>"
        "<style>body{font-family:Segoe UI,Arial,sans-serif;margin:20px;}"
        "table{border-collapse:collapse;width:100%;}"
        "th,td{border:1px solid #ccc;padding:6px 8px;font-size:13px;}"
        "th{background:#f5f5f5;text-align:left;}</style></head><body>"
        "<h2>Detected Strategies</h2>"
        "<table><thead><tr><th>Symbol</th><th>Magic</th><th>EA/Comment</th>"
        "<th>Events</th><th>Lots Sum</th><th>Profit Sum</th><th>Assigned EA</th><th>Live Inputs</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )
    path.write_text(html, encoding="utf-8")


def _write_expert_set_file(path: Path, inputs: Dict[str, str]) -> None:
    # MT5 .set supports simple key=value pairs for tester inputs.
    lines = [f"{k}={v}" for k, v in sorted(inputs.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _assign_eas_to_strategies(
    strategies: List[StrategyAggregate],
    candidates: List[Path],
    default_ea: str,
) -> None:
    if not strategies:
        return

    if default_ea:
        cand_names = {p.stem.lower(): p for p in candidates}
        chosen = cand_names.get(default_ea.lower())
        if not chosen:
            matches = [p for p in candidates if default_ea.lower() in p.stem.lower()]
            if matches:
                chosen = matches[0]
        if not chosen:
            raise UserInputError(
                f"Default EA '{default_ea}' not found among terminal EAs."
            )
        for s in strategies:
            s.assigned_ea = str(chosen)
        return

    non_example_candidates = [
        p for p in candidates
        if not p.stem.lower().startswith("expert")
        and "sample" not in p.stem.lower()
        and "demo" not in p.stem.lower()
        and "test" not in p.stem.lower()
    ]

    if len(non_example_candidates) == 1:
        only = str(non_example_candidates[0])
        for s in strategies:
            s.assigned_ea = only
        return

    if len(candidates) == 1:
        only = str(candidates[0])
        for s in strategies:
            s.assigned_ea = only
        return

    def _candidate_score(strategy: StrategyAggregate, candidate: Path) -> int:
        score = 0
        stem = candidate.stem.lower()
        stem_key = _match_name_key(candidate.stem)
        rel = str(candidate).lower()
        comment = (strategy.comment_hint or "").lower()
        comment_key = _match_name_key(strategy.comment_hint)
        symbol_key = _match_name_key(strategy.symbol)
        period_key = (strategy.period or "").strip().lower()

        if comment and not comment.isdigit():
            if stem == comment or stem_key == comment_key:
                score += 100
            elif stem in comment or comment in stem:
                score += 60
            elif comment_key and stem_key and (comment_key in stem_key or stem_key in comment_key):
                score += 40

        if symbol_key and symbol_key in stem_key:
            score += 30
        if period_key and period_key in stem:
            score += 15
        if "portfolio" in stem_key:
            score += 10

        if any(tok in rel for tok in ("\\examples\\", "/examples/")):
            score -= 100
        if stem.startswith("expert"):
            score -= 40
        if any(tok in stem for tok in ("sample", "demo", "test")):
            score -= 20

        return score

    for s in strategies:
        matched = max(candidates, key=lambda c: _candidate_score(s, c), default=None)
        s.assigned_ea = str(matched) if matched else ""


def _print_strategy_plan(strategies: List[StrategyAggregate], fallback_period: str) -> None:
    print("\nPlanned MT5 backtests:")
    for idx, s in enumerate(strategies, start=1):
        ea_name = Path(s.assigned_ea).name if s.assigned_ea else "(unassigned)"
        period_name = (s.period or fallback_period or "H1").strip()
        magic_name = s.magic or "NA"
        print(
            f"  {idx}. EA={ea_name} | symbol={s.symbol} | timeframe={period_name} | magic={magic_name} | trades={s.trades}",
            flush=True,
        )


def _ea_relative_to_expert_root(ea_path: Path, expert_root: Path) -> str:
    try:
        rel = ea_path.resolve().relative_to(expert_root.resolve())
        # For [Tester] Expert=..., path is relative to MQL5/Experts,
        # e.g. Advisors\FXHexaFlow 8.ex5.
        return str(rel).replace("/", "\\")
    except ValueError:
        return ea_path.name


def _write_tester_ini(
    ini_path: Path,
    expert_value: str,
    symbol: str,
    period: str,
    model: int,
    from_date: str,
    to_date: str,
    report_path_no_ext: Path,
    deposit: float,
    leverage: int,
    use_local: bool,
    delay_ms: int,
    expert_parameters: Optional[str] = None,
    login: str = "",
    password: str = "",
    server: str = "",
) -> None:
    # MT5 tester execution mode: 0=no delay, 2=fixed delay.
    execution_mode = 2 if delay_ms and delay_ms > 0 else 0
    # Report stem must be relative in /portable mode. Absolute paths run tests
    # but native report export is skipped by MT5.
    report_path = report_path_no_ext.name
    lines = [
        "; Auto-generated by mt5_account_risk_flow.py",
    ]
    if login and server:
        lines.extend(
            [
                "[Common]",
                f"Login={login}",
                f"Password={password}",
                f"Server={server}",
            ]
        )

    lines.extend([
        "[Tester]",
        f"Expert={expert_value}",
        f"Symbol={symbol}",
        f"Period={period}",
        f"Model={model}",
        "Optimization=0",
        "OptimizationCriterion=0",
        f"ExecutionMode={execution_mode}",
        f"Execution={execution_mode}",
        f"Delay={delay_ms}",
        f"LastDelay={delay_ms}",
        f"Delays={delay_ms}",
        "DateEnable=1",
        f"FromDate={from_date}",
        f"ToDate={to_date}",
        f"Deposit={deposit}",
        f"Leverage={leverage}",
        f"Report={report_path}",
        "ReplaceReport=1",
        "ShutdownTerminal=1",
        "Visual=0",
        f"UseLocal={1 if use_local else 0}",
    ])
    if expert_parameters:
        lines.append(f"ExpertParameters={expert_parameters}")
    ini_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _guess_report_file(report_stem: Path) -> Optional[Path]:
    candidates = [
        report_stem.with_suffix(".htm"),
        report_stem.with_suffix(".html"),
        report_stem,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _copy_native_report_bundle(native_report: Path, report_file: Path) -> int:
    """Copy native MT5 report and companion image files into the run backtests folder.

    Returns the number of companion files copied (excluding the main .htm/.html).
    """
    import shutil as _shutil

    native_report_resolved = native_report.resolve()
    report_file_resolved = report_file.resolve()
    if native_report_resolved != report_file_resolved:
        _shutil.copy2(native_report, report_file)

    companion_exts = {".png", ".gif", ".jpg", ".jpeg", ".webp", ".bmp", ".svg"}
    src_dir = native_report.parent
    dst_dir = report_file.parent
    src_stem = native_report.stem
    dst_stem = report_file.stem
    copied_companions = 0

    for src in src_dir.glob(f"{src_stem}*"):
        if not src.is_file() or src.suffix.lower() not in companion_exts:
            continue
        suffix_part = src.name[len(src_stem) :]
        dst = dst_dir / f"{dst_stem}{suffix_part}"
        if src.resolve() == dst.resolve():
            continue
        _shutil.copy2(src, dst)
        copied_companions += 1

    return copied_companions


def _parse_trades_from_log(
    log_file: Path,
    symbol: str,
) -> Tuple[List[Dict], float, float, int, int]:
    """
    Parse MT5 tester log and extract closed-deal rows for a specific symbol.
    Returns: (trades_list, gross_profit, initial_deposit, winning_trades, losing_trades)
    """
    try:
        log_content = log_file.read_text(encoding="utf-16-le")
    except Exception:
        try:
            log_content = log_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return [], 0.0, 10000.0, 0, 0

    trades: List[Dict] = []
    winning_trades = 0
    losing_trades = 0
    total_profit = 0.0
    initial_deposit = 10000.0
    final_balance = None
    pending_deal: Optional[Dict[str, object]] = None
    open_positions: Dict[str, Dict[str, object]] = {}

    ts_match_re = re.compile(r"\b(?P<dt>\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\b")
    deal_match_re = re.compile(
        r"deal\s+#(?P<ticket>\d+)\s+(?P<side>buy|sell)\s+(?P<volume>[\d.]+)\s+"
        + re.escape(symbol)
        + r"\s+at\s+(?P<price>[\d.]+)\s+done",
        re.IGNORECASE,
    )
    close_match_re = re.compile(
        r"Position Close,\s+#(?P<position_ticket>\d+)\s+POSITION_TYPE_(?P<side>BUY|SELL)\s+"
        + re.escape(symbol)
        + r"\s+OP=(?P<open_price>[\d.]+).*?volume=(?P<volume>[\d.]+)",
        re.IGNORECASE,
    )

    for line in log_content.splitlines():
        if "final balance" in line.lower():
            match = re.search(r"final balance\s+([\d.]+)", line, re.IGNORECASE)
            if match:
                final_balance = float(match.group(1))
                total_profit = final_balance - initial_deposit
            continue

        if symbol not in line:
            continue

        ts_match = ts_match_re.search(line)
        event_dt = ts_match.group("dt") if ts_match else ""

        deal_match = deal_match_re.search(line)
        if deal_match:
            pending_deal = {
                "deal": deal_match.group("ticket"),
                "side": deal_match.group("side").lower(),
                "volume": float(deal_match.group("volume")),
                "price": float(deal_match.group("price")),
                "dt": event_dt,
            }
            open_positions.setdefault(
                deal_match.group("ticket"),
                {
                    "ticket": deal_match.group("ticket"),
                    "side": deal_match.group("side").lower(),
                    "volume": float(deal_match.group("volume")),
                    "price": float(deal_match.group("price")),
                    "dt": event_dt,
                },
            )
            continue

        close_match = close_match_re.search(line)
        if not close_match or not pending_deal:
            continue

        ticket = close_match.group("position_ticket")
        side = close_match.group("side").lower()
        volume = float(close_match.group("volume"))
        entry_price = float(close_match.group("open_price"))
        close_price = float(pending_deal["price"])
        open_info = open_positions.get(ticket)
        open_time = open_info.get("dt", "") if open_info else ""
        close_time = str(pending_deal.get("dt", ""))
        open_type = str(open_info.get("side", side) if open_info else side)
        open_ticket = str(open_info.get("ticket", ticket) if open_info else ticket)
        close_ticket = str(pending_deal.get("deal", ""))

        points = close_price - entry_price
        if side == "sell":
            points = -points
        profit = points * volume

        trades.append(
            {
                "type": open_type,
                "open_ticket": open_ticket,
                "close_ticket": close_ticket,
                "open_time": open_time,
                "close_time": close_time,
                "volume": volume,
                "entry_price": entry_price,
                "close_price": close_price,
                "profit": profit,
                "commission": 0.0,
                "swap": 0.0,
            }
        )
        if profit > 0:
            winning_trades += 1
        elif profit < 0:
            losing_trades += 1
        open_positions.pop(ticket, None)
        pending_deal = None

    if final_balance is None:
        total_profit = sum(trade["profit"] for trade in trades)

    return trades, total_profit, initial_deposit, winning_trades, losing_trades


def _generate_mt5_html_report(
    report_path: Path,
    symbol: str,
    ea_name: str,
    period: str,
    from_date: str,
    to_date: str,
    model: int,
    deposit: float,
    trades: List[Dict],
    total_profit: float,
    winning_trades: int,
    losing_trades: int,
) -> None:
    """
    Generate an HTML report with an MT5-style Deals table that the stage3
    parser can ingest directly (Direction in/out rows).
    """
    total_trades = winning_trades + losing_trades
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
    roi = (total_profit / deposit * 100) if deposit > 0 else 0.0

    deal_rows: List[Tuple[datetime, str, str]] = []

    def _parse_dt(value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y.%m.%d %H:%M:%S")
        except ValueError:
            return datetime.max

    for trade in trades:
        open_type = str(trade.get("type", "buy")).lower()
        out_type = "sell" if open_type == "buy" else "buy"
        open_ticket = trade.get("open_ticket", "")
        close_ticket = trade.get("close_ticket", "")
        open_time = trade.get("open_time", "")
        close_time = trade.get("close_time", "")
        lots = float(trade.get("volume", 0.0))
        entry_price = float(trade.get("entry_price", 0.0))
        close_price = float(trade.get("close_price", 0.0))
        commission = float(trade.get("commission", 0.0))
        swap = float(trade.get("swap", 0.0))
        profit = float(trade.get("profit", 0.0))

        open_row = f"""
        <tr>
            <td>{open_time}</td><td>{open_ticket}</td><td>{symbol}</td><td>{open_type}</td><td>in</td>
            <td>{lots:.2f}</td><td>{entry_price:.5f}</td><td>{open_ticket}</td><td>{commission:.2f}</td><td>{swap:.2f}</td><td>0.00</td><td></td><td>{ea_name}</td>
        </tr>"""

        close_row = f"""
        <tr>
            <td>{close_time}</td><td>{close_ticket}</td><td>{symbol}</td><td>{out_type}</td><td>out</td>
            <td>{lots:.2f}</td><td>{close_price:.5f}</td><td>{open_ticket}</td><td>{commission:.2f}</td><td>{swap:.2f}</td><td>{profit:.2f}</td><td></td><td>{ea_name}</td>
        </tr>"""

        deal_rows.append((_parse_dt(open_time), "0", open_row))
        deal_rows.append((_parse_dt(close_time), "1", close_row))

    deal_rows.sort(key=lambda x: (x[0], x[1]))
    deals_rows_html = "".join(row_html for _, _, row_html in deal_rows)

    html_content = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-16">
<title>{symbol} Backtest Report</title>
<style>
    body {{ font-family: Arial, Helvetica, sans-serif; margin: 10px; background-color: #FFFFFF; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
    th {{ background-color: #D3D3D3; padding: 5px; text-align: left; border: 1px solid #999; font-weight: bold; }}
    td {{ padding: 4px; border: 1px solid #CCC; }}
    tr:nth-child(even) {{ background-color: #F9F9F9; }}
    .header {{ background-color: #E0E0E0; padding: 10px; border: 1px solid #999; margin-bottom: 10px; }}
    .summary {{ background-color: #F0F0F0; padding: 10px; border: 1px solid #999; margin: 10px 0; }}
    .positive {{ color: #00AA00; font-weight: bold; }}
    .negative {{ color: #AA0000; font-weight: bold; }}
</style>
</head>
<body>
<div class="header">
    <h2>MetaTrader 5 Strategy Tester Report</h2>
    <p><b>Symbol:</b> {symbol} &nbsp; <b>Period:</b> {period} &nbsp; <b>EA:</b> {ea_name}</p>
    <p><b>Time Frame:</b> {from_date} - {to_date}</p>
    <p><b>Model:</b> {'Real Ticks' if model == 4 else f'Model {model}'} &nbsp; <b>Initial Deposit:</b> ${deposit:,.2f}</p>
</div>

<div class="summary">
    <table>
        <tr>
            <td><b>Total Trades</b></td>
            <td align="right">{total_trades}</td>
            <td><b>Winning Trades</b></td>
            <td align="right"><span class="positive">{winning_trades}</span></td>
            <td><b>Losing Trades</b></td>
            <td align="right"><span class="negative">{losing_trades}</span></td>
        </tr>
        <tr>
            <td><b>Win Rate</b></td>
            <td align="right">{win_rate:.2f}%</td>
            <td><b>Gross Profit</b></td>
            <td align="right"><span class="{'positive' if total_profit >= 0 else 'negative'}">${total_profit:,.2f}</span></td>
            <td><b>Return (%)</b></td>
            <td align="right"><span class="{'positive' if roi >= 0 else 'negative'}">{roi:.2f}%</span></td>
        </tr>
    </table>
</div>

<h3>Deals</h3>
<table>
    <thead>
        <tr>
            <th>Time</th>
            <th>Deal</th>
            <th>Symbol</th>
            <th>Type</th>
            <th>Direction</th>
            <th>Volume</th>
            <th>Price</th>
            <th>Order</th>
            <th>Commission</th>
            <th>Swap</th>
            <th>Profit</th>
            <th>Balance</th>
            <th>Comment</th>
        </tr>
    </thead>
    <tbody>
{deals_rows_html}
    </tbody>
</table>

<hr>
<p><small>Report generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
</body>
</html>"""

    # Use UTF-16 with BOM so browsers detect the document encoding the same way
    # they do for native MT5 reports.
    report_path.write_text(html_content, encoding="utf-16")


def _read_tester_log_tail(log_path: Path, start_offset: int) -> Tuple[int, List[str]]:
    if not log_path.exists():
        return start_offset, []

    try:
        raw = log_path.read_bytes()
    except OSError:
        return start_offset, []

    if start_offset >= len(raw):
        return len(raw), []

    chunk = raw[start_offset:]
    encoding = "utf-16"
    if not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encoding = "utf-16-le"

    try:
        text = chunk.decode(encoding, errors="ignore")
    except UnicodeDecodeError:
        text = chunk.decode("utf-8", errors="ignore")

    return len(raw), [line.strip() for line in text.splitlines() if line.strip()]


def _emit_tester_progress(log_path: Path, start_offset: int, last_line: str) -> Tuple[int, str]:
    next_offset, lines = _read_tester_log_tail(log_path, start_offset)
    progress_patterns = (
        "processing ",
        "history downloaded",
        "preliminary downloading",
        "ticks data begins",
        "testing of ",
        "connected",
        "authorized",
        "agent process started",
        "started with inputs",
        "test passed in",
        "final balance",
        "automatical testing started",
        "automatical testing finished",
        "total time from login to stop testing",
    )
    for line in lines:
        lower = line.lower()
        if line == last_line:
            continue
        if any(pattern in lower for pattern in progress_patterns):
            print(f"    MT5: {line}", flush=True)
            last_line = line
    return next_offset, last_line


def run_mt5_backtests(
    strategies: List[StrategyAggregate],
    mt5_terminal_dir: Path,
    terminal_exe: Path,
    run_dir: Path,
    period: str,
    model: int,
    from_date: str,
    to_date: str,
    deposit: float,
    leverage: int,
    use_local: bool,
    delay_ms: int,
    force_order_filling_type: str,
    use_live_settings: bool,
    backtests_subdir: str = "backtests",
    broker_login: str = "",
    broker_password: str = "",
    broker_server: str = "",
) -> None:
    expert_root = _find_expert_root(mt5_terminal_dir)
    tester_profile_dir = _find_tester_profile_dir(mt5_terminal_dir)
    backtests_dir = run_dir / backtests_subdir
    inis_dir = backtests_dir / "tester_ini"
    inputs_dir = backtests_dir / "tester_inputs"
    inis_dir.mkdir(parents=True, exist_ok=True)
    inputs_dir.mkdir(parents=True, exist_ok=True)

    total = len(strategies)
    filling_map = {
        "FOK": "0",
        "IOC": "1",
        "RETURN": "2",
    }
    forced_fill = filling_map.get(force_order_filling_type.strip().upper(), "")

    for i, s in enumerate(strategies, start=1):
        if not s.assigned_ea:
            raise UserInputError(
                f"No EA assigned for {s.symbol} magic={s.magic or 'NA'}"
            )

        ea_path = Path(s.assigned_ea)
        expert_value = _ea_relative_to_expert_root(ea_path, expert_root)
        # Use the period detected from live logs; fall back to the global default.
        effective_period = s.period or period
        report_stem = backtests_dir / f"{s.symbol}_MAGIC_{s.magic or 'NA'}"
        ini = inis_dir / f"tester_{i:02d}_{_safe_name(s.symbol)}_{s.magic or 'NA'}.ini"
        set_file = None
        set_file_name = ""
        effective_inputs = dict(s.live_inputs) if use_live_settings else {}
        if "Order_Filling_Type" in effective_inputs:
            effective_inputs["Order_Filling_Type"] = _normalize_order_filling_value(
                effective_inputs["Order_Filling_Type"]
            )

        # Only override order filling for EAs that actually use that parameter.
        if force_order_filling_type.strip().upper() != "AUTO" and "Order_Filling_Type" in effective_inputs:
            effective_inputs["Order_Filling_Type"] = forced_fill
        set_file = inputs_dir / f"inputs_{i:02d}_{_safe_name(s.symbol)}_{s.magic or 'NA'}.set"
        _write_expert_set_file(set_file, effective_inputs)
        # Duplicate into MT5 tester profile dir to maximize compatibility
        # with ExpertParameters lookup rules.
        mt5_set = tester_profile_dir / set_file.name
        mt5_set.write_text(set_file.read_text(encoding="utf-8"), encoding="utf-8")
        set_file = mt5_set
        set_file_name = mt5_set.name

        symbol_attempts = _symbol_candidates(s.symbol) or [s.symbol]
        tester_log = mt5_terminal_dir / "Tester" / "logs" / f"{datetime.now().strftime('%Y%m%d')}.log"
        report_file = report_stem.with_suffix(".htm")
        test_symbol_used = s.symbol
        run_start_time = time.time()
        last_return_code = 0

        for attempt_idx, test_symbol in enumerate(symbol_attempts, start=1):
            _write_tester_ini(
                ini_path=ini,
                expert_value=expert_value,
                symbol=test_symbol,
                period=effective_period,
                model=model,
                from_date=from_date,
                to_date=to_date,
                report_path_no_ext=report_stem,
                deposit=deposit,
                leverage=leverage,
                use_local=use_local,
                delay_ms=delay_ms,
                expert_parameters=set_file_name,
                login=broker_login,
                password=broker_password,
                server=broker_server,
            )

            suffix = "" if attempt_idx == 1 else f" [symbol retry {attempt_idx}/{len(symbol_attempts)}]"
            print(
                f"[{i}/{total}] Running MT5 backtest: symbol={test_symbol}, magic={s.magic or 'NA'}, "
                f"period={effective_period}, ea={ea_path.name}{suffix}",
                flush=True,
            )
            if set_file is not None:
                print(f"    Using live input set: {set_file}", flush=True)
            if broker_login and broker_server:
                print(
                    f"    MT5 account switch: login={broker_login}, server={broker_server}",
                    flush=True,
                )

            # MT5 is single-instance per data folder; a running UI instance can ignore /config.
            subprocess.run(
                ["taskkill", "/F", "/IM", "terminal64.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            cmd = [str(terminal_exe), "/portable", f"/config:{ini}"]
            tester_logs_dir = mt5_terminal_dir / "Tester" / "logs"
            tester_log = tester_logs_dir / f"{datetime.now().strftime('%Y%m%d')}.log"
            log_offset = tester_log.stat().st_size if tester_log.exists() else 0
            last_progress_line = ""
            run_start_time = time.time()
            completed = subprocess.Popen(cmd)
            completion_markers = (
                "automatical testing finished",
                "test passed in",
                "thread finished",
            )
            forced_close_sent = False
            while True:
                return_code = completed.poll()
                log_offset, last_progress_line = _emit_tester_progress(
                    tester_log, log_offset, last_progress_line
                )
                if return_code is not None:
                    completed = subprocess.CompletedProcess(cmd, return_code)
                    break

                progress_text = (last_progress_line or "").lower()
                if (not forced_close_sent) and any(marker in progress_text for marker in completion_markers):
                    try:
                        completed.terminate()
                        forced_close_sent = True
                        print("    MT5 tester finished; closing terminal process to continue workflow.", flush=True)
                    except Exception:
                        forced_close_sent = True
                time.sleep(2)

            last_return_code = completed.returncode
            success_from_log = any(marker in (last_progress_line or "").lower() for marker in completion_markers)
            if completed.returncode == 0 or (forced_close_sent and success_from_log):
                if completed.returncode != 0 and forced_close_sent and success_from_log:
                    print("    MT5 tester completed successfully based on tester log; continuing workflow.", flush=True)
                test_symbol_used = test_symbol
                break

            if attempt_idx < len(symbol_attempts):
                print(
                    f"    ⚠ MT5 rejected symbol '{test_symbol}' (exit {completed.returncode}); trying next symbol variant.",
                    flush=True,
                )
                continue

            raise UserInputError(
                f"MT5 tester failed for {s.symbol} magic={s.magic or 'NA'} (exit {last_return_code})."
            )

        if test_symbol_used != s.symbol:
            print(
                f"    ✓ Broker symbol mapped: requested={s.symbol} -> actual={test_symbol_used}",
                flush=True,
            )

        tester_log = mt5_terminal_dir / "Tester" / "logs" / f"{datetime.now().strftime('%Y%m%d')}.log"
        if not tester_log.exists():
            logs_dir = mt5_terminal_dir / "Tester" / "logs"
            if logs_dir.exists():
                recent_logs = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
                if recent_logs:
                    tester_log = recent_logs[0]

        if not tester_log.exists():
            raise UserInputError("Could not find tester log for report generation")

        # ── Try to use the native MT5-generated report ─────────────────────────
        native_report = _find_native_mt5_report(
            report_stem=report_stem,
            mt5_terminal_dir=mt5_terminal_dir,
            run_start_time=run_start_time,
        )

        if native_report is not None and _native_report_has_trade_rows(native_report):
            copied_companions = _copy_native_report_bundle(native_report, report_file)
            if native_report != report_file:
                print(f"    ✓ MT5 native report copied from {native_report.name}", flush=True)
            else:
                print(f"    ✓ MT5 native report: {report_file}", flush=True)
            if copied_companions:
                print(
                    f"    ✓ Copied {copied_companions} companion report image(s)",
                    flush=True,
                )
        else:
            reason = (
                "MT5 native report missing"
                if native_report is None else
                "MT5 native report was incomplete"
            )
            print(f"    ERROR: {reason}.", flush=True)
            raise UserInputError(
                f"{reason} for {s.symbol} magic={s.magic or 'NA'}. "
                f"Expected report near {report_file}; tester log: {tester_log}"
            )

        s.backtest_html = str(report_file.resolve())


def _native_report_has_trade_rows(report_path: Path) -> bool:
    """Heuristic: confirm the MT5 HTML report includes actual deal rows, not just the summary."""
    try:
        raw = report_path.read_bytes()
    except OSError:
        return False

    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16", errors="ignore")
    elif raw[:3] == b"\xef\xbb\xbf":
        text = raw[3:].decode("utf-8", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")

    if "Deals" not in text or "Direction" not in text:
        return False

    timestamps = re.findall(r"\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}", text)
    return len(timestamps) >= 3


def _find_native_mt5_report(
    report_stem: Path,
    mt5_terminal_dir: Path,
    run_start_time: float,
) -> Optional[Path]:
    """Locate the native MT5-generated report after a tester run.

    Checks in priority order:
    1. The path we told MT5 to use in the INI (report_stem.htm / .html).
    2. Recently created .htm/.html files inside the MT5 terminal tree.
    Returns the Path if found, otherwise None.
    """
    # 1. Check the expected output paths first.
    for ext in (".htm", ".html"):
        p = report_stem.with_suffix(ext)
        if p.exists():
            # Make sure it's actually newer than before the run.
            if p.stat().st_mtime >= run_start_time - 5:
                return p

    # 2. Check common MT5 output locations by exact report filename.
    for ext in (".htm", ".html"):
        for p in (
            mt5_terminal_dir / f"{report_stem.name}{ext}",
            mt5_terminal_dir / "Tester" / f"{report_stem.name}{ext}",
            mt5_terminal_dir / "MQL5" / "Files" / f"{report_stem.name}{ext}",
            mt5_terminal_dir / "MQL5" / "Reports" / f"{report_stem.name}{ext}",
        ):
            if p.exists():
                try:
                    if p.stat().st_mtime >= run_start_time - 5:
                        return p
                except OSError:
                    pass

    # 3. Scan known MT5 report locations for recently created files.
    search_roots = [
        mt5_terminal_dir / "MQL5" / "Reports",
        mt5_terminal_dir / "Tester",
        mt5_terminal_dir,
    ]
    candidates: List[Tuple[float, Path]] = []
    for root in search_roots:
        if not root.exists():
            continue
        for p in root.rglob("*.htm"):
            try:
                mtime = p.stat().st_mtime
                if mtime >= run_start_time - 5:
                    candidates.append((mtime, p))
            except OSError:
                pass
        for p in root.rglob("*.html"):
            try:
                mtime = p.stat().st_mtime
                if mtime >= run_start_time - 5:
                    candidates.append((mtime, p))
            except OSError:
                pass

    if candidates:
        # Return the most recently written one.
        candidates.sort(key=lambda t: t[0], reverse=True)
        return candidates[0][1]

    return None


def _build_strategy_args(
    detected_csv: Path,
    ticks_dir: Path,
    tick_suffix: str,
    require_ticks: bool,
    risk_mode_override: str = "",
) -> Tuple[List[str], List[str]]:
    def _parse_inputs_cell(cell: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for part in (cell or "").split(";"):
            token = part.strip()
            if not token or "=" not in token:
                continue
            k, v = token.split("=", 1)
            out[k.strip()] = v.strip()
        return out

    def _is_truthy(value: str) -> bool:
        v = (value or "").strip().lower()
        return v in {"1", "true", "yes", "on", "auto", "enabled"}

    args: List[str] = []
    warnings: List[str] = []
    with detected_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            symbol = (row.get("symbol") or "").strip()
            market_symbol = (row.get("market_symbol") or symbol).strip()
            bt = (row.get("backtest_html") or "").strip()
            bars = (row.get("bars_csv") or "").strip()
            scale = (row.get("scale") or "1.0").strip()
            gmt = (row.get("broker_gmt") or "2").strip()
            if not symbol or not bt or not bars:
                continue

            bt_path = Path(bt)
            if not bt_path.exists():
                warnings.append(
                    f"{symbol}: backtest report missing -> {bt_path}"
                )
                continue

            bars_path = Path(bars)
            if not bars_path.exists():
                bars_dir = bars_path.parent
                file_name = bars_path.name
                if file_name.lower().startswith(symbol.lower()):
                    guessed_suffix = file_name[len(symbol):]
                else:
                    guessed_suffix = ".csv"

                resolved_bars, resolved_symbol = _resolve_symbol_data_file(
                    bars_dir, symbol, guessed_suffix
                )
                if not resolved_bars.exists():
                    resolved_bars, resolved_symbol = _resolve_symbol_data_file(
                        bars_dir, symbol, ".csv"
                    )
                if resolved_bars.exists():
                    bars_path = resolved_bars
                    bars = str(resolved_bars)
                    market_symbol = resolved_symbol
            if not bars_path.exists():
                warnings.append(
                    f"{symbol}: bars CSV missing -> {bars_path}"
                )
                continue

            if require_ticks:
                tick_path = ticks_dir / f"{market_symbol}{tick_suffix}"
                if not tick_path.exists():
                    resolved_tick, resolved_tick_symbol = _resolve_symbol_data_file(
                        ticks_dir, market_symbol, tick_suffix
                    )
                    if resolved_tick.exists():
                        market_symbol = resolved_tick_symbol
                        tick_path = resolved_tick
                if not tick_path.exists():
                    warnings.append(
                        f"{symbol}: tick CSV missing -> {ticks_dir / f'{market_symbol}{tick_suffix}'}"
                    )
                    continue

            live_inputs = _parse_inputs_cell(row.get("live_inputs") or "")
            auto_risk = _is_truthy(live_inputs.get("Auto_Risk", ""))
            detected_mode = "AUTO_RISK" if auto_risk else "FIXED_LOT"
            risk_mode = (risk_mode_override or detected_mode).strip().upper() or detected_mode
            args.append(
                f'--strategy "{market_symbol}|{bt}|{bars}|{scale}|{gmt}|{market_symbol}|{risk_mode}"'
            )
    return args, warnings


def build_portfolio_command(
    repo_root: Path,
    detected_csv: Path,
    out_dir: Path,
    title: str,
    account_size: float,
    dd_tolerance: float,
    backtest_months: Optional[float],
    no_xlsx: bool,
    ticks_dir: Path,
    tick_suffix: str,
    tick_gmt: int,
    curve_sources: str,
    risk_mode_override: str = "",
) -> Tuple[str, List[str]]:
    portfolio_script = repo_root / "stage3_portfolio_tick_check" / "portfolio_backtest.py"
    if not portfolio_script.exists():
        raise UserInputError(f"Missing portfolio script: {portfolio_script}")

    source_tokens = [s.strip().lower() for s in (curve_sources or "").split(",") if s.strip()]
    if not source_tokens:
        source_tokens = ["bars"]
    valid_sources = {"bars", "ticks"}
    invalid_sources = [s for s in source_tokens if s not in valid_sources]
    if invalid_sources:
        raise UserInputError(
            f"Invalid --curve-sources value(s): {', '.join(invalid_sources)}. Use bars,ticks"
        )
    require_ticks = "ticks" in source_tokens

    strategy_args, warnings = _build_strategy_args(
        detected_csv,
        ticks_dir,
        tick_suffix,
        require_ticks,
        risk_mode_override=risk_mode_override,
    )
    if not strategy_args:
        raise UserInputError(
            "No strategies available to build command. Check detected CSV and path patterns."
        )

    cmd_parts = [
        "python",
        f'"{portfolio_script}"',
        f'--out-dir "{out_dir}"',
        f'--title "{title}"',
        f"--account-size {account_size}",
        f"--dd-tolerance {dd_tolerance}",
        f'--curve-sources "{','.join(source_tokens)}"',
        f'--tick-suffix "{tick_suffix}"',
        f"--tick-gmt {tick_gmt}",
    ]
    if require_ticks:
        cmd_parts.append(f'--ticks-dir "{ticks_dir}"')
    if backtest_months is not None:
        cmd_parts.append(f"--backtest-months {backtest_months}")
    if no_xlsx:
        cmd_parts.append("--no-xlsx")
    cmd_parts.extend(strategy_args)
    return " ".join(cmd_parts), warnings


def write_portfolio_cmd(path: Path, command: str) -> None:
    lines = [
        "@echo off",
        "setlocal",
        "cd /d \"%~dp0\"",
        "echo.",
        f"echo Running: {command}",
        "echo.",
        command,
        "echo.",
        "pause",
        "endlocal",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _copy_review_file(src: Path, dst: Path) -> None:
    import shutil as _shutil
    dst.parent.mkdir(parents=True, exist_ok=True)
    _shutil.copy2(src, dst)


def _match_set_for_report(report_file: Path, set_files: List[Path]) -> Optional[Path]:
    report_parts = [
        p for p in re.split(r"[_\W]+", report_file.stem.lower())
        if p and p != "magic"
    ]
    for sf in set_files:
        stem = sf.stem.lower()
        if report_parts and all(part in stem for part in report_parts):
            return sf
    return set_files[0] if len(set_files) == 1 else None


def create_review_bundle(run_dir: Path) -> Path:
    import shutil as _shutil

    bundle = run_dir / "review_bundle"
    if bundle.exists():
        _shutil.rmtree(bundle, ignore_errors=True)
    bundle.mkdir(parents=True, exist_ok=True)

    backtests_dir = run_dir / "backtests"
    set_files = list(backtests_dir.rglob("*.set")) if backtests_dir.exists() else []

    if backtests_dir.exists():
        report_files = sorted(backtests_dir.rglob("*.htm")) + sorted(backtests_dir.rglob("*.html"))
        for report in report_files:
            rel_parent = report.parent.relative_to(backtests_dir)
            rel_name = "_".join(rel_parent.parts).strip()
            prefix = _safe_name(rel_name) if rel_name else "full_period"
            _copy_review_file(report, bundle / f"{prefix}_{report.name}")

            for companion in sorted(report.parent.iterdir()):
                if not companion.is_file():
                    continue
                if companion.suffix.lower() not in {".png", ".gif", ".jpg", ".jpeg", ".webp"}:
                    continue
                if companion.stem.lower().startswith(report.stem.lower()):
                    _copy_review_file(companion, bundle / f"{prefix}_{companion.name}")

            matched_set = _match_set_for_report(report, set_files)
            if matched_set is not None:
                _copy_review_file(matched_set, bundle / f"{prefix}_{report.stem}.set")

    comparison_dir = run_dir / "comparison"
    if comparison_dir.exists():
        for item in sorted(comparison_dir.rglob("*")):
            if item.is_file() and item.suffix.lower() in {".htm", ".html", ".png", ".gif", ".jpg", ".jpeg", ".webp"}:
                _copy_review_file(item, bundle / f"comparison_{item.name}")

    portfolio_dir = run_dir / "portfolio"
    if portfolio_dir.exists():
        for item in sorted(portfolio_dir.rglob("*")):
            if not item.is_file():
                continue
            if item.suffix.lower() not in {".htm", ".html", ".xlsx", ".cmd"}:
                continue
            rel = item.relative_to(portfolio_dir)
            prefix = _safe_name("_".join(rel.parts[:-1])) or "portfolio"
            _copy_review_file(item, bundle / f"{prefix}_{item.name}")

    return bundle


def _parse_optional_date(value: str) -> Optional[datetime]:
    v = (value or "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            continue
    raise UserInputError(
        f"Invalid date '{value}'. Use one of: YYYY-MM-DD, YYYY.MM.DD, DD/MM/YYYY, MM/DD/YYYY"
    )


def _write_run_summary(path: Path, args: argparse.Namespace, run_dir: Path, detected_count: int) -> None:
    rows = [
        ["timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        ["account_label", args.account_label],
        ["mt5_csv", str(Path(args.mt5_csv).resolve())],
        ["run_dir", str(run_dir.resolve())],
        ["detected_strategies", str(detected_count)],
        ["account_size", str(args.account_size)],
        ["dd_tolerance", str(args.dd_tolerance)],
        ["start_date", args.start_date or ""],
        ["end_date", args.end_date or ""],
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["key", "value"])
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "MT5 running-account risk flow: detect active strategy groups from MT5 CSV/logs, "
            "create run folders, and build portfolio risk command(s)."
        )
    )
    ap.add_argument("--mt5-csv", default="", help="Optional path to MT5 deals/history CSV export.")
    ap.add_argument("--account-label", default="account", help="Short label for output folder naming.")
    ap.add_argument("--out-root", default="./runs", help="Root folder where dated run folders are created.")
    ap.add_argument("--start-date", default="", help="Optional filter start date (e.g. 2026-01-01).")
    ap.add_argument("--end-date", default="", help="Optional filter end date (e.g. 2026-04-13).")
    ap.add_argument("--min-trades", type=int, default=3, help="Minimum trades/events per detected strategy group.")
    ap.add_argument(
        "--detect-source",
        choices=("auto", "csv", "terminal_logs"),
        default="auto",
        help="Where to detect active strategies from.",
    )

    ap.add_argument("--backtest-dir", default="", help="Folder containing per-symbol backtest HTML files.")
    ap.add_argument("--backtest-suffix", default=".html", help="Backtest filename suffix appended to symbol.")
    ap.add_argument("--bars-dir", required=True, help="Folder containing per-symbol bars CSV files.")
    ap.add_argument("--bars-suffix", default="_GMT+2_US-DST_M5.csv", help="Bars filename suffix appended to symbol.")
    ap.add_argument("--ticks-dir", default="", help="Folder containing per-symbol tick CSV files (used when curve sources include ticks).")
    ap.add_argument("--tick-suffix", default="_GMT+2_US-DST.csv", help="Tick filename suffix appended to symbol.")
    ap.add_argument("--tick-gmt", type=int, default=2, help="Tick timezone offset for stage3 parser.")
    ap.add_argument("--curve-sources", default="bars", help="Comma-separated stage3 sources to run: bars,ticks. Default bars.")
    ap.add_argument("--default-scale", type=float, default=1.0, help="Default scale for each detected strategy.")
    ap.add_argument("--broker-gmt", type=int, default=2, help="Broker GMT offset used by portfolio parser.")

    ap.add_argument("--title", default="MT5 Running Account Risk Check", help="Portfolio report title.")
    ap.add_argument(
        "--detect-grouping",
        choices=("auto", "magic", "comment", "symbol"),
        default="auto",
        help="How to group CSV-detected trades into strategies before backtesting. Use 'symbol' when one EA uses many magic numbers.",
    )
    ap.add_argument(
        "--preview-plan",
        action="store_true",
        help="Show the planned EA, symbol, timeframe, and count before running any MT5 backtests.",
    )
    ap.add_argument("--account-size", type=float, default=10000.0, help="Account size used in risk metrics.")
    ap.add_argument("--dd-tolerance", type=float, default=10.0, help="Allowed drawdown percent for safety factor.")
    ap.add_argument("--backtest-months", type=float, default=None, help="Optional backtest months override.")
    ap.add_argument("--no-xlsx", action="store_true", help="Skip xlsx output in portfolio run.")
    ap.add_argument("--mt5-terminal-dir", default="", help="MT5 terminal root folder to inspect and run tester from.")
    ap.add_argument("--mt5-terminal-exe", default="", help="Explicit path to terminal64.exe (optional).")
    ap.add_argument("--default-ea", default="", help="Optional EA name to force (stem match, e.g. HexaFlow8).")
    ap.add_argument("--tester-period", default="H1", help="Fallback MT5 tester timeframe if not auto-detected from logs (e.g. H1, M15, D1).")
    ap.add_argument(
        "--tester-model",
        type=int,
        default=4,
        help="MT5 model (default 4 = every tick based on real ticks).",
    )
    ap.add_argument("--tester-delay-ms", type=int, default=50, help="Tester execution delay in milliseconds (default 50).")
    ap.add_argument("--tester-from", default="", help="Backtest start date YYYY.MM.DD (or auto from --start-date).")
    ap.add_argument("--tester-to", default="", help="Backtest end date YYYY.MM.DD (or auto from --end-date/today).")
    ap.add_argument("--tester-deposit", type=float, default=10000.0, help="Tester initial deposit.")
    ap.add_argument("--tester-leverage", type=int, default=100, help="Tester leverage.")
    ap.add_argument(
        "--tester-order-filling",
        choices=("AUTO", "FOK", "IOC", "RETURN"),
        default="AUTO",
        help="Order_Filling_Type policy: AUTO keeps live value; otherwise force selected mode.",
    )
    ap.add_argument("--tester-use-local", action="store_true", help="Use local agents for tester runs.")
    ap.add_argument(
        "--skip-live-ea-settings",
        action="store_true",
        help="Do not inject detected live EA input settings into tester runs.",
    )
    ap.add_argument("--run-backtests-now", action="store_true", help="Run MT5 tester automatically before portfolio compile.")
    ap.add_argument("--run-portfolio-now", action="store_true", help="Execute portfolio command immediately.")
    ap.add_argument("--tester-login", default="", help="Optional MT5 account login for --run-backtests-now.")
    ap.add_argument("--tester-password", default="", help="Optional MT5 account password for --run-backtests-now.")
    ap.add_argument("--tester-server", default="", help="Optional MT5 server for --run-backtests-now.")

    # ── Trades-period comparison flow ─────────────────────────────────────────
    ap.add_argument(
        "--trades-csv", default="",
        help="Path to real trades CSV (separate from detect source). Used for date-range detection "
             "and as the real-results input for the stage1 comparison.",
    )
    ap.add_argument("--second-broker-label", default="Broker B",
                    help="Display label for the second broker (default: 'Broker B').")
    ap.add_argument("--broker-a-login", default="", help="Broker A MT5 account login for trades-period backtests.")
    ap.add_argument("--broker-a-password", default="", help="Broker A MT5 account password for trades-period backtests.")
    ap.add_argument("--broker-a-server", default="", help="Broker A MT5 server for trades-period backtests.")
    ap.add_argument("--broker-b-login", default="", help="Broker B MT5 account login for trades-period backtests.")
    ap.add_argument("--broker-b-password", default="", help="Broker B MT5 account password for trades-period backtests.")
    ap.add_argument("--broker-b-server", default="", help="Broker B MT5 server for trades-period backtests.")
    ap.add_argument(
        "--run-trades-period-backtests", action="store_true",
        help="Run backtests covering only the date range of real trades (requires --trades-csv "
             "or that strategies were detected from a trades CSV with timestamp data).",
    )
    ap.add_argument(
        "--run-comparison-now", action="store_true",
        help="After trades-period backtests, run the stage1 real-vs-backtest comparison.",
    )
    ap.add_argument("--compare-ticks-dir", default="",
                    help="Tick data folder for the stage1 comparison (defaults to --ticks-dir).")
    ap.add_argument("--compare-symbol", default="",
                    help="Clean symbol name for tick file lookup in comparison (e.g. EURJPY). "
                         "Defaults to the first detected strategy symbol.")
    ap.add_argument("--compare-broker-gmt", type=int, default=2,
                    help="Broker GMT offset for comparison (default 2).")
    ap.add_argument("--compare-tick-gmt", type=int, default=2,
                    help="Tick GMT offset for comparison (default 2).")
    ap.add_argument("--compare-magic", default="",
                    help="Optional magic-number filter for comparison real-statement parsing.")
    ap.add_argument("--compare-title", default="",
                    help="Title for comparison HTML report (auto-generated if blank).")

    args = ap.parse_args()

    try:
        mt5_csv = Path(args.mt5_csv).expanduser().resolve() if args.mt5_csv else None
        if mt5_csv and not mt5_csv.exists():
            raise UserInputError(f"MT5 CSV not found: {mt5_csv}")

        backtest_dir = Path(args.backtest_dir).expanduser().resolve() if args.backtest_dir else None
        bars_dir = Path(args.bars_dir).expanduser().resolve()
        out_root = Path(args.out_root).expanduser().resolve()

        if backtest_dir and not backtest_dir.exists():
            raise UserInputError(f"Backtest directory not found: {backtest_dir}")
        if not bars_dir.exists():
            raise UserInputError(f"Bars directory not found: {bars_dir}")

        start_dt = _parse_optional_date(args.start_date)
        end_dt = _parse_optional_date(args.end_date)
        if start_dt and end_dt and start_dt > end_dt:
            raise UserInputError("start-date cannot be after end-date")

        if args.detect_source == "csv":
            if mt5_csv is None:
                raise UserInputError("--detect-source csv requires --mt5-csv")
            strategies = parse_mt5_deals_csv(
                csv_path=mt5_csv,
                start_dt=start_dt,
                end_dt=end_dt,
                min_trades=args.min_trades,
                grouping_mode=args.detect_grouping,
            )
        elif args.detect_source == "terminal_logs":
            if not args.mt5_terminal_dir:
                raise UserInputError("--detect-source terminal_logs requires --mt5-terminal-dir")
            mt5_terminal_dir_for_detect = Path(args.mt5_terminal_dir).expanduser().resolve()
            if not mt5_terminal_dir_for_detect.exists():
                raise UserInputError(f"MT5 terminal folder not found: {mt5_terminal_dir_for_detect}")
            strategies = parse_mt5_terminal_logs(
                mt5_terminal_dir=mt5_terminal_dir_for_detect,
                start_dt=start_dt,
                end_dt=end_dt,
                min_events=args.min_trades,
            )
        else:
            if mt5_csv is not None:
                strategies = parse_mt5_deals_csv(
                    csv_path=mt5_csv,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    min_trades=args.min_trades,
                    grouping_mode=args.detect_grouping,
                )
            else:
                if not args.mt5_terminal_dir:
                    raise UserInputError(
                        "Provide --mt5-csv, or set --mt5-terminal-dir for auto terminal_logs detection."
                    )
                mt5_terminal_dir_for_detect = Path(args.mt5_terminal_dir).expanduser().resolve()
                if not mt5_terminal_dir_for_detect.exists():
                    raise UserInputError(f"MT5 terminal folder not found: {mt5_terminal_dir_for_detect}")
                strategies = parse_mt5_terminal_logs(
                    mt5_terminal_dir=mt5_terminal_dir_for_detect,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    min_events=args.min_trades,
                )
        if not strategies:
            raise UserInputError(
                "No strategies detected after filters. Reduce --min-trades or widen date range."
            )

        if args.preview_plan:
            if not args.mt5_terminal_dir:
                raise UserInputError("--preview-plan requires --mt5-terminal-dir")
            mt5_terminal_dir_preview = Path(args.mt5_terminal_dir).expanduser().resolve()
            if not mt5_terminal_dir_preview.exists():
                raise UserInputError(f"MT5 terminal folder not found: {mt5_terminal_dir_preview}")
            terminal_exe_preview = _find_terminal_exe(mt5_terminal_dir_preview, args.mt5_terminal_exe)
            expert_root_preview = _find_expert_root(mt5_terminal_dir_preview)
            candidates_preview = _ea_candidates(expert_root_preview)
            if not candidates_preview:
                raise UserInputError(
                    f"No eligible EA .ex5 files found under {expert_root_preview} after ignore filters."
                )
            _assign_eas_to_strategies(strategies, candidates_preview, args.default_ea)
            print(f"MT5 terminal: {mt5_terminal_dir_preview}")
            print(f"terminal64.exe: {terminal_exe_preview}")
            print(f"Experts root: {expert_root_preview}")
            print(f"Detected candidate EAs: {len(candidates_preview)}")
            _print_strategy_plan(strategies, args.tester_period)
            return

        run_dir = make_run_folder(out_root, args.account_label)
        if mt5_csv is not None:
            (run_dir / "inputs" / mt5_csv.name).write_text(mt5_csv.read_text(encoding="utf-8-sig"), encoding="utf-8")

        repo_root = _find_repo_root(Path(__file__))

        # ── Phase: trades-period backtests on Broker A + Broker B ────────────
        if args.run_trades_period_backtests:
            if not args.mt5_terminal_dir:
                raise UserInputError("--run-trades-period-backtests requires --mt5-terminal-dir")
            if not (args.broker_a_login and args.broker_a_password and args.broker_a_server):
                raise UserInputError(
                    "--run-trades-period-backtests requires --broker-a-login, --broker-a-password, and --broker-a-server"
                )
            if not (args.broker_b_login and args.broker_b_password and args.broker_b_server):
                raise UserInputError(
                    "--run-trades-period-backtests requires --broker-b-login, --broker-b-password, and --broker-b-server"
                )

            mt5_terminal_dir_period = Path(args.mt5_terminal_dir).expanduser().resolve()
            if not mt5_terminal_dir_period.exists():
                raise UserInputError(f"MT5 terminal folder not found: {mt5_terminal_dir_period}")

            # Determine date range from the detected strategies (first_ts / last_ts from trades CSV)
            period_from, period_to = _get_date_range_from_strategies(strategies)
            print(f"\n── Trades-period window: {period_from} → {period_to} ──")

            # ── Broker A (same terminal; account from credentials) ───────────
            broker_a_label = args.account_label
            terminal_exe_a = _find_terminal_exe(mt5_terminal_dir_period, args.mt5_terminal_exe)
            expert_root_a = _find_expert_root(mt5_terminal_dir_period)
            candidates_a = _ea_candidates(expert_root_a)
            if not candidates_a:
                raise UserInputError(
                    f"No eligible EA .ex5 files found under {expert_root_a} after ignore filters."
                )
            _assign_eas_to_strategies(strategies, candidates_a, args.default_ea)

            print(f"  [Broker A] {broker_a_label} — {mt5_terminal_dir_period.name}")
            run_mt5_backtests(
                strategies=strategies,
                mt5_terminal_dir=mt5_terminal_dir_period,
                terminal_exe=terminal_exe_a,
                run_dir=run_dir,
                period=args.tester_period,
                model=args.tester_model,
                from_date=period_from,
                to_date=period_to,
                deposit=args.tester_deposit,
                leverage=args.tester_leverage,
                use_local=args.tester_use_local,
                delay_ms=args.tester_delay_ms,
                force_order_filling_type=args.tester_order_filling,
                use_live_settings=not args.skip_live_ea_settings,
                backtests_subdir="backtests/broker_a_period",
                broker_login=args.broker_a_login,
                broker_password=args.broker_a_password,
                broker_server=args.broker_a_server,
            )
            broker_a_reports = {
                s.symbol: run_dir / "backtests" / "broker_a_period"
                          / f"{s.symbol}_MAGIC_{s.magic or 'NA'}.htm"
                for s in strategies
            }

            # ── Broker B (same terminal; account switched via credentials) ────
            broker_b_reports: Dict[str, Path] = {}
            # Reuse the same terminal and EA mapping, just switch account via INI credentials.
            print(f"  [Broker B] {args.second_broker_label} — {mt5_terminal_dir_period.name}")
            run_mt5_backtests(
                strategies=strategies,
                mt5_terminal_dir=mt5_terminal_dir_period,
                terminal_exe=terminal_exe_a,
                run_dir=run_dir,
                period=args.tester_period,
                model=args.tester_model,
                from_date=period_from,
                to_date=period_to,
                deposit=args.tester_deposit,
                leverage=args.tester_leverage,
                use_local=args.tester_use_local,
                delay_ms=args.tester_delay_ms,
                force_order_filling_type=args.tester_order_filling,
                use_live_settings=not args.skip_live_ea_settings,
                backtests_subdir="backtests/broker_b_period",
                broker_login=args.broker_b_login,
                broker_password=args.broker_b_password,
                broker_server=args.broker_b_server,
            )
            broker_b_reports = {
                s.symbol: run_dir / "backtests" / "broker_b_period"
                          / f"{s.symbol}_MAGIC_{s.magic or 'NA'}.htm"
                for s in strategies
            }

            # ── Stage-1 comparison ────────────────────────────────────────────
            if args.run_comparison_now:
                trades_csv_for_compare = (
                    Path(args.trades_csv).expanduser().resolve()
                    if args.trades_csv
                    else mt5_csv
                )
                if trades_csv_for_compare is None or not trades_csv_for_compare.exists():
                    print(
                        "WARNING: --run-comparison-now requires --trades-csv (or --mt5-csv). "
                        "Skipping comparison.",
                        flush=True,
                    )
                else:
                    compare_ticks = (
                        Path(args.compare_ticks_dir).resolve()
                        if args.compare_ticks_dir
                        else (Path(args.ticks_dir).resolve() if args.ticks_dir else bars_dir)
                    )
                    stage1_script = (
                        repo_root / "stage1_real_results_vs_backtest"
                        / "stage1_real_results_vs_backtest.py"
                    )
                    if not stage1_script.exists():
                        print(
                            f"WARNING: Stage1 script not found at {stage1_script}. "
                            "Skipping comparison.",
                            flush=True,
                        )
                    else:
                        for s in strategies:
                            bt_args_parts: List[str] = []
                            ba_path = broker_a_reports.get(s.symbol)
                            if ba_path and ba_path.exists():
                                bt_args_parts += [
                                    f'--backtest "{ba_path}"',
                                    f'--backtest-label "{broker_a_label}"',
                                ]
                            bb_path = broker_b_reports.get(s.symbol)
                            if bb_path and bb_path.exists():
                                bt_args_parts += [
                                    f'--backtest "{bb_path}"',
                                    f'--backtest-label "{args.second_broker_label}"',
                                ]
                            if not bt_args_parts:
                                print(
                                    f"  Skipping comparison for {s.symbol}: "
                                    "no broker backtest reports found.",
                                    flush=True,
                                )
                                continue

                            compare_sym = args.compare_symbol or re.sub(r"[^A-Z]", "", s.symbol.upper())[:6] or s.symbol
                            compare_title_str = (
                                args.compare_title or
                                f"Real vs Backtest Comparison — {s.symbol}"
                            )
                            magic_flag = f'--magic "{args.compare_magic}"' if args.compare_magic else ""
                            comparison_out_dir = run_dir / "comparison"

                            compare_cmd = (
                                f'python "{stage1_script}"'
                                f' --real-statement "{trades_csv_for_compare}"'
                                f' {" ".join(bt_args_parts)}'
                                f' --ticks-dir "{compare_ticks}"'
                                f' --symbol "{compare_sym}"'
                                f' --broker-gmt {args.compare_broker_gmt}'
                                f' --tick-gmt {args.compare_tick_gmt}'
                                f' {magic_flag}'
                                f' --title "{compare_title_str}"'
                                f' --out-dir "{comparison_out_dir}"'
                            )
                            print(f"\nRunning stage1 comparison for {s.symbol}…", flush=True)
                            print(f"  {compare_cmd}", flush=True)
                            subprocess.run(compare_cmd, shell=True)
                            print(
                                f"  ✓ Comparison report: "
                                f"{comparison_out_dir / 'real_vs_backtest_comparison.html'}",
                                flush=True,
                            )

        # ── Phase: full-period (5-year) backtests ─────────────────────────────
        if args.run_backtests_now:
            if not args.mt5_terminal_dir:
                raise UserInputError("--run-backtests-now requires --mt5-terminal-dir")

            mt5_terminal_dir = Path(args.mt5_terminal_dir).expanduser().resolve()
            if not mt5_terminal_dir.exists():
                raise UserInputError(f"MT5 terminal folder not found: {mt5_terminal_dir}")

            terminal_exe = _find_terminal_exe(mt5_terminal_dir, args.mt5_terminal_exe)
            expert_root = _find_expert_root(mt5_terminal_dir)
            candidates = _ea_candidates(expert_root)
            if not candidates:
                raise UserInputError(
                    f"No eligible EA .ex5 files found under {expert_root} after ignore filters."
                )

            print(f"MT5 terminal: {mt5_terminal_dir}")
            print(f"terminal64.exe: {terminal_exe}")
            print(f"Experts root: {expert_root}")
            print(f"Detected candidate EAs: {len(candidates)}")
            for c in candidates[:20]:
                print(f"  - {c.name}")
            if len(candidates) > 20:
                print(f"  ... and {len(candidates) - 20} more")

            _assign_eas_to_strategies(strategies, candidates, args.default_ea)

            tester_from = args.tester_from.strip()
            if not tester_from:
                tester_from = start_dt.strftime("%Y.%m.%d") if start_dt else "2020.01.01"
            tester_to = args.tester_to.strip()
            if not tester_to:
                tester_to = end_dt.strftime("%Y.%m.%d") if end_dt else datetime.now().strftime("%Y.%m.%d")

            run_mt5_backtests(
                strategies=strategies,
                mt5_terminal_dir=mt5_terminal_dir,
                terminal_exe=terminal_exe,
                run_dir=run_dir,
                period=args.tester_period,
                model=args.tester_model,
                from_date=tester_from,
                to_date=tester_to,
                deposit=args.tester_deposit,
                leverage=args.tester_leverage,
                use_local=args.tester_use_local,
                delay_ms=args.tester_delay_ms,
                force_order_filling_type=args.tester_order_filling,
                use_live_settings=not args.skip_live_ea_settings,
                broker_login=args.tester_login,
                broker_password=args.tester_password,
                broker_server=args.tester_server,
            )
        else:
            if backtest_dir is None and not args.run_trades_period_backtests:
                raise UserInputError(
                    "Provide --backtest-dir when not using --run-backtests-now."
                )

        detected_csv = run_dir / "detected_strategies" / "detected_strategies.csv"
        detected_html = run_dir / "detected_strategies" / "detected_strategies.html"
        write_detected_csv(
            path=detected_csv,
            strategies=strategies,
            backtest_dir=backtest_dir,
            backtest_suffix=args.backtest_suffix,
            bars_dir=bars_dir,
            bars_suffix=args.bars_suffix,
            default_scale=args.default_scale,
            broker_gmt=args.broker_gmt,
        )
        write_detected_html(detected_html, strategies)

        portfolio_out = run_dir / "portfolio" / "results"
        ticks_dir = Path(args.ticks_dir).resolve() if args.ticks_dir else bars_dir

        fixed_out = portfolio_out / "fixed_lot"
        auto_out = portfolio_out / "auto_risk"

        fixed_cmd, fixed_warnings = build_portfolio_command(
            repo_root=repo_root,
            detected_csv=detected_csv,
            out_dir=fixed_out,
            title=f"{args.title} [Fixed Lot]",
            account_size=args.account_size,
            dd_tolerance=args.dd_tolerance,
            backtest_months=args.backtest_months,
            no_xlsx=args.no_xlsx,
            ticks_dir=ticks_dir,
            tick_suffix=args.tick_suffix,
            tick_gmt=args.tick_gmt,
            curve_sources=args.curve_sources,
            risk_mode_override="FIXED_LOT",
        )
        auto_cmd, auto_warnings = build_portfolio_command(
            repo_root=repo_root,
            detected_csv=detected_csv,
            out_dir=auto_out,
            title=f"{args.title} [Auto Risk]",
            account_size=args.account_size,
            dd_tolerance=args.dd_tolerance,
            backtest_months=args.backtest_months,
            no_xlsx=args.no_xlsx,
            ticks_dir=ticks_dir,
            tick_suffix=args.tick_suffix,
            tick_gmt=args.tick_gmt,
            curve_sources=args.curve_sources,
            risk_mode_override="AUTO_RISK",
        )

        preflight_warnings = fixed_warnings + [w for w in auto_warnings if w not in fixed_warnings]
        if preflight_warnings:
            print("\nPreflight warnings (skipped strategies):")
            for w in preflight_warnings:
                print(f"  - {w}")

        run_cmd_path = run_dir / "portfolio" / "run_portfolio_risk_from_detected.cmd"
        fixed_cmd_path = run_dir / "portfolio" / "run_portfolio_risk_fixed_lot.cmd"
        auto_cmd_path = run_dir / "portfolio" / "run_portfolio_risk_auto_risk.cmd"
        write_portfolio_cmd(fixed_cmd_path, fixed_cmd)
        write_portfolio_cmd(auto_cmd_path, auto_cmd)
        combined_cmd_lines = "\n".join([
            "@echo off",
            "setlocal",
            "cd /d \"%~dp0\"",
            "echo.",
            "echo Running FIXED_LOT portfolio...",
            fixed_cmd,
            "if errorlevel 1 exit /b %errorlevel%",
            "echo.",
            "echo Running AUTO_RISK portfolio...",
            auto_cmd,
            "if errorlevel 1 exit /b %errorlevel%",
            "echo.",
            "pause",
            "endlocal",
            "",
        ])
        run_cmd_path.write_text(combined_cmd_lines, encoding="utf-8")

        _write_run_summary(run_dir / "run_summary.csv", args, run_dir, len(strategies))

        print("\nCreated run folder:")
        print(f"  {run_dir}")
        print("Detected strategies CSV:")
        print(f"  {detected_csv}")
        print("Detected strategies HTML:")
        print(f"  {detected_html}")
        print("Portfolio command files:")
        print(f"  {run_cmd_path}")
        print(f"  {fixed_cmd_path}")
        print(f"  {auto_cmd_path}")

        bundle_dir = None
        if args.run_portfolio_now:
            print("\nRunning portfolio commands now...\n", flush=True)
            completed_fixed = subprocess.run(fixed_cmd, shell=True)
            if completed_fixed.returncode != 0:
                return completed_fixed.returncode
            completed_auto = subprocess.run(auto_cmd, shell=True)
            if completed_auto.returncode != 0:
                return completed_auto.returncode
            bundle_dir = create_review_bundle(run_dir)
            print(f"\nReview bundle:\n  {bundle_dir}")
            return 0

        bundle_dir = create_review_bundle(run_dir)
        print(f"\nReview bundle:\n  {bundle_dir}")
        print("\nPortfolio run not executed (use --run-portfolio-now or run the cmd files).")
        return 0

    except UserInputError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
