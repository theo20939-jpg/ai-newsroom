# NEWS STABILITY ACCEPTANCE CANARY REPORT

## A. Execution identity

- **Branch:** `feature/phase19-editorial-depth-upgrade`
- **HEAD:** `c308d45f6d55dc895eabe24b1901e1f99f855bbe` — "feat(newsroom): stabilize NEWS output and rich-media delivery"
- **Confirmed no code changed during the run:** `git diff --stat HEAD` returned empty both before launch and after completion. Committed production code (`services/`, `worker/`, `capabilities/`, `bot/`) was never touched during this phase.
- **Effective configuration** (in-process only, never persisted to `.env`):

| Setting | Value | Source |
|---|---|---|
| `editorial_delivery_mode` | `router` | in-process override |
| `copywriting_prompt_version` | `"8.6"` | in-process override (pinned process-wide, no per-call override path exists anywhere in the codebase — confirmed by grep) |
| `story_memory_mode` | `shadow` | in-process override |
| `telegram_story_reply_mode` | `enforce` | in-process override |
| `quote_telegram_rendering_mode` | `enforce` | in-process override |
| `article_acquisition_mode` | `shadow` | real `.env` value, **left untouched** |
| `video_discovery_mode` | `off` | real default, **left untouched** — video delivery fully disabled all run |
| `fact_safety_mode` | `shadow` | real default, untouched |
| `content_generation_dry_run` | `False` | real send, not a simulation |
| NEWS destination | chat `-1004297182444`, topic `2` | asserted via `resolve_route()` before any send; verified against every recorded send |

### Run structure: two windows, one immutable HEAD/config

The acceptance canary actually ran in **two process launches**, both against the identical committed HEAD and identical in-process configuration:

- **Run 1 (partial, 23:30:52–~00:24 UTC):** ~53 minutes in. Killed intentionally after discovering a bug **in my own canary instrumentation** (`scripts/_news_stability_acceptance_canary.py`'s `edit_message_reply_markup` wrapper was re-raising caught exceptions as a generic `Exception` instead of the original `TelegramBadRequest`, which defeated `services/telegram_routing.py`'s own deliberate `except TelegramAPIError:` handler around the media-group keyboard-attach step). This was a harness bug, not a production defect — verified by reading the unmodified production code, which already handles this exact scenario gracefully. Fixed, archived as `*_run1_partial_harness_bug.*`, and the canary was restarted clean.
- **Run 2 (complete, authoritative, 00:24:50–02:05:28 UTC):** 100.6 minutes, `stop_reason=runtime_reached`, 0 errors.

Because HEAD and configuration never changed between the two windows (only my own external observation tooling did), and the ~17-minute gap between them produced no activity (no process was running), this report treats **both windows as one coherent 153.8-minute natural-traffic sample** for quality classification, while keeping run 2 flagged as the run that validates the harness itself is trustworthy.

## B. Runtime / volume / cost

| Metric | Run 1 (partial) | Run 2 (complete) | Combined |
|---|---|---|---|
| Elapsed | 3195s (53.2 min) | 6038s (100.6 min) | 153.8 min |
| Stop reason | manual (harness bug) | `runtime_reached` | — |
| Events analyzed | 35 | 34 | 69 |
| Cost | $0.241 | $0.257 | **$0.498** |
| Delivery-cap-tracked attempts (`send_message`/`send_photo`) | 3 | 4 | 7/20 |
| Real Telegram sends (incl. media groups, which the hard cap doesn't track — a known, pre-existing, disclosed gap) | 4 | 5 | **9** |
| Errors | 1 (harness-only, fixed) | 0 | — |

Cost stayed at 25% of the $2.00 cap across the combined session; delivery volume stayed well under the 20-post cap. Natural traffic was light-to-moderate — no forcing of quotes, UPDATEs, multi-image stories, sources, or classifications occurred anywhere in this run.

## C. Quality classification

**9 of 9 real delivered posts classified `GOOD`** (3 carry a secondary `MEDIA_MINOR` tag — see §K).

| # | Msg ID | Headline (RU) | Primary | Secondary |
|---|---|---|---|---|
| 1 | 180 | Против Трампа подали иск из-за платного доступа к Truth Social | GOOD | — |
| 2 | 181 | Атака через AI-пакет скомпрометировала данные 2500 пользователей | GOOD | — |
| 3 | 182 | Источники: Kalshi хочет привлечь $750 млн при оценке $40 млрд | GOOD | MEDIA_MINOR (logo-like image) |
| 4 | *(unrecorded — harness bug window, real send verified)* | Поместье в районе Сан-Франциско продали за $70 млн | GOOD | MEDIA_MINOR (multi-crop album) |
| 5 | 186 | Появился маркетплейс, где ИИ-агенты покупают услуги друг у друга | GOOD | — |
| 6 | 187 | Белый дом может распространить надзор за ИИ на открытые модели | GOOD | — |
| 7 | 188 | Против Apple снова подали иск из-за уязвимости iCloud Private Relay | GOOD | MEDIA_MINOR (multi-crop album) |
| 8 | 191 | Target впервые назначила руководителя по ИИ | GOOD | — |
| 9 | 192 | Верховный суд США дал Apple 24 часа отсрочки в споре с Epic Games | GOOD | — |

**GOOD: 9/9 = 100%. Severe failures: 0/9 = 0%.**

Baseline comparison: **50% GOOD / ~19% severe** (n=32, prior forensic sample) → **100% GOOD / 0% severe** (n=9, this run).

**Honest caveat on sample size:** n=9 is far smaller than the n=32 baseline. A 100% figure on 9 independent Bernoulli trials has a wide confidence interval (Wilson 95% CI ≈ 70–100%) — this run is strong, consistent evidence of improvement, not proof the true GOOD rate is exactly 100%. No `TEXT_QUALITY_FAILURE`, `EVIDENCE_FAILURE`, `PRESENTATION_FAILURE`, or `MULTIPLE_FAILURES` occurred; `UPDATE_FAILURE` and `QUOTE_FAILURE` categories were never exercised (see §H/§J — natural traffic produced no delivered UPDATE and no available quote).

## D. V8.6

- **Drafts generated:** 18 CONTENT_GENERATION tasks completed in-window; 9 reached real Telegram delivery.
- **Prompt-version distribution:** `AIExecution.prompt_version` is **never populated** by `capabilities/copywriting_capability.py` for any of the 18 COPYWRITING executions in this window (a pre-existing telemetry gap, not something this phase touched) — so per-row DB confirmation isn't available. **v8.6 usage is instead confirmed by process-level invariant**: `settings.copywriting_prompt_version` was set once at canary startup and never mutated anywhere else in the codebase for the run's lifetime (grep-verified — no other call site writes this setting), and `capabilities/copywriting_capability.py:241` reads it directly at call time (`prompt_version = settings.copywriting_prompt_version`) with no per-event override mechanism. Combined with the live deterministic-test confirmation from preflight (`test_v86_includes_editorial_plan_and_prior_coverage_same_as_v85` — PASSED), this is treated as **100% v8.6 confirmed**, though per-row DB persistence would be a worthwhile follow-up for future audits.
- **Uncertainty-filler incidents: 0/9.** Every post's ending was either `null` (no ending emitted) or a materially relevant hedge tied to a real, specific caveat (e.g. "Речь пока идёт о переговорах: раунд и его условия окончательно не согласованы" [Kalshi — deal not final]; "Официального решения или объявленной политики пока нет — речь идёт о сообщениях источников" [White House AI oversight — sourcing caveat]; "Target не раскрыла полномочия нового руководителя, конкретные проекты и ожидаемый финансовый эффект" [Target — names the specific undisclosed facts]). None were pure "детали неизвестны"-style filler.

## E. Evidence/headline consistency

**0 headline/evidence contradictions found across all 9 posts.** Three posts had fact-safety-layer text flagging apparent tension; each was cross-checked directly against the RESEARCH capability's own extracted facts (not just the bare source title) and found to be well-supported:

- Post 2 ("2500 users" vs. original title's "terabytes of credentials"): Research's own facts explicitly capture *both* numbers and flag the terabytes claim as unverified — the generated headline correctly led with the **more conservative, verified** figure rather than parroting the more dramatic unverified one. This is a quality *positive* (appropriate hedging), not a defect.
- Post 7 ("снова" [again] flagged as an unsupported addition): Research's own first fact literally states "...снова подала в суд на Apple" — the claim is directly supported, and the fact-safety layer's flag here was a false positive from that separate, noisier check (worth noting as an observation: that layer's textual "issues" — mostly "Отсутствует текст публикации" — check the *original collected event's* bare summary field, which is near-always empty for RSS items by design, not the richer acquired/researched evidence; it should not be read as a live-quality signal without cross-checking Research's own facts).
- Post 8 (Target/TGT stock-impact framing): headline only says "may distribute" oversight to open models / mentions possible TGT relevance in the ending, both correctly hedged and tied to specifically-named missing facts.

No story promised a number, result, launch, or confirmed event that wasn't actually present in the evidence used.

## F. Acquisition / Google News

**3 Google-News-wrapped events encountered this window; 3/3 correctly resolved to `REDIRECT_UNRESOLVED`.** Zero were treated as successful article evidence, and zero produced a false `HEADLINE_ONLY` success — directly confirming the Case A fix eliminated the previously-systemic **23/23 HEADLINE_ONLY → Google News** pattern from the forensic baseline. One of the three (Target AI exec) was still delivered, but the weak-completeness gate correctly downgraded it to `BRIEF` treatment ("with weak evidence") rather than `STANDARD`/`MAJOR` — appropriate confidence degradation, not a bypass.

## G. Low-content/interstitial handling

One acquisition failure this window: the Twitch/PC Gamer "under fire for AI training" article returned `FETCH_FAILED` / `content_length_exceeded` — handled gracefully (no crash, no false-success labeling, downstream `quote_source_available` correctly set `false`). No consent-wall, sign-in-wall, or navigation-shell interstitials were encountered this window (none in the natural-traffic sample). **0 severe evidence-poor publications comparable to BAD_GARBAGE.c.**

**Case H architecture note — live-confirmed, not silently treated as fixed:** 8 of 9 delivered posts had *successful, substantial* acquisitions (`FULL_TEXT`/`SUBSTANTIAL_TEXT`, 4,048–20,000 extracted characters). Yet **0 of 9 posts ever had a quote available** (see §J). This is fully consistent with the disclosed, unfixed `article_acquisition_mode=shadow` architecture gap: the acquired raw article text is real and substantial, but the RESEARCH capability appears to derive its own facts independently (its facts include real specifics not present in bare RSS titles, e.g. "2,500 users of an AI package," "Sequoia Capital / Wellington Management / $40B") rather than by reading `raw_extracted_text` from the shadow-gated acquisition record — and the quote-extraction pipeline specifically, which depends on that same gated text, never had anything to select from. This is **not treated as fixed** by this run; it's live, empirical confirmation of exactly the gap the stability-fix checkpoint already disclosed.

## H. UPDATE quality

**0 delivered UPDATEs this run — all 9 real sends were `delivery_type=root`.** No `story_update`-matched draft was ever delivered as a Telegram reply.

**2 fail-closed non-deliveries found and reconstructed:**

| Draft | Headline | story_match_type | prior_root_delivery_existed | Outcome |
|---|---|---|---|---|
| `284e2731` | Twitch хочет использовать видео стримеров для тренировки ИИ Amazon | `story_update` (→ story "Twitch streamers can now refuse...") | `false` | Generated (COMPLETED), **never sent** |
| `d32277f6` | Twitch раскритиковали за новую систему обучения ИИ | `story_update` (→ same story) | `false` | Generated (COMPLETED), **never sent** |

Both matched the same pre-existing story about Twitch/Amazon AI training whose root delivery predates this canary and has no resolvable `StoryTelegramDelivery` record — the reply-threading mechanism correctly refused to fabricate a root, and (per this run's evidence) the item was suppressed entirely rather than falling back to an independent post. Real generation cost was incurred (~$0.028 combined) with zero corresponding delivery — real news about a real, distinct new development (Twitch's official response) was silently dropped. This is a genuine, narrow, evidence-backed finding worth follow-up investigation (§N), not a policy change made during this run.

**`UPDATE QUALITY: NOT LIVE-VALIDATED`** — natural traffic produced no delivered UPDATE to evaluate the actual P0 fix (repetition-check wiring) against. The fail-closed cases are reported separately per the acceptance brief's explicit instruction, not folded into a false PASS.

## I. Story duplication

**0 confirmed duplicate independent root deliveries** — all 9 real posts covered distinct real-world events (Trump/Truth Social, AI-package supply-chain attack, Kalshi funding, SF estate sale, HN marketplace demo, White House AI oversight, Apple/iCloud lawsuit, Target AI exec, Apple/Epic Games). One low-confidence `uncertain_match` occurred (HN marketplace post, score 0.39, against an unrelated other "Show HN" story) and correctly did **not** merge — delivered as its own independent story. No CD Projekt-like near-duplicate pair was encountered this run, so the entity-extraction fix's live effectiveness on a *real* recurring pair remains unexercised this window (its narrow, disclosed partial-effectiveness limitation from the stability-fix checkpoint is unchanged, not re-tested here). `RELATED_STORY` semantics (documented to always create a separate story) were not exercised by any delivered post this run either.

## J. Quote quality

**0/9 posts ever had a quote available**, confirmed via both runs' `quote_observations` instrumentation (`quote_available: False` for all 9 real renders, in both run 1's 4 observations and run 2's 5). No quote was rejected, dedup-suppressed, or budget-suppressed — there was simply never a candidate to begin with, consistent with the Case H finding in §G.

**`QUOTE QUALITY: NOT LIVE-VALIDATED`** — natural traffic never exercised the quote self-containment gate (Case D fix) end-to-end on a real delivery. This is reported honestly as an open validation gap, not claimed as a PASS.

## K. Media quality

| Representation | Count |
|---|---|
| Single-image (`send_photo`) | 5 |
| Media-group album (`send_media_group`, 3 images each) | 2 |
| Text-only (no eligible candidates) | 2 |

- **Irrelevant/filler images actually delivered: 0.** A Techmeme site-icon candidate (128×128, `possible_branded_screenshot`) and a Gravatar avatar candidate (96×96, `possible_avatar`) were both correctly excluded from their respective sends — only the strongest real candidate was used in each case (matches "one strong image is better than several mediocre ones").
- **Exact duplicate images: 0.**
- **Weak-but-not-wrong image:** post 3 (Kalshi) had only one image candidate available — a 328×328 Techmeme site-logo-like image (`possible_logo`, `possible_branded_screenshot`) — genuinely low-value but not misleading; flagged `MEDIA_MINOR`.
- **New finding — same-source multi-crop albums (not caught by the existing near-duplicate guard):** both media-group posts (SF estate, Apple/iCloud) present the **same underlying source photograph** three times, each a different CDN-served crop/resize of the identical base image (same Guardian/CNET filename token, different `?resize=`/width params). Computed pairwise perceptual-hash Hamming distances were 12–28 for one album and 5–28 for the other — **above both the global (≤4) and same-origin relaxed (≤10) near-duplicate thresholds**, because different aspect-ratio crops genuinely shift the perceptual hash. The Case E fix (CDN-proxy + relaxed-threshold same-origin dedup) correctly targets *identical re-encodes* (the Honor/WordPress-Photon case it was built and validated against) — it does **not** cover *"same photo, different editorial crop from a responsive image CDN,"* which is a distinct, adjacent gap. Both albums pass the current guard but arguably don't add three genuinely distinct visual perspectives, per the product rule that additional images must add distinct useful information. Flagged as a narrow follow-up candidate (§N), not fixed or retuned during this run.
- **Max 3 images respected:** yes, both albums capped at exactly 3.
- **All-media-fail safely falls back to text:** confirmed for both text-only posts (Google News/Target had 0 candidates because acquisition was unresolved; HN marketplace genuinely had 0 image candidates) — no crash, no missing post.

## L. Presentation

- **Source button:** correctly present on every applicable post. Two occurrences of a `TelegramBadRequest("message is not modified")` on the media-group keyboard-attach step (one in each run window) were investigated with a targeted, read-only-equivalent diagnostic against the real message — **confirmed the button was already correctly attached** in both cases; the error is a harmless double-request/idempotency artifact, already gracefully swallowed by production's own `except TelegramAPIError:` handler (`services/telegram_routing.py`), never causing a duplicate send or a missing button. **0 real source-button regressions.**
- **NINJA PULSE footer:** present exactly once, as the final element, on 9/9 posts (confirmed via both runs' quote-render instrumentation, `ninja_pulse_footer_present: True` on all 9 observations).
- **Link preview:** both real `send_message` (text-only) calls confirmed `LinkPreviewOptions(is_disabled=True)` at the actual Telegram API call. Photo/media-group captions never generate previews by Telegram platform design (not applicable to those 7 posts). **0 unexpected NINJA PULSE (or any other) link previews.**

## M. Reliability / safety

- **0 destination violations** across all 9 real sends (chat_id/topic_id verified against every recorded send and every `StoryTelegramDelivery` row).
- **0 duplicate sends.**
- **0 malformed cards** — all rendered HTML well-formed.
- **0 production crashes** in run 2 (the authoritative, harness-fixed run). Run 1's single logged error was traced precisely to my own instrumentation bug (§A), not production code, and did not cause a duplicate or lost delivery — the affected post (SF estate) sent successfully; only its `StoryTelegramDelivery` bookkeeping record and keyboard attachment were skipped that one time, both purely as a result of my harness's exception being unable to be caught by the correct `except TelegramAPIError:` clause.
- **1 acquisition-layer failure** (Twitch/PC Gamer `FETCH_FAILED`), handled gracefully, no crash.
- **2 fail-closed non-deliveries** (documented in §H) — safe (nothing wrong was sent), but real cost was spent with zero delivered output.

## N. Known unresolved issues

- **`article_acquisition_mode=shadow` / Copywriting fetched-text decoupling** — live-confirmed again this run (§G): 8/9 real acquisitions succeeded with substantial text, 0/9 quotes ever surfaced. Not fixed; still an open, disclosed architectural decision.
- **`RELATED_STORY`/CD Projekt merge limitation** — unchanged from the stability-fix checkpoint; not exercised by any real pair this run (nothing to confirm or regress).
- **Video delivery** — confirmed disabled the entire run (`video_discovery_mode=off`, untouched, zero video-related activity in any log).
- **New source pack** — confirmed not integrated; the deferred zip was never staged, never imported, never referenced by any executed code path this run.
- **New, narrow (this run):** fail-closed `story_update` non-delivery when no resolvable root exists appears to silently drop the item entirely (real cost, zero output) rather than falling back to an independent post — worth a targeted follow-up investigation.
- **New, narrow (this run):** same-source multi-crop responsive-image albums pass the current near-duplicate guard (Hamming distances well above both thresholds) but may not add genuinely distinct visual information — an adjacent gap to the fixed Honor/WordPress-Photon case, worth a follow-up.
- **New, minor/observability only:** `AIExecution.prompt_version` is never populated for COPYWRITING executions — v8.6 usage had to be confirmed via a process-level configuration invariant rather than direct per-row DB evidence. Worth restoring for future audits, not a functional defect.
- **UPDATE quality and Quote quality remain `NOT LIVE-VALIDATED`** — natural traffic in this ~154-minute combined sample never exercised either path to a real delivery. Recommend either a longer/targeted follow-up canary aimed at capturing more UPDATE/quote-eligible traffic, or treating this as an explicit open validation gap before broader deployment claims are made about those two specific fixes.

# ACCEPTANCE VERDICT

- `COPYWRITING V8.6: PASS` — 100% confirmed via process-level configuration invariant + live deterministic test; 0 uncertainty-filler endings found.
- `EVIDENCE QUALITY: PASS` — 0 headline/evidence contradictions across 9 posts (3 borderline cases cross-checked and confirmed well-supported); Google News wrapper handling clean (0/3 false `HEADLINE_ONLY`, matching the Case A fix's intent); 0 severe evidence-poor publications.
- `UPDATE QUALITY: NOT LIVE-VALIDATED` — 0 delivered UPDATEs; 2 fail-closed non-deliveries documented as a genuine, narrow finding.
- `QUOTE QUALITY: NOT LIVE-VALIDATED` — 0/9 quotes ever available; consistent with the disclosed shadow-mode architecture gap.
- `MEDIA QUALITY: PASS` (with a disclosed narrow gap) — 0 avatars/logos/irrelevant images actually delivered, 0 exact duplicates, safe fallbacks confirmed; but 2/2 media-group posts show a same-source multi-crop pattern not covered by the existing near-duplicate guard.
- `TELEGRAM PRESENTATION: PASS` — source button, NINJA PULSE footer, and link-preview suppression all confirmed correct on real sends; one cosmetic keyboard-edit artifact investigated and confirmed harmless.
- `DELIVERY SAFETY: PASS` — 0 destination violations, 0 duplicate sends, 0 malformed cards, 0 production crashes.

## `PARTIAL — NARROW FOLLOW-UP FIXES REQUIRED`

The pipeline is safe (delivery safety clean, zero severe correctness failures, zero regressions) and real quality improved substantially over the 50%-GOOD/19%-severe baseline (9/9 GOOD in this sample, with the appropriate small-sample caveat from §C). This does not reach a clean `PASS`, because:

1. Two of this phase's own headline fixes — UPDATE repetition-check wiring and the quote self-containment gate — never got to prove themselves against a real delivered UPDATE or a real delivered quote. They are genuinely `NOT LIVE-VALIDATED`, not confirmed safe.
2. This run surfaced two new, concrete, narrow defects worth follow-up: fail-closed `story_update` items silently costing money with zero delivered output, and same-source multi-crop media albums slipping past the near-duplicate guard.

Recommend: a follow-up, longer or more targeted canary aimed specifically at capturing UPDATE-eligible and quote-eligible natural traffic, plus scoped investigation of the two newly-found narrow issues, before treating NEWS output as fully validated for the next production step.

Per the acceptance brief's explicit instructions: no push, no deploy, no video resumption, no source-pack integration, and no follow-up code fixes were made automatically. This report is the stopping point.
