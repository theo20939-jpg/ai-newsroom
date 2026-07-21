# OpenAI Structured Outputs Remediation Plan — Final Re-Audit

**Status: audit document. Does not modify the remediation plan, code, prompts, tests, or any
architecture contract.** No live API call was made. This is a fresh, independent verification pass
against current repository source — the prior audit's findings are used only to know what to check,
never trusted as already-proven.

---

# Executive Summary

The revised plan (`docs/openai_structured_outputs_remediation_plan.md`) fully resolves the prior
audit's one MAJOR finding and both MINOR findings. All six previously-missing existing test files
are now named explicitly, in the Confirmed Scope section, the Exact File Scope table, M2's
milestone description, and the Live Validation Gate. M2 now explicitly states the `PROMPT_VERSION`
bump and the six fixture updates are one atomic change with no intentional broken-test window. A
red/green proof requirement was added to the Test Plan, specifying both a synthetic-schema unit
check (proving the validator logic is real) and a documented before/after demonstration against
this repository's actual prompt content. The Live Validation Gate now lists nine explicit items,
including `mypy` and secret/hygiene checks.

Independent re-verification against live source confirms every one of these corrections is
accurate and complete: the six named test files are exactly, and only, the six affected (a broader
grep across all of `tests/` and a second broader grep for alternate quoting styles found no
seventh); the recalculated 20-file total is arithmetically correct from the plan's own enumerated
tables; the schema fix remains sufficient (all 8 prompt files are still genuinely flat — no nested
objects, no `$defs`, no `oneOf`/`anyOf`/`allOf` — reconfirmed by direct grep this session); and
Track B's narrow-fix claim holds against a broader check than either prior audit ran (see Findings,
MINOR-1, below).

One small, real, non-blocking inconsistency was found: the Live Validation Gate's `mypy` item
states "all 12 Python files" but then enumerates a list that sums to 14. This is an arithmetic
label error, not a scope omission — every file that should be mypy-checked is actually named in the
parenthetical; only the summary number is wrong.

No CRITICAL or implementation-blocking MAJOR finding remains.

---

# Previous Findings Resolution

| Prior finding | Status | Evidence |
|---|---|---|
| MAJOR-1: Track A undercounts test-file impact by 6x | **RESOLVED** | All six files now named in Confirmed Scope (lines naming each with its exact current hardcoded version), the Exact File Scope table (6 explicit rows), M2's milestone text ("M2 also owns... the six mechanical `FakePromptRepository` fixture-version updates"), and the Live Validation Gate (item 3, listed individually). Independently re-verified via `grep -rn 'version="[0-9]"' tests/*.py` and a second, looser regex pass (`version\s*=\s*['"][0-9]+['"]`) across all of `tests/` — confirms these six, and only these six, are genuinely affected; four other files matched the loose grep (`test_ai_execution_mapper.py`, `test_capability_testing_convention.py`, `test_file_prompt_repository.py`, `test_prompt_repository_protocol.py`) and were individually confirmed to use synthetic/unrelated prompt names (`"fake-prompt"`, `"example"`, `"greeting"`) or a locally-defined, disk-independent `FakePromptRepository` stub — none touches a real Capability's `PROMPT_VERSION`. |
| MINOR-1: Live Validation Gate omits `mypy`/secret-hygiene | **RESOLVED** | Gate now has 9 explicit items; item 6 is targeted `mypy`, item 8 is secret/security hygiene, independently confirmed present in the current document text. |
| MINOR-2: no red/green discipline in milestone order | **RESOLVED** | Test Plan gained a new "Red/green proof, required" subsection specifying both a synthetic-invalid-schema unit test and a documented before/after run against real repository content; M2's atomicity language separately closes the "no known broken-test window" requirement. |

---

# Verified 20-File Scope

Recalculated independently from the plan's own Exact File Scope table (22 rows total; 20 files
after excluding the 2 header/separator artifacts of table formatting — i.e., 20 genuine file
entries):

**Track A — 18 files, confirmed**:
- 6 new prompt YAML: `prompts/research/v2.yaml`, `prompts/intelligence/v2.yaml`,
  `prompts/scoring/v2.yaml`, `prompts/copywriting/v2.yaml`, `prompts/quality/v3.yaml`,
  `prompts/demo_summary/v3.yaml` — confirmed none exists on disk today (`find prompts -name
  "*.yaml"` returns exactly the 8 pre-existing files, no v2/v3 collision).
- 5 one-line `PROMPT_VERSION` edits — confirmed current values by direct grep this session:
  `research="1"`, `intelligence="1"`, `scoring="1"`, `copywriting="1"`, `quality="2"` — exactly
  matching the plan's claim, no drift.
- 1 new invariant test: `tests/test_openai_strict_schema_compliance.py`.
- 6 mechanical existing-test-fixture edits: `tests/test_copywriting_capability.py`,
  `tests/test_research_capability.py`, `tests/test_intelligence_capability.py`,
  `tests/test_scoring_capability.py`, `tests/test_scoring_capability_retry.py`,
  `tests/test_quality_capability.py` — independently reconfirmed by direct grep (see Previous
  Findings Resolution above).

**Track B — 2 files, confirmed**:
- `integrations/llm_gateway/fallback/policy.py`.
- 1 new/extended `FallbackPolicy` test.

**No duplicate-counted file, no missing required file, no unnecessary file found.** No hidden
implementation dependency was found outside this 20-file scope: `FilePromptRepository.__init__()`
re-confirmed to require zero code change to discover new version files (`glob("v*.yaml")` per
name-directory, re-read directly this session); `OpenAIAdapter._build_payload()` re-confirmed to
pass `request.response_schema` through verbatim with no transformation; `capabilities/registry.py`
re-confirmed to register exactly 5 Capabilities, no more, no fewer.

**Total: 20 files.** Matches the plan's own recalculated claim exactly.

---

# Prompt Versioning Verification

Current on-disk state, independently re-confirmed:

| Capability | Current `PROMPT_VERSION` | Resolved prompt today | Planned new version | Planned new `PROMPT_VERSION` |
|---|---|---|---|---|
| `ScoringCapability` | `"1"` | `scoring/v1.yaml` | `scoring/v2.yaml` (new) | `"2"` |
| `QualityCapability` | `"2"` | `quality/v2.yaml` | `quality/v3.yaml` (new) | `"3"` |
| `ResearchCapability` | `"1"` | `research/v1.yaml` | `research/v2.yaml` (new) | `"2"` |
| `IntelligenceCapability` | `"1"` | `intelligence/v1.yaml` | `intelligence/v2.yaml` (new) | `"2"` |
| `CopywritingCapability` | `"1"` | `copywriting/v1.yaml` | `copywriting/v2.yaml` (new) | `"2"` |

Six new YAML files exist because `QualityCapability` alone advances two version numbers ahead of
its predecessor (`v2` → `v3`, since `v1` is already historical/superseded and untouched), while the
other four advance one (`v1` → `v2`) — five Capability constants because `QualityCapability` is one
Capability with one constant, not two. This asymmetry is internally consistent, not an error.

- **Historical versions untouched**: confirmed — `research/v1.yaml`, `intelligence/v1.yaml`,
  `scoring/v1.yaml`, `copywriting/v1.yaml`, `quality/v1.yaml`, `quality/v2.yaml` are all named only
  as read/comparison targets in the plan's text, never as edit targets; no in-place edit appears
  anywhere in the document.
- **No collision**: confirmed by direct `find` — none of the six proposed new filenames exists.
- **`PromptRepository` resolution**: confirmed zero code change needed (see Verified 20-File Scope
  above).
- **Quality's version history**: `v1` (historical, immutable, superseded before this plan even
  existed), `v2` (current live default, being superseded by this plan), `v3` (new, becomes the live
  default once `PROMPT_VERSION` bumps in M2) — all three states are independently, permanently
  resolvable; the plan does not delete or renumber `v1` or `v2`.

No issue found in this section.

---

# Strict-Schema Sufficiency

Reconfirmed directly, this session, via `grep -rn "type: object|\$defs|definitions:|oneOf|anyOf|
allOf|additionalProperties" prompts/*/v*.yaml`: the only `type: object` match in any of the 8
existing prompt files is each file's own single root `output_schema` node — zero nested objects,
zero `$defs`/`definitions` blocks, zero `oneOf`/`anyOf`/`allOf` constructs, and zero existing
`additionalProperties` declarations anywhere. This matches the plan's own claim exactly.

Array-property gap reconfirmed by direct grep: `research.facts`, `research.gaps`,
`copywriting.hashtags`, `quality.issues` (both `v1` and `v2` share the gap, though only `v2`'s
successor, `v3`, is live-remediated) — four distinct array properties across four files, all
lacking `items`, all correctly identified in the plan's Per-Capability table.

`required`/`properties` alignment is unaffected by the fix (the fix adds sibling keys, doesn't
touch `required`/`properties`) — reconfirmed by direct read of all 8 files.

**The planned schema remediation is sufficient for every schema that currently exists in this
repository**, checked recursively (there is nothing to recurse into today, and the plan's own
required test is explicitly specified to recurse regardless, future-proofing against a schema this
repository does not yet have). No gap found.

---

# Red/Green Verification

The revised plan's "Red/green proof, required" subsection specifies:
1. **RED** — a dedicated unit-level test asserting the invariant validator's own function rejects
   a small, local, deliberately-invalid schema (missing `additionalProperties: false`, and
   separately an array property missing `items`) constructed inline, proving the validator logic
   itself is real, not a no-op. This directly targets the exact class of defect that produced the
   real `400` (a missing `additionalProperties`/`items` declaration), not an unrelated synthetic
   condition — the two invalid-schema shapes named are structurally identical to the real gap found
   in `research/v1.yaml` (missing `additionalProperties`) and `copywriting/v1.yaml`/`research/
   v1.yaml` (array property missing `items`).
2. Additionally documented: running the same repository-wide invariant against the pre-remediation
   (currently-active) prompt versions, before M2 switches the wiring, must fail and name the exact
   capability/prompt/field that violates the rule — this is the literal condition that produced the
   real failure, demonstrated at the correct point in the sequence (before the fix, not only
   asserted abstractly).
3. **GREEN** — after M1+M2, the same invariant passes for all 5 registered, live-default,
   structured-output Capabilities.

This combination is adequate: it is not possible for the RED unit test to trivially pass on an
unrelated condition, since it specifically constructs the two invalid shapes matching this
repository's own actual defect pattern, and it is not possible for the plan's GREEN claim to be
vacuous, since it is scoped to the same 5-Capability list the registry itself hardcodes. No
destructive git manipulation is required or permitted, matching the user's own stated constraint.

No gap found in this section.

---

# Track B Verification

Re-traced the exact failure flow independently, this session:

1. `OpenAIAdapter._translate_exception()` (`openai_adapter.py:119-133`, re-read directly) — for a
   `400`, redacts via `_redact()` (literal API-key value, `Bearer <token>` pattern, `sk-...`-shaped
   token) and attaches the sanitized message to `ProviderPermanentIncompatibleError` **before**
   `FallbackPolicy` ever sees it. Confirmed accurate.
2. `FallbackPolicy._attempt_candidate()` (`policy.py:196-200`, re-read directly) —
   `except ProviderPermanentIncompatibleError:` with **no `as exc` binding at all**: the caught
   exception object is not merely discarded after capture, it is never bound to a name in the
   current code — Python itself drops it. The plan's proposed fix correctly adds the `as exc`
   binding that does not exist today; this is not a mischaracterization, it is the precise,
   necessary correction. Only `FailureClass.PERMANENT_INCOMPATIBLE` survives into the returned
   `_AttemptOutcome`, confirmed.
3. `_run_sequence()`'s `"fallback"` log line (`policy.py:291-300`, re-read directly) logs
   `attempt_index`/`candidate_provider_id`/`candidate_model_id`/`outcome.failure_class.value`
   only — confirmed, no message text.
4. Exhaustion (`policy.py:315-322`, re-read directly) raises `AllProvidersFailedError` with a
   purely templated string — confirmed, zero per-candidate detail.
5. `AllProvidersFailedError.__init__(self, message: str, *, reason: str)`
   (`errors.py:77-79`, re-read directly) — confirmed, arbitrary message already accepted, no
   signature change needed or proposed.

**The plan proposes only the minimum correction**: one new dataclass field
(`failure_detail: str | None`), populated at the two existing `except` sites (via the `as exc`
binding the fix adds), read at two existing call sites (the log line's `extra` dict, and the final
error message's f-string). No new redaction logic (`str(exc)` is already the redacted message), no
new exception class, no `FailureClass` value change, no `GenerateRequest`/`GenerateResponse`/
`CapabilityCall` field change, no control-flow restructuring.

**Broader check than either prior session ran**: grepped every test file referencing
`AllProvidersFailedError` (10 files found, not the 6 the originating plan-audit checked:
`test_ai_execution_mapper... ` — correction, the additional four are
`test_ai_integration_layer_e2e.py`, `test_capability_boot_wiring_e2e.py`,
`test_fallback_policy.py`, `test_routing_gateway_pipeline.py`). Individually read every assertion
site in all four additional files — every one asserts only `.reason` or the exception type itself
(`pytest.raises(AllProvidersFailedError)`), never message text. **Zero existing test breaks from
Track B's change** — the plan's own claim is reconfirmed true, on a broader evidence base than
either prior document actually checked (see Findings, MINOR-1, for why this is flagged as a
process note, not a plan defect).

No unnecessary error-hierarchy redesign found. No secret-leak risk found (the enrichment re-surfaces
a string already safe to log before this fix; `_redact()` itself is untouched). No fallback
classification or retry/backoff/health-store behavior change found.

---

# Live Validation Gate Verification

All nine items are present and explicit in the current document: (1) Track A invariant test with
red/green proof, (2) `FallbackPolicy` test suite including new Track B assertions, (3) all six
mechanically-affected existing Capability tests individually, (4) full `pytest -q`, (5) `ruff check
.`, (6) targeted `mypy`, (7) `validate_architecture`, (8) secret/security hygiene check, (9) git
scope review against the (now-corrected) 20-file table. M6 (live retry) is gated on all nine by the
document's own explicit "Only once all nine hold" transition sentence — no earlier exit path to a
live call exists in the document.

M6 itself remains minimal: one optional smoke call (explicitly skippable if a recent smoke is
trusted), one real Phase 10 CLI run against the same already-identified-safe `NewsEvent`, and an
explicit closing sentence forbidding repeated retries within the same session.

**One arithmetic inconsistency found** (flagged in Findings, MINOR-2): gate item 6 states "all 12
Python files in the Exact File Scope table" but the same sentence's own parenthetical then lists
"the 5 `PROMPT_VERSION` edits, the 6 mechanical test fixture edits, the new invariant test,
`fallback/policy.py`, and the Track B test" — 5+6+1+1+1 = 14, not 12. The enumerated list itself is
complete and correct (it names every Python file in the 20-file scope); only the summary number
"12" is wrong. This does not cause any file to be skipped from the mypy gate, since the gate item's
binding instruction is "every changed Python production and test file," not the miscounted number.

---

# Phase 10 Isolation

Confirmed precisely: the plan names exactly four Phase-10-touching files —
`capabilities/copywriting_capability.py`, `capabilities/quality_capability.py` (their
`PROMPT_VERSION` constants) and `tests/test_copywriting_capability.py`,
`tests/test_quality_capability.py` (their fixture version strings) — each explicitly labeled
"cross-phase remediation touching a Phase 10-created/modified file — not new Phase 10 feature
work." No other Phase 10 file (the remaining 5 of Phase 10's 9 authorized production files:
`workflows/definitions/content_generation.py`, `capabilities/registry.py`,
`schemas/content_draft.py`, `services/content_draft_service.py`,
`scripts/run_content_generation.py`; plus `prompts/copywriting/v1.yaml`, `prompts/quality/v2.yaml`)
appears anywhere in the Exact File Scope table — independently re-confirmed by reading the table in
full this session.

No planned change exists anywhere in the document to `CONTENT_GENERATION` workflow semantics,
`ContentDraft` lifecycle, `run_content_generation_for_event()` orchestration behavior, Telegram
publishing, meme generation, a scheduler, `WorkflowRunner`, or `CapabilityExecutor` — none of these
symbols or files appear in the plan's Exact File Scope table, Executive Summary, or Final
Recommendation.

No gap found in this section.

---

# Milestone Consistency

M0 (baseline verification, no code change) → M1 (6 new prompt files, purely additive and inert
until M2) → M2 (5 `PROMPT_VERSION` bumps + 6 mechanical fixture updates, one atomic change, checkpoint
must be internally green) → M3 (offline invariant test, sequenced after M1/M2 so it exercises real,
already-fixed content, carrying the red/green proof) → M4 (Track B, independently confirmed to have
no code or data dependency on M1-M3) → M5 (full regression, depends on all of M1-M4) → M6 (live
retry, depends on M5 passing clean).

M1→M2→M3 remains a genuine hard sequence. M2's own text now explicitly forecloses an intentional
broken-test window — the constant bump and the six fixture updates are stated as one atomic unit,
not two sequential steps, and M2's own checkpoint (the six affected test files passing) is required
before M2 is "considered complete." M3 is correctly positioned to prove the invariant against
already-fixed content, with the red/green subsection separately covering the pre-fix failure
demonstration. M4 remains independent (no file overlap with M1-M3, reconfirmed). M5 correctly blocks
M6 via the Live Validation Gate's own "no further live API call... until all nine... hold" wording.

No circular dependency, no unsafe sequence, and no milestone that intentionally leaves the
repository with a known-broken test, found.

---

# Findings

## CRITICAL

None.

## MAJOR

None. The prior MAJOR-1 finding is fully resolved (see Previous Findings Resolution).

## MINOR

1. **The prior plan-audit's own "6 files touch `AllProvidersFailedError`" enumeration was itself
   incomplete** (it missed `tests/test_ai_integration_layer_e2e.py`,
   `tests/test_capability_boot_wiring_e2e.py`, `tests/test_fallback_policy.py`,
   `tests/test_routing_gateway_pipeline.py` — 10 files actually reference this exception, not 6).
   This is not a defect in the plan currently under audit — the plan itself makes no specific
   file-count claim about `AllProvidersFailedError` test references; this note only documents that
   a broader, independent check was run this session and the underlying safety conclusion ("zero
   existing test breaks from Track B's change") is reconfirmed true on the fuller evidence base, not
   contradicted. Non-blocking; no correction needed to the plan under audit.
2. **Live Validation Gate item 6 states "all 12 Python files" but its own parenthetical enumerates
   14.** The list itself is complete and correct; only the summary number is wrong. Does not cause
   any file to be skipped (the gate's binding instruction is the enumerated list / "every changed
   Python production and test file," not the miscounted total). Cosmetic; does not block
   implementation. A one-word correction (`12` → `14`) would resolve it but is not required before
   implementation may begin.

## OBSERVATIONS

1. The plan's own confidence that the schema fix will make the real OpenAI API accept the request
   remains, correctly, an unconfirmed-until-M6 prediction — grounded in OpenAI's documented
   Structured Outputs contract, not yet empirically re-tested against a live call in this or any
   prior session. This is stated accurately in the plan's own Risks section and is not overstated.
2. `demo_summary/v1.yaml`/`v2.yaml`'s remediation remains correctly optional/hygiene-only —
   reconfirmed via `grep -rn demo_summary capabilities/registry.py` returning nothing.

---

# Readiness Score

**9/10** — every previously-identified gap is fully and correctly resolved, independently
re-verified against live source rather than trusted from the plan's own prose. The architecture
diagnosis, both tracks' proposed fixes, the Phase 6 §8 ownership reasoning, the exact exception-flow
trace, the recalculated 20-file scope, and Phase 10 isolation all independently re-confirm correct.
The one point kept this from 10/10 is the small, purely cosmetic `12`-vs-`14` arithmetic label in
the Live Validation Gate (MINOR-2) — a documentation nit with zero functional consequence, not a
scope, safety, or correctness defect.

---

# Final Verdict

REMEDIATION PLAN APPROVED
