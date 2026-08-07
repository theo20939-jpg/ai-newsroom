# Phase 19 M14 — Model Cost/Quality Analysis

## 1. Scope

`scripts/phase19_m14_cost_quality_analysis.py` — read-only against real `ai_executions` data and
the real model catalog (`integrations/llm_gateway/models/catalog.py::build_model_registry()` —
never an invented model name or price). This script **was run** for real (read-only, zero writes,
zero paid calls — the same "safe to actually execute" class as the M6 calibration replay scripts),
producing the real results below.

Four clearly separated sections, per the overnight authorization's own explicit requirement:

## 2. Section A — Historical real execution cost data

13 (capability, model) groups from real, already-recorded `ai_executions` rows. **Total recorded
spend across every group: $7.186309.**

| Capability | Model | Calls | Total cost (USD) | Avg cost/call (USD) |
|---|---|---|---|---|
| INTELLIGENCE | gpt-5.6-luna | 2,134 | 3.836057 | 0.001798 |
| RESEARCH | gpt-5.6-luna | 1,072 | 1.410182 | 0.001315 |
| SCORING | gpt-5.6-luna | 1,065 | 0.812233 | 0.000763 |
| QUALITY | gpt-5.6-luna | 270 | 0.411040 | 0.001522 |
| COPYWRITING | gpt-5.6-luna | 271 | 0.361314 | 0.001333 |
| INTELLIGENCE | gpt-5.6-sol | 17 | 0.163490 | 0.009617 |
| RESEARCH | gpt-5.6-sol | 11 | 0.100755 | 0.009160 |
| SCORING | gpt-5.6-sol | 8 | 0.032945 | 0.004118 |
| INTELLIGENCE | gpt-5.6-terra | 7 | 0.028542 | 0.004077 |
| QUALITY | gpt-5.6-sol | 1 | 0.008140 | 0.008140 |
| COPYWRITING | gpt-5.6-sol | 1 | 0.006970 | 0.006970 |
| RESEARCH | gpt-5.6-terra | 4 | 0.011851 | 0.002963 |
| SCORING | gpt-5.6-terra | 2 | 0.002790 | 0.001395 |

**Observations** (descriptive only — see §5 for what these do and do not license):

- `gpt-5.6-luna` accounts for the overwhelming majority of both call volume and total spend
  across every capability — consistent with `RoutingCriteria.objective` defaulting to
  `LOWEST_COST` and no capability currently overriding it (confirmed by code inspection during
  M8's own research, `integrations/llm_gateway/routing/criteria.py`'s own comment).
- `gpt-5.6-sol`/`gpt-5.6-terra` calls are rare and have a noticeably higher average cost per call
  — consistent with a higher-capability/higher-price tier being selected only when the router's
  own health/availability/fallback logic routed away from the default cheapest candidate, not
  something this script attempts to further explain (that would require correlating with
  `usage_source`/provider-health data, out of this milestone's scope).

## 3. Section B — Catalog-price simulation

The same recorded token counts re-priced at the **current** catalog price. Drift (simulated −
recorded) is effectively zero across every group (at most a few millionths of a dollar, a
Decimal-rounding artifact, not a real price change) — the catalog's prices have not changed since
these executions were recorded. This is a legitimate, expected "no drift" result, not a
computation error.

## 4. Section C — Fake-gateway harness validation

**SIMULATED / FAKE-GATEWAY RESULT.** This script does not itself run anything against
`FakeLLMGateway` — every registered capability's own request/response contract (including token
usage accounting) is already exercised against `tests/fakes/fake_gateway.py::FakeLLMGateway` in
that capability's own test module (e.g. `tests/test_editorial_planning_capability.py`, `tests/
test_media_vision_review_capability.py`). Recorded here as a pointer, not duplicated machinery.

## 5. Section D — Real same-case model quality benchmark

**REAL SAME-CASE MODEL QUALITY BENCHMARK — NOT RUN / REQUIRES PAID AUTHORIZATION.** A genuine
model-quality comparison (identical prompt/context, multiple real models, real provider calls,
human- or automated-judged output quality) requires real, paid provider calls. Not made as part of
this implementation. **No concrete "switch capability X to model Y" recommendation is made in this
report** — Section A's cost data alone shows *what has been spent*, never *what should be spent*;
any such recommendation is a hypothesis requiring this benchmark's own separate, explicit
authorization before being treated as validated.

## 6. `capability_routing_objective_overrides` (new setting)

```python
capability_routing_objective_overrides: dict[str, str] = {}
```

Empty by default — populating it is a live routing-behavior change, not made as part of this
implementation. The gateway already knows how to honor a per-call `request.metadata["objective"]`
override (`integrations/llm_gateway/gateway.py::_build_routing_criteria()`, confirmed during M8's
own research) — no change to `RoutingEngine`/`RoutingCriteria`/the gateway itself was needed. The
only wiring required was one small addition to `capabilities/gateway_call.py::
_stamp_observability_metadata()` — looks up `settings.capability_routing_objective_overrides.
get(runtime.capability_name)` and injects it into the outgoing request's metadata only if present.
Verified with `tests/test_gateway_call.py` (3 new tests: no override by default, override
injected when configured for the matching capability, override never leaks to a
non-matching capability).

## 7. Validation performed

- `scripts/phase19_m14_cost_quality_analysis.py` executed for real (read-only against real
  `ai_executions` data, zero writes, zero paid calls) — results above are genuine.
- `tests/test_cost_quality_analysis.py` (5 tests): pure catalog-simulation logic, including an
  unknown-model-id case that must never raise.
- `tests/test_gateway_call.py` (+3 tests): the objective-override wiring.
- Ruff/Mypy clean.

## 8. What this milestone does NOT do

- Does not populate `capability_routing_objective_overrides` (stays empty).
- Does not change `RoutingCriteria`'s default objective (`LOWEST_COST`) for any capability.
- Does not run a real same-case model-quality benchmark or make a paid call of any kind.
- Does not recommend switching any capability to a different model — only reports historical
  spend.
