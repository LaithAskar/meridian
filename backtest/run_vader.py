"""
End-to-end VADER sentiment backtest over the FNSPID window (2010-2023).

Usage (from repo root)::

    python -m backtest.run_vader
    python -m backtest.run_vader --positions 10 --cash 1000000

Outputs written to ``backtest/results/vader/``::

    equity_curve.csv  — daily equity / cash / num_positions (DatetimeIndex)
    trades.csv        — closed-trade log
    metrics.json      — Sharpe / max DD / hit rate / etc. per window & regime
    spy_curve.csv     — SPY buy-and-hold equity (benchmark)

Window
------
FNSPID news data ends 2023-12-31 (DESIGN.md disclosure §6).  This backtest
runs 2010-01-01 → 2023-12-31.  For comparison with the quant backtest, the
quant equity curve should be sliced to the same window in the comparison
notebook (Phase 3.4) — apples-to-apples.

Regime splits follow DESIGN.md::

    Pre-COVID  : 2010-01-01 → 2020-02-29
    Post-COVID : 2020-03-01 → 2023-12-31

Prerequisites
-------------
``data/cache/news_{symbol}.parquet`` must exist for every symbol in
UNIVERSE_2010.  Populate via::

    python -m backtest.scripts.download_news
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.engine import Engine
from backtest.run_common import (
    benchmark_block,
    load_spy_close,
    metrics_for_window,
    slice_window,
    spy_returns_for_windows,
)
from backtest.signals.vader import VADERStrategy
from backtest.universe import UNIVERSE_2010

_LOG = logging.getLogger(__name__)

FULL_START = date(2010, 1, 1)
FULL_END = date(2023, 12, 31)               # FNSPID coverage ends here
PRE_COVID_END = date(2020, 2, 29)
POST_COVID_START = date(2020, 3, 1)

_RESULTS_DIR = Path(__file__).resolve().parent / "results" / "vader"


def run_vader_backtest(
    universe: list[str] | None = None,
    start: date = FULL_START,
    end: date = FULL_END,
    max_positions: int = 10,
    initial_cash: float = 1_000_000.0,
    threshold: float = 0.35,
    min_headlines: int = 2,
    min_consensus: float = 0.6,
    output_dir: Path = _RESULTS_DIR,
) -> dict[str, Any]:
    """Run VADERStrategy end-to-end and persist results."""
    if universe is None:
        universe = list(UNIVERSE_2010)

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Strategy + engine ─────────────────────────────────────────────────
    _LOG.info(
        "Running VADERStrategy: %d symbols, %s → %s, threshold=%.2f, max_positions=%d",
        len(universe), start, end, threshold, max_positions,
    )
    strategy = VADERStrategy(
        threshold=threshold,
        max_positions=max_positions,
        min_headlines=min_headlines,
        min_consensus=min_consensus,
    )
    engine = Engine(
        strategy=strategy,
        universe=universe,
        start=start,
        end=end,
        initial_cash=initial_cash,
        max_positions=max_positions,
    )
    result = engine.run()
    _LOG.info(
        "Engine done: %d trading days, %d closed trades",
        len(result.equity_curve), len(result.trades),
    )

    # ── Persist raw outputs ───────────────────────────────────────────────
    result.equity_curve.to_csv(output_dir / "equity_curve.csv")
    result.trades.to_csv(output_dir / "trades.csv", index=False)
    _LOG.info("Wrote equity_curve.csv and trades.csv")

    # ── SPY benchmark ─────────────────────────────────────────────────────
    spy_close = load_spy_close(start, end)
    if not spy_close.empty:
        spy_bah = (spy_close / float(spy_close.iloc[0])) * initial_cash
        spy_df = spy_bah.rename("equity").to_frame()
        spy_df.index.name = "ts"
        spy_df.to_csv(output_dir / "spy_curve.csv")

    # ── Regime metric slices ──────────────────────────────────────────────
    pre_ec, pre_trades   = slice_window(result.equity_curve, result.trades, end=PRE_COVID_END)
    post_ec, post_trades = slice_window(result.equity_curve, result.trades, start=POST_COVID_START)

    full_years = (end - start).days / 365.25
    pre_years  = (PRE_COVID_END - start).days / 365.25
    post_years = (end - POST_COVID_START).days / 365.25

    full_spy_rets, pre_spy_rets, post_spy_rets = spy_returns_for_windows(
        spy_close, start, end, PRE_COVID_END, POST_COVID_START
    )

    metrics: dict[str, Any] = {
        "run_date": date.today().isoformat(),
        "strategy": "vader",
        "parameters": {
            "universe_size":  len(universe),
            "start":          start.isoformat(),
            "end":            end.isoformat(),
            "max_positions":  max_positions,
            "initial_cash":   initial_cash,
            "slippage_bps":   5,
            "threshold":      threshold,
            "min_headlines":  min_headlines,
            "min_consensus":  min_consensus,
        },
        "full_window": metrics_for_window(
            result.equity_curve, result.trades, full_years, full_spy_rets
        ),
        "pre_covid":   metrics_for_window(pre_ec, pre_trades, pre_years, pre_spy_rets),
        "post_covid":  metrics_for_window(post_ec, post_trades, post_years, post_spy_rets),
        "benchmark":   benchmark_block(
            spy_close, start, end, PRE_COVID_END, POST_COVID_START,
            full_years, pre_years, post_years,
        ),
    }

    metrics_path = output_dir / "metrics.json"
    with open(metrics_path, "w") as fh:
        json.dump(metrics, fh, indent=2)
    _LOG.info("Wrote metrics.json to %s", output_dir)

    return metrics


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="Run VADER sentiment backtest end-to-end")
    parser.add_argument("--positions", type=int, default=10, metavar="N",
                        help="max concurrent positions (default: 10)")
    parser.add_argument("--cash", type=float, default=1_000_000.0, metavar="USD",
                        help="initial cash (default: 1,000,000)")
    parser.add_argument("--threshold", type=float, default=0.35, metavar="X",
                        help="VADER compound threshold (default: 0.35 — matches live bot)")
    parser.add_argument("--min-headlines", type=int, default=2, metavar="N",
                        help="minimum headlines per (ticker, date) (default: 2)")
    parser.add_argument("--min-consensus", type=float, default=0.6, metavar="X",
                        help="minimum directional fraction (default: 0.6)")
    args = parser.parse_args()

    result_metrics = run_vader_backtest(
        max_positions=args.positions,
        initial_cash=args.cash,
        threshold=args.threshold,
        min_headlines=args.min_headlines,
        min_consensus=args.min_consensus,
    )
    print(json.dumps(result_metrics, indent=2))
