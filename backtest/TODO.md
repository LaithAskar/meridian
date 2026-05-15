# Meridian Backtester — TODO

Routine reads this top-to-bottom. Take the **top item that is neither `[done]` nor `[blocked]`** — i.e., the first `[ ]` or `[~]`. You MAY skip over `[blocked]` items to keep working, but you may NOT skip over `[ ]` or `[~]` items. Execute the chosen item, mark it `[done]` (or `[~]` if not finished, `[blocked: <reason>]` if it requires Laith input), write the recap, commit, stop. Do not bundle multiple items per run unless one truly blocks the other and the combined work fits in one session.

Status marks: `[ ]` not started · `[~]` in progress (carry to next run) · `[done]` completed · `[blocked: <reason>]` needs Laith input

---

## Phase 0 — Bootstrap (do these first, in order)

**PIVOT 2026-05-15 (later in the day, finalized after a 2nd iteration):** Laith switched data source from Alpaca hourly 2016-2024 to **yfinance daily 2010-2024** with a **Jan 2010 OEX universe**. Reasons: (a) cloud routine has no Alpaca creds and can't accept env-var secrets, (b) yfinance is keyless and the routine can fetch it directly with no manual download step, (c) 14-year window with a Jan-2010 universe is the cleanest survivorship-bias-free play that avoids the 2008-09 carnage (LEH, BSC, WaMu, Wachovia all gone by Jan 2010). Earlier in the day we considered a 2005 start; rejected because the universe complexity (yfinance gaps on bankrupt 2008-era names) outweighed the marginal Sharpe-SE benefit of 5 extra years. Items 0.1, 0.2, 0.2.5, 0.3 below are obsolete — see 0.1-v2, 0.2-v2. DESIGN.md is the source of truth.

- [obsolete] **0.1 — (Alpaca hourly fetcher)** — replaced by 0.1-v2 yfinance daily fetcher
- [obsolete] **0.2 — (UNIVERSE_2016)** — replaced by 0.2-v2 UNIVERSE_2005
- [obsolete] **0.2.5 — (verify 2016 universe vs Wikipedia)** — verification rolled into 0.2-v2 acceptance criteria
- [obsolete] **0.3 — (verify pre-committed Alpaca bundle)** — no longer needed; yfinance fetched directly by routine, no manual download required

- [done] **0.1-v2 — yfinance daily bar fetcher with parquet cache.**
  - File: `backtest/data.py` (overwrite the existing Alpaca-specific module)
  - Function: `fetch_bars(symbols: list[str], start: date, end: date, interval: str = '1d') -> pd.DataFrame`
  - Returns a MultiIndex (symbol, date) DataFrame with columns `open, high, low, close, volume`. Use `yf.download(...)` with `auto_adjust=True` (total-return semantics — DESIGN.md requires this).
  - Cache layer: parquet at `data/cache/{symbol}_{interval}.parquet`. Cache check: if file exists and date index covers [start, end], read locally; otherwise re-fetch full range and overwrite.
  - Rate-limit: yfinance is unofficially rate-limited. Use the `threads=False` arg on `yf.download` and pace at ~5 symbols/sec. Retry once on Yahoo's "rate limited" string in the warning output.
  - Remove the old `alpaca-py` dependency from `requirements.txt`, add `yfinance>=0.2.40`.
  - Delete the old Alpaca-specific helpers (`_make_client`, `_get_timeframe`, `_fetch_from_api`) and their associated tests.
  - Tests (overwrite `backtest/tests/test_data.py`): use a `monkeypatch` on `yf.download` to return a synthetic DataFrame so tests don't hit the network. Cover: MultiIndex shape, expected columns, cache hit count = 0 on second call, cache file created, date filter applied, empty symbols list returns empty DataFrame, no NaN in OHLC.
  - Acceptance: `fetch_bars(['AAPL', 'MSFT'], date(2024, 1, 1), date(2024, 1, 31))` returns a non-empty MultiIndex DataFrame with the expected columns. All tests green.
  - (`backtest/scripts/bulk_download.py` was already deleted manually as part of this pivot — no action needed on it.)

- [ ] **0.2-v2 — UNIVERSE_2010: Jan 2010 S&P 100 (OEX) constituents, held constant, including any names that later delisted.**
  - File: `backtest/universe.py` (overwrite the existing `UNIVERSE_2016` module)
  - Export: `UNIVERSE_2010: list[str]` — 100 tickers.
  - Source: use `WebFetch` to read the Wikipedia article "S&P 100" (https://en.wikipedia.org/wiki/S%26P_100) → "Component changes" / historical members section. Reconstruct the Jan 2010 constituent list. If the article doesn't give a clean snapshot, cross-check with the Wayback Machine for archived OEX holdings from early 2010 (e.g., the iShares OEF ETF holdings page archived from Jan-Feb 2010).
  - The 2010 universe is much cleaner than 2005 — the worst 2008-09 bankruptcies (LEH, BSC, WaMu, Wachovia) are already excluded by the Jan 2010 start. But some names did delist or get acquired during 2010-2024. Check explicitly:
    - Renamed tickers (FB→META in Oct 2022, PCLN→BKNG in May 2018 — if they were 2010 OEX members, use the modern ticker)
    - Sprint (S) — merged into T-Mobile Apr 2020
    - Time Warner (TWX) — acquired by AT&T Jun 2018
    - DuPont/Dow (DD, DOW) — DowDuPont merger 2017 then 3-way split 2019; messy ticker history
    - DD (DuPont de Nemours, post-2019) vs DD (old DuPont, pre-2017) — confirm yfinance ticker continuity
    - Allergan (AGN) — acquired by AbbVie 2020
    - Monsanto (MON) — acquired by Bayer 2018 (no longer trades in US)
    - Any other 2010-OEX names that subsequently delisted entirely
  - For tickers that have NO yfinance data over their 2010-event-date window: add `KNOWN_NO_DATA: set[str]` constant. Phase 1.3 engine treats these as "no position." Expect this set to be SMALL (likely 0-3 tickers) given the post-2010 era.
  - For renamed entities with surviving tickers: use the modern ticker if economic continuity exists. Document the rename + date in the module docstring.
  - Tests (overwrite `backtest/tests/test_universe.py`): assert `len(UNIVERSE_2010) == 100`, all uppercase, no duplicates. Additionally: for 10 randomly-sampled tickers, attempt a yfinance fetch covering 2010-01-01 → 2010-12-31 (mock the call if running offline) and verify the result is non-empty OR the ticker is in `KNOWN_NO_DATA`.
  - Acceptance: every ticker in `UNIVERSE_2010` is either fetchable starting Jan 2010 or explicitly listed in `KNOWN_NO_DATA` with rationale. Docstring documents the methodology, primary source URL, and date of verification.

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
  - Functions: `sharpe(returns, freq='daily')`, `max_drawdown(equity_curve)`, `hit_rate(trades)`, `avg_win_loss(trades)`, `exposure(positions_over_time)`, `cagr(equity_curve, years)`.
  - Frequency annualization: **daily → multiply by sqrt(252) for Sharpe** (per DESIGN.md after the yfinance pivot — NOT the sqrt(252*6.5) hourly factor from the earlier draft).
  - Also implement `sharpe_se(returns)` — standard error of the Sharpe estimate, ≈ sqrt((1 + sharpe^2/2) / n) where n = number of return observations. Report alongside the point estimate so the regime-split comparison can show whether the difference is statistically meaningful.
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
