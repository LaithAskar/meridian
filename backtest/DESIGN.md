# Meridian Backtester — v1 Design

**Locked 2026-05-14.** This document is the source of truth for what gets built. Do not deviate without updating this doc first.

## Purpose

Measure the *edge* of Meridian's three signal sources — FinBERT, VADER, and quant (momentum + mean-reversion + regime) — under realistic execution assumptions. Output: defensible Sharpe / max drawdown / hit rate per signal source over 9 years of intraday data, split at COVID.

This is a **resume artifact**. Numbers must be honest, methodology must be interview-defensible. No close-price fills, no current-SPX-membership survivorship bias, no annualized 30-day Sharpe theatre.

## Architecture

```
backtest/
  DESIGN.md            # this file — read first
  TODO.md              # ordered task list — routine pulls from here
  engine.py            # event loop, portfolio accounting, fill simulation
  fills.py             # next-bar-open + 5 bps slippage model
  strategy.py          # Strategy ABC, signal injection
  data.py              # Alpaca historical bar loader + local parquet cache
  metrics.py           # Sharpe, max DD, hit rate, exposure, etc.
  signals/
    finbert.py         # wraps backend/trading/sentiment_engine.py (FinBERT path)
    vader.py           # wraps backend/trading/sentiment_engine.py (VADER path)
    quant.py           # wraps backend/trading/quant/{momentum, mean_reversion, regime_detector}
  universe.py          # top-100 by 2016-01 mcap, held constant
  results/
    finbert/           # per-run outputs
    vader/
    quant/
  notebooks/
    results.ipynb      # static results page — comparison plots + tables
data/
  cache/               # parquet cache of pulled Alpaca bars
```

## Locked spec

| Decision | Value | Rationale |
|---|---|---|
| Strategy interface | `Strategy.on_bar(ts, bars, portfolio) -> list[Order]` with signal source injected | Same class wraps all three signal types — only signal generator differs |
| Fill model | Next-bar-open + 5 bps slippage each side | Standard quant convention. Models execution latency. Close-price fills are amateurish |
| Granularity | Hourly bars | Sentiment signals fire on news events — daily bars would not capture the actual decision moment |
| Data source | Alpaca historical bars API (free tier, IEX feed) | Free, official market data. Laith already has account. Caveat: IEX has lower volume than SIP |
| Date range | 2016-01-01 → 2024-12-31 | Alpaca free tier history limit. 9 years total. Sharpe SE ≈ 0.35 over full window — interview-defensible |
| Regime split | Pre-COVID: 2016-01-01 → 2020-02-29. Post-COVID: 2020-03-01 → 2024-12-31 | Standard regime check. Reports both halves separately |
| Universe | Top-100 most liquid US equities by Jan 2016 market cap, held constant | Survivorship-bias-free second-best. Defensible if asked |
| Costs | 5 bps slippage per side. $0 commission (Robinhood/Alpaca convention) | Models adverse selection. Commissions actually zero |
| Position sizing | Equal-weight, max N positions concurrent (N = TBD by signal source, typically 5-15) | Matches live bot's flat-5%-per-trade behavior at $700 capital — but normalized for backtest |
| Risk halts in backtest? | No — backtester measures raw signal edge | Risk halts are a layer ON TOP of edge. Measure edge first, layer halts after |
| Benchmark | SPY buy-and-hold, same window | Standard. Report both absolute Sharpe and excess-over-SPY |

## Metrics reported (per signal source × per regime)

- Annualized Sharpe ratio (with std error)
- Max drawdown
- Hit rate (% of trades profitable)
- Average win / average loss / win-loss ratio
- Average holding period
- Total trade count
- Exposure % (time in market)
- Total return + CAGR
- Equity curve (plotted)

## What this backtester is NOT

- **Not a live trading system.** No execution to brokers. No real money.
- **Not a Tachyon integration.** Stub fill engine deliberately — see locked SWE portfolio plan.
- **Not a React dashboard.** Results land in a Jupyter notebook + static HTML export. Do not build a web UI.
- **Not a multi-strategy framework.** One strategy class, three signal injections. No abstraction over strategies beyond what's needed for these three.
- **Not a position-sizer test.** Equal weight, fixed N. Vol-targeting is deferred to fall per locked plan.

## Honest disclosures (for README + interview)

1. Hourly bars from IEX, not SIP — wider spreads + more gaps than full-market data
2. 5 bps slippage assumption is a stylized number; actual slippage varies by ticker liquidity
3. Top-100 universe is biased toward 2016-era winners (you'd need point-in-time membership for SPX-level rigor)
4. No commission model because Robinhood/Alpaca are commission-free for equities

## Routine ownership

This backtester is built by a scheduled Claude routine running twice daily. Each run reads `TODO.md`, picks the top unfinished task, executes it, writes code + tests, and produces a recap file at `journal/YYYY-MM-DD-{am|pm}.md` in the format: **task → code → explanation → output**.

Routine MUST NOT:
- Deviate from this design doc without first updating it AND noting the change in a recap
- Build a web UI of any kind
- Add scope (factor models, options pricing, etc. — see locked SWE portfolio plan)
- Bypass the TODO order (next task is the next task)
- Commit broken code — tests must pass before commit

Routine MUST:
- Write tests for every new module
- Update TODO.md to mark completed items
- Write a recap file per run
- Use `[routine]` prefix on all commits for git-log filtering
- Stop and flag for human decision if a task requires a judgment call not specified in this doc
