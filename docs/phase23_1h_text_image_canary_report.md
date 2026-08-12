# Phase 23.1H — 5-NEWS Text + Image Live Canary

**Branch**: `feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(no new commits — all work uncommitted, matching this session's established convention).
Production settings, branch, and worker states were confirmed unchanged immediately after the live
run (see §7/§18).

**Status**: implementation + tests + live canary + both reports complete. **STOP — waiting for
human review of the two real Telegram cards.** Per the phase's own explicit instruction, no further
phase work (VPS deploy, permanent workers, enforce modes, Telegraph/Instagram/Reels/Meme) proceeds
without that review.

---

## 1. Media architecture investigation (Part A Step 1, answered before any implementation)

1. **Where are image candidates discovered?** `services/image_intelligence.py` (shadow-mode
   discovery, already active — confirmed via the live run's own `image_intelligence_shadow_result`
   log line) and persisted as `ImageCandidateRecord` rows (`database/models/
   image_candidate_record.py`).
2. **How are they ranked?** `services/image_relevance.py::rank_candidates()` / `score_candidate()`
   — a deterministic relevance/quality scorer (title/entity token overlap, source-relationship
   classification, technical quality checks, generic-aggregator-asset exclusion) — unchanged this
   phase, only read from.
3. **What constitutes the selected/best image?** The candidate with `eligible_for_editorial=True`
   and the lowest (best) `rank`, retrieved via the already-existing `services/
   image_persistence.py::get_editorial_image_candidates()` — the exact same function the legacy
   image-preview path already used.
4. **Is the selected image already persisted or only available in-memory?** Persisted —
   `ImageCandidateRecord` rows exist independent of any Telegram send, keyed by
   `content_draft_id`, with `storage_status`/`storage_key` for the stored bytes.
5. **How does legacy Telegram delivery attach it?** `services/image_preview_notifier.py::
   send_news_with_image_preview()` — fetches candidates, resolves the top one via `bot/
   image_preview_media.py::resolve_photo_input()` (cached Telegram `file_id` or freshly-read
   bytes), sends via `bot.send_photo()` with an interactive preview keyboard.
6. **Why exactly does router delivery lose it?** Two independent reasons, both confirmed by direct
   read: (a) `worker/content_cycle.py`'s router branch (`if settings.editorial_delivery_mode ==
   "router":`) never called `get_editorial_image_candidates()` at all; (b) even if it had,
   `services/telegram_routing.py::send_to_editorial_destination()` — the router's *only* send
   function — wraps `bot.send_message()` exclusively; it has no `photo` parameter and cannot send
   a photo under any input.
7. **Can the existing behavior be reused without duplicating image-selection logic?** Yes, and
   this phase does exactly that — `get_editorial_image_candidates()` and `resolve_photo_input()`
   are called directly from the router branch, unmodified; no second discovery/ranking/validation
   pipeline was written.

## 2. Why router mode previously lost images

Confirmed by §1.6 above: the router branch never queried image candidates, and its one send
function (`send_to_editorial_destination`) had no photo capability. Both were structural gaps, not
a bug in the image pipeline itself (which was already working correctly for the legacy path).

## 3. Integration implemented

- **`services/telegram_routing.py`**: added `send_photo_to_editorial_destination()` — a sibling to
  the existing `send_to_editorial_destination()`, reusing the exact same `resolve_route()`/dry-run/
  error-handling shape, wrapping `bot.send_photo()` instead of `bot.send_message()`. The original
  function is completely untouched — every existing caller/destination (MEME/TELEGRAPH/INSTAGRAM/
  REELS, every pre-existing text-only NEWS send) is byte-for-byte unaffected.
- **`worker/content_cycle.py`**:
  - `_extract_intelligence_result()` — reads Intelligence `significance`/`recommendation` from the
    same NEWS_ANALYSIS `workflow` JSON blob `_extract_scoring_result()` already reads (zero extra
    queries beyond one EditorialTask row fetch).
  - `_classify_event_for_router_treatment()` — composes those signals plus
    `NewsEventArticleAcquisition.effective_completeness_status` and `NewsSource.reliability_score`
    into a real `services.editorial_treatment.EditorialTreatmentDecision`, mirroring exactly the
    signal set Phase 23.1G validated offline.
  - The main per-event loop now calls this classifier **before** `run_content_generation_for_event`
    whenever `editorial_delivery_mode == "router"` — a `SKIP` decision `continue`s immediately,
    so a SKIP costs zero Copywriting calls and zero Telegram calls, matching the phase's own
    pipeline diagram (Scoring/Intelligence → Editorial Treatment → V6 Copywriting). Every other
    delivery mode (today's real default, `"legacy"`) never calls this classifier at all — proven
    by test Case J (§5).
  - The router branch now: passes the real `treatment_decision.treatment` into
    `build_compact_news_body()` (previously always defaulted to STANDARD); looks up image
    candidates via the reused `get_editorial_image_candidates()`/`resolve_photo_input()`; computes
    whether the full, untruncated rendered card fits Telegram's 1024-code-unit photo-caption limit
    (`_telegram_utf16_length(html) <= CAPTION_SAFE_LIMIT`) and only then sends as a photo — falling
    back to the existing plain-text send path otherwise (§ caption-limit safety below).
- **Caption-limit safety (Step 5)**: chosen behavior is **Option A** from the brief (send image
  with an appropriately compact caption) **with a safe fallback**, not a squeeze/truncation of any
  kind: if the full card (header + title + treatment-selected body) doesn't fit the 1024-unit
  caption limit, the exact same full, untruncated text is sent as an ordinary text message instead
  (`send_to_editorial_destination`'s already-existing, already-tested path) — the image is dropped
  for that one post, never the text. This guarantees zero mid-sentence/word-boundary truncation of
  treatment-selected content, a disclosed, deliberate tradeoff validated by test Case G.
- **Image quality policy (Step 3)**: no new heuristics were written. `get_editorial_image_
  candidates()` only ever returns `eligible_for_editorial=True` rows — confirmed by direct read of
  `services/image_relevance.py::evaluate_eligibility()` that this flag already encodes technical-
  failure rejection (M2), hard quality rejection and non-representative-duplicate exclusion (M3),
  and generic-aggregator-asset exclusion (Phase 16.5) — i.e., essentially every rejection category
  the brief lists (unrelated, generic stock, broken/tiny, duplicate placeholder). One additional,
  genuinely new check was added: an already-`is_expired` candidate (computed metadata the legacy
  path itself did not consult) is now treated as "no candidate," a strict improvement.
- **Image vs. source button (Step 4)**: kept fully independent by construction — the image is
  whatever `resolve_photo_input()` resolves; the button is always built from `event.url` via the
  unmodified `build_source_only_keyboard()`. Neither can influence the other.

## 4. Files changed

**Modified**: `services/telegram_routing.py` (new `send_photo_to_editorial_destination()`
function, additive only), `worker/content_cycle.py` (treatment gate + image/caption integration in
the router branch only, two new `ContentCycleResult` counters).

**New**: `tests/test_router_media_integration.py` (12 tests, cases A–L),
`scripts/_phase23_1h_5_news_image_canary.py` (the one-shot bounded live-canary host script),
`docs/phase23_1h_text_image_canary_review.md`, `docs/phase23_1h_text_image_canary_report.md` (this
file). Scratch investigation/output files under `scripts/_phase23_1h_*` (read-only query scripts,
canary stdout log, and the raw JSON records the two docs above were built from — kept for audit
trail, per this session's established convention).

**Not modified**: `services/editorial_treatment.py`, `services/news_telegram_presentation.py`
(Phase 23.1G, reused as-is), `services/image_persistence.py`, `services/image_relevance.py`,
`bot/keyboards/image_preview.py`, `bot/image_preview_media.py`, `bot/formatting.py`, any database
model, `core/config.py` (no new settings — the canary applied every override in-process, in a
separate script subprocess, never touching the real `.env`).

## 5. Tests

**New test file**: `tests/test_router_media_integration.py` — 12 tests, all 12 assertions pass
(cases A, B, C, D, E, G, H, I, J, K, L — F is folded into A/case-level coverage per the file's own
docstring). The only "errors" seen are the exact same pre-existing shared-DB FK-teardown pattern
(`content_draft_editorial_plans_event_id_fkey`) already confirmed present in *every* prior phase
this session, including in an untouched, pre-existing test in `test_editorial_delivery_mode.py` run
side-by-side for comparison — not a regression.

**Ruff**: `worker/content_cycle.py`, `services/telegram_routing.py`, `tests/
test_router_media_integration.py` — clean. Repo-wide scan: the same 6 pre-existing issues in old,
untouched scratch scripts already disclosed in the Phase 23.1G report, unchanged.

**Mypy**: `worker/content_cycle.py` and `services/telegram_routing.py` — clean, zero issues. The
new test file has 2 pre-existing-pattern errors (generator-fixture typing, `object`→`NewsSource`
argument typing) — confirmed identical in the sibling file (`test_editorial_delivery_mode.py`)
whose exact conventions were reused, not a new issue.

## 6. Regression results

Full named suite covering every module touched or adjacent (content_cycle/router-dependent tests,
story delivery, content generation integration, editorial scoring, media-vision isolation, meme-
pipeline-not-live, source button, story memory v2 isolation, telegram editorial routing, plus a
re-run of the entire Phase 23.1G suite): **169 passed** across the batches run this phase (on top
of Phase 23.1G's already-clean 579), with a small number of failures/errors, **every one confirmed
pre-existing** via `git stash` (identical failure with all Phase 23.1G+H code removed):
- `test_editorial_scoring.py` ×2 — the accumulated `AIExecution` row-count pollution pattern.
- `test_content_generation_integration.py::test_full_chain_dry_run_creates_draft_and_renders_
  without_sending`, `test_content_worker_cycle.py::test_run_content_cycle_dry_run_never_calls_
  bot_send_message` — real `.env`'s `content_generation_dry_run=False` vs. the tests' own
  hardcoded "default is True" assumption.
- `test_content_worker_cycle_image_preview.py::test_image_preview_disabled_by_default_...`,
  `test_run_content_cycle_sequential_no_gather_and_notifies_after_draft_creation` — real `.env`'s
  `image_editorial_preview_enabled=True` vs. the tests' own "default is False" assumption.
- `test_content_cycle_story_delivery.py::test_shadow_mode_persists_proposal_but_never_skips_or_
  changes_the_real_send` — stash-confirmed pre-existing, unrelated to delivery mode at all.
- `test_fact_safety.py` ×2 — the same `AIExecution` pollution pattern.
- The remaining FK-teardown "ERROR" entries throughout — the same shared-DB pattern confirmed
  present even in an untouched sibling test run for direct comparison.

No paid calls, no real Telegram sends, and no worker starts occurred during any test run.

## 7. Runtime configuration (live canary)

Applied **in-process only**, inside the one-shot script's own Python process (a separate `python
scripts/_phase23_1h_5_news_image_canary.py` subprocess) — confirmed to have left this session's
own `settings` singleton and the real `.env` completely untouched immediately after the script
exited (`editorial_delivery_mode` back to `"legacy"`, `copywriting_prompt_version` back to `4`,
`newsroom_telegram_chat_id`/`news_topic_id` back to `None`).

| Setting | Canary value | Required? |
|---|---|---|
| `editorial_delivery_mode` | `router` | ✓ required |
| `copywriting_prompt_version` | `6` | ✓ required |
| `fact_safety_mode` | `shadow` | ✓ required (already the real default) |
| `story_memory_mode` | `off` | ✓ never touched — see §15 |
| `telegram_story_reply_mode` | `off` | ✓ never touched, story-update routing OFF |
| `content_generation_dry_run` | `False` | required for a *live* canary |
| `newsroom_telegram_chat_id` / `news_topic_id` | `-1004297182444` / `2` | ✓ resolved and hard-asserted before any send |

Resolved route, verified programmatically before any LLM/Telegram call: `RouteTarget(chat_id=
-1004297182444, topic_id=2)` — exact match to the required target, script would have raised an
`AssertionError` and refused to proceed otherwise.

## 8. Analyzed candidate count

**21 events analyzed** (NEWS_ANALYSIS workflow completed) across 6 bounded rounds (5+5+5+5+1+0),
within the 30-analyzed hard cap. **Preflight context**: at the start of this run, 0 of the 16
then-pending NEWS_ANALYSIS-complete events cleared the pre-existing `content_generation_min_score
=65` gate (highest was 62); `automation_worker`'s own continuous background triage produced the
21 newly-analyzed events during the run, 2 of which cleared both the score gate and the Editorial
Treatment gate.

## 9. SKIP / BRIEF / STANDARD / MAJOR counts

Of the 2 events that reached Editorial Treatment classification (i.e., cleared the pre-existing
score gate and entered `CONTENT_GENERATION`): **0 SKIP, 1 BRIEF, 1 STANDARD, 0 MAJOR.** No event
was gated out by the treatment SKIP rule this run — the pre-existing score threshold had already
filtered the pool down to only the two ultimately-delivered stories before treatment classification
ever ran, so this run happens not to exercise the SKIP path live (SKIP is exercised in the offline
replay validated in Phase 23.1G, §16 of that report).

## 10. Delivered count

**2 of a target 5.** Not a defect — the phase brief explicitly authorizes "stop with fewer posts"
rather than lowering thresholds to manufacture volume, and the human reviewer was informed of the
thin-pool preflight finding and explicitly chose to proceed. The run stopped cleanly on its own
`nothing_eligible` condition after round 6, not on any hard cap (cost/runtime/analyzed all had
headroom remaining — see §16).

## 11. Image attached count

**1 of 2** delivered posts (NEWS #1, `cdn.3dnews.ru`, the original article's own illustration,
800×545, `rank=1`, `quality_status=accepted`) — sent via `send_photo`.

## 12. Text-only fallback count

**1 of 2** delivered posts (NEWS #2) — 2 image candidates were discovered, both correctly rejected
by the existing `eligible_for_editorial` gate (a 300×300 generic Google-hosted aggregator
thumbnail, and one dimensionless/technically-failed candidate) — sent via `send_message`. This is
the "no image is better than a bad image" product rule (§3) working correctly on real, live data,
not a gap.

## 13. Source-button validation

Both delivered posts carry `[🔗 Источник]` with the real article URL (`3dnews.ru`/`servernews.ru`
for #1, a Google News redirect link for #2 — the real, resolvable source URL either way), and
neither post's visible body/caption text contains the raw URL anywhere — confirmed by direct
inspection of the actual sent `text`/`caption` strings recorded by the script's own send
instrumentation (§7 of `docs/phase23_1h_text_image_canary_review.md`). `reply_markup` was
correctly attached to both the `send_photo` and the `send_message` call.

## 14. Fact Safety results

**Both** delivered posts were flagged `status=block`, `highest_risk=high` under `fact_safety_mode=
shadow` — correctly advisory-only (shadow mode never suppresses a send; both sends proceeded as
expected). In both cases, every flagged finding was a named-entity "unsupported" claim (place
names, product/company names) — zero numeric or substantive-fact findings. This is disclosed as a
notable observation for human review, not a defect introduced this phase: it is the first time
this session Fact Safety's real shadow output was reviewed side-by-side with two real, delivered
posts, and the pattern (100% of flags being entity-matching, not fact-checking) is worth a
deliberate human judgment call before ever considering `fact_safety_mode=enforce`.

## 15. Story Memory real state

**`story_memory_mode` stayed `off` throughout this entire run** — the canary script never sets or
overrides it (confirmed by direct read of the script; it is absent from the settings block).
Story Memory did **not** participate in this canary's real path in any way — no shadow
computation, no story-link persistence, nothing to review. This is stated explicitly, honestly,
and is not conflated with "validated," per the phase brief's own explicit warning about this exact
limitation from prior canaries.

## 16. Cost

**$0.118788** incremental (baseline `$7.404410` → final `$7.523198`), well under the $1.00 cap —
6 rounds of analysis (21 events × ~4 LLM calls each for research/intelligence/engagement/scoring)
plus 2 full CONTENT_GENERATION pipelines (copywriting + quality/fact-safety, reusing the
already-computed research/intelligence/scoring results rather than re-calling them — confirmed by
the `capability_result_reused_from_news_analysis` log lines for both delivered posts). Runtime:
**444 seconds (≈7.4 minutes)**, well under the 4-hour cap.

## 17. Errors/retries

**Zero.** Every logged `httpx` call returned `HTTP/1.1 200 OK`; no retry, no `TelegramAPIError`, no
`notification_failed`, no `story_delivery_persistence_failed` anywhere in the run. Both `send_photo`
and `send_message` calls succeeded on the first attempt.

## 18. Known limitations

- The currently fresh-eligible pool was thin at run time (a real, disclosed, pre-existing-
  threshold effect, not something this phase changed) — this run validated the *mechanism*
  end-to-end (treatment, media, caption-limit safety, source button) on 2 real posts rather than
  the full 5. A future canary run at a moment with more fresh, higher-scoring stories in the
  pipeline would be needed to see BRIEF/STANDARD/MAJOR/SKIP all exercised live in one run (SKIP
  itself was already validated live in Phase 23.1F/G's own offline replay of real data).
  - **Note on cost**: budget headroom was very large ($0.12 of $1.00 used) — a longer or repeated
    run, not a threshold change, is the correct way to gather more live examples if desired.
- Fact Safety's shadow-mode "block" verdicts on both delivered posts, driven entirely by
  entity-matching rather than substantive fact-checking, are flagged for human judgment (§14) —
  not fixed or investigated further this phase (out of scope; Fact Safety itself was not touched).
- The router branch's new image-attachment logic is unconditional whenever
  `editorial_delivery_mode == "router"` — unlike the legacy path's separate `image_editorial_
  preview_enabled` flag, there is no independent on/off switch for images specifically within
  router mode. This is a deliberate design choice (router mode itself is already the explicit
  opt-in canary gate, matching the Phase 23.1A precedent) but is disclosed here as a real
  difference from the legacy path's configurability.
- Per-post cost is computed by summing `AIExecution.cost` filtered on `event_id` — accurate for
  this run (each event's LLM calls are cleanly attributable) but not a general-purpose
  cost-attribution mechanism (no time-window guard beyond the whole run's own baseline/final
  delta), sufficient for this canary's own reporting needs only.

---

## VPS readiness decision

**B — SMALL FIX REQUIRED BEFORE VPS.**

The architecture is sound: routing was correct on both real sends (exact chat/topic every time),
Editorial Treatment correctly drove text length (BRIEF vs. STANDARD, matching their own stated
significance/evidence reasons), the media integration worked correctly on real data in both
directions (attached a genuinely relevant original-source image once, correctly rejected two
low-quality candidates and fell back to text-only once), the source button was present and correct
on both sends with no raw URL leakage, and no architecture-level blocker was found (no routing
risk, no draft contamination, no uncontrolled processing, no broken treatment).

The one bounded, disclosed item to resolve before VPS preparation is **not** architectural: both
real delivered posts were flagged `block` by Fact Safety, with every finding being an
entity-matching false-positive pattern rather than a genuine factual problem (§14). Before this
system is trusted to run continuously and unattended on a VPS, a human should make a deliberate
call on Fact Safety V1's entity-matching sensitivity — either accept it as a known, harmless
shadow-mode quirk (and document that decision), or tune it, before ever considering
`fact_safety_mode=enforce` on a VPS deployment where a systematic false-block pattern would either
silently suppress good content (if enforced) or go unnoticed for longer (if left in shadow
indefinitely without review). This is a bounded product decision, not a rebuild — hence B, not C.

Per the phase's own explicit instruction: **STOP here.** No VPS deployment, no permanent `.env`
change, no permanent content workers, no Story Memory/duplicate-suppression/story-update-routing
enforce mode, no Telegraph/Instagram/Reels/Meme work proceeds from this phase. Waiting for human
review of the two real Telegram cards (`docs/phase23_1h_text_image_canary_review.md`).
