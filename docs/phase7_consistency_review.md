# Phase 7 Consistency Review — `phase7_ai_integration_layer_planning_v2.md`

No code, no migrations, no commits, no redesign. This document verifies internal consistency only — it does
not re-open design decisions, does not re-litigate whether a resolution was the *right* one, and does not
propose new abstractions except where naming one is the only way to describe a contradiction already present
in the text. `docs/phase7_ai_integration_layer_planning_v2.md` was not modified to produce this review.

Ten checks were run against the document as written. Findings are listed only where a specific, quotable
inconsistency exists — nothing below is inferred from what the document *doesn't* say unless the document
elsewhere makes a claim that absence contradicts.

---

## Findings

### 1. `RoutingEngine`'s filter-pipeline order is stated three different ways — **Major**

Three passages disagree on where the exclusion filter (`excluded_providers`) sits relative to the health
filter:

- **§A.1**'s own numbered sequence (steps 1–5) predates the exclusion filter entirely — it lists only hard
  filter → provider-enabled filter → health filter → zero-candidate check → preference ranking, with no
  exclusion step at all, and "steps 1–3" in step 4 was never updated to account for one.
- **§B.23** states the exclusion filter is inserted "between the provider-enabled filter and the health
  filter" — i.e., hard → provider-enabled → **exclusion → health** → ranking.
- **§C**'s `RoutingEngine` row states the pipeline as "Hard-filter → **health-filter → exclusion-filter** →
  preference-ranking" — health *before* exclusion, directly contradicting §B.23.
- **§D.5** states "hard filter → provider-enabled filter → **exclusion filter → health filter** →
  preference ranking" — matching §B.23, not §C.

§C is the odd one out against two other sections that agree with each other, and §A.1's own base sequence
was never amended to include the step at all. Functionally harmless — all of these are independent
set-membership predicates, so the final surviving candidate set is identical regardless of order — but this
is a genuine, three-way-checkable contradiction in the stated rule, not a stylistic variance.

### 2. "Never repeats a failed provider/model pair" is not reconciled with same-candidate retry — **Major**

§A.1 step 7 states, unqualified: *"TRANSIENT → mark `(provider_id, model_id)` unhealthy... move to next
candidate... **Never repeats** a failed provider/model pair within this call."*

§D.7 step 1 (and v1 §8, referenced as unchanged) states the Gateway performs *"up to `max_same_candidate_retries`
(default 1)... **before moving to the next candidate**."*

Read literally, these two rules conflict: if the very first transient failure on a candidate immediately
triggers "move to next candidate, never repeat this pair" (§A.1 step 7's wording), there is no point at
which a same-candidate retry could ever occur — it would already have been forbidden by the time
`max_same_candidate_retries` would apply. The document never states that "attempt" in step 7 is meant to
encompass the full attempt-plus-retry cycle for that candidate before the "never repeats" rule takes effect;
that reconciliation is a plausible reading, but it is not written down, and a reader implementing §A.1
literally would disable the same-candidate retry without being told they were doing so.

### 3. Budget check runs before the cache lookup, so a free cache hit can be denied for cost — **Major**

§A.3's exact sequence, confirmed identically by §D.6 and §D.11, is:

```
CostEstimator.estimate(candidate, request) -> CostEstimate(expected, worst_case)
BudgetGuard.check(capability_name, priority, worst_case) -> approve | deny
IF approved:
  CacheCoordinator lookup -> hit: return; miss: continue
```

`BudgetGuard` is consulted *before* the cache is ever checked. A request whose worst-case cost estimate
exceeds the remaining budget will be denied even if the response is already cached and would cost nothing
to serve. This is the exact scenario in which the cache matters most — under budget pressure — and the
stated ordering defeats it. Nothing in §A.2, §A.3, §C, or §D reconciles this; the cache is described
elsewhere as existing precisely to reduce provider spend, which this ordering partially undoes for any
candidate whose cache entry would have avoided a real call entirely.

### 4. `LatencyTracker` is real, stateful, and depended on, but has no entry in §C's component table — **Major**

§B.1 introduces `LatencyTracker` as *"a separate, explicitly stateful... component (owns the rolling p50
sample, Redis-backed... outside the `RoutingPolicy` entirely)"* — it is the mechanism that resolves the
purity contradiction the `FASTEST` objective originally created. §C's `RoutingEngine` row lists
`"LatencyTracker invocation"` as something `RoutingEngine` owns/does, and §E lists `LatencyTracker (Redis...)`
under components that must be distributed at scale.

But `LatencyTracker` itself is not one of the sixteen components documented in §C. Every other component
that holds genuine runtime state (`ProviderHealthStore`, `RateLimiter`, `CacheCoordinator`) has a full
owns/reads/writes/must-not-depend-on/state/failure-behavior row. `LatencyTracker` — despite being explicitly
called "stateful" in the same document that just finished insisting `RoutingPolicy` itself must stay pure —
has no such row. This is exactly the kind of state check 7 asks about: real mutable state that exists in the
design but isn't accounted for in the canonical boundary table the rest of the document relies on.

### 5. `WeightedSplitPolicy` cannot satisfy the `RoutingPolicy` Protocol as specified — **Major**

§B.1 fixes the `FASTEST`-objective purity contradiction by asserting, in the `RoutingPolicy.rank()`
docstring itself: *"Still pure: same three inputs always produce the same output."* This is stated as a hard
Protocol requirement, not a recommendation.

§B.17 then proposes `WeightedSplitPolicy(weights: dict[model_id, float])`, registered through the same
`RoutingPolicyRegistry` as any other `RoutingPolicy`, for gradual traffic migration between models — e.g.
"5% of calls to the new model, 95% to the old one." A percentage split is inherently non-deterministic
across otherwise-identical calls: the same `(candidates, criteria, telemetry)` input must sometimes rank the
new model first and sometimes the old one, or the split cannot exist at all. This directly contradicts the
purity requirement §B.1 just established two sections earlier, and §B.17 does not acknowledge the tension
or explain how a `RoutingPolicy` implementation can be simultaneously pure and probabilistic.

### 6. `CostTracker`'s ledger is not classified as needing distributed storage, unlike every structurally identical component — **Major**

§E's scalability table explicitly calls out `RateLimiter`, `CacheCoordinator`, `ProviderHealthStore`, and
`LatencyTracker` as needing to be Redis-backed at "millions of requests" scale, with the reasoning stated
plainly: *"an in-process rate limiter across N worker processes under-counts true request volume by a factor
of N, silently defeating the entire point of having one."*

`CostTracker`'s spend ledger is the one piece of runtime state Amendment C's entire justification depends on
— `BudgetGuard` reads it on every single candidate, and Amendment C's stated purpose is that *"budget
enforcement now happens in exactly one place, for every attempt."* §C's `CostTracker` row only says the
ledger is *"runtime, persisted in a future phase,"* without ever stating whether it is process-local or
shared, and §E's distributed-components list does not include it. At the same multi-process scale that
makes the Rate Limiter and Cache require Redis, an unshared ledger would mean each worker process enforces
budget against its own partial view of spend — the identical failure mode §E already names for the other
three components, left unaddressed for the one component whose entire redesign this pass was built around.

---

### 7. `BudgetGuard`'s parameter type is not explicitly reconciled with the new `CostEstimate` value — **Minor**

Amendment C (§A.3) states *"`BudgetGuard`'s own contract... is unchanged — only who calls it and when
moves."* Phase 6 describes `BudgetGuard.check()` as taking `(capability_name, priority, estimated_usage)`.
§A.3 now passes `worst_case` — a `Decimal` from the new `CostEstimate(expected, worst_case)` type — as that
third argument. Whether `estimated_usage` was always intended to be a cost figure (making this a
compatible, non-breaking substitution) or something usage/token-shaped (making this an unacknowledged
signature change) is never stated either way.

### 8. Response-cache TTL is said to be configurable "via `cache_policy`," but `cache_policy`'s shape doesn't support that — **Minor**

§A.2 states: *"Response cache TTL: default 1 hour... Configurable per-`Capability` via `cache_policy`, never
TTL-free."* `cache_policy` (v1, unchanged, referenced throughout §A.2) is a two-value
`Literal["none", "read_write"]` — a switch, with no field capable of carrying a TTL number. As written, the
document claims a configurability mechanism that the named field cannot actually express.

---

### 9. Citation discipline is a genuine strength — **Observation**

Outside the six items above, the document's internal cross-references (`§A.x`/`§B.x`/`§C`/`§D.x`) are
extensive and, almost without exception, accurate — the same rule is consistently traceable back to its one
origin across the four major sections. This is worth noting explicitly because it is what made findings 1
and 2 detectable at all: the contradictions are visible precisely because the surrounding citation practice
is otherwise rigorous enough that a mismatch stands out rather than being lost in vagueness.

---

## Summary

| # | Finding | Severity |
|---|---|---|
| 1 | `RoutingEngine` filter-pipeline order stated inconsistently across §A.1/§B.23/§C/§D.5 | Major |
| 2 | "Never repeats a failed pair" vs. same-candidate retry not reconciled | Major |
| 3 | Budget check sequenced before cache lookup — a free cache hit can be wrongly denied | Major |
| 4 | `LatencyTracker` is stateful and depended-upon but absent from §C's component table | Major |
| 5 | `WeightedSplitPolicy` cannot satisfy `RoutingPolicy`'s stated purity requirement | Major |
| 6 | `CostTracker`'s ledger not classified as needing distributed storage, unlike its peers | Major |
| 7 | `BudgetGuard`'s `estimated_usage` type vs. the new `CostEstimate` value left unreconciled | Minor |
| 8 | Response-cache TTL claimed configurable via `cache_policy`, which cannot express a TTL | Minor |
| 9 | Cross-reference/citation discipline is consistently accurate | Observation |

**Critical issues found: 0.**

Architecture is internally consistent and ready for Architecture Contract.
