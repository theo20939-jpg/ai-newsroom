# Phase 19 M7 — Story Timeline, Editorial Memory, and the Reply-Threading Shadow-Mode Fix

## 1. Scope

M7 covers two related pieces of work, both gated shadow-only:

1. **The disclosed reply-threading shadow-mode gap** (`docs/phase19_m0_audit.md` §7,
   `docs/phase19_m6_story_memory_calibration_report.md` §3.1) — a real, already-committed
   Phase 18.10 defect where `worker/content_cycle.py`'s reply-target computation (including a
   fail-closed skip) was gated directly on `story_memory_mode != "off"`, meaning
   `story_memory_mode="shadow"` could itself change Telegram delivery behavior. Fixed by
   decoupling delivery behavior onto its own independent setting, `telegram_story_reply_mode`
   (already scaffolded in `core/config.py` by a prior session, previously unconsumed by any code).
2. **Story Timeline + Editorial Memory** (`services/story_context.py`) — a deterministic,
   evidence-only reconstruction of a Story's event history, persisted for human review under a
   new `story_context_mode` setting.

## 2. The reply-threading fix

`worker/content_cycle.py`'s reply-target block now reads `settings.telegram_story_reply_mode`
instead of `settings.story_memory_mode`:

- **`"off"` (default)**: no `ContentDraftStoryLink` lookup at all, `reply_to_message_id` stays
  `None` unconditionally — byte-identical to pre-Phase-18.10 behavior, **regardless of
  `story_memory_mode`**. This is the concrete fix: previously, `story_memory_mode="shadow"` alone
  (a mode whose entire purpose is "compute and persist, never change behavior") could change
  which message a post replied to, or skip a send entirely via the fail-closed route. It no longer
  can — verified by `tests/test_content_cycle_story_delivery.py::
  test_story_memory_shadow_alone_never_affects_telegram_delivery`, a direct regression test for
  the disclosed defect: with `story_memory_mode="shadow"`, a real `story_update` link, and no root
  delivery (the exact case that used to fail-closed and skip the send), the send now proceeds as a
  normal standalone post.
- **`"shadow"`**: the reply decision is computed and persisted
  (`services.story_telegram_delivery.persist_reply_routing_proposal` →
  `content_draft_reply_routing_proposals`, `applied=False`) for review, but the real send always
  proceeds as a standalone post — `reply_to_message_id` stays `None` and a fail-closed case is
  never skipped (only counted, via the new `ContentCycleResult.story_reply_would_fail_closed_shadow`
  counter, purely observational).
- **`"enforce"`**: applies the decision to the real send (`applied=True`), preserving the original
  fail-closed skip-and-route-to-review guarantee. Requires a separate human authorization and the
  Phase 19 M6 calibration gate having been passed (a documented precondition, not a code check).

New table `content_draft_reply_routing_proposals` (1:1, PK reuses `content_draft_id`, mirrors
`content_draft_quotes`' convention) — migration `280fa1e7d6d2`, written but not applied live.

### 2.1 A second, real defect found and fixed while validating this

Validating the (previously always-skipped) integration tests against an actually-migrated
disposable database surfaced two more pre-existing, previously-undiscovered bugs, neither
introduced by M7:

1. **`database/models/story_telegram_delivery.py`**: `Enum(DeliveryType, ...)` /
   `Enum(DeliveryStatus, ...)` were mapped without `values_callable`, so SQLAlchemy sent each
   enum member's uppercase *name* (`"ROOT"`) to Postgres instead of its lowercase `.value`
   (`"root"`) — but migration `0fac25b59455` created the native Postgres enum types with only the
   lowercase labels. Every query/insert against `story_telegram_deliveries.delivery_type`/
   `delivery_status` would have failed with `invalid input value for enum` the moment the
   migration was applied. Fixed with the same `values_callable=_enum_values` pattern already
   established in `database/models/image_candidate_record.py`/`meme_candidate.py`.
2. **`tests/test_content_worker_cycle.py::test_source`'s teardown**: deleted `ContentDraft`/
   `EditorialTask`/`NewsEvent` without first deleting the newer Phase 18.10/19 child rows
   (`ContentDraftStoryLink`, `StoryTelegramDelivery`, `ContentDraftReplyRoutingProposal`,
   `StoryContextSnapshot`, `NewsEventStoryLink`, `Story`) that FK-reference them. Against a
   migrated database this made the teardown DELETE fail on a foreign-key violation, silently
   leaving a stale `COMPLETED` `NEWS_ANALYSIS` task in the database for a later test's
   `run_content_cycle()` call to pick up — a real test-isolation bug, invisible until now because
   these tables were never present during any prior test run. Fixed by extending the fixture's
   cleanup to delete the new child tables first, in FK-safe order, guarded by a runtime
   table-existence check so it degrades to a no-op against the real (unmigrated) database.

Both are narrow, disclosed, test/model-layer fixes — no architecture change, no behavior change
under current default settings (both bugs were only reachable once a migration is applied, which
has not happened to the real database).

## 3. Story Timeline (`services/story_context.py::build_story_timeline`)

Derives a Story's full event history purely from already-persisted evidence: `NewsEventStoryLink`
(event ↔ story), `ContentDraftStoryLink` (event ↔ resulting draft), `StoryTelegramDelivery`
(draft ↔ actual send). No LLM call, no embeddings, no guessed chronology. Three bounded queries
total per timeline build, never N+1.

- **Ordering**: `published_at`, falling back to `collected_at` when absent — the same anchor
  `worker/content_cycle.py::_select_eligible_events()` already established as this codebase's one
  authoritative freshness field.
- **`delta`**: a coarse, disclosed classification derived from `services.story_memory`'s own
  match-type vocabulary (`new_story` → `"new_story"`, `story_update` → `"new_information"`,
  `supporting_source`/`semantic_duplicate` → `"corroboration"`, `uncertain_match` →
  `"unknown"`) — never a semantic claim, never LLM-generated.
- **`introduced_new_facts` / `confirmed_existing_facts`**: since no per-event signature is ever
  persisted (`NewsEvent` deliberately has no such column), each event's `services.story_memory.
  extract_story_signature()` is recomputed fresh while walking the ordered event list, diffed
  against a running keyword pool built up to (not including) that event. A deterministic,
  narrow approximation of "what's new" — never a fabricated fact list.
- **`source_role`**: always `None` in this milestone — Source Intelligence (Phase 19 M8) is the
  first thing that could ever populate it. `UNKNOWN` stays `UNKNOWN`, never silently inferred.
- **`already_published` / `telegram_message_id`**: reflect only a `StoryTelegramDelivery` row
  with `delivery_status == SENT` — never inferred from a draft's mere existence.

Persisted for review via `services/story_context_persistence.py::persist_story_context_snapshot()`
into the new `story_context_snapshots` table (1:many, surrogate PK, mirrors
`content_draft_editorial_plans`' convention) — a dedicated persistence-indirection module, exactly
like `services/editorial_plan_persistence.py`, so `capabilities/executor.py` never imports
`database.models.story_context_snapshot` directly.

## 4. Setting and shadow-isolation proof

```python
story_context_mode: Literal["off", "shadow"] = "off"
```

No `"enforce"` value exists — this milestone never proposes to change Copywriting output.
`"shadow"`: `capabilities/executor.py::_attach_story_context()` (same seam/pattern as
`_attach_editorial_plan()`) builds and persists a timeline snapshot whenever the event is
story-linked; a no-op otherwise. Deliberately returns `None`, never touches `structured_output` —
Copywriting has no code path to read it, exactly like Editorial Planning's own structural
guarantee.

Shadow-isolation proof: `tests/test_story_context_shadow_integration.py`, mirroring
`tests/test_editorial_planning_shadow_integration.py` exactly — both with and without an actual
story link, `story_context_mode="shadow"` makes zero extra LLM calls (4, never 5) and produces
byte-identical Copywriting output to `"off"`.

## 5. Validation performed

- Disposable Postgres, migrated to head (through `280fa1e7d6d2`), upgrade/downgrade/re-upgrade
  all clean.
- All new/modified tests pass for real against the migrated disposable DB; the same tests skip
  cleanly (via a runtime table-existence check, not a static marker) against the real,
  intentionally-unmigrated dev DB.
- Real DB alembic revision unchanged (`31a8d7c95c87`) throughout.
- Ruff/Mypy clean on all touched source files.

## 6. What this milestone does NOT do

- Does not enable `telegram_story_reply_mode` or `story_context_mode` anywhere (both default
  `"off"`).
- Does not touch `services/story_memory.py`'s thresholds, gate, or `story_memory_mode`'s default.
- Does not send a real Telegram message.
- Does not apply any migration to the real database.
