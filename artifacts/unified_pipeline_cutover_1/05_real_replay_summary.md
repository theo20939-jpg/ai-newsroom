# Real replay summary (unified flag ON, safe local mode — no real Telegram send, no production DB touched)

All replays run through the actual, unmodified `worker.content_cycle.run_content_cycle()` entry
point (never a hand-rolled shortcut), against the real, isolated pytest database
(`ai_newsroom_test`), with `fake_bot = AsyncMock()` standing in for a real `aiogram.Bot` (no network
call reaches Telegram). Source: `tests/test_unified_pipeline_cutover_authority.py`.

| Case | Scenario | Result | Evidence |
|---|---|---|---|
| A | No visual resolves for a NEWS post (the Amodei/LA-Times-class "no visual" shape) | `NO_SUITABLE_MEDIA`, real durable `PENDING` row, `next_retry_at` set, **zero** calls to the old `_hold_for_visual_recovery()` | `test_replay_a_no_visual_holds_via_real_durable_no_suitable_media_recovery` |
| D | The real Maxus DATA fixture (`290 тыс. юаней` → the exact defect class that used to leave a mangled `"начинается с юаней"` label) | The real, worker-driven sent caption carries the correct fixed label; the OLD `decide_presentation().data_candidate` is still computed internally (format-selection reuse) but its value never reaches the send | `test_replay_d_maxus_data_label_fix_reaches_the_real_sent_caption` |
| F | A caption far exceeding Telegram's photo-caption budget, with a real photo resolved | `CAPTION_BUDGET_FAILED`, real durable row — **never** a silent text-only completion with the image dropped (`send_photo`/`send_message` both asserted never called) | `test_replay_f_caption_too_long_never_completes_text_only` |
| G | A real `TelegramAPIError("Bad Request: chat not found")` on `send_photo` | `MEDIA_SEND_FAILED`, real durable `PENDING` row — exactly one send attempt, never retried inline | `test_replay_g_media_send_failure_becomes_a_durable_recovery` |
| H (**new**, not in phase 1) | A real `TelegramAPIError("Request timeout error")` — the exact production shape from the prior TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 phase's own evidence | `AMBIGUOUS_TRANSPORT_RESULT` (via the new `RoutingOutcome.ambiguous` classification), real durable `PENDING` row — exactly one send attempt, **never** a blind duplicate resend | `test_replay_h_ambiguous_transport_timeout_never_auto_resent` |

## Authority (the orchestrator owns the decision, exactly once)

`test_authority_legacy_functions_never_invoked_for_a_unified_data_send` — a real DATA-format send
with the flag ON, spying on `worker.content_cycle._hold_for_visual_recovery`,
`render_editorial_card`, `build_rich_media_plan`, `resolve_photo_input`,
`send_media_group_to_editorial_destination`, `send_video_to_editorial_destination`: **all six
assert never called**. The unified path still produces a real, complete outcome
(`result.notified == 1` or `result.visual_required_held == 1`, `result.notification_failed == 0`).

## Persistence across a simulated restart

`test_recovery_row_created_by_a_real_cycle_is_visible_to_a_fresh_service_instance` — a row created
by one real `run_content_cycle()` call is read back correctly by a brand-new `RecoveryService()`
instance (simulating a worker process restart), via both `.get()` and `.find_open_recovery()`.

## Disclosed, not silently skipped: cases B/C/E from the phase brief's own list

Cases **B** (deepfake/police-crime media truthfulness) and **E** (foldable-iPhone carousel media
truthfulness) are NOT independently re-verified with a new vision-based classifier in this cutover
phase. `MediaResearchService.research()` — the real S10-S16 code from
UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 — IS genuinely invoked from a live call site for the first
time in this phase, but this phase supplies zero `subject_match_classifier` (no new vision-LLM
wiring was added here), so every candidate scores via the existing, already-tested, conservative
"unclassified" default (`services/media_candidate_scoring.py`) rather than a real EXACT_SUBJECT/
MISMATCH judgment. This is the same, already-disclosed limitation UNIFIED-EDITORIAL-PRODUCTION-
PIPELINE-1's own report named — this phase does not newly introduce it, and does not claim to have
closed it. Case C (Amodei/CBS) is the same underlying scenario shape as A and D and is covered by
the same real mechanism.
