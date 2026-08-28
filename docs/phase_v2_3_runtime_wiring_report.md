# Phase V2.3 — Runtime Recomposition Wiring, Default-OFF — Report

Uncommitted at time of writing (preserved through Phase V2.3A). Canonical HEAD:
`695a1f1a64ecb18ee74b1bc1bdccc78a81e811a4`.

## Summary

Implements the first production runtime consumer of the Phase V2.1/V2.2 image-edit
infrastructure: `services/editorial_recomposition.py` (`maybe_recompose()`,
`evaluate_eligibility()`), wired into `worker/content_cycle.py`'s NEWS presentation path only,
gated by a new `editorial_recomposition_mode` setting (`off`/`dry_run`/`live`, default `off`).

## Reachability (exact, as wired)

`maybe_recompose()` is reachable only when ALL of the following are true at once inside
`worker/content_cycle.py::run_content_cycle()`:
1. `settings.presentation_director_mode != "off"`
2. `settings.presentation_director_mode == "enforce"`
3. `settings.pulse_brand_enabled` is `True`
4. `presentation_decision.presentation_type == NEWS`
5. `source_bytes is not None`

Production has `presentation_director_mode = off` — the recomposition block is therefore
entirely unreached today, regardless of `editorial_recomposition_mode`. **This is the exact fact
Phase V2.3A re-verified and built a dedicated isolated canary harness around**, since the V2.3
report's own proposed canary procedure (implicitly: "just set `EDITORIAL_RECOMPOSITION_MODE=live`")
did not address this — see `docs/phase_v2_3a_canary_reachability_report.md`.

## Fail-open contract

Every failure at the `maybe_recompose()` boundary (provider error, timeout, unexpected exception,
empty image, undecodable result image, ineligible image, mode off) returns the caller's own
original bytes. Never escalates to `gemini-3-pro-image` or `gpt-image-2`.

## Eligibility (locked limitation — see the canonical doc §18)

Deterministic-only: requires `ResolutionBand.GOOD` + `AspectRatioBand.EDITORIAL_LANDSCAPE` (both
reused from `services/image_quality.py`, never new thresholds). No face/portrait/UI detector
exists in this codebase — this is a disclosed, real limitation, not a claim of scene
understanding. See `docs/nnj_source_faithful_editorial_visual_recomposition_v1.md` §18 for the
full statement and the three future paths (A/B/C) before any broader activation.

## Tests / validation

21 new tests (`tests/test_v2_3_editorial_recomposition.py`) covering OFF/DRY_RUN/LIVE-success/
LIVE-failure (5 distinct failure modes)/eligibility (7 cases)/security/prompt-equality. 272/272
relevant focused tests passing. Ruff/mypy clean.

## Files changed

`core/config.py` (+15, new `editorial_recomposition_mode` field), `worker/content_cycle.py`
(+34, the one hook). New: `services/editorial_recomposition.py`,
`tests/test_v2_3_editorial_recomposition.py`.

## Verdict (as originally reported)

A) DEFAULT-OFF RUNTIME RECOMPOSITION WIRING READY FOR LIVE CANARY — later corrected by V2.3A: the
proposed canary procedure was reachability-incomplete; see
`docs/phase_v2_3a_canary_reachability_report.md`.
