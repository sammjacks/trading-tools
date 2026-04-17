"""
real_results_review.py — review one real results file and optionally combine it
with additional strategies into a portfolio report.

This is a stage1-style single-source checker:
- supports live CSV, MT4 HTM/HTML, MT5 HTML/tester exports
- applies the same symbol / magic / date filters
- builds an equity review HTML with balance vs equity and summary stats
  using bar data, tick data, or a realised trade-event fallback
- optionally adds extra strategies in a stage3-style pipe format and writes
  a combined portfolio HTML and xlsx summary

Examples:
    python real_results_review.py ^
        --statement ./michel.htm ^
        --symbol USDJPY ^
        --ticks-dir D:/SEIF_system_new/Michel_Start ^
        --start-date 2026.03.04 ^
        --out-dir ./results

    python real_results_review.py ^
        --statement ./michel.htm ^
        --symbol USDJPY ^
        --ticks-dir D:/SEIF_system_new/Michel_Start ^
        --strategy "EURUSD|./eurusd.csv||1.0|2||EURUSD live" ^
        --strategy "GBPUSD|./gbpusd.htm||1.0|2|12345|GBP basket"
"""

import argparse
import csv
import html as html_lib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


HERE = Path(__file__).resolve().parent
DEFAULT_TOOLS_ROOT = Path(r"c:\Users\sammj\Projects\trading-tools")


def _unique_paths(paths: List[Path]) -> List[Path]:
    out: List[Path] = []
    seen = set()
    for p in paths:
        try:
            key = str(p.resolve())
        except Exception:
            key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _resolve_helper_file(folder_name: str, file_name: str) -> Path:
    env_root = (os.environ.get("TRADING_TOOLS_ROOT", "") or "").strip()
    candidates: List[Path] = []
    if env_root:
        candidates.append(Path(env_root))

    cwd = Path.cwd()
    candidates.extend([HERE, HERE.parent, cwd, cwd.parent, DEFAULT_TOOLS_ROOT])
    candidates.extend(list(HERE.parents))
    candidates.extend(list(cwd.parents))

    for base in _unique_paths(candidates):
        nested = base / folder_name / file_name
        flat = base / file_name
        if nested.exists():
            return nested
        if flat.exists():
            return flat

    checked = [str(p) for p in _unique_paths(candidates)[:12]]
    raise FileNotFoundError(
        f"Could not locate {file_name}. Checked nearby folders and TRADING_TOOLS_ROOT. "
        f"Either run it from the trading-tools repo, set TRADING_TOOLS_ROOT, or copy the helper folders too. "
        f"Checked: {checked}"
    )


def _load_helper(file_path: Path, module_name: str):
    if not file_path.exists():
        raise FileNotFoundError(f"Helper module not found: {file_path}")
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load helper module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_stage1():
    return _load_helper(
        _resolve_helper_file("stage1_real_results_vs_backtest", "stage1_real_results_vs_backtest.py"),
        "stage1_real_results_review_helpers",
    )


def _get_stage3():
    return _load_helper(
        _resolve_helper_file("stage3_portfolio_tick_check", "portfolio_backtest.py"),
        "stage3_portfolio_review_helpers",
    )


_STAGE1 = _get_stage1()


def _parse_date_start(value: str, broker_gmt: int) -> Optional[int]:
    s = (value or "").strip()
    if not s:
        return None
    return _STAGE1._parse_cli_date(s, timezone(timedelta(hours=broker_gmt)))


def _parse_date_end(value: str, broker_gmt: int) -> Optional[int]:
    s = (value or "").strip()
    if not s:
        return None
    end_start = _STAGE1._parse_cli_date(s, timezone(timedelta(hours=broker_gmt)))
    return end_start + 24 * 3600 - 1


def _simple_window_filter(trades: List[Dict],
                          start_ts: Optional[int],
                          end_ts: Optional[int]) -> List[Dict]:
    out: List[Dict] = []
    for t in trades:
        if start_ts is not None and t["close_ts"] < start_ts:
            continue
        if end_ts is not None and t["ts"] > end_ts:
            continue
        out.append(dict(t))
    return out


def _downsample_curve(curves: List[Dict],
                      display_tz: timezone,
                      max_points: int = 600) -> Tuple[List[str], List[float], List[float]]:
    if not curves:
        return [], [], []
    if len(curves) <= max_points:
        sample = curves
    else:
        step = max(1, len(curves) // max_points)
        sample = curves[::step]
        if sample[-1] is not curves[-1]:
            sample = sample + [curves[-1]]

    labels = [datetime.fromtimestamp(c["ts"], tz=display_tz).strftime("%Y-%m-%d %H:%M") for c in sample]
    bal = [float(c.get("bal", 0.0)) for c in sample]
    eq = [float(c.get("eq", 0.0)) for c in sample]
    return labels, bal, eq


def _hour_distribution(trades: List[Dict]) -> List[float]:
    bins = [0.0] * 24
    if not trades:
        return bins
    for t in trades:
        bins[(int(t["ts"]) // 3600) % 24] += 1
    total = sum(bins) or 1.0
    return [round(100.0 * x / total, 1) for x in bins]


def _try_write_xlsx(strategies, combined, out_path: str,
                    title: str,
                    account_size: float,
                    dd_tolerance: float) -> Tuple[bool, str]:
    try:
        stage3 = _get_stage3()
        stage3.write_portfolio_xlsx(
            strategies,
            combined,
            out_path,
            title,
            account_size,
            dd_tolerance,
            None,
        )
        return True, ""
    except ImportError:
        return False, "openpyxl not installed"
    except FileNotFoundError as exc:
        return False, str(exc)


def _looks_like_symbol_token(value: str) -> bool:
    s = (value or "").strip()
    if not s:
        return False
    if any(ch in s for ch in "\\/"):
        return False
    if s.lower().endswith((".csv", ".htm", ".html")):
        return False
    cleaned = s.replace(".", "").replace("_", "")
    return cleaned.isalnum() and any(ch.isalpha() for ch in cleaned)


def _resolve_input_statement_path(path: str) -> str:
    p = Path(path)
    candidates: List[Path] = [p]
    if not p.is_absolute():
        for base in _unique_paths([Path.cwd(), Path.cwd().parent, HERE, HERE.parent]):
            candidates.append(base / p)
            candidates.append(base / p.name)

    for candidate in _unique_paths(candidates):
        if candidate.exists():
            return str(candidate)
        if candidate.suffix.lower() == ".htm" and candidate.with_suffix(".html").exists():
            return str(candidate.with_suffix(".html"))
        if candidate.suffix.lower() == ".html" and candidate.with_suffix(".htm").exists():
            return str(candidate.with_suffix(".htm"))

    return path


def _statement_path_seems_valid(path: str) -> bool:
    resolved = _resolve_input_statement_path(path)
    return Path(resolved).exists()


def _build_bar_filename(symbol: str, bar_gmt: int, timeframe: str = "M5") -> str:
    base = _STAGE1.build_tick_filename(symbol, bar_gmt)
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


def _parse_strategy_arg(raw: str, default_broker_gmt: int) -> Dict[str, object]:
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 2:
        raise ValueError(f"--strategy needs at least SYMBOL|FILE (got: {raw!r})")

    symbol = parts[0].upper()
    path = parts[1]

    if not symbol and _looks_like_symbol_token(path):
        raise ValueError(
            f"Strategy looks incomplete: {raw!r}. It appears the symbol was put into the FILE field. "
            f"Use SYMBOL|FILE|... for example EURUSD|./michel.htm||1.0|2|12000|EURUSD basket"
        )

    if _looks_like_symbol_token(path) and not _statement_path_seems_valid(path):
        raise ValueError(
            f"Strategy file path looks wrong: {path!r}. This looks like a symbol, not a CSV/HTM/HTML file path. "
            f"In the cmd runner, set STRATn_FILE to the statement file and STRATn_SYMBOL to the pair such as EURUSD."
        )

    looks_like_stage3_shape = (
        len(parts) >= 3 and (
            parts[2] == "" or "/" in parts[2] or "\\" in parts[2]
            or parts[2].lower().endswith((".csv", ".htm", ".html"))
        )
    )
    if looks_like_stage3_shape:
        scale_idx, gmt_idx, magic_idx, label_idx = 3, 4, 5, 6
    else:
        scale_idx, gmt_idx, magic_idx, label_idx = 2, 3, 4, 5

    scale = float(parts[scale_idx]) if len(parts) > scale_idx and parts[scale_idx] else 1.0
    broker_gmt = int(parts[gmt_idx]) if len(parts) > gmt_idx and parts[gmt_idx] else default_broker_gmt
    magic = _STAGE1._normalize_magic(parts[magic_idx]) if len(parts) > magic_idx and parts[magic_idx] else ""

    if len(parts) > label_idx and parts[label_idx]:
        label = parts[label_idx]
    else:
        base_label = _STAGE1._display_source_name(path)
        label_bits = [base_label, symbol]
        if magic:
            label_bits.append(f"magic {magic}")
        label = " | ".join(label_bits)

    return {
        "symbol": symbol,
        "path": path,
        "scale": scale,
        "broker_gmt": broker_gmt,
        "magic": magic,
        "label": label,
    }


def _strategy_identity_key(source_path: str,
                           symbol: str,
                           magic_filter: str,
                           scale: float) -> Tuple[str, str, str, float]:
    try:
        norm_path = str(Path(source_path).resolve()).lower()
    except Exception:
        norm_path = str(source_path).lower()
    return (norm_path, (symbol or "").upper(), (magic_filter or "").strip(), round(float(scale), 8))


def _build_source_review(path: str,
                         symbol: str,
                         broker_gmt: int,
                         tick_gmt: int,
                         bar_gmt: int,
                         ticks_dir: str,
                         bars_dir: str,
                         start_date: str,
                         end_date: str,
                         magic_filter: str,
                         scale: float,
                         label: str,
                         account_size: float) -> Dict:
    resolved_path = _resolve_input_statement_path(path)
    trades, fmt = _STAGE1.parse_statement(resolved_path, broker_gmt, symbol, magic_filter or None)
    if not trades:
        raise ValueError(f"No trades found in {path} for symbol {symbol}")

    start_ts = _parse_date_start(start_date, broker_gmt)
    end_ts = _parse_date_end(end_date, broker_gmt)
    trade_min = min(t["ts"] for t in trades)
    trade_max = max(t["close_ts"] for t in trades)
    window_min = max(trade_min, start_ts) if start_ts is not None else trade_min
    window_max = min(trade_max, end_ts) if end_ts is not None else trade_max
    if window_min > window_max:
        raise ValueError("No trade history remains after applying the chosen start/end date filters")

    bar_points: List[Dict] = []
    tick_points: List[Dict] = []
    bar_file = ""
    tick_file = ""
    filtered_trades = _simple_window_filter(trades, window_min, window_max)
    curve_source = "trade-event"
    curve_note = "No matching bar or tick file was available, so the chart falls back to realised trade-event steps."

    if (bars_dir or "").strip():
        try:
            bar_file = _resolve_bar_file(bars_dir, symbol, bar_gmt)
            bar_points = _load_bar_points(bar_file, window_min, window_max)
            if bar_points:
                filtered_trades = _STAGE1.clip_trades_to_window(trades, window_min, window_max, bar_points)
                curve_source = "bar"
                curve_note = f"Equity mapping used {len(bar_points):,} M5 bar points from the local archive."
        except Exception as exc:
            print(f"  WARNING: bar load skipped for {label}: {exc}")
            bar_points = []

    if (ticks_dir or "").strip():
        try:
            tick_file = _STAGE1.resolve_tick_file(ticks_dir, symbol, tick_gmt)
            tick_points = _STAGE1.load_ticks(tick_file, tick_gmt, window_min, window_max)
            if tick_points:
                filtered_trades = _STAGE1.clip_trades_to_window(trades, window_min, window_max, tick_points)
                curve_source = "bar+tick" if bar_points else "tick"
                if bar_points:
                    curve_note = (
                        f"Bar data was loaded first ({len(bar_points):,} bar points), and tick data was then applied "
                        f"for the final higher-resolution mark-to-market curve from {len(tick_points):,} ticks."
                    )
                else:
                    curve_note = f"Balance/equity view uses a downsampled intraday mark-to-market curve from {len(tick_points):,} ticks."
        except Exception as exc:
            print(f"  WARNING: tick load skipped for {label}: {exc}")
            tick_points = []

    if not filtered_trades:
        raise ValueError(f"No trades remain for {label} after the selected filters")

    scaled_trades = _STAGE1._scale_trades(filtered_trades, scale)
    if tick_points:
        curves = _STAGE1.build_equity_curve_from_ticks(scaled_trades, tick_points)
    elif bar_points:
        curves = _STAGE1.build_equity_curve_from_ticks(scaled_trades, bar_points, sample_every=1)
    else:
        curves = _STAGE1.build_equity_curve_from_trade_events(scaled_trades)

    display_tz = timezone(timedelta(hours=broker_gmt))
    chart_labels, chart_bal, chart_eq = _downsample_curve(curves, display_tz)
    daily_labels, daily_bal, daily_eq = _STAGE1.curves_to_daily(curves, display_tz)
    stats = _STAGE1.compute_stats(scaled_trades)
    max_dd = _STAGE1.max_drawdown(daily_eq)
    ret_dd = stats["net"] / max_dd if max_dd > 0 else 0.0
    base_lot = _STAGE1._base_basket_lot_size(filtered_trades)

    portfolio_strategy = None
    try:
        stage3 = _get_stage3()
        strategy_cfg = {
            "symbol": label,
            "scale": scale,
            "risk_mode": "FIXED_LOT",
        }
        portfolio_strategy = stage3._build_strategy_result(
            strategy_cfg,
            scaled_trades,
            base_lot,
            scale,
            curves,
            curve_source,
            account_size,
            {},
        )
    except FileNotFoundError:
        portfolio_strategy = None

    return {
        "label": label,
        "source_path": resolved_path,
        "source_format": fmt,
        "symbol": symbol,
        "magic": magic_filter,
        "scale": scale,
        "base_lot": base_lot,
        "window_start": datetime.fromtimestamp(window_min, tz=display_tz).strftime("%Y-%m-%d %H:%M"),
        "window_end": datetime.fromtimestamp(window_max, tz=display_tz).strftime("%Y-%m-%d %H:%M"),
        "curve_note": curve_note,
        "curve_source": curve_source,
        "bar_file": bar_file,
        "tick_file": tick_file,
        "trades": scaled_trades,
        "stats": stats,
        "max_dd": max_dd,
        "ret_dd": ret_dd,
        "chart_labels": chart_labels,
        "chart_bal": chart_bal,
        "chart_eq": chart_eq,
        "hour_pct": _hour_distribution(scaled_trades),
        "portfolio_strategy": portfolio_strategy,
    }


def write_review_report(review: Dict,
                        out_path: str,
                        title: str,
                        portfolio_note: str = "") -> None:
    stats = review["stats"]
    rows = [
        ("Source", review["label"]),
        ("Format", review["source_format"]),
        ("Symbol", review["symbol"]),
        ("Equity Mapping", review.get("curve_source", "trade-event")),
        ("Trade Count", str(stats["count"])),
        ("Wins / Losses", f"{stats['wins']} / {stats['losses']}"),
        ("Win Rate", f"{stats['win_rate']:.1f}%"),
        ("Profit Factor", "inf" if stats["profit_factor"] == float("inf") else f"{stats['profit_factor']:.2f}"),
        ("Net Profit", f"${stats['net']:,.2f}"),
        ("Max Drawdown", f"${review['max_dd']:,.2f}"),
        ("Return/DD", f"{review['ret_dd']:.2f}"),
        ("Base Basket Lot", f"{review['base_lot']:.4f}" if review["base_lot"] else "n/a"),
        ("Applied Scale", f"{review['scale']:.2f}x"),
        ("Review Window", f"{review['window_start']} → {review['window_end']}"),
    ]
    table_rows = "".join(
        f"<tr><td style='border:1px solid #ddd;padding:6px 8px;text-align:left;font-weight:600;'>{html_lib.escape(k)}</td>"
        f"<td style='border:1px solid #ddd;padding:6px 8px;text-align:right;'>{html_lib.escape(v)}</td></tr>"
        for k, v in rows
    )

    portfolio_html = ""
    if portfolio_note:
        portfolio_html = (
            "<h2>Portfolio Outputs</h2>"
            f"<p style='font-size:12px;color:#666;margin:0 0 12px;'>{html_lib.escape(portfolio_note)}</p>"
        )

    html_out = f"""<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>{html_lib.escape(title)}</title>
<script src=\"https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js\"></script>
<style>
  body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f7f7f7; color: #222; }}
  .container {{ max-width: 1300px; margin: auto; background: white; padding: 24px;
                border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ font-size: 22px; margin: 0 0 16px; }}
  h2 {{ font-size: 16px; margin: 24px 0 12px; color: #333; }}
  .chart-box {{ position: relative; height: 400px; margin-bottom: 24px; }}
  table {{ font-size: 13px; border-collapse: collapse; }}
</style></head><body><div class=\"container\">
<h1>{html_lib.escape(title)}</h1>
<p style='font-size:12px;color:#666;margin:0 0 12px;'>{html_lib.escape(review['curve_note'])}</p>
<div class=\"chart-box\"><canvas id=\"eq_chart\"></canvas></div>
<h2>Statistics</h2>
<table>{table_rows}</table>
<h2>Trade Entry Hour Distribution (UTC)</h2>
<div class=\"chart-box\" style=\"height:260px;\"><canvas id=\"hour_chart\"></canvas></div>
{portfolio_html}
<script>
const eqLabels = {json.dumps(review['chart_labels'])};
new Chart(document.getElementById('eq_chart'), {{
  type: 'line',
  data: {{
    labels: eqLabels,
    datasets: [
      {{
        label: 'Balance',
        data: {json.dumps(review['chart_bal'])},
        borderColor: '#305496',
        backgroundColor: 'rgba(48,84,150,0.04)',
        borderWidth: 2,
        fill: false,
        pointRadius: 0,
        tension: 0.15
      }},
      {{
        label: 'Equity',
        data: {json.dumps(review['chart_eq'])},
        borderColor: '#F44336',
        backgroundColor: 'rgba(244,67,54,0.06)',
        borderWidth: 2,
        fill: false,
        pointRadius: 0,
        tension: 0.15
      }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{ legend: {{ position: 'top' }} }},
    scales: {{
      x: {{ ticks: {{ maxTicksLimit: 24, maxRotation: 45 }} }},
      y: {{ ticks: {{ callback: v => '$' + v.toLocaleString('en-US', {{ minimumFractionDigits: 0 }}) }} }}
    }}
  }}
}});
new Chart(document.getElementById('hour_chart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(list(range(24)))},
    datasets: [{{
      label: '{html_lib.escape(review['label'])} (%)',
      data: {json.dumps(review['hour_pct'])},
      backgroundColor: 'rgba(55,138,221,0.7)',
      borderColor: '#378ADD',
      borderWidth: 1
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ position: 'top' }} }},
    scales: {{
      x: {{ title: {{ display: true, text: 'Hour of Day (UTC)' }} }},
      y: {{ beginAtZero: true, title: {{ display: true, text: '% of Trades' }}, ticks: {{ callback: v => v + '%' }} }}
    }}
  }}
}});
</script></div></body></html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Review one real results file and optionally build a portfolio summary from additional strategies."
    )
    ap.add_argument("--statement", required=True, metavar="PATH", help="Primary result file to review (CSV / HTM / HTML).")
    ap.add_argument("--symbol", required=True, metavar="SYMBOL", help="Primary symbol filter, e.g. EURUSD or USDJPY.")
    ap.add_argument("--magic", default="", metavar="N", help="Optional magic filter for the primary statement.")
    ap.add_argument("--scale", type=float, default=1.0, metavar="X", help="Optional scale factor for the primary review.")
    ap.add_argument("--ticks-dir", default="", metavar="PATH", help="Optional tick folder used for higher-resolution mark-to-market equity.")
    ap.add_argument("--bars-dir", default="", metavar="PATH", help="Optional bar folder used for bar-based equity mapping before tick refinement.")
    ap.add_argument("--broker-gmt", type=int, default=2, metavar="N", help="Broker timezone offset for the primary statement.")
    ap.add_argument("--tick-gmt", type=int, default=2, metavar="N", help="Tick timezone offset.")
    ap.add_argument("--bar-gmt", type=int, default=2, metavar="N", help="Bar timezone offset.")
    ap.add_argument("--start-date", default="", metavar="YYYY.MM.DD", help="Optional start date filter.")
    ap.add_argument("--end-date", default="", metavar="YYYY.MM.DD", help="Optional end date filter.")
    ap.add_argument("--out-dir", default=".", metavar="PATH", help="Output directory.")
    ap.add_argument("--title", default="Real Results Review", help="Title for the single-source review HTML.")
    ap.add_argument("--account-size", type=float, default=10000.0, help="Account size used for portfolio safety-factor metrics.")
    ap.add_argument("--dd-tolerance", type=float, default=10.0, help="DD tolerance percent used for the portfolio spreadsheet.")
    ap.add_argument("--portfolio-title", default="Real Results Portfolio Review", help="Title for the optional portfolio report.")
    ap.add_argument("--strategy", action="append", default=[], metavar="SPEC",
                    help="Optional additional portfolio strategy. Supports either SYMBOL|FILE|SCALE|BROKER_GMT|MAGIC|LABEL or the stage3-style SYMBOL|FILE|IGNORED|SCALE|BROKER_GMT|MAGIC|LABEL.")
    ap.add_argument("--no-xlsx", action="store_true", help="Skip the portfolio xlsx output.")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    try:
        primary_label = _STAGE1._display_source_name(args.statement)
        primary_magic = _STAGE1._normalize_magic(args.magic)

        print("Loading primary results file…")
        review = _build_source_review(
            path=args.statement,
            symbol=args.symbol,
            broker_gmt=args.broker_gmt,
            tick_gmt=args.tick_gmt,
            bar_gmt=args.bar_gmt,
            ticks_dir=args.ticks_dir,
            bars_dir=args.bars_dir,
            start_date=args.start_date,
            end_date=args.end_date,
            magic_filter=primary_magic,
            scale=args.scale,
            label=primary_label,
            account_size=args.account_size,
        )
        print(f"  {review['label']}: {len(review['trades'])} trades loaded ({review['source_format']})")
        print(f"  Equity mapping: {review['curve_source']}")
        print(f"  Net P&L: ${review['stats']['net']:,.2f} | Max DD: ${review['max_dd']:,.2f}")

        portfolio_note = ""
        if args.strategy:
            print("\nBuilding optional portfolio…")
            stage3 = _get_stage3()
            if review["portfolio_strategy"] is None:
                raise FileNotFoundError("Portfolio helper code could not be located for the copied review script.")

            portfolio_strategies = [review["portfolio_strategy"]]
            seen_keys = {
                _strategy_identity_key(
                    review["source_path"],
                    review["symbol"],
                    review.get("magic", ""),
                    review["scale"],
                )
            }
            for raw in args.strategy:
                cfg = _parse_strategy_arg(raw, args.broker_gmt)
                candidate_key = _strategy_identity_key(
                    _resolve_input_statement_path(str(cfg["path"])),
                    str(cfg["symbol"]),
                    str(cfg["magic"]),
                    float(cfg["scale"]),
                )
                if candidate_key in seen_keys:
                    print(f"  Skipping duplicate portfolio strategy: {cfg['label']}")
                    continue

                print(f"  Adding portfolio strategy: {cfg['label']}")
                extra = _build_source_review(
                    path=str(cfg["path"]),
                    symbol=str(cfg["symbol"]),
                    broker_gmt=int(cfg["broker_gmt"]),
                    tick_gmt=args.tick_gmt,
                    bar_gmt=args.bar_gmt,
                    ticks_dir=args.ticks_dir,
                    bars_dir=args.bars_dir,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    magic_filter=str(cfg["magic"]),
                    scale=float(cfg["scale"]),
                    label=str(cfg["label"]),
                    account_size=args.account_size,
                )
                portfolio_strategies.append(extra["portfolio_strategy"])
                seen_keys.add(candidate_key)

            combined = stage3.combine_curves(portfolio_strategies, account_size=args.account_size)
            stats_lines = stage3.build_stats_text(
                portfolio_strategies,
                combined,
                args.account_size,
                args.dd_tolerance,
                None,
            )

            portfolio_dir = os.path.join(args.out_dir, "portfolio")
            os.makedirs(portfolio_dir, exist_ok=True)
            portfolio_html = os.path.join(portfolio_dir, "portfolio_report.html")
            stage3.write_portfolio_report(portfolio_strategies, combined, stats_lines, portfolio_html, args.portfolio_title)
            print(f"  Portfolio HTML: {portfolio_html}")

            portfolio_xlsx = os.path.join(portfolio_dir, "portfolio_report.xlsx")
            if args.no_xlsx:
                portfolio_note = "Portfolio HTML created. XLSX output was skipped by request."
            else:
                ok, reason = _try_write_xlsx(
                    portfolio_strategies,
                    combined,
                    portfolio_xlsx,
                    args.portfolio_title,
                    args.account_size,
                    args.dd_tolerance,
                )
                if ok:
                    print(f"  Portfolio XLSX: {portfolio_xlsx}")
                    portfolio_note = "Portfolio HTML and XLSX summary were created under the portfolio subfolder."
                else:
                    print(f"  WARNING: portfolio xlsx skipped — {reason}")
                    portfolio_note = f"Portfolio HTML was created, but the XLSX summary was skipped because {reason}."

        review_html = os.path.join(args.out_dir, "real_results_review.html")
        write_review_report(review, review_html, args.title, portfolio_note=portfolio_note)
        print(f"\nReview HTML saved: {review_html}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
