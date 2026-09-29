# KAGE Instagram — launch story evidence contract (2026-09-29)

Offline only: 0 provider calls, 0 image calls, no database, no network, no natural canary.

The final natural canary (`36b25f9`) selected a gadget launch (#1) and an AI model launch (#2) correctly, and both stopped at the
viral evidence preflight although their fetched articles supported them. This fix is at that boundary only. Selection, Director,
correction, judge, visuals and renderer are untouched.

## Files

- `saved_sources.jsonl` — the canary's saved inputs: each attempted copy's stored body and persisted acquisition (`raw_extracted_text`).
  Also included: the attempt-3 incident story, as a regression anchor.
- `replay_before.json` / `replay_after.json` — `scripts/_instagram_launch_evidence_replay.py`. It rebuilds each package from the saved
  source with the worker's own inputs and runs `viral_evidence_preflight` with the canary's own nominated event, at the canary clock.
- `preflight_regression.json` — `scripts/_instagram_launch_evidence_regression.py`. OLD (`36b25f9`) vs NEW preflight with identical
  inputs, on every evidence attempt saved by the paid viral canaries.

## Result

| Attempt | Before | After |
|---|---|---|
| Honor Magic 9 Super (3DNews) | FAIL: quantity, chronology | **PASS** |
| Claude Sonnet 5.5 (9to5Mac, copy 1) | FAIL: action | **PASS** (the worker stops here) |
| Claude Sonnet 5.5 (hightech.fm, copy 2) | FAIL: action, chronology | FAIL: chronology only (the text states no date) |
| OpenAI Medicare-hack apology (Guardian) | PASS | PASS |

Preflight regression over 38 saved attempts: 1 status change and 2 check changes, all of them the two Sonnet copies' `action`.
Every viral / incident attempt is identical in every check. In 7 of 38 attempts OLD does not reproduce the recorded status, because
the headline set is approximated by the attempt's own titles; OLD and NEW get the same inputs, so the differential still holds.
