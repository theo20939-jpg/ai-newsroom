# INSTAGRAM-TELEGRAM-EDITORIAL-FLOW-MISSING-1 — Incident Report

## Summary

**No code, runtime, or configuration regression exists.** Every layer of the Instagram→Telegram
editorial-delivery pipeline (routing config, delivery service, persistence/idempotency model, DB
migrations, deployed image) is present, correctly configured, and fully functional - proven by
successfully delivering a brand-new real production package during this incident response.

**Root cause**: the Instagram→Telegram editorial-delivery pipeline was never wired into any
recurring, automatic worker cycle. The one delivery Founder saw
(INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-PRODUCTION-CANARY-1) was a manually-invoked, one-off script
(`scripts/_instagram_telegram_delivery_canary_1.py`), not a standing pipeline - this was
explicitly disclosed in that phase's own report (§P: "no autonomous scheduler produces Instagram
candidates yet") but is being called out again here in incident terms since it produced a real
"the flow stopped" symptom. No script or job has run since that one manual invocation, so zero new
Instagram packages were ever attempted - not "generated but blocked," not "delivered to the wrong
place," not "suppressed by dedup." Nothing failed; nothing tried.

## 1. Production truth audit

```
content_worker: ai-newsroom-content_worker:instagram-editorial-delivery-4d3c2f0, Up (unchanged
                 since the prior canary), RestartCount=0
telegram_bot:    ai-newsroom-telegram_bot:instagram-editorial-delivery-4d3c2f0, Up (unchanged),
                 RestartCount=0
backend/automation_worker/news_analysis_worker: unchanged tags (d2dea2c/6f56aec/d2dea2c) -
                 no deploy touched them
DB revision:     b7d1f92a4e6c (head) - unchanged since the prior canary's final state
instagram_topic_id=40, newsroom_telegram_chat_id=-1004297182444 - both still correctly configured
instagram_publication_enabled=false, instagram_autonomous_publication_enabled=false
```

Nothing has been redeployed, restarted, or reconfigured since the prior canary concluded.

## 2. Code presence (verified live in the running content_worker)

- `resolve_route(EditorialDestination.INSTAGRAM)` → `chat_id=-1004297182444, topic_id=40` ✅
- `services/instagram_telegram_delivery.py`, `services/instagram_editorial_delivery_state.py`,
  `database/models/instagram_editorial_delivery.py` (table `instagram_editorial_deliveries`) all
  present and importable in the deployed image ✅

## 3. DB migration lineage

`alembic history` confirms `d7e4a92f1b83` and `a3f7c1e9b204` are both direct ancestors of the
current head `b7d1f92a4e6c` (`a3f7c1e9b204 -> b7d1f92a4e6c`, `d7e4a92f1b83 -> a3f7c1e9b204`) -
fully applied, nothing missing.

## 4/5. Last successful delivery and pipeline stage trace

- `instagram_editorial_deliveries` held exactly **one** row before this incident response:
  the prior canary's, `created_at = updated_at = 2026-09-14 18:35:52 UTC`. No row's `created_at`
  differs from its `updated_at` - no partial/stuck state anywhere.
- Real NEWS-pipeline activity in the same window was NOT absent: **10 real `content_drafts`**
  were created between 18:35 and the start of this incident response (a healthy, active
  newsroom - Jensen Huang/NVIDIA, Anthropic, Apple iOS 27, Samsung, RTX 5090, several AI-regulation
  stories). None of them were ever candidates for Instagram, because nothing ever submits anything
  to the Instagram package builder automatically.
- Direct source search in the deployed image: the ONLY non-test, non-canary-script caller of
  `deliver_instagram_package()`/`instagram_telegram_delivery` in the entire codebase is the
  callback handler (`bot/handlers/instagram_editorial_review.py`, which only *reacts* to a button
  press on an already-delivered package - it cannot initiate a new one). `worker/content_cycle.py`
  - the actual scheduled loop `content_worker` runs every cycle - contains zero real Instagram
  invocation; its only two mentions of "instagram" are code comments noting the branch "can never
  reach" that destination.

**Classification per the incident's own taxonomy**: not "candidates generated but HOLD/BLOCK", not
"READY but not delivered", not "delivered to the wrong topic", not "duplicate suppression blocking
a new version" - **no Instagram candidate was ever attempted** in the window between the two
canaries.

## 6. DATA Semantic Parser v2

Checked directly: no such work has been deployed to any running service. `backend`,
`automation_worker`, `news_analysis_worker` are all running unchanged image tags from before this
whole Instagram effort began. The only place any "DATA... v2" commits exist at all is inside
`/opt/ai-newsroom`'s own primary checkout (`feature/phase19-editorial-depth-upgrade`, 86
uncommitted local changes, HEAD `324a57a`) - a checkout this and the prior phase were both
explicitly instructed never to touch, and which was never built into any image running in
production. **This hypothesis is ruled out** - there is no interaction between that work and the
Instagram pipeline because that work was never deployed anywhere.

## 7. Verification canary (this incident response)

Ran a SECOND, genuinely new real production story (never previously attempted -
`news_events.id=2794382c-99fe-4859-a2d2-0495648d1dfa`, "Дженсен Хуанг включил Трампа на громкую
связь прямо на сцене саммита", created at 20:29 UTC, well after the prior canary) through the
exact same, untouched, already-deployed code path:

```
gate_decision = ready_for_editor
outcome.sent = True
delivery_id = 56309652-41ad-4aeb-86f3-095bb4ed9f63, version = 1
chat_id = -1004297182444, topic_id = 40 (exact match, verified against the persisted row)
```

`instagram_editorial_deliveries` now holds 2 rows, two distinct `package_identity` values, both
`state=DELIVERED`, both `telegram_chat_id=-1004297182444`/`telegram_topic_id=40`. Zero wrong-topic
rows, zero duplicate rows. No code was changed to make this succeed - the pipeline was never
broken.

## 8. Root cause

**Not a regression. Not missing code lineage. Not a runtime/config defect.** The Instagram→
Telegram editorial-delivery pipeline has no automatic trigger - it only runs when a human manually
executes a one-off script naming a specific real story. Founder's first delivery (canary 1) and
this incident's own verification delivery (canary 2) are both examples of exactly that: manual,
deliberate, one-at-a-time invocations - never a "flow" that runs on its own. Restoring "automatic
Instagram posting into the Telegram topic on every newsroom cycle" is new scope (an autonomous
scheduler/executor wiring the Instagram package builder into `worker/content_cycle.py` or a
dedicated Instagram cadence job) - explicitly not something either this incident response or the
prior implementation phase was authorized to build (the implementation phase's own §20 said
"initial production canary, keep volume controlled" and "do not create fake demo-only delivery
logic" - a recurring scheduler was never in scope, only manual/candidate-driven delivery).

## 9/10. Restoration

No restoration was necessary or performed - there was nothing broken to fix. No config change, no
redeploy, no migration, no code change. Verified the still-fully-functional pipeline with a real,
fresh delivery (§7) instead.

## 11/12. Canary verification

```
INSTAGRAM_WRITE_CALLS=0
INSTAGRAM_PUBLICATION_PERFORMED=false
WRONG_TOPIC_DELIVERIES=0
DUPLICATE_TELEGRAM_PACKAGE_SENDS=0
```

## Recommendation

If Founder wants Instagram packages to keep appearing in the Telegram topic without a manual
script run each time, that requires a new, explicitly-scoped phase to wire a real (volume-
controlled, HOLD/BLOCK-respecting, idempotent - all of which already exist and are tested) trigger
into either `worker/content_cycle.py` or a dedicated scheduled job. This report recommends that as
a distinct next step, not something to retrofit as part of an incident fix.
