# KAGE Instagram - final current-state natural acceptance (2026-10-01, HEAD 161e728)

Result: **STOPPED at the evidence preflight on all three of the worker's attempts. $0 spent. No Phase A, Director, image, render or Telegram send.**

Pool (read-only SELECT over SSH, 2026-10-01 10:14 UTC): 3,530 events in 48h -> 1,716 in the last 24h -> 664 KAGE-relevant -> 536 distinct events -> 7 daily-eligible.
Ranked shortlist (`selection/snapshot.json`): 1 Gemini 4 Argon (iXBT, 7 copies, ai_launch) · 2 the same launch as a Telegram-channel post (Бэкдор, 3 copies) ·
3 HN "Errol" kids' math robot (device_novelty) · 4 Samsung Galaxy SmartTag3 · 5/6 AI agents vs a Canadian government site · 7 Android e-reader case.
The worker tries at most 3 per cycle (mark_tried + continue on preflight != PASS); `_instagram_final_acceptance_run.py` = the unchanged canary + that tried-skip + a real topic-40 delivery that only fires for a READY package.

| attempt | story | copies tried | result |
|---|---|---|---|
| 1 | Google Gemini 4 Argon (iXBT) | 7 | preflight FAIL / PENDING: iXBT FAIL (action, quantity, chronology); 9to5Google, Android Authority, TechCrunch FAIL (action); Engadget + 2 Google-News redirects PENDING (no article) |
| 2 | Gemini 4 Argon (Telegram post) | 3 | PENDING (Telegram post has no article) / Habr FAIL (action) / Google News RU PENDING |
| 3 | HN "Errol" robot | 1 | PENDING: article fetch failed |

First divergence: EXPECTED a major, fully reported AI launch whose fetched articles (3-16k characters FULL_TEXT) carry its evidence to pass the launch preflight.
ACTUAL: four copies fetched full text, but the stored evidence package kept ~830-950 characters of each and the body check found no sentence establishing that the
launch HAPPENED ("action" UNSUPPORTED; the headlines say it, and headlines never count as evidence). Same family as 29 Sep's Honor/Sonnet preflight stops. Not retuned in this run.

Harness note (disclosed): the first launch attempt failed in 0 s, before any spend, because the canary's observation hook `record_package` did not accept the `launch=` keyword
added to `_feed_evidence_package` in a4e9dd4; it now forwards `**kw` (observation only, no product code). Log: `attempt_0_harness_error.log`.
Environment: the local scratch DB `kage_e2e_20260925` was renamed to `kage_e2e_20260925_pre_final_acc` and recreated schema-only (reversible); only the shortlist copies + their sources were copied from production.
Telegram: getMe OK (nnj_newsroombot, administrator in the authorised chat via the local HTTPS proxy); nothing was sent.
