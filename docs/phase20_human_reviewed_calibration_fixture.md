# Phase 20 Checkpoint 6 — Human-Reviewed Calibration Fixture

**Machine-readable source of truth**: `tests/fixtures/phase20_human_reviewed_cases.json`. This
document explains what it contains; never edit one without the other.

Built from a human review pass over `docs/phase20_m12_suppression_review_packet.md` (**not
modified** — the original packet stays intact as the raw review record). 23 cases total:

- **9 `FALSE_MATCH` cases** (58, 59, 60, 63, 64, 68, 71, 72, 73) — the relationship classifier
  currently treats these as at least loosely the same Story/event, and the human reviewer
  confirmed they are not. These are the primary regression targets for Checkpoint 6's hardening
  work.
- **6 genuine-update cases** (61, 62, 66, 67, 69, 70) — must keep behaving correctly (same Story,
  not suppressed, real material update) while the false-match cases above get fixed. Case 61 is
  recorded as `UNCERTAIN` per the human reviewer's own note (same underlying incident suspected,
  but not confident enough from titles alone to demand a stronger outcome) — `expected_suppress`
  is intentionally left `null` for it, not asserted either way.
- **1 special investigation case** (65) — deliberately has no pre-decided expected outcome; see
  the Checkpoint 6 report's own dedicated investigation section for the evidence-based conclusion.
- **7 representative `CORRECT_SUPPRESS` cases** (1, 2, 3, 7, 8, 55, 57) — exact duplicate, Habr
  cross-category duplicate (×2), arXiv cross-category duplicate (×2), the real AI Olympiad
  duplicate, and the Ai4 2026 aggregator-repeat duplicate. These must **not** regress while the
  false-match cases are fixed - the whole point of Checkpoint 6 is fixing precision without
  breaking the already-good duplicate-suppression behavior.

`matched_story_id` values are copied from the specific replay run that produced the packet -
**ephemeral**, regenerated fresh every disposable-DB replay. Tests built from this fixture key off
title pairs (via the same `_match_against_only()`-style isolation convention as `tests/
test_story_memory_v2.py`), never off these specific UUIDs.
