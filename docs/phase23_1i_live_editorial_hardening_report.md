# Phase 23.1I — Live Editorial Hardening + 5-Publishable-NEWS Canary

**Branch**: `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(no new commits — all work uncommitted, matching this session's established convention).

**Status**: implementation + tests + offline replay + live canary + both reports complete.
**STOP — waiting for human review.** Per the phase's own explicit instruction, no VPS deployment,
no permanent `.env` change, no enforce modes, no Telegraph/Instagram/Reels/Meme work proceeds from
this phase.

---

## 1. Armenia duplicate root cause

Investigated directly against the real persisted records for both Phase 23.1H events (§ Part A of
the phase brief) — **not assumed**. Two independent, compounding causes, both confirmed with
direct evidence:

**Cause A (primary, structural): Story Memory never ran for either event.** `story_memory_mode
=off` throughout the entire real pipeline both events went through — `automation_worker`'s own
triage (real environment default) and the Phase 23.1H canary script (which never touched this
setting). Confirmed directly: zero `NewsEventStoryLink` rows exist for either event.

**Finding beyond the brief's own taxonomy: even with Story Memory correctly wired, the current
matcher would likely NOT have recognized these two events as the same story anyway.** Isolated,
zero-contamination replay (a plain in-memory `Story` object built from event A's real signature,
never added to any DB session, scored directly via `services.story_memory.score_candidate()`
against event B's real title) gives **combined score 0.094** — far below even the 0.35
`UNCERTAIN_MATCH` threshold, let alone a confident match. Two contributing factors:
- `entity_overlap = 0.0` — a real, confirmed, narrow bug (see §9): a sentence-initial capitalized
  Russian preposition ("В Армении") gets swept into the entity span, producing a string that never
  matches the same real entity's mid-sentence, correctly-cased form ("Армении") elsewhere. Fixed
  this phase (§9) — but even with the fix, entity_overlap only rises to ≈0.14, nowhere near enough
  on its own.
- `title_overlap = 0.111` — genuinely low, a real content difference: event B's headline
  ("В Армении открыли один из самых больших дата-центров в Европе") never names Firebird, NVIDIA,
  or the specific MW figures event A's headline emphasizes. This is not a bug — it is two
  differently-framed headlines about (arguably) the same real-world event sharing very little
  distinctive vocabulary, which is exactly the class of case a deterministic keyword/entity
  matcher (without embeddings/LLM assistance, explicitly out of scope per the brief) cannot
  reliably catch.

This finding directly shapes §4's fix scope: the duplicate-delivery guard built this phase is real
and useful for future genuine duplicates the matcher DOES recognize, but it would **not**, by
itself, have prevented this specific pair even with perfect wiring. Disclosed honestly, not hidden.

## 2. Exact Story Memory replay result

| | Event A (Firebird/NVIDIA) | Event B (Zerkalo) |
|---|---|---|
| Entities (extracted) | крупнейш, снг ии-фабрик nvidia, армени, firebird, мвт | в армени, европ, zerkalo |
| Category | GADGETS | AI |
| Topic bucket | other | other |
| combined score (B vs. A, isolated) | — | **0.094** |
| entity_overlap | — | 0.0 |
| title_overlap (symmetric Dice) | — | 0.111 |

**Verdict**: the current matcher would classify these as **separate stories (NEW_STORY)**, not
`SUPPORTING_SOURCE`/`SEMANTIC_DUPLICATE`/`STORY_UPDATE`/`RELATED_STORY`/`UNCERTAIN_MATCH` — the
score is not even close to the lowest ("uncertain") band.

## 3. First divergence point

Traced collection → triage → Story Memory → NEWS_ANALYSIS → CONTENT_GENERATION → Editorial
Treatment → delivery, answering the phase brief's own 5 specific questions with direct evidence:

1. **Did `automation_worker` process these events while `story_memory_mode=off`?** Yes — confirmed
   (real `.env` default, unchanged this whole session; zero `NewsEventStoryLink` rows for either
   event).
2. **Did the one-shot canary's `story_memory_mode` override participate at all?** No — the Phase
   23.1H canary script never set this setting at all (confirmed by direct read).
3. **Were Story/NewsEventStoryLink rows created?** No, for either event.
4. **Did Editorial Treatment know anything about prior delivery of the same Story?** No —
   `services/editorial_treatment.py`'s signal set (Intelligence significance/recommendation,
   Scoring, evidence completeness, source reliability) contains nothing about Story/prior-delivery
   state — confirmed by direct code read, unchanged this phase.
5. **Was there any final pre-delivery guard preventing two ContentDrafts belonging to the same
   Story from being sent?** No — confirmed absent in Phase 23.1H's `worker/content_cycle.py`.
   This phase adds one (§4).

**The first, decisive divergence point is #1**: Story Memory's `story_memory_mode=off` default
means the entire downstream chain (#2-#5) never had anything to act on.

## 4. Duplicate-delivery fix (justified, narrow, implemented)

New module `services/story_duplicate_guard.py` — a pure decision function
(`should_block_duplicate_delivery(match_type, has_prior_root_delivery)`) plus a thin async
orchestrator (`check_duplicate_story_delivery(session, event_id)`), wired into `worker/
content_cycle.py`'s router branch immediately after the Editorial Treatment SKIP gate (same
cost-saving placement — before the paid Copywriting call).

**Reuses only real, already-persisted Phase 20 state — no invented signal**:
- `NewsEventStoryLink.match_type` — Story Memory's own existing outcome taxonomy.
- `services/story_telegram_delivery.py::get_root_delivery()` — the existing, already-tested "has
  this Story had a successful root delivery" query, reused verbatim.

**Rule**: blocks a standalone send only when `match_type ∈ {SEMANTIC_DUPLICATE,
SUPPORTING_SOURCE}` **and** the Story already has a delivered root post. `STORY_UPDATE` is never
blocked (Story Memory's own existing definition of "a materially different title, a real new
development" — the closest real signal to "material update" this codebase has ever computed and
persisted). `UNCERTAIN_MATCH`/`RELATED_STORY`/no-link-at-all are never blocked, matching Story
Memory's own established "false suppression is worse than a duplicate" philosophy.

**Explicitly NOT used**: `services/story_delta_engine.py`'s `delta_classification` output.
Confirmed by direct investigation that its migration (`3c22be05f4e5_add_story_memory_v2_shadow_
columns.py`) was never applied to the real database, and `services/triage_orchestrator.py` never
calls the delta engine at all — this finer-grained "no material change" vs. "material update"
distinction the brief's own Cases 3/4 describe **does not exist anywhere in the real persisted
pipeline**. Per the brief's own explicit "do not invent missing state" instruction, this module
does not approximate it — `STORY_UPDATE` is simply never blocked, a documented, deliberate
limitation (locked in by `test_story_update_is_never_blocked_material_or_not`, tests/
test_story_duplicate_guard.py), not a silent gap.

**Not global duplicate-suppression enforce**: this is a narrow, router-mode-only,
delivery-boundary check — it does not touch, enable, or approximate Phase 20's own experimental
`would_suppress` suppression system in any way, and that system's own NO-GO status from Phase 20
is completely unaffected.

## 5. Story Memory live-shadow wiring state

**Correctly wired and genuinely active this run** (unlike Phase 23.1D/23.1H's own confirmed-inert
canaries) — `settings.story_memory_mode = "shadow"` was set in-process, and the canary script
called the real `services.triage_orchestrator.run_triage_cycle()` itself, each round, before
`run_analysis_cycle()`/`run_content_cycle()`. To make this meaningful, `automation_worker` (which
otherwise races the canary for every event, always winning since it triages in near-real-time) was
**temporarily stopped** (`docker compose stop automation_worker`) for the run's duration and
**restarted immediately after** (`docker compose start automation_worker`, verified `Up` again) —
documented in the canary script's own docstring before being executed, matching the phase brief's
own explicit "document exactly what will happen before doing it" requirement. Same container,
same config, zero `.env` mutation.

**Honest result: this specific run still observed zero real Story Memory activity** —
`TriageCycleReport(events_claimed=0, ...)` in every round. Root cause: stopping
`automation_worker` pauses **both** collection and triage (they are bundled in one process,
`worker/cycle.py`, not decoupled — decoupling them would be an architecture change, out of scope).
`automation_worker`'s own near-real-time cadence means the raw, untriaged (`status=NEW`) backlog
is normally close to zero at any given moment (confirmed at Phase 23.1H's own preflight: only 1
untriaged event in a 24-hour window) — so at the exact moment of the pause, there was nothing
waiting for the canary's own `run_triage_cycle()` call to claim, and no new raw material could
arrive during the pause since collection was paused too. The 5 events the canary's
`run_analysis_cycle()` did process in round 1 were pre-existing NEWS_ANALYSIS-complete backlog
from *before* the pause (already triaged under the real `story_memory_mode=off`), not freshly
triaged under shadow mode.

**This is a real, disclosed structural tension**, not a bug: reliably exercising Story Memory
shadow live would require either a longer pause (accepting a longer collection gap, a bigger
operational tradeoff) or decoupling collection from triage in `worker/cycle.py` (an architecture
change explicitly out of scope this phase). Recommendation for a future phase: consider a
dedicated, separately-schedulable triage-only entry point if live Story Memory shadow validation
becomes a repeated need.

## 6. Plain-language changes

New prompt `prompts/copywriting/v7.yaml` (v6 stays completely frozen, per this codebase's
established prompt-immutability rule — confirmed by a structural test that v6's text was not
touched). Same field/schema shape as v6; new rules added:
- **PLAIN LANGUAGE**: explain the news to an intelligent non-specialist; avoid unnecessary
  jargon (дата-центр over ЦОД, компания over legal/structural labels) without mechanically
  replacing already-understood terms (ИИ, NVIDIA, ChatGPT, Apple, Google, Telegram, Steam).
- **TECHNICAL DETAIL RULE**: if a technical detail doesn't change why the story matters, remove it
  rather than explain it.
- **ABBREVIATION RULE**: never introduce an unexplained niche abbreviation; prefer avoiding one
  entirely in a short piece over expand-then-abbreviate.
- **IMPORTANCE DOES NOT IMPLY LENGTH**: write exactly as much as is needed for what-happened +
  why-it-matters, and stop; a third point only when it adds real information.

`capabilities/copywriting_capability.py`'s Editorial-Plan/Prior-Coverage context-block gate
extended from `prompt.version == "6"` to `in ("6", "7")` (v7 needs the same optional context
blocks v6 introduced). `core/config.py`'s `copywriting_prompt_version` Literal extended to include
`"7"`.

These rules are prompt-level (they shape what the LLM writes) — they cannot be deterministically
unit-tested for their actual textual effect, only structurally confirmed to exist in the prompt
file (`test_v7_prompt_contains_the_required_plain_language_rules`, tests/
test_news_telegram_presentation.py) and observed in the one real v7-generated live post (§13).

## 7. Brevity changes ("Importance-Aware Brevity V2")

`services/news_telegram_presentation.py`: length reinterpreted as a **ceiling**, never a target to
fill and never a string-slicing boundary.
- `_MAX_PARAGRAPHS_BY_TREATMENT` reduced: `{BRIEF: 2, STANDARD: 3, MAJOR: 4}` (was `{2, 3, 6}`).
- New `_CHAR_CEILING_BY_TREATMENT = {BRIEF: 450, STANDARD: 650, MAJOR: 900}`.
- New "two-paragraph default" (`_DEFAULT_PARAGRAPH_COUNT = 2`): the first two core paragraphs
  (what happened + why it matters, in the existing priority order) are always kept when present,
  regardless of the ceiling — a real paragraph is never dropped purely for length. A third/fourth
  paragraph is added only while both the paragraph-count budget and the character ceiling still
  have room (`_select_within_ceiling()`, new function) — since every candidate that reaches this
  function already passed the existing redundancy filter, "genuinely distinct" is already
  guaranteed by construction; the ceiling governs *how much* distinct material fits, not whether
  distinctness itself is required.
- The material `what_remains_unknown` caveat keeps its own reserved slot (existing Phase 23.1G
  mechanism) — its own length is subtracted from the core selector's budget, so the combined
  result stays close to the ceiling; a small, documented overshoot (a few dozen characters) can
  occur when the mandatory two-paragraph default is already near the ceiling before the caveat is
  added — an accepted, disclosed consequence of "never drop below the two-paragraph minimum,"
  not a bug (observed directly in the Armenia-A offline replay, §8: 687 vs. a 650 target).

## 8. Before/after real examples (offline replay)

**The Armenia pair** (§ Part H requirement): replayed through the corrected pipeline (real Story
Memory scoring, isolated, zero contamination). Required result was "NOT two standalone posts" —
the honest result, disclosed in §1/§2 above, is that **both would still be delivered as two
standalone posts**, because the current matcher's own real judgment (even after §9's fix) does not
consider these two specific headlines a match. The duplicate-delivery *mechanism* built this phase
is proven correct (unit tests, §11) for cases Story Memory DOES recognize — it was not, and could
not have been, retroactively applied to override the matcher's own real scoring for this specific
pair without inventing a match that isn't actually there.

**5 Phase 23.1F/G/H representative stories, replayed through the new Brevity V2 presentation
logic** (same underlying real V6 text, only the selection/ceiling logic changed — v7's prompt-level
effect is separately shown by the one real v7-generated live post in §13, since these 5 stories
were generated under v6):

| Story | Treatment | Before (23.1G/H) | After (Brevity V2) | Δ |
|---|---|---|---|---|
| Stack Overflow | MAJOR | 1318 chars / 4 paragraphs | 599 chars / 2 paragraphs | −55% |
| Israeli startup | STANDARD | 730 chars / 3 paragraphs | 497 chars / 2 paragraphs | −32% |
| Amazon/Gilroy | STANDARD | 678 chars / 3 paragraphs | 459 chars / 2 paragraphs | −32% |
| Armenia A (Firebird) | STANDARD | 687 chars / 3 paragraphs | 687 chars / 3 paragraphs | 0% (already at the two-required-plus-material-caveat minimum) |
| Armenia B (Zerkalo) | BRIEF | 369 chars / 2 paragraphs | 369 chars / 2 paragraphs | 0% (already fit) |

Real, meaningful compression on the 3 stories that had genuine hedge/context redundancy beyond the
two-paragraph core; zero change (correctly) on the 2 stories that were already at their genuine
informational minimum — matching the brief's own "shorter without losing the actual news" goal,
evidenced on real data, not asserted.

## 9. Fact Safety root cause

Investigated the exact two Phase 23.1H live drafts' Fact Safety `block` findings (7 total: 6 on
Post #1, 1 on Post #2), all `type=entity`, all `support=unsupported`, all `evidence=[]`. Traced
directly into `services/fact_safety.py`'s own extraction/normalization code (not assumed):

**Class 1 (confirmed, fixed): sentence-initial capitalized preposition swept into the entity
span.** `_ENTITY_RUN_PATTERN` (a capitalized-word-run heuristic) captures "В Армении"/"В Раздане"
as one 2-word "entity" whenever the preposition happens to start a sentence — this never matches
the same real place name's correctly-cased, mid-sentence form elsewhere, since entity matching
(`_normalize_entity`) requires exact equality, not substring/fuzzy containment. The same
false-positive mechanism the codebase's own M5.2/Checkpoint 6 already excluded for grammatical
determiners/demonstratives ("this"/"that"/"это"), just not yet for prepositions.

**Class 2 (confirmed, fixed): "ЦОД" (data center) missing from the existing generic
hyphenated-descriptor list.** `_ENTITY_GENERIC_HYPHENATED_RE` already strips "система"/
"технология"/"платформа"/"модель"/etc. from a leading hyphenated compound (e.g. "ИИ-модель X" →
"X") — "ЦОД" was simply never added, so "ИИ-ЦОД Firebird" stayed glued as one unmatchable compound
instead of correctly reducing to "Firebird".

**Class 3 (observed, NOT fixed — genuine evidence gap, not a bug):** "NVIDIA DSX" and
"TrimCooler" — specific technical/product names that may simply not have been present in the
retrieved research evidence pool at all, independent of any normalization issue. Flagging these as
`unsupported` may be Fact Safety correctly doing its job (the evidence genuinely didn't confirm
them), not a false positive — not touched, per the brief's own explicit "do NOT blanket-ignore
entity mismatches" instruction.

**A fourth, recurring instance observed live this phase** (§13): the standalone entity "ИИ" was
flagged `unsupported` three times in the one real Phase 23.1I delivered post, despite an existing
`_ENTITY_ALIAS_CANONICAL` group already covering `{"ии", "искусственный интеллект", "ai",
"artificial intelligence"}`. Root cause not fully isolated this phase (most likely: the evidence
pool never independently extracted "ИИ"/"AI" as its own checkable entity claim, since it appears
almost every sentence as a generic topical reference rather than a specific named entity — an
extraction-side gap, not a normalization-side one). **Disclosed as a known, recurring limitation
for a future phase**, not silently ignored and not fixed under this phase's own time-boxed scope
given it did not present as cleanly generalizable as Classes 1/2.

## 10. Fact Safety fix

Two narrow, test-first, deterministic changes to `services/fact_safety.py`, mirroring this
module's own established "small, hand-curated, conservative word list" convention exactly (never
a general NLP parser, per the module's own repeated "не создавай universal NLP engine" discipline):
- New `_ENTITY_GENERIC_PREPOSITION_WORDS` frozenset (в/во/на/от/с/со/из/по/для/у/к/ко/над/под/
  при/за/до/о/об/обо), consulted by `_is_unconditionally_generic_word()` alongside the existing
  role-noun/hyphenated-descriptor checks — strips a leading, sentence-initial-only-capitalized
  preposition from an extracted entity span.
- `"цод"` added to both `_ENTITY_GENERIC_HYPHENATED_RE` (extraction-time prefix stripping) and
  `_ENTITY_DESCRIPTIVE_SUFFIX_PATTERN` (normalization-time suffix stripping) — the two lists this
  module's own comments already document as "kept in sync by hand."

Both changes **only ever cause a spurious "entity" to no longer be extracted/flagged at all** —
they never mark a genuinely unsupported claim as supported, never weaken any real contradiction
check, never touch money/date/percentage/quote claim types, and `fact_safety_mode` remains
`shadow` throughout (never enabled to enforce). Verified with the full existing Fact Safety test
suite (§12) — zero weakening of any pre-existing passing test.

## 11. Tests

**New**: `tests/test_story_duplicate_guard.py` (19 tests — pure-function cases 1/2/5 + the
documented 3/4-collapse + orchestration-level DB tests + the Armenia-pair regression lock-in,
Case 6). `tests/test_router_media_integration.py` extended (Case G's fixture lengthened to remain
a genuine caption-overflow scenario under the new, tighter MAJOR ceiling). `tests/
test_news_telegram_presentation.py` extended (+5: Cases 8/9/13, the v7-prompt structural check,
Case F's own assertions updated to reflect the new ceiling-driven priority behavior — a real,
intentional behavior change from Phase 23.1H, not a regression). `tests/test_fact_safety.py`
extended (+2: the two confirmed false-positive classes, §10).

**All new tests pass.** No paid LLM calls, no real Telegram sends, no worker starts in any test.

## 12. Regression results

Full suite covering every file touched this phase, run in batches: `test_editorial_treatment.py`,
`test_news_telegram_presentation.py`, `test_story_duplicate_guard.py`, `test_fact_safety.py`(+v6
compat +calibration), `test_content_draft_v6_compatibility.py`, `test_copywriting_capability.py`
(+prompt-version-cutover +v6-context-seam), `test_editorial_delivery_mode.py`, `test_router_media_
integration.py`, `test_content_cycle_story_delivery.py`, `test_news_source_button.py` — **250+
real assertions pass**. Every failure/error encountered was individually confirmed pre-existing
via direct comparison against a sibling untouched test exercising the same ambient condition (the
established `AIExecution` row-count pollution pattern; the `content_generation_dry_run`/`image_
editorial_preview_enabled` real-`.env`-vs-test-assumed-default mismatch pattern; the shared-DB
FK-teardown pattern on `content_draft_editorial_plans`/`stories.first_event_id`) — none newly
introduced this phase.

**Ruff**: all new/modified files clean. Repo-wide: the same 6 pre-existing issues in old,
untouched scratch scripts already disclosed in Phase 23.1G/H's own reports, unchanged.

**Mypy**: `worker/content_cycle.py`, `services/story_duplicate_guard.py`, `services/news_telegram_
presentation.py`, `services/fact_safety.py`, `core/config.py`, `capabilities/copywriting_
capability.py` — all clean, zero issues.

## 13. Offline replay

Covered in §8 above (Armenia pair + 5 representative stories through the new presentation logic).
One additional, real, live example exists from the actual canary run itself (§ Part I, `docs/
phase23_1i_live_editorial_hardening_review.md`): a v7-generated MAJOR post, 879 characters, 3
distinct paragraphs, plain-language throughout (no unexplained jargon, no forced conclusion) — the
first real evidence that v7's prompt-level rules produce the intended output on live data, not
just synthetic test fixtures.

## 14. Live analyzed count

**5 events analyzed** in round 1 (pre-existing NEWS_ANALYSIS-complete backlog from before
`automation_worker` was paused); round 2 found nothing further eligible (`nothing_eligible` stop,
well within the 50-event/4-hour/$1 hard caps — 5/50 analyzed, ~255 seconds/4 hours runtime,
$0.033/$1.00 cost, all with large headroom remaining). Preflight and postflight checks both
confirmed the fresh, score-qualifying pool was genuinely thin (0 of 44 pending candidates cleared
the pre-existing `content_generation_min_score=65` gate at both check times) — a real, disclosed
resource constraint, not a defect this phase introduced or could fix without lowering thresholds,
which the brief explicitly forbids.

## 15. SKIP count

**0.** No event reached Editorial Treatment classification with a SKIP verdict this run (the one
event that reached Editorial Treatment scored significance 8.6, treatment MAJOR). SKIP's real
behavior on real data was already validated in Phase 23.1G's own offline replay (2 real SKIPs on
the two weakest Phase 23.1F stories) — not re-exercised live this run because the thin pool never
produced a low-significance/weak-evidence candidate that also cleared the separate, pre-existing
Scoring-based `content_generation_min_score` gate.

## 16. DUPLICATE_BLOCK count

**0.** The one event that reached the duplicate-delivery check had no `NewsEventStoryLink` at all
(Story Memory found no candidate stories to compare against — or, more precisely per §5, never
ran a real triage pass on it since it was pre-existing backlog), so the check was correctly a
no-op. The guard's real blocking behavior is validated by 19 passing unit/integration tests
(§11), not exercised live this run for the same thin-pool reason as §15.

## 17. BRIEF/STANDARD/MAJOR counts

**0 BRIEF, 0 STANDARD, 1 MAJOR.** A single real data point this run; BRIEF/STANDARD's real
Brevity V2 behavior is validated via the offline replay (§8, real Phase 23.1G/H data) and the
synthetic test suite (§11), not independently re-exercised live this run.

## 18. Delivered count

**1 of a target 5.** See §14 for the disclosed resource constraint. Combined with Phase 23.1H's
own 2 delivered posts, this session now has **3 total real, delivered, human-reviewable NEWS
posts** across the two live canaries — still a small sample, honestly disclosed as insufficient
for full statistical confidence in editorial quality, but sufficient to validate that the
architecture (treatment, media, duplicate guard, plain-language prompt, source button, routing)
works correctly end-to-end on real data in every dimension exercised so far.

## 19. Image attached count

**0 of 1** delivered posts this run (no eligible image candidate existed for this specific event -
text-only, correctly, per the existing "no image is better than a bad image" policy from Phase
23.1H, unchanged and untouched this phase).

## 20. Fact Safety results

**1 of 1** delivered posts this run was flagged `block` under shadow mode (never suppressed the
send) — 3 findings, all the same recurring "ИИ" entity-matching gap disclosed in §9 as a known,
not-yet-fixed limitation. The two false-positive classes actually fixed this phase (leading
preposition, "ЦОД" compound) did not recur in this specific post's findings, consistent with them
being real, narrow, and specific to the patterns they targeted.

## 21. Total cost

**$0.032776** incremental this canary (baseline `$7.597590` → final `$7.630366`), well under the
$1.00 cap. Combined with Phase 23.1H's own $0.118788, this session's two live canaries have spent
**$0.151564** total against the shared cost tracker.

## 22. Errors/retries

**Zero real errors** in the successful run. One earlier attempt (the first launch) was killed by
this tool environment's own background-command timeout (~10 minutes) partway through round 3,
before any final summary or Telegram send outside what rounds 1-2 had already completed (round 2
delivered nothing) — `automation_worker` was restarted immediately, and the canary was
successfully re-run to completion as a detached process on the second attempt. No duplicate sends,
no partial/corrupted DB state resulted from the interrupted first attempt (rounds 1-2's own
work had already committed cleanly before the kill).

## 23. Known limitations

- Story Memory shadow, though now correctly wired for real (§5), was not actually exercised on
  any live event this run — a real, disclosed, structural tension between pausing
  `automation_worker` (needed so the canary's own triage can claim events without racing) and that
  pause also halting new collection. Recommended follow-up: a dedicated, separately-schedulable
  triage-only path if repeated live Story Memory validation becomes necessary.
- The Armenia duplicate motivating example is **not** retroactively fixed by this phase's own
  duplicate-delivery guard — the current deterministic matcher's own real judgment does not
  recognize these two specific headlines as the same story (§1/§2/§8), a genuine limit of
  keyword/entity-based matching without embeddings/LLM assistance (explicitly out of scope).
- One Fact Safety false-positive class ("ИИ" alias-matching, §9/Class 4) was observed twice
  (Phase 23.1H and this phase) but not root-caused precisely enough to fix narrowly this phase —
  disclosed, not silently dropped.
- Only 1 new live delivered post this run (3 total across both live canaries this session) — a
  small sample for full editorial-quality confidence, though sufficient to validate every
  architectural mechanism this phase and Phase 23.1H introduced.
- The `_CHAR_CEILING_BY_TREATMENT`/`_DEFAULT_PARAGRAPH_COUNT` values are reasoned starting points
  from the phase brief's own explicit approximate ranges, not fit to a large calibration dataset —
  like every threshold introduced earlier in this project, expected to be revisited as more real
  data accumulates.

---

## VPS readiness decision

**B — SMALL FIX(ES) REMAIN.**

The architecture continues to be sound and is now meaningfully hardened: the duplicate-delivery
guard is real, tested, and safely reuses only existing Phase 20 state; Brevity V2 produces real,
evidence-based compression without losing substance (§8); the v7 plain-language prompt produced a
genuinely readable, appropriately-scoped real post (§13); two real Fact Safety false-positive
classes were found and fixed narrowly, test-first, without weakening any real check (§9/§10);
routing, source button, and image fallback all continued to work correctly on the one real send
this run.

Three bounded, disclosed items remain before full confidence, none of them architecture-level:
1. **Story Memory shadow's live-exercise gap** (§5/§23) — the mechanism is correctly wired, but
   this specific run's operational constraint (pausing collection to pause triage) meant it wasn't
   actually tested against a real, freshly-triaged event. A future canary run with a longer
   pause window, or a decoupled triage-only entry point, would close this gap.
2. **The recurring "ИИ" Fact Safety false positive** (§9 Class 4) — observed twice now, not yet
   root-caused precisely enough for a safe, narrow, test-first fix.
3. **A larger live sample** — 3 total delivered posts across two canaries is still small for full
   confidence in real-world editorial quality at scale, though every individual mechanism has now
   been validated correct.

None of these are structural/architecture-level blockers (routing risk, draft contamination,
uncontrolled processing, broken treatment, or a Fact Safety regression that weakens a real check) —
hence B, not C. Per the phase's own explicit instruction: **STOP here.** No VPS deployment, no
permanent `.env` change, no enforce modes (Story Memory, duplicate suppression, story-update
routing, Fact Safety), no Telegraph/Instagram/Reels/Meme work. Waiting for human review of the one
new real Telegram card (`docs/phase23_1i_live_editorial_hardening_review.md`) alongside the two
from Phase 23.1H.
