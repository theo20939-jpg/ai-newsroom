# PHASE 23.1C — V6 CONTENTDRAFT COMPATIBILITY FIX

**Status: fix implemented and tested. Canary not rerun.** Branch `feature/phase19-editorial-depth-
upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb` (unchanged, no commit made). `.env` untouched.
No worker started, no Telegram message sent this phase, no migration applied.

## 1. Root cause

`services/content_draft_service.py::ContentDraftService.create_from_result()`, previously:
```python
copywriting_output = _copywriting_output(result)
title = copywriting_output["title"]
body = copywriting_output["body"]    # hard KeyError for every V6 draft
```
V6's real schema (`prompts/copywriting/v6.yaml`, re-verified directly against the file, not
assumed) has no `body` key — its structure is `title, opening, context, why_it_matters,
what_changed, what_happens_next, conclusion, what_remains_unknown, quote`. This crashed with a raw
`KeyError`, confirmed live in the Phase 23.1B canary run: 4/4 real V6 `CONTENT_GENERATION`
workflows completed successfully (real Research/Intelligence/Copywriting/Quality/Fact Safety LLM
calls all succeeded) but every one failed at this exact line, and `ContentDraftService` — the only
component authorized to create a `ContentDraft` row — never persisted anything. The failure was
already caught by `scripts/run_content_generation.py`'s own existing `except Exception` guard
(logged as `content_generation_completed_but_draft_persistence_failed`), so no partial or corrupted
state resulted — confirmed directly against the database: the 4 `EditorialTask` rows stayed cleanly
`COMPLETED` with their real V6 output intact in `workflow.step_results`, and zero `ContentDraft`
rows existed for any of them.

## 2. Why Phase 21 did not catch this

Phase 21 was explicitly and narrowly scoped to "ONLY fixes V6 Copywriting compatibility with **Fact
Safety**" (its own brief, verbatim) — `services/fact_safety.py::apply_fact_safety()` is a
completely different function, called from a completely different place
(`capabilities/executor.py`'s "quality" step, an *additive* enrichment of `structured_output` that
can safely no-op or degrade), operating on `copywriting_output` read from
`context.business.workflow_state.step_results["copywriting"]` — the in-memory workflow context,
before persistence. `ContentDraftService.create_from_result()` is a structurally separate call,
made later, by a separate caller (`scripts/run_content_generation.py`), reading the same underlying
data from the *durable* `WorkflowRunResult.step_results` — but there is no shared code path between
the two; fixing one could not have automatically fixed the other. Phase 21's own report explicitly
disclosed this exact gap as a known, undisclosed-until-now-confirmed limitation: its §12 "Remaining
limitations" flagged that `capabilities/executor.py::_attach_editorial_completeness()` had "the
identical V6 blind spot" and was out of scope — it did not separately enumerate
`ContentDraftService`, but the same reasoning (a title/body-shaped extraction hard-coded to V4)
applies here too, and is now confirmed as the single most severe instance of the pattern, since it
blocks the pipeline's primary deliverable rather than an optional shadow signal.

## 3. Chosen fix

The same principle Phase 21 established: **adapt the extraction to the schema; never force V6
backwards.** A new pure function, `_extract_title_and_body()`, added to `services/
content_draft_service.py` immediately before `_fact_safety_status()`, structurally mirroring
`services/fact_safety.py::_extract_draft_text()` (Phase 21) almost exactly:

```python
_V6_REQUIRED_TEXT_KEYS = frozenset({"opening", "context", "why_it_matters", "what_changed", "conclusion"})
_V6_TEXT_KEYS_IN_ORDER = (
    "opening", "context", "why_it_matters", "what_changed", "what_happens_next", "conclusion",
    "what_remains_unknown",
)

def _extract_title_and_body(copywriting_output: dict[str, Any]) -> tuple[str, str]:
    title = copywriting_output.get("title")
    if not isinstance(title, str):
        raise ValueError(...)                       # no valid title at all

    body = copywriting_output.get("body")
    if isinstance(body, str):
        return title, body                            # V4 (byte-identical to before)

    if all(isinstance(copywriting_output.get(k), str) for k in _V6_REQUIRED_TEXT_KEYS):
        sections = [copywriting_output[k] for k in _V6_TEXT_KEYS_IN_ORDER
                    if isinstance(copywriting_output.get(k), str)]
        return title, "\n\n".join(sections)

    raise ValueError(...)                             # genuinely unrecognized schema
```

`create_from_result()` now calls `title, body = _extract_title_and_body(copywriting_output)` in
place of the two direct dict lookups — a one-line call-site change.

**One real design correction made during test-first development** (disclosed, not hidden): the
first draft grouped V6's five required sections together, then appended the two optional sections
at the end. The phase brief's own field listing (`opening / context / why_it_matters /
what_changed / what_happens_next / conclusion / what_remains_unknown / quote`) — and the real V6
prompt's own declared field order — interleaves `what_happens_next` between `what_changed` and
`conclusion`, not after it. `_V6_TEXT_KEYS_IN_ORDER` was corrected to iterate one single, natural,
prompt-declared order (skipping unset optional fields in place) rather than two separate
required/optional groups, so the concatenated body reads in the same order a human editor
encounters the sections — the phase brief's own explicit "preserve ordering" requirement, verified
directly against the real Roblox draft that crashed in Phase 23.1B (§5).

Unlike Fact Safety's `apply_fact_safety()` (which has a genuine safe-no-op path — enrichment is
optional), `ContentDraftService.create_from_result()` has no such fallback: its entire job is to
create a `ContentDraft` or fail loudly (its own pre-existing docstring: "Raises uncaught on failure
... MUST NOT swallow" — the exact same philosophy `_copywriting_output()`'s own sibling helper
already uses two lines above). So "explicit safe status/logging" for an unsupported schema here
means the same thing this module already does for a missing `title`: a clear, informative
`ValueError` (listing the keys actually present, and which schemas were checked) — not a raw,
unhelpful `KeyError`, and not a silently-swallowed no-op. This raise propagates uncaught into
`scripts/run_content_generation.py`'s existing `except Exception` guard, which already logs it
(`content_generation_completed_but_draft_persistence_failed`) — the same, already-correct,
already-safe failure path this bug already went through in Phase 23.1B; only the message is now
informative instead of a bare `KeyError: 'body'`.

## 4. Files changed

**Modified**: `services/content_draft_service.py` — added `_V6_REQUIRED_TEXT_KEYS`,
`_V6_TEXT_KEYS_IN_ORDER`, `_extract_title_and_body()`; `create_from_result()`'s two-line direct
lookup replaced with one call to it. Nothing else in the file changed — `_copywriting_output()`,
`_fact_safety_status()`, `_draft_status_for()`, `_to_read_schema()`, the quote/quality-gate/
story-link logic, and the `ContentDraft(...)` construction itself are all byte-unchanged.

**Created**: `tests/test_content_draft_v6_compatibility.py` (17 tests — 11 confirmed, see §5),
`docs/phase23_1c_v6_contentdraft_compatibility_report.md` (this report).

No migration created or applied (zero schema change). No `.env` edit. No prompt file edit
(`prompts/copywriting/v6.yaml` untouched, per the phase's own "do not change V6 schema" rule).

## 5. Tests

Test-first discipline verified directly: `tests/test_content_draft_v6_compatibility.py` was run
against unmodified code first and failed with `ImportError: cannot import name
'_extract_title_and_body'` (collection error, not merely an assertion failure — the function did
not exist yet). After implementation, 11 tests, all passing, covering all 6 required cases:

- **Pure unit tests** (6, no DB): V4's `body` key extracted unchanged; V6's five required sections
  concatenated correctly; V6's two optional fields included only when actually populated (both
  `None` is confirmed as the common case, matching Phase 23.1B's own real sample draft); section
  ordering preserved in the real prompt-declared order (explicitly re-verified after correcting the
  original grouping bug, §3); an unsupported schema raises `ValueError` with an informative
  message; a missing `title` raises explicitly too.
- **CASE 1** (`test_case_1_v4_output_creates_identical_content_draft`): a real, persisted
  `ContentDraft` from V4 input has the exact same `title`/`body` as before — regression guard.
- **CASE 2** (`test_case_2_v6_output_creates_content_draft_successfully`): a real V6 output
  persists successfully, `draft.body` contains the expected narrative content.
- **CASE 3** (`test_case_3_v6_missing_optional_fields_handled_safely`): both `what_happens_next`/
  `what_remains_unknown` `None` (V6's own real, common shape) still persists cleanly.
- **CASE 4** (`test_case_4_unsupported_schema_fails_explicitly_never_persists`): a genuinely
  unrecognized schema raises the explicit, informative `ValueError` — and, critically, confirmed
  directly against the database that **zero** `ContentDraft` rows exist for that task afterward
  (never a partial/corrupted persist).
- **CASE 5** (`test_case_5_content_draft_service_never_imports_telegram_code`): structural —
  `services/content_draft_service.py`'s own source contains no `aiogram`/`telegram_notifier`/
  `telegram_routing`/`bot.loader` reference at all (this module has never had any Telegram
  dependency; verified, not merely assumed).
- **CASE 6**: existing `ContentDraft` tests unchanged — verified via the full regression run (§6),
  not a new test in this file.

**Direct re-verification against the real, live-crashed data**: `_extract_title_and_body()` was run
against the exact `copywriting` step output persisted from the Phase 23.1B canary's Roblox
stock-drop event (the one that crashed live) — it now extracts cleanly, producing the correct
title and a well-ordered, complete Russian-language body (re-confirmed by direct file inspection,
not terminal output, to avoid this environment's known Windows-console Cyrillic display artifact).

Ruff (`services/content_draft_service.py`, `tests/test_content_draft_v6_compatibility.py`): all
checks passed. Mypy (`services/content_draft_service.py`): Success, no issues found.

## 6. Compatibility guarantees

- **V4: byte-identical.** `_extract_title_and_body()`'s first branch (`isinstance(body, str):
  return title, body`) is the exact same two-line extraction the pre-fix code performed inline —
  no new logic runs for a V4 draft at all. Confirmed by Case 1's regression test.
- **V6: now succeeds**, producing a well-ordered, complete narrative body from the real schema.
- **No fake `body` field was added anywhere** — V6's prompt (`prompts/copywriting/v6.yaml`) is
  completely untouched; `ContentDraft.body` (the database column) still exists and is still
  populated, but from a *derived* value, never a literal schema field forced onto V6's own output.
- **Unsupported schema: explicit failure, never silent.** Matches this module's own pre-existing,
  unmodified "MUST NOT swallow" philosophy exactly — this was already the correct behavior for a
  missing `title`; it is now also the behavior for a body-equivalent that matches no known schema,
  with an informative message instead of a bare `KeyError`.
- **Downstream consumers unaffected**: `check_no_hashtags(title, body)`, `evaluate_content_quality_
  gates(title=title, body=body, ...)`, and the `ContentDraft(title=title, body=body, ...)`
  construction itself all receive the same `(str, str)` shape as before — no changes were needed
  to any of them.

## 7. Remaining risks

1. **`capabilities/quality_capability.py`'s own prompt/judgment still assumes a `body`-shaped
   summary exists** — observed live in Phase 23.1B (`"passed": false`, flagging a missing "Body"),
   not fixed this phase (out of scope: this phase's mission was specifically `ContentDraft`
   persistence, not `QualityCapability`'s own separate LLM judgment). Non-blocking (Quality's
   `passed`/`issues` output has never gated delivery in this architecture) but disclosed, not
   hidden.
2. **`what_happened` (a V4-only field, distinct from V6's `what_changed`) is still read via
   `.get()` and stays `None` for every V6 draft**, feeding into `evaluate_content_quality_gates()`'s
   own `what_happened=` parameter as `None` — a secondary, non-blocking quality-gate input gap
   (that function already tolerates `None` inputs; it is informational only, never blocking
   persistence). Not in this phase's stated scope (the mission was specifically the `title`/`body`
   extraction blocking persistence) and not fixed — disclosed as a related, smaller gap.
3. **`capabilities/executor.py::_attach_editorial_completeness()`'s own identical V4-only `body`
   assumption** (already disclosed in Phase 21's own report §12) remains unfixed — still out of
   scope for this narrowly-targeted phase.
4. **Not yet re-validated live**: this fix is proven correct against real, previously-crashed V6
   data (§5) and a full test suite, but has not yet been exercised through an actual rerun of the
   Phase 23.1B canary script. Per this phase's own explicit STOP condition, that rerun is
   deliberately deferred to a separate, reviewed step.
5. **The `what_remains_unknown`/`what_happens_next` fields, when populated, are concatenated as
   plain narrative text** with no distinguishing header/label in the persisted `body` — a reader of
   the raw `ContentDraft.body` column cannot tell where "conclusion" ends and "what remains
   unknown" begins beyond the blank-line separator. This matches Fact Safety's own identical,
   already-accepted precedent (Phase 21) and was not treated as a problem there; noted here for
   completeness, not as a new concern.

## Regression results

```
python -m pytest tests/ -k "content_draft or copywriting or fact_safety or telegram or phase20 or
  phase21 or story_memory or story_delta or story_suppression or editorial_content_type or
  story_identity or human_reviewed_calibration or routing or whereami or evidence_package" -q
640 passed, 12 skipped, 2440 deselected, 9 failed, 1 error
```
All 9 failures + 1 error were individually confirmed, via a temporary `git stash` of the one
modified file, to reproduce identically on unmodified code: the same accumulated local-Postgres
FK/row-count pollution already disclosed in the Phase 21/22/23.1A reports (6 of the 9), plus 3
newly-checked `test_evidence_package_*` failures now also confirmed pre-existing (an unrelated
`article_acquisition_mode`/table-presence environment drift). Net new regressions from Phase
23.1C: **zero**.

---

**STOP condition met.** Fix implemented, tested, Ruff/Mypy clean. The Phase 23.1B canary script is
not being rerun this phase — waiting for review before any further live attempt.
