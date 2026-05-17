"""
Pre-compute the FinBERT classification cache for the Meridian backtester.

FinBERTScorer (backtest/signals/finbert.py) classifies one headline at a
time inside the strategy on_bar loop.  For a full 2010-2023 backtest the
strategy ends up calling _classify() ~480k times sequentially — ~13 hours
of CPU work — even though FinBERT is text-only and could batch happily.

This script does the same classifications in batches of 32 *before* the
backtest runs.  Result is the same parquet (``data/cache/finbert_scores.parquet``)
the FinBERTScorer reads at construction, so run_finbert.py then runs as
a pure cache-hit and finishes in minutes.

Usage (from repo root)::

    python -m backtest.scripts.precompute_finbert                  # full
    python -m backtest.scripts.precompute_finbert --batch-size 32  # tune
    python -m backtest.scripts.precompute_finbert --device cpu     # or cuda
    python -m backtest.scripts.precompute_finbert --limit 1000     # smoke test
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd

from backtest.signals.finbert import _DEFAULT_CACHE_PATH, _hash_headline
from backtest.universe import UNIVERSE_2010

_LOG = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _REPO_ROOT / "data" / "cache"


def collect_unique_headlines(symbols: list[str]) -> pd.DataFrame:
    """Walk per-symbol news parquets, return DataFrame[headline_hash, headline].

    Dedupes across symbols (a headline that mentions multiple tickers
    appears once per ticker in FNSPID but classifies identically).
    """
    seen_hashes: set[str] = set()
    rows: list[tuple[str, str]] = []
    for sym in symbols:
        path = _CACHE_DIR / f"news_{sym}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty or "headline" not in df.columns:
            continue
        for h in df["headline"].dropna().astype(str):
            stripped = h.strip()
            if not stripped:
                continue
            hh = _hash_headline(stripped)
            if hh in seen_hashes:
                continue
            seen_hashes.add(hh)
            rows.append((hh, stripped))
    return pd.DataFrame(rows, columns=["headline_hash", "headline"])


def load_existing_cache(cache_path: Path) -> dict[str, float]:
    if not cache_path.exists():
        return {}
    try:
        df = pd.read_parquet(cache_path)
        return dict(zip(df["headline_hash"].astype(str), df["compound"].astype(float)))
    except Exception as exc:
        _LOG.warning("Failed to read existing cache (%s) — starting fresh", exc)
        return {}


def save_cache(cache: dict[str, float], cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "headline_hash": list(cache.keys()),
            "compound": list(cache.values()),
        }
    )
    df.to_parquet(cache_path)


def classify_batch(
    headlines: list[str],
    tokenizer,
    model,
    torch_mod,
    device: str,
) -> list[float]:
    """Classify a batch of headlines, return compound = P(pos) - P(neg) per row."""
    inputs = tokenizer(
        headlines,
        return_tensors="pt",
        truncation=True,
        max_length=512,
        padding=True,
    )
    if device != "cpu":
        inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch_mod.no_grad():
        logits = model(**inputs).logits
    probs = torch_mod.softmax(logits, dim=-1).tolist()
    id2label = {i: lbl.lower() for i, lbl in model.config.id2label.items()}
    pos_idx = next(i for i, l in id2label.items() if l == "positive")
    neg_idx = next(i for i, l in id2label.items() if l == "negative")
    return [float(p[pos_idx]) - float(p[neg_idx]) for p in probs]


def precompute(
    symbols: Optional[list[str]] = None,
    cache_path: Path = _DEFAULT_CACHE_PATH,
    batch_size: int = 32,
    device: str = "cpu",
    limit: Optional[int] = None,
    save_every: int = 5_000,
) -> dict[str, float]:
    """Pre-compute FinBERT scores for every unique headline in the news cache.

    Returns the full cache (also persisted to *cache_path*).
    """
    symbols = list(symbols) if symbols is not None else list(UNIVERSE_2010)

    _LOG.info("Collecting unique headlines across %d symbols…", len(symbols))
    headlines_df = collect_unique_headlines(symbols)
    _LOG.info("%d unique headlines collected", len(headlines_df))

    cache = load_existing_cache(cache_path)
    _LOG.info("Existing cache size: %d entries", len(cache))

    todo_mask = ~headlines_df["headline_hash"].isin(cache.keys())
    todo = headlines_df.loc[todo_mask].reset_index(drop=True)
    if limit is not None:
        todo = todo.head(limit)
    _LOG.info("Headlines requiring classification: %d", len(todo))

    if todo.empty:
        _LOG.info("Nothing to do — cache already complete")
        return cache

    # Lazy heavy imports
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    import torch

    _LOG.info("Loading ProsusAI/finbert tokenizer + model on %s…", device)
    tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
    model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
    model.eval()
    if device != "cpu":
        model.to(device)

    t0 = time.time()
    last_save = 0
    processed = 0
    n = len(todo)

    for start in range(0, n, batch_size):
        batch = todo.iloc[start : start + batch_size]
        texts = batch["headline"].tolist()
        hashes = batch["headline_hash"].tolist()
        scores = classify_batch(texts, tokenizer, model, torch, device)
        for h, s in zip(hashes, scores):
            cache[h] = s
        processed += len(batch)

        if processed - last_save >= save_every:
            save_cache(cache, cache_path)
            last_save = processed
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0.0
            remaining = (n - processed) / rate if rate > 0 else float("inf")
            _LOG.info(
                "Checkpoint: %d / %d (%.1f%%) — %.0f hl/s — ~%.1f min remaining",
                processed, n, 100 * processed / n, rate, remaining / 60,
            )

    save_cache(cache, cache_path)
    elapsed = time.time() - t0
    _LOG.info(
        "Done: classified %d headlines in %.1f s (%.0f hl/s). Cache size: %d.",
        processed, elapsed, processed / elapsed if elapsed > 0 else 0.0, len(cache),
    )
    return cache


def main(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch-size", type=int, default=32,
                        help="batch size for tokenizer + model forward (default 32)")
    parser.add_argument("--device", type=str, default="cpu",
                        help="torch device, e.g. 'cpu' or 'cuda' (default cpu)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap on headlines to classify this run (smoke test)")
    parser.add_argument("--save-every", type=int, default=5_000,
                        help="checkpoint cache every N headlines (default 5000)")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="override symbols; default is UNIVERSE_2010")
    args = parser.parse_args(argv)

    precompute(
        symbols=args.symbols,
        batch_size=args.batch_size,
        device=args.device,
        limit=args.limit,
        save_every=args.save_every,
    )


if __name__ == "__main__":
    main()
