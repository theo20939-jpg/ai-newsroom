# Phase 13 — Automatic News Analysis Implementation Plan

Planning only. No production code, test, migration, or Contract file was modified to produce this
document. No worker was started. No external API/network call was made.

## 1. Status / Authority

**Status: Implementation Plan, revision pass 3, pending Final Gate Audit.** The Architecture Contract
(`docs/phase13_automatic_news_analysis_architecture_contract.md`, "PHASE 13 CONTRACT READY FOR
AUDIT") was approved by `docs/phase13_automatic_news_analysis_contract_audit.md` ("PHASE 13 CONTRACT
APPROVED — READINESS SCORE: 9/10", CRITICAL=0, MAJOR=0, two MINOR findings N1/N2). This plan
reinterprets nothing the Contract decided; it resolves N1/N2 mechanically (§8/§9 below), as
instructed, without reopening architecture.

**This revision**: the first version of this Plan ("PHASE 13 IMPLEMENTATION PLAN READY FOR AUDIT")
was audited in `docs/phase13_automatic_news_analysis_implementation_plan_audit.md` ("PHASE 13
IMPLEMENTATION PLAN NOT READY — CORRECTIONS REQUIRED", readiness 5/10, 3 MAJOR + 2 MINOR
findings). This revision resolves exactly those five findings — F1 (§9.1, broken eligibility-query
syntax replaced with the verified-correct `.as_string()`), F2 (§14, false M7 isolation claim
replaced with a direct pre-verified-`task_id` invocation strategy), F3 (§4/§7/§19,
`tests/test_openai_strict_schema_compliance.py` added to scope), F4 (§8.1, precedented
`# type: ignore[attr-defined]` added), F5 (§18/§19, mid-batch per-task-vs-cycle-level failure
distinction added) — and nothing else. No architecture decision already frozen by the Contract or
by the first version of this Plan is reopened.

**This second revision (Correction Pass 2)**: the once-revised Plan ("PHASE 13 IMPLEMENTATION PLAN
REVISION COMPLETE — READY FOR RE-AUDIT") was independently re-audited in
`docs/phase13_automatic_news_analysis_implementation_plan_final_reaudit.md` ("PHASE 13
IMPLEMENTATION PLAN NOT READY — CORRECTIONS REQUIRED", readiness 6/10). Every finding from the
first correction pass (F1-F5) was reconfirmed resolved; the re-audit's own independent, broader
grep found two new MAJOR findings — RA-1 and RA-2 — both a single root cause: two pre-existing,
currently-passing tests (`tests/test_phase9_research_intelligence_integration.py`,
`tests/test_phase10_capability_registration.py`) hardcode the assumption that `"engagement"` is an
unregistered `Capability` name, which Phase 13's own M1 milestone makes false. This revision
resolves exactly RA-1 and RA-2 — both files added to file scope (§4), both replacement test designs
frozen (§7.4/§7.5), M1's own atomic all-seven-together completion rule added (§7), a new M1
Regression Matrix added (§7.6), M6's own gate updated to run both as focused regressions before the
full suite (§12), the Risk Register and Exact File Counts updated (§26/§28) — and nothing else. No
architecture decision, and none of the five findings resolved in the first correction pass, is
reopened.

**This third revision (Correction Pass 3)**: the twice-revised Plan ("PHASE 13 IMPLEMENTATION PLAN
REVISION PASS 2 COMPLETE — READY FOR FINAL RE-AUDIT") was independently re-audited in
`docs/phase13_automatic_news_analysis_implementation_plan_test_scope_final_reaudit.md` ("PHASE 13
IMPLEMENTATION PLAN NOT READY — CORRECTIONS REQUIRED", readiness 7/10). Every finding through
RA-1/RA-2 was reconfirmed resolved; the re-audit found one new MAJOR finding — TS-1 — a
second-order effect of RA-1's own fix: §7.4's own replacement test, required to prove `NEWS_
ANALYSIS` reaches `COMPLETED`, reintroduces the exact three-token combination a separate,
pre-existing static-scan meta-test (`tests/test_phase9_cross_cutting_regression.py`) flags, while
the old exemption sentinel is deleted by the same fix. This revision resolves exactly TS-1 — the
file added to scope (§4), the exact one-line sentinel substitution frozen with a required
RED/GREEN proof (§7.7), M1's own atomic-ownership rule expanded from seven to eight items (§7),
the M1 Regression Matrix extended to eight rows (§7.6), M6's own focused-regression list extended
to three files (§12), the Risk Register and Exact File Counts updated (§26/§28) — and nothing
else. No architecture decision, and none of the findings resolved in either prior correction pass,
is reopened.

## 2. Baseline Re-verification

- `git rev-parse HEAD` = `e6cf33786cd36eadc438d4b55cfb6d5224ffbcd8` — the Phase 12 checkpoint,
  identical to every Phase 13 governance document's own citation.
- `git status --short` — only the same pre-existing, unrelated Phase 9/9.5/10/11-diagnostic
  documentation backlog; zero implementation drift.
- Re-read directly this session (not trusted from prior reports): `workflows/runner.py` (full),
  `capabilities/registry.py`, `capabilities/executor.py`, `capabilities/intelligence_capability.py`,
  `schemas/capability_definition.py`, `services/freshness.py`, `database/models/editorial_task.py`,
  `database/models/news_event.py`, `tests/test_workflow_runner.py` (full, 312 lines) —
  every fact this Plan relies on is independently re-confirmed, not copied forward.

**No Contract/source contradiction found. Proceeding.**

## 3. Implementation Boundary

```
EditorialTask(NEWS_ANALYSIS, CREATED)
  → SQL-side eligibility query (§12, N2 resolution)
  → WorkflowRunner atomic claim (§8, N1 resolution)
  → research (existing, unmodified)
  → intelligence (existing, unmodified)
  → engagement_analysis (NEW: EngagementCapability)
  → NEWS_ANALYSIS COMPLETED / FAILED
  → STOP
```

No automatic `CONTENT_GENERATION`. No `ContentDraft`. No migration.

## 4. Exact File Scope

| File | Status | Milestone | Exact change | Why required | Contract authorization |
|---|---|---|---|---|---|
| `workflows/runner.py` | MODIFY (narrow) | M2 | Replace `run()`'s `CREATED→RUNNING` read-then-write (lines 111-123) with an atomic conditional `UPDATE` + explicit in-memory sync (§8) | Closes the only genuine concurrency gap (Contract §10) | Contract §26, explicit |
| `capabilities/registry.py` | MODIFY (narrow) | M1 | Add one `registry.register(ENGAGEMENT_CAPABILITY_DEFINITION, EngagementCapability(gateway, prompt_repository))` line | Makes `"engagement"` resolvable | Contract §26, explicit |
| `core/config.py` | MODIFY (narrow) | M4 | Add 4 `Settings` fields (§17) | Contract §22 | Contract §26, explicit |
| `docker-compose.yml` | MODIFY (narrow) | M4 | Add 1 service (§18) | Contract §23 | Contract §26, explicit |
| `capabilities/engagement_capability.py` | NEW | M1 | `EngagementCapability`, `ENGAGEMENT_CAPABILITY_DEFINITION` | Contract §6/§7 | Contract §26, explicit |
| `prompts/engagement/v1.yaml` | NEW | M1 | Prompt + strict output schema | Contract §8 | Contract §26, explicit |
| `worker/analysis_main.py` | NEW | M4 | Entry point (mirrors `worker/main.py`) | Contract §12 | Contract §26, explicit |
| `worker/analysis_cycle.py` | NEW | M3 | Eligibility query + sequential claim/execute loop | Contract §12/§13 | Contract §26, explicit |
| `tests/test_engagement_capability.py` | NEW (test) | M1 | Unit tests (§19) | Contract §28 | Contract §26, explicit |
| `tests/test_workflow_runner.py` | MODIFY (append only) | M2 | Add atomic-claim concurrency tests (§19); **zero existing test in this file is modified or removed** (§10) | Contract §28 | Contract §26 ("Test files... not frozen more precisely") |
| `tests/test_analysis_worker_cycle.py` | NEW (test) | M3 | Eligibility, batch cap, race-loss, sequential-execution tests | Contract §28 | Contract §26 |
| `tests/test_analysis_worker_main.py` | NEW (test) | M4 | Loop, disabled-mode, cancellation tests (mirrors `tests/test_worker_main.py`) | Contract §28 | Contract §26 |
| `tests/test_settings_phase7.py` | MODIFY (append only) | M4 | 4 new Settings tests (§17) | Contract §28 | Contract §26 |
| `tests/test_news_analysis_integration.py` | NEW (test) | M5 | Real-Postgres, `FakeLLMGateway`, full-chain, boundary, backlog tests | Contract §28 | Contract §26 |
| `capabilities/registry.py`'s own existing test (`tests/test_capability_registry.py`) | MODIFY (append only) | M1 | Add a `resolve("engagement")` assertion | Contract §8 | Contract §26 |
| `tests/test_openai_strict_schema_compliance.py` | MODIFY (append only) | M1 | Add exactly one tuple, `("engagement", "1", ENGAGEMENT_CAPABILITY_DEFINITION)`, to `_ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES` (current lines 44-50); zero existing tuple, assertion, or helper changed | Closes a real coverage gap (Planning Audit F3): this file is the repository's one centralized OpenAI strict-schema-compliance safeguard, explicitly tied to a real historical production incident, and it does **not** auto-discover new capabilities — without this addition, `prompts/engagement/v1.yaml` would never be checked by it | Contract §26 ("Test files... not frozen more precisely") |
| `tests/test_phase9_research_intelligence_integration.py` | MODIFY (narrow — remove one obsolete test + its section comment, add nothing) | M1 | **EXISTING TEST FILE — MECHANICAL EXPECTATION UPDATE REQUIRED BY ENGAGEMENTCAPABILITY REGISTRATION** (Final Re-Audit RA-1). Remove `test_real_news_analysis_still_fails_at_engagement_analysis_step` and its preceding "4. Negative/boundary" section comment (current lines 368-394) in full — not a partial edit. Its intent (real `NEWS_ANALYSIS`, real `WorkflowRunner`/`CapabilityRegistry`, exact 3-step order, step-result propagation) is preserved, not discarded — it is replaced by a new positive counterpart in the same file, §7.4 below, not merely deleted | The test's entire premise — `"engagement"` is unregistered — becomes false the instant M1 registers it; its hardcoded `step_results[2].status == "FAILED"  # "engagement" is not a registered Capability` assertion would otherwise fail immediately | Contract §26 ("Test files... not frozen more precisely") |
| `tests/test_phase10_capability_registration.py` | MODIFY (narrow — replace one assertion pair, add nothing else) | M1 | **EXISTING TEST FILE — MECHANICAL EXPECTATION UPDATE REQUIRED BY ENGAGEMENTCAPABILITY REGISTRATION** (Final Re-Audit RA-2). In `test_unregistered_capability_still_raises_unknown_capability_error`, remove only the `registry.resolve("engagement")`/`pytest.raises(UnknownCapabilityError)` pair (current lines 83-84) and its docstring's now-false "engagement" sentence; replace with a genuinely-unregistered placeholder name, mirroring the established precedent already used elsewhere in this repository for the exact same situation (`tests/test_boot_assembly.py:61-66`'s own comment: "'research' was an unregistered-name example when this test was written; Phase 9 M6 legitimately registers it... so a genuinely-unregistered name is used here instead"). The function, its still-valid `registry.resolve("no_such_capability")` assertion, and every other test in the file are unchanged | Same root cause as the row above — `registry.resolve("engagement")` no longer raises `UnknownCapabilityError` once M1 registers it | Contract §26 ("Test files... not frozen more precisely") |
| `tests/test_phase9_cross_cutting_regression.py` | MODIFY (narrow — one-line sentinel-string substitution, nothing else) | M1 | **EXISTING TEST FILE — MECHANICAL SENTINEL/WHITELIST UPDATE REQUIRED BY THE AUTHORIZED PHASE 9 POSITIVE NEWS_ANALYSIS INTEGRATION TEST** (Final Test-Scope Re-Audit TS-1). In `test_no_phase9_test_pairs_real_news_analysis_with_completed_status` (line 81), replace the sentinel string `"test_real_news_analysis_still_fails_at_engagement_analysis_step"` with `"test_real_news_analysis_now_completes_through_engagement_analysis"` — the new, §7.4-authorized replacement test's exact name. No other line, and no other test in this file, changes. Full exact-trigger/exemption/RED-GREEN-proof documentation in §7.7 | §7.4's own replacement test (required to prove `COMPLETED`) reintroduces the exact three-token combination this meta-test scans for, while §4's own removal of the old test deletes the one string that used to exempt this file — a second-order, mechanical consequence of RA-1's own fix, not a new architecture decision | Contract §26 ("Test files... not frozen more precisely") |

**No `pyproject.toml`, `Dockerfile`, or `worker/__init__.py` change** — independently re-confirmed
necessary-not (Contract audit §7, re-verified again this session: `"worker"` already in
`pyproject.toml`'s `packages` list since Phase 12; `Dockerfile`'s `COPY . .` precedes `pip install
.`; `worker/__init__.py` needs no edit to gain sibling modules).

**Total (corrected this revision — Final Test-Scope Re-Audit TS-1, superseding the prior "10
test-file items" count): 4 narrow existing-file edits (production) + 4 new production files + 11
test-file items (4 new, 7 narrow modify-only edits to existing files — three of which, across this
and the prior revision, are mechanical expectation/sentinel updates on pre-existing tests broken,
directly or as a second-order effect, by `EngagementCapability`'s own registration, not new
functional scope). Exact recount, and the broader second-order meta-test search that confirmed no
further affected file exists, in §28.**

## 5. Dependency Graph

```
M0 (baseline, no code)
  └─→ M1 (EngagementCapability, prompt, registration) ── self-contained, zero touch to
  │                                                        WorkflowRunner/existing tests
  │                                                        [SAFE, additive — done first]
  └─→ M2 (WorkflowRunner atomic-claim fix) ── touches a frozen, shared, high-blast-radius
  │                                            file; done SECOND specifically so any
  │                                            CONTENT_GENERATION regression surfaces
  │                                            immediately via the full existing
  │                                            tests/test_workflow_runner.py suite, before
  │                                            anything else is built on top of it
  │                                            [depends on nothing from M1 - independent,
  │                                            but ordered after it per §32's reasoning]
        └─→ M3 (eligibility query + analysis_cycle.py) ── depends on M1 (needs
        │                                                  EngagementCapability registered
        │                                                  for the real workflow to be
        │                                                  completable) AND M2 (needs the
        │                                                  fixed, atomic run())
              └─→ M4 (worker/analysis_main.py, config, Docker) ── depends on M3
                    └─→ M5 (offline integration) ── depends on M1+M2+M3+M4 all together
                          └─→ M6 (full regression/readiness gate) ── depends on all above
                                └─→ STOP
                                      └─→ M7 (human-authorized live validation only)
```

**Ordering rationale (Step 32)**: M1 before M2 is deliberate, not arbitrary. `EngagementCapability`
is purely additive (a new file, one new registry line) and carries zero risk to any existing,
already-relied-upon code path — implementing and fully testing it first costs nothing and proves
half the Contract's surface area works. `WorkflowRunner`'s atomic-claim fix (M2) is the one change
in this entire Contract that touches a **frozen, shared** file `CONTENT_GENERATION` already depends
on in production — ordering it second, immediately followed by re-running the complete, unmodified
`tests/test_workflow_runner.py` suite, surfaces any regression at the earliest possible point, before
M3/M4/M5 build further code on top of an assumption that might be wrong. No milestone is designed to
intentionally leave the repository in a broken state; each milestone's own gate (§24) must be green
before the next begins.

## 6. M0 — Baseline

No code changes. Re-verify (already performed, §2): `HEAD`, `git status`, `WorkflowRunner`'s exact
current transition logic, `NEWS_ANALYSIS`'s exact 4-step definition, `CapabilityRegistry`'s exact 5
current registrations, prompt-repository/versioning conventions
(`prompts/intelligence/v1.yaml`/`v2.yaml`'s immutable-forward pattern), `assemble_ai_integration_
layer()`'s exact assembly, Phase 12's exact worker pattern (`worker/main.py`/`worker/cycle.py`),
current `Settings`/`docker-compose.yml`/`pyproject.toml`, `EditorialTask`/`NewsEvent` model exact
columns, and `tests/test_workflow_runner.py`'s exact existing test inventory (12 tests, enumerated
in §10). **M0 completion criterion**: repository matches every Contract assumption — met (§2).

## 7. M1 — EngagementCapability

**Target files**: `capabilities/engagement_capability.py` (new), `prompts/engagement/v1.yaml` (new),
`capabilities/registry.py` (one new line), `tests/test_engagement_capability.py` (new),
`tests/test_capability_registry.py` (one new assertion), `tests/test_openai_strict_schema_
compliance.py` (one new tuple in `_ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES` — Planning Audit
F3/MAJOR-3), `tests/test_phase9_research_intelligence_integration.py` (§7.4) and
`tests/test_phase10_capability_registration.py` (§7.5) (both **added Correction Pass 2**, Final
Re-Audit RA-1/RA-2), and, **added this revision (Correction Pass 3, Final Test-Scope Re-Audit
TS-1)**, `tests/test_phase9_cross_cutting_regression.py` (§7.7) — see §4/§19 for every exact
change.

**M1 atomic test ownership, binding (resolves Correction 3 of Revision Pass 2, expanded by one
file this revision — Final Test-Scope Re-Audit TS-1)**: M1 is not "done" when
`capabilities/registry.py::build_registry()` registers `EngagementCapability` in isolation — that
registration alone is the exact change that breaks the two pre-existing tests identified in
§7.4/§7.5, and §7.4's own required correction to the first of those has a further, second-order
effect on a third pre-existing file (§7.7). M1's own completion criterion is that **all eight** of
the following are green **together, in the same milestone, before M1 is considered complete**: the
new `capabilities/engagement_capability.py`; the new `prompts/engagement/v1.yaml`; the one-line
registration; `tests/test_engagement_capability.py` (new); the `tests/test_capability_registry.py`
addition; the `tests/test_openai_strict_schema_compliance.py` addition; the §7.4/§7.5 corrections;
and the §7.7 meta-test sentinel correction. No intermediate commit or milestone-internal step may
land the registration, or land §7.4's own replacement test, while either the Phase 10 test still
asserts the pre-Phase-13 unregistered behavior or the Phase 9 cross-cutting meta-test's sentinel
still points at the removed function name — there is no authorized "registration/replacement
lands, dependent tests fixed later" ordering, at any depth. If an implementer's own tooling forces
separate commits within M1, the registration commit and all three test corrections (§7.4, §7.5,
§7.7) must land together as one atomic unit of work before M1's own gate (§24) is evaluated.

### 7.4 `tests/test_phase9_research_intelligence_integration.py` — replacement design (resolves
Final Re-Audit RA-1)

**Original test's intent, preserved, not discarded**: real `NEWS_ANALYSIS` workflow definition,
real `WorkflowRunner`, real `CapabilityExecutor`, real `CapabilityRegistry` (via `build_registry()`
with a `FakeLLMGateway`), proving the exact 3-capability step order and step-result propagation.
Only the *outcome* the test proves changes — from "fails at step 3 because it's unregistered" to
"succeeds through step 3 because it's now registered" — because that is the exact, intended effect
of Phase 13's own M1 milestone; asserting the old, now-false outcome would not be "preserving
intent," it would be asserting something no longer true about the real system.

**Exact required replacement** (a new test in the same file, in place of the removed one — see §4
for why the old test's own name and section comment must be fully removed, not edited in place).
**Correction to this section's own prior wording (Final Test-Scope Re-Audit TS-1)**: full removal
of the old test does **not**, by itself, avoid tripping
`tests/test_phase9_cross_cutting_regression.py`'s own static-scan meta-test — the replacement
below, by correctly proving `COMPLETED`, reintroduces the exact trigger combination that meta-test
scans for, in a new function. §7.7 is the required, narrow, separate correction for that
second-order effect; it is not avoided by how this replacement is written, and must not be
"solved" by weakening this replacement's own required `COMPLETED` proof:

```python
async def test_real_news_analysis_now_completes_through_engagement_analysis(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    """Phase 13 M1: supersedes the removed `test_real_news_analysis_still_fails_at_
    engagement_analysis_step` (docs/phase13_automatic_news_analysis_implementation_plan.md §7.4)
    - the negative boundary it proved (engagement unregistered) no longer exists once
    EngagementCapability is registered. This is the positive counterpart, same real components,
    same file, one boundary later."""
    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(_ENGAGEMENT_OUTPUT),  # new canonical fixture, §7.4
        ]
    )
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]

    command = EditorialTaskCreate(event_id=real_news_event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)
    task = await workflow_service.create_task(db_session, command)  # default (real) WorkflowRegistry
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert [r.step_name for r in result.step_results] == ["research", "intelligence", "engagement_analysis"]
    assert result.step_results[0].status == "SUCCESS"
    assert result.step_results[1].status == "SUCCESS"
    assert result.step_results[2].status == "SUCCESS"
    assert result.step_results[2].result == _ENGAGEMENT_OUTPUT

    # Propagation proof (mirrors this file's own already-established pattern, e.g. the
    # intelligence-request-text assertion elsewhere in this file): Engagement's own request must
    # reflect both Research's and Intelligence's prior output, not just the raw event.
    engagement_request_text = _request_text(gateway.received_requests[2])
    assert "did not run" not in engagement_request_text.lower()
```

`_ENGAGEMENT_OUTPUT` is a new canonical fixture constant added to this file's existing fixture
block, shaped to `ENGAGEMENT_CAPABILITY_DEFINITION.expected_output_keys` (§7.1) — mirrors this
file's own existing `CANONICAL_RESEARCH_OUTPUT`/`_INTELLIGENCE_OUTPUT` convention exactly, not a
new pattern.

**Preserves, does not remove**: every other test in this file, including the earlier
research/intelligence-only propagation tests (e.g. the one asserting `result.status == "COMPLETED"`
for a synthetic 2-step registry, §6 of the Final Re-Audit — unaffected by this change and untouched
by this revision).

### 7.5 `tests/test_phase10_capability_registration.py` — replacement design (resolves Final
Re-Audit RA-2)

**Original test's intent, preserved, not discarded**: `test_unregistered_capability_still_raises_
unknown_capability_error` exists to prove the two-line registry addition (Phase 10's own
`CopywritingCapability` registration, at the time it was written) is purely additive and does not
alter `resolve()`'s existing rejection behavior for any other name. That intent — "registering a
new capability must never make `resolve()` permissive for names that are still genuinely
unregistered" — remains completely valid after Phase 13; only the specific example name used to
exercise it must change, because `"engagement"` stops being an example of an unregistered name.

**Exact required replacement**, split into the two logically separate assertions Correction 2B
requires — not a single merged edit:

```python
def test_unregistered_capability_still_raises_unknown_capability_error() -> None:
    """Proves the two-line registry addition (capabilities/registry.py) is purely additive and
    does not alter resolve()'s existing behavior for any other, still-unregistered name. Phase 13
    M1 registers "engagement" (previously this test's own example name, per Contract §3's citation
    of it) - "definitely_unregistered_capability" is used instead, mirroring the same, already-
    established repository precedent for this exact situation (tests/test_boot_assembly.py:61-66,
    written when Phase 9 M6 registered "research" out from under that test's own prior example)."""
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type]
        prompt_repository=_prompt_repository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("definitely_unregistered_capability")

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("no_such_capability")


def test_build_registry_resolves_engagement_directly() -> None:
    """Registered-capability proof (Correction 2B item 1) - mirrors this file's own existing
    test_build_registry_resolves_copywriting_directly() pattern exactly, for the sixth
    capability. Requires one new module-level import alongside this file's existing ones:
    `from capabilities.engagement_capability import CAPABILITY_NAME as
    ENGAGEMENT_CAPABILITY_NAME` and `from capabilities.engagement_capability import
    EngagementCapability` - the same `CAPABILITY_NAME as <NAME>_CAPABILITY_NAME` aliasing
    convention this file already uses for scoring/quality/research/intelligence/copywriting."""
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type]
        prompt_repository=_prompt_repository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    definition, capability = registry.resolve(ENGAGEMENT_CAPABILITY_NAME)

    assert definition.name == ENGAGEMENT_CAPABILITY_NAME
    assert isinstance(capability, EngagementCapability)
```

**Explicitly not authorized**: repurposing `"engagement"` itself as the new unknown-capability
example (that would merely relocate the same defect one line down, the moment it too becomes
registered by some future phase — the whole reason the codebase's own established precedent uses a
name, `"definitely_unregistered_capability"`/`"no_such_capability"`, that is not itself a real,
planned capability name). Also not authorized: renaming
`test_build_registry_resolves_all_five_capabilities` to "six," or adding `EngagementCapability` to
its loop — that test is scoped to Phase 10's own five, and altering it is unrelated, unnecessary
scope creep this correction does not require (Phase 13's own equivalent proof lives in the new
`test_build_registry_resolves_engagement_directly` above, and in
`tests/test_capability_registry.py`'s own addition, §4).

### 7.6 M1 Regression Matrix (resolves Correction 4 of Revision Pass 2, extended by row 8 this
revision — Final Test-Scope Re-Audit TS-1)

M1 is not complete until all eight of the following hold simultaneously — this is the exact,
binding checklist for M1's own gate (§24), in addition to (not instead of) the per-file test plan
in §19:

| # | Obligation | Proven by |
|---|---|---|
| 1 | `EngagementCapability` unit tests pass | `tests/test_engagement_capability.py` (new) |
| 2 | `CapabilityRegistry` resolves `"engagement"` | `tests/test_capability_registry.py` (append) and `tests/test_phase10_capability_registration.py::test_build_registry_resolves_engagement_directly` (§7.5, new) |
| 3 | A truly unknown capability still raises `UnknownCapabilityError` | `tests/test_phase10_capability_registration.py::test_unregistered_capability_still_raises_unknown_capability_error`, corrected (§7.5) — still asserts this, using a genuinely-unregistered name |
| 4 | Real `NEWS_ANALYSIS` no longer fails merely because `engagement_analysis` is unregistered | `tests/test_phase9_research_intelligence_integration.py::test_real_news_analysis_now_completes_through_engagement_analysis` (§7.4, new) |
| 5 | Existing Research and Intelligence behavior is unchanged | Every other, untouched test in both corrected files (§7.4/§7.5's own "preserves, does not remove" clauses) plus the full, unmodified `tests/test_workflow_runner.py` suite (§19, unaffected by M1) |
| 6 | Strict-schema centralized compliance includes the new prompt | `tests/test_openai_strict_schema_compliance.py` addition (§4, Planning Audit F3) |
| 7 | No `CONTENT_GENERATION` regression | `tests/test_phase10_workflow_integration.py::test_content_generation_reaches_completed_in_exact_step_order` (pre-existing, untouched, unaffected — verified this revision to use `WorkflowType.CONTENT_GENERATION`, not `NEWS_ANALYSIS`) plus §22's existing three-layer boundary proof |
| 8 | The Phase 9 cross-cutting static-scan meta-test's sentinel correctly recognizes the new, authorized replacement test — and still rejects any other, unauthorized `NEWS_ANALYSIS`+`COMPLETED` pairing | `tests/test_phase9_cross_cutting_regression.py::test_no_phase9_test_pairs_real_news_analysis_with_completed_status`, corrected (§7.7); RED/GREEN proof (§7.7) run once at M1 |

No milestone after M1 may proceed while any row above is red.

### 7.7 `tests/test_phase9_cross_cutting_regression.py` — meta-test sentinel correction (resolves
Final Test-Scope Re-Audit TS-1)

**Why this file, not previously in scope, must now be touched**: §7.4's own replacement test
(`test_real_news_analysis_now_completes_through_engagement_analysis`) is required — correctly, and
this requirement is not weakened by this correction — to prove the real `NEWS_ANALYSIS` task
reaches `COMPLETED`. That proof necessarily makes the file's raw text contain
`WorkflowType.NEWS_ANALYSIS` and `assert result.status == "COMPLETED"`, while §4's own "remove in
full" instruction for the old, superseded test simultaneously deletes the one string that used to
exempt this file from a separate, pre-existing static-scan test. Both changes are individually
correct; their combination has a real, mechanical, second-order effect on a third file, found by
directly re-simulating the meta-test's own logic against the Plan's own planned §7.4 text (Final
Test-Scope Re-Audit, §4/TS-1).

**Exact trigger condition, re-read directly from
`tests/test_phase9_cross_cutting_regression.py:64-84` this revision** (not re-described
generically): `test_no_phase9_test_pairs_real_news_analysis_with_completed_status` globs every
`tests_dir.glob("test_phase9_*.py")` file except itself, reads each file's raw text, and appends
that file's name to `offending_files` iff **all three** of `"NEWS_ANALYSIS" in text`,
`'"COMPLETED"' in text`, and `"status ==" in text` are true, **unless** the fourth condition
`"test_real_news_analysis_still_fails_at_engagement_analysis_step" not in text` is false (i.e.,
unless that exact literal string is present somewhere in the file). The test then asserts
`offending_files == []`.

**Exact existing exemption mechanism**: a single literal Python string comparison — the presence
of the old test function's own name, `test_real_news_analysis_still_fails_at_engagement_analysis_
step`, anywhere in the target file's raw text — is used as a name-string sentinel marking "this
file is the one, known, already-reviewed exception." It is not scoped to that function's own body;
it is a whole-file text search, matching this codebase's own established, already-precedented
convention for this class of check (mirrors, e.g., `tests/test_boot_assembly.py`'s own comment-based
self-documentation of a similar swap).

**Exact one-line mechanical change required**, and no other: in
`tests/test_phase9_cross_cutting_regression.py`, line 81, replace

```python
            if "test_real_news_analysis_still_fails_at_engagement_analysis_step" not in text:
```

with

```python
            if "test_real_news_analysis_now_completes_through_engagement_analysis" not in text:
```

— the new, §7.4-authorized replacement test's own exact name, substituted in place of the old,
now-removed one. No other line in this file changes. `test_full_boot_sequence_resolves_all_four_
capabilities` (the file's other test) is untouched and out of scope (a separate, pre-existing,
non-Phase-13-caused gap — Final Re-Audit RA-O4 — not addressed by this or any Phase 13
correction).

**Why this remains a narrow whitelist migration, not a weakening of the safety invariant**: the
mechanism itself — "exactly one, named, specific test function may legitimately pair real
`NEWS_ANALYSIS` with `COMPLETED`; every other `test_phase9_*.py` file/function may not" — is
completely unchanged. Only *which* specific, named function is that one legitimate exception
changes, because the legitimate exception itself changed identity (the old expected-failure test
is retired; the new expected-success test is its sole, deliberate, Plan-authorized successor). The
scan still globs every `test_phase9_*.py` file; the three trigger tokens are unchanged; the
"exactly one sentinel string" structure is unchanged; no wildcard, prefix-match, or broadened
condition is introduced. A different, unrelated, *unauthorized* future Phase 9 test that happened
to also pair `NEWS_ANALYSIS` with `COMPLETED` would still be flagged and would still fail this
meta-test's own assertion, exactly as today.

**RED/GREEN proof, required at M1, before M1 is considered complete**:

- **RED (pre-fix simulation, already performed once, in `docs/phase13_automatic_news_analysis_
  implementation_plan_test_scope_final_reaudit.md` §4 — re-run at implementation time as a
  regression check, not re-derived from scratch)**: with the sentinel string still reading the old
  name, and `tests/test_phase9_research_intelligence_integration.py` already containing §7.4's new
  replacement test, `test_no_phase9_test_pairs_real_news_analysis_with_completed_status` must be
  shown to fail (`offending_files == ["test_phase9_research_intelligence_integration.py"]`) —
  proving the problem is real, not hypothetical, immediately before applying the one-line fix.
- **GREEN, part A**: after the one-line substitution above, re-run the same meta-test —
  `offending_files == []` — the one, now-authorized replacement test is accepted.
- **GREEN, part B (proves the fix is a narrow migration, not a weakening)**: temporarily place one
  throwaway file matching `test_phase9_*.py` (e.g. `tests/test_phase9_zz_scratch_sentinel_check.py`
  — never committed, never a permanent addition to file scope, deleted immediately after this one
  manual check) containing a synthetic function that pairs `WorkflowType.NEWS_ANALYSIS` with
  `assert result.status == "COMPLETED"` under a name that is **not**
  `test_real_news_analysis_now_completes_through_engagement_analysis`. Run the meta-test again —
  it must still fail, flagging the throwaway file. This proves the corrected sentinel still
  rejects any other, unauthorized Phase 9 test containing the forbidden combination, not merely
  the one case that happens to exist today. Delete the throwaway file immediately after this
  one-time verification; it is never part of the Plan's authorized file scope (§4) and must leave
  no trace in the final diff.

**Explicitly not authorized**: deleting or skipping/xfailing this meta-test; removing its
`NEWS_ANALYSIS`/`COMPLETED` protection; broadening its exemption to match any `test_phase9_*`
function name, a prefix, or a regex; or exempting the whole file by filename instead of by the
specific function-name sentinel it already uses.

### 7.1 `capabilities/engagement_capability.py`, exact shape (mirrors `intelligence_capability.py`)

```python
"""EngagementCapability - Phase 13: predicted editorial/audience engagement potential from
Research's and Intelligence's already-extracted findings (docs/
phase13_automatic_news_analysis_architecture_contract.md §6/§7).

PREDICTED potential, never observed engagement - no real Telegram/HN metric (views, forwards,
reactions, replies) is available to or consumed by this Capability (none is persisted anywhere
in this codebase, per Discovery §7). engagement_potential_score is an LLM-produced estimate.

Ordinary Phase 8 Capability, identical construction shape to IntelligenceCapability:
__init__(gateway, prompt_repository) only, one call_generate() invocation, no retry.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from capabilities.errors import ValidationCapabilityError
from capabilities.gateway_call import call_generate
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository, RenderedPrompt
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "engagement"
PROMPT_VERSION = "1"

ENGAGEMENT_CAPABILITY_DEFINITION = CapabilityDefinition(
    name=CAPABILITY_NAME,
    version=1,
    config=CapabilityConfig(timeout_seconds=30),
    required_context=["news_event"],
    expected_output_keys=["engagement_potential_score", "audience_fit", "reasoning"],
)

_SCHEMA_TYPE_TO_PYTHON_TYPE: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _floor_validate(structured_output: dict[str, Any] | None, output_schema: dict[str, Any]) -> str | None:
    """Contract §9.1's floor (duplicated intentionally, matching every sibling capability's own
    established non-shared-helper convention - see intelligence_capability.py's identical docstring)."""
    if structured_output is None:
        return "structured_output is missing; the §9.1 floor requires an object."
    required = output_schema.get("required", [])
    missing = [key for key in required if key not in structured_output]
    if missing:
        return f"structured_output is missing required key(s): {missing}"
    properties: dict[str, Any] = output_schema.get("properties", {})
    for key, declared in properties.items():
        if key not in structured_output:
            continue
        declared_type = declared.get("type")
        expected_python_type = _SCHEMA_TYPE_TO_PYTHON_TYPE.get(declared_type)
        if expected_python_type is None:
            continue
        value = structured_output[key]
        if declared_type == "integer" and isinstance(value, bool):
            return f"structured_output['{key}'] must be an integer, got bool."
        if not isinstance(value, expected_python_type):
            return f"structured_output['{key}'] must be of type '{declared_type}', got {type(value).__name__}."
    return None


def _format_prior_step(label: str, output: dict[str, Any]) -> str:
    if not output:
        return f"({label} did not run, or produced no output - proceed without it.)"
    return str(output)


def _build_request(context: CapabilityContext, prompt: RenderedPrompt) -> GenerateRequest:
    news_event = context.business.news_event
    research_output = context.business.workflow_state.step_results.get("research", {})
    intelligence_output = context.business.workflow_state.step_results.get("intelligence", {})
    system_text = prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)
    context_text = (
        f"Title: {news_event.title}\n"
        f"Category: {news_event.category}\n"
        f"Target output language: {context.business.language}\n\n"
        f"Research output:\n{_format_prior_step('Research', research_output)}\n\n"
        f"Intelligence output:\n{_format_prior_step('Intelligence', intelligence_output)}"
    )
    task_text = (
        "Estimate the predicted editorial/audience engagement potential for the event above, "
        "based only on the given title/category and Research's/Intelligence's prior findings. "
        "This is a prediction, not a measurement - no real engagement data is available."
    )
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=system_text)]),
            Message(
                role="user",
                content=[ContentPart(type="text", text=f"CONTEXT:\n{context_text}\n\nTASK:\n{task_text}")],
            ),
        ],
        preferred_model=context.execution.preferred_model,
        preferred_provider=context.execution.preferred_provider,
        max_tokens=context.execution.max_tokens,
        temperature=context.execution.temperature,
        response_mode="json_schema",
        response_schema=prompt.output_schema,
    )


class EngagementCapability:
    """Implements the Capability Protocol. Holds only LLMGateway/PromptRepository - no
    BudgetGuard, no CostTracker (Amendment C, unchanged). Never claims access to real,
    observed engagement metrics - none reach this class (Contract §6)."""

    def __init__(self, gateway: LLMGateway, prompt_repository: PromptRepository) -> None:
        self._gateway = gateway
        self._prompt_repository = prompt_repository

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        started_at = datetime.now(timezone.utc)
        prompt = self._prompt_repository.resolve(CAPABILITY_NAME, PROMPT_VERSION)
        request = _build_request(context, prompt)

        outcome = await call_generate(self._gateway, request, runtime=context.runtime, sequence=0)

        if outcome.error is not None:
            logger.info(
                "capability_call_failed",
                extra={
                    "capability_name": CAPABILITY_NAME,
                    "call_id": str(outcome.call.call_id),
                    "sequence": outcome.call.sequence,
                    "gateway_method": outcome.call.gateway_method,
                    "status": outcome.call.status,
                    "error": outcome.call.error,
                },
            )
            raise outcome.error

        response = outcome.response
        assert response is not None

        violation = _floor_validate(response.structured_output, prompt.output_schema)
        if violation is not None:
            raise ValidationCapabilityError(violation)

        finished_at = datetime.now(timezone.utc)
        return CapabilityResult(
            status="SUCCESS",
            structured_output=response.structured_output,
            calls=[outcome.call],
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=(finished_at - started_at).total_seconds(),
        )
```

### 7.2 `prompts/engagement/v1.yaml`

```yaml
name: engagement
version: "1"
system: >
  You are a predictive editorial-engagement assistant for an AI-driven news editorial
  assistant. You estimate LIKELY audience interest and engagement POTENTIAL from an event's
  content alone - you have no access to real view counts, reactions, forwards, or comments.
  Never claim or imply you are reporting observed/measured engagement data.
rules:
  - Base your estimate only on the provided title, category, Research output, and Intelligence output.
  - engagement_potential_score must be a number between 0.0 and 1.0.
  - Never state or imply access to real engagement metrics.
output_schema:
  type: object
  additionalProperties: false
  required: ["engagement_potential_score", "audience_fit", "reasoning"]
  properties:
    engagement_potential_score:
      type: number
      minimum: 0.0
      maximum: 1.0
    audience_fit:
      type: string
    reasoning:
      type: string
```

(Exact prose/wording is Planning/implementation-session discretion within these frozen constraints —
the schema shape, required-field set, and `additionalProperties: false` are not.)

### 7.3 Registration (`capabilities/registry.py::build_registry()`)

Add exactly one line, after the existing 5:

```python
from capabilities.engagement_capability import ENGAGEMENT_CAPABILITY_DEFINITION, EngagementCapability
...
registry.register(ENGAGEMENT_CAPABILITY_DEFINITION, EngagementCapability(gateway, prompt_repository))
```

## 8. M2 — Atomic Workflow Claim (resolves audit finding N1)

**Target**: `workflows/runner.py`, the `run()` method body only (lines 111-123 of the current file) —
no other line changes.

### 8.1 Exact planned diff, N1-resolved

```python
async def run(self, session: AsyncSession, task_id: UUID) -> WorkflowRunResult:
    task = await session.get(EditorialTask, task_id)
    if task is None:
        raise TaskNotFoundError(f"No EditorialTask with id {task_id}")

    now = datetime.now(timezone.utc)
    claim_result = await session.execute(
        update(EditorialTask)
        .where(EditorialTask.id == task_id, EditorialTask.status == TaskStatus.CREATED)
        .values(status=TaskStatus.RUNNING, updated_at=now)
    )
    await session.commit()

    if claim_result.rowcount != 1:  # type: ignore[attr-defined]
        # Someone else already claimed/completed/failed this task (or it was never CREATED).
        # task.status in memory may be stale relative to what we just tried to commit - force a
        # reload so the exception raised below reflects the true, current, authoritative state.
        await session.refresh(task)
        if task.status == TaskStatus.RUNNING:
            raise TaskAlreadyRunningError(f"EditorialTask {task_id} is already RUNNING")
        raise TaskAlreadyCompletedError(f"EditorialTask {task_id} is already {task.status.value}")

    # Claim succeeded at the database level - sync the already-loaded in-memory object so every
    # downstream read (this method's own remaining logic, and any future maintainer reading this
    # code) sees a consistent, non-stale task.status. No ambiguity window exists after this line.
    task.status = TaskStatus.RUNNING
    task.updated_at = now

    state = WorkflowExecutionState.model_validate(task.workflow)
    definition = self._registry.resolve(state.workflow_name)

    logger.info("Workflow %s starting for task %s", state.workflow_name.value, task_id)

    if state.iteration_count >= definition.max_iterations:
        return await self._fail(
            session, task, state, list(state.step_results), "MaxIterationsExceededError",
            "max_iterations_exceeded",
        )

    try:
        return await asyncio.wait_for(
            self._execute_steps(session, task, state, definition), timeout=definition.timeout_seconds
        )
    except TimeoutError:
        ...  # unchanged
```

**Required new import**: `from sqlalchemy import update` (alongside the file's existing `select`-less
imports — `workflows/runner.py` currently imports no `sqlalchemy` symbols directly at module level
in the read version; add exactly this one Core construct).

**Mypy precision (resolves Planning Audit F4/MINOR-1)**: `claim_result.rowcount` requires
`# type: ignore[attr-defined]` on that exact line, and *only* that line — this matches the
pre-existing, already-shipped precedent at `services/triage_orchestrator.py:67`
(`return result.rowcount == 1  # type: ignore[attr-defined]  # CursorResult at runtime for an
UPDATE; Result[Any]'s stub doesn't expose it statically`), the same confirmed SQLAlchemy typing
limitation (`Result[Any]`'s stub does not expose `.rowcount`, which only exists on the
`CursorResult` subtype actually returned at runtime for an `UPDATE`), not a new or different
limitation. No other line in this diff requires an ignore. Do **not** add a broader or file-level
`# type: ignore`, do **not** relax `mypy` configuration, and do **not** change
`EditorialTask`/`TaskStatus` typing to work around this — the implementer must confirm at M2 that
every other new/changed line in this diff type-checks cleanly on its own merits before accepting
this one, narrow, precedented ignore.

**N1 resolution, explicit**: the atomic claim commits (§8.1's `await session.commit()`) *before* the
in-memory sync (`task.status = TaskStatus.RUNNING`) — this ordering is intentional: the commit is
what makes the claim durable and race-safe (§8.2); the in-memory sync afterward is purely a
local-object-consistency step with no bearing on correctness under concurrency, since no other
session can observe or interfere with this session's own local Python attribute assignment.
**Authoritative state after claim**: the database row (source of truth, already committed); the
in-memory `task` object is kept in lockstep with it by the explicit sync, so both agree from this
point onward — no stale-state ambiguity survives past this method's own first few lines.

**No other line of `_execute_steps()`, `_run_step()`, or `_fail()` is authorized to change** — the
rest of the file is byte-for-byte unmodified, exactly per Contract §26.

### 8.2 Race-safety, restated precisely

Two concurrent `run(session_a, task_id)` / `run(session_b, task_id)` calls (different sessions,
different DB connections — the realistic multi-worker scenario): both may `session.get()` the same
`CREATED` task. Both attempt the atomic `UPDATE ... WHERE status = 'CREATED'`. PostgreSQL's own
row-level locking during `UPDATE` guarantees only one of the two statements can affect the row —
whichever commits first "wins" (affects 1 row); the other's `UPDATE` either blocks until the first
commits (then evaluates against the now-`RUNNING` row, matches 0 rows) or evaluates against the
already-updated row directly, depending on transaction isolation timing — **in every ordering, the
loser's `rowcount` is `0`**, never a partial or ambiguous result. This is the exact same guarantee
`services/triage_orchestrator.py::_claim_new_event()` already relies on in production, reused, not
invented.

## 9. M3 — Analysis Cycle / Eligibility (resolves audit finding N2)

**Target**: `worker/analysis_cycle.py` (new).

### 9.1 Exact eligibility query, SQL-side, mandatory (N2 resolution; syntax corrected this
revision — Planning Audit F1)

**RED — proof the Plan's originally-offered syntax does not work.** Both options this Plan
previously offered (a primary and a named "fallback") were executed directly against the real
development database this session, before this correction, specifically to verify F1:
- `EditorialTask.workflow["workflow_name"].astext == WorkflowType.NEWS_ANALYSIS.value` raised
  `AttributeError: Neither 'BinaryExpression' object nor 'Comparator' object has an attribute
  'astext'` at statement-construction time — it does not compile at all. Root cause:
  `EditorialTask.workflow` is mapped as generic `sqlalchemy.JSON` (`database/models/
  editorial_task.py`), not PostgreSQL `JSONB`; `.astext` is a `JSONB`-only comparator and is not
  present on the generic `JSON` type's comparator.
- The named fallback, `cast(EditorialTask.workflow["workflow_name"], String) ==
  WorkflowType.NEWS_ANALYSIS.value`, compiles without error but is semantically wrong: Postgres's
  `->` operator returns a JSON-typed value, and `CAST(... AS VARCHAR)` on that value preserves the
  JSON string's own quoting (`"NEWS_ANALYSIS"`, literal quotes included), so it never equals the
  unquoted Python string. Executed directly against the real database: matched **0** of the 4723
  real `NEWS_ANALYSIS`-workflow rows present. (Comparing against the quoted string,
  `== '"NEWS_ANALYSIS"'`, does match all 4723 — confirming the quoting diagnosis; not adopted,
  since it is fragile and strictly worse than the syntax below.)

**GREEN — the corrected, sole, frozen syntax.** Generic `sqlalchemy.JSON`'s own purpose-built
scalar-text extractor, `.as_string()`:

```python
EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value
```

Verified this session, directly against the real development database: compiles without error;
matches all 4723 real `NEWS_ANALYSIS`-workflow `EditorialTask` rows; excludes every spot-checked
row of a different `WorkflowType` (`CONTENT_GENERATION` — 0 matched); passes `mypy` cleanly with
**no** `# type: ignore` required (`.as_string()` is part of the generic `JSON` comparator's own
public, typed API — unlike the unrelated `.rowcount` case in §8.1). **This is now the only
authorized JSON scalar-extraction syntax for this query. `.astext` and `cast(..., String)` are
both retired from this Plan and must not be reintroduced, including as a "fallback" or "either
syntax is acceptable" choice — Contract §34 item 13's "genuinely cosmetic" allowance does not
apply here, since one option is empirically broken, not merely stylistically different.**

An explicit, controlled-data GREEN regression test (not run against the uncontrolled production
backlog beyond the one already-approved read-only diagnostic above) is a required part of M3's own
test obligations — see the updated `tests/test_analysis_worker_cycle.py` row in §19: a test-owned
`NEWS_ANALYSIS`-workflow task must be found by `_select_eligible_task_ids()`, and a test-owned
task on a different `WorkflowType` (e.g. `CONTENT_GENERATION`) must not be — both inserted and
cleaned up under §20's existing real-Postgres isolation discipline.

```python
"""One automation-analysis cycle: query eligible NEWS_ANALYSIS tasks, claim and execute up to
news_analysis_batch_size of them, sequentially. No business logic of its own."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.registry import CapabilityRegistry
from capabilities.executor import CapabilityExecutor
from core.config import settings
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from schemas.workflow import WorkflowType
from workflows.errors import TaskAlreadyCompletedError, TaskAlreadyRunningError, TaskNotFoundError
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)


@dataclass
class AnalysisCycleResult:
    eligible_found: int = 0
    claimed: int = 0
    lost_races: int = 0
    completed: int = 0
    failed: int = 0
    task_ids: list[UUID] = field(default_factory=list)


async def _select_eligible_task_ids(session: AsyncSession) -> list[UUID]:
    """SQL-side filtering only - status, workflow-name JSON match, and freshness cutoff are all
    evaluated by Postgres itself; only the final, already-batch-capped result rows are ever
    materialized into Python. Never loads the full CREATED backlog (Contract §13, audit N2)."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        hours=settings.news_analysis_freshness_cutoff_hours
    )
    anchor = func.coalesce(NewsEvent.published_at, NewsEvent.collected_at)

    stmt = (
        select(EditorialTask.id)
        .join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
        .where(
            EditorialTask.status == TaskStatus.CREATED,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            anchor >= cutoff,
        )
        .order_by(EditorialTask.created_at.asc(), EditorialTask.id.asc())
        .limit(settings.news_analysis_batch_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

**Freshness anchor, explicit**: `COALESCE(NewsEvent.published_at, NewsEvent.collected_at)` — the
exact same anchor-selection rule `compute_freshness()` already implements in Python
(`services/freshness.py:62-64`), re-expressed as SQL. `collected_at` is `nullable=False` with a
`server_default`, so the `COALESCE` always yields a non-null value — no row is ever excluded or
wrongly included due to a null timestamp.

**Ordering, explicit**: `created_at ASC, id ASC` — oldest-eligible-first (Contract §13's own frozen
choice), `id` as a deterministic tie-breaker.

**Batch cap, explicit and hard**: `LIMIT settings.news_analysis_batch_size` is part of the SQL
statement itself — the query can never return more than 5 rows (default), full stop.

### 9.2 Exact cycle orchestration, race and refill semantics frozen

```python
async def run_analysis_cycle(
    session_factory,
    capability_registry: CapabilityRegistry,
) -> AnalysisCycleResult:
    result = AnalysisCycleResult()

    async with session_factory() as session:
        eligible_ids = await _select_eligible_task_ids(session)
    result.eligible_found = len(eligible_ids)
    result.task_ids = eligible_ids

    # Exactly the originally-selected candidates are attempted - never more. A lost race (another
    # worker/cycle claimed one first) is not backfilled with a replacement candidate (Contract
    # §16's frozen "no refill" rule) - this keeps per-cycle work exposure deterministic at <= 5
    # attempted claims, regardless of how many actually succeed.
    for task_id in eligible_ids:
        async with session_factory() as session:
            executor = CapabilityExecutor(session, task_id, capability_registry)
            runner = WorkflowRunner(executor)
            try:
                run_result = await runner.run(session, task_id)
            except (TaskAlreadyRunningError, TaskAlreadyCompletedError):
                # Lost the race to another worker/cycle since the eligibility query ran, or the
                # task was already handled - not a cycle failure, not an error (Contract §15).
                result.lost_races += 1
                continue
            except TaskNotFoundError:
                # Should not occur (tasks are never deleted) - logged, not fatal to the cycle.
                logger.exception("analysis_task_vanished", extra={"task_id": str(task_id)})
                continue

            result.claimed += 1
            if run_result.status == "COMPLETED":
                result.completed += 1
            else:
                result.failed += 1

    logger.info(
        "analysis_cycle_finished",
        extra={
            "eligible_found": result.eligible_found,
            "claimed": result.claimed,
            "lost_races": result.lost_races,
            "completed": result.completed,
            "failed": result.failed,
        },
    )
    return result
```

**Sequential, explicit**: the `for` loop above contains no `asyncio.gather`/`create_task` — each
`runner.run()` call is fully awaited before the next iteration begins, exactly per Contract §14/§18.

## 10. M4 — Runtime / Config / Docker

**Target files**: `worker/analysis_main.py` (new), `core/config.py` (narrow), `docker-compose.yml`
(narrow).

### 10.1 `worker/analysis_main.py`, mirrors `worker/main.py` exactly

```python
"""Entry point for running the NEWS_ANALYSIS automation worker.

Launch with:
    python -m worker.analysis_main
"""
import asyncio
import logging
import signal
from pathlib import Path

from core.config import settings
from core.logging import setup_logging
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from worker.analysis_cycle import run_analysis_cycle
from database.session import async_session_factory

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


async def _run_enabled_loop() -> None:
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)  # constructed once

    while True:
        try:
            await run_analysis_cycle(async_session_factory, ai_layer.capability_registry)
        except Exception:
            logger.exception("analysis_cycle_failed")
        await asyncio.sleep(settings.news_analysis_poll_interval_seconds)


async def _run_disabled_idle() -> None:
    logger.info("news_analysis_enabled is False - analysis worker idling, no cycles will run")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("analysis_worker_shutting_down_disabled")
        raise


async def main() -> None:
    setup_logging()
    task = asyncio.current_task()
    assert task is not None
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except NotImplementedError:
            pass  # Windows dev-only limitation, identical to worker/main.py's own guard

    try:
        if not settings.news_analysis_enabled:
            await _run_disabled_idle()
            return
        await _run_enabled_loop()
    except asyncio.CancelledError:
        logger.info("analysis_worker_shutdown_complete")
        raise


if __name__ == "__main__":
    asyncio.run(main())
```

**AI integration layer constructed once, at startup** (not per-cycle) — matches Contract §25/§21's
own binding decision, avoiding redundant boot work every 300 seconds.

### 10.2 `core/config.py` — exact new fields

```python
news_analysis_enabled: bool = False
news_analysis_poll_interval_seconds: int = Field(default=300, gt=0)
news_analysis_batch_size: int = Field(default=5, gt=0)
news_analysis_freshness_cutoff_hours: float = Field(default=48.0, gt=0)
```

`max_daily_ai_cost` is **not added** — re-confirmed absent from this list, per Contract §17/§22.

### 10.3 `docker-compose.yml` — exact new service (Redis included, re-derived not copied)

```yaml
news_analysis_worker:
  build: .
  container_name: ai_newsroom_news_analysis_worker
  restart: unless-stopped
  env_file: .env
  environment:
    POSTGRES_HOST: postgres
    REDIS_HOST: redis
  command: ["python", "-m", "worker.analysis_main"]
  depends_on:
    postgres:
      condition: service_healthy
    redis:
      condition: service_healthy
```

**Mandatory Docker validation safety rule, restated from the M3-Phase-12 incident**: validate this
service definition using **only** `docker compose config --quiet` (validates everything, prints
nothing on success) or `docker compose config --services` (service names only). **Plain `docker
compose config` (no flags) MUST NOT be run** — it resolves and prints every service's interpolated
`.env` environment, including real credentials, exactly as it did during Phase 12's own M3
incident (`docs/security_incident_telegram_credentials_rotation_verification.md`). This applies to
every milestone in this Plan that touches `docker-compose.yml` (M4) and to M6's own gate.

## 11. M5 — Offline Integration

**Target**: `tests/test_news_analysis_integration.py` (new), reusing the exact real-Postgres
fixture pattern already proven in `tests/test_automation_integration.py` (Phase 12) —
`independent_session_factory()`, a uniquely-named test-owned `NewsSource`/`NewsEvent`, explicit
FK-safe `try/finally` cleanup, no rollback-only isolation.

**Full-chain proof, using `FakeLLMGateway`** (already exists, `tests/fakes/fake_gateway.py`) wired
through a real `CapabilityRegistry` (built via `capabilities.registry.build_registry(fake_gateway,
real_or_fake_prompt_repository, ...)`, mirroring `tests/test_phase10_workflow_integration.py`'s own
established pattern):
1. Insert a test-owned `NewsSource` + `NewsEvent` + `EditorialTask(NEWS_ANALYSIS, CREATED)` directly
   (via `workflow_service.create_task()`, matching the real production shape Triage would produce).
2. Call `_select_eligible_task_ids()` — assert the test task is found (freshness ≤48h by
   construction, since it was just created).
3. Call `run_analysis_cycle()` (or directly `WorkflowRunner(CapabilityExecutor(...)).run(...)` for a
   more targeted unit-level version) — assert the real, unmodified `research → intelligence →
   engagement_analysis → scoring` order executes, each step's `step_results` correctly propagate
   (Research's output visible to Intelligence; both visible to Engagement — mechanically asserted by
   inspecting the persisted `EditorialTask.workflow` JSON after completion).
4. Assert final status `COMPLETED`.
5. Assert **zero** `CONTENT_GENERATION` `EditorialTask` rows and **zero** `ContentDraft` rows exist
   for this event afterward (mechanical, scoped, zero-rows — mirrors Phase 12's own proven
   assertion pattern).
6. A second, separate test: insert a test-owned task whose `NewsEvent` is deliberately >48h old
   (backdated `published_at`/`collected_at`) — assert `_select_eligible_task_ids()` never returns it.
7. A third test: insert 6+ eligible test-owned tasks — assert exactly 5 are selected/claimed in one
   cycle (batch cap proof).

## 12. M6 — Final Regression / Readiness Gate

**Focused regression first, then full suite (resolves Correction 7 of Revision Pass 2, extended by
row 3 this revision — Final Test-Scope Re-Audit TS-1)**: because M1 makes a currently-shared-state
change (registering `"engagement"`) with mechanical impact on two pre-existing, unrelated-milestone
test files (§7.4/§7.5), plus a second-order impact on a third (§7.7), M6 must explicitly re-run all
three, focused, before the full-suite step below — not merely trust that they were green once at
M1 and never regressed since:

1. Focused: `pytest tests/test_phase9_research_intelligence_integration.py` — full file, not just
   the new/changed test — green.
2. Focused: `pytest tests/test_phase10_capability_registration.py` — full file — green.
3. Focused: `pytest tests/test_phase9_cross_cutting_regression.py` — full file — green (proves the
   §7.7 sentinel correction; this is the meta-test whose own logic scans the file corrected in
   row 1, so it must be re-run as its own, separate, named step, not merely inferred from row 1
   passing).
4. Only then, the full-repository steps below. **M6 cannot pass while any of the three rows above
   is red, even if the full-suite step also happens to pass** (a full-suite run alone would not, by
   itself, distinguish "these three files are green" from "these three files were accidentally
   deselected/skipped" — the focused, named re-run removes that ambiguity).

All of the following must pass, run fresh at this milestone (not merely inherited from earlier
milestone runs):

1. Full `pytest` (whole repository) — must show the same or greater pass count than the current
   pre-Phase-13 baseline (816, per Phase 12's own final checkpoint), plus every new Phase 13 test,
   zero failures. Includes, and does not merely subsume, the three focused regressions above.
2. `ruff check .` (repo-wide) — all checks passed.
3. Targeted `mypy` on every changed/new production file: `workflows/runner.py`,
   `capabilities/registry.py`, `capabilities/engagement_capability.py`, `core/config.py`,
   `worker/analysis_main.py`, `worker/analysis_cycle.py`.
4. `python -m scripts.validate_architecture` — 0 violations.
5. Secret/security hygiene: `.env` remains ignored/untracked; `docker compose config --quiet`/
   `--services` only (§10.3's mandatory rule, re-verified at this gate specifically).
6. Migration audit: no new file under `alembic/versions/` (none exists in this repo at all, per
   Phase 12's own precedent — re-confirmed unchanged).
7. Git scope audit: `git status --short`/`git diff --name-only` show changes **only** to the files
   enumerated in §4 — no unrelated file touched.
8. DB pollution audit: post-test query for any leftover test-owned rows (unique-name-prefixed, per
   §11's fixture convention) — zero remaining.
9. `CONTENT_GENERATION`-boundary re-audit: grep `worker/analysis_*.py` for
   `run_content_generation_for_event`/`CONTENT_GENERATION` — zero matches (mechanical, independent
   of the unit-level test in §11).

**M6 is the last automated gate. No live API spend before it is fully green.**

## 13. STOP Gate Before Live Validation

Explicit, mandatory pause: once M6 is green, implementation **stops**. M7 (§14) requires separate,
explicit human authorization — mirroring Phase 12's own M5→M6 boundary exactly. No agent or
autonomous session may proceed past this point without that authorization, regardless of how green
M6 is.

## 14. M7 — Human-Authorized Live Validation

Not executed by this Plan or any earlier milestone. **Rewritten this revision (Planning Audit
F2) — the original procedure's isolation claim is retracted.**

**Why the original procedure was wrong**: it claimed `news_analysis_batch_size=1` plus the 48h
freshness cutoff was "the deterministic isolation mechanism," making the historical backlog
"structurally unreachable." A direct, read-only diagnostic query against the real development
database this session found **1153** `EditorialTask(NEWS_ANALYSIS, CREATED)` rows currently
satisfy the ≤48h freshness cutoff — a direct, expected consequence of Phase 12's own successful M6
live ingestion run still being inside its own freshness window. `LIMIT 1` against that live,
deterministically-ordered set simply selects the oldest of 1153 real, uncontrolled production
candidates, not a chosen, verified, "intended" sample. **Original steps 1-2 and their
"deterministic isolation" justification are withdrawn in full.**

**Hard precondition, binding**: the normal analysis worker (`worker/analysis_main.py`,
`news_analysis_enabled=true`) must **not** be started for the purpose of M7 while multiple
uncontrolled fresh-eligible `NEWS_ANALYSIS`/`CREATED` tasks exist (currently 1153), unless the
isolation method in use structurally guarantees no unintended task is processed. The corrected
procedure below satisfies this by construction — it never starts the batch worker for M7 at all.

**Corrected isolation strategy**: direct, one-off invocation of already-authorized primitives,
bypassing the eligibility-query/batch-selection mechanism entirely for this one supervised run.
Per instruction, this Plan does **not** invent a new one-shot exact-task CLI/script: Contract §26's
file scope authorizes no such file anywhere, and none is added here. Instead, M7 uses **only**
functions already authorized by the Contract and earlier sections of this Plan —
`WorkflowRunner.run()` (§8.1), `CapabilityExecutor`, `assemble_ai_integration_layer()`,
`FilePromptRepository`, `async_session_factory` (all already used by, and identical to, what
`worker/analysis_main.py`/`worker/analysis_cycle.py` construct at startup, §10.1/§9.2) — invoked
directly, once, against one specific, pre-identified `task_id`, from a human-supervised Python
session (an interactive REPL or a throwaway, uncommitted local script — never a new file added to
the repository, never committed). Because the eligibility query's own `SELECT`/`LIMIT` step is
never invoked for M7, the 1153-candidate ambiguity does not arise: there is no selection step left
to be ambiguous about. This is Option C of the three isolation options this correction was asked
to consider (an already-authorized exact-task execution mechanism) — it reuses `WorkflowRunner.
run(session, task_id)`, which already accepts an exact task identifier as its own parameter and
already performs the atomic claim (§8.1) against exactly that task, nothing more.

**Exact procedure**:
1. Read-only: query the real database directly for candidate `NEWS_ANALYSIS`/`CREATED` tasks
   (same shape as §9.1's `_select_eligible_task_ids()`, run manually, read-only, no claim) and pick
   exactly one specific `task_id` as the sample. Record, before any live API call: the exact
   `task_id`; its associated `NewsEvent.id`; the freshness timestamp used
   (`COALESCE(published_at, collected_at)`) and its value; confirmation that
   `EditorialTask.status == CREATED` at the moment of recording; and an explicit written statement
   that this specific `task_id` is the intended, controlled sample for this M7 run. No other task
   may be intentionally processed during this procedure.
2. Record baseline counts (`CREATED`/`RUNNING`/`COMPLETED`/`FAILED`, `ContentDraft`,
   `CONTENT_GENERATION` task count).
3. In the human-supervised session, construct the real AI integration layer exactly as
   `worker/analysis_main.py` does at startup (`assemble_ai_integration_layer(settings,
   FilePromptRepository(...))`), open one real session via `async_session_factory`, construct
   `CapabilityExecutor(session, task_id, capability_registry)` and `WorkflowRunner(executor)` for
   **the one recorded `task_id` only**, and call `await runner.run(session, task_id)` directly —
   the same atomic-claim code path (§8.1) the worker would use, exercised against exactly one,
   pre-verified task. The batch worker (`worker/analysis_main.py`) is **not started** for M7.
4. Confirm no other process (worker, developer, script) claims or touches any other
   `NEWS_ANALYSIS`/`CREATED` task for the duration of this single call.
5. Observe the single `run()` call: real atomic claim of the recorded `task_id` (verify by query:
   exactly that task transitioned `CREATED → RUNNING`, no other task's status changed), real
   `WorkflowRunner`, real provider calls (research, intelligence, engagement, scoring — up to 4-5
   real calls total), real `EngagementCapability` output.
6. Confirm the recorded `task_id` — and only that `task_id` — reaches `COMPLETED` (or document the
   real outcome honestly if it does not, without adjusting thresholds to force success). Verify by
   direct query that no other `EditorialTask` row's status changed during the run.
7. Confirm, by direct query: zero new `CONTENT_GENERATION` tasks, zero new `ContentDraft` rows.
8. Confirm bounded cost exposure (at most ~4-5 real LLM calls occurred, all attributable to the one
   recorded `task_id`).
9. No repeated uncontrolled retries — if any step fails, stop and report, do not loop, and do not
   pick a different `task_id` and try again without a fresh, separate human authorization.

**Why this does not require starting the batch worker at all**: M5's own offline integration test
(§11) already proves the eligibility query's selection logic (freshness, batch cap, ordering,
workflow-name match) end-to-end against a real Postgres database, using `FakeLLMGateway` (safe, no
spend). M7's sole remaining job is to prove the **real provider/LLM path** works — one real
execution, not a re-demonstration that selection also works with real spend attached. Splitting
these two concerns (selection logic proven safely at M5; real-provider execution proven safely, in
isolation, at M7) fully validates the system without ever running the real worker against the
real, currently-1153-task-deep backlog with a real LLM attached.

**If, at execution time, no Contract-compatible isolation method can actually be exercised**: M7
is BLOCKED. State plainly: **M7 LIVE VALIDATION REQUIRES A SEPARATE HUMAN-APPROVED ISOLATION
PROCEDURE BEFORE EXECUTION.** Do not silently broaden production scope, do not start the batch
worker against the uncontrolled 1153-task backlog, and do not invent a new committed one-shot
script to work around this — either would require a fresh human decision (and, for a new script, a
Contract amendment), both out of scope for this Plan.

## 15. Atomic Claim Pseudocode

See §8.1 in full — the complete, exact, final pseudocode (not a summary) is provided there,
including the N1 resolution.

## 16. Eligibility Query Pseudocode

See §9.1 in full — the complete, exact, final SQLAlchemy query (not a summary) is provided there,
including the N2 resolution and the RED/GREEN `.as_string()` syntax correction (Planning Audit
F1).

## 17. Worker Pseudocode

See §10.1/§9.2 in full for `worker/analysis_main.py` and `worker/analysis_cycle.py` respectively.

## 18. Failure Matrix

| Case | Task state before | Action | Task state after | Worker behavior | Retry? |
|---|---|---|---|---|---|
| Missing task | (none, id invalid) | `TaskNotFoundError` | N/A | Logged, cycle continues to next id (§9.2) | No |
| Claim success | `CREATED` | Atomic `UPDATE` affects 1 row | `RUNNING` (durable) | Proceeds to execute steps | N/A |
| Claim lost (race) | `CREATED` at query time, `RUNNING`/terminal by claim time | Atomic `UPDATE` affects 0 rows | Unchanged (owned by winner) | `TaskAlreadyRunningError`/`TaskAlreadyCompletedError` caught, cycle continues (§9.2) | No |
| Already `RUNNING` | `RUNNING` | Same as claim-lost | Unchanged | Same | No |
| Already `COMPLETED` | `COMPLETED` | Same | Unchanged | Same | No |
| Already `FAILED` | `FAILED` | Same | Unchanged | Same | No |
| Research step failure | `RUNNING` | `StepExecutionError`/`PermanentStepFailureError`, existing retry-then-fail logic | `FAILED` | Cycle continues to next id | No (step-level retry only, existing, bounded) |
| Intelligence step failure | `RUNNING` | Same | `FAILED` | Same | Same |
| Engagement step failure (new capability, same existing mechanism) | `RUNNING` | Same | `FAILED` | Same | Same |
| Provider fallback exhausted | `RUNNING` | `StepExecutionError` after existing `FallbackPolicy` exhaustion | `FAILED` (after step retries exhausted) | Same | No task-level retry |
| Step timeout | `RUNNING` | `StepTimeoutError`, treated as `StepExecutionError` | `FAILED` (after retries exhausted) | Same | No task-level retry |
| Malformed structured output | `RUNNING` | `ValidationCapabilityError` → `PermanentStepFailureError` | `FAILED` immediately, no retry | Same | No |
| Cycle-level DB query failure (eligibility query itself) | N/A | `except Exception` in `worker/analysis_main.py`'s loop | No task touched | Logged, next interval | N/A |
| Cancellation (`SIGTERM`/`SIGINT`) | Any | `asyncio.CancelledError` propagates (never caught by `except Exception`) | Whatever it was at the moment of cancellation | Clean shutdown, cleanup logged | N/A |
| Process crash after claim | `RUNNING` | No handler (process is gone) | `RUNNING` (stale) | N/A — next cycle's eligibility query does not select `RUNNING` tasks, so it is simply left; monitored/recovered manually (Contract §16) | No automatic recovery |

**No automatic `FAILED`-task retry anywhere in this matrix.**

**Mid-batch failure semantics, explicit (resolves Planning Audit F5/MINOR-2)**: this matrix
deliberately separates two distinct failure classes, and §9.2's `for task_id in eligible_ids` loop
must not conflate them.

- **PER-TASK WORKFLOW FAILURE** (every "step failure"/"fallback exhausted"/"timeout"/"malformed
  output" row above): scoped to exactly the one task being processed when it occurs. Concretely —
  in a batch of 5 (`[t1, t2, t3, t4, t5]`), if `t1` completes and `t2` then fails during workflow
  execution (any row above that ends in `FAILED`), `t2` becomes `FAILED` per that row's own
  existing, unmodified `WorkflowRunner` semantics; the worker logs the failure (already-existing
  `except Exception`-free step-level handling inside `_execute_steps()`/`_fail()`, unchanged by
  Phase 13); the loop then proceeds to `t3`, `t4`, `t5` exactly as originally selected — **no
  replacement candidate is fetched to replace `t2`** (§9.2's own already-frozen "no refill" rule),
  and the total number of tasks attempted in this cycle remains ≤5 regardless of how many of them
  fail. The cycle itself does **not** abort because one task failed.
- **CYCLE-LEVEL INFRASTRUCTURE FAILURE** (the "Cycle-level DB query failure (eligibility query
  itself)" row above, and any other exception raised outside an individual `runner.run()` call —
  e.g. the database becoming unavailable while opening a per-task session in §9.2's loop): this is
  caught by `worker/analysis_main.py`'s own outer `except Exception` (§10.1), which aborts the
  **entire remaining cycle** (no further tasks in `eligible_ids` are attempted this cycle), logs
  `analysis_cycle_failed`, and waits for the next `news_analysis_poll_interval_seconds` tick to try
  again from a fresh eligibility query. This is categorically different from a per-task failure:
  it is a failure of the cycle's own infrastructure, not of any one task's workflow.

An implementer must not merge these two classes: a per-task `WorkflowRunner` exception (caught
inside §9.2's own `try/except (TaskAlreadyRunningError, TaskAlreadyCompletedError)` block, or
allowed to propagate as a normal `FAILED`-terminal `WorkflowRunResult` per the rows above) must
never abort the remaining batch; an exception raised outside that per-task boundary (e.g. the
per-task `async with session_factory() as session:` context itself failing to open) must abort the
remaining cycle rather than being silently swallowed and retried task-by-task.

## 19. Test Plan

| Test file | New/Modified | Proves |
|---|---|---|
| `tests/test_engagement_capability.py` | New | Input propagation (research+intelligence step_results), graceful degradation when either is missing, output floor-validation, `FakeLLMGateway`-backed success/failure paths |
| `tests/test_capability_registry.py` | Modified (append) | `CapabilityRegistry.resolve("engagement")` succeeds once registered |
| `tests/test_workflow_runner.py` | Modified (append only — **zero existing test line changed**) | Atomic-claim concurrency: two real, concurrent `asyncio.gather()`'d `run()` calls on the same `CREATED` task id via `independent_session_factory()`-backed independent sessions — exactly one wins, the loser raises `TaskAlreadyRunningError` and its `CapabilityExecutor`/executor path is never entered (asserted via a call-count spy); static grep confirms no `except BaseException`/bare `except:` in the diff |
| `tests/test_analysis_worker_cycle.py` | New | `_select_eligible_task_ids()`: freshness cutoff (>48h excluded, <48h included), batch cap (6+ eligible → exactly 5 selected), deterministic ordering, **workflow-name JSON match via `.as_string()`** — a test-owned `NEWS_ANALYSIS` task is found, a test-owned `CONTENT_GENERATION`-workflow task is excluded (the GREEN proof from §9.1, run against controlled test-owned rows, not the production backlog); `run_analysis_cycle()`: sequential execution (no `asyncio.gather`), lost-race handling (not fatal, not refilled), **mid-batch per-task failure** (one test-owned task among several selected candidates is forced to fail its workflow — assert the remaining already-selected candidates still execute, no replacement candidate is fetched, and the cycle itself does not abort — §18's MINOR-2 correction) |
| `tests/test_analysis_worker_main.py` | New | Enabled loop (calls cycle, sleeps 300s-equivalent short interval in test), disabled idle (zero cycles, logs once), cancellation (during cycle, during sleep), static no-`BaseException` check, **cycle-level infrastructure failure** (the cycle's own outer call raises — assert `analysis_cycle_failed` is logged, the loop does not crash, and it waits for the next poll interval rather than retrying immediately — §18's MINOR-2 correction) — mirrors `tests/test_worker_main.py`'s own 8-test shape |
| `tests/test_settings_phase7.py` | Modified (append) | 4 new fields: default/override/validation, mirroring the existing Phase 12 pattern |
| `tests/test_news_analysis_integration.py` | New | Full real-Postgres chain (§11): research→intelligence→engagement→scoring order and propagation, `COMPLETED` result, zero `CONTENT_GENERATION`/`ContentDraft` rows, freshness exclusion, batch cap, zero-pollution cleanup |
| Prompt/schema invariant (inside `tests/test_engagement_capability.py`) | New | `additionalProperties: false` + all-3-fields-required — a synthetic invalid schema fails the invariant check, the real `prompts/engagement/v1.yaml` passes it (non-tautological, per Contract audit's own instruction) |
| `tests/test_openai_strict_schema_compliance.py` | Modified (append) | Resolves Planning Audit F3/MAJOR-3. One new tuple in `_ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES` (`("engagement", "1", ENGAGEMENT_CAPABILITY_DEFINITION)`) registers `prompts/engagement/v1.yaml` into the existing, unmodified, parametrized `test_active_capability_prompt_is_strict_schema_compliant` test — proves `_strict_schema_violations(rendered.output_schema) == []` (i.e. `additionalProperties: false` present, every property has a matching `required` entry, no unsupported JSON-Schema keyword used) and `rendered.output_schema.get("required") == definition.expected_output_keys` for the engagement prompt specifically, using the exact same centralized invariant every other capability's prompt is already held to — not a duplicate, capability-local reimplementation of the same check |
| `tests/test_phase9_research_intelligence_integration.py` | Modified (remove one obsolete test + comment, add one replacement — §7.4) | Resolves Final Re-Audit RA-1. `test_real_news_analysis_still_fails_at_engagement_analysis_step` is removed (its premise — `"engagement"` unregistered — is now false); `test_real_news_analysis_now_completes_through_engagement_analysis` (new, §7.4) proves the real, unmodified `NEWS_ANALYSIS` `WorkflowDefinition`, run through the real `WorkflowRunner`/`CapabilityExecutor`/`CapabilityRegistry` with a `FakeLLMGateway`, now completes all 3 capability-backed steps in exact order (`research → intelligence → engagement_analysis`), with propagation into Engagement's own request text |
| `tests/test_phase10_capability_registration.py` | Modified (one assertion pair replaced, one test added — §7.5) | Resolves Final Re-Audit RA-2. `test_unregistered_capability_still_raises_unknown_capability_error`'s `registry.resolve("engagement")` case is replaced with `registry.resolve("definitely_unregistered_capability")` (mirroring the established `tests/test_boot_assembly.py:61-66` precedent for the identical situation); its `registry.resolve("no_such_capability")` case and every other test in the file are unchanged; `test_build_registry_resolves_engagement_directly` (new) proves `CapabilityRegistry.resolve("engagement")` now succeeds and returns an `EngagementCapability` instance |
| `tests/test_phase9_cross_cutting_regression.py` | Modified (one-line sentinel-string substitution — §7.7) | Resolves Final Test-Scope Re-Audit TS-1. `test_no_phase9_test_pairs_real_news_analysis_with_completed_status`'s whitelist sentinel is updated from the removed `test_real_news_analysis_still_fails_at_engagement_analysis_step` to the new `test_real_news_analysis_now_completes_through_engagement_analysis` (§7.4); `test_full_boot_sequence_resolves_all_four_capabilities` and every other line in the file are unchanged; RED/GREEN proof (§7.7) demonstrates both that the fix is required and that the meta-test's protection against any *other*, unauthorized `NEWS_ANALYSIS`+`COMPLETED` pairing remains intact |

**Grep performed this session** (Step 27's own instruction) for hidden mechanical-update risk: no
test file anywhere hardcodes "5 registered capabilities" as a literal count assertion (checked
`tests/test_capability_registry.py`, `tests/test_registry_consistency.py`) — confirmed no existing
test needs updating merely because a 6th capability now exists, beyond the one new assertion already
planned above. No test hardcodes `NEWS_ANALYSIS`'s step count as "3 steps" anywhere (checked
`tests/test_workflow_schemas.py`, `tests/test_workflow_registry.py`) — the workflow definition
itself is unchanged by Phase 13 (already had 4 steps, `engagement_analysis` already declared, only
its capability was unregistered), so no update is needed there either.

**Correction to the grep above (Planning Audit F3)**: this original search missed
`tests/test_openai_strict_schema_compliance.py`, whose `_ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES`
list (5 hardcoded tuples) is exactly the kind of hidden mechanical-update risk this grep was meant
to catch — it does not auto-discover new capabilities/prompts, so `EngagementCapability`'s prompt
would silently receive zero centralized strict-schema coverage without the one-tuple addition now
listed in §4 and in the table above.

**Second correction to the grep above (Final Re-Audit RA-1/RA-2; this revision, Correction Pass
2)**: the "no other hardcoded-list file was found" claim in the paragraph above was itself
incomplete — it searched only for hardcoded *counts* ("5 registered capabilities", "3 steps"), not
hardcoded *identity* assumptions about the literal string `"engagement"` specifically. A broader,
repository-wide grep this revision for the literal token `"engagement"`, for `UnknownCapabilityError`
usage, for `NEWS_ANALYSIS` usage, and for step-order/step-count assertions across every test file
(not only `test_phase9_*`/`test_phase10_*`-prefixed ones) found exactly two affected pre-existing
tests — `tests/test_phase9_research_intelligence_integration.py::test_real_news_analysis_still_
fails_at_engagement_analysis_step` and `tests/test_phase10_capability_registration.py::test_
unregistered_capability_still_raises_unknown_capability_error` — both now in scope (§4, §7.4/§7.5).
Explicitly re-checked and ruled out as unaffected: `tests/test_boot_assembly.py:65` and `tests/
test_capability_boot_wiring_e2e.py:162` (both already use a safe, genuinely-unregistered
placeholder name, not `"engagement"`); `tests/test_capability_mapping.py:29` and `tests/test_ai_
execution_mapper.py:48` (both exercise `resolve_ai_capability("engagement") ==
AICapability.INTELLIGENCE`, an unrelated cost-accounting bucket mapping, independent of
`CapabilityRegistry` state — not affected by registration either way); `tests/test_phase9_
research_intelligence_integration.py`'s own `test_both_capabilities_dispatch_in_order_and_
synthetic_task_completes` (uses a synthetic 2-step registry that never declares an
`engagement_analysis` step at all — unaffected); `tests/test_phase10_workflow_integration.py::test_
content_generation_reaches_completed_in_exact_step_order` (tests `CONTENT_GENERATION`, not
`NEWS_ANALYSIS` — unaffected); `tests/test_phase9_cross_cutting_regression.py::test_full_boot_
sequence_resolves_all_four_capabilities` (does not enumerate `EngagementCapability` and was already
incomplete pre-Phase-13 — a pre-existing, non-Phase-13-caused gap, out of scope per §25's own
"escalate, don't fix" rule for pre-existing defects, not a new one this Plan introduces).

**Third correction to the grep above (Final Test-Scope Re-Audit TS-1; this revision, Correction
Pass 3)**: the "no 11th affected file exists" claim in the paragraph above was itself incomplete —
it searched for hardcoded *counts* and hardcoded *identity* (the literal string `"engagement"`),
but not for a third class: existing tests that statically scan **other test files' own source
text** for a name-string sentinel, which is exactly how
`tests/test_phase9_cross_cutting_regression.py::test_no_phase9_test_pairs_real_news_analysis_
with_completed_status` works, and exactly why §7.4's own (correctly-required) `COMPLETED` proof
has a second-order effect on it (§7.7 for the full mechanism). A repository-wide grep this
revision for every test performing a directory `.glob()` scan over sibling test files found
exactly two: `tests/test_content_draft_service.py::test_capabilities_never_import_content_draft`
(scans `capabilities/*.py`, auto-discovering via glob, checking for a `ContentDraft` import — the
Plan's own `capabilities/engagement_capability.py`, §7.1, does not import `ContentDraft`, so this
test continues to pass without any scope addition — confirmed unaffected) and
`tests/test_phase9_cross_cutting_regression.py` itself (the one requiring the §7.7 correction,
now in scope). A separate, non-glob, hand-maintained allowlist,
`tests/test_capability_testing_convention.py::_CAPABILITY_UNIT_TEST_FILES` (currently 3 entries:
scoring, scoring-retry, quality — notably not even research/intelligence/copywriting), does not
auto-include `tests/test_engagement_capability.py` either, but this is an **allowlist**, not a
blocklist: omission only means that file's own convention-compliance check silently does not run
against the new file, it does not cause any existing assertion to fail — the same pre-existing,
non-Phase-13-caused incompleteness class as `test_full_boot_sequence_resolves_all_four_
capabilities` above, correctly out of scope. **No 12th affected file exists. This file (§4's
addition of `tests/test_phase9_cross_cutting_regression.py`) is now the complete, exhaustive
test-scope correction across all three search dimensions (counts, identity, sibling-file static
scans); no further file was found on this revision's broader re-grep.**

**No live OpenAI call anywhere in the automated suite.**

## 20. Real Postgres Isolation

Reuses Phase 12's own proven, already-audited discipline exactly (`independent_session_factory()`,
unique test-owned row names, explicit FK-safe `try/finally` cleanup, no rollback-only isolation since
`WorkflowRunner`/`CapabilityExecutor` commit independently through their own sessions, no separate
test database — none exists). The atomic-claim concurrency test (§19) is the one genuinely new
pattern: two independent `session_factory()`-derived sessions racing against the same row, real
Postgres row-locking exercised, not mocked — directly modeled on
`tests/test_triage_orchestrator_claims.py`'s own already-proven concurrency-test shape for
`_claim_new_event()`.

## 21. Cost-Safety Controls

Restated, binding, unchanged from Contract §17: no `max_daily_ai_cost`, no `CostTracker` fix. Cost
exposure is bounded exclusively by: 48h freshness cutoff (§9.1), batch cap 5 (§9.1's `LIMIT`),
sequential execution (§9.2, no concurrency), 300s poll interval (§10.1), no `FAILED`-task retry
(§18), no `CONTENT_GENERATION` chaining (§11 item 5). Tests plan only what is actually enforceable
(§19) — no test asserts a dollar amount was capped, since no mechanism provides that guarantee.

## 22. CONTENT_GENERATION Boundary Proof

Three independent layers, none merely asserted: (1) mechanical grep of `worker/analysis_*.py` for
`run_content_generation_for_event`/`CONTENT_GENERATION` at M6's own gate (§12 item 9); (2) a
zero-rows database assertion in the M5 integration test (§11 item 5); (3) the full, unmodified
`tests/test_workflow_runner.py` suite (§19) continuing to pass proves the atomic-claim fix does not
alter `CONTENT_GENERATION`'s own, separate, already-tested execution path in any way.

## 23. Milestone Reports

Not created now — planned only, per instruction: `docs/phase13_m1_engagement_capability_report.md`,
`docs/phase13_m2_atomic_claim_report.md`, `docs/phase13_m3_analysis_cycle_report.md`,
`docs/phase13_m4_runtime_worker_report.md`, `docs/phase13_m5_integration_report.md`,
`docs/phase13_m6_readiness_report.md`, and separately, only after explicit human authorization,
`docs/phase13_m7_live_validation_report.md`.

## 24. Validation Commands / Gates

**Per-milestone (M1-M5)**: focused `pytest` for that milestone's own new/modified test file(s);
relevant regression `pytest` (e.g. the full `tests/test_workflow_runner.py` after M2); `ruff check`
on changed files; targeted `mypy` on changed files; `git status --short`/`git diff --name-only` scope
check against §4's table.

**M6 (final)**: the full list in §12, items 1-9, run fresh.

**Docker validation, every time `docker-compose.yml` is touched or reviewed**: `docker compose
config --quiet` and/or `docker compose config --services` only — **never** plain `docker compose
config` (§10.3's mandatory rule).

## 25. Autonomous Stop Rules

Autonomous implementation may proceed milestone-to-milestone through M0-M6 only if, at every
milestone boundary: no CRITICAL/MAJOR finding exists, that milestone's own tests are green, file
scope matches §4 exactly, and no new architecture decision is required beyond what this Plan already
specifies.

**STOP immediately, report, and wait for human review if**: the Contract or source is found to
contradict this Plan; a migration turns out to be genuinely required; the atomic claim cannot be
proven race-safe in the real concurrency test (§19); any existing `tests/test_workflow_runner.py`
test (`CONTENT_GENERATION`-related or otherwise) regresses; a new secret exposure occurs (mirroring
the Phase 12 M3 incident's own severity); a file outside §4's exhaustive scope turns out to be
genuinely required; a real, pre-existing (non-Phase-13-caused) defect is discovered (mirroring Phase
12's own R9 rule: fix only if directly caused by this Plan's own new code and within its already-
authorized narrow scope; otherwise escalate); or any step would require a live API call before M7.

**M7 always requires explicit, separate human authorization** — no exception, regardless of how
green M0-M6 are.

## 26. Risk Register

| ID | Cause | Impact | Mitigation | Verification |
|---|---|---|---|---|
| R1 | Atomic-claim fix regresses `CONTENT_GENERATION` | Would break Phase 10's own already-live manual path | Narrow, single-method fix; full existing test suite re-run unmodified (§19/§22) | M2's own gate; M6 item 1 |
| R2 | ORM identity-map staleness (audit N1) reintroduced by a future edit | Silent bug if any future code reads `task.status` before the explicit sync | Explicit in-memory sync immediately after claim (§8.1); comment explaining why | Code review at M2; no test can directly prove "no future bug," but the explicit sync removes the underlying hazard |
| R3 | Eligibility query falls back to Python-side full-table filtering (audit N2), or uses a JSON-extraction syntax that silently matches the wrong rows (Planning Audit F1 — `.astext` doesn't compile at all against this repo's generic `sqlalchemy.JSON` column; `cast(..., String)` compiles but matched 0 of 4723 real rows due to JSON quoting) | Loads ~4723+ rows into memory every 300s cycle, or (F1) matches zero/wrong rows so no `NEWS_ANALYSIS` task is ever processed | SQL-side `.as_string()` predicate is the sole, frozen, mandatory syntax (§9.1) — empirically verified against all 4723 real rows this session; `.astext`/`cast(..., String)` are explicitly retired, not offered as alternatives | M3's own gate; the query's own `EXPLAIN`-verifiable shape; the M3 GREEN regression test (§19) against controlled test-owned rows |
| R4 | Backlog burst | 4723+ tasks exist; freshness+batch caps are the only bound | Both mandatory, enforced in the SQL query itself, not application logic | M5 backlog-exclusion test; M6 item 9 |
| R5 | `EngagementCapability`'s untested new prompt underperforms | Low-quality `NEWS_ANALYSIS` output, not a safety issue | Floor-validation + strict schema catch malformed output; quality itself is a live-validation (M7) concern, not blocking M0-M6 | M1's own tests; M7 procedure |
| R6 | Redis dependency omitted from Docker service | Worker would fail on startup in the real deployment | Explicitly re-derived (not copied from Phase 12), included (§10.3) | M4's own gate; M6 item 5 |
| R7 | `docker compose config` (no flags) run again during validation | Re-exposes secrets, repeating the Phase 12 M3 incident | Explicit, repeated, mandatory prohibition (§10.3/§24) | Every milestone touching Docker |
| R8 | Stale `RUNNING` task after a crash | Permanently unexecutable without manual intervention | Documented monitoring query + manual recovery (Contract §16), no auto-recovery built | Operational, not automated — explicitly accepted |
| R9 | Live validation accidentally touches the uncontrolled fresh-eligible backlog — **not merely the historical stale backlog**: a direct query this session found 1153 `NEWS_ANALYSIS`/`CREATED` tasks currently satisfy the ≤48h freshness cutoff (Planning Audit F2), so freshness cutoff + `LIMIT 1` alone (the Plan's original claim) does **not** isolate a chosen sample | Uncontrolled cost/scope; a real LLM call against an unintended, unverified task | M7 no longer starts the batch worker at all; it uses a direct, one-off invocation of already-authorized primitives (`WorkflowRunner.run()`, `CapabilityExecutor`) against one pre-recorded, human-verified `task_id`, bypassing the eligibility-query selection step entirely (§14, corrected) | M7 procedure steps 1-6; hard precondition against starting the normal worker while the 1153-task condition holds |
| R10 | `tests/test_openai_strict_schema_compliance.py`'s hardcoded capability list silently omits `EngagementCapability`'s prompt (Planning Audit F3) | The new prompt's strict-schema compliance (`additionalProperties: false`, required keys) is never centrally checked; a future OpenAI 400-class failure (the exact historical incident this file exists to prevent) becomes possible for this capability specifically | One new tuple added to `_ACTIVE_STRUCTURED_OUTPUT_CAPABILITIES` at M1 (§4, §19) — no other change to that file | M1's own gate; M6 item 1 (full suite includes this parametrized test) |
| R11 | M1's own registration of `"engagement"` mechanically breaks two pre-existing, previously-out-of-scope tests that assert it is unregistered (Final Re-Audit RA-1/RA-2) — a class of hidden coupling a count-only grep does not catch | Two currently-passing regression tests fail the instant M1 ships, blocking M6's own "zero failures" gate for the entire Plan | Both files added to scope (§4), replacement designs frozen (§7.4/§7.5), M1's own atomic-ownership rule (§7 — registration and both test corrections land together, never separately), M1 Regression Matrix (§7.6), M6's own focused-regression-first step (§12) | M1's own gate (all eight §7.6 rows green together); M6 items 1-3 (focused regressions) before the full-suite step |
| R12 | §7.4's own required `COMPLETED` proof (needed to correctly resolve R11's own Phase 9 test) has a second-order effect: it reintroduces the exact three-token trigger combination a separate, pre-existing static-scan meta-test (`tests/test_phase9_cross_cutting_regression.py`) flags, while the old exemption sentinel is deleted in the same fix (Final Test-Scope Re-Audit TS-1) — a class of hidden coupling one level deeper than R11's, missed by a literal-identity-only grep | A third, previously-unlisted, currently-passing test fails mechanically at M1, for the same underlying reason class as R11, blocking M6's own gate again | File added to scope (§4), exact one-line sentinel substitution frozen with RED/GREEN proof (§7.7), M1's own atomic-ownership rule expanded to eight items (§7), M1 Regression Matrix row 8 (§7.6), M6's own focused-regression list expanded to three files (§12) | M1's own gate (all eight §7.6 rows green together, including row 8's RED/GREEN proof); M6 items 1-4 (focused regressions) before the full-suite step |

## 27. Definition of Done Mapping

| Contract §31 item | Milestone | Test/proof |
|---|---|---|
| 1. `EngagementCapability` exists | M1 | File exists, imports cleanly |
| 2. Registered correctly | M1 | `tests/test_capability_registry.py` addition |
| 3. Strict prompt/schema valid | M1 | Schema invariant test (§19) |
| 4. `NEWS_ANALYSIS` executable end-to-end (`FakeLLMGateway`) | M5 | `tests/test_news_analysis_integration.py` |
| 5. Atomic claim proven under concurrency | M2 | `tests/test_workflow_runner.py` addition |
| 6. One owner per task | M2 | Same |
| 7. Freshness ≤48h enforced | M3 | `tests/test_analysis_worker_cycle.py` |
| 8. Batch ≤5 | M3 | Same |
| 9. Sequential execution | M3 | Same (code inspection — no `gather`) |
| 10. Poll=300s | M4 | `tests/test_settings_phase7.py` addition + `tests/test_analysis_worker_main.py` |
| 11. Historical stale backlog untouched | M3/M5 | Freshness-exclusion tests both milestones |
| 12. No automatic `FAILED` retry | M3 | Eligibility query excludes `FAILED` by construction |
| 13. Stale `RUNNING` auto-recovery absent/documented | M2 (absence) + this Plan §18/§26 (documentation) | No code exists to test the absence of; documentation reviewed at M6 |
| 14. No `CONTENT_GENERATION` trigger | M5 | Zero-rows assertion |
| 15. No `ContentDraft` creation | M5 | Same |
| 16. No observed-engagement false claims | M1 | Schema/naming review + M1 tests |
| 17. No migration | All | M6 item 6 |
| 18. Full tests pass | M6 | Item 1 |
| 19. Ruff passes | M6 | Item 2 |
| 20. Mypy passes | M6 | Item 3 |
| 21. Architecture validator passes | M6 | Item 4 |
| 22. Secret hygiene clean | M6 | Item 5 |
| 23. Manual live tiny-sample acceptance passes | M7 | §14 |

**Every Contract DoD item is mapped. None is unmapped.**

## 28. Exact File Counts

**Recalculated this revision (Final Test-Scope Re-Audit TS-1, superseding the prior "10 test-file
items" count; the Planning Audit F3, Final Re-Audit RA-1/RA-2, and pre-existing
arithmetic-inconsistency corrections from prior passes remain in effect and are not re-litigated
here).**

**Production/runtime**: 4 new (`capabilities/engagement_capability.py`, `worker/analysis_main.py`,
`worker/analysis_cycle.py`, `prompts/engagement/v1.yaml`) + 4 modified (`workflows/runner.py`,
`capabilities/registry.py`, `core/config.py`, `docker-compose.yml`) = **8 total**. Unchanged by
this revision — TS-1, like RA-1/RA-2 before it, is a test-only correction.

**Tests**: 4 new (`tests/test_engagement_capability.py`, `tests/test_analysis_worker_cycle.py`,
`tests/test_analysis_worker_main.py`, `tests/test_news_analysis_integration.py` — the
`prompts/engagement/v1.yaml` schema-invariant test lives inside `test_engagement_capability.py`,
not a separate file; `test_build_registry_resolves_engagement_directly`, §7.5, lives inside the
already-counted `tests/test_phase10_capability_registration.py` modification below, not a separate
file) + 7 modified (`tests/test_workflow_runner.py`, `tests/test_capability_registry.py`,
`tests/test_settings_phase7.py`, `tests/test_openai_strict_schema_compliance.py`,
`tests/test_phase9_research_intelligence_integration.py`,
`tests/test_phase10_capability_registration.py`, and, **added this revision**,
`tests/test_phase9_cross_cutting_regression.py`) = **4 new + 7 modified = 11 total**, matching
§4's table row-for-row (recount performed directly against §4: 4 new-test rows, 7 modified-test
rows).

**Grand total files touched by Phase 13 implementation** (production + test, governance documents
excluded per below): 8 production + 11 test = **19 total**.

**Docs created during future implementation** (not counted as implementation files, per instruction):
6 milestone reports (M1-M6) + 1 M7 report (human-authorized only) = 7 expected future documents, not
created by this Plan.

**This Plan document itself, the Contract, the Audit, the Decision Resolution, and the Discovery
document are governance artifacts, not implementation files, and are excluded from the counts
above.**

## 29. Final Recommendation

Implementation may proceed milestone-by-milestone (M0→M6) exactly as sequenced in §5, with a
mandatory stop before M7 pending separate human authorization, once this three-times-revised Plan
itself passes a Final Gate Audit.

---

PHASE 13 IMPLEMENTATION PLAN REVISION PASS 3 COMPLETE — READY FOR FINAL GATE AUDIT
