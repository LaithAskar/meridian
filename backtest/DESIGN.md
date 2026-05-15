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
  universe.py          # top-100 by 2005-01 mcap (Jan 2005 OEX), held constant
  results/
    finbert/           # per-run outputs
    vader/
    quant/
  notebooks/
    results.ipynb      # static results page — comparison plots + tables
data/
  cache/               # parquet cache of pulled yfinance bars
```

## Locked spec

| Decision | Value | Rationale |
|---|---|---|
| Strategy interface | `Strategy.on_bar(ts, bars, portfolio) -> list[Order]` with signal source injected | Same class wraps all three signal types — only signal generator differs |
| Fill model | Next-bar-open + 5 bps slippage each side | Standard quant convention. Models execution latency. Close-price fills are amateurish |
| Granularity | **Daily bars** | yfinance hourly only spans ~730 days. Daily is the standard quant-backtest granularity. Sentiment becomes a daily-level signal ("EOD net sentiment → next day's open"). |
| Data source | **yfinance** (no API key required) | Free, no credentials required by the cloud routine. Caveats: known issues with adjusted-close vs unadjusted handling, occasional gaps on illiquid/delisted names, dividend treatment varies. Use `auto_adjust=True` for total-return semantics. |
| Date range | **2005-01-01 → 2024-12-31** | 19 years. Sharpe SE ≈ 0.23 over full window. Includes 2008-09 financial crisis and 2020 COVID crash — two regime-defining tail events |
| Regime splits | (a) Pre-financial-crisis: 2005-01-01 → 2007-12-31. Crisis + recovery: 2008-01-01 → 2015-12-31. Modern + COVID: 2016-01-01 → 2024-12-31. (b) Or a simpler pre/post-COVID cut at 2020-03-01. Report both | Two crisis events justify multi-regime reporting. Simpler binary split available for the bullet headline number |
| Universe | **Top-100 most liquid US equities by Jan 2005 market cap (S&P 100 / OEX constituents as of Jan 2005), held constant** including names that subsequently went bankrupt, were acquired, or delisted | Real survivorship-bias-free universe. Includes LEH, BSC, WM, AOL-TWX-era names. Returns on delisted/bankrupt names are taken as -100% (post-event) and the engine carries no position past the event |
| Costs | 5 bps slippage per side. $0 commission | Models adverse selection. Commissions actually zero on modern brokers |
| Position sizing | Equal-weight, max N positions concurrent (N = TBD by signal source, typically 5-15) | Matches live bot's flat-5%-per-trade behavior — but normalized for backtest |
| Risk halts in backtest? | No — backtester measures raw signal edge | Risk halts are a layer ON TOP of edge. Measure edge first, layer halts after |
| Benchmark | SPY buy-and-hold, same window | Standard. Report both absolute Sharpe and excess-over-SPY |
| Sharpe annualization | `mean(daily_returns) / std(daily_returns) * sqrt(252)` | Standard daily-bar Sharpe. NOT the hourly factor used in earlier draft |

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

1. Daily bars from yfinance — known data-quality caveats: adjusted-close handling may differ for stocks with complex corporate actions; occasional gaps on illiquid/delisted names; dividend treatment varies. Spot-check accordingly.
2. 5 bps slippage assumption is a stylized number; actual slippage varies by ticker liquidity and historical era (pre-decimalization 2001, pre-Reg-NMS 2007 had structurally different microstructure — backtest spans both).
3. Universe is S&P 100 (OEX) constituents as of Jan 2005, held constant. Some names (Lehman Brothers, Bear Stearns, Washington Mutual, AOL Time Warner, Anheuser-Busch, others) went bankrupt or were acquired during the window. Their post-event returns are recorded honestly (acquisitions at cash price, bankruptcies at -100%, no resurrection). This is the survivorship-bias-FREE universe.
4. No commission model because modern retail brokers (Robinhood, Alpaca, Fidelity) are commission-free. Pre-2019 commissions ($5-10 per trade) are NOT modeled — disclose this when reporting pre-2019 returns.
5. yfinance daily data is `auto_adjust=True` adjusted for dividends and splits (total-return semantics). Compare-to-SPY uses the same adjustment for apples-to-apples.

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
