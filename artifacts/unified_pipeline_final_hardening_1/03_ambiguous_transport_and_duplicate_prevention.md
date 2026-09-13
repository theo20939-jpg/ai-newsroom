# Ambiguous Transport & Duplicate-Publication Prevention Evidence (§11-§15)

## The fix

`services/editorial_pipeline/recovery_service.py::RecoveryService.create_or_retry()` now forces
`effective_max_attempts = 1` whenever `reason_code` is in a new, explicit, narrow
`_ALWAYS_TERMINAL_ON_FIRST_FAILURE_REASON_CODES` set (`QUALITY_GATE_FAILED`,
`AMBIGUOUS_TRANSPORT_RESULT`) — regardless of what `max_attempts` value any caller (present or
future) supplies. This is a SERVICE-LEVEL invariant, not a per-caller convention: even a
hypothetical future caller that forgets to pass `max_attempts=1` gets the safe behavior anyway.

Effect for `AMBIGUOUS_TRANSPORT_RESULT` specifically: the very first occurrence for a draft goes
straight to `TERMINAL_HOLD` (`next_retry_at=None`, `resolved_at` set) — never `PENDING`/`RETRYING`.
Since `find_open_recovery()` and `due_for_retry()` (the two queries any retry-consumer, present or
future, would use) only ever return `PENDING`/`RETRYING` rows, a `TERMINAL_HOLD` row is
structurally invisible to them. No new migration, no new state, no second retry subsystem — this
phase does not build a retry-consumer (§15's own explicit instruction).

## Test evidence — `tests/test_unified_pipeline_ambiguous_transport_hardening.py`

| Scenario | Test | Result |
|---|---|---|
| A. Send succeeds | `test_a_send_succeeds_no_recovery_job_created` | `RoutingOutcome(sent=True, ambiguous=False)`, zero recovery rows created |
| B. Definite pre-acceptance failure | `test_b_definite_failure_is_bounded_retryable_not_forced_terminal` | `RoutingOutcome(sent=False, ambiguous=False)` → `MEDIA_SEND_FAILED` → `PENDING`, `max_attempts=3`, `next_retry_at` set (normal bounded-retry semantics, UNCHANGED) |
| C. Timeout / unknown acceptance | `test_c_ambiguous_timeout_is_persisted_terminal_never_bounded_retryable` | `RoutingOutcome(sent=False, ambiguous=True)` → `AMBIGUOUS_TRANSPORT_RESULT` → `TERMINAL_HOLD` on first occurrence, `max_attempts=1`, `next_retry_at=None`; durably persisted (readable via `RecoveryService.get()`) but absent from both `find_open_recovery()` and `due_for_retry()` |
| D. A future generic retry method invoked on an ambiguous job | `test_d_due_for_retry_never_returns_an_ambiguous_terminal_row` | `due_for_retry()` (the query any retry-consumer would use) never returns the row |
| E. Multiple processing passes over the same ambiguous job | `test_e_repeated_processing_of_the_same_ambiguous_job_never_reopens_it` | 5 simulated "processing passes", `fake_bot.send_photo` never called, row never drifts back to `PENDING`/`RETRYING` |

`AMBIGUOUS_AUTO_RESEND_COUNT = 0` (asserted explicitly in scenario E).
`AUTO_RESEND_AFTER_AMBIGUOUS_RESULT = false`.
`AMBIGUOUS_TRANSPORT_DUPLICATE_RISK` — **downgraded from the founder-bundle's MEDIUM finding**: the
finding was "no reconciliation safeguard exists for a FUTURE retry-consumer" — this hardening adds
that safeguard at the domain-rule level (§15's own framing: "we only need the RecoveryService/
domain rule to be safe before such a consumer could ever be added"). No retry-consumer exists
today (unchanged), and now, even if one is added later using the existing, real
`due_for_retry()`/`find_open_recovery()` queries, it cannot resend an ambiguous result without a
deliberate, separate code change to bypass this safeguard.

## Regression: the pre-existing cutover-1 replay test updated, not broken

`tests/test_unified_pipeline_cutover_authority.py::test_replay_h_ambiguous_transport_timeout_never_auto_resent`
previously asserted `state == PENDING` for an ambiguous result (the OLD, un-hardened behavior) —
updated to assert `state == TERMINAL_HOLD`, `next_retry_at is None`, `max_attempts == 1`, matching
the new, correct behavior. `tests/test_unified_pipeline_recovery_service.py::
test_persisted_state_survives_a_fresh_service_instance_after_a_simulated_restart` was using
`AMBIGUOUS_TRANSPORT_RESULT` merely as an arbitrary reason code for an unrelated concern
(fresh-instance persistence) — switched to `MEDIA_SEND_FAILED` so that test keeps testing exactly
what its own name says, undisturbed by this reason code's new, correct semantics.
