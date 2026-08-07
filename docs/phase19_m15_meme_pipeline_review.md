# Phase 19 M15 — Meme Pipeline Review

**Documentation only. No code changes in this milestone.**

## 1. Current trigger gap

No live trigger exists anywhere in the meme pipeline today — confirmed by inspecting every meme-
related setting in `core/config.py`:

| Setting | Default | What it gates |
|---|---|---|
| `meme_opportunity_mode` | `"off"` | Whether `services/meme_opportunity.py::assess_meme_opportunity()` even runs |
| `meme_safety_gate_mode` | `"off"` | Safety/originality gating before a concept is considered |
| `meme_image_generation_mode` | `"off"` (`"dry_run"` also exists) | Real image generation — `"dry_run"` wires only `MockImageAdapter`, zero network/cost |
| `meme_telegram_preview_mode` | `"off"` (`"dry_run"` also exists) | Telegram preview delivery — `"dry_run"` only logs the payload, never calls the Telegram API |

Every stage — opportunity detection through image generation to Telegram delivery — is either
fully off or the safest possible non-production stub. There is no scheduler, cron, or worker path
that invokes any part of this pipeline automatically; `meme_concept`/`meme_copywriting`
capabilities are registered (like every capability, per this codebase's own "register everything,
wire selectively" convention) but referenced by no live `WorkflowDefinition` step. The gap is
simply that nothing has been turned on — not a missing mechanism, a missing *decision* to
activate one.

## 2. Relationship between Story Memory and meme-opportunity detection: none, today

`services/meme_opportunity.py::assess_meme_opportunity()` scores a candidate on five independent
signals: irony/contrast, audience relatability, visual potential, topic fit, and freshness (recency
of `published_at`). None of these read `services/story_memory.py`'s output (`match_type`,
`confidence`, or the linked `Story`) at all — the two systems are currently fully independent.

The one place Story Memory's `match_type` *is* already consumed for a scoring purpose is
`services/editorial_scoring.py::_compute_novelty_component()` (Phase 18.10 M7) — a novelty
component in the **editorial** scoring pipeline (`new_story`→1.0, `story_update`→0.45,
`supporting_source`→0.15, `semantic_duplicate`→0.0, `uncertain_match`→0.5), unrelated to memes.

## 3. A possible future enhancement (not implemented, not scheduled)

Meme-worthiness plausibly correlates with a story's novelty in the same way editorial
newsworthiness does, but not identically:

- A `semantic_duplicate`/`supporting_source` match (a rehash of something already covered) is
  probably a *weaker* meme candidate — the surprise/freshness that makes for a good meme has
  already been spent on the first post.
- A genuine `story_update` (something materially changed) could be a *stronger* candidate in
  specific cases (an unexpected plot twist is often more meme-worthy than the original
  announcement) — the opposite direction from a naive "novelty = better meme" assumption, so this
  is not a simple reuse of `_compute_novelty_component()`'s existing weights.

Any such integration would need its own calibration (mirroring this phase's own M6 discipline) —
substituting a value from a different domain (editorial newsworthiness) into meme-opportunity
scoring (audience amusement) without evidence that the two actually correlate the way assumed
would be exactly the kind of unvalidated coupling this codebase's own conventions warn against.
Not proposed as a concrete design here — noted only as a plausible direction for a future,
separately-scoped and separately-calibrated milestone.

## 4. Why no activation is performed in Phase 19

This phase's own hard prohibitions are explicit and unconditional: no meme generation activation,
regardless of any other milestone's findings. Independent of that instruction, activating any
stage of the meme pipeline would require its own real-provider validation (real image generation
calls, real Telegram sends) exactly analogous to the paid-call/live-activation authorization every
other Phase 19 milestone with a real-provider component (M3's comparison script, M13's vision
harness) explicitly defers — no such authorization exists for the meme pipeline in this run, and
none is requested by this review.

## 5. What this milestone does

- Confirms (by inspection, not by assumption) that every meme mode remains at its safest default.
- Documents the current, real absence of any relationship between Story Memory and meme-
  opportunity detection.
- Records a plausible, unimplemented future direction with an explicit caveat about needing its
  own calibration before ever being trusted.
- Makes no code change, no settings change, and no activation of any kind.
