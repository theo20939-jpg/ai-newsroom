# Phase 18 M3 — Meme Safety & Originality Gate: Implementation Report

Status: complete. Additive, shadow-only, `meme_safety_gate_mode` defaults to `"off"`. Zero new
LLM calls, zero new DB writes, zero migrations.

## 1. What was built

| File | Purpose |
|---|---|
| `schemas/meme_safety.py` | `MemeGateDecision`, `MemeSafetyAssessment`, `MemeOriginalityAssessment`, `MemeSafetyOriginalityGateResult` |
| `services/meme_safety.py` | Pure, deterministic safety + originality assessors, combined gate, `apply_meme_safety_originality_shadow()` |
| `services/meme_opportunity.py` | `_detect_sensitivity` renamed to public `detect_sensitive_categories()` and reused (not duplicated) by M3 |
| `capabilities/executor.py` | New `_attach_meme_safety_originality()` hook, called at the "meme_concept" step, gated by `meme_safety_gate_mode == "shadow"` |
| `core/config.py` | New `meme_safety_gate_mode: Literal["off", "shadow"] = "off"` |
| `tests/test_phase18_m3_meme_safety_originality.py` | 15 tests |

## 2. Design decisions and why

- **One shared sensitivity lexicon, not two.** M1 scans the *source NewsEvent*; M3 scans the
  *generated MemeConcept's own text* (premise/setup/punchline/visual_scene/text_overlay_intent/
  characters_objects/forbidden_interpretations). Both need the exact same category list (death/
  tragedy, disaster, war, crime-with-victim, minors'-safety, protected characteristics, serious
  illness, legal-jeopardy/accusation, harassment/stalking) - a second, independently-maintained
  copy would risk drifting apart on a safety-critical list. `services/meme_opportunity.py`'s
  `_detect_sensitivity` was renamed to public `detect_sensitive_categories()` and is now imported
  directly by `services/meme_safety.py`, rather than duplicated (a deliberate departure from this
  codebase's more common "duplicate small helpers" convention, justified specifically because this
  helper is safety-relevant, not because it's generically reusable).
- **BLOCK always wins.** The combined `gate_decision` is computed as `max(safety.decision,
  originality.decision)` by a fixed PASS < REVIEW < BLOCK rank - it can never disagree with either
  sub-assessment, and a concept-text sensitivity match or a calibrated Fact-Safety `"fail"` always
  hard-blocks regardless of every other signal, mirroring `services.fact_safety`'s own precedence
  discipline exactly.
- **A concept's own `forbidden_interpretations` disclosure is rewarded, not punished** - it
  escalates to `REVIEW`, never `BLOCK`, so a well-behaved concept that correctly flags its own
  risky reading isn't penalized harder than a concept that stayed silent about the same risk.
- **Originality scope is explicitly narrow and disclosed** (per `docs/
  phase18_m0_meme_discovery_report.md` §8 risk 3, restated in this module's own docstring): with
  no external meme database to compare against, M3 can only catch (a) a concept naming/describing
  a specific well-known meme template (a curated, disclosed-incomplete ~20-entry list), and (b) a
  punchline that is a near-verbatim restatement of the news headline (≥80% token overlap by
  minimum-set-size ratio) rather than an original transformation. It cannot and does not claim to
  detect similarity to memes already circulating on the internet - this is a permanent limitation
  of a zero-LLM, zero-external-lookup gate, not a bug to fix later.
- **No `calibrated_fact_safety_status` is available yet.** MEME_GENERATION has no "quality" step
  as of M2/M3 (`workflows/definitions/meme_generation.py`'s current 3-step list) - the executor
  hook passes `None` for this parameter, which `assess_meme_safety()` treats as "no additional
  signal," not an error. Once M7 (Quality Gate) or an earlier milestone adds a `quality`-equivalent
  step to MEME_GENERATION, this parameter should be wired to a real value - tracked as an open
  item in §5, not silently left as a TODO.
- **No persistence wiring added.** Mirrors M2's own explicit deferral: `MemeCandidateService` gets
  a `attach_safety_assessment()`-equivalent method once the broader task-creation/orchestration
  question is resolved (M2 report §5), not speculatively now.

## 3. Testing

15/15 tests pass (`python -m pytest tests/test_phase18_m3_meme_safety_originality.py -v`):
safety PASS on a clean concept; hard BLOCK on concept-text sensitivity (crime-with-victim tested
directly); calibrated Fact Safety `"fail"`/`"review"` escalation; self-flagged
`forbidden_interpretations` escalating to REVIEW (not BLOCK); originality PASS on an original
concept; BLOCK on a named meme-template reference; REVIEW on a near-duplicate-of-headline
punchline; a negative test proving incidental short word overlap does *not* false-positive the
duplicate check; the combined gate taking the worse of its two sub-decisions in both directions;
and `apply_meme_safety_originality_shadow()`'s mode gating (off = byte-identical passthrough,
shadow = exactly one new key, malformed input raises rather than silently degrading - the
try/except swallowing belongs to the executor hook, not this pure function, matching every prior
`apply_*_shadow()` function's identical division of labor).

Regression checks: the full Phase 18 test suite (M1+M2+M3, 54 tests across 4 files) passes
together, confirming the `detect_sensitive_categories` rename didn't break M1's own tests.
`python -m pytest --collect-only -q` - 2197 tests collected (2182 + 15 new), 0 collection errors.

Not run this session (disclosed, same constraint as M0-M2): `_attach_meme_safety_originality()`
against a real `CapabilityExecutor`/database - the local Postgres/Redis stack remains unavailable.

## 4. Risks / limitations carried forward

- Originality detection cannot see the outside world (§2) - this is permanent, not a future TODO.
- The known-meme-template list and the near-duplicate-headline threshold (80% token overlap) are
  v1, uncalibrated against real shadow-mode volume - same caveat as M1's own thresholds.
- `calibrated_fact_safety_status` is currently always `None` in the live call site - the gate is
  therefore currently running on concept-text-sensitivity and self-disclosure signals only, not
  yet benefiting from Phase 17's fact-safety machinery, until a later milestone wires it through.

## 5. Next milestone

M4 (Meme Copywriting) - a second, separate LLM capability (not merged with `meme_concept`,
consistent with this codebase's one-capability-per-judgment precedent, per `docs/
phase18_m0_meme_discovery_report.md` §10). `WorkflowType.MEME_GENERATION` registration is
reassessed once M4 lands, per M2's own §5.
