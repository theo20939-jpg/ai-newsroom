# R2 Shadow Synthesis Contract

**Status: DESIGN ONLY — no code written under this contract.** Builds on the pushed R2 Shadow v1
checkpoint (`c799c14aae6e0c5df1b5e8f0e80018475d892b63`, branch `feature/r2-shadow-preparation`,
isolated worktree `../ai-newsroom-r212`). This is the "second canary" R2 Shadow v1's own execution
plan explicitly deferred: *"the optional `--with-llm --single-attempt` synthesis stage... explicitly
deferred to a second canary."* Implementation waits for explicit confirmation, same discipline as
every prior R2 Shadow design round.

## 1. What R2 Shadow v1 already does (recap, unchanged by this contract)

`scripts/_recap_r2_shadow_batch.py` — deterministic-only, read-only, bounded (`--limit`,
default 20, ceiling 200), batch collector over recent Stories. Per Story: `build_shadow_report()`
calls `scan_story_readiness()` then, when a candidate exists, `build_event_recap_candidate(...,
force_shadow=True)` — never a synthesis call, never a Gateway import. Output: `story_<id>.json` /
`story_<id>.txt` per Story, `shadow_summary.json` per run. `evaluation_status` is a shadow-local
vocabulary (`OBSERVED`/`NEEDS_REVIEW`/`REJECTED`), deliberately never inheriting
`services/fact_safety.py`'s `pass`/`review`/`block` words.

**This contract does not change any of the above.** It adds one new, explicitly opt-in,
single-Story capability on top of it.

## 2. Objective

Let a human, having already reviewed a specific Story's R2 Shadow v1 output, request **exactly one
real, controlled EVENT_RECAP synthesis call** for that one Story, and see the result folded into
the same shadow output shape — never a batch, never automatic, never wired to any delivery path.

## 3. R2.11 integration — why this matters more once money is involved

`docs/r2_11_announcement_identity_findings.md`'s own conclusion: `announcement_count` is a raw,
report-level cluster count from the frozen `cluster_announcements()` — it can be satisfied by
several publishers describing ONE real event with zero actual development, and no reliable
deterministic signal exists to tell that apart from genuine multi-stage evolution (three
independent findings, all still valid, none touched since). While R2 Shadow v1's own deterministic
stage only *costs* a few extra read-only queries either way, a synthesis call spends real money on
whatever `announcement_count` happens to say — so this same finding now carries financial and
editorial-quality weight it did not have in Shadow v1's own text-only prototype.

**This contract does not attempt to fix that** (still DESIGN ONLY / BLOCKED, per R2.11's own
verdict — no new deterministic rule is proposed here). It instead makes the risk a hard
*procedural* gate rather than leaving it implicit:

- A Story is only eligible for shadow synthesis if a human has already read its R2 Shadow v1
  `story_<id>.json`/`.txt` output and the `quality_notes` entry this contract's own §7 requires
  ("announcement_count reflects raw report-level clusters, not confirmed distinct developments").
- Selection is always by explicit `--story-id`, never derived automatically from a `readiness_state`
  or `evaluation_status` value — `OBSERVED`/`NEEDS_REVIEW` from Shadow v1 is triage information for
  a human, never itself a green light to spend money.
- The evidence bundle a synthesis call actually reads (`render_event_recap_bundle_text()`) already
  carries its own defense here (§4) — this contract's job is making sure a human sees the
  R2.11 caveat *before* triggering the spend, not relying on the prompt alone to save them from a
  bad Story selection.

## 3a. Human Review Protocol (owner-required addition, formalized)

**Named rule: shadow synthesis runs only after the Shadow v1 artifact for that exact Story has been
viewed.** Formalizing §3's own procedural gate as a named, standalone protocol rather than leaving
it folded into the R2.11 discussion:

1. **Hard precondition, code-enforced**: `--from-shadow-run <dir> --story-id <id>` must resolve to
   an existing `<dir>/story_<id>.json` (R2 Shadow v1's own output). If it does not exist, the script
   refuses to run — exits before opening any DB connection, before any Gateway import. This is the
   one part of "viewed" that code can actually verify: the artifact was produced, meaning R2 Shadow
   v1 already ran for this Story.
2. **Honest limit, stated explicitly**: no code can verify a human actually *read* the file — this
   protocol does not pretend otherwise. What code enforces is existence; what remains a human
   responsibility is judgment. This contract does not simulate a review it cannot actually perform.
3. **Reinforcement, not just a gate**: at invocation time, before any spend, the script re-prints
   the prior artifact's own key fields to the operator's terminal — `readiness_state`,
   `evaluation_status`, `announcement_count`, and every `quality_notes` entry (especially the
   R2.11 caveat) — so the information that should drive the human's decision is surfaced again at
   the exact moment spend is about to happen, not merely available somewhere in a file they may
   have opened minutes or days earlier.
4. **No interactive prompt.** Consistent with this codebase's own established CLI discipline
   (R2.10 Night 2's own explicit "do not add interactive prompts that break automation" - `scripts/
   _recap_r2_event_shadow.py::_cli_safety_warnings()`), this protocol never blocks on a y/n
   confirmation. The precondition check (item 1) and the terminal re-print (item 3) are the
   complete, automation-compatible enforcement this stage provides — running the script at all,
   with the required flags, already IS the human's deliberate action.

## 4. Reused architecture — nothing new invented

| Piece | Source | Reuse discipline |
|---|---|---|
| Candidate | `services/event_recap.py::EventRecapCandidate` / `build_event_recap_candidate()` | Unchanged — the same object R2 Shadow v1 already builds |
| Evidence text | `services/event_recap.py::render_event_recap_bundle_text()` | Unchanged — the EXACT text the synthesis `GenerateRequest` embeds; already carries its own R2.11-relevant caveat verbatim: *"TIMELINE (order of PUBLICATION only... do not narrate multiple publications as proven sequential developments unless the evidence itself states that)"* |
| Synthesis call | `services/event_recap.py::synthesize_event_recap()` | Unchanged — makes exactly one `LLMGateway.generate()` call via `capabilities.gateway_call.call_generate()`; raises `EventRecapSynthesisError` on any failure or malformed output, never returns a partial candidate |
| Fact verification | `services/event_recap.py::_verify_synthesis_facts()` → `services/fact_safety.py::evaluate_fact_safety()` | Unchanged, frozen — `FactVerificationResult.status` ∈ `pass`/`review`/`block`/`not_run` |
| Internal-vocabulary guard | `services/event_recap.py::_detect_internal_vocabulary_leak()` | Unchanged |
| Prompt | `prompts/event_recap/v2.yaml` | **FROZEN, never touched** |
| Single-attempt guarantee | `scripts/_recap_r2_event_shadow.py::_SingleAttemptGateway` / `_build_single_attempt_gateway()` | Reused **by reference to the same pattern**, not by importing the private class across scripts (see §6) — reads the real, already-constructed `RoutingEngine`/`ProviderRegistry`/health/cache/cost/budget/rate-limiter, overrides only `max_same_candidate_retries=0` and `max_fallback_attempts=1` |
| Gateway boot | `integrations.llm_gateway.boot.assemble_ai_integration_layer()` | Unchanged — called only after the read-only DB transaction has already been rolled back and closed (see §6, transaction-before-Gateway ordering) |
| Runtime context | `schemas.capability.RuntimeContext` | Unchanged shape — synthetic `task_id`, real `event_id=candidate.anchor_event_id`, `capability_name` distinguishing this as a shadow call, `priority=TaskPriority.C` |

No new LLM architecture, no new Gateway, no second FallbackPolicy mechanism beyond the one
`_SingleAttemptGateway` already establishes.

## 4a. Cost safety (owner-required addition, revised — zero `services/event_recap.py` changes)

**Owner correction (this round): checked whether `max_tokens`/`reasoning_effort` are achievable
through an existing interface before proposing any change to `services/event_recap.py` — they are.
`services/event_recap.py` is not touched by this contract at all, for any reason, at this stage.**

`synthesize_event_recap(candidate, gateway, prompt_repository, *, runtime)` already takes `gateway:
LLMGateway` as a **caller-supplied** parameter — dependency injection is already the existing
interface here, exactly the seam this stage needs. `GenerateRequest` (`integrations/llm_gateway/
protocol.py`) is an immutable pydantic model (`model_config = ConfigDict(frozen=True, ...)`)
supporting the standard pydantic `.model_copy(update={...})` call to produce a modified copy without
mutating the original — confirmed by direct execution this session, not assumed. `capabilities/
gateway_call.py::call_generate()` calls `gateway.generate(stamped_request)` directly — the fully-
built, fully-metadata-stamped request reaches whatever `gateway` object the caller supplied,
unchanged by anything in `services/event_recap.py`.

**Consequence**: the new script's own single-attempt Gateway wrapper (§3 of the implementation
plan — already duplicated locally per script, never cross-imported, exactly like
`_SingleAttemptGateway` itself) can intercept the request inside its own `generate()` method and
apply `request = request.model_copy(update={"max_tokens": 1000, "reasoning_effort": "none"})`
before forwarding to the real routing engine — one line, entirely inside the new script, in the
exact same method that already reconstructs `RoutingCriteria` with an overridden `fallback` value.
No existing file needs any change for this.

Four independent controls, each tied to a concrete, already-existing mechanism — none invented for
this contract:

| Control | Requirement | Existing mechanism |
|---|---|---|
| Single attempt | Exactly one call to the shadow synthesis path per Story per invocation | `_SingleAttemptGateway`-pattern reuse (§4/§6) — mathematically guarantees at most one physical `generate()` call |
| No retry | Zero same-candidate retries | `FallbackPolicy(max_same_candidate_retries=0, ...)` — the existing script's own "one deliberate override," reused unchanged |
| No fallback | Zero fallback to a second/third-ranked model | `RoutingCriteria.fallback = FallbackEligibility(max_fallback_attempts=1)` — combined with zero retries, this caps the whole call at one physical attempt against the one top-ranked candidate, never a fallback switch |
| `max_tokens` | **Must be explicitly set, never left `None`/unbounded** | Applied via `request.model_copy(update={"max_tokens": 1000})` inside the new script's own Gateway wrapper (above) — no existing file touched |

**Recommended `max_tokens` value** (a starting point, not asserted as final — matches this
codebase's own established "reasoned default, refine from real evidence" discipline): the closest
real precedent is `capabilities/executor.py::_MAX_OUTPUT_TOKENS_BY_CAPABILITY["research"] = 1000`,
itself derived from real production-forensics truncation failures (raised 450 → 700 → 1000 against
measured `finish_reason="length"` failures) for a capability doing the same shape of work EVENT_
RECAP synthesis does — deterministic, bounded structured-JSON extraction from supplied evidence,
not open-ended editorial generation. Recommend starting from the same ~1000-token neighborhood and
recalibrating against real shadow-run truncation evidence exactly the way that dict's own history
did, never assumed correct in advance.

**Closely related, must not be overlooked**: `capabilities/executor.py`'s own module docstring
documents a real, already-fixed defect class (`docs/phase17_m4_1_reasoning_budget_fix_report.md`) —
the OpenAI Responses API draws reasoning and visible-answer tokens from the *same* `max_output_
tokens` pool, so an unmanaged `reasoning_effort` can silently consume the entire budget before any
visible JSON is written, regardless of how generous `max_tokens` is. `_REASONING_EFFORT_BY_
CAPABILITY["research"] = "none"` is the exact, already-proven-safe precedent for a deterministic-
extraction-shaped capability like this one (never `"low"`/`"medium"` without a documented reason,
per that same dict's own inline reasoning). Applied the same way, via the same `model_copy(update=
{"reasoning_effort": "none"})` call — no existing file touched.

## 4b. Output safety — `max_tokens` and `max_chars` (owner-required addition)

Two independent bounds, checked at two different points in the pipeline — an *input-side* cap on
what the model is allowed to generate, and an *output-side* cap on what the shadow script accepts
once generation is done:

| Bound | Value | Where enforced | Mechanism |
|---|---|---|---|
| `max_tokens` | `1000` | Request time (before the Gateway call) | §4a — `model_copy(update={"max_tokens": 1000})` in the new script's own Gateway wrapper |
| `max_chars` | `4000` | Response time (after `synthesize_event_recap()` returns, before any artifact is written) | New script measures `len(recap_title) + len(recap_summary) + sum(len(t) for t in key_takeaways) + sum(len(n) for n in uncertainty_notes)` (or the equivalent rendered `render_event_recap_telegram_preview()` text length — the implementation plan decides which) against `4000`; over the bound is treated as a `quality_notes` flag (escalating `evaluation_status` to `NEEDS_REVIEW` via the existing rule, §7), never a hard failure — `render_event_recap_telegram_preview()` already has its own hard `EventRecapTelegramPreviewTooLongError` at `4096` (Telegram's own real UTF-16 limit) as a second, independent, pre-existing layer; `4000` is deliberately tighter and shadow-specific, a belt-and-suspenders sanity bound layered on top of it, not a replacement for it |

Both bounds are plain integers, config-free at this stage (no new `core/config.py` setting) —
matching R2 Shadow v1's own constants (`DEFAULT_LIMIT`, `MAX_LIMIT`) living as script-local
constants rather than global settings, since nothing outside this one new script reads them.

## 4c. Synthesis scope (owner-required addition)

**The LLM transforms evidence into text. Nothing else.** Explicitly forbidden in any synthesized
output field:

- **External knowledge** — anything not present in `render_event_recap_bundle_text()`'s own output.
- **Assumptions** — filling a gap the evidence leaves open.
- **Predictions** — any statement about what will happen next.
- **Causal explanations without evidence** — asserting *why* something happened when the evidence
  only states *that* it happened.

**Existing coverage, and the one real gap.** `prompts/event_recap/v2.yaml` (frozen, verbatim rule
text) already substantially covers three of these four:
- *"Base every statement strictly on the evidence provided - never invent a fact, source, date,
  quote, or number."* — covers external knowledge and most assumption/invention risk.
- *"You never speculate about outcomes not stated in the evidence."* (system text) — covers
  predictions directly.
- *"Never invent chronology... do not narrate multiple publications as proven sequential
  developments unless the evidence itself states that."* — covers one specific causal/sequencing
  trap (mis-narrating publication order as event progression), the exact R2.11-adjacent protection
  already noted in §3/§4.

**Causal explanations more broadly are only implicitly covered** by the general "never invent"
rule — this was already identified as a genuine, disclosed gap in the R2.10 Night 2 Prompt v2
audit (`docs/r2_10_night2_forensics_and_runbooks.md`'s own "Proposed EVENT_RECAP v3 changes"):
*"Optionally make the 'no invented causal explanations' instruction explicit rather than relying
on the general anti-invention rule."* Since `prompts/event_recap/v2.yaml` is frozen and this
contract cannot propose editing it, the gap must be closed on the **shadow side**, not the prompt
side: a deterministic, post-synthesis detection pass, in the same spirit as
`_detect_internal_vocabulary_leak()`'s own small-explicit-term-list discipline (never a general
classifier, never silently rewriting output) — flag, via a `quality_notes` entry, any output
sentence containing an explicit causal connective ("because", "as a result", "this led to", "in
response to", "due to", and their Russian equivalents) whose asserted cause does not itself appear
as a distinct fact in the evidence bundle. **Owner-confirmed scope (this round): flag-only
metadata, full stop. No rewrite. No reject. No block.** This is a detection/flagging aid for the
human reviewer, never an automated rewrite, rejection, or block of any kind, under any
configuration — reliably verifying "is this specific causal claim evidenced" with certainty is not
achievable by keyword matching alone (the same precision caution R2.11's own conflict-detection
conclusion already established for a structurally similar problem), so this stays conservative:
flag for review, never silently pass, silently strip, or silently reject.

## 5. Hard safety requirements

| Control | Requirement | Enforcement |
|---|---|---|
| Telegram SEND | OFF, unconditionally | No `bot.*`/`worker.*` import anywhere — same AST-guard discipline as both existing scripts and R2 Shadow v1 |
| Database writes | OFF | Read-only transaction guard, closed **before** the Gateway is ever touched (§6) — matches `scripts/_recap_r2_event_shadow.py`'s own proven ordering exactly |
| Batch execution | **Explicitly forbidden at this stage** | One `--story-id` per invocation — no `--limit`, no loop over multiple Stories with `--with-llm` set. This is the one hard behavioral difference from R2 Shadow v1's own batch design |
| Automatic triggering | OFF | Manual CLI only, human-run, never registered with any scheduler/worker/Capability registry |
| Physical provider attempts | **At most 1** | `_SingleAttemptGateway`-equivalent reuse (§4/§6) |
| Cost visibility | Required | Print `LLM_ENABLED=True`, `SINGLE_ATTEMPT=True`, `MAX_PROVIDER_ATTEMPTS=1`, and the same post-call `physical_provider_attempts=`/`fallback_attempts=`/`same_candidate_retries=` line `scripts/_recap_r2_event_shadow.py` already emits, verbatim pattern |
| Human confirmation before spend | Required (Human Review Protocol, §3a) | `--story-id` and `--from-shadow-run` both required; the CLI refuses to run (exits before any DB connection) if no prior Shadow v1 `story_<id>.json` exists for that Story in the given directory — resolved, see §3a for the full protocol |
| `publishable` | Always `False` | Structural — `synthesize_event_recap()` never sets it otherwise; nothing in this contract changes that |

## 6. Sequencing (must not be reordered)

Exactly the ordering `scripts/_recap_r2_event_shadow.py::main()` already proves safe, reused
verbatim as a design constraint, not re-derived:

1. Open read-only DB transaction (`_verify_read_only()`).
2. Load the one Story, build the deterministic candidate (`force_shadow=True` if not naturally
   READY — a shadow synthesis run should be allowed to exercise a not-yet-READY Story, exactly like
   every other R2 diagnostic already does; `readiness_overridden` stays visible in the output,
   never hidden).
3. **Close the transaction — rollback, close connection, dispose engine.**
4. Only now: `assemble_ai_integration_layer()`, build `RuntimeContext`, build the single-attempt
   Gateway, call `synthesize_event_recap()`.
5. Write output (§7). No DB reopened at any point after step 3.

Step 3 happening strictly before step 4 is the one non-negotiable safety property carried over from
the existing script — the DB connection must never be open while a network call to a paid provider
is in flight.

## 7. Output artifacts (owner-corrected: separate files, not an embedded section)

**Correction from the initial draft**: the synthesis result is written to its own pair of files,
never merged into R2 Shadow v1's own `story_<id>.json`/`story_<id>.txt`. This keeps the free,
deterministic observation (Shadow v1) and the paid, synthesized result (this stage) on cleanly
separate, independently auditable artifacts — Shadow v1's own output file is never rewritten or
mutated by this stage, and the mere presence of a `story_<id>_synthesis.json` file is itself a
visible, at-a-glance record of "money was spent on this Story":

- **`story_<id>_synthesis.json`** — the synthesized fields (`recap_title`, `recap_summary`,
  `key_takeaways`, `uncertainty_notes`), `fact_verification` (verbatim `FactVerificationResult`),
  `quality_flags` (including any `internal_vocabulary_leak_detected:...` and, if §4c's own
  detection pass is implemented, any causal-claim flag), the cost-visibility fields from §4a
  (`physical_provider_attempts`, `fallback_attempts`, `same_candidate_retries`, `model_used`,
  `max_tokens` actually sent, `reasoning_effort` actually sent), and `readiness_state`/
  `publishable` **carried through read-only from the input candidate, clearly labeled as
  informational, never recomputed here** (see §7a).
- **`story_<id>_synthesis.txt`** — human-readable rendering. Recommend reusing
  `services/event_recap.py::render_event_recap_telegram_preview()` (the pure, already-built,
  already-tested R2.10 Night 2 prototype) rather than inventing new formatting — it already
  renders exactly these fields (title, summary, takeaways, uncertainty notes, source domains) in a
  bounded, Telegram-safe shape, and reusing it costs nothing new.

Both files are written **only after** a successful `synthesize_event_recap()` return — on
`EventRecapSynthesisError`, neither file is written (§8), matching "never a partially populated
candidate" carried through to "never a partially written artifact."

**`evaluation_status` computation, extended (still shadow-local, still never `fact_safety`
vocabulary as the enum itself)** — this remains a property of R2 Shadow v1's own base
`story_<id>.json`, not the new synthesis files, per §7a:
- `fact_verification.status != "pass"` → append a quality note (e.g.
  `"fact_verification_review"`/`"fact_verification_block"`, mirroring `EventRecapCandidate.
  quality_flags`'s own existing string, not inventing new wording) → this is exactly the existing
  `quality_notes`-triggers-`NEEDS_REVIEW` rule from R2 Shadow v1's own `_compute_evaluation_status()`
  — no new branch, the existing rule already covers it once the note is added.
- `internal_vocabulary_leak_detected:...` in `candidate.quality_flags` → same treatment, already
  falls through the same existing rule.
- `EventRecapSynthesisError` (Gateway failure or malformed output) → the whole run for that Story
  fails loudly (mirrors `synthesize_event_recap()`'s own "never returns a partially populated
  candidate" guarantee) — the script should exit non-zero and write neither synthesis artifact.

## 7a. Hard separation (owner-required addition): readiness_state is metadata only

**Already true today, structurally, in unmodified code — this section states an existing
guarantee as a locked invariant, not a new mechanism to build.** `synthesize_event_recap()`'s own
return statement (`services/event_recap.py`) is `dataclasses.replace(candidate, recap_title=...,
recap_summary=..., key_takeaways=..., uncertainty_notes=..., fact_verification=...,
quality_flags=..., publishable=False)` — it does not touch `readiness_state`,
`readiness_overridden`, `story_integrity_eligible`, or `announcement_count` at all; those fields
pass through from the input candidate completely unchanged, because `dataclasses.replace()` only
overrides the fields explicitly named. `publishable` is set to `False` *unconditionally* in that
same call, regardless of `fact_verification.status` — confirmed both by direct code inspection and
by an existing regression test (`tests/test_event_recap.py::
test_publishable_stays_false_across_every_reachable_r2_path`, R2.10 Night 2).

**The rule this contract locks in**: the eventual implementation must call the real, unmodified
`synthesize_event_recap()` — never a reimplementation, wrapper, or "improved" version that computes
its own `publishable`/`readiness_state`. A synthesis result, however clean, well-grounded, or
fully-`pass`-verified, **cannot** promote a Story past whatever `readiness_state` the deterministic
stage already assigned, and **cannot** make it publishable. `readiness_state` in the synthesis
output file (§7) is read-only, carried-through metadata for a human's own context — never an input
to any future decision this stage itself makes.

## 8. What this contract explicitly forbids

- Batch/looped synthesis calls in one invocation (§5).
- Any Telegram, worker, or delivery-path import, anywhere.
- Any database write, at any stage, before or after the Gateway call.
- Reopening the DB transaction after the Gateway call for any reason.
- Selecting a Story for synthesis without an explicit `--story-id` (no auto-selection from a batch
  run's own `readiness_state`/`evaluation_status`).
- Any new RECAP renderer, `RecapVisual` implementation, or `brand_renderer.py` change (unchanged
  from R2 Shadow v1's own observation-only visual boundary).
- Any modification to `prompts/event_recap/v2.yaml`, `services/recap_event.py`, or any other frozen
  file.
- Treating a `PASS`-shaped `fact_verification.status` as authorization to change `publishable` —
  it never changes, structurally, regardless of verification outcome.
- Sending a synthesis `GenerateRequest` with `max_tokens=None` (unbounded) through this stage's own
  Gateway wrapper — §4a's explicit cap is mandatory, not optional, here specifically. (The
  pre-existing `scripts/_recap_r2_event_shadow.py` caller keeps its own current unbounded behavior
  unchanged — out of scope to touch, and moot regardless, since §4a's resolution never modifies
  `services/event_recap.py` in the first place.)
- Any code path, in this stage or a future one, that lets a synthesis result change
  `readiness_state`, `readiness_overridden`, `story_integrity_eligible`, or `announcement_count` on
  the candidate — §7a's separation is absolute.
- Silently rewriting or stripping a detected unevidenced-causal-claim from the model's own output
  text (§4c) — flag via `quality_notes` only, never a brittle string-replacement "fix" (mirrors
  `_detect_internal_vocabulary_leak()`'s own explicit "never a rewrite/sanitizer" discipline). This
  is metadata-only, full stop — no rewrite, no reject, no block, under any configuration.

## 9. Open questions for the implementation plan (not decided here)

**Resolved this round**: whether `--from-shadow-run` is a hard requirement (YES — §3a) and whether
`services/event_recap.py` needs any change (NO — §4a, achieved entirely via the existing `gateway`
dependency-injection interface).

1. New script (`scripts/_recap_r2_shadow_synthesize.py`) vs. an additive `--with-llm --story-id`
   mode on the existing batch script — recommend a new script, same reasoning as R2 Shadow v1's own
   §1 (single-Story deep operation vs. multi-Story batch stay separate, composable tools).
2. Whether `model_used`/cost fields should also be written to a running-total file across multiple
   separate invocations, or stay per-invocation only (leaning per-invocation only, per R2 Shadow
   v1's own "no retention policy this canary" precedent).
3. Exact `max_tokens`/`reasoning_effort` values to ship with (§4a proposes ~1000/`"none"` as a
   starting point, not a final number) and the exact causal-connective term list for §4c's
   detection pass (a small, explicit, hand-curated list, same discipline as
   `_INTERNAL_VOCABULARY_TERMS` — the exact terms are an implementation-plan decision, not fixed
   here).
4. Whether `max_chars` (§4b) measures the raw synthesized-field concatenation or the fully-rendered
   `render_event_recap_telegram_preview()` output text.

No implementation begins before these are resolved and the contract itself is confirmed.
