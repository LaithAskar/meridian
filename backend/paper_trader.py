"""
Forward-extended paper trader for the three Meridian strategies.

Reuses the backtest engine entirely.  Each invocation runs the chosen
strategy from the canonical START date through the requested `end` date
(defaults to today), writes the same outputs the backtest produces
(``equity_curve.csv``, ``trades.csv``, ``metrics.json``, ``spy_curve.csv``)
into ``data/paper/{strategy}/`` instead of ``backtest/results/{strategy}/``,
and tags the metrics with ``mode='paper'`` so the dashboard can distinguish.

Semantics
---------
This is "paper trading" in the forward-extension sense: the SAME backtest
strategy is run with an end date that drifts forward, and the trailing
slice of the equity curve becomes the live paper history.  No broker
integration; no per-day state machine.  When the cron / cloud routine
runs `python -m backend.paper_trader --strategy quant` daily, the curve
grows one day at a time as new yfinance data lands.

Sentiment strategies (VADER, FinBERT) are bounded by the FNSPID news
dataset which ends 2023-12-31.  Forward extension past that date would
silently produce flat signals (no news = no orders), so paper runs for
the sentiment backends cap at FNSPID_END and emit a dashboard-readable
note ("frozen at 2023-12-31 — requires live news pipeline").

Usage
-----
    python -m backend.paper_trader                        # all three (quant extends; sentiment cap)
    python -m backend.paper_trader --strategy quant       # one strategy
    python -m backend.paper_trader --strategy quant --end 2026-05-17
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

_LOG = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PAPER_DIR = _REPO_ROOT / "data" / "paper"

# Canonical start matches the backtest START.
PAPER_START = date(2010, 1, 1)

# Sentiment strategies cannot run past the FNSPID news dataset cutoff.
FNSPID_END = date(2023, 12, 31)


def _final_positions(result_obj: Any) -> dict[str, float]:
    """Best-effort extraction of {symbol: qty} from a BacktestResult.

    The exact attribute depends on engine.run() — we probe common names so
    a downstream refactor of the engine doesn't break the dashboard.
    """
    for attr in ("final_positions", "ending_positions", "positions"):
        v = getattr(result_obj, attr, None)
        if isinstance(v, dict) and v:
            return {sym: float(q) for sym, q in v.items()}
    portfolio = getattr(result_obj, "portfolio", None)
    if portfolio is not None:
        positions = getattr(portfolio, "positions", None)
        if isinstance(positions, dict):
            return {sym: float(getattr(p, "qty", 0)) for sym, p in positions.items() if getattr(p, "qty", 0)}
    return {}


def _final_equity(result_obj: Any, fallback: float) -> float:
    ec = getattr(result_obj, "equity_curve", None)
    if ec is not None and len(ec) > 0:
        try:
            return float(ec["equity"].iloc[-1])
        except Exception:
            pass
    return fallback


def _run_quant_paper(end: date, output_dir: Path, initial_cash: float) -> dict[str, Any]:
    """Run the quant backtest with end-date drifting forward and write to paper dir."""
    from backtest.run_quant import run_quant_backtest

    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = run_quant_backtest(
        start=PAPER_START,
        end=end,
        initial_cash=initial_cash,
        output_dir=output_dir,
    )
    metrics["mode"] = "paper"
    metrics["paper_end"] = end.isoformat()
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def _run_vader_paper(end: date, output_dir: Path, initial_cash: float) -> dict[str, Any]:
    """VADER is data-bound by FNSPID; cap end at FNSPID_END."""
    from backtest.run_vader import run_vader_backtest

    effective_end = min(end, FNSPID_END)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = run_vader_backtest(
        start=PAPER_START,
        end=effective_end,
        initial_cash=initial_cash,
        output_dir=output_dir,
    )
    metrics["mode"] = "paper"
    metrics["paper_end"] = effective_end.isoformat()
    if end > FNSPID_END:
        metrics["data_limit_note"] = (
            f"frozen at {FNSPID_END.isoformat()} — requires live news pipeline "
            f"to extend beyond FNSPID's coverage"
        )
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


def _run_finbert_paper(end: date, output_dir: Path, initial_cash: float) -> dict[str, Any]:
    from backtest.run_finbert import run_finbert_backtest

    effective_end = min(end, FNSPID_END)
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = run_finbert_backtest(
        start=PAPER_START,
        end=effective_end,
        initial_cash=initial_cash,
        output_dir=output_dir,
    )
    metrics["mode"] = "paper"
    metrics["paper_end"] = effective_end.isoformat()
    if end > FNSPID_END:
        metrics["data_limit_note"] = (
            f"frozen at {FNSPID_END.isoformat()} — requires live news pipeline "
            f"to extend beyond FNSPID's coverage"
        )
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    return metrics


_RUNNERS: dict[str, Callable[[date, Path, float], dict[str, Any]]] = {
    "quant":   _run_quant_paper,
    "vader":   _run_vader_paper,
    "finbert": _run_finbert_paper,
}


def run_paper(
    strategy: str,
    end: Optional[date] = None,
    initial_cash: float = 1_000_000.0,
    paper_dir: Path = _PAPER_DIR,
) -> dict[str, Any]:
    """Run paper-mode forward extension for one strategy."""
    if strategy not in _RUNNERS:
        raise ValueError(f"unknown strategy: {strategy!r}")
    end_date = end if end is not None else date.today()
    output_dir = paper_dir / strategy
    _LOG.info("Paper run: %s → %s", strategy, end_date)
    return _RUNNERS[strategy](end_date, output_dir, initial_cash)


def main(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strategy", choices=("quant", "vader", "finbert", "all"),
                        default="all",
                        help="which strategy to run (default: all)")
    parser.add_argument("--end", type=lambda s: date.fromisoformat(s),
                        default=None, metavar="YYYY-MM-DD",
                        help="paper end date (default: today)")
    parser.add_argument("--cash", type=float, default=1_000_000.0,
                        help="initial cash (default 1,000,000)")
    args = parser.parse_args(argv)

    strategies = ("quant", "vader", "finbert") if args.strategy == "all" else (args.strategy,)
    for s in strategies:
        try:
            metrics = run_paper(s, end=args.end, initial_cash=args.cash)
            sharpe = metrics.get("full_window", {}).get("sharpe")
            print(f"{s}: paper Sharpe = {sharpe}")
        except Exception as exc:
            _LOG.error("Paper run failed for %s: %s", s, exc, exc_info=True)


if __name__ == "__main__":
    main()
