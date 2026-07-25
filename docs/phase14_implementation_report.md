# Phase 14 — Autonomous Newsroom Loop: Implementation Report (M0–M5)

## Status: GREEN — M0 through M5 complete, M7-equivalent (live send) NOT executed

Implements `docs/phase14_autonomous_newsroom_implementation_plan.md` exactly, as approved with
its four clarifications. No architecture was redesigned; every frozen boundary was respected
(verified explicitly below, not merely asserted).

## Milestones completed

| Milestone | Status | Summary |
|---|---|---|
| M0 — Baseline | GREEN | HEAD unchanged (`e6cf337`), no unexpected drift, Postgres+Redis running, 867 tests collected before any change |
| M1 — Automatic CONTENT_GENERATION trigger | GREEN | `worker/content_cycle.py::_select_eligible_events()` — eligibility, freshness bound, score threshold, duplicate exclusion, scan-limit cap |
| M2 — Content Worker | GREEN | `worker/content_cycle.py::run_content_cycle()` + `worker/content_main.py` — separate worker, not merged into `analysis_worker` |
| M3 — Telegram Notification | GREEN | `services/telegram_notifier.py::send_editorial_card()` — dry-run/live modes, `editorial_chat_id`, `content_generation_dry_run` |
| M4 — Testing | GREEN | 4 new test files + 1 extended, 54 new tests, all passing |
| M5 — Validation | GREEN | Full suite, ruff, mypy, architecture validator, secret hygiene, dry-run validation — all green (details below) |

## Files changed (exact scope, matches the approved Plan's §1 exactly — 10 files)

**Production (5)**:
- NEW: `worker/content_cycle.py`, `worker/content_main.py`, `services/telegram_notifier.py`
- MODIFIED (narrow, append-only): `core/config.py` (7 new `Settings` fields), `docker-compose.yml`
  (1 new `content_worker` service)

**Tests (5)**:
- NEW: `tests/test_content_worker_cycle.py` (14 tests), `tests/test_telegram_notifier.py` (7
  tests), `tests/test_content_worker_main.py` (9 tests), `tests/test_content_generation_
  integration.py` (3 tests)
- MODIFIED (append-only): `tests/test_settings_phase7.py` (+21 tests)

**Confirmed untouched** (verified by `git status`, not merely intended): `scripts/run_content_
generation.py`, `services/content_draft_service.py`, `workflows/definitions/content_
generation.py`, `workflows/definitions/news_analysis.py`, `workflows/runner.py`, `worker/
analysis_main.py`, `worker/analysis_cycle.py`, `bot/handlers/news.py`, `services/editorial_
inbox_service.py`, `bot/formatting.py`, `bot/loader.py`. `run_content_generation_for_event()` and
`render_editorial_card()`/`create_bot()` are imported and called exactly as-is.

## Implementation notes / deviations from the Plan's literal pseudocode

1. `NotificationOutcome.chat_id`'s original design required `chat_id is not None` unconditionally
   — this was wrong and caught by the dry-run test suite itself: dry-run mode must tolerate
   `editorial_chat_id` being unset (inspecting a dry-run payload before configuring the chat is
   part of what dry-run is for). Fixed: the `chat_id is not None` assertion now only fires in live
   mode (`dry_run=False`); `NotificationOutcome.chat_id` is typed `int | None` accordingly. A real
   bug caught by tests before it could reach any real usage, not a design change.
2. The "no asyncio.gather" static-grep test initially failed against the production file's own
   explanatory comment (which legitimately contained the word "gather"). Fixed by rewording the
   comment, not weakening the test — the underlying guarantee (sequential execution, verified by
   the same static check `tests/test_analysis_worker_cycle.py` already established) is unchanged.
3. `content_generation_scan_limit >= content_generation_batch_size` is enforced by a dedicated
   test against the shipped defaults (`test_content_generation_scan_limit_default_is_at_least_
   batch_size_default`), not a new pydantic cross-field validator — this codebase's `Settings`
   class has no existing cross-field-validator precedent, and introducing one would be a small
   architectural addition beyond this integration phase's own stated scope.

## Duplicate-prevention verification (frozen requirement, tested exhaustively)

`tests/test_content_worker_cycle.py::test_duplicate_content_generation_sibling_excludes_
regardless_of_status` is parametrized across all four `TaskStatus` values (`CREATED`, `RUNNING`,
`COMPLETED`, `FAILED`) — each run independently, each confirming the event is excluded. This is
the load-bearing test for "a NewsEvent must never receive more than one CONTENT_GENERATION task."

## Scan-limit verification

`test_scan_limit_caps_candidates_before_score_filtering` directly proves the SQL query itself
returns no more than `content_generation_scan_limit` rows even when more genuinely-eligible
test-owned candidates exist — not merely that the final batch is capped.

## Telegram dry-run verification (M5's own required step, executed)

`test_full_chain_dry_run_creates_draft_and_renders_without_sending` (`tests/test_content_
generation_integration.py`) is the exact chain M5 requires: a real, generated `ContentDraft` (via
the real `CONTENT_GENERATION` workflow, `FakeLLMGateway`-backed) → `send_editorial_card()` →
inspected `NotificationOutcome.rendered_html`, with `bot.send_message` asserted never called. A
second test (`test_full_chain_live_mode_sends_exactly_once`) proves the live path sends exactly
once when `content_generation_dry_run=False`. **No live Telegram send occurred anywhere in this
implementation** — every test uses a mocked `Bot`.

## Full validation results (M5, all run fresh)

1. **Full `pytest`** (whole repository): **921 passed, 0 failed** (baseline 867 + 54 new tests,
   accounted for exactly: +21 settings, +14 eligibility/orchestration, +7 notifier, +9 worker
   main, +3 integration). Runtime 5m24s.
2. **`ruff check .`** (repo-wide): all checks passed.
3. **Targeted `mypy`** on all 4 new/changed production files (`worker/content_cycle.py`, `worker/
   content_main.py`, `services/telegram_notifier.py`, `core/config.py`): no issues found.
4. **`python -m scripts.validate_architecture`**: 0 forbidden-dependency violations.
5. **Secret hygiene**: `.env` remains untracked; `docker compose config --quiet` clean;
   `docker compose config --services` confirms `content_worker` registers correctly alongside
   the existing 5 services. Plain `docker compose config` was never run.
6. **Git scope audit**: exactly the 10 files listed above changed — confirmed via `git status`,
   not merely intended.
7. **DB pollution audit**: zero leftover rows for every test-owned name prefix used across this
   and prior phases' own test suites.
8. **Frozen-boundary grep**: `worker/content_main.py`, `worker/content_cycle.py`, `services/
   telegram_notifier.py` — zero matches for `approve`/`approval`/`autopublish`/`InlineKeyboard`/
   `image`/`meme`/`dall-e`/`stable_diffusion`. `worker/content_cycle.py` never assigns to
   `EditorialTask.status` for a `NEWS_ANALYSIS`-workflow task — only reads it.

## Known limitations (disclosed, not defects)

- **Concurrent-replica race** (Plan §3): the duplicate-prevention `NOT EXISTS` check is not
  atomically closed against two simultaneous `content_worker` processes — correct only under the
  same single-instance assumption `analysis_worker`/`automation_worker` already operate under
  today.
- **No duplicate-notification protection** (Plan §5.1, frozen decision): a failed Telegram send
  is logged and not retried by any dedicated mechanism; `/news` remains the durable fallback for
  a lost push notification.
- **`content_generation_min_score`/`content_generation_freshness_cutoff_hours` defaults** (`70`,
  `24.0`) are placeholders for human review, not empirically derived.
- **`CONTENT_GENERATION` task priority** is always `TaskPriority.B` (the existing `run_content_
  generation_for_event()` default) — the originating `NEWS_ANALYSIS` task's own priority is not
  propagated.

## Confirmations (explicitly required by this task)

- **No autopublishing exists**: `content_worker` creates `ContentDraft` rows and, in live mode,
  sends one Telegram message to `editorial_chat_id` (a private/operator chat) — nothing writes to
  or posts in any channel; grep-confirmed above.
- **No images/memes exist**: zero image-generation or meme-generation code anywhere in the three
  new files; grep-confirmed above.
- **No approval workflow exists**: no buttons, no approve/reject state, no `InlineKeyboard`
  anywhere in the three new files; grep-confirmed above. `ContentDraft.status` remains `"draft"`,
  exactly as `ContentDraftService.create_from_result()` (unmodified) already sets it.

## M7-equivalent (live Telegram send) — NOT executed

Per the Plan's own §8 and this task's own instruction to stop after M5: no real Telegram message
was sent, `content_generation_dry_run` remains `True` in the shipped default, and
`editorial_chat_id` was never set in any real environment as part of this implementation. Live
validation (a human-confirmed `editorial_chat_id`, dry-run inspection, then one live send) is a
separate, explicitly human-authorized step, not performed here.

---

PHASE 14 M0-M5 COMPLETE — READY FOR VALIDATION
