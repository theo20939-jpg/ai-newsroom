# Phase 17 Stage 1 — Human Acceptance Result

**Source of truth: the user's own verbatim review conclusions, given directly in conversation on
2026-08-04, in response to `docs/phase17_stage1_human_acceptance_packet.md`.** Nothing below is
inferred, reconstructed, or regenerated from the underlying data beyond what the packet already
disclosed — this document records a human decision, not a new technical analysis.

## What was reviewed

`docs/phase17_stage1_human_acceptance_packet.md` — the 5-event packet built from the completed
Stage 1 retry canary (`checkpoint/phase17-stage1-shadow-canary-validated`, HEAD `223df5a`,
documented in full in `docs/phase17_stage1_shadow_canary_report.md`, Attempt 2).

**Reviewed as 4 unique real events, not 5.** Events `17389223` and `847618cd` are the same
underlying Bottleneck Labs/"Saul" agent story, picked up independently by two different RSS feeds
(Habr: Machine Learning vs. Habr: Artificial Intelligence) — the packet itself flagged this pair as
"not a duplicate `ContentDraft` ... but worth reading together" (packet, Event 4 §B). The human
review treated this pair as a single duplicate-delivery case rather than two independent editorial
decisions, and excluded it from separate scoring. The remaining 4 unique cases reviewed:
`2d35bad8` (NOT_READY), `12ce8e52` (INSUFFICIENT_SOURCE), one of the `17389223`/`847618cd` pair
(REVIEW), and `ac1f1ff5` (REVIEW).

## Human decisions (verbatim conclusions)

- **Channel relevance decisions: approved.** No correction requested to channel-fit calibration.
- **No false high-confidence REJECT detected.** Relevant because the packet's own Stage 2
  Readiness Rule (Option A) explicitly conditions approval on "no dangerous false positive" —
  satisfied.
- **Completeness classifications considered useful** — the packet's own open question (would this
  shadow metadata actually help an editor, or is it just noisy given the M5 calibration gap) was
  resolved in favor of "useful."
- **NOT_READY (`2d35bad8`) and REVIEW cases were judged justified** — not calibration false
  positives. This directly answers the packet's Special Focus §1 question ("is this NOT_READY
  verdict catching a real gap ... or is it a calibration false positive") and the parallel question
  in Special Focus §3 for the REVIEW cases: the human's read is that these classifications are
  correctly applied, not artifacts of the evidence-matching gap.
- **Production text quality issues are real, and attributed to insufficient source evidence — not
  Phase 17 misclassification.** I.e., where the existing production drafts fall short (short
  length, thin sourcing), the root cause is the underlying source material, not a Phase 17
  component incorrectly flagging good copy as deficient.
- **Stage 2 is approved.**

## Findings

1. Channel-fit calibration requires no changes going into Stage 2.
2. The Stage 2 Readiness Rule's Option A bar (≥4/5 decisions judged correct, no dangerous false
   positive or false READY) is met — 0/5 events reached READY in the sample, so "false READY" was
   trivially absent, and the human found no false high-confidence REJECT either.
3. The completeness gate's known 0%-READY calibration conservatism (M5 report, disclosed) does not
   by itself disqualify the signal from being useful to an editor — it was judged useful as a
   REVIEW-focusing signal, consistent with how it was actually used in this review.
4. The specific NOT_READY and REVIEW verdicts inspected were judged correct, not the
   evidence-matching false positives the packet flagged as a live possibility.
5. Where production copy quality is weak, the cause is source thinness (partial/headline-only
   sufficiency), not a Phase 17 classification defect.

## Approval decision

**PHASE 17 STAGE 2: APPROVED**, per the packet's own "A. APPROVE STAGE 2" criterion, on the human
conclusions above. This satisfies the Stage 1 Human Acceptance Packet's own condition that "Stage 2
remains disabled ... [until] this document does not authorize it" (packet, Summary) — this document
is that authorization.

**Scope of the approval is explicitly bounded** (verbatim from the authorizing message):
- Do NOT activate production enforcement.
- Do NOT change default behavior.
- Stage 2 scope: controlled candidate generation only.

This matches the M6.1 cutover runbook's own Stage 2 description (`docs/
phase17_m6_1_production_cutover_runbook.md`, "Staged rollout" table): *"A new Copywriting candidate
is produced (comparison mode) for controlled tasks, never delivered."* Stages 3-5 (canary delivery,
broader rollout, REJECT enforcement) remain unauthorized and unaddressed by this decision.

## Remaining limitations carried forward (not resolved by this approval)

- **M5 completeness-gate calibration gap**: 0/5 events reached READY in this sample, matching the
  0/96 gold-set backtest already disclosed in `docs/phase17_m5_editorial_completeness_gate_shadow_report.md`.
  Still not suitable for enforcement. Does not block Stage 2 as scoped, since Stage 2 makes no
  automatic accept/reject decision of any kind.
- **Evidence-matching gap**: the fuzzy phrase/claim-overlap matcher under-credits paraphrased
  coverage of `why_it_matters`/`what_next`/`uncertainty` text (M5 report §23; packet Special Focus
  §1 and §3). The human review judged the specific instances inspected as correctly classified
  regardless — but the underlying matcher limitation itself is unchanged by this review.
- **Fact Safety raw `block`→calibrated `review` downgrade** on `847618cd` (packet Special Focus
  §3) — flagged in the packet as "worth a second look." The human conclusions recorded above do not
  separately resolve this specific downgrade; it is carried forward as an open item, not
  contradicted or confirmed.
- **Duplicate-story handling** (`17389223`/`847618cd`) was resolved for the purposes of *this
  review* (treated as one case) but no code change was requested or made to deduplicate such pairs
  at the `NewsEvent`/collector level — two independent `NewsEvent` rows and two independent
  `ContentDraft`s were still produced in production, unchanged.

## Status

Human acceptance: **COMPLETE**. Stage 2: **APPROVED**, controlled candidate generation only, per
the restrictions above. Implementation: **NOT STARTED** — see the companion plan document,
`docs/phase17_stage2_controlled_candidate_generation_plan.md`, prepared alongside this record per
the same authorization. No code in this repository has been changed by this document; no default
behavior changes; no production enforcement exists.
