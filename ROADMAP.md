# Meridian + Tachyon Roadmap — Path to August 2026

**Created 2026-05-15. Owner: Laith. Updated weekly (Friday EOD review).**

---

## Goal

By **July 31, 2026** (11 weeks from now), have all of:

1. **Meridian backtester shipped** — measured Sharpe / max DD / hit rate per signal source over 2010-2024 daily, regime-split at COVID
2. **Tachyon matching engine shipped** — C++17 order book with submit/cancel/crossing, FIFO, real test coverage, measured throughput + latency
3. **NeetCode 75+ deeply solved** — not 150 grinded, 75 understood
4. **Resume v3 finalized** — measured numbers only, behavioral STAR stories drafted, BMW infra title honest
5. **Referral pipeline of 5-10 warm contacts** — at target companies, ready for portal-open week
6. **2-3 mock interviews completed** — to know your weak spots before they cost a real loop

**Then in August: apply.**

---

## What's IN scope

- Meridian backtester (this repo, routine-driven on 14-yr daily yfinance data)
- Tachyon matching engine (separate repo, your hand-coded C++)
- NeetCode 150 — first 75 problems deeply understood
- BMW STAR behavioral stories (3-4 strong examples)
- Referral outreach (LinkedIn + BMW alumni network)
- Resume v3 with measured project bullets
- Mock interviews (pramp.com, friends, or interviewing.io free tier)

## What's NOT in scope (do NOT add)

- Linear Algebra self-study (Strang) — defer to fall semester
- FSU research re-engagement — only if you actually contact the professor AND do 6+ weeks of real work; otherwise stays off resume
- React dashboard for Meridian — locked plan rule
- Live trading on Meridian — paper mode through August
- Tachyon FIX/wire protocol, market orders v1, multi-strategy framework — locked plan rule
- Quant brain-teaser prep — quant interviews deferred to mid-career
- NeetCode 150+250 "hardest" tier — Gemini called it delusional, agreed
- Any new feature in either project beyond locked DESIGN.md spec

---

## Decisions due (with hard deadlines)

| Decision | Deadline | Status |
|---|---|---|
| Historical news data for sentiment (Phase 2.4 in backtest/TODO.md) — pay Polygon, use GDELT, or skip sentiment | **2026-05-31** | open |
| Linear Algebra path: FSU summer class registration OR self-study commitment OR explicit defer to fall | **2026-06-01** | open |
| Referral target list — 10 named companies + 2 contacts each | **2026-05-31** | open |
| Tachyon-vs-Meridian integration: ship integrated or as two standalones? | **2026-06-30** (decision gate at Tachyon progress check) | open |
| Compute Sharpe / max DD on existing live trade logs (overdue from prior plan, doesn't need backtester done) | **2026-05-22** | open |
| Resume v3 first draft with measured Meridian numbers | **2026-06-30** | open |

---

## Week-by-week

### Week 1 — May 15-22

**Theme:** Data layer pivot lands. Backtester through Phase 0.

- `[routine]` 0.1-v2: yfinance daily fetcher overwrites `backtest/data.py`
- `[routine]` 0.2-v2: `UNIVERSE_2010` (Jan 2010 OEX) overwrites `backtest/universe.py`
- `[you]` Tachyon: project scaffolding committed (repo init, build system, README skeleton)
- `[you]` NeetCode: solve 5 problems (arrays + hashmaps). Don't grind — understand.
- `[you]` Send 2 LinkedIn DMs to BMW alumni / FSU CS grads at target companies
- `[you]` **Compute Sharpe + max DD on live bot trade logs** — overdue, data already exists in `logs/`

**End-of-week check (Fri May 22):**
- [ ] Routine has produced at least 4 recap files (one per run)
- [ ] yfinance daily data is verified to load
- [ ] 5 NeetCode problems done
- [ ] Live trade log metrics computed
- [ ] 2 referral DMs sent

---

### Week 2 — May 22-29

**Theme:** Backtester Phase 1 (engine + fills + metrics). Tachyon core begins.

- `[routine]` 1.1 Strategy ABC, 1.2 fills, 1.3 engine event loop, 1.4 metrics — all 4 should land this week
- `[you]` Tachyon: `submit()` + `cancel()` + `best_bid()` + `best_ask()` working
- `[you]` NeetCode: 6 more problems (target cumulative: 10-12)
- `[you]` 3 more referral DMs (cumulative: 5)
- `[you+me]` Decision call: historical news data for sentiment (deadline approaching)

**End-of-week check:**
- [ ] Backtester can run a NoopStrategy over a date range without errors
- [ ] Tachyon submit/cancel passing your first unit test
- [ ] NeetCode cumulative: 10+
- [ ] Cumulative referrals: 5

---

### Week 3 — May 29 - Jun 5

**Theme:** Quant signal wrapper. Sentiment data decision resolved. First mock.

- `[routine]` 2.1 quant signal wrapper (wraps existing `backend/trading/quant/`)
- `[routine]` 2.4 sentiment data — proceeds or blocks per decision from Week 2
- `[you]` Tachyon: crossing + FIFO matching, partial fills
- `[you]` NeetCode: 8 problems (cumulative: 18-20)
- `[you]` **1 mock interview** (pramp.com or friend)
- `[you+me]` Linear Algebra decision finalized

**End-of-week check:**
- [ ] Quant signal runs against backtester data
- [ ] Tachyon: 2 orders can cross and match correctly
- [ ] First mock done — note 3 weak areas
- [ ] LA path decided

---

### Week 4 — Jun 5-12

**Theme:** First end-to-end backtest. Tachyon hardening.

- `[routine]` 3.1 run quant strategy end-to-end over 2010-2024
- `[routine]` 2.2 / 2.3 sentiment wrappers if Week 3 unblocked them
- `[you]` Tachyon: market orders + edge cases (partial fills, self-trade prevention if relevant)
- `[you]` NeetCode: 8 problems (cumulative: 26-28)
- `[you]` **BMW behavioral: draft 3 STAR stories** (1 conflict, 1 ambiguity, 1 impact)

**End-of-week check:**
- [ ] Quant strategy produced a real Sharpe number (good or bad — number is the point)
- [ ] Tachyon: 5+ test cases passing
- [ ] STAR drafts written
- [ ] NeetCode cumulative: 25+

---

### Week 5 — Jun 12-19

**Theme:** Mid-June checkpoint. Halfway to end-of-June ship target.

- `[routine]` 3.2 / 3.3 sentiment strategy runs (or document as blocked)
- `[you]` Tachyon: replay mode for deterministic testing
- `[you]` NeetCode: 8 problems (cumulative: 33-36)
- `[you]` **Mid-month mock interview**
- `[you+me]` Mid-point reality check — are we on track for end-of-June ship?

**End-of-week check (Fri Jun 19):**
- [ ] Per-signal Sharpe comparison data exists for at least quant signals
- [ ] Tachyon replay mode demonstrably working
- [ ] Mid-June review: green / yellow / red on each project

---

### Week 6 — Jun 19-26

**Theme:** Polish notebook + README. Tachyon edge cases.

- `[routine]` 3.4 comparison notebook (equity curves, metrics tables, regime splits)
- `[routine]` 3.5 README v1 with results + honest disclosures
- `[you]` Tachyon: golden trace tests
- `[you]` NeetCode: 8 problems (cumulative: 41-44)
- `[you]` Resume v3 first draft with placeholder numbers

---

### Week 7 — Jun 26 - Jul 3 (END OF PHASE 1)

**Theme:** Both projects "demoable." Phase 2 (polish) begins.

- `[routine]` 4.1 SPY benchmark comparison, 4.2 robustness checks
- `[you]` Tachyon: Google Benchmark integration, measure orders/sec + p50/p99 latency
- `[you]` NeetCode: 8 problems (cumulative: 49-52)
- `[you]` **End-of-Phase-1 review** — are both projects demoable to a recruiter today?

**End-of-week check:**
- [ ] Meridian: notebook with equity curves + Sharpe + max DD per signal, regime split
- [ ] Tachyon: measured orders/sec number (not aspirational)
- [ ] Resume v3 with measured Meridian Sharpe (placeholder for Tachyon number)

---

### Week 8 — Jul 3-10

**Theme:** Tachyon profiling. Mock interview spike.

- `[you]` Tachyon: `perf` profiling + cache analysis write-up
- `[you]` Tachyon: identify and fix top 1-2 bottlenecks
- `[you]` NeetCode: 8 problems (cumulative: 57-60)
- `[you]` **2 mock interviews this week** — pressure-test what 60 NeetCode buys you
- `[you+me]` Tachyon-Meridian integration call (deadline)

---

### Week 9 — Jul 10-17

**Theme:** Polish push.

- `[you]` Tachyon: property-based / fuzz tests if time permits
- `[you]` NeetCode: 8 problems (cumulative: 65-68)
- `[you]` Both projects: architecture diagrams drawn
- `[you]` Both projects: demo GIFs / videos

---

### Week 10 — Jul 17-24

**Theme:** Resume + application prep.

- `[you]` Resume v3 final — measured numbers only, polished bullets
- `[you]` Cover letter template (1-2 variants — generalist + role-specific)
- `[you]` Target company list locked: 10 named companies + 2 referral contacts each
- `[you]` NeetCode: 8 problems (cumulative: 73-76)
- `[you]` **Final mock interview** with company-specific format

---

### Week 11 — Jul 24-31 (DEADLINE WEEK)

**Theme:** Ship + ready to apply.

- `[you]` Confirm all referral contacts know to expect your application
- `[you]` Final NeetCode push to 80+
- `[you]` Both project READMEs proofread + linked from resume
- `[you]` All resume bullets defensible — practice saying them out loud
- `[you]` **Send first 3 applications** the moment portals open

---

## Accountability ritual

**Every Friday 8-9pm ET:** 30 min review. Open ROADMAP.md, this week's section.

For each item:
- ✅ Done — mark and move on
- 🟡 Partial — note where you stopped, carry to next week
- ❌ Slipped — write WHY in one sentence. Patterns matter.

After the review, look at the next week's tasks. If 3+ items slipped this week, the next week is unrealistic — cut something explicitly.

**Hard rule:** No silent slipping. An item is either checked or has a written reason it didn't happen. "I forgot" is not a reason; what did you do instead?

---

## What gets cut first if we fall behind

In order of cut-first:

1. NeetCode count target (50 deep > 75 shallow)
2. Property-based / fuzz testing on Tachyon (Week 9 polish)
3. Resume cover letter templates (Week 10 — use a generic one)
4. SPY benchmark + robustness checks on Meridian (Week 7 polish)
5. Tachyon-Meridian integration (always optional)

What does NOT get cut, ever:
- Shipping ONE measurable number per project
- Resume v3
- At least 1 mock interview before Aug 1
- Referral list of 10 companies

---

## Related docs

- `backtest/DESIGN.md` — Meridian backtester locked spec
- `backtest/TODO.md` — routine's task queue for Meridian
- `journal/*.md` — routine recap files (read these to learn what was built)
- Memory: `project_swe_portfolio_plan.md`, `project_meridian_routine_execution_model.md`
