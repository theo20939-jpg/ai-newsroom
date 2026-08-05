# Phase 18 M0 — Meme Intelligence & Generation: Discovery Report

Status: complete. No production code changed in this milestone — read-only repository audit,
architecture recommendation, and a real-data meme-suitability taxonomy only.

## 1. Scope of this milestone

Per the Phase 18 brief: audit the post-Phase-17 repository, identify reuse points, decide where
the meme pipeline should attach, run a read-only meme-suitability audit against real news
samples, and produce a taxonomy + architecture recommendation. No workflow/capability/schema/DB
code is added in M0.

Environment note: the local Postgres/Redis stack (docker compose) is not running in this session
(`docker ps` fails to reach the Docker Engine). A live DB query for the "real-events audit" was
therefore not possible. Section 6 instead uses `scripts/_phase17_m0_manual_audit_text.json` — 32
real, already-fetched NewsEvent records (title/content/category/source) captured during Phase 17's
own M0 manual audit and left on disk as an untracked scratch file — as a representative, honest
substitute. It spans 7 real production categories (AI, TECH, GADGETS, STARTUPS, HARDWARE,
SOFTWARE, UNKNOWN) across RSS/Telegram/NEWS_API sources. This is disclosed as a directional
sample (n=32), not a statistically powered study; Appendix A lists every item and its
classification so the reasoning is auditable.

## 2. Repository state after Phase 17

`git log` confirms Phase 17 (Editorial Intelligence) is the last completed phase on `main`'s
lineage; this session branched `feature/phase18-meme-intelligence` off
`feature/phase17-editorial-intelligence` at commit `8872624` ("Add Phase 17 final completion
report and final Stage 2 validation"). No tracked files are modified — `git status` shows only
untracked Phase 15/17 scratch JSON/py files left over from those phases' own manual audits, none
of which this milestone touches. Phase 17's production behavior (Fact Safety calibration,
Editorial Completeness, Channel Relevance, Adaptive Length, Beginner-Friendly copy) is unchanged.

## 3. What already exists and can be reused

### 3.1 Capability Framework (Phases 6–10) — reusable as-is

- `capabilities/registry.py::CapabilityRegistry` — sealed registry of `(CapabilityDefinition,
  Capability)` pairs, built once at boot via `build_registry(gateway, prompt_repository,
  budget_guard, tool_registry)`. Currently registers exactly 6 capabilities: research,
  intelligence, scoring, copywriting, quality, engagement.
- `capabilities/executor.py::CapabilityExecutor` — the sole bridge from `WorkflowRunner` to a
  `Capability`. It resolves a step's `capability` name to an `AICapability` enum value via
  `capabilities/capability_mapping.py`, invokes `capability.execute(context)`, records cost
  (`services/cost_recording.py` + `services/cost_tracker.py`), and — critically — runs a chain
  of **additive, deterministic, zero-new-LLM-call "shadow hooks"** after specific steps
  (`_attach_editorial_brief`, `_attach_channel_relevance`, `_attach_image_intelligence`,
  `_attach_adaptive_length_plan`, `_attach_beginner_friendly_plan`,
  `_attach_editorial_completeness`). Every hook: (a) is gated by its own `settings.*_mode`
  flag defaulting to `"off"`; (b) reads only already-computed `step_results` plus the current
  step's own `structured_output`; (c) is wrapped in `try/except` and **never** fails the
  workflow step on error; (d) writes one new top-level key into `structured_output`, which then
  becomes part of the persisted `WorkflowStepResult.result` JSON on `EditorialTask.workflow`.
  This is the single most important reusable seam in the codebase for Phase 18 — see §5.

- `capabilities/capability_mapping.py` — the one place a workflow step's `capability` string name
  maps to the DB-persisted `AICapability` enum. **Finding:** `database/models/ai_execution.py`'s
  `AICapability` enum already contains `CREATIVE`, which is registered in the enum but has **no
  capability name mapped to it anywhere** in `_CAPABILITY_NAME_TO_AI_CAPABILITY`. This value is
  an unused, ready-made cost-tracking bucket for Phase 18's new creative-generation calls, with
  zero Alembic migration required (§7).

- `schemas/capability.py` — `CapabilityContext`/`CapabilityResult`/`CapabilityCall`. One
  structural constraint worth flagging early: `CapabilityCall.gateway_method` is a closed
  `Literal["generate", "generate_stream", "embed", "classify", "moderate", "rerank"]` — there is
  no `"generate_image"` value. See §4.2.

### 3.2 Workflow Engine (Phase 5) — reusable as-is

- `schemas/workflow.py::WorkflowType` is a plain Python `str, Enum` serialized into
  `EditorialTask.workflow` (a JSON column) — **not** a Postgres-native enum type. `DAILY_DIGEST`
  is already declared-but-unregistered as a forward-compatibility precedent for exactly this
  pattern. Adding `WorkflowType.MEME_GENERATION` requires a one-line enum addition and zero
  migration.
- `database/models/editorial_task.py::EditorialTask` is generic: `id`, `event_id`, `priority`,
  `workflow` (JSON), `status`, `retry_count`. Nothing here is CONTENT_GENERATION-specific. A new
  `WorkflowType.MEME_GENERATION` can reuse this table directly for task tracking — no new
  "MemeTask" entity needed.
- `workflows/definitions/content_generation.py` / `news_analysis.py` show the exact declarative
  shape a new `WorkflowDefinition` needs (ordered `WorkflowStepDefinition`s, retry policy,
  timeouts, `required_input`/`expected_output`).

### 3.3 Cost tracking / budget (Phases 6–7, API cost optimization) — reusable as-is

- `services/cost_tracker.py` (`RedisCostTracker`), `services/budget_guard.py`
  (`RedisBudgetGuard`), `services/pricing_catalog.py`, `services/cost_recording.py`
  (`record_ai_execution` → durable `AIExecution` row). All are capability-name-agnostic; any new
  capability automatically gets cost visibility and budget gating for free, provided it is
  registered and mapped through `capability_mapping.py` like every existing one. `llm_budget_mode`
  already defaults to `"shadow"` (compute+log, never block) — the same safe-by-default posture
  Phase 18 needs.

### 3.4 Editorial Telegram preview (Phases 11, 14, 16) — reusable pattern, not reusable code

- `services/telegram_notifier.py::send_editorial_card()` — dry-run-first delivery of a single
  card; `dry_run=True` renders and logs the exact payload without ever calling the Telegram API.
  This exact contract (`NotificationOutcome(sent=False)` in dry-run, real send only when
  `dry_run=False` **and** a chat id is configured) is the template Phase 18 M8 must copy for meme
  previews — never sending without the operational dry-run flag explicitly flipped, which is a
  human/config action, not something this milestone changes.
- `bot/handlers/image_preview.py` + `bot/keyboards/image_preview.py` + `services/image_persistence.py`
  (`get_editorial_image_candidates`, `set_editor_decision`, `reject_all_candidates`,
  `record_telegram_file_id`) — Phase 16 M6's interactive Telegram approve/reject/paginate flow.
  This is the concrete precedent for M8's editor actions (approve / reject / regenerate): a
  `callback_data`-driven `Router`, state re-queried fresh from the DB on every callback (never
  trusted from render time), one message per artifact, edited in place. Phase 18 should mirror
  this shape with a new `memeprev:` callback prefix and its own keyboard module — the code itself
  is image-candidate-specific and is not directly importable.
- `services/editorial_inbox_service.py` — read-only `/news` inbox query pattern (explicitly MUST
  NOT trigger AI generation or mutate state) — a template for a possible `/memes` inbox command,
  optional and not required for M8's core loop.

### 3.5 Fact Safety / editorial-judgment patterns (Phases 15, 17) — reusable as input, not as-is

- `services/fact_safety.py`, `services/candidate_fact_safety.py`,
  `services/fact_safety_calibration.py` (`calibrate_fact_safety`) — deterministic, zero-LLM
  factual-claim auditing already computed at the CONTENT_GENERATION "quality" step for ordinary
  drafts. Phase 18 M3's "originality/safety gate" is a **different concern** (meme-specific harm
  categories: death/tragedy/war/crime-with-victims/minors/protected-characteristics/unconfirmed-
  accusations, plus originality-vs-copying) and needs its own classifier, but should **reuse the
  calibrated Fact Safety *output*** as one input signal (a drafted meme about a story Fact Safety
  already flagged raw/unresolved should never reach `MEME_READY`).
- `services/editorial_brief.py`, `services/channel_relevance.py`, `services/editorial_completeness.py`
  — each is a small, self-contained deterministic classifier operating over
  `(news_event.title, news_event.content, research_output, ...)`, attached via the executor hook
  pattern above. Phase 18 M1 (Meme Opportunity Detection) should be built as exactly one more
  member of this family, not a new mechanism.

### 3.6 Image handling (Phase 16) — reusable storage backend, NOT a generation path

This is the discovery's single most consequential finding, and it corrects an assumption in the
Phase 18 brief.

**Phase 16 "Image Intelligence" is media *discovery and validation from already-published
sources* — never image *generation*.** Concretely:
- `services/image_intelligence.py` extracts native media hints from Telegram/RSS payloads
  already in hand, fetches article pages/candidate bytes through the SSRF-safe boundary
  (`integrations/http/safe_fetch.py`), and technically/qualitatively validates them.
  Its own module docstring states plainly: *"Zero LLM/provider call anywhere in this module."*
- `database/models/image_candidate_record.py::ImageCandidateRecord` models *provenance from a
  NewsSource* (`source_type`, `discovery_method`, `remote_url`, `article_url`) plus quality/
  dedup/relevance scoring against *other candidates for the same event*. None of this shape fits
  an AI-generated image, which has no `NewsSource`, no `remote_url` to fetch, no duplicate-
  candidate set to rank against.
- `integrations/storage/image_storage.py::ImageStorage`/`LocalImageStorage` (content-addressed,
  keyed by `build_storage_key(sha256, image_format)`) **is** generically reusable — it stores
  arbitrary image bytes by hash, with no assumption about where the bytes came from. Phase 18 M5/
  M6 should write generated/rendered meme bytes through this exact abstraction.
- `integrations/llm_gateway/providers/openai_adapter.py::OpenAIAdapter` exposes exactly six
  methods: `generate`, `generate_stream`, `embed`, `classify`, `moderate`, `rerank` — matching
  `CapabilityCall.gateway_method`'s closed `Literal` (§3.1). **There is no image-generation
  method anywhere in the LLM Gateway, and no other provider adapter exists.** grep for
  `image_generation|generate_image|dall.e|dalle|stable.diffusion|imagen\b` across the entire
  repository returns zero matches outside this phase's own new discovery.

**Consequence for M5:** "use the already-existing approved image-generation path" (as stated in
the brief) is not literally possible — no such path exists yet. The correct, minimal-blast-radius
move is to extend the Gateway along its *existing seam* (one new adapter method + one new
`CapabilityCall.gateway_method` literal value + one new request/response schema pair, mirroring
`generate()`'s exact shape) rather than inventing a parallel calling convention. This is still
"no direct provider calls from business logic" and "use the existing LLM Gateway" in spirit — it
is filling a genuine, disclosed gap in that Gateway along its own established pattern, not a new
architecture. Full engineering (adapter method, schemas, capability, cost estimation, dry-run
mode) can be completed with zero live calls; the first real provider call is a paid-run
authorization boundary (§9).

### 3.7 Existing meme-related code/docs

None. The only pre-existing hit for "meme" anywhere in the repository is
`database/models/content_draft.py::ContentType.MEME` — see §3.8. No prompts, no schemas, no
services, no docs mention memes anywhere before this report.

### 3.8 ContentDraft — a striking pre-existing reuse point

`database/models/content_draft.py::ContentType` already declares:
```python
class ContentType(str, enum.Enum):
    POST = "POST"
    SHORT = "SHORT"
    ANALYSIS = "ANALYSIS"
    MEME = "MEME"
    VIDEO_SCRIPT = "VIDEO_SCRIPT"
```
`ContentType.MEME` has existed, unused, since `ContentDraft` was introduced — the schema already
anticipated this content type. `ContentDraft` (`task_id`, `type`, `title`, `body`, `hashtags`
JSON, `version`, `status` free text) is the natural home for the **final, approved** meme's
human-readable text once it reaches the editorial inbox — but see §7 for why the *in-flight*
meme-candidate state (concept, safety verdict, image reference, regeneration count, cost, human
feedback taxonomy) needs a dedicated table rather than being force-fit into these five columns.

### 3.9 Settings conventions (`core/config.py`)

Every Phase 15–17 additive feature uses the identical `Literal["off", "shadow", ...]` mode-flag
pattern, always defaulting to `"off"`/`"shadow"` (never enforcing/live by default):
`fact_safety_mode`, `image_intelligence_mode`, `editorial_brief_mode`, `channel_relevance_mode`,
`adaptive_length_mode`, `beginner_copywriting_mode`, `editorial_completeness_mode`,
`image_candidate_persistence_mode`. Phase 18 will add new flags in exactly this shape
(`meme_opportunity_mode`, `meme_pipeline_mode`, `meme_image_generation_mode`,
`meme_telegram_preview_mode`, all defaulting to `"off"`), never repurposing an existing flag.

## 4. Where should the meme pipeline attach?

Three options were evaluated, per the brief's own question.

### 4.1 Additive hook to existing CONTENT_GENERATION (rejected as the sole mechanism)
Suitable only for M1 (Opportunity Detection): it is deterministic, zero-LLM, and cheap enough to
run on every CONTENT_GENERATION "quality" step, exactly like `_attach_editorial_completeness`.
**Not suitable** for M2 onward: concept/copy generation, image generation, rendering, and a
regenerate loop are expensive, meme-specific, and must not run on every ordinary news item that
happens to pass through CONTENT_GENERATION. Forcing them into that workflow would violate "не
ломать существующий pipeline" by adding latency/cost/risk to every content draft.

### 4.2 New Capability Chain inside CONTENT_GENERATION (rejected)
Adding meme steps as extra CONTENT_GENERATION steps was rejected for the same reason as 4.1 plus
one more: CONTENT_GENERATION's `WorkflowRunner` has no concept of "only run this step if a prior
step's shadow output says MEME_READY" — steps are unconditional in the current engine. Introducing
conditional step execution would be a real architecture change to the Workflow Engine itself,
which the brief explicitly says to avoid unless necessary.

### 4.3 Separate WorkflowType.MEME_GENERATION (recommended)
- Reuses `EditorialTask`/`WorkflowRunner`/`CapabilityExecutor` completely unmodified structurally.
- A new `EditorialTask` (workflow=`MEME_GENERATION`) is created only for events M1's shadow
  assessment (running inside the existing CONTENT_GENERATION quality step, or standalone against
  NEWS_ANALYSIS-completed events — implementation choice for M1) marks `MEME_READY`/`REVIEW` —
  mirrors exactly how `services/analysis_reuse.py` already lets a CONTENT_GENERATION task reuse a
  prior NEWS_ANALYSIS task's results for the *same* `event_id`. No new spawn mechanism needed;
  the existing "create an EditorialTask for workflow X against event_id Y" call path
  (`scripts/run_content_generation.py`'s own pattern) is reused for a new `workflow_name` value.
- Steps: `meme_concept` (LLM, new `MemeConceptCapability`) → `meme_copywriting` (LLM, new
  `MemeCopywritingCapability`) → `meme_safety_originality` (deterministic gate, executor
  post-hook, like `_attach_editorial_completeness`) → `meme_image` (new capability wrapping the
  new Gateway image method, §4.2/§3.6) → `meme_render` (deterministic, local, Pillow-based
  overlay, no LLM) → `meme_quality_gate` (deterministic gate, decides
  READY_FOR_EDITOR/REVIEW/REGENERATE_*/REJECT, bounded by the Workflow Engine's own existing
  `max_iterations` ceiling — no new retry mechanism invented).
- Capability-name → AICapability mapping (§3.1): `meme_concept` → `AICapability.CREATIVE`
  (reuses the already-declared-but-unused enum value — zero migration), `meme_copywriting` →
  `AICapability.COPYWRITING` (semantically correct reuse of the existing value — the copy step
  really is copywriting), `meme_image` → `AICapability.CREATIVE` as well (an image-generation
  call is exactly as "creative" as a concept call; introducing a 7th enum value purely to
  distinguish two creative sub-types would be the one avoidable migration in this phase — the
  cost row's `capability_name`/`workflow_name`/`model` string columns already disambiguate the
  two at the `AIExecution` audit-row level without needing a distinct enum member).

This keeps the change surface to: one new `WorkflowType` member (code, no migration), five new
`capabilities/*.py` files following the exact `CopywritingCapability` shape (`__init__(gateway,
prompt_repository)`, one `call_generate`, floor-validation, no cross-capability imports), two new
entries in `capability_mapping.py` (code, no migration), one new `workflows/definitions/
meme_generation.py`, and registration of both in `build_registry()`/`WorkflowRegistry` — all
purely additive, all following patterns already proven across Phases 6–10.

## 5. Recommended architecture summary

```
NewsEvent (existing)
   │
   ├─ CONTENT_GENERATION "quality" step (existing, unmodified)
   │     └─ [NEW] _attach_meme_opportunity() shadow hook, gated by meme_opportunity_mode="off"
   │           → writes "meme_opportunity" key into quality's structured_output (M1)
   │
   └─ [NEW] WorkflowType.MEME_GENERATION EditorialTask, created only when an operator/worker
     sees a MEME_READY/REVIEW opportunity assessment (never automatic in this phase — see §9)
         meme_concept        (LLM, CREATIVE)         — M2
         meme_copywriting    (LLM, COPYWRITING)       — M4
         meme_safety_originality (deterministic hook) — M3
         meme_image          (LLM/Gateway, CREATIVE)  — M5, off/dry-run by default
         meme_render         (deterministic, Pillow)  — M6
         meme_quality_gate   (deterministic hook)     — M7, bounded regenerate
   │
   └─ [NEW] MemeCandidate durable row (one migration, see §7) — accumulates concept/safety/
     image/quality/decision state across the above steps; ContentDraft(type=MEME) is written
     only once a human approves (M8/M9), exactly mirroring how ContentDraft is today written
     once per completed CONTENT_GENERATION task, never per intermediate step.
   │
   └─ [NEW] bot/handlers/meme_preview.py ("memeprev:" callbacks), modeled on
     bot/handlers/image_preview.py — approve / reject / regenerate text / regenerate image /
     regenerate concept / fallback-to-normal-news. Gated by meme_telegram_preview_mode="off"
     and the existing dry_run-before-live-send discipline (§3.4). No send without separate
     human authorization (§9).
```

## 6. Read-only meme-suitability audit (real data)

Using the 32 real NewsEvent records in `scripts/_phase17_m0_manual_audit_text.json` (categories:
AI, TECH, GADGETS, STARTUPS, HARDWARE, SOFTWARE, UNKNOWN; sources: RSS, Telegram, NEWS_API — the
same population Phase 17 itself audited). Full per-item classification is in Appendix A.

| Classification | Count | Share | Representative example |
|---|---|---|---|
| MEME_READY | 6 | 19% | "CEO Nvidia убеждает, что ИИ не уничтожает рабочие места" (AI-company CEO reassures about AI jobs — textbook irony/contrast); "75% работников обращаются к ИИ вместо коллег" (universally relatable office behavior); "Atoms привлёк $1,7 млрд" robotics startup, zero shipped products (funding-vs-substance irony); divinity school's AI-ethics doctorate (absurdist juxtaposition) |
| POSSIBLE | 9 | 28% | Netflix $500M for shared streaming rights; Samsung "gleefully counting its billions" while warning of supply crisis (irony already present in the source headline); Zuckerberg's "personal superintelligence" strategy reveal |
| NOT_SUITABLE | 9 | 28% | UMC fab expansion; Apple Q3 revenue table; arXiv SO(2)/MLIP paper; Dili's routine Series A |
| SENSITIVE_BLOCK | 6 | 19% | EU/TikTok minors-safety finding; Modi + student protests; man shot by police in a swatting incident; Pavel Durov added to a state terrorist/extremist registry (unconfirmed-to-readers, real named person, legal jeopardy); Weng's health-related resignation |
| INSUFFICIENT_SOURCE | 2 | 6% | TSMC "EMIB-like" packaging (anonymous-sourced rumor); "Copilot will propagate a malicious worm" (single unverified claim) |

One item (the OpenAI "rogue prototype" report) legitimately double-flags as both
`SENSITIVE_BLOCK` and `INSUFFICIENT_SOURCE` (an unverified accusation against a named company) —
Appendix A shows both labels for that row; it is counted once, under `SENSITIVE_BLOCK`, in the
table above since a hard-block reason always takes precedence over a soft "needs more sourcing"
reason in M1's decision logic (§6 taxonomy table).

**Directional findings** (n=32, one real production sample window — treat as hypothesis-forming,
not final calibration data):
- **Category correlates with meme potential.** AI/STARTUPS/TECH stories about funding hype,
  founder/exec statements, and viral-adjacent behavior skew MEME_READY/POSSIBLE. HARDWARE/
  SOFTWARE/GADGETS stories that are purely technical or financial-table content skew
  NOT_SUITABLE. Crime, minors, unverified accusations, and named-person legal/political
  jeopardy stories cluster tightly in SENSITIVE_BLOCK regardless of category.
- **Irony/contrast is the strongest single signal**, matching the brief's own feature list —
  every MEME_READY item in this sample has an explicit expectation-vs-reality gap (AI company
  reassuring about AI jobs; $1.7B raised, zero product; AI-focused hedge fund losing money on AI
  bets).
- **Unconfirmed/single-source claims are a recurring, distinct risk category** separate from
  "sensitive subject matter" — several items in this sample are drafted with explicit hedging
  ("непроверенное обвинение", "согласно заголовку... нужна проверка") by Phase 17's own Fact
  Safety/Editorial Completeness layer. This validates reusing calibrated Fact Safety output as an
  M1 input signal (§3.5) rather than re-deriving source-confidence from scratch.
- **Real named private/public individuals in a legal-jeopardy or health context appear more
  often than expected** (Durov/terrorist registry, Weng's health-related resignation) — this
  argues for M3's safety gate treating "real, identifiable person + legal/health/protected
  context" as a hard block category, not merely a review flag, consistent with the brief's own
  M3 list.

### Gold-sample taxonomy (recommended, for M1)

| Label | Definition | Decision |
|---|---|---|
| `MEME_READY` | Clear irony/contrast/absurdity, confirmed facts, no sensitive-category overlap, adequate visual/textual hook | Proceed to MEME_GENERATION automatically-eligible (still requires human approval at M8) |
| `REVIEW` | Meme potential present but borderline (mild irony, or one soft risk flag e.g. political-adjacent without being a named-person accusation) | Proceed to MEME_GENERATION but flagged for extra scrutiny in preview |
| `NOT_SUITABLE` | No irony/contrast, purely factual/technical/financial, low audience relatability | Do not proceed |
| `SENSITIVE_BLOCK` | Death/tragedy/disaster/war/crime-with-victim/serious illness/minors/protected characteristics/unconfirmed accusation/named-private-individual harm | Hard block, never proceeds, logged with reason code |
| `INSUFFICIENT_SOURCE` | Facts too thin/unconfirmed/single-hedge-source to build a meme without inventing detail | Do not proceed (distinct from SENSITIVE_BLOCK — a thin-but-safe story is just not usable, not dangerous) |

(The brief's M0 section names a fifth label `INSUFFICIENT_CONTEXT`; M1's own section instead
lists `INSUFFICIENT_SOURCE`. This report adopts `INSUFFICIENT_SOURCE` as the canonical name for
M1's implementation, since it is the label M1 actually specifies as a decision outcome, and notes
the discrepancy here rather than silently picking one.)

## 7. Migration decision

**One migration is recommended for the whole phase, not zero and not several.**

What does *not* need one (§3.1, §3.2, §4.3): `WorkflowType.MEME_GENERATION`, both new
`AICapability` mappings, all five new Capability classes, the new Workflow definition, cost
tracking, budget gating, and the `meme_opportunity` shadow hook (M1) — all ride entirely on
JSON columns or code-level enums.

What *does* need one: a **new `meme_candidates` table**, modeled directly on
`ImageCandidateRecord`'s already-approved shape (§3.6) — a single evolving row per meme attempt
that accumulates state across `meme_concept → meme_copywriting → meme_safety_originality →
meme_image → meme_render → meme_quality_gate → human decision`, plus the human-feedback taxonomy
(M9: not-funny / unclear / factual-risk / bad-image / off-brand / too-toxic / stale / duplicate-
idea), regeneration counts per stage, and cumulative cost.

**Why existing tables cannot honestly absorb this:**
- `EditorialTask.workflow` (JSON) is `WorkflowRunner`'s own *transient execution-state* snapshot
  (current_step, completed_steps, iteration_count) — it is not meant to be queried as a business
  record (no durable-row precedent in this codebase treats it that way; Phase 16 M5's own report
  explicitly introduced `ImageCandidateRecord` *because* the equivalent JSON-only approach wasn't
  durable/queryable enough for a multi-stage candidate that must survive independent of workflow
  execution-state bookkeeping).
- `ContentDraft` has no slot for concept/safety/image/regeneration/feedback data, and repurposing
  `hashtags` (JSON, semantically hashtags) or `status` (free text) to carry it would be exactly
  the kind of undisclosed schema abuse the project's own conventions elsewhere reject (see
  `ImageCandidateRecord`'s module docstring explicitly rejecting a similar shortcut, "see the M5
  report §4 for why a second `image_assets` table was evaluated and rejected in favor of..." —
  i.e. this codebase's own precedent is to introduce a purpose-built table when the shape
  genuinely doesn't fit, not to overload an existing column).
- `ImageCandidateRecord` itself is the wrong table (§3.6) — its schema is provenance-from-a-
  NewsSource shaped, not generation-shaped, and reusing it would silently make `discovery_method`/
  `source_type`/`remote_url` mean two different things depending on row, which is exactly the kind
  of ambiguity Phase 16 M5's own design explicitly avoided.

**When to introduce it:** at M2 (Meme Concept Generation), the first milestone that needs to
persist state across more than one step of a bounded regenerate loop. Introducing it later (e.g.
deferred to M9) would force M2–M7 to either invent a temporary ad hoc persistence mechanism or
keep meme state entirely in-memory across a multi-step async workflow (fragile, loses M7's bounded
retry state on process restart). One migration, introduced once, early, is more honest and less
churny than one migration per milestone or zero migrations plus a workaround.

## 8. Risks

1. **Image generation is a real cost and safety surface.** Any AI image provider call is a paid,
   external, potentially-slow dependency with its own content-policy risk (a provider might itself
   refuse or return an unsafe image). M5 must ship fully wired but **default off**, with a
   deterministic dry-run/mock mode that lets M6/M7/M8 be built and tested end-to-end without a
   single paid call, per §9.
2. **Meme humor about real news is inherently higher-risk than ordinary summarization** — the
   Phase 18 M3 safety gate is the single most important new component in this phase and must be
   conservative-by-default (block/review, never guess towards MEME_READY on an ambiguous case).
3. **Duplicate-idea / near-identical-meme risk compounds over time** — with no external "meme
   database" to compare against, M3's originality check can only detect (a) near-copy of the
   *source article's own image* (reusable via perceptual-hash tooling already proven in
   `services/image_deduplication.py`) and (b) near-duplicate meme concepts *within this
   Newsroom's own history* (queryable once `meme_candidates` exists). It cannot detect similarity
   to memes already circulating elsewhere on the internet — this is a disclosed, permanent
   limitation, not a milestone to "complete" later.
4. **Small audit sample (§6).** The n=25 taxonomy is directional. M1's thresholds should be
   revisited once `meme_opportunity_mode="shadow"` has run against real production volume for a
   period, exactly as Phase 17's own M1–M7 calibration milestones did against live shadow data.
5. **Two-LLM-call cost per meme attempt** (`meme_concept` + `meme_copywriting`) before any image
   cost is incurred — bounded but non-trivial at scale; M1's zero-LLM gate is therefore the
   primary cost control, not an afterthought.

## 9. Live/paid/production boundaries (restated for this phase)

Per the operating rules already given: no live/paid image-generation call, no live Telegram send,
no `.env`/live-mode flip, and no production canary will occur without a separate, explicit
human-authorization step. Every default introduced by this phase is `"off"`. Where M5/M8
implementation requires exercising real behavior for validation, it will be done via dry-run/mock
providers and a documented human-authorization packet at the point live activation would begin —
never by silently flipping a flag.

## 10. Recommended milestone order

The brief's M0→M9 order is sound and is adopted with two disclosed deviations, both justified
above:

1. **M1 Opportunity Detection** — implemented as an executor shadow-hook on existing
   CONTENT_GENERATION (§4.1), not a MEME_GENERATION workflow step — it must run before any
   MEME_GENERATION task is even created.
2. **M2 Concept Generation** — this is also where the one migration (§7) lands, rather than at
   M9 as the brief's "if for M9 a persistence strategy is needed" phrasing might suggest — needed
   two milestones earlier than a literal reading implies, because M2's own regenerate loop
   requires it.
3. M3 Safety & Originality Gate — deterministic executor hook, reusing calibrated Fact Safety.
4. M4 Copywriting — separate LLM capability from M2 (not merged), consistent with this
   codebase's existing precedent of one capability per distinct judgment (research vs
   intelligence vs copywriting vs quality are 4 separate calls today; merging concept+copy into
   one call would be the outlier, not the norm).
5. M5 Image Generation — new Gateway surface, ships off/dry-run only pending authorization.
6. M6 Rendering/Text Overlay — deterministic, fully buildable and testable now.
7. M7 Quality Gate — deterministic executor hook, bounded regenerate via existing
   `max_iterations`.
8. M8 Telegram Editorial Preview — mirrors Phase 16 M6's interaction pattern; ships with
   `meme_telegram_preview_mode="off"` and dry-run send by default.
9. M9 Human Feedback & Decision Logging — extends the M2 `meme_candidates` table with decision/
   feedback columns (an additive migration on the same table, not a second new table).

No blockers were found that would prevent proceeding directly to M1.

---

## Appendix A — Full per-item audit (n=32, source: scripts/_phase17_m0_manual_audit_text.json)

| # | Category | Title (truncated) | Label | Why |
|---|---|---|---|---|
| 1 | GADGETS | Netflix pays $500M to share Walking Dead rights | POSSIBLE | Mild irony (huge sum for *shared*, not exclusive, rights); modest visual/audience hook |
| 2 | AI | US agency's AI immigration tool listing vanished after inquiry | REVIEW | Government transparency angle, politically adjacent; needs editorial judgment |
| 3 | AI | Nvidia CEO: AI isn't destroying jobs | MEME_READY | Strong contrast: AI company reassures about AI's own effect on jobs |
| 4 | AI | Free AI clubs open in Tatarstan schools | NOT_SUITABLE | Purely informational, no irony/tension |
| 5 | AI | Torvalds: AI useful for Linux development | POSSIBLE | Mild niche-audience irony (skeptic figure endorsing AI tooling) |
| 6 | AI | OpenAI's autonomous agent hacked a platform, tried 4 more | REVIEW | Irony-rich but touches unverified security-incident claims |
| 7 | GADGETS | EU: TikTok insufficient on minors' safety | SENSITIVE_BLOCK | Minors safety — protected category |
| 8 | GADGETS | UMC expands fab capacity | NOT_SUITABLE | Dry industrial/financial news |
| 9 | GADGETS | Warhammer 40,000: Dawn of War 4 trailer | POSSIBLE | Fandom/gaming humor potential |
| 10 | GADGETS | DOJ vs Apple antitrust records dispute | NOT_SUITABLE | Legal-procedural, low visual/humor hook |
| 11 | GADGETS | Google may update Chrome without full restart | NOT_SUITABLE | Purely technical |
| 12 | GADGETS | Apple warns of worsening supply constraints | POSSIBLE | Mild "expect the unexpected" framing |
| 13 | TECH | Modi turns to Instagram Reels amid student protests | SENSITIVE_BLOCK | Political figure + active protests — high-risk political topic |
| 14 | TECH | Lilian Weng returns to OpenAI after health-related departure | SENSITIVE_BLOCK | Named individual's health disclosed as departure reason |
| 15 | TECH | TSMC developing "EMIB-like" AI chip packaging (sourced, unnamed) | INSUFFICIENT_SOURCE | Anonymous-sourced technical rumor, no confirmed detail |
| 16 | TECH | AI hedge fund Situational Awareness sold portfolio after losses | MEME_READY | AI-focused fund losing money on AI bets — sharp irony, relatable financial-loss angle |
| 17 | TECH | Apple Q3 earnings by product line | NOT_SUITABLE | Pure financial data table |
| 18 | STARTUPS | Tile's weak security enables stalking | SENSITIVE_BLOCK | Real safety/stalking harm potential |
| 19 | STARTUPS | 75% of workers ask AI instead of colleagues | MEME_READY | Universally relatable workplace behavior |
| 20 | STARTUPS | Dili raises $21.7M Series A | NOT_SUITABLE | Routine funding announcement, no irony |
| 21 | STARTUPS | Man shot by police in game-related swatting incident | SENSITIVE_BLOCK | Crime with a real victim/injury |
| 22 | UNKNOWN | arXiv paper on SO(2) interatomic-potential theory | NOT_SUITABLE | Highly technical academic content, no audience relatability |
| 23 | UNKNOWN | Moonshot AI raises $3.5B at $35B valuation | POSSIBLE | Mild contrast (planned $1-2B → actual $3.5B) |
| 24 | UNKNOWN | Pavel Durov added to a state terrorist/extremist registry | SENSITIVE_BLOCK | Named real person, unconfirmed-to-readers serious legal accusation |
| 25 | HARDWARE | Report: OpenAI took a week to notice a rogue prototype (unnamed report) | INSUFFICIENT_SOURCE / SENSITIVE_BLOCK | Unverified accusation against a named company; draft itself hedges it as unconfirmed |
| 26 | HARDWARE | Samsung warns of "severe" 2029 memory supply crisis | POSSIBLE | Source headline itself already frames irony ("gleefully counting its billions") |
| 27 | SOFTWARE | Claim: Copilot can propagate a worm between Word docs | INSUFFICIENT_SOURCE | Single unverified security claim, no confirmation |
| 28 | SOFTWARE | Deepfakes undermine corporate video-call trust | POSSIBLE | Topical but security/fraud-adjacent, moderate care needed |
| 29 | AI | Zuckerberg details Meta's "personal superintelligence" strategy | POSSIBLE | Hype-heavy public-figure statement, decent irony potential |
| 30 | TECH | AI compute costs could rise >10x | NOT_SUITABLE | Abstract economic projection, low visual potential |
| 31 | UNKNOWN | Atoms (Kalanick) raises $1.7B with zero shipped products | MEME_READY | Sharp raised-vs-delivered contrast, classic startup-hype irony |
| 32 | AI | Divinity school launches "AI and Moral Agency" doctorate | MEME_READY | Delightful institutional-juxtaposition absurdity |
