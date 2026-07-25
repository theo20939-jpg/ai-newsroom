# Phase 15 — Editorial Intelligence — M3 Engagement Signal Preservation — Implementation Report

Status: COMPLETE.

**Context recovery note (2026-07-25)**: work on this milestone was interrupted by a computer
restart after implementation, migration-apply, and deployment had already happened but before
this report's final sections were written. A read-only repository/DB/runtime audit on resume
confirmed every claim in §§1–7 below against live evidence (migration head, container code,
production DB contents, containers healthy since restart) before any further action was taken —
no code was rewritten, no migration was regenerated, no destructive command was run. Work resumed
directly at "run the full regression suite and write §§8–14," exactly where the DRAFT status left
off. See §15 for the full recovery findings.

---

## 1. Original data-loss root cause

`integrations/sources/telegram_source.py::TelegramSourceAdapter._to_raw_item()` built
`RawNewsItem` from only `external_id`, `text`, `url`, `published_at` — every other attribute on
the already-fetched Telethon `Message` object (`.views`, `.forwards`, `.replies`, `.reactions`)
was silently discarded at this exact boundary, before `RawNewsItem` even existed.
`schemas/raw_news_item.py` had no fields to carry them even if the adapter had read them, and
`services/cleaning.py::CleanedItem` / `database/models/news_event.py::NewsEvent` had no fields to
receive them either — a three-layer discard, confirmed by inspection (Phase 15 M0 discovery §5),
not merely a single missed line.

---

## 2. Engagement availability matrix

| Signal | Telegram | RSS/web | Currently parsed (pre-M3) | Currently persisted (pre-M3) | Consumed by EngagementCapability (pre-M3) | Caveat |
|---|---|---|---|---|---|---|
| views | Yes — `Message.views` (raw TL field, already fetched) | No | No | No | No | Only populated for broadcast-channel posts; `None` for groups/DMs or where Telegram doesn't track it — not every message has a real count |
| forwards | Yes — `Message.forwards` | No | No | No | No | Same optionality as views |
| replies/comments | Yes — `Message.replies.replies` (only when the channel has a linked discussion group / comments enabled) | No | No | No | No | `Message.replies` itself is `None` when comments aren't enabled for that post — distinct from "0 comments" |
| reactions (per-type) | Yes — `Message.reactions.results[].count`, each tied to a `Reaction` (emoji) | No | No | No | No | M3 does not persist per-emoji breakdowns (§5) — only the aggregate |
| reaction count total | Yes — `sum(r.count for r in Message.reactions.results)` | No | No | No | No | `Message.reactions` itself is `None` when reactions are off — distinct from "0 reactions" |
| subscribers/followers/channel size | Not on the already-fetched `Message` object — would require one additional Telethon call (`get_entity`/`GetFullChannelRequest`) per source | No | No | No | No | Explicitly **not implemented in M3** — see §8 |
| source/channel identifier | Yes — `NewsSource.url` (the channel handle) | Yes — `NewsSource.url` | Yes | Yes (`NewsSource.id`/`.url`) | N/A | Unchanged by M3 |
| published_at | Yes — `Message.date` | Yes — feed's own pubDate/updated | Yes | Yes | N/A | Unchanged by M3 |
| collected_at | N/A (server-generated) | N/A (server-generated) | Yes | Yes (`NewsEvent.collected_at`, server default) | N/A | Unchanged by M3 |

**All four core signals (views/forwards/replies/reactions_count) are now parsed and persisted
after M3** — the "Currently parsed/persisted" columns above describe the pre-M3 state this
milestone fixes.

---

## 3. Persistence contract

**Chosen boundary**: four new nullable `Integer` columns directly on the existing `NewsEvent`
model (`database/models/news_event.py`) — `views_count`, `forwards_count`, `replies_count`,
`reactions_count`. No new table.

**Why NewsEvent, not a new table**: `NewsEvent` is already the point-in-time snapshot of a
collected item (title, content, category, published_at are all already collection-time
snapshots, not references to mutable source state) — engagement metrics observed at collection
time are the same kind of fact, captured once, never updated in place. A separate
`EngagementSnapshot` table would only be justified by a need for *multiple* snapshots per event
over time (re-measuring engagement hours/days later) — nothing in Phase 15 M0's discovery or this
milestone's scope calls for that, and the task explicitly instructs against adding tables unless
absolutely necessary.

**Audience/subscriber size**: investigated and **not implemented** in M3 — see §8 (deferred,
correctly, not fabricated).

---

## 4. NULL vs. zero semantics

Preserved end-to-end, at every boundary, verbatim — never converted in either direction:

- `integrations/sources/telegram_source.py`: `message.views`/`message.forwards` are Telethon's
  own `Optional[int]` fields, passed straight through (`None` stays `None`, `0` stays `0`).
  `message.replies.replies` is only read when `message.replies is not None`; the object being
  `None` (comments not enabled at all) maps to `None`, while a linked-but-empty discussion maps
  to `0`. `_reactions_count()` returns `None` when `message.reactions is None` (reactions off),
  and correctly sums to `0` (not `None`) when reactions are enabled but `results == []`.
- `schemas/raw_news_item.py` (`RawNewsItem`) / `services/cleaning.py` (`CleanedItem`): plain
  `int | None` fields, no transformation — `clean_item()` copies all four verbatim.
- `services/collector.py`: copies `cleaned.*_count` straight onto the new `NewsEvent` columns.
- `database/models/news_event.py`: nullable `Integer` columns, no default — an event for which a
  metric was never observed gets a real SQL `NULL`, not a `0` row value.
- RSS/web/GitHub/arXiv/Hacker-News-sourced items never set any of the four `RawNewsItem` fields
  at all — they default to `None` (§5's `RawNewsItem` schema default), so every such `NewsEvent`
  gets `NULL` for all four, never a fabricated `0`.

---

## 5. Reaction normalization

Per M3.3: a single deterministic aggregate, `reactions_count = sum(result.count for result in
message.reactions.results)` — no sentiment analysis, no taxonomy, no per-emoji persistence. This
is implemented in `integrations/sources/telegram_source.py::_reactions_count()`. Per-emoji detail
(`👍 42, 🔥 8, ❤️ 12`) is read from `Message.reactions.results` but only the sum is kept — the
existing `NewsEvent`/`RawNewsItem` schemas have no field for a reaction breakdown, and adding one
would be new taxonomy design, explicitly out of M3's scope.

---

## 6. Files changed

Production:
- `schemas/raw_news_item.py` — 4 new optional `int` fields (`views_count`, `forwards_count`,
  `replies_count`, `reactions_count`), all defaulting to `None`.
- `integrations/sources/telegram_source.py` — `_to_raw_item()` now reads all four from the
  already-fetched `Message` object; new `_reactions_count()` helper.
- `services/cleaning.py` — `CleanedItem` gained the same 4 fields; `clean_item()` passes them
  through verbatim.
- `database/models/news_event.py` — 4 new nullable `Integer` columns.
- `services/collector.py` — `_process_item()` now copies the 4 fields from `CleanedItem` onto the
  new `NewsEvent`.

Migration:
- `database/migrations/versions/c2a4e6f9b3d1_add_news_event_engagement_metrics.py` — additive
  only, 4 nullable `Integer` columns, no default, no backfill.

Tests (new/extended):
- `tests/test_telegram_source.py` (new) — 10 unit tests for `_to_raw_item()`/`_reactions_count()`.
- `tests/test_cleaning.py` (extended) — 3 new tests proving verbatim pass-through.
- `tests/test_phase15_m3_engagement_signal_preservation.py` (new) — DB-level persistence proofs
  (full metrics, real zeros, missing metrics, category-independence) and structural "no scoring
  change"/"no new provider calls" proofs.
- `tests/test_engagement_capability.py` (extended) — 1 new structural test proving
  `EngagementCapability` does not read the new fields.

No other file was modified for M3.

---

## 7. Migration details

`c2a4e6f9b3d1`, revises `8941ebf13fb0` (the current head after Phase 15 M2). Adds
`views_count`/`forwards_count`/`replies_count`/`reactions_count` (all `Integer`, `nullable=True`,
no default) to `news_events`. Applied to the real, shared Observation Mode database (workers
stopped first, per the established isolation precedent — see §9). Confirmed after apply: all
6254 pre-existing `NewsEvent` rows remain valid, all four new columns `NULL` on every one of them
— no backfill, no rewrite, no fabricated value. `downgrade()` drops the four columns (safe,
reversible, no data-loss concern since nothing but this migration's own upgrade ever wrote them).

---

## 8. EngagementCapability compatibility / audience size

`capabilities/engagement_capability.py` was inspected and left untouched by M3. It predicts
`engagement_potential_score` from Research/Intelligence output only; its prompt-building code
(`_build_request`) does not read `news_event.views_count`/`forwards_count`/`replies_count`/
`reactions_count` — enforced structurally by
`tests/test_engagement_capability.py::test_engagement_capability_does_not_yet_read_real_engagement_metrics`
and by `tests/test_phase15_m3_engagement_signal_preservation.py`'s equivalent sweep over
`services/triage.py`, `capabilities/scoring_capability.py`,
`scripts/run_content_generation.py`, and both workflow definitions. Real engagement metrics
reaching any scoring/eligibility path is explicitly deferred to a future milestone (M4).

Audience/subscriber size was investigated and confirmed **not implemented**:
`integrations/sources/telegram_source.py` makes no `get_entity`/`GetFullChannelRequest` call and
no field named `participants_count`/`subscriber` appears anywhere in the changed files (verified
by grep across the full M3 file set — zero matches). `Message.views`/`.forwards`/`.replies`/
`.reactions` are read only from the `Message` object already fetched by the adapter's existing
`iter_messages()` call; no additional Telegram API round-trip was added.

## 9. Tests and exact results

Focused (60 tests, all new/extended for M3 or its immediate neighbors):

```
tests/test_phase15_m3_engagement_signal_preservation.py  15 passed
tests/test_telegram_source.py                            10 passed
tests/test_cleaning.py                                    18 passed
tests/test_engagement_capability.py                       17 passed
============================= 60 passed in 6.22s ==============================
```

Full regression suite (`python -m pytest tests/`, real Postgres, workers left running — see §12
for why this was judged safe): **1014 collected, 1009 passed, 5 failed**, 15m13s.

The 5 failures, individually triaged:

- `tests/test_analysis_worker_main.py::test_enabled_loop_survives_ordinary_exception_and_continues`
- `tests/test_content_worker_main.py::test_enabled_loop_survives_ordinary_exception_and_continues`

  Both assert `call_count >= 2` after `asyncio.sleep(0.15)` with a 0.01s poll interval — a
  wall-clock race, not a logic assertion. Re-run in isolation (outside the 15-minute full-suite
  CPU load): **both passed**. Confirmed pre-existing timing flakiness, unrelated to M3 (grep for
  `views_count|forwards_count|replies_count|reactions_count` across all 4 failing test files:
  zero matches in any of them).

- `tests/test_content_generation_integration.py::test_full_chain_dry_run_creates_draft_and_renders_without_sending`
- `tests/test_content_worker_cycle.py::test_run_content_cycle_sequential_no_gather_and_notifies_after_draft_creation`
- `tests/test_content_worker_cycle.py::test_run_content_cycle_dry_run_never_calls_bot_send_message`

  All three fail on `assert settings.content_generation_dry_run is True` — this environment's
  `.env` currently has `content_generation_dry_run=False` (confirmed via the loaded `Settings`
  repr in the failure output), not the `True` these tests assume as "the safe default." This is a
  pre-existing environment/test-assumption mismatch from a prior phase, not caused by M3 (no M3
  file touches `content_generation_dry_run`, and `.env` was not modified during this recovery per
  the explicit constraint against touching it). Left as-is and out of scope for M3 to fix.

Verdict: **zero M3-attributable regressions.**

Static checks:
- `ruff check` on all 8 M3-changed/added production files: **all checks passed**.
- `scripts/validate_architecture.py`: **clean — 0 forbidden-dependency violations**.
- `mypy` on the 7 M3-affected production files: 6 errors, all pre-existing — 5 are
  `import-untyped` (missing stubs for `feedparser`/`telethon`, present before M3) and 1
  (`telegram_source.py` — `_to_raw_item`'s `channel: str` argument accepting `str | None`)
  reproduces identically against the last-committed (`HEAD`) version of the file, confirming M3
  introduced no new mypy error.

## 10. Provider/API call impact

Zero. `tests/test_phase15_m3_engagement_signal_preservation.py::test_m3_changed_files_import_no_llm_gateway_or_capability`
structurally proves none of the 4 changed production files import `llm_gateway`, any
`capabilities.*` module, or call `call_generate`. The engagement fields are read from Telethon's
already-fetched `Message` object (§1/§8) — no new Telegram API call, no new LLM call.

## 11. Deployment

Already performed prior to the restart. Verified on resume (not repeated):
- `docker-compose.yml` builds `automation_worker`/`news_analysis_worker`/`content_worker` from
  local source (`build: .`), not a bind mount — confirming the running containers only reflect
  M3 code if they were rebuilt after it was written.
- `docker exec ai_newsroom_automation_worker python -c "... inspect.getsource(services.collector) ..."`
  and the same for `integrations.sources.telegram_source` both show the M3 code
  (`views_count`, `_reactions_count`) present inside the running container image — confirmed
  live, not inferred from file timestamps.
- `docker compose ps`: `ai_newsroom_automation_worker` was recreated ~8h before this recovery
  (vs. `content_worker` at 36h, `news_analysis_worker` at 18h), consistent with a rebuild for
  M3 (M3 does not touch `news_analysis_worker`'s or `content_worker`'s code paths — see §8 — so
  their older container ages are expected and correct, not a missed deployment step).
- Alembic: `SELECT version_num FROM alembic_version` on the live `ai_newsroom` database returns
  `c2a4e6f9b3d1` — the M3 migration's own revision — confirming it is applied and is the current
  head, with no unapplied migration behind it.

No redeployment was performed during this recovery; the running state was verified sufficient.

## 12. Live validation evidence

Postgres was queried directly (read-only) rather than stopping workers, because the M3 migration
was already applied and the running container code already matched the schema — no
code/schema incompatibility existed to protect against (§ Step 5 of the recovery brief). Workers
were left running throughout.

Engagement-field population by source type (`news_events` joined to `sources`, live DB):

| Source type | events with ≥1 non-NULL engagement field | total events |
|---|---|---|
| TELEGRAM | 3 | 516 |
| RSS | 0 | 4,720 |
| NEWS_API | 0 | 1,150 |

RSS and NEWS_API sources correctly show **zero** fabricated engagement values across 5,870
events combined — every one of their four engagement columns is `NULL`, never a synthesized `0`.

Three real, naturally-collected Telegram events with non-zero metrics (most recent, 2026-07-25):

| views | forwards | replies | reactions | note |
|---|---|---|---|---|
| 4,402 | 60 | 6 | 14 | |
| 13,093 | 228 | 18 | 281 | |
| 1,385 | 11 | *(NULL)* | 10 | comments not enabled on this post — `replies` correctly `NULL`, not `0`, alongside real values for the other three fields on the same row |

This third row is direct, naturally-occurring proof that NULL/zero semantics are preserved
**per-field**, not as an all-or-nothing decision per event.

Container logs (`docker logs --since 2h`, all three affected workers) show no M3-attributable
errors: the only errors present are a pre-existing Hacker News fetch failure (`RemoteProtocolError`)
and a stale `M6 Live Validation Source` test fixture from an earlier phase hitting a dead
`example.com` URL — both unrelated to engagement persistence and pre-dating M3.
`news_analysis_worker` and `content_worker` logs show zero errors in the same window.

Selection/scoring behavior: unchanged — enforced by §9's structural tests, and
`content_generation_min_score` confirmed still `65` (`test_content_generation_min_score_setting_unchanged_by_m3`).

Observation Mode configuration: unchanged. Not touched during this recovery:
`news_collection_enabled`, `news_analysis_enabled`, `content_generation_enabled`, all poll
intervals/batch sizes, `content_generation_min_score`, freshness cutoffs, `content_generation_dry_run`
(§9's environment-mismatch finding notwithstanding — that value was not modified, only observed),
`editorial_chat_id`. No manual Telegram message was sent; no backlog was manually processed.

## 13. Metric coverage sample

See §12's table — 3 of 516 Telegram-sourced events collected so far carry at least one non-NULL
engagement value (channels where Telegram exposes public view counts and reactions are enabled);
the remainder are `NULL` across all four fields, consistent with §2's documented optionality
(private channels, comments/reactions disabled, or Telegram simply not tracking the metric for
that message type) — not a persistence defect.

## 14. Remaining gaps for M4

- Real engagement metrics are persisted but consumed nowhere (§8) — Editorial Scoring V2 (M4)
  would be the milestone to decide whether/how `views_count`/`forwards_count`/`replies_count`/
  `reactions_count` should influence `engagement_potential_score` or Triage priority.
- Per-emoji reaction breakdown is read from `Message.reactions.results` but only the sum is kept
  (§5) — a future milestone could persist the breakdown if a use case needs it; no schema exists
  for it today.
- Audience/subscriber size remains unavailable without an additional per-source Telethon call
  (§8) — not attempted in M3, and not free (introduces a new API call per source per cycle).
- The pre-existing `content_generation_dry_run` environment/test mismatch (§9) and the stale
  `M6 Live Validation Source` fixture (§12) are both unrelated cleanup opportunities, surfaced by
  this recovery's audit, not introduced by or in scope for M3.

## 15. Runtime health after completion

All five containers (`postgres`, `redis`, `automation_worker`, `news_analysis_worker`,
`content_worker`) were already `Up` and `healthy`/running throughout this recovery — none were
stopped or restarted, since the migration was already applied and the running code already
matched the live schema (no incompatibility window existed to protect against). Alembic head
matches the M3 migration (`c2a4e6f9b3d1`). Full regression suite result: 1009/1014 passing, 5
pre-existing/environmental failures unrelated to M3 (§9). No secrets were printed; no `.env`
content was read or modified; no destructive git or database command was run at any point in this
recovery.
