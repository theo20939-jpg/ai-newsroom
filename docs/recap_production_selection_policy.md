# RECAP Production Selection Policy

Status: **MVP POLICY — SHADOW VALIDATION REQUIRED**

## Purpose

This policy decides which existing Story objects are worth sending into bounded EVENT_RECAP
synthesis for editorial review.

It is deliberately a separate layer from R1 readiness.

It does not redefine Story Memory, Story Integrity, announcement clustering, or readiness semantics.

It adds no database state, migration, worker, scheduler, model, embedding layer, or new orchestration
architecture.

## Output states

Every inspected Story must result in exactly one selection outcome:

- `REJECT`
- `WAIT`
- `MANUAL_IDENTITY_REVIEW`
- `EDITORIAL_CANDIDATE`

No outcome means automatic Telegram publication.

All generated RECAP content remains:

`publishable=false`

until a separately authorized production publication phase.

## Existing signals reused

The policy reuses existing signals only:

- confirmed-member event count;
- Story Integrity eligibility;
- Origin Membership Projection result;
- unique source count;
- last event time / cooling state;
- announcement clustering;
- editorial relevance;
- research-abstract detection;
- finance/investment detection;
- synthesis-input quality preflight;
- existing conflicting-distinctive-facts helper.

No new opaque numeric score is introduced.

## Existing readiness thresholds

Current configured R1 readiness thresholds remain unchanged:

- minimum confirmed events: `3`
- minimum announcement clusters: `4`
- minimum unique sources: `2`
- cooling window: `90 minutes`
- Story Integrity: required
- unresolved factual conflicts: zero
- research complete: required for natural R1 `READY`

The policy does not modify these settings.

## Important readiness limitation

R2 does not persist a `research_complete` signal.

The current readiness scanner correctly reports:

`research_complete_tracked=False`

Therefore natural `READY` must not be treated as a prerequisite for MVP production selection.

The production-selection layer may select a `COOLING` Story for editorial synthesis when its
evidence/maturity conditions are independently satisfied.

This is explicit selection-policy behavior, not a silent readiness override.

`research_complete` must continue to be shown as untracked/false in diagnostics.

## Announcement-count limitation

`announcement_count` is the existing report-level cluster count.

R2.11 proved that several publishers describing one real event can inflate this value.

Therefore:

**`announcement_count >= recap_min_announcement_count` is NOT a production-selection hard gate.**

Announcement count remains useful for:

- diagnostics;
- ordering candidates;
- understanding the evidence shape.

It must never by itself prove that a Story contains multiple real developments.

## REJECT

A Story is `REJECT` when any hard editorial/safety condition fails.

Hard rejection conditions:

1. Event RECAP candidate construction fails closed.
2. Story Integrity is ineligible.
3. Origin Membership Projection is required but ineligible.
4. Editorial relevance is rejected.
5. The Story is classified as a research-abstract-like item.
6. The Story is classified as finance/investment/advice-like material outside NINJA PULSE scope.
7. Synthesis-input quality preflight returns `FAIL`.
8. Publisher/evidence contamination is still present in the actual rendered synthesis bundle.

`REJECT` Stories are not sent to an LLM.

## WAIT

A structurally valid Story is `WAIT` when it has not yet accumulated enough evidence or has not
cooled sufficiently.

WAIT conditions:

- confirmed event count `< 3`; or
- unique source count `< 2`; or
- cooling window `< 90 minutes`.

A WAIT Story may become eligible naturally when more evidence arrives or the cooling interval
elapses.

No LLM call is made for WAIT.

## MANUAL_IDENTITY_REVIEW

A Story that otherwise satisfies the structural/evidence conditions enters
`MANUAL_IDENTITY_REVIEW` when the existing deterministic announcement evidence exposes a possible
Story-identity conflict.

The initial MVP signal is:

`_has_conflicting_distinctive_facts(...) == True`

for at least one relevant announcement pair.

This is a REVIEW signal only.

It must NOT automatically reject or split the Story because the frozen helper has known precision
limitations, including the decimal-comma case documented in R2.11.

Purpose:

catch suspicious Falcon/Starlink-class candidates before spending a paid synthesis call.

A human may inspect the evidence and either:

- approve the candidate for synthesis; or
- reject it as an upstream Story Memory false merge.

No Story Memory row or Story membership is modified by this review.

## EDITORIAL_CANDIDATE

A Story becomes `EDITORIAL_CANDIDATE` only when all of the following are true:

1. Story Integrity is eligible.
2. Origin Membership Projection is valid or not needed.
3. Confirmed event count is at least `3`.
4. Unique source count is at least `2`.
5. At least `90 minutes` have elapsed since the latest event.
6. Editorial relevance is accepted.
7. It is not finance/investment/advice-like.
8. It is not research-abstract-like.
9. Synthesis-input quality preflight is not `FAIL`.
10. The rendered synthesis evidence is clean of known publisher contamination.
11. No unresolved manual identity-review flag remains.

`announcement_count` is intentionally absent from this hard eligibility list.

`research_complete` is intentionally not fabricated.

## Synthesis contract

Only `EDITORIAL_CANDIDATE` may automatically enter bounded synthesis.

The existing R2 synthesis safety contract remains unchanged:

- one Story at a time;
- bounded provider budget;
- no uncontrolled retries;
- Gateway only;
- Fact Safety after generation;
- `publishable=false`;
- no automatic Telegram publication.

## Fact Safety output

After synthesis:

- Fact Safety PASS -> candidate may be shown to the editor;
- Fact Safety REVIEW -> candidate may be shown to the editor with REVIEW status;
- Fact Safety BLOCK -> do not present as publish-ready content.

A REVIEW is not silently converted to PASS.

## Editorial delivery target

The MVP endpoint is the existing editorial Telegram workflow.

RECAP is a new editorial material type, not a new publishing system.

The editor must be able to inspect:

- generated RECAP;
- source/evidence references;
- Fact Safety status;
- readiness/selection status;
- meaningful review flags.

Automatic public-channel publication remains out of scope for this policy.

## Final shadow validation

Before Telegram wiring, run one small fresh validation sample.

Target:

- 5–10 naturally selected Stories if available;
- quality over quota;
- do not manufacture weak candidates to hit a target;
- no broad historical backlog processing.

Validation must measure:

- selection outcome distribution;
- false REJECT;
- false EDITORIAL_CANDIDATE;
- MANUAL_IDENTITY_REVIEW usefulness;
- synthesis quality;
- Fact Safety PASS/REVIEW/BLOCK;
- publisher contamination;
- provider-attempt count.

Do not rerun paid synthesis automatically after a REVIEW/BLOCK.

Inspect the produced artifact first.

## Acceptance target

The policy is suitable for editor-facing MVP wiring when:

- no known unsafe candidate bypasses the hard gates;
- suspicious identity cases are surfaced before automatic paid synthesis;
- selected Stories are genuinely useful recap material;
- synthesis remains bounded;
- Fact Safety remains fail-closed;
- no Telegram auto-publication occurs.

## Explicitly deferred

Not part of this phase:

- Story Memory global retuning;
- Falcon-specific Story Memory fix;
- rewriting frozen R1 Story Integrity;
- automatic Story splitting;
- persistent RECAP research state;
- automatic public-channel publishing;
- Rich presentation.

These require separate evidence and authorization.
