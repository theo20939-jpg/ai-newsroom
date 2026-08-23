# R2 Shadow Final Closure Report

Status: **CLOSED / PASS FOR SHADOW MVP**

Branch: `feature/r2-shadow-preparation`

## Scope completed

R2 established a read-only, shadow-only RECAP pipeline over the existing Newsroom architecture.

Implemented and validated:

- Event RECAP candidate construction;
- Story Integrity gating;
- RECAP readiness evaluation;
- announcement/timeline/fact projection;
- immutable RECAP synthesis prompts;
- single-Story bounded synthesis canary;
- Fact Safety verification;
- origin membership projection;
- synthesis evidence sanitization;
- nested publisher suffix removal;
- deterministic production-data candidate scanning;
- real paid synthesis canaries;
- conservative fail-closed behavior;
- `publishable=false` throughout R2 Shadow.

No separate crawler, worker, database, vector store, orchestration layer, or publication system was introduced.

## Production safety state

R2 remains shadow-only.

- Telegram publication: HOLD
- automatic production RECAP publication: HOLD
- Rich presentation: HOLD
- production workers were not started for R2 evaluation
- no RECAP database migrations were required
- no persistent Story/Event/Announcement state is modified by synthesis
- R1 Story semantics remain frozen during this checkpoint

## Synthesis validation

Real synthesis canaries demonstrated that the R2 path can produce useful editorial RECAP output under a bounded provider budget.

The corrective paid canary for Story:

`322a2615-f0b1-47a3-a111-116b10f001f1`

used:

- caller Gateway calls: 1
- physical provider attempts: 1
- fallback attempts: 0
- same-candidate retries: 0
- max tokens: 1000
- reasoning effort: none
- publishable: false

Publisher contamination was absent from both synthesis-facing evidence and final generated editorial text after the corrective fixes.

## Known Fact Safety limitation

The same paid canary produced a conservative Fact Safety REVIEW:

- claims checked: 9
- supported: 8
- unsupported: 1
- highest risk: medium

Flagged claim:

`Внедрение ИИ`

Offline replay reproduced the result exactly.

The evidence contains morphological forms such as `внедряют ИИ`, while the generated editorial text contains the nominalized form `Внедрение ИИ`.

This is retained as a conservative exact-match / morphological-granularity REVIEW.

No fuzzy or morphology-specific relaxation was introduced.

## Announcement-count limitation

`announcement_count` currently reflects report-level announcement clustering rather than a proven count of distinct real-world developments.

This behavior remains explicit in R2 Shadow diagnostics and is not silently interpreted as ground-truth development count.

## Falcon / Starlink production finding

Real Story:

`c4f1375e-af6c-4d4e-b1ba-042e09d845e5`

contained two reports that appear to describe different launches:

Origin:

`101-я миссия в 2026 году и 30-я успешная посадка: ракета Falcon 9 разом запустила 29 спутников Starlink`

Later member:

`SpaceX в сотый раз запустила ракету Falcon в этом году — на орбиту доставлено ещё 27 спутников Starlink`

The reports contain conflicting distinctive numeric evidence:

- 29 satellites vs 27 satellites;
- origin also contains 101 / 30 / 2026.

Existing announcement-identity logic detects the conflict and keeps them as two announcement clusters.

However, frozen Story Integrity currently returns eligible=True for the same pair.

This behavior is pinned by:

`tests/test_recap_r2_11_announcement_identity_forensic.py`

## Falcon first divergence: confirmed upstream

Production database forensic established the exact lifecycle.

Origin event:

`94a3a9eb-63b6-4e76-9f95-adde6f968c5d`

was linked as:

- match_type: `related_story`
- match_score: `0.3333333333333333`

and correctly created its own Story.

Second event:

`32f9e5f5-1baa-4fb2-af86-86872e29dc67`

was subsequently linked to that Story as:

- match_type: `story_update`
- match_score: `0.6538461538461539`

The exact offline Story Memory reproduction produced the same score:

- combined: `0.6538461538461539`
- Story Memory high threshold: `0.65`
- entity overlap: `0.6666666666666666`
- title overlap: `0.38461538461538464`

Story Memory identity scoring currently uses:

- entity overlap;
- title overlap;
- category bonus;
- topic bonus;
- distinctive shared entity gate;
- editorial content-type gate.

It does not use conflicting numeric facts as a Story-identity veto.

Therefore the first confirmed divergence is upstream of RECAP:

1. two different launch reports are available;
2. Story Memory scores the second report just above the confident threshold;
3. the second report is persisted as `story_update`;
4. it becomes a confirmed member of the first launch's Story;
5. RECAP later receives an already-contaminated Story.

This is classified as a known **Story Memory precision gap**, not an R2 origin-projection defect and not an R2 synthesis defect.

No Story Memory correction is implemented as part of R2 closure.

The issue should be addressed separately using a broader corpus of real Story Memory false-merge examples rather than retuning global identity semantics around this single case.

## R2 acceptance decision

R2 Shadow is accepted as a sufficiently safe RECAP MVP foundation.

Accepted limitations:

- conservative Fact Safety false REVIEW may occur;
- report-level `announcement_count` is not a proven development count;
- upstream Story Memory false merges can contaminate a RECAP candidate;
- candidate selection therefore remains conservative;
- editorial review remains required before any production publication.

No additional paid retry is required for R2 closure.

## Next phase

The next phase is not another R2 forensic repair.

The next phase is **RECAP Production Selection Policy**:

- define which Stories are eligible to become RECAP candidates;
- define minimum evidence/source requirements;
- define lifecycle/readiness timing;
- define conservative rejection conditions;
- exclude suspicious Story-integrity cases;
- decide editor-facing Telegram workflow;
- validate the resulting policy on a small fresh shadow sample before any production enablement.

R2 Shadow: **CLOSED**

Production RECAP: **HOLD pending selection-policy validation**
