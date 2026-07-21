# Phase 10 — Implementation Advisory

**Status: advisory document only.** Records implementation guidance surfaced during the
Implementation Plan Audit (`docs/phase10_implementation_plan_audit.md`). This document does not
modify, does not reinterpret, and is not a substitute for `docs/
phase10_production_content_pipeline_architecture_contract.md` (the frozen Architecture Contract) or
`docs/phase10_implementation_plan.md` (the frozen Implementation Plan). Both remain authoritative
and unchanged.

---

## 1. Planning Audit Summary

Implementation planning is **approved**
(`docs/phase10_implementation_plan_audit.md`, verdict: PHASE 10 IMPLEMENTATION PLAN APPROVED,
9/10). Architecture is unchanged — the Architecture Contract (revision 3) remains frozen and
unmodified, and the Implementation Plan's milestones, file scope, and implementation order remain
unmodified. Implementation may begin.

---

## 2. Advisory

The Planning Audit's one MAJOR finding (non-blocking) concerns `docs/
phase10_implementation_plan.md`'s Milestone 4 sketch of `scripts/run_content_generation.py`. As
drafted, the sketch's `run_content_generation_for_event()` unconditionally calls
`assemble_ai_integration_layer()`, which always constructs the real, live provider stack — with no
seam for a fake `LLMGateway`/`CapabilityRegistry` to be substituted in. This is in tension with the
Implementation Plan's own Verification Plan for Milestone 4, which requires this same function to
be exercised against fakes (Contract §12's "CLI tests" — invoked directly with fakes, mirroring how
`services.triage_orchestrator.run_triage_cycle()` is tested, not the thin script wrapper).

This repository already has a working precedent for exactly this kind of seam:
`services/triage_orchestrator.py::run_triage_cycle()` accepts `session_factory:
async_sessionmaker[AsyncSession] = async_session_factory` (`services/triage_orchestrator.py:
222-223`) — a keyword parameter defaulting to the real, production factory, but overridable by a
caller (a test) that wants an isolated one. Production callers never pass it explicitly and get
production behavior automatically; tests pass a fake/isolated one explicitly. Nothing about this
pattern required a new abstraction, a new file, or a Contract amendment — it is an existing,
already-approved shape in this codebase.

This is an **implementation recommendation, not an architectural requirement**. The Architecture
Contract does not mandate a specific injection mechanism for `scripts/run_content_generation.py`,
and this advisory does not add one to it. It is guidance for whoever implements Milestone 4, not a
new binding rule — the Implementation Plan's own testability goal (Contract §12's CLI tests) is
achievable without this change too, just less directly than with it.

---

## 3. Recommendation

When implementing `scripts/run_content_generation.py` (Milestone 4), prefer allowing
`run_content_generation_for_event()` (or whatever its final internal `services/`-layer function is
named, per the Implementation Plan's own naming) to accept an optional, already-approved
abstraction for tests — a `CapabilityRegistry` (or equivalent, e.g. the assembled AI integration
layer object) — as an injectable parameter, mirroring `run_triage_cycle()`'s
`session_factory` parameter shape exactly.

**Default behavior must remain production behavior**: if the caller passes nothing, the function
must construct the real registry via `assemble_ai_integration_layer()` exactly as the Implementation
Plan's Milestone 4 sketch already describes — the default path is unchanged. Only an explicit,
opt-in override (as a test would supply) bypasses it. No script behavior visible to a human running
it manually changes.

---

## 4. Non-goals

This advisory:
- does **not** modify the Architecture Contract.
- does **not** modify the Implementation Plan.
- does **not** authorize any additional production file beyond the nine already authorized by the
  Architecture Contract (§3) and reflected in the Implementation Plan.
- does **not** change Phase 10's milestones, their objectives, or their completion criteria.
- does **not** change the Implementation Plan's recommended implementation order.

It is a note for the implementer to consider while building the already-planned
`scripts/run_content_generation.py`, nothing more.

---

## 5. Ready For Implementation

Phase 10 is cleared to enter implementation. Implementation should follow the frozen Architecture
Contract (`docs/phase10_production_content_pipeline_architecture_contract.md`, revision 3) and the
frozen Implementation Plan (`docs/phase10_implementation_plan.md`) exactly as approved, incorporating
this advisory's Milestone 4 recommendation at the implementer's discretion.

---

PHASE 10 ADVISORY RECORDED — CLEARED FOR IMPLEMENTATION
