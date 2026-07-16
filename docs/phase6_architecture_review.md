# Phase 6 Architecture Review — One Year Later, 30+ Capabilities

No code, no migrations, no commits. This document reviews `docs/phase6_capability_framework_planning.md`
(the accepted Phase 6 design baseline) as if the system had grown from 7 capabilities to 30+ without a
redesign. It does not modify that document. Where a "redesign" is requested below (Q3, Q8), the code
blocks shown are **proposed contract shapes for discussion**, not implementation — nothing here is written
to `capabilities/`, `schemas/`, or `integrations/`.

---

## 1. Does the architecture survive 7 → 30+ capabilities without redesign?

Mostly, but not entirely. Split by component:

**Scales cleanly, no changes needed:** `CapabilityRegistry` (dict-keyed register/resolve/seal — O(1),
no structural growth cost), the error hierarchy (§13 of the baseline), `CapabilityDefinition`/`CapabilityConfig`
(purely additive per capability), and the `WorkflowRunner ↔ CapabilityExecutor` boundary (Option 1,
constructor injection — adding capability #30 touches zero Workflow code, exactly like adding #8 does).

**Breaks concretely at scale — three things:**

1. **`CapabilityContext.news_event` is a hardcoded, non-optional, single-event field.** All 7 of today's
   capabilities operate on exactly one `NewsEvent`. That stops being universally true well before 30
   capabilities exist — a clustering capability, a digest capability, or anything operating on a
   `ContentDraft` instead of a raw event has no honest way to populate this field. See Q10.1 for the
   concrete case; it is already partially acknowledged by the baseline's own Conflict D / `DAILY_DIGEST`
   precedent, but `CapabilityContext` doesn't yet reflect that acknowledgment structurally.
2. **`CapabilityExecutor`'s fetch pattern is single-purpose**: fetch one `EditorialTask`, fetch its one
   `NewsEvent` via `task.event_id`, build one `CapabilityContext`. This is fine for a pipeline where every
   capability is a Workflow step over one event. It does not stretch to capabilities invoked outside a
   Workflow run at all (ad hoc embedding calls from a search service, a nightly batch re-scoring job) —
   there would be no `WorkflowStepDefinition`, no `task_id`, and nothing for `CapabilityExecutor` to fetch.
3. **`LLMGateway`'s four-method, single-shot, token-and-text-centric contract** doesn't naturally cover
   binary outputs (image generation), non-generative retrieval (search may not be an LLM call at all), or
   multi-turn tool-use loops (planning). See Q3 and Q8 for the specific fixes.

None of these are "the design is wrong" — they're places where the current shape quietly assumes
"Workflow step over one NewsEvent, one model call" as a universal law rather than the common case it
actually is today. That assumption is safe to keep as the *default* path; it stops being safe once it's
the *only* path.

---

## 2. `CapabilityContext` — one object, or `RuntimeContext` / `BusinessContext` / `ExecutionContext`?

Today's fields fall into four natural groups: **identity** (`task_id`, `event_id`, `capability_name`),
**business/domain data** (`news_event`, `workflow_state`), **runtime metadata owned by the executor**
(`priority`, `attempt`, `iteration_count`), and **Gateway-routing hints** (`preferred_model`, `max_tokens`,
`temperature`) plus **editorial config** (`language`, `audience`, `brand_voice`).

| | One immutable object (current) | Split into 3 contexts |
|---|---|---|
| Pro | Simple call site: `capability.execute(context)`, one thing to construct, one thing to test | A capability that only needs business data doesn't import/mock runtime concepts like `iteration_count`; a future non-Workflow caller can build `BusinessContext` + `ExecutionContext` without inventing meaningless `attempt`/`iteration_count` values |
| Con | Every capability — including ones that will exist only outside a Workflow — is forced to accept fields that only make sense inside a Workflow step | Three objects to construct at every call site; `Capability.execute()`'s signature must decide between 3 params (more surface area) or a wrapper (which just re-creates today's single object) |

**The real trigger for the split isn't capability count, it's execution mode.** All 7 (and likely the
next several dozen) capabilities run as Workflow steps, so `attempt`/`iteration_count` are always
meaningful. The split earns its cost only once a capability exists that has *no* Workflow step wrapping
it at all (Q1's "ad hoc embedding call" case). That hasn't happened yet.

**Recommendation:** don't split into three top-level parameters yet — that's solving a problem no
capability has today. Do restructure `CapabilityContext` internally into three nested frozen sub-models
now (`context.business.news_event`, `context.runtime.attempt`, `context.execution.preferred_model`)
instead of flat top-level fields. This costs nothing today (same object, same call site,
`Capability.execute(context)` unchanged) and turns a future full split into a mechanical extraction —
each nested model becomes its own top-level parameter — rather than a rewrite of every capability's field
access. Cheap insurance, not a redesign.

---

## 3. `CapabilityResult` — does it survive image generation, embeddings, moderation, summarization, translation, planning, search?

Walking each future capability against the current shape:

- **Summarization, translation, moderation** — fit today's shape without a hack: text/labels go in
  `structured_output: dict[str, Any]`, `confidence` is already optional so moderation's score-shaped
  output doesn't need to abuse it.
- **Embeddings** — fits mechanically (`structured_output` is unconstrained), but `confidence` is simply
  unused (`None`), which is fine, not a hack.
- **Image generation** — fits *if and only if* one rule is made explicit: `structured_output` must hold a
  reference (object-storage URL/path), never inlined bytes. That rule already exists implicitly for
  `logs` ("never full payloads") but isn't stated for `structured_output`. Worth stating explicitly, not
  a redesign.
- **Search** — the field that breaks: `model_used: str | None` is already nullable so a non-LLM retrieval
  call is representable, but `usage: CapabilityUsage` is **mandatory and token-only**. A paid-per-query
  search API, or a free local vector lookup, has no token count at all. Forcing `input_tokens=0,
  output_tokens=0` to satisfy the schema is exactly the kind of hack this question is asking about.
- **Planning** — the sharpest break. A planning capability (per the future Workflow → Capability → Tool
  calls → Gateway → Provider layering named in Q5) makes **multiple internal Gateway calls**, potentially
  to different models, using different prompts, before returning one `CapabilityResult`. Today's
  `model_used: str | None`, `prompt_name: str`, `prompt_version: str` are all **singular** — there is no
  non-lossy way to report "this capability made 4 Gateway calls, 2 with a cheap routing model and 2 with
  the synthesis model" through a single scalar triple.

**Conclusion: the contract does not survive planning (and, by the same defect, any future ensemble/
cross-model capability) without a hack. Redesign, contract-only:**

```python
class CapabilityUsage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    input_tokens: int | None = Field(default=None, ge=0)   # None, not 0 - "not token-billed", not "free"
    output_tokens: int | None = Field(default=None, ge=0)
    units: int | None = Field(default=None, ge=0)           # e.g. image count, search queries
    unit_type: str | None = None                            # "image" | "search_query" | ... - opaque to the framework


class CapabilityCallRecord(BaseModel):
    """One underlying LLMGateway call made while producing this CapabilityResult."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    model_used: str
    prompt_name: str
    prompt_version: str
    usage: CapabilityUsage
    started_at: datetime
    finished_at: datetime


class CapabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["SUCCESS", "FAILED"]
    structured_output: dict[str, Any] | None
    confidence: int | None = Field(default=None, ge=0, le=100)

    calls: list[CapabilityCallRecord] = Field(min_length=1)   # replaces model_used/prompt_name/prompt_version/usage
    # Cost Tracker sums usage across `calls`; a single-Gateway-call capability just returns a list of length 1 -
    # today's 7 capabilities need zero behavioral change, only a one-element list instead of four scalar fields.

    started_at: datetime
    finished_at: datetime
    duration_seconds: float

    metadata: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    next_context: dict[str, Any] | None = None
```

This is the one place in the whole review where I'd say the fix belongs **in Phase 6, before any
Capability is implemented against the old scalar shape** — retrofitting `model_used: str` →
`calls: list[...]` after real capabilities and the `AIExecution` persistence mapping (§15 of the
baseline) both depend on the scalar version means touching every capability and the persistence layer
simultaneously. Today, while zero capabilities exist, it's a pure schema decision with no migration cost.

---

## 4. `CapabilityRegistry` — sufficient if capabilities become installable modules? (Evaluation only, no plugin loading.)

The `register(definition, capability)` / `seal()` / `resolve(name)` API is **discovery-mechanism-agnostic
already** — nothing about it assumes *how* `register()` gets called. Today `build_registry()` calls it
directly from explicit imports; a future plugin system would just change `build_registry()` to iterate
`importlib.metadata.entry_points()` (or similar) and call the same `register()` for each discovered
package, then still `seal()` before returning. **The registry's core contract survives untouched.**

Two things would not survive without a change, both worth naming now even though neither is fixed today:

1. **Flat, un-namespaced `name: str` identifier**, shared verbatim between `CapabilityDefinition.name` and
   the already-shipped Phase 5 `WorkflowStepDefinition.capability`. At 7 in-house capabilities, collision
   risk is zero. At 30+ capabilities potentially contributed by separate teams or third-party packages,
   `"research"` is not a safe global key. Fixing this means widening the identifier shape (e.g. a
   package-qualified string) in **two** places at once — `CapabilityDefinition.name` (Phase 6, not yet
   shipped) and `WorkflowStepDefinition.capability` (Phase 5, already shipped, explicitly out of scope to
   touch). This is the reason to flag it now rather than silently accept the coupling: whoever eventually
   builds installable modules will need to touch a Phase 5 file to do it correctly, and that should be a
   known, accepted cost, not a surprise.
2. **No provenance metadata.** `CapabilityDefinition` has no field recording which package/version a
   registered capability came from. Purely additive (`source_package: str | None`), not a breaking
   change, but worth pre-planning since "why did capability X's behavior change" becomes a real debugging
   question the moment capabilities are independently versioned and shipped by different owners.

Sealing itself (register-until-boot, immutable thereafter) is *correct* to keep even for installable
modules — "install the package, restart the process" is consistent with this project's existing "no
dynamic module discovery" rule (baseline item 14), not a limitation the plugin future needs to remove.

---

## 5. `CapabilityExecutor` — survives Workflow → Capability → Tool calls → Gateway → Provider?

Tool calls sit **below** `Capability`, between `Capability` and `LLMGateway` — not between `Workflow` and
`Capability`, where `CapabilityExecutor` lives. Structurally, a tool-calling capability just makes
multiple internal `LLMGateway.generate()` calls inside its own `execute()` and returns one
`CapabilityResult` at the end. `CapabilityExecutor` never needs to know tool calls exist, **provided**
`CapabilityResult` can represent a multi-call execution faithfully — which is exactly Q3's finding. Fix
Q3, and `CapabilityExecutor`'s code doesn't need to change for this layering to work.

Two things *should* change now, not in `CapabilityExecutor`'s code, but in decisions that shape it:

1. **AIExecution persistence currently assumes 1 row per Capability execution** (§15 of the baseline:
   "persist an AIExecution row… on success"). If `CapabilityResult.calls` becomes a list (Q3), persistence
   becomes "persist N rows, one per call, grouped under one logical capability invocation." That grouping
   concept doesn't exist in `AIExecution` today (see Q6) — deciding *now* that one `CapabilityResult` may
   produce N `AIExecution` rows avoids retrofitting a grouping column after millions of 1-row-per-call
   records already exist.
2. **Retry semantics for partially-completed internal call sequences are undefined.** If a tool-call loop
   fails on its 4th of 5 internal Gateway calls and the whole capability is retried at the step level,
   nothing in the framework preserves or discards the first 3 calls' results. This should be a documented
   contract rule on `Capability` itself ("`execute()` is called fresh on retry; no partial internal state
   is preserved by the framework between attempts") — not a `CapabilityExecutor` code change, but a
   protocol-docstring decision worth locking in before a real tool-calling capability has to guess.

---

## 6. `AIExecution` — architecturally future-proof at millions of executions? (Ignore indexes/performance.)

Three structural cracks, none requiring action this phase (correctly — §16 of the baseline already
establishes no migration is needed for Phase 6 itself), but all three are the specific reasons a *real*
migration will eventually be unavoidable:

1. **`capability: AICapability` is a closed Postgres enum.** Every new capability name requires a schema
   migration. That's a manageable tax at 7 → 15 capabilities. It is **directly incompatible** with Q4's
   installable-module future: a plugin-installed capability cannot write its first `AIExecution` row
   until a DBA-approved migration adds its enum value, which defeats the point of "installable." This is
   the clearest concrete conflict found anywhere in this review between two of the ten questions.
2. **`task_id` is a required (`NOT NULL`) foreign key to `editorial_tasks.id`.** This hardcodes "every AI
   call belongs to exactly one Workflow-driven task." The first capability that runs outside a Workflow —
   an ad hoc embedding call from search, a moderation check on user feedback, a nightly re-scoring batch —
   cannot be recorded at all under the current schema. Given docs/10_1 §12's daily/monthly budget
   enforcement reads as a *system-wide* limit, not a per-task one, this gap will surface the first time
   any AI spend happens outside the editorial pipeline, which is very likely well before 30 capabilities
   exist.
3. **Implicit 1-row-per-model-call assumption**, with no grouping/parent concept — the schema-side twin of
   Q5's finding. Once a single capability invocation can span N Gateway calls, "how much did this one
   capability invocation cost" requires either a grouping column or an application-layer join that has
   nothing to join on today.

A smaller, non-urgent note: there's no column recording which `CapabilityDefinition.version` produced a
row (only `prompt_version` is captured) — worth an eventual additive column, not urgent.

---

## 7. `PromptRepository` — own versioning, or stay read-only under a separate lifecycle owner?

**Stay strictly read-only; push lifecycle to a separate component.** The current contract already is
read-only (`resolve(name, version=None) -> RenderedPrompt`, no create/update/publish/rollback method) —
the recommendation here is to make that a **permanent, explicit rule**, not just today's incidental shape.

This mirrors a pattern already established twice in this codebase: `WorkflowRegistry` and
`CapabilityRegistry` are both build-time-populated, sealed-and-immutable-at-runtime resolvers — authoring
happens in versioned source (`workflows/definitions/`, future `capabilities/`), not through the
registry's own runtime API. Prompts should follow the same split: prompt *content* lives in versioned
files (docs/07 §23.1's yaml format, under `prompts/`), a build/lint/test step (docs/13 Level 3,
docs/07 §26.3) validates and publishes them, and `PromptRepository` at runtime does nothing but resolve
already-published artifacts.

Why this matters more for prompts than almost anything else in the system: prompts will change far more
often than schemas or capability code — they're the highest-churn artifact in the whole design. If
`PromptRepository`'s runtime contract ever grew a mutating method, every capability's dependency graph
would implicitly include "something that can change behavior at runtime without a code change or
migration," which breaks the same reproducibility guarantee the registries already protect: a given
`(name, version)` must resolve to the same `RenderedPrompt` forever, so that `AIExecution.prompt_version`
remains a trustworthy audit pointer and prompt regression tests run against exactly what production uses.

**Recommendation:** confirm `PromptRepository` is permanently read-only, and name the missing counterpart
(a "Prompt Publisher" / build pipeline, not designed here) as a required future component now, so prompt
lifecycle doesn't get bolted onto `PromptRepository` under later time pressure.

---

## 8. LLM Gateway — survives OpenAI, Anthropic, Gemini, Grok, DeepSeek, Ollama, OpenRouter, local models?

The 4-method surface and provider-agnostic request/response shape survive structurally — all eight are
HTTP request/response APIs with a model name, messages/prompt, and usage counts. Two provider-shape
differences don't require an interface change:

- **Non-uniform method support** (not every provider has a dedicated classify/moderate endpoint) is
  handled by allowing a provider implementation to raise `UnsupportedCapabilityError` for a method it
  doesn't back — a provider-routing concern, not a Protocol change.
- **Local models / Ollama** are shape-identical from the Gateway's point of view (still request/response,
  still has a model name and token counts); the only difference is a $0 price entry in Cost Tracker's
  price table — not a Gateway concern.
- **OpenRouter**, being itself a meta-router, is just another Protocol implementation from the Gateway's
  perspective — no special-casing needed.

Two gaps genuinely require an interface change, both cheap and additive, both worth making **now**:

1. **No `preferred_provider` field** — only `preferred_model: str | None` exists, which conflates model
   identity and provider identity. At 8 providers with possibly overlapping model name strings, there's no
   way to express "prefer Anthropic specifically" vs. "any provider with a model called X." One-line,
   non-breaking addition.
2. **No tool-calling fields, despite the future layering in Q5 requiring them.** `GenerateRequest`/
   `GenerateResponse` as specified carry no `tools`/`tool_calls` shape. Since the Gateway's entire job is
   to normalize provider-specific wire formats into one contract, and every one of the eight target
   providers has some form of function/tool calling, this is the one Gateway gap that actually blocks the
   architecture named elsewhere in this same task (Q5's Tool-calls layer). Retrofitting it after
   Capabilities exist means touching every call site; adding it now as optional fields costs nothing.
3. **`allow_stream: bool` on `CapabilityConfig` has no corresponding Gateway contract.** `generate() ->
   GenerateResponse` is call-and-wait; nothing in the Protocol can represent token-by-token streaming.
   This is a promise (the config flag) with no contract behind it today.

**Redesign, contract-only:**

```python
class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    description: str
    parameters_schema: dict[str, Any]   # JSON Schema for the tool's arguments


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    arguments: dict[str, Any]


class GenerateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    messages: list[dict[str, Any]]
    preferred_model: str | None = None
    preferred_provider: str | None = None      # new - see gap 1
    max_tokens: int | None = None
    temperature: float | None = None
    tools: list[ToolDefinition] | None = None  # new - see gap 2
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerateResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    text: str | None
    structured_output: dict[str, Any] | None
    tool_calls: list[ToolCall] | None = None   # new - see gap 2
    model_used: str
    usage: "CapabilityUsage"
```

For gap 3, resolve the inconsistency rather than carry it forward silently: either drop `allow_stream`
from `CapabilityConfig` now (nothing consumes it, no capability needs it yet) or add a real
`generate_stream(request) -> AsyncIterator[GenerateChunk]` method to the Protocol. Cheapest correct move:
drop the flag now, add streaming as a real method only when a concrete capability needs it — don't ship a
config field that quietly promises behavior no contract exists for.

---

## 9. Hidden coupling between Workflow / Capability / Prompt / Gateway / Cost Tracker / Persistence

Most boundaries are clean: Workflow never touches Prompt or Gateway; Capability never touches persistence
directly (the ORM/session lives only in `CapabilityExecutor`); Capability depends on `LLMGateway` and
`PromptRepository` only via injected Protocols. Three real couplings exist, two already partly named, one
not named anywhere:

1. **`AIExecution.capability` enum ↔ `CapabilityRegistry` namespace** — already flagged as Conflict D in
   the baseline and again in Q6 here. Two independent sources of truth for "what capabilities exist,"
   which must be kept manually in sync via migration. Known, not fixed, correctly deferred.
2. **`CapabilityContext.workflow_state` couples Capability schemas to Workflow's snapshot shape.** This is
   deliberate and probably necessary — docs/11 §11's "capabilities communicate only through persisted
   state" *requires* a capability to understand the shape of what a prior step wrote. It's one-directional
   (Capability reads a Workflow-shaped snapshot; Workflow never reads anything Capability-shaped) and
   read-only, so it's an acceptable coupling — but it's currently an *implicit* one. Worth documenting
   explicitly as "the one intentional exception to Capability/Workflow decoupling," so it isn't
   rediscovered and mistaken for a violation of the decoupling rule.
3. **Cost Tracker's invocation point relative to `CapabilityExecutor` is entirely undefined — this is the
   one nobody has written down yet.** `CapabilityResult.usage` (or, post-Q3, `calls`) plus `model_used`
   are the inputs Cost Tracker needs (§14 of the baseline), but nothing says *when* Cost Tracker runs.
   Two real options with different architectural consequences:
   - **Post-hoc recording**: `CapabilityExecutor` persists the `AIExecution` row(s); Cost Tracker reads
     them asynchronously to aggregate spend and enforce limits on the *next* call. Loose coupling, but
     cannot prevent a single over-budget call from happening — it can only refuse the one *after* it.
   - **Pre-flight enforcement**: `CapabilityExecutor` must call into Cost Tracker *before* invoking
     `capability.execute()`, to check remaining budget and potentially reject the call outright. This
     matches docs/10_1 §12's "enforced against daily/monthly limits" reading more literally (enforcement
     implies prevention, not just reporting) — but it means `CapabilityExecutor`'s dependency list grows
     to include a service-layer component (`services/cost_tracker.py`), and its constructor signature
     (currently `session, task_id, registry`) is incomplete for that future.

   This is the most consequential hidden coupling in the whole review, precisely because it's invisible
   today — nothing about it is wrong in the current design, because nothing about it has been decided at
   all. It should be resolved as an explicit question before Cost Tracker is built, since
   `CapabilityExecutor`'s shape is being locked down now and its constructor is exactly the place this
   decision would land.

---

## 10. Breaking the architecture — three future capabilities

### 10.1 Multi-event digest / trend-clustering capability
Clusters many `NewsEvent`s into a small number of trending stories in one capability run.

- **Why hard:** `CapabilityContext.news_event` is a single, non-optional field; `CapabilityExecutor`
  fetches exactly one `NewsEvent` via `task.event_id`; `EditorialTask.event_id` is itself a single foreign
  key.
- **Assumption that breaks:** "one `EditorialTask` ↔ one `NewsEvent` ↔ one `CapabilityContext.news_event`"
  is baked into three layers at once (domain model, context schema, executor fetch logic).
- **Fix now or later:** Later — and this is not actually a Phase 6 gap. It's already correctly identified
  and deferred at the Workflow layer: `WorkflowType.DAILY_DIGEST` is explicitly declared-but-unregistered
  in Phase 5 for exactly this reason. Phase 6 shouldn't attempt to fix it either, but should not treat
  `news_event` as a permanently-singular field while pretending this case doesn't exist — it should be a
  one-line note in the schema's docstring, not a surprise rediscovered during Digest work.

### 10.2 Human-in-the-loop planning capability
Proposes an action, suspends for human editorial approval (arbitrary wall-clock time — possibly hours),
then resumes.

- **Why hard:** `Capability.execute(context) -> CapabilityResult` is one bounded async call.
  `CapabilityExecutor` awaits it inside `WorkflowRunner`'s per-step `asyncio.wait_for(timeout)`. There is
  no concept anywhere in the framework of a capability suspending mid-execution and resuming from
  external input.
- **Assumption that breaks:** "a Capability execution is a single bounded async call" — true of the
  `Capability` Protocol itself, `CapabilityExecutor`, the step timeout wrapper, and `MAX_AGENT_ROUNDS`
  (which assumes rounds happen within one process's control flow, not across a human-approval gap).
- **Fix now or later:** Later, and probably never as an extension of `Capability` at all. A suspend/resume
  approval gate is architecturally a different *kind of Workflow step* — one that ends the current run and
  waits for an external event to start a new one — not a long-running Capability call. This is a signal
  that "human approval gate" should eventually be its own step type sitting outside the Capability
  abstraction, not a gap in Capability's design. No action needed in Phase 6; worth one sentence so this
  boundary is a recognized non-goal, not a rediscovered limitation.

### 10.3 Continuous / streaming trend-monitoring capability
Watches for emerging patterns continuously rather than running once and returning.

- **Why hard:** There is no natural `finished_at`/single terminal result — `CapabilityResult`'s
  `started_at`/`finished_at`/`duration_seconds` assume a call that starts and ends. A continuously-running
  or periodically-polling process doesn't fit "one `execute()` call, one `CapabilityResult`" at all.
- **Assumption that breaks:** "every Capability invocation is a discrete call with a clear start and end,"
  which underlies `CapabilityResult`'s timing fields and the one-Workflow-step-per-invocation model.
- **Fix now or later:** Not at all, as a Capability. This should stay outside the Capability Framework
  entirely — a scheduled/background job that itself creates discrete `EditorialTask`s (or triggers
  Workflow runs) when it detects something, each of which then uses a normal, bounded Capability. Fixing
  this "inside" Capability would be the wrong move — it's better handled as an explicit boundary: streaming/
  continuous work is a different execution model, not a variant of Capability, and should never be forced
  through `execute()`.

*(A fourth candidate — an ensemble/cross-model consensus capability making parallel calls to several
providers and reconciling disagreement into a confidence score — was considered and turned out to be the
same underlying gap as Q3/Q5, not a new one: it's covered by the `calls: list[CapabilityCallRecord]`
redesign in Q3, and is exactly the concrete case that validates making that fix now rather than deferring
it.)*

---

## Honest final assessment

No — I don't believe Phase 6, as currently designed, should be claimed to *never* require a structural
redesign, and I'd be overstating confidence if I said otherwise. Three of the ten questions above surfaced
real, if narrow, gaps: `CapabilityResult`'s singular-call assumption (Q3), `LLMGateway`'s missing tool-call
fields and the unresolved `allow_stream` promise (Q8), and the fully undefined Cost Tracker invocation
point (Q9). Two more are correctly-deferred-but-real future migrations: `AIExecution`'s closed
`capability` enum and required `task_id` (Q6), and `CapabilityContext`'s single-event assumption (Q10.1).

What I do believe: the *separation itself* — Workflow, Capability, Prompt, Gateway, Cost Tracker, and
Persistence as decoupled layers mediated by Protocols and immutable, sealed registries — is the right
shape, and it will very likely carry the system to 30+ capabilities without a *rewrite*. The failure mode
this architecture is actually vulnerable to isn't "the layers are wrong," it's "a scalar field quietly
assumed to always be singular turns out not to be" (Q3, Q6) — which is a schema problem, not a
structural one, and cheap to fix before any capability exists to be broken by fixing it.

Concretely: fold the Q3 (`CapabilityResult.calls`) and Q8 (`tools`/`tool_calls`,
`preferred_provider`, resolve `allow_stream`) contract changes into Phase 6 now — before any Capability
implementation depends on the old scalar shapes — and resolve Q9's Cost Tracker invocation-point question
before `CapabilityExecutor`'s constructor signature is treated as final. With those three folded in, I'd
call the remaining gaps (Q6, Q10.1, Q10.2, Q10.3) acceptable technical debt: correctly identified,
correctly deferred, and cheap to resolve later precisely because they were named now instead of
discovered under pressure. That's a stable foundation. It is not, and no design at this stage honestly
can be, a guarantee against ever needing to touch the architecture again.
