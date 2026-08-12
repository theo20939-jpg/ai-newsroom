# NEWS OUTPUT STABILITY FORENSIC REPORT

Status: **forensic only. No code changed. No prompts edited. No thresholds tuned. No commits. No
deploys.** Produced in response to an explicit forensic-first directive following the video
classification checkpoint. All findings below are traced against real, persisted database rows
(`content_drafts`, `editorial_tasks.workflow.step_results`, `news_event_article_acquisitions`,
`image_candidates`, `story_telegram_delivery`, `news_event_story_links`) and real source files —
never inferred from prose description alone.

## 0. Methodology note (read first — this materially changes how every case below must be read)

**Every real Telegram delivery in this environment came from this session's own canary scripts,
not from a continuously running production service.** This was not assumed — it was established
empirically:

- The dockerized worker stack (`ai_newsroom_automation_worker`, `ai_newsroom_content_worker`,
  `ai_newsroom_news_analysis_worker`, `ai_newsroom_telegram_bot`) is not currently running and has
  no run history overlapping with any of the deliveries analyzed below: `content_worker`'s last run
  was 2026-08-05 21:54–23:57 UTC (predates every code change described as "recent work" in the
  authorizing message), `news_analysis_worker` matches, `automation_worker`'s only recent run
  (2026-08-11 14:15–14:20 UTC) did collection/triage only, produced zero content_drafts, and ended
  in a graceful `CancelledError` (a deliberate stop, not a crash).
- `story_telegram_delivery` contains 57 rows total; 25 of them use the mock chat id `123456789`
  with repeating message ids `999`/`1001`/`2002` across many different drafts and timestamps — the
  unmistakable signature of `AsyncMock()` test bots (this project's own established test
  convention hardcodes the *real* chat id constant for assertion purposes, but never makes a real
  Telegram API call) — these are **test artifacts written into the real dev DB by pytest runs**,
  not real deliveries, and are excluded from all analysis below.
- The remaining 32 rows (chat id `-1004297182444`, message ids `139`–`177`, monotonically
  increasing — the real channel's own message counter) are genuine live sends. **All 32 occurred on
  2026-08-12, between 09:19:58 UTC and 20:11:15 UTC**, and every one of them maps cleanly onto one
  of five canary script runs this session executed (cross-referenced against each run's own
  `canary_start_utc`/`elapsed_s` state and each script file's own `settings.*` overrides, confirmed
  via file mtimes and in-DB timestamps, not guessed):

| Run | Window (UTC) | Script | `copywriting_prompt_version` |
|---|---|---|---|
| "Run 1" | 09:06:17–10:06 | `scripts/_phase23_1q_2h_canary.py` | `"8.5"` (hardcoded) |
| "Run 2" | 13:11:44–14:42 | `scripts/_phase23_1q_2h_canary.py` | `"8.5"` (hardcoded) |
| video-shadow partial run | 15:55:53–16:22 | `scripts/_phase23_1q_video_shadow_canary.py` | `"8.5"` (hardcoded) |
| video-shadow (pre-classification-fix) | 17:13:14–18:28:37 | same script | `"8.5"` (hardcoded) |
| video-shadow (post-classification-fix validation) | 19:33:43–20:18:48 | same script | `"8.5"` (hardcoded) |

- `prompts/copywriting/v8.6.yaml` was written to disk at **14:52:28 UTC** (file mtime) — i.e.
  **after Run 1 and Run 2 had already both finished**, and every canary script that ran afterward
  explicitly hardcoded `settings.copywriting_prompt_version = "8.5"` in-process (each one's own
  comment says "not re-reviewing v8.6 live here" — a deliberate scope-narrowing choice at the time,
  not an oversight, but the practical effect stacks up).

**Conclusion, stated plainly: v8.6 has never been used to generate a single real delivered post.**
Every one of the 32 real deliveries analyzed in this report — including every case the user
flagged — was generated under v8.5. This is not a hypothesis to weigh against alternatives; it is
directly observable in the code that ran. This single fact is the primary, though not sole,
explanation for Case F and materially contributes to Case A.

## 1. Executive summary

- **32 real deliveries reviewed** (the entire real-channel delivery history available in this
  environment; see §10 for full classification).
- **GOOD: 16 (50%)**
- **TEXT_QUALITY_FAILURE only (filler ending, no deeper defect): 10 (31%)**
- **EVIDENCE_FAILURE (headline/evidence mismatch or evidence too thin to justify publication): 3 (9%)**
- **MULTIPLE_FAILURES: 3 (9%)**
- **Approximate severe-failure rate (EVIDENCE_FAILURE + MULTIPLE_FAILURES — the ones a reader would
  call genuinely "bad"): 6/32 ≈ 19%.**
- **Approximate any-defect rate (everything except clean GOOD): 16/32 = 50%**, but this figure is
  dominated by the single, already-fixed-but-never-deployed v8.6 filler pattern (§0) — the
  underlying architecture is not nearly as broken as a 50% raw number suggests.
- **Independent failure classes identified: 8 named (A–H) + 2 additional, discovered during
  this audit** (a missed-duplicate-story pair at §9, and a fully-built-but-never-wired
  `update_not_repeating_root` quality gate at §2.6/§12).
- **Central unifying finding:** a real, already-computed content-quality gate
  (`services/content_draft_service.py::evaluate_content_quality_gates()`, Phase 18.10 M6/M7) is
  **explicitly documented as non-blocking by original design** ("computed and logged for
  visibility, never blocking persistence") — every one of the 8 traced drafts, GOOD and BAD alike,
  shows `quality.passed = False`. This is not itself the root cause of the bad posts (the gate's
  own signal is too noisy to safely enforce as-is — see §12), but it means **no code path in this
  pipeline currently blocks publication based on content quality at all** — the only thing that
  currently blocks publication is `services/editorial_treatment.py`'s SKIP gate, which requires
  weak evidence **and** an explicit keyword-detected negative recommendation simultaneously — a
  narrow intersection that several real bad posts fell outside of for reasons traced case-by-case
  below.

## 2. Case A — Headline/evidence mismatch

**Draft:** `442b7fd2-9078-481f-b13a-f375dc5135ab`, created 2026-08-12 17:52:32 UTC, delivered as
msg 167 (within the pre-classification-fix video-shadow canary window → v8.5).
**Event:** `0527dbc9-23a3-4b37-bbd7-e36a762487d8` — "How much time does AI save at work? New Census
Bureau data breaks it down. - CBS News", sourced from **`Google News: Artificial Intelligence`**
(RSS), `event.url = https://news.google.com/rss/articles/CBMi...` (a Google News redirect link,
not the CBS News URL directly).

**First divergence point: article acquisition.** `news_event_article_acquisitions` row for this
event: `acquisition_status = HEADLINE_ONLY`, `extracted_char_count = 11`,
`raw_extracted_text = "Google News"`. The acquisition layer fetched the Google News interstitial
redirect page itself — never followed through to the real `cbsnews.com` article — and extracted
literally the words "Google News" (11 characters) as the entire article body.

**Everything downstream behaved reasonably given that starting point:**
- Research correctly reported only 2 generic facts and explicitly flagged the gap: *"В
  предоставленном тексте отсутствуют конкретные числовые данные, методология исследования, период
  наблюдения..."*
- Intelligence (`significance=0.58`) correctly recommended caution: *"перед выпуском необходимо
  получить полный текст исследования... Не подавать тему как доказанное массовое повышение
  производительности без этих данных"* — but phrased as a **conditional/hedged** recommendation
  ("recommended for publication as analysis, but get the real data first"), not an unambiguous "do
  not publish."
- `_is_negative_recommendation()` (`services/editorial_treatment.py`) is a fixed keyword matcher
  (`"не публиковать"`, `"не выпускать"`, `"не рекомендуется публиковать"`, `"do not publish"`,
  `"not publish"`, `"do not release"`). Case A's actual recommendation text contains **none** of
  these markers — it contains "к публикации" (recommends *to* publish) and "перед выпуском"
  (before release), neither of which match. **Recomputed directly against
  `classify_editorial_treatment()`: `weak_evidence=True` (HEADLINE_ONLY), `negative_rec=False` →
  treatment = BRIEF**, not SKIP. The unconditional SKIP trigger requires both conditions; only one
  held.
- Copywriting (v8.5) then faithfully reflected the deficient evidence it was given — it did **not**
  hallucinate a number. The headline ("...показывает, сколько времени ИИ экономит...") was
  generated from the event's own *title* (which itself already overclaims relative to the 11
  characters of real body text available), and the body/ending correctly stated the numbers were
  undisclosed. This is copywriting behaving correctly on bad input, not copywriting introducing the
  defect.

**Root cause:** the acquisition failure (Google News redirect never resolved to the real article)
is the first wrong decision. A secondary, independent contributor: no stage in this pipeline checks
whether a *headline* (generated from the event's own title, before Research/Copywriting ever
touch it) makes a stronger factual claim than the *body's own evidence* supports — this is a real,
missing check, not merely a consequence of the acquisition failure (see §12).

**Scope check:** `news_event_article_acquisitions.effective_completeness_status = HEADLINE_ONLY`
occurs **23 times in the entire dataset — every single one from a Google-News-named RSS source**
("Google News RU": 16, "Google News: Artificial Intelligence": 7). This is a 100% clean, systemic,
reproducible pattern, not a one-off.

**Files involved:** `services/article_acquisition.py` (acquisition/redirect handling — needs
investigation of Google News URL resolution), `integrations/http/safe_fetch.py` (the underlying
fetcher), `services/editorial_treatment.py::_is_negative_recommendation()` (keyword-only, cannot
parse hedged/conditional recommendations).
**Ruled out:** Story Memory (not involved — new_story), quote pipeline (no quote), image pipeline
(image candidates were themselves poor quality but that is a separate, minor contributor, not the
headline defect), fact_safety (shadow mode only, see §12).
**Severity: BLOCKER** (a factually misleading headline reached a real reader).

## 3. Case B — Insufficient-evidence NEWS passed publication

**Draft:** `00dcb70d-db56-48e6-bf3a-67f7cb64fbcc`, created 2026-08-12 20:11:14 UTC, delivered as msg
177 (within the post-classification-fix validation canary window → v8.5).
**Event:** `4268324c-77ca-4db8-a797-aaacaf666fb9` — CNET, "An AI Agent Reportedly Hacked a Gym to
Get Someone Into a Class."

**Full chain:** unlike Case A, acquisition here **succeeded completely** —
`effective_completeness_status = FULL_TEXT`, `extracted_char_count = 7292`, a real, full CNET
article body was fetched. Research correctly extracted the two facts the article itself contains
(agents sometimes take extreme measures; the headline's own claim) and explicitly flagged the real
gap: *"Основной текст не сообщает, какой именно ИИ-агент... какой спортзал... когда... что именно
означает «взломал»"* — this is not a Research extraction failure; the source article genuinely
does not contain these details (CNET's own piece is itself reporting on an unconfirmed viral claim,
not an investigated story). Intelligence (`significance=6`, `evidence_completeness=FULL_TEXT` →
**not** in `_WEAK_COMPLETENESS_STATUSES`, so `weak_evidence=False`) recommended: *"Можно публиковать
как короткую новость... Не следует подавать случай как установленный факт"* — again does not match
the negative-recommendation keyword list ("не следует" ≠ "не публиковать"). Recomputed treatment:
**STANDARD** (medium significance, evidence not flagged weak). Copywriting (v8.5) actually followed
the spirit of Intelligence's recommendation reasonably well — the delivered body explicitly uses
"по сообщениям"/hedges every unconfirmed detail, and does not overclaim beyond what CNET itself
reported.

**Root cause — genuinely different in kind from Case A:** this is **not a mechanical pipeline
defect**. Acquisition worked, Research was accurate, Intelligence's judgment was defensible,
Copywriting followed instructions. The actual gap is architectural: `evidence_completeness`
(`HEADLINE_ONLY`/`PARTIAL_TEXT`/`FULL_TEXT`/`FETCH_FAILED`) measures **whether the full article text
was fetched**, not **whether the underlying event has enough independently-verified concrete facts
to justify a NEWS post at all**. A fully-fetched article that is itself reporting on an
unconfirmed social-media claim registers as "not weak evidence" by this metric, even though the
*event itself* — not the acquisition process — is thin. This is the deeper form of the question the
user asked ("is this too weakly evidenced to deserve NEWS status at all") — and the honest answer
is: **the pipeline has no signal that measures this**, only a proxy (fetch completeness) that
happens to correlate with it in some cases (Case A) but not others (Case B).

**Files involved:** `services/editorial_treatment.py::_is_weak_evidence()` (evidence-completeness
proxy, no fact-density signal exists to complement it).
**Ruled out:** acquisition (succeeded), Research (accurate given real source content), Copywriting
(followed the hedge instruction).
**Severity: MEDIUM** (a defensible, hedged short post about a genuinely viral, appropriately-caveated
claim — not misleading, but a legitimate product-policy question about whether it belongs in NEWS
at all).

## 4. Case C — UPDATE repeats root

**Root:** draft `5f4a0459-3b91-4813-9d25-92946d736de7`, event `1af5bed3-6b5c-4e4d-a24c-c0a7a473eeae`
(Telegram source, `t.me/rozetked/27125`), delivered msg 144, 2026-08-12 13:51:00 UTC → v8.5, **before**
this session's own media-quality corrective-phase edit to `worker/content_cycle.py` (saved 16:38:31
UTC) — root has **zero** `image_candidates` rows (`image_intelligence.candidates_discovered=0`,
`article_fetch_attempted=false`) and was delivered **text-only**. Case E does not apply to the root.
**UPDATE:** draft `94fa4891-58ec-4819-b8f7-5134c8ba3c09`, event
`b1687aa3-de8f-4a9f-9427-ebd826dd8e2a` (9to5google.com), delivered msg 174 as a `reply`,
2026-08-12 20:10:55 UTC → v8.5, **after** the corrective-phase fix.

**Story Memory classification was correct**, not the defect: `NewsEventStoryLink` for the update
event shows `match_type = story_update`, `match_score = 0.8`, correctly linked to the same
`Story` row the root belongs to (`story.event_count = 4`).

**Root cause, precisely located:** `is_story_update` (the one and only place `story_update`
classification is consumed anywhere in the content-generation path,
`services/content_draft_service.py:346`) is computed and persisted onto a `ContentDraftStoryLink`
row **after** the draft has already been generated — it exists purely to drive Telegram
reply-routing, never as an input to Copywriting. Grepping the entire copywriting/content-generation
call chain (`capabilities/copywriting_capability.py`, `services/content_draft_service.py`,
`scripts/run_content_generation.py`) for any root-headline/root-body/delta signal being passed into
generation returns **nothing** — Copywriting for the update event runs through the **exact same
code path as a completely independent, unrelated CONTENT_GENERATION run**. It never receives the
root post's text, never receives a list of "already-covered facts," and has no way to know this is
an update at all. This directly and completely answers the user's own diagnostic question: the
copywriter had access to **none** of {root headline, root body, previously-known facts, explicit
delta}.

**Approximate factual overlap (root vs. update):** phone name — 100% overlap; price (root: "9999
юаней — около 123 тысяч рублей"; update: "около $1500", i.e. the identical figure in a different
currency, presented as if new) — effectively 100% redundant; mechanical/robotic-camera design
concept — root's "четырёхосевая стабилизированная конструкция" and update's "механический подвес"
describe overlapping physical mechanisms in different words, ~70–80% conceptual overlap. The one
genuinely new fact: **availability status** (root = announcement; update = now launched, available
in China, not available in most other countries) — real, but occupies roughly the last third of the
update's three sentences, with the first two-thirds restating already-published information.

**A directly relevant mechanism already exists and is unused:** `services/content_quality_gates.py`
defines `check_update_not_repeating_root(body, is_update, root_body)` — built specifically for this
exact failure mode (Phase 18.10 M6/M7), computing `token_overlap_ratio(body, root_body) <
_UPDATE_ROOT_REPETITION_THRESHOLD (0.6)`. It is included in `QualityGateReport` and
`evaluate_content_quality_gates()`'s signature (`is_update: bool = False`, `root_body: str | None =
None`). **`content_draft_service.py`'s actual call site never passes either parameter** — both
silently default (`is_update=False`), so `check_update_not_repeating_root()` trivially returns
`True` (pass) on every single draft, update or not, real repetition or not. Worse: the call to
`evaluate_content_quality_gates()` happens at line 300, **before** the `story_link` lookup that
would supply `is_update` even exists in the function (that lookup happens later, at line 336) — the
data needed to wire this correctly is not yet available at the point where it would need to be
passed, a genuine ordering gap, not just a missing argument.

**Determination:** the failure is **prompt/context assembly** (no delta ever constructed or passed)
— compounded by a **dead, already-built quality-gate check that could catch this class of defect
today with a narrow wiring fix** (see §13, WIRING ONLY). It is not Story Memory (correct), not
delta extraction (never attempted at all — there is no delta-extraction step anywhere in this
codebase to fail), and not fundamentally a Copywriting quality problem (Copywriting cannot write a
delta-focused update when given zero delta signal).

**Files involved:** `services/content_draft_service.py` (`is_story_update` computed too late,
`evaluate_content_quality_gates()` call missing `is_update`/`root_body`), `services/story_memory.py`
(correct, not at fault), `services/content_quality_gates.py::check_update_not_repeating_root()`
(exists, unwired), `capabilities/copywriting_capability.py`/`prompts/copywriting/*.yaml` (no
UPDATE-specific input schema or instruction exists at all).
**Severity: HIGH** (undermines the entire purpose of reply-threaded updates — a reader following the
thread gets no new information for two-thirds of the reply).

## 5. Case D — Bad/meaningless quote

**Draft:** `894cf848-63c8-4bfb-8379-476394a1e203`, event `b8906ab4-7a1a-428f-bbef-c39fec256ba1` (BBC),
delivered msg 162, 2026-08-12 17:51:44 UTC → v8.5.

**Quote provenance, reconstructed exactly:**
- `content_draft_quotes` row: `quote_text = "thoughtfully reviewing"`, `speaker = "Discord"`,
  `translated_text = "вдумчиво рассматривает"`.
- Real source sentence (event's own RSS excerpt, `news_events.content`): *`Discord told the BBC it
  was "thoughtfully reviewing" the order by Brazil's data protection agency and it was "committed to
  user safety"`.*

**Answers to the user's specific questions:**
1. **Is this text verbatim from the source?** Yes — "thoughtfully reviewing" appears character-for-
   character inside the real BBC-sourced RSS excerpt, inside quotation marks in the original.
2. **What surrounding sentence/context existed?** A full sentence: *"Discord told the BBC it was
   'thoughtfully reviewing' the order... and it was 'committed to user safety'"* — a much longer,
   coherent statement than the two words that were extracted.
3. **Was it extracted as a fragment?** Yes — only the first of two quoted clauses in that sentence
   was pulled, and only the quoted words themselves, dropping the subject ("Discord"/"it") and verb
   framing that would make it read as a complete thought.
4. **Was it translated/paraphrased?** Translated faithfully (a verb phrase mapped to a verb phrase);
   not paraphrased, not fabricated.
5. **Why was "Discord" assigned as speaker?** Correctly — the source sentence itself attributes the
   quote to Discord (a corporate spokesperson statement, not a named individual), so "Discord" is an
   accurate, not a placeholder, attribution.
6. **What validator allowed it?** `services/quote_verification.py::verify_quote()` — confirmed via
   direct code read to do exactly one thing: fuzzy-match the quote text against the source content
   (`services/text_normalization.py::fuzzy_phrase_contains`). It has no concept of standalone
   grammatical or semantic completeness — a verbatim two-word fragment passes this check exactly as
   readily as a complete sentence would, because completeness was never in its scope.
7. **Does the existing quote quality layer evaluate grammatical/semantic completeness, attribution
   confidence, standalone usefulness, length, or editorial value?** No.
   `services/content_quality_gates.py::check_quote_has_attribution()` checks only that `speaker` is
   non-empty and not a generic placeholder ("someone"/"a person"/"unknown") — it passed, correctly,
   since "Discord" is a real, specific attribution. **No gate anywhere in this codebase evaluates
   whether an extracted quote reads as a complete, standalone, editorially meaningful statement.**
   This is a real, missing capability, not a bug in an existing one.

**Root cause:** the extraction/translation/attribution mechanism worked exactly as designed and
produced a technically correct result — verbatim, correctly attributed, real quote. The defect is
that **"technically attributable and verbatim" was treated as sufficient for publication**, because
no downstream check ever asks the different, harder question: "does this read as something on its
own, without needing the sentence I removed it from?" This is the user's own stated principle,
directly confirmed by evidence: a technically attributable fragment is not automatically a
publishable quote, and this codebase currently has no mechanism that would catch it.

**Files involved:** `services/quote_verification.py` (verbatim-match only, working as designed but
insufficient), `services/content_quality_gates.py::check_quote_has_attribution()` (attribution-only,
correctly passed), `capabilities/copywriting_capability.py` (the LLM call that selected this
particular fragment length — the underlying extraction decision itself is inside the LLM's own
output, not separately inspectable code).
**Ruled out:** attribution mechanism (correct), verbatim-match mechanism (correct, working as
designed), translation (accurate).
**Severity: MEDIUM** (reads as broken/unprofessional in isolation, but is not misleading or false).

## 6. Case E — Duplicate media (Honor Robot Phone)

**Established first (per the explicit instruction not to assume): which draft, before or after the
fix?** The Honor **root** post (§4) has zero image candidates — text-only, no media group exists to
audit. **The duplicate images the user observed can only be the Honor UPDATE's media group**
(draft `94fa4891-...`, delivered 20:10:55 UTC, generated using code saved at 16:38:31 UTC —
**confirmed AFTER** the media-quality corrective-phase fix was active). This is a genuine post-fix
finding, not a stale pre-fix artifact.

**Full per-candidate trace** (`image_candidates` rows, `content_draft_id = 94fa4891-...`):

| rank | eligible | quality | dims | sha256 (short) | phash | warnings |
|---|---|---|---|---|---|---|
| 1 | True | 96 | 3000×1500 | `c5436e6...` | `a0bab2b23ababa30` | none |
| 2 | True | 88 | 1200×628 | `063630...` | `a0b8b0b07838b820` | none |
| 3 | True | 56 | 96×96 | `804373...` | `514d4d4c6931e5f2` | `possible_avatar` |
| — | False | — | — | — | — | (unresolvable duplicate) |
| — | False | 90 | 1600×800 | `834540...` | `a0bab2b23ababa30` | (excluded — exact `duplicate_exact` match) |

- **Rank 3 (96×96 avatar)** is correctly excluded from the additional-image slot by this session's
  own `_meets_additional_album_image_bar()` fix (`worker/content_cycle.py`) — WEAK/ICON resolution
  band. This part of the fix is working.
- **Rank 1 and rank 2 URLs are the identical source photo, resized by WordPress:**
  `.../honor-robot-phone-2.jpg?quality=82&strip=all` (3000×1500, the original) vs.
  `.../honor-robot-phone-2.jpg?resize=1200%2C628&quality=82&strip=all&ssl=1` (1200×628, an explicit
  `?resize=` variant of the *same filename*). Different bytes (different `sha256`, since resizing
  changes the file), but visually the same picture.
- **Computed Hamming distance between rank 1 and rank 2's perceptual hashes: `hamming_distance("a0bab2b23ababa30", "a0b8b0b07838b820") = 9`** — well above the existing calibrated
  `_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE = 4` threshold. The dedup mechanism computed this
  correctly, correctly did not flag them as duplicates **per the existing threshold**, and both
  candidates cleared the resolution/branding bar — so both were selected into the media group. This
  is exactly what a human viewer would call "near-duplicate images" in the album.

**Determination (matching the user's own enumerated categories exactly):** **not** a stale
pre-fix delivery (confirmed post-fix), **not** missing hash generation (`sha256`/`perceptual_hash`
were both present and correctly propagated for every candidate), **not** a ranking bug (ranking
correctly selected the two highest-quality eligible images given its inputs) — it is **"perceptual
hash insensitive to this resize/crop case."** A same-source image served through multiple
CDN-generated `?resize=` variants is common enough (WordPress's own responsive-image convention)
that a Hamming distance of 9 at *this specific resize ratio* (3000×1500 → 1200×628, a ~2.5×
downscale) should be treated as evidence the current `<=4` threshold is calibrated too tightly for
this real, recurring pattern — not that the mechanism is broken.

**Files involved:** `services/media_ranking.py::_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE`,
`worker/content_cycle.py::_compute_within_event_duplicate_flags()` (both working exactly as
designed; the constant is the only thing implicated).
**Severity: MEDIUM** (a real, visible product-quality defect, but narrowly scoped to one threshold
value with concrete before/after evidence already in hand — no redesign needed).

## 7. Case F — Uncertainty filler still present

Already substantially answered by §0. Direct answers to the user's six numbered questions,
applied to Case A's own draft as a representative example (and confirmed identically across all 32
real deliveries, not just this one):

1. **Was v8.6 actually used?** No.
2. **Is production/canary configuration still selecting v8.5?** Yes — every canary script that ran
   after v8.6 was created explicitly hardcodes `settings.copywriting_prompt_version = "8.5"` in
   process, by deliberate choice at the time each was written ("not re-reviewing v8.6 live here").
3. **Were old drafts generated under v8.5 delivered after v8.6 existed?** Yes — the entirety of
   the 15:55–20:18 UTC window (video-shadow partial run + both video-shadow canaries) ran under
   v8.5 despite v8.6 having existed on disk since 14:52 UTC.
4. **Is v8.6's semantic rule still too permissive?** Cannot be determined — it has never been
   exercised against real live traffic. (Unit tests exist —
   `tests/test_copywriting_v86_uncertainty_fix.py` — but that is a different question from live
   behavior against real, messy source material.)
5. **Is another stage appending a separate uncertainty ending?** No evidence of this — every
   filler ending traced back directly to the single `ending` field in the v8.5 structured
   copywriting output; no second, deterministic uncertainty-appending stage was found anywhere in
   `services/news_telegram_presentation.py`, `bot/formatting.py`, or the render path.
6. **Is deterministic post-processing involved?** No — confirmed by direct code read of the
   rendering path; the `ending` field is rendered as-is.

**The US AI-productivity post (Case A) is explicitly noted, per the user's own instruction, as
exposing a more serious problem than style** — see §2; its filler ending is a symptom of the same
acquisition failure that also produced the headline mismatch, not an independent defect.

**Files involved:** `prompts/copywriting/v8.6.yaml` (exists, correct, unused), every
`scripts/_phase23_1q_*canary.py` (hardcode v8.5), `core/config.py` (default is `"4"`, unrelated to
this finding — no canary run relied on the default).
**Severity: HIGH** (this is not a prompt-quality problem — it is a deployment/activation gap; the
fix already exists in the repository).

## 8. Case G — NINJA PULSE Telegram link preview

**Code-inspection case** (confirmed by direct grep of every Telegram-send call site — no matches
anywhere in the codebase for `LinkPreviewOptions`, `link_preview`, or
`disable_web_page_preview`): `services/telegram_routing.py`'s three send functions
(`send_to_editorial_destination`, `send_photo_to_editorial_destination`,
`send_media_group_to_editorial_destination`) never set any link-preview parameter on any
`bot.send_*()` call. Confirmed against the installed aiogram version (3.29.1):
`Bot.send_message()` accepts `link_preview_options: LinkPreviewOptions | Default | None` (the
modern API; `disable_web_page_preview` is the deprecated predecessor, both present in the
signature).

**Per delivery mode:**
- **Text-only NEWS** (`bot.send_message()`): affected — Telegram's own default behavior is to scan
  the message text for the first URL and generate a preview card for it. The NINJA PULSE footer's
  `<a href="https://t.me/nnjvpn">` is the only link in the message body for the majority of
  text-only sends (the source URL itself is never embedded in the text, only as an inline button),
  so Telegram expands **that** link into the large NINJA VPN channel preview card.
- **Single-photo** (`bot.send_photo()`) and **media-group** (`bot.send_media_group()`): **not
  affected** — this is standard, long-established Telegram Bot API platform behavior, not something
  this codebase controls: link previews are only ever generated for text messages, never for photo
  or media-group captions, regardless of any parameter. Confirmed by inspecting the aiogram
  `InputMediaPhoto`/`InputMediaVideo` types, neither of which exposes a link-preview field at all
  (consistent with Telegram's own API never offering one for captions).
- **UPDATE reply:** same mechanism as whichever underlying send type (text/photo/media-group) the
  update uses — no separate code path.

**Smallest fix (not implemented, per instruction):** pass
`link_preview_options=LinkPreviewOptions(is_disabled=True)` to the one `bot.send_message()` call
inside `send_to_editorial_destination()` — a single-parameter, single-call-site change. No other
send function needs it, since the platform itself never generates previews for captions.

**Files involved:** `services/telegram_routing.py::send_to_editorial_destination()`.
**Severity: MEDIUM** (visually disruptive on every text-only post — and text-only posts are common,
see §10 — but not a correctness/safety issue).

## 9. Case H — BAD_GARBAGE.c / low-content article

**Draft:** `6102059f-d1a7-412e-bd7b-2556cfbc2f5e`, event
`31866577-4d67-401b-a177-eebeb8b074ce` (LinkedIn Pulse article, discovered via Lobsters RSS),
delivered msg 172, 2026-08-12 19:40:47 UTC → v8.5.

**First divergence point, more insidious than Case A's:** `effective_completeness_status =
FULL_TEXT`, `extracted_char_count = 20000` (the extraction cap) — the acquisition layer reports
**success**, with a large amount of text. The actual `raw_extracted_text`, read directly: *"BAD_
GARBAGE.c: The AF_UNIX Container Escape That Resurrected Twice - Part I \n LinkedIn respects your
privacy \n LinkedIn and 3rd parties use essential and non-essential cookies to provide, secure,
analyze and improve our Services... Accept / Reject..."* — **this is LinkedIn's cookie-consent
banner and site chrome, not the article.** LinkedIn's real article content requires a login/consent
wall that a basic HTTP fetch cannot get past; the fetcher captured 20,000 characters of boilerplate
and reported it as a full-text success.

**Consequence, traced precisely through `editorial_treatment.py`:** because
`effective_completeness_status = FULL_TEXT` (not a member of `_WEAK_COMPLETENESS_STATUSES`),
`_is_weak_evidence()` returns **False** — the evidence-completeness signal was fooled by the
boilerplate into reporting high confidence. Intelligence's own recommendation, independently and
correctly, states *"Не публиковать как полноценную новость без дополнительной проверки"* — this
**does** match `_NEGATIVE_RECOMMENDATION_MARKERS` ("не публиковать" is literally on the list), so
`negative_rec = True`. **The unconditional SKIP trigger requires `weak_evidence AND negative_rec` —
one of the two inputs was wrong (due to the boilerplate misclassification), so despite Intelligence
correctly saying "do not publish," the SKIP gate never fired.** Recomputed treatment: **BRIEF, with
`human_review_required=True`** — but per `EditorialTreatmentDecision`'s own docstring, "nothing
reads it to block anything" — the flag is inert metadata with no enforcement mechanism behind it.
`fact_safety` (shadow mode) independently and correctly flagged `status="block"`,
`highest_risk="high"` for this draft — also inert, by the same design (§12).

**Determination:** this is a genuine **article-acquisition content-validity failure** — the
acquisition layer has no check for whether extracted "full text" is actually substantive article
prose versus boilerplate/consent-wall/paywall interstitial content. This is a distinct failure mode
from Case A (Case A silently got almost nothing and was correctly flagged `HEADLINE_ONLY`; Case H
got a large amount of *wrong* content and was incorrectly marked as a complete success) — Case H is
arguably more dangerous precisely because it defeats the `HEADLINE_ONLY` safety signal that would
otherwise have caught it.

**Scope check:** 19 acquisitions in the entire dataset hit exactly the 20,000-character extraction
cap. Only this one was manually confirmed to be boilerplate; the other 18 were not individually
audited in this pass (see §14 — a targeted audit of all 19 is a cheap, valuable next step).

**Files involved:** `services/article_acquisition.py` (HTML-to-text extraction — no boilerplate/
consent-wall detection exists), `services/editorial_treatment.py::_is_weak_evidence()` (correctly
designed, but trusts an upstream signal that can be fooled).
**Ruled out:** Intelligence (correctly recommended against publication), fact_safety (correctly
flagged high risk, just not enforced — see §12), Story Memory (not implicated).
**Severity: BLOCKER** (a post was generated and delivered with literally zero real source content,
and the one internal signal that explicitly said "do not publish this" was overridden by a
boilerplate-fooled upstream flag).

## 10. Good-vs-bad comparative sample

**Methodology:** all 32 real deliveries (§0) were reviewed — the full available real-delivery
population, not a subsample. The 8 named cases plus 2 named controls (Google Pixel/Made by Google,
Sergey Brin/Gemini — both explicitly cited as good by the user) received full pipeline traces
(§2–§9, this section). The remaining 22 received a lighter-touch review: full title/body text
inspection for headline-evidence consistency, filler-ending patterns, and cross-referencing against
`image_candidates`/`story_telegram_delivery` for any additional duplicate-story or media issues
noticed along the way (§9 discovered one this way, reported below).

| msg | Title (abbreviated) | Classification |
|---|---|---|
| 139 | Kyoto Fusioneering fusion-fuel prototype | TEXT_QUALITY_FAILURE |
| 140 | Abbott + Google Health glucose monitoring | TEXT_QUALITY_FAILURE |
| 141 | Craft Ventures $1B fund | TEXT_QUALITY_FAILURE |
| 142 | Chinese robot dogs for Moon base | GOOD |
| 143 | Ad agencies disable Meta AI | GOOD |
| 144 | Honor Robot Phone (root) | GOOD |
| 145 | Sber "first Russian autonomous AI agent" | EVIDENCE_FAILURE |
| 146 | Thrive Holdings $2B raise | TEXT_QUALITY_FAILURE |
| 147 | WhatsApp Scam Alert | TEXT_QUALITY_FAILURE |
| 148 | Chrome Android blocks 7B notifications | GOOD |
| 149 | Pixel 11 Pro AI Pro access cut | GOOD |
| 151 | Pixel 11 Gboard Rambler | TEXT_QUALITY_FAILURE |
| 153 | Anti-Flock account monitoring | GOOD |
| 154 | CodeRabbit $143M raise | GOOD |
| 157 | Grok 4.6 vs. OpenAI/Anthropic | GOOD |
| 159 | DeepMind sign-language model | TEXT_QUALITY_FAILURE |
| 160 | Pixel 11 extreme charging | GOOD |
| **161** | **Google Pixel 11 / Made by Google (control)** | **GOOD** |
| 162 | Discord Brazil livestream order | **MULTIPLE_FAILURES** (QUOTE + TEXT_QUALITY) |
| 163 | Grok 4.6 for long agent tasks | GOOD |
| 164 | CD Projekt/Project Sirius layoffs (#1) | TEXT_QUALITY_FAILURE — *see note below* |
| 166 | Pixel 11 pre-event preview | GOOD |
| **167** | **US Census AI productivity data** | **MULTIPLE_FAILURES** (EVIDENCE + TEXT_QUALITY) |
| 168 | Grok 4.6 pricing | GOOD |
| 169 | Medvedev backs AI in schools | TEXT_QUALITY_FAILURE |
| 170 | Meta child-safety lawsuit, $1.4T | GOOD |
| **171** | **Sergey Brin / Gemini reshuffle (control)** | **GOOD** (borderline — see note) |
| **172** | **BAD_GARBAGE.c** | **EVIDENCE_FAILURE** |
| 173 | CD Projekt/Project Sirius layoffs (#2) | GOOD — *see note below* |
| **174** | **Honor Robot Phone (UPDATE)** | **MULTIPLE_FAILURES** (UPDATE + MEDIA) |
| 176 | Pixel Tag $29 | TEXT_QUALITY_FAILURE |
| **177** | **AI agent "hacked" a gym (Case B)** | **EVIDENCE_FAILURE** |

**Counts:** GOOD = 16, TEXT_QUALITY_FAILURE = 10, EVIDENCE_FAILURE = 3, MULTIPLE_FAILURES = 3.
UPDATE_FAILURE/QUOTE_FAILURE/MEDIA_FAILURE/PRESENTATION_FAILURE never occur in isolation in this
sample — each co-occurs with another defect where found (162, 167, 174), reflected under
MULTIPLE_FAILURES. PRESENTATION_FAILURE (Case G) is a systemic, config-level defect affecting
essentially every text-only send equally, not a per-post discriminator — reported separately (§8)
rather than inflating individual post classifications.

**Notable discovery made during this pass, not one of the 8 named cases:** msg 164 and msg 173 are
about the **same real-world event** (CD Projekt's Project Sirius layoffs) — msg 164 is vague ("another
round of layoffs"), msg 173 (3 hours later) gives the confirmed specific figure (18 people, >20% of
the team). Checked directly: `NewsEventStoryLink` for both events shows **two different `story_id`
values, both classified `match_type = new_story`** — Story Memory never linked them to each other
at all. Two independent "root" posts about the identical underlying news went to the same channel
three hours apart. This is a close cousin of Case C (same *symptom family* — redundant coverage of
one event) but a **different mechanism**: not "update repeats root" but "story-linking missed the
match entirely," so no update/reply relationship was ever established in the first place. msg 173
is individually a well-evidenced, good post; the defect is at the story-deduplication layer, not in
either post's own text.

**Good_Brin (msg 171) borderline note:** its own `quality` step flagged a real, minor issue —
*"В исходном заголовке указано, что Брин призвал ключевых сотрудников... в черновике это сужено до
всей команды Google"* — the delivered headline ("призвал команду Google" — "called on the Google
team") is a mild broadening of the source's own "key AI staff" framing. Small in degree (nowhere
near Case A's zero-evidence headline), but structurally the *same kind* of headline-precision issue,
worth noting as evidence this is not purely a one-off.

## 11. Effective configuration matrix

| Setting | Code default | `.env` | In-process canary override (all 5 real-delivery runs) | Effective value for every real delivery in this dataset |
|---|---|---|---|---|
| `copywriting_prompt_version` | `"4"` | not confirmed this pass | `"8.5"` (hardcoded in every canary script that ran) | **`"8.5"`, always** |
| `editorial_delivery_mode` | (not this session's focus) | — | `"router"` | `"router"` |
| `story_memory_mode` | `"off"` | — | `"shadow"` | `"shadow"` |
| `telegram_story_reply_mode` | `"off"` | — | `"enforce"` | `"enforce"` |
| `quote_telegram_rendering_mode` | `"off"`/`"shadow"` (varies by prior session state) | — | `"enforce"` | `"enforce"` |
| `image_intelligence` mode (shadow M1–M4 discovery inside copywriting) | — | — | `"shadow"` | `"shadow"` (informational only — real selection uses the separate `image_candidates` table, not this block) |
| `video_discovery_mode` | `"off"` | — | `"shadow"` (video-shadow runs only) or `"off"` (Run 1/2) | mixed, not relevant to any of Cases A–H |
| `fact_safety_mode` | (three-state) | — | `"shadow"` (confirmed per-draft, `mode: "shadow"` field inside every `quality.fact_safety` block) | `"shadow"`, always — **never enforced, by original design** |
| content-quality gate (`evaluate_content_quality_gates`) | non-blocking by original Phase 18.10 design (`content_draft_service.py`'s own comment: "computed and logged for visibility, never blocking persistence") | n/a — not settings-gated at all, it is architecturally always non-blocking | n/a | **always non-blocking, unconditionally, regardless of any setting** |
| Telegram link-preview handling | none set anywhere (§8) | n/a | n/a | Telegram's own server-side default (auto-preview first URL found) |

**Critical distinction the user asked to be made explicit:** the current config for a post
generated *today* would be identical to what generated every post in this dataset, **because no
canary run since 14:52 UTC has changed which prompt version it selects** — this is not a stale
snapshot from an old run; it is the *current, still-true* effective configuration for the next
canary someone runs with these same scripts, unless the scripts themselves are edited.

## 12. Root-cause clustering

**Investigated directly, per the user's explicit instruction, whether uncertainty filler +
evidence-poor posts + headline mismatch are one deeper weakness rather than three unrelated
problems.**

They are **two** clusters, not one and not three:

**Cluster 1 — evidence-completeness signal can be fooled or is absent entirely (Cases A, H, and
contributes to B).** `NewsEventArticleAcquisition.effective_completeness_status` is the *only*
signal `editorial_treatment.py` uses to judge evidence weakness (when available), and it can be
wrong in two opposite directions found in this dataset: it can correctly detect near-total absence
(Case A, `HEADLINE_ONLY`) but the pipeline's own recommendation-detection is too narrow (keyword-
only) to catch a hedged-but-real "don't trust this yet" signal; or it can be actively fooled into
reporting `FULL_TEXT` success on pure boilerplate (Case H), silently disabling the weak-evidence
path entirely regardless of how explicit Intelligence's own negative recommendation is. Case B
shows the same signal's blind spot from a third angle: a fully-fetched article can itself be
evidence-thin at the fact level, and `FULL_TEXT` cannot distinguish "thin because we couldn't get
the article" from "thin because the article itself reports on an unconfirmed claim."

**Cluster 2 — v8.6 never shipped to a real delivery (Case F, and the *style* dimension of Case A,
D — narrower than Cluster 1).** This is a pure deployment/activation gap, unrelated in mechanism to
Cluster 1 — it is not that the pipeline lacks a fix, it is that the fix that already exists was
never exercised outside canary scripts that deliberately excluded it.

**These two clusters are independent — Case A is the one case in this dataset where they visibly
overlap** (its filler ending is Cluster 2's symptom; its headline/body mismatch and its failure to
be caught by the publish gate are Cluster 1's). This overlap does not mean they are the same root
cause; fixing Cluster 2 alone would not have prevented Case A's headline defect, and fixing Cluster
1 alone would not have removed Case A's filler style (though a properly weak-evidence-gated Case A
likely would have been SKIPped or downgraded enough that the filler ending would never have shipped
at all).

**Case C (UPDATE repetition) investigated separately, per instruction, for whether it is
copywriting-only or a missing-delta problem:** conclusively the latter (§4) — there is no delta
extraction stage anywhere in this codebase to have failed; the gap is that Story Memory's correct
classification is never threaded into Copywriting's input at all, and a purpose-built quality gate
that could catch the *symptom* even without a delta (`check_update_not_repeating_root`) is fully
implemented but never called with real arguments.

**A third, smaller cluster worth naming explicitly:** the content-quality and fact-safety gates
(§0 executive summary) are **real, already-computed, often-accurate diagnostic signals that are
architecturally incapable of blocking anything, by original design, and — critically — are not
currently precise enough that blocking on them naively would be safe** (`quality.passed=False` and
`fact_safety.status="block"` both fire on the Good_Pixel and Good_Brin controls too, driven
substantially by a "Body is None" check that fires unconditionally on every V8-family draft — a
timing artifact, not a real signal — and an entity-level fact-checker that flags bare terms like
"ИИ" as "unsupported" with implausible frequency). Simply flipping these to enforce mode today
would very likely block a large fraction of genuinely good posts alongside the bad ones. This
cluster is a precondition for eventually reusing these signals productively, not a root cause of
any individual case above.

## 13. Proposed remediation sequence

**Not implemented.** Labeled per the user's taxonomy; prioritized P0 (correctness/unsafe
publication) → P1 (severe quality/UX) → P2 (polish); earlier semantic-boundary fixes preferred over
downstream filters throughout.

**P0**

1. **[WIRING ONLY]** Wire `check_update_not_repeating_root()` in `content_draft_service.py`:
   move the `story_link` lookup before the `evaluate_content_quality_gates()` call, fetch the real
   root `ContentDraft.body` when `story_link.match_type` indicates an update, and pass
   `is_update=`/`root_body=` through. The check already exists; only the call site needs the two
   missing arguments and a reordering. (Case C)
2. **[PROMPT VERSION]** Point every canary/production entry point that currently hardcodes
   `copywriting_prompt_version = "8.5"` to `"8.6"` for the *next* live validation run — a one-line
   change per script, already-authored, already unit-tested. (Case F, and contributes to A)
3. **[NARROW FIX]** Article acquisition: detect and reject Google-News-redirect URLs as
   non-terminal (either resolve the real redirect target before fetching, or classify the result as
   `HEADLINE_ONLY`/`FETCH_FAILED` rather than silently extracting the interstitial page's own
   11-character text as if it were article content — the second half of this is arguably already
   correct; the real fix is resolving the redirect). Scope: 23/23 real `HEADLINE_ONLY` rows in this
   dataset, a clean, 100%-reproducible target. (Case A)
4. **[NARROW FIX]** Article acquisition: add a lightweight boilerplate/consent-wall detector (e.g.
   presence of cookie-consent/GDPR-notice phrase patterns combined with extraction hitting the
   truncation cap) that downgrades `effective_completeness_status` away from `FULL_TEXT` when the
   extracted text is very likely not real article prose. Scope: at minimum the one confirmed case
   (Case H); 18 other 20,000-character extractions in this dataset are unaudited and should be
   spot-checked before this is scoped further. (Case H)
5. **[POLICY / PRODUCT DECISION]** Decide whether `_is_negative_recommendation()`'s keyword-only
   detection is sufficient, or whether Intelligence's `recommendation` field needs a structured,
   explicit boolean signal (e.g. a dedicated `should_publish_without_further_verification: bool`
   field in the Intelligence schema) rather than relying on free-text keyword matching that misses
   hedged/conditional negative recommendations like Case A's. (Cases A, B)

**P1**

6. **[NARROW FIX]** Loosen `_NEAR_DUPLICATE_MAX_HAMMING_DISTANCE` from `4`, calibrated specifically
   against the real evidence in this report (distance 9 for a confirmed same-source, differently-
   resized image pair) — recommend gathering 3–5 more real same-source/different-resize pairs before
   picking a new number, per the user's own "do not increase the threshold without evidence"
   instruction; this report supplies the first data point, not a full calibration set. (Case E)
7. **[NEW CAPABILITY]** A standalone-quote-quality check (length floor, presence of a finite verb/
   subject, not merely a fuzzy-matched fragment) added to `content_quality_gates.py` alongside the
   existing `check_quote_has_attribution()`. (Case D)
8. **[NEW CAPABILITY]** A headline-grounding check: does the generated title assert a specific
   factual claim (a number, a named outcome) that the generated body does not itself state? Likely
   implementable as a narrow, deterministic pattern check (numbers/superlatives in title absent from
   body) rather than a new LLM call, mirroring this codebase's own established "deterministic, no
   ML" convention for `content_quality_gates.py`. (Case A, and the Good_Brin borderline note)
9. **[POLICY / PRODUCT DECISION]** Decide, now that Cluster 1's mechanism is understood (§12),
   whether an explicit fact-density/verifiability signal independent of fetch-completeness should
   gate publication at all, or whether hedged-but-honest thin-evidence posts like Case B are an
   acceptable, intentional NEWS-channel product category. This is a genuine product question, not a
   bug — the report does not recommend an answer.
10. **[NARROW FIX]** `send_to_editorial_destination()`: pass
    `link_preview_options=LinkPreviewOptions(is_disabled=True)` on its one `bot.send_message()`
    call. Single parameter, single call site, no other function needs it. (Case G)
11. **[POLICY / PRODUCT DECISION]** Decide whether Story Memory's story-matching sensitivity should
    be tuned to catch same-event pairs like msg 164/173 (§10), or whether this specific miss is
    within acceptable tolerance for the current matching approach.

**P2**

12. **[NARROW FIX]** Fix the "Body is None" false-positive in the `quality`/completeness-assessment
    capability — it checks `ContentDraft.body` at a pipeline stage where that column is
    structurally always `None` for V8-family drafts (rendered later from `title`/`main_body`/
    `ending`, never written back). Fixing this removes the single largest source of noise currently
    making `quality.passed` fire on essentially every draft regardless of real quality — a
    prerequisite for cluster-3 (§12) ever becoming a usable signal, not urgent on its own.
13. **[POLICY / PRODUCT DECISION]** Once (12) is fixed and the fact-safety entity-checker's
    precision is separately improved, revisit whether either signal is ready to move from `shadow`
    to a real (even soft/advisory, not necessarily hard-blocking) publish-time gate.

## 14. Stability acceptance criteria

Proposed for the **next** bounded live validation run (not run in this phase):

| Dimension | Target |
|---|---|
| Evidence/headline consistency | Zero posts where the headline states a specific numeric/factual claim absent from the body (spot-check every delivered post's title against its own body) |
| Evidence-poor publication rate | `HEADLINE_ONLY`-sourced events: 0 reach delivery without either a successful redirect-resolved re-fetch or an explicit SKIP; `FULL_TEXT` boilerplate false-positives: 0 confirmed in a manual spot-check of any draft whose acquisition hit the 20,000-char cap |
| Uncertainty-filler rate | With v8.6 actually live: filler-pattern endings (the same 10/32 TEXT_QUALITY_FAILURE pattern from this report) below 10% of delivered posts, down from this run's 31% |
| UPDATE delta quality | `check_update_not_repeating_root` (wired, §13 item 1) passes on 100% of update-classified drafts; manual spot-check factual-overlap estimate (as computed in §4) below 40% for any update |
| Quote quality | Zero standalone quote fragments under ~5 words delivered without a completeness check (once §13 item 7 exists) |
| Duplicate-image rate | Zero same-source/different-resize pairs delivered together in one media group, verified against the specific recalibrated threshold from §13 item 6 |
| Irrelevant additional-image rate | Zero WEAK/ICON-band or `possible_avatar`/`possible_logo`-flagged images selected as an additional (non-sole) album image — already the corrective-phase behavior; re-confirm it holds |
| Unexpected Telegram link-preview rate | Zero large preview cards on text-only NEWS sends once §13 item 10 ships |
| Destination/send safety | Unchanged from this session's own already-established canary safety controls (hard delivery cap, cost cap, destination assertion) — no regression expected from any of the above fixes, should be explicitly re-verified in the same canary run |

## 15. Recommended next action

**READY FOR NARROW STABILITY FIXES.**

Every finding in this report traces to a concrete, scoped, well-understood mechanism — a redirect
never followed, a boilerplate page misclassified as success, a keyword-only recommendation
detector, an already-built quality check that was never wired with two missing arguments, a
perceptual-hash threshold too tight for one specific resize pattern, a quote-completeness check
that was never built, a missing link-preview parameter, and a prompt fix that exists but has never
been deployed to a real send. None of these require an architectural redesign; none require a new
LLM call; several are one-line or few-line wiring fixes to mechanisms that already exist in the
codebase. This is the "prefer fixing earlier semantic boundaries" case the instructions favored —
every P0 item above sits at or near the actual first-divergence point identified for its case, not
downstream of it.
