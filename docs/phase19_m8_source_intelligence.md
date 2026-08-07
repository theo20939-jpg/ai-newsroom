# Phase 19 M8 — Source Intelligence

## 1. Scope

A deterministic, heuristic-only classifier estimating a NewsEvent's likely role in its Story's
coverage — never a factual attribution claim. Shadow-only, independent of Story Timeline (M7):
both milestones must be provably isolated from each other and from Copywriting.

## 2. Classification (`services/source_intelligence.py::classify_source_role`)

Pure function, no I/O. Inputs: whether this event is the earliest known event for its Story
(`Story.first_event_id`), `services.story_memory`'s own match_type for this event's story link,
and the event's title (checked against a narrow, fixed analysis/opinion keyword lexicon — mirrors
`services/story_memory.py`'s own `_TOPIC_KEYWORDS` convention).

Labels, all hedged:

- **`POSSIBLE_ORIGINAL`** — this is the earliest known event for its Story.
- **`POSSIBLE_CONFIRMATION`** — matched as `semantic_duplicate`/`supporting_source` (near-identical
  or corroborating coverage of something already seen).
- **`POSSIBLE_AGGREGATION`** — matched as `story_update` (adds new information, more likely a
  synthesis than the origin).
- **`POSSIBLE_ANALYSIS`** — title matches the analysis/opinion keyword lexicon (checked first,
  overrides the above — an analysis piece isn't "the origin" merely for being first-seen).
- **`UNKNOWN`** — insufficient signal (no story link, or an `uncertain_match`).

No label is ever a bare, definitive claim (`ORIGINAL_SOURCE`, `CONFIRMED`) — enforced by
`tests/test_source_intelligence_isolation.py::test_source_intelligence_labels_are_all_hedged`,
which inspects the module's own exported constants directly.

## 3. Isolation

- `source_intelligence_mode: Literal["off", "shadow"] = "off"` — no `"enforce"` value; this
  milestone never proposes to change any output.
- Persisted for review only, via `services/source_intelligence_persistence.py` (same
  capabilities-never-import-database-models indirection as Editorial Planning/Story Context) into
  standalone table `news_event_source_intelligence` (1:1, PK reuses `news_event_id`) — migration
  `8faedf40f596`, chained onto M7's `280fa1e7d6d2`, written but not applied live.
- `capabilities/executor.py::_attach_source_intelligence()` (same seam/pattern as
  `_attach_story_context()`) never touches `structured_output` — Copywriting has no code path to
  this data.
- `tests/test_source_intelligence_isolation.py` mechanically enforces (via `ast.parse`, mirroring
  `tests/test_content_draft_service.py::test_capabilities_never_import_content_draft()`'s
  established technique) that no file under `capabilities/` (other than `executor.py` itself)
  imports `services.source_intelligence`, and that no prompt YAML file references the label
  vocabulary.
- `tests/test_source_intelligence_shadow_integration.py` (mirrors
  `tests/test_story_context_shadow_integration.py`) proves `source_intelligence_mode="shadow"`
  makes zero extra LLM calls and produces byte-identical Copywriting output, both with and
  without an actual story link.

## 4. Deliberately reserved, not yet load-bearing

`classify_source_role()` accepts `source_type`/`reliability_score` for interface completeness but
does not currently use them in the classification — reserved for future refinement once real
shadow-mode data exists to inform whether they should matter (mirrors
`services/story_memory.py`'s own precedent of accepting an unused `category` parameter in
`extract_story_signature()`).

## 5. Validation performed

- Disposable Postgres, migrated through `8faedf40f596` (chained onto M7's migrations),
  upgrade/downgrade/re-upgrade all clean.
- All tests pass for real against the migrated disposable DB; skip cleanly (runtime
  table-existence check) against the real, intentionally-unmigrated dev DB.
- Real DB alembic revision unchanged (`31a8d7c95c87`).
- Ruff/Mypy clean on all touched source files.

## 6. What this milestone does NOT do

- Does not enable `source_intelligence_mode` anywhere (defaults `"off"`).
- Does not generate "first reported by"/"confirmed by"/"other outlets copied"-style prose
  anywhere — this module only ever produces a label, never prose.
- Does not apply any migration to the real database.
