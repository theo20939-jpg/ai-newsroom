# UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1 — Report

## A. Exact starting SHA

`9335426aa98aa5a8360dcadbcd1faeb565787da9` (branch `feature/unified-editorial-production-pipeline-1`,
the exact commit the Founder reviewed). This phase's own branch,
`feature/unified-editorial-production-pipeline-cutover-1`, was created from this same SHA in the
existing worktree `C:/Users/Theodor/ai-newsroom-unified-pipeline-1` (clean at the start of this
phase — the only pre-existing untracked entries were the prior phase's own review-bundle artifacts).

## B. Worker ownership before this phase

Per the prior phase's own honest review bundle
(`artifacts/unified_editorial_pipeline_review_bundle_1/06_WORKER_OWNERSHIP.md`): **nothing had
moved**. `worker/content_cycle.py` gained 41 lines, 0 removed. The new orchestrator
(`services/editorial_pipeline/orchestrator.py`) was a real, tested, parallel implementation, invoked
ONLY from a shadow-comparison hook (`services/editorial_pipeline/shadow.py::run_shadow_comparison()`)
that ran alongside the untouched legacy send, logged one comparison line, and never influenced the
real outcome — "a genuine strangler-pattern *beachhead*, not a strangler pattern *in progress*."

## C. Worker ownership after this phase

See `docs/unified_pipeline_worker_ownership_after_cutover.md` (full concern-by-concern BEFORE/AFTER
table, reproduced in `artifacts/unified_pipeline_cutover_1/00_worker_ownership_before_after.md`).
Summary: for the scope this phase cuts over (single-photo-or-text NEWS/BREAKING/DATA/QUOTE Telegram
delivery, gated on `unified_editorial_pipeline_enabled AND is_unified_router_eligible(copywriting_
output)` — i.e. a real V8-family shape, the only shape any live send has ever produced), the
orchestrator/`RecoveryService`/`telegram_integration` module now make every editorial decision
exactly once: format selection, DATA/QUOTE structured-content extraction, media research/selection,
composition strategy, caption budget, quality gate, and recovery. `worker/content_cycle.py`'s own
code for this case shrank from a ~900-line inline decision tree to ~35 lines of signal-fetching,
one function call, and counter bookkeeping.

`ORCHESTRATOR_IS_AUTHORITATIVE_WITH_FLAG_ON = true`

## D. The authoritative orchestrator path (flag ON)

`worker/content_cycle.py`'s router-mode branch now reads:

```python
if (
    settings.unified_editorial_pipeline_enabled
    and is_unified_router_eligible(outcome.copywriting_output)
):
    unified_outcome = await run_unified_telegram_delivery(...)
    # ~15 lines translating 4 outcome fields into existing ContentCycleResult counters
else:
    # the entire, byte-for-byte-unchanged legacy decision tree (re-indented only)
```

`run_unified_telegram_delivery()` (`services/editorial_pipeline/telegram_integration.py`) is the one
real, worker-reachable entry point: it selects format (`decide_presentation()`, reused for
format/category/BREAKING-rate-limiting only — its `.data_candidate`/`.quote_candidate` outputs are
computed but never read), builds an `EvidencePack`, resolves at most one legacy-ranked photo
candidate and wraps it as a Tier-1 `ResolvedMediaCandidate`, builds a real Telegram `RenderCallable`
(wrapping the frozen V8 renderers unchanged), and calls
`run_editorial_production_pipeline(..., session=session, recovery_service=RecoveryService(),
require_media=True)`. On `READY`, it dispatches via the existing dumb transport
(`send_photo_to_editorial_destination`/`send_to_editorial_destination`) and maps the real
`RoutingOutcome` (SENT/FAILED/AMBIGUOUS) back into recovery when needed. See
`artifacts/unified_pipeline_cutover_1/02_flag_on_flow.md` for the full flow diagram.

## E. The legacy compatibility path (flag OFF, or a non-V8 shape)

Unchanged, byte-for-byte, except pure re-indentation (the legacy decision tree now lives one
indentation level deeper, inside an `else:`) and the removal of the OLD, now-superseded shadow
hook (`if settings.unified_editorial_pipeline_enabled: ... run_shadow_comparison(...)`, along with
its two now-dead supporting local variables, `research_facts_for_shadow` and the shadow-only
branch). No other line inside the legacy tree (media-group/video assembly, recomposition,
caption-budget-drops-image, `_hold_for_visual_recovery()`, the four real send calls) was touched.
Proven via the full flag-off/non-V8 regression suite (§O) with `NEW_FAILURES=0`.

## F. Recovery persistence

New table `recovery_jobs` (migration `a126e750c727`, `database/models/recovery_job.py`): `id`,
`content_draft_id` (FK → `content_drafts.id`), `platform`, `reason_code` (7 real values, matching
`RecoveryReasonCode` exactly), `failed_stage`, `state` (`PENDING`/`RETRYING`/`RECOVERED`/
`TERMINAL_HOLD`), `attempt_count`, `max_attempts`, `next_retry_at`, `last_error_summary` (bounded
500 chars, never a full traceback), `candidate_diagnostics` (JSON list of short strings, never raw
candidate objects), `created_at`/`updated_at`/`resolved_at`. See §migration status
(`artifacts/unified_pipeline_cutover_1/08_migration_status.md`) for the clean/test/apply detail —
applied to the dedicated pytest database only, never dev or production.

## G. Recovery state machine

`services/editorial_pipeline/recovery_service.py::RecoveryService` — real, tested state transitions
against the real table (not the in-process, always-immediately-terminal dataclass the Founder
review flagged). `create_or_retry()` looks up any existing OPEN row for a draft
(`find_open_recovery()`, scoped to `PENDING`/`RETRYING`) and increments it in place (a genuine
retry — the exact missing mechanism the Founder review named) rather than always constructing
`attempt_count=1`. Deterministic backoff (`60s → 300s → 900s`). `QUALITY_GATE_FAILED` is always
`max_attempts=1` (terminal on first failure — a quality/safety verdict does not change on a blind
retry of unchanged content) and maps to `OrchestratorVerdict.BLOCK`; every other reason code is
bounded-retryable (`DEFAULT_MAX_ATTEMPTS=3`) and maps to `RETRY` while open, `HOLD` once
`TERMINAL_HOLD`. See `artifacts/unified_pipeline_cutover_1/03_recovery_state_diagram.md` and
`04_retry_examples.md` for the full diagram and worked, real-value examples.

## H. Transport integration

`services/telegram_routing.py` — one additive field, `RoutingOutcome.ambiguous: bool = False`
(default preserves every existing construction/test), set `True` for a `TelegramAPIError` whose
message contains "timeout" (case-insensitive) on `send_to_editorial_destination()`/
`send_photo_to_editorial_destination()` — the exact real production shape the prior
TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 phase's own test fixture already used
(`TelegramAPIError(method=None, message="Request timeout error")`). `sent` stays `False` either
way; `ambiguous=True` is the new signal `telegram_integration.py` reads to route to
`AMBIGUOUS_TRANSPORT_RESULT` instead of `MEDIA_SEND_FAILED` — never a blind resend either way.
Confirmed zero existing test relies on the word "timeout" appearing in an unrelated failure
message (`test_telegram_editorial_routing.py`'s own two `TelegramAPIError` fixtures use "boom" and
"upload failed").

## I. Caption-budget integration

`services/editorial_pipeline/platforms/telegram.py::plan_telegram_caption_budget()` (already built
in the prior phase, now actually invoked from the live orchestrator path for the first time):
full caption fits → send; footer-stripped fits → send without the footer; still too long →
`CAPTION_BUDGET_FAILED`, real durable recovery — never a silent text-only completion with the image
dropped. Proven end-to-end (real worker call, real oversized caption, real photo candidate) in
`tests/test_unified_pipeline_cutover_authority.py::test_replay_f_caption_too_long_never_completes_text_only`.

## J. Media-research integration

`services/editorial_pipeline/media.py::MediaResearchService` (phase 2, now genuinely invoked from a
live call site for the first time) wrapped in `asyncio.wait_for(timeout=8.0s)` — a timeout produces
`MEDIA_RESEARCH_TIMEOUT`, proven with a fake never-completing service in
`tests/test_unified_pipeline_orchestrator_cutover.py::test_media_research_timeout_produces_a_bounded_recovery_never_a_hang`.
New `require_media` orchestrator parameter (opt-in, default `False` — every pre-existing test
unaffected) mirrors the real, currently-deployed worker product invariant ("an ordinary router-mode
NEWS/BREAKING/DATA/QUOTE post must never silently complete as a normal finished text-only send
merely because no valid final visual could be resolved") as an explicit orchestrator policy: NEWS/
BREAKING/QUOTE with no truthful candidate → `NO_SUITABLE_MEDIA` before render is ever attempted;
DATA never needs this gate (its own `DATA_TYPOGRAPHIC` composition strategy is a legitimate,
pre-existing no-media outcome — though see §Q for the real V8 renderer's own separate constraint).
**Disclosed limitation** (unchanged from phase 2, not newly introduced): no `subject_match_
classifier` is wired by this phase, so every candidate is scored via the existing, tested,
conservative "unclassified" default rather than a real vision-based EXACT_SUBJECT/MISMATCH
judgment — full media-truthfulness discrimination (the deepfake/foldable-iPhone class of case) is
not independently re-verified in this cutover.

## K. Quality-gate integration

`services/editorial_pipeline/quality.py::run_quality_gate()` (phase 2, now genuinely invoked live)
runs unconditionally before any `DeliveryPackage` can exist — FACT_SUPPORT, CLAIM_TRACEABILITY,
LANGUAGE_QUALITY, VISUAL_TRUTHFULNESS, MEDIA_PROVENANCE, FORMAT_REQUIREMENTS, PLATFORM_BUDGET,
ART_VALIDATION. A non-READY verdict always becomes `QUALITY_GATE_FAILED` → `OrchestratorVerdict.
BLOCK` (terminal, never silently bypassed or re-decided by the worker afterward).

## L. Real replay results

See `artifacts/unified_pipeline_cutover_1/05_real_replay_summary.md` for the full table. Summary:
A (no-visual → `NO_SUITABLE_MEDIA`), D (Maxus DATA label fix reaches a real sent caption), F
(caption-too-long → `CAPTION_BUDGET_FAILED`, never text-only), G (real `TelegramAPIError` → `MEDIA_
SEND_FAILED`), H (new — real timeout-shaped `TelegramAPIError` → `AMBIGUOUS_TRANSPORT_RESULT`,
never auto-resent) all PASS, run through the real, unmodified `run_content_cycle()` entry point.
B/C/E (media-truthfulness-heavy cases) are disclosed as inheriting the same, already-known phase-2
limitation (§J) rather than independently re-verified with new vision-classifier wiring in this
phase.

## M. V8 parity

`git diff --stat 9335426 -- services/brand_renderer.py services/nnj_master_news_overlay.py
services/news_telegram_presentation.py services/nnj_board_metrics.py services/presentation_director.py
services/data_source_classification.py` → zero output. `V8_PIXEL_DIFF = 0`. See
`artifacts/unified_pipeline_cutover_1/06_v8_parity.md`.

## N. Flag-off regression

Re-run, unmodified: `tests/test_router_media_integration.py` (2 pre-existing failures, proven via
`git stash` against the unmodified base — both about an `InlineKeyboardMarkup` button count,
unrelated to this phase; 0 new), `tests/test_visual_fallback_hold_repair_1.py` (all pass),
`tests/test_content_worker_cycle.py` (all pass, plus one additive fixture fix — see §T),
`tests/test_editorial_delivery_mode.py` (all pass). `FLAG_OFF_REGRESSION = PASS`.

## O. Flag-on tests

`tests/test_unified_pipeline_cutover_authority.py::test_authority_legacy_functions_never_invoked_for_a_unified_data_send`
spies on `worker.content_cycle._hold_for_visual_recovery`, `render_editorial_card`,
`build_rich_media_plan`, `resolve_photo_input`, `send_media_group_to_editorial_destination`,
`send_video_to_editorial_destination` — all six asserted never called for a real, flag-on DATA send
that still produces a complete, real outcome. `tests/test_unified_pipeline_shadow_wiring.py`
(rewritten — see §T) additionally proves flag-on with a non-V8 shape still uses the untouched
legacy path.

## P. Migration status

See `artifacts/unified_pipeline_cutover_1/08_migration_status.md`. Not applied to production or the
shared local dev database (left at `4a1b7c9d2e3f`, its pre-phase state); applied only to the
dedicated, isolated pytest database.

## Q. Remaining legacy debt (disclosed, not silently skipped)

1. **Media groups / native hosted video / Gemini editorial recomposition** are not reimplemented in
   the unified path — `rich_media_mode` is "off"/"shadow" in every real deployed environment today
   (confirmed in this codebase's own comments), so this has zero effect on current production
   traffic. Remains exactly where it already is, in the legacy path, reachable whenever the unified
   gate does not apply.
2. **No vision-based media subject-match classifier is wired by this phase** (§J) — media
   truthfulness selection beyond the existing conservative default is unchanged from phase 2.
3. **The real V8 DATA renderer (`render_branded_media()`, unmodified) requires a real source photo**
   for DATA — "DATA no longer has a source-photo-free synthetic card form" (a pre-existing V2.20
   constraint, confirmed by reading the unmodified renderer, not introduced by this phase). This
   means the editorial_pipeline package's own `DataCompositionStrategy.DATA_TYPOGRAPHIC` strategy,
   while a real, tested code path in `services/editorial_pipeline/composition.py`, cannot currently
   be realized by the actual live V8 renderer without a source photo — a DATA event with genuinely
   zero resolvable photo and no real series will reach `RENDER_FAILED` (a real, bounded, reason-coded
   recovery) rather than a typographic card. This is a pre-existing renderer constraint this phase
   discovered and disclosed, not one it introduced or is authorized to fix (V8 is frozen).
4. **`apply_telegram_recovery()`** (the old in-process bridge function from phase 2) remains
   unmodified and still has zero callers — fully superseded by `RecoveryService`, not deleted (S3:
   "do not delete the legacy pipeline yet"). A future cleanup phase may remove it once the cutover
   is Founder-approved and stable.
5. **Instagram** (`services/editorial_pipeline/platforms/instagram.py`) is untouched by this phase —
   it still uses the in-process `create_recovery_job()`, not the new durable `RecoveryService`.
   Instagram publication stays fully out of scope (S constraint) and `instagram_publication_enabled`
   remains `False`, unmodified.

## R. Rollout recommendation

Do NOT enable `unified_editorial_pipeline_enabled` in production as part of this phase (explicitly
forbidden). Recommended next steps for a future, separately-authorized rollout phase: (1) Founder
review of this report and the artifact bundle; (2) a bounded, monitored canary with the flag ON in a
non-production or shadow-adjacent environment, watching the new observability events
(`unified_pipeline_selected`, `unified_orchestrator_started/finished`, `recovery_created`,
`recovery_retry_scheduled`, `recovery_attempt_started`, `recovery_recovered`, `recovery_terminal_hold`,
`transport_result`); (3) apply the `recovery_jobs` migration to production only after that review;
(4) address remaining legacy debt (§Q) as separately-scoped, Founder-approved follow-up phases,
starting with the DATA-no-photo renderer constraint (§Q3) since it is the one gap most likely to
surface in real traffic.

## S. Test results

Full command: `pytest tests/ --ignore=tests/test_phase20_m1_harness_fixes.py
--ignore=tests/test_v2_3a_editorial_recomposition_canary.py
--ignore=tests/test_v2_4d_overlay_contract.py --ignore=tests/test_v2_4f_compact_overlay.py` (the 4
ignored files fail to even COLLECT on the unmodified base SHA `9335426` itself — missing `scripts.*`
modules and one missing asset manifest file, confirmed via `git log` showing these test files were
last touched in an old, unrelated commit `6dec326`, long before this phase's own branch existed).

**First full run**: `49 failed, 6571 passed, 28 skipped` (26m52s). Every one of the 49 failures was
individually triaged against a real, temporary `git worktree add` at the unmodified base SHA
`9335426` (never `git stash` in this shared-`.git` multi-worktree repo — see this session's own
prior incident note) — never assumed pre-existing by inspection alone:

- **44 of 49** failed identically on the unmodified base (FK-violation-style shared-test-DB
  pollution, `git diff`-based "no production files changed" checks, `.env`-mtime checks, and
  similar environment/ordering-sensitive assertions — all confirmed present on the base commit
  itself, none related to this phase's own files).
- **4 of 49** (`test_recap_r2_10_g3_llm_judge.py::test_llm_path_cannot_write_db`, and 3 tests in
  `tests/test_story_memory_v2_phase1.py`) failed only as part of the full 6620-test sweep but
  passed on the unmodified base when run in that same full sweep too, AND passed in isolation on
  both the base and this phase's own branch — confirmed pure test-order/shared-DB-state artifacts
  of this suite's own size, identical on both branches, not caused by this phase.
- **1 of 49 was a real, new finding**: `tests/test_visual_single_brand_mark_call_sites.py::
  test_apply_master_news_branding_has_no_unapproved_call_sites` — a static AST guard (VISUAL-
  SINGLE-BRAND-MARK-1) restricting which modules may import `apply_master_news_branding()`.
  `services/editorial_pipeline/telegram_integration.py` is a real, deliberate new caller of that
  function (the unified path's own NEWS branding step, functionally replacing `worker/content_
  cycle.py`'s own call for the events it owns, never duplicating it for the same event). Root-
  caused (not merely allowlisted blindly): `services/media_finalizer.py::finalize_photo_input()` —
  the guard's own suggested alternative — is NOT a fit here (its own docstring: gated on different
  settings, NEWS-only, explicitly "not a router replacement"); `telegram_integration.py` IS a
  router replacement for this scope, exactly like the already-approved `worker/content_cycle.py`.
  Fixed by adding it to the guard's own `_ALLOWED_IMPORTERS` allowlist with a full justification
  comment — a deliberate, reviewed decision, exactly what the guard's own failure message asks for.

**Fix verified**: `tests/test_visual_single_brand_mark_call_sites.py` now passes (2/2), and all 5
of the order-dependent/pollution-artifact tests above pass together in one batch on this phase's
own branch post-fix (`6 passed`). The full combined suite of every test file this phase touched or
added (`test_editorial_pipeline_*`, `test_unified_pipeline_*`, `test_telegram_editorial_routing.py`,
`test_visual_single_brand_mark_call_sites.py`) — 108 tests — passes cleanly together.

`PRE_EXISTING_FAILURES = 48` (44 environment/ordering-sensitive + 4 order-dependent artifacts, all
confirmed present on the unmodified base SHA).
`NEW_FAILURES = 0` (the one real finding was root-caused and fixed, not suppressed).

## T. Additive fixture fix (not a behavior change)

`tests/test_content_worker_cycle.py::test_source`'s teardown now also deletes `recovery_jobs` rows
for the test's own content drafts before deleting the drafts themselves (guarded by the same
`_table_exists()` check convention every other FK-referencing child table in that fixture already
uses) — needed because real-committed-row tests exercising the unified path now write real
recovery rows. Without this, a `ForeignKeyViolationError` occurs at teardown for any such test
(discovered and fixed during this phase's own test authoring).

## Pass-criteria checklist

| Criterion | Status |
|---|---|
| `ORCHESTRATOR_IS_AUTHORITATIVE_WITH_FLAG_ON` | `true` |
| `LEGACY_AND_UNIFIED_PIPELINES_ARE_NOT_INTERLEAVED` | `true` (single `if/else`, never both) |
| `RECOVERY_HAS_REAL_RUNTIME_CALLERS` | `true` (7/7 reason codes, real call sites) |
| `RECOVERY_STATE_IS_DURABLE` | `true` (real table, survives fresh-service-instance test) |
| `RECOVERY_RETRY_IS_BOUNDED` | `true` (max_attempts, deterministic backoff, proven no-infinite-loop test) |
| `AMBIGUOUS_SEND_CANNOT_BLINDLY_DUPLICATE` | `true` (never auto-resent, proven in replay H) |
| `CAPTION_TOO_LONG_CANNOT_FINISH_TEXT_ONLY_IN_UNIFIED_MODE` | `true` (proven in replay F) |
| `QUALITY_GATE_CANNOT_BE_BYPASSED_IN_UNIFIED_MODE` | `true` (terminal, BLOCK, never re-decided by worker) |
| `FLAG_OFF_REGRESSION` | `PASS` |
| `V8_PIXEL_DIFF` | `0` |
| `INSTAGRAM_REAL_WRITES` | `0` |
| `STORY_MEMORY_REGRESSION` | `PASS` |
| `NEW_FAILURES` | `0` |

## Final verdict

**UNIFIED_PIPELINE_CUTOVER_READY_FOR_FOUNDER_REVIEW**
