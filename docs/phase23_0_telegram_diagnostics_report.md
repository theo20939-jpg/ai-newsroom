# PHASE 23.0A — TELEGRAM DIAGNOSTICS READY

## 1. Branch / HEAD

`feature/phase19-editorial-depth-upgrade` @ `d509566154368bf42d54e7dd66166712d77409cb`
(unchanged — no commit made this phase, matching every prior phase's own convention).

## 2. Working tree state

New this phase (all uncommitted):
- `bot/handlers/whereami.py` — the `/whereami` diagnostic handler.
- `tests/test_whereami_handler.py` — 8 tests (§5).
- `docs/phase23_0_telegram_diagnostics_report.md` — this report.
- `docs/phase23_0_canary_configuration_plan.md` — the canary configuration plan (§7 of the phase
  brief), values only, nothing applied.

Modified:
- `bot/handlers/__init__.py` — registers the new `whereami_router` alongside every existing
  router (one new `router.include_router(whereami_router)` line, nothing else changed).

No migration created or applied (zero schema change — this phase touches no database model). No
`.env`/`.env.example` edit (`git status --short .env .env.example` — empty).

## 3. Bot process state

`ai_newsroom_telegram_bot` was already running (`Up 44-45 hours`) at the start of this phase, but
does **not** bind-mount the `bot/` source directory (`docker-compose.yml`'s `telegram_bot` service
only mounts the read-only `image_storage_data` volume — unlike `backend`, which bind-mounts
`./app`/`./core`/`./database`), so the new handler could not take effect without a rebuild.
Action taken, in order, exactly as reported before execution:
1. `docker compose build telegram_bot` — rebuilt only this one service's image (confirmed by the
   build log: `Image ai-newsroom-telegram_bot Built`).
2. `docker compose up -d --no-deps telegram_bot` — recreated and restarted **only** this
   container (`--no-deps` explicitly prevents Compose from touching any dependency container).
3. Verified via `docker logs ai_newsroom_telegram_bot`:
   ```
   INFO | __main__ | Bot started
   INFO | aiogram.dispatcher | Start polling
   INFO | aiogram.dispatcher | Run polling for bot @nnj_newsroombot id=7688429343 - 'Ninja Newsroom'
   ```
   Confirms the correct bot (`@nnj_newsroombot`, matching the bot the phase brief names) is up and
   polling cleanly, zero errors.
4. Confirmed `content_worker`/`news_analysis_worker` remain `Exited (1)` throughout (checked
   immediately before and immediately after the restart) — neither was started, neither was
   affected by the `telegram_bot`-only restart.

## 4. Diagnostic implementation

`bot/handlers/whereami.py` — a `Router`-registered `/whereami` command handler, the same
`Router`/`Command`/`message.answer()` shape every other handler in this package already uses
(`bot/handlers/status.py`). Reads exactly four fields from the incoming `Message`: `chat.id`,
`chat.type`, `chat.is_forum`, `message.message_thread_id` (plus `message.is_topic_message`, logged
only, not echoed in the reply). Replies with:
```
TELEGRAM ROUTE DEBUG

chat_id: <int>
is_forum: true|false
message_thread_id: <int>|none
```
No DB query, no other Telegram call, no state mutation — `message.answer()` is the handler's only
outbound effect. Not gated behind an admin-authorization check: no such mechanism exists anywhere
in this codebase to reuse (confirmed by grep — no `ADMIN_USER_ID`/allowlist setting, no
auth-filter precedent in any handler), and building one would itself be a scope-exceeding
architecture change for a temporary command. Safe regardless, because the three echoed fields are
ordinary Telegram routing metadata already visible to any chat member through Telegram's own
client UI — never a secret, credential, or personal data field.

## 5. Tests

Test-first discipline verified directly, not merely asserted: the handler file and its router
registration were temporarily removed, `tests/test_whereami_handler.py` was run and failed with
`ModuleNotFoundError: No module named 'bot.handlers.whereami'`, then both files were restored and
the suite re-run to green. 8 tests, covering all 5 required cases:

- **CASE A** (`test_case_a_non_forum_chat_reports_message_thread_id_none`): a plain, non-forum
  chat → reply contains `message_thread_id: none`.
- **CASE B**: two tests — a forum topic with a real integer `message_thread_id` (987) is reported
  verbatim; two distinct topics in the same chat produce distinguishably different reported IDs
  (11 vs. 22) — the direct sanity check for the manual ID-collection workflow itself (§7).
- **CASE C**: two tests — a real (monkeypatched) `telegram_bot_token`/`postgres_password` secret
  value never appears anywhere in the outgoing reply text, and the string `"token"` does not
  appear at all; a second test asserts the reply is *exactly* the four documented lines (header,
  blank line, `chat_id`, `is_forum`, `message_thread_id`) — no raw Update/Message dump, no extra
  field.
- **CASE D** (`test_case_d_exactly_one_outbound_call_and_it_is_send_message`): exactly one
  recorded outbound Telegram method call, and it is `SendMessage` — no other side effect.
- **CASE E**: two tests — the root router still includes every previously-registered router
  (`start`, `news`, `digest`, `status`, `settings`, `image_preview`, `meme_preview`) alongside the
  new `whereami` router; `bot.main.main()`'s own `include_router`/`start_polling` call shape is
  unchanged (AST-based, mirrors `tests/test_bot_router_registration.py`'s own established
  convention).

Result: `8 passed in 7.72s`. Ruff (`bot/handlers/whereami.py`, `bot/handlers/__init__.py`, `tests/
test_whereami_handler.py`): all checks passed. Mypy (`bot/handlers/whereami.py`, `bot/handlers/
__init__.py`): Success, no issues found.

Broader regression (`pytest tests/ -k "handler or bot_router or telegram_notifier or
docker_compose_telegram or telegram_editorial_routing"`): **72 passed, 1 failed** (deselected:
3011). The one failure (`test_news_handler.py::test_integrated_stack_empty_state`, a
`ForeignKeyViolationError` on `content_drafts`/`image_candidates` at teardown) was confirmed via a
temporary removal of this phase's own changes to reproduce byte-identically on unmodified code —
the same pre-existing local-Postgres test-pollution pattern already identified and disclosed in
the Phase 21 and Phase 22 reports (an accumulated real local database carrying leftover rows from
many manual/replay scripts run across this session), unrelated to this phase's changes.

## 6. Whether any real Telegram send happened

**No.** Every test in this phase uses a fake, in-memory `aiogram.client.session.base.BaseSession`
subclass (`FakeSession`, mirroring `tests/test_news_handler.py`'s own already-proven-feasible
technique) — zero real network access, zero contact with `api.telegram.org`. The one real action
taken against the live bot process was rebuilding and restarting the `telegram_bot` container
itself (§3) — a code deployment, not a message send. No `/whereami` invocation has happened yet
inside the real Telegram group; that is the next step, requiring the user's own manual action
(§7 below).

## 7. Exact instruction for the user

Open each of the following topics in the **Newsroom Ninja** forum group, one at a time, and send
`/whereami@nnj_newsroombot` (or just `/whereami` if Telegram doesn't require the `@botname`
suffix in that chat type) as a message inside that topic:

1. **news**
2. **meme**
3. **telegraph**
4. **instagram**
5. **reels**
6. **General** (optional sanity check)

The bot will reply in-topic with `chat_id` / `is_forum` / `message_thread_id` for that exact
topic. Please send all six (or five, if skipping General) before reporting back — once you
confirm you've invoked it everywhere, the observed values will be read back and assembled into
the `NEWSROOM_CHAT_ID` / `NEWS_TOPIC_ID` / `MEME_TOPIC_ID` / `TELEGRAPH_TOPIC_ID` /
`INSTAGRAM_TOPIC_ID` / `REELS_TOPIC_ID` mapping the phase brief's §5 requires, plus the three
required confirmations (all topic IDs distinct, all belong to the same `chat_id`, `chat.is_forum
== true`).

## 8. Current production/live worker state

| Container | State | Role |
|---|---|---|
| `ai_newsroom_telegram_bot` | **Up** (restarted this phase, §3) | inbound command handling only — now includes `/whereami` |
| `ai_newsroom_automation_worker` | Up 45 hours (unchanged, untouched this phase) | Collection + Triage only (`worker/cycle.py`) — creates `NEWS_ANALYSIS` tasks, never analyzes them, never sends Telegram |
| `ai_newsroom_content_worker` | **Exited (1)**, unchanged this phase | creates `CONTENT_GENERATION`, and is the **only** worker that constructs a real `Bot` and sends Telegram editorial drafts (`worker/content_cycle.py`) |
| `ai_newsroom_news_analysis_worker` | **Exited (1)**, unchanged this phase | runs `NEWS_ANALYSIS` (`worker/analysis_cycle.py`) |
| `postgres` / `redis` / `backend` | Up, unchanged | infrastructure |

**Critical safety finding (§8 of the phase brief, "we had a previous real backlog issue"),
confirmed directly against the real database, read-only queries only:**

- `editorial_tasks` currently holds **15,258** `NEWS_ANALYSIS` tasks in `CREATED` status (a
  backlog spanning **2026-07-19 through 2026-08-09** — three weeks) — `automation_worker` has kept
  creating these continuously while `news_analysis_worker` has been stopped.
- This backlog is **not** a live risk by itself: `news_analysis_worker`'s own eligibility query
  (`worker/analysis_cycle.py::_select_eligible_task_ids()`) filters by
  `news_analysis_freshness_cutoff_hours` (currently **2.0 hours**) — of the 15,258 `CREATED` tasks,
  only **27** currently fall inside that freshness window. If `news_analysis_worker` were started
  right now, it would process at most a small, recent slice — never the full historical backlog.
- Separately, **1,597** events are `NEWS_ANALYSIS(COMPLETED)`, of which **66** fall inside
  `content_generation_freshness_cutoff_hours` (currently **24.0 hours**) and would be scanned by
  `content_worker`'s own eligibility query if it were started (further filtered by
  `content_generation_min_score=65` and capped at `content_generation_batch_size=5` per cycle).
- **The actual live-risk finding**: `settings.content_generation_dry_run` is currently **`False`**
  in the real, running configuration — **not** the safe default (`core/config.py`'s own default is
  `True`). Combined with `content_worker` currently being stopped, this has had no effect so far —
  but it means that starting `content_worker` under the *current* settings, for any reason, would
  immediately attempt **real** Telegram sends (to `settings.editorial_chat_id = 5507703201` — a
  real, different, already-in-production chat, **not** the new Newsroom Ninja test group, since
  `newsroom_telegram_chat_id` is still unconfigured and nothing wires Phase 22's routing into this
  path yet) for any of those 66 eligible events. **`content_worker` was not started this phase**,
  and must not be started under the current `content_generation_dry_run=False` setting for any
  reason, canary included, without first being deliberately reviewed and set to the intended value
  for whatever step is about to run. Full detail in `docs/phase23_0_canary_configuration_plan.md`
  §3.
- Docker restart-policy check: every service in `docker-compose.yml` uses `restart: unless-stopped`.
  `content_worker`/`news_analysis_worker` are currently in `Exited` status (a stopped state) — per
  Docker's own `unless-stopped` semantics, a Docker Desktop/daemon restart will **not** resurrect a
  container that is currently stopped; it only restarts containers that were *running* at the time
  the daemon itself stopped. This was checked directly against the containers' current real state,
  not merely inferred from the compose file.

## 9. Confirmation that no canary has started yet

**Confirmed. No canary has started.** `content_worker` and `news_analysis_worker` remain stopped
and untouched. No settings were changed (`content_generation_dry_run`, `editorial_chat_id`,
`story_memory_mode`, `copywriting_prompt_version`, `fact_safety_mode` are all exactly as they were
at the start of this phase — verified by direct read, see §8's table and
`docs/phase23_0_canary_configuration_plan.md` §2). No real Telegram send happened (§6). The only
live action taken was rebuilding/restarting the already-running `telegram_bot` container to load
one new, safe, read-only diagnostic command.

---

**STOP condition met.** Waiting for the user to manually invoke `/whereami` in each of the six
topics (§7) and report back before any further action — including Phase 22 real-ID routing
validation (§6 of the phase brief) or any canary step — is taken.
