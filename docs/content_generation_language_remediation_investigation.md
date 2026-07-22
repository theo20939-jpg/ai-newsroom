# Russian Output Remediation Report

**Investigation only.** No production code, test, prompt, database record, or migration was
modified to produce this report. This is explicitly **not** Phase 11 work — Phase 11's own
Contract (§18) freezes every file implicated below; any change here requires its own, separately
authorized governance cycle, outside Phase 11's now-closed M0–M5 scope.

---

## 1. Exact current language propagation path

```
capabilities/executor.py::_build_context()   <- the ONLY production construction site
    BusinessContext(news_event=..., workflow_state=...)
        language field NOT passed  ->  falls back to schemas/capability.py's Pydantic default

schemas/capability.py
    class BusinessContext(BaseModel):
        ...
        language: str = "en"          <- the ONE place "en" is defined, anywhere

capabilities/{research,intelligence,copywriting,quality,scoring}_capability.py
    each _build_request() interpolates:
        f"Language: {context.business.language}\n\n"
    into the CONTEXT block of the message sent to the LLM (alongside Title/Category/Content/
    Summary) - never into the system prompt, never as an imperative instruction.

    -> LLMGateway.generate(request)  (real dispatch, unmodified, not bypassed by this
       investigation's proposed change)

    -> structured JSON result (title/body/hashtags for copywriting)

services/content_draft_service.py::create_from_result()
    persists ContentDraft.title/.body/.hashtags verbatim from the "copywriting" step's result -
    no language field stored anywhere.

services/editorial_inbox_service.py (Phase 11) / bot/formatting.py (Phase 11)
    read ContentDraft.title/.body/.hashtags exactly as persisted and render them - no
    transformation, no translation, no language logic of any kind.
```

## 2. Exact first point where "en" enters the pipeline

`schemas/capability.py`, `BusinessContext.language: str = "en"` — a **Pydantic field default**,
not a value explicitly assigned anywhere. It takes effect the moment
`capabilities/executor.py:137` constructs `BusinessContext(news_event=..., workflow_state=...)`
**without** passing `language=`, which happens on **every single Capability step of every single
workflow run** (both `NEWS_ANALYSIS` and `CONTENT_GENERATION` share this one executor — confirmed:
`grep` found exactly one production construction site of both `BusinessContext` and
`CapabilityExecutor`, `capabilities/executor.py:137` and `scripts/run_content_generation.py:104`
respectively).

---

## Investigation questions, answered

### 1. Where is BusinessContext instantiated for NEWS_ANALYSIS and CONTENT_GENERATION?

One shared site: `capabilities/executor.py::CapabilityExecutor._build_context()`, called fresh on
every `execute(step)` call. `CapabilityExecutor` is workflow-type-agnostic — it is handed a
`task_id` and dispatches whatever `step.capability` the `WorkflowDefinition` names, so the exact
same code path serves both `workflows/definitions/news_analysis.py` (research → intelligence →
engagement → scoring) and `workflows/definitions/content_generation.py` (research → intelligence →
copywriting → quality). **Note**: `NEWS_ANALYSIS` tasks are, in the repository's current state,
only ever *created* (by `services/triage_orchestrator.py`, confirmed as the source of 3,132
`CREATED`-status `EditorialTask` rows observed in the M5 investigation) — nothing in production
code currently *executes* a `NEWS_ANALYSIS` task through `WorkflowRunner`/`CapabilityExecutor`.
Only `scripts/run_content_generation.py` (`CONTENT_GENERATION`) does, in the repository's current
state. A language fix at `_build_context()` would apply to both, whenever/if `NEWS_ANALYSIS`
execution is ever wired up.

### 2. Is `language="en"` inherited implicitly, or explicitly supplied anywhere?

**Purely implicit.** `grep -rn "BusinessContext(" --include="*.py"` across the entire repository
(excluding tests) returns exactly one hit, and it does not pass `language=`. No code anywhere sets
`language` to any value, ever, in production. It is 100% the Pydantic model's own default.

### 3. Which capabilities/prompts actually consume `BusinessContext.language`?

All five registered Capabilities, uniformly and identically:
`research_capability.py:95`, `intelligence_capability.py:104`, `copywriting_capability.py:120`,
`quality_capability.py:113`, `scoring_capability.py:138` — each interpolates
`f"Language: {context.business.language}"` into its own `_build_request()`'s context block.
**Confirmed by direct inspection of every active prompt YAML** (`prompts/research/v2.yaml`,
`intelligence/v2.yaml`, `copywriting/v2.yaml`, `quality/v3.yaml`, `scoring/v2.yaml`): none of them
contain the words "language," "English," or "Russian" anywhere in `system`/`rules` — the versioned
prompt content itself is entirely language-agnostic. The `Language:` line is positioned exactly
like `Title:`/`Category:`/`Content:`/`Summary:` — i.e., it reads as **metadata describing the
source `NewsEvent`**, not as an instruction to the model about which language to *write* its own
output in. No `task_text` in any of the five capabilities mentions output language at all.

### 4. Is changing the default to `"ru"` alone sufficient and safe?

**Likely insufficient, evidence-based conclusion, not merely a cautious guess.** Because
`Language: {value}` is presented to the model as one attribute among several describing the input
event (alongside Title/Category/Content), a model is at least as likely to interpret it as *"this
source material is in Russian"* as it is to infer *"therefore write your own output in Russian"* —
especially since `task_text` (the actual instruction, e.g. copywriting's *"Write a short,
social-ready post... based only on the given title/category and Research's/Intelligence's
output"*) never mentions output language at all. Flipping only the default would make behavior
depend on the model's own implicit inference from an ambiguous metadata field — not a deterministic,
contract-worthy guarantee. It is **safe** (no crash, no schema violation — `language` is a free
`str` field, any value is valid), but not **sufficient** on its own for the stated requirement.

### 5. Should language be explicitly injected at workflow/context construction time instead?

**Yes — this is the recommended approach**, for two independent reasons: (a) it makes the decision
explicit, centrally located, and configurable (via `core/config.py`, `.env`-overridable) rather
than silently baked into a schema's default value with no operational visibility; (b) combined with
finding #4, the value alone doesn't determine output language — an explicit instruction is also
needed in the capability that actually produces user-facing text (see §"Minimal recommended
remediation" below).

### 6. Does any persisted task/context/state store language, risking stale "en" values?

**No.** `grep -n "language"` across `schemas/workflow.py`, `database/models/editorial_task.py`, and
`database/models/content_draft.py` returns zero matches. `EditorialTask.workflow`'s JSON blob
(`WorkflowExecutionState`) stores only step names/statuses/results — never the `BusinessContext`
that produced them. `language` is constructed fresh, in memory, on every `_build_context()` call
and is never written to the database in any form. **No migration risk, no stale-value risk**: every
future task, from the moment any fix lands, would pick up the (changed) language source with zero
special-casing for already-completed tasks (whose own `ContentDraft.title`/`.body` are already
final, static text — not re-evaluated against `language` after generation).

### 7. Which existing tests assume English output?

**None, explicitly.** `grep -rn "language"` across every test file that constructs a
`BusinessContext` (`test_capability_schemas.py`, `test_copywriting_capability.py`,
`test_intelligence_capability.py`, `test_phase8_cross_cutting_regression.py`,
`test_phase9_capability_registration.py`, `test_quality_capability.py`,
`test_research_capability.py`, `test_scoring_capability.py`, `test_scoring_capability_retry.py`)
returns zero matches — every one of them constructs `BusinessContext` without passing `language=`
(relying on the same implicit default), and **none asserts on the literal `"Language: en"` string**
or on any language-dependent content, since these are `FakeLLMGateway`/`FakePromptRepository`-based
structural unit tests (checking schema shape, field presence, retry logic) that never invoke a real
LLM and never produce real natural-language prose. **Changing the default, or injecting an explicit
value, breaks none of them.**

### 8. What regression tests would be required to guarantee Russian output?

Real language *content* cannot be asserted by the existing fake-gateway unit-test tier (it never
calls a real model). Guaranteeing actual Russian output requires:
- A new, narrowly-scoped **live-API integration check** (mirroring Phase 10 M6's own
  minimal-real-API-call discipline) that runs `CopywritingCapability` against a real
  `LLMGateway`/real provider once, with the corrected context, and asserts the returned
  `title`/`body` contain a majority of Cyrillic characters (a simple, robust, deterministic
  heuristic — e.g. `sum(1 for c in text if 'Ѐ' <= c <= 'ӿ') / len(text) > 0.5` — not a
  full linguistic-correctness check, which is out of reach for an automated test).
- A cheaper, fully offline **prompt-construction unit test** (using `FakePromptRepository`/
  `FakeLLMGateway`, no real network) asserting that `_build_request()`'s assembled `task_text`/
  `context_text` for `CopywritingCapability` contains the explicit output-language instruction —
  proving the *instruction* is present deterministically, even though the *test* can't prove the
  model obeys it (that's what the live-API check above is for).
- Confirmation (via the existing `test_capability_testing_convention.py`-style AST check) that this
  new live-API test is excluded from the default unit-test tier and requires the same explicit,
  narrow authorization Phase 10 M6 required for its own live call.

### 9. How should existing English ContentDraft records be treated?

**Leave the one existing record untouched.** It is `[M6 VALIDATION]`-labeled Phase 10 test/
validation data, not organically-produced editorial content, and no code path (Phase 11 included)
has any write access to `ContentDraft` rows other than `ContentDraftService.create_from_result()`
(called only from `scripts/run_content_generation.py`, which never updates — only creates). There
is no "regenerate in place" mechanism, and building one would be exactly the kind of new,
un-authorized write path both Phase 11's Contract and this investigation's own constraints forbid
inventing. If a Russian-language example is wanted for future manual verification, the correct,
already-existing mechanism is to run `scripts/run_content_generation.py` again against a *fresh*
`NewsEvent`/task after the fix lands — producing a *new* `ContentDraft` row, never touching the old
one. This is a decision to make later, at fix-implementation time, not something this investigation
needs to resolve now.

---

## Minimal recommended remediation

Two changes, three files, no new files, no migration, no new architecture, no LLM Gateway bypass,
no parallel content-generation path:

1. **`core/config.py`**: add one new `Settings` field, e.g. `default_content_language: str = "ru"`
   — matches the file's existing plain-typed-field, `.env`-overridable convention exactly (same
   shape as `app_name`, `log_level`, etc.).
2. **`capabilities/executor.py`**: in `_build_context()`, explicitly pass
   `language=settings.default_content_language` into the `BusinessContext(...)` constructor,
   instead of relying on the schema's own implicit `"en"` default. One new import
   (`from core.config import settings`), one changed line.
3. **`capabilities/copywriting_capability.py`**: in `_build_request()`, append an explicit,
   imperative output-language instruction to `task_text` — entirely in Python code, e.g.
   `f"Write the title, body, and hashtags in {context.business.language}."` — **not** in the
   versioned prompt YAML, so this requires **no new prompt version file** and touches no frozen,
   published prompt content (Phase 6 §8's prompt-immutability rule is fully respected: the change
   lives in the same dynamically-interpolated Python string construction that already builds
   `context_text` today, not in `prompt.system`/`prompt.rules`).

**Why only `copywriting_capability.py` gets the explicit instruction, not all five**: Phase 11's
`/news` inbox displays exclusively `ContentDraft.title`/`.body`/`.hashtags`, which come exclusively
from `CopywritingCapability`'s output. Research/Intelligence/Quality/Scoring's own structured
outputs (facts, significance/angle/audience-relevance text, quality issues, scoring rationale) are
internal step-chained data, never displayed to an end user by any code in this repository today.
The user's own stated desired flow — *"source in any language → research/analysis → editorial
generation → Russian user-facing ContentDraft"* — explicitly describes exactly this shape: upstream
steps may reason in whatever language is natural (including reading the still-English
`NewsEvent.content`); only the final, user-facing Copywriting step needs an explicit,
deterministic Russian-output instruction. `BusinessContext.language="ru"` still flows to all five
uniformly (harmless, arguably correct metadata for all of them), but only Copywriting's own
`task_text` is changed to *act* on it imperatively.

## Alternative options considered

- **Change only `schemas/capability.py`'s default to `"ru"`, nothing else.** Rejected as primary
  recommendation: per finding #4, this is not proven sufficient — the model has no explicit
  instruction to write its own output in the target language, only ambiguous source-language-shaped
  metadata. Kept as a *partial*, necessary-but-not-sufficient piece of the real fix (superseded by
  explicit injection at the executor, which is more visible/testable/configurable than a buried
  schema default).
- **Add the instruction to a new, additively-versioned prompt file (e.g. `prompts/copywriting/
  v3.yaml`)** instead of Python code. Considered because it would keep *all* prompt content
  entirely inside the frozen, versioned YAML layer, which is arguably the "purer" place for
  behavioral instructions to live. Not recommended as the minimal choice because: it requires a new
  `PROMPT_VERSION` bump (cascading into the same mechanical `PROMPT_VERSION`-string test updates
  Phase 10's OpenAI-remediation work needed), and because the instruction is inherently *dynamic*
  (`{context.business.language}`, not a fixed string) — exactly matching the pattern the existing
  `Language:` line already uses in Python code, not YAML. Still a legitimate alternative if a
  future governance decision prefers keeping all behavioral text in versioned prompts.
- **Add the instruction to all five capabilities uniformly**, not just Copywriting. Considered for
  consistency; rejected as broader than necessary given only Copywriting's output is user-facing
  today (see justification above) — can be revisited later, narrowly, if a future phase makes
  Research/Intelligence/Quality/Scoring output user-facing too.
- **Add a per-`NewsSource` or per-`NewsEvent` language override** (e.g. wiring
  `schemas/source_definition.py`'s existing, currently-unused `language: str` field through to
  `BusinessContext`). Considered because it would support the user's own stated allowance that
  *"source material may be in any supported language"* with per-source nuance. Rejected as
  **out of scope for this minimal remediation** — it's a legitimate future enhancement, not
  required to satisfy "Russian by default," and touches an additional file
  (`database/models/news_source.py`/`services/source_importer.py`) this investigation was not asked
  to scope.

## Architecture impact

**None.** No new component, no new persistence, no new capability, no new workflow, no bypass of
`LLMGateway`, no parallel content-generation path. The change is a narrow, three-file parameter/
instruction addition inside the exact same, already-existing `BusinessContext →
CapabilityExecutor → Capability → LLMGateway → ContentDraft` flow this repository has used since
Phase 6/10.

## Migration/data impact

**None.** Confirmed in Q6: `language` is never persisted. No Alembic migration, no schema change,
no backfill is required or proposed. The single existing `ContentDraft` row is explicitly
recommended to be left untouched (Q9).

## Required tests (if/when this remediation is authorized for implementation)

- Extend `tests/test_copywriting_capability.py` (already-existing `FakePromptRepository`/
  `FakeLLMGateway` unit tests) with an assertion that the constructed `task_text`/`context_text`
  contains the explicit output-language instruction for a non-default `language` value.
- A new, narrowly-scoped, explicitly-authorized-before-running live-API check (Q8) verifying real
  Cyrillic output — mirroring Phase 10 M6's own minimal-live-call discipline, not part of the
  default `pytest -q` suite.
- Full existing regression suite (774 tests, confirmed green as of Phase 11 M4) re-run unchanged —
  Q7 confirms none of them encode an English-output assumption, so none are expected to break.

## Exact proposed file scope

| File | Change | New file? | New prompt version? | Migration? |
|---|---|---|---|---|
| `core/config.py` | +1 `Settings` field | No | No | No |
| `capabilities/executor.py` | +1 import, 1 changed line in `_build_context()` | No | No | No |
| `capabilities/copywriting_capability.py` | 1 changed line (`task_text` construction) in `_build_request()` | No | No | No |
| `tests/test_copywriting_capability.py` | +1 assertion in an existing test (or one new test) | No | — | — |
| A new, separately-authorized live-API test | New test, narrow scope | Possibly (or added to an existing Phase 10-style live-validation script) | — | — |

**Zero new production files. Zero new prompt versions. Zero migrations.**

## Confirmation: Phase 11 handler/renderer files

**`bot/handlers/news.py`, `bot/formatting.py`, `services/editorial_inbox_service.py`, and
`schemas/editorial_inbox.py` do not need to change.** All evidence gathered points to the language
gap originating entirely upstream, in Phase 6's `BusinessContext` default and Phase 10's
`CopywritingCapability` prompt construction — Phase 11 correctly displays whatever
`ContentDraft.title`/`.body`/`.hashtags` already contain, in whatever language they were generated
in, exactly as its own Contract describes (a read-only display layer, never a
content-transformation layer). No evidence found anywhere in this investigation implicates any
Phase 11 file.

---

## Investigation integrity

- **Files changed during this investigation**: zero (only this report was added;
  `git status --short` is unchanged from the end of the M5 failure investigation, module the new
  report file).
- **Database data modified**: no — every query this investigation ran (BusinessContext/
  CapabilityExecutor/prompt-YAML inspection) was static code/file reading; no new DB query beyond
  what was already gathered in the M5 report was needed or run.
- **Nothing staged or committed.**

Awaiting explicit authorization before implementing any part of this remediation.
