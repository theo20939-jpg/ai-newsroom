# R2 Shadow Execution Plan

Companion to `docs/r2_shadow_contract.md`. **Design only — nothing here has been implemented.**

## 1. Reusable components (nothing new needs to be built to start)

| Need | Existing component | Status |
|---|---|---|
| Read-only DB transaction guard | `_verify_read_only()` pattern, duplicated per-script per this codebase's own convention (`scripts/_recap_r2_event_shadow.py`, `scripts/_recap_r2_10_readiness_candidate_scanner.py`) | Proven, production-validated |
| Bounded Story selection | `scripts/_recap_r2_10_readiness_candidate_scanner.py` (`--limit`, ordered by `Story.updated_at`) | Ships today |
| Deterministic candidate build | `services/event_recap.py::build_event_recap_candidate()` | Ships today |
| Evidence bundle rendering | `services/event_recap.py::render_event_recap_bundle_text()` | Ships today |
| Optional single-attempt synthesis | `scripts/_recap_r2_event_shadow.py::_build_single_attempt_gateway()` (`--with-llm --single-attempt`) | Ships today, real-Gateway tested (`tests/test_recap_r2_single_attempt_gateway.py`) |
| Fact verification | `services/fact_safety.py::evaluate_fact_safety()` (via `_verify_synthesis_facts()`) | Ships today |
| Telegram-shaped text prototype | `services/event_recap.py::render_event_recap_telegram_preview()` | Ships today (pure prototype, unwired) |
| Manual-review flagging pattern | `CandidateScanRow.recommended_for_manual_review` | Ships today |
| Status vocabulary precedent | `FactVerificationResult.status` (`pass`/`review`/`block`), `TelegraphProposalStatus` (3-value, "keep lifecycle minimal") | Ships today |
| Media candidate collection + relevance | `services.image_persistence.get_editorial_image_candidates()`, `services.video_discovery_persistence.get_video_candidates_for_event()`, wrapped by `_collect_media_candidates()` | Ships today (known N+1, documented, out of scope) |
| Approved visual target contract | `docs/ninja_pulse_visual_system_v2_1.md` (`EditorialPresentation`, `RecapVisual` slot) | Spec only, no code yet — shadow must not contradict it |
| JSON + human-readable report output | Both existing R2 scripts' own `_serialize()`/`_render_text_report()` pattern | Ships today |

**Net new code needed for a first canary: one script that loops the scanner's own Story selection,
calls the existing deterministic build per Story, and writes the three-section output (§3 of the
contract) per Story — no new primitive, purely composition of what's listed above.**

## 2. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `announcement_count` over-interpreted by a reviewer as "development count" (R2.11 finding) | Medium — misjudgment risk, not a system defect | Mandatory `quality_notes` entry on every Story whose announcements are near-simultaneous / lack a distinguishing fact; contract doc's own explicit labeling requirement (§3) |
| Shadow run accidentally spends money (accidental `--with-llm` without `--single-attempt`) | High if it happens, but already mitigated | Reuse the EXISTING `_cli_safety_warnings()` guard (R2.10 Night 2) verbatim; a shadow batch script must apply `--single-attempt` semantics per-Story, never a bulk unprotected loop over `--with-llm` |
| Read-only guard silently not enforced (Postgres session pooling edge case) | High if it happens | Reuse the EXISTING `_verify_read_only()` (queries `SHOW transaction_read_only`, raises `ReadOnlyGuardError` rather than proceeding) — proven pattern, not a new one |
| Media relevance appears "validated" but the anchor-preference gap (Night 2 Phase 19) silently picks a weak image for a multi-event Story | Low-medium | `quality_notes` flag whenever `media_candidates` spans more than one distinct `event_id` |
| Shadow output JSON/text files accumulate on disk with no retention policy | Low | Out of scope for the first canary — a fixed, small `--limit` and manual cleanup is sufficient; a retention policy is a later decision, not a blocker |
| A future contributor reads shadow output and assumes it's already the final RECAP visual format | Medium | Contract doc (§4) explicit disclaimer; every shadow output file should carry a header stating it is data-only, not a rendering |
| Scope creep — shadow script grows into a second implementation of the CLI diagnostic instead of composing it | Medium | Explicit non-goal (§6 of contract); code review of any implementation must confirm it calls existing functions, not new duplicated logic |

## 3. Minimal first shadow canary — proposal

**Scope**: extend `scripts/_recap_r2_10_readiness_candidate_scanner.py`'s own selection logic
(read-only, bounded `--limit`) with a *second*, opt-in mode that, for each selected Story, also
builds the full deterministic `EventRecapCandidate` (not just the scanner's own summary row) and
writes the three-section JSON output (§3 of the contract) per Story to a bounded output directory.
**Deterministic stage only for the very first canary — no `--with-llm` at all**, to keep the first
run's safety story as simple as possible (zero cost, zero Gateway touch, matching the "Hard Safety
Requirements" table's own "LLM calls = OFF" row exactly).

**Owner-confirmed requirements (approval round):**
- Deterministic only: no `--with-llm`, no Telegram, no workers, no DB writes.
- Bounded scan (`--limit`, same hard-ceiling discipline as the existing scanner's `MAX_LIMIT`).
- Per-Story JSON (the three sections from the contract, `evaluation_status` computed from
  `EventRecapBuildResult.rejected`/`manual_review_required`/`quality_notes` — no LLM, no
  fact-verification stage, since no synthesis runs in this canary).
- Per-Story TXT evidence (`render_event_recap_bundle_text()`'s own output, written verbatim —
  mirrors `scripts/_recap_r2_event_shadow.py`'s own pre-synthesis evidence-audit file).
- **One aggregate `shadow_summary.json`**, covering the whole scan run, containing:
  - `scanned_count` — total Stories examined;
  - `candidate_count` — how many produced a built `EventRecapCandidate` (i.e. not rejected outright);
  - `rejection_reasons_distribution` — a count per distinct rejection-reason string (or a stable
    normalized bucket of it) across all rejected Stories;
  - `readiness_states_distribution` — a count per `readiness_state` value across all built
    candidates.

Concretely, as a **design note** (still not yet approved for implementation — see the plan
requested in the owner's own §4):
- New script or an additive flag on the existing scanner (`--shadow-output-dir <path>`) — exact
  choice is the first decision point in the implementation plan below.
- `--limit` default small (5-10), hard ceiling matching the scanner's own existing `MAX_LIMIT`.
- No batch execution, no automatic scheduling — a human runs this by hand, exactly like every
  prior R2 diagnostic.

**Explicitly deferred to a second canary** (not part of the first): the optional `--with-llm
--single-attempt` synthesis stage, fact-verification-driven `quality_notes`, and any Telegram-shape
preview generation. The first canary's only job is proving the read-only, zero-cost,
multi-Story batch collection loop is safe and produces useful, correctly-labeled output — the
smallest slice that delivers real editorial value (a batch of real candidates to look at, plus an
aggregate view) with the smallest possible new-code surface.

## 4. Sequencing after this document

1. Owner reviews `docs/r2_shadow_contract.md` + this plan.
2. On confirmation: implement the minimal canary exactly as scoped in §3 — deterministic-only,
   no synthesis, no Telegram shape.
3. Run the canary against a small `--limit` locally/read-only, review output manually.
4. Only then: propose (as its own, separately-reviewed design note) the optional synthesis stage
   and/or Telegram-preview stage extensions.

No implementation begins before step 2's explicit confirmation.
