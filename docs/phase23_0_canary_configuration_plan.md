# PHASE 23.0 — Canary Configuration Plan (NOT APPLIED)

**Nothing in this document has been applied.** Every value below is a target for a *future*,
separately-authorized canary start (Phase 23.1 or later, after real topic IDs are collected and
reviewed) — no `.env` change, no settings mutation, no worker start happened as part of producing
this plan.

## 1. Scope of the first canary

**ONLY** the NEWS topic. MEME, TELEGRAPH, INSTAGRAM, REELS receive nothing during the first
canary — `services/telegram_routing.py` (Phase 22) is not even wired into any live path yet, so
no code change is required to enforce this scope; it is enforced simply by not starting a canary
that uses those destinations.

## 2. Target settings (current real value -> target canary value)

| Setting | Current real value | Target for canary | Change type |
|---|---|---|---|
| `story_memory_mode` | `off` | `shadow` | flip to shadow (never `enforce`) |
| `story_memory_suppression_mode` (would-suppress is a replay-only pure function today, per Phase 20 — no production setting exists to enable it) | n/a | remains **off** — no such switch exists to turn on | unchanged |
| Story-update routing | not implemented in any live path | remains **off** | unchanged |
| `copywriting_prompt_version` | `"4"` | `"6"` | flip to V6 |
| `fact_safety_mode` | `shadow` | `shadow` (already correct, per Phase 21 approval) | unchanged |
| `content_generation_dry_run` | **`False`** (see §3 - a live finding, not a target) | `True` for the canary's own dry-run rehearsal stage; only flipped to `False` for the canary itself after an explicit, separate human go-ahead | **must change** - see §3 |
| `editorial_chat_id` | `5507703201` (an existing, different, already-in-production chat) | must point at the **new** NINJA NEWSROOM chat - not yet possible, since Phase 22's routing settings (`newsroom_telegram_chat_id`, `news_topic_id`, etc.) are a *separate* mechanism from `editorial_chat_id` (docs/phase22_telegram_editorial_routing_report.md §5) | requires a design decision (§5 below), not just a value flip |
| `content_generation_min_score` | `65` | unchanged | unchanged |
| `content_generation_batch_size` | `5` | unchanged or lower for the canary's first hours (operator judgment at canary-start time, not decided here) | unchanged/lower |
| Automatic publishing | dry-run only in practice today (see §3's own caveat) | **off** - canary output is an editorial draft/preview only, never auto-published without review | must be enforced explicitly, not assumed |

## 3. Critical live finding this plan is built around

`settings.content_generation_dry_run` is currently **`False`** in the real environment - **not**
the safe default (`core/config.py`'s own default is `True`; the real, running configuration has
been explicitly flipped to `False` at some point before this session). Combined with
`content_worker` currently being stopped, this has had no live effect so far - but it means
`content_worker` **must not be started under the current settings** for any reason, canary or
otherwise, until this is deliberately reviewed and set to the intended value for whatever step is
about to run (rehearsal: `True`; the live canary itself, once explicitly authorized: a deliberate,
reviewed `False`). See docs/phase23_0_telegram_diagnostics_report.md §8 for the full backlog/
safety finding this is based on.

## 4. Content volume bound for the canary itself

Not decided here (explicitly deferred to canary-start time, per the phase brief's own "bounded and
controllable" instruction, not a number to guess in a diagnostics-only phase) - candidates:
lowering `content_generation_batch_size` for the canary's first hours, or a dedicated one-shot/
manual invocation instead of the full `content_worker` loop, so the very first live sends can be
watched one at a time rather than trusting the batch loop unattended immediately.

## 5. Open design question this plan does not resolve

Phase 22's routing settings (`newsroom_telegram_chat_id`/`news_topic_id`) are a distinct mechanism
from the existing, already-wired `editorial_chat_id`/`send_editorial_card()` path that
`worker/content_cycle.py` actually calls today. Making the *automated* canary actually land in the
NINJA NEWSROOM NEWS topic requires **either**: (a) pointing `editorial_chat_id` itself at the new
chat and separately handling `message_thread_id` for the NEWS topic in `send_editorial_card()`
(a real code change to the existing production path, not yet made or requested), or (b) wiring
`worker/content_cycle.py` to call Phase 22's `send_to_editorial_destination()` instead, for the
NEWS destination only (also a real code change, not yet made or requested). **Neither has been
built or authorized** - this is flagged explicitly as the next real implementation decision after
diagnostics complete, not something this plan silently assumes away.

## 6. Explicit non-changes

This document changes nothing. `.env` is untouched. No settings were mutated in the running
application. No worker was started or stopped as part of producing this plan (§4 of docs/
phase23_0_telegram_diagnostics_report.md covers the one container action taken this phase -
rebuilding/restarting `telegram_bot` only, for the diagnostic command - entirely separate from
this configuration plan).
