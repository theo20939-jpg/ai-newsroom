# Phase V2.3A — One-Story Canary Reachability & Safety Repair — Report

Uncommitted. Canonical HEAD: `695a1f1a64ecb18ee74b1bc1bdccc78a81e811a4`. No paid image
generation, no Telegram send, and no commit were authorized or performed in this phase.

## Authoritative finding, verified

The V2.3 final report's proposed canary procedure (set `EDITORIAL_RECOMPOSITION_MODE=live` for
one story) was **reachability-incomplete**. Confirmed with code evidence
(`worker/content_cycle.py`):

1. **With `presentation_director_mode=off`, `editorial_recomposition_mode=live`: `maybe_recompose()`
   cannot execute.** The entire block containing the call is nested inside
   `if settings.presentation_director_mode != "off":` — false when mode is `off`, so the block
   (and everything inside it, including `editorial_recomposition_mode`'s own read) is never
   reached at all.
2. **With `presentation_director_mode=enforce`, `editorial_recomposition_mode=live`: every**
   NEWS-presentation item across every event in every cycle, for as long as the worker runs with
   those settings, would be affected — there is no per-story/per-event/per-task selector anywhere
   in this codebase (confirmed by grep).
3. **Env var changes require a process restart to take effect.** `core/config.py::get_settings()`
   is `@lru_cache`d and `settings = get_settings()` is a module-level singleton built once at
   process start — a running `automation_worker` never re-reads `.env`.
4. **No per-story canary selector exists.**

This confirms the proposed procedure was not safe as originally described — explicitly
acknowledged, not worked around.

## Resolution: isolated one-story canary harness

`scripts/nnj_editorial_recomposition_canary.py` — reuses `services.editorial_recomposition.
maybe_recompose()` and `services.brand_renderer.render_branded_media()` directly (never goes
through `content_cycle.py`, never flips `presentation_director_mode`/`pulse_brand_enabled`, never
restarts or touches the running worker). Mutates `settings.editorial_recomposition_mode` only in
its own one-off process (never `.env`, never the real container — same precedent as V2.3's own
Stage 15 local proof).

**Gates** (both required for any real call): `--live` and `--source-reviewed` (a temporary,
disclosed-as-such developer acknowledgement that the named source has no prominent portrait, is
not a screenshot/UI-dominant image, and shows a clean physical subject — not a claim the automatic
`evaluate_eligibility()` detects any of that). Missing either → zero provider calls.

**Cap**: at most 1 successful generation, gemini-3.1-flash-image only, at most 1 retry (genuine
transport/provider failure only, disclosed). Outputs: original copy, raw recomposed image (only if
generated), branded result (always, via the real `render_branded_media()`), machine-readable
manifest.

## Eligibility limitation — locked in documentation

See `docs/nnj_source_faithful_editorial_visual_recomposition_v1.md` §18 (added this phase): the
automatic eligibility check is a conservative pre-filter only, not proof of "safe to recompose" —
explicit disclosure plus three future paths (A: thread MediaRankingResult signals forward; B: a
real deterministic safety signal, no new ML classifier; C: retain manual eligibility). None solved
in this phase, per its own explicit scope limit.

## Tests

13 new tests (`tests/test_v2_3a_editorial_recomposition_canary.py`): structural AST proof that
`maybe_recompose(` is nested inside the `presentation_director_mode == "enforce"` block; both
missing-gate refusal cases; single-source-required; Gemini-Flash-only + 1-generation cap;
no-Pro/GPT-import proof; all-4-artifacts-produced under mocked live success; provider-failure
fail-open still produces a branded result with 0 Telegram sends; no Telegram/docker/subprocess
import anywhere in the harness. All passing. A genuine bug was caught and fixed while writing
these tests: `run_canary()` crashed on any `--output-dir` outside the repo root
(`Path.relative_to()` raising) — fixed with a safe `_display_path()` fallback.

## Side-effect audit

Paid image calls: 0. Telegram sends: 0. `automation_worker`: untouched (not restarted).
`presentation_director_mode`/`editorial_recomposition_mode`: still `off` in the real environment.

## Files changed (this phase)

New: `scripts/nnj_editorial_recomposition_canary.py`,
`tests/test_v2_3a_editorial_recomposition_canary.py`, this doc, `docs/phase_v2_3_runtime_wiring_
report.md` (retroactive V2.3 writeup), plus the §18 addition to
`docs/nnj_source_faithful_editorial_visual_recomposition_v1.md`. No production file touched.
