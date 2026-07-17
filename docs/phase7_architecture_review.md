# Phase 7 Architecture Review — Ten Providers, A Hundred Models, Millions of Requests

No code, no migrations, no commits. This document reviews `docs/phase7_ai_integration_layer_planning.md`
(the Phase 7 design baseline) the way `docs/phase6_architecture_review.md` reviewed Phase 6's baseline —
as if the system had grown to the scale named in the brief without a redesign. It does not modify that
document. Proposed contract shapes below are **for discussion**, not implementation — nothing here is
written to `integrations/llm_gateway/`, `capabilities/`, or anywhere else.

---

## 1. Does the design survive 3 → 10 providers, 7 → 100 models, without redesign?

Yes, for the Provider Registry and Model Registry themselves — this is the part of the baseline that most
directly inherited a proven pattern (`CapabilityRegistry`/`WorkflowRegistry`/`AdapterRegistry`: dict-keyed,
sealed-after-boot, O(1) resolve) rather than inventing a new one, and it shows. Adding provider #10 or model
#100 is a registration-table edit, structurally identical to adding provider #4 or model #8. Nothing about
the Router's filter-then-rank algorithm (§6 of the baseline) changes shape as candidate counts grow — it's
already expressed as operations over `list[ModelDescriptor]`, not per-provider branches.

**Where it doesn't survive without a caveat:**

1. **`ModelRegistry.filter()` is a linear scan, explicitly accepted as "fine at n=100" (baseline §21).**
   True today. At true scale (the "100 models" ceiling named in the brief, not an arbitrary future number),
   this is still sub-millisecond — not a real risk. Worth confirming this isn't quietly assumed to also
   cover "1,000 models" without re-checking; the baseline doesn't claim that, and this review agrees the
   claim as scoped (100) holds.
2. **The Fallback Chain's candidate list can quietly grow long tails at 10 providers.** If a `Capability`
   requests `requires_vision=True` with no `preferred_model`, and 6 of 10 providers now have at least one
   vision-capable model, the Router's ranked list could be 6+ candidates deep. `max_fallback_attempts`
   (baseline §7, default 3) already bounds *how many* are tried — but the *ranking* still has to consider
   all 6+ before truncating to 3. This is cheap (in-memory sort), not a real scaling problem, but it means
   `max_fallback_attempts` is doing real work at 10-provider scale that it wasn't really doing at 3
   providers (where "try all of them" and "try the top 3" were nearly the same thing). Worth naming: the
   bound matters more as provider count grows, which is exactly when a config regression (someone quietly
   raising it) would be easiest to miss.

**Verdict: survives structurally.** The registries and Router algorithm are provider-count-agnostic by
design, which is the correct property to have locked in now.

---

## 2. Rate Limiter and Cache — the two components the baseline itself flags as scale-critical (§21, §16, §15)

The baseline is explicit that these two MUST be Redis-backed, not in-process, "the moment this system runs
more than one worker process." This review agrees with that conclusion but finds the baseline under-specifies
**one operational consequence of centralizing them**: a Redis-backed rate limiter and a Redis-backed
response/embedding cache both add a **new failure mode class** to every single AI call — Redis itself
becoming a dependency of the hot path, not just a nice-to-have optimization.

The baseline does name this for the Rate Limiter specifically (Open Question 5 — fail-open vs. fail-closed
on Redis unavailability) but does **not** ask the same question for the Cache. A cache read/write failure
should almost certainly **fail open** (treat as a cache miss, proceed to a real provider call) — unlike the
Rate Limiter, where fail-open vs. fail-closed is a genuine safety tradeoff, a *cache* failing open just
means "no caching happened this time," which is a performance/cost regression, not a correctness or safety
one. **This asymmetry is worth stating explicitly in the eventual Contract**: Rate Limiter's fail-open/closed
question is genuinely open (baseline Open Question 5); Cache's is not — it should always fail open, and this
should be locked in now rather than left as a second open question that gets resolved inconsistently later.

**Recommendation:** add "Cache failures MUST fail open (treat as miss)" as a settled rule alongside Open
Question 5, not bundled into the same open-ended question.

---

## 3. `RoutingCriteria`/`RoutingPolicy` — sufficient for a 3rd-party or dynamically-tunable routing objective?

The baseline's `RoutingPolicyRegistry` (§6.2) is deliberately built on the same sealed-registration pattern
as everything else, and that's the right call for the same reason Phase 6's `CapabilityRegistry` made it —
but it's worth stress-testing the one place this pattern has historically needed a caveat (Phase 6 review
§4, on `CapabilityRegistry`'s flat namespace): **is `RoutingObjective`/objective-name a namespace collision
risk once routing policies might come from more than one team or package?**

At the scale actually named in the brief (10 providers, 100 models, 50 capabilities — not "N teams shipping
routing policies"), this is not a real risk today, same conclusion Phase 6 reached about capability names at
30-50 capabilities. Flagged only so it's a *known*, not rediscovered, limitation if routing policies are
ever externally contributed — mirroring the same caveat already accepted for `CapabilityDefinition.name`.

**More substantive gap: `RoutingCriteria` has no way to express "avoid provider X for this specific call"
(a negative constraint), only "prefer provider X" (a positive, advisory one).** A real operational need this
design doesn't yet cover: a provider having a known, temporary quality regression (not an outage — the kind
of thing that doesn't trip the Fallback Chain's failure-trigger table at all, because the calls *succeed*,
just badly) with no way for an operator to steer traffic away from it short of disabling the provider
entirely (a blunt, all-capabilities instrument). This is a legitimate gap the baseline doesn't name.
**Proposed, for discussion only:** an `excluded_providers: list[str]` field on `RoutingCriteria`, defaulting
to empty, settable per-call by a `Capability` or, more usefully, by an operational override layer not yet
designed (a "provider health" side-channel the Router consults, separate from the hard-failure-driven
`unhealthy` flag already in §7 of the baseline). Not designed further here — named as a real, not
hypothetical, operational gap.

---

## 4. `CapabilityCall` / `AIExecution` — does routing/fallback survive without leaking internal complexity upward?

Yes, and this is the baseline's strongest result. §1's governing principle — "one `CapabilityCall` per
`LLMGateway` invocation, routing is invisible above the boundary" — means every mechanism this document
reviews (routing, fallback, retry, caching, rate limiting) adds **zero** new fields to `CapabilityCall`,
`CapabilityResult`, or the `AIExecutionMapper` boundary. This is worth stating plainly as a success, not
just an absence of problems: Phase 6's contract, written before any of Phase 7's routing machinery was
designed, already had the right shape to absorb all of it without a schema change. That's a genuine
validation of Phase 6's `calls: list[CapabilityCall]` redesign (Phase 6 review §3) — it was designed for
exactly this kind of internal complexity growth, and it worked.

**The one place this "invisible by construction" property creates a real cost, not just a benefit**, is
Critical Risk 2 (shadow cost of failed internal attempts, baseline §17.2/§23). The same design property that
keeps `CapabilityCall` clean also means failed-attempt cost has structurally nowhere to go without a
deliberate, separate telemetry path. This isn't a flaw in the "invisible by construction" decision — it's
the direct, honest tradeoff that decision makes, and the baseline already names it as an unresolved risk
rather than hiding it. This review agrees with the baseline's own assessment here and doesn't add a new
finding — it confirms the existing one is correctly the most important unresolved item in the whole
document.

---

## 5. Tool calling — does the design survive a *planning* capability making 10+ sequential tool calls?

The baseline's answer (§11) is "yes, mechanically" — every `generate()`/tool-execution round produces its
own `CapabilityCall`, and `CapabilityResult.calls` is already an unbounded list. This review confirms that
holds at 10+ rounds exactly as it holds at 2.

**What doesn't fully hold: the round ceiling.** The baseline reuses `MAX_AGENT_ROUNDS` (§11) as "the
existing accepted system-wide ceiling concept" without specifying **where that ceiling is actually enforced
for a tool-calling capability specifically.** `MAX_AGENT_ROUNDS` (per `CLAUDE.md`/Phase 5-era docs) was
established in the context of Workflow-level `next_context` chaining between separate step executions
(different `Capability.execute()` calls across a run) — it is not obviously the same concept as "how many
times may `Capability.execute()` call `generate()` internally within *one* execution." The baseline treats
these as "the same ceiling, not a second competing one," but doesn't show they're actually the same counter
measured in the same place. **This is a real ambiguity, not a settled reuse.** Two readings are both
plausible from the baseline's text: (a) `MAX_AGENT_ROUNDS` is a single shared budget across both meanings
(a tool-calling capability making 3 internal rounds "spends" the same budget a 3-step Workflow chain would),
or (b) they're conceptually parallel but numerically independent ceilings that happen to share a name and a
default value. **Recommended: treat as (b) explicitly** — a per-`Capability`-execution internal round
ceiling (name it `MAX_TOOL_ROUNDS`, distinct constant, same default value as `MAX_AGENT_ROUNDS` purely by
coincidence of both being "3," not by being the same counter) — because conflating them means a
tool-calling capability's internal loop silently consumes budget from an unrelated Workflow-level concept
it has no visibility into and didn't cause. **Flagged as a gap in the baseline, not present in its own Open
Questions list — should be added.**

---

## 6. Retry-multiplication ceiling — does §8's "reviewed number" discipline survive at 50 capabilities, many authors?

The baseline is honest that this is "a process discipline, not a code-enforced ceiling" (Critical Risk 5,
§23) — and at 7 capabilities, single-author (the state of this codebase today), that's a reasonable amount
of trust to place in process. **At 50 capabilities, plausibly multiple contributors over time, this review
disagrees with leaving it purely a process discipline** — the exact failure mode named (a capability author
setting `max_attempts=10` and a Gateway config of `max_fallback_attempts=10` without noticing the product)
is precisely the kind of mistake that's invisible in code review unless someone happens to multiply two
numbers defined in two different files.

**Proposed, for discussion:** a boot-time (not runtime) validation — when `CapabilityRegistry` seals (or a
parallel validation step immediately after), compute
`WorkflowRetryPolicy.max_attempts × max_fallback_attempts × (1 + max_same_candidate_retries)` for every
registered `Capability`'s effective configuration and raise a boot-time error (not a warning — consistent
with this system's existing "no dynamic discovery, fail loud at boot" ethos) if it exceeds a configured
ceiling (e.g. 30). This is cheap — pure arithmetic over already-loaded config, no new runtime cost — and
converts the baseline's "reviewed number" discipline into something that actually can't ship silently
wrong. **This is the review's strongest concrete recommendation**, precisely because the baseline already
did the hard part (identifying the risk and the exact formula) — this only proposes making the check
mechanical instead of aspirational.

---

## 7. Configuration — `enabled_providers` list plus per-provider `SecretStr` fields, at 10 providers

The baseline's `core/config.py` extension (§18) — one `SecretStr | None` field per provider plus an
`enabled_providers: list[str]` — works at 7 providers exactly as cleanly as it does at 3. This review's only
addition: **the baseline doesn't specify what happens when `enabled_providers` names a provider with no
matching `SecretStr` field at all** (a config typo, or a provider added to the enabled list before its
credential field was added to `Settings` in the same PR). Given this system's established "fail loud at
boot" pattern (registries raise on bad registration, not silently skip), the same discipline should apply
here: **`build_provider_registry()` should raise at boot** (not silently skip the misconfigured provider) if
`enabled_providers` names something the settings/factory list doesn't recognize — consistent with, not a new
addition to, the baseline's own stated philosophy, just not spelled out for this specific edge in §18.

---

## 8. Hidden couplings not named in the baseline's own review sections

The baseline is unusually thorough about naming its own tensions (§7.1, §17.2, §23's five risks) — this
section looks for what's still missing, the same exercise Phase 6's review did in its §9.

1. **`ModelDescriptor.reasoning_tier` and the `REASONING` routing objective (baseline §6) have no defined
   relationship to `requires_tools`/`requires_structured_output`.** A capability wanting "the best reasoning
   model that also supports tools" has no documented way to combine a hard filter with the `REASONING`
   objective simultaneously — is `objective=REASONING` combined with `requires_tools=True` well-defined
   (filter first, then rank by reasoning tier among survivors — which the algorithm in §6 actually does
   support structurally), or does the baseline's prose only ever describe these as if a request picks one
   objective in isolation? Re-reading §6's algorithm: filtering and ranking are already separate steps, so
   this combination **does** work mechanically — but the baseline's own examples never show a combined case,
   which is worth adding for clarity, not because the mechanism is broken.
2. **The Model Registry's `quality_tier` field (§6.1, proposed but not fully specified) has no defined
   relationship to `reasoning_tier`.** Are these two independent axes (a low-quality-tier model could still
   have `reasoning_tier="extended"`) or is one expected to imply something about the other? The baseline
   proposes both fields in different subsections (§5's `ModelDescriptor` doesn't actually include
   `quality_tier` at all — it's introduced only in prose in §6.1 as a *recommended addition*, not shown in
   the schema). **This is a real internal inconsistency**: §6.1 recommends shipping `quality_tier` "as a
   static field now," but §5's `ModelDescriptor` code block (written earlier in the same document) doesn't
   include it. Either §5's schema is incomplete relative to the document's own final recommendation, or
   §6.1's recommendation wasn't actually adopted into the canonical schema shown in §5. **Should be
   reconciled before this becomes a Contract** — the two sections currently disagree with each other.
3. **`RateLimitKey.tenant_id` (§16) is explicitly named as unused/forward-compatible-only** — consistent
   and fine, but the baseline doesn't ask the symmetric question for `ModelDescriptor`/`ProviderDescriptor`:
   is there any per-tenant *provider access* concept anticipated (tenant A allowed only OpenAI, tenant B
   allowed everything)? Not required by the current brief (no multi-tenancy exists), but if `tenant_id` is
   being pre-plumbed into the Rate Limiter "ahead of need" (baseline's own stated rationale, echoing
   `preferred_provider`'s precedent), the same ahead-of-need reasoning arguably applies to Provider Registry
   access control too, and the baseline is inconsistent in applying it to only one of the two places
   multi-tenancy would eventually touch. **Minor, not urgent** — named for completeness, not as a defect.

---

## 9. Breaking the architecture — one future scenario not in the baseline's own list

The baseline's Critical Risks and Open Questions are thorough; this review adds one scenario not explicitly
walked through: **a single `Capability` execution that legitimately needs two different routing objectives
for two different calls it makes internally** — e.g. a planning capability that wants `LOWEST_COST` for a
cheap intent-classification sub-call and `BEST_QUALITY` for the final synthesis call, within the *same*
`Capability.execute()` invocation (the same scenario Phase 6's own review used to justify
`CapabilityResult.calls` becoming a list in the first place).

**Does this already work?** Yes, mechanically — `RoutingCriteria` (and therefore `objective`) is constructed
per-`GenerateRequest`, not once per `Capability` execution, so two `generate()` calls within one `execute()`
can trivially carry two different objectives. **This is not a gap** — it falls out correctly from the
existing per-request design. Worth stating explicitly as a confirmed capability, though, since the baseline
never walks through this exact case even though it's the most natural stress test of "does routing survive
multi-call capabilities" and the answer deserves to be on record rather than just inferable.

---

## Honest final assessment

This design is more internally consistent than it might first appear from the sheer number of sections, and
its central architectural bet — that everything below `LLMGateway` (routing, fallback, retry, caching, rate
limiting) can remain entirely invisible to `CapabilityCall`/`AIExecution` — holds up under review (§4). That
bet is the single most load-bearing decision in the whole document, and it's the right one: it's exactly
why adding provider #10 or model #100 costs nothing structurally (§1), and why none of Phase 6's already-approved
contracts needed to be touched to accommodate any of Phase 7's machinery.

**Three things should be fixed before this becomes a Contract, in priority order:**

1. **§8 (this review)** — the `quality_tier`/`reasoning_tier` schema inconsistency between §5 and §6.1 of
   the baseline is a real internal contradiction, not a stylistic nit, and would produce a broken
   `ModelDescriptor` if implemented as currently written across both sections.
2. **§6 (this review)** — the retry-multiplication ceiling should become a boot-time-enforced check, not a
   process discipline, given 50-capability, multi-contributor scale is explicitly the brief's own stated
   target.
3. **§5 (this review)** — the `MAX_AGENT_ROUNDS`/tool-calling-round-ceiling ambiguity needs an explicit
   answer (this review recommends treating them as separate counters) before any tool-calling capability is
   built against an assumption that turns out to be wrong.

Two of the baseline's own named items deserve to be elevated rather than left as merely "open": **Open
Question 3 (tool idempotency)** is, as the baseline itself says, the highest-severity open item in the
document, and this review agrees — it's the one gap where "no recommendation yet" is the honest and correct
answer, not a placeholder that should have been filled in. **Critical Risk 2 (shadow cost)** is the second
most important, precisely because the design property that causes it (§1's governing principle) is also the
design's biggest strength — it's a genuine, structural tradeoff, not an oversight, and this review's §4
confirms there isn't a free way to have the clean boundary *and* full attempt-level cost visibility
simultaneously without adding new machinery.

**What I do believe:** the layering — `Capability` → `LLMGateway` (Phase 6, unchanged) → Routing Gateway →
Provider Registry / Model Registry / Router / Fallback Chain → Provider Adapter → SDK (Phase 7, this
document) — is the right shape, is provider-count-agnostic and model-count-agnostic by construction, and
gives every future provider (including ones not on today's seven-name list) a mechanical, zero-Gateway-contract-change
path to being added. That is a genuinely stable foundation for the next several years' worth of provider
churn. It is not, and this review does not claim it to be, a design with every internal detail already
consistent — §8's schema mismatch is a concrete, fixable inconsistency that exists today, in this baseline,
not a hypothetical future one.
