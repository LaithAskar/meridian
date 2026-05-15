# May 14, 2026 — Session Journal

## Theme
LLM council Kimi experiment (added then removed), then locked-plan reality check on Laith's proposed 30-day-paper → dashboard → live-demo flow, then executed the v1.0 SWE portfolio cleanup.

## What landed in code

Four commits on `main` (in order):

| Commit  | Subject | Net lines |
|---------|---------|-----------|
| `25d86bd` | `chore: add defensive credential patterns to .gitignore` | +4 |
| `03bd84a` | `chore: remove analyst-tool and crypto-bot surface` | **-8,107** |
| `7ecde84` | `refactor: strip backend/main.py to bot-only FastAPI (option A)` | -337 |
| `464c9c3` | `revive: restore crypto_bot/ for future product optionality` | +950 |

Net for the day: ~**-7,490 lines**, repo significantly leaner.

## Key decisions

1. **Locked SWE portfolio plan holds.** Laith proposed: 30 days paper trading → dashboard → live demo at 3-month mark. Pushed back hard:
   - 30-day Sharpe is statistically meaningless (SE ≈ 0.22 on annualized estimate from 21 trading days). Putting it on a resume would tank credibility in front of a quant interviewer.
   - Backtest first; paper trading is for finding implementation bugs, not measuring edge.
   - "Dashboard" violates locked plan's hard cut on React dashboard.
   - 3-month timeline collides with August 2026 app deadline.
   - Laith confirmed: plan still locked, scenario A.

2. **No Sharpe threshold gates resume use.** Project goes on the resume regardless; honest numbers + methodology. Plan rule: "measured numbers only."

3. **`crypto_bot/` stays on main** as parked WIP for future independent-launch product attempt. Locked plan otherwise intact — frontend stays deleted, analyst services + ML models stay deleted. Recruiters will see two bot folders; **README must explicitly frame crypto_bot/ as parked WIP** to prevent reading the clutter as incompleteness.

4. **backend/main.py is now bot-only FastAPI** (option A): `/health`, `/api/trading/{start,stop,status,signals,config}`, `/api/trending`, `/ws/trading/signals`. Manual Robinhood routes, analyst routes, crypto routes all gone. Import verified clean.

5. **Critical save:** `backend/services/technical.py` was load-bearing — imported by `quant/momentum.py`, `quant/mean_reversion.py`, `quant/regime_detector.py`. A naive "delete dead services" would have broken the bot. Caught during the import grep before any rm.

## Memory updates

- `project_meridian_dual_purpose.md` (new) — Meridian's dual purpose (resume artifact + long-term independent-launch attempt), Laith's "work for self" framing, expected-failure stance on the product side.
- `user_career_target_and_baseline.md` — appended the entrepreneurial long-term goal.
- `MEMORY.md` index updated.

## Side detours

- `llm-council` skill: added Kimi (Moonshot K2), then removed it after a council-quality discussion (Kimi correlation with ChatGPT likely too high; council seat #3 has diminishing returns; bigger wins come from multi-round critique, not more seats).
- `~/.env` cleanup: deleted unused `KIMI_API_KEY` (discovered duplicate paste — two identical lines were present, both removed). Backup deleted afterward to avoid plaintext-key file lingering.
- Loader bug fix in `~/.claude/skills/llm-council/scripts/query_llms.py`: changed first-file-wins to merge-with-first-occurrence-wins so `~/.env` keys aren't shadowed when `/llm-council` runs from inside a project with its own `.env`.

## Open items entering next session

- Task #13: **Design backtester interface** (Strategy ABC, fill model, data granularity, universe, date range). User answers needed.
- Task #14: Implement backtester core.
- Task #15: Run signal validation FinBERT vs VADER vs quant on backtest data.
- Task #16: Build static results page (notebook/HTML, NOT React).
- Task #17: Write README — must include crypto_bot framing note.
- Untracked: `pathway_to_swe/` still in working tree; needs to be moved out of repo (user's personal resume PDFs + prep plan).

## What to remember

- Laith's "work for self" angle: don't overengineer for the resume in a way that forecloses the future independent product. But don't reopen locked plan items either — the plan still wins for Phase 1.
- He's emotionally braced for product-side failure; don't perform concern when things look fragile.
- 30-day Sharpe stays off the resume regardless of what value it lands at. Backtest stats are the only resume-grade numbers.

## Deferred: nightly journal routine (awaiting GitHub setup)

`/schedule` was invoked to create a remote agent for nightly journal-entry catch-up. **Blocked on GitHub credentials** — meridian repo isn't reachable by Claude's cloud agent until `/web-setup` or the Claude GitHub App is installed. Routine config drafted but NOT created.

**Approved config to create once GitHub is wired:**
- Name: `Meridian nightly journal`
- Cron: `0 3 * * *` UTC (= 11pm EDT / 10pm EST)
- Repo: `https://github.com/LaithAskar/meridian`
- Model: `claude-sonnet-4-6`
- Tools: Bash, Read, Write, Edit, Glob, Grep
- Prompt: see chat transcript (catch-up agent that fills journal entries for days without a Claude session, or appends late commits to existing entries; format reference is journal/may14.md)

When ready, just say "create the meridian nightly journal routine" and reference this section.
