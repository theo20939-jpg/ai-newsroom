# OpenAI Structured Outputs Remediation Plan
## Track A (schema compatibility) + Track B (provider error observability)

**Status: planning document only.** No production code, prompt, test, or architecture contract was
modified to produce this document. No live API call was made. This plan re-verifies, from source,
the two MAJOR findings of `docs/openai_structured_outputs_blocker_audit.md` and specifies exactly
what a future, explicitly authorized implementation session must do — it does not implement
anything itself.

---

# Executive Summary

Two independent, real defects block Phase 10's live-validation Definition-of-Done item, both
inherited from pre-Phase-10 (Phase 6/7) infrastructure:

- **Track A**: `OpenAIAdapter._build_payload()` (`integrations/llm_gateway/providers/
  openai_adapter.py:229-237`) unconditionally sets `"strict": True` on every structured-output
  request. None of the 6 live-reachable prompt schemas (independently re-confirmed this session by
  direct read of all 8 files under `prompts/`) declare `"additionalProperties": false`, which
  OpenAI's Structured Outputs API requires under `strict: true`. Three of those six also have
  array-typed properties with no `items` sub-schema (`research.facts`/`.gaps`,
  `copywriting.hashtags`, `quality.issues`), a second, related strict-mode gap. All 5 registered
  Capabilities are affected identically.
- **Track B**: `FallbackPolicy._attempt_candidate()` (`integrations/llm_gateway/fallback/
  policy.py:196-200`) catches `ProviderPermanentIncompatibleError`/`ProviderTransientError` —
  which, per direct read of `openai_adapter.py:119-171`'s `_translate_exception()`, already carry a
  fully redacted, safe-to-log message containing OpenAI's real rejection detail — and discards that
  message entirely, keeping only a coarse `FailureClass` enum value. The final
  `AllProvidersFailedError` raised at exhaustion (`policy.py:323-327`) is a purely templated string
  with zero per-candidate detail, and that same generic string is exactly what ends up persisted in
  `WorkflowStepResult.error` (traced through `capabilities/gateway_call.py`'s error classification
  and `workflows/runner.py`'s `_run_step()`).

Both tracks are cross-phase infrastructure corrections (Phase 6/7 artifacts), not Phase 10 defects.
Track A's fix touches only prompt YAML files (new versions, never in-place edits) plus one-line
`PROMPT_VERSION` bumps in 5 Capability files (2 of which are Phase 10's own —
`copywriting_capability.py`, `quality_capability.py`). Track B's fix touches exactly one file,
`integrations/llm_gateway/fallback/policy.py`. Neither requires a migration, a Protocol change, or
any frozen architectural-boundary change.

---

# Confirmed Scope

Re-verified from source this session (not copied from the prior audit without re-checking):

**Track A files** (schema remediation):
- `prompts/research/v1.yaml` — `facts: array` (no `items`), `gaps: array` (no `items`), no
  `additionalProperties`.
- `prompts/intelligence/v1.yaml` — no array properties; no `additionalProperties`.
- `prompts/scoring/v1.yaml` — no array properties; no `additionalProperties`.
- `prompts/copywriting/v1.yaml` — `hashtags: array` (no `items`); no `additionalProperties`.
- `prompts/quality/v1.yaml` — `issues: array` (no `items`); no `additionalProperties`. (Superseded
  as the default by v2, but still independently resolvable — Phase 6 §8 immutability — and would
  fail identically if ever resolved directly.)
- `prompts/quality/v2.yaml` — same gap as v1 (current live default for `QualityCapability`).
- `prompts/demo_summary/v1.yaml` / `v2.yaml` — same `additionalProperties` gap; no array
  properties. **Dormant**: `grep -rn "demo_summary" capabilities/registry.py` returns nothing — no
  Capability is registered under this name, confirmed this session. Included for repository-wide
  hygiene only, not live-blocking.
- Corresponding `PROMPT_VERSION` one-line edits: `capabilities/research_capability.py:37`,
  `capabilities/intelligence_capability.py:36`, `capabilities/scoring_capability.py:45`,
  `capabilities/copywriting_capability.py:38`, `capabilities/quality_capability.py:43` — current
  values confirmed this session: `"1"`, `"1"`, `"1"`, `"1"`, `"2"` respectively.
- One new test file: `tests/test_openai_strict_schema_compliance.py`.
- **Six existing test files, mechanically updated** (corrects MAJOR-1 of
  `docs/openai_structured_outputs_remediation_plan_audit.md` — the original scope claim of "one new
  test file" undercounted this by 6x). Each of these six files' `FakePromptRepository` fixture
  registers a `RenderedPrompt` with a hardcoded `version="<current PROMPT_VERSION>"` string,
  confirmed by direct grep this session:
  - `tests/test_copywriting_capability.py:76` — `version="1"`
  - `tests/test_research_capability.py:58` — `version="1"`
  - `tests/test_intelligence_capability.py:68` — `version="1"`
  - `tests/test_scoring_capability.py:56` — `version="1"`
  - `tests/test_scoring_capability_retry.py:40` — `version="1"`
  - `tests/test_quality_capability.py:52` — `version="2"`

  Each hardcoded value is the exact same value being bumped away from in M2 above. This is the
  identical mechanical break Phase 10 M2 already fixed once, for `test_quality_capability.py`
  alone, when `QualityCapability.PROMPT_VERSION` moved `"1"` → `"2"` — the same fix pattern now
  applies to all six. For every one of these six files: **this is a mechanical fixture/version
  registration update only** — the `version="..."` string argument changes to match the
  Capability's new `PROMPT_VERSION`, nothing else. **Assertions and behavioral expectations MUST
  NOT be weakened.** The change exists *only* because the corresponding Capability's
  `PROMPT_VERSION` moves from vN to vN+1 in this same plan's M2 — no test behavior redesign is
  authorized, and none is needed (`FakePromptRepository` is version-string-keyed only; its
  `system`/`rules`/`output_schema` content stays whatever each test already asserts against).

**Track B files** (error observability):
- `integrations/llm_gateway/fallback/policy.py` — exactly one file. `_AttemptOutcome` (a
  `@dataclass`, `policy.py:92-96`) gains one field; `_attempt_candidate()`
  (`policy.py:161-217`) populates it at its two failure `except` sites; `_run_sequence()`
  (`policy.py:236-`) threads the last failure's detail into the final `AllProvidersFailedError`
  message (`policy.py:323-327`) and into the existing `"fallback"` log line's `extra` dict
  (`policy.py:292-301`).
- `integrations/llm_gateway/errors.py`'s `AllProvidersFailedError` — **no signature change
  needed**; its constructor already accepts an arbitrary `message: str` plus `reason: str`
  (`errors.py:70-78`), so a richer message string is sufficient — confirmed by direct read.
- One new/extended test.

**Phase 10 file isolation, stated precisely**: four files this plan touches were created or
modified during Phase 10 — `capabilities/copywriting_capability.py` and
`capabilities/quality_capability.py` (their `PROMPT_VERSION` constants), plus
`tests/test_copywriting_capability.py` and `tests/test_quality_capability.py` (their
`FakePromptRepository` fixture version strings, mechanically realigned in M2). Each of these four
is explicitly **cross-phase remediation touching a Phase 10-created/modified file** — not new
Phase 10 feature work, not a change to Phase 10 workflow, `ContentDraft`, CLI, or architecture
behavior. No other Phase 10-authorized file (the remaining 5 of Phase 10's 9 authorized production
files, and Phase 10's own test files beyond the two named above) needs any change.

---

# Track A — Structured Outputs Remediation

## Per-Capability detail

| Capability | Current prompt version | New prompt version | Schema change | `PROMPT_VERSION` bump |
|---|---|---|---|---|
| `ResearchCapability` | `research` v1 | `research` v2 (new file) | root `additionalProperties: false`; `facts.items: {type: string}`; `gaps.items: {type: string}` | `"1"` → `"2"` |
| `IntelligenceCapability` | `intelligence` v1 | `intelligence` v2 (new file) | root `additionalProperties: false` only (no arrays) | `"1"` → `"2"` |
| `ScoringCapability` | `scoring` v1 | `scoring` v2 (new file) | root `additionalProperties: false` only (no arrays) | `"1"` → `"2"` |
| `CopywritingCapability` | `copywriting` v1 | `copywriting` v2 (new file) | root `additionalProperties: false`; `hashtags.items: {type: string}` | `"1"` → `"2"` |
| `QualityCapability` | `quality` v2 | `quality` v3 (new file) | root `additionalProperties: false`; `issues.items: {type: string}` | `"2"` → `"3"` |
| *(dormant, no Capability)* | `demo_summary` v2 | `demo_summary` v3 (new file, hygiene only) | root `additionalProperties: false` only | N/A — no `PROMPT_VERSION` constant exists to bump |

Every schema in this repository (all 8 files, confirmed by direct read) is a **flat** object — no
property has `type: object` nested inside it. The fix therefore does not need to recurse into any
*currently existing* nested object, but the new mechanical test (see Required Tests) must still be
written recursion-safe, since OpenAI's own rule is inherently recursive and a future prompt could
add a nested object.

## Immutability

Confirmed, `docs/phase6_architecture_contract.md:543-546`, quoted exactly: *"prompt content...
is authored and versioned as files under `prompts/`, outside Python. `PromptRepository` is a pure
lookup contract over already-published prompt artifacts."* And `:576-577`: preserving old versions
"is what makes prompt regression tests... meaningful against production content." This is a binding
immutability rule — **no existing `v1.yaml`/`v2.yaml` file is edited in place anywhere in this
plan.** Every affected prompt gets exactly one new, additively-versioned file
(`vN+1.yaml`), mirroring the exact precedent Phase 10 M2 itself already established for
`quality/v1.yaml` → `quality/v2.yaml`. Old versions remain on disk, byte-for-byte unchanged,
forever independently resolvable via an explicit `resolve(name, old_version)` call.

**New files** (6): `prompts/research/v2.yaml`, `prompts/intelligence/v2.yaml`,
`prompts/scoring/v2.yaml`, `prompts/copywriting/v2.yaml`, `prompts/quality/v3.yaml`,
`prompts/demo_summary/v3.yaml`.

**Existing files, edited (one line each — the `PROMPT_VERSION` constant only, nothing else in the
file)**: `capabilities/research_capability.py`, `capabilities/intelligence_capability.py`,
`capabilities/scoring_capability.py`, `capabilities/copywriting_capability.py`,
`capabilities/quality_capability.py`.

## Strict mode / schema-mutation-location decision

**Do not disable `strict=true`.** The audit's own Architectural Ownership analysis (Option D)
concluded this suppresses the symptom without ever making the prompt contracts complete, and is a
deliberate trade-away of OpenAI's stronger enforcement that deserves a visible human decision, not
a silent flip inside an adapter file. This plan does not revisit that conclusion — re-verified as
still correct this session (no new evidence changes it).

**Do not move schema normalization/mutation into `OpenAIAdapter`.** Re-verified: `_build_payload()`
passes `request.response_schema` through to OpenAI **verbatim**
(`payload["text"]["format"]["schema"] = request.response_schema`, `openai_adapter.py:234`) — no
transformation happens there today, and this plan does not introduce one. Injecting
`additionalProperties`/`items` inside the adapter would create a permanent, silent divergence
between what a prompt author wrote in the YAML (still incomplete) and what OpenAI actually
enforces — exactly what Phase 6 §8's ownership rule exists to prevent (the schema
`_floor_validate()` validates against, the schema a human reads in the YAML, and the schema OpenAI
enforces must be the same schema).

**Do not normalize inside `PromptRepository`/`FilePromptRepository`.** Explicitly forbidden by
Phase 6 §8 (`docs/phase6_architecture_contract.md:578-579`, quoted exactly): *"Validation (schema
conformance, prompt-quality gates) happens in the Prompt Publisher, at publish time — never inside
`PromptRepository.resolve()`."* `FilePromptRepository.__init__()` (re-read this session,
`integrations/prompts/file_repository.py:105-121`) already performs zero schema transformation —
this plan does not add any.

---

# Track B — Error Observability

## Exact failure flow, traced this session

1. `OpenAIAdapter.generate()` catches `openai.OpenAIError` and calls `_translate_exception(exc,
   self._api_key)` (`openai_adapter.py:318-322`), which — for a `400` — builds
   `ProviderPermanentIncompatibleError(_redact(f"openai: bad request (code={code}): {exc.message}",
   api_key))` (`openai_adapter.py:128-133`). **The real OpenAI error detail is captured and safely
   redacted at this point** — `_redact()` (`openai_adapter.py:106-116`) strips the literal API key
   value, any `Bearer <token>` pattern, and any `sk-...`-shaped string before the message is ever
   attached to the exception. This message is safe to log or persist as-is.
2. `FallbackPolicy._attempt_candidate()` catches this exact exception
   (`policy.py:196-200`) and **discards it** — only `FailureClass.PERMANENT_INCOMPATIBLE` survives
   into the returned `_AttemptOutcome`.
3. `_run_sequence()`'s `"fallback"` log line (`policy.py:292-301`) logs `attempt_index`,
   `candidate_provider_id`, `candidate_model_id`, and `outcome.failure_class.value` — never the
   original message.
4. On exhaustion, `AllProvidersFailedError` is raised with a purely templated string
   (`policy.py:323-327`) — `f"All candidates exhausted for capability '{criteria.capability_name}'
   (objective={criteria.objective.value}, reason={reason})"` — zero per-candidate detail.
5. `capabilities/gateway_call.py::_classify_gateway_error()` wraps this into
   `PermanentCapabilityError(str(error))` — inherits the same generic string.
6. `capabilities/executor.py` re-raises as `PermanentStepFailureError(str(error))` — same string.
7. `workflows/runner.py::_run_step()` persists `WorkflowStepResult(..., error=str(error))` — **the
   generic string is exactly, and only, what ends up in the database**, which is exactly what was
   found (and found insufficient) during the live-validation session's own DB query.

## Minimal fix

- `_AttemptOutcome` (`policy.py:92-96`) gains one new field: `failure_detail: str | None = None`.
- `_attempt_candidate()`'s two failure branches capture it:
  ```python
  except ProviderPermanentIncompatibleError as exc:
      await self._health_store.mark_runtime_unavailable(provider_id, model_id)
      return _AttemptOutcome(
          success=False, response=None,
          failure_class=FailureClass.PERMANENT_INCOMPATIBLE, failure_detail=str(exc),
      )
  ```
  and identically for the `ProviderTransientError` branch (after retries are exhausted).
  `str(exc)` is exactly the already-redacted message `_translate_exception()` built — **no new
  redaction logic is needed in this file**, since the safety guarantee already exists one layer
  down, at the adapter boundary, and this fix only stops discarding what's already safe.
- `_run_sequence()` tracks `last_failure_detail: str | None` across the loop, updated whenever
  `outcome.success` is `False`; the `"fallback"` log line's `extra` dict gains one key,
  `"failure_detail": outcome.failure_detail`.
- The final `AllProvidersFailedError` message gains the last attempt's detail when one exists:
  ```python
  detail_suffix = f"; last error: {last_failure_detail}" if last_failure_detail else ""
  raise AllProvidersFailedError(
      f"All candidates exhausted for capability '{criteria.capability_name}' "
      f"(objective={criteria.objective.value}, reason={reason}){detail_suffix}",
      reason=reason,
  )
  ```
  This is the one change with outsized value: it makes the detail visible all the way to
  `WorkflowStepResult.error` (§ traced above) with **zero change to `capabilities/gateway_call.py`,
  `capabilities/executor.py`, or `workflows/runner.py`** — the existing `str(error)` propagation
  chain carries it automatically, since the enrichment happens at the message-string level, the
  earliest point already proven safe.

**No new redaction mechanism, no new exception class, no new field on `GenerateRequest`/
`GenerateResponse`/`CapabilityCall`, no change to the `FailureClass` enum's own values, no change
to retry/backoff/health-store behavior.** This is the smallest change that closes the gap at its
one real source.

---

# Affected Capability / Prompt Matrix

| Prompt | Version | Used by Capability | Structured output? | Strict mode? | Schema compliant today? | Affected? | Remediation |
|---|---|---|---|---|---|---|---|
| `scoring` | 1 | `ScoringCapability` (registered, live default) | Yes | Yes | No | **Yes** | new `scoring/v2.yaml` |
| `research` | 1 | `ResearchCapability` (registered, live default) | Yes | Yes | No | **Yes** — the exact schema that produced the observed live `400` | new `research/v2.yaml` |
| `intelligence` | 1 | `IntelligenceCapability` (registered, live default) | Yes | Yes | No | **Yes** | new `intelligence/v2.yaml` |
| `copywriting` | 1 | `CopywritingCapability` (registered, live default) | Yes | Yes | No | **Yes** | new `copywriting/v2.yaml` |
| `quality` | 1 | superseded (still independently resolvable) | Yes | Yes | No | **Yes**, if ever resolved directly | not remediated (immutable, historical) |
| `quality` | 2 | `QualityCapability` (registered, live default) | Yes | Yes | No | **Yes** | new `quality/v3.yaml` |
| `demo_summary` | 1 | none registered | N/A (never dispatched) | N/A | No | **Dormant** | not remediated (no consumer; hygiene-only `v3` optional) |
| `demo_summary` | 2 | none registered | N/A | N/A | No | **Dormant** | new `demo_summary/v3.yaml` (hygiene only) |

**5 of 5 registered Capabilities affected identically.** `quality/v1.yaml` is deliberately **not**
remediated — it is superseded, historical, immutable content; remediating it would violate the
"same version forever resolves the same content" rule for no live benefit (nothing resolves it by
default).

---

# Exact File Scope

| File | Track | Change type | Reason | Risk |
|---|---|---|---|---|
| `prompts/research/v2.yaml` | A | new file | strict-mode schema completeness | Low — additive, content-only |
| `prompts/intelligence/v2.yaml` | A | new file | strict-mode schema completeness | Low |
| `prompts/scoring/v2.yaml` | A | new file | strict-mode schema completeness | Low |
| `prompts/copywriting/v2.yaml` | A | new file | strict-mode schema completeness | Low |
| `prompts/quality/v3.yaml` | A | new file | strict-mode schema completeness | Low |
| `prompts/demo_summary/v3.yaml` | A | new file (hygiene, optional) | consistency; no live consumer | Negligible |
| `capabilities/research_capability.py` | A | 1-line edit (`PROMPT_VERSION`) | point at the compliant version | Low — no other line changes |
| `capabilities/intelligence_capability.py` | A | 1-line edit | same | Low |
| `capabilities/scoring_capability.py` | A | 1-line edit | same | Low |
| `capabilities/copywriting_capability.py` | A | 1-line edit | same | Low |
| `capabilities/quality_capability.py` | A | 1-line edit | same | Low |
| `tests/test_openai_strict_schema_compliance.py` | A | new test file | prevent regression; carries the red/green proof | Low |
| `tests/test_copywriting_capability.py` | A | mechanical edit (`FakePromptRepository` fixture `version="1"` → `"2"`, one line) | corresponding Capability `PROMPT_VERSION` bumps in M2; no assertion change | Low — cross-phase remediation touching a Phase 10-created test file, not new Phase 10 feature work |
| `tests/test_research_capability.py` | A | mechanical edit (fixture `version="1"` → `"2"`, one line) | same | Low |
| `tests/test_intelligence_capability.py` | A | mechanical edit (fixture `version="1"` → `"2"`, one line) | same | Low |
| `tests/test_scoring_capability.py` | A | mechanical edit (fixture `version="1"` → `"2"`, one line) | same | Low |
| `tests/test_scoring_capability_retry.py` | A | mechanical edit (fixture `version="1"` → `"2"`, one line) | same | Low |
| `tests/test_quality_capability.py` | A | mechanical edit (fixture `version="2"` → `"3"`, one line) | corresponding `QualityCapability.PROMPT_VERSION` bump `"2"`→`"3"` in M2; no assertion change | Low — cross-phase remediation touching a Phase 10-created test file (M2's own fix, applied a second time for the same reason), not new Phase 10 feature work |
| `integrations/llm_gateway/fallback/policy.py` | B | narrow edit (~10 lines across 3 functions) | preserve diagnostic detail | Low-Medium — touches frozen Phase 7 dispatch-loop code; must not change retry/health-store/cache semantics |
| `tests/test_fallback_policy_failure_detail.py` (or an addition to an existing `FallbackPolicy` test file, whichever the implementer finds cleaner after inspecting current test file layout) | B | new/extended test | prove detail survives, no regression | Low |

**File count, recalculated from the table above**: Track A = 18 files (6 new prompt YAML + 5
one-line `PROMPT_VERSION` edits + 1 new invariant test + 6 mechanical existing-test-fixture edits).
Track B = 2 files (1 `FallbackPolicy` edit + 1 new/extended test). **Total = 20 files**, corrected
from the prior, undercounted 14 (corrects MAJOR-1 of the plan audit).

**Architecture-change flag: none of the above represents an architecture change.** No `Protocol`
shape changes (`LLMGateway`, `PromptRepository`, `Capability` all untouched); no new inter-layer
dependency edge is introduced (Track B stays entirely inside the Gateway layer; Track A stays
entirely inside the prompt-versioning mechanism); no frozen contract's binding rule is violated —
confirmed against Phase 6 §8 (prompt ownership) and Phase 7's `FallbackPolicy`/`GatewayError`
contract sections. No migration is needed for either track — nothing touches the database schema.

Neither track touches any file outside this table. In particular: `openai_adapter.py`,
`FilePromptRepository`, `capabilities/executor.py`, `workflows/runner.py`,
`capabilities/gateway_call.py`, and every Phase 10 file **other than** the two `PROMPT_VERSION`
one-liners already counted above remain byte-for-byte unchanged.

---

# Dependency-Ordered Milestones

- **M0 — baseline / scope verification**: confirm current `git status` is clean of unrelated
  changes; confirm the exact current `PROMPT_VERSION` values and prompt file inventory (this
  document already did this once; re-verify immediately before implementation in case time has
  passed). No code change.
- **M1 — strict-schema prompt remediation**: create the 6 new prompt YAML files (Track A). No
  Python change yet — `PROMPT_VERSION` constants still point at the old versions, so behavior is
  unchanged; this milestone is purely additive and inert until M2.
- **M2 — prompt-version wiring**: bump the 5 `PROMPT_VERSION` constants. This is the one moment
  behavior changes — from this point, every registered Capability resolves the new, compliant
  schema by default. **M2 also owns, in the same milestone/commit, the six mechanical
  `FakePromptRepository` fixture-version updates** listed in Confirmed Scope above
  (`tests/test_copywriting_capability.py`, `tests/test_research_capability.py`,
  `tests/test_intelligence_capability.py`, `tests/test_scoring_capability.py`,
  `tests/test_scoring_capability_retry.py`, `tests/test_quality_capability.py`) — the
  `PROMPT_VERSION` bump and its six corresponding fixture updates are one atomic change, not two
  sequential ones. There must be no intentional broken-test window between the constant bump and
  the fixture update: M2's own checkpoint (running the six affected test files, plus
  `tests/test_copywriting_capability.py`'s and the others' full suites) must be internally green
  before M2 is considered complete — no milestone in this plan may intentionally leave the
  repository with a known-broken test, even transiently.
- **M3 — offline schema-compatibility test**: add `tests/test_openai_strict_schema_compliance.py`,
  proving (no network) that every Capability's currently-resolved prompt satisfies OpenAI's
  strict-mode shape. Sequenced after M1/M2 so the test is written and immediately verified against
  real, already-fixed content, not written blind.
- **M4 — provider error observability**: implement Track B's `FallbackPolicy` change, independent
  of M1-M3 (no dependency either direction — Track B would be equally correct applied before or
  after Track A; sequenced after only so a live retry, if M1-M3 alone had sufficed, would not be
  needlessly delayed by M4, but M4 provides no direct benefit to Track A's own correctness).
- **M5 — regression verification**: full automated suite (`python -m pytest -q`), `ruff check .`,
  targeted `mypy` on every changed file, `python -m scripts.validate_architecture` — all from a
  clean, dependency-ordered state, not skipped for either track.
- **M6 — retry Phase 10 live validation**: exactly the live-validation gate defined below.

No milestone here depends on anything outside this plan's own file scope; M1→M2→M3 is a hard
sequence (each depends on the previous), M4 is independent, M5 depends on all of M1-M4, M6 depends
on M5 passing clean.

---

# Test Plan

## Track A — `tests/test_openai_strict_schema_compliance.py`

**One repository-wide invariant test**, not five per-capability spot tests (cleaner, and
automatically covers any future Capability without a new test file) — hardcodes the same list of
five `(CAPABILITY_NAME, PROMPT_VERSION)` pairs `capabilities/registry.py::build_registry()` itself
hardcodes (mirroring this repository's own "no dynamic discovery" convention, confirmed as the
established pattern by `capabilities/registry.py`'s own module docstring), resolves each via a
real `FilePromptRepository` against the real `prompts/` directory (no network, no fakes — this
must validate the actual artifact a production boot would load), and recursively asserts, for
every object node found in `output_schema`:
1. `"additionalProperties" in schema and schema["additionalProperties"] is False`.
2. Every key in `schema.get("properties", {})` appears in `schema.get("required", [])` — already
   established practice, extended to be asserted by this same mechanical pass rather than only by
   each Capability's own `_floor_validate()` at runtime.
3. Every property whose `type == "array"` declares an `items` key.
4. Recurse into any property whose `type == "object"` (none exist today, but the check must not
   silently skip a future one).

Additionally: one assertion that each `PROMPT_VERSION` constant currently imported actually
resolves without raising `UnknownPromptError` (proving the wiring, not just the content) — a cheap
addition once the resolve call is already being made for the schema check above.

This directly extends the exact convention Contract §6 already established for a narrower, related
check (`output_schema.required` must equal `expected_output_keys`) — same "mechanically verify
every prompt file against a fixed rule" philosophy, not a new testing approach.

### Red/green proof, required

The invariant test above must be demonstrated capable of actually catching the exact class of
defect that produced the real OpenAI `400` — not merely a test that only ever proves already-compliant
schemas pass. Both of the following are required, using the safest repository-appropriate
technique; **no destructive git manipulation (e.g. temporarily checking out pre-remediation prompt
files) is required or permitted to demonstrate this**:

- **RED**: a dedicated unit-level test (not the repository-wide invariant itself, which by M3 is
  sequenced after M1/M2 and would only ever see already-fixed content) asserts the invariant's own
  validator function correctly *rejects* a small, local, known-invalid representative schema
  constructed inline in the test — e.g. `{"type": "object", "properties": {"x": {"type": "string"}},
  "required": ["x"]}` with no `additionalProperties: false`, and separately a schema with an
  array property missing `items`. This proves the validator logic itself is a real check, not a
  no-op or a check that only ever returns "pass."
  Additionally, documented (not necessarily re-executed once M2 has already switched the wiring):
  before M2 bumps the `PROMPT_VERSION` constants, running the same repository-wide invariant
  against the then-active (pre-remediation) prompt versions must fail, naming the exact
  capability/prompt/field that violates the rule — this is the literal condition that produced the
  real `400`, and the invariant must be shown to catch it at that point in the sequence, not only
  asserted to do so in the abstract.
- **GREEN**: after M1 (new versions exist) and M2 (constants point at them) both land, the same
  repository-wide invariant test passes for every one of the 5 registered, live-default,
  structured-output Capabilities.

This red/green pairing — a synthetic-schema unit check proving the validator logic is real, plus a
before/after demonstration against this repository's own actual prompt content — is the minimum
proof required; it does not require preserving a broken repository state at any commit boundary.

## Track B — extend or add a `FallbackPolicy` test

Must prove, without any live network call (using the existing `FakeProviderAdapter`/local
`ProviderRegistry`/`ModelRegistry` test harness already established in
`tests/test_phase9_capability_registration.py`'s and similar files' own pattern):
1. When every candidate raises `ProviderPermanentIncompatibleError` (or `ProviderTransientError`
   after exhausting `max_same_candidate_retries`), the raised `AllProvidersFailedError`'s message
   contains the last candidate's original exception message text.
2. `FailureClass` classification (`TRANSIENT` vs `PERMANENT_INCOMPATIBLE`) is unchanged — same
   `_AttemptOutcome.failure_class` values as before this change, for the same input conditions.
3. No sensitive data appears in the enriched message — assert a fake exception message containing
   a fabricated `sk-...`-shaped token, if constructed to already carry it (mirroring the redaction
   this Capability chain already relies on at the adapter boundary), is unaffected, since this
   fix does not touch `_redact()` at all — it only stops discarding an already-redacted string.
   (This is a "confirm we didn't break the existing guarantee," not a new redaction test — the
   redaction itself remains `openai_adapter.py`'s sole responsibility, unchanged.)
4. Existing `FallbackPolicy` behavior — retry count, backoff invocation, health-store marking,
   cache lookup/store, budget/rate-limit denial handling, moderation-block immediate-raise
   semantics — is unchanged: run the existing `FallbackPolicy` test suite (whatever file currently
   covers it) unmodified and confirm 100% pass, as the primary no-regression proof, plus the new
   assertions above as additions, not replacements.

---

# Live Validation Gate

No further live API call is made until **all nine** of the following hold, in this exact order:
1. `tests/test_openai_strict_schema_compliance.py` passes, including its red/green proof (Track A
   correctness, offline).
2. The `FallbackPolicy` test suite, including the new Track B assertions, passes (Track B
   correctness, offline, no regression).
3. All six mechanically-affected existing Capability tests pass
   (`tests/test_copywriting_capability.py`, `tests/test_research_capability.py`,
   `tests/test_intelligence_capability.py`, `tests/test_scoring_capability.py`,
   `tests/test_scoring_capability_retry.py`, `tests/test_quality_capability.py`) — confirmed green
   individually, not only as part of the full-suite run in the next item.
4. Full automated suite (`python -m pytest -q`) passes — the entire repository, not just the new
   tests, to catch any unforeseen interaction.
5. `python -m ruff check .` passes clean.
6. Targeted `mypy` passes clean for every changed Python production and test file (all 12 Python
   files in the Exact File Scope table above — the 5 `PROMPT_VERSION` edits, the 6 mechanical test
   fixture edits, the new invariant test, `fallback/policy.py`, and the Track B test).
7. `python -m scripts.validate_architecture` reports 0 violations.
8. Secret/security hygiene check: no credential committed, no `.env` tracked, no debug-only bypass,
   no live test accidentally calling an external API — mirroring the same check already performed
   during Phase 10's own live-validation session.
9. `git status`/`git diff --stat` scope is reviewed and matches exactly this plan's Exact File
   Scope table (20 files) — no unrelated file touched.

Only once all nine hold:
1. **One** minimal OpenAI smoke call (`python scripts/smoke_test_openai_adapter.py`) — only if
   meaningfully time has passed since the last confirmed-working smoke, or if the implementer wants
   independent confirmation the credential/quota state is still healthy before spending a
   pipeline-shaped call; skippable if the last smoke is still recent and trusted.
2. **One** real Phase 10 CLI run (`python -m scripts.run_content_generation <event_id>`), default
   production path, no fake injection — reusing the same, already-identified-safe `NewsEvent`
   (`cf8eaaab-4499-48ed-9bfb-3b6b593adec2`) from the prior live-validation attempt, since it still
   has no `CONTENT_GENERATION` task and no `ContentDraft` (re-verify this immediately before the
   retry, since state may have changed).

No repeated live retries are planned or authorized by this document. If this one retry still fails,
the correct response is a new, narrowly-scoped diagnostic session — not additional retries inside
the same session.

---

# Risks

- **`FallbackPolicy` is frozen, high-scrutiny Phase 7 dispatch-loop code.** Any change here risks
  subtly altering retry/backoff/health-store timing even when unintended. Mitigation: the plan's
  Track B change is additive-only (one new field, populated at two existing `except` sites, read at
  two existing call sites) — no existing control-flow branch, loop bound, or `await` point is
  restructured. The full existing `FallbackPolicy` test suite must pass unmodified as the primary
  no-regression gate (Test Plan, Track B, item 4).
- **A future prompt schema could add a nested object and the mechanical test could silently miss
  it if written non-recursively.** Mitigation: Test Plan explicitly requires recursive object-node
  traversal, not a root-only check, even though no current schema needs it.
- **Bumping 5 `PROMPT_VERSION` constants simultaneously changes live behavior for every registered
  Capability at once**, not just the one that produced the observed failure. Mitigation: the schema
  changes are purely additive completions of an already-declared contract (`additionalProperties:
  false`/`items` narrow, they do not loosen, the schema OpenAI validates against) — `_floor_validate()`
  is provably unaffected (it only reads `required`/`properties[*].type`, confirmed unchanged by this
  plan), so no Capability's runtime validation behavior changes; only OpenAI's own acceptance of the
  request changes, from reject to accept.
- **This plan's own confidence in the exact 400 cause remains a code-and-documentation-based
  hypothesis** (per the prior audit's own honest disclosure) until the retry in the Live Validation
  Gate actually succeeds — this plan does not overstate that as empirically proven.
- **Cross-phase authorization gap**: neither Track A nor Track B is currently authorized by any
  frozen Contract (Phase 10's is frozen and out of scope for Phase 6/7 files; no Phase 6/7
  amendment process has been invoked). This plan does not itself constitute that authorization —
  a human decision to open this narrow, cross-phase scope is still required before implementation,
  exactly as the prior audit already concluded.

---

# Definition of Done

Remediation is complete only when every one of the following holds:
1. All 5 registered Capabilities' currently-resolved prompt `output_schema` (via their live
   `PROMPT_VERSION`) is OpenAI strict-mode compliant — `additionalProperties: false` at every
   object node, every `properties` key present in `required`, every array property carries `items`.
2. No historical prompt-version file was edited in place — every fix shipped as a new version;
   `quality/v1.yaml`, `research/v1.yaml`, `intelligence/v1.yaml`, `scoring/v1.yaml`,
   `copywriting/v1.yaml` (Track A's "before" versions) remain on disk, byte-identical to today,
   still independently resolvable.
3. A real OpenAI structured-output request (any of the 5 Capabilities) proceeds past OpenAI's own
   schema validation — i.e., no `400 Bad Request` attributable to `additionalProperties`/`items`
   incompleteness recurs.
4. A genuine provider rejection (of any kind, not just this one) now surfaces enough diagnostic
   detail — provider name, HTTP status/code where the SDK exposes it, a sanitized message — in the
   final raised error and therefore in `WorkflowStepResult.error`, without ever exposing a
   credential.
5. `python -m pytest -q` passes in full (all pre-existing tests plus the new Track A/B tests).
6. `python -m ruff check .` and `python -m scripts.validate_architecture` both report clean.
7. Phase 10's live CLI validation (`scripts/run_content_generation.py`, default production path,
   real credential, real `NewsEvent`) completes with `TaskStatus.COMPLETED` and exactly one
   `ContentDraft` row persisted, independently re-verified in the database (mirroring the exact
   verification steps `docs/phase10_live_production_validation.md` already specifies).
8. Only once 1-7 all hold: Phase 10's Definition-of-Done items 9/10 (the real live smoke and the
   real manual CLI run) can be marked `PASS`, and Phase 10 may proceed to its own separate closure
   step.

---

# Final Recommendation

Implement Track A via **Option A only** (six new, additively-versioned prompt files; five one-line
`PROMPT_VERSION` bumps; one new recursive, no-network mechanical test carrying an explicit
red/green proof; six existing test files' `FakePromptRepository` fixtures mechanically realigned
to the new version strings, in the same M2 milestone as the `PROMPT_VERSION` bumps, with zero
assertion or behavioral change) and Track B via the **minimal `_AttemptOutcome`/
`AllProvidersFailedError` message-enrichment change** described above (one file, ~10 lines, one
new/extended no-network test). Both tracks are cross-phase infrastructure corrections requiring a
narrow, explicit authorization outside Phase 10's own frozen Contract before implementation — this
plan specifies both precisely enough, across 20 total files (18 Track A, 2 Track B), for that
future, authorized session to implement directly from this document, in the M0-M6 order given,
gated on the nine-item Live Validation Gate before any further API quota is spent.

REMEDIATION PLAN REVISION COMPLETE — READY FOR RE-AUDIT
