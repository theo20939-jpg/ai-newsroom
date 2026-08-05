# Phase 18 M9 — Human Feedback & Decision Logging: Implementation Report

Status: complete (engineering). Extends M8's approve/reject with the full reason taxonomy, cost
accumulation, and a read-only feedback-summary view — all on columns reserved since M2's
migration, so this milestone needs **zero additional migration**.

## 1. What was built

| File | Purpose |
|---|---|
| `schemas/meme_feedback.py` | `MemeRejectionReason` (8-way taxonomy), `MemeFeedbackSummary` |
| `services/meme_candidate_service.py` | `record_editor_decision()` extended with `reasons`/`notes`; new `add_cost()`, `build_feedback_summary()` |
| `bot/keyboards/meme_feedback.py` | reason-picker keyboard + callback codec |
| `bot/handlers/meme_preview.py` | "Reject" now shows the reason picker instead of finalizing immediately; new `memereason:` callback handler finalizes |
| `tests/test_phase18_m9_meme_feedback.py` | 18 tests |

## 2. How it satisfies each brief requirement

- **approved/rejected** — already real since M8 (`record_editor_decision`); unchanged here.
- **Reason** (не смешно / непонятно / factual risk / bad image / off-brand / too toxic / stale /
  duplicate idea) — `MemeRejectionReason`, the brief's own eight values exactly
  (`test_taxonomy_matches_the_brief_exactly` asserts the full set). Captured via a genuine second
  interaction step: pressing "Reject" no longer finalizes the decision immediately — it swaps the
  message's keyboard for a one-tap reason picker (`build_reject_reason_keyboard`), and the
  decision is only written once a reason (or an explicit "Skip") is chosen. `reasons` is stored as
  a JSON list (not a single value) on `MemeCandidate.editor_decision_reasons` — the schema always
  supported a list; M9's UI currently offers single-tap selection (one reason per rejection) as
  the MVP interaction, with room to become genuinely multi-select later without a schema change.
- **Regeneration counts** — `concept_regeneration_count`/`copy_regeneration_count`/
  `image_regeneration_count` were already reserved columns (M2); `MemeFeedbackSummary` surfaces
  all three in one read-only report view.
- **Cost** — `add_cost()` accumulates (never overwrites) `MemeCandidate.cumulative_cost_usd`, so
  repeated calls across a candidate's concept/copy/image generation attempts (including
  regenerations) correctly sum the real total. Rejects a negative amount outright
  (`ValueError` — a real cost can never be negative).
- **Published / not published** — `MemeCandidate.published` (reserved since M2) is surfaced in
  `MemeFeedbackSummary`. No code path in this phase ever sets it `True` — there is no autopublish
  logic anywhere in Phase 18, matching the brief's own explicit invariant. This is enforced by
  absence (no setter exists), not by a schema-level constant that could be silently bypassed.

## 3. Design decisions

- **`record_editor_decision()`'s `reasons`/`notes` are additive, optional keyword-only
  parameters** — the M8 call site (a plain "Approve," no reason prompt) keeps working completely
  unchanged with both defaulting to `None`.
- **Reasons are never validated against the decision** — `record_editor_decision()` stores
  whatever the caller supplies regardless of `decision` value. This method records; it does not
  police *when* a reason is editorially appropriate (a caller could in principle attach a
  rejection reason to an approval, which is unusual but not this method's concern to prevent).
- **Single-tap reason selection, not multi-select-then-confirm** — a deliberate MVP simplicity
  choice (documented in `bot/keyboards/meme_feedback.py`'s own docstring), consistent with this
  phase's broader "не устраивай бесконечную generation / keep it simple" discipline applied here
  to interaction complexity rather than generation cost. A future multi-select flow is a
  contained UI change, not a schema change (`editor_decision_reasons` already stores a list).
- **`add_cost()`/`build_feedback_summary()` have no live call site yet** — same disclosed
  deferral pattern as every prior milestone's persistence wiring (no orchestrator exists that
  calls the individual pipeline pieces end-to-end for a real `MemeCandidate` row). Both methods
  are real, tested in isolation via their contract (raises on negative cost; correctly reads back
  every reserved field), and ready for that orchestrator once it exists.

## 4. Testing

18/18 tests pass: the taxonomy matches the brief's eight values exactly; every reason and the
"skip" (`None`) case round-trip through the callback codec; malformed/wrong-prefix/unknown-
reason/non-UUID callback data all correctly return `None`; the reason keyboard includes every
reason plus skip, laid out two-per-row with a trailing single-button skip row;
`MemeFeedbackSummary` is frozen and rejects unknown fields; `published` is exercised as always
`False` (with the accompanying docstring explaining this is enforced by there being no setter in
this phase, not a schema promise alone); and cost is proven to round-trip as a precision-safe
string, never a float.

Regression: full Phase 18 suite — **156/156 pass** across all nine milestones together.
`tests/test_bot_router_registration.py` (3/3) — the M8 router-registration change remains
unaffected by M9's handler edits. `python -m pytest --collect-only -q` — **2299 tests collected**
(2281 + 18 new), 0 collection errors.

Not run this session (disclosed, unchanged constraint): the DB-backed
`record_editor_decision(reasons=...)`/`add_cost()`/`build_feedback_summary()` methods and the
two-step reject flow in `bot/handlers/meme_preview.py` against a live Bot/database.

## 5. What is explicitly NOT done in M9 (disclosed, not oversights)

- No live orchestrator calls `add_cost()` after a real capability/image-generation call — cost
  accumulation is real and tested but not yet wired into any end-to-end run (no such run exists
  in this phase, per every prior milestone's own disclosure).
- No analytics/reporting script consumes `build_feedback_summary()` yet — it is a building block
  for one, not the report itself.
- Multi-select reason capture (more than one reason per rejection in a single interaction) is not
  implemented — single-tap MVP only, as decided in §3.

## 6. This completes the engineering scope of Phase 18 M0–M9

All nine milestones described in the brief are now implemented, tested, and committed. The final
phase report (`docs/phase18_final_completion_report.md`) synthesizes all nine milestones'
findings, quantifies the phase as a whole, and gives the GO/NO-GO recommendation.
