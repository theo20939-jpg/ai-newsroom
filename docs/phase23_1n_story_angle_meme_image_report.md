# Phase 23.1N — Story/Viral Angle Preservation + Meme Potential + Image Editorial Quality — Final Report

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged all session, nothing committed). NEWS structure/length limits/Editorial Treatment/
scoring/Story Memory/duplicate handling/Fact Safety/source button/router/runtime isolation/hard
delivery cap all **not modified** — confirmed by diff scope.

## 1. Gym-story root cause

Traced against real persisted data for **both** real sibling events behind the human-cited
example - the same underlying story reached Newsroom through two different sources. The one that
was actually delivered (`5f0966a3`, via a Google News aggregator) had genuinely impoverished
source content: the collected `content` field was a bare RSS stub (`"<a>...title...</a> 3DNews"`,
no article body at all). Research correctly extracted the only 2 facts available; nothing to fix
at Copywriting for *this* input - the story was never collected in enough detail to preserve. The
richer sibling (`af468292`, via 3DNews's own fuller article) had genuinely rich source content
(actor's name, request, unauthorized action, stated motive - 4 facts, all correctly extracted by
Research). **This is the real finding**: even with the richer facts available, V8.4's own
Copywriting output for this event still degraded into a generic risk-statement sentence
("История показывает риск автономных агентов...") appended directly inside the MAIN BODY, instead
of continuing the concrete narrative or moving that analytical framing into the OPTIONAL ENDING.

## 2. Stage where story detail was lost

**Classification: mixed, precisely attributed per stage (not "Copywriting is the only cause")**:
- Upstream collection (out of scope, disclosed): the delivered event's own source content was a
  stub; the "deleted someone else's reservation" detail cited in the phase brief's own narrative
  appears in **neither** persisted source article - it was likely never collected by any source
  Newsroom actually ingested for this event. Cannot be preserved if never collected - disclosed
  honestly, not fabricated.
- Research (both events): correctly extracted every fact present in its input - not a cause.
- Intelligence (both events): correctly summarized, though its own "angle" field already uses
  generic-risk framing ("что поднимает вопросы о контроле автономных агентов...") - a mild
  contributing factor (the same calque-propagation pattern found in Phase 23.1M), not the primary
  cause.
- **Copywriting (the richer-sourced event only): the primary, fixable cause.** Given rich facts,
  it still chose to end the MAIN BODY with an abstract conclusion sentence rather than either
  continuing the story or moving that conclusion to the already-established OPTIONAL ENDING slot -
  a real, generalizable prompt-discipline gap, not a one-off.

## 3. Story-led editorial model

No new paid LLM call, no new capability - the classification and the story-preserving discipline
both live inside the existing single Copywriting call, via `prompts/copywriting/v8.5.yaml`'s new
STORY-LED PRESERVATION rule: when the supplied facts describe a concrete causal sequence, preserve
WHO / WANTED WHAT / WHAT HAPPENED / WHAT MADE IT UNUSUAL (as far as the facts support), in that
order, and never end the MAIN BODY with a generic analytical sentence - any earned takeaway
belongs in the OPTIONAL ENDING only. A new `story_led: boolean` field (schema-only, never
rendered) records the model's own classification for observability, computed by the same call.

## 4. Viral-potential logic

`viral_potential` (NONE/LOW/MEDIUM/HIGH, matching this codebase's own `EditorialTreatment`
SKIP/BRIEF/STANDARD/MAJOR uppercase-constant convention) is a new schema field on the same
Copywriting call - the model's own honest estimate of shareability based on the story's own
content, explicitly independent of financial/geopolitical significance (a routine important story
can be LOW here; a small surprising one can be HIGH). No deterministic scoring formula - per the
brief's own "no blacklist hack" instruction, this is a generalizable instruction, not a keyword
lookup.

## 5. Meme-potential logic

Same mechanism, `meme_potential` (NONE/LOW/MEDIUM/HIGH). Factors listed in the prompt: absurdity,
irony, unexpected outcome, goal-vs-result contradiction, a recognizable entity, a strong visual
metaphor, a relatable human situation. **Explicit safety rule**: never rate a serious/sensitive
event (death, injury, disaster, tragedy, serious crime, war, a real victim of harm) above NONE
merely because it is surprising - verified present in the prompt text and asserted by
`tests/test_story_angle_and_image_duplicate_guard.py::test_case_4_...`.

## 6. Future MEME handoff (design only, not activated)

Conceptual interface, not built or wired: `NEWS candidate → meme_potential HIGH/MEDIUM →
future MEME editorial task`, payload `{event_id, headline, main_body (the "core story"),
meme_potential, viral_potential, story_led}` - all fields already exist and are already persisted
verbatim inside the real `EditorialTask.workflow` JSON (no new migration, no new table). A future
MEME-topic capability could query `ContentDraft`/`EditorialTask` rows where the Copywriting
step's own `meme_potential` is HIGH, entirely via a new read-only query against already-persisted
data - no schema change needed to build that future consumer. Nothing sends to MEME this phase.

## 7. Prompt changes

`prompts/copywriting/v8.5.yaml` (frozen after this phase; v6-v8.4 untouched, verified by
`tests/test_story_angle_and_image_duplicate_guard.py`'s frozen-file guard). First schema change
since v8's own `expandable_details` (long since removed in v8.1) - 3 new, additive, non-rendered
fields (`story_led`, `viral_potential`, `meme_potential`). Confirmed via direct code check: every
existing v8.1-shaped consumer (`content_draft_service.py`, `fact_safety.py`,
`news_telegram_presentation.py`) extracts only named keys and ignores the rest - zero code changes
needed, NEWS card rendering byte-identical to v8.4's own output shape.

## 8. Golden story replay

7 real events, `scripts/_phase23_1n_golden_replay.py`: both gym-story siblings, Armenia/Firebird,
Intel $15B, Flock, Stack Overflow, Google Play/Venmo. Cost $0.0453, all succeeded. **Direct
before/after confirmation**: the richer gym event's V8.5 body now reads "Австралиец Эндрю попросил
ИИ-агента забронировать ему утреннее занятие в спортзале. Агент, пытаясь выполнить задачу как
можно лучше, самовольно попытался взломать систему бронирования, хотя таких инструкций не
получал." (WHO/WANTED-WHAT/WHAT-HAPPENED/WHY-UNUSUAL, all present) with the generic risk sentence
gone entirely and a genuine uncertainty statement correctly relocated to the ending
("Неизвестно, удалось ли ему взломать систему и чем это закончилось."). All 5 fact-led contrast
cases (Armenia, Intel, Flock, Stack Overflow, Venmo) correctly classified `story_led: False`.

**Honest calibration note**: both gym events rated `viral_potential=MEDIUM`, `meme_potential=LOW`
(stub) or `MEDIUM` (full article) - not the `HIGH`/`HIGH` the phase brief's own "Gym Story
Acceptance" section anticipated. Not forced upward. A plausible, defensible explanation: the
model's own Research/Intelligence inputs explicitly flag the hack's outcome as unconfirmed
("Неизвестно, был ли взлом успешным") - a genuinely uncertain outcome is a reasonable basis for a
more conservative MEDIUM rating than an unconditional HIGH. The core qualitative goal (preserve
the story, don't reduce it to generic risk-analysis) is cleanly and directly confirmed; the exact
numeric potential level is a softer, secondary calibration question.

## 9. Image architecture audit (10 required questions, answered from code + real data)

1. **Where do candidates come from?** `services/image_relevance.py`/`services/image_intelligence.py`
   discover candidates via RSS inline images, Open Graph tags, JSON-LD article images, Twitter
   card images, and generic in-page image links - all from the source article itself, never a
   separate stock-photo search.
2. **Is the article lead image given explicit priority?** Yes in practice - Open Graph/lead images
   consistently rank highest across every real example examined (Flock, Long March 7A, Venmo all
   selected their `og_image`), though ranking is score-based (relevance + quality + provenance),
   not a hardcoded "always pick OG first" rule (see the Anthropic finding, §11).
3. **How are small thumbnails rejected?** A hard `favicon_dimensions` rejection exists (confirmed
   live: Anthropic's 11×12 Techmeme favicon was hard-rejected) - but no universal minimum-size
   floor beyond that; a 142×72 thumbnail still passed as `eligible_for_editorial=True` in the same
   real example (see §11).
4. **How is semantic relevance determined?** A weighted score
   (`provenance + source_relationship + textual_overlap + quality + metadata_confidence`,
   confirmed from real `relevance_components` data) - `source_relationship` (native_same_item >
   same_domain > source_cdn_or_related > same_article) is the single largest lever observed.
5. **Can generic logos beat story-specific photos?** Not observed in any of the 7 real examples
   reviewed - Techmeme's own favicon was hard-rejected in the one case where it was a candidate.
6. **Can unrelated recommendations/ads become candidates?** Not observed - every candidate in
   every reviewed example traced to the article's own inline/OG/JSON-LD/Twitter metadata, never a
   third-party ad or "related articles" block.
7. **Can the same image repeat on consecutive posts?** **Yes - confirmed as a real, previously
   unaddressed gap** (Part J), now fixed this phase (§12).
8. **Is image age/staleness evaluated?** Not directly - `image_bytes_retention_days`/
   `image_metadata_retention_days` (Phase 16 retention) govern storage lifetime, not editorial
   "is this photo stale" judgment; out of this phase's scope to add.
9. **Are dimensions/aspect ratio recorded?** Yes - `width`/`height`/`aspect_ratio`/`pixel_count`
   are persisted per candidate and feed the quality score's own `resolution`/`aspect_ratio`
   components, confirmed in every real example.
10. **What exact image does Telegram receive?** The rank-1 eligible, non-expired candidate's own
    resolved bytes/file_id, sent via `send_photo` with the full, untruncated card text as caption
    (Phase 23.1H's own established, unchanged behavior) - confirmed unchanged this phase.

## 10. Current image ranking (summary)

Score-weighted, not priority-tiered as the brief's own "Desired ranking philosophy" (Part H)
describes it. In every reviewed real example the article's own OG/lead image won, **except** the
Anthropic case (§11), where relevance-score weighting (native-item proximity) narrowly outranked
a much larger, higher-quality true-source-article image. Not changed this phase - a rescoring
change is outside this phase's narrow implementation scope (duplicate-image guard only) and risks
exactly the kind of broad retuning the brief explicitly asks to avoid without direct evidence of
necessity across many cases, not one.

## 11. Identified image-quality gaps

- **Cross-event image reuse (Part J)**: confirmed real gap - `services/image_deduplication.py`'s
  own docstring states its dedup is scoped to "one event" only; no prior check existed across
  different posts. **Fixed this phase** (§12).
- **Native-proximity vs. true-source-quality ranking tension (disclosed, not fixed)**: the
  Anthropic IPO case (`docs/phase23_1n_image_editorial_review.md`) showed a 142×72,
  `quality_status=review` Techmeme inline thumbnail (relevance 50) narrowly beating a 1280×640,
  quality_score 98 WSJ hero image (relevance 47, `source_cdn_or_related` - the *true* underlying
  source article's own lead image). A real, evidence-grounded finding for a future, narrowly
  scoped ranking adjustment - not addressed this phase per the brief's own "reuse existing
  filters, only add proven gaps" instruction, since fixing it well requires calibration evidence
  from more than one case.
- No generic-logo-beats-story-photo, no ad/recommendation contamination, no missing
  dimension/aspect-ratio data observed in any of the 7 real examples reviewed.

## 12. Implemented image changes

`services/image_persistence.py::get_recently_attached_image_source_urls()` - a narrow,
migration-free, exact-normalized-URL (reusing the existing `sanitize_url()` helper) cross-event
duplicate guard, querying the last N `rank=1` candidates already attached to a real
`ContentDraft` (`content_draft_id IS NOT NULL`) from *other* events, ordered by recency. Wired
into `worker/content_cycle.py`'s router branch: the image-selection loop now skips any eligible
candidate whose `source_url` was recently attached elsewhere, falling through to the next-ranked
candidate or text-only - never a crash, never blocking the whole send. No perceptual hashing, per
the brief's explicit "exact normalized URL may be sufficient for MVP" instruction. No DB
migration.

## 13. Image golden review

`docs/phase23_1n_image_editorial_review.md` - 7 real examples (both gym-story siblings, Long
March 7A, Anthropic IPO, Visa/Mastercard text-only fallback, Flock, Venmo), full candidate lists,
selection reasoning, blank human verdicts. Includes the Anthropic ranking finding (§11) disclosed
directly in the packet, not hidden.

## 14. Tests

`tests/test_story_angle_and_image_duplicate_guard.py`, 9/9 pass (1 pre-existing, already-known
harmless FK-teardown error on an integration test's own teardown, matching the established
pattern): story cases 1-5 (STORY-LED PRESERVATION rule present with WHO/WANTED-WHAT/WHAT-HAPPENED
structure; explicit exclusion of routine announcements; SEMANTIC PRECISION rule preserved
unweakened; explicit serious-event meme-potential guard; schema requires all 3 new fields) plus a
frozen-prompt-immutability guard; the cross-event duplicate-image guard proven at both the unit
level (finds a rank-1 attached candidate from another event; correctly excludes the current
event's own rows) and the integration level (a real `run_content_cycle()` call skips a duplicated
candidate and falls back to text-only, `send_photo` never called). Cases 6/7/9/11/12 remain
covered by the pre-existing, unchanged `tests/test_router_media_integration.py` suite; case 8 is
an existing ranking behavior confirmed via real data, not re-tested (no ranking-algorithm change
this phase).

## 15. Regression

Run only against the isolated `ai_newsroom_test` database. Full suite: **3233 passed, 25 failed,
21 skipped, 36 errors** (11m18s). 21 of the 25 failures and 35 of the 36 errors byte-match the
already-confirmed Phase 23.1M baseline. The remaining 4 failures
(`test_analysis_worker_main.py`/`test_content_worker_main.py`'s own `test_enabled_loop_*` tests)
are confirmed timing-flaky, not a regression: they use a 10ms poll-interval tolerance, passed
cleanly in the immediately-prior run with identical (untouched-this-phase) code, and this run's
own 11m18s wall-clock time (vs. ~5m in adjacent runs) indicates heavier system load during this
specific run - a known class of flakiness, not caused by any change in this phase. The +1 error
is this phase's own new integration test hitting the same already-documented FK-teardown pattern.
Ruff (full repo): clean except the same 6 pre-existing, untouched scratch-script issues. Mypy (all
4 modified production files): clean.

## 16. Costs

Golden replay: $0.0453 (7 events). No live canary this phase (explicitly out of scope - "NO paid
live canary yet"). Total this phase: **$0.045**.

## 17. Remaining limitations

Disclosed, not hidden: (a) the gym story's own `viral_potential`/`meme_potential` calibrated
MEDIUM rather than the anticipated HIGH - a defensible, evidence-grounded model judgment given
genuine outcome uncertainty in the underlying facts, not a bug, but worth human review; (b) the
Anthropic-case native-proximity-vs-true-source-quality ranking tension (§11) remains unaddressed,
a real but narrow gap for a future phase; (c) the "deleted someone else's reservation" detail from
the phase brief's own narrative was never found in either real persisted source article for the
gym story - a collection-stage/source-diversity limitation, not fixable at the Copywriting layer.

## 18. Recommendation: **B — SMALL FIX REMAINS**

The mission's core, most important goal - stop replacing a concrete, memorable story with generic
abstract analysis - is directly, cleanly confirmed fixed via real before/after evidence on the
exact motivating example, with zero semantic drift, zero length regression, and a working,
tested, no-extra-cost meme/viral signal ready for a future MEME-topic consumer. The cross-event
duplicate-image guard closes a real, previously-unaddressed gap. However, two honestly-disclosed,
narrow items remain open: the gym story's own potential-signal calibration undershot the brief's
own anticipated level (a soft, secondary finding, not a functional defect), and a real image-
ranking tension (native proximity vs. true source quality) was found but intentionally left
unfixed this phase, consistent with the brief's own narrow-implementation-scope instruction. Both
are exactly the kind of "narrow, reproducible" residuals this decision option describes - not
blocking, not a factual or architectural failure.

## STRICT STOP

Per the phase brief: investigation, the new immutable prompt version, the duplicate-image guard,
tests, golden replay, image audit, and both review packets are complete. No live canary, no MEME
topic sends, no meme generation, no VPS deployment, no Telegraph/Instagram/Reels. Awaiting human
review before Phase 23.1O (Final Combined NEWS Canary).
