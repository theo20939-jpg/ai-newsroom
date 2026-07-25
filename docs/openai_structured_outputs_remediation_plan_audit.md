# OpenAI Structured Outputs Remediation Plan — Independent Audit

**Status: audit document. Does not modify the remediation plan, code, prompts, tests, or any
architecture contract.** No live API call was made. Every claim below was independently re-derived
against current repository source, not taken on the remediation plan's or the originating blocker
audit's word.

---

# Executive Summary

The remediation plan (`docs/openai_structured_outputs_remediation_plan.md`) correctly diagnoses
both MAJOR findings and proposes the architecturally correct fix for each: Track A (versioned
prompt YAML files adding `additionalProperties: false`/`items`, never in-place edits) and Track B
(a narrow `FallbackPolicy` change that stops discarding an already-redacted provider message).
Every citation this audit re-checked — file:line references, exact code snippets, the Phase 6 §8
contract quotes, the `AllProvidersFailedError` constructor signature, the five registered
Capabilities, the flat (non-nested) shape of every prompt schema — was independently confirmed
accurate against live source, not merely re-stated from the plan's own text.

However, this audit found **one real, verifiable scope-completeness gap the plan did not catch**:
Track A's own "Exact File Scope" table claims exactly **one new test file** for Track A. Direct
`grep` across `tests/` found **six existing test files** that hardcode a `FakePromptRepository`
registration at `version="1"` (or `"2"` for quality) matching each affected Capability's *current*
`PROMPT_VERSION` — every one of them will raise `KeyError` the moment M2 bumps that constant,
exactly the same class of breakage the plan's own author already fixed once, for
`tests/test_quality_capability.py`, during Phase 10 M2. The plan's Milestone 6 M5 regression gate
would still catch this immediately and loudly (not silently) — so this is not a safety defect — but
it is a real, material undercount of the plan's own stated scope (1 file claimed vs. 6 actually
required), found by exactly the verification this audit was asked to perform (Part 3: "identify
every existing test likely to require a mechanical version update").

A second, smaller gap: the plan's Live Validation Gate omits explicit `mypy` and secret/hygiene
checks as gate conditions, even though every one of Phase 10's own M1-M4 milestones treated both as
mandatory before any live check — a real but trivial-to-add omission.

Neither gap invalidates the plan's technical approach, architecture-ownership reasoning, or
Track B design, all of which independently re-verify as correct. Both are additions, not
redesigns.

---

# Verified Scope

Independently re-derived (not copied from the plan's own 14-file claim):

**Track A — 6 new prompt files, confirmed correct and complete**:
`prompts/research/v2.yaml`, `prompts/intelligence/v2.yaml`, `prompts/scoring/v2.yaml`,
`prompts/copywriting/v2.yaml`, `prompts/quality/v3.yaml`, `prompts/demo_summary/v3.yaml` — verified
against the actual current version on disk for each of the 8 prompt files found via
`Glob("prompts/**/*.yaml")` (which returned exactly 8: `demo_summary` v1/v2, `scoring` v1,
`quality` v1/v2, `research` v1, `intelligence` v1, `copywriting` v1 — matching the plan's own count
exactly, no missed file, no phantom file).

**Track A — 5 `PROMPT_VERSION` one-line edits, confirmed correct and complete**: re-grepped every
`*_capability.py` file directly; confirmed current values `research="1"`, `intelligence="1"`,
`scoring="1"`, `copywriting="1"`, `quality="2"` — exactly matching the plan's claim, no drift since
the plan was written.

**Track A — test files: INCOMPLETE, corrected below** (see Findings MAJOR-1). The plan claims one
new file (`tests/test_openai_strict_schema_compliance.py`, correct and needed). It does not list
six *existing* files that will break: `tests/test_copywriting_capability.py`,
`tests/test_research_capability.py`, `tests/test_intelligence_capability.py`,
`tests/test_scoring_capability.py`, `tests/test_scoring_capability_retry.py`, and
`tests/test_quality_capability.py` (again — this time "2"→"3", not "1"→"2").

**Track B — 1 file (`integrations/llm_gateway/fallback/policy.py`) + 1 test file, confirmed
correct and complete**: re-traced the full exception path directly (see Observability Audit below)
and confirmed no other file needs to change. Checked every existing test that constructs or asserts
against `AllProvidersFailedError` (6 files found via grep: `test_copywriting_capability.py`,
`test_intelligence_capability.py`, `test_research_capability.py`, `test_scoring_capability.py`,
`test_gateway_call.py`, `test_llm_gateway_errors.py`) — none asserts exact message text; all either
construct the exception directly with their own hand-picked message (bypassing `FallbackPolicy`
entirely) or assert only `.reason`/type. `tests/test_fallback_policy.py`'s own two real
exhaustion-through-`dispatch()` tests were checked directly and also assert only `.reason`, never
message text. **Zero existing test breaks from Track B's change** — the plan's claim here holds.

**No hidden adapter/loader file requiring modification was found.** `FilePromptRepository.
__init__()` re-read directly: performs zero schema transformation, discovers new version files via
plain `sorted(name_dir.glob("v*.yaml"))` with no code change needed — confirmed. `OpenAIAdapter.
_build_payload()` passes `request.response_schema` through verbatim (`payload["text"]["format"]
["schema"] = request.response_schema`) — confirmed no transformation happens there today, and the
plan does not add one there (correctly, since that would violate Phase 6 §8, see below).

**No hidden `PROMPT_VERSION`-equivalent constant elsewhere in the codebase** was found — grepped
`PROMPT_VERSION` repository-wide via the same search Track A's own scope re-derivation used; the
only production-code occurrences are the five `*_capability.py` files already accounted for.

---

# Capability / Prompt Matrix

Rebuilt from source, not copied:

| Capability | `PROMPT_VERSION` (current) | Resolved prompt | `response_mode="json_schema"`? | `additionalProperties: false` today? | Nested objects? | Array `items` declared? | Plan's next version |
|---|---|---|---|---|---|---|---|
| `ScoringCapability` | `"1"` | `scoring/v1.yaml` | Yes (confirmed, `scoring_capability.py`) | No | None (flat: `score:int`, `rationale:str`) | N/A — no array properties | `scoring/v2.yaml` |
| `QualityCapability` | `"2"` | `quality/v2.yaml` | Yes | No | None (flat: `passed:bool`, `issues:array`) | No — `issues` has no `items` | `quality/v3.yaml` |
| `ResearchCapability` | `"1"` | `research/v1.yaml` | Yes | No | None (flat: `facts:array`, `confidence:number`, `gaps:array`) | No — neither array has `items` | `research/v2.yaml` |
| `IntelligenceCapability` | `"1"` | `intelligence/v1.yaml` | Yes | No | None (flat, no arrays) | N/A | `intelligence/v2.yaml` |
| `CopywritingCapability` | `"1"` | `copywriting/v1.yaml` | Yes | No | None (flat: `title:str`, `body:str`, `hashtags:array`) | No — `hashtags` has no `items` | `copywriting/v2.yaml` |
| *(no Capability)* | — | `demo_summary/v1.yaml`, `v2.yaml` | N/A — never dispatched, confirmed via `grep -rn demo_summary capabilities/registry.py` returning nothing | No | None | N/A | `demo_summary/v3.yaml` (hygiene only) |

**No capability/prompt mismatch found.** Every one of the 5 registered Capabilities' `_build_request()`
was individually re-read this session and confirmed to set `response_mode="json_schema"` and
`response_schema=prompt.output_schema` with no exception. `capabilities/registry.py::build_registry()`
re-read directly: exactly 5 `register()` calls, no more, no fewer — `scoring`, `quality`, `research`,
`intelligence`, `copywriting` — matching the plan's claim exactly.

Every one of the 8 schemas is confirmed, by direct read, to be a genuinely flat object — no property
anywhere has `type: object`, no `$defs`/`definitions` block exists in any file, no `oneOf`/`anyOf`/
`allOf` construct exists in any file. The plan's claim that "the fix therefore does not need to
recurse into any currently existing nested object" is accurate for the current repository state.

---

# Versioning Audit

- **Historical published prompt versions remain untouched**: confirmed — the plan lists only new
  `vN+1`/`v3` files, never an edit to `research/v1.yaml`, `intelligence/v1.yaml`, `scoring/v1.yaml`,
  `copywriting/v1.yaml`, or `quality/v1.yaml`/`v2.yaml`. No in-place edit appears anywhere in the
  plan's own text.
- **New version numbers do not collide**: confirmed by direct `Glob` — no `research/v2.yaml`,
  `intelligence/v2.yaml`, `scoring/v2.yaml`, `copywriting/v2.yaml`, `quality/v3.yaml`, or
  `demo_summary/v3.yaml` exists on disk today. All six proposed filenames are genuinely free.
- **`FilePromptRepository` resolves new versions with zero code change**: independently re-traced
  `integrations/prompts/file_repository.py:105-121` — `__init__()` iterates
  `sorted(name_dir.glob("v*.yaml"))` per prompt-name directory at construction time; adding a new
  `vN.yaml` file requires no code change, confirmed directly (not inferred).
- **One-line `PROMPT_VERSION` bumps are sufficient**: confirmed — `resolve(CAPABILITY_NAME,
  PROMPT_VERSION)` is a plain string-keyed lookup; nothing else in any of the five Capability files
  reads or derives from `PROMPT_VERSION`, confirmed by direct read of all five files.
- **Existing tests requiring mechanical version updates**: **the plan under-identifies this by six
  files.** See Findings, MAJOR-1, for the full list and exact mechanism. This is the audit's single
  most important correction.

---

# Strict-Schema Audit

Independently re-checked every schema node, recursively, not just root-level:

- **Root `additionalProperties: false`**: needed and correctly proposed for all 6 live-reachable
  schemas (`scoring`, `quality` v1 — not remediated, correctly, since it's historical/superseded —
  and v2, `research`, `intelligence`, `copywriting`) plus the 2 dormant `demo_summary` files.
- **Nested objects**: none exist in any of the 8 files today (independently re-confirmed by direct
  read of every file, not by trusting the plan's claim) — so no recursive fix is *currently* needed.
  The plan's own required test (recursive traversal) correctly future-proofs against a later prompt
  adding one; this audit confirms that test design is the right mitigation, not a missing one.
- **Array `items`**: three properties need this — `research.facts`, `research.gaps`,
  `copywriting.hashtags`, plus `quality.issues` (both v1 and v2, though only v2's replacement,
  `v3`, is live-remediated) — all four confirmed by direct read to currently lack `items`, all
  correctly identified by the plan.
- **`required`/`properties` alignment**: confirmed unaffected by this fix in every schema — every
  existing schema already lists every `properties` key inside `required` (re-verified by direct
  read of all 8 files); the fix adds keys (`additionalProperties`, `items`) that are siblings of
  `properties`/`required`, not replacements, so this invariant is untouched.
- **No unsupported JSON Schema construct**: confirmed — no `oneOf`/`anyOf`/`allOf`/`$defs`/
  `definitions`/`$ref` appears in any of the 8 files, so no additional OpenAI strict-mode
  constraint beyond `additionalProperties`/`items`/`required` applies to this repository's actual
  content today.

**The plan's proposed schema remediation is sufficient for OpenAI's strict-mode rules as applied
to every schema that currently exists in this repository.** No approval-blocking gap found in this
section.

---

# Observability Audit

Re-traced the exact failure flow independently, not from the plan's or blocker audit's description:

1. `OpenAIAdapter.generate()` (`openai_adapter.py:312-322`) catches `openai.OpenAIError`, calls
   `_translate_exception(exc, self._api_key)`. For a `400`, this builds
   `ProviderPermanentIncompatibleError(_redact(f"openai: bad request (code={code}): {exc.message}",
   api_key))` (`:128-133`). `_redact()` (`:106-116`) strips the literal API key value, any
   `Bearer <token>` pattern, and any `sk-...`-shaped string. **Confirmed independently: the
   sanitized message is fully built and attached to the exception at this point, before
   `FallbackPolicy` ever sees it.**
2. `FallbackPolicy._attempt_candidate()` (`policy.py:196-200`) catches this exact exception type
   and returns `_AttemptOutcome(success=False, response=None,
   failure_class=FailureClass.PERMANENT_INCOMPATIBLE)` — **confirmed: the caught exception object
   itself (and its already-redacted message) is discarded here**, only the enum survives.
3. `_run_sequence()`'s `"fallback"` log line (`:292-301`) logs `attempt_index`,
   `candidate_provider_id`, `candidate_model_id`, `outcome.failure_class.value` — confirmed, no
   message text.
4. On exhaustion (`:323-327`), `AllProvidersFailedError` is raised with a purely templated string
   — confirmed by direct read, zero per-candidate detail.
5. `capabilities/gateway_call.py::_classify_gateway_error()` wraps this as
   `PermanentCapabilityError(str(error))` — confirmed, inherits the same generic string verbatim.

**The plan's claim that a narrow, `FallbackPolicy`-only change is sufficient is confirmed.** Since
`str(exc)` at capture time in `_attempt_candidate()` is exactly the already-redacted message built
at the adapter boundary, no new redaction logic is needed in `policy.py` — re-confirmed directly,
not merely trusted.

**Effect on secrets**: none — the enrichment only re-surfaces a string that was already safe to log
before this fix; `_redact()` itself is untouched by the plan.
**Effect on public exception contracts**: none — `AllProvidersFailedError.__init__(self, message:
str, *, reason: str)` (`errors.py:77-79`, re-read directly) already accepts an arbitrary message
string; no signature change is proposed or needed.
**Effect on existing assertion/equality tests**: none found (see Verified Scope above — all 6
files touching `AllProvidersFailedError` checked directly).
**Effect on fallback classification**: none — `_AttemptOutcome.failure_class` assignment logic is
untouched by the plan; only a new, additional field is proposed.
**Effect on retry/backoff/health-store behavior**: none — the plan's diff touches only the `return`
statements of two existing `except` branches (adding one field to the constructed dataclass) and
two existing log/raise sites (extending an f-string and a dict); no control-flow branch, loop
bound, or `await` point is restructured, confirmed by direct read of the exact functions named.

No unnecessary error-hierarchy redesign was found anywhere in the plan — no new exception class, no
`FailureClass` value change, no `GenerateRequest`/`GenerateResponse`/`CapabilityCall` field change is
proposed.

---

# Milestone Order Audit

M0→M1→M2→M3 is confirmed a genuine hard sequence: M1 (new prompt files) is inert until M2 (constant
bumps) makes them live; M3 (the test) is sequenced after both so it exercises real, already-fixed
content. M4 (Track B) is independently confirmed to have no code or data dependency on M1-M3 —
`FallbackPolicy` and prompt content are unrelated files. M5 (full regression) correctly depends on
all of M1-M4. M6 (live retry) correctly depends on M5 passing clean. No circular dependency found.

**One process gap, not a correctness gap**: the plan's M1→M2→M3 order writes the new mechanical
test (M3) only *after* the fix already landed (M1+M2), so the test is never empirically proven to
fail against the pre-fix schemas — a red-green discipline gap. This does not block safe
implementation (the schema fix's correctness was independently re-verified in this audit's
Strict-Schema Audit section by direct inspection, not by trusting the test), but it means a latent
bug in the new test itself (e.g., checking the wrong dict key) would not be self-evident from the
milestone sequence alone. Flagged as MINOR below, not a blocking defect.

---

# Test Plan Audit

Re-verified each of the 7 required proof points against the plan's actual test design:

1. **Every registered structured-output Capability resolves a strict-compatible schema** — the
   plan's proposed test resolves via the real `FilePromptRepository` against the real `prompts/`
   directory (no fakes), hardcoding the same `(CAPABILITY_NAME, PROMPT_VERSION)` list
   `build_registry()` itself hardcodes — confirmed this mirrors the existing "no dynamic discovery"
   convention (`capabilities/registry.py`'s own docstring, re-read: "No dynamic discovery"). Sound.
2. **Recursive, not root-only** — confirmed the plan's description explicitly requires recursing
   into any `type: object` property; correctly future-proofed per the Strict-Schema Audit above.
3. **`expected_output_keys` alignment** — confirmed this extends, not duplicates, the existing
   Contract §6 convention (`output_schema.required == expected_output_keys`), independently
   re-verified as an existing, already-tested rule in this codebase (Phase 10's own §6, confirmed
   by re-reading `docs/phase10_production_content_pipeline_architecture_contract.md` earlier in
   this engagement's history).
4. **New `PROMPT_VERSION` values resolve successfully** — the plan's own design (resolving via the
   real repository as part of the same test) makes this a byproduct of proof point 1, not a
   separate mechanism; sound.
5. **`FallbackPolicy` preserves sanitized detail** — the plan's proposed assertion (final error
   message contains the last candidate's original exception text) is directly buildable against
   `FakeProviderAdapter`'s existing, deterministic failure messages (re-read
   `tests/fakes/fake_provider_adapter.py:67-79`: `behavior="permanent_incompatible"` raises
   `ProviderPermanentIncompatibleError(f"[{provider_id}/{model_id}] simulated permanent-
   incompatible failure")` — a distinctive, assertable string) with zero new fake infrastructure.
   Confirmed buildable exactly as planned.
6. **Failure classification unchanged** — the plan's own test item 2 explicitly proposes asserting
   this; sound, and independently confirmed the underlying code doesn't change classification
   logic (Observability Audit above).
7. **Fallback/retry semantics unchanged** — the plan's own test item 4 proposes running the
   existing `FallbackPolicy` suite unmodified as the primary no-regression gate; confirmed this
   suite exists (`tests/test_fallback_policy.py`, re-read directly, includes real
   `dispatch()`-through-exhaustion tests) and is a legitimate, sufficient no-regression signal.

**`FakeLLMGateway`/`FakeProviderAdapter`/`FakePromptRepository` permissiveness remains a blind spot
after the new tests — correctly, deliberately, and the plan understands this distinction
correctly.** Re-confirmed directly: `FakeLLMGateway.generate()` never reads `request.response_
schema`; `FakeProviderAdapter.generate()`'s `structured_output` is independent of
`request.response_schema`/`response_mode`; `FakePromptRepository` performs no schema validation.
The new Track A test is a separate, dedicated static-schema check — not a change to any fake's
behavior — exactly the right architectural choice (re-implementing OpenAI's validator inside a
shared fake would conflate two different testing responsibilities).

**Test-scope gap (repeated from Findings for completeness of this section)**: the plan's own test
list does not mention the six existing per-Capability unit-test files whose `FakePromptRepository`
fixtures will need a version-string update once M2 lands. This is a completeness gap in "what tests
are affected," not a gap in "what the new test proves."

---

# Phase 10 Isolation

Confirmed: exactly two of Phase 10's 9 authorized production files are touched by this plan
(`capabilities/quality_capability.py`'s `PROMPT_VERSION`, `capabilities/copywriting_capability.py`'s
`PROMPT_VERSION`) — both are named **explicitly**, not hidden under the "cross-phase remediation"
label. The plan's own text states this plainly twice (Executive Summary: "2 of which are Phase
10's own"; Confirmed Scope: "No Phase 10-authorized file needs a change beyond the two
`PROMPT_VERSION` one-liners already listed above"). No other Phase 10 file
(`workflows/definitions/content_generation.py`, `capabilities/registry.py`,
`schemas/content_draft.py`, `services/content_draft_service.py`,
`scripts/run_content_generation.py`, `prompts/copywriting/v1.yaml`, `prompts/quality/v2.yaml`) is
touched — confirmed by re-reading the plan's own Exact File Scope table in full; none of these
seven appears in it.

**One addition this audit adds, not a contradiction**: the six test-file gap identified above
includes `tests/test_copywriting_capability.py` and (again) `tests/test_quality_capability.py` —
both Phase 10 M1/M2 test artifacts. This does not change the "2 production files" count (test
files were never part of Phase 10's 9-file *production* authorization, and Phase 10's own Contract
never froze its *test* files against future, explicitly-authorized modification) — but it should
be named explicitly in the corrected scope, for the same transparency reason the plan already
applies to the two production files.

No hidden Phase 10 production edit was found beyond what the plan already discloses.

---

# Live Validation Gate

The six listed conditions (Track A test passes, Track B test suite passes, full `pytest` passes,
`ruff` passes, `validate_architecture` passes, git scope reviewed) are individually sound and in a
safe order — no live call is reachable in the plan's own document without all six holding first.

**Gap found**: the gate omits two conditions this audit's own instructions explicitly required
checking for — `mypy` passing on changed code, and a secret/hygiene scan. Every one of Phase 10's
own M1-M4 milestones (re-confirmed by this engagement's own prior session history) treated both as
mandatory pre-live-check gates, including catching a real, non-trivial type mismatch in M3
(`ContentDraft.hashtags`'s `Mapped[dict | None]` vs. the list Phase 10 actually stores) that `ruff`
alone would not have caught. Omitting `mypy` from this plan's gate is a real, if minor and easily
corrected, weakening of gate strictness relative to this repository's own established discipline.

Once corrected (add `mypy`/secret-hygiene as explicit gate items — a documentation addition, not a
new mechanism, since both commands already exist and were already used throughout Phase 10), the
gate is strict enough. The plan's "exactly one smoke + one real CLI run, no repeated retries"
closing instruction is confirmed appropriately conservative and consistent with the live-validation
session's own prior cost-discipline.

---

# Findings

## CRITICAL

None. No unsafe architecture, no data corruption risk, no security issue. The recommended fix
(Option A: versioned prompt files; narrow `FallbackPolicy` field addition) is architecturally sound
and independently re-confirmed against Phase 6 §8's binding prompt-ownership rule.

## MAJOR

1. **Track A's "Exact File Scope" table undercounts affected test files by six.** The plan claims
   exactly one new test file for Track A. Direct `grep -rn 'version="1"' tests/*.py` (cross-checked
   against each affected Capability's `CAPABILITY_NAME`) found six *existing* files whose
   `FakePromptRepository` fixture hardcodes a registration at the version each Capability
   *currently* resolves — every one will raise `KeyError: FakePromptRepository: no prompt
   '<name>' version '<new version>'` the instant M2 bumps that Capability's `PROMPT_VERSION`
   constant, for every test in that file that calls `.execute()`:
   - `tests/test_copywriting_capability.py` (`version="1"`, line 76) — needs `"1"` → `"2"`.
   - `tests/test_research_capability.py` (`version="1"`, line 58) — needs `"1"` → `"2"`.
   - `tests/test_intelligence_capability.py` (`version="1"`, line 68) — needs `"1"` → `"2"`.
   - `tests/test_scoring_capability.py` (`version="1"`, line 56) — needs `"1"` → `"2"`.
   - `tests/test_scoring_capability_retry.py` (`version="1"`, line 40) — needs `"1"` → `"2"`.
   - `tests/test_quality_capability.py` (`version="2"`, confirmed already updated once in Phase 10
     M2 for the `"1"`→`"2"` bump) — needs `"2"` → `"3"` this time.

   This is exactly the same, already-proven, one-line mechanical fix (`_prompt_repository()`'s
   registered `RenderedPrompt.version` string) already applied once for `quality_capability.py`
   during Phase 10 M2 — not a new kind of problem, and not something requiring new judgment to fix.
   **Impact**: the plan's own M5 regression gate (`python -m pytest -q`) would catch this
   immediately and loudly — no silent breakage, no risk of shipping a false pass. This is a
   scope-completeness defect in the planning document itself (Part 9's own "Exact File Scope"
   deliverable is materially wrong — 1 file claimed vs. 6 required), not a safety defect in the
   proposed fix. **Required correction**: add these six files to Track A's file scope and to M2's
   milestone description (each needs its `_prompt_repository()` fixture's registered `version`
   string bumped by one, in the same commit/step as the corresponding `PROMPT_VERSION` change, to
   avoid a broken intermediate state at M5).

## MINOR

1. **Live Validation Gate omits `mypy` and secret/hygiene checks as explicit conditions**, despite
   every Phase 10 milestone treating both as mandatory. Both commands already exist and are already
   proven useful (mypy caught a real type mismatch in Phase 10 M3); this is a one-line addition to
   the gate's checklist, not a new mechanism.
2. **No red-green verification step in the milestone order** (M1→M2→M3 writes the new mechanical
   test only after the fix already lands) — the test's ability to actually detect the class of
   defect it targets is never empirically demonstrated by the milestone sequence itself. Mitigated
   in practice by this audit's own independent, direct verification of the schema fix's
   correctness (Strict-Schema Audit above), but worth a one-sentence addition to M3's description
   recommending the implementer temporarily point the test at the pre-fix version to confirm it
   fails, before applying M1/M2 for real (or, equivalently, run it once against `git stash`ed
   changes).

## OBSERVATIONS

1. The plan's Track B test design (item 3, "no sensitive data appears in the enriched message")
   relies on constructing a synthetic exception with a fabricated `sk-...`-shaped token by hand,
   since `FakeProviderAdapter`'s built-in failure messages don't contain one — the plan's own text
   already correctly frames this as "confirm we didn't break the existing guarantee," not a new
   redaction test; this audit confirms that framing is accurate and does not require a stronger
   test.
2. `demo_summary/v1.yaml`/`v2.yaml`'s remediation remains correctly optional/hygiene-only — no
   registered Capability resolves either version, reconfirmed via the same `grep` this audit ran
   independently.
3. This plan's own confidence in the schema-fix's *live* effectiveness (i.e., that it will actually
   make the real OpenAI API accept the request) remains, correctly, an unconfirmed-until-M6
   prediction — grounded in OpenAI's stable, well-documented Structured Outputs contract, not yet
   empirically re-tested against a live call in this or any prior session (correctly, per every
   session's own scope constraints).

---

# Readiness Score

**8/10** — the core technical diagnosis, architecture-ownership reasoning, and both tracks' proposed
fixes are correct and independently re-verified from source, not merely trusted. The one MAJOR
finding is a real, precisely-identified scope gap in the plan's own file-count claims (not a flaw in
the recommended approach), fully specified by this audit (six named files, one known fix pattern
each) so a future implementing session does not need to re-derive anything — it can be corrected by
appending six lines to the plan's Exact File Scope table and one sentence to M2's description before
implementation begins.

---

# Final Verdict

REMEDIATION PLAN NOT READY — CORRECTIONS REQUIRED
