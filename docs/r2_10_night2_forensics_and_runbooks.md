# R2.10 Night 2 — Forensics, Design, and Operator Runbooks

Companion to `docs/r2_10_runtime_and_synthesis_readiness_report.md` (Night 1). Covers the Night 2
autonomous session's real-bug forensics plus every report-only phase (no code change). Isolated
worktree `../ai-newsroom-r210`, branch `feature/r2-10-autonomous-hardening`. No production access,
no paid LLM calls, no pushes.

## Phase 7 — R2.11 Conflict Detection Design (not implemented)

**Conclusion: BLOCKED on unreliable claim alignment, documented rather than implemented**, per this
phase's own explicit fallback ("if deterministic claim alignment is not sufficiently reliable, do
not implement").

**Existing dormant support found** (confirms the R2.10 Night 1 audit): `services/recap_event.py`'s
own frozen `evaluate_recap_readiness()` already accepts `unresolved_conflict_count: int = 0` as a
caller-supplied signal (exactly like `research_complete`) - R2 always passes `0`. `services/
event_recap.py`'s `VerifiedFactCandidate.conflicting_evidence: bool = False` is a dormant field,
never set `True` anywhere.

**Why a reliable detector isn't buildable today**: `_extract_meaningful_numbers()` (and R1's
`_extract_numeric_tokens()`) produce bare digit strings with **zero surrounding
context** - no unit, no claim type, no subject. Two different numeric values ("58" and "60") could
be: the same claim genuinely in conflict (58M vs 60M shares), or two completely unrelated claims
(58M shares vs 60% approval rating) that happen to co-occur. Nothing in the current extraction
pipeline distinguishes these cases. A narrower attempt - "flag any numeric disagreement within one
already-clustered announcement" - was evaluated and rejected: R1's clustering groups events by
headline/entity similarity, not by claim identity, so a single announcement legitimately contains
several different genuine numbers (percentage move, dollar amount, share count) with zero conflict
between them - this heuristic would false-positive on nearly every multi-fact cluster.

**R2.11 requirements for a future, reliable version** (not built, design only):
1. A claim-typed extraction layer - each number needs an associated *subject* (what is being
   measured: share count, dollar value, percentage, date) before two numbers can be compared as
   "the same claim, different value" vs. "different claims."
2. A conservative, high-precision claim-matching rule - e.g., require both the SAME distinctive
   entity AND the SAME unit/claim-type word adjacent to each number before treating a value
   mismatch as a conflict candidate.
3. Fail-closed by construction: an ambiguous case must never be flagged as a false conflict merely
   because a value differs - only genuinely-aligned-claim mismatches should count.
4. Wire the result into the already-dormant `unresolved_conflict_count`/`conflicting_evidence`
   signals - no new architecture needed at the readiness-evaluator layer, since both hooks already
   exist and are frozen-but-accepting.

Until (1)-(2) exist with real, evidence-backed precision, R2.11 should not be attempted - a
false-positive conflict flag would incorrectly block otherwise-good candidates, which is worse than
the current, honest "R2 does not detect conflicts" disclosure.

## Phase 16 — Paid-Candidate Selection Runbook

Prepared, not executed:

1. **Exact-file extraction**: from the approved local commit (`git log --oneline -8` in the
   isolated worktree to confirm the exact hash), never from a dirty working tree.
2. **Read-only DB verification**: confirm target Postgres is reachable and NOT the production
   write path, before running anything.
3. **Manual candidate scanner**: `python scripts/_recap_r2_10_readiness_candidate_scanner.py
   --limit 30 --output /tmp/scan.json` (zero cost, zero LLM, read-only transaction).
4. **Shortlist**: read the ranked stdout output; anything marked `***`
   (`recommended_for_manual_review`) with `readiness_state` COOLING is the practical shortlist -
   nothing will show READY today (research_complete is never True in current production, by
   design - see Night 1 report).
5. **Human evidence inspection**: for each shortlisted `story_id`, run
   `python scripts/_recap_r2_event_shadow.py --story-id <id>` (still zero cost, no `--with-llm`) -
   read the `.txt` report and the `_evidence.txt` pre-synthesis evidence dump.
6. **Choose ONE Story** based on that evidence - coherent, multi-source, genuinely evolving,
   editorially relevant (NINJA PULSE's own gadgets/AI/tech focus).
7. **Only then**, follow the Night 1 report's own "Paid single-attempt runbook" (§9 there) - not
   repeated here.

## Phase 17 — Editorial Quality Rubric

Reviewer worksheet for the first paid synthesis output(s), PASS threshold noted per row:

| Dimension | PASS threshold | Notes |
|---|---|---|
| Factuality | Every claim traces to `render_event_recap_bundle_text()`'s own evidence, zero exceptions | Cross-check against the `_evidence.txt` dump, not the model's own confidence |
| Grounding | No number/entity/date absent from evidence appears in output | `fact_verification.status` should be `pass` or `review` with a human-reviewed reason, never `block` accepted silently |
| Timeline accuracy | Publication order never narrated as proven event-progression stages | Prompt v2 rule 4's own explicit caveat - verify the model actually honored it |
| Source diversity | Reviewer independently confirms `readiness_source_count`/`evidence_reference_count` reflects genuinely distinct outlets, not wrapper artifacts | See Night 1 Phase 3 forensic - Google News wrapper inflation/deflation is real |
| Uncertainty handling | Every single-source claim in the output has a corresponding uncertainty note OR is phrased with appropriate hedging | No overclaiming corroboration language ("independently confirmed") absent real evidence |
| Novelty/value | Recap says something a bare headline list wouldn't - synthesizes, doesn't just concatenate | Subjective, reviewer judgment |
| Concision | `recap_summary` 2-4 sentences (schema's own target), `key_takeaways` no padding | Reviewer flags any filler/boilerplate phrase |
| Telegram readability | Reads naturally as a human-authored recap, zero internal-vocabulary leak | `_detect_internal_vocabulary_leak()` should already show `quality_flags` empty - reviewer double-checks anyway |
| Headline quality | Non-sensational, factual, matches schema's own `recap_title` description | Reviewer judgment |
| Takeaway quality | Each takeaway independently verifiable against evidence, none redundant with another | Reviewer flags near-duplicate takeaways |

Overall PASS requires: Factuality PASS, Grounding PASS, Publishable-invariant confirmed still
`False` in the raw JSON output, and no more than one dimension below threshold elsewhere.

## Phase 18 — Telegram Presentation

**PURE PROTOTYPE** (implemented, see commit `6d44645`) -
`services/event_recap.py::render_event_recap_telegram_preview()`. Report-only beyond that: no
wiring into `bot/`/`worker/`/any delivery path (repo-wide AST guard proves this, now covering the
new scanner script too).

## Phase 19 — Media Readiness Audit (Minimal EVENT_RECAP Media v1, report only)

`EventRecapCandidate.media_candidates` already reuses the EXISTING, already-persisted read
contracts unchanged (`services.image_persistence.get_editorial_image_candidates()`, `services.
video_discovery_persistence.get_video_candidates_for_event()` - module docstring, confirmed by
reading `_collect_media_candidates()`, Night 1). No Rich media, no new architecture, per instruction.

- **Which existing source to reuse**: the same per-event image/video candidate tables every other
  editorial surface already reads - no new persistence.
- **Anchor media preference**: NOT currently implemented - `_collect_media_candidates()` collects
  from every member event equally, deduplicated by `(kind, url)`, with no anchor-event
  preference/ranking. For a future v1: prefer the anchor event's own top-ranked image first, fall
  back to other members' - a small, narrow ordering change, not attempted tonight (no concrete
  evidence yet that ordering matters for a shadow-only, unpublished candidate).
- **Multiple-event media mismatch risk**: real - an image ranked highly for one member event might
  visually represent only that event's specific detail, not the Story's overall arc. Since nothing
  publishes in R2, this risk is currently inert but must be revisited before any real send.
- **Branding risk**: NINJA PULSE's own visual system (separate, uncommitted Visual v1.2 work in
  the primary worktree - untouched this session) is not consulted anywhere in this path; a future
  Telegram wiring would need to apply the same branding rules any other image-bearing send does.
- **No-image case**: `media_candidates=[]` is already a normal, handled outcome - the deterministic
  candidate build never fails or degrades when it's empty (confirmed: `_collect_media_candidates()`
  returns `[]` cleanly when no images/videos exist for any member event).

No pure selector helper was added - the existing collection/dedup logic already covers the "no
image" case correctly, and an anchor-preference reordering has no test-backed justification yet.

## Phase 20 — Query / Performance Audit

`build_event_recap_candidate()`'s own query shape, traced by direct code reading (not profiled
against a live DB this session - no production access):

- `load_story_events()`: 1 query (frozen R1).
- `resolve_recap_origin_projection()` (only when anchor missing): 2 bounded, indexed reads (own
  docstring's explicit claim, confirmed by reading the function).
- `load_canonical_urls_for_events()`: 1 batched query (`WHERE news_event_id IN (...)`).
- `_collect_media_candidates()`: **a real, confirmed N+1** - `get_editorial_image_candidates()` +
  `get_video_candidates_for_event()` are called ONCE PER EVENT (2 queries × N events). For a
  10-event Story, ~20 media queries; for 50 events, ~100+.

**Not fixed tonight**: both functions are single-event-scoped, shared read contracts used by other
callers beyond RECAP (`services/image_persistence.py`, `services/video_discovery_persistence.py`).
Batching them would require either changing their shared signature (risking behavior change for
other callers) or duplicating query logic in `event_recap.py` (against this module's own explicit
"reuses the EXISTING... read contracts... no new media architecture" discipline). In practice,
every real Story fixture seen this session (Marvell, Yakutia, the R2.9 corpus) has single-digit to
low-double-digit event counts, so the N+1's practical blast radius is bounded today - documented as
a real, disclosed limitation rather than fixed, per this phase's own "otherwise document" fallback.

## Phase 21 — Fail-Closed DB Error Matrix

Already substantially covered by `tests/test_recap_r2_9_origin_membership_projection.py`'s own
Cases 9-14 (`classify_origin_projection()` fail-closed states): missing origin event
(`ORIGIN_EVENT_MISSING`), no own link (`ORIGIN_LINK_MISSING`), link to a different Story
(`ORIGIN_LINK_WRONG_STORY`), multiple current links (`ORIGIN_LINK_AMBIGUOUS` - structurally
unreachable via real persistence, since `news_event_id` is the links table's own primary key, but
tested defensively anyway), unexpected match_type (`ORIGIN_MATCH_TYPE_UNEXPECTED`).

Additional finding this session: `grep -n "except" services/event_recap.py
scripts/_recap_r2_event_shadow.py scripts/_recap_r2_10_readiness_candidate_scanner.py` returns
**zero matches** across all three files - no exception is ever caught and swallowed anywhere in
R2-owned code. Any DB error, malformed-data error, or unexpected exception propagates naturally and
crashes loudly; nothing fabricates a candidate on infrastructure failure. This is fail-closed by
construction, not by explicit handling - confirmed by direct inspection, no new tests needed.

"Story not found" is handled one level up, by each CLI script's own `_load_story()`/direct
`session.get()` call returning `None` (both scripts already check this and exit cleanly).

## Phase 22 — CLI UX Hardening

**Implemented** (commit `e1c7a94`): `_cli_safety_warnings()` in
`scripts/_recap_r2_event_shadow.py` warns on `--with-llm` without `--single-attempt` (the one
genuinely dangerous silent-default-resilience state) and notes when `--single-attempt` has no
effect without `--with-llm`; an output-path-collision note before any report file is overwritten.
Invalid UUID and missing Story were already handled correctly (argparse's own `type=UUID` and an
explicit `if story is None` check) - no change needed there.

## Phase 23 — Deprecated / Historical R2 Tooling Audit

| Script | Classification | Evidence |
|---|---|---|
| `scripts/_recap_r2_8_anchor_repair_shadow_scaffold.py` | **KEEP** | Actively tested and passing (`tests/test_recap_r2_8_anchor_repair_shadow_scaffold.py`, 2 tests, confirmed passing this session) - still validates real R2.7/R2.8 anchor-repair reasoning, complementary to (not superseded by) R2.9's origin projection |
| `scripts/_recap_r1_1_real_corpus_calibration.py` | **HISTORICAL_ONLY** | No active test imports it; referenced only in `services/recap_event.py`'s own docstrings as the citation for how frozen thresholds were originally calibrated against real corpus data - the calibration already happened, results are baked into frozen constants |
| `scripts/_recap_r1_2_production_calibration.py` | **HISTORICAL_ONLY** | Same as above |
| `scripts/_recap_r1_3_offline_diagnostic.py` | **HISTORICAL_ONLY** | Same as above |
| `scripts/_recap_r1_3_production_replay.py` | **HISTORICAL_ONLY** | Same as above |
| `scripts/_recap_r1_4_production_replay.py` | **HISTORICAL_ONLY** | Same as above |
| `scripts/_recap_r1_5c_broad_announcement_safety_replay.py` | **HISTORICAL_ONLY** | Same as above |

None deleted tonight (explicit instruction). Future cleanup command, when the owner decides the
historical citation value has been fully absorbed into permanent docs:
```
git rm scripts/_recap_r1_1_real_corpus_calibration.py scripts/_recap_r1_2_production_calibration.py \
       scripts/_recap_r1_3_offline_diagnostic.py scripts/_recap_r1_3_production_replay.py \
       scripts/_recap_r1_4_production_replay.py scripts/_recap_r1_5c_broad_announcement_safety_replay.py
```
(NOT run this session.)

## Phase 25 — Recap Test Matrix (condensed)

| Feature | Primary test file | Checkpoint | Status |
|---|---|---|---|
| Story Integrity Gate | `test_recap_story_integrity.py`, `test_recap_event.py` | R1 | frozen, passing |
| Announcement clustering / readiness | `test_recap_event.py` | R1 | frozen, passing |
| Origin projection | `test_recap_r2_9_origin_membership_projection.py` | R2.9 | passing, extended (case4b) Night 1 |
| Anchor lifecycle forensic | `test_recap_r2_7_anchor_lifecycle_forensic.py` | R2.7 | passing |
| Anchor repair shadow scaffold | `test_recap_r2_8_anchor_repair_shadow_scaffold.py` | R2.8 | passing, KEEP (Phase 23) |
| Shortlist policy | `test_recap_r2_6_shortlist_policy.py` | R2.6 | passing |
| Single-attempt Gateway | `test_recap_r2_single_attempt_gateway.py` | R2.3a | passing, extended (CLI warnings) Night 2 |
| Evidence/candidate build, synthesis, numeric/entity extraction | `test_event_recap.py` | R2.2-R2.10 | passing, extensively extended both nights |
| Readiness candidate scanner | `test_recap_r2_10_readiness_candidate_scanner.py` | R2.10 Night 2 | new, passing |
| Story Memory / triage integration | `test_story_memory.py`, `test_triage_orchestrator_story_memory.py`, `test_story_identity_invariant.py` | R1/Phase 20 | frozen, passing |

No duplicate, unreachable, or weak-assertion tests were found in the files touched this session
(all new tests assert concrete values/states, none are tautological - the one tautology introduced
by mistake, `anchor_event_id in {anchor_event_id}`, was caught and fixed before commit tonight, see
the Phase 8 invariant test's own history in this branch). A full audit of the entire pre-existing
suite (hundreds of tests across R1-R2.9) was out of scope for one night - this matrix covers what
was directly touched or reused.

## Phase 27 — Security / Secret / Network Surface Audit

Offline review of every R2 addition this session (`services/event_recap.py`,
`scripts/_recap_r2_10_readiness_candidate_scanner.py`, the CLI script's own new
`_cli_safety_warnings()`/output-collision code):

- No credential, API key, or environment variable is logged, printed, or written to any JSON/text
  report anywhere in the new code.
- The new scanner script never imports `integrations.llm_gateway.*` (confirmed by the same AST
  guard test now covering it) - zero provider exception messages possible, since zero provider
  calls are possible.
- Source URLs are printed/written verbatim in existing reports (`_render_text_report()`,
  `render_event_recap_bundle_text()`) - these can legitimately contain tracking query parameters
  from the original publisher, never anything from this system's own secrets; no new exposure
  introduced tonight.
- Output files are written with default OS permissions (no `chmod`/ACL changes anywhere) -
  unchanged from the existing script's own established behavior, not a new risk.
- No new network import was added to any zero-LLM code path (confirmed structurally via the
  existing/extended AST guard tests).

No findings requiring remediation.

## Phase 24 — Documentation Index

This session's documentation, all inside the isolated worktree only:
- `docs/r2_10_runtime_and_synthesis_readiness_report.md` (Night 1)
- `docs/r2_10_night2_forensics_and_runbooks.md` (this file, Night 2)

The primary worktree's own untracked `docs/r2_recap_checkpoint_history_and_architecture.md` was
not read or modified this session (report-only reference in the owner's overnight prompt; the
material actually needed for R1/R2 context was already present in this codebase's own frozen
module docstrings, read directly).
