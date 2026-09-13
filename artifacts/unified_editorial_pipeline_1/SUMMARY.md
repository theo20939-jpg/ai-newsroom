# UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 — Founder review package

Full detail lives in `docs/unified_editorial_production_pipeline_1_report.md` (sections A-U) and
`docs/unified_editorial_source_reconciliation_1.md`. This file is the visual/quick-reference index.

## Did we solve the class of problems, or one symptom?

**The class.** Three concrete symptom classes named in the phase brief, each traced to one shared
architectural gap and fixed once, centrally, rather than as three separate patches:

| Symptom | Old cause | New, shared fix |
|---|---|---|
| Telegram NEWS silently text-only | fallback decisions inline in `worker/content_cycle.py` | already fixed, prior phase — `_hold_for_visual_recovery()`; this phase adds the shared `RecoveryJob` contract around it |
| Wrong (ordinary) iPhone used for "iPhone Duo" carousel | no subject-identity check anywhere in media selection | `MediaResearchService` (shared, both platforms) + real vision-LLM `SubjectMatchClassification` |
| "начинается с юаней" (Maxus 9 DATA) | renderer-adjacent code re-parsing generated prose to recover a number | `StructuredDataContent` decided once, before rendering, from real evidence — the renderer never re-derives facts again |

## Architecture before / after

```
BEFORE                                          AFTER
NewsEvent                                       NewsEvent
  -> worker/content_cycle.py (2400 lines,          -> EvidencePack (evidence.py)
     everything inline: media, presentation,       -> StructuredContent (content.py) — DATA fixed
     render dispatch, caption budget,              -> VisualIntent -> MediaResearchService (media.py,
     transport, recovery)                             shared by Telegram + Instagram)
  -> services/presentation_director.py             -> CompositionPlan (composition.py) — DATA
     (DATA candidate = regex over prose)               precedence: graph > source image > typographic
  -> services/telegram_routing.py (transport)      -> [renderer, injected, V8 unchanged]
                                                    -> QualityGateResult (quality.py, shared —
Instagram: a completely separate, parallel            LANGUAGE_QUALITY catches Maxus-class defects
  content-package/render/gate/publish stack             on BOTH platforms)
  with zero code sharing                           -> DeliveryPackage | RecoveryJob (recovery.py)
                                                    -> platforms/telegram.py (caption budget fixed,
                                                       S19) | platforms/instagram.py (shared gate
                                                       over Instagram's own real, unmodified package)

                                                 worker/content_cycle.py: ONE new flag-gated,
                                                 exception-guarded shadow hook added; legacy logic
                                                 100% unchanged and still the only reachable path.
```

## The Maxus 9 DATA fix — real before/after

Real article text (SAIC Maxus 9, iXBT, independently fetched this phase):
> "Рекомендованная цена автомобиля начинается с 290 тыс. юаней (примерно 3,8 млн рублей)."

| | Old (`_find_data_candidate`/`_safe_label`, currently deployed) | New (`build_structured_data_content`) |
|---|---|---|
| Label | `Рекомендованная цена автомобиля начинается с юаней (примерно 3,8 млн рублей).` — number gone | `Стартовая цена Maxus 9` — clean, constructed |
| Value | `290` | `290` |
| Unit | `тыс` (currency word "юаней" dropped) | `290 тыс. юаней` captured whole |
| Root cause | (1) `с` missing from the guarded-preposition list; (2) `юань` never recognized as a currency at all | both fixed in the new pipeline's own vocabulary (S18 freeze — old module untouched) |

Reproduced and proven in `tests/test_editorial_pipeline_data_content.py` (pins the OLD bug as a
regression baseline, then proves the fix) and `tests/test_editorial_pipeline_language_qa.py`.

## Foldable-iPhone carousel — real replay

Real, live re-run of `scripts/_cross_platform_media_research_canary_1.py` against this reconciled
worktree (real downloads, real OpenAI vision call):

```
candidates_considered=4
candidates_by_classification={'mismatch': 1, 'exact_subject': 3}
exact_subject_media_not_found=False
selected=web:0:macrumors.com
selected_score=86.0
rejection_reasons=['tier1_local_ordinary_iphone: subject_match=mismatch (The candidate visibly
  depicts conventional non-foldable iPhones, while the claimed iPhone Duo would need to be
  represented as the distinct foldable/Duo product...)']
```

Full artifacts (before/after slide images, real downloaded candidate photos, the real vision-model
call log): `artifacts/cross_platform_media_research_canary_1/`.

## Three real Telegram HOLD examples (production, right now)

All three of the phase brief's own named cases are real, live production events — found via
read-only DB query, not fabricated — and all three are already correctly HELD, never silently
text-only:

| Event | `content_drafts.status` | Candidates |
|---|---|---|
| "Amodei, Altman, Musk call for slowing AI model development" | `hold_for_visual` | 0 eligible |
| "163 crimes involving keywords like AI-generated, deepfake..." | `hold_for_visual` | **2 eligible, ranked, stored — held anyway** |
| "'exponential' growth of AI is a 'warning sign'" | `hold_for_visual` | 0 eligible |

The deepfake case is the interesting one: real, usable media existed and the post still held — the
kind of case `MediaResearchService`'s richer selection could plausibly resolve differently once
wired into a live worker in a future phase.

## Telegram V8 parity proof

```
git diff b5d5276 HEAD -- services/brand_renderer.py services/nnj_master_news_overlay.py \
  services/presentation_director.py services/news_telegram_presentation.py services/render_evidence.py
```
→ **0 lines.** Byte-identical source, every existing V8 test still passing (460/460 of the
non-pre-existing-failing tests, exact same 17 pre-existing failures as the verified baseline).

## Instagram safety proof

`evaluate_instagram_package()` never touches the network — proven with a `socket.connect`
monkeypatch that raises `AssertionError` if any connection is attempted
(`test_evaluate_instagram_package_never_touches_the_network`). `instagram_publication_enabled`
stays `false`, untouched, throughout.

## Test summary

- 48 new tests across 9 files in `services/editorial_pipeline/`'s own test suite — all passing.
- 460 passed / 17 failed (all pre-existing, independently confirmed) / 0 errors across the 18
  existing test files that exercise `worker/content_cycle.py` — **NEW_FAILURES = 0**.
- `ruff` + `mypy`: 0 new errors.
- `SECRET_EXPOSURE_FOUND = false`.

## What this package is NOT

Not a production deployment. Not Instagram going live. Not the flag being turned on anywhere. Not a
rewrite of `worker/content_cycle.py`'s legacy logic (untouched, still the only reachable path). See
report §T for the complete, honest list of what remains open.
