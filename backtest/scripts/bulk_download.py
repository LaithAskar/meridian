"""
One-time bulk-download script for the Meridian backtester.

Pulls hourly bars for every symbol in UNIVERSE_2016 from Alpaca (IEX feed)
over 2016-01-01 to 2024-12-31 and writes one parquet file per symbol to
data/cache/.

Run locally — the cloud routine has no Alpaca credentials.

    export ALPACA_API_KEY=...        # bash
    export ALPACA_SECRET_KEY=...
    # or PowerShell:
    # $env:ALPACA_API_KEY = "..."
    # $env:ALPACA_SECRET_KEY = "..."

    .venv/Scripts/python.exe backtest/scripts/bulk_download.py

Resume-safe: re-run anytime — symbols already fully cached are skipped via
fetch_bars's internal cache check. Failed symbols are listed at the end;
re-run to retry them.

Once finished:

    git add data/cache/
    git commit -m "data: bulk bar cache for UNIVERSE_2016 (2016-2024)"
    git push origin main

The cloud routine then picks up Phase 0.3 and verifies the bundle.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from backtest.data import fetch_bars  # noqa: E402
from backtest.universe import UNIVERSE_2016  # noqa: E402

START = date(2016, 1, 1)
END = date(2024, 12, 31)
TIMEFRAME = "1Hour"

# Alpaca free tier: 200 req/min. Pace at ~150/min for headroom on retries.
PACE_SECONDS = 60.0 / 150.0


def main() -> int:
    if not os.environ.get("ALPACA_API_KEY") or not os.environ.get("ALPACA_SECRET_KEY"):
        print("ERROR: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set.", file=sys.stderr)
        return 1

    total = len(UNIVERSE_2016)
    failed: list[tuple[str, str]] = []

    print(f"Downloading {total} symbols, {START} -> {END}, timeframe={TIMEFRAME}")
    print(f"Cache dir: {_REPO_ROOT / 'data' / 'cache'}")
    print()

    t0 = time.time()

    for i, sym in enumerate(UNIVERSE_2016, start=1):
        sym_t0 = time.time()
        try:
            df = fetch_bars([sym], START, END, timeframe=TIMEFRAME)
            n_bars = len(df) if not df.empty else 0
            dt = time.time() - sym_t0
            status = "CACHE" if dt < 0.5 else "FETCH"
            print(f"[{i:3d}/{total}] {sym:6s} {status}  bars={n_bars:>6,}  ({dt:5.1f}s)")
        except Exception as exc:  # noqa: BLE001
            print(f"[{i:3d}/{total}] {sym:6s} FAILED  {exc}", file=sys.stderr)
            failed.append((sym, str(exc)))

        time.sleep(PACE_SECONDS)

    elapsed = time.time() - t0
    print()
    print(f"Total wall time: {elapsed / 60:.1f} min")
    print(f"Failed: {len(failed)}/{total}")

    if failed:
        print()
        print("Failed symbols (re-run script to retry — cached symbols will be skipped):")
        for sym, msg in failed:
            print(f"  {sym}: {msg}")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
