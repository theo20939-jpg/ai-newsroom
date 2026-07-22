# Russian Output Remediation — Implementation Report

Implements the approved `docs/content_generation_language_final_implementation_plan.md` under
the exact authorized narrow scope. Not committed or staged.

## 1. Exact files changed/created

**Modified (8 production files)**:
`core/config.py`, `capabilities/executor.py`, `schemas/capability.py`,
`capabilities/research_capability.py`, `capabilities/intelligence_capability.py`,
`capabilities/quality_capability.py`, `capabilities/scoring_capability.py`,
`capabilities/copywriting_capability.py`.

**Created (1 new production file)**: `prompts/copywriting/v3.yaml`.

**Modified (4 test files)**: `tests/test_copywriting_capability.py`, `tests/test_capability_executor.py`,
`tests/test_settings_phase7.py`, `tests/test_editorial_card_formatting.py`.

**Untouched**: every Phase 11 production file (`bot/handlers/news.py`, `bot/formatting.py`,
`services/editorial_inbox_service.py`, `schemas/editorial_inbox.py`) — confirmed via `git diff
--stat`, none appear in this remediation's diff (the `bot/handlers/news.py` modification visible
in `git status` predates this remediation, from Phase 11 M3). `prompts/copywriting/v2.yaml` —
confirmed byte-for-byte unchanged (re-verified via the new
`test_real_v3_prompt_file_contains_the_governed_language_rule` test, which asserts its exact
`rules` list).

## 2. Exact semantic change

`BusinessContext.language` is now explicitly documented (docstring/inline comment,
`schemas/capability.py`) as the **desired editorial output language**, not the source
`NewsEvent`'s own language — matching its original Phase 6 "editorial config" design intent
(grouped with `audience`/`brand_voice`). No field was renamed. Every prompt-facing label that read
the ambiguous `"Language:"` now reads `"Target output language:"` in all five capabilities.

## 3. Configuration behavior

`core/config.py` gained `default_content_language: str = "ru"` — a plain, `.env`-overridable
`Settings` field, matching the file's existing convention exactly. Verified: default is `"ru"`;
overridable via `DEFAULT_CONTENT_LANGUAGE` env var (both proven by new tests in
`tests/test_settings_phase7.py`).

## 4. BusinessContext propagation behavior

`capabilities/executor.py::CapabilityExecutor._build_context()` now explicitly passes
`language=settings.default_content_language` into every `BusinessContext(...)` it constructs — one
call site, shared by every step of both `NEWS_ANALYSIS` and `CONTENT_GENERATION` workflows. No
longer left to the schema's own implicit `"en"` default. Proven directly (not just inferred) by two
new tests calling `_build_context()` in isolation with both the default (`"ru"`) and an overridden
(`"en"`) configured value, asserting the resulting `BusinessContext.language` matches exactly.

## 5. Prompt v3 summary

`prompts/copywriting/v3.yaml`: `system` and the original three `rules` copied verbatim from v2,
plus one new governed rule:
> "Always write the title, body, and hashtags entirely in the language given by 'Target output
> language' in the CONTEXT block below — regardless of the source material's own language — never
> mix languages within a single field."

`output_schema` unchanged. The instruction is now governed, versioned prompt content — not
Python-embedded text — per the Concern 1 resolution.

## 6. Confirmation that v2 was untouched

Confirmed three ways: (a) `prompts/copywriting/v2.yaml` was only ever `Read`, never `Write`/`Edit`,
this session; (b) `git diff --stat` shows zero change to it; (c) a new test,
`test_real_v3_prompt_file_contains_the_governed_language_rule`, loads it through the real
`FilePromptRepository` and asserts its `rules` list is byte-for-byte the original three-item list,
with the new language rule confirmed absent from it and present only in v3.

## 7. Copywriting PROMPT_VERSION change

`capabilities/copywriting_capability.py::PROMPT_VERSION`: `"2"` → `"3"`, now resolving
`prompts/copywriting/v3.yaml` through the existing, unmodified
`prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION)` call — no new lookup mechanism.

## 8. Tests added/updated

- `tests/test_copywriting_capability.py`: fixture bumped to `version="3"` (mechanical); **6 new
  tests** — `PROMPT_VERSION == "3"`; target-label/value propagation; English-source-context still
  targets the configured language (regression A, request-construction level); Russian-source
  context also targets the configured language (regression B); the governed rule flows into the
  actual constructed `system_text` (regression C); the real, published v3/v2 prompt files verified
  directly (regression C + v2-immutability, §6).
- `tests/test_capability_executor.py`: **2 new tests** — full config→executor→`BusinessContext`
  propagation, both at the default and at an overridden value (regression D).
- `tests/test_settings_phase7.py`: **2 new tests** — `default_content_language` defaults to `"ru"`;
  overridable via env var.
- `tests/test_editorial_card_formatting.py`: **2 new tests** — a genuinely Russian
  `EditorialInboxCard` renders verbatim (regression F: no translation, no transliteration); Russian
  text mixed with real HTML metacharacters is still escaped exactly like English would be (proves
  the renderer doesn't special-case language).

**12 new tests total**, zero tests removed, zero test behavior weakened.

## 9. Focused test results

- `tests/test_copywriting_capability.py`: **17/17 passed**.
- `tests/test_capability_executor.py`: **10/10 passed**.
- `tests/test_settings_phase7.py`: **11/11 passed**.
- `tests/test_editorial_card_formatting.py`: **26/26 passed**.
- `tests/test_research_capability.py`, `test_intelligence_capability.py`,
  `test_quality_capability.py`, `test_scoring_capability.py`, `test_scoring_capability_retry.py`,
  `test_capability_schemas.py`: **63/63 passed** (label-change regression check).
- `tests/test_capability_boot_wiring_e2e.py`, `test_phase9_capability_registration.py`,
  `test_phase9_research_intelligence_integration.py`, `test_phase10_workflow_integration.py`,
  `test_phase10_capability_registration.py`, `test_content_draft_service.py`,
  `test_run_content_generation.py`, `test_phase8_cross_cutting_regression.py`: **30/30 passed**
  (regression E — existing workflow/capability contracts remain valid).

## 10. Full regression result

`python -m pytest -q`: **786/786 passed** (5:57) — up from Phase 11 M4's 774, reflecting exactly
the 12 new tests; zero failures, zero regressions.

## 11. Ruff result

`python -m ruff check .`: clean.

## 12. Mypy result

Targeted `mypy` on all 8 changed production files: clean, no issues found.

## 13. Architecture validator result

`python -m scripts.validate_architecture`: 0 violations.

## 14. Secrets/scope result

`.env` not tracked, not in `git status`. No credential-shaped string found in any changed file.

## 15. Git diff/status summary

```
 M capabilities/copywriting_capability.py  |   7 +-
 M capabilities/executor.py                |   9 ++-
 M capabilities/intelligence_capability.py |   2 +-
 M capabilities/quality_capability.py      |   2 +-
 M capabilities/research_capability.py     |   2 +-
 M capabilities/scoring_capability.py      |   2 +-
 M core/config.py                          |   9 +++
 M schemas/capability.py                   |   8 ++
 M tests/test_capability_executor.py       |  67 ++++++++++
 M tests/test_copywriting_capability.py    | 128 +++++++++++++
 M tests/test_settings_phase7.py           |  16 ++++
??  prompts/copywriting/v3.yaml (new)
??  tests/test_editorial_card_formatting.py (modified within this remediation; file itself
    pre-exists from Phase 11 M2, so it does not show as newly-created relative to Phase 11's own
    baseline, only relative to git's tracked history)
```
Plus the unrelated, pre-existing Phase 11 M0–M5 files already shown in every prior report
(`bot/handlers/news.py` modified, `bot/formatting.py`/`schemas/editorial_inbox.py`/
`services/editorial_inbox_service.py`/`tests/test_editorial_inbox_service.py`/
`tests/test_news_handler.py` new) — none of them touched by this remediation. Nothing staged.
Nothing committed.

## 16. Deviations

None from the approved plan's design decisions. One minor addition beyond the plan's own explicit
test list, within its spirit: `test_english_context_still_targets_configured_language_english_case`
and `test_russian_source_context_still_targets_configured_language` were written as two distinct,
narrowly-scoped tests (rather than one parametrized test) for clarity — no scope expansion, both
map directly to required regressions A/B.

## 17. Confirmation: no Phase 11 production file changed

Confirmed via `git diff --stat` — none of `bot/handlers/news.py`, `bot/formatting.py`,
`services/editorial_inbox_service.py`, `schemas/editorial_inbox.py` appear in this remediation's
diff.

## 18. Confirmation: no historical ContentDraft was modified

Confirmed by construction (no code path this remediation touches writes to `ContentDraft` — the
only writer, `ContentDraftService`, is untouched, and no script was run) and re-verified directly:
the real `get_latest_editorial_cards()` query, re-run after implementation, returns the exact same
single row (`draft_id=2190d42d-e6e6-4f10-bc94-2a20520d1382`, `title='OpenAI GPT-5.6 Unifies
Enterprise Multimodal Workflows'`) as before this session began.

## 19. Readiness verdict for fresh live ContentDraft generation and M5 re-validation

**Automated gates are fully green.** Per the plan's own procedure, the next step —
generating one fresh `ContentDraft` via `scripts/run_content_generation.py` against a real
`NewsEvent`, confirming Cyrillic output, then re-running M5's live Telegram validation — requires
a real OpenAI API call and is **explicitly not authorized by this task**. Stopping here.

---

Awaiting explicit authorization for live validation (fresh `NewsEvent` → real generation call →
Cyrillic confirmation → M5 re-validation).
