# R2 Shadow Corrective Checkpoint Report

Status: **PASS**

Branch: `feature/r2-shadow-preparation`

Checkpoint implementation commits:

- `66d9e26` — `fix(recap): sanitize R2 synthesis evidence`
- `8d84c1c` — `fix(recap): strip nested publisher suffixes in R2`

## Scope

This checkpoint addressed two deterministic R2 Shadow synthesis-evidence issues discovered during production-data shadow evaluation:

1. publisher/source suffixes leaking from raw Story and Announcement titles into synthesis-facing evidence;
2. a legitimate entity granularity mismatch in Fact Safety that caused the VTB case to false-BLOCK on `Банка России`.

The fixes are R2-local.

The following boundaries remain unchanged:

- R1 semantics remain frozen;
- `services/recap_event.py` was not modified;
- global `services/fact_safety.py` was not modified;
- stored Story/Event/Announcement data is not mutated;
- prompts remain immutable;
- Telegram publishing remains disabled for R2 Shadow;
- `publishable` remains `false`;
- no production RECAP deployment was performed.

## VTB finding and corrective behavior

Real shadow Story:

`e30c9ad0-b7d8-4dac-98fc-faa7f613491b`

Observed contamination included publisher suffixes such as:

- `Сибирское информационное агентство`
- `Самарская газета`

The deterministic fix now strips publisher suffixes only from the R2 synthesis-facing display projection.

Forensic/raw candidate data remains unchanged.

The legitimate `Банка России` entity is no longer false-blocked by the exact entity-granularity mismatch.

The previously generated tainted VTB draft correctly remains BLOCK because it explicitly attributes a claim to `Самарская газета`, which is absent from the cleaned evidence. The verifier was not weakened to make the old tainted draft pass.

## Nested syndication finding

Real shadow Story:

`322a2615-f0b1-47a3-a111-116b10f001f1`

Observed title shape:

`Компании Центральной Азии внедряют ИИ вдвое быстрее мирового уровня — Euronews - Kursiv Media`

A single suffix pass removed only the outer syndicator and left `Euronews` in synthesis-facing evidence.

R2 `_synthesis_display_title()` now performs a bounded second suffix pass while preserving substantive punctuation.

Verified behavior:

- `Euronews.com` removed;
- nested `Euronews - Kursiv Media` removed;
- substantive headline retained;
- VTB substantive trailing punctuation preserved.

## Offline regression validation

Focused corrective regression:

`5 passed`

Pure `tests/test_event_recap.py` suite:

`61 passed`

Additional checks:

- `python -m py_compile` — PASS
- `git diff --check` — PASS
- `mypy services/event_recap.py` — PASS

No database writes, Gateway calls, paid LLM calls, Telegram sends, or workers were used for these regression tests.

## Post-fix deterministic shadow observation

Post-fix deterministic run:

`/tmp/r2_shadow_runs/20260822T150506Z`

The batch scanner reported:

- LLM disabled;
- 200 Stories scanned;
- 198 candidates built.

For Story:

`322a2615-f0b1-47a3-a111-116b10f001f1`

the fresh synthesis-facing bundle contained the substantive Central Asia / Caucasus AI adoption headlines while containing neither:

- `Euronews`
- `Kursiv Media`

The raw forensic candidate continued to retain the original publisher-bearing titles.

## Paid corrective canary

Story:

`322a2615-f0b1-47a3-a111-116b10f001f1`

Run:

`/tmp/r2_shadow_runs/20260822T150506Z`

Provider budget:

- caller Gateway calls: 1
- physical provider attempts: 1
- fallback attempts: 0
- same-candidate retries: 0
- model: `gpt-5.6-luna`
- max tokens: 1000
- reasoning effort: `none`

Safety:

- evaluation status: `NEEDS_REVIEW`
- `publishable=false`
- no Telegram delivery
- no application workers started

Generated editorial text contained no `Euronews` or `Kursiv Media`.

**Publisher-contamination corrective objective: PASS.**

## Remaining Fact Safety REVIEW

The generated recap produced:

- claims checked: 9
- supported: 8
- uncertain: 0
- unsupported: 1
- highest risk: `medium`
- status: `review`

Single flagged claim:

`Внедрение ИИ`

Exact offline replay reproduced the saved result.

Forensics showed:

- `Внедрение ИИ` is present in generated editorial text;
- the exact phrase is absent from the cleaned Story title;
- the exact phrase is absent from the synthesis-facing evidence bundle;
- evidence instead contains morphological forms such as `внедряют ИИ`.

This is classified as a conservative exact-match / morphological-granularity REVIEW, not publisher contamination and not evidence corruption.

No fuzzy, semantic, or language-specific morphological matching is added as part of this checkpoint.

Global Fact Safety remains unchanged.

## Other shadow finding kept out of scope

Story:

`c4f1375e-af6c-4d4e-b1ba-042e09d845e5`

was rejected as a paid-canary candidate because its two announcements appear to describe different Falcon 9 / Starlink launches:

- 101st mission / 29 satellites;
- 100th launch / 27 satellites.

Despite `story_integrity_eligible=true`, this appears to be a Story Integrity false-positive / merge limitation.

It is intentionally not fixed in this corrective checkpoint.

## Final decision

R2 Shadow corrective checkpoint is **PASS**.

Confirmed:

- publisher suffix leakage fixed in deterministic and paid paths;
- nested syndication suffix leakage fixed;
- substantive headline evidence preserved;
- VTB legitimate entity false-BLOCK corrected without weakening publisher hallucination protection;
- paid corrective canary stayed within the one-attempt budget;
- no publisher contamination in generated editorial text;
- remaining Fact Safety REVIEW is understood and reproduced offline;
- no further paid retry is required.

R2 remains shadow-only.

Telegram: **HOLD**

Production RECAP deployment: **HOLD**

Rich presentation: **HOLD**
