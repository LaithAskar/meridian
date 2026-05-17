# Audit: backtest/universe.py

**Auditor:** Claude (machine-drafted, see disclosure below)
**Date:** 2026-05-17
**Module audited:** `backtest/universe.py`
**Checklist section:** `backtest/REVIEW_CHECKLIST.md` §3 (universe.py / survivorship bias)

---

## Disclosure: how this audit was produced

This file was drafted by Claude after Laith explicitly authorized machine-drafted audit findings ("do the audit for me", 2026-05-17 PM). It is NOT the hand-read audit the 2026-05-16 council prescribed.

What this changes:
- **Findings are still real.** The checks below identify concrete issues, not rubber-stamps.
- **Interview-defense layer is weaker.** Laith has not read the code line-by-line against the checklist. Under hostile review ("walk me through how you confirmed §3.6") he can answer about WHAT was found but not WHAT IT FELT LIKE to find it. The cognitive trace that produces fluent defense is missing.
- **What it would take to restore interview defense:** re-read each cited section in `universe.py` and re-write each "Interview gloss" below in Laith's own voice. The verdicts can stay; the glosses must be his to be defensible.

The findings stand regardless of who wrote them. The interview-prep layer does not.

---

## §3.1 — KNOWN_NO_DATA rationale

**Check:** Is each ticker in `KNOWN_NO_DATA` documented with a *named event* (delisting date, acquirer, bankruptcy), not just "couldn't fetch"?

**Citation:** `universe.py:47-72` ("Partial-history tickers" table in the module docstring) + `universe.py:126-135` (`KNOWN_NO_DATA` comment confirming empirical 2026-05-16 bulk-download verification).

**Verdict:** **PARTIAL — contains an internal contradiction.**

Every ticker in `KNOWN_NO_DATA = {APC, KFT, MON, MRO, RTN, UTX, WBA}` does have a named event in the docstring table. So the checklist's literal text is satisfied. BUT:

- **WBA contradiction.** Lines 41-43 (rename-mapping section) state: *"yfinance carries WBA history back through the WAG era."* Line 135 (`KNOWN_NO_DATA` comment) states: *"WBA returned empty DataFrames from yfinance ... yfinance dropped their historical price feeds."* These cannot both be true. Either the rename-mapping claim is stale (WBA was once fetchable, no longer is) or the empirical 2026-05-16 result was a transient yfinance failure.
- **MRO contradiction.** Line 67 says *"MRO continues as upstream-only E&P"* — implying it has data — but MRO is in `KNOWN_NO_DATA`.

These contradictions don't break the run (the engine treats `KNOWN_NO_DATA` tickers as "no position" regardless of which side is right) but they make the documentation internally inconsistent.

**Interview gloss (machine-drafted, rewrite in your voice for defense):** `KNOWN_NO_DATA` is the empirically-verified set of 2010-OEX names where yfinance returns no data at all over 2010-2024 — typically because the company was acquired/merged out of existence and Yahoo Finance dropped its historical feed. Each ticker has a named M&A or delisting event documented in the module docstring. There are two documentation contradictions (WBA and MRO are described elsewhere in the file as having continuous yfinance history) that should be resolved by re-running a fetch on each and updating whichever side is stale.

**Fix required before §3.1 is PASS:** resolve WBA + MRO documentation contradictions by running `python -c "from backtest.data import fetch_bars; from datetime import date; print(fetch_bars(['WBA','MRO'], date(2010,1,1), date(2024,12,31)).head())"` and updating either the docstring or `KNOWN_NO_DATA` to match observed reality.

### Empirical resolution (run 2026-05-17 PM during this audit)

```
WBA: EMPTY (no data)             # yfinance returns HTTP 404 "Quote not found"
MRO: EMPTY (no data)             # same
AET: 2244 bars, last=2018-11-29  # matches docstring claim (CVS acquired ~Nov 2018)
EMC: 411 bars, first=2023-05-15  # SEE §3.1-bonus BELOW — ticker re-use
HPQ: 3774 bars, last=2024-12-31  # full continuous history, matches docstring
```

Resolution of the two contradictions:
- **WBA** is correctly in `KNOWN_NO_DATA`. The docstring rename-mapping claim at `universe.py:41-43` ("yfinance carries WBA history back through the WAG era") is **STALE/WRONG**. yfinance returns HTTP 404 today.
- **MRO** is correctly in `KNOWN_NO_DATA`. The docstring claim at `universe.py:66-67` ("MRO continues as upstream-only E&P") is **STALE/WRONG**. yfinance returns empty.

The docstring should be edited to move WBA and MRO out of their respective non-`KNOWN_NO_DATA` claim sections.

### §3.1-bonus — NEW FINDING: EMC ticker re-use

**EMC was acquired by Dell Technologies in Sep 2016** (docstring `universe.py:60`). Therefore the EMC ticker for the 2010-OEX-era EMC Corporation should return data ONLY through ~Sep 2016, or be in `KNOWN_NO_DATA` (which it is NOT).

**Empirical fetch returned 411 bars starting 2023-05-15.** This means the EMC ticker has been **re-used by an unrelated company** post-acquisition. The data currently being consumed by the backtester for "EMC" from 2023-05-15 onward is the price history of *some other company* — not the EMC Corporation that was in the Jan 2010 OEX.

This is a real data-integrity bug. The engine is treating the EMC ticker as having continuous coverage with a 7-year gap (2016 → 2023), but the post-gap data is a different security entirely.

**Verdict:** **FAIL — silent data-source error.**

**Required fix:** Add `EMC` to `KNOWN_NO_DATA` with rationale: *"acquired by Dell Sep 2016; ticker has since been re-used by an unrelated company. Post-2023 yfinance data under this ticker is NOT continuous with the 2010-OEX EMC Corporation."*

This is exactly the bug-class the audit gate exists to catch. A passing test on `EMC` fetchability returning non-empty data would *appear* to validate the universe, while silently feeding a different company into the strategy.

---

## §3.2 — Delisted name handling

**Check:** For tickers that delisted DURING the window, how does the engine handle the post-event period? Three acceptable patterns: (a) acquisition price + remove, (b) -100% if bankruptcy, (c) NaN'd out with documented assumption. Silently dropping rows is survivorship bias and NOT acceptable.

**Citation:** `universe.py:51` ("The engine treats missing bars as 'no position' for that symbol from that point onward.") + `backtest/fills.py` (missing-next-bar cancels the order rather than silently filling — confirmed during A.2 audit, deferred for now).

**Verdict:** **PARTIAL — "freeze in place" doesn't match any of the three named patterns and slightly biases returns downward for acquired names.**

The actual handling is "position last marked-to-market at the final available bar, then held forever with no further trades because the engine has no next bar to fill on." This is closest to pattern (c) — NaN'd out — but with an implicit assumption that's defensible but non-obvious: for an acquired name like AET (CVS acquisition ~Nov 2018), the strategy never realizes the acquisition-price cash payout. If the quant strategy was long AET at the time of acquisition, the realized P&L on that position is the price drift up to the last yfinance bar, which is typically *below* the eventual acquisition price (acquirers pay a premium to last trade). So the engine **slightly UNDERSTATES** the strategy's realized return on acquired names.

Magnitude: probably small. The documented partial-history names (lines 47-72) are mostly large-cap acquisitions where the prior-close-to-acquisition-price premium is typically 10-30% — so a held position bears this drag once, not repeatedly. Over a 14-year backtest with ~210-day avg holding period and 215 total trades, the affected trades are a small fraction.

For bankruptcies (no documented cases in the partial-history table), the same "freeze in place" logic would *overstate* returns by avoiding the -100% loss. None of the listed events are bankruptcies, so this bias is not active for the current universe.

**Interview gloss (machine-drafted, rewrite for defense):** When a name in the universe is acquired or merged out during the backtest window, its yfinance bars simply stop and the engine treats the held position as frozen — last mark-to-market, no further fills. This is honest about survivorship (the position is NOT silently dropped — its last-known equity contribution stays in the portfolio) but it's stylistically choice (c) from the checklist with an implicit assumption: we leave a small bias on the table (typically underestimating returns by the acquisition-price premium for held names) rather than introducing a corporate-actions data source. For the modern era (2010+) and a universe of large-cap names mostly being acquired (not bankrupted), this trades a small *downward* bias for documentation simplicity.

**Fix required for full PASS:** either (a) explicitly state this in DESIGN.md as choice (c) with named assumption, or (b) wire in a corporate-actions handler that emits a sell at the documented acquisition price for each `KNOWN_NO_DATA` ticker. (b) is more rigorous but materially more code. (a) is the honest version of what's already shipped.

---

## §3.3 — Renamed tickers (yfinance continuity)

**Check:** For FB→META, PCLN→BKNG, etc., does the universe use the modern ticker AND does yfinance return continuous history at the rename date? Spot-check one rename.

**Citation:** `universe.py:29-46` (rename-mapping section documenting GOOGL/WBA/ELV).

**Verdict:** **UNCERTAIN — claim is asserted but no spot-check artifact exists in this file or in tests.**

The docstring asserts yfinance carries continuous history for each of the three renames (GOOGL since 2004 IPO, WBA through WAG era, ELV through WellPoint→Anthem→Elevance). The WBA claim is directly contradicted by §3.1's finding above — so at least one of the three renames has an unresolved data-availability question.

There is no test in `backtest/tests/test_universe.py` that fetches a renamed ticker over its rename window and asserts the date range covers both pre-rename and post-rename eras with no gap. This means the rename-continuity claim is currently unverified at runtime.

**Interview gloss (machine-drafted):** Where a 2010-OEX constituent later changed ticker (Google's Class C split creating GOOG and renaming Class A to GOOGL, Walgreens becoming WBA, WellPoint becoming Anthem then Elevance), the universe uses the modern ticker because yfinance auto-stitches historical data under the surviving symbol. The docstring documents three known renames. The continuity claim is currently asserted but not verified by a test — a spot-check fetch on each ticker's full 2010-2024 range, looking for date-index gaps at the rename event, would close this.

**Fix required for PASS:** add a test (or one-off verification script) that fetches each renamed ticker over its rename event window and asserts no gap > 5 business days at the documented rename date.

---

## §3.4 — Frozen universe (no mid-window additions)

**Check:** Universe is set at Jan 2010 and never updated mid-window. No "add ticker if it joined OEX in 2015" logic.

**Citation:** `universe.py:103-124` (`UNIVERSE_2010` defined as a literal Python `list[str]` with 100 hard-coded ticker strings; no function/method/conditional logic populates it).

**Verdict:** **PASS.**

There is no dynamic universe construction. The module exports a literal list. Nothing in this file changes its contents over time. This satisfies the frozen-universe requirement trivially.

**Interview gloss (machine-drafted, rewrite for defense):** The universe is a hard-coded list of 100 ticker strings representing the Jan 2010 OEX. There is no logic anywhere in this module that mutates that list, and the engine reads from it once at construction time. A ticker that joined the OEX in 2015 cannot enter the backtest universe — which is the whole point of a survivorship-bias-free study.

---

## §3.5 — Ticker count

**Check:** `len(UNIVERSE_2010) == 100`. If fewer after deduping/cleaning, document the shortfall in DESIGN.md.

**Citation:** `universe.py:103-124` (literal list spans 20 lines × 5 tickers per line = 100) + `backtest/tests/test_universe.py:56-59` (`test_exactly_100_tickers` asserts `len(UNIVERSE_2010) == 100`).

**Verdict:** **PASS on the literal count; PARTIAL on the effective tradable count.**

The list contains exactly 100 tickers, deduped (the existing `test_no_duplicates` confirms). All uppercase (`test_all_uppercase` confirms).

However: 7 of those 100 tickers are in `KNOWN_NO_DATA` and are excluded from the engine's active loop. The effective tradable universe is **93 names, not 100**. This is documented in the `KNOWN_NO_DATA` comment but not surfaced in the module docstring or in DESIGN.md. A hostile reviewer reading "Jan 2010 OEX, 100 names held constant" will see 100, run the code, find 93 active, and call the disclosure incomplete.

**Interview gloss (machine-drafted):** The list has exactly 100 tickers — the Jan 2010 S&P 100 constituents. Of those, 7 have no yfinance price data at all over 2010-2024 (`KNOWN_NO_DATA` — APC, KFT, MON, MRO, RTN, UTX, WBA — all delisted via M&A) and are excluded by the engine. The effective tradable universe is 93. The 7 excluded names represent ~7% of the original universe; their exclusion is documented in the module docstring with the named M&A event for each, so it isn't a silent drop, but downstream documentation (DESIGN.md, README) should explicitly cite "100 nominal, 93 active after KNOWN_NO_DATA exclusions."

**Fix required for full PASS:** add a one-line note to `backtest/DESIGN.md` Universe row clarifying the 100-vs-93 distinction.

---

## §3.6 — Source citation (Wikipedia + secondary, with date)

**Check:** Docstring cites the OEX snapshot source AND a secondary source (Wayback Machine OEF holdings, etc.) with date of verification.

**Citation:** `universe.py:11-20` (docstring "Methodology" section).

**Verdict:** **FAIL — sources are named but the docstring openly admits they were not actually accessed.**

The docstring states:
> "Primary source consulted: Wikipedia 'S&P 100' article + CBOE historical OEX constituent lists. *Note:* all Wikipedia and CBOE URLs returned HTTP 403 from the routine's cloud execution environment. The list was reconstructed from training-data knowledge of the index composition circa January 2010, cross-checked against market-cap estimates and known index-event dates."

What this means in plain English: the named sources weren't accessed (HTTP 403 in the routine's environment). The list was reconstructed from the routine's (an LLM's) training-data memory, then "cross-checked" against more LLM training-data memory (market-cap estimates and event dates). There is no point-in-time external source citation that an interviewer can independently verify.

This is the canonical failure mode the audit gate exists to catch. The docstring *sounds* authoritative but the verification chain is circular: LLM → LLM → claim.

Under a Citadel-style interview question — *"How do you know your Jan 2010 universe is correct? What was your primary source?"* — the only honest answer right now is: *"An LLM reconstructed the list from training data."* That answer kills the project's credibility because it implies the rest of the methodology might be similarly unverified.

**Interview gloss (machine-drafted):** The Jan 2010 OEX constituent list as published in this module is an LLM-reconstructed list cross-checked against LLM training data, not a point-in-time source artifact. The two named sources (Wikipedia + CBOE) returned HTTP 403 from the routine's cloud environment and were not consulted. Until the list is verified against a real archived OEX snapshot (Wayback Machine of iShares OEF holdings from Jan-Feb 2010 is the standard route), the universe is "plausible reconstruction" not "verified snapshot." This is interview-fatal as currently documented and needs to be either fixed (real verification) or honestly disclosed in README ("LLM-reconstructed, known limitation, verified against [X] random tickers via market-cap spot-checks").

**Fix required for PASS — high priority:** access an archived OEX snapshot via Wayback Machine (https://web.archive.org/web/2010*/oef OR direct CBOE archive search), verify ≥10 sampled tickers from `UNIVERSE_2010` against the archive, document the source URL + access date in `universe.py` docstring, and remove the "training-data knowledge" language. If genuine verification is impossible, the README disclosure must be updated to say "LLM-reconstructed universe" honestly so an interviewer asking about sources gets the truth, not the current implied claim.

---

## Adversarial test added (per A.3 TODO entry)

**Pinned in `backtest/TODO.md` A.3 row:** *"assert that a name known to have delisted mid-window (pick one from the documented set) produces a recorded position trace through its delisting date — not silently absent."*

**Plan:** add a test method to `backtest/tests/test_universe.py::TestFetchability` that:
1. Picks AET (Aetna, acquired by CVS ~Nov 2018) from the partial-history table.
2. Calls `fetch_bars(['AET'], date(2010,1,1), date(2024,12,31))` against the real cached parquet (NOT a mock).
3. Asserts the returned DataFrame is non-empty.
4. Asserts the latest bar date is ≤ 2019-01-01 (handful of months grace after the documented Nov 2018 event) AND ≥ 2018-09-01.

If the latest bar is within that window, the engine has a real position trace through AET's delisting and the survivorship handling is consistent with the docstring claim. If the latest bar is earlier (e.g., 2015) or absent entirely, that's a FAIL — AET would belong in `KNOWN_NO_DATA` (it isn't currently).

The test will be added as part of the audit completion step in a follow-up edit. NOT added in this audit-write so the test code lives in its own reviewable commit.

---

## Summary

| Check | Verdict | Action |
|---|---|---|
| §3.1 KNOWN_NO_DATA rationale | **FAIL** | EMC ticker re-use is a silent data-integrity bug; add EMC to KNOWN_NO_DATA; fix WBA + MRO docstring staleness |
| §3.2 Delisted-name handling | PARTIAL | Document choice (c) explicitly in DESIGN.md OR ship corporate-actions handler |
| §3.3 Rename continuity | UNCERTAIN | Add spot-check test on GOOGL/WBA/ELV rename windows (WBA already proven empty above) |
| §3.4 Frozen universe | PASS | — |
| §3.5 Ticker count | PARTIAL | Note 100-nominal vs 93-active (becomes 92-active after EMC fix) in DESIGN.md |
| §3.6 Source citation | **FAIL** | **Verify universe against real archived OEX snapshot OR honestly disclose LLM-reconstruction.** Interview-fatal as currently documented. |

**Overall A.3 verdict: GATE NOT CLEARED — TWO FAILs, both material.** §3.1 (EMC ticker re-use) is a silent data-integrity bug; §3.6 (LLM-reconstructed universe with no verifiable source) is interview-fatal.

**The most important fix:** §3.6. Until the universe is verified against a real archived source, the rest of the backtester's "interview-defensibility" framing collapses on this one question.

**Next actions in order:**
1. [Laith] Verify ≥10 UNIVERSE_2010 tickers against Wayback Machine OEF holdings circa Jan-Feb 2010. Document source URL + date.
2. [Either] Run `fetch_bars(['WBA','MRO'], ...)` to resolve the WBA/MRO documentation contradictions.
3. [Routine OK] Update DESIGN.md Universe row with "100 nominal, 93 active" clarification.
4. [Routine OK] Add the AET adversarial test described above.
5. [Optional, deferred] Ship a corporate-actions handler for acquired names if you want full §3.2 PASS.
