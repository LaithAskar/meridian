# Meridian Backtester — TODO

Routine reads this top-to-bottom. Take the **top item that is neither `[done]` nor `[blocked]`** — i.e., the first `[ ]` or `[~]`. You MAY skip over `[blocked]` items to keep working, but you may NOT skip over `[ ]` or `[~]` items. Execute the chosen item, mark it `[done]` (or `[~]` if not finished, `[blocked: <reason>]` if it requires Laith input), write the recap, commit, stop. Do not bundle multiple items per run unless one truly blocks the other and the combined work fits in one session.

Status marks: `[ ]` not started · `[~]` in progress (carry to next run) · `[done]` completed · `[blocked: <reason>]` needs Laith input · `[audit-required]` Laith must hostile-review before routine may touch dependent items

---

## AUDIT GATE — added 2026-05-16 (council-driven)

**Read `backtest/REVIEW_CHECKLIST.md` before continuing past this section.**

The routine has shipped Phase 0/1/4 autonomously. Before any further routine work touches signals (Phase 2) or integration runs (Phase 3), Laith must hostile-review every shipped module against the checklist. Bug classes specifically in scope: lookahead leakage, survivorship-bias gaps in universe handling, fill-on-same-bar leakage, annualization confusion, NaN propagation in metrics, point-in-time data integrity. The annualization mistake that surfaced in spec revisions (sqrt(252) vs sqrt(252*6.5)) is the canonical example of why this gate exists.

**Hand-built territory (routine MUST NOT modify without explicit Laith authorization in this file):**
- `backtest/signals/*.py` — signal evaluation logic (Phase 2.x)
- `backtest/run_quant.py` and any future `run_*.py` integration scripts (Phase 3.x)
- Any regime-split or point-in-time-join logic added beyond what Phase 1 shipped
- `backtest/metrics.py` annualization constants — frozen after audit; do not edit

Routine MAY still touch (scaffolding territory):
- `backtest/data.py` data loaders and parquet cache plumbing
- `backtest/notebooks/*.ipynb` reporting and visualization glue
- `backtest/scripts/*.py` one-off download/utility scripts
- `backtest/tests/test_*.py` — but only to ADD tests, never to weaken or delete existing ones

If the routine hits a Phase 2 or Phase 3 task while the audit gate is unresolved, it must mark it `[audit-required]` and skip to the next eligible item or stop.

### Audit checklist progress

**Recommended order (locked 2026-05-17 after council):** A.3 → A.1 → A.2 → A.5 → A.4 → A.6.
Principle: audit from most-fundamental-flaw-class first (a biased universe invalidates the experiment regardless of math correctness; wrong annualization is recomputable). Then engine/fill mechanics, then data integrity, then metrics math, then test depth.

**Each audit item now bundles THREE deliverables** (locked 2026-05-17 after council):
1. **Cite-or-FAIL per check** — for each numbered check in the REVIEW_CHECKLIST.md section, either cite `file:line` that satisfies it OR write `FAIL: <description>` and reopen the relevant TODO item.
2. **Interview gloss per check** — 2-3 sentences "what I'd say in an interview" explaining the choice and the alternative. If unable to write this without consulting the file, the check is not done.
3. **Adversarial test for the bug class** — write the hostile test that the routine-written tests don't have (e.g., for A.1: a malicious `Strategy` subclass that tries to look ahead, with the engine expected to prevent or expose it). Commit as part of the audit.

**Cascade budget**: expect 2-3 FAIL→fix→re-audit cycles across the six items total. Plan for this; don't be surprised by it.

**No routine-drafted findings** — even draft. The cognitive load of reading code against checklist is the interview-defense generator. Routine output recreates the failure mode this gate exists to fix.

- [audit-required] **A.3 — Audit `backtest/universe.py`** (DO FIRST) for survivorship-bias gaps. Confirm `KNOWN_NO_DATA` rationale is documented per ticker. Confirm delisted names have post-event returns recorded honestly (acquisition price or -100%), NOT dropped. Run REVIEW_CHECKLIST.md §3. Adversarial test: assert that a name known to have delisted mid-window (pick one from the documented set) produces a recorded position trace through its delisting date — not silently absent.
- [audit-required] **A.1 — Audit `backtest/engine.py`** for lookahead leakage. Confirm `on_bar(ts, bars, portfolio)` cannot access bars beyond `ts`. Confirm fills happen at `ts+1` open, not `ts` close. Run REVIEW_CHECKLIST.md §1 line-by-line. Adversarial test: a `LookaheadStrategy` subclass that tries to read `bars[ts + timedelta(days=1)]` — engine must either raise or return identical results to a non-lookahead control (the latter would prove the lookahead attempt had no effect).
- [audit-required] **A.2 — Audit `backtest/fills.py`** for fill semantics. Confirm slippage direction is correct on both sides. Confirm missing-next-bar cancels rather than silently filling. Run REVIEW_CHECKLIST.md §2. Adversarial test: a sequence where the next bar is `None` (delisting simulation) — assert the order is cancelled, not silently filled at `None` or at the current bar's close.
- [audit-required] **A.5 — Audit `backtest/data.py`** for point-in-time integrity. Confirm `auto_adjust=True` semantics are NOT being re-applied somewhere downstream (double-adjustment is a silent disaster). Confirm cache reads cannot serve dates outside fetched range. Run REVIEW_CHECKLIST.md §5. Adversarial test: cache `[2020, 2022]`, then request `[2010, 2024]` — assert the engine receives the full widened range, not the cached subset.
- [audit-required] **A.4 — Audit `backtest/metrics.py`** annualization. Confirm `sqrt(252)` not `sqrt(252*6.5)` for daily bars. Confirm `sharpe_se` formula matches Lo's standard error. Confirm `max_drawdown` uses running maximum, not full-series maximum (the latter is a lookahead bug). Run REVIEW_CHECKLIST.md §4. Adversarial test: a hand-computed Sharpe for a known 5-element return series, pinned to 6 decimal places — and a `max_drawdown` test on a curve whose full-series-max is in the middle (so full-max would give a wrong number that running-max would not).
- [audit-required] **A.6 — Audit existing tests** for shallowness. For each test file: does any test assert WRONG numbers would fail? (i.e., are tests just `assert result is not None`, or do they pin known values?) Run REVIEW_CHECKLIST.md §6. Adversarial work here is meta: count shape-only assertions, list which checks have zero pinned-value coverage, and stub the test names that need writing as `[ ]` items in this TODO file.

Each audit item: Laith reads the code, runs the checklist section, writes findings to `journal/audit-{module}.md` (with the three deliverables above), commits the adversarial test. If a bug is found, mark the relevant Phase task `[~]` so the routine reopens it. If clean, mark `[done]` here.

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

- [done] **0.2-v2 — UNIVERSE_2010: Jan 2010 S&P 100 (OEX) constituents, held constant, including any names that later delisted.**
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

- [done] **1.1 — Strategy ABC and Order dataclass.**
  - File: `backtest/strategy.py`
  - Define `Order` (symbol, side, qty, order_type='market_next_open'), `Position` (symbol, qty, avg_cost), `Portfolio` (cash, positions, equity).
  - Define `Strategy(ABC)` with abstract `on_bar(self, ts: datetime, bars: dict[str, pd.Series], portfolio: Portfolio) -> list[Order]`.
  - Tests: instantiate a NoopStrategy subclass that always returns []. Verify type contract.

- [done] **1.2 — Fill model: next-bar-open + 5 bps slippage.**
  - File: `backtest/fills.py`
  - Function: `fill_order(order, next_bar) -> Fill` where Fill has (ts, symbol, side, qty, fill_price). Fill price = next_bar.open * (1 + 5e-4) for buy, * (1 - 5e-4) for sell.
  - Edge cases: handle gap-up/gap-down (just use the open price, don't try to model partial fills). If next_bar is missing (e.g., delisted), order is cancelled.
  - Tests: known order → known fill price, both sides.

- [done] **1.3 — Engine event loop.**
  - File: `backtest/engine.py`
  - `class Engine`: takes (strategy, universe, start, end, initial_cash, max_positions). Iterates bars in time order. For each ts: calls strategy.on_bar, simulates fills at NEXT bar's open, updates portfolio, records state.
  - State recording: at each ts, snapshot (equity, cash, positions, num_positions). Save as a list of dicts → DataFrame at end.
  - Tests: run NoopStrategy over 1 month of AAPL+MSFT data. Verify equity stays at initial_cash (no trades). Verify no NaN in equity curve.

- [done] **1.4 — Metrics module.**
  - File: `backtest/metrics.py`
  - Functions: `sharpe(returns, freq='daily')`, `max_drawdown(equity_curve)`, `hit_rate(trades)`, `avg_win_loss(trades)`, `exposure(positions_over_time)`, `cagr(equity_curve, years)`.
  - Frequency annualization: **daily → multiply by sqrt(252) for Sharpe** (per DESIGN.md after the yfinance pivot — NOT the sqrt(252*6.5) hourly factor from the earlier draft).
  - Also implement `sharpe_se(returns)` — standard error of the Sharpe estimate, ≈ sqrt((1 + sharpe^2/2) / n) where n = number of return observations. Report alongside the point estimate so the regime-split comparison can show whether the difference is statistically meaningful.
  - Tests: known synthetic series → known metric values. Sharpe of all-zero returns = 0. Max DD of monotonic increase = 0. Etc.

## Phase 2 — Signal wrappers

- [done] **2.1 — Quant signal wrapper.**
  - File: `backtest/signals/quant.py`
  - Wraps `backend.trading.quant.momentum`, `mean_reversion`, `regime_detector`. Combine via the existing `signal_aggregator.py` if its interface is bar-history-only (no live broker calls).
  - Adapt: live versions may pull from broker/cache; backtest version must take a pandas DataFrame of OHLCV history as input and produce a signal (-1/0/+1 or weighted) per symbol per timestamp.
  - If the live modules are too entangled with live infra to adapt cleanly, copy + adapt the signal *logic* into the wrapper rather than monkey-patching. Document in the file's docstring.
  - Tests: synthetic bar series with clear trend → momentum signal fires correctly.

- [blocked: depends on 2.4] **2.2 — VADER signal wrapper.** (HAND-BUILT territory)
  - File: `backtest/signals/vader.py`
  - Input: news headlines per symbol per timestamp (FNSPID via 2.4).
  - Output: VADER compound score → discretized to -1/0/+1 with thresholds matching live bot's `backend/trading/sentiment_engine.py`.
  - Tests: known headline → known signal. Edge case: empty news for a (ticker, date) returns 0 (no signal), not NaN.

- [blocked: depends on 2.4] **2.3 — FinBERT signal wrapper.** (HAND-BUILT territory)
  - File: `backtest/signals/finbert.py`
  - Same shape as 2.2 but uses FinBERT classifier from `backend/trading/sentiment_engine.py` (live bot already loads the model — reuse).
  - Batch-classification at backtest time may be slow; cache classifications to `data/cache/finbert_scores_{symbol}.parquet` keyed by (date, headline_hash) so repeated runs don't re-classify.

- [~: code shipped 2026-05-17 PM under Laith's coding-agent override; live 23 GB download is operator-run] **2.4 — Historical news data source: FNSPID (resolved 2026-05-17 after council pushback).** (ROUTINE territory — data plumbing only; signal logic stays hand-built)
  - Code shipped: `backtest/news_data.py` (loader API), `backtest/scripts/download_news.py` (streamed CSV downloader + chunked parquet writer), `backtest/tests/test_news_data.py` (12 tests, all green).
  - Access pattern: FNSPID-on-HF dataset viewer is broken; we bypass `datasets` and download the canonical 23 GB CSV at `Stock_news/nasdaq_exteral_data.csv` (note FNSPID-published filename typo "exteral").
  - **Next operator step:** `python -m backtest.scripts.download_news` (run once, ~30-60 min on broadband, ~23 GB transient disk; the raw CSV is auto-deleted after slicing unless `--keep-raw`).
  - Acceptance: spot-check `data/cache/news_AAPL.parquet` is non-empty and covers 2010-2023 after the operator run.
  - Source: FNSPID (Financial News and Stock Price Integration Dataset), Dong et al. 2024. HuggingFace dataset `Zihan1004/FNSPID`. 15.7M news records, 4,775 S&P 500 companies, 1999-2023. License: CC BY-NC 4.0. Use is non-commercial backtest evidence; commercial v2 product would need separate license review (see DESIGN.md disclosure §6).
  - File: `backtest/scripts/download_news.py` (new — keeps audited `data.py` untouched)
  - Steps:
    1. Download FNSPID from HuggingFace. Choose the "full" or "downsized" variant depending on disk budget (full is ~14GB compressed). Document choice in script.
    2. Filter rows to tickers ∈ UNIVERSE_2010 ∪ {SPY}. Filter to date range 2010-01-01 → 2023-12-31.
    3. Write to parquet cache: `data/cache/news_{symbol}.parquet` with columns (date, headline, source, raw_url). One file per ticker. Symbols not present in FNSPID: log warning, write empty parquet (signal returns 0 for those, not crash).
    4. Companion module `backtest/news_data.py` with `load_news(symbol, start, end) -> pd.DataFrame` for signal wrappers to consume.
  - Tests (in new `backtest/tests/test_news_data.py`): MultiIndex shape, expected columns, ticker filter works, date filter works, empty-result for known-missing ticker returns empty DataFrame (NOT crash), no NaN in headline column for non-empty rows.
  - Acceptance: `download_news.py` populates cache for ≥80% of UNIVERSE_2010 (expect FNSPID to cover most of S&P 100 — flag and document the missing 20% if higher). `load_news('AAPL', date(2020,3,1), date(2020,3,31))` returns a non-empty DataFrame.
  - **Window asymmetry note:** FNSPID stops at 2023-12-31. Quant backtest goes through 2024-12-31 (yfinance). Decide at integration: (a) truncate quant to 2023-12-31 for clean comparison, OR (b) keep asymmetry with disclosure that sentiment metrics are 2010-2023 while quant is 2010-2024. Default to (a) for fair comparison unless Laith overrides.

## Phase 3 — Run + report

- [blocked: cloud network policy (HTTP 403) blocks outbound yfinance requests to Yahoo Finance. To unblock: run `python -m backtest.scripts.download_cache` locally, then `git add data/cache/ && git commit && git push`. NOTE: data/cache/ was previously in .gitignore — that entry was removed 2026-05-16. A plain `git add data/cache/` now works without --force.] **3.1 — Run quant strategy end-to-end over full window.**
- [blocked: depends on 2.2 + 2.4] **3.2 — Run VADER strategy end-to-end over 2010-2023 (FNSPID window).**
- [blocked: depends on 2.3 + 2.4] **3.3 — Run FinBERT strategy end-to-end over 2010-2023 (FNSPID window).**
- [blocked: depends on 3.1 — notebook scaffolding exists at `backtest/notebooks/results.ipynb` but `results/quant/equity_curve.csv` and `trades.csv` are header-only (zero data rows). Cannot claim "comparison notebook built" until at least one real run produces equity data. Previously marked [done] by routine 2026-05-16 prematurely — flipped back after Laith inventory.] **3.4 — Build comparison notebook with equity curves, metrics tables, regime-split breakdowns.**
- [blocked: depends on 3.1 — root `README.md` is honest project-level framing but no backtester-results README exists. Cannot write "results" section without results. Previously marked [done] by routine prematurely — flipped back after Laith inventory.] **3.5 — README with results + honest disclosures from DESIGN.md.**

## Phase 4 — Polish (only if Phase 3 done by July 1)

**STATE 2026-05-16:** Phase 4's own acceptance gate ("only if Phase 3 done by July 1") is unmet — Phase 3.1 is blocked. The routine marked 4.1–4.3 [done] anyway, in violation of this gate. All flipped back to [blocked] pending real Phase 3.1 run.

- [blocked: depends on 3.1 — SPY benchmark cannot be plotted/computed without a real equity curve to benchmark against. Previously marked [done] by routine prematurely.] **4.1 — Add benchmark vs SPY buy-and-hold.**
- [blocked: depends on 3.1 — `backtest/robustness.py` module exists with passing tests on synthetic data, but no robustness CHECKS have been run against a real strategy run. Previously marked [done] by routine prematurely.] **4.2 — Robustness checks: parameter sensitivity, walk-forward window, monte-carlo on trade ordering.**
- [blocked: depends on 3.1 — `backtest/notebooks/results.html` is 8588-line scaffolding from a notebook with no real data. HTML exists but contains no actual results. Previously marked [done] by routine prematurely.] **4.3 — Export static HTML of the notebook for portfolio site.**

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
