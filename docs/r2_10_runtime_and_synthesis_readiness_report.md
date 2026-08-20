# R2.10 Runtime & Synthesis Readiness Report

Autonomous overnight session. Isolated worktree `../ai-newsroom-r210`, branch
`feature/r2-10-autonomous-hardening`, based on the closed R2.9 landing commit
`51feac0819baf28b7558874fd54203f4d30c1560`. No production access, no paid LLM calls, no pushes.

## 1. R2.9 frozen baseline

Confirmed unchanged before any work: `51feac0` is HEAD of
`feature/phase19-editorial-depth-upgrade` in the primary repo; its parent is `7ebfd82`. The
combined R2 regression suite (`test_recap_r2_9_origin_membership_projection.py`,
`test_recap_r2_8_origin_membership_semantics_shadow.py`,
`test_recap_r2_7_anchor_lifecycle_forensic.py`, `test_event_recap.py`,
`test_recap_r2_6_shortlist_policy.py`, `test_recap_r2_single_attempt_gateway.py`,
`test_story_identity_invariant.py`, `test_story_memory.py`,
`test_triage_orchestrator_story_memory.py`) reproduced exactly as documented: **194 passed, 1
skipped, 0 failed**.

## 2. MissingGreenlet forensic (R2.10A.1)

**Classification: REAL_RUNTIME_HAZARD**, not a fixture artifact.

Root cause: `services/event_recap.py`'s `last_event_at` computation read
`max((e.published_at or e.collected_at for e in events), default=story.updated_at)`. Python
evaluates a `max(..., default=...)` keyword argument unconditionally, regardless of whether the
iterable is empty - so `story.updated_at` was read on *every* call, even though `events` is
provably non-empty on both paths that reach that line (direct-anchor case: `events` already
contains the anchor; origin-projection case: `build_effective_recap_members()` always returns
`[origin_event] + confirmed_members`, never empty; the only other outcome returns early before
this line). The fallback was unreachable dead code.

`Story.updated_at` (`database/models/story.py`) is a server-side `onupdate=func.now()` column.
Any earlier flush in the same session that touches the `Story` row (the real production case:
`services/triage_orchestrator.py`'s own `matched_story.event_count += 1`) leaves the attribute
expired with no automatic RETURNING-based refresh observed under this session's configuration
(`expire_on_commit=False`, `create_savepoint` join mode). The eager, unconditional read of that
expired attribute then triggered an implicit lazy-load outside a greenlet context - a real
`sqlalchemy.exc.MissingGreenlet`, reproduced deterministically (confirmed by reverting the fix and
re-running the regression test, which failed with the exact stack trace before the fix and passed
after).

**Fix implemented** (`services/event_recap.py`, ~15 lines): removed the unreachable
`default=story.updated_at`, added an explicit `assert events, ...` documenting the invariant, and
compute `last_event_at = max(e.published_at or e.collected_at for e in events)` unconditionally.
Zero behavior change (the fallback value was never reachable), fails loudly instead of fabricating
a timestamp if the invariant is ever violated by a future code change.

**Regression test**: `tests/test_event_recap.py::test_missinggreenlet_regression_no_story_refresh_needed`
- mirrors the real triage_orchestrator sequence (`event_count += 1`, flush, no explicit refresh),
proven to fail with `MissingGreenlet` before the fix and pass after.

## 3. Natural readiness positive test (R2.10A.3)

Confirmed R2.9 coverage gap: no test proved an origin-projected Story reaches `READY` *without*
`--force-shadow`. Root cause of the gap: `build_event_recap_candidate()` hardcoded
`research_complete=False` in its call to the frozen `evaluate_recap_readiness()`, with no way for
a caller to supply the signal - unlike R1's own `build_recap_event_snapshot()`, which already
exposes `research_complete` as a caller-supplied parameter (default `False`).

**Fix**: added `research_complete: bool = False` to `build_event_recap_candidate()`, threaded
straight through to `evaluate_recap_readiness()` unmodified. Default unchanged for every existing
caller (all call sites use keyword arguments; none pass this parameter). This does not touch
`services/recap_event.py`, does not lower any threshold, does not implement a Recap Research step -
it only lets a caller supply an already-existing R1 signal, exactly as R1 itself always allowed.

**New test**: `tests/test_recap_r2_9_origin_membership_projection.py::test_case4b_marvell_google_origin_projection_reaches_natural_readiness`
extends the real Marvell/Google fixture (Case 4) with a 4th genuinely distinct, on-topic
announcement (satisfying `recap_min_announcement_count=4`) and `research_complete=True`, proving
the complete natural path with no `force_shadow`:

- `origin_projection_applied=True`, `anchor_event_id == story.first_event_id`
- `story_integrity_eligible=True`
- `readiness_overridden=False`, `readiness_state == "READY"`
- `publishable=False`
- global confirmed membership (re-queried via `load_story_events()`) unchanged; origin still
  excluded from it
- `db_session.new`/`db_session.dirty` unchanged across the call (no writes)
- a companion assertion proves the *same* Story, called without `research_complete=True`, still
  correctly fails to reach readiness (default behavior is unchanged)

## 4. R2.10A test matrix

Full suite after both changes: **196 passed, 1 skipped, 0 failed** (194 baseline + 2 new). Ruff
and mypy clean on `services/event_recap.py`, `tests/test_event_recap.py`,
`tests/test_recap_r2_9_origin_membership_projection.py`.

## 5. Clean-checkout reproducibility

A separate, disposable, detached-HEAD worktree was created from the unmodified `51feac0` commit;
the exact 3-file diff (`git diff` from the R2.10A worktree) was applied there with `git apply`
(clean, no conflicts) and the full suite re-run: **196 passed, 1 skipped**, ruff clean, mypy clean,
`import services.event_recap` succeeds. Reproducible: **YES**. The verify worktree was removed
afterward; the primary autonomous worktree (`../ai-newsroom-r210`) was untouched by this step.

## 6. R2.10B synthesis boundary audit

Walked `EventRecapCandidate -> render_event_recap_bundle_text() -> _build_synthesis_request() ->
Gateway -> synthesize_event_recap() -> _verify_synthesis_facts()` end to end, offline, reading code
only (no execution against a real provider).

| # | Question | Finding |
|---|---|---|
| 1 | What evidence enters the prompt? | `render_event_recap_bundle_text()`: timeline, `_synthesis_verified_facts()`-filtered verified facts, per-announcement headline/numbers/entities/evidence-ref-count. All derived from `EventRecapCandidate` fields, themselves built from confirmed Story events. |
| 2 | Grounded in Story events? | PASS - every field traces to `_build_announcement_summaries`/`_build_timeline`/`_build_verified_facts`, all built from the same `events` list `build_event_recap_candidate()` loaded. |
| 3 | Deterministic source refs? | PASS - `source_refs = list(dict.fromkeys(...))`, order-preserving dedup, no randomness. |
| 4 | Deterministic ordering? | PASS - `cluster_announcements()` is documented as a deterministic single-pass over chronologically-sorted input; `build_effective_recap_members()` explicitly re-sorts by `(published_at or collected_at, id)` for a total order. |
| 5 | Duplicate facts/refs possible? | PASS (guarded) - `source_refs` dedups via `dict.fromkeys`; `verified_facts`/`_synthesis_verified_facts()` operate over already-deduplicated cluster/entity sets (frozen R1 machinery). |
| 6 | Unsupported numbers/entities in the bundle? | PASS (guarded, with a disclosed limitation) - numeric/entity extraction is publisher-suffix-sanitized (R2.2/R2.6b); `conflicting_evidence` is **deliberately always `False`** in R2 (documented in `services/event_recap.py`: "detecting a genuine cross-announcement factual conflict from titles alone is not reliably possible") - a real, disclosed limitation, not a bug. |
| 7 | Confirmed vs. single-source vs. uncertain vs. conflicting? | PARTIAL - confirmed/single-source is explicit (`FACT_MULTI_SOURCE_CONFIRMED`/`FACT_SINGLE_SOURCE_ONLY`) and reaches the prompt via `_describe_fact_provenance()`; **conflicting evidence has no representation anywhere in the pipeline** (see #6). |
| 8 | Expected output fields? | `recap_title: str`, `recap_summary: str`, `key_takeaways: list[str]`, `uncertainty_notes: list[str]` - `output_schema.required` in the prompt, enforced again defensively in code. |
| 9 | Malformed output? | FAIL-CLOSED - `structured_output` not a dict raises `EventRecapSynthesisError` (new regression test added, see below). |
| 10 | Missing required fields? | FAIL-CLOSED - explicit `missing = [key for key in required if key not in structured]` check, raises. |
| 11 | Unsupported claims introduced? | FAIL-CLOSED, non-blocking - `_verify_synthesis_facts()` reuses frozen `evaluate_fact_safety()`; a `review`/`block` status is recorded in `quality_flags`, never silently hidden, but never blocks `publishable` (already unconditionally `False`). |
| 12 | What does fact verification block/flag? | Flags via `quality_flags` (`fact_verification_review`/`fact_verification_block`); blocks nothing structurally in R2 since nothing is ever published. |
| 13 | `publishable` guaranteed False after synthesis? | PASS - `synthesize_event_recap()`'s own `replace(..., publishable=False)` is unconditional, independent of every other field. |
| 14 | Can synthesis write to DB? | PASS (structurally impossible) - `synthesize_event_recap(candidate, gateway, prompt_repository, *, runtime)` takes no `session`/DB handle at all. |
| 15 | Can synthesis reach Telegram? | PASS - already covered by the existing repo-wide static test `test_no_bot_or_worker_or_telegram_imports_anywhere_in_r2()`; re-confirmed by inspection (`services/event_recap.py` imports nothing from `bot/`, `worker/`, or any delivery path). |
| 16 | `--single-attempt` caps physical attempts without touching the shared Gateway? | PASS - `scripts/_recap_r2_event_shadow.py::_build_single_attempt_gateway()` builds a diagnostic-only wrapper from the same already-constructed routing/registry/health/cache/cost/budget/rate-limiter objects, with a fresh `FallbackPolicy(max_same_candidate_retries=0)` and `max_fallback_attempts=1` capped for that one request only - the shared production Gateway/FallbackPolicy instance is never mutated. |
| 17 | DB transaction closed before a possible real LLM call? | PASS - `main()`'s `trans.rollback()`/`conn.close()`/`engine.dispose()` all execute in `finally` blocks that unconditionally run before the `if args.with_llm:` block (line ~458, well after the transaction teardown at ~426-430). |
| 18 | Hidden network path without `--with-llm`? | PASS - Gateway/LLM imports (`assemble_ai_integration_layer`, `LLMGateway`) are deferred *inside* the `if args.with_llm:` block; the safe-default path never imports them. |

### Offline fake-Gateway matrix (Phase 8)

| Case | Scenario | Result | Evidence |
|---|---|---|---|
| A | Valid well-grounded synthesis | PASS | `test_synthesis_makes_exactly_one_gateway_call`, `test_fewer_than_max_takeaways_allowed_no_padding` (existing) |
| B | Malformed JSON / non-dict `structured_output` | FAIL-CLOSED | `test_synthesis_raises_when_structured_output_is_not_a_dict` (**new**) |
| C | Unsupported numeric claim | FAIL-CLOSED | `test_unsupported_claim_flagged_never_silently_published` (existing) |
| D | Unsupported entity/factual claim | FAIL-CLOSED | same mechanism as C, `evaluate_fact_safety()` (existing coverage) |
| E | Conflicting-evidence scenario | **UNKNOWN / not implemented** | `conflicting_evidence` is deliberately always `False` in R2 (disclosed limitation, item 6/7 above) - no test can exercise a code path that doesn't exist; documented as a real gap for a future phase, not fixed here |
| F | Missing recap fields | FAIL-CLOSED | `test_synthesis_raises_on_malformed_output` (existing) |
| G | Excessive/unexpected fields | PASS (harmlessly ignored) | `test_synthesis_ignores_unexpected_extra_fields` (**new**) |
| H | Gateway exception | FAIL-CLOSED | `test_synthesis_raises_on_gateway_error` (existing) |
| I | Fact-verification failure | FAIL-CLOSED, non-blocking | same as C/D - `publishable` stays `False` regardless (existing coverage) |

Two new regression tests added (`tests/test_event_recap.py`): case B and case G were the only
gaps with no existing coverage; every other case was already exercised by the pre-existing suite.
Case E is not a test gap - it is a real, disclosed architectural limitation (no conflict-detection
mechanism exists anywhere in R1 or R2) and is out of scope to fix here (would require new
cross-announcement comparison logic - an architecture change).

## 7. Prompt v2 audit (report only - v2.yaml was NOT modified)

`prompts/event_recap/v2.yaml` audited against the checklist:

| Property | Status |
|---|---|
| Uses only supplied evidence | PASS - system text + rule 1 |
| Handles single-source claims | PASS - rule 2, explicit uncertainty-notes instruction |
| Handles conflicting evidence | **ISSUE** - no rule addresses contradictory evidence at all; consistent with the code-level finding that R2 never detects conflicts in the first place |
| Avoids invented causal explanations | PARTIAL - only implicit via the general "never invent" rule; not called out explicitly the way chronology is |
| Avoids invented chronology | PASS - rule 4, explicit |
| Avoids invented numbers | PASS - system text + rule 1 |
| Clear schema/output contract | PASS - `output_schema` with `required`/`additionalProperties: false` |
| Handles uncertainty | PASS - `uncertainty_notes` field + rule 2 |
| Telegram-quality conciseness | Reasonable - asks for natural editorial text, but explicitly frames output as "internal review only," appropriately deferring publish-readiness |
| Preserves summary vs. takeaways distinction | PASS - distinct schema fields with distinct descriptions |

### Proposed EVENT_RECAP v3 changes (report only - not implemented)

1. Add an explicit rule for conflicting evidence once (and only once) the evidence pipeline itself
   can represent a conflict - e.g. "If two stored reports state different values for the same
   fact, note the discrepancy in uncertainty_notes rather than picking one silently." This is
   blocked on a code-level prerequisite (`conflicting_evidence` detection) that does not exist yet
   and is out of scope for R2.10.
2. Optionally make the "no invented causal explanations" instruction explicit rather than relying
   on the general anti-invention rule - low priority, likely already covered in practice.

Both are proposals only; v1/v2 remain byte-for-byte unmodified.

## 8. Paid synthesis candidate shortlist

No live production access this session - candidates are drawn entirely from already-recorded local
forensic evidence (the master checkpoint's own record, and `scripts/_recap_r2_6_broader_shadow_candidate_selection.py`'s own `_PRIOR_R2_6_CANDIDATE_NOTES`).

**No candidate can be confirmed currently READY from local evidence alone** - every known
production Story's last-recorded state is either explicitly disqualified or explicitly not-ready:

| Story ID | Topic | Status | Why (dis)qualified |
|---|---|---|---|
| `15f88e47-cdaa-4103-b951-d0cced63d4b1` | Marvell/Google chip deal | **PRIMARY (once ready)** | R2.9's own positive control: Integrity PASS (2/2 coherent, ratio 1.00), origin projection applied correctly. Last known state: **COOLING**, not READY - blocked only by `announcement_count 3 < required 4` and `recap research not complete` (both ordinary, satisfiable readiness gaps, not integrity/evaluator problems - confirmed generalizable by this session's own R2.10A.3 synthetic fixture, which reached natural READY with a 4th announcement). Must NOT be treated as READY until a live read-only re-check confirms a 4th real announcement exists and research is genuinely complete. |
| `2a39731e-06ea-4caa-8b91-e6e2fc6d1641` | Yakutia AI cluster | ALTERNATE 1 | Noted in R2.6 broader-shadow-scan forensics as "GOOD candidate, best real Story so far" - predates the Marvell finding; current readiness state unverified without a live re-scan. |
| `0d7e1ee3-b5ae-4b75-8498-77ce36e91385` | Nvidia-backed AI chip CEO stock purchase | ALTERNATE 2 (weak) | R2.6 notes: "ordinary finance/investment content, R2.6b finance-filter miss" - editorially marginal for NINJA PULSE's gadgets/AI/tech focus. |
| `80e4b284-df69-4975-9ad3-a6f2d4d8d476` | On-policy distillation (OPD) abstract | ALTERNATE 3 (weak) | Research-abstract-like content, likely thin on multi-source corroboration. |

Excluded per explicit instruction: `b312bb8b-...` (broad LLM garbage, 0/14 coherent),
`272352b7-...` (Cyrillic garbage, 0/2 coherent), `f9328cb5-...` (Stripe/OpenRouter, known
conservative evaluator false-negative), `60be3f72-28d3-4c5a-af65-f0550923fe94` (Sverdlovsk -
already CLOSED after 3 prior paid validation runs), `859ffea0-9b54-41cb-be25-13c061ca75ad`
(Taiwan - proven frozen fail-closed case).

**Recommendation**: before spending the first paid call, run the existing, zero-cost, read-only
`scripts/_recap_r2_event_shadow.py --story-id <id>` (no `--with-llm`) against Marvell and Yakutia
to get a live readiness re-check - this alone might resolve the announcement-count gap with no
paid spend at all.

## 9. Paid single-attempt runbook (prepared, NOT executed)

Preconditions (verify all before running):
1. Confirm current production HEAD and that the target Story's readiness has been re-checked
   read-only (`scripts/_recap_r2_event_shadow.py --story-id <id>`, no `--with-llm`) and is READY
   or an explicitly-accepted `--force-shadow` override.
2. Confirm Redis is reachable (required by `assemble_ai_integration_layer()`).
3. Confirm no other paid RECAP validation is in flight (avoid concurrent budget/cost confusion).

Execution (exact flags, one Story, one physical attempt):
```
docker compose run --rm --no-deps backend python scripts/_recap_r2_event_shadow.py \
  --story-id <UUID> --with-llm --single-attempt
```

Guarantees already built into the script (verified in this audit, §6 items 16-18):
- read-only DB transaction, rolled back and closed BEFORE the Gateway import/call
- `--single-attempt` mathematically caps physical provider `generate()` calls at 1
  (`max_same_candidate_retries=0`, `max_fallback_attempts=1`), without touching the shared
  Gateway's own resilience settings for any other caller
- zero Telegram/worker import anywhere in the script or `services/event_recap.py`
- `publishable=False` unconditionally, regardless of synthesis outcome
- stdout prints `LLM_ENABLED=`, `SINGLE_ATTEMPT=`, `MAX_PROVIDER_ATTEMPTS=`, and post-call
  `caller_gateway_calls=1 physical_provider_attempts=... fallback_attempts=... same_candidate_retries=...`
  for direct before/after safety verification - capture this stdout as the audit record
- result JSON/text/evidence-audit files are written to `/tmp` (or `--output`) for capture

No secrets/credentials are printed by the script; none are included here. Not executed this
session (no paid-call authorization).

## 10. Transferability plan (report only)

Once the first paid synthesis is reviewed, exercise 3-5 structurally different real Stories before
trusting the prompt/pipeline broadly:

1. AI model/product launch (category-typical, multi-source) - closest to Marvell/Yakutia.
2. Gadget/hardware development story - not yet identified locally; requires a live scan.
3. Evolving multi-source tech story with a real timeline (3+ genuinely sequential announcements,
   not just near-simultaneous coverage) - stress-tests the "publication order ≠ event stages"
   rule (v2 rule 4).
4. Gaming story, if a high-quality fixture exists - not yet identified locally.
5. A genuine uncertainty/conflicting-evidence case - given §6/§7's own finding that R2 has no
   conflict representation at all, this case is really "does the model correctly hedge on a
   single-source claim," not true conflict handling (out of scope until v3 + code-level conflict
   detection).

PASS criteria per case: fact-grounding (every claim traceable to evidence text), timeline fidelity
(no invented sequencing), editorial quality (reads as natural prose, no internal-vocabulary leak -
already guarded by `_detect_internal_vocabulary_leak()`), cost within expected single-attempt
bounds. FAIL criteria: any invented fact/number/entity, any internal-vocabulary leak, more than one
physical provider attempt under `--single-attempt`, any `publishable=True` (would itself indicate
a code regression, since it's structurally impossible today).

## 11. Telegram integration readiness audit (report only - no implementation)

Reusable existing paths identified (no new bot/service/worker needed):
- `services/story_telegram_delivery.py` - `determine_reply_target()` (pure decision:
  send-as-root / send-as-reply / fail-closed-route-to-review) and durable delivery tracking
  (`StoryTelegramDelivery`, `DeliveryStatus`) - already the exact mechanism a Story-linked RECAP
  post would need to reuse for correct threading against the Story's existing root message.
- `services/telegram_notifier.py` / `services/telegram_routing.py` - existing send/routing
  primitives.
- `services/news_telegram_presentation.py` - existing message-formatting conventions to mirror
  rather than reinvent.

Still missing (not built, not started, per instructions):
- A RECAP-specific presentation/formatting function (title/body/takeaways/uncertainty-notes/source
  references) - would need to reuse `news_telegram_presentation.py`'s established conventions.
- An explicit editor-review gate before any send (R2 has none - `publishable` is always `False`,
  by design, so nothing currently authorizes a send at all).
- Source-button/media handling respecting the two hard Telegram constraints already known:
  channel posts cannot place images inside text, and forwarded inline buttons do not persist (so
  no subscription semantics may be designed around a forwarded button).

This phase is analysis only - no Telegram wiring, no new bot, no new service.

## 12. Remaining blockers

- No confirmed-READY paid-synthesis candidate without a live, read-only re-check (§8).
- Conflicting-evidence detection does not exist anywhere in R1 or R2 (§6/§7) - a real, disclosed
  architectural gap, not a regression; fixing it is out of scope (new cross-announcement logic).
- Transferability cases 2 (gadget/hardware) and 4 (gaming) have no identified local fixture yet.
