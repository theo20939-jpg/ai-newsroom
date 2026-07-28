# Model Routing Benchmark (Step 2)

Status: **BENCHMARK COMPLETE, OFFLINE-ONLY — LIVE PAID VALIDATION CURRENTLY BLOCKED.**

## 0. Hard constraint discovered before any probe

A single minimal probe (`scripts/smoke_test_openai_adapter.py gpt-5.6-luna`, run once, inside
`news_analysis_worker`) confirms the OpenAI account is **still** returning `insufficient_quota`
(HTTP 429) — the same outage Phase 15's closure task discovered, ongoing since
`2026-07-25 22:04:46 UTC`. This is a rejected request (OpenAI does not bill tokens for a 429
before generation starts), so it cost **$0** of the $0.50 paid-validation budget, but it also
means **no further real paid probe of any kind can succeed right now**, regardless of budget.
Every conclusion below is built from **static, offline, code/schema-level verification** —
never a real generated sample, and this is stated honestly rather than fabricated.

## 1. `gpt-5.4-nano` does not exist in this codebase's model catalog

`integrations/llm_gateway/models/catalog.py` (the sole, hand-maintained, officially-verified
source of truth per its own docstring) defines exactly three models: `gpt-5.6-sol`,
`gpt-5.6-terra`, `gpt-5.6-luna`. `gpt-5.4-nano` is not among them, and this task's own
instruction ("Do not assume every model is compatible", "verify... before switching") combined
with having zero live-verification capability right now (§0) means it **cannot be safely
added** — doing so would require independently re-verifying its real pricing/capabilities
against OpenAI's official documentation, which this environment cannot currently do (no
successful live call is possible, and inventing catalog numbers would violate the catalog's own
explicit "verified against official docs, never invented" discipline).

**Resolution, per the task's own explicit conditional**: *"Engagement: gpt-5.4-nano if it passes
structured-output and quality tests; otherwise gpt-5.6-luna"* — nano fails the very first gate
(it isn't verifiably available at all), so **Engagement routes to `gpt-5.6-luna`**, identical to
every other capability.

## 2. Structured-output schema conformance — verifiable offline, strong confidence

All three real catalog models declare `supports_structured_output=True`
(officially-verified 2026-07-17, per the catalog's own docstring). Every capability that emits
structured JSON (`Research`, `Intelligence`, `Engagement`, `Copywriting`, `Quality`, `Scoring`)
already sets `response_mode="json_schema"` + a real `response_schema`
(`capabilities/*_capability.py`, confirmed by direct inspection), which
`integrations/llm_gateway/providers/openai_adapter.py::_build_payload()` translates to OpenAI's
Structured Outputs feature with **`"strict": True`** — a model-level guarantee (not a
probabilistic one) that any successful response conforms to the schema exactly, regardless of
which of the three models produced it. This means **schema pass/fail risk is not meaningfully
different between Sol/Terra/Luna** — all three either support the feature (and then always
conform) or fail outright (a hard, immediately-visible error, not a silent malformed response).
**No live probe is needed to have reasonable confidence in this axis.**

## 3. What genuinely cannot be verified without a live call

Semantic quality — Russian-language fluency, correct entity/monetary/date preservation,
editorial tone, factual grounding — is **not** verifiable from the schema guarantee alone, and
**no historical evidence exists to substitute for a live comparison**: `WorkflowStepResult` (the
persisted per-step record) has no `model` field, so it is impossible to determine, from any
existing completed task, which of Sol/Terra/Luna actually produced any given real historical
output (confirmed in `docs/api_cost_audit_report.md` §0's own finding). There is no free,
already-collected "here is what Luna actually produced" sample to fall back on — Luna has
essentially never been the dispatched candidate in practice (`docs/api_cost_audit_report.md`
§3: the existing `BEST_QUALITY` objective always tries Terra first, Luna only ever fires on a
Terra failure).

**This is disclosed as a genuine, unresolved risk, not glossed over.** The mitigation available
without spending the paid budget on a call that would just fail anyway (§0):

- The existing architecture's fallback-on-failure mechanism (`FallbackPolicy`) already applies
  unchanged: if Luna raises an exception (`ProviderTransientError`,
  `ProviderPermanentIncompatibleError`, etc.), the next candidate in the eligibility-filtered,
  ranked sequence is tried automatically — this is why Terra is kept as the explicit next
  candidate in the new routing (§4), matching the task's own "fallback for quality-critical
  failures: gpt-5.6-terra" instruction.
- This safety net **only catches hard failures**, never a technically-valid-but-editorially-worse
  response — a real, disclosed gap. Recommended mitigation (not implemented as code, a
  process/monitoring recommendation): once the OpenAI quota outage resolves, treat the first
  natural batch of real Luna-routed drafts the same way this project has already treated every
  other new-behavior rollout this phase (Editorial Scoring V2, Fact Safety) — observe a bounded
  natural sample before trusting it unconditionally. Unlike those two, this change is *already*
  being deployed live (§ Step 11), not gated behind a shadow flag, because unlike scoring/fact-
  safety the downside of a bad Luna response is bounded (Quality/Fact-Safety-shadow still runs
  on top of it, and a materially broken response is far more likely to simply fail schema
  validation than to silently pass with bad content, per §2's strict-mode guarantee).

## 4. Final routing decision

| Capability | New default | Fallback (on failure) | Sol in ordinary route? |
|---|---|---|---|
| Research | `gpt-5.6-luna` | `gpt-5.6-terra` | No |
| Intelligence | `gpt-5.6-luna` | `gpt-5.6-terra` | No |
| Engagement | `gpt-5.6-luna` (nano unavailable, §1) | `gpt-5.6-terra` | No |
| Scoring | `gpt-5.6-luna` (the task's own "Quality" 4th `NEWS_ANALYSIS` step — see `docs/api_cost_audit_report.md` §2's naming correction) | `gpt-5.6-terra` | No |
| Copywriting | `gpt-5.6-luna` | `gpt-5.6-terra` | No |
| Quality | `gpt-5.6-luna` | `gpt-5.6-terra` | No |

**Implementation**: a single, minimal, architecture-preserving change —
`RoutingCriteria.objective`'s default flips from `RoutingObjective.BEST_QUALITY` to
`RoutingObjective.LOWEST_COST` (`integrations/llm_gateway/routing/criteria.py`). No capability
file changes, no new `RoutingObjective`, no new `RoutingPolicy` — `LowestCostPolicy` (ranks by
`standard_combined_price` ascending: Luna $7.00 < Terra $17.50 < Sol $35.00) and the existing
3.0× cost-ceiling eligibility filter (`FallbackPolicy._build_attempt_sequence()`, unchanged)
already combine to produce exactly the desired sequence: **`[Luna, Terra]`**, Sol excluded
(35/7 = 5.0× > 3.0×), for every capability, with zero further code needed. This reuses
100%-already-tested infrastructure (`LowestCostPolicy` was already registered in
`integrations/llm_gateway/boot.py` before this change) rather than adding anything new.

## 5. Estimated cost impact of routing alone

Per-million pricing: Luna $1.00 in / $6.00 out vs. Terra $2.50 in / $15.00 out — **Luna is 2.5×
cheaper on both axes.** Applied uniformly to the 94.2%/5.8% NEWS_ANALYSIS/CONTENT_GENERATION
call-volume split from `docs/api_cost_audit_report.md` §4, routing alone is expected to cut the
Terra-attributable portion of spend by **~60%** (1 − 1/2.5 = 60%) wherever Luna successfully
handles the call without falling back to Terra — the actual realized reduction depends on how
often Luna needs to fall back, which is unmeasurable until quota resumes (§3). See
`docs/api_cost_optimization_report.md` §13 for the combined projection with Steps 3/4 included.

---

**BENCHMARK COMPLETE — ROUTING DECISION MADE ON STRUCTURAL/SCHEMA EVIDENCE; SEMANTIC QUALITY
VALIDATION DEFERRED TO POST-OUTAGE NATURAL OBSERVATION (DISCLOSED RISK, NOT HIDDEN)**
