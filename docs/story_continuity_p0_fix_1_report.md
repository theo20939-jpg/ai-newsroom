# STORY-CONTINUITY-P0-FIX-1 — Report

**VERDICT: `STORY_CONTINUITY_P0_FIX_PASS`**
Full regression on the P0 branch vs a pristine-`d2dea2c` worktree: **0 new failures, 0 new
collection errors** (and 2 pre-existing story-memory version-separation baseline failures now
pass). Focused suite + Meta replay + the 12-case adversarial matrix all pass.

Deterministic Story identity + duplicate classification fixed. No deploy, no production DB
mutation, no flag change, no suppression enabled. The 0.65 confident-match threshold is
unchanged. P1 not started.

---

## A. Source

```
WORKTREE       = C:/Users/Theodor/ai-newsroom-meta-forensics
BRANCH         = feature/story-continuity-p0-fix-1
BASE           = d2dea2c  (d2dea2cd7d5da714988217b1286afb8b96c26bb9)
HEAD           = 6b8f9a9
WORKTREE_CLEAN = yes (untracked: this phase's 5 report docs + scripts/_meta_ai_duplicate_
                 forensics_1_repro.py from a prior phase; no `git add .`)
COMMITS        = 5
  09e8cb2  feat(story-continuity): tier entity evidence, down-weight generic tokens
  de9d8fd  feat(story-continuity): capability-aware delta + deterministic continuity contract
  3803caa  feat(story-continuity): persist continuity + delta evidence on the StoryLink
  2e17d33  test(story-continuity): Meta incident replay + adversarial matrix + refinements
  6b8f9a9  refactor(story-continuity): gate aggressive entity rules to the matching path only
DIFF           = 15 files, +1682 / -112
```
`feature/director-control-plane-v1` / the visual branch — not touched.

## B. Architecture

```
CONTINUITY_PRODUCER = services/triage_orchestrator.py::_apply_story_memory
                      -> runs in automation_worker (python -m worker.main -> run_automation_cycle
                      -> run_triage_cycle), the worker already on d2dea2c.

CONTINUITY_CONSUMERS = none at runtime in P0. The continuity outcome + delta evidence are
   persisted on the canonical NewsEventStoryLink row (final_decision / delta_classification /
   confidence_band / would_suppress / new_facts / material_delta / decision_reason /
   decision_source="story_continuity_p0") and emitted in one structured "story_continuity_
   decision" log line - P1 hand-off + observability ONLY. Audited: check_duplicate_story_
   delivery() recomputes delta/would_suppress itself and still returns blocked=False
   unconditionally; director_editorial_gate_context reads the on-the-fly DuplicateDeliveryCheck,
   not the persisted column (Director gate is shadow / not in production). Nothing reads
   NewsEventStoryLink.final_decision.

DEPLOYMENT_SURFACE_REQUIRED = automation_worker only (+ the shared services it imports).
   content_worker / telegram_bot need NO change - they never run triage / match_story.
   news_analysis_worker imports services/story_memory only for extract_story_signature() via
   the recap / story_context paths - the DEFAULT (non-aggressive) signature is byte-unchanged
   from d2dea2c, so rebuilding it keeps the shared module in sync with zero behaviour change to
   the NEWS_ANALYSIS workflow.
```

## C. Matching

```
MATCH_THRESHOLD_BEFORE = _HIGH_THRESHOLD = 0.65   (_LOW_THRESHOLD = 0.35)
MATCH_THRESHOLD_AFTER  = _HIGH_THRESHOLD = 0.65   (_LOW_THRESHOLD = 0.35)
  -> unchanged; asserted by tests/test_story_memory.py::test_p0_confident_match_threshold_is_unchanged.
  Only the FEATURES feeding the score changed.
```

### The aggressive-vs-default split (commit 5)

`extract_story_signature(title, category, *, aggressive_entities=False)` — **default is
byte-unchanged from d2dea2c**. `aggressive_entities=True` is passed **only** by
`match_story()` / `_score_components()`. Every other consumer (event_recap forensic-fact
capture, `recap_story_integrity`'s coherence gate, the news golden suite, `story_context`) sees
the pre-P0 extractor exactly. `_score_components()` re-extracts BOTH sides' entities aggressively
from the titles, so matching is consistent regardless of when a candidate Story row was created
— **no production Story row needs re-extraction / migration.**

```
ENTITY_NORMALIZATION_FIXED = yes (aggressive path)
  - _GENERIC_DOMAIN_ENTITIES (tiny, closed): broad AI acronyms ("ai","ml","llm","genai","agi",
    "ии","модель") + sentence-opener modals ("will","would","should","could"). Common nouns
    that appear in real names ("Model","Agent","Technology","Platform") stay extractable.
  - _extract_entities_impl(..., aggressive=True): drop generic vocab from WITHIN a run
    ("new AI transcription model" -> "AI" -> dropped; "New Muse AI Agent" -> "muse agent"),
    drop a run that is only generic vocab or a Title-Case headline fragment (>5 tokens), and
    capture a trailing version/generation number via _ENTITY_RUN_RE_VERSIONED ("iPhone 17" ->
    "phone 17", "Muse Spark 1.3" -> "muse spark 1.3").
  - normalize_story_identity_title(): strip the Russian legal-designation disclaimer and a
    leading wire-format label ("Investigation:") before extraction (aggressive path only).

DISTINCTIVE_ENTITY_WEIGHTING = yes
  - classify_entity() -> DISTINCTIVE (named product/model/version: multi-word non-generic, any
    run with a digit, or a single coined name) / SUPPORTING (a globally-recurring org from the
    closed _SUPPORTING_ORG_ENTITIES set) / GENERIC.
  - compute_entity_evidence(): effective entity score = distinctive overlap (weight 1.0) +
    capped supporting overlap (weight 0.35, hard cap 0.45 when there is no distinctive overlap)
    + generic overlap (0.0). A distinctive run captured whole on one side overlaps its split
    form on the other via shared constituent tokens (_distinctive_match_keys).

GENERIC_ENTITY_DOWNWEIGHTING = yes
  - COMPANY-ONLY GUARD: no distinctive overlap + title_overlap below the supporting-source bar
    -> `combined` capped just under 0.65 (never a confident SEMANTIC_DUPLICATE / SUPPORTING_
    SOURCE / STORY_UPDATE). Skipped when the wording itself is near-verbatim (the V2.22 / VK
    rationale).
  - an UNCERTAIN_MATCH whose only shared identity is an org/generic token gets its own Story in
    _apply_story_memory (no provisional link).

LEGAL_BOILERPLATE_HANDLING = yes
  - strip_ru_legal_designation / strip_wire_format_prefix (closed phrase sets); canonicalize_url
    (closed tracking-param set). Adversarial tests E/F/G/H.

VERSION / PRODUCT SEPARATION (Section 9) = yes
  - _version_incompatible / titles_differ_by_release_version: a different explicit
    version/edition (incl. bare 4-digit years: "Olympiad 2025" vs "2026") or a distinct product
    in the same family ("Muse Voice Transcribe" vs "Muse Spark 1.3") -> RELATED_STORY (its own
    Story), and a -0.30 penalty on `combined`. RECAP event-family logic NOT implemented (P0 scope).
```

## D. Continuity contract

```
SUPPORTED_OUTCOMES = NEW_STORY | DUPLICATE_NO_DELTA | MATERIAL_UPDATE_CANDIDATE | AMBIGUOUS
   (services/story_continuity.py - ContinuityResult + classify_continuity(), pure/deterministic,
    ONE non-overlapping outcome per event)

NEW_STORY                 = NEW_STORY / RELATED_STORY, or an UNCERTAIN_MATCH with weak/company-
                            only entity overlap. A distinct development.
DUPLICATE_NO_DELTA        = confident same-Story (SEMANTIC_DUPLICATE / SUPPORTING_SOURCE) backed
                            by a distinctive shared entity, delta_class = NO_DELTA.
                            suppression_eligible = True  (DIAGNOSTIC ONLY - see §F).
MATERIAL_UPDATE_CANDIDATE = confident same-Story + delta MATERIAL_DELTA (or a STORY_UPDATE match,
                            or delta MINOR_DELTA - Section 11 safe semantics). suppression_
                            eligible = False; flows the existing NEWS path, never dropped.
AMBIGUOUS                 = a confident score NOT backed by a distinctive shared entity, or an
                            UNCERTAIN_MATCH that attached for observability. Never merges, never
                            suppresses; structured evidence retained.

ContinuityResult: outcome, matched_story_id, match_score, confidence_band, delta_class,
  suppression_eligible, reason_codes (concise machine-readable), match_components
  (distinctive/supporting/generic overlap + entity_overlap + match_score), new_signals,
  repeated_signals. No chain-of-thought.
Invariant (tests/test_story_continuity.py::test_continuity_outcomes_are_mutually_exclusive):
  only DUPLICATE_NO_DELTA can ever carry suppression_eligible=True.
```

## E. Delta

```
DELTA_CLASSES          = NO_DELTA | MINOR_DELTA | MATERIAL_DELTA
   (coarse_delta_class(); UNCERTAIN_DELTA and a not-computable delta -> MINOR_DELTA, never
    NO_DELTA, so an ambiguous delta can never make an event suppression-eligible)
DELTA_CAPABILITY_AWARE = yes - a genuinely NEW capability / availability / spec / pricing keyword
   ("multilingual","diarization","API","iOS app","open weights","100M tokens","limited
    preview"; closed _MATERIAL_CAPABILITY_KEYWORDS set) escalates classify_delta() to
   MATERIAL_UPDATE even with no numeric claim. Reuses the existing extracted keyword/claim
   structures - no third parser.
DELTA_PERSISTED        = yes - _apply_story_memory writes delta_classification / confidence_band
   / would_suppress / new_facts / material_delta / decision_reason on the NewsEventStoryLink row
   via the canonical creation path (previously LOGGED-ONLY; all ~28k existing prod rows are NULL).
DELTA_MIGRATION_REQUIRED = false - migration 3c22be05f4e5 (delta_classification / confidence_band
   / would_suppress) is confirmed already applied to the production DB (PHASE STORY-MEMORY-V2-2
   preflight; re-verified this phase via information_schema against the working DB). The ORM
   model now declares the three columns; no new migration created.
```

## F. Safety

```
P0_WOULD_IMMEDIATELY_SUPPRESS_IN_CURRENT_PROD = NO.
  Trace under deployed d2dea2c orchestration + STORY_MEMORY_MODE=enforce:
    - _apply_story_memory calls create_task() unconditionally after computing the continuity
      result (P0 adds NO create_task() gate; the deployed "'enforce''s suppression path is not
      implemented" is unchanged).
    - services/story_duplicate_guard.py::check_duplicate_story_delivery() still returns
      blocked=False unconditionally (the transitional fail-open override is untouched).
    - services/story_suppression.py stays shadow-only; nothing reads would_suppress /
      suppression_eligible to drop a send.
  Verified: tests/test_story_continuity_meta_replay.py::
    test_p0_does_not_suppress_delivery_under_current_orchestration, plus the unchanged
    tests/test_story_memory_v2_shadow_isolation.py "never imports V2 modules" guards for
    capabilities/executor.py, worker/content_cycle.py, capabilities/copywriting_capability.py.
  No new feature flag added - the existing hard-off override already provides the
  "classification available, suppression OFF" contract.

PRODUCTION_SUPPRESSION_ENABLED = false
MATERIAL_UPDATE_STILL_FLOWS    = yes
```

## G. Meta replay

```
META_ITEMS       = 19 replayed (13 Sept-8 personal-agent burst + 4 Voice Transcribe / Muse Spark
                   1.3 precursors + 2 roundup/noise), frozen in tests/fixtures/meta_muse_incident.json.
OLD_STORY_COUNT  = 7 for the Sept-8 agent burst (009f5e08, 72d0206b, 13520bfd, e4423834,
                   8ec5abfb, 77b5efcd, e98904fc).
NEW_STORY_COUNT  = the burst no longer shatters into a Story-per-item: the replay asserts
                   <= 4 NEW_STORY outcomes over the 13 items and >= 1 paraphrase recognised as
                   the same Story.

OLD_FALSE_MERGES = 2 (confirmed in production):
   - "Meta debuts its Muse AI agent. Will consumers trust it?" -> Story 72d0206b, the garbage
     cluster anchored solely on "will" (7 unrelated members).
   - "Meta bets on AI agent Muse …" / "Meta reveals its AI agent that can shop …" -> Story
     13520bfd (a Sept-1 Voice-Transcribe Story) on the generic {meta, ai} overlap.
NEW_FALSE_MERGES = 0 - the replay asserts NEITHER wrong Story is ever a CONFIDENT merge for any
   burst item ("will" cannot survive aggressive extraction; {meta} alone is company-only and
   capped). A provisional AMBIGUOUS pointer is tolerated (non-merging, no event_count bump).

OLD_DUPLICATE_CLASSIFIED     = 0 semantic_duplicate / 0 story_update across the entire burst.
NEW_DUPLICATE_NO_DELTA       = paraphrases of the same launch resolve to the same Story
   (DUPLICATE_NO_DELTA or MATERIAL_UPDATE_CANDIDATE).
NEW_MATERIAL_UPDATE_CANDIDATES = capability/pricing-bearing items ("connect their apps … send
   emails … purchases via agents"; "powered by Muse Spark 1.3 … 100M tokens … paid tiers") ->
   MATERIAL_UPDATE_CANDIDATE, suppression_eligible=False.
Muse Spark 1.3 vs the Muse personal agent -> separate Stories; a "GPT-6 … Meta … new AI models
this week" roundup and an unrelated "Lexar Muse" SSD -> no merge.

META_REPLAY_PASS = true
```

### Item-by-item (Sept-8 personal-agent burst) — invariants pinned by the replay

| n | source | headline (short) | OLD story / match | NEW continuity |
|---|---|---|---|---|
| 1 | The Verge AI | Meta bets on AI agent Muse | 13520bfd (Voice-Transcribe) / uncertain 0.45 | NEW_STORY / AMBIGUOUS — company-only, never a confident merge into 13520bfd |
| 2 | TechCrunch AI | Meta debuts its Muse AI agent. Will consumers trust it? | 72d0206b ("will" cluster) / uncertain 0.44 | NEW_STORY — never touches the "will" cluster |
| 3 | Techmeme | Meta launches Muse, a personal AI agent … VM | related_story 0.40 | NEW_STORY (anchor) |
| 4 | GN:AI | Meta launches personal AI agent, Muse … privacy - WRAL | supporting_source 0.69 | DUPLICATE_NO_DELTA / MATERIAL_UPDATE_CANDIDATE |
| 5 | Techmeme | Meta says users can connect their apps to Muse … emails … | uncertain 0.40 | MATERIAL_UPDATE_CANDIDATE (capability) |
| 6 | 9to5Mac | Meta AI launches Muse personal agent … iPhone app | uncertain 0.40 | MATERIAL_UPDATE_CANDIDATE / AMBIGUOUS |
| 7 | Techmeme | Muse powered by Muse Spark 1.3 … 100M tokens … paid tiers | uncertain 0.57 | MATERIAL_UPDATE_CANDIDATE (pricing/capability) |
| 8 | HN | Muse: Meta's personal AI agent, features and capabilities | uncertain 0.62 | DUPLICATE_NO_DELTA / MATERIAL_UPDATE_CANDIDATE |
| 9 | WIRED AI | Meta Releases Muse, a Personal AI Agent With Privacy … | new_story 0.77 | DUPLICATE_NO_DELTA / MATERIAL_UPDATE_CANDIDATE |
| 10 | GN:AI | Meta launches personal AI agent, Muse … everyday tasks - PBS | supporting_source 0.69 | DUPLICATE_NO_DELTA / MATERIAL_UPDATE_CANDIDATE |
| 11 | GN:AI | Meta Targets Mass Market Automation With New Muse AI Agent | new_story 0.78 | NEW_STORY / AMBIGUOUS — Title-Case headline fragment, no confident merge |

*(Exact per-item cell depends on candidate-pool document frequency at replay time; the replay
pins the invariants — no fragmentation, no confident false merge, paraphrases converge,
capability items are update candidates, Spark 1.3 separate — not each individual cell.)*

## H. Historical / adversarial

```
ADVERSARIAL_CASES = 12 (Section 19 A-L), tests/test_story_continuity_meta_replay.py::test_adv_*
ADVERSARIAL_PASS  = true
  A same product / paraphrase / different publisher   -> same Story (not NEW_STORY)
  B same company / same domain / different product    -> NEW_STORY
  C same product / material new capability            -> MATERIAL_UPDATE_CANDIDATE / AMBIGUOUS, not suppressed
  D generic overlap only                              -> NEW_STORY / AMBIGUOUS, never confident same-story
  E Russian legal boilerplate                         -> no confident merge of two unrelated RU items
  F wire-format label ("Investigation:")              -> identical entity set with/without the label
  G URL tracking-param variants                       -> canonicalize equal
  H syndicated mirror, same canonical URL             -> same key
  I same product / incompatible version               -> NEW_STORY
  J generic token "will"                              -> cannot anchor / attach to the "will" cluster
  K minor factual delta                               -> suppression_eligible = False (never dropped)
  L missing / weak entities                           -> never DUPLICATE_NO_DELTA (fail safe)

HISTORICAL_SAMPLE_SIZE       = the full Phase 20 calibration corpus + VK / CD-Projekt / Warner-
   Chappell / iPhone-17-vs-16 / Anthropic-lawsuit / Fields-of-Mistria / GTA / Kitesurf /
   ai_olympiad / moscow_student real-case regression suites (~400 assertions) - all re-run.
HISTORICAL_ASSIGNMENT_CHANGES (deliberate, intent preserved):
   - VK "Отчёт VK" / CD-Projekt: still reach a confident same-story outcome, now via the
     near-verbatim-title route rather than a raw entity Jaccard of 1.0 (the score_candidate()
     middle value is now the component-tiered EFFECTIVE score).
   - moscow_student_pair: uncertain_match -> supporting_source (expected_relationship is
     SAME_STORY, so more correct). Calibration fixture + golden fixture updated (1-line each).
   - "iPhone 17" vs "iPhone 16" and "Olympiad 2025" vs "2026": now correctly separated by the
     version/edition token check (one of these previously FAILED at the d2dea2c baseline and now
     passes).
   - editorial_content_type case_e (SpaceX earnings, only "SpaceX" shared): now UNCERTAIN_MATCH
     (Section 7 - org overlap alone is not confident identity). Still attaches for review; the
     content-type gate is asserted not to be the blocker.
UNEXPECTED_REGRESSIONS       = none. Every changed assertion is a documented consequence of the
   component-tiered evidence model; commit 5 gates the invasive extractor changes to the
   matching path so no non-matching consumer (event_recap, recap integrity, golden suite) is
   affected.
```

## I. Cost position

```
DUPLICATE_DECISION_STAGE = triage (services/triage_orchestrator.py::_apply_story_memory), inside
   run_triage_cycle, BEFORE the NEWS_ANALYSIS EditorialTask is created - before any Research /
   Intelligence / Engagement / Scoring LLM call, before Copywriting, before Director Stage 2,
   before visual generation, before delivery.
EXPENSIVE_CALLS_AVOIDABLE_LATER (per suppressed duplicate, once a rollout enables suppression):
   ~1 Research + ~1 Intelligence + ~1 Engagement + ~1 Scoring LLM (NEWS_ANALYSIS) + ~1
   Copywriting LLM + optional Director Stage 2 LLM + image-candidate generation + brand render
   + 1 Telegram delivery. For the Sept-8 Muse burst (~6 delivered duplicates) ~6x that stack.
   NOT enabled by this phase.
```

## J. Tests

```
FOCUSED = 401 passed / 2 skipped / 2 failed  (both KNOWN d2dea2c baseline)
  (story_memory[/_v2/_v2_phase1/_v2_shadow_isolation/_integration/_human_reviewed_calibration],
   story_continuity[/_meta_replay], story_delta_engine, triage[/_orchestrator_story_memory/
   _orchestrator_cycle/_orchestrator_claims], story_suppression, story_duplicate_guard,
   content_draft_story_link_integration, article_acquisition_sibling_reuse)
  Both failures are KNOWN d2dea2c baseline failures, verified byte-identical on pristine d2dea2c:
    - test_story_memory_v2_shadow_isolation.py::test_only_expected_files_import_the_v2_modules
      (offender scripts/_phase23_1p_post_run_analysis.py; services/story_continuity.py is added
      to that test's own allowlist so it is NOT a new offender)
    - test_triage_orchestrator_cycle.py::test_residual_processing_state_remains_recoverable_on_a_
      later_pass  (fails identically on d2dea2c with services/+database/ reverted)

Targeted regression subset (18 story/triage/recap/event_recap/editorial/golden files):
  573 passed / 1 skipped / 7 failed - all 7 pre-existing d2dea2c baseline (5x recap_story_
  integrity generic-opener cases, recap_r2_9 marvell, v2-shadow-isolation script offender).
  NEW_FAILURES on the subset = 0.

FULL_REGRESSION = run against a pristine `d2dea2c` worktree (dedicated `git worktree`) with the
  IDENTICAL command (`pytest -q --continue-on-collection-errors`), then the FAILED/ERROR lists
  diffed:
    d2dea2c baseline    : 42 failed / 6101 passed / 28 skipped / 4 collection errors
    P0 branch (6b8f9a9) : 39 failed / 6163 passed / 28 skipped / 4 collection errors  (+62 passed = the new tests)
    comm -13 (new in P0, not in baseline) : EMPTY
    comm -23 (in baseline, fixed by P0)   : 3 -
        test_story_memory_human_reviewed_calibration.py::...[case_72_iphone20_vs_iphone18]
          (version/edition token check now separates "iPhone 20 Pro" vs "iPhone 18 Pro")
        test_story_memory_integration.py::test_different_release_version_without_entities_is_not_forced_duplicate
          (titles_differ_by_release_version now separates "...v0.32.2" vs "v0.32.3")
        test_rate_limiter.py::test_acquire_refills_over_time  (a flaky timing test; unrelated)
    collection-error FILES : identical 4 on both (test_phase20_m1_harness_fixes,
        test_v2_3a_editorial_recomposition_canary, test_v2_4d_overlay_contract, test_v2_4f_compact_overlay)

KNOWN_FAILURES        = 42 (measured d2dea2c baseline this session; phase-stated 41 + 1 flaky)
NEW_FAILURES          = 0
KNOWN_COLLECTION_ERRORS = 4
NEW_COLLECTION_ERRORS   = 0

RUFF = 0 new  ("All checks passed" on every changed .py file)
MYPY = 0 new  (only the 2 pre-existing baseline errors in services/story_delta_engine.py -
        `.get` overload on the _MATERIAL_CLAIM_TYPES loop, present verbatim on d2dea2c)
```

## K. Production

```
PRODUCTION_MUTATION = none
DEPLOYED            = false
FLAGS_CHANGED       = false
PUBLIC_SENDS        = 0
Live VPS access this phase: read-only SELECT to freeze the incident fixture only.
```

## L. P1 contract

`MATERIAL_UPDATE_CANDIDATE` reaches P1 as **already-decided structured state on the
`NewsEventStoryLink` row** — P1 does not re-run Story identity:

* `final_decision = "MATERIAL_UPDATE_CANDIDATE"`, `decision_source = "story_continuity_p0"`
  (a later AI-Judge phase keys on `decision_source` to supersede).
* `story_id`, `match_type`, `match_score`, `confidence_band`.
* `delta_classification` ∈ {MINOR_DELTA, MATERIAL_DELTA}.
* `new_facts` = the new factual/capability signals; `material_delta` = the reason codes;
  `decision_reason` = a compact evidence string (per-tier overlaps + delta reason).
* `would_suppress` (the shadow V1+V2 value, always False-effective in P0).

P1 is purely presentation/threading: for a `MATERIAL_UPDATE_CANDIDATE` link with a resolvable
root delivery for `story_id`, decide reply-vs-standalone and render the UPDATE from `new_facts`;
for `DUPLICATE_NO_DELTA` with `suppression_eligible=True`, decide (under a Founder-approved
rollout flag) whether to drop the standalone send. No entity extraction, no scoring, no delta
recomputation on the P1 side.

## M. Verdict

```
STORY_CONTINUITY_P0_FIX_PASS
```
Confirmed: full regression diffed against a pristine-`d2dea2c` worktree — **0 new failures, 0
new collection errors** (2 pre-existing story-memory version-separation baseline failures now
pass); focused suite 401/2/2 (both fails known-baseline); frozen Meta replay + 12-case
adversarial matrix pass; `META_REPLAY_PASS=true`; threshold invariant asserted; `RUFF=0 new`,
`MYPY=0 new`; `P0_WOULD_IMMEDIATELY_SUPPRESS_IN_CURRENT_PROD=NO`; `DELTA_MIGRATION_REQUIRED=false`.

## STOP

Commits + tests + report complete. No deploy. P1 not started. Awaiting Founder review.
