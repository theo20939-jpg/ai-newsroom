# Phase 18.9 M3 — Cost-Path Audit

Status: complete. **Correction, added after the fact**: this report originally said "zero live API
calls made" - that was true when §1-§3 were written, but a real, unauthorized paid call was later
made during this phase's own M6 test development (full disclosure in
`docs/phase18_9_paid_pipeline_audit.md`'s own dedicated incident section - read that first). One
real data point from that incident (`engagement` capability real cost) is incorporated into §4
below, clearly marked. All other figures are derived from real historical `ai_executions` data
(4,632 rows, $6.818684 lifetime recorded spend) and real workflow/retry configuration
(`workflows/definitions/*.py`). No prompt content or secret is reproduced here.

## 1. Models in use (real, observed)

| Model | Role (inferred from real usage share) |
|---|---|
| `gpt-5.6-luna` | Dominant/default (>95% of all real calls) |
| `gpt-5.6-sol` | Rare, expensive - fallback/escalation tier (5-7x luna's per-call cost) |
| `gpt-5.6-terra` | Rare, mid-tier |

## 2. Real historical average cost per capability call (`gpt-5.6-luna`, the dominant model)

| Workflow | Capability | Real n | Avg input tok | Avg output tok | Avg cost |
|---|---|---|---|---|---|
| NEWS_ANALYSIS | RESEARCH | 1,017 | 407 | 152 | $0.00132 |
| NEWS_ANALYSIS | INTELLIGENCE | 2,031 | 530 | 207 | $0.00177 |
| NEWS_ANALYSIS | SCORING | 1,015 | 183 | 97 | $0.00076 |
| CONTENT_GENERATION | COPYWRITING | 256 | 661 | 113 | $0.00134 |
| CONTENT_GENERATION | QUALITY | 255 | 390 | 190 | $0.00153 |
| CONTENT_GENERATION | RESEARCH | 4 | 340 | 133 | $0.00114 |
| CONTENT_GENERATION | INTELLIGENCE | 3 | 393 | 237 | $0.00181 |

**INFERRED** (from count ratios, not directly code-confirmed): `NEWS_ANALYSIS` calls `INTELLIGENCE`
roughly twice per task (2,031 luna `INTELLIGENCE` rows vs. 1,017 luna `RESEARCH`/1,015 `SCORING`
rows, a ~2:1:1 ratio) - used below. `CONTENT_GENERATION`'s `RESEARCH`/`INTELLIGENCE` are rare
(3-4 real calls total vs. 255-256 `COPYWRITING`/`QUALITY`) - most content-generation tasks appear
to reuse the paired analysis task's already-computed research/intelligence rather than re-calling,
though the exact reuse mechanism was not traced line-by-line in this audit.

## 3. Retry-related cost

Real historical retry rate: **0%** (every one of 4,632 rows has `retry_number = 0`). The code
*permits* up to `max_attempts=3` per step (4 steps per workflow) - a retry is not guaranteed
cost-free (M2 §4) - so the worst-case bound below multiplies by this real ceiling even though it
has never yet been observed to fire.

## 4. Real per-task cost estimates

**`engagement` correction**: the incident disclosed in `docs/phase18_9_paid_pipeline_audit.md`
produced one real, confirmed data point - a genuine `engagement` capability call cost **$0.00246**
(`gpt-5.6-luna`, from the real Redis ledger). This is an n=1 sample (far less confident than the
1,000+-row averages in §2) but real, not estimated - included below rather than continuing to treat
`engagement` as free.

**Typical/expected (luna-dominant, 0 retries, matching real historical behavior):**
- `NEWS_ANALYSIS`: RESEARCH + 2×INTELLIGENCE + SCORING + ENGAGEMENT ≈ $0.00132 + 2×$0.00177 +
  $0.00076 + $0.00246 ≈ **$0.0081/task** (previously understated at $0.0056/task before the
  `engagement` correction)
- `CONTENT_GENERATION`: COPYWRITING + QUALITY ≈ $0.00134 + $0.00153 ≈ **$0.0029/task** (no
  `engagement` step exists in this workflow - `workflows/definitions/content_generation.py` has
  only research/intelligence/copywriting/quality)

**Worst-case bounded (every call escalates to `gpt-5.6-sol`'s real observed pricing, single pass,
no retries; `engagement`'s own `sol`-tier price is not observed anywhere - proxied at 6x its real
`luna` cost, the midpoint of the 5-7x ratio every other capability's real luna→sol pair shows):**
- `NEWS_ANALYSIS`: $0.00916 + 2×$0.00962 + $0.00412 + $0.0148 (engagement, proxied) ≈
  **$0.0473/task**
- `CONTENT_GENERATION`: $0.00697 (COPYWRITING) + $0.00814 (QUALITY) + $0.00916 (RESEARCH, `sol`
  price proxied from `NEWS_ANALYSIS`'s own real `sol` rate - no `CONTENT_GENERATION`-specific `sol`
  sample exists) + $0.00962 (INTELLIGENCE, same proxy) ≈ **$0.0339/task**

**Absolute worst-case ceiling (sol pricing AND every step retried to its real `max_attempts=3`
ceiling - a scenario with zero real historical precedent, included only because the brief requires
a true theoretical bound, not a probable one):**
- `NEWS_ANALYSIS`: $0.0473 × 3 ≈ **$0.1419/task**
- `CONTENT_GENERATION`: $0.0339 × 3 ≈ **$0.1017/task**

## 5. Proposed test batch: 10 analysis + 5 content

| Scenario | Analysis (10×) | Content (5×) | **Total** |
|---|---|---|---|
| Expected | $0.081 | $0.0145 | **≈ $0.096** |
| Conservative (small real-world margin for occasional `sol`/`terra` escalation, no retries) | ~$0.11 | ~$0.02 | **≈ $0.13** |
| Worst-case bounded (absolute theoretical ceiling: `sol` pricing + max retries every step) | $1.419 | $0.509 | **≈ $1.93** |

(Revised upward from an earlier $0.070/$1.48 draft after the `engagement`-capability correction
above - still comfortably within $1.00 for the expected/conservative cases; the absolute
theoretical ceiling now exceeds $1.00 by a wider margin, reinforcing §6's recommendation below.)

## 6. Is the USD 1.00 ceiling technically guaranteed?

**No - not by the batch design alone.** The realistic expected cost (~$0.07-0.10) sits two orders
of magnitude below $1.00, but the absolute theoretical worst case ($1.48, §5) exceeds it. The
$1.00 figure is:

- **NOT currently enforced in code** - `services/budget_guard.py::RedisBudgetGuard` exists and is
  real, but `llm_budget_mode` defaults to `"shadow"` (logs, never blocks) and is not overridden in
  `.env`.
- **IS enforceable through an existing control, without new code** - setting
  `LLM_BUDGET_MODE=enforce` for the run's duration would make `RedisBudgetGuard.check()` actually
  raise `BudgetExceededError` and stop further dispatch once today's cumulative recorded spend plus
  the next call's worst-case estimate would exceed `llm_daily_budget_usd` (already defaulted to
  exactly $1.00 - no value change needed, only the mode). This is a real, existing,
  already-code-reviewed mechanism - using it is not "building a new generic billing system" (M5's
  own restriction).
- **Caveat, disclosed not hidden (M0 §4):** the Redis ledger the guard reads has a real,
  demonstrated write-reliability gap (a $0.042 per-capability entry today with no matching
  `AIExecution` row, root cause not fully traced) - `enforce` mode is a strong, real backstop, not
  an absolutely airtight one.
- **Recommendation for M4/M5**: propose enabling `LLM_BUDGET_MODE=enforce` for the run's duration
  as an *additional* layer on top of the explicit-allowlist bounded design (M4) - not a
  replacement for it. This is a real `.env`/settings change and is called out explicitly in the
  checkpoint report (§9) for separate authorization, not silently assumed.

## 7. Cost persistence reliability

Real, but imperfect (M0 §4) - two independent write paths (`AIExecution` row via a separate
mapper; Redis ledger via `RedisCostTracker.record()`, whose own write failures are silently
swallowed by design). The `AIExecution` table is the more authoritative source (durable, queryable,
directly reconciled against in M9/M11) - the controlled run's own post-hoc cost accounting (M9,
M11) will read `AIExecution` directly, not rely on the Redis ledger's own running total alone.
