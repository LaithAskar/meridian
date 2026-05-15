# Meridian Backtester Roadmap — Path to August 2026

**Scope: Meridian only.** Tachyon, NeetCode, referrals, behavioral prep, resume work live outside this repo. This doc covers only what gets built in `meridian/` between now and the August application window.

**Created 2026-05-15. Owner: Laith. Review every Friday EOD.**

---

## Goal

By **July 31, 2026**, Meridian has shipped:

- Working backtester over yfinance daily bars, **2010-2024** (14 years)
- **Measured Sharpe, max DD, hit rate, exposure** per signal source (FinBERT, VADER, quant) over pre/post-COVID regime split
- Static results notebook (no React, no web UI)
- README with measured numbers + honest disclosures
- One resume bullet you can defend in an interview

---

## In scope (locked from DESIGN.md)

- Strategy ABC with injected signal source
- Next-bar-open fill + 5 bps slippage
- yfinance daily bars, 2010-2024
- Jan 2010 OEX universe (100 names) held constant
- Equal-weight position sizing, max N concurrent
- Sharpe / max DD / hit rate / avg win-loss / exposure / CAGR per signal
- Pre/post-COVID regime split (cut at 2020-03-01)
- SPY buy-and-hold benchmark
- Static notebook + HTML export

## Not in scope (do NOT add)

- React or any web UI
- Live trading or paper-broker integration
- Tachyon integration (separate Tachyon roadmap; integrate only if Tachyon comfortably ahead at end of June)
- Options pricing, factor models, multi-strategy frameworks
- Vol-targeted position sizing (deferred to fall)
- Sector / concentration limits (deferred to fall)
- Custom indicator framework — `ta` library covers 90%
- Twitter / Discord / new signal sources

---

## Decisions due (Meridian-only)

| Decision | Deadline | Status |
|---|---|---|
| **Sharpe / max DD on existing live trade logs** (data exists in `logs/`, overdue from prior plan) | 2026-05-22 | open |
| **Historical news data for sentiment** (Phase 2.4) — pay Polygon, use GDELT, skip sentiment entirely, or use subset window | 2026-05-31 | open |
| **Position sizing N** — max concurrent positions per strategy (currently TBD, typically 5-15) | 2026-06-05 | open |
| **Tachyon integration ON/OFF** — only if Tachyon clears its own milestone | 2026-06-30 | open |
| **Resume bullet draft with measured Meridian Sharpe** | 2026-07-15 | open |

---

## Phases

### Phase 0 — Bootstrap (May 15 → May 22)

- `[routine]` 0.1-v2: yfinance daily fetcher overwrites `backtest/data.py`
- `[routine]` 0.2-v2: `UNIVERSE_2010` overwrites `backtest/universe.py`
- `[you]` Read both recap files. Confirm the yfinance fetcher matches spec. Push back via TODO.md edits if not.
- `[you]` Compute Sharpe + max DD on `logs/` live trade history (overdue, doesn't need backtester)

**Milestone (Fri May 22):** Can load yfinance data for the full UNIVERSE_2010 over 2010-2024 without errors. Live-bot metrics computed.

---

### Phase 1 — Engine (May 22 → Jun 5)

- `[routine]` 1.1 Strategy ABC + Order/Position/Portfolio dataclasses
- `[routine]` 1.2 Fill model (next-bar-open + 5 bps slippage)
- `[routine]` 1.3 Engine event loop
- `[routine]` 1.4 Metrics module (Sharpe + Sharpe SE, max DD, hit rate, exposure, CAGR)
- `[you]` Read each recap. The engine is the load-bearing piece — read 1.3 carefully and verify the equity accounting is correct.

**Milestone (Fri Jun 5):** NoopStrategy runs over 1 year of data, equity stays flat (no trades), no NaN in equity curve. Metrics module passes unit tests on known synthetic series.

---

### Phase 2 — Signals + sentiment data decision (Jun 5 → Jun 19)

- `[routine]` 2.1 Quant signal wrapper (wraps `backend/trading/quant/{momentum, mean_reversion, regime_detector}`)
- `[routine]` 2.4 hits the sentiment-data blocker — produces a recap proposing options
- `[you+me]` Resolve 2.4: pay Polygon ($), GDELT (messy free), skip sentiment, or subset window
- `[routine]` 2.2 VADER wrapper (or `[blocked]` and skip)
- `[routine]` 2.3 FinBERT wrapper (or `[blocked]` and skip)

**Milestone (Fri Jun 19):** Quant signal produces buy/sell signals over backtest data. Sentiment data path is decided and committed to DESIGN.md.

---

### Phase 3 — End-to-end + comparison (Jun 19 → Jul 3)

- `[routine]` 3.1 Quant strategy end-to-end run, full window + regime split
- `[routine]` 3.2 VADER strategy run (if 2.4 unblocked)
- `[routine]` 3.3 FinBERT strategy run (if 2.4 unblocked)
- `[routine]` 3.4 Comparison notebook — equity curves overlaid, metrics tables, regime breakdowns
- `[routine]` 3.5 README v1 with results + disclosures from DESIGN.md
- `[you]` Read the comparison notebook carefully. The numbers in it are what go on the resume.

**Milestone (Fri Jul 3):** Have a measurable Sharpe number per signal source. **Number is the point — good, bad, or zero, all are interview-defensible.** Quant Sharpe SHIPPING is non-negotiable; sentiment is optional if 2.4 stalled.

---

### Phase 4 — Polish (Jul 3 → Jul 17)

- `[routine]` 4.1 SPY benchmark comparison (overlay equity curve, report excess Sharpe)
- `[routine]` 4.2 Robustness checks (parameter sensitivity, walk-forward window, monte-carlo on trade ordering)
- `[routine]` 4.3 Static HTML export of the notebook for portfolio use
- `[you]` First draft of resume bullet using actual numbers

**Milestone (Fri Jul 17):** Pre/post-COVID Sharpes reported with standard error. SPY benchmark on equity curve plot. Resume bullet draft v1 written.

---

### Phase 5 — Demo prep (Jul 17 → Jul 31)

- `[you]` README final polish — opening hook, results section with chart screenshots
- `[you]` Architecture diagram drawn (Excalidraw / drawio / Mermaid)
- `[you]` One-paragraph elevator pitch — "What is Meridian, what did you measure, what was surprising?"
- `[you]` Resume bullet final — measured numbers only
- `[you]` Practice the design defenses out loud: "Why daily? Why 2010 start? Why next-bar-open fill? Why this universe?"
- `[you+me]` Final dry-run session — I pretend to be a quant interviewer and grill you on the project

**Milestone (Fri Jul 31):** Project demoable in 5 minutes to a recruiter. Every design choice has a defensible answer. Bullet on resume.

---

## Routine vs you split

- **~85% of code** → routine (twice-daily cron, sonnet-4-6 on Anthropic cloud)
- **~10% of your time** → reading recaps, editing TODO.md to redirect, approving design changes
- **~5% of your time** → demo materials at Phase 5 (architecture diagram, README polish, elevator pitch)

**You write the resume bullet yourself. Always. Non-negotiable.**

---

## Risks specific to Meridian

1. **Sentiment data block (Phase 2.4)** — historical news headlines for 100 tickers over 14 years isn't free. If you skip sentiment, the project becomes "quant-signal backtester" — narrower but still shippable. Quant Sharpe is the load-bearing number.
2. **yfinance data quality on delisted names** — UNIVERSE_2010 includes acquired/delisted tickers. `KNOWN_NO_DATA` set in universe.py covers the gaps. Spot-check 5 ticker histories before Phase 3 to make sure data quality is acceptable.
3. **DESIGN.md churn** — May 15 had three data-layer iterations in one day (Alpaca → yfinance/2005 → yfinance/2010). The routine wasted 2 runs on dead code. **Steady spec from here.** If a 4th iteration looks tempting, the answer is probably "ship what we have."
4. **You stop reading recaps** — black-box risk. The recap-as-learning loop only works if you actually engage with the code. Recap pile-up = project becomes indefensible. Counter: Friday review ritual catches this.
5. **Phase 3 numbers come back ugly** — quant Sharpe at 0.0 or negative is *fine* and *still resume-worthy* if framed honestly. "Measured X signal sources, found Y had no statistically significant edge after costs" is a stronger interview story than fabricated returns.

---

## What gets cut first if we fall behind

In order of cut-first:

1. Phase 4.2 robustness checks (walk-forward, monte-carlo)
2. Phase 4.3 static HTML export (just link the notebook on GitHub)
3. Phase 4.1 SPY benchmark (nice-to-have, not load-bearing)
4. Phase 2 sentiment signals (if 2.4 doesn't resolve cleanly — ship quant-only)
5. Phase 3.5 README v1 (replace with bullet-point summary)

**Does NOT get cut, ever:**

- Phase 1 (engine + fills + metrics) — without these, there's no backtester at all
- Phase 3.1 quant strategy end-to-end run with a measured Sharpe
- Phase 5 README + elevator pitch (5 min of demo > nothing)
- One defensible resume bullet

---

## Friday review

End of each week, open this doc, scan the current phase. For each line item:

- ✅ Done — mark and move on
- 🟡 In progress — note state, carry to next week
- ❌ Slipped — write WHY in one sentence. Patterns matter.
- ⛔ Blocked — note what's needed to unblock

After scanning, look at next phase. If 2+ items slipped this week, current phase milestone is probably going to slip by 1 week — explicitly acknowledge that, don't pretend.

**Hard rule:** No silent slipping. Item is either checked or has a written reason it didn't happen.

---

## Related docs

- `backtest/DESIGN.md` — locked spec (yfinance daily 2010-2024, UNIVERSE_2010, next-bar-open + 5bps, etc.)
- `backtest/TODO.md` — routine's ordered task queue
- `journal/*.md` — routine recap files (read these — recap is the contract)
- Memory: `project_meridian_routine_execution_model.md` (routine setup + why), `project_swe_portfolio_plan.md` (broader August strategy)
