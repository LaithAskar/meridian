# Meridian Backtest Log

Narrative record of each backtest conducted — what the strategy is, what
happened during the run (bugs, surprises, anomalies), and how the result is
interpreted. When a strategy is paper-traded, its paper-trading result is
appended in the same section so backtest and out-of-sample behaviour sit
side by side.

**This file is prose, not a numbers source.** Canonical metrics live in
`backtest/results/{strategy}/metrics.json` and the results notebook
(`backtest/notebooks/results.ipynb`, which auto-loads them). Headline figures
are quoted here for narrative context only — if they ever disagree with
`metrics.json`, trust `metrics.json`.

**Window asymmetry.** Quant runs 2010–2024; VADER and FinBERT stop at
2023-12-31, where FNSPID news coverage ends. A strict three-way comparison
restricts quant to 2010–2023.

---

## Quant

### Backtest — 2026-05-21

**Strategy.** Price-based quant signal (momentum + mean-reversion) over the
Jan-2010 S&P 100 universe. Signal spec: `backtest/DESIGN.md`.

**Run.** 92 symbols, 2010-01-01 → 2024-12-31, max 10 positions, 5 bps
slippage each side, $1M initial. Runtime ~64 minutes. Metrics:
`results/quant/metrics.json`.

**Headline.** Sharpe 0.76 vs SPY 0.84 (excess −0.08). Max drawdown 31.9%
(vs SPY 33.7%). 215 trades, 58% hit rate, total return 5.34x vs SPY 5.81x.

**What happened.**
- *EMC data-integrity bug (found + fixed).* The ticker `EMC` was reused —
  the original EMC Corporation was acquired by Dell in 2016, and yfinance
  now returns 411 bars under `EMC` from 2023-05-15 belonging to an unrelated
  company. The backtester was silently capable of feeding wrong-company
  data. Fixed in commit `12a1a44`: `EMC` added to `KNOWN_NO_DATA`, and a
  `tradable_universe()` helper now enforces the exclusion (it was
  documentation-only before). `universe_size` is 92 active (nominally 100).
- *The fix changed no numbers.* The post-EMC-fix re-run produced aggregate
  metrics identical to the pre-fix run. The 8 `KNOWN_NO_DATA` tickers have
  no usable price data and never traded — removing them changed the label,
  not the simulation. The fix removes latent risk; it does not move the
  result.
- *64-minute runtime anomaly.* This run took ~64 minutes, while the FinBERT
  backtest over the same engine and universe took ~5. Unexplained — open
  lead for the A.1 `engine.py` audit (likely a per-bar inefficiency).

**Interpretation.** The quant strategy tracks SPY closely — ~92% of total
return, marginally smaller drawdown, marginally worse Sharpe after costs,
negative excess Sharpe in both regimes. This is a genuine "no measured
risk-adjusted edge" result — the expected outcome for a simple price-based
strategy on large-cap US equities, the most efficiently priced segment. It
is interview-defensible framed honestly, and it is not a project failure:
the rigorous measurement is the deliverable.

### Paper trading

_Not yet run. After the first paper run, append here: run dates + config,
result (pointer to `data/paper/quant/`), and whether out-of-sample behaviour
held up against the backtest._

---

## VADER

### Backtest — 2026-05-17

**Strategy.** News-sentiment signal using VADER, a general-purpose lexicon
sentiment model, applied to FNSPID news headlines. Threshold 0.35, min 2
headlines, 0.60 consensus.

**Run.** 92 symbols, 2010-01-01 → 2023-12-31 (FNSPID news window), max 10
positions, 5 bps slippage, $1M initial. Metrics: `results/vader/metrics.json`.

**Headline.** Sharpe 0.59 vs SPY 0.79 (excess −0.20) — the worst of the
three. Max drawdown 41.2% (worse than SPY's 33.7%). Only 69 trades, ~540-day
average holding period, 62% hit rate, total return 2.17x vs SPY 4.46x.

**What happened.**
- *news_data performance bug (found + fixed during bringup).* The first
  VADER run did not finish in 40 minutes. Cause: `load_news` was called per
  `(symbol, bar)`, producing ~320k full-parquet reads per backtest. Fixed
  with an in-memory cache (commit `6c469bd`); the run then completed in ~7
  minutes.
- *Thin, slow strategy.* 69 trades over 14 years with a ~540-day average
  hold — VADER rarely produced an actionable signal; it behaves more like
  occasional concentrated bets than an active strategy.

**Interpretation.** VADER produced no measurable alpha and underperformed
SPY and both other signals on every axis — lower Sharpe, deeper drawdown,
lower return. A generic English-language sentiment lexicon is poorly matched
to financial news: it has no notion of "beat estimates" vs "missed
estimates." This is a useful negative result — it is the baseline that
motivates the domain-specific model and quantifies what that model is worth.

### Paper trading

_Not yet run._

---

## FinBERT

### Backtest — 2026-05-21

**Strategy.** News-sentiment signal using FinBERT (`ProsusAI/finbert`), a
transformer fine-tuned on financial text, applied to FNSPID headlines.
Threshold 0.60, min 2 headlines, 0.60 consensus.

**Run.** 92 symbols, 2010-01-01 → 2023-12-31 (FNSPID news window), max 10
positions, 5 bps slippage, $1M initial. Runtime ~5 minutes — the FinBERT
classification is a precomputed cache hit. Metrics:
`results/finbert/metrics.json`.

**Headline.** Sharpe 0.71 vs SPY 0.79 (excess −0.08). Max drawdown 30.0%
(better than SPY's 33.7%). 235 trades, 60% hit rate, total return 3.36x vs
SPY 4.46x.

**What happened.**
- *FinBERT classification precomputed.* Classifying one headline at a time
  inside the backtest loop would take ~13 hours. Instead all 340,840 unique
  FNSPID headlines were classified offline in batches and cached to
  `data/cache/finbert_scores.parquet` (~65 min compute), making `run_finbert`
  a pure cache hit.
- *Cloud-offload attempt failed.* An attempt to run the precompute on a
  cloud routine failed: the cloud environment returns HTTP 403 from
  HuggingFace, so the FinBERT model weights cannot be downloaded there. The
  precompute was run locally instead. Lesson: cloud routines have restricted
  outbound network — model downloads and open-web fetches do not work there.
- *FinBERT clearly beat VADER* — 0.71 vs 0.59 on the same window and
  benchmark. The finance-domain transformer closed most of the gap to SPY
  (excess −0.08) where the generic lexicon did not (excess −0.20).
- *Regime split is not flat.* Pre-COVID excess Sharpe −0.17; post-COVID
  excess Sharpe +0.06 (FinBERT beat SPY risk-adjusted post-COVID). But the
  post-COVID window is only 67 trades — that positive excess is within noise
  and must NOT be reported as a real edge.

**Interpretation.** FinBERT has no full-window risk-adjusted edge over
buy-and-hold, but it is the strongest of the three signals relative to its
benchmark and produces the headline finding of the comparison: a
finance-domain model materially outperforms a generic sentiment lexicon. The
honest framing of the post-COVID number is "a positive excess Sharpe the
sample is too small to distinguish from zero" — not "FinBERT beats the market
post-COVID."

### Paper trading

_Not yet run._

---

## Three-way summary

| Strategy | Sharpe | SPY benchmark | Excess | Window |
|----------|--------|---------------|--------|--------|
| Quant    | 0.76   | 0.84          | −0.08  | 2010–2024 |
| FinBERT  | 0.71   | 0.79          | −0.08  | 2010–2023 |
| VADER    | 0.59   | 0.79          | −0.20  | 2010–2023 |

No strategy beats buy-and-hold on a risk-adjusted basis after 5 bps
slippage. That is the honest result and the deliverable: three signal
sources measured rigorously, with a clear finding that a finance-domain
model (FinBERT) outperforms a generic lexicon (VADER), while neither — nor
the price-based quant signal — adds alpha over SPY on large-cap US equities.
Quant's figure is on the longer window; a strict comparison restricts it to
2010–2023.
