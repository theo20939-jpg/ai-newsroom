# Phase 23.1Q — Final Telegram Output Checkpoint

Branch `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged, nothing committed). Covers: Run 2 canary partial result, the v8.6 uncertainty-filler
fix, the NINJA PULSE footer enablement, and a full read-only audit of UPDATE/quote Telegram output
wiring with explicit rendered examples. No live sends performed for any of this checkpoint's own
work — only the already-completed, now-stopped canary runs sent real messages.

---

## 1. Run 2 partial canary result

**Not PASS, not FAIL — an intentionally, manually stopped partial run.**

- Runtime: 90.6 minutes (5438.6s) of a 2-hour bound, `2026-08-12T13:11:44Z` → manually stopped
  `~2026-08-12T14:49Z`.
- Termination reason: **manually stopped by authorization** (`TaskStop`), not any of the script's
  own caps (`stop_reason` was never set — none of runtime/cost/delivery/analyzed caps were
  reached).
- Collected: 340 events. Analyzed: 65/100. Delivered: 7/20 (hard cap).
- Cost: $0.4546 / $2.00 cap.
- Quote-bearing candidates observed: **0** (all 7 delivered posts had `quote_available: False`).
- UPDATE candidates observed: **14** real `story_update` classifications at the Story Memory
  triage level; **6** became real `ContentDraftStoryLink(is_story_update=True)` drafts.
- Threaded replies observed: **0**. All 6 update-eligible drafts hit
  `fail_closed_route_to_review` (`applied=True`, confirmed directly from
  `content_draft_reply_routing_proposals`) — each one correctly, safely declined delivery (no
  resolvable root existed for their story yet), never sent as either a reply or a fabricated
  standalone post. This is real, live evidence of Case E's behavior (§6 below).
- Destination violations: **0** — all 7 sends confirmed `chat_id=-1004297182444`,
  `message_thread_id=2`.
- Send failures: **0** (`errors_log` empty).
- **No send was interrupted mid-flight**: confirmed via the `cap.attempted == len(recorded_sends)`
  invariant (7 == 7, exact) — the hard-cap counter increments synchronously before every Telegram
  API call, and every counted attempt has a matching completed record with a real `message_id`.
  The process was stopped mid-triage (DB-only Story Memory matching), not mid-send — verified from
  the log tail before stopping.
- **No stray application process remains**: `Get-Process python` returned nothing after the stop.
- Docker: `ai_newsroom_postgres`/`ai_newsroom_redis` untouched, still healthy, 6+ hours uptime
  unaffected by the stop.
- Settings restoration: the script's own `finally` block (which prints explicit "restored to"
  confirmations) did **not** run — `TaskStop` does not trigger Python's normal exception-unwind
  path the way a caught signal would. This has **zero real risk**: every override
  (`story_memory_mode`, `telegram_story_reply_mode`, `quote_telegram_rendering_mode`) was an
  in-process attribute mutation on a now-terminated OS process; `.env` was never touched at any
  point, and no other process shares that process's memory. Confirmed no "existing harness"
  graceful-stop mechanism (signal handler / stop-file) exists in this script — `TaskStop` was the
  available option; flagged honestly rather than assumed clean.

Combined with the earlier Run 1 (killed externally, also partial, also clean — no destination
violations, no failed sends): across both partial runs, quotes were never naturally observed, and
UPDATE reply-threading's *positive* path (an actual resolvable-root reply reaching Telegram) was
never naturally observed either — only its fail-closed safety path was, twice now (Run 1: 0
instances; Run 2: 6 real instances). This is exactly the outcome the original validation goals
anticipated as a valid, non-forced result — not a failure of the mechanism.

---

## 2. v8.6 diff/results

**Root cause (previously reported, re-confirmed):** v8.5's own UNCERTAINTY rule used "данные
неизвестны"/"подробности не раскрыты" as *positive* worked examples, constraining only repetition,
never materiality — directly contradicting the adjacent OPTIONAL ENDING rule's own intent.
Confirmed live via the real Craft Ventures post generated during Run 1.

**Diff:** `prompts/copywriting/v8.6.yaml` (new file) — identical to v8.5 except the header comment,
`version: "8.6"`, and the UNCERTAINTY rule itself (full diff shown in the prior turn; header +
version + one rule only, everything else byte-for-byte identical). `core/config.py` — one line,
`Literal[...]` extended with `"8.6"`, plus an explanatory comment block matching every prior
version's own convention. `services/news_telegram_presentation.py` — `_HEDGE_FAMILIES["undisclosed"]`
extended with 3 new stems (`неизвестн`, `не раскрыва`, `отсутству`), defense-in-depth only.

**v8.5 confirmed byte-for-byte untouched**: `diff` against the original v8.5.yaml content shows
zero changes; v8.6.yaml is a wholly new, additional file.

**Tests:** new file `tests/test_copywriting_v86_uncertainty_fix.py`, 15 tests — materiality
distinction present, old filler-licensing framing removed (with a sanity check proving the test
*would* have failed against the real v8.5 defect), OPTIONAL ENDING/plain-language/one-paragraph
rules unchanged, schema unchanged, every earlier prompt version confirmed still frozen, config
`Literal` accepts `"8.6"`, all 3 new hedge-family inflections recognized, redundant same-family
endings still collapse against main_body, and — critically — material uncertainty
(`"Дата запуска пока не объявлена."`, `"Компания официально не подтвердила сделку."`) is **not**
stripped merely for belonging to a tracked hedge family when it doesn't duplicate main_body.
**Result: 15/15 passed.**

---

## 3. NINJA PULSE footer diff/results

**Diff:** one line at the real call site, `worker/content_cycle.py`:
```python
html = render_v81_news_card_html(
    outcome.copywriting_output, treatment=treatment_decision.treatment,
    quote_text=quote_text, quote_speaker=quote_speaker,
    include_ninja_pulse_footer=True,
)
```
No changes to `build_ninja_pulse_footer_html()`, `_NINJA_PULSE_URL`, `_NINJA_PULSE_TEXT`, or
renderer block order — all reused exactly as built in Phase 23.1J.

**Tests:** reused the two pre-existing renderer-level tests unchanged
(`test_ninja_pulse_footer_is_disabled_by_default_for_v81`,
`test_ninja_pulse_footer_can_still_be_explicitly_enabled`). Added only the previously-missing
call-site/integration regressions: photo-caption path (exactly one footer, correct anchor, no bare
URL outside the anchor, source button unaffected), text-only path, UPDATE reply-threaded path
(footer present exactly once, positioned after the quote block), and a genuine caption-overflow
fallback (a deliberately long V8-family MAJOR post exceeds the 1024-code-unit caption limit,
correctly falls back to the existing plain-text path with **zero** truncation and the footer still
present — proving the footer is included in the existing length calculation by construction, no
second truncation system). **Result: 5/5 new tests passed** (individually verified against the
same pre-existing teardown-FK pattern documented throughout this phase — 1 passed/1 error each in
isolation, zero real failures).

---

## 4. Exact UPDATE output wiring

**Classification field:** `database.models.content_draft_story_link.ContentDraftStoryLink.is_story_update`
(boolean) — set once, at draft-creation time, in `services/content_draft_service.py`:
`is_story_update = story_link.match_type not in (NEW_STORY, UNCERTAIN_MATCH)`. True for
`story_update`/`supporting_source`/`semantic_duplicate` match types that survived the earlier
suppression gate (`services/story_duplicate_guard.py::check_duplicate_story_delivery`, called
*before* the paid Copywriting call — a true duplicate with a prior ROOT delivery never reaches
this point at all).

**Root message source:** `services.story_telegram_delivery.get_root_delivery(session, story_id)` —
the story's own earliest `StoryTelegramDelivery` row with `delivery_type=ROOT` **and**
`delivery_status=SENT` (a failed/unconfirmed root never counts, even if a row exists).

**`reply_to_message_id` resolution:** `services.story_telegram_delivery.determine_reply_target(is_story_update, root_message_id)`
— pure function, three outcomes: `SEND_AS_ROOT` (not an update → `reply_to_message_id=None`),
`SEND_AS_REPLY` (update + resolvable root → `reply_to_message_id=root_message_id`),
`FAIL_CLOSED_ROUTE_TO_REVIEW` (update + no resolvable root). Computed once in
`worker/content_cycle.py`, **before** the legacy/router branch split — identical for every
delivery mode.

**No valid root exists → current behavior:** **fail-closed, not standalone-fallback.** Under
`telegram_story_reply_mode="enforce"`, the draft is **never sent at all** — `result.story_fail_closed_review += 1`
and `continue` (skips to the next draft). Under `"shadow"`, the same decision is computed and
persisted (`ContentDraftReplyRoutingProposal`) for review, but the real send still proceeds as a
standalone post (shadow never changes real behavior). This is the exact design-tension point
flagged in the original investigation, and the recommendation to preserve it (rather than add a
new "send standalone anyway" fallback) has not been revisited — still the current, live-proven
(6 real instances this run) behavior. See §6/Case E below.

**Renderer:** UPDATE and NEW use the **identical** `render_v81_news_card_html()` call for
V8-family output — reply-ness is purely a property of the *send* call
(`reply_to_message_id` kwarg), never of which renderer builds the HTML. Confirmed: headline, body,
quote (if present), and the NINJA PULSE footer are **all** preserved identically for an UPDATE
reply (proven by `test_router_mode_story_update_with_existing_root_replies_to_it`, which now
asserts the footer survives a real reply-threaded send). The source button (a separate inline
keyboard, built by `bot/keyboards/image_preview.py::build_source_only_keyboard()`, attached at the
`send_to_editorial_destination`/`send_photo_to_editorial_destination` call, not inside the HTML
string at all) is untouched by any of this — same mechanism for root and reply.

**Send function:** router mode (the only mode any real canary has used) always calls
`services.telegram_routing.send_to_editorial_destination()` (text) or
`send_photo_to_editorial_destination()` (photo) — never the legacy `send_editorial_card()`.
`reply_to_message_id` is threaded through to the real `bot.send_message()`/`bot.send_photo()` call
as a direct keyword argument (aiogram 3.29.1 still supports this parameter natively — confirmed by
inspecting the installed `Bot.send_message`/`send_photo` signatures directly, no `reply_parameters`
object needed).

**Confirmed Telegram receives it as a direct reply:** yes — `reply_to_message_id` is a first-class
`Bot.send_message`/`send_photo` parameter; a live send with it set produces a message Telegram
renders as a reply to that exact `message_id`, in the same chat/topic. (Telegram would reject the
call outright — a `TelegramAPIError`, already handled — if the target message didn't exist or
belonged to a different chat; this project has never exercised that failure path live, since no
positive reply case has occurred yet.)

**NEW items guaranteed `reply_to_message_id=None`:** yes, structurally — `determine_reply_target(is_story_update=False, ...)`
always returns `SEND_AS_ROOT` with `reply_to_message_id=None`, regardless of `root_message_id`'s
value; the only place `reply_to_message_id` is ever reassigned away from its `None` initial value
is the `elif is_enforce: reply_to_message_id = reply_decision.reply_to_message_id` branch, whose
value is `None` for `SEND_AS_ROOT` too. Directly tested
(`test_off_mode_never_queries_story_link_or_records_delivery`, and every NEW-story path in the
router-media-integration suite).

**Can DUPLICATE/SUPPORTING_SOURCE ever reach send:** yes, by design, when the V2 delta engine
determines real new information exists despite the coarse match type (`compute_would_suppress()`
returning `False`) — the exact case `test_orchestration_v1_would_block_but_v2_delta_shows_real_new_information_allowed`
locks in. A true, no-new-information duplicate is blocked earlier and never reaches this point at
all.

**Current gating/config values (real `.env`, unchanged by this phase):** `story_memory_mode="off"`
(default, not set in `.env`), `telegram_story_reply_mode="off"` (default, not set in `.env`).
**Production default vs. canary override:** in a real always-on worker with no canary script
involved, reply-threading is entirely inert (no `ContentDraftStoryLink` ever created since
`story_memory_mode` stays off). Every canary so far has overridden both to `"shadow"`/`"enforce"`
in-process only, per this project's established convention — never persisted to `.env`.

**Topic/thread routing vs. reply-to-root threading — independence confirmed:** these are two
structurally separate parameters passed to the same `bot.send_message()`/`send_photo()` call:
`message_thread_id` always comes from `resolve_route(destination).topic_id` (a pure function of
`settings.news_topic_id`, destination-based, never touched by Story Memory); `reply_to_message_id`
always comes from the independently-resolved `determine_reply_target()` decision (story-based,
never touched by topic routing). Verified directly in `services/telegram_routing.py`'s two send
functions — both parameters are always passed together but computed from entirely disjoint inputs;
neither can overwrite the other, and every real send this session confirmed both values
independently correct (`message_thread_id=2` on all 7 sends; `reply_to_message_id` correctly
`None` on all 7, since none had a resolvable root).

---

## 5. Exact quote output wiring

**Source fields:** `capabilities/executor.py` populates `BusinessContext.quote_source_text` from
the real acquired article text (`NewsEventArticleAcquisition.raw_extracted_text`, cleaned via
`services/article_cleaning.py::clean_extracted_text()`) when `article_acquisition_mode != "off"`
(real `.env` value: `"shadow"`). Copywriting's structured output (`prompts/copywriting/v8.5.yaml`/
`v8.6.yaml`) returns a `quote` object (`text`/`translated_text`/`speaker`) or `null`.

**Validation:** `services/quote_verification.py` — a claimed quote must appear verbatim (or as a
verbatim translation) in the source excerpt; a fabricated/paraphrased quote is dropped **before**
a `ContentDraftQuote` row is ever created (`test_fabricated_quote_is_dropped_never_persisted`,
real DB integration proof).

**Dedup:** `services/news_telegram_presentation.py::_is_distinct(quote_text, [body], threshold=_OPTIONAL_REDUNDANCY_THRESHOLD)`
— reuses the exact same helper/threshold already established for the `ending` field's own dedup
check.

**Length budgeting:** `services/quote_budget.py::fits_within_budget()`/`select_quote_or_omit()` —
the same pure functions `bot/formatting.py`'s legacy quote budget already uses, applied against
Telegram's hard 4096-code-unit message limit. Whole-or-omit, never partial.

**Renders when:** a verified `ContentDraftQuote` row exists for the draft (via
`services.quote_lookup.get_quote_for_draft()` + `resolve_display_text()`, gated by
`settings.quote_telegram_rendering_mode`), it is textually distinct from `main_body`, and it fits
within the length budget.

**Suppressed when:** no quote was extracted/verified; `quote_telegram_rendering_mode` is `"off"`
or `"shadow"` (looked up and logged, never assigned to the variables that reach the renderer); the
quote duplicates `main_body`; or including it would exceed the hard message-length limit.

**Current `quote_telegram_rendering_mode`:** real `.env` value is `"shadow"` (confirmed by direct
grep). **Production default vs. canary override:** in a real always-on worker, quotes are looked
up (proving the pipeline works) but never rendered — every canary so far overrode this to
`"enforce"` in-process only.

**Exact HTML generated:** `💬 <blockquote>{escaped quote text}</blockquote>\n— {escaped speaker}` —
identical convention to `bot/formatting.py`'s own pre-existing legacy quote block, non-expandable
(always visible, never collapsed).

**Position:** strictly after `main_body` (+ optional `ending`, which is part of the same body
block), strictly **before** the NINJA PULSE footer — confirmed both by direct code order
(`services/news_telegram_presentation.py` lines 656–671) and by the live rendered examples in §6.

**Survives photo-caption path:** yes — the quote block becomes part of the same `html` string used
as the photo caption; `test_ninja_pulse_footer_present_exactly_once_in_photo_caption_with_source_button`
and the pre-existing `test_router_mode_verified_quote_renders_in_the_v8_family_card` both confirm
this directly. **Survives text-only path:** yes, same string, different send function only.
**Survives UPDATE reply path:** yes — confirmed directly (§4; same renderer, reply-ness is a
send-call property only).

**Missing speaker:** `_v81_quote_block_html()` omits the `— {speaker}` line entirely when
`quote_speaker` is falsy (`speaker_suffix = f"\n— {...}" if quote_speaker else ""`) — never a
malformed or empty attribution line. Directly tested
(`test_quote_without_speaker_omits_the_attribution_line`).

**Quote text too long:** `fits_within_budget()` returns `False`; `select_quote_or_omit()` returns
`(None, None)`; the quote block is simply never appended — the rest of the card (headline, body,
footer) is completely unaffected. Directly tested
(`test_quote_omitted_when_it_would_blow_the_hard_telegram_length_limit`).

**Can the quote appear twice due to body overlap:** no — the dedup check (`_is_distinct`) compares
the quote against the actual rendered `body` text before deciding to append it; if the quote
materially restates something already in `main_body`/`ending`, it is omitted entirely, never
duplicated. Directly tested (`test_quote_omitted_when_it_only_restates_the_main_body`).

---

## 6. Cases A–E — rendered examples / resolved send kwargs

Generated directly from the real, unmodified `render_v81_news_card_html()` — no live sends, no
fabricated behavior.

### Case A — NEW, no quote
```html
<b>Стартап привлёк $50 млн на разработку нового чипа</b>

Стартап Acme AI привлёк $50 млн в раунде под руководством крупного венчурного фонда для разработки специализированного чипа для инференса ИИ-моделей.

<a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>
```
Send kwargs: `reply_to_message_id=None`, `message_thread_id=2`, `reply_markup=<source button>`.
Structure matches spec exactly (headline → body → footer → source button, standalone).

### Case B — NEW + quote
```html
<b>Стартап привлёк $50 млн на разработку нового чипа</b>

Стартап Acme AI привлёк $50 млн в раунде под руководством крупного венчурного фонда для разработки специализированного чипа для инференса ИИ-моделей.

💬 <blockquote>Мы хотели построить что-то, чего раньше не существовало.</blockquote>
— Джейн Фаундер, CEO Acme AI

<a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>
```
Send kwargs: `reply_to_message_id=None`, `message_thread_id=2`, `reply_markup=<source button>`.

### Case C — UPDATE, no quote
Renderer output is **byte-identical to Case A** (reply-ness never changes the HTML). Send kwargs:
`reply_to_message_id=<root_message_id, e.g. 139>`, `message_thread_id=2`,
`reply_markup=<source button>`. Live-proven mechanism (fail-closed path exercised 6 times this
session); the positive branch itself has not yet occurred naturally — the HTML/kwargs shape above
is derived from real code, not invented.

### Case D — UPDATE + quote
Renderer output is **byte-identical to Case B**. Send kwargs:
`reply_to_message_id=<root_message_id>`, `message_thread_id=2`, `reply_markup=<source button>`.
Not yet naturally observed together live (neither quotes nor positive reply-threading has
co-occurred with real traffic yet) — combination is structurally sound (independent mechanisms,
directly tested individually and, for reply+footer, together in
`test_router_mode_story_update_with_existing_root_replies_to_it`), but this exact combined case
remains unobserved live.

### Case E — UPDATE, root Telegram message ID unavailable
**Current implemented behavior, reported as-is, not redesigned:** **fail-closed.** The draft is
never sent — neither as a reply, nor as a standalone post. `result.story_fail_closed_review`
increments; the loop `continue`s to the next draft. A `ContentDraftReplyRoutingProposal` row
(`action="fail_closed_route_to_review"`, `applied=True`) is persisted so the decision is reviewable
after the fact, but no Telegram API call of any kind is made for that draft.

**Risk of this policy:** a real, confirmed update to a real story is silently *not delivered* at
all (not even as a standalone post) whenever its story's root message can't be resolved (root
delivery genuinely doesn't exist yet, was never `SENT`, or `StoryTelegramDelivery` bookkeeping has
a gap) — this is real information loss in the sense that the reader never sees the update, though
it is **never** an unsafe/wrong-target send. This is the safer of the two policies under
discussion in the original design-tension flag; it has now been live-proven 6 times this session
with zero incidents. **Not changed. Not recommended for change without further direction** — flagged
here exactly as requested, not altered.

---

## 7. Current production config values

Read directly from the real `.env` / `core/config.py` defaults (not from any canary override):

| Setting | Real value | Source |
|---|---|---|
| `copywriting_prompt_version` | `"4"` | code default; not set in `.env` |
| `quote_telegram_rendering_mode` | `"shadow"` | set explicitly in `.env` |
| `telegram_story_reply_mode` | `"off"` | code default; not set in `.env` |
| `story_memory_mode` | `"off"` | code default; not set in `.env` |
| `editorial_delivery_mode` | `"legacy"` | code default; not set in `.env` |
| `article_acquisition_mode` | `"shadow"` | set explicitly in `.env` |

A real always-on worker/bot process, with no canary script involved, would today run the old
legacy/v4 path with none of Phase 23.1P/Q's work active at all — unchanged by this phase, exactly
as disclosed in the original session-recovery report.

---

## 8. What must be overridden/enabled for the next live validation

Same in-process-only convention as every prior canary, never persisted to `.env`:
`editorial_delivery_mode="router"`, `copywriting_prompt_version="8.6"` (to exercise the actual fix
— any V8-family version 8.1–8.6 gets the footer, since that wiring is unconditional now, but only
8.6 has the corrected UNCERTAINTY rule), `story_memory_mode="shadow"`,
`telegram_story_reply_mode="enforce"`, `quote_telegram_rendering_mode="enforce"`,
`newsroom_telegram_chat_id`/`news_topic_id` set to the real NEWS destination.

---

## 9. Remaining ambiguity / unsafe edge cases

1. **Case D (UPDATE + quote combined) remains structurally sound but not yet live-observed** —
   both mechanisms are independently proven; their co-occurrence live has not happened simply for
   lack of natural incidence so far.
2. **Case E's fail-closed policy trades delivery completeness for safety** — explicitly not
   changed this phase; a real, disclosed design choice, not a bug, but still worth a deliberate
   human decision at some point about whether silent non-delivery is acceptable long-term for
   VPS/24-7 operation, versus e.g. investigating why root-delivery bookkeeping gaps occur at all.
3. **v8.6's materiality judgment is inherently a soft LLM judgment**, not deterministically
   enforceable — the deterministic hedge-family extension is defense-in-depth only, per your own
   explicit instruction; a live canary is the only way to confirm the prompt fix actually holds up
   against real, varied source material (not yet run — the next canary should specifically sample
   for repeat instances of the original filler pattern).
4. **Settings-restoration honesty**: `TaskStop` does not run this script's own `finally` block;
   confirmed zero real risk (§1), but any future manual stop should be aware no graceful in-script
   handler exists to build one if desired.

---

## 10. Exact files changed this phase (23.1Q, cumulative across this whole session)

**Production code:**
- `services/news_telegram_presentation.py` — quote rendering in V8.5 card; `_HEDGE_FAMILIES["undisclosed"]` extension
- `services/telegram_routing.py` — `reply_to_message_id` parameter on both send functions
- `worker/content_cycle.py` — quote/reply kwargs wired into router branch; `include_ninja_pulse_footer=True`
- `core/config.py` — `"8.6"` added to `copywriting_prompt_version` Literal
- `prompts/copywriting/v8.6.yaml` — new, immutable successor to v8.5

**Tests:**
- `tests/test_news_telegram_presentation_v81.py` — quote rendering unit tests
- `tests/test_telegram_editorial_routing.py` — reply_to_message_id passthrough unit tests
- `tests/test_content_cycle_story_delivery.py` — router-mode reply/quote/footer integration tests; one incidental flaky-query fix
- `tests/test_router_media_integration.py` — footer integration tests (photo, text, caption-overflow)
- `tests/test_copywriting_v86_uncertainty_fix.py` — new, v8.6 + hedge-family regression tests

**Canary artifacts (not production code):** `scripts/_phase23_1q_2h_canary.py` and its state/log
dumps (both runs), `scripts/_phase23_1q_output_examples.txt`.

**Documentation:** this file; `docs/session_recovery_after_phase23_1o_reset.md` (from earlier in
this session).

---

## 11. Git status (final)

Working tree remains fully uncommitted, consistent with this project's established pattern across
Phases 20–23.1Q — HEAD unchanged at `d509566` (Phase 19 M16). All changes listed in §10 are present
as either modified-tracked or new-untracked files; no destructive operations performed; `.env`
never touched; no migrations applied; Docker limited to `postgres`/`redis` throughout.

---

## STOP

Checkpoint complete. No commit, no deploy, no new canary started. Awaiting authorization before
any further live validation.
