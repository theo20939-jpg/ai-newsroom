# Phase 23.1J — Copywriting V8 / Final Telegram NEWS Text Format

**Branch**: `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(no new commits — all work uncommitted, matching this session's established convention).

**Status**: implementation + tests + offline golden replay + both reports complete. **STOP —
waiting for human review.** No live Telegram canary was run this phase, per the phase's own
explicit instruction. `copywriting_prompt_version` was set to `"8"` only in-process, by two
standalone offline scripts — it was never written to the real `.env` and is not the production
default (still `"4"`).

---

## 1. Current V7 problem

Human review of Phase 23.1I's own live post and offline replays found V7 (despite its own
plain-language + Brevity V2 work) still asked the model to independently fill **seven** narrative
sections (`opening/context/why_it_matters/what_changed/what_happens_next/conclusion/what_remains_
unknown`), then relied on the presentation layer to select/trim/de-duplicate after the fact. This
architecture structurally invites redundancy - the Google Pay story's real V6/V7 draft expressed
"details not disclosed" **five separate times** across five different sections, each individually
plausible, only caught by an increasingly complex presentation-layer hedge-cap mechanism. The
brief's own diagnosis: *"Do not ask the model to independently fill seven editorial sections and
then hope the presentation layer can remove the repetition."*

## 2. V8 design

New prompt `prompts/copywriting/v8.yaml` (v6/v7 stay completely frozen, verified by a structural
test that v8-only rule text never appears in either). Four possible editorial parts instead of
seven: **HEADLINE + MAIN BODY (mandatory) + OPTIONAL ENDING + OPTIONAL EXPANDABLE DETAILS**. The
model is told this is the *entire* structure up front, in the system prompt itself - no
independent background/why-it-matters/what-happens-next/unknowns sections exist to fill.

## 3. Schema decision

Investigated first (per the phase brief's own instruction), decided against a broad rename:
- The JSON field is still named `title` (not literally `headline`) - a deliberate choice so
  `services/content_draft_service.py` and `services/fact_safety.py`'s own shared title-lookup
  code needed zero changes. The brief's "HEADLINE" is documented as *this* field's semantic
  meaning, not a literal rename.
- `main_body` (mandatory), `ending` (optional), `expandable_details` (optional) are genuinely
  new field names - not a cosmetic rename of V6/V7 fields, a real, smaller structure matching the
  brief's own explicit instruction not to ask the model to fill seven sections.
- `quote` is unchanged from V6/V7 - a separate, structured field, untouched by
  `expandable_details`. Quote verification/persistence (`services/quote_verification.py`) needed
  zero changes.

## 4. Plain-language rules

`prompts/copywriting/v8.yaml` rules (verbatim intent, not paraphrased): **PLAIN LANGUAGE** (prefer
the simplest accurate wording - "дата-центр" over "ЦОД", "запустила" over "осуществила
развертывание" - without mechanically replacing already-understood terms like ИИ/NVIDIA/Apple/
Google/Telegram/Steam/ChatGPT/iPhone); **DELETE BEFORE EXPLAINING** (if a technical detail isn't
needed to understand the news, delete it rather than explain it); **ABBREVIATIONS** (avoid niche
abbreviations - prefer the plain term throughout rather than defining-then-abbreviating in a short
post). These are prompt-level rules - they shape what the LLM writes and cannot be
deterministically unit-tested for their textual effect, only structurally confirmed present in the
prompt file (verified) and observed on real data (§16-22).

## 5. Brevity rules

**IMPORTANCE DOES NOT IMPLY LENGTH** is stated explicitly in the prompt (treatment determines
available depth, never a word-count requirement) *and* enforced at the presentation layer as a
genuine behavior change, not just a stated ideal: `services/news_telegram_presentation.py`'s new
`_V8_SOFT_CEILING_BY_TREATMENT = {BRIEF: 280, STANDARD: 450, MAJOR: 600}` (with a wider
`_V8_EXCEPTIONAL_CEILING_BY_TREATMENT[MAJOR] = 750` for genuinely rich stories) governs whether the
optional `ending` gets appended on top of the mandatory `main_body` - a **soft** ceiling only,
never a truncation wall (`main_body` itself is never split, cut, or dropped below the mandatory
minimum). Per the phase brief's own explicit §30 instruction ("do not solve bad copy with
truncation"), this ceiling is a safety net; the prompt's own brevity discipline is the *primary*
mechanism, confirmed by the golden replay (§16-22): all 5 real stories landed well under their
soft ceilings without the ceiling ever needing to reject anything.

## 6. Optional-ending behavior

`build_v8_news_body()` appends `ending` only when it passes three checks, all reused from Phase
23.1G/I's own established mechanisms: not filler-pattern-matched (`_is_filler()`), distinct from
`main_body` (`_is_distinct()`, `symmetric_token_overlap` < 0.3), and not the same hedge family
already expressed in `main_body` (`_hedge_family()` - the same one-uncertainty-maximum enforcement
V7 already established, now applied to V8's simpler two-field shape). When `ending` is `None` or
fails any check, the post ends after `main_body` alone - confirmed in the golden replay (ghost
particles/virus-bacteria/Google Pay's second sentence all correctly either kept or omitted an
ending per this logic).

## 7. Expandable-blockquote implementation

Investigated first (per the phase brief's own instruction): aiogram 3.29.1 (the installed version)
exposes `html_decoration.expandable_blockquote()`, confirmed to produce exactly `<blockquote
expandable>...</blockquote>` - real, documented Telegram Bot API HTML syntax, not assumed.
`render_v8_news_card_html()` builds this tag manually (mirroring `bot/formatting.py`'s own
established "escape content, not tags" convention, rather than adding aiogram's `html_decoration`
utility as a new dependency pattern), wrapping `expandable_details` only when present and
non-filler. Nothing was sent live - confirmed purely by direct string inspection in tests.

## 8. NINJA PULSE footer implementation

`build_ninja_pulse_footer_html()` - a pure, deterministic function returning exactly `<a
href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>`, **never generated by the LLM** (no
field for it anywhere in `prompts/copywriting/v8.yaml`'s output schema, zero tokens spent on it).
Appended by `render_v8_news_card_html()` exactly once, as the final block, after any expandable
details. Verified: exact text, exact link, appears exactly once, the raw URL is never the visible
anchor text (Case O/P/S, tests/test_news_telegram_presentation_v8.py).

## 9. Source-button preservation

`[🔗 Источник]` remains a completely separate mechanism (the existing inline keyboard, built by
the caller - `worker/content_cycle.py`, untouched this phase) - `render_v8_news_card_html()`'s own
function signature has no URL parameter at all (Case R, a structural guarantee, not just an
empirical one), and its output never contains the word "Источник" or any button markup (Case Q).

## 10. Fact Safety compatibility

`services/fact_safety.py::_extract_draft_text()` gained one new recognized-schema branch
(`_V8_REQUIRED_TEXT_KEYS = ("main_body",)`, `_V8_OPTIONAL_TEXT_KEYS = ("ending",
"expandable_details")`), added alongside the existing V4/V6 branches, never replacing them.
Confirmed: a claim placed only in `expandable_details` (which will later be visually hidden behind
a Telegram expandable blockquote) is still extracted and checked - Fact Safety sees the complete
draft regardless of how it will eventually be displayed (tests/
test_fact_safety_v8_compatibility.py, Cases 1-3, all passing). `fact_safety_mode` stays `shadow`
throughout this phase - never enabled to enforce.

## 11. ContentDraft compatibility

`services/content_draft_service.py::_extract_title_and_body()` gained the identical new branch
(`_V8_REQUIRED_TEXT_KEYS`/`_V8_TEXT_KEYS_IN_ORDER`), mirroring the Fact Safety change exactly.
Verified end-to-end: a real `ContentDraftService.create_from_result()` call with V8 output
persists correctly, `title`/`body` populated, `ending`/`expandable_details` concatenated in order
when present (tests/test_content_draft_v8_compatibility.py, 6/6 passing).

## 12. Files changed

**New**: `prompts/copywriting/v8.yaml`, `tests/test_content_draft_v8_compatibility.py`, `tests/
test_fact_safety_v8_compatibility.py`, `tests/test_news_telegram_presentation_v8.py`,
`scripts/_phase23_1j_golden_replay.py` (+ its own JSON output artifacts, kept for audit trail),
`docs/phase23_1j_copywriting_v8_human_review.md`, `docs/phase23_1j_copywriting_v8_report.md`
(this file).

**Modified**: `core/config.py` (`copywriting_prompt_version` Literal extended to include `"8"`,
default unchanged at `"4"`), `capabilities/copywriting_capability.py` (Editorial-Plan/Prior-
Coverage context-block gate extended from `("6","7")` to `("6","7","8")`), `services/
content_draft_service.py` (+V8 extraction branch), `services/fact_safety.py` (+V8 extraction
branch), `services/news_telegram_presentation.py` (+ ~150 lines: `build_v8_news_body()`,
`build_v8_expandable_details()`, `build_ninja_pulse_footer_html()`, `render_v8_news_card_html()`,
new V8-specific ceiling constants - all additive, the existing V6/V7
`build_compact_news_body()` function completely untouched).

**Not modified**: `worker/content_cycle.py` (V8 is not wired into any live delivery path this
phase - matches "NO LIVE TELEGRAM CANARY"), `services/editorial_treatment.py`, `services/
story_duplicate_guard.py`, `services/story_memory.py`, any image-related module, `.env`.

## 13. Tests

**New**: 6 (ContentDraft V8) + 3 (Fact Safety V8) + 18 (presentation V8, Cases A-T) = **27 new
tests, all passing**. No paid LLM calls, no real Telegram sends, no worker starts in any test.

## 14. Regression

Full suite covering every file touched this phase plus adjacent modules: `test_content_draft_v6_
compatibility.py`, `test_fact_safety_v6_compatibility.py`, `test_news_telegram_presentation.py`,
`test_editorial_treatment.py`, `test_copywriting_capability.py` (+prompt-version-cutover +v6-
context-seam), `test_router_media_integration.py`, `test_editorial_delivery_mode.py`,
`test_content_generation_integration.py`, `test_story_duplicate_guard.py` — **198+ real
assertions pass**. Every failure/error was individually re-confirmed as the exact same pre-existing
pattern already disclosed in Phase 23.1G/H/I's own reports (the `AIExecution`-count pollution
pattern; the `content_generation_dry_run`/`image_editorial_preview_enabled` real-`.env`-vs-
test-assumed-default mismatch; the shared-DB FK-teardown pattern on `content_draft_editorial_
plans`/`stories.first_event_id`) - none newly introduced this phase, none re-verified via a fresh
`git stash` this time since they are the identical, already-documented signatures from the
immediately preceding phase's own stash-verified findings.

**Ruff**: all new/modified files clean. Repo-wide: the same 6 pre-existing issues in old,
untouched scratch scripts already disclosed in every prior phase's own report, unchanged.

**Mypy**: `services/content_draft_service.py`, `services/fact_safety.py`, `services/news_
telegram_presentation.py`, `core/config.py`, `capabilities/copywriting_capability.py` - all
clean, zero issues.

## 15. Real replay methodology

`scripts/_phase23_1j_golden_replay.py` - since all 5 target events already had a real
`CONTENT_GENERATION` `EditorialTask` from an earlier phase, and `services/workflow_service.py::
create_task()` unconditionally refuses a second task for the same `(event, workflow_type)` pair
regardless of status, the normal `run_content_generation_for_event()` path (which always creates a
fresh task) could not be reused. Instead, mirroring `scripts/phase19_overnight_abc_harness.py`'s
own established "manual `CapabilityContext` construction, direct `capability.execute()` call"
pattern: each event's real, already-persisted NEWS_ANALYSIS `research`/`intelligence` step
results were read directly and fed into a hand-built `CapabilityContext`, then
`CopywritingCapability.execute()` was called in complete isolation - no Research/Intelligence/
Quality/Fact-Safety re-computation, no ContentDraft persistence, no Telegram involvement of any
kind. Cost records were attached to each event's *existing* NEWS_ANALYSIS `task_id` (a disclosed,
deliberate choice for this bounded, one-off evaluation script only - not a production
cost-attribution pattern).

## 16-22. Before/after results (character counts, paragraph counts, per story)

See `docs/phase23_1j_copywriting_v8_human_review.md` for the full text of every card. Summary:

| Story | Treatment | BEFORE chars/paragraphs | AFTER chars/paragraphs | Expandable |
|---|---|---|---|---|
| Armenia/Firebird/NVIDIA | STANDARD | 687 / 3 (V7) | 373 / 2 | YES |
| Google Pay AI | STANDARD | 154 / 1 (V6, already hedge-capped) | 250 / 2 | NO |
| Ghost particles | STANDARD* | 1015 / — (V6, never delivered) | 356 / 2 | NO |
| AI virus/bacteria | STANDARD* | 1430 / — (V6, never delivered) | 283 / 1 | NO |
| Stack Overflow | MAJOR | 599 / 2 (V7) | 391 / 2 | NO |

\* Real Editorial Treatment (unchanged this phase) classifies these two SKIP (weak evidence) -
replayed anyway per the phase brief's own explicit instruction; would not be delivered in
production regardless of V8 text quality.

**§29 Armenia acceptance target, evaluated structurally** (not by lexical similarity, per the
brief's own instruction): understandable immediately - yes. Approximately 2 paragraphs - yes (2
main_body paragraphs + 1 expandable block, no forced 3rd visible paragraph). No infrastructure
jargon - mostly yes ("NVIDIA DSX AI Factory"/"серверы Dell" are named, not explained - a judgment
call, flagged for review). Keeps 15→300 MW - **no**, and this is explained, not hidden (§18 below).
Keeps six-month construction fact - yes. At most one useful caveat - yes (the independent-
confirmation caveat, stated once). No filler conclusion - yes (no forced ending was written at
all beyond the one material caveat).

## 18. Armenia result — the missing 15→300 MW figures, explained

The real Research capability output for this event (already-persisted, reused verbatim, not
regenerated) explicitly lists as a gap: *"Основной текст не подтверждает заявленные в заголовке
показатели развертывания 15 из 300 МВт"* - the article's own body text does not confirm the
headline's 15/300 MW claim. V8 correctly declined to state an unconfirmed number as established
fact, consistent with its own "base every claim only on the supplied Research/Intelligence output"
rule and with this entire session's repeated Fact-Safety-driven emphasis on not asserting
unconfirmed claims. This is disclosed as a genuine, evidence-grounded finding, not hidden: the
phase brief's own acceptance target assumed the number was confirmable; real evidence retrieval
found it was not-per the brief's own text, "keeps 15→300 MW **if supported by evidence**" - and in
this real case, it was not.

## 19. Google Pay result

See human review packet #2. A real, evidence-grounded case where V8's more expressive two-field
structure (main_body + one ending) is numerically longer (250 vs. 154 chars) than the maximally
hedge-capped V6+BrevityV2 baseline, while expressing meaningfully fewer redundant uncertainty
statements (2 vs. the original V6 draft's 5). Flagged for human judgment on whether the ending
paragraph adds real value or is borderline redundant with main_body.

## 20. Ghost-particles result

See human review packet #3. Real Editorial Treatment (unrun this phase) already classifies this
SKIP - the V8 text itself is concise (356 chars/2 paragraphs) and appropriately cautious given
thin evidence, useful as a demonstration that V8's writing quality holds even on a weak-evidence
story, though it would never actually be delivered.

## 21. Virus/bacteria result

See human review packet #4. The shortest of the 5 (283 chars, 1 paragraph, no ending) -
appropriately brief given the single-source, unverifiable nature of the underlying claim. Same
SKIP-in-production caveat as ghost particles.

## 22. Stack Overflow result

See human review packet #5. MAJOR treatment, 391 chars/2 paragraphs - well under even MAJOR's new
450-normal/600-soft-ceiling range, demonstrating the "importance does not imply length" rule
holding on a genuinely major, widely-relevant story: the 98.5% traffic-collapse statistic and the
comparison to three other affected platforms (Shutterstock/Getty/Quora) are both kept because they
are genuinely load-bearing facts, with no padding around them.

## 23. Known limitations

- V8 is not wired into any live delivery path this phase (`worker/content_cycle.py` untouched) -
  by design, matching "NO LIVE TELEGRAM CANARY." A future phase would need to wire
  `render_v8_news_card_html()`/`build_ninja_pulse_footer_html()` into the router branch alongside
  a version check, mirroring how V7 was eventually wired in Phase 23.1I.
- The Armenia replay's missing MW figures (§18) surface a genuine, unresolved editorial tension
  between "state what the headline claims" and "state only what the body evidence confirms" - not
  fixed this phase (a product/editorial policy question, not a code bug), disclosed for human
  decision.
- The `_V8_SOFT_CEILING_BY_TREATMENT`/`_V8_EXCEPTIONAL_CEILING_BY_TREATMENT` values are reasoned
  starting points from the phase brief's own explicit new numbers, not fit to a large calibration
  set - like every threshold introduced this session, expected to be revisited as more real data
  accumulates. This phase's 5-story sample never actually exercised the exceptional-MAJOR ceiling
  or the ending-rejection-by-ceiling path at all (every real ending fit comfortably) - only
  synthetic tests exercise that specific branch.
- Only 5 real stories replayed this phase (as specified) - a useful, evidence-grounded sample for
  structural/format validation, but still small for full confidence in writing-quality consistency
  at scale.
- The Google Pay "ending" (§19) is flagged as a borderline case for human judgment, not resolved
  by this report.

## 24. Cost

**$0.022624** total this phase (5 Copywriting-only calls, Research/Intelligence reused from
cache at zero additional cost). Combined with this session's prior live canaries (Phase 23.1H:
$0.118788, Phase 23.1I: $0.032776), cumulative session AI spend across all Phase 23.1 canaries/
replays: **$0.174188**.

---

## Final decision

**A — V8 READY FOR LIVE CANARY.**

The real golden replay demonstrates, on 5 real stories spanning weak-evidence/thin (ghost
particles, virus/bacteria), thin-but-real (Google Pay), and substantive (Armenia, Stack Overflow)
cases, that V8 consistently produces HEADLINE + SHORT MAIN BODY + OPTIONAL ENDING without losing
important facts: every AFTER body landed at 250-391 characters (all comfortably under STANDARD's
450/MAJOR's 600 soft ceilings, several barely above BRIEF's 280), zero cases required the safety-
net ceiling to reject content, zero cases needed truncation, and the one real, disclosed factual
tension (Armenia's MW figures) is a genuine evidence-discipline finding, not a formatting failure
or a lost fact due to truncation - the number was never stated because the underlying evidence
itself did not confirm it. The NINJA PULSE footer and expandable-blockquote mechanisms both work
correctly and deterministically, verified without any live Telegram call. Fact Safety and
ContentDraft compatibility are both confirmed with passing tests, `fact_safety_mode` stays
`shadow`.

Per the phase's own explicit instruction: **STOP here.** No live Telegram sends, no continuation
of the 5-news canary, no VPS deployment, no permanent `.env` change, no Story Memory/Armenia-
duplicate work, no image behavior changes, no enforce modes, no other editorial destinations.
Waiting for human review of the 5 real V8 examples (`docs/
phase23_1j_copywriting_v8_human_review.md`).
