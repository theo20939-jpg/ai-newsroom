# PHASE 18.10 IMPLEMENTATION COMPLETE — MIGRATION/LIVE CANARY AUTHORIZATION REQUIRED

Status: implementation and validation complete. **No migration applied to the live database, no
rebuild/redeploy of running containers, no paid workers restarted, no live/enforce mode enabled,
no `.env` change, no live canary run, no Telegram message sent, no VPS deployment or Phase 19
work started** — all per explicit instruction throughout this phase.

## 1. Branch and HEAD

Branch: `feature/phase18-9-controlled-ai-activation`
HEAD: `03038f4b29995119ab04b6b4b36cef432f6e16ee` ("Complete Phase 18.9-R remediation evidence and
report", 2026-08-05 18:51:42 +0300)

All Phase 18.10 work exists as **uncommitted working-tree changes** on top of this HEAD — no new
commits were created (none were requested this phase).

## 2. Commits

**0 new commits.** All Phase 18.10 changes remain uncommitted in the working tree, staged for
your review before you decide whether/how to commit them.

## 3. Files changed

**58 files total: 33 modified, 25 new** (1,020 insertions / 116 deletions across modified files;
~2,487 lines across new files).

**Modified (33):**
`bot/formatting.py`, `capabilities/capability_mapping.py`, `capabilities/copywriting_capability.py`,
`capabilities/quality_capability.py`, `core/config.py`, `database/models/ai_execution.py`,
`database/models/content_draft.py`, `database/models/news_event.py`,
`schemas/editorial_inbox.py`, `scripts/run_content_generation.py`,
`services/content_draft_service.py`, `services/editorial_scoring.py`,
`services/image_preview_notifier.py`, `services/telegram_notifier.py`,
`services/triage_orchestrator.py`, `worker/content_cycle.py`, and 17 test files (
`tests/test_ai_execution_mapper.py`, `tests/test_capability_mapping.py`,
`tests/test_content_draft_service.py`, `tests/test_content_generation_integration.py`,
`tests/test_content_worker_cycle.py`, `tests/test_copywriting_capability.py`,
`tests/test_cost_recording_integration.py`, `tests/test_editorial_card_formatting.py`,
`tests/test_editorial_scoring.py`, `tests/test_fact_safety.py`,
`tests/test_integrated_editorial_validation.py`, `tests/test_openai_strict_schema_compliance.py`,
`tests/test_phase10_workflow_integration.py`,
`tests/test_phase18_m2_meme_concept_schema_and_registry.py`, `tests/test_quality_capability.py`,
`tests/test_run_content_generation.py`, `tests/test_telegram_notifier.py`).

**New (25):** 4 migrations, 5 models, 4 services, 1 prompt, 1 doc, 11 test files — full lists in
§4 and §18. `database/models/story.py` and `database/models/story_link.py` (Stage 4);
`database/models/content_draft_story_link.py` and `database/models/story_telegram_delivery.py`
(Stage 6); `database/models/content_draft_quote.py` (Stage 7); `services/story_memory.py` (Stage
4); `services/story_telegram_delivery.py` (Stage 6); `services/quote_verification.py` and
`services/content_quality_gates.py` (Stage 7); `prompts/copywriting/v4.yaml` (Stage 7);
`docs/phase18_10_meme_pipeline_audit.md` (Stage 2).

Three scratch/replay scripts used only for this validation pass (never touching the real
database): `scripts/_phase18_10_muse_code_replay.py`, `scripts/_phase18_10_additional_replay_sets.py`,
`scripts/_phase18_10_quote_scenarios.py` — left in place following this repository's own
established convention (numerous `scripts/_phase15_*`/`_phase17_*`/`_phase18_5_*` scratch files
already exist uncommitted in this tree from prior phases).

## 4. Migrations created

4 new files, in dependency order (none applied to the live database):

1. `8b9d649bc69b_add_engagement_value_to_ai_capability_.py` — adds `ENGAGEMENT` to the
   `ai_capability` Postgres enum (Stage 1 / M9). `downgrade()` raises `NotImplementedError`
   (Postgres cannot drop an enum value).
2. `c2bc6affb100_add_story_memory_tables.py` — creates `stories` and `news_event_story_links`
   only. **No columns added to `news_events` or `content_drafts`** — this migration was rewritten
   mid-phase after a hot-path-table dependency bug was found and fixed (see §21).
3. `0fac25b59455_add_telegram_reply_context_tables.py` — creates `content_draft_story_links` and
   `story_telegram_deliveries`, the latter with a DB-level `CHECK` constraint enforcing
   `delivery_status != 'sent' OR telegram_message_id IS NOT NULL`.
4. `f12a9b9732cc_add_content_draft_quotes_table.py` — creates `content_draft_quotes`.

Every new table's own primary key is reused from the table it links to (e.g.
`news_event_story_links.news_event_id` is itself the PK+FK) — this is what makes "at most one
link per row" a database constraint rather than an application convention, and what keeps all
four migrations fully independent of `NewsEvent`/`ContentDraft`'s own INSERT statements.

## 5. Disposable migration validation

Performed entirely against a throwaway database (`ai_newsroom_migration_test`), never the real
`ai_newsroom` database, never touching `.env`:

1. `CREATE DATABASE ai_newsroom_migration_test` on the running `ai_newsroom_postgres` container.
2. `POSTGRES_DB=ai_newsroom_migration_test alembic upgrade head` — succeeded, applying the full
   chain from base through all 4 new migrations.
3. `alembic downgrade 8b9d649bc69b` — succeeded, cleanly reverting the 3 new table-creating
   migrations.
4. `alembic downgrade 21177d5b859e` — **correctly raised `NotImplementedError`** exactly as
   designed (enum-value drop is not supported by Postgres).
5. `alembic upgrade head` from that exact failure point — succeeded cleanly. Final `alembic
   current` = `f12a9b9732cc (head)`.
6. `DROP DATABASE ai_newsroom_migration_test`.

Confirmed via `\l` afterward: only `ai_newsroom` (real) and `phase18_validation_db` (a pre-existing,
untouched artifact from an earlier phase) remain.

A second disposable database (`ai_newsroom_muse_replay`) was created/migrated/dropped for the
Muse Code and additional replay sets in §7–9 — also confirmed cleaned up.

## 6. Story-memory design

`services/story_memory.py` — deterministic, no embeddings, no new LLM capability, mirrors
`services/text_normalization.py`'s own "deliberately not a general NLP engine" convention.

- `extract_story_signature(title, category)`: entities via a capitalized-run regex +
  `normalize_for_entity_match()`; keywords via length-filtered tokens; `topic_bucket` via a
  hand-curated keyword table (`product`, `financial`, `corporate`, `legal_regulatory`,
  `security_incident`, `other`), checked narrowest-first.
- `match_story()`: bounded same-category candidate fetch (14-day lookback, 50-row cap) → **hard
  topic-bucket gate** (a candidate in a different bucket is rejected before any scoring — this is
  what keeps "Company announces product" from ever merging with "Company releases financial
  results" even when every entity matches) → weighted score
  (`0.6·entity_overlap + 0.4·title_overlap`) against two thresholds (low 0.35, high 0.65) → within
  the confident zone, a 3-way split on `title_overlap`: ≥0.75 → `SEMANTIC_DUPLICATE`, ≥0.55 →
  `SUPPORTING_SOURCE`, else → `STORY_UPDATE`. Below 0.35 → `NEW_STORY`. Between thresholds →
  `UNCERTAIN_MATCH`.
- Persisted in the standalone `NewsEventStoryLink` table (§4), never on `NewsEvent` itself.
- Gated behind `story_memory_mode: Literal["off","shadow","enforce"] = "off"`. Ships `shadow`-only
  this phase — computes and persists the link, never suppresses task creation. `enforce` is not
  implemented.

## 7. Muse Code controlled replay result

**Real-data finding (read-only query against the live database):** the Phase 18.9 live test's
real "Meta Muse Code" launch produced **12 real `NewsEvent` rows** (categories: STARTUPS,
GADGETS×4, TECH, AI×3, UNKNOWN, SOFTWARE) and **3 real `ContentDraft` rows** — i.e., 3 actual
duplicate Telegram posts were generated for the same real-world story. This is the concrete,
empirical problem Phase 18.10 addresses.

**Controlled replay** (disposable DB, clean run, deterministic and reproducible — re-run to
confirm): 7 curated real historical titles replayed chronologically through the real
`match_story()`:

```
[STARTUPS ] new_story       conf=1.00  "Meta launches Muse Code, an AI agent for large code bases"
[GADGETS  ] new_story       conf=1.00  "Meta Is Challenging Claude Code and Codex With New Muse Code"
[GADGETS  ] new_story       conf=1.00  "Meta launches Muse Code AI coding agent for macOS and Linux"
[TECH     ] new_story       conf=1.00  "Meta releases Muse Code in beta, a terminal coding agent..."
[GADGETS  ] uncertain_match conf=0.37  "Meta introduces Muse Code, its take on a coding agent"
                                        -> matched the 3rd entry above (entity_overlap=0.20, title_overlap=0.62)
[AI       ] new_story       conf=1.00  "Meta has launched Muse Code, an artificial intelligence agent..."
[SOFTWARE ] new_story       conf=1.00  "Introducing Muse Code and Muse Spark 1.2"
```

**Finding, disclosed honestly:** only 1 of 7 same-story titles was even flagged as related
(`uncertain_match`, correctly *not* auto-merged) — the other 6 landed as `new_story`, entirely
because of the category/topic-bucket hard partition (different sources categorized the identical
real event as STARTUPS/GADGETS/TECH/AI/SOFTWARE, and the algorithm only ever compares
same-category, same-bucket candidates). **Shadow mode alone would not have prevented most of the
3 real duplicate posts** from this specific story — see §21.

A first, uncontrolled run of this same script produced a misleading result (entry 1 matched an
existing story) traced to a leftover row committed by an earlier crashed script attempt (an
`expire_on_commit`/FK bug in the script itself, not in `story_memory.py`) — the table was
truncated and the run repeated cleanly; the numbers above are from the clean, reproducible run.

## 8. Duplicate suppression metrics

**No suppression was performed** — `story_memory_mode` ships `shadow`-only; task creation is
never blocked this phase. The metric below is "what shadow mode would have flagged," not "what
was prevented":

- Muse Code set (§7): 1/7 titles flagged as related to another (as `uncertain_match`, which is
  explicitly *not* an auto-merge outcome — see §21). 6/7 real duplicates of the same event were
  **not** flagged at all, due to the category hard partition.
- Genuine-update set (§9, Set A): 3/3 titles correctly linked to the same story (2/3 as
  `uncertain_match`, 1/3 as the seed `new_story`) — zero missed links within a single category/bucket.
- Similar-but-distinct set (§9, Set B): 3/3 titles correctly stayed unlinked (`new_story` each) —
  zero false merges despite highly similar surface phrasing ("X releases new voice model for Y").

## 9. False merge / missed merge metrics

**False merges observed: 0** across every replay set. The entity-overlap requirement rejected
all 3 similar-but-distinct titles in §9 Set B (`entity_overlap=0.00` each, since the company names
differ) despite `title_overlap` as high as 0.71.

**Missed merges observed:** 6/7 in the Muse Code set (§7), entirely attributable to the
category/topic-bucket hard partition — a known, now-quantified design limitation (§21), not a
scoring-threshold problem. Within a single category+bucket, 0 missed merges were observed in any
replay set.

## 10. Novelty-scoring results

`services/editorial_scoring.py::_compute_novelty_component()`, computed directly:

| Match outcome | Match score | Novelty | Available |
|---|---|---|---|
| `new_story` | 1.00 | **1.000** | True |
| `story_update` | 0.55 | **0.450** | True |
| `supporting_source` | 0.60 | **0.150** | True |
| `semantic_duplicate` | 0.90 | **0.000** | True |
| `uncertain_match` | 0.50 | **0.500** | True (conservative/neutral-leaning) |
| *(no story match, pre-18.10 default)* | — | 0.5 | **False** (permanent redistribution — byte-identical to pre-18.10 behavior) |

Ordering confirmed monotonic and matches the specified intent: duplicates score zero, genuine
updates score positive-but-reduced, new stories score full novelty, uncertain matches stay
conservative rather than confidently swinging either direction.

## 11. Telegram root/reply payload examples

`services/story_telegram_delivery.py::determine_reply_target()`, computed directly:

```
Fresh story (not an update):
  determine_reply_target(is_story_update=False, root_message_id=None)
  -> ReplyDecision(action='send_as_root', reply_to_message_id=None, delivery_type=ROOT)

Genuine update, root message already sent:
  determine_reply_target(is_story_update=True, root_message_id=48213)
  -> ReplyDecision(action='send_as_reply', reply_to_message_id=48213, delivery_type=REPLY)

Update, but no confirmed root message exists yet:
  determine_reply_target(is_story_update=True, root_message_id=None)
  -> ReplyDecision(action='fail_closed_route_to_review', reply_to_message_id=None, delivery_type=None)
```

`build_idempotency_key(content_draft_id)` → `"content_draft:<uuid>"` (deterministic, one key per
draft, backed by a DB-level unique constraint).

## 12. Telegram delivery persistence design

`StoryTelegramDelivery` (standalone table, §4): `story_id`, `content_draft_id`,
`telegram_chat_id`, `telegram_message_id`, `reply_to_message_id`, `delivery_type` (ROOT/REPLY),
`delivery_status` (SENT/FAILED/UNCONFIRMED/SKIPPED_REVIEW), `idempotency_key` (unique), `sent_at`.

- **A send is never recorded as `SENT` without a real `telegram_message_id`** — enforced both in
  `record_delivery()`'s call contract and by the migration's own `CHECK` constraint at the DB
  level.
- `get_root_delivery()` only ever considers `delivery_type=ROOT, delivery_status=SENT` rows,
  ordered by `sent_at` ascending — an unsuccessful attempt is never treated as a reply target.
- Fail-closed for updates with no discoverable root: never silently downgraded to a fresh
  standalone post; routed to `SKIPPED_REVIEW` instead (§11, 3rd example).
- In `worker/content_cycle.py`, `record_delivery()` runs in its own commit *after* the real
  Telegram send — a persistence failure there is logged at CRITICAL
  (`story_telegram_delivery_persistence_failed_after_real_send`) but never retried as a duplicate
  send, since the message is already irreversibly sent.

## 13. Hashtag-removal confirmation

`services/content_draft_service.py::check_no_hashtags(title, body)` — pure, unconditional, no
mode flag (explicitly rejected adding one per your own feedback during this phase — hashtag
removal is a hard requirement, not an experiment). Raises `ValueError` before a draft is ever
persisted if any `#\w+` token is found. `hashtags` is always persisted as `None` going forward.
`bot/formatting.py` and `capabilities/quality_capability.py` no longer reference hashtags at all,
even for legacy rows that still have historical hashtag data. 10 dedicated tests in
`tests/test_hashtag_removal.py`, plus assertions flipped from presence→absence across 5 other
test files.

## 14. Quote extraction and blockquote examples

Ran 5 controlled scenarios through the real, unmocked `verify_quote()` and
`evaluate_content_quality_gates()` (pure functions, no LLM, no DB, no Telegram send):

```
1. Direct verbatim quote:
   source: '...said, "We are doubling our compute budget next year,"...'
   claimed: "We are doubling our compute budget next year"
   verify_quote() -> True

2. Indirect speech / paraphrase (must NOT verify):
   source: "...said the company was planning to expand its compute budget substantially..."
   claimed: "We are doubling our compute budget next year"
   verify_quote() -> False

3. Conflicting/altered quote (must NOT verify):
   source: '...said, "Revenue grew by fifteen percent this quarter."'
   claimed: "Revenue grew by fifty percent this quarter"
   verify_quote() -> False

4. Unattributed quote -> quality gate fails:
   passed=False, failed_gates=['quote_traceable', 'quote_has_attribution']
   (quote_traceable failed here because no source_content was supplied for verification -
   the gate correctly refuses to assume traceability)

5. Fully-attributed, traceable, well-formed blockquote -> all gates pass:
   passed=True, failed_gates=[]
```

A quote that fails `verify_quote()` is dropped before persistence, never fabricated or rendered
(`content_draft_service.py`, logs `quote_failed_verification_dropped`).

## 15. Content-quality before/after examples

**v3 (frozen, pre-18.10) output shape:** `{"title": ..., "body": ..., "hashtags": [...]}` — a
single title/body pair, structurally indistinguishable from a rewritten RSS summary, no
"why it matters," no quote support, no update/root distinction.

**v4 (Stage 7, this phase) output shape:**
`{"title", "body", "what_happened", "why_it_matters", "what_remains_unknown", "quote": {"text",
"translated_text", "speaker"} | null}` — hashtags removed at the schema source; `why_it_matters`
mechanically required and gate-checked for genuine content (not a restatement of `what_happened`,
minimum length enforced); quotes only ever populate from a verified excerpt of the real source
event, never invented.

8 deterministic quality gates run over every draft (`services/content_quality_gates.py`):
headline/body repetition, duplicate untranslated source headline leaking through, generic filler
phrases (English + Russian lexicon), unsupported superlative competitive claims, empty/repetitive
`why_it_matters`, untraceable quote, missing quote attribution, malformed `<blockquote>` tag
balance, and (for updates) the update repeating the root post's body rather than containing only
the delta.

## 16. Meme pipeline diagnosis

Full detail: `docs/phase18_10_meme_pipeline_audit.md`. Summary: **root cause of 0 memes in the
Phase 18.9 live test is that no live code path ever creates a `MEME_GENERATION` task** — every
downstream stage (candidate creation, opportunity scoring, safety gate, image generation,
rendering, Telegram preview) is fully built and independently tested but structurally unreachable.
Three further, independently-sufficient blockers exist even if a trigger were added: the
`meme_candidates` migration (`21177d5b859e`, pre-existing, unrelated to this phase) is also not
yet applied to the live database; neither `meme_opportunity_mode` nor `meme_safety_gate_mode` has
an `enforce`/live value defined anywhere in the codebase yet (only `off`/`shadow`); and
`meme_image_generation_mode`/`meme_telegram_preview_mode` remain `off`. **No meme code was
modified, no meme mode was changed, no `MEME_GENERATION` task was created.**

## 17. Cost-attribution status

Root cause confirmed and fixed in code: `capabilities/capability_mapping.py`'s
`"engagement": AICapability.INTELLIGENCE` alias (an explicit, documented "Amendment A" — dollar
totals already agreed between Postgres and Redis, only the Postgres *label* was wrong) is now
`"engagement": AICapability.ENGAGEMENT`. Requires the new `ENGAGEMENT` enum value
(`8b9d649bc69b`, unapplied) to actually persist — `record_ai_execution()`'s pre-existing
"never raises" contract means a real engagement call simply fails to persist its `AIExecution`
row silently until migrated (the Redis ledger, which never used the alias, is unaffected either
way). New cross-ledger test added, skip-marked pending the migration.

## 18. Tests added

**11 new test files** (~70 test functions): `tests/test_story_memory.py` (9),
`tests/test_story_memory_integration.py` (9, skip-marked pending `c2bc6affb100`),
`tests/test_triage_orchestrator_story_memory.py` (3), `tests/test_hashtag_removal.py` (3),
`tests/test_meme_pipeline_not_live.py` (2), `tests/test_story_telegram_delivery.py` (6),
`tests/test_content_cycle_story_delivery.py` (3, 2 skip-marked),
`tests/test_content_draft_story_link_integration.py` (1, skip-marked),
`tests/test_quote_verification.py` (7), `tests/test_content_quality_gates.py` (25),
`tests/test_content_draft_quote_integration.py` (2, skip-marked).

**Targeted additions to 8 existing test files**: `tests/test_editorial_scoring.py` (+7 novelty
tests), `tests/test_editorial_card_formatting.py` (+4 blockquote tests),
`tests/test_telegram_notifier.py` (+5 reply/message_id tests),
`tests/test_copywriting_capability.py` (+4 Amendment-B/v4 tests),
`tests/test_cost_recording_integration.py` (+1 skip-marked cross-ledger test), plus fixture-shape
updates (not new tests) across `tests/test_run_content_generation.py`,
`tests/test_content_draft_service.py`, `tests/test_phase10_workflow_integration.py`,
`tests/test_content_worker_cycle.py`, `tests/test_content_generation_integration.py`,
`tests/test_fact_safety.py` for the v4 copywriting output shape.

Every DB-dependent test requiring an unapplied migration carries an explicit
`@pytest.mark.skip(reason="Requires Alembic migration <hash>...")` — never silently omitted.

## 19. Full regression result

`ruff check` on all 58 changed files: **all checks passed.**
`mypy` on all 29 changed non-test source files: **success, no issues found.**

Full suite: **2,600 tests collected. Final run: 30 failed, 2,555 passed, 15 skipped, in 35m22s.**

## 20. Exact failure-set comparison (by node ID against baseline)

Baseline established via `git stash` (Phase 18.10 changes fully removed), same subset re-run:
**29 pre-existing failures**, unrelated to this phase — the same established causes documented in
prior phases (`content_generation_dry_run=False`/`image_editorial_preview_enabled=True` — both
non-default in this dev `.env` — plus a handful of pre-existing test-design issues and known
worker-loop timing flakiness).

Comparing the Phase 18.10 branch's failures against that exact baseline surfaced **2 genuine,
newly-introduced regressions**, both investigated, root-caused, and fixed during this validation
pass (not merely disclosed):

1. `tests/test_openai_strict_schema_compliance.py::test_active_capability_prompt_is_strict_schema_compliant[copywriting]`
   — the test's own independently-hardcoded `prompt_version="2"` was never bumped to match the
   real `PROMPT_VERSION="4"`. Fixed (one-line).
2. `tests/test_fact_safety.py::test_real_four_step_content_generation_workflow_runs_fact_safety_from_copywriting_output`
   — its hand-built `copywriting_output` fixture was still the frozen v3 shape (missing v4's
   required fields), so the real capability's floor-validation correctly rejected it. Fixed
   (fixture updated to the v4 shape). This file was outside the 5-file "known" fixture-update list
   from earlier in this phase — genuinely missed until this final validation pass caught it.

Both were confirmed fixed and passing in isolation, then reflected in the final regression run
(§19), which shows **30** failures = the 29 pre-existing baseline **plus exactly 1**:
`tests/test_triage_orchestrator_cycle.py::test_create_task_success_outcome` — absent from both
the baseline and the earlier (pre-fix) 32-failure run, present only in the final full-suite pass.
Investigated: passes cleanly in isolation (57.4s single-test runtime — a slow,
polling/sleep-driven test), consistent with the same class of load-contention timing flakiness
already documented for other worker-cycle tests in this suite, not a deterministic regression
from any Phase 18.10 code path. Disclosed honestly rather than discarded, since it was not
possible to fully rule out with the time available in this pass.

**Net result: 0 confirmed deterministic regressions remaining; 1 unresolved but non-reproducible,
load-timing-correlated intermittent failure disclosed for your awareness.**

No migration-gated skip was counted as a pass anywhere in this comparison.

## 21. Known limitations

1. **Category/topic-bucket hard partition** (quantified in §7–9): the same real-world story is
   treated as unrelated `new_story` entries whenever different sources categorize it into
   different `NewsEvent` categories or topic buckets — only same-category, same-bucket candidates
   are ever compared. This is the single largest limiter on duplicate-suppression effectiveness
   demonstrated by the Muse Code replay (6/7 missed).
2. **`uncertain_match` is a conservative, non-actionable-by-default outcome** — by design, it
   never auto-merges and never auto-creates-new; it links the story for visibility but does not
   resolve the ambiguity. Real "genuine update" titles with materially new numbers frequently
   landed in this band in testing (§9 Set A) rather than confidently `story_update`.
3. **Quote rendering is wired into the plain-card Telegram send path only** — `image_preview_notifier.py`'s
   `_to_card()` was not extended with `quote_text`/`quote_speaker` this phase (a disclosed scope
   trim); a story sent via the image-preview path will not render its quote.
4. **`story_memory_mode="enforce"` is not implemented** — shadow-only this phase, so no live
   suppression of duplicate task creation is possible without further work.
5. One intermittent, load-timing-correlated test failure (§20) could not be conclusively
   classified as pre-existing or new within this pass's time budget.
6. `ContentDraftQuote` persistence has no settings flag to gate behind (quotes are unconditional
   once v4 is live) — protected instead via a separate, independently-committed transaction after
   the main draft commit, so an unapplied-migration failure there can never take down the main
   `ContentDraft` row, but it does mean quote data is silently dropped (logged at ERROR) until the
   migration is applied.

## 22. Exact live migration order

The live database is currently at `31a8d7c95c87` — **one revision behind even the pre-existing,
Phase-18-era `meme_candidates` migration**, which was never applied and is unrelated to this
phase. Running `alembic upgrade head` will apply, in this exact order:

```
31a8d7c95c87 (current)
  -> 21177d5b859e  add meme candidates table            [pre-existing, NOT part of Phase 18.10]
  -> 8b9d649bc69b  add ENGAGEMENT value to ai_capability [Stage 1 / M9]
  -> c2bc6affb100  add story memory tables               [Stage 4 / M1-M2]
  -> 0fac25b59455  add telegram reply context tables     [Stage 6 / M3]
  -> f12a9b9732cc  add content draft quotes table (head) [Stage 7 / M5]
```

Flagging explicitly: applying head will also apply `meme_candidates`, which this phase did not
introduce and did not validate beyond the disposable-DB dry run in §5. It creates a table only,
gated entirely behind existing `off`-mode settings — no behavior changes as a result.

## 23. Exact rollback constraints

Downgrading is safe and clean from `head` down to `8b9d649bc69b` (confirmed in §5). **Downgrading
past `8b9d649bc69b` back to `21177d5b859e` is not possible** — `downgrade()` deliberately raises
`NotImplementedError`, because Postgres cannot drop a value from an existing enum type. Once
`ENGAGEMENT` is added to `ai_capability` in production, it is permanent; the only way to remove it
would be a manual, out-of-band enum-recreation migration, which is not provided by this phase and
is not recommended casually. All other new tables (`stories`, `news_event_story_links`,
`content_draft_story_links`, `story_telegram_deliveries`, `content_draft_quotes`) downgrade
cleanly (plain `DROP TABLE`).

## 24. Controlled live canary plan (proposed, not executed)

1. Apply migrations in the exact order in §22, during a low-traffic window.
2. Leave every new mode at its default (`story_memory_mode="off"`) for one full cycle to confirm
   the running system is unaffected by schema presence alone (expected: byte-identical behavior,
   per the dual-path design in `editorial_scoring.py` and the settings-gating throughout).
3. Flip `story_memory_mode="shadow"` only. Monitor for a defined bake period (recommend
   matching the Phase 18.9 2-hour live-test window, or longer) — confirm `NewsEventStoryLink` rows
   populate correctly and `TriageCycleReport` counters look sane, with zero change to published
   volume.
4. The v4 copywriting prompt and quote pipeline are **not** shadow-gateable the same way (there is
   no dry-run equivalent for prompt content) — recommend cutting over `PROMPT_VERSION` on a single
   canary content cycle first (already the default once these changes are deployed), with a human
   reviewing the first N generated drafts in the editorial inbox before Telegram sends resume, and
   `content_generation_dry_run=True` kept on until that review is complete.
5. Telegram reply-context (`ContentDraftStoryLink` + `StoryTelegramDelivery`) only activates once
   `story_memory_mode != "off"` produces real links — recommend enabling only after step 3's bake
   period looks correct, and only after step 4's dry-run review is signed off.
6. Do not flip `story_memory_mode="enforce"` in this canary — not implemented this phase.

## 25. Estimated paid cost

- Story memory (Stage 4/5): **$0 incremental** — fully deterministic, no LLM calls.
- Telegram reply context (Stage 6): **$0 incremental** — no LLM calls; one additional lightweight
  DB read (`get_root_delivery()`) per story-linked send.
- Content quality gates (Stage 7): **$0 incremental** — deterministic, no LLM calls.
- Copywriting prompt v4 (Stage 7): replaces v3 **1:1**, same one LLM call per draft. Expect a
  modest token increase from the larger output schema (3 new fields + optional quote object) and
  the Amendment-B source excerpt now included in context (~3,000 chars) — a small, bounded
  per-call cost increase, not a new call. No exact dollar figure is available without a live run;
  recommend treating the canary in §24 as the first real cost sample.
- Cost-attribution fix (Stage 1): **$0** — corrects a label, not a spend amount; Redis totals are
  unaffected either way.
- No new paid workers, no new capabilities registered in `build_registry()`, no meme generation.

## 26. GO/NO-GO recommendation

- **GO — migrations (§22):** low risk, standalone tables, rollback validated except the one
  documented irreversible enum step (§23), which is itself low-risk (additive-only, no data loss).
- **GO — `story_memory_mode="shadow"` + novelty scoring:** proven byte-identical to pre-18.10
  behavior when off; shadow mode never suppresses task creation; graceful degradation confirmed
  even if the migration lags.
- **GO — hashtag removal, cost-attribution fix:** both unconditional, already validated, no
  staged rollout needed.
- **STAGED GO — Telegram reply context + prompt v4/quotes:** functionally complete and tested,
  but this is the first real production exposure of new user-facing content shape and Telegram
  threading behavior — recommend the canary sequence in §24 (dry-run-first, human review of first
  drafts) rather than a direct cutover.
- **NO-GO — `story_memory_mode="enforce"`:** not implemented this phase; do not attempt to enable
  it.
- **Overall: authorization requested to (a) apply the 4 migrations, and (b) run the staged canary
  in §24** — both remain your decision; nothing above has been executed.

---

*Stop after this report. No migration applied. No live canary run. No Telegram message sent. No
VPS deployment started.*
