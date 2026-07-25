# Phase 15 — Editorial Intelligence — M5 Fact Safety and Unsupported Claims Guard — Implementation Report

Status: IMPLEMENTED, TESTED, BACKTESTED, DEPLOYED IN SHADOW MODE. `fact_safety_mode` is `"shadow"`
— findings are computed and recorded on every real CONTENT_GENERATION run, but **delivery
behavior is unchanged**: nothing is blocked, no draft's status changes, Telegram sends proceed
exactly as before. Enforcement is fully implemented but not activated.

---

## 1. Original factual-safety defect

Phase 14.5's live validation run found a delivered draft ("Atoms привлёк $1,7 млрд до выпуска
первого продукта") whose body stated *"Раунд возглавил Andreessen Horowitz, среди инвесторов —
Uber"* — two specific factual claims (lead investor, a named co-investor) that, per Phase 14.5's
own validation methodology, were **not present in the source title** used for that check
(`docs/phase14_5_real_news_validation_report.md` §on Atoms, lines 77–88). Nothing in the pipeline
at the time deterministically verified a draft's concrete factual claims against the article that
actually generated it.

## 2. Current evidence-flow root cause

Traced exactly (M5.0), and reconfirmed still current after Phase 15 M1–M4.2's own changes — no
architectural drift since Phase 15 M0's original diagnosis:

1. **`NewsEvent.title`** is available on `CapabilityContext.business.news_event.title` at every
   step (Research, Intelligence, Copywriting, Quality) — all four read it.
2. **`NewsEvent.content`** is structurally present on the same snapshot object
   (`schemas/capability.py::NewsEventSnapshot.content`) at every step too — but
   `capabilities/copywriting_capability.py`'s own docstring is explicit: *"Contract §5's Input
   row: title/category only from `context.business.news_event` (never `content`...)"*. Quality
   reads `.summary`, not `.content`, either. So although the *data* is present in the object at
   every step, no existing prompt-builder actually passes full source content into Copywriting or
   Quality's own LLM calls.
3. **`source_url`** (`NewsEventSnapshot.url`) is likewise present but unused by every existing
   prompt-builder. **Source identity** (channel/publisher name) is not carried on
   `CapabilityContext` at all — no `NewsSource` reference exists on the snapshot, and none was
   added for M5 (not needed: title/content/url are sufficient for M5's own claim-matching).
4. **Research's `facts`** output (`prompts/research/v2.yaml`'s real, current schema) is a bare
   `list[str]` — plain paraphrased sentences, nothing more.
5. **Zero provenance**: confirmed by direct inspection of the schema — no citation, URL, or
   quote-span field exists anywhere in Research's output contract. Every fact is an unlinked LLM
   paraphrase.
6. **Intelligence** (`significance`/`angle`/`audience_relevance`/`recommendation`) does not carry
   money/date/entity-shaped fields — lower risk of introducing new fabricatable facts than
   Research/Copywriting, though its free-text `angle`/`recommendation` fields are not immune in
   principle.
7. **Copywriting receives only paraphrased evidence**: confirmed (point 2) — title/category plus
   Research's/Intelligence's own already-unprovenanced output only.
8. **Quality does not check factual support today**: confirmed by reading
   `capabilities/quality_capability.py` in full — its `{"passed": bool, "issues": list}` output is
   a second LLM *opinion* on "editorial quality," never a deterministic comparison against
   original evidence. Its own `_build_request()` doesn't even receive `NewsEvent.content`.
9. **Final draft text before persistence**: lives in-memory as
   `WorkflowRunResult.step_results[i].result` for `step_name == "copywriting"`
   (`{"title", "body", "hashtags"}`), durably persisted into `EditorialTask.workflow` JSON by
   `workflows/runner.py`'s existing per-step commit (Phase 9.5), then read by
   `services/content_draft_service.py::ContentDraftService.create_from_result()` to build the
   `ContentDraft` row — **unconditionally**, regardless of what Quality's own `passed`/`issues`
   said. Confirmed by reading `scripts/run_content_generation.py`: a workflow that COMPLETED
   (all 4 steps technically succeeded) always creates a draft; Quality's semantic verdict was
   never read by anything gating persistence or delivery, before M5.
10. **Safest existing deterministic boundary**: `capabilities/executor.py`'s
    `CapabilityExecutor.execute()`, gated on `step.capability == "quality"` — the exact same
    architectural seam Phase 15 M4 already proved out for `step.capability == "scoring"`. At this
    point, `context.business.news_event` already carries the raw title/content/url, and
    `context.business.workflow_state.step_results` already contains every prior completed step
    (including `"research"`), all with **zero additional DB queries** — `_build_context()`
    already loads `NewsEvent` once per step and already merges every completed step's result into
    the context object before Quality's own capability is even invoked.

## 3. Evidence packet contract

`services/fact_safety.py::FactEvidence` (a frozen dataclass, mirroring
`services/editorial_scoring.py`'s own pure-dataclass convention):

```python
@dataclass(frozen=True)
class FactEvidence:
    source_title: str
    source_content: str | None       # None = genuinely unavailable, tracked distinctly (§6)
    source_url: str | None
    research_facts: list[str] = ()          # real, current, always-unprovenanced Research shape
    research_facts_provenanced: tuple[tuple[str, str], ...] = ()  # (fact, source_url) - extensibility hook
    intelligence_summary: str | None = None
```

Built entirely from data already on `CapabilityContext` — no new external call, no new DB query,
no duplicated storage. `research_facts_provenanced` is never populated by production code today
(no Research output carries provenance — §2 point 5) but the classifier already knows how to
treat a provenanced match as full-strength support, distinct from an unprovenanced one (tested
directly: `test_11_research_fact_with_valid_provenance_supports` /
`test_12_research_claim_without_provenance_does_not_override_original_evidence`) — so a future
Research capability version that *does* attach provenance requires no classifier change, only
population of this already-designed field.

## 4. Claim extraction rules

Pure `re`-based (stdlib only — no new dependency; this repository has zero NLP libraries
installed and M5 does not add one, per its own explicit scope boundary). Five claim types
(`services/fact_safety.py::extract_claims()`):

- **money**: currency-symbol-anchored (`$1.7 billion`, `$1.7B`), magnitude-word-anchored
  (`1.7 billion dollars`, `1,7 млрд долларов`), or currency-word-anchored (`50 dollars`) — never a
  bare number alone (a real, fixed bug during development: an early version matched `"5 bears"` as
  `$5B` because a lone-letter magnitude shorthand matched as a prefix of an unrelated word; every
  magnitude/currency alternative is now `\b`-anchored to its own word boundary).
- **percentage**: `14%` / `14 percent` / `14 процента`, any of the same number formats as money.
- **date**: ISO (`2026-07-24`), slash (`24.07.2026`), month-name-first and day-first forms in
  English and Russian, plus a bare 4-digit year fallback.
- **entity**: 1–4 consecutive capitalized-word runs, with a legal suffix attached when present.
  A *lone* single Title-Case word (just a capitalized first letter) is **deliberately excluded**
  unless it carries an independent stronger signal — all-caps acronym (`NASA`), an internal
  capital past the first letter (`OpenAI`, `iPhone`), or an attached legal suffix (`Acme Inc`).
  This is the single largest false-positive control in the whole module: an unfiltered "any
  capitalized word" heuristic flags every sentence-initial word in both English and Russian.
- **quote**: text inside `"…"`, `«…»`, or `"…"`, **required to contain at least two words** — a
  second real, fixed false-positive class found during backtesting: Russian news writing
  conventionally wraps a bare brand/proper name in guillemets (`«Медикейд»`, `«Палантир»`) as pure
  orthographic styling, not an attributed statement; a single-word "quote" is essentially always
  this pattern, never genuine reported speech.

Money/percentage/date extraction all share one number sub-pattern
(`_MONEY_NUMBER`) requiring either proper 3-digit thousands-grouping or at most one decimal
separator — a second real, fixed bug: an earlier, more permissive digit-class let a date like
`24.07.2026` (two periods) get mis-parsed as a money amount once a stray "b"/"m"/"k" happened to
follow it in the surrounding text.

Entities never extract across a newline (a third real, fixed bug: a capitalized word ending a
draft's title could otherwise concatenate with a capitalized word starting the body into one
false multi-word "entity" spanning the title/body boundary — the internal word-separator is
`[^\S\n]+`, not `\s+`).

## 5. Normalization rules

`services/fact_safety.py`, each independently unit-tested:

- **Unicode**: `unicodedata.normalize("NFKC", …)` + casefold + collapsed whitespace as the base
  step for every comparison — a safe, standard compatibility fold (e.g. full-width Latin `Ａ` →
  `A`), never a lossy/fuzzy transformation.
- **Money**: `("$1.7 billion", "$1,7 млрд", "$1.7B")` all normalize to `("USD", 1_700_000_000.0)`.
  Decimal-comma vs. decimal-point, and proper thousands-grouping (`1,700,000` / `1.700.000`) vs.
  a plain decimal (`1,7`), are disambiguated by trailing-digit-count and separator-count rules
  (`_parse_money_number`'s own docstring documents the exact rule).
  Currency resolved from symbol (`$€£₽`) or word (English + Russian, both cases).
- **Percentage**: same number parsing, strips `%`/`percent`/`процент(а/ов)`.
- **Date**: resolves to `(year, month|None, day|None)`. Two dates *match* when every field both
  sides actually specify agrees — a source saying only "2026" does not contradict a draft saying
  "July 2026" (compatible, not identical), but a draft saying "August 2026" against a source
  saying "July 2026" is a genuine, caught mismatch.
- **Entity**: strips legal suffixes (`Inc`/`LLC`/`Ltd`/`Corp`/`GmbH`/`plc`, case-insensitive,
  trailing) *and* Russian legal-form prefixes (`ООО`/`ЗАО`/`ПАО`/`ОАО`, leading — the reverse
  convention from English, a real bug caught and fixed by the module's own test suite: an initial
  suffix-only pattern didn't handle `"ООО Ромашка"` at all).

Not attempted, per M5.3's own "where practical" qualifier and the module's explicit scope
boundary: full Russian noun-case declension (a name can appear as "Трэвиса Каланика" (genitive)
vs. "Трэвисом Калаником" (instrumental) depending on sentence role) — a real, characterized,
accepted limitation, not silently ignored (§13's false-positive review documents a live example).

## 6. Support classifications

Three states (`SupportLevel`), checked in this exact precedence per claim
(`services/fact_safety.py::_classify_claim`):

1. Matches something in **original source evidence** (title + content) → **SUPPORTED**.
2. Else matches something in **provenanced** Research evidence → **SUPPORTED** (equal-strength
   to original evidence, per its own provenance).
3. Else matches something in **unprovenanced** Research evidence → **UNCERTAIN** — an
   unprovenanced AI paraphrase is never treated as confirming support on its own, only as
   downgrading an otherwise-confident UNSUPPORTED verdict to a flagged-for-review UNCERTAIN one.
4. Else, if `source_content` is `None`/empty (evidence genuinely incomplete, not merely
   "claim absent") → **UNCERTAIN** — never a confident UNSUPPORTED verdict manufactured from
   missing data.
5. Else → **UNSUPPORTED**.

Harmless stylistic language is never a "claim" at all — it is simply never extracted (§4), so it
never enters this classification pipeline in the first place (`test_9_harmless_editorial_
wording_is_not_a_factual_claim`: `claims_checked == 0`).

## 7. Severity rules

Centralized in two small tables (`_UNSUPPORTED_SEVERITY`, `_UNCERTAIN_SEVERITY`), never scattered:

| Claim type | UNSUPPORTED severity | UNCERTAIN severity |
|---|---|---|
| money | HIGH | MEDIUM |
| percentage | HIGH | MEDIUM |
| date | HIGH | MEDIUM |
| quote | HIGH | MEDIUM |
| entity | HIGH if central to the story (appears in the draft's own title), else MEDIUM | LOW |

The entity central-vs-secondary distinction is the one context-sensitive rule (`_entity_severity`)
— and it is precisely calibrated against the real Phase 14.5 incident shape: a fabricated
*secondary* investor/company (not the story's own subject) is MEDIUM, matching M5.5's own worked
example; a fabricated entity that *is* the story's own subject is HIGH.

## 8. Shadow/enforcement mode design

`core/config.py::Settings.fact_safety_mode: Literal["off", "shadow", "enforce"] = "shadow"` — the
explicit M5.6-mandated default, safe because shadow mode is provably delivery-neutral (§9's own
tests). Three states:

- **`off`**: `apply_fact_safety()` returns its input completely unchanged, before any processing
  — verified by object identity in tests, not merely equality.
- **`shadow`** (the live default): computes the full result and merges a `"fact_safety"` key into
  the existing `"quality"` step's structured output — purely additive; `ContentDraft.status`
  always stays `"draft"`; delivery always proceeds exactly as before.
- **`enforce`** (implemented, never activated by this milestone): the safest available existing
  mechanism was identified and reused, not invented — `services/telegram_notifier.py::
  send_editorial_card()`'s own, already-established `dry_run` parameter (render and log, never
  call the Telegram API). `worker/content_cycle.py::_fact_safety_delivery_decision()` forces
  `dry_run=True` for one notification specifically when `fact_safety_mode == "enforce"` and the
  verdict is `"review"`/`"block"` — a pure function, unit-tested directly for every mode/status
  combination. `ContentDraft.status` (a **free-text column** — `database/models/content_draft.py`'s
  own documented "not a constrained enum" design, confirmed by inspection, so no migration is
  needed) becomes `"draft_review_fact_safety"`/`"draft_blocked_fact_safety"` under `enforce` mode
  for a non-"pass" verdict — visibility, not deletion: the draft row, its full text, and the
  fact-safety findings in `EditorialTask.workflow` all remain fully queryable.

**Duplicate-task account (the task's own explicit concern)**: `worker/content_cycle.py::
_select_eligible_events()`'s existing exists-check excludes an event from re-selection the moment
*any* CONTENT_GENERATION task exists for it, regardless of that task's status — confirmed by
re-reading the query. This means a BLOCK verdict is inherently final for that event today,
structurally, independent of anything M5 does — the WorkflowRunner task itself is left
`COMPLETED` (not failed) precisely so a human reviewing `/news` or the database can see *why* a
story never reached Telegram, rather than have it look like an ordinary infra failure. This
satisfies the task's own explicit requirement: "do not create a blocked state that permanently
loses the story without visibility."

## 9. Output contract

Stored in the existing `EditorialTask.workflow["step_results"]` JSON, under the `"quality"`
step's own `result`, merged additively alongside `passed`/`issues` (never replacing them):

```json
{
  "passed": true,
  "issues": [],
  "fact_safety": {
    "version": "v1",
    "status": "review",
    "mode": "shadow",
    "claims_checked": 4,
    "supported": 3,
    "uncertain": 1,
    "unsupported": 0,
    "highest_risk": "low",
    "findings": [
      {"claim": "...", "type": "entity", "support": "uncertain", "severity": "low", "evidence": ["..."]}
    ]
  }
}
```

`findings` lists only non-SUPPORTED claims (SUPPORTED claims are summarized in the counts, not
individually surfaced — nothing to review there). Logs (`editorial_score_v2_computed`'s own
sibling event, `services/fact_safety.py` itself logs nothing — logging happens once, at the
integration boundary) are concise: `event_id`, `draft_id` (when suppression fires,
`worker/content_cycle.py`'s own `content_notification_suppressed_by_fact_safety` event), and the
`fact_safety_status` — never full article/draft text.

## 10. Files changed

Production:
- `services/fact_safety.py` (new) — pure claim extraction/normalization/classification
  (`evaluate_fact_safety`), plus the thin `apply_fact_safety()` integration function.
- `capabilities/executor.py` — 1 import + a 9-line conditional call, only for
  `step.capability == "quality"` (mirrors M4's identical `"scoring"` hook exactly).
- `core/config.py` — `fact_safety_mode` field.
- `services/content_draft_service.py` — `_fact_safety_status()` / `_draft_status_for()` helpers;
  `ContentDraft.status` now computed instead of the hardcoded literal `"draft"` (byte-identical
  result outside `enforce` mode).
- `scripts/run_content_generation.py` — `ContentGenerationOutcome` gains `fact_safety_status`
  (extracted from the already-in-scope `WorkflowRunResult`, zero extra DB query);
  `_fact_safety_status()` helper (deliberately duplicated from `content_draft_service.py`'s own,
  per this codebase's established per-module step_results-lookup-duplication convention).
- `worker/content_cycle.py` — `_fact_safety_delivery_decision()` pure helper;
  `ContentCycleResult.fact_safety_suppressed` counter; the one notification call's `dry_run` now
  computed via the helper instead of the raw setting.

Diagnostics (not part of the runtime path):
- `scripts/phase15_m5_fact_safety_backtest.py` (new) — read-only historical backtest, §12.

Tests:
- `tests/test_fact_safety.py` (new) — 76 tests, §11.

No other file was modified for M5 — in particular `capabilities/research_capability.py`,
`capabilities/intelligence_capability.py`, `capabilities/copywriting_capability.py`,
`capabilities/quality_capability.py`, every `prompts/*.yaml`, `workflows/definitions/
content_generation.py`, `workflows/runner.py`, `services/editorial_scoring.py`, and
`services/telegram_notifier.py` are all untouched.

## 11. Tests and exact results

`tests/test_fact_safety.py` — **76/76 passed**, covering: normalization unit tests for every
claim type across multiple real-world formats; extraction regression tests for all three bugs
found and fixed during development (§4); all 20 of the task's own required test cases (1–20,
including the exact Phase 14.5 defect shape as test 8, its central-entity counterpart as test 8b,
and both provenance tests 11/12); mode behavior (15/16/17 — shadow non-blocking, off passthrough
identity, enforce decision matrix); structural no-provider-call and no-cross-contamination proofs
(18/19/20); and three real integration tests driving the actual `CapabilityExecutor` +
`WorkflowRunner` path against the real `"quality"` step with a local fake capability (off-mode
byte-identical passthrough, shadow-mode enrichment + detection, and a direct proof that Research's
step_results reach the classifier with zero additional DB query) — every integration test also
asserts zero `AIExecution` rows, regardless of fact-safety mode.

Full regression suite (`python -m pytest tests/`, 1138 collected — 1062 from the Phase 15 M4.2
checkpoint + 76 new M5 tests): **1135 passed, 3 failed**, 16m17s. All 3 failures are the
identical, already-thrice-documented pre-existing `content_generation_dry_run` environment/test-
assumption mismatch (M3 checkpoint report §9, M4 report §11, M4.1 report §9) — this environment's
`.env` has it `False`; the affected tests assert the code default `True` directly, with no
monkeypatch. Confirmed unrelated to M5 by inspection: none of the 3 failing test files
(`tests/test_content_generation_integration.py`, `tests/test_content_worker_cycle.py`) reference
`fact_safety` at all, and the failure mode (a bare `assert settings.content_generation_dry_run is
True` with no fact-safety-related setup) is identical to every prior occurrence. **Zero
M5-attributable regressions.**

Static checks (this session): `ruff check` (all 8 changed/new files) — all checks passed;
`scripts/validate_architecture.py` — clean, 0 violations; `mypy` on all 6 changed/new production
files — no issues found; manual secret-pattern scan across all 8 files — zero matches.

## 12. Historical backtest

`scripts/phase15_m5_fact_safety_backtest.py`, fully read-only (no row ever mutated, no LLM call),
against every real `ContentDraft` row currently in the database.

**Sample**: 8 total `ContentDraft` rows exist in this environment — **far below the task's own
50-draft target**, reported honestly rather than padded (mirrors Phase 15 M4.2's own established
precedent for a thin sample: use what's available, mark confidence as limited). After excluding
2 Phase 13 M7/Phase 14 M6 synthetic validation-run duplicates and 1 pre-Phase-15-M1
malformed-title artifact (a raw HTML fragment as a title — exactly the class M1's gate now
prevents at ingestion), **5 clean, real drafts** remain.

**Confidence**: explicitly limited by sample size. Every finding below is a real, individually
inspected data point, not a statistically stable rate.

| | count |
|---|---|
| PASS | 1 |
| REVIEW | 2 |
| BLOCK | 2 |

By source type: RSS 1 BLOCK; NEWS_API 1 BLOCK + 1 REVIEW; TELEGRAM 1 REVIEW + 1 PASS.
By category: AI 1 BLOCK; UNKNOWN 1 BLOCK + 2 REVIEW + 1 PASS.

Severity across all findings: 2 HIGH, 1 MEDIUM, 3 LOW (post-fix — see §13 for the pre-fix numbers
these bug fixes corrected).

**The Phase 14.5 example, evidence still available**: the exact "Atoms привлёк $1,7 млрд..."
draft (`draft_id=491db283-8ea0-4719-860c-2fc02ee9ab2b`) is present in this backtest.
Evaluated against the *current* `NewsEvent.content` (which, unlike the title-only comparison
Phase 14.5's own report used, contains the full article text): the money amount ($1.7B) and the
lead investor ("Andreessen Horowitz") both come back **SUPPORTED** — the source content genuinely
does state both. Only "Uber [as investor, in a declined grammatical form]" comes back UNCERTAIN
(downgraded from a confident verdict by a real, documented limitation — Russian noun-case
declension, §5/§13), not UNSUPPORTED. **Honest finding, stated plainly**: this specific historical
draft does not currently reproduce as a confirmed "unsupported claim" catch under M5, because the
fuller evidence M5 uses (full content, not title-only) actually supports the claims that Phase
14.5's title-only comparison flagged. This is not a failure of M5 — it demonstrates exactly why
M5's evidence packet deliberately includes full `source_content`, not just the title (§3): with
richer evidence, this draft was likely never actually unsupported, only under-evidenced by the
comparison method used at the time it was first flagged.

## 13. False-positive review

Two systematic false-positive classes were found and **fixed** during this milestone (not merely
documented — code changes, §4/§5):

1. **Russian brand names in guillemets** (`«Медикейд»`, `«Палантир»`) were being extracted as
   "quote" claims and classified HIGH-severity UNSUPPORTED (since no evidence would ever contain
   an *identical* quoted span for a single proper noun in a different sentence position) — this
   single bug alone was responsible for the ICE/Palantir draft's initial (pre-fix) verdict of
   BLOCK with 4 HIGH findings, all false positives. **Fixed**: a "quote" claim now requires 2+
   words. Post-fix, that same draft correctly reads REVIEW with 1 LOW finding.
2. **A date's periods parsed as a money magnitude** (`24.07.2026` → a spurious `$24.07B`-shaped
   match when a stray "b"/"m"/"k" happened to follow in nearby text) and **single-letter money
   magnitudes matching as a prefix of an unrelated word** (`"5 bears"` → `$5B`) — both fixed at
   the regex level (§4), both covered by dedicated regression tests
   (`test_extract_claims_does_not_confuse_a_date_for_money`,
   `test_extract_claims_does_not_flag_ordinary_words_as_magnitude_prefix`).

One systematic false-positive class was found, characterized, and **deliberately not fixed** (an
honest scope decision, not an oversight):

3. **English Title-Case headline phrases mistaken for multi-word entities** — e.g. "Unifies
   Enterprise Multimodal Workflows" (from the draft title "OpenAI GPT-5.6 Unifies Enterprise
   Multimodal Workflows") was extracted as a 4-word capitalized-run "entity" and classified
   UNSUPPORTED/HIGH. This is a real, structural limitation: English headline-style Title Case
   capitalizes every word, making an ordinary headline fragment visually indistinguishable from a
   genuine multi-word proper noun using only capitalization as a signal. Fixing this properly
   would require part-of-speech awareness (a real NLP capability), which M5.2 explicitly rules
   out ("do not build a general natural-language parser... do not add a new NLP service"). Left
   as a documented, watched limitation (§17) rather than a fragile ad-hoc patch — this is exactly
   what shadow mode exists to surface before any enforcement decision is made.

A fourth, lower-severity observation: a dense, jargon-heavy arXiv-style physics-paper title
(NEWS_API source) produced more entity-extraction noise (acronyms, model-version strings) than
typical news prose — an expected consequence of the same capitalized-run heuristic applied to
non-news technical writing, not a new bug.

**10 PASS-adjacent / REVIEW / likely-false-positive sample**: given the sample's small size (5
clean drafts total), every finding from §12 is individually listed above rather than sampled —
there are fewer than 10 total findings to sample from. The one PASS draft ("Black Forest Labs
анонсировала Flux 3") had exactly 1 checked claim (the product name "Flux 3"), correctly matched
against the source and classified SUPPORTED, 0 findings.

## 14. Deployment details

Affected service: `content_worker` only — `capabilities/executor.py`'s new fact-safety hook is
gated on `step.capability == "quality"`, a step that exists exclusively in the `CONTENT_GENERATION`
workflow definition; `NEWS_ANALYSIS` (the only workflow `news_analysis_worker` runs) has no
`"quality"` step, so the hook is structurally inert there regardless of whether that image is
rebuilt. `automation_worker` (the Collector) does not import `capabilities/executor.py` at all.

Sequence performed: (1) `docker compose ps` recorded pre-deployment state — all 5 containers
already `Up`/healthy; (2) no migration exists or was needed (§8 — `ContentDraft.status` is
already free-text), so no code/schema-compatibility window needed protecting; (3) `docker compose
build content_worker` built cleanly; (4) `docker compose up -d --no-deps content_worker`
recreated only that one container — `--no-deps` left `postgres`/`redis`/every other service
untouched; (5) verified inside the running container: `settings.fact_safety_mode == "shadow"`,
`settings.editorial_scoring_version == "v1"` (unchanged), `settings.content_generation_min_score
== 65` (unchanged) — confirming the new code is live and Observation Mode's other configuration
is completely undisturbed. `automation_worker` and `news_analysis_worker` were left on their
pre-M5 images — both provably unaffected by this milestone's code, so rebuilding/restarting them
would have been an unnecessary touch of unrelated infrastructure.

## 15. Live shadow validation

**Blocked by a pre-existing, out-of-scope condition — reported honestly rather than worked
around.** Within minutes of redeployment, `content_worker` naturally picked up one real,
newly-eligible event and correctly attempted `CONTENT_GENERATION` (no manual trigger). However,
its `"research"` step failed immediately (`capability_call_failed`, no `routing_decision` log
entry at all — the call short-circuits before ever reaching the LLM Gateway's own routing engine,
consistent with a budget/rate-limit guard rejecting it pre-flight). The `"quality"` step — where
M5's own hook lives — never ran, so no natural fact-safety evaluation was observed live in this
session.

**Confirmed unrelated to M5, not worked around**: the identical failure (`required step research
failed`, same log signature, same ~10ms-fail timing, zero `routing_decision` entries) is
occurring simultaneously on `news_analysis_worker` — a container left entirely untouched by this
milestone, still running its pre-M5 image, calling the same `ResearchCapability` from an
unrelated workflow (`NEWS_ANALYSIS`). `news_analysis_worker`'s own logs show 0 successful
`NEWS_ANALYSIS` completions and 28 consecutive research failures over the prior 2 hours, dating
back to approximately 11:49 UTC the same day — well before this milestone's deployment. This is a
sustained, pre-existing provider-availability condition, not a regression this milestone
introduced, and — per the task's own explicit scope boundary ("no new provider calls"; nothing in
scope permits touching `BudgetGuard`/`CostTracker`/routing) — was not diagnosed further or
"fixed."

What *was* validated, in place of the blocked live observation:
- **Deployment health**: `content_worker` started cleanly, registered all 6 capabilities
  correctly, and attempted its one eligible event with zero worker-level errors attributable to
  M5's own code — the failure occurred one step *before* M5's hook would even run.
- **Config correctness**: confirmed live inside the container (`fact_safety_mode == "shadow"`,
  `editorial_scoring_version == "v1"`, `content_generation_min_score == 65`,
  `content_generation_dry_run == False`) — Observation Mode's configuration is completely
  undisturbed by this deployment.
- **The mechanism itself, proven end-to-end against real Postgres** (§11's integration tests):
  the exact `CapabilityExecutor` + `WorkflowRunner` path a real `"quality"` step takes was
  exercised directly, including a real database round-trip, with `AIExecution` row count
  confirmed at 0 throughout — this is the same evidentiary standard Phase 15 M4's own executor
  hook was validated against before its own first live observation, and is not a substitute
  claim: it is direct proof the wiring is correct, independent of whether a live draft happened
  to reach it during this session's observation window.
- **The historical backtest** (§12) already exercises the full evaluation logic against 5 real,
  previously-delivered drafts — a genuine (if small) sample of real production data, distinct
  from and complementary to a live *forward* observation.

Once the underlying Research-capability condition resolves (external to this milestone), shadow
mode will begin accumulating real `"fact_safety"` findings automatically — no further action or
redeployment is required, since the code is already correctly deployed and gated.

## 16. Cost/latency impact

**Provider calls: 0 added**, in every mode — proven structurally
(`test_18_fact_safety_module_imports_no_llm_gateway_or_capability`, checking only actual `import`
lines, not prose) and at runtime (every `CapabilityExecutor`/`WorkflowRunner` integration test
asserts `AIExecution` row count stays 0 regardless of `fact_safety_mode`). `ResearchCapability`'s/
`QualityCapability`'s own existing calls are completely unchanged — M5 only post-processes
Quality's *already-produced* output, never re-invokes it or any other capability.

**DB queries added**: **0** — the entire evidence packet (`NewsEvent.title`/`.content`/`.url`,
Research's completed `step_results`) is already present on `CapabilityContext` before
`apply_fact_safety()` is ever called; `capabilities/executor.py` already loaded `NewsEvent` once
per step, for its own pre-existing purposes, before M5 existed.

**Deterministic compute**: `evaluate_fact_safety()` is pure Python (regex + dict lookups) over
already-in-memory strings — on the 5-draft backtest sample, claims-checked ranged 1–9 per draft
(mean ≈ 4.2), each evaluated in well under a millisecond; not separately micro-benchmarked given
this negligible cost relative to the LLM calls already surrounding it in the same workflow.

**Memory/storage impact**: the `"fact_safety"` JSON block adds a few hundred bytes to
`EditorialTask.workflow` per CONTENT_GENERATION task (the same JSON column that already stores
every other step's result) — no new table, no new column, no migration.

**Monetary cost**: not fabricated. Zero new provider calls means zero new LLM spend, in every
mode including `enforce`.

## 17. Enforcement recommendation

**Do not activate `enforce` mode yet.** Two independent reasons, both evidence-based:

1. **Sample size**: 5 clean historical drafts is far too small to characterize false-positive
   *rate* with any confidence (§12's own explicit limitation) — only false-positive *classes*
   were identifiable, and two of the three found were code bugs (now fixed), leaving one
   structural, unfixable-without-NLP limitation (Title-Case headline entities, §13) whose
   real-world frequency is still unknown.
2. **The Title-Case entity limitation is a real, live risk under `enforce`**: it produced a HIGH
   severity finding (→ `status: "block"`) for a completely legitimate draft in this very backtest
   (§12/§13, item 1). Activating `enforce` today would risk withholding real, correct stories
   purely because their headline happens to use English Title-Case styling with 2+ consecutive
   capitalized words that don't literally appear together in the source. This is precisely the
   "a fact-safety system that blocks good stories is also unsafe" risk the task's own M5.10
   instruction warns against.

**Recommended path to a future `enforce` decision**: let shadow mode run for a meaningful window
(the same "let real data accumulate" pattern Phase 15 M4.2 already established for Editorial
Scoring V2) — specifically watching the `status`/`highest_risk`/`findings[].type` distribution
across many more real drafts than 5, to (a) get a statistically meaningful false-positive rate
for the Title-Case entity limitation specifically, and (b) confirm the Russian-declension
UNCERTAIN-not-UNSUPPORTED safety net (§5/§12) continues to behave conservatively at scale. Only
after that evidence exists should a human make the `enforce` cutover decision — mirroring Phase
15 M4/M4.1/M4.2's own repeatedly-applied "implement, backtest, shadow-validate, then decide"
discipline for Editorial Scoring V2.

## 18. Remaining limitations

- **English Title-Case headline phrases can be mistaken for multi-word entities** (§13, item 3) —
  the single most important open risk for a future `enforce` decision; no fix attempted, by
  design, given the "no general NLP parser" scope boundary.
- **Russian noun-case declension is not normalized** (§5) — a named entity can fail to
  string-match its own source mention purely due to grammatical case, downgraded to UNCERTAIN
  (never silently dropped, never falsely UNSUPPORTED) but still a real precision gap.
- **Quote attribution is not parsed** — a quote's *speaker* is never checked against evidence,
  only the quoted text's presence; M5.2's own "where detectable" qualifier was interpreted
  conservatively (detect the span, not the attribution) given the added complexity a full
  attribution parser would require.
- **The engagement-magnitude-style "unweighted sum" simplification does not apply here** (fact
  safety has no analogous aggregation step), but a comparable simplification exists in claim
  matching: money/percentage/date/quote comparisons are exact-after-normalization, never fuzzy —
  a deliberate, tested choice (M5.3: "no broad fuzzy matching that can turn unrelated claims into
  matches") that trades a small amount of recall (a claim expressed in a very unusual paraphrase
  might not match) for zero risk of a false SUPPORTED verdict.
- **Sample size for the historical backtest (5 clean drafts) is far below the task's own 50-draft
  target** — an honest, environment-driven limitation (only 8 `ContentDraft` rows exist at all in
  this database), not a shortcut taken. Every finding in §12/§13 should be read as "real evidence
  of a genuine phenomenon," not "a statistically stable rate."
- **Intelligence's own free-text fields (`angle`, `recommendation`) are not separately checked**
  for fact-shaped content — Copywriting's prompt draws primarily from Research for facts, so this
  was judged lower-priority (§2 point 6), but it is not a proven-zero risk, only an
  unencountered one in the available evidence.

## 19. Recommended manual cutover action

**No `.env` change and no `fact_safety_mode` change is recommended at this time.** The concrete,
sequenced recommendation for a human maintainer: (1) leave `fact_safety_mode` at its code default
(`"shadow"`) in production for a real observation window; (2) periodically re-run
`scripts/phase15_m5_fact_safety_backtest.py` (read-only, safe to run anytime) as more real
`ContentDraft` rows accumulate, watching specifically for the Title-Case-entity false-positive
rate; (3) only once that rate is understood at a meaningful sample size, make an explicit,
separate decision to set `fact_safety_mode=enforce` in `.env` — a one-line, no-migration,
instantly-reversible change (§8) — ideally paired with a decision on whether the Title-Case
entity heuristic needs a targeted refinement first.

## 20. Phase 15 completion status

With M5 shipped (in shadow mode) and documented, Phase 15 — Editorial Intelligence's originally
planned milestone set (per `docs/phase15_editorial_intelligence_implementation_plan.md`) is now
functionally complete end-to-end:
- **M1** (Source Quality) — deployed, active.
- **M2** (Category Reliability) — deployed, active.
- **M3** (Engagement Signal Preservation) — deployed, active, data accumulating.
- **M4/M4.1/M4.2** (Editorial Scoring V2) — implemented, calibrated, shadow-reviewed; cutover
  deliberately deferred pending more post-M3 data (Phase 15 M4.2's own recommendation, unchanged
  by this milestone).
- **M5** (Fact Safety) — implemented, backtested, deployed in shadow mode; enforcement
  deliberately deferred pending more shadow-mode evidence (§17, this report's own recommendation).

Two independent shadow-mode cutover decisions (Editorial Scoring V2 → `v2`, Fact Safety →
`enforce`) now await the same kind of human, evidence-based authorization this report and the
M4.2 report both explicitly reserve for a separate, deliberate step — neither was activated by
this or any prior Phase 15 milestone. `master` and the Phase 13–15 M3 checkpoint branch remain
untouched throughout.

---

# M5.1 RESEARCH RECOVERY AND LIVE SHADOW VALIDATION

Status: RESEARCH RECOVERED — HEALTHY. Live shadow validation completed to the extent naturally
practical within this session's window; enforcement remains blocked, for reasons unrelated to
this recovery (§11).

## 1. Research outage root cause

**Classification: A — provider-availability circuit-breaker state (a recurrence of the exact
mechanism already documented in `docs/llm_runtime_availability_recovery_report.md`), not B/C/D/E/
F/G/H/I/J.**

Durable evidence, read directly from `EditorialTask.workflow["step_results"]` for multiple
recently-`FAILED` `NEWS_ANALYSIS` tasks (e.g. `e389949e-8b29-4bf9-9d67-7145c6967e1e`):

```json
{"step_name": "research", "status": "FAILED", "attempt": 1,
 "error": "No routable candidate for capability 'unknown' (objective=best_quality)", "result": null}
```

- `attempt: 1`, `retry_count: 0` on the owning task — the failure occurred on the **first and
  only** attempt, never retried. This is the signature of a `PermanentCapabilityError`-class
  mapping (`CapabilityConfigurationError`/`NoRoutableCandidateError` → `PermanentStepFailureError`
  in `capabilities/executor.py`), not a `RetryableCapabilityError` — ruling out D (rate limit) and
  E (timeout/network), both of which map to the retryable path and would show `attempt: 2`/`3`.
- No `routing_decision` log line appears before the failure in `integrations/llm_gateway/
  routing/engine.py::RoutingEngine.route()` — the exception is raised at Step 5 of that method
  (the zero-candidate check), strictly *before* the routing-decision log statement — meaning the
  request never reached FallbackPolicy or any provider adapter at all. Ruling out B
  (authentication — that would require a request to actually reach the provider) and F
  (structured-output/schema incompatibility — same reason).
- The error string itself (`No routable candidate for capability '{criteria.capability_name}'`)
  originates from exactly one call site: `integrations/llm_gateway/routing/engine.py:109`, raised
  only when **zero candidates survive the health filter** (`ProviderHealthStore.is_healthy()`
  returning `False` for every one of the 3 catalog models).

Recent failures inspected (representative sample, both workflows):

| event_id | task_id | workflow | timestamp (UTC) | failed step | exception class | provider/model | retries | fallback attempted | final task state |
|---|---|---|---|---|---|---|---|---|---|
| 34d3a366… | e389949e-8b29… | NEWS_ANALYSIS | 2026-07-25 17:06:07 | research | `NoRoutableCandidateError` (via `PermanentStepFailureError`) | none selected — zero candidates | 0 | No — never reached FallbackPolicy | FAILED |
| ca01bfcb… | 285529e4-846a… | NEWS_ANALYSIS | 2026-07-25 17:06:07 | research | same | same | 0 | No | FAILED |
| fa9d4b8e… | a129d52f-4dc8… | CONTENT_GENERATION | 2026-07-25 16:38:09 | research | same | same | 0 | No | FAILED (workflow), `content_generation_task_failed` logged, no `ContentDraft` attempted |

## 2. Provider/runtime state

`KEYS "phase7:health:*"` (before any change): exactly 3 keys, matching the full model catalog
(`OPENAI_MODELS`, confirmed no drift — `gpt-5.6-sol`/`gpt-5.6-terra`/`gpt-5.6-luna`, all
`provider_id="openai"`), no other key pattern present.

| Key | Fields (`HGETALL`) | TTL |
|---|---|---|
| `phase7:health:openai:gpt-5.6-sol` | `runtime_unavailable=1` | `-1` (no TTL) |
| `phase7:health:openai:gpt-5.6-luna` | `runtime_unavailable=1` | `-1` (no TTL) |
| `phase7:health:openai:gpt-5.6-terra` | `runtime_unavailable=1` | `-1` (no TTL) |

**This is the exact same permanent, no-TTL circuit-breaker latch already documented** in
`docs/llm_runtime_availability_recovery_report.md` §1 — `mark_runtime_unavailable()`
(`integrations/llm_gateway/fallback/policy.py`), written on a `ProviderPermanentIncompatibleError`
or `ProviderModerationBlockedError`, with **no automatic-clear or `mark_healthy()`/`reset()`
mechanism anywhere in this codebase** (re-confirmed: no new clearing mechanism was added between
that report and now). **Yes, the previously-documented no-TTL permanent-latch mechanism has
recurred** — a second, independent occurrence of the same architectural gap, not a new class of
failure. The specific upstream trigger this time was not separately re-diagnosed (the durable
per-task record only retains the generic `NoRoutableCandidateError` message, not the original
provider exception that first set the latch — the same limitation §8 of the prior report already
disclosed); given §4's probe results, whatever it was is no longer active.

## 3. Configuration sanity (no secrets exposed)

Checked inside the live `content_worker` container:
- `OPENAI_API_KEY` configured: `True` — shape `sk-`-prefixed, length 164 (identical to the prior
  recovery's own recorded shape — no drift, no value printed).
- `enabled_providers`: `['openai']` — provider enabled.
- Model catalog (`OPENAI_MODELS`) lists exactly `gpt-5.6-sol`/`gpt-5.6-terra`/`gpt-5.6-luna`,
  `provider_id="openai"` for all three — matches the health-store keys exactly, no naming drift.
- `capabilities.capability_mapping.resolve_ai_capability("research")` → `AICapability.RESEARCH`
  — ResearchCapability's own configuration mapping resolves correctly; not disabled, not
  misconfigured.
- `integrations.llm_gateway.providers.openai_adapter.OpenAIAdapter` imports cleanly — no import-
  time error, no missing dependency.
- Redis: `PING` → `PONG`. PostgreSQL: `pg_isready` → `accepting connections`. Both healthy
  throughout — ruling out H (cache/Redis issue as the *root* cause — Redis itself was never down,
  it was correctly serving a stale-but-valid latch) and I (database/task-state issue — task state
  transitions, e.g. `FAILED` after `attempt: 1`, all behaved exactly per `workflows/runner.py`'s
  own documented contract).
- Worker code revision: `content_worker` confirmed running the M5 image (`apply_fact_safety`
  present in `capabilities/executor.py`'s loaded source); `news_analysis_worker` confirmed
  **not** running M5 code (absent) — the intended, unchanged control: this outage is observed
  identically on a container that has never had any M5 code deployed to it.

No missing environment variable, no configuration drift, and no application-level bug in
`ResearchCapability` or its mapping explains the outage (ruling out G) — every check in this
section passed.

## 4. Minimal safe probe

Used the existing `scripts/smoke_test_openai_adapter.py` (calls `OpenAIAdapter` directly,
bypassing `FallbackPolicy`/`RoutingEngine`/the Redis health store entirely — the exact same
probe, and the exact same rationale, as the prior recovery). One request per model, run inside
the live `content_worker` container (same network egress as production). No `NewsEvent`,
`EditorialTask`, or `ContentDraft` was created; no Telegram call of any kind.

| Model | Result | Token usage | Response preview |
|---|---|---|---|
| gpt-5.6-terra | **SUCCESS** | input=16, output=9 | "I'm online and ready." |
| gpt-5.6-sol | **SUCCESS** | input=16, output=7 | "I'm online." |
| gpt-5.6-luna | **SUCCESS** | input=16, output=8 | "I'm online." |

All 3 models responded successfully, normal latency (single round-trip each), zero errors of any
kind, real structured/plain completion — direct, current, first-hand evidence that the underlying
provider is healthy right now and the Redis `runtime_unavailable` latch was stale, not reflecting
current provider reality.

## 5. Recovery action

Per §4's conclusive evidence (provider healthy; Redis state proven stale) and per §2's
confirmation that manual key deletion is the *only* clearing mechanism this codebase's
health-store design provides — clearing it is the intended (if manual) recovery path, not a
workaround.

**Action taken**: re-confirmed the exact key set immediately before deletion (`KEYS
"phase7:health:*"` → the same 3 keys, no others), then:

```
DEL phase7:health:openai:gpt-5.6-sol phase7:health:openai:gpt-5.6-luna phase7:health:openai:gpt-5.6-terra
```

Confirmed after: `KEYS "phase7:health:*"` → empty. No `FLUSHDB`/`FLUSHALL`, no other Redis key
pattern touched, no PostgreSQL data touched, `.env` never written (`git status --short` showed no
change throughout this entire recovery).

**Verification, before any natural traffic**: constructed a `RoutingEngine` against the live
Redis instance and called `route()` directly with `capability_name="research"` — a pure read/
filter operation, zero network calls to any provider. Result: all 3 models returned as routable
candidates (`[('openai', 'gpt-5.6-sol'), ('openai', 'gpt-5.6-terra'), ('openai', 'gpt-5.6-luna')]`)
— before recovery this same call raised `NoRoutableCandidateError`.

## 6. Workers affected

**None restarted.** `ProviderHealthStore` reads Redis fresh on every routing call (no in-process
caching) — clearing the Redis keys took effect immediately for every worker without any restart,
rebuild, or redeploy. Confirmed: `docker compose ps` showed identical uptimes for all 5 containers
immediately before and after the key deletion (`content_worker` continuously "Up" since its
earlier M5 deployment, `news_analysis_worker`/`automation_worker`/`postgres`/`redis` all
continuously "Up" since well before this session) — this recovery action touched zero containers.

## 7. Natural pipeline recovery evidence

**No event, task, or draft was manually created or forced at any point** — every completion
below is a naturally-scheduled worker cycle picking up already-existing, already-eligible
backlog.

**NEWS_ANALYSIS**: the next natural `news_analysis_worker` cycle after recovery
(`~17:31:07 UTC`) completed multiple tasks successfully — `abe12f0b-c29a-4fb9-a5a3-c085929e9543`,
`a8ed0014-5160-4cb2-986a-95d15a281a26`, `5f1834c7-f311-48c6-8d40-cc814664af83`, and more in
subsequent cycles — each showing the normal, healthy log pattern (`routing_decision` →
`HTTP/1.1 200 OK` → `latency` → next step, repeated for all 4 steps) that was completely absent
during the outage. Durably confirmed `status = COMPLETED` for all three sampled directly from
`editorial_tasks`. **10 NEWS_ANALYSIS tasks completed in total** in the first ~40 minutes after
recovery — the first successful completions since 11:49:21 UTC the same day (a ~5h40m outage
window), with real, varied scores (12 to 68) proving genuine LLM-produced output, not a stub or
cached response.

**CONTENT_GENERATION**: one natural attempt was observed shortly before the fix took effect
(`a129d52f-4dc8…`, 16:38:09, failed with the identical `NoRoutableCandidateError` signature as
NEWS_ANALYSIS — confirming both workflows shared the exact same root cause, since they call the
identical `ResearchCapability`/routing/gateway code). After recovery, `content_worker`'s next two
natural cycles (17:38:37 and 18:08:53) both found **zero eligible events** — not a failure, a
`eligible_found=0` outcome, explained fully in §7's own continuation below (not a Research
problem).

## 7b. Why no CONTENT_GENERATION draft reached "quality" in this session's window

Investigated (read-only) rather than assumed. `worker/content_cycle.py::_select_eligible_events()`
orders its SQL candidate query by `EditorialTask.updated_at.asc()` (oldest-completed-first) and
caps it at `content_generation_scan_limit=50` rows, applying the score filter in Python only over
that capped set (this exact behavior is already documented as intentional in the function's own
docstring, predating M5). At the time of this validation: **150 `COMPLETED` `NEWS_ANALYSIS` tasks
existed within the 24-hour `CONTENT_GENERATION` freshness window**, of which 30 already have an
existing `CONTENT_GENERATION` task (excluded from re-selection), leaving 120 real candidates —
**far more than the 50-row scan cap**. The outage itself is the direct cause of this backlog
depth: `content_worker` could not successfully process *any* candidate for ~5h40m, so completed-
but-unscanned `NEWS_ANALYSIS` tasks accumulated continuously during that entire window. My 3
newly-completed, genuinely eligible (score 68, 68) events are among the *newest* ~30 of 120
candidates — sorted to the back of an oldest-first, 50-row-capped scan, and were correctly not
selected in either post-recovery cycle. This is a **pre-existing, unrelated selection-ordering
characteristic** (not a bug, not something this recovery or M5 introduced, and explicitly out of
this task's scope to change — "do not change thresholds, intervals, or batch sizes") that will
resolve on its own as the older backlog either gets selected (if its own score qualifies) or ages
out past the 24-hour window (the oldest currently-in-window task is from `2026-07-24 22:41:24`,
i.e. already ~19 hours old at the time of this check — due to age out within a few more hours of
normal operation, unassisted).

## 8. Live Fact Safety sample

**0 new live drafts reached the `"quality"` step within this session's practical validation
window**, for the reason fully explained in §7b — a pre-existing backlog/scan-ordering
interaction, not a Research-recovery or Fact-Safety problem. This is reported honestly, per the
task's own explicit "if fewer than 5 drafts naturally appear, use all available drafts and state
the sample limitation honestly" instruction — extended here to the honest case of a genuine 0 for
this specific live-forward-observation window, while still providing everything else this step
asked for:

- **Confirmed indirect evidence the mechanism will work correctly once fed a candidate**:
  `CONTENT_GENERATION`'s `"research"` step calls the exact same `ResearchCapability` class,
  through the exact same `LLMGateway`/`RoutingEngine`, as `NEWS_ANALYSIS` — already proven fully
  healthy by 10 real, successful completions (§7). There is no code-path difference between the
  two workflows' `"research"` step that could make one work and not the other.
- **The existing historical backtest remains the evidentiary base for live Fact Safety
  findings** (Fact Safety report §12, unchanged by this recovery) — 5 real, previously-delivered
  drafts, already analyzed in full, including the exact Phase 14.5 defect shape.
- No claim of live findings is fabricated to fill this section — the honest answer is zero new
  observations this session, with a fully diagnosed, non-M5 reason why.

## 9. False-positive observations

None available to observe from this session's live window (§8 — zero new drafts). No new
evidence beyond the Fact Safety report's own §13 (Russian brand-name guillemets — fixed;
digit-heavy date/money collisions — fixed; English Title-Case headline entities — documented,
unfixed, primary open risk; Russian grammatical name inflection — documented, unfixed, downgrades
to UNCERTAIN not UNSUPPORTED). No extraction rule was changed during this validation task, per
instruction — this recovery's scope was strictly the Research outage, not fact-safety
calibration.

## 10. Provider-call impact

**Zero new provider calls attributable to M5** in this recovery — confirmed by the same
structural proof already established (`test_18_fact_safety_module_imports_no_llm_gateway_or_
capability`, unchanged). The provider calls that *did* occur during this session were: (a) 3
one-shot smoke-test probes (§4, a diagnostic action explicitly authorized by this task's own Step
4, not part of any workflow), and (b) the normal, expected `ResearchCapability`/`Intelligence`/
`Scoring` calls made by 10 naturally-scheduled `NEWS_ANALYSIS` cycles recovering to their
ordinary, already-existing call pattern — no different in kind or volume from any other healthy
operating period, and in particular unaffected by `fact_safety_mode` (still `shadow`, still
zero-DB-query/zero-provider-call in that mode's own no-op path since no `"quality"` step ran in
this session's window at all — §8).

## 11. Runtime health

- `docker compose ps`: all 5 containers `Up`/healthy throughout — `content_worker` unrestarted
  since its earlier M5 deployment; `automation_worker`/`news_analysis_worker`/`postgres`/`redis`
  unrestarted since before this session. Zero containers were restarted or rebuilt by this
  recovery task.
- `fact_safety_mode`: confirmed still `"shadow"` (live, inside the running container).
- `editorial_scoring_version`: confirmed still `"v1"`.
- `.env`: confirmed unchanged throughout (`git status --short` clean for the whole session; the
  only state ever modified was the 3 Redis keys, never any file).
- `news_analysis_freshness_cutoff_hours=2.0`, `content_generation_freshness_cutoff_hours=24.0`,
  `content_generation_min_score=65`, `news_analysis_batch_size=5`,
  `content_generation_batch_size=5`, `news_analysis_poll_interval_seconds=300`,
  `content_generation_poll_interval_seconds=1800` — all confirmed unchanged, read live from the
  running container.
- No synthetic/test event entered the live flow during this session (confirmed: zero
  `news_events` rows created during this session's window matching `%synthetic%`).
- No historical row was modified — this recovery only ever wrote to Redis (3 key deletions,
  already-fully-disclosed), never to PostgreSQL.
- No manual Telegram message was sent — confirmed `content_generation_dry_run=False` (live
  sending remains configured exactly as before this session, unchanged), and zero
  `CONTENT_GENERATION` drafts were even created during this session's window (§8), so there was
  nothing for the (unmodified) notifier to send, manually or otherwise.

## 12. Remaining enforcement blockers

Unchanged from the Fact Safety report's own §17 — this recovery did not add or remove any
enforcement blocker, and did not touch `fact_safety_mode`. The two reasons `enforce` remains
not-recommended stand exactly as documented: (1) the historical backtest's 5-draft sample is too
small to characterize a false-positive *rate*, and (2) the English Title-Case-entity limitation
is a real, demonstrated risk of blocking a legitimate draft, not yet mitigated. This recovery
task's own scope explicitly excluded any fact-safety calibration change (§9) — nothing here moves
that recommendation in either direction.

## 13. Final recommendation

**Research is fully recovered and confirmed healthy** — no further diagnostic or recovery action
is needed for the outage itself. **Live Fact Safety validation on a genuinely new natural draft
remains open**, not because of any Research or Fact-Safety defect, but because of an orthogonal,
pre-existing backlog/scan-ordering condition (§7b) that this task's own scope correctly forbids
"fixing" (no threshold/batch-size/ordering changes authorized). Recommended next step for a
future session: simply re-check `content_worker`'s natural cycles after the current 120-deep
`CONTENT_GENERATION` candidate backlog has had more time to age out or clear — no code or
configuration change is needed, only the passage of normal operating time. No `.env` change, no
`fact_safety_mode` change, and no `editorial_scoring_version` change were made or are recommended
at this time.

---

PHASE 15 M5 LIVE SHADOW VALIDATION COMPLETE — ENFORCEMENT REMAINS BLOCKED
