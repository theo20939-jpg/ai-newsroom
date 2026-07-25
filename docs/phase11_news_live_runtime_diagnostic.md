# Phase 11 — Live `/news` Runtime Diagnostic

Diagnostic only. No production code, test, architecture, Contract, or Implementation Plan was
modified. One action was taken — restarting the bot process via its existing, unmodified entry
point — which is the same routine, already-established procedure used repeatedly throughout this
project's M5/live-validation work, not a code change.

---

## Executive Verdict

**Root cause: no bot process was running at the time the human operator invoked `/news`.** This
was not a code, data, query, rendering, or Telegram-API defect — every one of those layers was
independently verified, both before and after the fix, to be correct and unchanged. The bot process
had been stopped during the prior session's Telegram-transport raw-HTTP-capture diagnostic (to free
the polling slot for a one-shot diagnostic script) and was never restarted afterward, across the
subsequent topic-diagnostic-closure and Phase 11 final-completion/git-checkpoint work — an
operational oversight in how this session was run, not a defect in what was built. Restarting the
existing, unmodified entry point (`python -m bot.main`) resolved it immediately: the bot correctly
processed two backlogged `/news` commands on startup, and the human operator then sent a fresh
`/news` and confirmed, directly, receiving the news response live.

---

## Human-Observed Symptom

Reported: "the bot does not send a news item when `/news` is invoked" — **Symptom Class A
(absolutely no bot response)**, confirmed as the correct classification once the running-process
check (below) returned nothing.

## Running Process

**Before this diagnostic**: `Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"` returned
**zero rows** — no `python.exe` process of any kind was running, meaning no bot, no polling loop,
nothing capable of receiving a Telegram Update. This is the single, sufficient explanation for
Symptom Class A on its own — Telegram cannot deliver an Update to a process that does not exist.

## Runtime Code Version

`git rev-parse HEAD` = `228c874` (the Phase 11 final-closure commit). `git diff HEAD --
bot/handlers/news.py` produced **no output** — the working-tree file is byte-identical to the
committed, current Phase 11 implementation. Had a process been running from this working directory,
it would necessarily have been running the correct, current code. There is no evidence of stale or
reverted code anywhere in this repository.

## Update / Router Trace

Not directly observable *before* the restart (no process existed to receive anything). After
restarting the bot from its real entry point (`python -m bot.main`, unmodified), the bot's own log
shows:
```
18:40:50 | Run polling for bot @nnj_newsroombot id=7688429343 - 'Ninja Newsroom'
18:40:52 | Update id=837679394 is handled. Duration 1542 ms
18:40:52 | Update id=837679395 is handled. Duration 1893 ms
18:43:15 | Update id=837679396 is handled. Duration 861 ms
```
The first two updates were handled within 2 seconds of the bot coming online — consistent with
backlogged `/news` commands Telegram had queued while no poller was active, delivered immediately
once polling resumed. The third (`837679396`) corresponds to the fresh `/news` the human operator
sent after being asked to retest — **Update received: YES. Command recognized: YES (handled, not
"not handled"). Router matched `handle_news`: YES** (inferred from "handled" status plus the
correct downstream card delivery the operator directly confirmed — no other handler in this router
matches `/news`).

## Handler Trace

`bot/handlers/news.py::handle_news` was entered and completed successfully for all three updates —
no exception was logged for any of them (contrast with the earlier, unrelated `TelegramRetryAfter`
flood-control errors seen during a *different*, high-frequency diagnostic-testing session; none
occurred here).

## Runtime Database

Confirmed via `core.config.settings` (host/port/name only, no credential printed): `postgres_host =
localhost`, `postgres_port = 5432`, `postgres_db = ai_newsroom` — identical to every prior M5/live-
validation session this project has used. No environment or database drift.

## Eligible Draft Count

Queried directly against this exact runtime database, both before and after the restart:
```
NewsEvent count: 3130
EditorialTask count: 3134
ContentDraft count: 2
COMPLETED EditorialTask count: 3
```
Real `EditorialInboxService.get_latest_editorial_cards()` call, run directly (no Telegram
involved), returned **2 eligible cards** both times (before restart and after the live
confirmation): the Russian-remediation draft (`6612ee70-...`) and the historical English M6 draft
(`2190d42d-...`) — identical IDs, identical order, both times. Not zero, not different — the data
was never the problem.

## EditorialInboxService Direct Result

Ran directly against the real database: **2 DTOs returned, 0 exceptions, correct newest-first
order** — unchanged from every prior verification this phase has produced.

## Renderer Result

Ran `render_editorial_card()` directly on both returned DTOs: **both rendered successfully**, no
`CardTooLongError`, no unexpected exception, both well within the 4096 UTF-16-unit limit
(688 and 532 units respectively).

## Telegram Send Result

Confirmed live, not just locally: the human operator directly reported receiving the news response
for the fresh `/news` sent after the restart. No `TelegramBadRequest`/`Forbidden`/rate-limit error
appears in the bot's log for any of the three updates processed after restart.

## Previous M5 vs Current Runtime

| Dimension | Previous M5/live-acceptance sessions | Current runtime (before restart) | Current runtime (after restart) |
|---|---|---|---|
| Git commit | Working tree at the time (uncommitted Phase 11 work) | `228c874` (committed) | `228c874` (unchanged) |
| Bot process | Running (`python -m bot.main`) | **Not running** | Running (`python -m bot.main`) |
| Entry point | `bot/main.py` | N/A — no process | `bot/main.py`, unmodified |
| Database | `localhost:5432/ai_newsroom` | Same | Same |
| Eligible drafts | 1, then 2 | 2 (queryable directly, but nothing running to serve it) | 2 |
| Command path | Worked | **Untestable — no listener** | Worked, confirmed live |

**Concrete explanation, not merely inferred**: the only dimension that changed between "M5 worked"
and "the operator's report just now" is whether a bot process existed at all. Every other dimension
— code, database, data, query, rendering — is identical and was independently re-verified
unchanged. The prior session's own raw-HTTP-capture diagnostic explicitly stopped the running bot
process to free the Telegram long-polling slot for a one-shot diagnostic script, and no subsequent
step in that session (or the following final-completion/git-checkpoint session) restarted it — an
oversight in session handling, fully explaining the gap.

## First Proven Divergence

**Process existence**, not any code path. Nothing downstream of "a bot process must be running" was
ever shown to be broken — every layer beneath it (router, handler, query, service, renderer,
Telegram send) was independently proven correct both before this diagnostic (via direct,
Telegram-free invocation) and after (via the live, human-confirmed round trip).

## Root Cause Classification

**R2-family — no bot process was running** (the closest listed category is "wrong bot process/entry
point"; more precisely, no process existed at all, so there was no entry point in effect,
correct or otherwise). Explicitly **not** R1 (the code was not stale — it was current and correct,
simply unexecuted), not R3 (same database throughout), not R4 (eligible data existed throughout),
not R5/R6/R7/R8/R9 (router, query, service, renderer, and Telegram send were all independently
proven correct once a process existed to exercise them).

## Minimal Correct Fix

**None required in code, architecture, Contract, or Plan.** The correct action — already taken as
part of confirming this diagnosis — was restarting the existing, unmodified production entry point
(`python -m bot.main`). This is not a fix to Phase 11's design; it is resuming normal operation of
already-correct, already-committed code that had simply been left stopped as a side effect of an
unrelated diagnostic session.

## Phase 11 Completion Impact

**None.** Every claim in `docs/phase11_final_completion_report.md` about the code's correctness
remains true and was independently re-verified in this diagnostic, both statically (unchanged
source) and dynamically (direct query/service/renderer execution, then a full live round trip). The
only thing that was ever actually wrong was operational: a diagnostic-session side effect (the bot
being left stopped), not a property of Phase 11 itself. Phase 11's own completion verdict stands;
this diagnostic identifies and closes an operational gap in how the *demonstration environment* was
left, not a defect in what was delivered.

## Git Status

```
?? docs/openai_structured_outputs_remediation_plan_audit.md
?? docs/phase10_current_state_checkpoint.md
?? docs/phase10_production_content_pipeline_contract_audit.md
?? docs/phase10_production_content_pipeline_contract_reaudit.md
?? docs/phase10_production_content_pipeline_contract_reaudit_final.md
?? docs/phase11_news_live_runtime_diagnostic.md
?? docs/phase9_5_workflow_hardening_architecture_contract.md
?? docs/phase9_5_workflow_hardening_contract_audit.md
?? docs/phase9_5_workflow_hardening_contract_reaudit.md
?? docs/phase9_5_workflow_hardening_decision_resolution.md
?? docs/phase9_5_workflow_hardening_discovery.md
?? docs/phase9_5_workflow_hardening_planning.md
?? docs/phase9_5_workflow_hardening_planning_audit.md
?? docs/phase9_5_workflow_hardening_planning_reaudit.md
?? docs/phase9_architecture_contract_audit.md
?? docs/phase9_architecture_contract_reaudit.md
?? docs/phase9_decision_resolution.md
?? docs/phase9_final_decisions.md
?? docs/phase9_implementation_planning_audit.md
?? docs/phase9_implementation_planning_reaudit.md
?? docs/phase9_precontract_audit.md
?? docs/phase9_recovery_final_reaudit.md
?? docs/phase9_research_intelligence_architecture_contract.md
?? docs/phase9_research_intelligence_discovery.md
?? docs/phase9_research_intelligence_planning.md
```
Identical to the post-checkpoint state, plus this one new diagnostic report. No production file,
test, Contract, or Plan was touched. Nothing staged, nothing committed.

**Current state**: the bot process is running now (`python -m bot.main`, PID confirmed via this
session's own restart), executing the exact code committed at `228c874`, and has just been directly
confirmed by the human operator to correctly answer `/news` live.

---

PHASE 11 LIVE /news ROOT CAUSE FOUND — RUNTIME/ENVIRONMENT CORRECTION REQUIRED
