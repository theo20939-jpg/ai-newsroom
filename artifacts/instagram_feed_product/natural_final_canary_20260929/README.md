# KAGE Instagram — final natural end-to-end canary (2026-09-29, HEAD ec21f5d)

No fixture, no injected story, no manual edit. Read-only production pool pulled 2026-09-29 11:46 UTC.
Pool: 3,201 events in 48h -> 2,043 current (24h) -> 744 KAGE-relevant -> 590 distinct events -> 11 daily-eligible.

The worker's MEME_TREND slot shortlist (3) was tried in order, exactly as `worker/content_cycle.py` does
(`mark_tried` + `continue` on preflight != PASS, max 3 attempts per cycle). `natural_run_wrapper.py` = the unchanged
`scripts/_instagram_viral_nominated_canary.py` + the review-payload capture + that tried-skip.

| # | Story | Result |
|---|---|---|
| 1 | Honor Magic 9 Super (11,000 mAh gaming phone) | evidence preflight FAIL (quantity, chronology): the article holds both, but the 6-fact package kept a page-navigation line instead of the battery sentence. $0 |
| 2 | Anthropic Claude Sonnet 5.5 launch | preflight FAIL on both copies (action; chronology on copy 2): "upgrading / replacing / презентовала" not accepted for the hook verb "выпустила". $0 |
| 3 | OpenAI apologises for its agent's hack of Medicare / Australian government sites | PASS through Phase A, the Director, one correction, judge v5 CLEAN, 4 generated images, art PASS (1 warning), 4 slides rendered, ready_for_editor |

Review payload: `attempt_3/telegram_review_payload/` (NOT sent - no Instagram topic is configured in this environment).
Cost: LLM $0.116830 (6 calls), images $0.090365 (4), total $0.207195.
