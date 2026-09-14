# INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1 — Production Canary Report

Development branch: `feature/instagram-automatic-editorial-trigger-1` (`68ac76f`). Deployed
branch: `feature/instagram-automatic-editorial-trigger-data-v2-integration-1` (`1be8162`) - see §A
for why a merge was required. No Instagram Graph API call anywhere in this phase. Both publication
flags remained `false` throughout. No DB migration.

## A. Unplanned integration requirement discovered before deploy

Before touching production, the pre-deploy snapshot found `content_worker` already running a
DIFFERENT image than expected: `ai-newsroom-content_worker:data-semantic-v2-instagram-6e91f6c`,
deployed ~19 minutes earlier by another session/process, per its own
`docker-compose.override.yml` comment: a merge of the Instagram-Telegram delivery lineage
(`593d476`/`4d3c2f0`) with the previously-disclosed-but-undeployed DATA semantic-overflow/parser-v2
hotfix (`45de6d4`/`f5b5225`), on branch
`feature/telegram-data-semantic-parser-v2-instagram-integration-1` (tip `d5295be`).

This meant deploying my own branch (based on `0cae684`, a plain descendant of `4d3c2f0`) directly
would have **reverted the already-live DATA v2 fix**. Per `git diff --name-only 4d3c2f0 6e91f6c`,
the DATA v2 work touches only `services/brand_renderer.py`, `services/editorial_pipeline/
content.py`, `services/render_evidence.py`, plus its own tests/docs/artifacts - zero overlap with
`worker/content_cycle.py` or any file this phase touches. A merge
(`feature/instagram-automatic-editorial-trigger-1` + `feature/telegram-data-semantic-parser-v2-
instagram-integration-1` → `feature/instagram-automatic-editorial-trigger-data-v2-integration-1`,
commit `1be8162`) completed with **zero conflicts**, confirmed by re-running the combined test
suite (168 + 158 = 326 tests, including both DATA v2's own suite and this phase's own suite)
before deploying. This is the same "preserve both, do not roll either back" resolution this
phase's own brief anticipated as a contingency (§10), applied to a second, independently-discovered
integration need.

## B. Deployment

Isolated production worktree (`/opt/ai-newsroom-instagram-automatic-editorial-trigger-1`, detached
at `1be8162`) - `/opt/ai-newsroom`'s own dirty checkout was never touched (confirmed unchanged
before/after: same HEAD `324a57a`, same branch, same uncommitted line count). Built one immutable
image (`ai-newsroom-content_worker:instagram-auto-trigger-1be8162`), confirmed its `alembic heads`
matches production's current DB revision exactly (`b7d1f92a4e6c` - no migration needed), pinned it
via `docker-compose.override.yml` (extending the same pattern three phases have now used), and
recreated ONLY `content_worker`. `telegram_bot` was left untouched (still `instagram-editorial-
delivery-4d3c2f0`) - neither this phase nor the DATA v2 work touches any `bot/` file.
`backend`/`automation_worker`/`news_analysis_worker`/`postgres`/`redis` were never restarted.

## C. Service health

Post-deploy: `content_worker` `running`, `RestartCount=0`, clean `content_cycle_finished` logs
from the first cycle onward. Postgres `healthy`. Redis `role=master`, `6379/tcp` not publicly
bound. No restart loop, no import error, no config error at any point in the observation window.

## D. Production observation (50 minutes, natural traffic only)

A background poll (every ~2.5 minutes, 20 checks) watched `content_worker`/`telegram_bot` restart
counts, `instagram_automatic_trigger_cycle_finished` log occurrences, error-log counts, and the
`instagram_editorial_deliveries` row count - no manual script was run against this deployment at
any point.

**Result**: the automatic trigger fired for real production traffic exactly once during the window
(21:37:38 UTC) - it evaluated a real, fresh, COMPLETED NEWS_ANALYSIS story and correctly rejected
it (treatment was not `MAJOR`), producing zero package and making zero Creative Director call -
confirmed by the complete absence of any `routing_decision`/Creative-Director-related log line tied
to that event. This is a real, successful exercise of the SELECTION gate, not a failure: exactly
the "10 NEWS drafts ≠ 10 Instagram packages" behavior §2 required.

No `MAJOR`-treatment story occurred naturally during this 50-minute window, so **no automatic
READY package was delivered to Telegram topic 40 in this observation**. `instagram_editorial_
deliveries` stayed at 2 rows throughout (both pre-existing manual-canary rows from the prior
phase, from before this phase even started - untouched, unduplicated). All 20 checkpoints: `0`
restarts on every service, `0` errors, stable row count.

A read-only diagnostic (`_select_eligible_events()` invoked directly, twice, minutes apart) found
`0` currently-eligible events both times - real evidence that this production newsroom's NEWS-
content-generation loop is currently draining its own "analyzed but not yet content-generated"
backlog close to as fast as it fills, so the window in which a fresh, still-unprocessed candidate
exists to evaluate is often narrow. This is a genuine traffic-timing characteristic of the current
deployment, not a defect in the trigger.

## E. Why this phase does not claim `PRODUCTION_PASS`

Per §23's own explicit instruction ("Do not force a fake candidate merely for PASS") and §24's
`MANUAL_SCRIPT_USED=false` requirement, this report does not fabricate a delivered automatic
package. The mechanism is proven correctly wired for real production data (real evaluation, real
correct rejection, zero errors, zero regressions, zero Instagram writes) - what remains unproven
by this specific 50-minute window is a real accept-and-deliver path with a naturally-occurring
`MAJOR` story. Given real newsroom volume (confirmed continuous story production throughout this
whole multi-phase session), this is expected to occur within a longer natural observation window -
recommend the Founder either extend passive observation, or authorize a longer monitored window in
a follow-up check.

## F. Safety confirmation

```
INSTAGRAM_WRITE_CALLS=0
INSTAGRAM_PUBLICATION_PERFORMED=false
WRONG_TOPIC_DELIVERIES=0
DUPLICATE_TELEGRAM_PACKAGE_SENDS=0
INSTAGRAM_PUBLICATION_ENABLED=false
INSTAGRAM_AUTONOMOUS_PUBLICATION=false
```

## G. Rollback readiness

Not triggered - no rollback condition occurred. If ever needed: revert `docker-compose.override.
yml`'s `content_worker` image back to `ai-newsroom-content_worker:data-semantic-v2-instagram-
6e91f6c` (the immediately-prior, already-validated production image, preserved and untouched) and
`docker compose up -d --no-deps content_worker`. No DB change to reverse.
