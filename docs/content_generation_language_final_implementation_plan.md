# Russian Output — Final Implementation Plan

**Investigation only. No production code, test, prompt, database record, or migration was modified
to produce this plan.** Not Phase 11 work — every file discussed below is Phase 6/10-owned; Phase
11's Contract §18 freeze remains untouched by this document.

---

## Concern 1 — Prompt governance: is Python-built instruction text acceptable?

### The governing text, found and quoted exactly

`docs/phase6_architecture_contract.md` §8 (Prompt Repository Contract):

> **Ownership:** prompt *content* (system role, rules, output schema...) is authored and versioned
> as files under `prompts/`, outside Python... `Capability` fills the `CONTEXT`/`TASK` blocks
> **itself** from `CapabilityContext` and hands the assembled `Message` list to
> `LLMGateway.generate()`; `PromptRepository` never sees `CapabilityContext`.

This is authoritative and unambiguous: Phase 6's own architecture draws a hard line between two
categories, both already in production use, identically, in all five existing capabilities:

| Category | Owner | Versioned? | Current example |
|---|---|---|---|
| SYSTEM ROLE, RULES, OUTPUT FORMAT | `prompts/*/v*.yaml`, loaded via `PromptRepository` | **Yes** — immutable once published (§8 binding rule) | `prompt.system`, `prompt.rules`, `prompt.output_schema` |
| CONTEXT, TASK | The `Capability`'s own Python `_build_request()`, built fresh from `CapabilityContext` every call | **No** — by design, dynamic, per-request | Today's `f"Title: {news_event.title}\nCategory: ...\nLanguage: {context.business.language}"` and `task_text = "Write a short, social-ready post..."` |

So the concern's premise — "Python-built task instructions" being architecturally illegitimate —
is **not correct as a blanket claim**: CONTEXT/TASK are *already*, by explicit Phase 6 §8 design,
Python-built, unversioned, per-request content, and every existing capability already relies on
this split. My prior proposal (append `"write in {language}"` to `task_text`) was **architecturally
permitted**, but I now agree it under-serves the user's *deeper, legitimate* concern: a genuinely
new, general **behavioral norm** — *"Copywriting must always match the target editorial
language, regardless of source"* — is exactly the kind of thing a human prompt-governance reviewer
would want to see, review, and version-control explicitly, not something that should exist only as
an ad hoc string concatenation buried in a capability's Python file, invisible to anyone auditing
`prompts/copywriting/v*.yaml` for what the model is actually instructed to do.

### Decision

**Split the two roles it explains:**
- The **norm** ("always write in the target editorial language given by the context") becomes a
  new, governed **RULE** in a new, additively-versioned prompt file
  (`prompts/copywriting/v3.yaml`) — reviewable, versioned, immutable once published, exactly like
  every other behavioral constraint Copywriting already has (*"Base the draft only on the given
  title/category..."*, *"Keep the title concise..."*).
- The **value** (which language, this request) continues to flow through CONTEXT, in Python,
  exactly as it already does today for every other per-request fact (`Title:`, `Category:`) — this
  part of the existing architecture is correct and untouched.

This is the exact "existing immutable copywriting prompt version → new copywriting prompt version →
explicit output-language instruction in the governed prompt → normal version selection through the
existing prompt system" flow the user's message prefers. **No parallel prompt system, no bypass of
`PromptRepository`, no edit to `prompts/copywriting/v2.yaml`** (left in place, immutable, per §8).

---

## Concern 2 — Source language vs. target output language

### Investigation

`BusinessContext.language: str = "en"` is defined in `schemas/capability.py` and — critically —
`docs/phase6_architecture_review.md` line 49 explicitly categorizes it: *"...plus **editorial
config** (`language`, `audience`, `brand_voice`)."* It is grouped, by the architecture's own design
taxonomy, with `audience` and `brand_voice` — both of which are unambiguously **properties of the
desired output** (who this is written for, what tone) and **cannot** describe the source
`NewsEvent` at all (a raw collected news item has no "audience" or "brand voice" of its own — those
are AI Newsroom's own editorial policy choices). `NewsEventSnapshot` (the model that *does*
represent the actual source article) has **no** `language` field of its own — confirming `language`
was deliberately placed in the *editorial-config* sibling group, not the *source-data* group.

**A separate, genuinely distinct "source language" concept already exists**, unrelated and never
conflated with this one: `schemas/source_definition.py:42`'s `SourceDefinition.language` — a field
on the *source-pack config* describing what language a given RSS/API feed publishes in. Confirmed
via `grep`: this field is **currently completely unwired** — it is captured from
`config/newsroom_sources_v1/*.yaml` but never propagated into `NewsSource`, `NewsEvent`, or
anywhere else in the runtime pipeline (no `database/models/news_source.py` column, no `.language`
read anywhere in `services/`, `database/`, `integrations/sources/`).

**Conclusion, evidence-backed**: `BusinessContext.language`'s *design intent*, per its own
categorization, already is "target editorial output language" — not source language. The ambiguity
the user correctly worried about is real, but it lives in the **current prompt-text presentation**
(`f"Language: {value}"` sits visually among `Title:`/`Category:`/`Content:` in `context_text`,
making it *read* like a source-event attribute to a model, even though it was never *designed* to
mean that) — not in the field's own schema-level meaning. This is a second, independent root-cause
refinement beyond the M5 report's original finding (no imperative instruction): the field is
*also* mislabeled at its point of use.

### Decision

**Keep the Pydantic field named `language` on `BusinessContext`** (it is already correctly scoped,
per its own "editorial config" categorization; renaming it — e.g. to `target_language` — was
considered and would touch five additional capability files' attribute access for zero functional
benefit, given the semantic confusion lives in the prompt *label*, not the *field name*). **Fix its
presentation everywhere it is used**: change the literal prompt-facing label from `"Language:
{value}"` to `"Target output language: {value}"` in all five capabilities' `_build_request()`
functions, and strengthen `BusinessContext.language`'s docstring/field description to state
explicitly: *"the desired editorial output language — not the source NewsEvent's own language."*
This removes the ambiguity for both the LLM and any future human reader, at the smallest possible
diff. `SourceDefinition.language` remains untouched, unwired, and unrelated — no conflict, no
overlap, confirmed.

**Alternative considered and rejected as the primary recommendation** (documented per instruction,
not implemented): renaming the field to `target_language` throughout. Cleaner in isolation, but
touches `schemas/capability.py` + all five capability files' `context.business.language` reads for
no behavior change beyond naming — a larger diff for the same outcome. Available if the user prefers
maximum unambiguity over minimal diff.

---

## Investigation questions, answered

**1. Intended semantic contract of `BusinessContext.language`**: target/desired editorial output
language (per its "editorial config" categorization alongside `audience`/`brand_voice`), not
source language. See Concern 2 above.

**2. Every read site and what each assumes**: all five capabilities
(`research_capability.py:95`, `intelligence_capability.py:104`, `copywriting_capability.py:120`,
`quality_capability.py:113`, `scoring_capability.py:138`) read it identically, interpolating it
into `context_text` — none of them currently treat it as an *instruction*; all five currently
present it ambiguously (label reads "Language:", positioned like a source attribute). None of them
assume anything more specific than "a string describing language" — no capability's own logic
branches on its value.

**3. Would `"ru"` incorrectly label English source content as Russian?** No — the field never
described the source to begin with (§2), so setting it to `"ru"` does not mislabel `NewsEvent`
content; it correctly states "write the output in Russian," which is exactly what it was designed
to mean. The current *ambiguous prompt-facing label* is the actual defect, fixed separately (§2/§7).

**4. Does existing architecture already have an appropriate target-output-language mechanism?**
Yes — `BusinessContext.language` already is that mechanism, by design (categorization evidence);
it was simply never wired with a value other than the implicit `"en"` default, and never labeled
unambiguously at its point of use.

**5. Smallest architecture-preserving representation**: no new field needed. Fix the *default*
(via config injection, not a silent schema-default flip — Concern-independent, restated from the
prior report) and fix the *label* (§2). Zero new schema, zero new nesting, zero new component.

**6. Prompt Registry/versioning mechanism**: `integrations/prompts/protocol.py`'s
`PromptRepository.resolve(name, version=None)` / `RenderedPrompt` (frozen, `name`/`version`/
`system`/`rules`/`output_schema`); `integrations/prompts/file_repository.py`'s `FilePromptRepository`
resolves `prompts/<name>/v<version>.yaml` files from disk. Immutability is a binding Phase 6 §8
rule (confirmed, re-read this session) — a published `(name, version)` must resolve to the same
content forever. `CopywritingCapability.PROMPT_VERSION = "2"` (confirmed,
`capabilities/copywriting_capability.py:38`) currently resolves `prompts/copywriting/v2.yaml`.

**7. How Copywriting receives the instruction through the governed system**: a new RULE, added to a
new `prompts/copywriting/v3.yaml` (copy of `v2.yaml`'s `system`/existing `rules`, plus one new
rule), with `CopywritingCapability.PROMPT_VERSION` bumped from `"2"` to `"3"` — normal version
selection through the existing, unmodified `PromptRepository.resolve(CAPABILITY_NAME,
PROMPT_VERSION)` call already in `capabilities/copywriting_capability.py:159`. No `PromptRepository`
code changes; no new lookup mechanism.

**8. Is a new Copywriting prompt version required?** **Yes** — the new rule is governed RULES
content, and Phase 6 §8 forbids editing `v2.yaml` in place.

**9. Do Research/Intelligence/Scoring/Quality need target-output-language behavior?** Only
Copywriting's own output reaches Phase 11's `/news` — re-confirmed this session: `services/
content_draft_service.py::_copywriting_output()` reads exclusively `step_results["copywriting"]`;
Research/Intelligence/Scoring's own structured outputs (facts, significance/angle/audience-
relevance, score/rationale) are internal, step-chained data never displayed anywhere. They do
**not** need the explicit instruction for the stated requirement. `BusinessContext.language="ru"`
still flows to all five uniformly (harmless — arguably *correct* metadata for all of them, now
correctly labeled "Target output language" too), but only Copywriting's prompt gets the new
imperative RULE.

**10. Should Quality verify the generated ContentDraft is actually in the target language?**
Investigated the enforcement question directly: **Quality's `passed`/`issues` verdict currently has
zero enforcement power.** Re-confirmed: `ContentDraftService._copywriting_output()` reads only the
`"copywriting"` step's result — it never inspects `step_results["quality"]` at all, and
`WorkflowRunner`'s step-completion logic treats a schema-conformant Quality response as step
`SUCCESS` regardless of whether `passed` is `true` or `false` (`_floor_validate()` checks shape
only, never the boolean's value). Adding a language check to Quality today would be **purely
informational** (visible in `step_results`, not surfaced anywhere) — not a real safety net, and
building real enforcement (blocking `ContentDraft` persistence on Quality failure) would be a new
gating mechanism, i.e. an actual architecture change, explicitly out of scope. **Recommendation:
do not add this now** — it adds a second prompt-version bump (`prompts/quality/v4.yaml`) for a
check that cannot currently block anything. Documented as a real, legitimate future enhancement
(paired with an actual enforcement mechanism), not part of this minimal remediation.

**11 & 12. File scope and test scope**: see dedicated sections below.

---

## Exact proposed files

| File | Change | New file? |
|---|---|---|
| `core/config.py` | +1 `Settings` field, e.g. `default_content_language: str = "ru"` | No |
| `capabilities/executor.py` | `_build_context()`: +1 import (`from core.config import settings`), pass `language=settings.default_content_language` explicitly into `BusinessContext(...)` | No |
| `capabilities/copywriting_capability.py` | `PROMPT_VERSION` `"2"` → `"3"`; `_build_request()`'s context label `"Language:"` → `"Target output language:"` | No |
| `capabilities/research_capability.py`, `intelligence_capability.py`, `quality_capability.py`, `scoring_capability.py` | label-only fix, `"Language:"` → `"Target output language:"` (no `PROMPT_VERSION` bump — their `rules` content is unchanged, only the Python-built CONTEXT label text changes) | No |
| `schemas/capability.py` | `BusinessContext.language`'s docstring/description clarified (no field rename, no default change here — the default stays whatever it already documents; the *effective* value comes from the executor's explicit injection, §Concern 2/§5) | No |
| `prompts/copywriting/v3.yaml` | **New**, additive prompt version: `v2.yaml`'s `system`/existing `rules` copied verbatim, plus one new rule (see exact text below); `output_schema` unchanged | **Yes** |
| `tests/test_copywriting_capability.py` | Update the `FakePromptRepository` fixture's registered `version="2"` → `"3"`; add a new assertion that `task_text`/`context_text` contains the target-language label and value | No (existing file) |
| A new, narrowly-scoped, explicitly-authorized-before-running live-API check | New test/script, mirroring Phase 10 M6's discipline | Possibly new, small file — not yet named, pending separate authorization |

**Zero new production components. Zero new capabilities. Zero new workflow steps. Zero migration.
`v2.yaml` is never edited.**

## Exact proposed changes

**New rule text for `prompts/copywriting/v3.yaml`** (appended to the existing three rules,
verbatim-copied from v2):
> "Always write the title, body, and hashtags entirely in the language given by 'Target output
> language' in the CONTEXT block below — regardless of the source material's own language — never
> mix languages within a single field."

**`capabilities/executor.py::_build_context()`** — one changed line:
```python
business=BusinessContext(
    news_event=news_event_snapshot,
    workflow_state=workflow_state_snapshot,
    language=settings.default_content_language,
),
```

**`capabilities/copywriting_capability.py::_build_request()`** — one changed line (label only, no
new imperative text here — the imperative now lives in the governed prompt, per Concern 1's
decision):
```python
f"Target output language: {context.business.language}\n\n"
```

## Exact prompt version impact

| Capability | Old version | New version | Reason |
|---|---|---|---|
| Copywriting | `"2"` (`v2.yaml`) | `"3"` (`v3.yaml`, new) | New governed RULE (imperative language instruction) |
| Research, Intelligence, Quality, Scoring | unchanged | unchanged | Label-only Python change; `rules`/`system` content untouched, no version bump needed |

`prompts/copywriting/v1.yaml` and `v2.yaml` remain exactly as published, forever, per §8.

---

## Test plan (mapping to the required A–G regression tests)

| Required test | How it's satisfied |
|---|---|
| **A. English source → Russian ContentDraft** | Live-API integration check (new, narrowly authorized): real `NewsEvent` with English `content`, real `CopywritingCapability` call through the real `LLMGateway`, assert returned `title`/`body` are majority-Cyrillic |
| **B. Russian source → Russian ContentDraft** | Same live-API check, second case: a `NewsEvent` with Russian `content` — proves the fix doesn't depend on source language, matching the stated *"source may be any language, output is always the target"* requirement |
| **C. Output-language instruction explicitly present in the actual request/prompt contract** | Offline unit test (`FakePromptRepository`/`FakeLLMGateway`, no network) on `tests/test_copywriting_capability.py`: register a `RenderedPrompt` whose `rules` includes the new language rule, assert the constructed `system_text` contains it verbatim, and assert `context_text` contains `"Target output language: ru"` for a given context |
| **D. Configured target language propagates correctly** | Unit test on `capabilities/executor.py::_build_context()` (new or extended existing executor test): construct with a non-default `settings.default_content_language` (e.g. via monkeypatch/override) and assert the resulting `BusinessContext.language` matches |
| **E. Existing workflow/capability contracts remain valid** | Full existing regression suite (774 tests, Phase 11 M4 baseline) re-run unchanged — confirmed in the prior report that zero existing test encodes an English-output or literal-label assumption, so none are expected to break; re-verified this session that the `FakePromptRepository` fixture is the only place a literal `version="2"` string requires the same one-line mechanical bump the OpenAI-remediation work already established as routine |
| **F. Phase 11 `/news` renders Russian content without performing translation itself** | Extend `tests/test_editorial_card_formatting.py` with one new case: a `draft_title`/`draft_body` containing genuine Cyrillic text renders through `render_editorial_card()` unchanged (escaped only where `<`/`>`/`&` occur, Cyrillic passed through verbatim, `telegram_utf16_length` computed correctly for BMP Cyrillic — already proven generically by the existing `test_bmp_only_payload_utf16_length_equals_python_len` test, extended with an explicit Cyrillic fixture for direct evidence) — proves Phase 11 does no transformation, exactly as its own Contract already requires |
| **G. Historical English ContentDraft rows are not silently mutated** | A new assertion in the live-API check (A/B above): before/after row-count and full-field snapshot of the *existing* M6 validation `ContentDraft` row, confirmed byte-for-byte unchanged after the new draft is created — mirrors the exact technique Phase 11 M4's own zero-mutation test already uses |

---

## Data handling plan for historical English drafts

**Leave the single existing `ContentDraft` row (`[M6 VALIDATION]`, English) completely untouched.**
No code path this remediation introduces writes to, updates, or deletes any existing row —
`ContentDraftService.create_from_result()` remains create-only, called only from
`scripts/run_content_generation.py`, which is not modified by this plan. No backfill, no
regeneration-in-place, no migration. If a Russian example is wanted for manual comparison, the
correct mechanism (already established, no new code needed) is running
`scripts/run_content_generation.py` again against a *fresh* `NewsEvent`, producing a **new** row —
exactly what regression test G above verifies leaves the old row untouched.

---

## M5 re-validation procedure

**Re-running `/news` against the existing single historical English `ContentDraft` is explicitly
NOT valid evidence either way** — that row is expected to remain English forever (§ data handling
plan above); seeing it in English after the fix is correct, not a failure.

Procedure, once remediation is implemented and authorized:
1. Run the full offline test suite (tests C/D/E/F above) — must be green before any live call.
2. Run the one, narrowly-authorized live-API check (tests A/B/G above) — produces exactly one new,
   real `ContentDraft` row from a fresh `NewsEvent`, confirmed Cyrillic, confirmed the old row is
   untouched. This is the same minimal-live-call discipline Phase 10 M6 already established — not
   a new precedent.
3. Only then, restart the bot (`python -m bot.main`) and send `/news` in the same authorized test
   chat used for the original M5 attempt. Expected result this time: **two** cards — the new
   Russian draft (newest, sorted first) and the original English M6 draft (second, unchanged) —
   both rendering correctly, neither mutated, proving coexistence works and ordering remains
   newest-first.
4. This same live session is also the natural opportunity to gather the disambiguating evidence the
   original M5 failure report flagged as still-needed for the **unrelated** thread/topic and
   duplicate-perception issues (e.g., sending `/news` exactly once per chat/topic this time, noting
   the exact resulting card count) — but that is a separate investigation track, not blocked on or
   required by this language remediation, and not re-litigated in this plan.

---

## Architecture impact assessment

**None.** No new component, no new persisted field, no new capability, no new workflow step, no
change to `LLMGateway`/`PromptRepository`'s own protocols, no bypass of either, no parallel
content-generation path, no new gating/enforcement mechanism (Quality remains advisory-only, per
Q10's finding — adding real enforcement was identified and explicitly deferred as its own, separate,
future architecture decision). The entire change is: one new config default, one explicit
context-construction parameter, one corrected prompt-facing label (applied uniformly for clarity),
and one new, additively-versioned prompt file carrying the one genuinely new governed behavioral
rule. Every change traces to, and stays within, the exact `BusinessContext → CapabilityExecutor →
Capability → PromptRepository/LLMGateway → ContentDraft` flow Phase 6/10 already established.

---

## Investigation integrity

Zero files modified except this plan document. `git status --short` unchanged from the prior
report's state. No database data modified. Nothing staged or committed.

Awaiting explicit authorization before implementing any part of this plan.
