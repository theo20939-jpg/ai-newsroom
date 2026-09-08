# Editorial Gate Cost Model

DIRECTOR-CONTROL-PLANE-1A §28 - a realistic, staged cost estimate for the two-stage Editorial Gate
(`services/director_editorial_gate.py` Stage 1, `services/director_editorial_gate_llm.py` Stage 2).
The hard ceiling below is enforced by real code
(`services/director_editorial_gate_budget.py::check_gate_llm_budget()`), not just this document -
every other figure is a reasoned estimate, explicitly labeled as such, never presented as measured
production data (this environment has no live gate traffic yet - `telegram_editorial_gate_enabled`
stays `false`).

## Volume assumptions (reasoned estimates, not measured)

| Field | Value | Basis |
|---|---|---|
| RAW_ITEMS_PER_DAY | ~800-1500 | `news_collection_interval_seconds=1800` (48 collection cycles/day) across the currently configured `NewsSource` set; not a measured production figure - no live collection has run continuously in this environment. |
| CLUSTERED_STORIES_PER_DAY | ~150-300 | Typical dedup/clustering ratio (multiple articles about the same event collapse into one Story) seen in comparable single-topic-cluster news pipelines; not measured here. |
| DETERMINISTIC_PREFILTER_SURVIVORS | ~60-150 | Stage 1 (`evaluate_editorial_gate()`) is a cheap, deterministic filter - the stories that reach SEND_TO_EDITOR/PRIORITY/BREAKING or land in HOLD (never a paid call) at this stage. |
| EXPECTED_DIRECTOR_LLM_REVIEWS | ~15-40/day | Stage 2 (`is_escalation_worthy()`) only escalates stories that are ambiguous/high-value/campaign-relevant/breaking/feed-gap - a real minority of prefilter survivors, per the same design principle already proven by `services/director_editorial_gate.py::_AMBIGUOUS_NOVELTY_BAND` (a narrow 0.35-0.65 band, not "most stories"). |

## Hard, code-enforced ceiling (the real safety bound)

| Field | Value | Enforcement |
|---|---|---|
| MAX_DIRECTOR_LLM_REVIEWS_PER_DAY | `settings.director_editorial_gate_max_llm_reviews_per_day` (default **100**, `core/config.py`) | `services/director_editorial_gate_budget.py::check_gate_llm_budget()` counts real `DirectorEditorialDecision` rows created today with `director_version="v1-llm"` and returns `DAILY_LIMIT_REACHED` once the count is met - independent of whatever the volume estimates above turn out to be in production. |

## Per-call cost (real PricingCatalog figures)

Stage 2 (`llm_escalate_gate()`) issues one `TaskPriority.S` structured-output call per escalation -
a short system prompt + a compact task-text summary (story facts, novelty/duplicate/breaking
signals) in, a small `{decision, reason_codes, short_reason}` JSON object out. Estimated at a
generous **1,000 input / 300 output tokens per call** (real prompt: `prompts/director_editorial_
gate/v1.yaml`; real call shape: `services/director_editorial_gate_llm.py::llm_escalate_gate()`).

Priced against **GPT-5.6 Luna** (`integrations/llm_gateway/models/catalog.py` -
`$1.00`/million input tokens, `$6.00`/million output tokens, the cost-sensitive tier this task's
`TaskPriority.S` classification is expected to route to):

```
cost_per_call  = (1000 / 1_000_000) * 1.00 + (300 / 1_000_000) * 6.00
               = 0.0010 + 0.0018
               = $0.0028 per call
```

## ESTIMATED_COST_BOUND

```
ESTIMATED_COST_BOUND (hard, worst case) = MAX_DIRECTOR_LLM_REVIEWS_PER_DAY * cost_per_call
                                         = 100 * $0.0028
                                         = $0.28 / day
```

This is the real, code-enforced worst case regardless of actual production volume - even if
EXPECTED_DIRECTOR_LLM_REVIEWS above turns out to be badly wrong, `check_gate_llm_budget()` still
caps the day at 100 calls / ~$0.28. For comparison, this is well under the existing
`visual_max_cost_per_day=$20.00` and `social_advisory_max_cost_per_day=$5.00` precedents already
configured in `core/config.py` for other Director-facing LLM surfaces.

## What would replace the reasoned estimates with real data

Once `telegram_editorial_gate_enabled=true` runs in production for a real week, replace the
RAW_ITEMS_PER_DAY / CLUSTERED_STORIES_PER_DAY / DETERMINISTIC_PREFILTER_SURVIVORS /
EXPECTED_DIRECTOR_LLM_REVIEWS estimates above with the real shadow-metrics counters already
persisted by `worker/content_cycle.py`'s `ContentCycleResult` (`gate_total_stories`,
`gate_cheap_prefilter_passed`, `gate_director_reviewed`, ...) - this document's own estimates exist
only to size `director_editorial_gate_max_llm_reviews_per_day` sanely before any real traffic
exists, never as a claim about actual production behavior.
