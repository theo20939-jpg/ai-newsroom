# Phase 12 — Fresh News Automation Final Targeted Contract Re-Audit

Final targeted re-audit only. No Contract, Decision Resolution, production code, test, or migration
file was modified to produce this document. Every claim below was independently re-verified against
current source this session — the Revision Report from Correction Pass 2 was not trusted; the same
underlying files (`services/collector.py`, `services/adapter_registry.py`,
`services/adapter_keys.py`, `integrations/sources/base.py`, `docker-compose.yml`, `pyproject.toml`,
`Dockerfile`, `core/config.py`, `tests/test_settings_phase7.py`) were re-read directly.

## 1. Executive Verdict

**Both remaining findings from the prior re-audit are genuinely resolved.** The `SourceAdapterResolver`
`Protocol` retype, traced end-to-end against current source, correctly closes the hidden
`ADAPTER_KEY_TO_ADAPTER` singleton dependency: `_load_active_sources()`/`_process_source()` consume
the injected `registry` parameter through exactly one structural call
(`registry.resolve(source)`), so narrowing its type from the concrete `AdapterRegistry` class to a
`Protocol` exposing only that method is sufficient — a test-owned fake resolver can now satisfy the
seam without ever constructing a real `AdapterRegistry` or importing `ADAPTER_KEY_TO_ADAPTER`, and
`services/adapter_registry.py`/`services/adapter_keys.py` remain genuinely unmodified. The
`tests/test_settings_phase7.py` authorization for Correction 2 is independently confirmed to be
this repository's own established location for `Settings`-field tests. No new CRITICAL or MAJOR
issue was introduced by Correction Pass 2. One trivial, non-blocking documentation inconsistency was
found (§11, N1) — a stale file count in §30's self-audit narrative that does not match §22's own
(correct) content — which does not affect feasibility or leave any decision to Planning.

## 2. Audit Scope

This audit re-verifies only the two items Correction Pass 2 targeted (the adapter-singleton seam,
the config-test file-scope gap), confirms no regression in the five previously-resolved corrections
(cancellation semantics, disabled-state model, Redis dependency, failure-table Case A, `CREATED`-task
framing), and performs one final exhaustive file-scope and determinism check. Unrelated,
already-approved Phase 12 decisions (cadence, concurrency, observability, dedup, media-discard
disclosure, public-publishing exclusion) were not re-litigated.

## 3. Adapter Resolution Source Trace

Independently re-read `services/collector.py`, `services/adapter_registry.py`, and
`services/adapter_keys.py` directly (current, unmodified working tree — no Phase 12 code exists yet).
Confirmed production call chain exactly as the Contract's §4/§7 now state:

```
run_collection_cycle()
  → source_pack_loader()                         [load_source_pack(), services/source_registry.py]
  → adapter_resolver_factory(definitions)         [build_registry(), services/adapter_registry.py]
       → AdapterRegistry(url_index, definition_index)
  → registry.resolve(source)                      [services/adapter_registry.py:75-95]
       → resolve_adapter_key(...) → adapter_key (a string)
       → ADAPTER_KEY_TO_ADAPTER.get(adapter_key)   [services/adapter_keys.py:64-66, real singletons]
  → resolution.adapter.fetch(source, context)      [_fetch_with_retry(), services/collector.py:103-134]
  → _process_item() → deduplication.is_duplicate() → NewsEvent persistence
```

This confirms the Contract's own trace in §4 (lines 95-114) is accurate: the real adapter *object*
is decided by `ADAPTER_KEY_TO_ADAPTER`, not by anything `source_pack_loader`/`adapter_resolver_factory`
supplies directly — the only lever that actually reaches the adapter-instance decision is
`registry.resolve()`'s own return value, which is exactly what the `SourceAdapterResolver` `Protocol`
now targets.

## 4. SourceAdapterResolver Protocol Verification

Re-read `_load_active_sources()` (`services/collector.py:81-85`) and `_process_source()`
(`services/collector.py:88-100`) line by line. Confirmed both consume their `registry` parameter
through **exactly one** call each — `registry.resolve(source)` — and nothing else: no
`.resolve_many()`, no `._url_index`/`._definition_index` access, no other attribute or method.
**Check 2 passes**: the Contract's `Protocol` (`resolve(self, source: NewsSource) -> AdapterResolution
| None`) covers the complete set of members either function actually touches. No insufficiency found.

## 5. Production Default Verification

Re-read `AdapterRegistry.resolve()` (`services/adapter_registry.py:75-95`) sync signature:
`def resolve(self, source: NewsSource) -> AdapterResolution | None` — synchronous, matching the
Contract's Protocol exactly in parameter shape, return shape, and sync semantics (no `async def`
mismatch). **Check 3 passes**: `AdapterRegistry` already structurally satisfies
`SourceAdapterResolver` with zero modification — Python's `Protocol` (PEP 544) does not require an
explicit `class AdapterRegistry(SourceAdapterResolver):` relationship for either static (mypy) or
runtime (duck-typed) correctness. Re-confirmed `build_registry()`'s own implementation
(`services/adapter_registry.py:98-129`) is untouched by anything in the Contract's authorized scope
— the production default path (`adapter_resolver_factory=build_registry`, called with zero
Phase-12-supplied arguments in `worker/cycle.py`/`scripts/run_collector.py`) resolves through the
exact same `ADAPTER_KEY_TO_ADAPTER` map as today, with **zero change to which adapter any given
`NewsSource` resolves to**. **Check 4 passes.**

## 6. Fake Adapter / Singleton Bypass Proof

Traced the future test path conceptually against real, re-read source: a test-owned class — e.g.
`FakeAdapterRegistry` in `tests/fakes/fake_source_adapter.py` — need only define one method,
`resolve(self, source: NewsSource) -> AdapterResolution | None`, returning a real
`AdapterResolution(adapter=FakeSourceAdapter(...), definition=...)` (a plain, frozen dataclass —
`services/adapter_registry.py:35-42` — safely constructible directly, since it is a passive data
container with no business logic of its own). Nothing in this construction requires importing
`services.adapter_keys`, constructing `AdapterRegistry`, or calling `build_registry()`/
`resolve_adapter_key()`. Re-confirmed `_load_active_sources()`/`_process_source()` perform no
`isinstance(registry, AdapterRegistry)` check anywhere (§4 above) — Python's duck typing accepts the
fake object unconditionally at the call sites that matter. **Check 5/6 pass: no mandatory
production DB, filesystem source pack, real adapter singleton, external network, or credential
remains reachable on the injected fake path.** The three frozen seams (`session_factory`,
`source_pack_loader`, `adapter_resolver_factory`) are genuinely sufficient — no fourth hidden
dependency was found on this final pass.

## 7. Integration-Test Feasibility

Re-confirmed §25's frozen flow is now fully specified with no unstated mechanism: fake
`source_pack_loader` → fake `adapter_resolver_factory` (test-owned resolver, §6 above) → real
`run_collection_cycle()` orchestration (`_load_active_sources`, `_process_source`,
`_fetch_with_retry`, `_process_item`, exact-hash dedup — none of these were duplicated; **Check 7
confirmed**: the test exercises the real, unmodified functions directly, not a test-only
reimplementation) → real test `session_factory` → real `NewsEvent` persistence → real
`run_triage_cycle(session_factory=...)` (pre-existing DI, unchanged) → `EditorialTask(NEWS_ANALYSIS,
CREATED)`. No external network, no production credential, no global singleton mutation, no
`WorkflowRunner`, no `EngagementCapability` execution, no `ContentDraft` — all independently
re-confirmed against §9/§21/§23's unchanged exclusions. **No unstated architectural decision remains
on this path.**

## 8. Config-Test Scope Verification

Re-read `tests/test_settings_phase7.py` directly (lines 1-60+). Confirmed it already contains direct
`Settings()`-construction tests for `enabled_providers`, `verify_capabilities_at_boot`,
`redis_unavailable_policy`, and `default_content_language` (the last one, confirmed via its own
docstring reference to `docs/content_generation_language_final_implementation_plan.md`, was added
well after Phase 7 proper — direct proof that later-phase `Settings` fields already land in this
file by established convention, not a new precedent invented for this Contract). §22 (lines 624-631)
explicitly authorizes a narrow addition to this exact file for
`news_collection_enabled`/`news_collection_interval_seconds`, and §24 (lines 743-748) specifies the
exact required assertions (default, env override, `gt=0` validation) matching this file's own
existing test shape. **No other existing test file needs to be touched for this obligation.**

## 9. Exact File Scope Verification

Re-derived the full authorized scope directly from §22/§23 text:

- **New (3)**: `worker/__init__.py`, `worker/main.py`, `worker/cycle.py`.
- **Existing narrow edits (4)**: `core/config.py`, `docker-compose.yml`, `pyproject.toml`,
  `services/collector.py`.
- **Test files (5)**: `tests/test_worker_cycle.py`, `tests/test_worker_main.py`,
  `tests/fakes/fake_source_adapter.py`, `tests/test_automation_integration.py` (or Contract-permitted
  equivalent), `tests/test_settings_phase7.py` (narrow addition).

Re-confirmed via direct source/build-file inspection: no `Dockerfile` change is needed
(`Dockerfile:8-11` — `COPY . .` then `pip install .` already installs whatever `pyproject.toml`'s
`packages` list names, and `worker` is already added there per §22); no change to
`services/adapter_registry.py`/`services/adapter_keys.py` is needed (§5/§6 above); no migration is
authorized or required; no hidden package/export file is missing (`worker/__init__.py` already
covers the package marker `python -m worker.main` needs). **Check 12 passes — scope is exhaustive
and sufficient; no genuinely-required file remains unauthorized.**

## 10. Previous-Fix Non-Regression

Directly re-read §10, §13, §14, §15 in full: text is **byte-for-byte unchanged** from the
already-approved Correction Pass 1 revision except for cross-reference labels (e.g. "corrected in
Revision 3" annotations added to §7's own heading) — Correction Pass 2 touched only §1, §4, §7, §22,
§23, §24, §25, §29, §30, confirmed by direct diff-free re-read of every other section.

- **A/B (exception semantics)**: `except Exception` only, `BaseException`/bare-`except` explicitly
  forbidden, `CancelledError` propagation invariant — unchanged, §13.
- **C (disabled mode)**: `asyncio.Event().wait()` idle model, log-once, no cycle, no DB/source
  access, cancellation-responsive, no restart loop — unchanged, §14.
- **D (Redis)**: worker depends only on `postgres` — unchanged, §15.
- **E (failure semantics)**: Case A/B split matches actual `run_collection_cycle()`/
  `run_triage_cycle()` behavior — unchanged, §13.
- **F (`CREATED`-task buildup)**: accepted temporary operational debt, monitored at Manual Live
  Acceptance — unchanged, §10/§26/§28.
- **G (no `NEWS_ANALYSIS` execution)**: unchanged, §9/§23, mechanically enforced via §24's AST
  import-boundary test.

**No regression found in any of the seven previously-resolved items.**

## 11. Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

**N1 — §30 item 8's file-scope count is stale.**
- **CONTRACT LOCATION**: §30, Acceptance Checklist, item 8.
- **SOURCE EVIDENCE**: §22 (current, correct) authorizes 3 new files + 4 existing-file edits
  (`core/config.py`, `docker-compose.yml`, `pyproject.toml`, `services/collector.py`) + 5 test-file
  items including the Correction-2 addition of `tests/test_settings_phase7.py`.
- **PROBLEM**: Item 8 still reads "three new files, three config/build edits, no broad directory" —
  a count that predates Correction 1's authorization of `services/collector.py` (Revision 2) and was
  never updated; it also does not mention the Correction-2 test-file addition at all.
- **IMPACT**: None on feasibility or determinism — §22 itself (the actual binding file-scope
  section) is accurate and was independently re-verified correct in §9 above. This is a narrative
  cross-reference inside the self-audit section only, not a source of ambiguity for Planning, since
  Planning would read §22 directly rather than count files from §30's prose.
- **REQUIRED CORRECTION** (not performed — re-audit only): update item 8's wording to "four new/edited
  production files, plus authorized test-file additions including a narrow `tests/test_settings_phase7.py`
  extension."

### OBSERVATIONS

- Every other item in §30's self-audit checklist (items 1-7, 9-10, 11/11a/11b/11c, 12-17) was
  independently re-verified accurate against current source this session, not merely re-stated.
- The `SourceAdapterResolver` `Protocol` design is a clean, idiomatic, minimal-diff resolution — it
  required no change to any previously-frozen file (`services/adapter_registry.py`,
  `services/adapter_keys.py`), consistent with the correction task's own "prefer the smallest seam"
  and "do not rewrite `AdapterRegistry` unless absolutely necessary" instructions.

## 12. Readiness Score

**9/10.** Both targeted findings are genuinely, structurally resolved — not merely asserted — and
no regression was found in any of the seven previously-approved corrections. The one remaining item
is a cosmetic, non-blocking documentation inconsistency in the self-audit narrative, not a defect in
the Contract's binding content.

## 13. Final Verdict

PHASE 12 CONTRACT APPROVED — READINESS SCORE: 9/10
