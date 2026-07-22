# Russian Output — Live Acceptance Report

Narrowly-scoped live validation of the Russian output remediation. No production code, test,
prompt, or architecture was modified during this validation. Not committed or staged.

## Exact fresh NewsEvent used

`id = 68876ae8-7a45-4f1d-b798-7d4e0e6be12d` — English-language arXiv abstract, title *"In this
paper, we provide a systematic investigation of SO(2) theory to machine learning interatomic
potentials (MLIPs)"*, `category = UNKNOWN`, `created_at = 2026-07-15`. Selected via a read-only
query joining `ContentDraft → EditorialTask → NewsEvent` to find events with **zero** prior
`ContentDraft` anywhere in their history — confirmed exactly one event in the whole database
already had one (the Phase 10 M6 record); every other event, including this one, qualified as
genuinely fresh.

## Exact workflow/generation path

```
python -m scripts.run_content_generation 68876ae8-7a45-4f1d-b798-7d4e0e6be12d
  -> workflow_service.create_task(event_id=..., workflow_type=CONTENT_GENERATION)
  -> WorkflowRunner.run() via CapabilityExecutor (unmodified, real session, real registry)
  -> research -> intelligence -> copywriting -> quality (all four real Capability steps, in order)
  -> ContentDraftService.create_from_result()
```
The real, unmodified, already-authorized CLI entry point — no bypass of `CapabilityExecutor`, no
direct provider SDK call, no manual `ContentDraft` insertion.

## Real provider/model used

`enabled_providers = ["openai"]` (confirmed before running); terminal log shows exactly 4 real
`POST https://api.openai.com/v1/responses` calls, each `200 OK`. Model family: `gpt-5.6-*`
(`integrations/llm_gateway/models/catalog.py`'s registered catalogue) — the exact variant is
selected internally by `RoutingEngine`, not individually logged at `INFO` level; provider identity
(`openai`, real network call) is directly confirmed by the `httpx` log line itself.

## Copywriting prompt version

`3` — confirmed by the code already in place (`PROMPT_VERSION = "3"`, resolving
`prompts/copywriting/v3.yaml`); this run exercised that exact, already-implemented path.

## Target output language value

`"ru"` — `core.config.settings.default_content_language`'s default, explicitly injected by
`CapabilityExecutor._build_context()` into every step's `BusinessContext.language`, unmodified
since the implementation report.

## New ContentDraft ID

`6612ee70-0606-450c-8875-69b4d33a0e89` (`task_id = 718780ed-1d10-4a97-a385-b4826be06e68`,
`created_at = 2026-07-22 00:04:06.957047+00:00`).

## Actual persisted title/body language

Directly inspected (UTF-8, not the garbled console rendering caused by the Windows terminal's own
codepage):
```
title: Новые SO(2)-архитектуры для межатомных потенциалов
body:  Авторы систематически исследовали применение теории SO(2) к MLIP и предложили два новых
       блока: Edge Complex Product Basis для многочастичных взаимодействий и Radial Rotary
       Complex Attention для улучшения экстраполяции. Модель TECE-OAM-RRA-1.0, обученная на
       OMat24, sAlex и MPTrj, заявлена как SOTA на Matbench Discovery, однако метрики и детали
       сравнений не приведены.
hashtags: #MLIP #МашинноеОбучение #Материаловедение #АтомистическоеМоделирование
```
Cyrillic-character ratio (of alphabetic characters): title 95.2%, body 66.2% (the remainder is
technical Latin-script identifiers — `MLIP`, `SOTA`, `OMat24`, `TECE-OAM-RRA-1.0` — expected and
correct in a technical-content translation, not a defect), 3 of 4 hashtags fully Cyrillic (the
4th, `#MLIP`, is an acronym, correctly left as-is).

## Is the output genuinely Russian?

**Yes — confirmed two ways, not merely `language == "ru"` metadata.** (1) Direct human reading of
the actual persisted text: grammatically correct, fluent Russian prose, not a mechanical
transliteration or partial translation. (2) Beyond the required scope: the workflow's full
`step_results` were inspected and show `research`'s facts/gaps, `intelligence`'s
angle/audience_relevance/recommendation, and `quality`'s issues were **also** produced in fluent
Russian — even though only `CopywritingCapability` received the new, explicit, governed
instruction (the other four capabilities only got the corrected `"Target output language:"` label,
no imperative rule). This is a bonus positive observation, not a guarantee this remediation itself
established for those four steps — noted honestly, not overclaimed.

## Did `/news` display it?

**Yes**, confirmed live. `/news` sent once (Update id `837679379`, handled in 850 ms, no
exception). Read-only re-query immediately after confirmed **2 eligible cards**, newest-first: the
new Russian draft first, the historical English M6 draft second. User-confirmed, visually, in the
real Telegram client: 2 cards received; the newer card's title and body are genuinely Russian;
rendering is clean (bold formatting works, no literal `<b>` tags, no broken/garbled characters).

## Did Phase 11 change/transform/translate it?

**No — confirmed directly, and this is worth stating precisely rather than glossing over.** The
rendered card mixes two languages by design, not by accident: the header line (`news_category`,
`news_title`, `news_url` — sourced verbatim from the original English `NewsEvent`, which Phase 11
has never translated and was never asked to) remained in **English**; only `draft_title`/
`draft_body`/`hashtags` (the `ContentDraft` fields, i.e., `CopywritingCapability`'s own generated
output) are **Russian**. This is the correct, designed behavior — Phase 11's Contract (§12) reads
`news_title`/`news_category`/`news_url` straight from `NewsEvent` and `draft_title`/`draft_body`/
`hashtags` straight from `ContentDraft`, with zero transformation of either. This mixed-language
card is direct, positive proof that Phase 11 performs **no** translation of any kind — it displays
exactly what is stored, in whatever language each stored field happens to be in.

## AIExecution/accounting evidence

Zero `AIExecution` rows exist anywhere in the database (re-confirmed this session) — expected and
correct per Phase 6 Amendment B (`CapabilityExecutor` does not persist `AIExecution` rows in this
phase). Evidence instead comes from: the terminal log's 4 real `200 OK` HTTP calls, and the
persisted `EditorialTask.workflow` JSON's `step_results`, which records each step's real,
non-synthetic structured output content (quoted above) with real `started_at`/`finished_at`
timestamps spanning the actual call latencies (~4–16 seconds per step).

## Number of real AI calls made

**4** — exactly the minimum required: `research → intelligence → copywriting → quality`, the
CONTENT_GENERATION workflow's full, unskippable step chain (`WorkflowRunner` processes steps in
sequence; `copywriting` cannot run without `research`/`intelligence` having already completed).
Zero additional or exploratory calls were made.

## Files changed during validation

**Zero.** Two transient inspection files (`scratch_draft_output.json`, `scratch_task_workflow.json`,
plus one rendered-card preview, `scratch_rendered_card.txt`) were created in the repository root
to work around this session's terminal codepage garbling real Cyrillic output, then immediately
deleted after inspection — confirmed absent via `git status --short`, which is identical to the
state at the end of the implementation report.

## DB rows intentionally created by normal workflow

Exactly 2, both via the normal, unmodified, already-authorized `scripts/run_content_generation.py`
path — no manual insertion: one `EditorialTask` (`718780ed-1d10-4a97-a385-b4826be06e68`,
`CONTENT_GENERATION`, `COMPLETED`) and one `ContentDraft`
(`6612ee70-0606-450c-8875-69b4d33a0e89`).

## Confirmation: historical English draft untouched

Re-queried before and after the entire validation: `draft_id = 2190d42d-e6e6-4f10-bc94-2a20520d1382`,
`title = "OpenAI GPT-5.6 Unifies Enterprise Multimodal Workflows"` — byte-identical at every check
point, including after the live `/news` invocation.

## Git status

Identical to the end of the implementation report: 12 modified files (the remediation), 3 new
production/test files (`prompts/copywriting/v3.yaml` plus the two Phase 11 M2 files already
tracked as new from earlier milestones), no new file from this validation, nothing staged, nothing
committed.

---

## Final verdict

**PASS**

A fresh `NewsEvent` was carried through the real, unmodified `CapabilityExecutor` →
`LLMGateway` → real OpenAI provider path, using exactly 4 real AI calls (the workflow's minimum),
and produced a new `ContentDraft` whose AI-generated `title`/`body`/`hashtags` are genuinely,
fluently Russian — verified both programmatically (Cyrillic-character ratio) and by direct human
reading of the actual persisted text. `/news`, invoked once live, correctly surfaced this new
draft (newest-first, alongside the untouched historical English draft) and rendered it cleanly in
a real Telegram client — user-confirmed: 2 cards, genuinely Russian title/body, clean formatting,
no broken entities. Phase 11 was proven, not merely assumed, to perform zero translation: the
card's source-derived header remained English while only the AI-generated body became Russian,
exactly matching what each underlying field actually contains. The historical English
`ContentDraft` remains byte-for-byte unchanged. Zero files were left modified by this validation.
