# OpenAI Structured Outputs Strict-Schema Blocker — Root Cause & Remediation Audit

**Status: audit/planning document only.** No production code, prompt, test, or architecture
contract was modified to produce this document. No live API call was made. This document
independently re-verifies, and in one respect corrects, the hypothesis recorded in
`docs/phase10_live_production_validation.md`.

---

# Executive Summary

The real, live Phase 10 CLI run failed at the `research` step with an OpenAI `400 Bad Request`.
Direct code inspection confirms a deterministic, repository-wide defect:
`integrations/llm_gateway/providers/openai_adapter.py::_build_payload()` unconditionally sets
`"strict": True` on every structured-output request, but **none of the 8 prompt YAML files in this
repository** (`demo_summary` v1/v2, `scoring` v1, `quality` v1/v2, `research` v1, `intelligence`
v1, `copywriting` v1) declare `"additionalProperties": false`, which OpenAI's Structured Outputs
API requires under `strict: true`. All 5 real, registered Capabilities (`scoring`, `quality`,
`research`, `intelligence`, `copywriting`) use `response_mode="json_schema"` with
`response_schema=prompt.output_schema` — every one of them is affected identically. This is a
pre-existing, cross-phase defect (Phase 6 prompt-authoring convention × Phase 7 adapter
implementation), not something Phase 10 introduced, and it was undetectable by any existing
automated test because every fake provider/gateway in this codebase unconditionally ignores
`response_schema` and returns whatever fixed `structured_output` it was configured with — no fake
anywhere in this repository ever validates a request against OpenAI's real schema rules. **One
important correction to the prior session's hypothesis**: the *exact* OpenAI validation error text
was never actually captured anywhere in this repository's logs or database — `FallbackPolicy.
_attempt_candidate()` discards the underlying exception's message entirely on a
`ProviderPermanentIncompatibleError`, keeping only a coarse `failure_class`. The root cause below
is therefore a very high-confidence hypothesis grounded in deterministic code inspection and
OpenAI's own stable, extensively documented Structured Outputs contract — not an empirically
observed literal error string. The recommended fix (adding `additionalProperties: false` to every
prompt's `output_schema`, plus one new mechanical test) is small, entirely YAML+test-file scoped,
touches zero Python production files, and requires no migration and no architecture change.

---

# Failure Reconstruction

Traced `OpenAIAdapter.generate()` → `_build_payload()` → the exact dict passed to
`self._client.responses.create(**payload)` (`openai_adapter.py:312-317`):

1. `model_id` resolved from `request.metadata["resolved_model_id"]` (set by `FallbackPolicy`
   before dispatch).
2. `payload["input"]` built from `request.messages` via `_translate_message()`/
   `_translate_content_part()` — unaffected by this defect.
3. Because the `research` Capability's `_build_request()` sets
   `response_mode="json_schema"` and `response_schema=prompt.output_schema`
   (`capabilities/research_capability.py:111-112`), `_build_payload()`'s final branch fires
   unconditionally (`openai_adapter.py:229-237`):
   ```python
   payload["text"] = {
       "format": {
           "type": "json_schema",
           "name": "structured_output",
           "schema": request.response_schema,   # = prompts/research/v1.yaml's output_schema, verbatim
           "strict": True,
       }
   }
   ```
4. `request.response_schema` at this point is exactly `prompts/research/v1.yaml`'s
   `output_schema` as loaded, byte-for-byte, by `FilePromptRepository` (which performs zero
   transformation — confirmed by direct read of `integrations/prompts/file_repository.py`):
   ```json
   {
     "type": "object",
     "properties": {
       "facts": {"type": "array"},
       "confidence": {"type": "number"},
       "gaps": {"type": "array"}
     },
     "required": ["facts", "confidence", "gaps"]
   }
   ```
5. This exact object, wrapped in `strict: true`, was sent to `POST
   https://api.openai.com/v1/responses`. No secret appears anywhere in this payload or in this
   trace.

No secret was printed or handled in reconstructing this.

---

# Confirmed Root Cause

**High-confidence, code-verified hypothesis** (see the honesty note below — the literal OpenAI
error text was never captured anywhere in this repository, for a separate, real reason documented
under Findings):

`_build_payload()` sets `"strict": True` **unconditionally**, with no per-request override and no
settings-gated toggle anywhere in this codebase (grep for `strict` in `openai_adapter.py` finds
exactly two occurrences: the `text.format.strict: True` above, and `_translate_tool()`'s own
`"strict": False` for function-tool definitions — an existing asymmetry, not itself a defect, just
worth noting).

OpenAI's Structured Outputs feature, when `strict: true`, requires (per OpenAI's stable, published
API contract) that **every object node in the schema** — the root and any nested object —
declare `"additionalProperties": false`, and that every key in `properties` appear in `required`.
None of this repository's prompt schemas declare `additionalProperties` anywhere:

```
grep -rn "additionalProperties" prompts/**/*.yaml   ->  (zero matches, all 8 files)
```

Every one of the 8 prompt schemas is a **flat** object (no property has `type: object` nested
inside it), so the fix does not need to recurse into nested objects for any *currently existing*
schema — but the fix must still be written to be recursion-safe for any future prompt that does
add a nested object, since OpenAI's rule is inherently recursive.

**A second, related, unconfirmed-but-plausible compliance gap**: none of the `type: array`
properties (`research.facts`/`gaps`, `copywriting.hashtags`, `quality.issues`) declare an `items`
sub-schema at all (e.g. `facts: {type: array}` with no `items` key). OpenAI's Structured Outputs
strict mode is documented to require array schemas to fully specify their `items` type as well.
This was **not independently confirmed against a live call** in this session (forbidden by scope),
but it is architecturally the same class of gap as the `additionalProperties` omission and should
be fixed in the same pass rather than discovered in a second failed live-validation attempt.

**All 5 real Capabilities are affected identically** — confirmed by grep, not by capability-by-
capability manual inspection alone:
```
grep -n "response_mode\|response_schema" capabilities/*.py
```
returns the identical two-line pattern (`response_mode="json_schema"`,
`response_schema=prompt.output_schema`) for `scoring_capability.py`, `quality_capability.py`,
`research_capability.py`, `intelligence_capability.py`, `copywriting_capability.py` — no
exceptions, no capability opts out of structured mode.

---

# Affected Prompt Matrix

| Prompt | Version | Used by capability | Structured output? | Strict mode? | Schema compliant? | Affected? |
|---|---|---|---|---|---|---|
| `scoring` | 1 | `ScoringCapability` (registered) | Yes | Yes (unconditional) | No — missing `additionalProperties: false` | **Yes** |
| `quality` | 1 | `QualityCapability`'s prior default (superseded, still independently resolvable) | Yes | Yes | No | **Yes** (would fail identically if resolved) |
| `quality` | 2 | `QualityCapability` (registered, current default) | Yes | Yes | No | **Yes** |
| `research` | 1 | `ResearchCapability` (registered) | Yes | Yes | No | **Yes — this is the exact schema that produced the observed 400** |
| `intelligence` | 1 | `IntelligenceCapability` (registered) | Yes | Yes | No | **Yes** |
| `copywriting` | 1 | `CopywritingCapability` (registered) | Yes | Yes | No | **Yes** |
| `demo_summary` | 1 | none — no Capability is registered under this name (own docstring: "no Capability is registered under this name and none depends on this content") | N/A (never actually sent to a real Gateway in production) | N/A | No (same gap, latent) | **Dormant** — same defect if ever wired to a real Capability, but not currently exercised by any registered code path |
| `demo_summary` | 2 | none (same as above) | N/A | N/A | No (same gap, latent) | **Dormant** |

**Every currently-registered, production-reachable Capability (5 of 5) is affected.** The two
`demo_summary` versions carry the identical latent defect but are not reachable through any
registered `CapabilityRegistry` entry, so they are not currently blocking anything live.

---

# Architectural Ownership

**Option A — Add `additionalProperties: false` (and `items` where needed) to every prompt YAML.**
- Correctness: fixes the actual, root cause directly at the artifact OpenAI validates against.
- Blast radius: 6 files with real, live impact (`scoring/v1`, `quality/v1`, `quality/v2`,
  `research/v1`, `intelligence/v1`, `copywriting/v1`), 2 more for full repository hygiene
  (`demo_summary/v1`, `demo_summary/v2`).
- Coupling: none introduced — YAML remains the sole content authority, exactly as Phase 6 §8
  requires ("prompt content... is authored and versioned as files under `prompts/`, outside
  Python").
- Risk: very low — a pure additive schema-completeness fix; `_floor_validate()` (every
  Capability's own runtime validation) already only checks `required` keys and declared types, and
  is unaffected by `additionalProperties`/`items` additions.
- Backwards compatibility: fully preserved — `_floor_validate()`'s behavior is identical before and
  after; `PromptRepository.resolve()`'s "same (name, version) resolves to the same `RenderedPrompt`
  forever" invariant is not violated by this class of change any differently than any other prompt
  edit already is (each edit still requires a **new version file**, per Phase 6 §8's immutability
  rule — this is a content-authoring correction, not a runtime behavior change).
- Testability: trivially testable with a static, mechanical, no-network test (see Required Tests).
- Does it hide invalid prompt contracts? **No — the opposite.** It forces every prompt's contract to
  become fully, explicitly specified, which is a strictly more complete, more honest artifact than
  today's.
- Architecture change: none. No frozen contract's ownership boundary is touched.

**Option B — Normalize/inject the missing keys inside `OpenAIAdapter` before sending.**
- Correctness: would also fix the live symptom.
- Blast radius: one file (`openai_adapter.py`), but conceptually reaches every prompt without
  ever showing the fix in the artifact that's supposed to be authoritative.
- Coupling: low (self-contained inside the adapter's own existing request-translation logic,
  analogous to `_translate_tool()`'s own OpenAI-specific `"strict": False` injection).
- Risk: **this is where the real risk lives** — the adapter would be silently sending a
  *different* schema to OpenAI than the one recorded in `RenderedPrompt.output_schema` (which
  `_floor_validate()` and any human reading the YAML would still see as "missing
  `additionalProperties`"), creating a permanent, silent divergence between "what the prompt
  author wrote" and "what actually gets enforced by the provider." A future prompt author reading
  the YAML would have no visible signal that this transformation exists unless they also read
  `openai_adapter.py`.
- Testability: still testable, but the test would need to assert on the adapter's *transformed*
  payload, one layer removed from the artifact a prompt author actually edits — a weaker signal for
  the person who should fix it.
- Does it hide invalid prompt contracts? **Yes, materially.** This is exactly Part 5's concern.
- Architecture change: does not violate any *written* rule (the adapter already translates
  provider-specific idiosyncrasies), but is in tension with Phase 6 §8's spirit that prompt content,
  including its output schema, is authored "outside Python" and is the thing tests/audits should be
  able to trust by reading the YAML alone.

**Option C — Normalize/enforce inside `PromptRepository`/`FilePromptRepository`.**
- **Explicitly forbidden by the frozen Phase 6 Contract.** §8 states, verbatim: *"`PromptRepository`
  is a **pure lookup contract** over already-published prompt artifacts. It owns nothing about how
  a prompt is authored, tested, or promoted"* and *"Validation (schema conformance, prompt-quality
  gates) happens in the Prompt Publisher, at publish time — never inside `PromptRepository.
  resolve()`."* Injecting or mutating schema content inside `resolve()` would be exactly the kind
  of validation/mutation this binding rule prohibits. **Ruled out on architectural-ownership
  grounds alone**, independent of any correctness concern.

**Option D — Disable `strict=true` entirely.**
- Correctness: would eliminate the 400 error, but by weakening OpenAI's own enforcement rather
  than fixing the schema — the underlying prompt contracts remain incomplete/non-compliant, just
  never checked by OpenAI.
- Blast radius: exactly one line, one file (`openai_adapter.py`), zero prompt files touched.
- Risk: low in one specific sense worth naming precisely — every Capability's own
  `_floor_validate()` (required-key + declared-type check) already runs independently on every
  response regardless of whether OpenAI's own strict mode is active, so a malformed/incomplete
  response would still be caught and correctly raise `ValidationCapabilityError` even with
  `strict: False`. This means Option D would not silently degrade the *observable* correctness
  guarantee this repository's own code already independently enforces.
- Backwards compatibility: preserved.
- Testability: trivial (one assertion that the payload always carries `strict: False`).
- Does it hide invalid prompt contracts? **Yes** — it makes the underlying schema-incompleteness
  permanently invisible to both OpenAI and to any future prompt author, since nothing will ever
  again surface it as an error. It is a real fix for the *symptom*, not the *cause*.
- Architecture change: none structurally, but it is a behavior-changing decision (weakening a
  previously deliberate choice — `strict: True` was written intentionally, not accidentally, per
  the adapter's own extensive "verified against live OpenAI SDK source" docstring) that deserves a
  human decision, not a silent flip.

**Option E — other minimal repository-native solution**: none identified beyond A-D that is
meaningfully different in kind. A hybrid (Option A now, Option D never) is not needed since A alone
fully resolves the defect without trade-offs.

---

# Source of Truth

Confirmed directly (`docs/phase6_architecture_contract.md` §8, quoted above): prompt *content* —
explicitly including "output schema" — is the authoritative, Python-external artifact.
`PromptRepository` (and, by clear extension of the same rule's spirit, any component reading its
output) is meant to be a passive, side-effect-free lookup over exactly what was authored. Silently
mutating or injecting schema fields inside `OpenAIAdapter` (Option B) or `FilePromptRepository`
(Option C, separately already forbidden outright) would mean the schema `_floor_validate()`
validates against, the schema a human reads in the YAML, and the schema OpenAI actually enforces
would be three different things whenever they matter most — exactly the kind of silent divergence
Phase 6 §8's ownership rule exists to prevent. **Option A is the only option that keeps all three
in agreement.**

---

# Fix Options Considered

(See Architectural Ownership above for the full per-option analysis. Summary ranking: **A is
correct and recommended. D is a legitimate, smaller, but symptom-only alternative. B is workable
but architecturally worse than A for no compensating benefit. C is contractually forbidden.**)

---

# Recommended Minimal Fix

**Option A: add `additionalProperties: false` to every `output_schema` object node, and add an
explicit `items` sub-schema to every `type: array` property, in every prompt YAML file currently
used by a registered Capability.**

**Exact files needing a content change** (6 files with live impact; 2 more for full-repository
consistency, not currently live-blocking):
- `prompts/scoring/v1.yaml`
- `prompts/quality/v1.yaml`
- `prompts/quality/v2.yaml`
- `prompts/research/v1.yaml`
- `prompts/intelligence/v1.yaml`
- `prompts/copywriting/v1.yaml`
- `prompts/demo_summary/v1.yaml` (dormant, but should not be left as a latent trap)
- `prompts/demo_summary/v2.yaml` (same)

**Exact nature of each change** — for every file above, add one line at the root
`output_schema` object:
```yaml
output_schema:
  type: object
  additionalProperties: false      # <- new
  properties:
    ...
```
and, for every property whose `type: array`, add an `items` sub-schema matching that array's actual
element type (e.g. `research/v1.yaml`'s `facts`/`gaps` and `copywriting/v1.yaml`'s `hashtags` all
hold strings, so `items: {type: string}`; `quality/v1.yaml`/`v2.yaml`'s `issues` likewise). This is
a content-only change to already-existing prompt files — but note Phase 6 §8's own binding
immutability rule: *"A given (name, version) MUST resolve to the same `RenderedPrompt` forever."*
This means the correct, contract-compliant way to ship this fix is **not** to edit
`research/v1.yaml`/`quality/v1.yaml`/etc. in place, but to **publish a new version of each affected
prompt** (`research/v2.yaml`, `scoring/v2.yaml`, `intelligence/v2.yaml`, `copywriting/v2.yaml`,
`quality/v3.yaml`, `demo_summary/v3.yaml`) with the corrected schema, and bump each affected
Capability's own `PROMPT_VERSION` constant to point at it — mirroring exactly the precedent Phase
10 M2 itself already established for `QualityCapability`'s `v1` → `v2` migration. The old versions
remain on disk, unmodified, forever resolvable, exactly as Phase 6 §8 and Phase 10's own precedent
require.

**Phase 10 vs. cross-phase**: this is a **cross-phase infrastructure correction**, not a Phase 10
correction. `openai_adapter.py` is unmodified Phase 7 code; `research`/`intelligence`/`scoring`/
`quality-v1` predate Phase 10 (Phase 6/8/9). Only `quality-v2`/`copywriting-v1` are Phase 10's own
artifacts, and they inherited the identical, pre-existing gap rather than introducing a new one.
Whichever future session performs this fix will need a **new, narrow contract amendment or a small
follow-up contract** (not a Phase 10 Contract change, since Phase 10 is frozen and this fix reaches
into Phase 6/8/9 territory) explicitly authorizing: (a) publishing one new prompt version per
affected Capability, (b) bumping each Capability's `PROMPT_VERSION` constant by one line, and (c)
adding the mechanical strict-schema test named below. No other file needs to change.

**Migration**: none needed — this is prompt-YAML content plus a one-line Python constant per
Capability; nothing touches the database.

**Architecture changes**: none — no Protocol shape, no Capability contract, no Gateway routing
logic, no frozen boundary is touched. This is squarely a content-correctness fix within the already
existing, already-frozen prompt-versioning mechanism.

---

# Exact Authorized File Scope Needed

For the future session that implements this (not this session):
- **New files**: `prompts/research/v2.yaml`, `prompts/intelligence/v2.yaml`,
  `prompts/scoring/v2.yaml`, `prompts/copywriting/v2.yaml`, `prompts/quality/v3.yaml`,
  `prompts/demo_summary/v3.yaml` (6 new prompt version files).
- **Existing files to edit, narrowly** (one line each — the `PROMPT_VERSION` constant only):
  `capabilities/research_capability.py`, `capabilities/intelligence_capability.py`,
  `capabilities/scoring_capability.py`, `capabilities/copywriting_capability.py`,
  `capabilities/quality_capability.py`.
- **New test file**: one mechanical, static, no-network test file (see Required Tests) —
  e.g. `tests/test_openai_strict_schema_compliance.py`.
- **No other production file.** No migration. No architecture contract change beyond whatever
  small, explicit authorization document a future session produces to open this cross-phase scope
  (this audit itself does not constitute that authorization — it only specifies the fix precisely
  enough for a future, explicitly authorized session to implement it directly).

---

# Required Tests

**Why existing tests (707/707 passing) missed this — confirmed by direct inspection, not
inference:**
- `tests/fakes/fake_gateway.py::FakeLLMGateway.generate()` returns a fixed, pre-configured
  `GenerateResponse` unconditionally — it never reads `request.response_schema` at all.
- `tests/fakes/fake_provider_adapter.py::FakeProviderAdapter.generate()` is identical in this
  respect: `structured_output` is whatever was passed to its constructor, entirely independent of
  `request.response_schema`/`request.response_mode`.
- `tests/fakes/fake_prompt_repository.py::FakePromptRepository` is a pure in-memory lookup with no
  schema validation of any kind, by design (mirrors `FilePromptRepository`'s own "resolve() is a
  pure lookup" contract).

None of this is a defect in the fakes — their entire purpose (Phase 8 §15.1-§15.4's own stated
convention) is to provide fast, deterministic, network-free unit tests for Capability *logic*, not
provider wire-format compliance. **This class of defect is structurally undetectable by any
fake-based test, no matter how the fakes are extended** — a fake that validated OpenAI's exact
strict-mode rules would just be reimplementing OpenAI's own validator inside a fake, which is
better done once, directly, as its own dedicated static check, not folded into `FakeLLMGateway`'s
unrelated routing/retry-testing responsibilities.

**Minimum test needed**, written to make zero network calls: a static, mechanical test that loads
every prompt YAML `FilePromptRepository` would load in production (`prompts/` directory, real
files, exactly as `test_phase9_capability_registration.py` and others already do) and asserts,
recursively, for every object node in every `output_schema`:
1. `"additionalProperties" in schema and schema["additionalProperties"] is False`.
2. Every key in `schema.get("properties", {})` appears in `schema.get("required", [])`.
3. (Recommended, addressing the second gap found above) every `type: array` property declares an
   `items` sub-schema.

This mirrors the exact convention Phase 10's own Contract §6 already established for a related,
narrower check (`output_schema.required` must equal `expected_output_keys`) — extending that same
"mechanically verify every prompt file against a fixed rule" pattern to OpenAI's specific
strict-mode contract, rather than inventing a new testing philosophy.

---

# Phase 10 Impact

- **Is Phase 10's own implementation (M1-M4) defective?** No. `capabilities/copywriting_capability.py`,
  `capabilities/quality_capability.py`'s amendment, `services/content_draft_service.py`,
  `scripts/run_content_generation.py`, and every other Phase 10 file behave exactly as designed —
  `run_content_generation_for_event()` correctly detected `result.status != "COMPLETED"`, correctly
  logged `content_generation_task_failed`, and correctly never attempted `ContentDraft` persistence.
  Every layer Phase 10 actually owns worked precisely as verified by the 707/707 automated
  regression and the Final Implementation Verification.
- **Is this entirely inherited from pre-existing infrastructure?** Yes — `openai_adapter.py` (Phase
  7) and the `research`/`intelligence`/`scoring`/`quality-v1` prompt-authoring gap (Phase 6/8/9)
  predate Phase 10 by definition. Phase 10's own new artifacts (`quality-v2`, `copywriting-v1`)
  inherited the identical convention rather than introducing a new mistake.
  `prompts/copywriting/v1.yaml`'s schema is exactly as non-compliant as every prompt that came
  before it, in exactly the same, uniform way.
  Comparing implementation dates: Phase 6/7 (this codebase's own numbering) predate Phase 10;
  Phase 10 simply never had the file-scope authorization to touch `openai_adapter.py` or any
  pre-Phase-10 prompt file, so it could not have introduced or fixed this even if it had been
  noticed during implementation.
- **Should Phase 10 remain blocked on live validation?** Yes, as a strict logical consequence — no
  Capability in the entire repository can currently complete a real, structured-output OpenAI call,
  so Phase 10's own live-validation Definition-of-Done item cannot pass until this cross-phase issue
  is fixed, regardless of anything Phase 10 itself could change.
- **Does any Phase 10 file need modification to fix this?** Yes, narrowly — `capabilities/
  copywriting_capability.py`'s `PROMPT_VERSION` and `capabilities/quality_capability.py`'s
  `PROMPT_VERSION` are two of the five one-line edits needed (since Copywriting and the amended
  Quality are both affected Capabilities), plus two new prompt version files
  (`prompts/copywriting/v2.yaml`, `prompts/quality/v3.yaml`). The other three affected files
  (`research`, `intelligence`, `scoring`) sit entirely outside Phase 10's own authorized scope and
  belong to earlier phases.
- **Retry live validation as-is, or fix first?** Fix first. Retrying `scripts/
  run_content_generation.py` today, unchanged, would deterministically reproduce the identical `400
  Bad Request` at the `research` step every single time — `research` runs first in the chain and is
  affected identically to every other Capability. No amount of retrying changes this outcome.

---

# Findings

**CRITICAL** — none. No data corruption, no security issue, no unsafe architecture. The
architecture itself (Capability pattern, prompt-ownership rule, Gateway/adapter translation
boundary) is sound; only a content-completeness gap in the prompt artifacts plus one unconditional
adapter setting are implicated.

**MAJOR**:
1. **Every currently-registered Capability (5 of 5: scoring, quality, research, intelligence,
   copywriting) cannot complete a real OpenAI structured-output call today** — `strict: true` is
   unconditional in `openai_adapter.py`, and zero prompt schemas in this repository declare
   `additionalProperties: false`. This makes the entire AI Integration Layer non-functional against
   the real OpenAI API for any structured-output request, blocking Phase 10's live-validation
   Definition-of-Done item and, by extension, any other phase's future live use of these same
   Capabilities.
2. **The specific OpenAI rejection reason is silently discarded by `FallbackPolicy._attempt_
   candidate()`** (`integrations/llm_gateway/fallback/policy.py`) — on `ProviderPermanentIncompatibleError`,
   only a coarse `failure_class` enum value is kept; the actual exception message (which would have
   contained OpenAI's own precise validation error text) is never logged, never stored in
   `WorkflowStepResult.error`, and is unrecoverable after the fact. This materially slowed this
   audit's own diagnosis and would equally hamper any future operator debugging a real provider
   rejection of any kind (not just this one) — a genuine observability gap in Phase 7's own
   frozen `FallbackPolicy`, independent of and additional to the schema defect itself.

**MINOR**:
1. `type: array` properties across every prompt schema lack an `items` sub-schema — plausibly a
   second OpenAI strict-mode compliance gap, not independently confirmed via a live call in this
   session (correctly, per scope), but architecturally the same class of defect and should be fixed
   in the same pass to avoid discovering it in a second failed live-validation attempt.
2. This audit's root-cause conclusion is a very high-confidence code-and-documentation-based
   hypothesis, not an empirically observed exact OpenAI error string — a direct consequence of
   MAJOR finding 2 above, not a weakness in this audit's method.

**OBSERVATIONS**:
1. `_translate_tool()` already sets `"strict": False` for function-tool definitions, in contrast to
   the unconditional `"strict": True` for structured-output responses — an existing asymmetry, not
   itself a defect, worth the implementer's awareness when writing the fix.
2. `demo_summary/v1.yaml`/`v2.yaml` carry the identical latent defect but are not reachable through
   any registered `CapabilityRegistry` entry today — including them in the fix is for
   repository-wide hygiene, not because anything live depends on them.

---

# Final Recommendation

Fix via **Option A only**: publish one new prompt version per affected Capability
(`research/v2.yaml`, `intelligence/v2.yaml`, `scoring/v2.yaml`, `copywriting/v2.yaml`,
`quality/v3.yaml`, plus `demo_summary/v3.yaml` for hygiene), each adding
`additionalProperties: false` at every object node and an `items` sub-schema for every array
property; bump each Capability's `PROMPT_VERSION` constant by one line; add one new, static,
no-network mechanical test asserting every prompt's `output_schema` satisfies OpenAI's strict-mode
shape recursively. This is a cross-phase infrastructure correction (Phase 6/7/8/9 artifacts, plus
two Phase 10 artifacts that inherited the same gap), requires no migration, no architecture change,
and touches zero files outside the prompt-versioning mechanism this repository already has. Do not
disable `strict=true` (Option D) as the primary fix — it would suppress the symptom permanently
without ever making the underlying prompt contracts complete, and would need a deliberate,
visible human decision to trade away OpenAI's stronger enforcement, not a silent flip buried in an
adapter file. Separately, and independently of the schema fix, `FallbackPolicy._attempt_candidate()`
should be revisited in a future, correctly-scoped session to stop discarding per-candidate failure
detail — this materially impairs debuggability of any future live provider failure, not just this
one.

STRUCTURED OUTPUT BLOCKER CONFIRMED — MINIMAL FIX IDENTIFIED
