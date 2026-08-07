# Phase 19 M3 — Editorial Plan Human Comparison Packet

Status: template + worked example only. `scripts/phase19_m3_editorial_plan_comparison.py` has
**not** been executed for real against a live provider — this document is the template a real run
would populate, plus one worked example built with the fake gateway (zero real cost), so a
reviewer knows exactly what to expect before any real, paid run is authorized.

## Purpose

Before Editorial Planning may influence production Copywriting output (a decision explicitly out
of scope for this phase — see `core/config.py`'s `editorial_planning_mode`, which has no
`"enforce"`/live value at all), a human reviewer must compare a **baseline** (today's exact
Copywriting output, no plan involved) against a **candidate** (a real, LLM-generated Editorial
Plan, per `prompts/editorial_planning/v1.yaml`) for the same real event, and judge whether the
plan's structured answers would plausibly improve the resulting post.

## Acceptance threshold (explicit, non-vague — required per the design correction)

For each reviewed case, the candidate plan must be **preferred or tied** against the baseline on
each of the following three dimensions — never a vaguer "looks better" standard:

1. **Factual grounding** — every claim in the plan traces to the supplied evidence (Research's
   facts, the article excerpt/full text). A plan that states something not in the evidence fails
   this dimension outright, regardless of the other two.
2. **Avoidance of repetition** — for an `update`/`confirmation` classification, the plan's
   `what_changed`/`must_not_repeat` fields correctly identify what the audience has already been
   told, so a future Copywriting pass would not restate it.
3. **Clarity of "why it matters"** — the plan's `why_it_matters` field states a genuine,
   specific editorial angle, not a generic filler sentence.

A case fails the packet's overall acceptance bar if it fails any single dimension. No
production-use decision may be made from this packet alone — that remains a separate, later,
explicitly-authorized decision even if every reviewed case passes.

## Review row template

| Field | Value |
|---|---|
| `event_id` | |
| Real headline | |
| Baseline title/body (verbatim) | |
| Candidate plan `central_fact` | |
| Candidate plan `story_classification` | |
| Candidate plan `why_it_matters` | |
| Candidate plan `essential_facts` | |
| Candidate plan `what_remains_unknown` | |
| Safety report `passed` | |
| Safety report `failed_checks` (if any) | |
| Reviewer: grounding (preferred/tied/worse) | *(blank — human fills in)* |
| Reviewer: repetition-avoidance (preferred/tied/worse) | *(blank — human fills in)* |
| Reviewer: why-it-matters clarity (preferred/tied/worse) | *(blank — human fills in)* |
| Reviewer notes | *(blank — human fills in)* |

## Worked example (fake gateway, zero real cost — illustrates the packet shape only)

Built via `capabilities/editorial_planning_capability.py`'s own unit tests
(`tests/test_editorial_planning_capability.py`), not a real provider call:

**Baseline** (today's Copywriting, no plan):
```json
{
  "title": "Example draft title",
  "body": "Example draft body text.",
  "what_happened": "Example event happened.",
  "why_it_matters": "Example editorial interpretation of the impact.",
  "what_remains_unknown": null,
  "quote": null
}
```

**Candidate plan** (v1 schema, fake-gateway output):
```json
{
  "central_fact": "The company raised five million dollars.",
  "what_changed": null,
  "what_is_new": "A new funding round.",
  "why_it_matters": "It funds their next product.",
  "essential_facts": ["Raised $5M"],
  "secondary_facts_omittable": [],
  "necessary_background": null,
  "already_published_summary": null,
  "must_not_repeat": null,
  "story_classification": "new_story",
  "headline_emphasis": "Funding round",
  "opening_emphasis": "The company raised funds.",
  "what_remains_unknown": null,
  "verified_quote_text": null,
  "media_role_needed": "none",
  "editorial_risks": []
}
```

Reviewer row for this example is intentionally left blank in the template above — this worked
example exists only to show the packet's shape, not to pre-judge a real comparison.

## Real-run procedure (for future, separately-authorized execution)

1. Confirm `editorial_planning_mode == "comparison"` is explicitly set (the script refuses to run
   otherwise — `tests/test_phase19_m3_editorial_plan_comparison.py` proves this).
2. `python -m scripts.phase19_m3_editorial_plan_comparison <event_id>` for each reviewed event —
   makes real LLM calls (Research/Intelligence/Copywriting/Quality for the baseline, plus one real
   Editorial Planning call for the candidate plan). Writes `phase19_m3_comparison_<event_id>.json`.
3. A human fills in this packet's review rows from the written JSON files.
4. Only after the acceptance threshold above is met across a meaningful sample does any future
   phase's decision about production use become a live question — not decided here.
