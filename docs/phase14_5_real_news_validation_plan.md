# Phase 14.5 — Real News End-to-End Validation Plan

## Objective

Validate that AI Newsroom can process **one real, actually-collected news item** (not
synthetic, not test data) through `NEWS_ANALYSIS` → `CONTENT_GENERATION` → Telegram delivery,
end-to-end, for real. This is **not** a new feature phase — no architecture change, no new
capability, no new table, no workflow-contract change, no autonomous mode.

## What is already proven vs. not yet proven

| Proven already | Not yet proven |
|---|---|
| Collector infra, NewsEvent persistence, Triage (Phase 12/13) | The full chain starting from a **real, collected** event |
| `NEWS_ANALYSIS` workflow, live (Phase 13 M7 — synthetic event) | `NEWS_ANALYSIS` against **real** article content |
| `CONTENT_GENERATION` workflow, live (Phase 14 M6 — pre-seeded state) | `CONTENT_GENERATION` re-deriving research/intelligence from a **real** NewsEvent |
| Telegram delivery to verified private chat (Phase 14 M6, message_id=11) | Delivering a draft actually generated from real content in *this* run |

## Repository analysis performed (read-only)

- Confirmed `worker/content_cycle.py::_select_eligible_events()`'s exact SQL shape (status ==
  COMPLETED NEWS_ANALYSIS, no CONTENT_GENERATION sibling in any status, via `aliased
  (EditorialTask)` + `~exists()`), and reused the same duplicate-check predicate — adapted to
  `status == CREATED` — to enumerate real, unprocessed `NEWS_ANALYSIS` candidates.
- Scanned the 60 most recently created `CREATED`/`NEWS_ANALYSIS` tasks with no
  `CONTENT_GENERATION` sibling. Found 84 active `NewsSource` rows in total. Of the 60 scanned
  candidates, 20 have well-formed, real-looking titles; the remainder are excluded (see below).
- Confirmed `scripts/run_content_generation.py::run_content_generation_for_event()` and
  `workflows/runner.py::WorkflowRunner.run()` are unmodified since Phase 14 M6 — same atomic
  claim (`UPDATE ... WHERE status == CREATED`), same per-step persistence, same three-outcome
  `ContentGenerationOutcome` contract.
- Confirmed `services/telegram_notifier.py::send_editorial_card()` and `bot/loader.py::
  create_bot()` are unmodified since Phase 14 M6 — same dry_run/live split, same
  `NotificationOutcome` contract.

## Two data-quality issues discovered (NOT to be fixed — out of scope, reported as limitations)

1. **Malformed titles from several RSS-derived sources** ("Google News RU: ИИ", "Google News:
   Artificial Intelligence", "Techmeme", "Lobsters", "Tproger", "Habr: Artificial Intelligence",
   "GamesIndustry.biz", "PyTorch Releases"): `NewsEvent.title` is literally an HTML fragment
   (`'<a'`, `'<img src="..."'`, `'<p>...'`) — the Collector's title-extraction for these feeds is
   truncating on the first HTML tag instead of extracting the actual headline text. A pre-existing
   Collector/parsing defect (Phase 12 territory). **Excluded from candidate selection; not fixed
   here.**
2. **Phase 13 M7 preserved synthetic artifact** (`NewsSource` name
   `phase13-m7-live-validation-1fcc068e-...`) still appears in this candidate pool, as intended by
   the deliberate preserve-and-label evidence policy. **Explicitly excluded from selection** since
   it is synthetic, not real news.

## Selection method (read-only, deterministic, no mutation)

```sql
SELECT task.id, task.event_id, task.created_at, event.title, event.published_at,
       event.collected_at, event.url, source.name
FROM editorial_task task
JOIN news_event event ON task.event_id = event.id
JOIN news_source source ON event.source_id = source.id
WHERE task.status = 'CREATED'
  AND task.workflow->>'workflow_name' = 'NEWS_ANALYSIS'
  AND NOT EXISTS (
        SELECT 1 FROM editorial_task cg
        WHERE cg.event_id = task.event_id
          AND cg.workflow->>'workflow_name' = 'CONTENT_GENERATION'
      )
ORDER BY task.created_at DESC
LIMIT 60
```

Then, in Python, exclude any row where the source name contains "test"/"validation"
(case-insensitive), or the title starts with `<` (malformed-HTML marker). From the remaining
clean candidates, pick the single freshest, most substantive, non-truncated, real-looking title.

**Selected candidate:**

| Field | Value |
|---|---|
| `task_id` (NEWS_ANALYSIS) | `10d30deb-2a45-4770-a3bd-68ab35c13675` |
| `event_id` | `9420a3c1-ef14-4f7f-8ebf-b8a809db183e` |
| source | `vc.ru` |
| title | «Робототехнический стартап Atoms сооснователя Uber Трэвиса Каланика привлёк $1,7 млрд. Оценку компании не раскрыли.» |
| published_at | 2026-07-23 10:15:15+00:00 |
| collected_at | 2026-07-23 10:35:06.328114+00:00 |
| url | https://t.me/vcnews/62532 |
| current workflow state | `CREATED`, `workflow_name=NEWS_ANALYSIS`, no steps run yet |

Rationale: real, current-day, self-contained, complete-sentence Russian headline about an actual
funding event (a genuine editorial topic); source is a real content feed, not RSS/HTML-derived;
no CONTENT_GENERATION sibling exists for this event in any status.

## Execution procedure

1. **Print candidate details** (event_id, source, title, created_at, current workflow state) —
   done above. **STOP here and wait for explicit human confirmation before any AI call.**
2. After confirmation, **run `NEWS_ANALYSIS` live**: direct invocation of
   `WorkflowRunner(CapabilityExecutor(session, task_id, real_registry)).run(session, task_id)`
   against `task_id=10d30deb-...` — the same direct-invocation pattern used in Phase 13 M7 (no
   eligibility scan, no worker loop, exactly this one pre-identified task_id). Uses the real,
   assembled AI integration layer (`assemble_ai_integration_layer()`), same as
   `run_content_generation_for_event()`'s own default path. No retries beyond what
   `WorkflowRunner` already performs internally per step's `max_attempts`.
3. If `NEWS_ANALYSIS` completes, **run `CONTENT_GENERATION` live** via
   `run_content_generation_for_event(event_id=9420a3c1-..., capability_registry=<same real
   registry>)` — unmodified, reused verbatim from Phase 14 M6/production. This creates exactly
   one new `EditorialTask` (CONTENT_GENERATION) and, on success, exactly one `ContentDraft`.
4. Record: provider call count, wall-clock execution time per stage, workflow statuses, step
   results (from `task.workflow["step_results"]`).
5. **Editorial quality check** on the resulting `ContentDraft`: real topic? explains what
   happened and why it matters? no hallucination vs. the source title? no internal/test wording?
   suitable tone/format for an SMM channel? Russian language preserved?
6. **Telegram delivery**: reuse chat_id `5507703201` (verified Phase 14 M6,
   `docs/phase14_m6_chat_id_verification.md`). Pre-send, re-verify via a fresh `bot.get_chat()`
   call that `chat.id == 5507703201` and `chat.type == "private"`. Temporary in-process-only
   override of `settings.content_generation_dry_run`/`settings.editorial_chat_id`, reverted in a
   `finally` block, verified reverted from a separate fresh process afterward — the exact pattern
   already proven twice in Phase 14 M6. Exactly one `send_message()` call.
7. **Post-validation audit**: confirm exactly one new `CONTENT_GENERATION` task exists for this
   event, exactly one new `ContentDraft` exists, no other event was touched, no worker process
   was started, no channel/approval flow was invoked.
8. Write `docs/phase14_5_real_news_validation_report.md` documenting all of the above, including
   the two discovered limitations (malformed RSS titles; preserved Phase 13 M7 artifact still
   present in the pool).

## Safety boundaries (frozen, restated)

- Exactly one event, hand-picked by explicit read-only query — never an eligibility scan, never a
  worker loop, never a batch.
- No `.env` changes, no permanent `dry_run` disable, no background service started.
- No architecture change, no new capability, no new table, no workflow-contract change.
- Hard stop for human confirmation between event selection and AI execution.
- If anything unexpected occurs at any step: stop, do not fix architecture, do not expand scope,
  report the blocker.

---

PHASE 14.5 VALIDATION PLAN READY — AWAITING EVENT SELECTION CONFIRMATION
