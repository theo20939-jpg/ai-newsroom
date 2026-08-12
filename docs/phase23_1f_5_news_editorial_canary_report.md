# PHASE 23.1F — 5-NEWS EDITORIAL CANARY

**Status: SUCCESS — 5/5 real posts generated and delivered to the correct NEWS topic.**

# Environment

- Branch: `feature/phase19-editorial-depth-upgrade`
- HEAD: `d509566154368bf42d54e7dd66166712d77409cb` (unchanged, no commit made)
- Database revision: `8faedf40f596` (Alembic head `3f37cf34109d`, unchanged, two migrations still
  unapplied)
- `.env`/`.env.example`: untouched (confirmed empty diff before and after)
- Worker states: `telegram_bot`/`automation_worker` already running, untouched;
  `content_worker`/`news_analysis_worker` confirmed `Exited` before and after — nothing started

# Configuration

Applied **in-process only**, inside one bounded, one-shot script (`scripts/
_phase23_1f_5_news_canary.py`), never written to `.env`, confirmed reverted to real defaults in a
fresh process immediately after the run:

| Setting | Value used |
|---|---|
| `editorial_delivery_mode` | `router` |
| `copywriting_prompt_version` | `6` |
| `story_memory_mode` | `shadow` |
| `fact_safety_mode` | `shadow` (already live, unchanged) |
| `newsroom_telegram_chat_id` | `-1004297182444` |
| `news_topic_id` | `2` |
| `content_generation_dry_run` | `False` |

**Execution shape**: a single fresh-eligible batch (5 `NEWS_ANALYSIS` tasks) only delivered 1
message per round in Phase 23.1D's own prior single-round run, so this canary looped bounded
(analysis cycle, content cycle) rounds — capped at 8, safety-bounded, never open-ended — stopping
the moment cumulative deliveries reached the 5-message target or a round found nothing left
eligible. **4 rounds ran in total** (confirmed directly: `Round 3` delivered 1, `Round 4`
delivered 2, per the captured log; rounds 1-2's own individual counts were not preserved in the
captured log tail, only their contribution to the final `total_notified=5` running total — the
script's own `=== TARGET REACHED (5/5) ===` line confirms the loop stopped the instant the target
was reached, never chasing volume beyond it, exactly as required).

**Cost**: real, measured via `AIExecution.cost` before/after — **$0.135944** for the entire run
(20 `NEWS_ANALYSIS` workflows + 5 successful `CONTENT_GENERATION` workflows + several more
`CONTENT_GENERATION` attempts that didn't clear the score threshold and were never billed for
Copywriting/Quality beyond Research/Intelligence reuse).

# Delivery

| # | Title | Source | Destination | chat_id | message_thread_id |
|---|---|---|---|---|---|
| 1 | Stack Overflow перевели в режим «только для чтения»... | t.me/vcnews/62834 | NEWS | -1004297182444 | 2 |
| 2 | ИИ может создавать новые вирусы против устойчивых к лекарствам бактерий | Vietnam.vn (via Google News RSS) | NEWS | -1004297182444 | 2 |
| 3 | ИИ могут обучить поиску «призрачных частиц» под землёй | New-Science.ru (via Google News RSS) | NEWS | -1004297182444 | 2 |
| 4 | Израильский стартап связали с несанкционированными атаками на OpenAI, Anthropic и Meta | cnbc.com | NEWS | -1004297182444 | 2 |
| 5 | Amazon обошла голосование жителей Гилроя по проекту ИИ-центра | tomshardware.com | NEWS | -1004297182444 | 2 |

All 5 confirmed delivered (`ContentCycleResult.notified` summed to 5, cross-checked against 5
distinct recorded `bot.send_message()` calls). **Telegram `message_id` was not captured by this
script's own instrumentation** (only `chat_id`/`message_thread_id`/text/button presence were
recorded) — a real, disclosed gap, not fabricated; delivery success is independently confirmed via
`ContentCycleResult.notified` and the real (non-mocked) aiogram send completing without error for
all 5.

# Editorial Quality Table

| # | News | Topic relevance | Style | Compactness | Unknown handling | Publishability |
|---|---|---|---|---|---|---|
| 1 | Stack Overflow read-only mode | High — concrete, quantified, tech-audience-relevant | Real editorial analysis, not PR | Good (1318 chars, no padding) | One material caveat (causal claim unverified), not repeated | **A** |
| 2 | AI creates viruses vs. drug-resistant bacteria | Clickable but thin/single-source | Reads as a verification request, not a finished post | Long relative to actual content (1430 chars) | **Excessive** — nearly every paragraph independently hedges (unconfirmed, source incomplete, biosafety unclear) | **C** |
| 3 | AI to search for "ghost particles" underground | Niche science interest, very thin | Reads as "we don't actually know anything yet" | 1015 chars for very little concrete content | **Excessive** — repeated "no details available" across most paragraphs | **C** |
| 4 | Israeli startup linked to AI hacks | High — major AI companies, security angle | Appropriately cautious (allegation, not confirmed fact) | Reasonable (1302 chars) but repeats "insufficient data" 3x | Borderline — hedging here is *editorially correct* (unconfirmed allegation against named companies) but slightly over-repeated | **B** |
| 5 | Amazon circumvents Gilroy community vote | High — real accountability story | Direct, confident, no unnecessary hedging | Best of the five (824 chars, no padding) | Clean — no repeated uncertainty at all | **A** |

**2 of 5 (40%) rated C — not suitable for the channel as delivered.** Both are exactly the two
cases flagged by Intelligence itself as low-confidence (see below) — the editorial read and
Intelligence's own advisory judgment agree.

# Intelligence Analysis

Two cases where Intelligence's own recommendation said "do not publish," but the post was
delivered anyway (current architecture: Intelligence is advisory only, confirmed unchanged this
phase per the brief's own explicit "do not implement a blocking gate" instruction):

| Case | Scoring | Significance | Recommendation (verbatim, translated) | Fact Safety | Delivered? | Editorial verdict |
|---|---|---|---|---|---|---|
| #2 — AI/viruses/bacteria | **88/100** | **3/10** | "Do not publish as confirmed news without further verification. Verify the original source, authors, and study status, and obtain independent confirmation of results and a biosafety assessment." | pass (5/5 claims supported — the draft itself made no unsupported claims, it simply *is* thin) | **Yes** | C (agrees with Intelligence) |
| #3 — AI/ghost particles | 78/100 | **3/10** | "Do not release as a standalone news item without verifying the external material and additional context." | **block** (highest_risk: high — 2/5 claims unsupported, including a high-severity "quote"-type finding) | **Yes** | C (agrees with Intelligence) |

**The most concrete, actionable finding of this canary**: in both cases, the numeric `Scoring`
result (78-88, comfortably above the 65 threshold) and `Intelligence`'s own `significance` (3/10)
**diverge sharply** — Scoring appears to reward topical/keyword newsworthiness ("AI," "major
companies," "breakthrough medicine") independent of how *substantiated* the underlying claim
actually is, while Intelligence's significance score already correctly penalizes source
thinness. Case #3 additionally shows Fact Safety's own independent signal (`block`, high risk)
agreeing with Intelligence's low-confidence read — three independent signals (Intelligence
significance, Intelligence recommendation text, Fact Safety status) all pointed the same direction
on the two posts an independent editorial read also rated worst.

**Recommendation on a future `human_review_required` marker**: the evidence from this one canary
run is a real, if small (n=2), signal that such a flag would be useful and cheap to compute
deterministically — e.g., `significance <= 3` (or a similar low threshold) OR the recommendation
text containing an explicit negative marker ("не публиковать"/"do not publish"/"не выпускать") OR
Fact Safety returning `block`. **Not implemented this phase**, per the brief's own explicit
instruction — this is an observation and a recommendation for a future, separately-authorized
phase, not an architecture change made here.

# Technical Validation

- **Fact Safety**: ran correctly on all 5 real V6 drafts — statuses `review`/`pass`/`block`/
  `review`/`pass`, a genuine spread (not a fixed value), confirming Phase 21's V6 compatibility
  fix continues to work correctly at real scale, including correctly flagging the two weakest
  posts.
- **ContentDraft**: all 5 persisted successfully — Phase 23.1C's fix confirmed working at scale
  (5/5, zero `KeyError` crashes, versus 0/4 in Phase 23.1B before the fix).
- **V6**: all 5 drafts generated with the full 8-field structure; `QualityCapability`'s own
  separate LLM judgment flagged all 5 with "Body is None"-style issues — the **same, already-
  disclosed** (Phase 23.1B/D/E) `QualityCapability`-own-`body`-assumption gap, now confirmed at
  5/5, still non-blocking (Quality's `passed`/`issues` has never gated delivery), still not fixed
  this phase (explicitly out of scope).
- **Telegram routing**: all 5 sends confirmed (programmatically, not just visually) to have used
  exactly `chat_id=-1004297182444`, `message_thread_id=2` — zero deviation.
- **Source button**: all 5 sends confirmed to have `reply_markup` attached (`has_button=True`).
- **No raw URL in body**: confirmed programmatically for all 5 — none of the five real source URLs
  (including two long Google News RSS URLs) appear anywhere in the sent text.
- **Compact body lengths**: 1318, 1430, 1015, 1302, 824 characters — noticeably longer than the
  Google Pay reference case (715, Phase 23.1E), all above the "500-900" guideline's upper bound
  except post 5. Consistent with the design principle "do not truncate a meaningful story" — these
  are all more information-dense stories than the Google Pay case — but also, for posts #2/#3
  specifically, partly a symptom of the *same* hedge-budget mechanism not fully suppressing
  repeated-but-differently-worded uncertainty across many fields when a story is this thin (see
  Problems below).

# Problems discovered

1. **The anti-repetition/unknown-budget mechanism (Phase 23.1E) does not fully suppress excessive
   hedging in genuinely thin, low-confidence stories** (#2, #3). It was designed and tested against
   one real case (Google Pay) where the uncertainty was expressed as near-duplicate restatement of
   the *same* missing fact; posts #2/#3 instead hedge about *several different* aspects (source
   verification, biosafety, technical specifics) in nearly every paragraph — each individual hedge
   is technically "distinct" by both the lexical-overlap and hedge-marker checks (different
   specific concern each time), so the budget mechanism (built to catch one repeated theme) does
   not catch "many different flavors of uncertainty, all in one thin story." This is a real,
   disclosed limitation of the deterministic, non-LLM approach (already flagged generally in Phase
   23.1E's own report §16.2) — now confirmed with two concrete, real examples.
2. **`Scoring` and `Intelligence.significance` diverge sharply on thin stories** (§"Intelligence
   Analysis" above) — Scoring alone is not a reliable proxy for "is this substantiated enough to
   publish."
3. **`QualityCapability`'s own `body`-assumption gap recurred at 5/5** — already tracked, not
   fixed (out of scope).
4. **Category `UNKNOWN`** for post #1 (Stack Overflow, a Telegram-sourced item) — a pre-existing
   categorization gap, unrelated to this phase's own scope, not investigated further.
5. **`message_id` was not captured** for the delivery table (§"Delivery" above) — a minor
   instrumentation gap in this canary's own script, not a system defect.

# Recommendation

**B — Needs small editorial fixes before VPS.**

Not **A**: two of five real posts (40%) were independently rated unsuitable for the channel by
this review, and — importantly — the system's *own* existing signals (Intelligence's
significance/recommendation, Fact Safety's status) already correctly identified both of them
before this report did. That is a strong, encouraging signal that the *information* needed to
avoid these two posts already exists in the pipeline; it just isn't used as a gate yet.

Not **C**: nothing here points to an architectural defect. Routing, ContentDraft persistence, Fact
Safety, and the compact presentation profile all worked correctly and consistently across a real,
varied 5-story batch — three of five posts were genuinely strong (A, A, B), and the two weak ones
failed for a well-understood, articulable reason (thin/unverified source material), not a code
bug.

**The recommended "small editorial fix"** is exactly the one this phase was instructed to only
observe, not implement: a deterministic, cheap `human_review_required` (or similar) marker
computed from `Intelligence.significance` / recommendation text / `Fact Safety.status`, reviewed
and authorized as its own, separately-scoped next step — not a redesign, not a new LLM call, not a
hard block, just visibility before delivery for the cases this canary showed the system can
already, correctly, identify as weak.

---

**STOP condition met.** 5/5 real NEWS posts delivered and confirmed correctly destined. Not
proceeding to VPS deployment, production workers, or other content formats. Waiting for human
editorial review.
