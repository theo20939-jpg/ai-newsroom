# R2 Shadow — First Canary Implementation Plan

**Status: PLAN ONLY — no code written. Waiting for confirmation per the owner's own explicit
"wait for confirmation before writing code."** Reflects all four approval-round clarifications
(shadow-local `evaluation_status` vocabulary, observation-only visual integration, the exact
first-canary output shape, this plan itself).

## 1. Design decision: new script, not a scanner extension

The (not-yet-approved) execution plan floated two options — a new script, or an additive flag on
`scripts/_recap_r2_10_readiness_candidate_scanner.py`. **Recommendation: a new script,
`scripts/_recap_r2_shadow_batch.py`.**

Reasoning: the scanner's own docstring and R2.10 Night 2 commit message explicitly frame it as
lightweight triage — *"this scanner's own job is triage/ranking across MANY Stories, not full
detail for one."* The shadow canary's job is the opposite emphasis: full per-Story evidence
(anchor, bundle, facts, timeline, media, visual metadata) for a *smaller* bounded batch. Bolting
that onto the scanner would blur an already-documented division of labor and risk exactly the
scope-creep risk flagged in the execution plan's own risk table. Three small, composable scripts
(single-Story deep diagnostic + optional LLM / multi-Story triage / multi-Story full-evidence
batch) match this codebase's own established one-script-per-purpose convention better than one
increasingly overloaded scanner.

## 2. Files to touch (new)

### `scripts/_recap_r2_shadow_batch.py` (new)

- CLI: `--limit` (default small, e.g. 5; hard ceiling reusing the scanner's own `MAX_LIMIT=200`
  constant/pattern), `--output-dir` (default mirrors existing scripts' `DEFAULT_OUTPUT_DIR`
  convention).
- **No `--with-llm` flag exists in this script at all** — not a flag defaulting to off, an
  argument that is physically absent from the parser. Stronger than a deferred-import guard: there
  is no code path in this file that can construct a Gateway request, period.
- Read-only transaction guard: `_verify_read_only()` / `ReadOnlyGuardError`, duplicated verbatim
  from `scripts/_recap_r2_event_shadow.py` — this codebase's own established per-script-private-
  helper convention (matches `_normalize_domain()`'s own cross-reference precedent), not a shared
  import, so each script's safety guard stays self-contained and independently auditable.
- Bounded Story selection: the scanner's own `select(Story).order_by(Story.updated_at.desc())
  .limit(args.limit)` query, duplicated (three lines, same reasoning as above).
- Core per-Story logic (a pure-ish, independently testable async function — mirrors
  `scan_story_readiness()`'s own split from `main()`):
  ```python
  async def build_shadow_report(session: AsyncSession, story: Story, *, now: datetime) -> ShadowStoryReport:
      row = await scan_story_readiness(session, story, now=now)   # reused, unchanged
      if row.readiness_state == "REJECTED":
          return ShadowStoryReport(story=row, candidate=None, evaluation_status="REJECTED", quality_notes=[])
      result = await build_event_recap_candidate(session, story, force_shadow=True, now=now)
      # result.candidate is not None here - row already proved integrity/origin-projection succeeded
      quality_notes = _compute_quality_notes(result.candidate)
      status = _compute_evaluation_status(row, quality_notes)
      return ShadowStoryReport(story=row, candidate=result.candidate, evaluation_status=status, quality_notes=quality_notes)
  ```
  Calling both `scan_story_readiness()` (for the clean `origin_projection_status`/
  `manual_review_required`/Story-section fields it already derives correctly) and
  `build_event_recap_candidate()` (for the full Candidate-section fields it alone provides) means
  one Story is evaluated twice when a candidate exists - a deliberate, accepted trade-off: it adds
  a handful of extra read-only queries per Story (bounded by the batch's own small `--limit`,
  matching the "do not prematurely optimize" instruction from R2.10 Night 2's own query audit) in
  exchange for zero duplicated evaluation logic and zero new logic paths to get wrong.
- `_compute_evaluation_status(row, quality_notes) -> str`: pure function.
  - `row.readiness_state == "REJECTED"` → `"REJECTED"`
  - `row.recommended_for_manual_review or quality_notes` → `"NEEDS_REVIEW"`
  - else → `"OBSERVED"`
- `_compute_quality_notes(candidate) -> list[str]`: pure function, deterministic strings only
  (mirrors `EventRecapCandidate.quality_flags`'s own shape) — e.g. `"media_candidates empty"`,
  `"media spans N distinct events - possible anchor mismatch (R2.10 Night 2 Phase 19)"`,
  `"announcement_count reflects raw report-level clusters, not confirmed distinct developments -
  see R2.11"` (emitted whenever `announcement_count > 1`, unconditionally — an honest, static
  caveat, never a claim shadow can distinguish the two).
- Aggregate summary: `_build_shadow_summary(reports: list[ShadowStoryReport]) -> dict` — pure
  function computing `scanned_count`, `candidate_count`, `rejection_reasons_distribution`,
  `readiness_states_distribution`.
- `main()`: engine/connection/transaction setup (mirrors both existing scripts exactly), loops
  Stories, calls `build_shadow_report()` per Story, writes:
  - `shadow_<story_id>.json` per Story (Story + Candidate + Evaluation + visual-metadata sections,
    per the contract),
  - `shadow_<story_id>.txt` per Story (`render_event_recap_bundle_text(candidate)` verbatim, only
    when a candidate was built),
  - one `shadow_summary.json` for the whole run.

### `tests/test_recap_r2_shadow_batch.py` (new)

See §4.

## 3. Files reused, unchanged

| File | What's reused |
|---|---|
| `services/event_recap.py` | `build_event_recap_candidate()`, `render_event_recap_bundle_text()` |
| `services/recap_event.py` (frozen) | `load_story_events()` — read-only, indirectly via the above |
| `services/recap_origin_projection.py` | `resolve_recap_origin_projection()` — indirectly, via `scan_story_readiness()` |
| `scripts/_recap_r2_10_readiness_candidate_scanner.py` | `scan_story_readiness()`, `CandidateScanRow` — imported directly (the one legitimate cross-script import here: identical evaluation logic, not duplicated, mirroring this codebase's own "duplicate trivial helpers, reuse substantial logic" split) |
| `database/models/story.py`, `database/models/news_event.py` | `Story`, `NewsEvent` |
| `core/config.py` | `settings.database_url` |

No file in this list is modified. No frozen file (`services/recap_event.py`,
`services/story_memory.py`, `services/triage_orchestrator.py`, `prompts/event_recap/v1.yaml`,
`prompts/event_recap/v2.yaml`) is touched.

## 4. Safety checks

All reused from already-proven guards — nothing new invented:

| Check | Mechanism |
|---|---|
| Read-only DB | `SET TRANSACTION READ ONLY` + `SHOW transaction_read_only` verification, `statement_timeout`, rollback in `finally` — duplicated from `scripts/_recap_r2_event_shadow.py` |
| No DB writes | Structural: the batch only ever calls `session.execute(select(...))`/`session.get()`; never `.add()`/`.flush()`/`.commit()` — verified by a test asserting `session.new`/`session.dirty` unchanged (mirrors R2.10 Night 2's own synthesis-invariant test pattern) |
| No LLM calls | Structural: no `--with-llm` flag exists in the parser at all; no import of `integrations.llm_gateway.*` anywhere in the file (AST-verified, extending the existing repo-wide guard) |
| No Telegram/worker | No import of `bot.*`/`worker.*` anywhere (same AST guard, extended to cover this new file) |
| No workers/scheduler | Manual CLI script, never registered with any scheduler/Capability registry — same as both existing R2 scripts |
| Bounded scan | `--limit` with a hard ceiling, same pattern as the scanner |

## 5. Tests to add

1. `test_compute_evaluation_status_rejected` / `_needs_review` / `_observed` — pure-function unit
   tests, one per branch.
2. `test_compute_quality_notes_flags_empty_media` / `_flags_multi_event_media` /
   `_always_flags_announcement_count_caveat` — pure-function unit tests.
3. `test_build_shadow_summary_counts_correctly` — pure-function test against a small synthetic
   list of `ShadowStoryReport` objects (no DB).
4. `test_shadow_batch_end_to_end_writes_expected_files` (DB-backed, `db_session` fixture, 2-3
   Story fixtures reusing existing helpers from `tests/test_recap_r2_9_origin_membership_projection.py`
   /`tests/test_event_recap.py`) — asserts per-Story JSON/TXT written with the correct fields,
   `shadow_summary.json` counts match.
5. `test_shadow_batch_makes_zero_db_writes` — `session.new`/`session.dirty` unchanged
   before/after the full batch run (mirrors the R2.10 Night 2 invariant-test pattern).
6. `test_shadow_batch_script_has_no_with_llm_flag` — parses the argparse setup (or greps
   `--with-llm` absent from the source) — a structural, not just behavioral, guarantee.
7. `test_shadow_batch_has_no_bot_worker_or_gateway_imports` — extends the existing repo-wide AST
   guard (`test_no_bot_or_worker_or_telegram_imports_anywhere_in_r2`) to cover
   `scripts/_recap_r2_shadow_batch.py`.
8. `test_shadow_batch_cli_help_works` — `--help` smoke test (proves no import-time side effects).
9. Ruff + mypy clean on the new script and test file.

## 6. Explicitly out of scope for this canary (unchanged from the execution plan)

`--with-llm`/synthesis stage, fact-verification-driven notes, Telegram-preview generation, any
`RecapVisual`/`brand_renderer.py` change, any retention policy for output files.

## 7. Open questions for confirmation

1. Output directory default — `/tmp/recap_shadow/` (matching `scripts/_recap_r2_event_shadow.py`'s
   own `DEFAULT_OUTPUT_DIR = Path("/tmp")`) or a project-relative path? Defaulting to `/tmp` for
   consistency unless told otherwise.
2. `--limit` default — proposing `5` (smaller than the scanner's own `20`, since this canary does
   materially more per-Story work).
3. Confirm the recommendation in §1 (new script) rather than extending the existing scanner.

Waiting for confirmation before writing any code.
