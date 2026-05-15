# Meridian

A retail-style automated trading platform built as a learning project: full-stack FastAPI + Next.js, with an experimental sentiment + quant signal pipeline that places small-dollar trades through `robin_stocks`.

## Honest framing

Read this before anything else.

- **This is a hobby/learning project, not a production trading system.** It is not "institutional-grade." It does not approach the latency, rigor, or operational standards of a real quantitative trading firm.
- **It depends on `robin_stocks`**, an unofficial reverse-engineered Robinhood API. No professional firm would build on this. Sessions can break without warning when Robinhood changes things on their side.
- **The live signals are heuristics, not validated edges.** A systematic backtester (`backtest/`) is under construction to measure the edge of each signal source over 2010-2024. Results are not yet merged — see the Backtester section below for current status and methodology.
- **The sentiment engine scrapes free public sources** (Finviz, Yahoo Finance, Reddit, StockTwits). These are noisy data sources with significant sample selection bias. Using them for live trading is an experiment, not a strategy.
- **The ML "ensemble" (Prophet + XGBoost + optional LSTM)** is a kitchen-sink approach. Real applied ML in finance is far more focused — typically one well-understood model per market regime, with careful attention to overfitting, alpha decay, and capacity.
- **Trading is risky and most retail automated systems lose money over time.** This system is run with explicit small-dollar bounds for learning, not for return.

## What this project actually demonstrates

- End-to-end full-stack engineering: FastAPI backend, Next.js frontend, separate crypto bot worker, all wired together.
- Integration with a messy real-world API (`robin_stocks`) including session caching, MFA flow, and graceful paper-mode fallback.
- Operational hygiene I'm building muscle on: PDT-rule tracker, daily-loss circuit breaker, liquidity reserve, paper-mode safety toggle that actually skips live API calls.
- Modern Python and TypeScript tooling (Python 3.10+, FastAPI, pydantic, yfinance, `ta`; Next.js 16, TanStack Query, shadcn-style UI primitives).

## Lessons learned (kept honest)

- A `.env` file is not a secrets manager. Plaintext credentials in `~/Downloads` are a footgun.
- Module-level state machines are easy to duplicate accidentally. The first iteration of this codebase had two parallel "logged in to Robinhood" flags pointing at the same underlying session — the dashboard could read "not connected" while the bot was actively trading.
- A "paper mode" flag that doesn't gate the live API call is worse than no paper mode at all — it teaches false confidence. Defensive defaults must actually defend.
- Silent fallback to a safer mode on failure (e.g., login fails → quietly switch to paper) is the worst possible behavior when the operator intends real money. Failures must be loud and abort startup.
- The gap between "the bot's pipeline runs end-to-end" and "the bot has a real edge" is enormous. The first is software engineering; the second is statistics and domain knowledge. This project is good at the first and makes no claims about the second.

## Architecture

```
Frontend (Next.js :3000)  →  Backend (FastAPI :8000)  →  Robinhood (robin_stocks, unofficial API)
                                    ↓
                          ┌─────────┴─────────┐
                    Sentiment Engine       Quant Engine
                    (Finviz + Yahoo +     (Momentum + Reversion
                     Reddit + StockTwits   + Factor model voting)
                     → VADER → consensus)
                          ↓                    ↓
                       Trade Executor (PDT-aware, dynamic sizing,
                                       circuit breaker, paper-mode skip)
                                    ↓
                             Crypto Bot (separate process, 24/7)
```

## Backtester

The `backtest/` directory is a systematic, interview-defensible backtester that measures the *edge* of Meridian's three signal sources — a quant pipeline (momentum + mean-reversion + regime detection), VADER sentiment, and FinBERT sentiment — over 14 years of daily US equity data.

### Goal

Produce honest Sharpe / max drawdown / hit rate numbers per signal source over 2010-2024, split at the COVID regime break. "Honest" means no survivorship bias in the universe, no close-price fills, no cherry-picked windows, and no annualized-30-day-Sharpe theatre.

### Universe

**100 tickers: S&P 100 (OEX) constituents as of January 2010, held constant.**

- Source: OEX index composition circa Jan 2010 (reconstructed from CBOE + Wikipedia historical data).
- Why Jan 2010? The worst 2008-09 bankruptcies — Lehman, Bear Stearns, WaMu, Wachovia — are already off the index. The 2010-2024 window is clean without having to model distressed-debt recovery paths.
- Survivorship-bias-free: companies that were acquired, merged, or delisted *during* 2010-2024 remain in the universe. Their price bars simply end at the event date. The engine treats missing bars as "no position" from that point forward.
- Notable events handled: Facebook (META, May 2012 IPO — not in 2010 OEX); Sprint (S, merged into T-Mobile Apr 2020); Time Warner (TWX, acquired by AT&T Jun 2018); Monsanto (MON, acquired by Bayer Jun 2018); DowDuPont merger and three-way split (DD/DOW, 2017-2019); and others. Full ticker map in `backtest/universe.py`.

### Data

- **Source:** yfinance daily bars, `auto_adjust=True` (total-return semantics: adjusted for dividends and splits).
- **Cache:** parquet files at `data/cache/{symbol}_1d.parquet`. Fetched once per symbol, read locally on subsequent runs.
- **Date range:** 2010-01-01 → 2024-12-31 (14 years, ≈3 528 trading days).
- **Benchmark:** SPY buy-and-hold over the same window.

### Fill model

**Next-bar-open + 5 bps slippage each side.** The strategy generates orders at bar close; fills execute at the following day's open price, multiplied by `1.005` for buys and `0.9995` for sells. This models execution latency and adverse selection. Close-price fills are amateurish — they imply you trade at the price that triggered the signal, which is impossible.

Missing next bars (delisted stocks) cancel the order rather than filling at a stale price.

### Signal sources

| Signal | Module | Method |
|---|---|---|
| **Quant** | `backtest/signals/quant.py` | Momentum (12-month cross-sectional + EMA-MACD time-series) + mean-reversion (RSI-14 + Bollinger Band z-score) combined with regime-adjusted weights. Regime is detected from SPY SMA-50/SMA-200 and VIX level. |
| **VADER** | `backtest/signals/vader.py` | Blocked — requires historical news headlines aligned to daily timestamps for 100 tickers over 14 years. No free source exists. See [blocker details](#blockers). |
| **FinBERT** | `backtest/signals/finbert.py` | Blocked — same dependency as VADER. See [blocker details](#blockers). |

### Regime splits

| Window | Dates | Rationale |
|---|---|---|
| Pre-COVID | 2010-01-01 → 2020-02-29 | ~10 years, includes 2011 flash crash, 2015-16 China selloff, 2018 Q4 correction |
| Post-COVID | 2020-03-01 → 2024-12-31 | ~5 years, includes COVID crash + V-shaped recovery, 2022 rate-hike bear market |

### Metrics reported (per signal source × per regime window)

- Annualized Sharpe ratio: `mean(daily_returns) / std(daily_returns) × √252`
- Sharpe standard error: `√((1 + Sharpe² / 2) / n)` — so the regime-split comparison can show whether differences are statistically meaningful
- Max drawdown (peak-to-trough fraction)
- Hit rate (% of closed trades profitable)
- Average win / average loss / win-loss ratio
- Average holding period (trading days)
- Total trade count
- Exposure % (fraction of days with at least one open position)
- Total return and CAGR
- Equity curve (plotted, rebased to 100)

### Current status

| Task | Status |
|---|---|
| yfinance daily bar fetcher with parquet cache | Done |
| Jan 2010 OEX universe (100 tickers) | Done |
| Strategy ABC, Order/Fill/Portfolio dataclasses | Done |
| Next-bar-open + 5 bps fill model | Done |
| Event-loop engine with portfolio accounting | Done |
| Metrics module (Sharpe, max DD, hit rate, etc.) | Done |
| Quant signal wrapper | Done |
| VADER signal wrapper | Blocked — no historical news data source |
| FinBERT signal wrapper | Blocked — same |
| Run quant backtest end-to-end | Blocked — cloud environment network policy blocks outbound yfinance requests (HTTP 403 from Yahoo Finance). To unblock: either whitelist `finance.yahoo.com` in the environment's network policy, or pre-download and commit parquet files to `data/cache/` from a local machine. |
| Run VADER / FinBERT backtests | Blocked — waiting on news data decision |
| Comparison notebook (`backtest/notebooks/results.ipynb`) | Done — renders gracefully with no data; fills in automatically once results land |

**Results are not yet available** because the yfinance data fetch is blocked by the cloud environment's outbound network policy. The code is complete and all 269 unit tests pass. See `journal/2026-05-15-pm9.md` for the exact error and unblocking options.

### Running it locally

Once the data cache is populated (one-time download):

```bash
# From repo root. Fetches all 100 tickers + SPY + ^VIX into data/cache/ (≈180 MB parquet).
python -c "
from datetime import date
from backtest.data import fetch_bars
from backtest.universe import UNIVERSE_2010
fetch_bars(UNIVERSE_2010 + ['SPY', '^VIX'], date(2010,1,1), date(2024,12,31))
"

# Run the quant backtest (reads from cache, no network needed).
# Outputs → backtest/results/quant/{equity_curve.csv, trades.csv, metrics.json, spy_curve.csv}
python -m backtest.run_quant --positions 10 --cash 1000000

# Open the results notebook
jupyter lab backtest/notebooks/results.ipynb
```

### Running the tests

```bash
python3 -m pytest backtest/tests/ -q   # 269 tests, all green
```

### Honest disclosures

These disclosures are locked in `backtest/DESIGN.md` and are reprinted here verbatim so they appear wherever the project is described.

1. **Daily bars from yfinance** — known data-quality caveats: adjusted-close handling may differ for stocks with complex corporate actions; occasional gaps on illiquid/delisted names; dividend treatment varies. Spot-check accordingly.

2. **5 bps slippage assumption** is a stylized number; actual slippage varies by ticker liquidity. The 2010-2024 era is post-Reg-NMS and post-decimalization — a single slippage assumption is more defensible here than spanning 2005-2007.

3. **Universe is S&P 100 (OEX) constituents as of Jan 2010, held constant.** A handful of names were acquired or delisted during 2010-2024. Post-event returns are recorded honestly (acquisitions at cash price, bankruptcies at -100%, no resurrection). This is the survivorship-bias-free universe.

4. **No commission model** because modern retail brokers (Robinhood, Alpaca, Fidelity) are commission-free. Pre-2019 retail commissions ($5-10 per trade) are not modeled — disclose this when reporting pre-2019 returns. Institutional commissions over 2010-2018 (1-3 bps) are folded into the 5 bps slippage assumption.

5. **yfinance daily data is `auto_adjust=True`**, adjusted for dividends and splits (total-return semantics). The SPY benchmark uses the same adjustment for an apples-to-apples comparison.

### Blockers

**VADER and FinBERT backtests (items 2.2, 2.3):** Historical news headlines aligned to daily timestamps for 100 tickers over 14 years do not exist for free. Options: (a) Polygon news API (paid), (b) GDELT (free but noisy and requires alignment work), (c) limit sentiment backtest to last 2-3 years where free sources exist, (d) report only the quant signal. Awaiting Laith's decision — see `journal/2026-05-15-pm8.md` for the full tradeoff analysis.

**Quant backtest network access (item 3.1):** Cloud execution environment blocks outbound HTTP to Yahoo Finance (HTTP 403). The fastest fix is to pre-download the parquet cache locally and commit it to `data/cache/`. See `journal/2026-05-15-pm9.md`.

---

## Quick Start

### Backend

```bash
cd meridian
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; on Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env             # then edit with your Robinhood credentials
                                  # leave TRADING_PAPER_MODE=true unless you know what you're doing

# Run from the project root (NOT from inside backend/)
# Imports use the absolute path `backend.main:app`.
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:3000
```

### Crypto Bot (optional, separate process)

```bash
cd crypto_bot
python main.py
```

## Configuration knobs (`backend/trading_config.yaml`)

| Knob | Effect | Conservative default |
|---|---|---|
| `paper_mode` | If true, all trade decisions are simulated. **Real money requires this be `false` AND `TRADING_PAPER_MODE` env var not set to `true`/`1`/`yes` (the env var is a one-way ratchet to paper).** | `true` |
| `max_position_pct` | Max position size as fraction of account equity | `0.02` |
| `max_trade_dollars` | Hard ceiling on per-trade dollar amount | `25` |
| `min_trade_dollars` | Floor — trades sized below this are skipped | `5` |
| `max_daily_trades` | Daily trade count cap | `5` |
| `max_daily_loss_pct` | Daily loss halts trading for the day | `0.015` |
| `liquidity_reserve_pct` | Fraction of equity always held back | `0.20` |

The `TRADING_PAPER_MODE` env var only ratchets toward paper mode (true forces paper; false is a no-op). To go live, you must set `paper_mode: false` in the YAML AND not have `TRADING_PAPER_MODE=true` in `.env`.

## API Endpoints

### Stock Data
| Endpoint | Description |
|---|---|
| `GET /api/quote/{ticker}` | Real-time quote (Yahoo Finance) |
| `GET /api/history/{ticker}?period=1y` | OHLCV time series |
| `GET /api/analysis/{ticker}` | Technical + fundamental snapshot |
| `GET /api/news/{ticker}` | News headlines + VADER sentiment |
| `GET /api/earnings/{ticker}` | Earnings history |
| `GET /api/predict/{ticker}?days=30` | ML ensemble forecast (heuristic, not validated) |
| `POST /api/portfolio` | Markowitz mean-variance optimization |
| `GET /api/trending` | Trending tickers from social scrape |

### Trading Bot
| Endpoint | Description |
|---|---|
| `POST /api/trading/start` | Start the trading loop |
| `POST /api/trading/stop` | Stop |
| `GET /api/trading/status` | Status, mode, login state, recent trades |
| `GET /api/trading/signals` | Recent signals + intents |

### Robinhood Account
| Endpoint | Description |
|---|---|
| `POST /api/robinhood/login` | Manual login (push MFA) |
| `GET /api/robinhood/status` | Connection state |
| `GET /api/robinhood/account` | Equity, buying power, cash |
| `GET /api/robinhood/positions` | Open positions |
| `POST /api/robinhood/order` | Place trade |

### Crypto Bot
| Endpoint | Description |
|---|---|
| `POST /api/crypto/start` | Start crypto bot loop |
| `POST /api/crypto/stop` | Stop |
| `GET /api/crypto/status` | Status + trade log |
| `GET /api/crypto/prices` | Live prices |

## Safety nets currently in place

- **PDT tracker** — under-$25K accounts are capped at 3 day trades per rolling 5 business days. The bot tracks day-trade counts and will refuse to sell same-day positions when capped.
- **Daily loss circuit breaker** — once daily P&L crosses `max_daily_loss_pct`, trading halts for the day.
- **Liquidity reserve** — `liquidity_reserve_pct` of equity is held back from being deployed.
- **Paper mode early-return** — when `paper_mode` is true, the trade executor skips the Robinhood login entirely. No accidental live API calls in paper mode.
- **Loud startup failure** — real-money login failures raise `RuntimeError` and abort backend startup. The backend cannot come up "running" while the bot is silently broken.

These are basic and necessary. They are not sufficient to make this a production system.

## Known gaps and post-launch tech debt

- No tests. No backtests. No P&L attribution.
- Two parallel login state machines that synchronize once at startup but could diverge if the underlying robin_stocks session expires mid-session. Should be unified into a single source of truth with on-demand session validation.
- `_rh_login()` doesn't reset its flag on failure.
- Frontend `NEXT_PUBLIC_API_URL` is in the backend `.env` but Next.js reads `frontend/.env.local`. Currently works only because `localhost:8000` is hard-coded as a fallback.
- README's deployment section (systemd) is aspirational — the project has not been deployed under systemd.

## Disclaimer

For educational purposes only. Not financial advice. Trading involves significant risk of loss. Past performance does not guarantee future results. Use at your own risk. The author is not a registered investment advisor.
