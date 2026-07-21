# Phase 10 — Production AI Pipeline Discovery

**Status: discovery only. No production code, test, or migration was modified to produce this
document. No commit was created. This document does not authorize implementation.**

Every claim below is tagged **FACT** (direct repository evidence, cited by file/line),
**INFERENCE** (a reasoned conclusion drawn from one or more FACTs), **RECOMMENDATION** (a
proposed decision, not binding), or **OPEN QUESTION** (a genuine unresolved decision point this
document does not answer). HEAD at the time of this discovery: `89e111d` (Phase 9 + Phase 9.5
closure commit).

---

## 1. Executive Summary

**FACT**: this repository already contains a code-complete, real OpenAI provider adapter
(`integrations/llm_gateway/providers/openai_adapter.py`) implementing `generate()` against
OpenAI's live Responses API, and a frozen `CONTENT_GENERATION` workflow definition
(`workflows/definitions/content_generation.py`) whose first step (`"copywriting"`) has no
implementing Capability yet.

**INFERENCE**: the single smallest, most architecture-aligned next step is not "connect a
provider" (already done) and not "build a Publisher" (a real gap, but a second-order one) — it
is implementing `CopywritingCapability`, the exact missing piece that would let
`CONTENT_GENERATION` become the **first** `WorkflowType` in this entire system able to reach
`TaskStatus.COMPLETED` for real, using a pattern Phase 9 already proved twice (Research,
Intelligence).

**RECOMMENDATION**: Phase 10's boundary should be narrower than "production AI pipeline" as a
whole. Real LLM provider connection needs only configuration + one live smoke test, not new
code. Content generation needs one new Capability plus a small, new persistence/DTO layer for
`ContentDraft` (a model that already exists, unused). Telegram publishing and meme generation
each carry a genuine, unresolved architectural gap (who writes `ContentDraft`; where image
generation lives in a Gateway Protocol that has no image-output method) that should not be
decided inside an implementation milestone — they need their own, narrower discovery/decision
passes, mirroring exactly how Phase 9.5 was spun out of Phase 9 M7's own discovery.

---

## 2. Current Repository State

**FACT**: HEAD is `89e111d` ("Document Phase 9 and Phase 9.5 completion"). Phase 9 (M0–M7) and
Phase 9.5 (M1–M2) are committed and closed, per `docs/phase9_9_5_completion_report.md`.

**FACT**: registered Capabilities today (`capabilities/registry.py::build_registry()`):
`ScoringCapability` ("scoring"), `QualityCapability` ("quality"), `ResearchCapability`
("research"), `IntelligenceCapability` ("intelligence"). No fifth Capability exists.

**FACT**: registered `WorkflowType`s in the real, global registry (`workflows/registry.py:81-82`):
`NEWS_ANALYSIS` and `CONTENT_GENERATION`. `DAILY_DIGEST` is declared in the enum but deliberately
never registered (`schemas/workflow.py:17-28`).

---

## 3. Frozen Architecture Constraints

Restated from this task's own instructions, cited against repository evidence where a citation
strengthens the constraint:

- **Phase 5**: `workflows/runner.py`'s execution semantics (including Phase 9.5's own per-step
  persistence invariant) are frozen. **FACT**: no scheduler, resume verb, or crash-recovery
  mechanism exists anywhere in `workflows/`.
- **Phase 6**: **FACT**, verified via `scripts/validate_architecture.py`'s `capability-isolation`
  rule (lines 112-146): a Capability file may not import a provider SDK, `database.session`,
  `sqlalchemy`, `services.budget_guard`, `services.cost_tracker`, or `integrations.llm_gateway`'s
  internal cache/rate_limit/fallback/routing/providers modules, or anything under `workflows/`.
  This rule already applies to any new file placed under `capabilities/` with zero change needed.
- **Phase 8**: **FACT**, verified against `capabilities/scoring_capability.py` and
  `capabilities/research_capability.py` (both read this session): every existing Capability's
  shape is `__init__(gateway: LLMGateway, prompt_repository: PromptRepository)`, `execute()`
  returns `CapabilityResult` via the centralized `capabilities/gateway_call.py::call_generate()`
  mechanism.
- **Phase 9**: **FACT**: `capabilities/capability_mapping.py` (read this session) forbids
  Capability-to-Capability coupling; `IntelligenceCapability` consumes `ResearchCapability`'s
  output only via `context.business.workflow_state.step_results`, never a direct import.
- **Phase 9.5**: **FACT**: `workflows/runner.py`'s per-step persistence (added at line 189-199)
  means a later step's Capability can now observe an earlier step's `CapabilityResult` within
  one `run()` call — already proven for Research→Intelligence, and structurally identical for
  any future two-step chain (e.g., a future `copywriting`→`quality` chain already benefits from
  this without any further change).

---

## 4. LLM Gateway Analysis

**FACT**: `integrations/llm_gateway/providers/openai_adapter.py` implements `OpenAIAdapter`
against the real `openai` PyPI SDK (`AsyncOpenAI`), calling `client.responses.create(...)` (line
317) — OpenAI's Responses API, not the older Chat Completions API. `generate()` is fully
implemented, including structured-output (`json_schema`) support (lines 229-237), tool
definition translation (lines 206-213), and a complete `openai.OpenAIError` subtype →
`GatewayError` translation table (lines 119-171) with credential redaction (lines 106-116).
`generate_stream`/`embed`/`classify`/`moderate`/`rerank` all raise
`UnsupportedGatewayCapabilityError` (lines 335-359) — explicitly deferred, not broken.

**FACT**: `integrations/llm_gateway/boot.py::_build_provider_factories()` (line 136-140) wires
exactly one provider factory: `{OPENAI_PROVIDER_ID: build_openai_provider_factory()}`. No second
provider is wired.

**FACT**: `core/config.py` (`Settings`) already declares `openai_api_key: SecretStr | None = None`
(line 45) and `anthropic_api_key: SecretStr | None = None` (line 46), but only
`build_openai_credential()` (`integrations/llm_gateway/providers/base.py:45-54`) reads a
credential field — `anthropic_api_key` is read nowhere in the codebase (confirmed by the absence
of any `anthropic`-adapter file under `integrations/llm_gateway/providers/`).

**FACT**: `Settings.enabled_providers: list[str] = []` (line 55) — empty by default.
`build_provider_registry()` (`providers/base.py:127-152`) only constructs and registers a
provider that is **both** named in `enabled_providers` **and** has a present credential (line
147: `if not _credential_is_present(credential): continue`). No provider goes live without an
explicit environment/config change.

**FACT**: `scripts/validate_architecture.py:37-45` (`PROVIDER_SDK_MODULE_PREFIXES`) already lists
`openai`, `anthropic`, `google.generativeai`, `google.genai`, `ollama`, `cohere`, `mistralai` —
the architecture validator already anticipates and permits future adapters under any of these
names, confined to `integrations/llm_gateway/providers/<provider>_adapter.py`, with **zero
validator change needed** to add one.

**FACT**: `integrations/llm_gateway/models/catalog.py` catalogues exactly 3 real, priced OpenAI
text models (`gpt-5.6-sol`/`terra`/`luna`) with real per-million-token USD pricing (Sol
$5.00/$30.00, Terra $2.50/$15.00, Luna $1.00/$6.00, input/output respectively) and
`quality_tier` values (100/70/40). No image-generation model is catalogued anywhere.

**FACT**: `assemble_ai_integration_layer()` (`boot.py:143-219`) wires real, non-fake
infrastructure: `RedisProviderHealthStore`, `RedisLatencyTracker`, `RedisRateLimiter`,
`RedisCacheStore`/`CacheCoordinator`, `RedisBudgetGuard`, `RedisCostTracker` — all requiring a
running Redis instance. `RoutingPolicyRegistry` is seeded with `BestQualityPolicy`,
`LowestCostPolicy`, `FastestPolicy`, `ReasoningPolicy` (lines 188-193) — already-built,
already-wired model-selection strategies.

**FACT**: `GenerateRequest`/`GenerateResponse` (`integrations/llm_gateway/protocol.py:60-95`)
model chat/completion-style calls only. `ContentPart.artifact_ref` + `GenerateRequest.modalities`
(`Literal["text","image","audio"]`) are used, per `openai_adapter.py::_translate_content_part`
(lines 174-183), for **image input** ("input_image") — vision, not image generation. The
`LLMGateway` Protocol has no `generate_image()` (or equivalent) method.

**INFERENCE**: production OpenAI text-generation usage is close to "flip a switch" — set
`enabled_providers=["openai"]` and a real `openai_api_key` in the target environment. No new
Gateway-layer code is required for text-only Capabilities.

**INFERENCE**: no test in this repository has ever made a real network call to any LLM provider
(confirmed by this session's own repeated verification that every Capability test uses
`FakeLLMGateway`/`FakeProviderAdapter`, per the established Phase 7 §15.5 testing discipline) —
so the OpenAI adapter's correctness against the *live* API, despite its careful source-verified
construction, has not been empirically exercised in this repository.

**INFERENCE**: Anthropic/Gemini/other-provider integration is not "prepared" beyond a placeholder
config field and a validator-level namespace reservation — a real adapter is a from-scratch build
(bounded, since `OpenAIAdapter` is a complete, provable template), not a configuration change.

**RECOMMENDATION**: Phase 10 must not modify `LLMGateway`'s Protocol, `RoutingGateway`,
`FallbackPolicy`, or any other Phase 6/7 frozen file to enable real usage — only (a) set
production configuration (`enabled_providers`, `openai_api_key`), (b) provision Redis/Postgres in
the target environment, and (c) run one deliberate, out-of-band live smoke test (never inside the
automated suite, mirroring this repository's own established no-real-network-call discipline).

**OPEN QUESTION**: does Phase 10 require a second provider (Anthropic/Gemini) at all, or is
OpenAI-only sufficient to begin production usage? No repository evidence answers this — it is a
product decision.

---

## 5. Capability Layer Analysis

**FACT**: `capabilities/capability_mapping.py` (`_CAPABILITY_NAME_TO_AI_CAPABILITY`, read this
session and in Phase 9) already maps `"copywriting"` → `AICapability.COPYWRITING` and
`"creative"` → `AICapability.CREATIVE`. `database/models/ai_execution.py`'s `AICapability` enum
(lines 14-23) already includes `COPYWRITING` and `CREATIVE` members, alongside `RESEARCH`,
`INTELLIGENCE`, `TREND`, `SCORING`, `QUALITY`.

**FACT**: `workflows/definitions/content_generation.py` (frozen since Phase 5) defines
`WorkflowType.CONTENT_GENERATION` with exactly two steps: `WorkflowStepDefinition(name=
"copywriting", capability="copywriting", ...)` then `WorkflowStepDefinition(name="quality",
capability="quality", ...)` (lines 19-20). `quality` is **already implemented and registered**
(`QualityCapability`, Phase 8 M7).

**FACT**: no file matching `capabilities/*copywriting*`, `capabilities/*content*`, or
`capabilities/*meme*` exists anywhere in the repository.

**INFERENCE**: implementing a `CopywritingCapability` — an ordinary Phase 8 Capability,
`__init__(gateway, prompt_repository)`, mapped to the already-existing `"copywriting"` name —
would make `CONTENT_GENERATION` the first `WorkflowType` in this system's history able to reach
`TaskStatus.COMPLETED` for real (both of its steps would then be registered Capabilities). This
is structurally identical to how Phase 9 M4/M5 added Research/Intelligence into
`NEWS_ANALYSIS`'s already-frozen step names — zero workflow-definition change, zero
`CapabilityExecutor` change, a `build_registry()` two-line addition (Phase 8 M7's own precedent,
reused three times already).

**RECOMMENDATION**: name the new Capability `CopywritingCapability`, not
`ContentGenerationCapability` — matching the existing, frozen `"copywriting"` step/capability
name exactly, avoiding a second, parallel vocabulary for the same concept (the same principle
Phase 9's Contract enforced for `TaskPriority` vs. a hypothetical parallel priority enum).

**OPEN QUESTION — MemeCapability placement**: should meme generation be a `ContentType.MEME`
branch inside `CopywritingCapability`, or a distinct Capability/workflow step? Repository evidence
(§8 below) suggests a **distinct** Capability, because meme generation's hard part — actual image
rendering — has no representable path through today's `LLMGateway.generate()` shape at all, making
it a structurally different kind of work from text copywriting, not a stylistic variant of it. This
document does not decide the question, only surfaces the evidence bearing on it.

---

## 6. Content Pipeline Analysis

**FACT**: `database/models/content_draft.py` already defines `ContentDraft` (table
`content_drafts`) with `task_id` (FK → `editorial_tasks.id`), `type` (`ContentType` enum: `POST`,
`SHORT`, `ANALYSIS`, `MEME`, `VIDEO_SCRIPT` — `MEME` already present), `title`, `body`,
`hashtags` (JSON), `version` (int, default 1), `status` (free-text, per the model's own comment:
"status values are not enumerated in the project documentation... stored as free-form text
rather than a constrained enum to avoid inventing business rules").

**FACT**: `ContentDraft`/`content_draft` is referenced in exactly two places repository-wide: its
own migration (`database/migrations/versions/fbb55860708f_add_pipeline_infrastructure_tables.py`)
and `database/models/__init__.py`. No service, capability, or schema reads or writes it.

**FACT**: no `schemas/content_draft.py` exists — `schemas/` (read this session) contains
`raw_news_item.py`, `source_import.py`, `source_definition.py`, `workflow.py`,
`editorial_task.py`, `capability.py`, `capability_definition.py` — every existing DB-backed model
that has production read/write traffic has a matching Pydantic schema module; `ContentDraft` does
not.

**INFERENCE**: `ContentDraft`'s existing columns are sufficient for a first content-generation
slice (title/body/hashtags/version/status) — no migration should be required to store
`CopywritingCapability`'s output. This satisfies the "no new database models unless absolutely
unavoidable" instruction for at least the text-content case.

**FACT**: `services/workflow_service.py` (`create_task()`/`get_task()`, read this session) is the
established, minimal precedent for a "scoped, two-function service" owning one model's
create/read lifecycle, with Pydantic DTOs at its boundary (`EditorialTaskCreate`/
`EditorialTaskRead`) and no ORM object crossing it.

**RECOMMENDATION**: add `schemas/content_draft.py` (mirroring `schemas/editorial_task.py`) and a
correspondingly scoped `services/content_draft_service.py` (mirroring `workflow_service.py`'s own
shape) before or alongside `CopywritingCapability`.

**OPEN QUESTION — who writes `ContentDraft`?** Per Phase 6 P1/P4 (verified unbroken across every
existing Capability), a Capability never holds a database session, so `CopywritingCapability`
itself cannot persist a `ContentDraft` row. Two structurally different answers exist, neither
decided by repository evidence: (a) `CapabilityExecutor` (frozen Phase 6) gains a new
responsibility to persist a `ContentDraft` after a `"copywriting"` step succeeds — but this is a
change to a frozen file, requiring the same kind of contract-amendment process Phase 9.5 used for
`WorkflowRunner`; or (b) a separate, new, `services/`-layer step — invoked *after*
`WorkflowRunner.run()` returns a `COMPLETED` `WorkflowRunResult`, reading `step_results["
copywriting"]` from the result already in hand — persists the `ContentDraft`, with zero change to
any frozen Phase 5/6 file. Option (b) is the smaller, non-frozen-file-touching option, but this
document does not select between them.

---

## 7. Telegram Integration Analysis

**FACT**: `bot/` is an `aiogram`-based Telegram **Bot API** polling client (`bot/main.py`,
`dp.start_polling(bot)`). `bot/handlers/` contains `start.py`, `news.py`, `digest.py`,
`status.py`, `settings.py` — all inbound command handlers. `bot/handlers/digest.py` (read this
session, full file) is a literal placeholder: `PLACEHOLDER_TEXT = "This functionality will be
implemented in the next development phases."`.

**FACT**: no `integrations/telegram/` directory exists (confirmed by `Glob` returning zero
matches).

**FACT**: `services/adapter_keys.py`, `tests/test_adapter_keys.py`, and
`tests/test_source_pack_importer.py` are the only other `TelegramChannel`/`telegram_channel`
references repository-wide, and all concern **source collection** (Telethon, the Telegram
**Client** API, gated by `telegram_api_id`/`telegram_api_hash`/`telegram_session_string`) — an
entirely separate credential and API surface from `telegram_bot_token` (Bot API). `core/
config.py:67` states this explicitly: "Fully separate from telegram_bot_token, which is Bot API
and belongs to bot/."

**FACT**: no publishing/outbound service exists anywhere — `services/` (18 files, enumerated this
session) contains no `publish`/`telegram_publish`/`channel_publisher`-named module.

**INFERENCE**: a genuinely new component — a Publisher Service — is required. It does not yet
exist in any form, not even a placeholder.

**RECOMMENDATION**: the pipeline this task's own prompt proposed —
`Capability → ContentDraft → Publisher Service → Telegram API` — is consistent with existing
repository patterns: Capabilities already never call any external system except `LLMGateway`
(verified unbroken across all 4 existing Capabilities); a `services/`-layer Publisher, reusing
`bot/loader.py::create_bot()` for the `Bot` instance and calling `bot.send_message`/`send_photo`
against a `TelegramChannel.telegram_chat_id`, is the direct structural analog to
`services/collector.py`'s existing role for **inbound** collection — the same layer, symmetric
direction.

---

## 8. Meme Generation Analysis

**FACT** (restated from §4/§5/§6, load-bearing here): (a) `ContentType.MEME` already exists as a
schema value with zero consuming code; (b) no image-generation model is catalogued in
`integrations/llm_gateway/models/catalog.py`; (c) `LLMGateway`'s Protocol has no image-output
method — `generate()` is chat/completion-shaped; `ContentPart.artifact_ref` is currently used only
for image **input**, never output.

**INFERENCE**: the proposed pipeline shape —
`NewsEvent → IntelligenceCapability → MemeOpportunityCapability → MemeDraft → ImageGenerationProvider → Telegram Publisher`
— is directionally consistent with existing architecture for its **first three stages**
(Capability → structured output → persisted draft, exactly `CopywritingCapability`'s own shape),
but its **fourth stage has no home in the current frozen Gateway abstraction**. Two structurally
different resolutions exist, neither authorized by any current contract: (a) amend the Phase 6
`LLMGateway` Protocol to add an explicit image-generation method — a binding contract change,
requiring the same amendment discipline Phase 9.5 used for `WorkflowRunner`; or (b) build a
deliberately separate, parallel integration (e.g. `integrations/image_gateway/`) that is **not**
an `LLMGateway`/`ProviderAdapter` implementation at all, with its own, analogous
provider-SDK-confinement rule — never a provider SDK reference held directly inside a Capability,
mirroring `provider-sdk-confinement`'s existing, mechanically-enforced boundary
(`scripts/validate_architecture.py:158-164`).

**INFERENCE**: `MemeOpportunityCapability` itself — a text-only Capability judging whether/what
meme concept fits a given `NewsEvent`'s already-extracted Research/Intelligence output — is
buildable today with **zero** new architecture, exactly like `ResearchCapability`/
`IntelligenceCapability` were. Only the subsequent image-**rendering** stage carries the
unresolved architectural question above.

**RECOMMENDATION**: meme generation should not be Phase 10's first milestone. Its
text-only "opportunity detection" half has no blocking dependency and could ship alongside
`CopywritingCapability` using the identical pattern; its image-rendering half has a genuine,
undecided architectural question that this discovery document surfaces but does not resolve.

**OPEN QUESTION**: should Phase 10 ship `MemeOpportunityCapability` (text-only, judges + produces
a `MemeDraft` concept) while explicitly deferring image rendering to a later, narrower
decision/discovery pass — mirroring exactly how Phase 9.5 was spun out of Phase 9 M7's own
discovery, rather than folding an unresolved Protocol-amendment question into Phase 10's main
scope?

---

## 9. API Cost Considerations

**FACT**: real, current per-million-token pricing (USD, standard tier) exists for exactly three
models: GPT-5.6 Sol $5.00 in / $30.00 out (quality_tier 100), Terra $2.50 / $15.00 (quality_tier
70), Luna $1.00 / $6.00 (quality_tier 40) — `integrations/llm_gateway/models/catalog.py:41-96`.

**INFERENCE, illustrative only — explicit assumptions stated, not a forecast**: at 1000
news/day, assuming ~800 input + 400 output tokens per Research call and ~600 input + 300 output
per Intelligence call (rough orders of magnitude for a structured-extraction/judgment prompt over
a single article, not measured from any real run in this repository):

| Stage | Model tier (existing `RoutingPolicy`) | Illustrative cost / 1000 events |
|---|---|---|
| Research (bulk extraction) | Luna (`LowestCostPolicy`) | ≈ $3.20/day |
| Intelligence (editorial judgment) | Terra (`BestQualityPolicy`/`ReasoningPolicy`, if reasoning matters) | ≈ $2.85/day |
| Copywriting (final content) | Terra or Sol depending on desired output quality | ≈ $3–9/day (Terra low end, Sol high end, at ~500 in / 400 out) |
| Meme opportunity (text-only judgment) | Luna | ≈ $1–2/day |
| Meme image rendering | **no data — no model catalogued** | not estimable from repository evidence |

**RECOMMENDATION**: this per-Capability tier choice needs no new mechanism —
`ExecutionContext.preferred_model`/`preferred_provider` (`schemas/capability.py`, already used by
every existing Capability's `_build_request()`) combined with the already-registered
`LowestCostPolicy`/`BestQualityPolicy`/`FastestPolicy`/`ReasoningPolicy`
(`integrations/llm_gateway/routing/policy.py`, wired in `boot.py:188-193`) is the existing,
sufficient mechanism. Phase 10 should choose per-Capability policy/model preference, not build new
routing infrastructure.

**FACT**: `CacheCoordinator`/`RedisCacheStore` (Phase 7) are already wired into
`assemble_ai_integration_layer()`. **RECOMMENDATION**: new Capabilities' prompts should be
structured so repeated near-identical requests (e.g., re-triaged or retried events) benefit from
this existing cache, rather than building a second caching layer.

**OPEN QUESTION**: real per-call token counts for Research/Intelligence/Copywriting have never
been measured against a live API call in this repository (§4's "no real network call" finding) —
the table above cannot be validated until Phase 10's own live smoke test runs.

---

## 10. Risks

- **INFERENCE**: this repository has never made a real network call to an LLM provider in any
  test; the first real call in any environment is inherently the point where source-verified-but-
  never-executed code (the OpenAI adapter) meets reality. **RECOMMENDATION**: a single, deliberate,
  manually-run smoke test (never part of the automated suite) should be Phase 10's first concrete
  action, before any Capability is built on top of it.
- **FACT**-grounded: `enabled_providers` defaults to `[]` — a safe default. **RISK**: enabling it
  in a shared/CI environment by accident (e.g., a misconfigured `.env`) would start making real,
  billed API calls; this is an operational risk, not a code risk, but worth naming.
- **RISK**, directly tied to §8's finding: implementing meme image generation by holding a
  provider SDK reference (e.g., a raw `openai.Image` call) directly inside a Capability would
  violate the mechanically-enforced `capability-isolation` and `provider-sdk-confinement` rules —
  a concrete, checkable violation this document flags in advance, not a hypothetical.
- **RISK**, tied to §6's open question: persisting `ContentDraft` from inside `CapabilityExecutor`
  (frozen Phase 6) without a contract amendment would repeat the exact kind of undisclosed-scope
  problem Phase 9.5's own discovery process was built to catch — any `ContentDraft`-write
  mechanism should go through the same discovery→decision→contract→audit sequence this repository
  has now used twice.
- **FACT**-grounded: `CONTENT_GENERATION` is already registered in the real, global
  `WorkflowRegistry` (`workflows/registry.py:82`), but **FACT**: zero production code
  (`services/`, `scripts/`, `bot/`, `capabilities/`) creates a task with
  `WorkflowType.CONTENT_GENERATION` anywhere (confirmed by repository-wide grep). **RISK**:
  implementing `CopywritingCapability` alone does not produce any end-to-end value without
  *something* triggering a `CONTENT_GENERATION` task — this must be scoped explicitly (even a
  manual/API-triggered creation, deliberately short of a "scheduler," would suffice for a first
  slice) or Phase 10's first milestone will ship inert code.

---

## 11. Recommended Phase 10 Boundary

**RECOMMENDATION, derived from the evidence above, not assumed in advance**: the smallest correct
Phase 10 is narrower than the full "production AI pipeline" — it should stop at proving
`CopywritingCapability` end-to-end, deliberately deferring Telegram publishing and meme image
generation to their own, later discovery/decision passes, exactly mirroring the Phase 9 →
Phase 9.5 precedent this repository already established.

| # | Title | Depends on | Rationale |
|---|---|---|---|
| M0 | Production LLM provider verification | — | Configuration + one live, manual smoke test against the real OpenAI API. No new code. Closes the "never actually called a real provider" gap before anything is built on top of it. |
| M1 | `CopywritingCapability` | M0 | Ordinary Phase 8 Capability, mapped to the already-existing `"copywriting"` name — zero workflow-definition change, zero `CapabilityExecutor` change, a `build_registry()` two-line addition. Makes `CONTENT_GENERATION` completable for the first time. |
| M2 | `ContentDraft` schema + service layer | M1 (or parallel) | `schemas/content_draft.py` + a scoped `services/content_draft_service.py`, resolving §6's "who writes `ContentDraft`" open question with a concrete, non-frozen-file-touching design — a genuine decision point requiring its own short discovery/decision note, not assumed here. |
| M3 | Manual/API-triggered `CONTENT_GENERATION` task creation | M1, M2 | Closes §10's "inert code" risk — deliberately NOT a scheduler; the smallest trigger that produces real, observable end-to-end value. |

**Explicitly excluded from this Phase 10 boundary, per this discovery's own findings**: Telegram
Publisher Service (§7 — real gap, but independently schedulable once M2 exists); `MemeOpportunityCapability`
(§8 — architecturally clean, but has no consumer without a Publisher); meme image generation (§8
— has a genuine, unresolved Protocol-level question that must not be decided inside an
implementation milestone); a second LLM provider (§4, open question, no evidence requires it yet);
any scheduler (explicitly frozen, Phase 5).

---

## 12. Open Questions

Consolidated from §4–§9, for explicit visibility, not re-argued here:

1. Does Phase 10 require a second LLM provider (Anthropic/Gemini), or is OpenAI-only sufficient?
2. Should `MemeCapability` be a distinct Capability/workflow step, or a `ContentType.MEME` branch
   inside `CopywritingCapability`?
3. Who persists `ContentDraft` — a new `CapabilityExecutor` responsibility (frozen-file
   amendment) or a new, separate post-`run()` service (no frozen-file change)?
4. Should meme image generation be pursued via a Phase 6 `LLMGateway` Protocol amendment, or a
   deliberately parallel, non-Gateway `integrations/image_gateway/`-style integration?
5. Should Phase 10 ship `MemeOpportunityCapability`'s text-only half while explicitly deferring
   image rendering to a later, narrower phase?
6. What is the smallest acceptable "trigger" for `CONTENT_GENERATION` tasks in a first
   production slice — manual, API-triggered, or something else short of a scheduler?

---

## 13. Final Discovery Verdict

**FACT**: no production file, test, or migration was modified to produce this document; `git
status --short` shows only new, untracked documentation files throughout this discovery.

PHASE 10 DISCOVERY COMPLETE — WAITING FOR REVIEW.
