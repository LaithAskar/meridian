"""
Download and slice the FNSPID financial news dataset for the Meridian backtest.

Source: FNSPID — Financial News and Stock Price Integration Dataset
    Dong et al. 2024, arXiv:2402.06698
    https://huggingface.co/datasets/Zihan1004/FNSPID
    License: CC BY-NC 4.0 (non-commercial only)

The dataset is distributed as a single ~23 GB CSV at
    https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/Stock_news/nasdaq_exteral_data.csv

(Note the FNSPID-published filename typo "exteral" — preserved upstream.)

This script:
  1. Streams the CSV from HuggingFace to a local raw file
     (default: ``data/cache/_fnspid_raw.csv``).
  2. Parses it in chunks with pandas, keeping only the columns we need
     (Date, Article_title, Stock_symbol, Publisher, Url) — discards the
     heavy ``Article`` / ``*_summary`` columns at parse time so peak memory
     stays small even though the CSV is 23 GB on disk.
  3. Filters each chunk to (a) Stock_symbol in our universe and
     (b) Date in [2010-01-01, 2023-12-31].
  4. Groups by ticker and writes one parquet per symbol at
     ``data/cache/news_{symbol}.parquet``.
  5. Logs coverage (tickers found vs tickers absent from FNSPID).

Usage (from repo root)::

    python -m backtest.scripts.download_news               # full pipeline
    python -m backtest.scripts.download_news --dry-run     # show plan, no I/O
    python -m backtest.scripts.download_news --symbols AAPL MSFT
    python -m backtest.scripts.download_news --max-rows 200000   # smoke test
    python -m backtest.scripts.download_news --keep-raw          # do not delete CSV
    python -m backtest.scripts.download_news --skip-download     # reuse local CSV

After the parquet files are present, sentiment signal wrappers can call
``backtest.news_data.load_news(symbol, start, end)`` for fast in-memory access.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests

from backtest.universe import UNIVERSE_2010

FNSPID_URL = (
    "https://huggingface.co/datasets/Zihan1004/FNSPID/resolve/main/"
    "Stock_news/nasdaq_exteral_data.csv"
)

# Backtest window (DESIGN.md §6 — FNSPID ends 2023-12-31).
START_DATE = date(2010, 1, 1)
END_DATE = date(2023, 12, 31)

# Universe + SPY.  We exclude ^VIX because there are no headlines for an index.
DOWNLOAD_SYMBOLS: list[str] = list(UNIVERSE_2010) + ["SPY"]

# Columns we keep from the FNSPID CSV.  Heavy columns
# (Article, Lsa_summary, Luhn_summary, Textrank_summary, Lexrank_summary,
#  Author) are pruned at parse time so peak memory stays small.
_KEEP_COLS: list[str] = ["Date", "Article_title", "Stock_symbol", "Publisher", "Url"]

# Output schema (lowercase, normalized) — must match backtest.news_data.NEWS_COLUMNS
_OUT_COLS: list[str] = ["date", "headline", "publisher", "url"]

_CHUNK_ROWS = 200_000  # rows per pandas chunk — ~50-100 MB working set
_DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024  # 8 MiB per HTTP chunk


def _cache_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "cache"


def _raw_csv_path() -> Path:
    return _cache_dir() / "_fnspid_raw.csv"


def _format_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def stream_download(url: str, dest: Path, expected_bytes: Optional[int] = None) -> None:
    """Stream *url* to *dest* with progress.  Skips if dest already exists."""
    if dest.exists():
        print(f"  CSV already present: {dest} ({_format_bytes(dest.stat().st_size)}) — skipping download")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)

    print(f"  Downloading from: {url}")
    print(f"  Saving to       : {dest}")

    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()

        total = int(resp.headers.get("Content-Length") or expected_bytes or 0)
        downloaded = 0
        last_print = 0

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded - last_print >= 256 * 1024 * 1024:  # progress every 256 MiB
                    last_print = downloaded
                    pct = (downloaded / total * 100) if total else 0.0
                    print(
                        f"    {_format_bytes(downloaded)} / {_format_bytes(total)} "
                        f"({pct:.1f}%)",
                        flush=True,
                    )

    print(f"  Download complete: {_format_bytes(dest.stat().st_size)}")


def iter_filtered_chunks(
    csv_path: Path,
    symbols: set[str],
    start: date,
    end: date,
    max_rows: Optional[int] = None,
) -> Iterable[pd.DataFrame]:
    """
    Yield filtered chunks from the FNSPID CSV.

    Each yielded chunk has the *output* schema (lowercase ``date, headline,
    publisher, url``) restricted to symbols in *symbols* and dates in
    [start, end].
    """
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)

    rows_read = 0
    rows_kept = 0

    reader = pd.read_csv(
        csv_path,
        usecols=_KEEP_COLS,
        chunksize=_CHUNK_ROWS,
        dtype={
            "Article_title": "string",
            "Stock_symbol": "string",
            "Publisher": "string",
            "Url": "string",
        },
        on_bad_lines="skip",
        low_memory=True,
    )

    for i, raw in enumerate(reader):
        rows_read += len(raw)

        # Date parsing — FNSPID dates look like "2020-06-05 06:30:54 UTC".
        # Parse as UTC (the literal "UTC" suffix makes pandas return tz-aware)
        # then strip the tz so we can compare against tz-naive Timestamps.
        # errors='coerce' turns unparseable rows into NaT which we then drop.
        raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce", utc=True)
        if hasattr(raw["Date"].dt, "tz") and raw["Date"].dt.tz is not None:
            raw["Date"] = raw["Date"].dt.tz_localize(None)

        # Symbol filter — vectorized membership test against the set.
        sym_mask = raw["Stock_symbol"].isin(symbols)
        date_mask = (raw["Date"] >= start_ts) & (raw["Date"] <= end_ts)
        keep = raw.loc[sym_mask & date_mask].copy()

        # Normalize to output schema
        keep = keep.rename(
            columns={
                "Date": "date",
                "Article_title": "headline",
                "Stock_symbol": "symbol",
                "Publisher": "publisher",
                "Url": "url",
            }
        )

        # Drop NaN headlines
        keep = keep.dropna(subset=["headline"])
        rows_kept += len(keep)

        if i % 50 == 0 and i > 0:
            print(
                f"    chunk {i:5d}: read {rows_read:>12,} rows / kept {rows_kept:>10,}",
                flush=True,
            )

        if not keep.empty:
            yield keep

        if max_rows is not None and rows_read >= max_rows:
            print(f"    --max-rows {max_rows} reached; stopping")
            break

    print(f"  Total rows read : {rows_read:,}")
    print(f"  Total rows kept : {rows_kept:,}")


def write_per_symbol_parquets(
    chunks: Iterable[pd.DataFrame],
    symbols: list[str],
    cache_dir: Path,
    force: bool = False,
) -> dict[str, int]:
    """
    Accumulate chunks by ticker and write one parquet per symbol.

    Returns
    -------
    dict mapping symbol -> number of headlines written.  Symbols absent
    from the input chunks (no headlines in FNSPID) get a 0-row parquet
    written so downstream loaders don't have to special-case missing files.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Buffer rows per symbol.  For 100 symbols * ~10k headlines/symbol
    # this is ~1M rows total — well within RAM.  If FNSPID coverage is
    # heavier than expected we can revisit with a disk-backed buffer.
    buffers: dict[str, list[pd.DataFrame]] = {s: [] for s in symbols}

    for chunk in chunks:
        for sym, sub in chunk.groupby("symbol"):
            if sym not in buffers:
                continue  # belt-and-braces: should already be filtered
            sub = sub[_OUT_COLS].copy()
            buffers[sym].append(sub)

    counts: dict[str, int] = {}
    for sym in symbols:
        out_path = cache_dir / f"news_{sym}.parquet"

        if out_path.exists() and not force:
            existing = pd.read_parquet(out_path)
            # If --force was not passed and a non-empty cache already exists,
            # keep it.  Empty caches get overwritten (likely from a prior dry
            # run or first-time-no-data scenario).
            if not existing.empty:
                counts[sym] = len(existing)
                continue

        parts = buffers[sym]
        if parts:
            df = pd.concat(parts, ignore_index=True).sort_values("date").reset_index(drop=True)
        else:
            df = pd.DataFrame(
                {
                    "date": pd.Series(dtype="datetime64[ns]"),
                    "headline": pd.Series(dtype="object"),
                    "publisher": pd.Series(dtype="object"),
                    "url": pd.Series(dtype="object"),
                }
            )

        df.to_parquet(out_path)
        counts[sym] = len(df)

    return counts


def main(
    symbols: Optional[list[str]] = None,
    dry_run: bool = False,
    keep_raw: bool = False,
    skip_download: bool = False,
    force: bool = False,
    max_rows: Optional[int] = None,
) -> int:
    syms = symbols if symbols is not None else DOWNLOAD_SYMBOLS
    sym_set = set(syms)

    cdir = _cache_dir()
    csv_path = _raw_csv_path()

    print("FNSPID news downloader")
    print(f"  Window      : {START_DATE} -> {END_DATE}")
    print(f"  Symbols     : {len(syms)} tickers")
    print(f"  Cache dir   : {cdir}")
    print(f"  Raw CSV path: {csv_path}")
    print(f"  Source URL  : {FNSPID_URL}")
    print()

    if dry_run:
        print("--dry-run: would download ~23 GB CSV, filter to symbols+window,")
        print("           and write per-symbol parquets.  No I/O performed.")
        return 0

    if not skip_download:
        print("Step 1/3: downloading FNSPID CSV (~23 GB) ...")
        stream_download(FNSPID_URL, csv_path)
    else:
        if not csv_path.exists():
            print(f"ERROR: --skip-download but no local CSV at {csv_path}")
            return 1
        print(f"Step 1/3: skipping download, using local {csv_path}")
    print()

    print("Step 2/3: streaming + filtering CSV ...")
    counts = write_per_symbol_parquets(
        iter_filtered_chunks(csv_path, sym_set, START_DATE, END_DATE, max_rows=max_rows),
        syms,
        cdir,
        force=force,
    )
    print()

    print("Step 3/3: coverage summary")
    nonempty = sorted([s for s, n in counts.items() if n > 0])
    empty = sorted([s for s, n in counts.items() if n == 0])
    print(f"  With headlines    : {len(nonempty)}/{len(syms)} symbols")
    print(f"  No headlines (0)  : {len(empty)}/{len(syms)} symbols")
    if empty:
        print(f"  Empty list        : {', '.join(empty)}")
    print()
    print("Top 10 by headline count:")
    for sym, n in sorted(counts.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {sym:8s}  {n:>8,}")

    if not keep_raw and csv_path.exists():
        size = csv_path.stat().st_size
        print(f"\nDeleting raw CSV ({_format_bytes(size)}) — pass --keep-raw to retain.")
        csv_path.unlink()

    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download and slice the FNSPID news dataset for Meridian backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--dry-run", action="store_true", help="show plan only, no I/O")
    p.add_argument(
        "--symbols",
        nargs="+",
        metavar="TICKER",
        help="subset of tickers (default: UNIVERSE_2010 + SPY)",
    )
    p.add_argument(
        "--keep-raw", action="store_true",
        help="do not delete the 23 GB raw CSV after slicing",
    )
    p.add_argument(
        "--skip-download", action="store_true",
        help="reuse a local raw CSV instead of re-downloading",
    )
    p.add_argument(
        "--force", action="store_true",
        help="overwrite existing per-symbol parquets even if non-empty",
    )
    p.add_argument(
        "--max-rows", type=int, default=None,
        help="stop after reading N raw rows (smoke testing)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    rc = main(
        symbols=args.symbols,
        dry_run=args.dry_run,
        keep_raw=args.keep_raw,
        skip_download=args.skip_download,
        force=args.force,
        max_rows=args.max_rows,
    )
    sys.exit(rc)
