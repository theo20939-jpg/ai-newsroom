# INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1 — Development Report

Base: `0cae684` (`feature/instagram-telegram-editorial-delivery-1`). Branch:
`feature/instagram-automatic-editorial-trigger-1`. No Instagram Graph API call anywhere in this
phase. Both publication flags remain `false` throughout. No new DB migration - the existing
`instagram_editorial_deliveries` table/idempotency mechanism is reused verbatim.

## A. Incident/root cause

Per INSTAGRAM-TELEGRAM-EDITORIAL-FLOW-MISSING-1: the pipeline was never broken - it simply had no
automatic trigger. The only real (non-test) caller of `deliver_instagram_package()` was a
manually-invoked one-off script. This phase closes that gap.

## B. Existing manual entry point

Traced `scripts/_instagram_telegram_delivery_canary_{1,2}.py`'s exact call chain: `ContentOpportunity`
→ `FormatDecision` (hardcoded SINGLE) → `InstagramSingleCreative` (hand-authored, no real LLM call)
→ `build_instagram_content_package()` → `render_instagram_feed_image()` → `validate_instagram_art()`
→ `evaluate_instagram_editorial_gate()` → `present_single()` → `build_package_snapshot()` →
`deliver_instagram_package()`. Per §5, this chain was NOT copy/pasted - `services/
instagram_automatic_trigger.py::evaluate_and_submit_instagram_candidate()` is the one real,
reusable service-layer function both the worker and (if ever needed again) a manual script now
call, and it uses a REAL Creative Director call instead of a hand-authored creative.

## C. Chosen automatic trigger

A new, completely independent step inside `worker/content_cycle.py::run_content_cycle()`
(`_run_instagram_automatic_trigger()`), invoked once per cycle immediately after the existing
`event_ids = await _select_eligible_events(session)` scan - reusing that SAME already-bounded,
already-fresh, already-reviewed eligible-event list, never a second/divergent query.

## D. Why this trigger point is correct

- `_select_eligible_events()` already guarantees: `EditorialTask.status == COMPLETED`,
  `workflow_name == NEWS_ANALYSIS`, `updated_at >= cutoff` (a real, existing, reviewed freshness
  bound - `content_generation_freshness_cutoff_hours`, default 24h) - i.e. "sufficiently complete
  and evidence-grounded" (§6) is already true for every event_id in this list, by construction.
  Nothing here needed reinventing.
- The Instagram loop is completely separate from the main NEWS content-generation loop that
  follows - Instagram submission never depends on Telegram NEWS delivery succeeding, and a failure
  in either loop cannot affect the other (§6's own explicit "do not couple" instruction).
- `editorial_delivery_mode` (legacy/router) - the setting that gates whether NEWS itself computes
  a treatment decision today - is irrelevant to this trigger: `_classify_event_for_router_
  treatment()` is called directly and unconditionally for the Instagram evaluation, regardless of
  which mode governs NEWS's own presentation.

## E. Candidate selection reuse (§2/§3 - no new thresholds)

Eligibility is exactly one check: `classify_editorial_treatment()` (Phase 23.1H/23.1P, the SAME
real, already-reviewed significance/evidence classifier NEWS itself uses in router mode) returns
`MAJOR`. `STANDARD`/`BRIEF`/`SKIP` are never submitted. No new score, no new percentile cutoff, no
new topic weight was introduced anywhere in this phase - `_ELIGIBLE_TREATMENTS = (MAJOR,)` is the
entire selection policy, and it is a direct reuse of an existing tier. Format is always SINGLE,
via the real, existing `evaluate_format_shadow(objective=REACH, has_video_asset=False,
has_multi_step_narrative=False)` - its own deterministic logic always resolves this exact input to
SINGLE, so no new format heuristic was written either (§15 - visual behavior is completely
unchanged).

**Disclosed gap**: this codebase has no existing "carousel-worthy" or "reel-worthy" structural
signal for a plain NEWS story (`has_multi_step_narrative`/`has_video_asset` have no real producer
for NEWS content yet) - per §3's own instruction, this is exposed here rather than invented. Every
automatic package this phase produces is a SINGLE post.

## F. Idempotency

Zero new tables. `services.instagram_editorial_delivery_state.compute_package_identity(source_key
=event_id, content_format="single")` + the EXISTING `instagram_editorial_deliveries` partial-unique
`package_identity` index (built in the prior phase) is the entire idempotency mechanism -
`evaluate_and_submit_instagram_candidate()` checks `find_current()` BEFORE any Creative Director
call (so a re-submitted story never even costs an LLM call), and the actual delivery is still
protected by the same DB-enforced guarantee under a race, exactly as before.

## G. Crash/restart behavior

- **Per-story**: `evaluate_and_submit_instagram_candidate()` catches
  `CreativeDirectorUnavailableError`/`UngroundedEvidenceError`/`CreativeFactSafetyError` and any
  unexpected exception, returning a rejected outcome rather than propagating - one story's failure
  never blocks the rest of the batch.
- **Per-cycle**: `_run_instagram_automatic_trigger()` wraps each event's full evaluate-and-submit
  call in its own `try/except`, logs, and `continue`s - a DB hiccup or unexpected error for one
  event never aborts the remaining candidates in the same cycle.
- **Process crash**: nothing is held in memory across the `await session.commit()` boundary inside
  `deliver_instagram_package()`'s own persistence - a crash after candidate creation, after package
  generation, or after the Telegram send (before the DB write, mirroring the exact real
  BigInteger-overflow incident from the prior canary) leaves durable, DB-backed state that a later
  cycle's `find_current()` check correctly reads - never a duplicate resend, never a lost record of
  intent to submit (the worst case is a story that gets re-evaluated once more, at zero cost beyond
  the treatment-classification query, until the freshness window excludes it).
- **Worker/bot restart**: nothing about the trigger holds any process-local state - a restarted
  `content_worker` picks the exact same `_select_eligible_events()` scan back up on its next cycle.

## H. Backlog policy

`HISTORICAL_BACKFILL_AUTOMATIC=false`. The automatic trigger never scans beyond `_select_eligible_
events()`'s own existing, already-reviewed freshness cutoff (24h default) - nothing older is ever
touched, on first deploy or ever.

## I. Rollout volume policy

`_INSTAGRAM_TRIGGER_MAX_PER_CYCLE = 3` - a plain module constant in `worker/content_cycle.py`,
explicitly documented as a TECHNICAL rollout-safety cap, NOT an editorial policy. A MAJOR-treatment
story beyond this count in one cycle is simply picked up on a later cycle (never dropped/rejected -
it stays eligible until the existing freshness cutoff excludes it). Separate and orthogonal from
`_ELIGIBLE_TREATMENTS` (the actual, permanent editorial selection criterion). Intended to be raised
once real production volume validates it is safe to.

## J. Telegram routing

Reuses `EditorialDestination.INSTAGRAM`/`deliver_instagram_package()` from the prior phase
unmodified - `chat_id=-1004297182444`, `message_thread_id=40`, already configured in production.
The same strict fail-closed guarantee applies: if `instagram_topic_id` were ever unset, the
automatic trigger would safely no-op (never fall back to the chat root or another topic).

## K. Publication safety

`INSTAGRAM_PUBLICATION_ENABLED=false`, `INSTAGRAM_AUTONOMOUS_PUBLICATION=false`. Structurally
verified (ast-based tests): `services/instagram_automatic_trigger.py` imports neither
`services.instagram_publish_adapter` nor `services.instagram_account_reader` nor
`services.instagram_media_hosting` - the automatic trigger cannot reach any Instagram write
endpoint and does not depend on Instagram credentials or media hosting being configured.

## L. Tests

New: `tests/test_instagram_automatic_trigger.py` (11 tests - selection MAJOR-only, idempotent
submission, topic-correct delivery, Creative-Director-level fact-safety rejection surviving
gracefully, structural no-credentials/no-media-hosting/no-publish-import guarantees, publication
flags false) + `tests/test_instagram_automatic_trigger_worker_wiring.py` (3 tests - `gate_gateway=
None` safe no-op, the per-cycle rollout cap, per-story crash isolation). All using
`FakeLLMGateway`/`FakePromptRepository` (zero real LLM calls) and `AsyncMock` `Bot` (zero real
Telegram calls), mirroring this codebase's own established conventions exactly.

**Results**: 14/14 new tests pass. Combined regression: 167/167 (new tests + existing Instagram/
delivery/creative-director/routing suites, including the pre-existing `test_content_worker_cycle.py`
structural import-boundary test), 49/49 (Unified Pipeline freeze + analysis-worker-cycle suites).
`NEW_FAILURES=0`. `ruff check` clean on every new/modified file.

## M. Regression

`TELEGRAM_EXISTING_FLOW_CHANGED=false` (the new step is a completely separate loop; every existing
`test_content_worker_cycle.py` test - including ones exercising `event_ids_override`, router mode,
and the Director pre-generation gate - passes unchanged, since `gate_gateway`/`gate_prompt_
repository` default `None` in every test that doesn't opt in, making the new step a byte-identical
no-op there). `STORY_MEMORY_CHANGED=false`, `ARXIV_CHANGED=false`, `UNIFIED_PIPELINE_CHANGED=false`,
`VISION_GATE_CHANGED=false` - none of those modules were touched.

## N. Production rollout plan

Deploy only `content_worker` (the automatic trigger lives entirely in `worker/content_cycle.py`,
which only that service runs) - `telegram_bot` needs no code change this phase (the callback
handler it already runs is untouched). No DB migration. Isolated production worktree, immutable
image tag, `docker-compose.override.yml` pin - the exact same pattern established in the prior two
canaries. Canary must come from real, natural newsroom traffic (§23) - no manual script.
