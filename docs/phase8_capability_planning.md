# Phase 8 — Capability Layer Implementation Roadmap

**Status: implementation plan. Not a specification, not binding.** `docs/phase8_capability_contract.md`
is the single source of truth for every rule this roadmap implements against. This document
sequences that contract into independently reviewable milestones, mirroring the discipline
`docs/phase7_session_handoff.md`/`docs/phase7_implementation_log.md` already established for
Phase 7 — small slices, real infrastructure over fakes wherever practical, a full checkpoint
(tests/ruff/mypy/architecture-validation/runtime-evidence) after every milestone, and no commit
without explicit approval. No code is written in producing this document.

## How this roadmap was derived

Every milestone below traces to a specific, numbered rule in `docs/phase8_capability_contract.md`.
Nothing here invents scope the contract didn't already require, and nothing here resolves an open
question (§19.2's Q1–Q5) the contract left provisional — where a milestone touches one of those,
it implements the *provisional default* and explicitly does not attempt to close the question.

## What already exists (not rebuilt by any milestone below)

- `capabilities/registry.py` — `CapabilityRegistry`, and `build_registry()` with the contract's
  exact four-parameter signature (§5.2). Currently ships empty-sealed; its body is what several
  milestones below extend, never its signature.
- `capabilities/executor.py`, `capabilities/errors.py`, `capabilities/capability_mapping.py` —
  frozen (Phase 6), unmodified by this roadmap.
- `schemas/capability.py`, `schemas/capability_definition.py` — frozen (Phase 6), unmodified.
- `integrations/llm_gateway/` (the entire Phase 7 stack, including `RoutingGateway`,
  `assemble_ai_integration_layer()`, and `ToolRegistry`) — frozen (Phase 7), unmodified.
- `integrations/prompts/protocol.py` — the `PromptRepository` Protocol, frozen. No concrete
  implementation exists yet; building the first one is M2 below.
- `tests/fakes/fake_gateway.py` (`FakeLLMGateway`) and `tests/fakes/fake_capability.py` — already
  exist from Phase 6, reused (not rebuilt) starting at M1.

## Milestone sequence at a glance

| # | Milestone | Contract sections implemented |
|---|---|---|
| M0 | Capability-layer boundary validator rules | §2 |
| M1 | Shared Gateway-call support mechanism | §6.8, §11, §12 |
| M2 | Minimal `PromptRepository` implementation | §7.5, §7.6 |
| M3 | Golden Path: first real `Capability` | §3, §4, §6, §9 |
| M4 | Boot-sequence wiring and end-to-end proof | §5, §14 |
| M5 | Structured-output correction retry | §10 |
| M6 | Testing-convention hardening | §15 |
| M7 | Second `Capability`: extension-model proof | §14 |
| M8 | Cross-cutting regression and Phase 8 checkpoint | §15, §17, §18 |

Tool Integration (§8) is deliberately not scheduled — see "Deliberately not scheduled" at the end.

---

## M0 — Capability-layer boundary validator rules

**Goal**: Encode `docs/phase8_capability_contract.md` §2's forbidden-edges table into
`scripts/validate_architecture.py`, mirroring the precedent Phase 7 M0 already set for its own
contract. This milestone builds nothing a `Capability` will use — it builds the mechanical check
that every later milestone's `Capability` code is validated against.

**Files**:
- `scripts/validate_architecture.py` (modified — new rule entries only, no change to existing
  Phase 6/7 rules)
- `tests/test_validate_architecture.py` (modified — new rule tests, synthetic fixture files only)

**Implementation scope**:
- New validator rules scoped specifically to *Capability implementation files* — not
  `capabilities/registry.py`, `capabilities/executor.py`, `capabilities/errors.py`, or
  `capabilities/capability_mapping.py`, which legitimately reference `BudgetGuard`/`LLMGateway`/
  `ToolRegistry` types at the boundary and must remain exempt (mirroring the existing
  `capability-isolation` rule's own `capabilities/executor.py` exemption precedent).
- Forbid, for capability-implementation files only: `services.budget_guard`, `services.cost_tracker`,
  any `integrations.llm_gateway.cache`/`rate_limit`/`fallback`/`routing` import, any
  `integrations.llm_gateway.providers` import (direct), and any `workflows.*` import — restating
  §2's table mechanically, on top of the provider-SDK/database-session/other-Capability rules the
  existing `capability-isolation` rule already enforces.
- **The specific convention this milestone establishes**: the validator's new `applies_to`
  predicate treats any `.py` file directly under `capabilities/` as a Capability implementation
  file **except** the four already-named infrastructure files —
  `capabilities/registry.py`, `capabilities/executor.py`, `capabilities/errors.py`,
  `capabilities/capability_mapping.py` — and `capabilities/__init__.py`. This is a simple
  exclusion rule over the directory's existing, already-fixed shape, not a new subdirectory or
  file-layout convention: it makes what already exists mechanically checkable, nothing more, and
  introduces no new project-wide organizational pattern.

**Out of scope**: any real `Capability`, `PromptRepository`, or shared helper. No rule changes to
anything already covering Phase 6/7 code. No new subdirectory or file-layout convention beyond
the exclusion rule stated above.

**Tests**: synthetic fixture files (mirroring the existing validator test pattern) proving each
new forbidden import is flagged for a capability-implementation-shaped file and correctly *not*
flagged for `capabilities/registry.py` itself; one additional test asserting the exclusion list
itself — that `applies_to` exempts exactly `{registry.py, executor.py, errors.py,
capability_mapping.py, __init__.py}` and no other file — so a future accidental narrowing or
widening of the exemption is caught by CI rather than discovered later.

**Definition of Done**: `python scripts/validate_architecture.py` remains clean (0 violations) on
the current tree; new synthetic-fixture tests pass, proving the positive case (a file matching
the exclusion rule above is flagged for each new forbidden import), the negative case (each of
the four named infrastructure files is confirmed exempt), and the exclusion-list test itself
(the adopted convention is exactly what the tests assert, not merely what this document
describes).

**Expected commit checkpoint**: `Implement Phase 8 M0: capability-layer boundary validator rules`

**Rollback safety**: Purely additive — new rule entries and new tests only, zero behavior change
to any existing rule or any production file. No later milestone modifies
`scripts/validate_architecture.py` or `tests/test_validate_architecture.py` again, so this
milestone's rollback stays unconditionally clean regardless of what has landed since.

**Verification commands**:
```
python -m pytest -q
python -m ruff check scripts/ tests/
python -m mypy scripts/validate_architecture.py
python scripts/validate_architecture.py
```
(plus a runtime check: running `python scripts/validate_architecture.py` directly against a
small, throwaway fixture tree containing one capability-implementation-shaped file with a
forbidden import and one `capabilities/registry.py`-shaped file with a legitimate one, confirming
the former is flagged and the latter is not — the same style of direct, human-readable runtime
evidence M4 below captures for its own milestone)

---

## M1 — Shared Gateway-call support mechanism

**Goal**: Build the single, centralized mechanism contract §6.8 requires — the one piece of
shared infrastructure every later `Capability` will depend on for `CapabilityCall` bookkeeping
(§6.4, §13.3), observability-metadata stamping (§6.5, §12), and `GatewayError`→`CapabilityError`
translation (§6.7, §11.2–§11.4). Per §19.2 Q1, this milestone MUST make the mechanism exist and
MUST NOT lock in a specific shape (base class vs. composed helpers) beyond what's needed to prove
it correct in isolation — the shape question stays open, to be revisited per Q1 after M3/M7 give
real evidence.

**Files**: one new module (exact path is an implementation detail the contract deliberately
leaves open; this roadmap does not name one), plus its dedicated test file.

**Implementation scope**:
- Given a resolved `GenerateRequest`, `CapabilityContext.runtime`, and the result of one
  `LLMGateway.generate()` call (success or a raised exception), produce one `CapabilityCall`
  matching §6.4/§13.3's shape.
- Stamp `trace_id`/`capability_execution_id`/`request_id` onto every outgoing request, derived
  exactly per Phase 7 §16.1's formula (§6.5, §12.1–§12.3) — no new identifier scheme.
- Classify the four externally observable Gateway exceptions (`NoRoutableCandidateError`,
  `ProviderModerationBlockedError`, `AllProvidersFailedError`, `UnsupportedGatewayCapabilityError`)
  into the correct `CapabilityError` subtype per §11.2, with `ProviderModerationBlockedError`'s
  no-retry handling (§11.3) preserved.

**Out of scope**: any concrete `Capability`, `PromptRepository`, tool-loop logic, or structured-
output retry composition (§10 — a separate, later concern). No decision on base-class-vs-
composition beyond what's needed to ship one working mechanism.

**Tests**:
- `CapabilityCall` sequencing/timing correctness across multiple sequential Gateway calls.
- Observability-metadata stamping matches §16.1's derivation formula exactly, for a
  `FakeLLMGateway` capturing the outgoing request.
- All four externally observable exceptions map to the contract-specified `CapabilityError`
  subtype; `ProviderModerationBlockedError`'s classification is asserted as non-retryable.
- A negative test confirming `ProviderTransientError`/`ProviderPermanentIncompatibleError`/
  `RateLimitExceededError`/`capabilities.errors.BudgetExceededError` are *not* referenced anywhere
  in this mechanism's exception-handling code (guards against reintroducing the corrected
  contract §11.4 misconception).

**Definition of Done**: full test suite above passes against `FakeLLMGateway`; the mechanism has
zero consumers yet (nothing calls it) but is independently, completely verified in isolation.

**Expected commit checkpoint**: `Implement Phase 8 M1: shared Gateway-call support mechanism`

**Rollback safety**: Purely additive, zero consumers at this point in the sequence — reverting
removes an unused module and its tests with no effect on any other code path. This module MAY
later be extended by M5 (if M5's own file-location choice lands the retry logic here rather than
in the M3 capability); clean, isolated rollback of this milestone is guaranteed only up to the
point M5 has made that choice and extended this file.

**Verification commands**:
```
python -m pytest -q
python -m ruff check <new module path> tests/
python -m mypy <new module path>
python scripts/validate_architecture.py
```
(plus a runtime check: constructing the mechanism directly against a `FakeLLMGateway`, making one
`generate()` call, and printing the resulting `CapabilityCall` and the request's stamped
`trace_id`/`capability_execution_id`/`request_id` — confirming the mechanism works standalone
before anything in M3 depends on it)

---

## M2 — Minimal `PromptRepository` implementation

**Goal**: Satisfy contract §7.5/§7.6 — a concrete, minimal, lookup-only `PromptRepository`, since
no `Capability` can be meaningfully exercised outside a test double until one exists.

**Files**: one new module implementing `PromptRepository` (path is an implementation detail, not
named here), a small number of initial prompt-content source files it reads from, and its
dedicated test file.

**Implementation scope**:
- `resolve(name, version=None) -> RenderedPrompt`, side-effect-free, no network call (§7.6).
- A given `(name, version)` resolves to the same `RenderedPrompt` for the life of the deployment —
  enforced by construction (e.g. immutable, versioned source content), not by convention alone.
- `version=None` returns the latest published version, matching the Protocol's own documented
  contract.
- Static, code-reviewed content only — mirrors `ModelRegistry`'s "one explicit, statically-typed
  module" discipline (Phase 7 §3 rule 2's precedent, applied here by analogy, not by contract
  requirement).

**Out of scope**: a Prompt Publisher (authoring workflow, validation gates, promotion — §16.5,
explicitly excluded). No mutating method of any kind. No `Capability` yet consumes this
implementation.

**Tests**:
- `resolve()` determinism: identical `(name, version)` returns an equal `RenderedPrompt` across
  repeated calls.
- Unknown `name`/`version` raises a clear, typed error rather than returning a wrong result.
- `version=None` resolves to the latest published version.
- No test in this suite makes a network call or touches a database (proves §7.6's isolation
  claim, not just asserts it).

**Definition of Done**: implements the `PromptRepository` Protocol completely; all tests above
pass; zero `Capability` dependency exists on it yet.

**Expected commit checkpoint**: `Implement Phase 8 M2: minimal PromptRepository implementation`

**Rollback safety**: Purely additive, standalone, no existing consumer — reverting removes an
unused implementation with no downstream effect. No later milestone modifies this module itself
(M3+ depend only on the `PromptRepository` Protocol, never on this concrete class — a future,
different `PromptRepository` implementation remains swappable in without restructuring any
milestone below), so this rollback stays unconditionally clean regardless of what has landed
since.

**Verification commands**:
```
python -m pytest -q
python -m ruff check <new module path> tests/
python -m mypy <new module path>
python scripts/validate_architecture.py
```
(plus a runtime check: calling `resolve()` twice for the same `(name, version)` and printing both
`RenderedPrompt` values to confirm they are equal, then calling it for an unknown name and
confirming the expected typed error is raised)

---

## M3 — Golden Path: first real `Capability`

**Goal**: Prove the smallest possible real `Capability` slice end to end — `CapabilityContext` in,
one `LLMGateway.generate()` call via the M1 mechanism, prompt resolution via the M2
`PromptRepository`, structured-output validation against the §9.1 floor, one `CapabilityResult`
out — before any second capability or any additional mechanism (tools, retry) is built. Mirrors
Phase 7 M6's own Golden Path precedent exactly: smallest real slice first, real infrastructure
underneath (M1/M2), not a bypass.

Which specific product capability this is (`research`, `scoring`, or another name from the
existing roster in `capabilities/capability_mapping.py`) is a product-scoping choice, not an
architectural one, and is explicitly left to whoever executes this milestone — consistent with
`docs/phase8_capability_discovery.md`'s own deferral of this exact question.

**Files**: one new `Capability` implementation, one new `CapabilityDefinition` registration entry
(not yet wired into `build_registry()` — that is M4), one new prompt entry in M2's repository, and
a dedicated test file.

**Implementation scope**:
- Construction accepts only `LLMGateway` and `PromptRepository` (§4.2) — no `BudgetGuard`, no
  `CostTracker` (§4.3, §4.4).
- `execute()` builds exactly one `GenerateRequest` from `CapabilityContext`, via the M1 mechanism,
  resolves its prompt via the M2 repository, and validates `structured_output` against the §9.1
  floor before returning `status="SUCCESS"`.
- No per-call mutable state (§3.2); behaves identically and independently on repeated invocation
  (§3.4).
- This milestone's `Capability` is text-only. The same shape — `Message`/`ContentPart` in,
  `CapabilityResult` out — already accommodates the multimodal abstractions contract §6.9 confirms
  are sufficient (`ContentPart(type="artifact_ref", ...)`, `GenerateResponse.artifacts`); a future
  multimodal `Capability` follows this exact milestone's template, not a different one.

**Out of scope**: tool usage (§8, not scheduled — see closing section), structured-output
correction retry (§10 — M5), `build_registry()` wiring (M4), a second capability (M7).

**Tests**:
- `execute()` against `FakeLLMGateway` + the real M2 `PromptRepository`, proving the full
  `CapabilityContext -> GenerateRequest -> GenerateResponse -> CapabilityResult` shape.
- A validation-failure case (`FakeLLMGateway` returns output failing the §9.1 floor) raises
  `ValidationCapabilityError`, not a silent `SUCCESS`.
- Construction with only the two permitted dependencies; no test attempts to construct it with a
  `BudgetGuard` (would fail at the type level, per §4.3).
- Repeated `execute()` calls against fresh `CapabilityContext` instances produce independent,
  uncontaminated results (§3.4).

**Definition of Done**: one real, working `Capability` exists, fully tested against fakes, not yet
reachable through `CapabilityExecutor` or the real `RoutingGateway` (that proof is M4's job
specifically, kept separate so this milestone stays reviewable in isolation).

**Expected commit checkpoint**: `Implement Phase 8 M3: golden path Capability`

**Rollback safety**: Additive — a new, unregistered `Capability` implementation with its own
tests. Reverting removes it with no effect on `build_registry()`'s current empty-sealed state.
This milestone's capability file MAY later be extended by M5 (if M5's file-location choice keeps
the retry logic capability-local), and its test file is explicitly reused by M6 (§ "Testing-
convention hardening" formalizes it retroactively); clean, isolated rollback of this milestone is
guaranteed only up to the point either has landed.

**Verification commands**:
```
python -m pytest -q
python -m ruff check <new files>
python -m mypy <new files>
python scripts/validate_architecture.py
```
(plus a runtime check: constructing the capability with `FakeLLMGateway` and the real M2
`PromptRepository`, calling `execute()` with a constructed `CapabilityContext`, and printing the
resulting `CapabilityResult` to confirm the full slice works end to end outside the test runner)

---

## M4 — Boot-sequence wiring and end-to-end proof

**Goal**: Register the M3 `Capability` in `build_registry()` (§5.1, extending its body, never its
frozen signature) and prove it reachable through the complete, real stack:
`CapabilityExecutor -> CapabilityRegistry -> Capability -> LLMGateway (real RoutingGateway,
via assemble_ai_integration_layer()) -> FakeProviderAdapter`. This is the first point at which
Phase 8 code and the frozen Phase 6/7 stack are proven to compose correctly, for real.

**Files**: `capabilities/registry.py` (modified — `build_registry()`'s body only; its
`(gateway, prompt_repository, budget_guard, tool_registry) -> CapabilityRegistry` signature is
unchanged, per §5.2/§16.5), a new end-to-end test file.

**Implementation scope**:
- `build_registry()` constructs the M3 `Capability` with `gateway` and `prompt_repository` from
  its own parameters, registers it, seals the registry. `budget_guard` continues to be accepted
  and continues to be passed to nothing (§5.3, §18 rule 19 — unchanged by this milestone).
- One end-to-end test assembling a real `RoutingGateway` (via `assemble_ai_integration_layer()`,
  Phase 7 M19, unmodified) with a `FakeProviderAdapter` underneath, a real `CapabilityExecutor`,
  and the M3 `Capability` resolved by name — proving the full call chain a real `EditorialTask`
  would traverse.

**Out of scope**: a real provider adapter in this test (a `FakeProviderAdapter` is sufficient and
matches Phase 7's own testing discipline — §15.5); a second capability (M7); tool integration.

**Tests**:
- `build_registry()` still raises `UnknownCapabilityError` for any unregistered name and resolves
  the M3 capability correctly for its registered name.
- A full `CapabilityExecutor.execute(step)` call, through a real `RoutingGateway`, returns the
  expected `structured_output` dict.
- A Gateway-layer failure (a `FakeProviderAdapter` configured to fail) surfaces to
  `CapabilityExecutor` as the correct `workflows.errors` type, proving the full §11 translation
  chain works end to end, not just in M1's isolated unit tests.

**Definition of Done**: the full stack, top to bottom, is proven to compose without any bypass or
shortcut; every test passing at the end of M3 (M0's, M1's, M2's, and M3's own, plus the full
pre-Phase-8 Phase 6/7 suite) still passes unmodified, and the new tests this milestone adds also
pass — a strictly additive, zero-regression result relative to the M3 checkpoint, not tied to any
specific absolute count.

**Expected commit checkpoint**: `Implement Phase 8 M4: boot-sequence wiring and end-to-end proof`

**Rollback safety**: Narrow, revertable change to one function body (`build_registry()`) plus
additive tests. Reverting returns `build_registry()` to its M19 empty-sealed state; no schema, no
migration, no Phase 7 file touched. This guarantee holds only up to the point M7 has also
extended `build_registry()`'s body with a second registration — reverting M4 cleanly in isolation
requires doing so before M7 lands; after M7 lands, reverting M4 alone would also need to account
for M7's registration line.

**Verification commands**:
```
python -m pytest -q
python -m ruff check capabilities/ tests/
python -m mypy capabilities/registry.py
python scripts/validate_architecture.py
```
(plus a runtime check: constructing `assemble_ai_integration_layer()` with a real
`FakeProviderAdapter`-backed provider factory and confirming `capability_registry.resolve(...)`
returns the M3 capability, mirroring how each Phase 7 milestone's own runtime evidence was
captured)

---

## M5 — Structured-output correction retry

**Goal**: Implement the §10 correction-retry path for the M3 (or any) `Capability`: on a schema
mismatch, retry exactly once by appending a correction `Message`, never mutating the original
`RenderedPrompt`, never re-routing to a different model.

**Files**: the M1 shared mechanism (extended, if the retry composition belongs there) or the M3
capability itself (extended, if it stays capability-local) — this milestone decides which, but
either way only additive/narrow changes to already-existing Phase 8 files, never a Phase 6/7 file.
Dedicated test file.

**Implementation scope**:
- On a first schema-validation mismatch, compose and send exactly one correction `Message`
  against the same resolved model (§10.2), recording `retry_reason`/`retried_call_id` in the
  retry's `CapabilityCall.metadata` (§10.3).
- A second consecutive mismatch raises `ValidationCapabilityError`; no third attempt is made
  (§10.4).

**Out of scope**: any capability other than the one this retry logic is proven against in this
milestone; tool integration.

**Tests**:
- First mismatch triggers exactly one retry, with the correction message appended (not replacing)
  the existing message list, and the original `RenderedPrompt` object unmodified.
- The retry's `CapabilityCall.metadata` carries the exact `retry_reason`/`retried_call_id` shape
  §10.3 specifies.
- A second consecutive mismatch raises `ValidationCapabilityError` and makes no third Gateway
  call.
- A `FakeLLMGateway` configured to succeed on the retry proves the full corrected path returns
  `status="SUCCESS"`.

**Definition of Done**: all tests above pass; the existing M3/M4 tests remain green (no
regression to the non-retry path).

**Expected commit checkpoint**: `Implement Phase 8 M5: structured-output correction retry`

**Rollback safety**: Additive/narrow — extends existing Phase 8 code only. Reverting removes the
retry path; the M3 capability's non-retry behavior is unaffected either way.

**Verification commands**:
```
python -m pytest -q
python -m ruff check capabilities/ tests/
python -m mypy capabilities/
python scripts/validate_architecture.py
```
(plus a runtime check: constructing the M3 capability with a `FakeLLMGateway` seeded to return one
schema-mismatched response followed by one valid response, calling `execute()`, and printing the
resulting `CapabilityResult` plus the retry `CapabilityCall.metadata` to confirm the corrected
path actually runs end to end outside the test runner)

---

## M6 — Testing-convention hardening

**Goal**: Convert contract §15's testing-philosophy rules into a reusable, shared testing
convention for every subsequent `Capability` — formalizing what M3–M5 already did ad hoc into a
consistent, documented pattern later milestones (and later, independent engineers) reuse without
re-deriving it.

**Files**: shared test fixtures (extending or formalizing the existing `tests/fakes/fake_gateway.py`/
`tests/fakes/fake_capability.py` pattern, plus a fake `PromptRepository` fixture if M2's real
implementation doesn't already make one trivial to construct for tests).

**Implementation scope**:
- A reusable, deterministic fake `LLMGateway` fixture (§15.2) and fake `PromptRepository` fixture
  (§15.3), available to every future `Capability`'s tests without duplicating construction logic.
- One golden-path-style regression test per registered `Capability` (§15.7), formalized as a
  documented pattern — applied retroactively to M3's capability if not already in that shape.
- A checked confirmation that no test in the standard suite makes a real network call (§15.5),
  matching the same discipline already proven for Phase 7's own suite.

**Out of scope**: any new `Capability`; any change to M0–M5's already-shipped behavior beyond
formalizing its test structure.

**Tests**: this milestone's "tests" are the testing convention itself — verified by confirming
the fixtures work correctly for the M3 capability's existing test suite when swapped in, and that
the full suite still passes with zero real network calls.

**Definition of Done**: shared fixtures exist, are used by at least the M3 capability's tests, and
the pattern is ready for M7's second capability to reuse without rebuilding anything.

**Expected commit checkpoint**: `Implement Phase 8 M6: testing-convention hardening`

**Rollback safety**: Purely additive test-infrastructure change; no production code touched.

**Verification commands**:
```
python -m pytest -q
python -m ruff check tests/
python -m mypy tests/fakes/
python scripts/validate_architecture.py
```
(plus a runtime check: importing the formalized fixtures directly, constructing the M3 capability
through them instead of its milestone-local setup, and printing the resulting `CapabilityResult`
to confirm the shared fixtures reproduce the same working slice before M7 is asked to reuse them)

---

## M7 — Second `Capability`: extension-model proof

**Goal**: Prove contract §14's zero-change extension guarantee for real, not just structurally —
add a second, genuinely different `Capability` (different prompt, different output shape) using
only the M6 testing convention, and confirm zero modification to the M3 capability, to
`workflows/`, to `LLMGateway`, or to `PromptRepository`'s own contract.

**Files**: one new `Capability` implementation, one new `CapabilityDefinition`, one new prompt
entry, one new registration line in `build_registry()`, one new test file. No existing file from
M0–M6 is modified except `capabilities/registry.py`'s registration list.

**Implementation scope**: identical shape to M3/M4, applied to a second, distinct capability.

**Out of scope**: any change to the M3 capability's own behavior; tool integration.

**Tests**: mirrors M3/M4's test shape for the new capability, plus one explicit test proving both
capabilities coexist correctly in the same sealed `CapabilityRegistry` (each resolves to the
correct implementation by name, neither interferes with the other).

**Definition of Done**: two independently-working capabilities registered and passing, with a
`git diff` against the M6 checkpoint touching only new files plus `build_registry()`'s
registration list — the concrete, verifiable form of §14's guarantee.

**Expected commit checkpoint**: `Implement Phase 8 M7: second Capability, extension-model proof`

**Rollback safety**: Additive plus one narrow registration-list addition to `build_registry()`;
reverting removes the second capability with zero effect on the first.

**Verification commands**:
```
python -m pytest -q
python -m ruff check capabilities/ tests/
python -m mypy capabilities/
python scripts/validate_architecture.py
```
(plus a runtime check: resolving both the M3 and the new capability from the same constructed
`CapabilityRegistry` by name and printing each resolved implementation's identity, confirming
neither shadows or interferes with the other's registration)

---

## M8 — Cross-cutting regression and Phase 8 checkpoint

**Goal**: The Phase 8 equivalent of Phase 7 M20 — a final, cross-cutting validation pass proving
the whole Capability Layer (M0–M7 combined) is internally consistent, fully tested, and has
introduced zero regression to the frozen Phase 6/7 stack beneath it.

**Files**: none new, beyond a final cross-cutting test file exercising both M3 and M7 capabilities
through the real end-to-end path M4 established.

**Implementation scope**:
- Full test suite re-run, confirming the pre-Phase-8 baseline count still passes unmodified.
- A single test proving both registered capabilities are reachable through
  `assemble_ai_integration_layer()`'s real boot sequence in one process.
- A review pass confirming every §15 (Testing Requirements) rule holds across the accumulated
  M0–M7 test suite, not just each milestone's own tests in isolation.

**Out of scope**: any new `Capability`, any new mechanism, any resolution of §19.2's open items
(Q1, Q3, Q4 remain provisional, exactly as the contract specifies).

**Tests**: as described above — this milestone adds a small number of genuinely cross-cutting
tests, not a new feature.

**Definition of Done**: full suite green, architecture validation clean, no regression anywhere
in the frozen Phase 6/7 test suite, both capabilities provably coexisting in one real boot.

**Expected commit checkpoint**: `Implement Phase 8 M8: cross-cutting regression checkpoint`

**Rollback safety**: Additive test-only change; nothing to roll back beyond the tests themselves.

**Verification commands**:
```
python -m pytest -q
python -m ruff check capabilities/ integrations/ services/ tests/ scripts/
python -m mypy capabilities/ integrations/llm_gateway/
python scripts/validate_architecture.py
```
(plus a runtime check: booting `assemble_ai_integration_layer()` once with a
`FakeProviderAdapter`-backed provider factory and, in that single process, resolving and executing
both the M3 and the M7 capability in turn, printing both `CapabilityResult`s to confirm the whole
layer composes as one real system rather than as isolated per-milestone slices)

---

## Deliberately not scheduled

- **Tool Integration (contract §8)**: no milestone above builds a tool-using `Capability` or
  exercises `ToolRegistry` for real. Building this without a concrete, named tool need would be
  speculative — exactly the kind of premature build-out this roadmap otherwise avoids. When a
  real tool-using capability is scoped, it becomes its own milestone, inserted after M7, following
  the identical Goal/Files/Scope/Tests/DoD/Checkpoint/Rollback/Verification shape every milestone
  above already uses.
- **§19.2's open items (Q1, Q3, Q4)**: this roadmap implements each one's provisional default
  (a shared M1 mechanism of unspecified shape; unconstrained per-capability validation strategy
  beyond the §9.1 floor; M2's file-based `PromptRepository`) without attempting to close any of
  them. Per the contract's own instruction, Q1 specifically should be revisited only after M3 and
  M7 give real evidence of how much boilerplate is genuinely shared — not before.
- **A third or later `Capability`**: M7 proves the extension model once; repeating it a further
  28–48 times (per Phase 6 §6's own 30–50-capability scale target) is expected future work, not
  additional roadmap design — each one follows M7's exact shape.

---

*End of roadmap. Every milestone above is independently reviewable and independently revertable;
none depends on a later milestone's code, only on earlier ones already having landed.*
