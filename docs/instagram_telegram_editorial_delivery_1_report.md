# INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 — Report

Base: `4181287` (`feature/instagram-media-hosting-closure-1`). Branch:
`feature/instagram-telegram-editorial-delivery-1`. No Instagram Graph API call anywhere in this
phase's code or its tests. Both publication flags remain `false` throughout.

## A. Base/source lineage

`git merge-base` confirms `feature/instagram-growth-engine-v1` (05585ae) IS an ancestor of
`feature/instagram-media-hosting-closure-1` (4181287) - the latter is a clean, complete descendant
of every prior Instagram line (Execution Foundation → Visual System V1 → Production Rollout →
Production Readiness Closure → Growth Engine v1 → Media Hosting Closure). `4181287` is therefore
the correct, most current base; no other branch needed reconciliation. Primary worktree
untouched - this phase used its own isolated `git worktree add`.

## B. Existing Instagram pipeline (reused, not rebuilt)

Confirmed and reused as-is: `ContentOpportunity` → `FormatDecision`/`ShadowPlanResult` →
`services.instagram_creative_director` (`generate_single_creative`/`generate_carousel_creative`/
`generate_reel_creative`) → `build_instagram_content_package()` → `render_instagram_feed_image()`/
`render_instagram_carousel()`/`render_instagram_reel_cover()` → `validate_instagram_art()` →
`evaluate_instagram_editorial_gate()` (READY_FOR_EDITOR/HOLD/BLOCK). No second content generator
was created. Discovered that `services/telegram_routing.py` **already has** a first-class
`EditorialDestination.INSTAGRAM` → `instagram_topic_id` routing entry (Phase 22), including
`send_photo_to_editorial_destination()`/`send_media_group_to_editorial_destination()`/
`send_to_editorial_destination()` - all reused unmodified.

## C. Telegram topic discovery

Audited `services/telegram_routing.py`, `core/config.py`, production `.env`, and
`bot/handlers/whereami.py` (the existing safe discovery mechanism - reply with a topic's real
`message_thread_id` when `/whereami` is typed inside it). Result:

- `INSTAGRAM_TOPIC_ID` is **not present** in production `.env` (confirmed via SSH, key-name-only
  grep).
- No prior `/whereami` invocation is present in `telegram_bot`'s current container logs - the
  numeric thread id for the "instagram" topic is genuinely not known to the application anywhere
  today.
- The Telegram Bot API has no generic "list forum topics" endpoint - `/whereami` (or an operator
  manually reading the topic's own settings in the Telegram client) is the only safe way to learn
  it, matching this phase's own §4 guidance exactly.

**This is the one genuine external-input boundary this phase cannot cross.** Per §4's own
instruction, a fallback to the chat root was never implemented for Instagram - see D below.
Founder action needed: type `/whereami` inside the real "instagram" Telegram topic and set
`INSTAGRAM_TOPIC_ID` in production `.env` to the returned `message_thread_id`.

## D. Package contract

New `services/instagram_editorial_package_snapshot.py::build_package_snapshot()` / plain JSON,
stored on the new `InstagramEditorialDelivery.package_snapshot` column - carries `package.to_dict()`,
the source `ContentOpportunity`/`FormatDecision`/`ShadowPlanResult`/`CreativeDirectorInput`, the
previous creative object, and the media-identity fields (`media_candidate_id`/
`media_subject_match`/`media_usage_classification`) needed for §7's `PACKAGE_ASSET ==
TELEGRAM_DELIVERED_ASSET` invariant and for a future regeneration. `restore_regeneration_inputs()`/
`restore_package()`/`restore_media_identity()` round-trip it exactly (tested).

## E. Single-post delivery

`services/instagram_telegram_package_presenter.py::present_single()` builds one rendered image +
one HTML control message (format label, full caption, hashtags, CTA, one compact truthfulness
line). `services/instagram_telegram_delivery.py::deliver_instagram_package()` sends the photo via
`send_photo_to_editorial_destination()`, then the control message (with the editor keyboard)
replying to it. Verified via a real fixture (`artifacts/instagram_telegram_editorial_delivery_1/
single_news/`) - real rendered NEWS visual + exact control-message text.

## F. Carousel delivery

`present_carousel()` preserves `render_instagram_carousel()`'s own slide order exactly (never
re-sorted) - `CAROUSEL_ORDER_PRESERVED=true`, proven both by a unit test and the real 3-slide
fixture. Sent via `send_media_group_to_editorial_destination()` (already handles the
media-group-then-edit-in-keyboard sequencing correctly - reused, not reimplemented), followed by
the caption/control message.

## G. Reel delivery

`present_reel()` is strictly truthful: `package.external_video_asset_ref` is the ONLY signal
trusted for "a real video exists" - confirmed via code audit that no video-rendering capability
exists anywhere in `services/instagram_platform_renderer.py` today, so every Reel this phase
produces is honestly labeled "REEL-КОНЦЕПТ (видео ещё не создано)" with the real cover image plus
the real stored storyboard/shot-list/script from `package.media_plan` - never a fabricated
placeholder. Proven via the real fixture (`artifacts/.../reel_package/`).

## H. Editor actions

- **✅ Принять** - fully real. `InstagramEditorialDeliveryService.set_approved()` only changes
  `state` to `APPROVED`; idempotent and immutable-once-final (mirrors
  `TelegramArticleReviewService.set_decision()`'s established policy exactly). No Instagram API
  call exists on this path at all (structurally verified by an `ast`-based test).
- **🔄 Переделать / 📝 Текст / 🎨 Визуал** - the underlying regeneration logic is fully real and
  tested (`services/instagram_editorial_regeneration.py`): full regen re-runs the real Creative
  Director end-to-end; text-only regen forces every visual-facing field back to its previous value
  and never renders at all (so it can never touch media, and never even needs the original image
  bytes); visual-only regen is the inverse and always re-renders. **Disclosed limitation**: wiring
  a real `LLMGateway`/`PromptRepository` into a live Telegram callback handler is an
  application-boot-lifecycle concern (`integrations/llm_gateway/boot.py::
  assemble_ai_integration_layer()`) this phase deliberately did not thread through the bot's own
  startup, to avoid constructing a second, divergent gateway instance. Until a future,
  explicitly-authorized wiring phase calls `bot.handlers.instagram_editorial_review.
  set_regenerator_factory()`, pressing 🔄/📝/🎨 in production replies honestly that regeneration
  isn't wired yet and safely reverts the delivery to its previous, still-actionable state - never a
  crash, never a fabricated result. No existing production caller ever invoked the Creative
  Director's `generate_*_creative()` functions before this phase either (confirmed by a repo-wide
  search) - this is a pre-existing gap this phase did not silently paper over.

## I. Versioning

New `InstagramEditorialDelivery` table (`version` integer, `package_identity` stable across
regenerations). `create_new_version()` supersedes the previous row and creates version N+1 in one
transaction; a partial unique index (`ix_instagram_editorial_deliveries_current_identity`) makes
"at most one non-superseded row per identity" a real DB-enforced guarantee, not just an
application-level convention.

## J. Idempotency

- **Delivery dedup** (§21): `get_or_create_first_version()` - a worker cycle re-considering an
  already-delivered `package_identity` returns the existing row (`created=False`), never resends.
  `DUPLICATE_TELEGRAM_PACKAGE_SENDS=0`, proven by test.
- **Approval** (§11): idempotent/immutable-once-final. `DOUBLE_APPROVAL_SIDE_EFFECTS=0`, proven by
  a test that spies on `session.flush()` call count on the second approval attempt (zero calls).
- **Regeneration** (§11): `begin_regeneration()` atomically checks-and-sets state before any
  generation work begins; a second tap sees the guarded state and no-ops. `DOUBLE_REGENERATION_
  JOBS=0`, proven by test.
- **Stale callback** (§N): `is_actionable()` checks both `version` and `state` together - a button
  from an old message (superseded version) or an already-final delivery (approved/regenerating/
  HOLD/BLOCK) is never actionable. Proven by test.

## K. HOLD/BLOCK behavior

`deliver_instagram_package()` checks `gate_decision.permits_publication` FIRST - a HOLD/BLOCK
package is never sent with media or an editor keyboard; only a concise internal notice ("⚠️
INSTAGRAM · HOLD/BLOCK", format + reason) is sent to the topic, and duplicate-prevention still
applies (a second worker cycle reconsidering the same HOLD/BLOCK identity does not re-notify).
Proven by test for both HOLD and BLOCK.

## L. Instagram publication safety

`INSTAGRAM_PUBLICATION_PERFORMED=false` throughout. Structurally verified (an `ast`-based test
parses actual `import`/`import from` statements, not a naive substring match) that
`services/instagram_telegram_delivery.py` and `bot/handlers/instagram_editorial_review.py` never
import `services.instagram_publish_adapter` or `services.instagram_account_reader` - there is no
code path from this phase's work to any Instagram Graph API write endpoint. Generation and
delivery never depend on Instagram credentials being present (see M).

## M. Media-hosting independence

`services/instagram_telegram_delivery.py` never imports `services/instagram_media_hosting.py` or
`services/instagram_account_reader.py` at all - `MEDIA_HOSTING_READY=false` and Instagram
credentials being absent cannot block Telegram editorial delivery by construction, not merely by
convention. Proven by a test with `instagram_topic_id` configured but no media-hosting/credential
state referenced anywhere in the call path.

## N. Tests

New `tests/test_instagram_telegram_editorial_delivery.py` - 23 tests covering the required matrix:
A/B/C (single+carousel delivery, slide order), E (Reel never mislabeled), F/G (caption preserved,
source button), H/I (approve-only, never publishes), J/K/L/M (real full/text/visual regeneration,
including a carousel slide-count-mismatch safe bail-out), N (stale callback), O/P (HOLD/BLOCK never
READY), Q (duplicate worker cycle), R/S (media-hosting/credentials independence), T/U (publication
flags off, structural no-write-import guarantee). D (Reel with an actual video) is covered at the
presenter level only (`kind` correctly switches to `"reel_video"` given a real
`external_video_asset_ref`) - honestly disclosed as untestable end-to-end since no real video asset
capability exists in this codebase to produce one.

**Results**: 23/23 new tests pass. Combined regression: 228/228 (full Instagram suite + Telegram
routing + Telegraph notifier tests), 114/114 (Unified Pipeline freeze + meme + recap + Telegraph
pipeline worker suites). `NEW_FAILURES=0`. `ruff check` clean on every new/modified file (the one
pre-existing `database/models/__init__.py` F401 side-effect-import pattern left untouched, as in
every prior phase).

## O. Regression / non-regression

`TELEGRAM_EXISTING_FLOW_CHANGED=false`, `STORY_MEMORY_CHANGED=false`, `ARXIV_CHANGED=false`,
`UNIFIED_PIPELINE_CHANGED=false`, `INSTAGRAM_VISUALS_CHANGED=false` - no file under Telegram
NEWS/BREAKING/DATA/QUOTE production delivery, Story Memory, arXiv guard, Unified Editorial
Pipeline semantics, Vision Gate, DATA hotfix, recovery, or the frozen Instagram visual layouts was
touched. `services/telegram_routing.py` itself was not modified - Instagram delivery only calls its
existing, unmodified functions.

## P. Production rollout plan

**Not deployed this phase.** No migration was applied to production (`a3f7c1e9b204` tested only
against the isolated local test DB). Production health recorded for the record (read-only, nothing
changed): `content_worker`/`backend`/`telegram_bot` all `running`, `RestartCount=0`; Postgres
`healthy`; Redis `role=master`, `6379/tcp` still not publicly exposed
(`PUBLIC_REDIS_6379=false`, unchanged from the prior phase's own incidental Postgres-only finding).

**Rollout is gated on exactly one Founder action**: run `/whereami` inside the real "instagram"
Telegram topic and configure `INSTAGRAM_TOPIC_ID` in production `.env`. Once that's done, the
sequence is: apply the additive migration to production → deploy `content_worker` (and `backend`/
`telegram_bot` if the callback handler needs to be reachable from wherever the bot process runs) →
run the manually-invoked candidate script (mirroring `scripts/_instagram_readiness_dry_run_1.py`'s
established pattern) against a small number of real candidates → observe the required 30-minute
window per §32. This phase does not perform that canary - see the verdict below.
