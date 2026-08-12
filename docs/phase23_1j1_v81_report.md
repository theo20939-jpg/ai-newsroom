# Phase 23.1J.1 — Copywriting V8.1 Finalization + Live Canary Preparation

**Branch**: `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(no new commits). **Status**: implementation + tests + offline golden replay + review packet
complete. **STOP — waiting for human review, no live canary run this phase.**
`copywriting_prompt_version` was set to `"8.1"` only in-process by one offline script — never
written to `.env`, not the production default (still `"4"`).

## Summary of changes

1. **Infra fix, test-first**: `prompts/copywriting/v8.1.yaml`'s literal filename would have
   crashed `FilePromptRepository`'s construction entirely (the existing `^v(\d+)\.yaml$` regex
   only accepted plain integers, with no try/except around the raise). Extended
   `integrations/prompts/file_repository.py` to accept one optional minor-version level
   (`^v(\d+(?:\.\d+)?)\.yaml$`), with a real numeric sort key (`(8,1)` sorts correctly between
   `(8,0)` and `(10,0)` — never a naive string comparison). 15 tests (12 pre-existing + 3 new),
   all passing; verified against the real `prompts/` directory that v4–v8 resolve unchanged.
2. **`prompts/copywriting/v8.1.yaml`** (new, v6/v7/v8 untouched): schema reduced to
   `title/main_body/ending/quote` — no `expandable_details` field at all. `main_body` is an
   "ABSOLUTE rule" single paragraph. Tighter length rules matching the phase brief's own new
   numbers.
3. **ContentDraft/Fact Safety compatibility**: confirmed, via 5 new tests, that the *existing* V8
   extraction branches in `services/content_draft_service.py`/`services/fact_safety.py` already
   handle V8.1's smaller shape correctly with **zero code changes** — both iterate their own
   V8 field-order tuples via `.get()`, which degrades gracefully for a key (`expandable_details`)
   that simply doesn't exist in a V8.1 dict.
4. **Presentation layer** (`services/news_telegram_presentation.py`, additive only — V6/V7/V8
   functions untouched): `build_v81_news_body()` (single-paragraph `main_body`, defensive
   `_collapse_to_one_paragraph()` safety net, optional `ending` gated by the same
   filler/redundancy/hedge-family checks V8 established, new tighter soft/absolute ceilings) and
   `render_v81_news_card_html()` (headline + body + optional ending, no expandable block ever, no
   NINJA PULSE footer unless `include_ninja_pulse_footer=True` is explicitly passed — defaults to
   `False` this phase, per the brief's own "disable it from normal NEWS delivery" instruction).
   Also extended the shared `_FILLER_CONCLUSION_PATTERNS` list with the brief's own new "BAD
   ending" examples ("время покажет," "будет продолжаться," "может стать важным шагом," "станут
   известны позже") — a shared list, so this also strengthens V6/V7/V8's own filler detection;
   verified zero regression across all 47 presentation tests.
5. **Tests**: 3 (prompt repository) + 5 (ContentDraft/Fact Safety v8.1) + 11 (presentation v8.1,
   Cases 1/2/4/5/6/7 + structural checks) = **19 new tests, all passing**. Cases 8/9/10 (image
   delivery, text-only, legacy regression) confirmed via re-running the pre-existing
   `test_router_media_integration.py`/`test_editorial_delivery_mode.py` suites unchanged (V8.1 is
   not wired into `worker/content_cycle.py` at all this phase).
6. **Golden replay**: same 5 real stories as Phase 23.1J, real V8.1 CopywritingCapability calls
   (cost $0.020424, Research/Intelligence reused from cache). All 5 bodies are genuinely single
   paragraphs. **One real, disclosed finding**: without `expandable_details`, the Armenia story's
   main body absorbed the vendor/technical detail (Schneider Electric, Vertiv, GPU density) that
   V8 had previously routed into its expandable block, pushing this story to 445 characters
   (within STANDARD's 500 absolute ceiling, above its 400 normal target) and arguably keeping more
   technical detail than the "DELETE BEFORE EXPLAINING" rule intends. Flagged prominently in the
   review packet, not hidden or worked around.
7. **Regression**: 153 tests pass across every file touched plus adjacent modules. Ruff/mypy
   clean on all modified files (repo-wide ruff: same 6 pre-existing scratch-script issues,
   unchanged from every prior phase's own disclosure).

## Known limitation flagged for human decision

The Armenia finding (§6 above) suggests the "no overflow bucket" design may need one more
iteration of prompt wording (making "DELETE BEFORE EXPLAINING" more forceful specifically for
vendor/supplier names) if human review agrees the current result is too technical - not fixed
this phase, since the phase brief's own scope was implementation + offline validation only, and
this is exactly the kind of judgment call the review packet exists to surface.

## Production state (verified unchanged)

Branch/HEAD unchanged. `copywriting_prompt_version` back to `"4"` after every script run.
`automation_worker` never touched this phase (no live canary, no worker starts). No `.env`
changes. No enforce modes. No architecture changes beyond the disclosed, tested, backward-
compatible prompt-version-parsing extension.

## Next step

Per the phase's own explicit instruction: **STOP.** Waiting for human review of
`docs/phase23_1j1_v81_review.md` before any live canary.
