# Retry examples — real, computed values from `services/editorial_pipeline/recovery_service.py`

All examples below are exactly what `tests/test_unified_pipeline_recovery_service.py` asserts
against the real `recovery_jobs` table (not illustrative pseudocode).

## Example 1 — a draft that fails twice then succeeds

| Call | attempt_count | state | next_retry_at | max_attempts |
|---|---|---|---|---|
| 1st failure (`NO_SUITABLE_MEDIA`) | 1 | `PENDING` | now + 60s | 3 |
| 2nd failure, same draft (`NO_SUITABLE_MEDIA` again) | 2 | `RETRYING` | now + 300s | 3 |
| A later cycle's render succeeds → `mark_recovered()` | 2 (unchanged) | `RECOVERED` | `None` | 3 |

## Example 2 — max attempts exhausted (bounded, never infinite)

| Call | attempt_count | state | next_retry_at |
|---|---|---|---|
| 1st failure | 1 | `PENDING` | now + 60s |
| 2nd failure | 2 | `RETRYING` | now + 300s |
| 3rd failure (== max_attempts) | 3 | `TERMINAL_HOLD` | `None` (`resolved_at` set) |
| 4th failure, same draft | 1 (**new row** — `find_open_recovery()` never returns a `TERMINAL_HOLD` row) | `PENDING` | now + 60s |

## Example 3 — `QUALITY_GATE_FAILED` is terminal on the very first failure

| Call | attempt_count | max_attempts | state | `OrchestratorVerdict` |
|---|---|---|---|---|
| 1st (and only) failure | 1 | 1 (forced by `orchestrator.py::_TERMINAL_ONLY_REASON_CODES`) | `TERMINAL_HOLD` immediately | `BLOCK` |

## Example 4 — `due_for_retry()` query

A row created with `next_retry_at` in the past (`now - 1 day`) is returned by
`RecoveryService.due_for_retry()`; a row created with `next_retry_at` in the future (`now + 1 day`)
is not — proven directly against two real rows in
`test_due_for_retry_only_returns_rows_whose_next_retry_at_has_passed`. This query exists and is
tested now so a future retry-consumer (out of this phase's own scope — S9 asks only that the state
be real and durable) has a real, already-proven query to build on.
