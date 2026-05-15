# Live bot metrics analysis — 2026-05-15

**Purpose:** ROADMAP Phase 0 deliverable — compute Sharpe and max DD on the May 4-5 live trading run.

**Owner:** Laith (with Claude doing the log parsing)

**Outcome: Sharpe and max DD are LITERALLY UNCOMPUTABLE from the available data. This is the finding.**

---

## What was attempted

Parsed `logs/diag_2026-05-04.log`, `logs/launch_2026-05-04.log`, `logs/launch_2026-05-05.log` looking for:
- Per-trade entry prices and fill confirmations
- Per-trade exit prices
- Position-level realized P&L
- An equity time series

## What's actually in the logs

| Event type | Count | What it gives us |
|---|---|---|
| BUY submitted | 13 | Notional ($), timestamp, signal source |
| BUY rejected (Robinhood fractional min) | 2 | Symbol + reason |
| BUY error (NoneType float bug) | 2 | Symbol + stack trace |
| **SELL events** | **0** | Nothing — PDT rules blocked sells |
| Equity snapshots | 2 (start of each session only) | $199.88 (5/4), $200.22 (5/5) — that's it |

## What we know

- **Total notional deployed:** $50.58 across 13 successful fills
- **Per-trade size range:** $1.00 to $6.69 (5% of equity, often clipped to fractional minimums)
- **Signal source distribution:** 14 sentiment-finviz, 1 sentiment-yfinance, 2 quant
- **Symbols touched:** MSFT, META, TSLA, AMD, PLTR, RIVN, AMZN, SOFI, GME, AAPL, others
- **Starting equity (5/4):** $199.88. Loss-halt threshold: $19.99 (10%).
- **Trading window:** ~25 hours wall clock across 2 days, but the bot was paused/restarted multiple times.

## Why Sharpe is uncomputable

Sharpe requires a *series of returns* — typically daily or per-trade. We need either:

1. **Daily equity snapshots** to compute daily returns. **We have 2 snapshots ($199.88 start of day 1, $200.22 start of day 2).** Two data points = one return = no standard deviation = Sharpe undefined.

2. **Per-trade realized P&L** (close-out price minus entry price). **Zero round-trip trades exist** — PDT rules blocked every sell. All 13 positions are still held in Robinhood as of this writing, with mark-to-market value unknown from the logs.

Even if we MTM the positions today from real-time prices, we'd get one return number (10 days later), not a series.

## Why max DD is uncomputable

Max drawdown requires an equity curve over time. We have **two equity readings, 19 hours apart**. A curve through two points has no drawdown.

## The honest summary that goes on the resume

**Wrong:** "Live bot achieved Sharpe of X" — would be a lie (data shape doesn't support the claim).

**Right:** "Live deployed for 2 days on $200 capital, surfaced 9 latent bugs under real money pressure, paused to build a 14-year historical backtester for defensible signal-edge measurement."

The 2-day live run is a **debugging accomplishment**, not a performance accomplishment. Frame it that way.

## Implication for ROADMAP

This confirms why the entire backtester project exists. Live data on this bot will never produce resume-grade Sharpe because:

1. PDT rules limit retail bot to ~5 round-trips per 5-day window — even a year of running gives ~50 trades, not enough for tight Sharpe SE.
2. Equity tracking isn't persistent (was supposed to be Phase 4 of prior plan: "sqlite trade log"). Without persistent equity snapshots, even 50 round-trips wouldn't yield a return series.
3. Live noise dominates signal at $200 scale (per-trade size $1-7 vs spread crossing $0.01-0.10).

**The backtester is the only path to a defensible Sharpe number for this resume.** Council validated this on May 5-7. This analysis confirms it concretely.

## Bugs discovered while parsing (worth noting for the bot fix backlog)

1. `BUY SQ $4.26 - error [float() argument must be a string or a real number, not 'NoneType']` — same error twice on different days. Trade executor isn't handling None-priced quotes for some tickers. Low priority — won't impact backtester, but the live bot in `backend/trading/trade_executor.py` should guard against this.
2. `BUY AMC $1.00 - rejected ['Fractional orders must be at least $1...']` — bot is asking for sub-$1 notional somehow despite passing the $1 check upstream. Edge case in position sizing math.

These are **NOT** in scope for ROADMAP Phase 0. Filed for later when (if) live trading resumes.

## ROADMAP Phase 0 status update

`[you]` Compute Sharpe + max DD on live trade logs → **DONE** (with finding: uncomputable from this data, documented above). Mark `✅` on the Friday review.
