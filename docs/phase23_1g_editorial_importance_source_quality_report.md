# Phase 23.1G — Editorial Importance + Source Quality + Final Text Safety

**Branch**: `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(no new commits made this phase — all work uncommitted, matching this session's established
convention pending human approval).

**Status at end of phase**: implementation + tests + offline replay + reports complete. **STOP —
waiting for human review**, per the phase's own explicit instruction. No live canary was run. No
Telegram sends. No paid calls. No worker starts. No `.env` changes. No image behavior enabled.

---

## 1. Root causes from the Phase 23.1F live canary

Human review of the 5 real Phase 23.1F Telegram deliveries surfaced four concrete problems, each
independently investigated this phase:

1. **Low-importance stories were delivered at full length regardless of how weak the underlying
   story was.** The virus/bacteria story (Intelligence significance 3/10, evidence
   `HEADLINE_ONLY`) and the ghost-particles story (same profile) were both sent as full ~1000-1400
   character posts — no different in length from the strongest story in the batch.
2. **Weak/poorly-verified sources could still produce large editorial posts.** Neither source
   reliability nor evidence-acquisition status (`NewsEventArticleAcquisition.
   effective_completeness_status`, already populated in shadow mode) had any effect on delivery.
3. **Hedge/uncertainty language repeated across multiple V6 sections of the same post.** Phase
   23.1E's hedge budget applied only to *optional* sections, leaving `opening` and other core
   sections free to independently restate the same caution, and used a flat marker list rather
   than recognizing that many differently-worded sentences express the *same* underlying doubt.
4. **A pasted live sample appeared to show Stack Overflow text after an unrelated virus story.**
   Investigated as a **blocking** item before any other work (see §8) — verdict: **not a system
   defect**. Explained fully below.

## 2. Treatment architecture

New module: `services/editorial_treatment.py`. A pure decision function, not a new service, not
a new AI capability, no new database table. Its only export of consequence is
`classify_editorial_treatment()` (and the convenience wrapper
`treatment_from_intelligence_and_evidence()`, which reads directly from the existing
Intelligence/Scoring step-result dicts already produced by the workflow). Returns an
`EditorialTreatmentDecision(treatment, human_review_required, reason)` — one of
`SKIP`/`BRIEF`/`STANDARD`/`MAJOR`, a boolean review flag, and a human-readable audit reason
string (always non-empty for SKIP).

`services/news_telegram_presentation.py`'s `build_compact_news_body()` now accepts a `treatment`
parameter that controls the paragraph cap (`BRIEF=2, STANDARD=3, MAJOR=6`) and the global
hedge-family cap (`BRIEF=1, STANDARD=1, MAJOR=2`) used when assembling the final text. Nothing
about *how* a paragraph is selected/filtered changed with treatment — only *how many* survive and
*how much* repeated hedging is tolerated.

**Not wired into the live delivery path this phase** (`worker/content_cycle.py`'s router branch
still calls `build_compact_news_body(outcome.copywriting_output)` with no `treatment` argument,
defaulting to `STANDARD`) — a deliberate scope decision. Wiring SKIP/BRIEF/MAJOR into live
delivery, and therefore changing what actually gets sent to Telegram, is Phase 23.1H's job, after
this offline design is reviewed and approved.

## 3. Exact deterministic decision rules

All thresholds live as named constants at the top of `services/editorial_treatment.py`, chosen
from the phase brief's own worked examples and validated against the 5 real Phase 23.1F events
(§13/§16 below).

```
_WEAK_COMPLETENESS_STATUSES = {HEADLINE_ONLY, PARTIAL_TEXT}     # FETCH_FAILED excluded, see §4
_WEAK_SOURCE_RELIABILITY_MAX = 0.7                                # fallback only, no acquisition row
_VERY_LOW_SIGNIFICANCE_MAX = 3.0
_LOW_SIGNIFICANCE_MAX = 5.0
_MEDIUM_SIGNIFICANCE_MAX = 7.0
_HIGH_SIGNIFICANCE_MIN = 8.0
_STRONG_COMPENSATING_SCORE_MIN = 85                               # Scoring capability's 0-100 score
```

Decision order (first match wins):

1. **Weak evidence AND a negative Intelligence recommendation** → `SKIP`, unconditionally,
   regardless of significance tier. (This is the rule that fires for the virus and ghost-particle
   stories.)
2. **Significance missing/unparseable** → `BRIEF`, `human_review_required=True` — a conservative
   default, never a silent full-length publish and never a silent drop.
3. **Very low significance (≤3)**: weak evidence → `SKIP` unless a strong compensating Scoring
   signal (≥85) is present, in which case → `BRIEF` + review flag. Otherwise → `BRIEF` (review
   flag set only if the recommendation itself was negative).
4. **Low significance (≤5)** → `BRIEF`.
5. **Medium significance (≤7)** → `STANDARD`, or `BRIEF` if evidence is weak.
6. **High significance (≥8)**: weak evidence → `STANDARD` (downgraded from MAJOR, review flag
   set); otherwise → `MAJOR`.

This directly implements §6's example rules verbatim ("very low Intelligence + weak
source/evidence → SKIP"; "very low Intelligence + strong compensating signal → BRIEF + review
flag") without inventing anything beyond what the brief specified, and composes only real,
already-produced signals (§5).

## 4. Source/evidence quality rule

`_is_weak_evidence(evidence_completeness, source_reliability)`: `evidence_completeness` (from
`NewsEventArticleAcquisition.effective_completeness_status`, already populated via
`article_acquisition_mode=shadow`, which is active in real settings) is authoritative whenever an
acquisition row exists. `HEADLINE_ONLY`/`PARTIAL_TEXT` count as weak; `FULL_TEXT` does not.
`NewsSource.reliability_score` (below 0.7) is used **only as a fallback** when no acquisition row
exists at all (e.g. a Telegram-sourced event, which never runs article acquisition).

**`FETCH_FAILED` is deliberately excluded from the weak set.** Initial implementation included it;
validating against real data caught this as a real bug (§ Errors below) — `FETCH_FAILED` means an
*attempted upgrade* to the full article failed, not that the original NewsEvent's own
title/excerpt content is thin. The Amazon/Gilroy story (`FETCH_FAILED`, independently rated the
single strongest post in the Phase 23.1F batch by manual review) confirms this: it correctly
lands at `STANDARD` (driven by its significance=7), not downgraded for weak evidence.

## 5. Intelligence integration

Phase 23.1F's live proof showed Intelligence scoring a story 3/10 with recommendation "do not
publish," yet the story was still delivered — advisory only. This phase makes that signal load-
bearing, but not a blind universal gate: the negative-recommendation check
(`_is_negative_recommendation()`, keyword-matched against both Russian and English phrasings —
"не публиковать", "не рекомендуется публиковать", "do not publish", etc.) only produces a `SKIP`
when *combined with* weak evidence (rule 1 above). A negative recommendation with strong evidence
does not skip. A very-low significance with a strong compensating Scoring signal does not skip
either — it downgrades to `BRIEF` with a review flag instead, so a human can look at it rather
than either force-publishing or silently dropping it.

## 6. SKIP/BRIEF/STANDARD/MAJOR semantics (as implemented)

- **SKIP**: no Telegram message is produced. The decision and its reason string are always
  available for audit/logging (`EditorialTreatmentDecision.reason` is guaranteed non-empty for
  SKIP). The underlying `NewsEvent` row is never touched or deleted — only the delivery step is
  a no-op.
- **BRIEF**: `_MAX_PARAGRAPHS_BY_TREATMENT[BRIEF] = 2`, `_MAX_HEDGE_FAMILIES_BY_TREATMENT[BRIEF] =
  1`. In practice this yields the opening fact plus one context/why-it-matters paragraph, with at
  most one hedge-family statement surviving anywhere in the text.
- **STANDARD**: 3-paragraph cap, 1 hedge family. Main fact + context + a third paragraph only if
  it clears the redundancy filter (`_is_distinct`, token-overlap threshold 0.5).
- **MAJOR**: 6-paragraph cap (effectively "keep everything the V6 output produced, after
  filler/redundancy/hedge filtering"), 2 hedge families — allows a genuinely material second
  caveat to survive alongside the primary one, per the brief's "do not automatically make every
  high-scoring story long" instruction: MAJOR does not synthesize extra length, it just removes a
  lower floor. The Stack Overflow item (§16) demonstrates this directly — MAJOR treatment left it
  byte-identical to its original V6 output because nothing needed trimming.

Paragraph selection is never blind character-cutting (§4 of the brief): treatment only changes
which structured V6 fields (`opening`/`why_it_matters`/`what_changed`/`context`/
`what_happens_next`/`conclusion`/caveat) are kept, each field kept or dropped whole, never sliced
mid-sentence.

## 7. Hedge hardening V2

Replaced Phase 23.1E's flat `_HEDGE_MARKERS` list and per-optional-section-only budget with:

- **`_HEDGE_FAMILIES`**: 6 named semantic categories (`undisclosed`, `insufficient_evidence`,
  `unconfirmed`, `requires_verification`, `ambiguous_reference`, `signal_not_result`), each
  containing multiple differently-worded Russian/English phrasings that express the *same*
  underlying doubt (matching every example family named in the brief: "не подтверждено",
  "данных недостаточно", "требует дополнительной проверки", "нет независимого подтверждения",
  "неясно, идет ли речь", "это только заявление").
- **A global cap**, applied across *every* candidate paragraph including core sections (not just
  optional ones): `_apply_hedge_cap()` keeps only the first occurrence per family and drops later
  occurrences of an already-claimed family, up to `_MAX_HEDGE_FAMILIES_BY_TREATMENT[treatment]`
  (1 for BRIEF/STANDARD, 2 for MAJOR — matching §8's "DEFAULT 0... ORDINARY MAX 1... only MAJOR
  stories with genuinely different material caveats may exceed 1").
- A material caveat (`what_remains_unknown`, when it names something concrete — price, deal
  status, a rumor/leak, a disputed claim) is tracked separately from the core paragraphs
  (`_candidate_caveat()`) and is guaranteed a reserved slot so it is never silently dropped purely
  because of construction order (see Errors §d below — this was a real bug caught by testing).

Validated directly against the real virus story: 1430 chars (5 sections, effectively all
expressing the same "not yet confirmed" doubt in different words) → 835 chars STANDARD / 488
chars BRIEF, with exactly one hedge statement surviving in each.

## 8. Cross-draft mixing investigation — BLOCKING, resolved first

**Verdict: A — COPY_PASTE_ONLY, no system defect.**

Investigated using the real, persisted Phase 23.1F `ContentDraft` rows and Telegram send records
(`scripts/_phase23_1g_cross_draft_check.json`), before any other Phase 23.1G work began, per the
brief's explicit "STOP all other work" instruction if a real defect were found.

Evidence:
- All 5 Phase 23.1F events have distinct `event_id`/`task_id`/`content_draft_id` — no row reuse
  anywhere in the persisted data.
- Programmatic scan of every persisted `ContentDraft.body` found zero cross-contamination — no
  draft's body contains a title fragment or sentence from any other draft.
- Programmatic scan of the actual sent Telegram texts (the 5 real recorded sends) found the same:
  each message contains exactly one story's own title and body, nothing from another story.

The human-observed "virus story immediately followed by Stack Overflow text" was explained by
these being two genuinely correct, independently-sent, consecutive Telegram messages (send index
0 and 1 in the Phase 23.1F recorded sends) — pasting two adjacent real messages together into one
clipboard block looks identical to cross-contamination without any code defect existing. No fix
was needed; work proceeded to the rest of the phase.

## 9. Source button regression check

`bot/keyboards/image_preview.py::build_source_only_keyboard()` and its Phase 23.1E integration in
`worker/content_cycle.py` (real source URL preserved, `[🔗 Источник]` inline button, no raw URL in
body, safe fallback when a URL is missing) are **untouched this phase**. `build_compact_news_body`
was extended with a new optional `treatment` parameter that defaults to `STANDARD` — the exact
same value it always implicitly used before this phase — so every existing caller (including
`worker/content_cycle.py`'s router branch) is byte-for-byte unaffected unless it's updated to pass
a different treatment. No regression.

## 10. Current image/media state (investigation only — no changes made)

- `settings.image_editorial_preview_enabled = True`, `settings.image_candidate_persistence_mode =
  "finalists"` in the real current environment — image discovery is architecturally active.
- **Why no image appeared in the Phase 23.1F live canary**: that canary ran with
  `editorial_delivery_mode = "router"` (confirmed from `docs/
  phase23_1f_5_news_editorial_canary_report.md`). In `worker/content_cycle.py`, the router branch
  is checked **first** and is unconditionally hardcoded to the Phase 23.1A/23.1E card-render path
  (`to_editorial_card` + `build_compact_news_body` + `render_editorial_card`), which has no
  image-preview capability at all. The `elif image_editorial_preview_enabled and
  image_candidate_persistence_mode != "off":` branch that *would* attach an image is structurally
  unreachable whenever router mode is active — regardless of whether eligible image candidates
  exist. This fully explains the absence of images in that canary; it is not a bug.
- **Did image discovery actually run for the 5 real Phase 23.1F stories?** Yes, for 3 of 5 —
  queried directly against `ImageCandidateRecord` (`scripts/_phase23_1g_image_state.json`):
  - Stack Overflow: 0 candidates found.
  - Virus/bacteria story: 2 candidates found, both `relevance_status=ineligible`.
  - Ghost particles: 2 candidates found, both `relevance_status=ineligible`.
  - Israeli startup: 4 candidates found — 2 ranked (rank 2, 3), `eligible_for_editorial=true`,
    `quality_status=review` (flagged, not auto-accepted), `storage_status=stored`.
  - Amazon/Gilroy: 0 candidates found.
- Only one of the 5 real stories (Israeli startup) had any eligible, stored candidates ready to
  attach — and even those were flagged `review` rather than `accepted` by the quality gate.
- **No image-related code or settings were modified this phase**, per the explicit out-of-scope
  instruction. This section is investigation/documentation only.

## 11. Files changed this phase

**New**:
- `services/editorial_treatment.py` — SKIP/BRIEF/STANDARD/MAJOR decision engine.
- `tests/test_editorial_treatment.py` — 12 tests (cases A-F + significance normalization edge
  cases).
- `docs/phase23_1g_editorial_treatment_review.md` — human review packet (§17 of the brief).
- `docs/phase23_1g_editorial_importance_source_quality_report.md` — this report.
- Scratch/investigation files under `scripts/_phase23_1g_*` (read-only query scripts and their
  JSON/text outputs — not part of the shipped system, kept for audit trail per this session's
  established convention).

**Modified**:
- `services/news_telegram_presentation.py` — restructured hedge handling (named families +
  global cap replacing the flat per-section marker list), added generic low-information paragraph
  filtering, added the `treatment` parameter to `build_compact_news_body()`, separated caveat
  selection from core-paragraph selection to guarantee it survives truncation when it clears the
  hedge cap.
- `tests/test_news_telegram_presentation.py` — extended with 3 new tests (5-section hedge
  collapse, material caveat survival alongside the hedge cap, cross-draft isolation proof); one
  pre-existing test (Case F) updated to explicitly pass `treatment=MAJOR`, matching its own
  stated intent.

**Not modified** (investigated only, confirmed compatible/unaffected): `worker/content_cycle.py`,
`bot/keyboards/image_preview.py`, `database/models/news_source.py`,
`database/models/news_event_article_acquisition.py`, `prompts/intelligence/v2.yaml`,
`core/config.py`.

## 12. Tests

**New/extended test files, isolated run**: `tests/test_editorial_treatment.py` (12 tests) +
`tests/test_news_telegram_presentation.py` (14 tests) — **26/26 passing**.

**Full named regression suite** (per §18's required list — scoring/triage, intelligence
integration, ContentDraft, V6 Copywriting, Fact Safety, NEWS presentation, Telegram
routing/notifier, Phase 20 Story Memory, Phase 21, Phase 22/23 editorial planning/delivery-mode),
48 test files run in 5 batches (the full set together exceeds this tool's per-call timeout; batch
4 alone legitimately takes ~23 minutes against the real DB — not a hang):

| Batch | Files | Result |
|---|---|---|
| Scoring/triage core | `test_scoring_capability(_retry)`, `test_triage` | 37 passed |
| ContentDraft/Copywriting/delivery-mode | `test_capability_executor_image_intelligence`, `test_content_draft_*` (3 files), `test_content_worker_cycle_image_preview`, `test_copywriting_*` (3 files), `test_editorial_delivery_mode` | 83 passed, 3 skipped, **2 failed, 9 errors — pre-existing, see below** |
| Fact Safety / image preview / NEWS presentation / intelligence | `test_fact_safety(_calibration/_v6_compatibility)`, `test_image_preview_*` (4 files), `test_intelligence_capability`, `test_news_source_button`, `test_news_telegram_presentation` | 181 passed, **2 failed — pre-existing, see below** |
| Research/Source Intelligence/Story Memory/Delta | `test_phase9_research_intelligence_integration`, `test_source_intelligence*` (4 files), `test_story_delta_engine`, `test_story_memory(_human_reviewed_calibration/_integration)` | 96 passed |
| Story Memory V2 / Telegram notifier / Triage orchestrator | `test_story_memory_v2(_shadow_isolation)`, `test_telegram_notifier`, `test_triage_orchestrator_*` (3 files) | 72 passed, 1 skipped |
| Editorial Planning (Phase 19) / Phase 20 harness / Suppression | `test_editorial_plan*` (5 files), `test_phase19_m3_editorial_plan_comparison`, `test_phase20_m1_harness_fixes`, `test_story_suppression` | 110 passed |

**Total: 579 passed, 4 skipped, 4 failed, 9 errors.**

All 4 failures and all 9 errors were **confirmed pre-existing** by re-running the exact same
failing tests with every Phase 23.1G change stashed (`git stash -u`) — identical failures occur
with none of this phase's code present, then Phase 23.1G work was restored (`git stash pop`) and
confirmed intact. Two distinct pre-existing root causes, both already known from prior phases in
this session:
- `test_content_draft_service.py::test_content_draft_is_durable_to_a_genuinely_independent_connection`
  and cascading `content_worker_cycle_image_preview`/`editorial_delivery_mode` errors: the
  long-standing shared-DB FK-violation-on-teardown pattern
  (`content_draft_editorial_plans_event_id_fkey`) plus one test
  (`test_image_preview_disabled_by_default_uses_the_text_only_card`) that hardcodes an assumption
  the real `.env`'s `image_editorial_preview_enabled=True` no longer satisfies — an environment
  fact unrelated to any code in this phase.
- `test_fact_safety.py::test_off_mode_leaves_quality_step_result_completely_unchanged` and
  `test_shadow_mode_enriches_quality_result_and_detects_unsupported_claim`: the accumulated
  `AIExecution` row-count pollution in the shared real DB, also previously confirmed in earlier
  phases of this session.

**Ruff**: new/modified Phase 23.1G files (`services/editorial_treatment.py`,
`services/news_telegram_presentation.py`, both test files) — clean, zero issues. Repository-wide
scan found 6 pre-existing issues, all in old, untouched scratch scripts from prior phases
(`scripts/_phase20_build_m12_packet.py`, `scripts/_phase23_0b_routing_smoke_test.py`,
`scripts/phase17_m0_output_quality_audit.py`) — not introduced this phase.

**Mypy**: `services/editorial_treatment.py` + `services/news_telegram_presentation.py` — clean,
zero issues (one real variance error caught and fixed during development — see Known Limitations/
Errors below).

**Architecture validation**: no dedicated "architecture validation" script/command exists in this
repository (consistent with every prior phase's own disclosure of this). The closest equivalent
this phase is the new AST-based cross-draft isolation test
(`test_two_distinct_drafts_never_leak_into_each_other` in `tests/
test_news_telegram_presentation.py`), which passes — see §12's isolated test-file run above.

No paid LLM calls were made by any test. No real Telegram sends. No workers were started.

## 13. Live-item BEFORE/AFTER (offline replay of Phase 23.1F data)

Full detail with source titles, scoring, Intelligence data, and complete before/after text is in
`docs/phase23_1g_editorial_treatment_review.md`. Summary:

| Item | Significance | Evidence | Treatment | Before → After |
|---|---|---|---|---|
| Stack Overflow read-only | 8 | *(none, reliability 0.78)* | MAJOR | 1318 → 1318 (unchanged — no hedge language existed to collapse) |
| AI viruses vs. bacteria | 3 | HEADLINE_ONLY | **SKIP** | 1430 → 0 |
| Ghost particles | 3 | HEADLINE_ONLY | **SKIP** | 1015 → 0 |
| Israeli startup / AI hacks | 7 | FULL_TEXT | STANDARD | 1302 → 730 (−44%) |
| Amazon / Gilroy | 7 | FETCH_FAILED | STANDARD | 824 → 678 (−18%) |

This matches the hypotheses given in the brief closely: ghost particles and the virus story (the
two weakest, evidence-thin items) both land on SKIP; Stack Overflow (strong evidence, high
significance) lands on the top tier; none of the outcomes were hardcoded — every decision was
computed from the real persisted signals for each event.

## 14. Known limitations

- Treatment is **not yet wired into the live delivery path** — `worker/content_cycle.py` still
  defaults every router-mode send to `STANDARD`. This is deliberate (Phase 23.1H's job), but it
  means today's live behavior is unchanged until that wiring happens.
- The SKIP/BRIEF boundary for a *missing* significance value is conservative (`BRIEF` +
  mandatory human review) rather than a hard SKIP — this trades a small risk of an occasional
  weak post surviving review for the certainty that a pipeline gap (missing Intelligence output)
  never silently drops a story with no trace.
- `_STRONG_COMPENSATING_SCORE_MIN = 85` and the hedge-family lists are reasoned starting points
  validated against this session's one real 5-story sample, not a large calibration set — like
  every threshold introduced earlier in this project, they should be expected to move once more
  real data exists.
- Russian morphological variants of hedge phrasing beyond the ones explicitly named in the brief
  are not exhaustively covered — the family lists are deliberately conservative (a few concrete
  phrasings each) rather than an attempt at full lexical coverage, to avoid over-matching and
  accidentally treating a non-hedge sentence as one.
- The BRIEF tier was not exercised by any of the 5 real replayed items (real significance scores
  in this batch were either ≤3 with weak evidence, routed to SKIP, or 7-8, routed to
  STANDARD/MAJOR) — its behavior is covered by the synthetic CASE C unit test only, not by a real
  example in this report.

### Errors caught and fixed during development

- **`FETCH_FAILED` initially misclassified as weak evidence** — caught by validating against the
  real Amazon/Gilroy event (independently rated the strongest post in the batch, yet would have
  been wrongly downgraded). Fixed by excluding `FETCH_FAILED` from the weak-evidence set (§4).
- **Mypy list-variance error** in `build_compact_news_body` — `list[str] + [caveat_or_None]`
  produced `list[str | None]`. Fixed with an explicit `list[str]` + conditional `.append()`.
- **Material caveat could be silently truncated by the paragraph-count cap** — because it was
  constructed last in the candidate list, a flat `[:max_paragraphs]` slice could cut it off even
  after it had correctly survived the hedge-family cap. Fixed by reserving a guaranteed slot for
  the caveat, truncating only the non-caveat paragraphs to `max_paragraphs - 1` when a caveat is
  present.

## 15. Recommendation for next live canary

This phase's implementation, offline replay, and both review documents are ready for human
review. Per the phase's own explicit instruction: **STOP here. Wait for approval.**

If approved, the recommended next step is exactly as specified: **Phase 23.1H — 5-NEWS TEXT +
IMAGE CANARY**, which would (a) wire `EditorialNewsTreatment` into the live router delivery path
so SKIP/BRIEF/STANDARD/MAJOR actually govern what gets sent, (b) enable the already-built image
path in a controlled way, (c) send 5 real NEWS items, (d) verify treatment-based length, source
button, and image quality end-to-end, and (e) use the outcome to decide VPS readiness. Given this
phase's finding that only 1 of the 5 real replayed stories had any eligible stored image
candidate at all (and even that one was flagged `review`, not `accepted`), Phase 23.1H's live
sample should be watched for how often a real story actually has an image to attach versus
sending text-only — that ratio is currently unknown from live data and worth measuring rather
than assuming.
