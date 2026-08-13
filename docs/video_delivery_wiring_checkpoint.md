# Video Delivery Wiring Checkpoint

**Scope:** Wire the existing, already-built video pipeline (discovery → validation → persistence
→ ranking → rich-media delivery) into `worker/content_cycle.py`'s live send path. Minimal wiring
only — no new subsystem, no redesign, no changes to discovery or ranking logic. Direct follow-up
to the read-only audit delivered in this same conversation.

**Not committed. Not deployed. `rich_media_mode` and `video_discovery_mode` are unchanged in
config (both stay `"off"` by default) — nothing in production behavior changes until an operator
explicitly sets `rich_media_mode="enforce"`.**

---

## 1. What already existed (unchanged, reused verbatim)

Per the prior audit, every component below was already implemented and tested; none of it was
modified in this phase:

| Component | File |
|---|---|
| Discovery (RSS/HTML/og:video/Twitter card, URL classification) | `services/video_discovery.py` |
| Bounded validation (direct-hosted only) | `services/video_discovery.py` |
| Persistence — write | `services/video_discovery_persistence.py::persist_video_hint` |
| Persistence — read | `services/video_discovery_persistence.py::get_video_candidates_for_event` |
| Schema | `schemas/video_candidate.py` (`NativeVideoHint`, `VideoPlatform`, `VideoDiscoveryMethod`, `VideoValidation`) |
| DB table | `content_draft_media_items` (migration `f2654fa00185`, confirmed applied — 39 real rows, all `youtube`/`unvalidated_hosted_platform`) |
| Ranking (video-aware) | `services/media_ranking.py::rank_media_candidates` |
| Rich-media plan construction incl. `InputMediaVideo` | `services/image_preview_notifier.py::build_rich_media_plan` |
| Full mixed-media send function | `services/image_preview_notifier.py::send_news_with_rich_media` |
| Feature flags | `core/config.py::video_discovery_mode`, `rich_media_mode` (both three-state, both default `"off"`) |

None of these files were touched.

## 2. Files changed

| File | Change |
|---|---|
| `services/video_discovery_persistence.py` | +27 lines. Added `to_native_video_hint(candidate: EligibleVideoCandidate) -> NativeVideoHint \| None` — pure converter, no I/O. Added `VideoDiscoveryMethod`/`VideoPlatform` to the existing import line. |
| `worker/content_cycle.py` | +15/-1 lines. Added one import line (`get_video_candidates_for_event`, `to_native_video_hint`). Replaced the hardcoded `build_rich_media_plan(top_candidates, None, caption=html)` with a gated retrieval/conversion block. |
| `tests/test_video_discovery_persistence.py` | +71 lines. 4 new converter unit tests. |
| `tests/test_router_media_integration.py` | +135 lines. 3 new worker-integration tests. |

Diffstat: 4 files changed, 246 insertions(+), 2 deletions(-).

## 3. The converter

```python
def to_native_video_hint(candidate: EligibleVideoCandidate) -> NativeVideoHint | None:
    try:
        return NativeVideoHint(
            discovery_method=VideoDiscoveryMethod(candidate.discovery_method),
            remote_url=candidate.remote_url,
            platform=VideoPlatform(candidate.platform),
            declared_width=candidate.declared_width,
            declared_height=candidate.declared_height,
            declared_mime_type=candidate.declared_mime_type,
            declared_duration_seconds=candidate.declared_duration_seconds,
        )
    except ValueError:
        return None
```

Placed in `services/video_discovery_persistence.py`, next to the type it converts from
(`EligibleVideoCandidate`) and the type it converts to (`NativeVideoHint`, imported from
`schemas.video_candidate`, already used elsewhere in the same file). No duplicated
validation/classification logic — it only re-wraps already-validated stored strings into their
enum form. Returns `None` (never raises) if a stored value no longer maps onto a known enum
member, which the caller treats identically to "no video available."

## 4. Wiring path — before / after

**Before** (`worker/content_cycle.py`, inside the V8-family rich-media branch):
```python
top_candidates = _select_top_ranked_image_candidates(eligible_candidates, limit=_MAX_ROUTER_IMAGES)
plan = build_rich_media_plan(top_candidates, None, caption=html)
```
`video_hint` was hardcoded to `None` — `build_rich_media_plan`'s video parameter was reachable in
production but never exercised.

**After:**
```python
top_candidates = _select_top_ranked_image_candidates(eligible_candidates, limit=_MAX_ROUTER_IMAGES)
video_hint = None
if settings.rich_media_mode == "enforce":
    async with session_factory() as video_session:
        video_candidates = await get_video_candidates_for_event(video_session, event.id, limit=1)
    if video_candidates:
        video_hint = to_native_video_hint(video_candidates[0])
plan = build_rich_media_plan(top_candidates, video_hint, caption=html)
```

Full path when `rich_media_mode == "enforce"`:
```
event.id
  -> get_video_candidates_for_event()   [existing, unmodified read contract]
  -> to_native_video_hint()             [new, pure converter]
  -> build_rich_media_plan()            [existing, unmodified]
  -> send_media_group_to_editorial_destination()   [existing, unmodified - already
                                                      catches TelegramAPIError internally,
                                                      never raises]
```

When `rich_media_mode` is `"off"` or `"shadow"` (both current defaults), the `if` body never
runs — zero extra DB query, `video_hint` stays `None`, behavior is byte-identical to before this
change. This mirrors `rich_media_mode`'s own documented meaning in `core/config.py` ("off": byte-
identical to today's delivery); no code sets `rich_media_mode` to `"enforce"` anywhere — it must
be set externally by an operator.

Ranking (`rank_media_candidates`) was deliberately **not** invoked for video, matching the task's
explicit instruction to reuse only `get_video_candidates_for_event()` and `build_rich_media_plan()`
— `get_video_candidates_for_event(limit=1)` already returns eligibility-filtered
(non-`rejected`), oldest-first candidates, which is sufficient for this minimal wiring.

## 5. Fallback behavior (verified, not just asserted)

| Failure mode | Behavior |
|---|---|
| No video candidate exists for the event | `video_candidates` is `[]` → `video_hint` stays `None` → `build_rich_media_plan` behaves exactly as before (image-only plan) |
| Conversion fails (unrecognized `platform`/`discovery_method` string) | `to_native_video_hint` returns `None` → same as "no candidate" |
| Delivery fails (Telegram API error) | Unchanged — `send_media_group_to_editorial_destination` already catches `TelegramAPIError` internally and returns a non-`sent` `RoutingOutcome`; this was true before this change and is untouched |
| `rich_media_mode` at its default (`"off"`) | The retrieval branch never executes — confirmed by `test_video_lookup_is_never_called_when_rich_media_mode_is_off` |

Image-only delivery (the existing, unmodified flow) is provably unaffected: every pre-existing
test in `tests/test_router_media_integration.py` continues to pass with no changes to its own
code, and `rank_media_candidates`/`services/video_discovery.py` were not touched at all.

## 6. Tests

**New (7 total):**
- `tests/test_video_discovery_persistence.py` (+4): valid direct-hosted conversion, valid YouTube
  conversion, unrecognized-platform → `None`, unrecognized-discovery-method → `None`.
- `tests/test_router_media_integration.py` (+3):
  - `test_valid_video_candidate_reaches_the_media_group_when_rich_media_enforced` — end-to-end:
    seeds one image + a mocked direct-hosted video candidate, `rich_media_mode="enforce"`, asserts
    the real `bot.send_media_group` call's `media` list ends with an `InputMediaVideo` whose URL
    matches the candidate.
  - `test_no_video_candidate_leaves_image_only_delivery_unchanged` — `rich_media_mode="enforce"`,
    no video candidates → image-only group sent, no `InputMediaVideo` present, no crash.
  - `test_video_lookup_is_never_called_when_rich_media_mode_is_off` — default config → the video
    lookup mock is never called at all.

**Results:**

| Suite | Result |
|---|---|
| `test_video_discovery.py`, `test_video_discovery_validation.py`, `test_video_discovery_persistence.py`, `test_video_discovery_integration.py`, `test_media_ranking.py`, `test_media_ranking_story_reuse.py`, `test_rich_media_notifier.py` | 100/100 passed |
| `test_router_media_integration.py` (new 3 tests, isolated run) | 3/3 assertions passed |
| `test_router_media_integration.py` (full file, 80 tests) | 45 passed cleanly; 35 (including all 3 new tests and 32 pre-existing ones) passed their assertions but then hit a pre-existing, unrelated teardown-fixture error — see below |
| News golden suite (`scripts/run_news_golden_suite.py`) | 39/39 PASS |
| Architecture validation (`scripts/validate_architecture.py`) | clean, 0 forbidden-dependency violations |

**Pre-existing teardown issue (not caused by this change, not fixed):** when the full
`test_router_media_integration.py` file runs as one session, tests whose fixture creates a
`ContentDraftEditorialPlan` row hit a `ForeignKeyViolationError` during fixture teardown
(`DELETE FROM news_events` fails because `content_draft_editorial_plans_event_id_fkey` still
references it) — a pytest `ERROR`, not a `FAILED`; the test's own assertions already passed by
that point. Verified this reproduces identically on a clean `git stash` of this change (same test,
same error, same query), confirming it predates this phase and is unrelated to video wiring.
Consistent with this session's standing convention, documented here and left unfixed.

## 7. Remaining limitations (disclosed, not solved here)

- **No real direct-hosted video has ever been observed in production data.** All 39 persisted
  rows are `youtube`/`unvalidated_hosted_platform`, which `build_rich_media_plan` turns into a
  caption link, not an `InputMediaVideo` attachment. The `InputMediaVideo` path is fully wired and
  unit/integration-tested with a synthetic candidate, but has not yet run against a real
  direct-hosted video in this environment.
- **Video-only delivery is not reachable.** The new retrieval only runs inside the existing
  `is_v8 and html is not None and eligible_candidates` branch — i.e., only when at least one
  eligible image candidate already exists. A story with a discovered video but zero eligible
  images still falls through to the pre-existing single-image/text path with no video. Extending
  that would be a larger change than "minimal wiring" and was out of scope here.
- **Selection is "oldest persisted candidate," not ranked.** Per the task's explicit instruction
  to reuse only `get_video_candidates_for_event()`/`build_rich_media_plan()`, `rank_media_candidates`
  was not wired in for video. With multiple video candidates for one event, the first persisted
  one (not necessarily the best) is used.
- **Activation requires two flags, not one.** `video_discovery_mode` must already be `"shadow"`/
  `"enforce"` for rows to exist at all; `rich_media_mode` must be `"enforce"` for this new wiring
  to look them up. Both remain `"off"`/unset by any code in this change.

---
Stopping here per task instructions — not committed, not deployed.
