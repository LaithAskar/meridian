# Hostile-Review Checklist — Meridian Backtester

**Purpose:** scan routine-produced code for the bug classes that pass syntactic tests but break interview defensibility. Run this against every `[routine]` commit touching `engine.py`, `fills.py`, `metrics.py`, `universe.py`, or `data.py` before allowing dependent Phase 2/3 work to proceed.

**How to use:** read the named file with one section of this checklist open. For each numbered check, either (a) cite the file:line that satisfies it, or (b) write a `FAIL` finding to `journal/audit-{module}.md` and reopen the relevant TODO item.

The bias you are fighting: optimism toward routine-written code that ran and passed tests. Tests passing means the code does what the test asserted. It does NOT mean the code is correct. Most of these checks are NOT covered by routine-written tests.

---

## §1 — `engine.py` (lookahead leakage)

1. **Bar visibility at `on_bar(ts, bars, portfolio)`:** does `bars` only contain data with index `<= ts`? Not `<= ts + 1`? Not the full DataFrame sliced after the fact? Cite the slicing line.
2. **Fill timing:** does the engine generate orders at `ts`, then execute them at `ts+1`'s open? Or does it execute at `ts`'s close (lookahead) or `ts`'s open (also lookahead, since `ts`'s open is in `bars[ts]` and visible to `on_bar`)?
3. **Portfolio mark-to-market timing:** when equity is recorded at `ts`, is it marked using `ts`'s close (acceptable, end-of-bar valuation) or using `ts+1`'s open (lookahead — but possibly correct if you're modelling "after the next-day fill")? Be explicit about which and why.
4. **Order persistence:** if an order is submitted at `ts` but `ts+1` has no bar (delisting, holiday), is it cancelled or carried forward? Carried-forward orders that fill on `ts+2` are NOT necessarily wrong, but must be deliberate.
5. **Position-level data access:** when computing per-position equity, are you using the *position's* symbol's bar at `ts`, or are you accidentally pulling current-day bars for ALL symbols (subtle, only matters if `bars` is a DataFrame view vs. a copy).
6. **Index-not-time bug:** if any iteration uses `df.iloc[i]` then `df.iloc[i+1]`, confirm the underlying DataFrame is sorted by date ascending AND has no duplicate timestamps.

## §2 — `fills.py` (slippage and fill semantics)

1. **Slippage direction:** buy at `open * (1 + 5e-4)`, sell at `open * (1 - 5e-4)`. Confirm BOTH signs and that they hurt the trader, not help.
2. **Slippage on liquidation:** when a position is closed, is slippage applied to the close-side fill? Sometimes routines apply it only on entry.
3. **Missing-next-bar handling:** if `next_bar` is `None` (delisting, suspended, missing data), is the order cancelled, OR is there a `try/except` that silently swallows it and returns a Fill with `None` price? Trace the code path.
4. **Same-bar leakage:** confirm `fill_order(order, next_bar)` cannot be called with the SAME bar `order` was generated from. Search for callers and verify.
5. **Fractional shares:** does the fill model round to whole shares? If it allows fractional, is that documented in DESIGN.md? (Live bot supported fractional via robin_stocks but backtest semantics may differ.)
6. **Quantity sign:** `qty` for sells is negative or positive? Confirm consistent convention and that portfolio accounting matches.

## §3 — `universe.py` (survivorship bias)

1. **`KNOWN_NO_DATA` rationale:** is each ticker in this set documented with a reason in the module docstring or inline? "Couldn't fetch" is not a reason — name the event (delisting date, acquirer, bankruptcy).
2. **Delisted name handling:** for tickers in `UNIVERSE_2010` that delisted DURING the window, how does the engine handle the post-event period? Three acceptable patterns: (a) recorded at acquisition price then ticker removed from active universe, (b) recorded at -100% if bankruptcy, (c) NaN'd out with a documented assumption. Silently dropping rows is survivorship bias and is NOT acceptable.
3. **Renamed tickers:** for FB→META, PCLN→BKNG, etc., does the universe use the modern ticker AND does yfinance return continuous history under that ticker (yfinance auto-stitches some renames but not all)? Spot-check one rename by fetching the full range and checking for gaps at the rename date.
4. **Frozen universe:** confirm the universe is set at Jan 2010 and NEVER updated mid-window. No "add ticker if it joined OEX in 2015" logic should exist.
5. **Ticker count:** `len(UNIVERSE_2010) == 100`. If the cleaned list is fewer than 100 after removing duplicates or untradeable names, document the shortfall in DESIGN.md.
6. **Source citation:** docstring cites Wikipedia OEX snapshot AND a secondary source (Wayback Machine OEF holdings page, etc.) with date of verification.

## §4 — `metrics.py` (annualization, drawdown, NaN propagation)

1. **Sharpe annualization factor:** `sqrt(252)` for daily, NOT `sqrt(252*6.5)` (that's hourly). This is the canonical bug that already surfaced once during spec revisions. Greppable check: search for `252` and confirm no `* 6.5` anywhere.
2. **Sharpe denominator:** uses `std(returns)` with `ddof=1` (sample std) or `ddof=0` (population)? Quant convention is `ddof=1`. Document either way.
3. **Zero-variance returns:** `sharpe(returns=[0,0,0])` — does this divide by zero and crash, return `nan`, or return `0`? All three are defensible but be explicit.
4. **Max drawdown direction:** for an equity curve, `max_drawdown` should be the LARGEST peak-to-trough decline, expressed as a negative number or absolute positive. Confirm sign convention. Confirm it uses a *running* maximum (`equity.cummax()`), not the full-series maximum (which would be lookahead).
5. **Hit rate calculation:** `wins / total_trades` — does `wins` include exact-zero PnL trades or exclude them? Are commissions/slippage already netted out? (They should be — fills already include slippage.)
6. **CAGR formula:** `(final/initial)^(1/years) - 1`. Confirm `years` is computed from actual bar timestamps, not `len(equity) / 252` (the latter assumes no holiday gaps).
7. **Sharpe SE formula:** `sqrt((1 + sharpe^2 / 2) / n)` per Lo (2002). Confirm the formula, AND confirm `n` is number of return observations, not number of trades.
8. **Per-signal-source metrics:** when reporting metrics per signal source, are the same metric functions applied identically? Or does each signal source have a copy-pasted-and-drifted version? Diff them.

## §5 — `data.py` (point-in-time integrity)

1. **`auto_adjust=True` application:** yfinance with `auto_adjust=True` already adjusts for splits/dividends. Confirm NO downstream code re-applies adjustment (multiplying by a split factor again, etc.).
2. **Cache invalidation:** if `fetch_bars(['AAPL'], 2020, 2024)` is cached, then later `fetch_bars(['AAPL'], 2010, 2024)` is called, does the cache serve the partial range (wrong) or re-fetch the full range (correct)?
3. **MultiIndex ordering:** the returned DataFrame is MultiIndex (symbol, date) — confirm date is the inner level and is sorted ascending. Downstream `engine.py` likely assumes this.
4. **NaN in OHLC:** tests assert no NaN in OHLC for the cached output. But what about gaps from delisting mid-window? Are those rows present-with-NaN or absent-entirely? Either is defensible but engine.py and universe.py logic must match the choice.
5. **Rate-limit retry behavior:** if yfinance returns the "rate limited" string, the retry-once logic — does it retry the ENTIRE call or just the failed symbol? Look for partial-failure handling.
6. **Timezone:** are date indices tz-naive or tz-aware? US market open at 09:30 ET vs. UTC matters less for daily bars but should be consistent. Spot-check.

## §6 — Existing test shallowness

1. **Pinned values vs. shape-only:** count tests that assert `result is not None` or `len(result) > 0` versus tests that pin known numeric values. Shape-only tests catch nothing.
2. **Edge cases covered:** for each module, does the test file cover (a) empty input, (b) single-element input, (c) all-NaN input, (d) negative input where positive expected? Routine-written tests typically miss these.
3. **Adversarial cases:** is there a test that asserts a KNOWN WRONG output would fail? E.g., a test that hand-computes Sharpe for a 3-element synthetic series and asserts the metric matches to 6 decimal places.
4. **Mocked vs real:** `test_data.py` mocks `yf.download`. Is there at least one integration test (possibly marked `slow`) that hits the real yfinance API to confirm the mock contract matches reality?
5. **Test coverage of lookahead:** is there a test in `test_engine.py` that DELIBERATELY tries to use future bars (via a malicious `Strategy` subclass) and asserts the engine prevents it or that the resulting backtest gives an obviously-wrong result? Without this, lookahead protection is unverified.

---

## Audit completion criteria

A module passes audit when:
- Every numbered check in its section has a citation OR a documented `FAIL` finding with a fix
- All `FAIL` findings are either fixed (reopened TODO item, routine re-shipped, re-audited) or accepted with explicit rationale in `journal/audit-{module}.md`
- Audit finding file exists and is committed

Until all six sections pass, the audit gate in TODO.md remains in effect and the routine cannot proceed past Phase 1.

## Interview-defense use

This checklist doubles as your interview prep. If you can speak to each numbered item without consulting the file — what choice was made, why, and what the alternatives would have implied — the project is interview-defensible. If you can't, you don't yet own the code.
