# A.3 survivorship-integrity audit support (not an audit verdict)

**Prepared for:** human-led review of `backtest/universe.py` against `backtest/REVIEW_CHECKLIST.md` §3  
**Evidence boundary:** repository-tracked sources only; no web or memory-derived citation is treated as proof.  
**Status:** support material only. This file does **not** clear A.3, rewrite the required human interview glosses, or change any TODO/audit status.

## Locked requirements consulted

- `backtest/REVIEW_CHECKLIST.md:29-36` defines the six cite-or-FAIL checks.
- `backtest/REVIEW_CHECKLIST.md:68-75` reserves completion for a committed finding file with every finding resolved or explicitly accepted.
- `backtest/TODO.md:31-43` locks A.3 first, requires cite-or-FAIL + human interview gloss + an adversarial test, and keeps A.3 `[audit-required]`.
- `backtest/DESIGN.md:44-48,74-80` claims a frozen Jan-2010 OEX universe and acquisition-price / bankruptcy-loss treatment.

## Cite-or-FAIL evidence matrix for the human reviewer

This matrix deliberately supplies evidence and blockers rather than final PASS/FAIL certification.

### §3.1 — `KNOWN_NO_DATA` rationale

**Candidate repository citations**

- `backtest/universe.py:55-74` names events for APC, EMC, KFT, MON, MRO, RTN, UTX, and other partial-history names.
- `backtest/universe.py:40-44` names the WAG→WBA event and records the unavailable WBA feed.
- `backtest/universe.py:129-146` defines the eight-name `KNOWN_NO_DATA` set and documents the EMC ticker-reuse concern.

**Human checks still needed**

- Decide whether approximate event dates (`~Aug 2019`, `~Sep 2016`, etc.) satisfy the checklist's required rationale.
- The event statements are internal documentation, not independent citations to historical corporate-action sources.

### §3.2 — Delisted-name handling

**Repository evidence exposing an unresolved mismatch**

- The locked design says acquired names are recorded at acquisition price and bankruptcies at -100%: `backtest/DESIGN.md:47,78`.
- The universe docstring instead says bars end and the engine treats the symbol as "no position": `backtest/universe.py:49-53`.
- The engine only marks a held position when that symbol has a current bar: `backtest/engine.py:136-160`.
- When the current price is absent, `Portfolio.equity` values the still-held position at **average cost**, not at its last bar, acquisition proceeds, or -100%: `backtest/strategy.py:62-75`.
- Eight names are removed from runner input entirely by `tradable_universe()`: `backtest/universe.py:146-162`; default runners use that helper (`backtest/run_quant.py`, `backtest/run_vader.py`, and `backtest/run_finbert.py`).

**Blocker for human disposition**

The implementation does not demonstrate any of the locked acquisition-price / bankruptcy treatments. For an already-open position whose bars end, the observable code path retains the position and falls back to cost basis. The human reviewer must decide whether to (a) reopen implementation work, (b) change the locked disclosure/assumption, or (c) supply corporate-action evidence and handling. This support work does not choose among them.

### §3.3 — Renamed tickers

**Candidate repository citations**

- `backtest/universe.py:29-47` documents GOOGL, WBA, and ELV mappings and asserts continuity for GOOGL/ELV.
- `backtest/tests/test_universe.py:93-96` checks only GOOGL membership, not historical continuity.

**Missing evidence / blocker**

No repo-tracked source establishes a point-in-time rename event or proves continuous yfinance history across a rename boundary. The existing machine-drafted audit also labels this uncertain at `backtest/journal/audit-universe.md:92-106`. A live fetch would not satisfy this packet's repo-tracked-source boundary unless its verified output were intentionally reviewed and added as an audit artifact.

### §3.4 — Frozen universe

**Candidate repository citations**

- `backtest/universe.py:106-127` is a literal 100-symbol list.
- `backtest/universe.py:149-162` applies a deterministic, date-independent exclusion set.
- `backtest/tests/test_universe.py:63-121` checks count, uppercase symbols, duplicates, historical-era exclusions, and required historical-era members.

**Human check still needed**

Repository search should be reviewed for any runner that bypasses `tradable_universe()` or dynamically changes membership. The price and news download utilities intentionally use the nominal list, while the default strategy runners use the effective list.

### §3.5 — Ticker count

**Candidate repository citations**

- `backtest/tests/test_universe.py:64-67` pins the nominal list to 100.
- `backtest/universe.py:146-162` removes eight `KNOWN_NO_DATA` symbols, yielding an effective runner universe of 92.
- `backtest/TODO.md:158` itself describes a rerun with `universe=92`.

**Missing disclosure / blocker**

`backtest/DESIGN.md:47` and its disclosure at line 78 still describe 100 names held constant without disclosing the 92-name effective runner universe. The checklist explicitly requires a cleaned-list shortfall to be documented in DESIGN (`backtest/REVIEW_CHECKLIST.md:35`). No DESIGN change is made here because the human reviewer must decide whether exclusion is acceptable or implementation should preserve all nominal members via corporate actions.

### §3.6 — Source citation

**Repository evidence of a cite failure**

- `backtest/universe.py:11-20` names Wikipedia and CBOE but explicitly says they returned HTTP 403 and that the list was reconstructed from training-data knowledge.
- `backtest/TODO.md:75-91` required Wikipedia plus a Wayback/secondary cross-check and a verification date.
- No repo-tracked Jan/Feb-2010 OEX snapshot, archived holdings file, exact historical source URL, or constituent reconciliation is present.

**Blocker**

There is no citeable repository-tracked proof for the Jan-2010 membership list. This must remain an explicit blocker until a human verifies and records suitable point-in-time primary and secondary sources. The named-but-unread sources are not citations.

## Adversarial regression support

Added two linked tests under `TestTrackedDelistingEvidence` in `backtest/tests/test_universe.py`. They load the repository-tracked AET and SPY parquet files, adapt those files to the production engine's `(symbol, date)` input, and run an actual buy-and-hold AET position through the full 2010-2024 engine clock. `fetch_bars` is replaced only at the I/O boundary so the test is deterministic and cannot refresh the delisted ticker from the network; the production `Engine`, fill path, `Portfolio`, and equity snapshot path remain exercised.

The green evidence test, `test_aet_has_continuous_position_trace_through_delisting`, asserts:

1. AET remains in nominal `UNIVERSE_2010` and is not hidden in `KNOWN_NO_DATA`.
2. Its first observation is near the backtest start (2010-01-04), it has at least 2,200 observations, each complete 2010-2017 year has at least 240 bars, and duplicate/OHLC-NaN checks are clean.
3. Its last observation is in the documented 2018 acquisition window (2018-11-29).
4. A real 10-share AET position exists on the final AET bar, on the first subsequent SPY-only engine day, and at 2018-12-31 even though AET has no current bar.
5. On the first missing-price day, the engine keeps `num_positions == 1` and equity equals cash plus AET quantity times **average cost**. This is an explicit regression observation of the current fallback, not approval of it.

The companion test, `test_aet_post_delisting_value_matches_locked_acquisition_treatment`, is marked `xfail(strict=True)`. It states the locked DESIGN expectation by comparing post-final-bar equity with the final tracked acquisition-window value and currently fails because the engine uses average cost instead. Strict mode makes an unexplained future pass fail the suite as XPASS, forcing review rather than silently converting this evidence into certification.

The AET artifact is tracked by git and, at preparation time, had SHA-256 `e9c37cd3e1ab7552fb0cd3e374087988bcf04414ceaea9a6f661a0589a53b5e3`. A direct read measured 2,244 rows from 2010-01-04 through 2018-11-29, with zero duplicate dates and zero OHLC NaN cells. SPY supplies a tracked engine clock through 2024-12-31 after AET disappears.

## Explicit assumptions and open human decisions

1. **Source-of-truth membership:** obtain and review an actual Jan-2010 OEX snapshot plus a secondary point-in-time source; reconcile all 100 names, not only a sample.
2. **Eight unavailable names:** decide whether excluding them (92 active) is acceptable, or whether corporate-action / alternate historical data must keep them economically represented.
3. **Held position after final bar (decision required before removing strict xfail):** verify and add a reviewed corporate-action payout/date fixture for AET, then choose whether the engine must liquidate at those acquisition proceeds; alternatively explicitly amend the locked DESIGN/README assumption to a documented NaN/last-value rule. The present average-cost fallback is neither the locked acquisition-price treatment nor an acceptable silent default. The final tracked adjusted close (`212.70` on 2018-11-29) is used only to make the desired-path test fail deterministically and must not be certified as acquisition proceeds without human source verification.
4. **Rename continuity:** provide tracked verification for GOOGL and ELV across documented rename dates; WBA is already excluded for unavailable data.
5. **Disclosure alignment:** if 92 active names and cost-basis fallback are accepted, reconcile DESIGN/README claims before any results are represented as survivorship-bias-free.
6. **Human interview glosses:** Laith must write the required 2-3 sentence gloss per check in his own voice; none are supplied or certified here.

## Non-certification statement

A.3 audit clearance is **NOT claimed**. `backtest/TODO.md` remains unchanged and A.3 remains `[audit-required]`. This packet preserves the missing source chain, effective-universe shortfall, rename-continuity gap, and post-delisting valuation mismatch as unresolved human-led audit decisions.
