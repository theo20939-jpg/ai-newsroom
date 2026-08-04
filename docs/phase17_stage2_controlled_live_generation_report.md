# Phase 17 Stage 2 — Controlled Live Generation Report

**Real, completed run. Nothing in this document is simulated or projected — every figure below is
read directly from `scripts/_phase17_stage2_candidate_results.json` (this session, 2026-08-04) or
from a live, read-only database check performed immediately before and after the run.**

## Authorization scope

Explicit, narrow user authorization for Stage 2 controlled live candidate generation only, given
in two steps in this conversation: (1) an initial "PHASE 17 STAGE 2 LIVE RUN READY — USER
CONFIRMATION REQUIRED" pre-check, and (2) a second, explicit "CONFIRMED — RUN PHASE 17 STAGE 2 LIVE
CANDIDATE GENERATION" authorization naming the exact command to run. Scope: exactly 4 unique Stage
1 cases, duplicate excluded, ≤4 primary calls, ≤4 empty-output retries only if required, no
Telegram send, no `ContentDraft`/`EditorialTask` mutation, no automatic `editorial_preference`, no
Stage 3.

## Selected four cases

Resolved by read-only DB lookup from `docs/phase17_stage1_human_acceptance_packet.md` short event
IDs, with the duplicate-story pair (`17389223` vs `847618cd`) disambiguated by explicit user choice
(`847618cd` kept):

| Short event ID | Category | draft_id |
|---|---|---|
| `2d35bad8` | AI | `b372e285-dcbe-4873-9ccc-82f5f43faa7f` |
| `12ce8e52` | STARTUPS | `8b4f59f8-982b-490f-a734-691935a15be8` |
| `847618cd` | SOFTWARE | `56ca1a78-03cb-48a7-82d7-62a25a8fca8c` |
| `ac1f1ff5` | AI | `f0c40711-5dc4-40f1-99b4-9f98b99f9aa2` |

## Duplicate exclusion

`17389223` (same underlying Bottleneck Labs/"Saul" story as `847618cd`, picked up via a different
RSS feed — Habr: Machine Learning vs. Habr: Artificial Intelligence) was explicitly excluded, per
your selection, in favor of `847618cd`.

## A bug found and fixed before the real run

The first invocation of the approved command made **zero** calls and cost **$0** — not because
anything was blocked correctly, but because of a genuine defect in `_load_existing_output()`
(`scripts/phase17_stage2_candidate_generation.py`): it treated the prior dry-run's placeholder
`generation_status="dry_run"` records as already "resolved" and skipped them on resume, so the
live run silently reused the dry-run's empty candidates instead of generating real ones. Fixed by
introducing an explicit `_TERMINAL_GENERATION_STATUSES` set (`valid`, `still_empty`, `error`,
`skipped_insufficient_source`, `skipped_max_cases_reached`) that excludes `dry_run` and
`live_not_allowed` from resume-skipping — those are placeholder outcomes from a run that made no
generation attempt at all, not a resolved case. The corresponding test
(`tests/test_phase17_stage2_candidate_generation.py::test_load_existing_output_keeps_only_resolved_generation_status`)
was updated to assert the corrected behavior; all 13 Stage 2 unit tests pass after the fix. This
fix is disclosed here rather than silently folded in — it changed code behavior after the
checkpoint `checkpoint/phase17-stage2-candidate-generation`, before the real live run.

## Dry-run result (before the fix, and again after, both zero-cost)

Final dry-run immediately preceding the live attempt: `4 processed, 0 calls, $0.0 cost, all 4
generation_status="dry_run"` — baseline text and Fact Safety for all 4 cases matched the acceptance
packet's own disclosed figures exactly (word counts 35/34/45/33, Fact Safety pass/review/review/
review), confirming correct case resolution before any paid call was made.

## Live-call result

```
{
  "sample_size": 4,
  "cases_processed": 4,
  "dry_run": false,
  "live_allowed": true,
  "resumed_from_existing": 0,
  "cases_with_live_attempt": 4,
  "total_calls_made": 4,
  "total_estimated_cost_usd": 0.0155,
  "candidate_generated_count": 4,
  "not_yet_reviewed_count": 4
}
```

- Initial (primary) calls: **4**
- Retry calls: **0** — every case produced a valid, non-empty candidate on the first attempt at
  `reasoning_effort="low"`; the M4.1 empty-output retry policy (`reasoning_effort="none"` fallback,
  max 1 retry per case) was never triggered.
- Total calls: **4**
- Model: `gpt-5.6-luna` for all 4 calls (Gateway-routed, not pinned by this script or the prompt).
- Empty output rate: **0/4 (0%)**.
- Truncation rate: **0/4 (0%)** — `finish_reason="stop"` for every call, none hit the
  `max_tokens` cap (`candidate_max_tokens()`: 710/510/1200/1030 tokens respectively).
- Total cost: **$0.0155** (close to the pre-run estimate of ≈$0.015 typical/4-call case).

### Per-case token usage and cost

| Case | Input tokens | Output tokens | Reasoning tokens | Cost |
|---|---|---|---|---|
| `2d35bad8` | 1729 | 316 | 134 | $0.003625 |
| `12ce8e52` | 1597 | 223 | 106 | $0.002935 |
| `847618cd` | 2148 | 472 | 98 | $0.00498 |
| `ac1f1ff5` | 1908 | 342 | 110 | $0.00396 |
| **Total** | **7382** | **1353** | **448** | **$0.0155** |

## Candidate generation result

All 4 candidates generated successfully, non-empty, `finish_reason="stop"`. Candidate word counts
are consistently longer than baseline (baseline 35/34/45/33 → candidate 77/44/174/98 words) —
candidates move closer to (but in every case still under) their respective ideal-length ranges,
never over.

## Deterministic assessment comparison

Full detail and human-readable text in `docs/phase17_stage2_human_comparison_packet.md`. Summary:

| Case | Baseline completeness | Candidate completeness | Baseline Fact Safety | Candidate Fact Safety |
|---|---|---|---|---|
| `2d35bad8` | NOT_READY (0.500) | REVIEW (0.682) | pass | pass |
| `12ce8e52` | INSUFFICIENT_SOURCE (0.500) | INSUFFICIENT_SOURCE (0.800) | review (medium) | review (low) |
| `847618cd` | REVIEW (0.591) | REVIEW (0.773) | review (medium) | **fail (high)** |
| `ac1f1ff5` | REVIEW (0.636) | REVIEW (0.818) | review (medium) | review (low) |

Completeness assessments were recomputed deterministically (`build_editorial_completeness_assessment`,
zero LLM calls) with `calibrated_fact_safety=None` — the M5 calibrated-Fact-Safety criterion
therefore reads `UNKNOWN` (score 0.5) in every recompute rather than a real pass/fail; this is a
disclosed simplification, not a defect. The authoritative fact-safety comparison is the
`CandidateFactSafetyAudit` (already computed live during generation, same audit M4/M4.1 use) shown
in the right two columns.

**One case needs explicit human attention before any decision**: `847618cd`'s candidate Fact
Safety status escalates to `fail`/`high` — a numeric flag on "320.7M input tokens" (a figure that
*is* present in the disclosed source evidence, so this may be the same literal-text-matching gap
already disclosed in the M5 report rather than a genuine fabrication) plus two entity-phrase flags
and one causal-connector flag. See the comparison packet's Case 3, section E, for full detail —
this is flagged, not resolved, by this report.

Filler/repetition detection (folded into the same deterministic completeness pass): **0 flags in
any of the 8 texts** (4 baseline + 4 candidate). Truncation detection: **0/4** (see above).
Headline/body evidence-strength (headline-rewrite risk): baseline had one `medium` case
(`ac1f1ff5`) and three `low`/`not_applicable`; all 4 candidates are `low`/`not_applicable` — no
candidate increased rewrite risk relative to its own baseline.

No additional LLM judges were used for any of the above — every comparison in this report and the
companion packet is either the real Gateway output from the 4 approved calls, or a deterministic,
zero-LLM recompute.

## Production invariants (verified, not assumed)

- **`ContentDraft` mutated: no.** All 4 rows' `updated_at` and title+body hash confirmed
  byte-identical, read directly from Postgres immediately before and immediately after the run.
- **`EditorialTask` state mutated: no.** All 4 tasks' `status` and `updated_at` confirmed
  byte-identical across the same before/after check.
- **Telegram messages sent: 0.** `telegram_bot` container confirmed `Exited` before, during, and
  after the run; the Stage 2 script has no `bot`/`aiogram` import.
- **Workers started: no.** `automation_worker`/`content_worker`/`news_analysis_worker` confirmed
  `Exited`, RestartCount unchanged, throughout.
- **`editorial_preference` set automatically: no.** All 4 records remain `not_yet_reviewed` in the
  output artifact — only the separate, human-driven `record-preference` command can change this.
- **Feature flags/config changed: no.** `beginner_copywriting_mode` remains `off` at the process
  default; the live run's own `comparison` value was supplied only as a one-shot env var prefix on
  the single command invocation, never written to `.env` or `docker-compose.override.yml`.

## Remaining human decisions

Nothing has been decided. For each of the 4 cases, `docs/phase17_stage2_human_comparison_packet.md`
has an open review form (editorial preference, factual accuracy, completeness, clarity, headline
strength, candidate decision, failure reasons, notes) — none pre-filled, none inferred by this
report. `847618cd` in particular should not be approved without a human specifically checking the
flagged Fact Safety escalation.

## Stage 3

**Not started.** No canary delivery, no chat routing, no production cutover code exists or was
touched by this work. Stage 2 remains scoped to controlled candidate generation and comparison
only, exactly as authorized.

## Artifacts (not committed — local/untracked, matching every prior M0-M6 script's own convention)

- `scripts/_phase17_stage2_sample_ids.json` — the 4 `draft_id`s used as input.
- `scripts/_phase17_stage2_candidate_results.json` — full baseline/candidate text, token usage,
  cost, and Fact Safety audit per case (source of truth for this report).
- `scripts/_phase17_stage2_completeness_check.json` — the deterministic completeness recompute
  used in the table above.

These are left untracked, consistent with this project's own established discipline for every
prior Phase 17 milestone's `scripts/_phase17_*` scratch artifact — never `git add`ed. Only this
report and the comparison packet (both markdown, both free of raw token-level provider metadata
beyond aggregate counts already public in this document) are intended for commit.
