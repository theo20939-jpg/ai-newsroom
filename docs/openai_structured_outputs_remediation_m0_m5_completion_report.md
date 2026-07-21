# CROSS-PHASE REMEDIATION M0–M5 COMPLETION REPORT
## OpenAI Structured Outputs Compatibility + Provider Error Observability

**Status: implementation report.** Records what M0–M5 actually built, against
`docs/openai_structured_outputs_remediation_plan.md` (approved) and its re-audit
(`docs/openai_structured_outputs_remediation_plan_reaudit.md`, verdict: APPROVED). M6 (live
validation) was explicitly **not** performed — no OpenAI API call was made anywhere in this
session.

---

## 1. Executive Summary

Both approved tracks are implemented, tested, and verified clean:

- **Track A** (structured-outputs strict-schema compatibility): 6 new, additively-versioned
  prompt files created; 5 `PROMPT_VERSION` constants bumped; 6 existing test files' fixtures
  mechanically realigned; 1 new repository-wide invariant test added, with explicit red/green
  proof.
- **Track B** (provider error observability): `FallbackPolicy` now preserves the sanitized
  provider rejection detail `OpenAIAdapter` already safely captures; 4 new tests added; all 13
  pre-existing `FallbackPolicy` tests pass unmodified.

Exactly the approved 20-file scope was touched — independently re-verified against `git status`/
`git diff` below, matching the plan's own table file-for-file. **727/727** tests pass
(707 Phase 10 baseline + 20 new), ruff/mypy/architecture-validator all clean, no secret exposure
found. The repository is ready for M6; M6 was not performed in this session.

---

## 2. M0 Baseline Result

Reconfirmed immediately before implementation, all matching the approved plan exactly:
- 5 registered Capabilities (`scoring`, `quality`, `research`, `intelligence`, `copywriting`) —
  confirmed via `capabilities/registry.py`.
- Pre-remediation `PROMPT_VERSION`s: scoring `"1"`, quality `"2"`, research `"1"`, intelligence
  `"1"`, copywriting `"1"`.
- 8 prompt files on disk before remediation, exactly as the plan enumerated.
- `OpenAIAdapter._build_payload()`'s unconditional `strict: True` and `_translate_exception()`'s
  already-redacted message capture, re-read and confirmed unchanged.
- `FallbackPolicy._attempt_candidate()`'s two `except` clauses confirmed to have **no `as exc`
  binding at all** before this session's edit — the exact discard point the plan named.
- All six mechanically-affected test files' hardcoded `version="..."` fixture values reconfirmed
  by direct grep.
- The re-audit's cosmetic "12 Python files" label was ignored per instruction; the complete
  enumerated 20-file list was used as scope authority throughout.

No discrepancy from the approved plan was found. Proceeded automatically to M1.

---

## 3. M1 Schema Remediation

Six new prompt versions created, every one additive (no historical file edited in place):

| File | Semantic content | Schema change |
|---|---|---|
| `prompts/research/v2.yaml` | unchanged from v1 | + `additionalProperties: false`; + `items: {type: string}` on `facts`/`gaps` |
| `prompts/intelligence/v2.yaml` | unchanged from v1 | + `additionalProperties: false` (no arrays) |
| `prompts/scoring/v2.yaml` | unchanged from v1 | + `additionalProperties: false` (no arrays) |
| `prompts/copywriting/v2.yaml` | unchanged from v1 | + `additionalProperties: false`; + `items: {type: string}` on `hashtags` |
| `prompts/quality/v3.yaml` | unchanged from v2 | + `additionalProperties: false`; + `items: {type: string}` on `issues` |
| `prompts/demo_summary/v3.yaml` (hygiene, dormant, no consumer) | unchanged from v2 | + `additionalProperties: false` (no arrays) |

Verified: all six load via a real `FilePromptRepository(Path("prompts"))` with zero code change;
`tests/test_file_prompt_repository.py`/`test_prompt_repository_protocol.py` (11 tests) pass
unmodified; every pre-existing `v1`/`v2` file confirmed untouched (`git status` shows no
modification to any historical prompt path — only the six new files appear as untracked
additions).

---

## 4. M2 Version Wiring

**Five `PROMPT_VERSION` bumps** (one line each, nothing else changed in any of these files):

| Capability file | Before | After |
|---|---|---|
| `capabilities/scoring_capability.py` | `"1"` | `"2"` |
| `capabilities/quality_capability.py` | `"2"` | `"3"` |
| `capabilities/research_capability.py` | `"1"` | `"2"` |
| `capabilities/intelligence_capability.py` | `"1"` | `"2"` |
| `capabilities/copywriting_capability.py` | `"1"` | `"2"` |

**Six mechanical test fixture updates**, landed in the same milestone (no broken-test window):

| Test file | Fixture change |
|---|---|
| `tests/test_copywriting_capability.py` | `FakePromptRepository` registration `version="1"` → `"2"` |
| `tests/test_research_capability.py` | `version="1"` → `"2"` |
| `tests/test_intelligence_capability.py` | `version="1"` → `"2"` |
| `tests/test_scoring_capability.py` | `version="1"` → `"2"` |
| `tests/test_scoring_capability_retry.py` | `version="1"` → `"2"` (registration, plus two `resolve(CAPABILITY_NAME, "1")` call sites also updated to `"2"` — a second hardcoded reference the original plan's scope note didn't separately enumerate but which is the identical class of mechanical break) |
| `tests/test_quality_capability.py` | `version="2"` → `"3"` (registration, plus `test_prompt_version_resolves_to_2` renamed to `test_prompt_version_resolves_to_3` and its assertion updated — same class of mechanical break) |

All six modules run together: **57/57 passed**. No assertion was weakened; no behavioral
expectation changed; every fix exists solely because its Capability's `PROMPT_VERSION` moved
forward.

Also re-ran the broader boot-wiring/registration/Phase 10 suite (28 tests spanning
`test_phase8_cross_cutting_regression.py` through `test_run_content_generation.py`) to confirm
no wider interaction — **28/28 passed**.

---

## 5. M3 Invariant Protection

New file: `tests/test_openai_strict_schema_compliance.py` (16 tests). A pure, recursive validator
function (`_strict_schema_violations()`) checks, at every object node: `additionalProperties`
is exactly `False`; every `properties` key is in `required`; every array property has `items`;
recurses into any nested object (none exist today, but the check is not root-only).

**RED evidence** (5 tests):
- Four unit tests prove the validator itself is a real check: it correctly flags a synthetic
  schema missing `additionalProperties`, a synthetic schema with a property absent from
  `required`, a synthetic array missing `items`, and a synthetic *nested* object missing
  `additionalProperties` at the inner level — and correctly passes a fully compliant synthetic
  schema.
- **One parametrized test, 6 cases**, resolves the real, still-on-disk, unmodified
  pre-remediation prompt files (`scoring` v1, `quality` v1, `quality` v2, `research` v1,
  `intelligence` v1, `copywriting` v1) via a real `FilePromptRepository` and asserts each one
  *fails* the invariant — empirical proof against this repository's own actual historical
  content (including `research` v1, the literal schema that produced the real live `400`), not
  a synthetic proxy. No git manipulation of any kind was needed — these files were never edited
  in place, so they remain directly resolvable exactly as they were before remediation.

**GREEN evidence** (1 parametrized test, 5 cases): every currently-active `(capability_name,
PROMPT_VERSION)` pair — `scoring`/`"2"`, `quality`/`"3"`, `research`/`"2"`,
`intelligence`/`"2"`, `copywriting`/`"2"` — resolves without raising `UnknownPromptError` and
passes the same invariant with zero violations, and each one's `output_schema["required"]` is
reconfirmed equal to its `CapabilityDefinition.expected_output_keys`.

All 16 tests pass. Ruff and mypy clean.

---

## 6. M4 Observability Fix

**File**: `integrations/llm_gateway/fallback/policy.py` (one file, as planned).

**Before**: `_attempt_candidate()`'s `except ProviderPermanentIncompatibleError:` and
`except ProviderTransientError:` had no `as exc` binding at all — the exception object,
including its already-redacted message, was discarded entirely. `_AttemptOutcome` carried only
`success`/`response`/`failure_class`. The final `AllProvidersFailedError` was a purely templated
string (`"All candidates exhausted for capability '{name}' (objective=..., reason=...)"`) with
zero per-candidate detail — exactly what ended up in `WorkflowStepResult.error` in the live
validation session's own database query.

**After**: `_AttemptOutcome` gains one field, `failure_detail: str | None = None`. Both `except`
clauses now bind `as exc` and pass `failure_detail=str(exc)` — `str(exc)` is exactly the message
`OpenAIAdapter._translate_exception()` already built and redacted; no new redaction logic was
added anywhere in this file. `_run_sequence()` tracks `last_failure_detail` across its loop
(updated on every failed attempt) and threads it into both the existing `"fallback"` log line's
`extra` dict and the final `AllProvidersFailedError` message, as an appended `"; last error:
..."` suffix only when a detail exists.

**No signature change** to `AllProvidersFailedError` (its constructor already accepted an
arbitrary message string). **Zero change** to `capabilities/gateway_call.py`,
`capabilities/executor.py`, or `workflows/runner.py` — the existing `str(error)` propagation
chain carries the enriched message automatically.

Verified: all 13 pre-existing `FallbackPolicy` tests pass **unmodified** (primary no-regression
proof — retry counts, backoff, health-store marking, cache lookup/store, budget/rate-limit
denial, moderation-block immediate-raise semantics all untouched). 4 new tests added and passing:
detail survives to the raised exception; no additional sensitive-data exposure beyond what
`_redact()` already guaranteed upstream; `FailureClass` classification unchanged
(white-box-verified per attempt type); a successful attempt carries no `failure_detail`.

---

## 7. M5 Verification — All Nine Gates

| # | Gate | Result |
|---|---|---|
| 1 | Track A strict-schema invariant tests | **16/16 passed** |
| 2 | Track B observability tests (full `FallbackPolicy` suite) | **17/17 passed** (13 pre-existing + 4 new) |
| 3 | All six mechanically-affected Capability test modules | **57/57 passed** |
| 4 | Full repository `pytest -q` | **727/727 passed** |
| 5 | `python -m ruff check .` | **All checks passed** |
| 6 | Targeted `mypy` on all 14 changed Python files | **Success: no issues found** |
| 7 | `python -m scripts.validate_architecture` | **0 violations** |
| 8 | Secret/security hygiene | **Clean** (§12 below) |
| 9 | Git scope review | **Exact 20-file match** (§13 below) |

---

## 8. Full Test Count

```
727 passed in 358.81s (0:05:58)
```
727 = 707 (Phase 10 M0–M4 baseline) + 20 new (16 invariant + 4 Track B). **0 failed, 0 errors,
0 skipped.**

---

## 9. Ruff

```
python -m ruff check .
All checks passed!
```

---

## 10. Mypy

```
python -m mypy capabilities/scoring_capability.py capabilities/quality_capability.py \
  capabilities/research_capability.py capabilities/intelligence_capability.py \
  capabilities/copywriting_capability.py tests/test_copywriting_capability.py \
  tests/test_research_capability.py tests/test_intelligence_capability.py \
  tests/test_scoring_capability.py tests/test_scoring_capability_retry.py \
  tests/test_quality_capability.py tests/test_openai_strict_schema_compliance.py \
  integrations/llm_gateway/fallback/policy.py tests/test_fallback_policy.py
Success: no issues found in 14 source files
```

---

## 11. Architecture Validator

```
python -m scripts.validate_architecture
validate_architecture: clean - 0 forbidden-dependency violations under C:\Users\Theodor\ai-newsroom
```

---

## 12. Security / Secret Hygiene

- `.env` confirmed not tracked (`git ls-files | grep -x "\.env"` → no output).
- Grep for credential-shaped strings (`sk-...`, `api_key = "..."`, `OPENAI_API_KEY = "..."`)
  across every changed prompt/production/test file → **no output, clean**.
- Grep for any live-API reference (`api.openai.com`, `openai.OpenAI(`, `AsyncOpenAI(`) across
  every new/modified test file → **no output, clean**.
- No debug-only bypass introduced anywhere in this diff.
- No credential of any kind appears in this report or in any file this session touched.

---

## 13. Git Scope

**Implementation files changed this session (20, exactly matching the approved plan):**

*Track A — Track A = 18:*
- New prompt files (6): `prompts/research/v2.yaml`, `prompts/intelligence/v2.yaml`,
  `prompts/scoring/v2.yaml`, `prompts/copywriting/v2.yaml`, `prompts/quality/v3.yaml`,
  `prompts/demo_summary/v3.yaml`
- `PROMPT_VERSION` edits (5): `capabilities/scoring_capability.py`,
  `capabilities/quality_capability.py`, `capabilities/research_capability.py`,
  `capabilities/intelligence_capability.py`, `capabilities/copywriting_capability.py`
- New invariant test (1): `tests/test_openai_strict_schema_compliance.py`
- Mechanical test fixture edits (6): `tests/test_copywriting_capability.py`,
  `tests/test_research_capability.py`, `tests/test_intelligence_capability.py`,
  `tests/test_scoring_capability.py`, `tests/test_scoring_capability_retry.py`,
  `tests/test_quality_capability.py`

*Track B — 2:*
- `integrations/llm_gateway/fallback/policy.py` (edit)
- `tests/test_fallback_policy.py` (edit)

**Pre-existing, untouched by this session** (confirmed via `git status`, listed for
completeness, not part of this diff): `capabilities/registry.py` and
`workflows/definitions/content_generation.py` (Phase 10 M2's own prior modifications);
`schemas/content_draft.py`, `services/content_draft_service.py`,
`scripts/run_content_generation.py`, `prompts/copywriting/v1.yaml`, and the four Phase 10
M3/M4 test files (Phase 10 M3/M4's own prior additions); every `docs/phase9_*` and
`docs/phase10_*` process document from earlier sessions; the four
`docs/openai_structured_outputs_*` planning/audit documents from earlier in this remediation
effort.

**Documentation-only file added this session**: this report,
`docs/openai_structured_outputs_remediation_m0_m5_completion_report.md`.

**No unexpected file was touched.** `git diff --name-only` lists exactly 13 modified tracked
files (5 capability + 6 test fixture + `policy.py` + `test_fallback_policy.py`); `git status
--short`'s untracked section adds exactly 7 new implementation files (6 prompts + 1 invariant
test) plus this one report, on top of everything already untracked from Phase 10/prior planning.

---

## 14. Phase 10 Isolation

**No Phase 10 behavior changed.** `workflows/definitions/content_generation.py`,
`capabilities/registry.py`, `schemas/content_draft.py`, `services/content_draft_service.py`,
and `scripts/run_content_generation.py` are all byte-identical to their state at the start of
this session — none was opened for editing. `capabilities/copywriting_capability.py` and
`capabilities/quality_capability.py` (Phase 10-created/modified files) each received exactly the
one-line `PROMPT_VERSION` mechanical edit already counted in Track A above — cross-phase
remediation touching a Phase-10-created file, not new Phase 10 feature work, per the approved
plan's own precise classification. `tests/test_copywriting_capability.py` and
`tests/test_quality_capability.py` (Phase 10-created test files) received the same class of
mechanical, non-behavioral fixture edit. No `CONTENT_GENERATION` workflow semantics,
`ContentDraft` lifecycle, `run_content_generation` orchestration behavior, `WorkflowRunner`, or
`CapabilityExecutor` code was touched.

---

## 15. Remaining Risks / Limitations

- **Root cause remains a very-high-confidence, code-and-content-based hypothesis until M6
  actually succeeds** — this report does not claim the live `400` is empirically fixed; it
  claims the identified defect class is now provably absent from every active schema (§5's
  red/green proof) and that the fix is minimal, additive, and does not touch anything the prior
  live failure didn't already implicate.
- **Two pre-existing `test_quality_capability.py` tests** (`test_v1_prompt_remains_on_disk_and_
  still_independently_resolvable`, `test_expected_output_keys_and_v2_schema_identical_to_v1`)
  still pass but now compare v1-vs-v2 rather than v1-vs-currently-active(v3); their docstrings
  describe v2 as "what QualityCapability now resolves," which is no longer accurate post-M2. Not
  broken, not blocking — left unmodified per the "no test behavior redesign" constraint; flagged
  here as a minor, non-blocking documentation-staleness note for a future session.
- **`FallbackPolicy`'s commit-failure/exhaustion-detail path was not exercised against a real
  OpenAI error** — Track B's tests use `FakeProviderAdapter`/a custom local adapter, proven
  correct at the unit level; the actual redacted-message format from a genuine OpenAI `400` will
  only be seen for real during M6.
- All limitations already disclosed in the four prior remediation-planning documents (the
  cross-phase authorization note, the plan's own risk table) remain accurate and are not
  repeated here.

---

## 16. Self-Audit Answers

1. **Are all active registered structured-output Capabilities strict-schema compatible?** Yes —
   proven directly (§5 GREEN, 5/5).
2. **Are all historical prompt versions untouched?** Yes — confirmed via `git status` (no
   modification to any pre-existing prompt path) and via the RED proof's own resolution of them.
3. **Do all active `PROMPT_VERSION` constants resolve to the intended new versions?** Yes —
   `"2"`/`"3"`/`"2"`/`"2"`/`"2"` for scoring/quality/research/intelligence/copywriting
   respectively, confirmed by direct grep and by the invariant test's successful resolution.
4. **Did any `expected_output_keys`/`output_schema` contract drift?** No — explicitly asserted
   equal for all 5 in the invariant test.
5. **Does the invariant test catch the actual defect class that caused the live `400`?** Yes —
   proven against the real, unmodified `research` v1 file (the literal schema involved) plus five
   other real pre-remediation files, not only synthetic schemas.
6. **Does `FallbackPolicy` now preserve useful sanitized provider rejection detail?** Yes —
   proven directly.
7. **Did fallback classification change?** No — proven directly (white-box `FailureClass` check)
   and by all 13 pre-existing tests passing unmodified.
8. **Did retry/fallback behavior change?** No — same evidence as above.
9. **Was any Phase 10 workflow behavior changed?** No.
10. **Was `ContentDraft` behavior changed?** No.
11. **Was `run_content_generation` behavior changed?** No.
12. **Was `WorkflowRunner` or `CapabilityExecutor` changed?** No — neither file was opened.
13. **Was any migration introduced?** No.
14. **Was any architecture contract violated?** No — `validate_architecture` reports 0
    violations; Phase 6 §8's prompt-immutability rule was followed exactly (every fix
    additively versioned, nothing edited in place).
15. **Is the repository safe to perform exactly one M6 real CLI validation run?** Yes — all nine
    gates pass, working tree contains exactly the expected 20-file remediation diff plus
    pre-existing, unrelated Phase 10/planning documentation, no secret exposure, no unauthorized
    change of any kind.

---

## 17. M6 Readiness

M6 READY — WAITING FOR HUMAN AUTHORIZATION
