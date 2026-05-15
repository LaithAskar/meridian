# Friday Review — 2026-05-15

## Current phase
Phase 0 — Bootstrap (May 15 → May 22) — week 1 of 1.

## Items this week

**Phase 0 items (current phase):**

| Item | Status | Evidence |
|---|---|---|
| [routine] 0.1-v2 — yfinance daily bar fetcher | ✅ | commit e9be3d1; recap 2026-05-15-pm.md; 15 tests green |
| [routine] 0.2-v2 — UNIVERSE_2010 (100 tickers, Jan 2010 OEX) | ✅ | commit 3f88545; recap 2026-05-15-pm2.md; 26 tests green |
| [you] Read both recap files + confirm yfinance fetcher matches spec | ❌ | No evidence of Laith review in any recap, TODO mark, or commit |
| [you] Compute Sharpe + max DD on live trade logs | ✅ | 2026-05-15-live-bot-metrics.md (commit cabf915); finding: uncomputable from 2-snapshot data window; documented |
| **Milestone gate:** actual yfinance data load for UNIVERSE_2010 | ⛔ | recap pm9.md; HTTP 403 from cloud network allowlist blocks all outbound Yahoo Finance calls |

**Routine ran ahead into Phases 1–3 (same day):**

| Item | Status | Evidence |
|---|---|---|
| [routine] 1.1 — Strategy ABC + Order/Position/Portfolio dataclasses | ✅ | commit 6766811; recap pm3.md; 20 tests green |
| [routine] 1.2 — Fill model (next-bar-open + 5 bps slippage) | ✅ | commit 8d3e55c; recap pm4.md; 14 tests green |
| [routine] 1.3 — Engine event loop | ✅ | commit c5c0577; recap pm5.md; 35 tests green |
| [routine] 1.4 — Metrics module (Sharpe + SE, max DD, hit rate, CAGR, exposure) | ✅ | commit 4b04b25; recap pm6.md; 59 tests green |
| [routine] 2.1 — Quant signal wrapper (QuantStrategy, regime detection) | ✅ | commit 8b2980c; recap pm7.md; 180/180 tests green |
| [routine] 2.2 — VADER signal wrapper | ⛔ | recap pm8.md; no historical news source exists for 2010-2024 |
| [routine] 2.3 — FinBERT signal wrapper | ⛔ | recap pm8.md; same dependency as 2.2 |
| [routine] 2.4 — Historical news data source decision | ⛔ | recap pm8.md; five options documented; waiting for Laith decision |
| [routine] 3.1 — End-to-end quant run (run_quant.py) | ⛔ | commit 64454f8; recap pm9.md; code complete, 214 tests green, actual execution blocked by HTTP 403 |
| [routine] 3.4 — Comparison notebook (nb_utils.py + results.ipynb) | ✅ | commit c760690; recap pm10.md; 55 tests green; notebook validates via nbformat |

## What shipped

**[routine] commits:**
- `e9be3d1` — 0.1-v2: yfinance daily bar fetcher, per-symbol parquet cache, 15 tests
- `3f88545` — 0.2-v2: UNIVERSE_2010 — 100-ticker Jan 2010 OEX universe, ticker-rename docs (GOOGL, WBA, ELV), 11 tests
- `6766811` — 1.1: Strategy ABC, Order/Position/Portfolio dataclasses with validation, NoopStrategy, 20 tests
- `8d3e55c` — 1.2: Fill model — next-bar-open + 5 bps adverse slippage, delisted-bar cancellation, 14 tests
- `c5c0577` — 1.3: Engine event loop — portfolio accounting, trade records, equity curve DataFrame, 35 tests
- `4b04b25` — 1.4: Metrics module — Sharpe (ddof=1, ×√252), Sharpe SE (Lo 2002), max DD, hit rate, avg win/loss, exposure, CAGR; 59 tests; full suite 154 green
- `8b2980c` — 2.1: QuantStrategy — regime-adjusted quant signal wrapper (momentum + mean-reversion), live yfinance calls replaced with pre-loaded Series to avoid look-ahead; 26 tests, 180/180 total
- `800e225` — 2.2/2.3/2.4: marked blocked; news data options documented in pm8.md
- `64454f8` — 3.1: run_quant.py runner + QuantStrategy history cap (300-bar trim, ~12× speedup); blocked on network allowlist; 34 new tests, 214 total
- `c760690` — 3.4: nb_utils.py + results.ipynb + _build_notebook.py; graceful-degradation notebook works with zero results today, fills in as data arrives; 55 tests, 269 total

**Laith's non-routine commits:**
- `90c9d8a` — fix requirements: corrected yfinance version pin (1.2.0 doesn't exist, correct is 0.2.x)
- `cabf915` — live-bot metrics analysis: Sharpe uncomputable from 2-day data; documented why
- `961fff5` / `73e98cd` — rescoped ROADMAP to Meridian-only; added 11-week roadmap through July 31
- `b8c1883` / `2f53d55` — two-step data-source pivot: Alpaca hourly → yfinance daily 2005 → yfinance daily 2010-2024

**Journal recaps filed this week:**
- `may14.md` — May 14 plan-lock session: stripped 8,107 lines of dead code, locked backtest-first plan, rejected 30-day paper trading Sharpe for resume on statistical-validity grounds
- `2026-05-15-live-bot-metrics.md` — parsed May 4-5 live bot logs; 2 equity snapshots + 0 round-trips = Sharpe undefined; explains why the backtester is the only path to a resume-grade number
- `2026-05-15-am.md` — routine recap for original 0.1 Alpaca fetcher (now obsolete after same-day pivot)
- `2026-05-15-pm.md` through `pm10.md` (10 recaps) — one per task executed today; covers 0.1-v2 through 3.4 with full code, tests, and tradeoff rationale

## What slipped or is blocked

- **[you] Read recap files + confirm spec:** No evidence this happened. Ten recap files landed today. Skipping them violates the recap-as-contract rule and makes the engine a black box before it runs on real data. The engine (1.3) specifically needs eyeballs — the equity accounting choices (avg-cost basis, fill-before-snapshot ordering, sell-cap logic) are the kind of subtle decisions that compound into wrong Sharpe numbers. ROADMAP says "read 1.3 carefully."

- **Phase 0 milestone — actual yfinance data load:** All code is correct and tested with mocks (269 tests green), but not one real yfinance call has succeeded in the cloud environment. The milestone wording is "can load yfinance data for the full UNIVERSE_2010 over 2010-2024 without errors" — that cannot be verified until the 403 blocker is resolved. This is a two-option fix (recap pm9.md): enable Yahoo Finance hosts in the cloud allowlist, or run the download locally and commit the parquet cache.

- **3.1 — Quant strategy end-to-end run:** Code complete (commit 64454f8), runner ready, 214 tests green. No actual backtest results exist. This is the load-bearing deliverable — Phase 4 polish, the resume bullet, and every downstream item depend on having a real Sharpe number from this run. Currently blocked purely by infrastructure, not logic.

- **2.2 / 2.3 / 2.4 — Sentiment signals:** Blocked on historical news data decision. Deadline May 31. Five options with cost/effort/quality breakdown in recap pm8.md. Routine recommends Option C (skip sentiment, quant-only) as the highest interview-defensibility path. If you want sentiment numbers, Option A (Polygon, ~$79–200 one-time) is the right call. Don't let this drift past May 22.

## Decisions overdue

None. First deadline is 2026-05-22 (Sharpe/max DD on live logs). That item is complete — finding is "uncomputable from 2 equity snapshots," documented in 2026-05-15-live-bot-metrics.md. No decisions are past their deadline as of today.

## Phase milestone trajectory

🟡 **At risk.** Phase 0 milestone (May 22) requires actual yfinance data loading for UNIVERSE_2010 without errors. The cloud environment's network policy blocks all outbound calls to Yahoo Finance (HTTP 403). The code is correct and fully tested; the blocker is infrastructure, not logic. One action from Laith unblocks it. If the network issue isn't resolved before May 22, the milestone slips by definition — "can load data" hasn't been demonstrated.

## Recommended actions for next week

1. **Fix the network blocker (this weekend):** Run `fetch_bars(UNIVERSE_2010, date(2010,1,1), date(2024,12,31))` locally, commit `data/cache/` parquet files, push. This unblocks the Phase 0 milestone and enables 3.1 to produce the first real Sharpe number. Alternatively, add `finance.yahoo.com`, `query1.finance.yahoo.com`, `query2.finance.yahoo.com` to the cloud environment's outbound allowlist. Script for local download is in recap pm9.md.

2. **Decide on sentiment data by May 22 (not May 31):** The routine's recommendation is Option C — quant-only with honest disclosure. If you want sentiment in the final report, commit to Option A (Polygon) now so it doesn't sit open until June and block Phase 2 from closing. ROADMAP's "What gets cut first" list has sentiment at #4 — this decision is effectively a scope call.

3. **Read Phase 1 recaps (pm3–pm6) before 3.1 produces numbers:** Equity accounting errors are silent until the Sharpe comes out wrong. You need to verify the fill-timing ordering (fill at t+1 open before on_bar at t+1), the avg-cost basis on additive buys, and the sell-cap behavior. This is the most important [you] item currently undone.

4. **Once 3.1 runs, read metrics.json cold:** The first Sharpe number is the point. Compare pre- vs post-COVID. Check the SE — if n_trades is small, the SE will be wide. Per ROADMAP risk #5: a Sharpe near zero or negative is fine and interview-defensible. Don't touch parameters to chase a prettier number.
