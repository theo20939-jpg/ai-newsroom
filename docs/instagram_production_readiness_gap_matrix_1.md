# Instagram Production Readiness — Gap Matrix 1

Source: `docs/instagram_production_rollout_1_report.md` (commit `b9c5c0e`), re-verified directly
against current code/production this phase (not assumed from memory).

| GAP | SEVERITY | CURRENT STATE | REQUIRED STATE | CODE CHANGE NEEDED | INFRA CHANGE NEEDED | FOUNDER MANUAL ACTION NEEDED | CAN CLAUDE COMPLETE NOW | EVIDENCE |
|---|---|---|---|---|---|---|---|---|
| 1. Credentials | BLOCKER | `INSTAGRAM_ACCESS_TOKEN`/`INSTAGRAM_BUSINESS_ACCOUNT_ID` absent from production `.env`/container env (verified this phase) | Long-lived token w/ `instagram_business_content_publish` scope + account id configured | No | No (config only) | **Yes** - Business Login for Instagram OAuth flow (operator-run) | No - cannot obtain/invent | `docs/instagram_meta_production_setup_1.md` |
| 2. Media hosting | BLOCKER | No public HTTPS media endpoint anywhere; real publish path used a literal placeholder (`pending-media-ref:...`); `backend` reachable only on plain HTTP `0.0.0.0:8000`, no reverse proxy/TLS/domain/object-storage exists | A real, bounded, safe HTTPS endpoint serving exactly the selected publication asset | **Yes - built this phase** (`services/instagram_media_hosting.py` + `app/routes/instagram_media.py`) | **Yes - TLS/domain/reverse-proxy provisioning, a genuine ops decision, not attempted this phase** | Yes - choose+provision HTTPS ingress (domain+cert, or managed storage with public HTTPS) | Partial - code done, infra deploy decision is Founder's | §D below |
| 3. Unified safety gate wiring | BLOCKER (safety) | `instagram_editorial_gate.py` never checked `subject_match`/rights; `source_image_ref` only ever set by a manual canary script | Real `MediaResearchService`-verified `SelectedMediaAsset` feeds the package; gate hard-BLOCKs MISMATCH/NOT_USABLE, HOLDs EDITORIAL_REVIEW_REQUIRED | **Yes - built this phase** | No | No | **Yes - done this phase** | §E below |
| 4. Publication state persistence | HIGH | `PublicationResult` in-memory only; `package_id` a random `uuid4()` | Durable lifecycle table + deterministic idempotency key | **Yes - built this phase** (additive migration) | No | No | **Yes - done this phase** | §F/§G below |
| 5. Caption validation | MEDIUM | No caption-length check anywhere in the Instagram service layer | Bounded validation before any network write, mirroring the Telegram pattern | **Yes - built this phase** | No | No | **Yes - done this phase** | §D of the main report |
| 6. Ambiguous-write reconciliation | HIGH | Adapter retried transient/rate-limit errors but had no readback-before-retry step for a genuinely ambiguous (unknown) outcome | Readback via official API status before any retry decision; unresolvable -> AMBIGUOUS/HOLD, never blind resend | **Yes - built this phase** | No | No | **Yes - done this phase** | §H below |
| 7. Dry-run runtime evidence | HIGH | `DRY_RUN_CANDIDATES=0` - only unit tests existed, no live-recent-candidate runtime path | >=5 real recent candidates run through the full flow, zero network writes, classified READY/HOLD/BLOCK | **Yes - built this phase** | No | No | **Yes - done this phase** | §I/§J below |

**Incidental, out-of-scope observation** (not a gap this phase addresses, disclosed for Founder
awareness only): production Postgres (`5432`) is also bound to `0.0.0.0`, publicly reachable at the
network level (auth-protected by password, but not firewalled to localhost/VPN). Pre-existing,
unrelated to Instagram, not touched by this phase - flagged, not fixed, per this phase's own narrow
scope.
