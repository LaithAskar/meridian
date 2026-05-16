"""
Download the full yfinance daily bar cache for the 2010-2024 backtest.

Run this script ONCE on a machine with unrestricted internet access, then
commit the parquet files so the cloud backtest routine can find them.

Usage (from repo root):
    python -m backtest.scripts.download_cache
    python -m backtest.scripts.download_cache --dry-run   # list status, no download
    python -m backtest.scripts.download_cache --symbols AAPL MSFT  # subset

After running:
    git add data/cache/
    git commit -m "add yfinance parquet cache (2010-2024)"
    git push origin main

The cloud routine will then find the parquet files, skip all downloads, and
run the full quant backtest end-to-end (TODO item 3.1) on its next wake.

NOTE: data/cache/ was previously in .gitignore; that entry was removed in the
same commit that added this script.  A plain `git add data/cache/` now works
without --force.

Estimated download time : 5-15 min (102 symbols × ~0.2 s/symbol + latency)
Estimated cache size    : ~180 MB (102 parquet files, ~3 500 rows each)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from backtest.data import fetch_bars
from backtest.universe import UNIVERSE_2010

# Symbols required by run_quant.py: the 100-ticker universe plus SPY and VIX
DOWNLOAD_SYMBOLS: list[str] = list(UNIVERSE_2010) + ["SPY", "^VIX"]

START = date(2010, 1, 1)
END = date(2024, 12, 31)


def _cache_dir() -> Path:
    """Return the absolute path to data/cache/ (repo-root relative)."""
    return Path(__file__).resolve().parents[2] / "data" / "cache"


def download(symbols: list[str], start: date, end: date) -> list[str]:
    """
    Download and cache bars for each symbol individually so progress is visible.

    Returns a list of symbols for which no data was retrieved (empty result
    from yfinance — expected for a handful of 2010-OEX tickers that later
    delisted with no yfinance coverage).
    """
    failed: list[str] = []
    for i, sym in enumerate(symbols, 1):
        print(f"  [{i:3d}/{len(symbols)}] {sym:10s}", end="", flush=True)
        bars = fetch_bars([sym], start, end)
        if bars.empty:
            print("  FAILED (no yfinance data)")
            failed.append(sym)
        else:
            print(f"  ok  ({len(bars):5d} rows)")
    return failed


def dry_run(symbols: list[str]) -> None:
    """Print cache status for each symbol without downloading anything."""
    cdir = _cache_dir()
    print(f"Cache dir: {cdir}")
    cached, missing = 0, 0
    for sym in symbols:
        path = cdir / f"{sym}_1d.parquet"
        if path.exists():
            status = "CACHED"
            cached += 1
        else:
            status = "missing"
            missing += 1
        print(f"  {sym:10s}  {status}")
    print(f"\n{cached} cached, {missing} missing (of {len(symbols)} total)")


def main(symbols: list[str] | None = None, is_dry_run: bool = False) -> None:
    syms = symbols if symbols is not None else DOWNLOAD_SYMBOLS

    if is_dry_run:
        dry_run(syms)
        return

    cdir = _cache_dir()
    print(f"Downloading {len(syms)} symbols: {START} → {END}")
    print(f"Cache dir : {cdir}")
    print()

    failed = download(syms, START, END)

    print()
    n_ok = len(syms) - len(failed)
    print(f"Done. {n_ok}/{len(syms)} symbols downloaded successfully.")
    if failed:
        print(f"No data for: {', '.join(failed)}")
        print("These symbols are expected to be sparse/absent for delisted names.")

    print()
    print("Next steps:")
    print("  git add data/cache/")
    print("  git commit -m 'add yfinance parquet cache (2010-2024)'")
    print("  git push origin main")
    print()
    print("The cloud routine will then run TODO item 3.1 automatically.")

    if n_ok == 0:
        print("\nERROR: 0 symbols downloaded — likely a network block.")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download yfinance bar cache for the Meridian backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print cache status without downloading",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        metavar="TICKER",
        help="subset of symbols to download (default: full universe + SPY + ^VIX)",
    )
    args = parser.parse_args()
    main(symbols=args.symbols, is_dry_run=args.dry_run)
