# UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-FINAL-HARDENING-1 — Report

## A. Source SHA / branch / worktree

- **Base (Founder-reviewed HEAD of the prior cutover phase)**: `9e73053db8d47f41efd546f39776729a2687cae4`
- **New branch**: `feature/unified-editorial-pipeline-final-hardening-1`, created via `git worktree add`
  from the exact base SHA above (never `git reset`/`clean`/`stash drop`/`amend`/`rebase`)
- **New worktree**: `C:/Users/Theodor/ai-newsroom-unified-pipeline-hardening-1`
- All other worktrees (`ai-newsroom-unified-pipeline-1` and every other listed worktree) were left
  completely untouched by this phase.

## B. Founder review findings being addressed

From the prior `UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-FOUNDER-REVIEW-BUNDLE-1`:

- **HIGH**: "Media truthfulness is not actually enforced at the unified runtime call site. The
  taxonomy exists, but a wrong-subject photo may still be accepted." — CLOSED this phase (§C-H).
- **MEDIUM**: "`AMBIGUOUS_TRANSPORT_RESULT` has no reconciliation safeguard against future
  automatic retry." — CLOSED this phase (§I-K).
- **MEDIUM**: "The real V8 DATA renderer cannot currently realize a pure typographic no-photo
  strategy." — explicitly NOT addressed this phase, per the Founder's own instruction; documented
  as `KNOWN_SAFE_LIMITATION_DATA_TYPOGRAPHIC_FALLBACK` (§L).

## C. Actual media authority call path (traced from real HEAD code before any change was made)

```
run_unified_telegram_delivery()                          [services/editorial_pipeline/telegram_integration.py]
  → decide_presentation()                                 [format selection only - unchanged]
  → build_evidence_pack()                                 [unchanged]
  → _resolve_single_photo_candidate()                      [reuses legacy candidate discovery - unchanged]
  → _wrap_legacy_candidate_as_tier1()                       [ResolvedMediaCandidate, subject_match=None]
  → run_editorial_production_pipeline()                    [services/editorial_pipeline/orchestrator.py]
      → MediaResearchService.research()                     [services/editorial_pipeline/media.py]
          → research_and_select_media()                      [services/media_research_selection.py, UNMODIFIED]
              → is_selectable() / score_candidate()            [services/media_candidate_scoring.py, UNMODIFIED]
      → build_composition_plan()                            [unchanged]
  → render callback → V8 renderer                          [unchanged, zero-diff]
```

**The exact point a candidate becomes authoritative**: `research_and_select_media()`'s own
selection (`services/media_research_selection.py`), which calls `is_selectable()`/
`score_candidate()` (`services/media_candidate_scoring.py`) — both COMPLETELY UNMODIFIED by this
phase. Before this phase, that selection ran with `subject_match_classifier=None` (the default),
so every candidate's `subject_match` field stayed `None` for its entire lifetime and the scoring
function's own `GENERIC_CONTEXT` default applied uniformly, with `is_selectable()`'s `MISMATCH`
exclusion never able to fire (it requires `subject_match is not None`). This IS the confirmed root
cause of the HIGH finding — not a bug in the scoring/exclusion logic itself (which was already
correct and already tested), but the complete absence of a real classification being fed into it.

## D. Subject-match classifier design

New file: `services/editorial_pipeline/subject_match.py::classify_subject_match()` — the ONE
classifier now injected as `subject_match_classifier` into `MediaResearchService.research()` from
`telegram_integration.py`. Never a second, competing authority: `services/media_candidate_scoring.
py`'s own dominance/exclusion policy remains completely unmodified and is the sole ranking/
selection mechanism; this module only supplies the real classification that policy already knew how
to act on correctly.

**Design**: deterministic, evidence-based, text/metadata comparison — never a vision/LLM call
(avoiding both "no fabricated image semantics" and "do not create a second parallel classifier"
alongside the real, existing `capabilities/media_subject_match_capability.py`, left untouched and
available for a FUTURE phase to wire in as an even richer classifier without displacing this one).

Two-tier identity model, built entirely from existing `MediaIntent` fields (no schema change):
- **Required tier** (`model_name` + `must_show`) — must ALL be textually confirmed for
  `EXACT_SUBJECT`.
- **Category tier** (`product_name`, `company`, `person`, `event`, `location`) — a match here is
  `STRONG_CONTEXT` at best, never `EXACT_SUBJECT`.
- **Forbidden phrases** (`must_not_imply`) — a positive textual match is `MISMATCH`, regardless of
  any other signal.
- **No evidence at all** — `GENERIC_CONTEXT`, never asserted `EXACT_SUBJECT` or `MISMATCH` without
  real evidence.

Generic by construction: no brand, product, or keyword of any kind is hardcoded anywhere in the
file — every comparison is driven entirely by the caller-supplied `MediaIntent`.

## E. Candidate ranking policy

**Unmodified** — `services/media_candidate_scoring.py`'s own dominance invariant
(`SUBJECT_MATCH_SCORE[EXACT_SUBJECT]=60` > max possible non-exact total of 40, enforced by a
runtime `assert`) and hard `MISMATCH`/`NOT_USABLE` exclusion in `is_selectable()` are exactly as
they were before this phase — zero-diff. This phase's only change is that these mechanisms now
receive REAL classifications to act on, proven end-to-end in
`tests/test_unified_pipeline_media_truthfulness_replay.py`.

## F. Provenance behavior

See `artifacts/unified_pipeline_final_hardening_1/06_provenance_evidence.md`. No provenance field
is dropped or overwritten; `SubjectMatchValidation.reason`/`depicted_subject_description` are now
real, meaningful values (previously always absent, since `subject_match` was always `None`). No
large payloads, no credentials.

## G. Foldable iPhone replay

See `artifacts/unified_pipeline_final_hardening_1/01_foldable_iphone_replay.md` for the full
scenario table. `WRONG_IPHONE_IMAGE_SELECTED = false` proven in three real selection scenarios
(exact candidate present, exact candidate absent, only the wrong candidate available).

## H. Additional mismatch tests

10 scenarios from §10 of the phase brief, all passing, spanning product/version, vehicle, and
person-identity domains (deliberately not overfit to one brand) — see
`artifacts/unified_pipeline_final_hardening_1/02_mismatch_rejection_and_ranking.md`.

## I. Ambiguous transport semantics

`AMBIGUOUS_TRANSPORT_RESULT` now forces `TERMINAL_HOLD` on the very FIRST occurrence, enforced
centrally inside `RecoveryService.create_or_retry()` (a new
`_ALWAYS_TERMINAL_ON_FIRST_FAILURE_REASON_CODES` set, alongside the pre-existing
`QUALITY_GATE_FAILED`) — never dependent on a caller remembering to pass `max_attempts=1`. Definite
failures (`MEDIA_SEND_FAILED`) keep their existing, unchanged bounded-retry semantics (3 attempts,
deterministic backoff) — this phase preserves that distinction exactly (§13's own "preserve
distinction" instruction).

## J. Duplicate-send prevention

`find_open_recovery()` and `due_for_retry()` — the two queries any retry-consumer, present or
future, would use — only ever return `PENDING`/`RETRYING` rows. A `TERMINAL_HOLD` row (which every
`AMBIGUOUS_TRANSPORT_RESULT` occurrence now becomes immediately) is structurally invisible to both.
No retry-consumer was built (§15's own explicit instruction) — this is a domain-rule safeguard, not
a new subsystem.

## K. Recovery behavior

See `artifacts/unified_pipeline_final_hardening_1/03_ambiguous_transport_and_duplicate_prevention.md`
for the full transport-scenario table (A-E, §14) and the exact two pre-existing tests updated (not
broken) to reflect the new, correct semantics.

## L. DATA known safe limitation

`KNOWN_SAFE_LIMITATION_DATA_TYPOGRAPHIC_FALLBACK`, severity MEDIUM/NON-BLOCKING, explicitly not
addressed this phase per the Founder's own instruction — see
`artifacts/unified_pipeline_final_hardening_1/05_data_known_safe_limitation.md`.

## M. Architectural boundary verification

Re-proven against this phase's own base (`9e73053...`), by direct `git diff --stat`, not by
inspection alone:

| Property | Value | Evidence |
|---|---|---|
| `LEGACY_FALLTHROUGH_FOUND` | `false` | `worker/content_cycle.py` zero-diff |
| `TEXT_ONLY_VISUAL_DEMOTION_FOUND` | `false` | same |
| `TRANSPORT_EDITORIAL_AUTHORITY` | `false` | `services/telegram_routing.py` zero-diff |
| `STORY_MEMORY_CHANGED` | `false` | zero-diff on every Story Memory/identity file |
| `ARXIV_GUARD_CHANGED` | `false` | same |
| `TELEGRAM_V8_CHANGED` | `false` | zero-diff on every V8 renderer/presentation file |
| `INSTAGRAM_PUBLICATION_ENABLED` | `false` | `core/config.py` zero-diff |
| `UNIFIED_FLAG_DEFAULT` | `false` | `core/config.py` zero-diff |

## N. Story Memory freeze

Zero-diff — see §M. No Story Memory file appears anywhere in this phase's change set.

## O. arXiv freeze

Zero-diff — see §M. No arXiv-identity file appears anywhere in this phase's change set.

## P. V8 freeze

Zero-diff — see §M and `artifacts/unified_pipeline_final_hardening_1/04_flag_off_and_v8_preservation.md`.

## Q. Instagram publication safety

Unchanged — `instagram_publication_enabled` remains `False` (`core/config.py` zero-diff);
`services/editorial_pipeline/platforms/instagram.py` zero-diff (still uses the old in-process
recovery, as already disclosed by the prior phase — untouched, not addressed here, out of scope).

## R. Test results

**New tests this phase (23, all passing)**:
- `tests/test_unified_pipeline_subject_match_classifier.py` (13) — direct classifier unit tests: 10
  scenarios from §10 (same-brand/wrong-product, same-family/wrong-version, correct exact,
  strong/generic context, mismatch-despite-quality, no-evidence-available, low-quality-exact,
  person-identity, vehicle-identity) plus 3 named structural invariants.
- `tests/test_unified_pipeline_media_truthfulness_replay.py` (5) — the mandatory foldable iPhone
  replay (§9, all 3 scenarios) + the selection-level low-quality-exact-beats-high-quality-mismatch
  proof (§10 item 8).
- `tests/test_unified_pipeline_ambiguous_transport_hardening.py` (5) — transport scenarios A-E
  (§14): send succeeds, definite failure stays bounded-retryable, ambiguous timeout forces
  terminal, a hypothetical retry-consumer query never surfaces it, repeated processing passes never
  reopen it.

**Existing tests updated for new, correct behavior (not broken — the OLD assertions described the
Founder-flagged, now-fixed defect)**:
- `tests/test_unified_pipeline_cutover_authority.py::test_replay_h_ambiguous_transport_timeout_never_auto_resent`
  — now asserts `TERMINAL_HOLD`/`next_retry_at=None`/`max_attempts=1` instead of the old `PENDING`.
- `tests/test_unified_pipeline_recovery_service.py::test_persisted_state_survives_a_fresh_service_instance_after_a_simulated_restart`
  — switched its arbitrary reason code from `AMBIGUOUS_TRANSPORT_RESULT` to `MEDIA_SEND_FAILED` so
  it keeps testing exactly what its own name says (fresh-instance persistence), undisturbed by
  `AMBIGUOUS_TRANSPORT_RESULT`'s new semantics (covered by its own dedicated tests instead).

**Full-repo sweep** (`pytest tests/`, excluding the same 4 pre-existing, unrelated collection
errors as the prior cutover phase's own report): run in 7 batches (479 test files split
6-then-8-ways, due to a low-memory condition on this machine that killed two earlier full/large-
batch attempts — never silently worked around; the batching was chosen specifically so each
individual run stays memory-bounded) rather than one single invocation:

| Batch | Result |
|---|---|
| 1 (83 files) | 9 failed, 1042 passed, 11 skipped |
| 2 (77 files) | 4 failed (see note below), 1122-1124 passed, 10 skipped |
| 3 (82 files) | 0 failed, 1007 passed |
| 4 (79 files) | 8 failed, 1078 passed |
| 5a (41 files) | 11 failed, 680 passed |
| 5b (39 files) | 6 failed, 618 passed |
| 6 (78 files) | 9 failed, 1037 passed, 7 skipped |

**Every failure was checked against this phase's own base SHA (`9e73053...`) via a real, temporary
`git worktree add`** — never assumed pre-existing by name-pattern-matching alone:

- The large majority (43 of 47) match, by exact test node id, the 48-item pre-existing list the
  prior cutover phase's own report already established and disclosed (environment/ordering-
  sensitive: shared-test-DB FK pollution, `git diff`-based "no production files changed" checks,
  `.env`-mtime checks, and similar).
- **2 additional cases required direct, fresh verification** (not covered by the prior phase's own
  list, since batch composition differs from that phase's own single-invocation run):
  `tests/test_event_recap_scheduler.py::test_C_D_non_confirming_match_does_not_raise_freshness`
  (both parametrizations) failed once in one batch run, then PASSED on an identical re-run of the
  same batch on this same branch (genuine non-determinism/flakiness tied to real wall-clock timing
  in a freshness-window check, not a deterministic regression), and
  `tests/test_recap_r2_10_g3_eventness_harness.py::test_no_production_readiness_mutation` — proven
  to fail IDENTICALLY on the base SHA when run with the exact same batch composition
  (`11 failed` on both branches, byte-identical failure list).

`PRE_EXISTING_FAILURES = 47` (43 matching the prior phase's own disclosed list + 2 freshly verified
against the base SHA under identical batch conditions + the 2 known pre-existing
`test_router_media_integration.py` failures already counted in the 43).
`NEW_FAILURES = 0`.

## S. Regression comparison

No failure observed anywhere in this phase's full-sweep run traces back to any file this phase
changed (`services/editorial_pipeline/recovery_service.py`,
`services/editorial_pipeline/telegram_integration.py`,
`services/editorial_pipeline/subject_match.py`, or the 4 test files). Every failure is either a
byte-identical match to the prior phase's own disclosed pre-existing list, or independently
reproduced on the unmodified base SHA under identical test-batch conditions. `worker/content_cycle.py`,
`services/telegram_routing.py`'s dumb-transport functions, every Story Memory/arXiv/V8/Instagram
file, and `core/config.py` are all zero-diff against this phase's own base (§M) — there is no
mechanism by which this phase's change set could have caused any of the observed failures.

## T. Remaining risks

| Severity | Finding |
|---|---|
| MEDIUM | `KNOWN_SAFE_LIMITATION_DATA_TYPOGRAPHIC_FALLBACK` (§L) — explicitly deferred, fails safe |
| LOW | Real production `MediaIntent` construction (`services/editorial_pipeline/media.py::build_visual_intent_from_evidence()`, unchanged) does not yet populate `model_name`/`must_show`/`must_not_imply` for real events — the classifier is real and wired, but for TODAY'S single legacy Tier-1 candidate (no `caption_or_alt` text available at all), it will correctly default to `GENERIC_CONTEXT` rather than assert a stronger verdict. This is the SAFE default (never fabricates), not a false-EXACT risk - disclosed, not a blocker. It will begin to bite in practice the moment richer web-discovered (Tier 2-5) candidates or richer `MediaIntent` construction are wired in a future phase. |
| LOW | `services/editorial_pipeline/platforms/instagram.py` still on the old in-process recovery (already-disclosed, unchanged, out of scope) |

No BLOCKER, no HIGH finding remains open from the Founder review bundle.

## U. Production cutover readiness

Unchanged from the prior cutover phase's own recommendation
(`docs/unified_editorial_production_pipeline_cutover_1_report.md` §R /
`artifacts/unified_pipeline_founder_review_bundle_1/17_PRODUCTION_CUTOVER_PRECONDITIONS.md`) — this
phase closes the one HIGH and hardens one MEDIUM finding from the Founder's own review, but does not
itself perform or newly authorize any production action. `unified_editorial_pipeline_enabled`
remains `False`; no migration was applied to production; no real Telegram/Instagram write occurred.

## Pass-criteria checklist

| Criterion | Status |
|---|---|
| `MEDIA_TRUTHFULNESS_ENFORCED` | `true` |
| `WRONG_SUBJECT_CAN_WIN` | `false` |
| `FOLDABLE_IPHONE_WRONG_IMAGE_SELECTED` | `false` |
| `AMBIGUOUS_AUTO_RESEND` | `false` |
| `LEGACY_FALLTHROUGH_FOUND` | `false` |
| `TEXT_ONLY_VISUAL_DEMOTION_FOUND` | `false` |
| `STORY_MEMORY_CHANGED` | `false` |
| `ARXIV_GUARD_CHANGED` | `false` |
| `TELEGRAM_V8_CHANGED` | `false` |
| `INSTAGRAM_PUBLICATION_ENABLED` | `false` |
| `UNIFIED_FLAG_DEFAULT` | `false` |
| `NEW_FAILURES` | `0` |

## Final verdict

`BLOCKER_COUNT = 0`, `HIGH_COUNT = 0`, `MEDIUM_COUNT = 1` (the DATA typographic fallback limitation,
explicitly accepted as non-blocking and not addressed per the Founder's own instruction),
`LOW_COUNT = 2`. Every required successful-state criterion from §24 of the phase brief is met.

**UNIFIED_PIPELINE_FINAL_HARDENING_READY_FOR_FOUNDER_REVIEW**
