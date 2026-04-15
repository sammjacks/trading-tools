#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Tuple


def _find_repo_root(script_path: Path) -> Path:
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


def _resolve_helper_script(local_dir: Path, shared_path: Path) -> Path:
    if shared_path.exists():
        return shared_path
    local_path = local_dir / shared_path.name
    if local_path.exists():
        return local_path
    raise FileNotFoundError(f"Required helper script not found: {shared_path} or {local_path}")


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _clean_compare_symbol(symbol: str) -> str:
    clean = "".join(ch for ch in (symbol or "").upper() if ch.isalpha())
    return clean[:6] if len(clean) >= 6 else (clean or symbol)


def _dedupe_strategies_by_symbol(strategies: List) -> List:
    best = {}
    for s in strategies:
        key = (s.symbol or "").upper()
        if not key:
            continue
        cur = best.get(key)
        if cur is None or getattr(s, "trades", 0) > getattr(cur, "trades", 0):
            best[key] = s
    return sorted(best.values(), key=lambda s: (s.symbol or ""))


def _real_trade_window(stage1, statement_file: Path, broker_gmt: int, magic_filter: str) -> Tuple[List[dict], str, str, str]:
    trades, fmt = stage1.parse_statement(
        str(statement_file),
        broker_gmt,
        None,
        magic_filter or None,
    )
    if not trades:
        raise ValueError(f"No real trades found in {statement_file}")

    tz = timezone(timedelta(hours=broker_gmt))
    first_ts = min(t["ts"] for t in trades)
    last_ts = max(t.get("close_ts", t["ts"]) for t in trades)
    from_date = datetime.fromtimestamp(first_ts, tz=tz).strftime("%Y.%m.%d")
    to_date = datetime.fromtimestamp(last_ts, tz=tz).strftime("%Y.%m.%d")
    return trades, fmt, from_date, to_date


def _filter_strategies_to_real_trades(stage1, strategies: List, statement_file: Path, broker_gmt: int, magic_filter: str) -> List:
    tz = timezone(timedelta(hours=broker_gmt))
    kept = []
    for s in _dedupe_strategies_by_symbol(strategies):
        compare_symbol = _clean_compare_symbol(s.symbol)
        trades, _ = stage1.parse_statement(
            str(statement_file),
            broker_gmt,
            compare_symbol,
            magic_filter or None,
        )
        if not trades:
            continue
        s.trades = len(trades)
        s.first_ts = datetime.fromtimestamp(min(t["ts"] for t in trades), tz=tz).replace(tzinfo=None)
        s.last_ts = datetime.fromtimestamp(max(t.get("close_ts", t["ts"]) for t in trades), tz=tz).replace(tzinfo=None)
        kept.append(s)
    return kept


def _load_existing_real_period_backtests(run_dir: Path) -> List:
    backtests_dir = run_dir / "backtests" / "real_period"
    if not backtests_dir.exists():
        return []

    found = []
    seen = set()
    for report in sorted(list(backtests_dir.glob("*_MAGIC_*.htm")) + list(backtests_dir.glob("*_MAGIC_*.html"))):
        symbol = re.split(r"_MAGIC_", report.stem, maxsplit=1)[0].strip()
        key = symbol.upper()
        if not symbol or key in seen:
            continue
        seen.add(key)
        found.append(SimpleNamespace(symbol=symbol, backtest_html=str(report)))
    return found


def _run_stage1_comparisons(stage1_script: Path, statement_file: Path, strategies: List, run_dir: Path,
                            account_label: str, ticks_dir: Path, broker_gmt: int, tick_gmt: int,
                            magic_filter: str) -> None:
    for s in strategies:
        if not s.backtest_html:
            continue
        compare_symbol = _clean_compare_symbol(s.symbol)
        comparison_out_dir = run_dir / "comparison" / compare_symbol
        comparison_out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(stage1_script),
            "--real-statement", str(statement_file),
            "--backtest", str(s.backtest_html),
            "--backtest-label", account_label,
            "--ticks-dir", str(ticks_dir),
            "--symbol", compare_symbol,
            "--broker-gmt", str(broker_gmt),
            "--tick-gmt", str(tick_gmt),
            "--title", f"Real vs Backtest Comparison — {compare_symbol}",
            "--out-dir", str(comparison_out_dir),
        ]
        if magic_filter:
            cmd.extend(["--magic", magic_filter])

        print(f"\nRunning comparison for {compare_symbol}...", flush=True)
        completed = subprocess.run(cmd)
        if completed.returncode != 0:
            raise RuntimeError(f"Comparison failed for {compare_symbol} (exit {completed.returncode})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Single-broker account review flow for MT5 + real-vs-backtest + 5-year portfolio.")
    ap.add_argument("--statement-file", default="", help="Optional path to real trade history statement HTM/HTML/CSV (e.g. Portfolio4.htm). Required for comparison modes, not needed for backtests-only mode.")
    ap.add_argument("--account-label", default="AccountReview")
    ap.add_argument("--out-root", default="./runs")
    ap.add_argument("--mt5-terminal-dir", required=True)
    ap.add_argument("--mt5-terminal-exe", default="")
    ap.add_argument("--detect-source", choices=("terminal_logs",), default="terminal_logs")
    ap.add_argument("--min-trades", type=int, default=1)
    ap.add_argument("--magic-filter", default="", help="Optional magic-number filter for the real HTML/CSV statement.")
    ap.add_argument("--default-ea", default="")
    ap.add_argument("--tester-period", default="H1")
    ap.add_argument("--tester-model", type=int, default=4)
    ap.add_argument("--tester-delay-ms", type=int, default=50)
    ap.add_argument("--tester-deposit", type=float, default=10000.0)
    ap.add_argument("--tester-leverage", type=int, default=100)
    ap.add_argument("--tester-order-filling", choices=("AUTO", "FOK", "IOC", "RETURN"), default="AUTO")
    ap.add_argument("--tester-use-local", action="store_true")
    ap.add_argument("--skip-live-ea-settings", action="store_true")
    ap.add_argument("--broker-login", default="")
    ap.add_argument("--broker-password", default="")
    ap.add_argument("--broker-server", default="")
    ap.add_argument("--bars-dir", required=True)
    ap.add_argument("--bars-suffix", default="_GMT+2_US-DST_M5.csv")
    ap.add_argument("--ticks-dir", required=True)
    ap.add_argument("--tick-suffix", default="_GMT+2_US-DST.csv")
    ap.add_argument("--tick-gmt", type=int, default=2)
    ap.add_argument("--curve-sources", default="bars")
    ap.add_argument("--broker-gmt", type=int, default=2)
    ap.add_argument("--compare-broker-gmt", type=int, default=2)
    ap.add_argument("--compare-tick-gmt", type=int, default=2)
    ap.add_argument("--account-size", type=float, default=10000.0)
    ap.add_argument("--dd-tolerance", type=float, default=10.0)
    ap.add_argument("--default-scale", type=float, default=1.0)
    ap.add_argument("--backtest-months", type=float, default=None)
    ap.add_argument("--no-xlsx", action="store_true")
    ap.add_argument("--full-from", default="")
    ap.add_argument("--full-to", default="")
    ap.add_argument("--resume-run-dir", default="", help="Existing run folder to resume from.")
    ap.add_argument("--resume-comparison-only", action="store_true", help="Reuse existing real-period backtests from --resume-run-dir and rerun only the comparison stage.")
    ap.add_argument("--comparison-only", action="store_true", help="Run only the real-period backtests and comparison, then stop before the 5-year stage.")
    ap.add_argument("--backtests-only", action="store_true", help="Only run the chart-detected MT5 backtests, save them neatly, and stop before comparison and portfolio stages.")
    ap.add_argument("--preview-plan", action="store_true")
    ap.add_argument("--run-review-now", action="store_true")
    ap.add_argument("--run-portfolio-now", action="store_true")
    ap.add_argument("--title", default="Single-Broker 5-Year Portfolio Review")
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = _find_repo_root(Path(__file__))
    mt5_script = _resolve_helper_script(
        script_dir,
        repo_root / "running_account_risk_check_and_folder_creation" / "mt5_account_risk_flow.py",
    )
    mt5 = _load_module("mt5_account_risk_flow", mt5_script)

    stage1_script: Optional[Path] = None
    stage1 = None
    if not args.backtests_only:
        stage1_script = _resolve_helper_script(
            script_dir,
            repo_root / "stage1_real_results_vs_backtest" / "stage1_real_results_vs_backtest.py",
        )
        stage1 = _load_module("stage1_real_results_vs_backtest", stage1_script)

    statement_file: Optional[Path] = None
    if args.statement_file.strip():
        statement_file = Path(args.statement_file).expanduser().resolve()

    mt5_terminal_dir = Path(args.mt5_terminal_dir).expanduser().resolve()
    if not mt5_terminal_dir.exists():
        raise FileNotFoundError(f"MT5 terminal folder not found: {mt5_terminal_dir}")

    bars_dir = Path(args.bars_dir).expanduser().resolve()
    ticks_dir = Path(args.ticks_dir).expanduser().resolve()
    out_root = Path(args.out_root).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    all_real_trades: List[dict] = []
    statement_fmt = ""
    real_from = ""
    real_to = ""

    if not args.backtests_only:
        if statement_file is None or not statement_file.exists():
            raise FileNotFoundError(f"Statement file not found: {statement_file or args.statement_file}")
        if stage1 is None:
            raise RuntimeError("Stage1 comparison helper is not available.")
        all_real_trades, statement_fmt, real_from, real_to = _real_trade_window(
            stage1, statement_file, args.broker_gmt, args.magic_filter
        )
        print(f"Real statement: {statement_file}")
        print(f"Statement format: {statement_fmt}")
        print(f"Real trades found: {len(all_real_trades)}")
        print(f"Real trading window: {real_from} -> {real_to}")

    if args.resume_comparison_only:
        if not args.resume_run_dir:
            raise RuntimeError("--resume-comparison-only requires --resume-run-dir")
        run_dir = Path(args.resume_run_dir).expanduser().resolve()
        if not run_dir.exists():
            raise FileNotFoundError(f"Resume run folder not found: {run_dir}")
        strategies = _load_existing_real_period_backtests(run_dir)
        if not strategies:
            raise RuntimeError(f"No saved real-period backtest HTML files found under {run_dir}")
        print(f"Resuming comparison from existing run: {run_dir}")
        if statement_file is None or stage1_script is None:
            raise RuntimeError("A real statement file is required for comparison resume mode.")
        _run_stage1_comparisons(
            stage1_script=stage1_script,
            statement_file=statement_file,
            strategies=strategies,
            run_dir=run_dir,
            account_label=args.account_label,
            ticks_dir=ticks_dir,
            broker_gmt=args.compare_broker_gmt,
            tick_gmt=args.compare_tick_gmt,
            magic_filter=args.magic_filter,
        )
        print(f"\nComparison resume complete for: {run_dir}")
        return 0

    strategies = mt5.parse_mt5_terminal_logs(mt5_terminal_dir, None, None, args.min_trades)
    if args.backtests_only:
        strategies = _dedupe_strategies_by_symbol(strategies)
        if not strategies:
            raise RuntimeError("No active MT5 chart strategies were detected for the backtests-only run.")
        real_from, real_to = mt5._get_date_range_from_strategies(strategies)
    else:
        if stage1 is None or statement_file is None:
            raise RuntimeError("A real statement and stage1 helper are required for comparison modes.")
        strategies = _filter_strategies_to_real_trades(
            stage1, strategies, statement_file, args.broker_gmt, args.magic_filter
        )
        if not strategies:
            raise RuntimeError("No active MT5 chart strategies matched trades in the real statement.")

    terminal_exe = mt5._find_terminal_exe(mt5_terminal_dir, args.mt5_terminal_exe)
    expert_root = mt5._find_expert_root(mt5_terminal_dir)
    candidates = mt5._ea_candidates(expert_root)
    if not candidates:
        raise RuntimeError(f"No eligible EA .ex5 files found under {expert_root}")
    mt5._assign_eas_to_strategies(strategies, candidates, args.default_ea)

    print(f"MT5 terminal: {mt5_terminal_dir}")
    print(f"terminal64.exe: {terminal_exe}")
    print(f"Experts root: {expert_root}")
    print(f"Detected candidate EAs: {len(candidates)}")
    mt5._print_strategy_plan(strategies, args.tester_period)

    if args.backtests_only:
        planned_from = args.full_from.strip() or real_from
        planned_to = args.full_to.strip() or real_to
        print(f"Backtests-only window: {planned_from} -> {planned_to}")
        print("Timeframes are auto-detected from the MT5 charts above; the tester period is only a fallback if a chart timeframe is missing.")

    if args.preview_plan and not args.run_review_now and not args.run_portfolio_now:
        return 0

    if not args.run_review_now:
        return 0

    run_dir = Path(args.resume_run_dir).expanduser().resolve() if args.resume_run_dir else mt5.make_run_folder(out_root, args.account_label)
    if statement_file is not None:
        (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
        shutil.copy2(statement_file, run_dir / "inputs" / statement_file.name)

    if args.backtests_only:
        print(f"\n=== Backtests-only mode: chart-detected backtests ===")
        backtest_from = args.full_from.strip() or real_from
        backtest_to = args.full_to.strip() or real_to
        print(f"Backtest window: {backtest_from} -> {backtest_to} (from real account history)")
        backtest_only_strategies = copy.deepcopy(strategies)
        mt5.run_mt5_backtests(
            strategies=backtest_only_strategies,
            mt5_terminal_dir=mt5_terminal_dir,
            terminal_exe=terminal_exe,
            run_dir=run_dir,
            period=args.tester_period,
            model=args.tester_model,
            from_date=backtest_from,
            to_date=backtest_to,
            deposit=args.tester_deposit,
            leverage=args.tester_leverage,
            use_local=args.tester_use_local,
            delay_ms=args.tester_delay_ms,
            force_order_filling_type=args.tester_order_filling,
            use_live_settings=not args.skip_live_ea_settings,
            backtests_subdir="backtests/chart_only",
            broker_login=args.broker_login,
            broker_password=args.broker_password,
            broker_server=args.broker_server,
        )

        detected_csv = run_dir / "detected_strategies" / "detected_strategies.csv"
        detected_html = run_dir / "detected_strategies" / "detected_strategies.html"
        mt5.write_detected_csv(
            path=detected_csv,
            strategies=backtest_only_strategies,
            backtest_dir=None,
            backtest_suffix=".htm",
            bars_dir=bars_dir,
            bars_suffix=args.bars_suffix,
            default_scale=args.default_scale,
            broker_gmt=args.broker_gmt,
        )
        mt5.write_detected_html(detected_html, backtest_only_strategies)

        print(f"\nBacktests-only mode complete.")
        print(f"Saved backtests: {run_dir / 'backtests' / 'chart_only'}")
        print(f"Run folder: {run_dir}")
        return 0

    print(f"\n=== Phase 1: real-period backtests and comparison ===")
    existing_real_period = _load_existing_real_period_backtests(run_dir) if args.resume_run_dir else []
    if existing_real_period:
        print(f"Reusing {len(existing_real_period)} saved real-period backtest report(s) from {run_dir}", flush=True)
        period_strategies = existing_real_period
    else:
        period_strategies = copy.deepcopy(strategies)
        mt5.run_mt5_backtests(
            strategies=period_strategies,
            mt5_terminal_dir=mt5_terminal_dir,
            terminal_exe=terminal_exe,
            run_dir=run_dir,
            period=args.tester_period,
            model=args.tester_model,
            from_date=real_from,
            to_date=real_to,
            deposit=args.tester_deposit,
            leverage=args.tester_leverage,
            use_local=args.tester_use_local,
            delay_ms=args.tester_delay_ms,
            force_order_filling_type=args.tester_order_filling,
            use_live_settings=not args.skip_live_ea_settings,
            backtests_subdir="backtests/real_period",
            broker_login=args.broker_login,
            broker_password=args.broker_password,
            broker_server=args.broker_server,
        )

    if statement_file is None or stage1_script is None:
        raise RuntimeError("A real statement file is required for the comparison stage.")
    _run_stage1_comparisons(
        stage1_script=stage1_script,
        statement_file=statement_file,
        strategies=period_strategies,
        run_dir=run_dir,
        account_label=args.account_label,
        ticks_dir=ticks_dir,
        broker_gmt=args.compare_broker_gmt,
        tick_gmt=args.compare_tick_gmt,
        magic_filter=args.magic_filter,
    )

    if args.comparison_only:
        print(f"\nComparison-only mode complete.")
        print(f"Run folder: {run_dir}")
        return 0

    print(f"\n=== Phase 2: 5-year backtests and portfolio compile ===")
    full_from = args.full_from.strip() or (datetime.now() - timedelta(days=365 * 5)).strftime("%Y.%m.%d")
    full_to = args.full_to.strip() or datetime.now().strftime("%Y.%m.%d")
    full_strategies = copy.deepcopy(strategies)
    mt5.run_mt5_backtests(
        strategies=full_strategies,
        mt5_terminal_dir=mt5_terminal_dir,
        terminal_exe=terminal_exe,
        run_dir=run_dir,
        period=args.tester_period,
        model=args.tester_model,
        from_date=full_from,
        to_date=full_to,
        deposit=args.tester_deposit,
        leverage=args.tester_leverage,
        use_local=args.tester_use_local,
        delay_ms=args.tester_delay_ms,
        force_order_filling_type=args.tester_order_filling,
        use_live_settings=not args.skip_live_ea_settings,
        backtests_subdir="backtests/full_period",
        broker_login=args.broker_login,
        broker_password=args.broker_password,
        broker_server=args.broker_server,
    )

    detected_csv = run_dir / "detected_strategies" / "detected_strategies.csv"
    detected_html = run_dir / "detected_strategies" / "detected_strategies.html"
    mt5.write_detected_csv(
        path=detected_csv,
        strategies=full_strategies,
        backtest_dir=None,
        backtest_suffix=".htm",
        bars_dir=bars_dir,
        bars_suffix=args.bars_suffix,
        default_scale=args.default_scale,
        broker_gmt=args.broker_gmt,
    )
    mt5.write_detected_html(detected_html, full_strategies)

    portfolio_cmd, warnings = mt5.build_portfolio_command(
        repo_root=repo_root,
        detected_csv=detected_csv,
        out_dir=run_dir / "portfolio" / "results",
        title=args.title,
        account_size=args.account_size,
        dd_tolerance=args.dd_tolerance,
        backtest_months=args.backtest_months,
        no_xlsx=args.no_xlsx,
        ticks_dir=ticks_dir,
        tick_suffix=args.tick_suffix,
        tick_gmt=args.tick_gmt,
        curve_sources=args.curve_sources,
    )
    mt5.write_portfolio_cmd(run_dir / "portfolio" / "run_portfolio_review.cmd", portfolio_cmd)

    for warning in warnings:
        print(f"WARNING: {warning}")

    if args.run_portfolio_now:
        completed = subprocess.run(portfolio_cmd, shell=True)
        if completed.returncode != 0:
            raise RuntimeError(f"Portfolio compile failed (exit {completed.returncode})")

    bundle = mt5.create_review_bundle(run_dir)
    print(f"\nRun folder: {run_dir}")
    print(f"Review bundle: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
