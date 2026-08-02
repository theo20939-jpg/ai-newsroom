# Phase 17 M4.1 — Reasoning-Budget Exhaustion Fix (Beginner-Friendly Copywriting Candidates)

Status: **COMPLETE — EMPTY OUTPUT FIX VALIDATED ON REAL DATA**. Live replay executed 2026-08-02
(7 calls, $0.026632, all 7 valid). Every number in this report is taken directly from the real
Gateway response data or the deterministic Fact Safety audit — nothing is estimated or assumed
past §7.

## 1. Blocker this milestone fixes

M4's own real 32-case paid run (`docs/phase17_m4_beginner_friendly_copywriting_report.md` §20,
§22) produced **7/32 empty candidate generations** (`candidate={}`) despite
`candidate_generated=True` and substantial real `output_tokens` usage — a 21.9% truncation rate
against M4's own 0% target. M4 explicitly deferred the fix (its own 32-call hard cap was already
spent under a single user-confirmed paid batch) and recorded a final verdict of **TUNING
REQUIRED**, not VALIDATED, specifically because of this defect. M4.1 exists solely to fix this
one defect and replay only the 7 affected cases — it does not touch prompt content, `safe_range`
logic, or any other part of M4's design.

## 2. Root-cause proof (inherited from M4, re-verified here)

For all 7 affected `draft_id`s (`fa60525c`, `44381b14`, `7352db1a`, `5c856b45`, `d9c0b32c`,
`7bca7a5b`, `073437a9`), `token_usage.output_tokens` **exactly equals** the script's own computed
`max_tokens` cap (`min(1200, round(safe_range.max_words * 4) + 150)`):

| draft_id | safe_max_words | max_tokens cap | output_tokens |
|---|---|---|---|
| fa60525c | 112 | 598 | 598 |
| 44381b14 | 112 | 598 | 598 |
| 7352db1a | 252 | 1158 | 1158 |
| 5c856b45 | 320 | 1200 | 1200 |
| d9c0b32c | 90 | 510 | 510 |
| 7bca7a5b | 112 | 598 | 598 |
| 073437a9 | 90 | 510 | 510 |

An exact match in all 7 cases, not a coincidence. The OpenAI Responses API this project's Gateway
calls exposes exactly **one** output budget, `max_output_tokens` — reasoning and visible-answer
tokens are drawn from the same pool (`usage.output_tokens_details.reasoning_tokens` is a
subcategory of `output_tokens`, never a separate counter, per
`integrations/llm_gateway/providers/openai_adapter.py`'s own `_translate_response()`). M4's own
`_build_candidate_request()` set `reasoning_effort="medium"` — a deliberate deviation from M3's
own `"low"` — with no matching increase to `max_tokens`. Internal reasoning consumed the entire
budget before any visible-answer token could be written, for exactly the cases with the largest
`safe_range` (plausibly the most complex sources, triggering more internal reasoning). M3's own
real 32-case run used the identical `max_tokens` formula with `reasoning_effort="low"` and had
**zero** truncations — the only variable M4 changed was `reasoning_effort` itself. This isolates
the cause to `reasoning_effort`, not to the token-cap formula, not to prompt content, and not to
`safe_range` sizing.

## 3. Policy change: `reasoning_effort` medium → low

`services/candidate_generation_policy.py`: `PRIMARY_REASONING_EFFORT = "low"` — reverts M4's own
`"medium"` back to M3's real, proven-safe value (zero truncations across M3's own 32-case real run
using the identical `candidate_max_tokens()` formula). This is the minimal fix, not a redesign:
prompt content, `safe_range` derivation, and the token-cap formula itself are all left unchanged
from M4 (`candidate_max_tokens()` is verbatim M3's/M4's own formula).

## 4. Controlled retry: low → none

If, and only if, the primary attempt at `reasoning_effort="low"` still returns an empty visible
output, `services/candidate_generation_policy.py` allows exactly one retry at
`RETRY_REASONING_EFFORT = "none"` (`MAX_RETRIES = 1`, enforced in
`generate_with_retry()`'s own retry-count logic, not just by convention). `"none"` is not a
speculative untested value — it is already this project's own production `reasoning_effort` for
the `research` capability (`capabilities/executor.py`'s `_REASONING_EFFORT_BY_CAPABILITY`). No
case receives more than 2 total generation calls (1 primary + at most 1 retry).

## 5. Empty-output classification

`services/candidate_generation_policy.classify_empty_output()` is pure and never raises — any
unexpected input shape is classified `UNKNOWN_EMPTY_OUTPUT` rather than propagating an exception
into the replay loop, so a single malformed response cannot abort the whole batch. It returns
`None` only when `structured_output` is a real, non-blank dict (non-blank `title` and `body`).
Every other path returns a specifically named `EmptyOutputReason`:

- `EMPTY_VISIBLE_OUTPUT` — structured output present but `title`/`body` blank.
- `REASONING_BUDGET_EXHAUSTED` — `finish_reason == "length"`, response text blank, and
  `reasoning_tokens` is at least 90% of `output_tokens` (only applied when the provider actually
  reports `reasoning_tokens`; never inferred when that field is absent).
- `OUTPUT_CAP_REACHED` — `finish_reason == "length"`, response text blank, reasoning-token
  threshold not met.
- `PROVIDER_EMPTY_RESPONSE` — blank response text, `finish_reason` not `"length"`.
- `PARSE_EMPTY` — non-blank `response_text` that didn't parse as the requested JSON schema
  (`openai_adapter.py`'s own `_translate_response()` leaves `structured_output=None` on a
  `JSONDecodeError`).
- `UNKNOWN_EMPTY_OUTPUT` — classification itself hit an unexpected exception.

An empty-output candidate can never be silently counted as a normal result — every empty case
carries a named reason into the output record.

## 6. Failed-only replay design

`scripts/phase17_m4_1_failed_case_replay.py` replays **only** the 7 pinned failed cases
(`scripts/_phase17_m4_1_failed_case_ids.json` by default). The 25 already-successful M4
candidates are never regenerated — reused verbatim from
`scripts/_phase17_m4_comparison_results.json` via `_load_m4_records()` and merged in by
`_write_merged_output()`. Discipline matching `scripts/phase17_m4_beginner_copywriting_comparison.py`
exactly:

- Defaults to `--dry-run` (no Gateway call, plan-only output).
- A real (paid) call additionally requires **all** of: `--live`, `--confirm-paid-calls`, and
  `core.config.settings.beginner_copywriting_mode == "comparison"`.
- Hard cap of 7 primary calls + at most 1 retry per case (14 calls total, worst case), enforced
  regardless of any `--max-cases` value.
- Resume support: an existing `--output` file's already-resolved (`final_status` present) records
  are kept, not re-generated, on a subsequent run.
- Read-only against the database — never calls `session.add/flush/commit` on
  `ContentDraft`/`EditorialTask`/`NewsEvent`.
- Never imports `bot`/aiogram or `services.collector`/`integrations.sources` — Telegram sends and
  new event collection are structurally unreachable from this script's import graph.
- A per-case failure is logged and the run continues — never aborts the whole batch.
- Output is a local, untracked JSON artifact — never written to `ContentDraft`/`EditorialTask`.
- Merge is deterministic: the 25 original M4 records are never touched or re-derived; an old,
  empty artifact for a replayed ID is always replaced by that ID's own newest replay outcome,
  never mixed with it.

## 7. Dry-run result

`scripts/_phase17_m4_1_dry_run_results.json` (local artifact, not committed — see §12): all 7
pinned failed cases processed successfully in plan-only mode.

```json
{
  "failed_case_count": 7,
  "cases_processed": 7,
  "dry_run": true,
  "live_allowed": false,
  "resumed_from_existing": 0,
  "total_calls_made": 0,
  "total_estimated_cost_usd": 0.0,
  "valid_count": 0,
  "still_empty_count": 0,
  "retry_used_count": 0
}
```

Zero LLM calls, zero cost, as expected for a dry run. `BeginnerFriendlyPlan`s were rebuilt for all
7 cases with no plan-construction errors. Computed `safe_range` stats across this 7-case subset:
mean `max_words` = 155.4, mean `target_words` = 130.4 — close to M4's own full-32-case means (158.4
/ 133.6), confirming this subset is not systematically different in size from the general
population.

## 8. Tests

36 targeted tests, all passing:

```
tests/test_candidate_generation_policy.py + tests/test_phase17_m4_1_replay.py
....................................                                     [100%]
36 passed in 2.12s
```

Additional local checks, all clean:

- `ruff check` on all 4 changed files — all checks passed.
- `mypy` on all 4 changed files — no issues found.
- `python scripts/validate_architecture.py` — 0 forbidden-dependency violations.

## 9. Cost controls

- Live calls require `--live` **and** `--confirm-paid-calls` **and**
  `settings.beginner_copywriting_mode == "comparison"` — any one missing blocks all Gateway calls
  (`replay_live_requested_but_blocked` logged instead).
- Hard cap: 7 primary calls, at most 7 additional retries (one per case, only on a classified
  empty primary result) — **14 calls maximum**, enforced in code, not just by convention.
- Resume support avoids re-spending on cases an interrupted prior run already resolved.
- A per-case cost is computed from the real Gateway `usage` response
  (`ModelRegistryPricingCatalog`) and summed into `total_estimated_cost_usd` — never estimated
  post hoc from assumptions.

## 10. Planned merge with 25 existing candidates

`_write_merged_output()` (in `phase17_m4_1_failed_case_replay.py`) builds
`scripts/_phase17_m4_1_dry_run_merged.json`/the real merged-output file by taking the 25
already-successful M4 records from `scripts/_phase17_m4_comparison_results.json` unchanged, and
replacing each of the 7 originally-empty records with that same `draft_id`'s newest replay outcome
(`valid` or `still_empty`, whichever the live run actually produces). No original M4 record is
regenerated or re-derived. This merge has been dry-run exercised
(`scripts/_phase17_m4_1_dry_run_merged.json` produced from the dry-run pass above, where all 7
replayed records carry `replay_skipped_reason="dry_run"` rather than a real candidate) but **not
yet exercised against real replay output** — see §11.

## 11. Live replay metrics — real results (2026-08-02)

Command run: `BEGINNER_COPYWRITING_MODE=comparison python -m
scripts.phase17_m4_1_failed_case_replay --live --confirm-paid-calls`. Summary
(`scripts/_phase17_m4_1_replay_results.json`):

```json
{
  "failed_case_count": 7, "cases_processed": 7, "dry_run": false, "live_allowed": true,
  "resumed_from_existing": 0, "total_calls_made": 7, "total_estimated_cost_usd": 0.026632,
  "valid_count": 7, "still_empty_count": 0, "retry_used_count": 0
}
```

**7/7 valid, non-empty candidates. 0 retries needed (no primary attempt was classified empty). 0
still-empty.** Model: `gpt-5.6-luna` for all 7 calls (same as M4's own real run). Per-case detail:

| draft_id | reasoning_effort | finish_reason | output_tokens | reasoning_tokens | cost (USD) |
|---|---|---|---|---|---|
| fa60525c | low | stop | 195 | 0 | 0.002964 |
| 44381b14 | low | stop | 157 | 0 | 0.002582 |
| 7352db1a | low | stop | 452 | 156 | 0.004705 |
| 5c856b45 | low | stop | 586 | 299 | 0.005473 |
| d9c0b32c | low | stop | 316 | 159 | 0.003690 |
| 7bca7a5b | low | stop | 380 | 227 | 0.003937 |
| 073437a9 | low | stop | 246 | 66 | 0.003281 |

Every case ended with `finish_reason="stop"` (natural completion, never `"length"`) — confirms
the primary root cause (§2) is fully resolved: none of the 7 previously-truncated cases hit the
output cap this time, at `reasoning_effort="low"`. Total cost **$0.026632** for the initial 7
calls, well under the $0.04 estimate and the $0.08 worst-case ceiling presented for confirmation.

**Deterministic `CandidateFactSafetyAudit`** (run automatically inside the replay for every valid
case, zero additional LLM calls): of the 7, 0 `pass`, 5 `review`, 2 `fail`. Manual read of both
`fail` cases found each a known false-positive class already disclosed in M4's own §26 (not a new
extractor limitation) — see `docs/phase17_m4_beginner_friendly_copywriting_report.md` §33 for the
full breakdown.

**Manual review of all 7 new candidates** (same rubric as M4's own §23): 0/7 WEAK, 0/7 MISLEADING,
0/7 contain a fabricated or unsupported specific fact. 2/7 (`7352db1a`, `073437a9`) preferred over
their own M3 candidate; the remaining 5/7 rated TIE (comparable accuracy/hedging, none worse than
M3). Filler rate 0/7, repetition rate 0/7 (`detect_filler_phrases()`/`detect_repetition()` run
directly against the new candidate bodies). 2/7 are headline-only/thin-source cases
(`d9c0b32c`, `073437a9`); headline-only fabrication rate 0/2.

**Merged 32-case metrics** (25 original M4 + 7 replayed, `scripts/_phase17_m4_1_merged_results.json`):
empty/truncated 0/32 (0%, down from 7/32); mean words 94.5, median 90.5; safe-range compliance
19/32 (59.4%, up from 15/32=46.9%); ideal-range compliance 7/32 (21.9%); preferred-or-tied vs M3
31/32 (96.9%); quality GOOD 29 / ACCEPTABLE 3 / WEAK 0 / MISLEADING 0 (of 32); Fact Safety
pass 4 / review 25 / fail 3 (of 32). Full table and discussion in
`docs/phase17_m4_beginner_friendly_copywriting_report.md` §33 (closure appendix — original M4
results untouched, only appended to).

**Production impact verified**: `ContentDraft.updated_at == created_at` for all 7 replayed rows
(checked directly against the database post-run) — no mutation. Zero Telegram messages sent
(structurally unreachable — no `bot`/aiogram import). No production prompt, routing, or worker
config changed at any point in M4.1.

## 12. Artifact handling

`scripts/_phase17_m4_1_dry_run_results.json`, `scripts/_phase17_m4_1_dry_run_merged.json`, and
`scripts/_phase17_m4_1_failed_case_ids.json` are local, untracked, temporary artifacts — consistent
with every prior M0–M4 milestone's own underscore-prefixed scratch files, none of which were
committed to the repository either. Only the implementation and tests
(`services/candidate_generation_policy.py`, `scripts/phase17_m4_1_failed_case_replay.py`,
`tests/test_candidate_generation_policy.py`, `tests/test_phase17_m4_1_replay.py`) were committed
(commit `170730a813bbd4bb8105f96f3f90391301aabd30`, "Fix reasoning-budget exhaustion in M4
candidates").

## 13. Status

**PHASE 17 M4.1 COMPLETE — EMPTY OUTPUT FIX VALIDATED.** The one defect in scope (7/32 empty
candidate generations from reasoning-budget exhaustion, `docs/phase17_m4_beginner_friendly_copywriting_report.md`
§22) is fixed and confirmed on real, paid replay data: 7/7 valid outputs, 0 still-empty, 0 retries
needed, $0.026632 total cost. Manual and automated review found no fabrication, no filler, no
repetition, and no case worse than its own M3 candidate introduced by the fix. `beginner_friendly`
copywriting remains shadow/comparison-mode only — no production prompt, routing, or worker change
was made, and no production activation decision is made by this milestone (out of scope). Pre-
existing length-target (safe-range) compliance variance, already disclosed in M4's own §21 at a
60% rate for the original 25 cases, is statistically unchanged for the 7 new cases (57.1%, 4/7) —
not a regression, and not a defect M4.1 ever claimed to fix.
