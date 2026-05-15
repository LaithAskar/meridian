# Meridian Backtester — TODO

Routine reads this top-to-bottom. Take the **top unfinished item**, execute it, mark it `[done]`, write the recap, commit, stop. Do not skip ahead. Do not bundle multiple items per run unless one truly blocks the other and the combined work fits in one session.

Status marks: `[ ]` not started · `[~]` in progress (carry to next run) · `[done]` completed · `[blocked: <reason>]` needs Laith input

---

## Phase 0 — Bootstrap (do these first, in order)

- [ ] **0.1 — Data infra: Alpaca historical bar fetcher with parquet cache.**
  - File: `backtest/data.py`
  - Function: `fetch_bars(symbols: list[str], start: date, end: date, timeframe='1Hour') -> pd.DataFrame`
  - Cache layer: parquet at `data/cache/{symbol}_{timeframe}.parquet`. If cached file covers requested range, skip API call.
  - Use alpaca-py (already in requirements.txt — verify) with `StockHistoricalDataClient`. IEX feed is free tier default.
  - Tests: pull a known symbol (AAPL), verify shape, verify cache hit on second call. Use a tiny date range for test speed.
  - Acceptance: can call `fetch_bars(['AAPL', 'MSFT'], date(2024, 1, 1), date(2024, 1, 31))` and get a multi-index DataFrame back without errors.

- [ ] **0.2 — Universe definition: top-100 most liquid US equities by Jan 2016 mcap.**
  - File: `backtest/universe.py`
  - Hardcode the list in the file (do not pull at runtime — list is held constant per design doc).
  - Source: research the top-100 S&P constituents by market cap as of 2016-01-01. If exact data unavailable, use a defensible proxy (e.g., S&P 100 OEX constituents as of 2016-01) and document the choice in a docstring.
  - Export: `UNIVERSE_2016: list[str]`
  - Tests: assert len == 100, assert all uppercase tickers, assert no duplicates.

- [ ] **0.3 — Bulk-download all hourly bars for the universe over 2016-01-01 to 2024-12-31.**
  - One-time script: `backtest/scripts/bulk_download.py`
  - Use the fetcher from 0.1. Iterate the universe. Handle rate limits (Alpaca free tier: 200 req/min). Sleep + retry on 429s.
  - Acceptance: `data/cache/` populated with ~100 parquet files. Spot-check 3 random symbols for date coverage and bar count.
  - Estimate: ~75-90 minutes wall clock. Routine should plan accordingly — this likely consumes a full run.

## Phase 1 — Engine

- [ ] **1.1 — Strategy ABC and Order dataclass.**
  - File: `backtest/strategy.py`
  - Define `Order` (symbol, side, qty, order_type='market_next_open'), `Position` (symbol, qty, avg_cost), `Portfolio` (cash, positions, equity).
  - Define `Strategy(ABC)` with abstract `on_bar(self, ts: datetime, bars: dict[str, pd.Series], portfolio: Portfolio) -> list[Order]`.
  - Tests: instantiate a NoopStrategy subclass that always returns []. Verify type contract.

- [ ] **1.2 — Fill model: next-bar-open + 5 bps slippage.**
  - File: `backtest/fills.py`
  - Function: `fill_order(order, next_bar) -> Fill` where Fill has (ts, symbol, side, qty, fill_price). Fill price = next_bar.open * (1 + 5e-4) for buy, * (1 - 5e-4) for sell.
  - Edge cases: handle gap-up/gap-down (just use the open price, don't try to model partial fills). If next_bar is missing (e.g., delisted), order is cancelled.
  - Tests: known order → known fill price, both sides.

- [ ] **1.3 — Engine event loop.**
  - File: `backtest/engine.py`
  - `class Engine`: takes (strategy, universe, start, end, initial_cash, max_positions). Iterates bars in time order. For each ts: calls strategy.on_bar, simulates fills at NEXT bar's open, updates portfolio, records state.
  - State recording: at each ts, snapshot (equity, cash, positions, num_positions). Save as a list of dicts → DataFrame at end.
  - Tests: run NoopStrategy over 1 month of AAPL+MSFT data. Verify equity stays at initial_cash (no trades). Verify no NaN in equity curve.

- [ ] **1.4 — Metrics module.**
  - File: `backtest/metrics.py`
  - Functions: `sharpe(returns, freq='hourly')`, `max_drawdown(equity_curve)`, `hit_rate(trades)`, `avg_win_loss(trades)`, `exposure(positions_over_time)`, `cagr(equity_curve, years)`.
  - Frequency annualization: hourly → multiply by sqrt(252 * 6.5) for Sharpe.
  - Tests: known synthetic series → known metric values. Sharpe of all-zero returns = 0. Max DD of monotonic increase = 0. Etc.

## Phase 2 — Signal wrappers

- [ ] **2.1 — Quant signal wrapper.**
  - File: `backtest/signals/quant.py`
  - Wraps `backend.trading.quant.momentum`, `mean_reversion`, `regime_detector`. Combine via the existing `signal_aggregator.py` if its interface is bar-history-only (no live broker calls).
  - Adapt: live versions may pull from broker/cache; backtest version must take a pandas DataFrame of OHLCV history as input and produce a signal (-1/0/+1 or weighted) per symbol per timestamp.
  - If the live modules are too entangled with live infra to adapt cleanly, copy + adapt the signal *logic* into the wrapper rather than monkey-patching. Document in the file's docstring.
  - Tests: synthetic bar series with clear trend → momentum signal fires correctly.

- [ ] **2.2 — VADER signal wrapper.**
  - File: `backtest/signals/vader.py`
  - Input: news headlines per symbol per timestamp (need a news data source — see 2.4).
  - Output: VADER compound score → discretized to -1/0/+1 with thresholds matching live bot.
  - If no historical news data, this signal is BLOCKED — note as `[blocked: need historical news data source]` and skip to next item.
  - Tests: known headline → known signal.

- [ ] **2.3 — FinBERT signal wrapper.**
  - File: `backtest/signals/finbert.py`
  - Same shape as 2.2 but uses FinBERT classifier from `backend/trading/sentiment_engine.py`.
  - Same blocker risk as 2.2.

- [ ] **2.4 — Historical news data source (BLOCKED CHECKPOINT).**
  - This is the hardest part. Historical news headlines aligned to timestamps for 100 tickers over 9 years is not free.
  - Options: (a) Polygon news API ($$), (b) GDELT (free but messy), (c) skip sentiment backtest and only report quant (degraded scope), (d) use a subset window (last 2 years where news data is cheaper/available).
  - **STOP HERE AND FLAG FOR LAITH.** Write a recap proposing the options with cost/effort tradeoffs. Do not proceed past this without his decision.

## Phase 3 — Run + report

- [ ] **3.1 — Run quant strategy end-to-end over full window.**
- [ ] **3.2 — Run VADER strategy end-to-end (if 2.4 resolved).**
- [ ] **3.3 — Run FinBERT strategy end-to-end (if 2.4 resolved).**
- [ ] **3.4 — Build comparison notebook with equity curves, metrics tables, regime-split breakdowns.**
- [ ] **3.5 — README with results + honest disclosures from DESIGN.md.**

## Phase 4 — Polish (only if Phase 3 done by July 1)

- [ ] **4.1 — Add benchmark vs SPY buy-and-hold.**
- [ ] **4.2 — Robustness checks: parameter sensitivity, walk-forward window, monte-carlo on trade ordering.**
- [ ] **4.3 — Export static HTML of the notebook for portfolio site.**

---

## Recap file format

Each routine run writes one of:
- `journal/YYYY-MM-DD-am.md` (morning run)
- `journal/YYYY-MM-DD-pm.md` (evening run)

Recap structure:
```
# Routine recap — {date} {am|pm}

## Task
{TODO item slug + line}

## Code
{file paths + diffs or new files written, with code blocks}

## Explanation
{what the algorithm does, why this approach, what tradeoffs were noted, what alternatives were rejected}

## Output
{test results, sample run outputs, metric values if relevant}

## Status
{[done] / [in progress, continuing next run] / [blocked on Laith decision: X]}

## Next routine run will
{next TODO item, OR "wait for Laith decision on Y"}
```

Laith reads recaps to understand what was built. Recap is the contract.
