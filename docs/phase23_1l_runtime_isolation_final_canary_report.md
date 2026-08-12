# Phase 23.1L — Runtime Isolation + Hard Delivery Cap + Final Local Acceptance Canary — Final Report

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged all session, nothing committed). `prompts/copywriting/v8.2.yaml` and every other frozen
item listed in the phase brief (editorial length targets, Editorial Treatment thresholds, scoring
thresholds, Story Memory algorithm, Fact Safety algorithm, image ranking, Telegram card design)
were **not modified** this phase — confirmed by scope of the diff (only new files plus targeted
edits to `core/config.py`, `tests/conftest.py`, `tests/test_triage_orchestrator_claims.py`,
`.env.example`, and `tests/test_canary_delivery_cap.py`'s own bugfix).

## 1. Test-data contamination root cause

Proven precisely, not guessed. Two integration test files (`tests/test_news_analysis_integration.py`,
`tests/test_content_generation_integration.py`) used `independent_session_factory()` — a helper,
shared by 16 test files, that constructed a real Postgres engine directly against
`settings.database_url`: **the exact same database** production containers and the live canary
read from, by deliberate historical design (`"Real Postgres, no separate test database"`, stated
verbatim in both files' own module docstrings, dating to Phase 12-14's own concurrency-testing
needs). These tests use real commits (not the SAVEPOINT-rollback `db_session` fixture), relying
entirely on hand-maintained, per-table teardown `DELETE` statements. That list was missing a guard
for `content_draft_editorial_plans` — a table populated by the Editorial Planning capability's
shadow-mode evaluation (`editorial_planning_mode=shadow`, the real `.env` default, active for
every test run) whenever a real NEWS_ANALYSIS pipeline runs. Reproduced live during this phase's
own forensics: the exact failing statement was `DELETE FROM news_events ... violates foreign key
constraint "content_draft_editorial_plans_event_id_fkey"`. When that DELETE fails, the entire
teardown transaction aborts uncommitted — not just `ContentDraftEditorialPlan`, but the
`NewsEvent`, its `EditorialTask`(s), and its `NewsSource` all survive permanently in the real dev
database.

**Correction to Phase 23.1K's own report**: that report speculated `tests/test_phase10_workflow_integration.py`
as a likely contamination source. Direct investigation this phase found that file uses the
`db_session` fixture (SAVEPOINT-rollback, always safe) — it was never a contamination source. The
real sources are the two files named above, both using the unrelated
`independent_session_factory()` convention.

## 2. Exact contaminating tests

- `tests/test_news_analysis_integration.py` (titles `"M5 integration test event <uuid>"`) — via
  its own `test_source` fixture teardown.
- `tests/test_content_generation_integration.py` (titles `"Phase 14 M5 integration test event <uuid>"`)
  — same mechanism.
- **Scope**: NOT limited to these two. 16 test files share `independent_session_factory()` as their
  connection source (`test_analysis_worker_cycle.py`, `test_automation_integration.py`,
  `test_content_draft_service.py`, `test_content_worker_cycle.py`,
  `test_content_worker_cycle_image_preview.py`, `test_image_retention.py`,
  `test_phase15_m1_invalid_title_gate.py`, `test_phase15_m3_engagement_signal_preservation.py`,
  `test_run_content_generation.py`, `test_triage_orchestrator_claims.py`,
  `test_triage_orchestrator_cycle.py`, `test_triage_orchestrator_story_memory.py`,
  `test_workflow_runner.py`, `test_workflow_runner_per_step_persistence.py`, plus the two named
  above) — evidenced further by `NewsSource` naming patterns found in the dev DB spanning
  `phase13-m5-integration-test-*` and `phase14-m5-integration-test-*`, confirming at least Phase
  13's own test module (the origin of `independent_session_factory()`) was affected too.
- **Existing protection before this phase: none.** No environment marker, no separate database, no
  fail-fast assertion anywhere in the DB-connecting code path.

## 3. Isolation design

Physical database separation (the brief's own preferred direction), not a naming convention.
`core/config.py` gained `postgres_test_db: str = "ai_newsroom_test"` and a `test_database_url`
property (mirrors `database_url` exactly, differing only in database name). A real, physically
separate Postgres database (`ai_newsroom_test`, same server) was created and migrated
independently to Alembic head. `tests/conftest.py`'s `_test_engine` (backing the `db_session`
fixture) and `tests/test_triage_orchestrator_claims.py`'s `independent_session_factory()` (the
single shared choke point for all 16 dependent files) were both repointed at
`settings.test_database_url`.

## 4. Fail-fast protection

`tests/conftest.py` Barrier 4 (`assert_is_test_database`), applied at module import time exactly
like the pre-existing Barriers 1-3, before any fixture or test runs. Exact identity comparison
(not substring matching, per the brief's explicit instruction) — a candidate database name must
equal `settings.postgres_test_db` and must NOT equal `settings.postgres_db`, checked
independently. A pure string comparison — zero I/O — so a rejection happens before any connection
is even opened, let alone a write. `independent_session_factory()` calls it before constructing
its engine.

## 5. Isolation tests

`tests/test_db_isolation_guard.py`, 7/7 pass: accepts the real test DB name; **rejects the real
dev DB name** (Part E's own required "a test intentionally pointed at the normal development DB
... FAIL FAST BEFORE ANY WRITE" case); rejects an arbitrary third name; asserts the two settings
values actually differ; proves `independent_session_factory()`'s live connection genuinely targets
`ai_newsroom_test` (verified via `SELECT current_database()`, not by re-reading a URL string);
proves the `db_session` fixture's engine does too; proves a manually-constructed engine pointed at
`settings.database_url` is correctly rejected by the guard.

## 6. Existing pollution cleanup

Exact-ID only, per the brief's explicit "do not use broad title-pattern DELETE statements"
instruction — title/name patterns were used only to *discover* IDs (logged to
`scripts/_phase23_1l_cleanup_audit.json` before any DELETE ran), every actual DELETE statement
targeted `WHERE id IN (<exact ids>)`. Every one of the 33 `NewsEvent` titles was verified to start
with exactly one of the two known synthetic patterns (zero ambiguous titles); every one of the 18
`NewsSource` rows was verified exclusively referenced by these 33 events (no shared/legitimate
use) before being included in the delete. Full dependency graph traced (a live run surfaced one
additional FK not part of the original plan: `ai_executions.task_id` → `editorial_tasks.id` — cost
rows exclusively tied to the confirmed-test tasks, included in the cleanup by exact task ID list).
FK-safe delete order: `content_draft_editorial_plans` → `ai_executions` → `content_drafts` →
`editorial_tasks` → `news_event_article_acquisitions` → `news_events` → `news_sources`.

## 7. Dev DB before/after state

| Table | Before | After | Delta |
|---|---|---|---|
| `news_events` | 18745 | 18712 | −33 |
| `sources` | 505 | 487 | −18 |
| `editorial_tasks` | 19757 | 19707 | −50 |
| `content_drafts` | 634 | 620 | −14 |
| `content_draft_editorial_plans` | 557 | 536 | −21 |

Every delta matches the pre-verified audit counts exactly. Re-confirmed zero remaining pollution
rows (`title LIKE '%integration test event%'` → 0) at this report's own preflight (§12) — no
regrowth since cleanup.

**Incident during this work, disclosed in full**: an initial attempt to migrate the new test
database used a non-existent `alembic -x db=test` flag; `database/migrations/env.py` hardcodes
`settings.database_url`, so the command silently applied 4 previously-deliberately-unapplied
migrations to the **real dev database** instead. Caught immediately (checked `alembic_version`
right after), confirmed zero data loss (the new tables were empty, `stories`' existing 61 rows
untouched by the additive-only DDL), and fully reverted via `alembic downgrade 8faedf40f596`,
restoring the exact prior state. The test database was then correctly migrated using a
`POSTGRES_DB=ai_newsroom_test` environment-variable override for that one subprocess only.

## 8. Hard-cap root cause

Phase 23.1K's canary checked `if total_notified >= target: break` once **between rounds**, not
before each individual send. `run_content_cycle()` can itself deliver more than one message per
call (bounded by batch processing, not any per-message budget) — round 3 started with
`total_notified=4` (below the cap of 5) and that one call delivered 2 messages, landing at 6.

## 9. Hard-cap implementation

`scripts/_canary_delivery_cap.py` — deliberately NOT a change to `worker/content_cycle.py` or any
other production editorial service (per the brief's explicit "do not inject test-specific counters
throughout production editorial services" instruction). `HardDeliveryCap.try_consume()` is a
synchronous, zero-I/O counter check; `wrap_bot_with_hard_cap()` patches the canary's own
`aiogram.Bot` instance's `send_message`/`send_photo` so every real Telegram call — regardless of
which production code path invokes it — is gated immediately before the network call. Once
exhausted, it raises `DeliveryCapExhaustedError` (a real `TelegramAPIError` subclass), which every
existing `except TelegramAPIError:` call site already handles gracefully (records
`notification_failed`, never crashes the cycle) — zero new error-handling code needed anywhere in
production. Budget semantics (documented explicitly): consumed on every send **attempt**, success
or failure — the invariant is "at most N real calls reach the Telegram API," not merely "at most N
successful deliveries."

## 10. Hard-cap tests

`tests/test_canary_delivery_cap.py`, 9/9 pass, covering all 7 required Part G cases: exact-N cap
(case 1), cap=1 (case 2), cap=0 (case 3), partial remaining allowance — delivered=4/batch=5/max=5
(case 4), a failed attempt still consumes the budget by design (case 6, documented rationale), no
sixth send after a successful fifth (case 7), plus two wrapped-bot-mechanism tests and one
end-to-end integration test (6 eligible drafts through a real `run_content_cycle()` call → exactly
5 real sends, `cap.attempted == 5`).

## 11. Regression results

Run **only** against the isolated `ai_newsroom_test` database (per the brief's explicit "do NOT
run the old full regression suite against the shared dev DB again"). Full suite: **3204 passed, 22
failed, 21 skipped, 35 errors** (7m in the isolated DB — vs. 9h35m in Phase 23.1K's own dev-DB run;
the isolated DB's much smaller row counts and freedom from `automation_worker` contention account
for the ~80x speedup, itself indirect evidence the isolation is real).

**A genuine new failure was found and fixed, not dismissed**: the first full run (before this
report's final state) showed 33 failed — 11 more than the final count. Investigated directly (not
assumed as "DB pollution"): `tests/test_canary_delivery_cap.py`'s own integration test set
`settings.editorial_delivery_mode = "router"` directly (not via `monkeypatch`) with no restore
fixture, leaking global state into every test that ran afterward in the same process — exactly the
class of bug `tests/test_router_media_integration.py` already guards against with its own
`_reset_delivery_mode` autouse fixture. Fixed by adding the identical fixture to the new file;
verified fixed by re-running the exact failing file pair together (isolated: 1 failed, matching
baseline; combined: same 1 failed) and then the full suite again.

**Every one of the remaining 22 `FAILED` entries name-matches Phase 23.1K's own already-disclosed
39-failure baseline list** — zero genuinely new failures. The single `test_content_cycle_story_delivery.py::
test_shadow_mode_persists_proposal_but_never_skips_or_changes_the_real_send` failure was
independently re-verified in complete file isolation (proving it is not order-dependent). All 35
`ERROR` entries match exactly 4 previously-documented FK-teardown constraint names
(`content_draft_editorial_plans_event_id_fkey`, `news_event_article_acquisitions_news_event_id_fkey`,
`content_draft_story_links_content_draft_id_fkey`, `stories_first_event_id_fkey`) — no new/unknown
error type appeared.

Ruff (full repo): clean except 6 pre-existing issues in old, untouched one-off scratch scripts.
Mypy (full application tree + this phase's new files): 11 pre-existing errors, unrelated to this
phase (missing third-party stubs, 2 pre-existing `services/story_delta_engine.py` issues from
Phase 20) — **zero** in any file this phase touched.

## 12. Final preflight

See `docs/phase23_1l_final_canary_preflight.md` (all 15 required items). Summary: dev DB revision
`8faedf40f596` (unchanged), test DB independently at head `3f37cf34109d`, zero remaining pollution
rows, `content_worker`/`news_analysis_worker` stopped, `copywriting_prompt_version=8.2` (frozen,
set in-process only), `editorial_delivery_mode=router` (in-process only), `story_memory_mode=off`
(honestly unchanged), `fact_safety_mode=shadow`, 5 fresh NEWS_ANALYSIS-eligible /
0 fresh CONTENT_GENERATION-eligible at preflight time, destination hardcoded to
`chat_id=-1004297182444, topic=2`.

## 13. Events analyzed

**25** (5 rounds × 5 per round, `news_analysis_batch_size`), well under the 50 cap. Provenance
logged for every candidate that reached treatment classification (event_id, source id, source
name/type, source URL, `collected_at`, `published_at`) — every one a real `NEWS_API`/`RSS` source
row with a real upstream URL and timestamp; none could structurally be a synthetic fixture under
the new isolation model (the canary reads from `ai_newsroom` alone, and Part D/E's cleanup +
Part 12's zero-pollution recheck rule that out).

## 14. Candidate decisions

7 candidates reached treatment classification across the run; 5 were SEND (STANDARD ×4, BRIEF ×1),
0 SKIP, 0 BLOCK, 0 duplicate-guard blocks (`duplicate_blocked=0` every round). Full per-candidate
log (`scripts/_phase23_1l_final_canary_records.json`'s `treatment_decisions` array) includes each
one's score, Intelligence significance/recommendation, and reason.

## 15. Delivered count

**5.**

## 16. Confirmation delivered_count <= 5

**Confirmed, three independent ways**: (1) the canary's own runtime assertions
(`assert total_notified <= 5`, `assert cap.attempted <= 5`) passed without raising; (2) the hard
cap's own internal counter: `cap.attempted = 5, cap.max_deliveries = 5`, stop reason
`hard_delivery_cap_exhausted`; (3) `recorded_sends` (the instrumented wrapper's own ground-truth
log of real Telegram API calls) contains exactly 5 entries, message IDs 92-96, all at the correct
`chat_id`/`message_thread_id`. No sixth send was attempted or possible — round 5 itself delivered 2
messages (bringing the total from 3 to 5), and the cap correctly stopped the loop immediately
after, before round 6 could start.

## 17. V8.2 live results

All 5 posts pass every structural acceptance check: exactly one main-body paragraph, no
`expandable_details` key present, no NINJA PULSE footer, no raw source URL inside the body text.
Headlines and bodies read as plain-language, no vendor/technical overload (matches the delete-
before-explaining/vendor-supplier rules — none of the 5 stories happened to involve a vendor-name
scenario like Armenia/Firebird, but none show unnecessary jargon either). At most one uncertainty
statement per post (each ending is a single, distinct caveat sentence, never stacked hedges).

## 18. Images

2 of 5 posts (40%) delivered with an attached image (techcrunch.com ×2, www.techmeme.com — 3
image-domain entries total across posts 1/2/4); posts 3 and 5 fell back to text-only (no eligible
candidate found — the expected, safe degradation, not a bug).

## 19. Source buttons

5 of 5 posts have a `🔗 Источник` button pointing at the real article URL. No raw URL appears
inline in any body text.

## 20. Fact Safety observations

`fact_safety_mode=shadow` throughout — never suppressed a send. Disclosed honestly: shadow flagged
issues on **all 5** posts (a legacy `passed`/`issues` quality-completeness check consistently
reports "missing body text" — a known, already-disclosed schema-understanding gap where that
particular sub-check does not fully recognize the V8-family `main_body` field shape; not a new
finding). The newer, structured `fact_safety` sub-check found 2 of 5 at `status=block`
(high-severity unsupported entity claims — "Камеры Flock", "Жители Сахалинской") and 1 at
`status=review` (2 medium-severity unsupported entities). None suppressed delivery, consistent
with shadow mode's contract. This calibration behavior (flagging most posts) matches prior phases'
own disclosed Fact Safety findings and remains out of scope to fix this phase per the brief's
explicit freeze.

## 21. Story Memory observations

`story_memory_mode=off` throughout, honestly unchanged — all 5 delivered posts show
`story_id=None, story_match_type=None`. Part N's own canary-side duplicate tripwire (a simple,
transparent, high-threshold word-overlap check, explicitly NOT a Story Memory change) never fired
— `duplicate_tripwire: None` in the run's own records — all 5 stories are genuinely distinct (even
the two OpenAI stories in round 1 are about different events: an employee tender offer vs. a new
cybersecurity model).

## 22. Cost/runtime

$0.1358 incremental (25 events analyzed, 5 delivered), 333 seconds (~5.5 minutes) runtime — both
far under the $1/4h caps.

## 23. Errors/retries

Zero send failures, zero content-generation failures among the 5 delivered candidates (one
unrelated NEWS_ANALYSIS task failed in round 4's own analysis cycle — a real, isolated,
non-blocking failure logged by `run_analysis_cycle()`'s own existing per-task error handling,
consistent with normal operation, not investigated further as out of this phase's scope).

## 24. Remaining blockers

None structural. Two narrow, disclosed, non-blocking items for future attention (neither gates
Phase 23.2): (a) the pre-existing `content_draft_editorial_plans` teardown-guard gap in the 16
`independent_session_factory()`-based test files is now harmless (contained to the disposable test
DB) but not itself fixed — a future cleanup could add the missing guard for tidiness, not safety;
(b) Fact Safety shadow's legacy `passed`/`issues` check does not fully recognize V8-family output
shape (flags "missing body" on every V8.2 post) — cosmetic/log-noise only, never blocking, since
shadow mode never enforces.

## 25. Final recommendation: **A — READY FOR PHASE 23.2 VPS PREPARATION**

All required conditions are met: tests can no longer contaminate dev/live data (physical DB
separation + fail-fast guard, proven with a real negative-case test and three independent
before/after row-count checks); the 33 previously-leaked rows are fully and safely cleaned
(exact-ID only, zero collateral risk, verified before/after); the hard delivery cap is proven both
in unit tests (all 7 required cases) and in this exact live run (5/5, `hard_delivery_cap_exhausted`,
never a 6th attempt); all 5 delivered messages are genuine, verifiably-provenanced real news;
V8.2 remains editorially sound and untouched; routing/images/source buttons all functioned
correctly. No new structural blocker appeared.

## STOP

Per the phase brief: do NOT deploy to VPS. Awaiting human approval to begin Phase 23.2.
