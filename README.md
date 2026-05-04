# Meridian

A retail-style automated trading platform built as a learning project: full-stack FastAPI + Next.js, with an experimental sentiment + quant signal pipeline that places small-dollar trades through `robin_stocks`.

## Honest framing

Read this before anything else.

- **This is a hobby/learning project, not a production trading system.** It is not "institutional-grade." It does not approach the latency, rigor, or operational standards of a real quantitative trading firm.
- **It depends on `robin_stocks`**, an unofficial reverse-engineered Robinhood API. No professional firm would build on this. Sessions can break without warning when Robinhood changes things on their side.
- **There are no backtests, no statistical validation, no P&L attribution analysis** committed to this repo. The signals here are heuristics, not validated edges. Treat any P&L as noise unless and until rigorous backtesting is added.
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
