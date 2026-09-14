# INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-PRODUCTION-CANARY-1 — Report

Base implementation branch: `feature/instagram-telegram-editorial-delivery-1`. Starting HEAD
`593d476`, final HEAD `4d3c2f0` (a real bug fix found and applied during this canary - see H
below). No Instagram Graph API call anywhere in this phase. Both publication flags remained
`false` throughout.

## A. Source release

Verified in the local development worktree before touching production: clean working tree,
`git rev-parse HEAD` = `593d476` (matched the expected implementation HEAD exactly),
`LOCAL_HEAD == REMOTE_HEAD`. A real bug fix (§H) was committed and pushed mid-phase, bringing the
branch to `4d3c2f0` - re-verified clean/matching before the final deploy.

**Production topology discovery**: `/opt/ai-newsroom` (the primary production checkout) was found
to be on an unrelated branch (`feature/phase19-editorial-depth-upgrade`) with real, uncommitted
local changes - not this phase's work. Per explicit Founder instruction, `/opt/ai-newsroom` was
never touched (no checkout, no stash, no reset, no clean). All work in this phase used a separate,
isolated `git worktree` (`/opt/ai-newsroom-instagram-telegram-editorial-delivery-1`) checked out at
the exact approved commit, and Docker images were built only from that directory.

## B. Founder-provided topic identity

`chat_id=-1004297182444` (already correctly present in production `.env` as
`NEWSROOM_TELEGRAM_CHAT_ID` from a prior phase - unchanged), `message_thread_id=40` (obtained by
Founder running `/whereami` inside the real "instagram" Telegram topic). Treated as authoritative,
per the phase brief.

## C. Route configuration

Confirmed `services/telegram_routing.py`'s existing `EditorialDestination.INSTAGRAM ->
instagram_topic_id` mapping was reused unmodified - no second routing abstraction introduced.
Added exactly one new key to the shared production `.env` (backed up first):
`INSTAGRAM_TOPIC_ID=40`. No other destination's configuration was touched. Live verification
against the real running settings (`resolve_route()` for every `EditorialDestination`):

```
NEWS      -> chat_id=-1004297182444, topic_id=2      (unchanged)
MEME      -> chat_id=-1004297182444, topic_id=37     (unchanged)
TELEGRAPH -> chat_id=-1004297182444, topic_id=39     (unchanged)
INSTAGRAM -> chat_id=-1004297182444, topic_id=40     (newly configured - matches Founder exactly)
REELS     -> chat_id=-1004297182444, topic_id=None   (unchanged, still unconfigured)
```

`INSTAGRAM_TOPIC_FOUND=true`, `INSTAGRAM_TOPIC_THREAD_ID_CONFIGURED=true`,
`INSTAGRAM_PACKAGE_WRONG_TOPIC=false`.

## D. Deployment

Built one immutable image (one Dockerfile serves both `content_worker`/`telegram_bot`, which
differ only by `command:`) from the isolated worktree, tagged `ai-newsroom-content_worker:
instagram-editorial-delivery-4d3c2f0` / `ai-newsroom-telegram_bot:instagram-editorial-delivery-
4d3c2f0` - never `latest`. Reused the exact existing `docker-compose.override.yml` pinning
convention already established by the prior UNIFIED-EDITORIAL-PIPELINE-PRODUCTION-CANARY-2 phase
(which pins `content_worker` to its own approved image, `UNIFIED_EDITORIAL_PIPELINE_ENABLED=
"true"` preserved unchanged) - extended it with a new `telegram_bot` block (none existed before).
Recreated only `content_worker`/`telegram_bot` via `docker compose up -d --no-deps`. `backend`,
`automation_worker`, `news_analysis_worker`, `postgres`, `redis` were never restarted (confirmed
via unchanged uptimes before/after).

**DB migrations** (§7 - reported before applying, per explicit approval): two migrations were
pending, both purely additive (new table + new enum type each, already reviewed in prior phase
reports) - `d7e4a92f1b83` (instagram_publication_jobs) and `a3f7c1e9b204`
(instagram_editorial_deliveries). Applied with explicit Founder approval. A third, corrective
migration (`b7d1f92a4e6c`) was added mid-phase - see H.

## E. Service health

Post-deploy (both recreations): `content_worker`/`telegram_bot` `running`, `RestartCount=0`.
`telegram_bot`'s live Dispatcher confirmed to include the new `instagram_editorial_review` router
(checked directly against the running process). Postgres `healthy`. Redis `role=master`,
`6379/tcp` not publicly bound. No config/import/runtime loop observed at any point.

## F. Canary package

No naturally-occurring live Instagram candidate appeared during this session's own window (no
autonomous scheduler produces Instagram candidates yet - a pre-existing, disclosed gap from the
prior phase, not attempted to be fixed here). Per §12's own explicit fallback, one controlled,
production-shaped package was built through the REAL pipeline from a REAL recent production story
(pulled read-only via SSH+psql): "Blizzard анонсировала новый шутер StarCraft с открытым миром"
(`news_events.id = c4b6f23e-e1aa-4df3-a920-f3bbb266eeb4`) - `gate_decision=ready_for_editor`,
delivered via the real `deliver_instagram_package()` code path, never a fabricated/simulated
outcome.

## G. Topic correctness

Verified directly against the persisted delivery row and the live settings the send actually used:
`chat_id=-1004297182444`, `message_thread_id=40` - exactly Founder's authoritative values, never
the chat root, never another topic. `CORRECT_TELEGRAM_TOPIC=true`.

## H. Media/caption integrity — real bug found and fixed mid-canary

The **first** real send attempt hit a genuine production bug: `InstagramEditorialDelivery.
telegram_chat_id` was declared `Integer` (32-bit) - Telegram's real supergroup id
(`-1004297182444`) is far outside int32 range. The two real Telegram messages (a photo and the
caption/keyboard message) **were already sent successfully** by the time the subsequent database
write raised `asyncpg.exceptions.DataError: value out of int32 range`. The whole DB transaction
rolled back (confirmed: zero rows existed afterward), so no corrupted/stuck row was left behind -
but the two now-orphaned real Telegram messages existed with no durable record.

**Fix, in order**: (1) widened `telegram_chat_id` and (proactively, same overflow class)
`decided_by_telegram_user_id` to `BigInteger` via a new additive migration; (2) fixed the test
fixture that had been using an artificially small chat id (`-1009999`, which fit safely in int32
and had masked this exact bug class) to a realistically-sized one, and added an explicit
regression test using the real production chat-id shape; (3) rebuilt the image from the fixed
commit (`4d3c2f0`) and re-deployed; (4) applied the corrective migration to production; (5)
**deleted the two orphaned messages** from the failed first attempt (confirmed via
`bot.delete_message()` succeeding on both - itself proof the first send really had reached
Telegram); (6) re-ran the canary cleanly. The second attempt succeeded end-to-end: persisted row
`telegram_chat_id=-1004297182444`, `telegram_topic_id=40`, `media_message_ids=[1801]`,
`control_message_id=1802`, `state=DELIVERED`.

`MEDIA_COMPLETE=true`, `CAPTION_COMPLETE=true` (the full caption text was built by
`present_single()`, well under Telegram's message limit, never truncated).
`PACKAGE_ASSET_EQUALS_TELEGRAM_ASSET=true` (the exact rendered image bytes were sent - no
substitution point exists in the code path). `SOURCE_TRACEABILITY_READY=true` as a capability (the
"🔗 Источник" button renders when a `source_url` is supplied); this specific canary package
disclosed no source URL was fetched for it (a real, but non-controversial, publicly-known gaming
announcement), so no source button was shown for this particular delivery - not a defect, a
disclosed scope choice for this one canary story.

## I. Buttons

The delivered control message carries exactly the intended keyboard (✅ Принять / 🔄 Переделать /
📝 Текст / 🎨 Визуал), built by the same `build_review_keyboard()` already covered by 24 passing
unit tests, including an explicit structural test proving no "🚀 Опубликовать" (or any
publish-capable) button can ever be produced by this codec. Per the phase's own explicit
instruction, no button was pressed automatically - the delivered package awaits Founder's own
manual action.

## J. Idempotency

Directly re-verified against the real production database, not merely by unit test: re-running the
exact same canary script a second time against the SAME real DB row returned
`outcome.sent=False, reason=duplicate_skipped`, same `delivery_id`, same `version=1`, and the
persisted row's `media_message_ids`/`control_message_id`/`updated_at` were confirmed unchanged -
**no second Telegram send occurred**. `DUPLICATE_TELEGRAM_PACKAGE_SENDS=0`.
`DOUBLE_APPROVAL_SIDE_EFFECTS=0`/`DOUBLE_REGENERATION_JOBS=0` trivially hold (no button was pressed
this phase, so neither code path executed at all - both remain covered by their own unit tests
from the implementation phase).

## K. Existing Telegram flow freeze

`resolve_route()` re-verified live for NEWS/MEME/TELEGRAPH/REELS - all four unchanged from their
pre-canary values (§C). `content_worker`/`telegram_bot`'s only code change from this phase's own
diff is the addition of the Instagram editorial-delivery modules and the one new router
registration - no NEWS/MEME/TELEGRAPH handler or presentation module was touched.
`TELEGRAM_EXISTING_FLOW_CHANGED=false`.

## L. Instagram write safety

`INSTAGRAM_PUBLICATION_ENABLED=false`, `INSTAGRAM_AUTONOMOUS_PUBLICATION=false` confirmed against
the live running settings both before and after deployment. `INSTAGRAM_WRITE_CALLS=0`,
`INSTAGRAM_PUBLICATION_PERFORMED=false` - no code path exercised this canary imports or calls
`services/instagram_publish_adapter.py` or `services/instagram_account_reader.py` (structurally
verified by the implementation phase's own `ast`-based test, unchanged this phase). Neither
`MEDIA_HOSTING_READY` nor Instagram credential state was read anywhere in the delivery path -
`MEDIA_HOSTING_FALSE_BLOCKS_TELEGRAM_EDITORIAL=false`,
`INSTAGRAM_CREDENTIALS_REQUIRED_FOR_TELEGRAM_EDITORIAL=false`.

## M. Observation

A full 30-minute, 6-checkpoint (5-minute interval) background observation ran against the live
production host, checking `content_worker`/`telegram_bot`/`backend`/`automation_worker`/
`news_analysis_worker` restart counts, Postgres health, Redis role/port exposure, the
`instagram_editorial_deliveries` row count, and `telegram_bot`/`content_worker` error-log counts.
All 6 checkpoints (18:37, 18:42, 18:48, 18:53, 18:58, 19:03) came back identical and clean:

```
cw_restarts=0 tg_restarts=0 backend_restarts=0 automation_restarts=0 newsanalysis_restarts=0
db_health=healthy redis_role=master redis_port=6379/tcp
delivery_row_count=1 tg_bot_errors_6min=0 content_worker_errors_6min=0
```

`delivery_row_count` stayed at exactly 1 across the entire window - independent, real-time
confirmation (on top of the explicit re-run test in §J) that no duplicate resend ever occurred.
Zero errors logged by either service across the full 30 minutes. Separately, direct log inspection
of `automation_worker`/`news_analysis_worker` (§K) showed continuous, normal NEWS-pipeline activity
(new `EditorialTask`s created, `analysis_cycle_finished` every ~60s) throughout and after the
deploy - the existing newsroom flow was never interrupted.

## N. Rollback readiness

Not triggered - no rollback condition from §18 occurred (correct topic, no duplicate spam beyond
the disclosed-and-cleaned bug in H, no existing-flow regression, no Instagram write, no service
restart loop, no DB instability). Rollback images/config preserved regardless: the prior
`docker-compose.override.yml` content_worker pin (`ai-newsroom-content_worker:unified-vision-
77a105f`) is recorded in this report and in git history; reverting is a two-line override-file
edit plus `docker compose up -d --no-deps content_worker telegram_bot` (telegram_bot would need a
prior working tag identified before this phase, since it had no override before - `ai-newsroom-
telegram_bot:d2dea2c`, the tag it was running before this phase, per this phase's own pre-deploy
snapshot). The corrective migration (`b7d1f92a4e6c`) and the two prior ones have clean
`downgrade()`s if ever needed - not exercised, since no rollback condition occurred.

## O. Final verdict

Every hard gate passed: correct topic, real package, no duplicate sends, no existing-flow
regression, zero Instagram writes, clean 30-minute observation. One real bug (H) was found and
fully fixed, tested, and re-verified within this same phase before the canary was declared
complete - disclosed in full above, not hidden.

**`INSTAGRAM_TELEGRAM_EDITORIAL_DELIVERY_PRODUCTION_PASS`**
