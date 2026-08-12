# PHASE 21 — V6 FACT SAFETY COMPATIBILITY FIX

**Status: reporting only. No production activation.** This phase touched only Fact Safety's own
draft-text extraction. Story Memory, suppression, routing, and Telegram delivery are all
unchanged and remain exactly where Phase 20.8 left them.

## 1. Current state

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged — no commit made this milestone; every Phase 21 change is an uncommitted working-tree
edit, consistent with every prior phase this session). Real DB revision `8faedf40f596`, Alembic
head `3f37cf34109d` (unchanged — no migration was needed or created this milestone; this fix
touches zero schema). `.env` unchanged (`git status --short .env` empty). Docker: `postgres`,
`redis`, `backend`, `automation_worker`, `telegram_bot` up; `content_worker`/
`news_analysis_worker` stopped (unchanged from every prior checkpoint). Settings verified live:
`fact_safety_mode=shadow` (pre-existing, not touched this phase — enforce was never active before
and is not active now), `story_memory_mode=off` (unchanged), `copywriting_prompt_version=4` (V6
remains opt-in only, selected per-call by the manual A/B/C harness — never the global default).
No worker started, no Telegram sent, no paid LLM/vision call made (every test in this phase uses
fake gateways/fixtures, matching every prior phase's own discipline).

## 2. Root cause

`services/fact_safety.py::apply_fact_safety()` (the only integration point Fact Safety has —
called exclusively from `capabilities/executor.py`, only for the "quality" step) extracted the
draft's text with two hard-coded lookups:

```python
title = copywriting_output.get("title")
body = copywriting_output.get("body")
if not isinstance(title, str) or not isinstance(body, str):
    return structured_output   # silent no-op
```

`copywriting_output` is `context.business.workflow_state.step_results["copywriting"]` — the real,
already-produced output of whichever Copywriting prompt version actually ran. V4's schema has a
`body` key (confirmed via `capabilities/copywriting_capability.py::COPYWRITING_CAPABILITY_
DEFINITION.expected_output_keys`). V6's schema (`prompts/copywriting/v6.yaml`'s own
`output_schema`, read directly — not assumed) has **no `body` key at all**: its required fields
are `title, opening, context, why_it_matters, what_changed, what_happens_next, conclusion,
what_remains_unknown, quote`. For every real V6 draft, `copywriting_output.get("body")` returns
`None`, the `isinstance` guard fires, and `apply_fact_safety()` returns `structured_output`
completely unchanged — no `"fact_safety"` key, no log line, no exception. This is silent: nothing
in a log, a metric, or a test (before this phase) distinguished "fact safety ran and passed" from
"fact safety never ran because the schema wasn't recognized." Confirmed as a real, currently-live
gap by `tests/test_phase20_m1_harness_fixes.py`, which had already documented (Phase 20 M1) that
Variant B/C's real V6 drafts produced `fact_safety_status is None` — that assertion is fixed in
this milestone (§7) since the underlying behavior it recorded is what this phase repairs.

## 3. Architecture investigation

- **`capabilities/copywriting_capability.py`**: `execute()` returns `response.structured_output`
  verbatim (after floor-validating it against `prompt.output_schema`) — whatever shape the active
  prompt version's own schema declares, unmodified, unmapped, never normalized to a common shape
  anywhere in this file. `prompt_version` is read live from `settings.copywriting_prompt_version`
  at call time (default `"4"`); V6 is only ever selected by the manual comparison harness for the
  duration of a single call.
- **`prompts/copywriting/v6.yaml`** (read directly, not paraphrased): `output_schema.required` =
  `[title, opening, context, why_it_matters, what_changed, what_happens_next, conclusion,
  what_remains_unknown, quote]`. `what_happens_next`/`what_remains_unknown`/`quote` are the only
  genuinely nullable fields (`type: [string, "null"]` / `[object, "null"]`); the other five text
  fields are always non-null strings when Copywriting succeeds (Copywriting's own floor-validation
  in `_floor_validate()` enforces required-key presence and declared type before `execute()` ever
  returns).
- **`capabilities/quality_capability.py`**: `QUALITY_CAPABILITY_DEFINITION.expected_output_keys`
  is `{"passed": bool, "issues": list}` only — confirmed Quality's own output never carries draft
  text, exactly as `apply_fact_safety()`'s pre-existing docstring already stated.
- **`capabilities/executor.py`** (the sole call site, lines ~249-255): for `step.capability ==
  "quality"`, reads `research_output`/`copywriting_output` from `context.business.workflow_state.
  step_results` and calls `apply_fact_safety(news_event.title, news_event.content, news_event.url,
  research_output, copywriting_output, structured_output)`. Zero other call sites exist anywhere
  in the codebase.
- **`services/fact_safety.py::evaluate_fact_safety(draft_title: str, draft_body: str, evidence)`**
  — the pure, deterministic core — was already schema-agnostic *by construction*: its entire
  contract is two plain strings, concatenated into one `draft_text = f"{draft_title}\n{draft_body}
  "` blob before `extract_claims()` (itself a pure regex-based extractor with no notion of
  "Copywriting output" at all) ever runs. **The coupling to V4's specific field names lived
  entirely in `apply_fact_safety()`'s own two-line extraction, nowhere else.** This is the single
  most important architectural finding: no change to `evaluate_fact_safety()`, `extract_claims()`,
  `_classify_claim()`, or any classification/severity logic was needed or made.
- **`tests/test_fact_safety.py`**: existing convention confirmed — pure unit tests for extraction/
  classification, integration tests driving the real `CapabilityExecutor`/`WorkflowRunner` path
  with a fake "quality" Capability, `monkeypatch.setattr(settings, "fact_safety_mode", ...)` for
  mode control. Mirrored for the new Phase 21 test file (§7).
- **`capabilities/executor.py::_attach_editorial_completeness()`** (Phase 17 M5, a *different*
  quality-step hook, independent of `fact_safety_mode`/`apply_fact_safety()`'s own result) has the
  **exact same** `title = copywriting_output.get("title"); body = copywriting_output.get("body")`
  narrow-extraction pattern and therefore the same V6 blind spot. **Explicitly out of scope this
  phase** (the instruction scoped this work to "ONLY fixes V6 Copywriting compatibility with Fact
  Safety") — disclosed as a remaining limitation (§12), not fixed, not silently left undocumented.

**Answers to the four required questions**:
1. Fact Safety receives Copywriting's output via `capabilities/executor.py`'s "quality"-step
   branch, reading `context.business.workflow_state.step_results.get("copywriting", {})` and
   passing it as `copywriting_output` into `apply_fact_safety()`.
2. Before this fix, exactly two fields: `title`, `body` — both required to be `str`.
3. Yes, `apply_fact_safety()`'s own extraction was exclusively coupled to V4's `{title, body}`
   shape; `evaluate_fact_safety()` itself was never coupled to any schema at all.
4. The safest layer is the smallest one: a single pure function, `_extract_draft_text()`, added
   inside `services/fact_safety.py` itself, that reduces any *known* Copywriting schema to the
   `(title, body_text)` tuple `evaluate_fact_safety()` already accepted — see §4.

## 4. Chosen solution

**Option B (extend the extractor), implemented as one small pure function — not a new module,
not a new layer.** A full separate "Draft Safety Adapter" module (Option A as originally framed)
would duplicate work: the "common internal representation" `evaluate_fact_safety()` already
expects is just two strings, and that function was never touched or needed touching. Building a
whole new adapter module to produce two strings that already have a natural home
(`services/fact_safety.py`, the same file that already defines `FactEvidence`/`evaluate_fact_
safety`/`extract_claims`) would be over-engineering relative to the actual gap.

Added to `services/fact_safety.py`, immediately before `apply_fact_safety()`:

```python
_V6_REQUIRED_TEXT_KEYS = ("opening", "context", "why_it_matters", "what_changed", "conclusion")
_V6_OPTIONAL_TEXT_KEYS = ("what_happens_next", "what_remains_unknown")

def _extract_draft_text(copywriting_output: dict[str, Any]) -> tuple[str, str] | None:
    title = copywriting_output.get("title")
    if not isinstance(title, str):
        return None
    body = copywriting_output.get("body")
    if isinstance(body, str):
        return title, body                      # V4 (and any future schema keeping "body")
    if all(isinstance(copywriting_output.get(k), str) for k in _V6_REQUIRED_TEXT_KEYS):
        sections = [copywriting_output[k] for k in _V6_REQUIRED_TEXT_KEYS]
        sections.extend(
            copywriting_output[k] for k in _V6_OPTIONAL_TEXT_KEYS
            if isinstance(copywriting_output.get(k), str)
        )
        return title, "\n\n".join(sections)
    return None                                  # genuinely unrecognized schema
```

`apply_fact_safety()` now calls this once, and — new behavior — explicitly handles the "genuinely
unrecognized schema" case instead of silently returning `structured_output` unchanged:

```python
draft_text = _extract_draft_text(copywriting_output)
if draft_text is None:
    logger.warning("fact_safety_unsupported_copywriting_schema",
                    extra={"copywriting_output_keys": sorted(copywriting_output.keys())})
    return {**structured_output, "fact_safety": {
        "version": FACT_SAFETY_VERSION, "status": "skipped",
        "mode": settings.fact_safety_mode, "reason": "unsupported_copywriting_schema",
    }}
title, body = draft_text
# ... unchanged: build FactEvidence, call evaluate_fact_safety(title, body, evidence)
```

V6's two nullable narrative fields (`what_happens_next`, `what_remains_unknown`) are included in
the concatenation only when the draft actually populated them (V6's own prompt sets them to
`null`, not `""`, when there's nothing genuine to say — §21 of the v6 prompt's own rules) —
concatenating a `None` would be a type error, and treating a deliberate `null` as an empty string
to check would add no real claim-checking value while risking a spurious "why is a null field
part of the checked text" question later. `quote` (a nullable *object*, not a text field — its own
`text`/`translated_text`/`speaker` sub-fields) is deliberately excluded from the concatenation:
quotes are governed by their own strict sourcing rule in the v6 prompt already (verbatim-only,
never paraphrased) and are a structurally different kind of claim than the numeric/date/entity
claims `extract_claims()` looks for in prose; folding a quote's `text` into the same blob risks a
quoted *third party's* words being misclassified as the *draft's own* unsupported claim. Extending
quote-awareness into Fact Safety, if ever wanted, is a distinct, separately-scoped future decision
— not made here, not needed to close this phase's stated gap.

## 5. Why this solution is safest

- **`evaluate_fact_safety()` was not modified at all** — every existing claim-extraction/
  classification/severity test for it (`tests/test_fact_safety.py`'s pure-unit tier) exercises
  exactly the same code path as before, unchanged behavior guaranteed by construction, not by
  re-testing.
- **V4 behavior is byte-identical**: `_extract_draft_text()`'s first branch (`isinstance(body,
  str): return title, body`) is the exact same two-line extraction the pre-fix code performed —
  no new logic runs for a V4 draft at all.
- **Never returns success without checking**: the previous behavior (return `structured_output`
  unchanged, no key, no log) was indistinguishable from "ran and found nothing wrong." The new
  behavior for a genuinely unrecognized schema adds an explicit `"fact_safety": {"status":
  "skipped", "reason": "unsupported_copywriting_schema"}` marker plus a `logger.warning(...)` call
  — any caller inspecting the result, and any log-based monitoring, can now tell the difference.
- **`"skipped"` cannot be mistaken for a real gating verdict downstream**: `services/
  content_draft_service.py::_draft_status_for()` only ever branches on the literal strings
  `"block"`/`"review"`; every other value (including the pre-existing `"pass"` and the new
  `"skipped"`) falls through to its default `"draft"` return. This function's own long-standing
  "must not affect delivery" discipline (stated in its own docstring, unchanged) is preserved
  exactly — a schema this module doesn't yet recognize degrades to *visible inaction*, never to a
  silent false "pass" and never to blocking a draft it couldn't actually check.
- **No prompt changed, no V6 field renamed or removed, no `body` field added to V6's schema**:
  `prompts/copywriting/v6.yaml` is untouched (confirmed: `git status --short prompts/copywriting/
  v6.yaml` shows only its pre-existing untracked/new status from Phase 19, no further edit this
  phase). Fact Safety adapted to V6, not the reverse, exactly as instructed.
- **Extending to a hypothetical future V7 schema needs no change to `evaluate_fact_safety()` or
  any claim-classification code** — only a new branch inside `_extract_draft_text()`, the single
  narrow seam this fix introduced for exactly this purpose.

## 6. Files changed

**Modified**: `services/fact_safety.py` (added `import logging`/module `logger`; added
`_extract_draft_text()` and its two key-tuples; `apply_fact_safety()`'s draft-text extraction now
calls it and handles the unsupported-schema case explicitly — everything else in the file,
including `evaluate_fact_safety()`, `extract_claims()`, `_classify_claim()`, `FactEvidence`, is
byte-unchanged). `tests/test_phase20_m1_harness_fixes.py` (one assertion updated — see §8 — the
test's own prior comment explicitly described the bug this phase fixes; the assertion now reflects
the corrected, real behavior instead of the documented-bug behavior).

**Created**: `tests/test_fact_safety_v6_compatibility.py` (new, dedicated Phase 21 test file — the
existing `tests/test_fact_safety.py` was not edited destructively, matching this session's own
established "create a dedicated regression file" convention); `docs/phase21_v6_fact_safety_report.md`
(this report).

No migration created (none needed — zero schema change). No `.env` edit. No prompt file edit.

## 7. Tests added

`tests/test_fact_safety_v6_compatibility.py`, 6 tests, exactly covering the four required cases
(two of the four cases get an extra corroborating test each):

- **CASE 1** — `test_case_1_v4_body_schema_runs_fact_safety_normally`: V4 `{title, body}` still
  produces a real `fact_safety` result (regression guard).
- **CASE 2** — `test_case_2_v6_schema_runs_fact_safety_normally` (a full, realistic V6 output with
  every required section populated produces a real result) and
  `test_case_2_v6_schema_checks_claims_from_every_section_not_just_one_field` (a fabricated $4.2
  billion claim placed only in `conclusion` — a section with no V4 analogue — is still caught,
  proving the whole draft is concatenated, not just `title` or one field).
- **CASE 3** — `test_case_3_unsupported_schema_never_silently_passes` (a schema with neither `body`
  nor V6's required fields produces `status: "skipped"`, `reason: "unsupported_copywriting_schema"`,
  and a captured `WARNING` log — asserted via `caplog`) and
  `test_case_3_unsupported_schema_missing_title_also_fails_explicitly` (no `title` at all also
  degrades explicitly, never silently).
- **CASE 4** — `test_case_4_story_memory_update_context_v6_draft_checked_against_prior_facts`:
  simulates Research's `facts` list already containing a fact from *prior* coverage (the shape
  Story Memory's own prior-coverage context would surface) alongside a new V6 draft whose
  `what_changed` section states a genuinely new, unsupported $9.3 million figure; Fact Safety
  correctly flags it as `unsupported`, proving the fix works with Story Memory's own upstream
  context, not only in isolation.

## 8. Before/after results

**Before** (confirmed failing against unmodified code, test-first — see the raw pytest output
captured this session): Cases 2/3/4 all failed. Case 2's two tests failed with `KeyError:
'fact_safety'` (the key was never added). Case 3's two tests failed because `"fact_safety" in out`
was `False` (nothing logged, nothing returned — indistinguishable from success). Case 4 failed
identically to Case 2. Case 1 (V4) passed even before the fix, as expected — it is the pure
regression guard.

**After**: all 6 pass. Full command and result:
```
python -m pytest tests/test_fact_safety_v6_compatibility.py -v
6 passed in 8.81s
```

**Pre-existing bug now fixed in an already-existing test**: `tests/test_phase20_m1_harness_fixes.py
::test_m1_shared_context_costs_are_recorded_and_not_duplicated` had asserted `variant_b.fact_
safety_status is None` / `variant_c.fact_safety_status is None`, with its own comment explicitly
documenting this as "a real discovery, not a bug in this fix" (Phase 20 M1's own honest disclosure
of the exact gap this phase closes). That assertion is now `== "pass"` for both variants,
confirmed passing:
```
python -m pytest tests/test_phase20_m1_harness_fixes.py -v
1 passed in 2.82s
```

**Full relevant regression** (Fact Safety, Copywriting, Quality, Story Memory, Editorial
Completeness, Editorial Content Type, all Phase 20 suites, all new Phase 21 tests — 441 tests
total in this run):
```
python -m pytest tests/ -k "fact_safety or story_memory or story_delta or story_suppression or
  editorial_content_type or phase20 or story_identity or human_reviewed_calibration or
  copywriting or quality_capability" -q
438 passed, 2 skipped, 2620 deselected, 2 failed, 1 error
```
The 2 failures and 1 error are **pre-existing, confirmed via `git stash` to reproduce byte-
identically on unmodified code** (not caused by this phase):
- `test_fact_safety.py::test_off_mode_leaves_quality_step_result_completely_unchanged` and
  `::test_shadow_mode_enriches_quality_result_and_detects_unsupported_claim` — both assert
  `await _ai_execution_count(db_session) == 0` but observe `4863`, a real-Postgres `AIExecution`
  row count that already includes rows left over from unrelated prior sessions/runs in this local
  environment (not scoped to the test's own transaction) — reproduces identically with `services/
  fact_safety.py` fully reverted.
- `test_content_cycle_story_delivery.py::test_story_memory_shadow_alone_never_affects_telegram_
  delivery` — a teardown-time `ForeignKeyViolationError` deleting a leftover `news_events` row
  still referenced by another table (`content_draft_editorial_plans` this run; a *different* table,
  `news_event_article_acquisitions`, on the reverted-code run — confirming this is generic
  fixture-cleanup ordering noise from accumulated local DB state, not something this phase's
  own diff touches). The test's own assertions pass; only its teardown errors.
- The same `4863`-row pattern also appears in `tests/test_editorial_scoring.py` (2 tests),
  `tests/test_content_generation_integration.py` (1 test + 1 error), `tests/
  test_content_worker_cycle.py` (2 tests + 1 error) when run — reproduced identically on unmodified
  code via the same `git stash` check. None of these files were touched this phase.

Ruff (`services/fact_safety.py`, `tests/test_fact_safety_v6_compatibility.py`, `tests/
test_phase20_m1_harness_fixes.py`): **all checks passed**. Mypy (`services/fact_safety.py`):
**Success: no issues found**.

## 9. V4 compatibility result

**Unchanged, confirmed byte-identical.** `_extract_draft_text()`'s V4 branch is the exact
pre-existing two-line lookup; every existing `tests/test_fact_safety.py` test that exercises V4
`{title, body}` output (102 passing, 2 pre-existing/unrelated failures per §8) behaves exactly as
before. Case 1 of the new test file is a dedicated regression guard for this.

## 10. V6 compatibility result

**Fixed.** A real, fully-populated V6 draft (`title` + all 5 required narrative sections, 2
optional sections when present) now produces a genuine `fact_safety` result — claims are extracted
from the complete draft text (every section, not one field), classified, and returned exactly as
V4 always was. Verified both in isolation (Case 2) and via the real Phase 20 M1 harness path
(§8's `test_m1_shared_context_costs_are_recorded_and_not_duplicated`), which drives the actual
`CopywritingCapability`/prompt-resolution/`apply_fact_safety()` chain, not a synthetic fixture.

## 11. Story Memory compatibility result

**Confirmed working end-to-end.** Case 4 (the required Story Memory scenario) simulates Research's
`facts` already containing a fact carried forward from prior coverage — the exact shape Story
Memory's own prior-coverage serializer produces — alongside a new V6 draft whose `what_changed`
section states a new, unsupported number. Fact Safety correctly classifies it as `unsupported`
against the supplied evidence, proving the fix composes correctly with Story Memory's own upstream
context rather than only working in a hand-crafted isolated case. Story Memory itself
(`services/story_memory.py`, `services/story_delta_engine.py`, `services/story_suppression.py`,
`services/editorial_content_type.py`) was not touched this phase — all 438 passing tests in §8's
combined run include the full Phase 20 Story Memory suite, confirming no regression there either.

## 12. Remaining limitations

1. **`capabilities/executor.py::_attach_editorial_completeness()` has the identical V6 blind
   spot** (`title`/`body`-only extraction, same silent-no-op-on-missing-body shape) — confirmed
   during this phase's own investigation (§3) but **explicitly out of scope**: the phase brief
   scoped this work to "ONLY fixes V6 Copywriting compatibility with Fact Safety." Disclosed here,
   not fixed, not silently left undiscovered.
2. **Quote-field claims are not checked**: V6's `quote` object (`text`/`translated_text`/
   `speaker`) is deliberately excluded from the concatenated draft text (§4's own reasoning) —
   Fact Safety's existing `"quote"` `ClaimType` still only ever fires on quote-shaped text inside
   the narrative sections, exactly as it did for V4 (V4's `body` never structurally separated a
   quote from prose either, so this is not a new gap V6 introduces — it is pre-existing and
   unchanged).
3. **`fact_safety_mode` remains `"shadow"`** in the real environment (pre-existing, unchanged this
   phase, unrelated to this fix) — `"enforce"` was never active before this phase and is not
   active now; nothing in this fix requires or suggests changing that setting, and it was not
   changed.
4. **Every remaining Phase 20 limitation is carried forward unchanged and unaddressed this
   phase**: Cases 58/60's same-content-type-different-work gap (Phase 20.7 §13), AI Olympiad
   4/8's identity-bootstrap gap, Moscow-pair non-convergence, the 173-case suppression packet
   still awaiting full human review beyond the 23 already-reviewed calibration cases, and Story
   Memory/duplicate-suppression/story-update routing remaining **NO-GO for enforce** exactly as
   Phase 20.8's final decision matrix concluded — this phase changed none of those recommendations.
5. **Pre-existing local-environment test pollution** (§8's `4863`-row `AIExecution` count and the
   FK-violation teardown error) is unrelated to this fix but was newly *observed* and documented
   this phase — worth a future, separately-scoped cleanup (likely a stale local Postgres volume
   accumulating rows across many manual/replay runs this session), not attempted here since it is
   outside this phase's stated scope and does not affect the correctness of anything shipped this
   milestone.

---

**STOP condition met.** No Telegram routing, no server deployment, no Story Memory production
activation, no `fact_safety_mode` change, and no Phase 22 work was started. Waiting for review
before Phase 22 — Telegram Editorial Routing.
