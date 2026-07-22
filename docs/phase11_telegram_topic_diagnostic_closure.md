# Phase 11 — Telegram Topic Diagnostic Closure

Documentation/verification-state closure only. No production code, test, Contract, or
Implementation Plan was modified to produce this document.

---

## 1. Executive Verdict

The forum-topic investigation is closed with a proven, upstream root cause: for the specifically
reproduced controlled incoming Update, the raw HTTP response received directly from
`api.telegram.org` did not contain `message_thread_id` or `is_topic_message`. No defect was found
in `bot/handlers/news.py`, `bot/formatting.py`, aiogram's parsing, or this repository's transport
configuration. No Phase 11 workaround is authorized. The core `/news` read-only editorial inbox
feature — DB query, eligibility, ordering, escaping, UTF-16 safety, rendering, multi-card delivery —
is unaffected and has been independently, repeatedly proven correct, including live. Phase 11's
substantive M5 requirements are satisfied; forum-topic context preservation is reclassified as a
disclosed, external/upstream limitation for this deployment, not a blocking gate. **Recommendation:
Phase 11 is ready for closure.**

---

## 2. Investigation Chronology

1. **Original M5 live attempt** (`docs/phase11_m5_failure_investigation_report.md`) surfaced three
   observations: (a) forum-topic responses appearing in General, (b) apparent "duplicate" news
   delivery, (c) English output where Russian was expected.
2. **Language** was root-caused (`docs/content_generation_language_remediation_investigation.md`,
   `..._final_implementation_plan.md`), implemented (`..._remediation_implementation_report.md`,
   786/786 tests passing), and **live-validated as PASS**
   (`docs/content_generation_language_live_acceptance_report.md`): a fresh `NewsEvent` produced a
   genuinely Russian `ContentDraft` through the real, unmodified pipeline, and `/news` displayed it
   live without any translation performed by Phase 11.
3. **"Duplicates"** were investigated in the same failure report and assessed as very likely a
   misreading of multiple manual `/news` invocations against a database that, at the time,
   contained only one eligible draft — not a query or rendering defect (only one `ContentDraft` row
   existed; a single `SELECT` cannot return one row twice). This was explicitly confirmed,
   not merely inferred, by the subsequent live acceptance test: with **two** real, distinct
   eligible drafts now in the database, a single `/news` invocation returned exactly those two
   distinct `draft_id`s, in the correct newest-first order, with no repeated card. The original
   "duplicate" observation is resolved as a non-issue.
4. **Forum-topic routing** was investigated across three escalating, evidence-based diagnostic
   passes: (a) a handler-level diagnostic capturing incoming/outgoing fields
   (`docs/telegram_topic_routing_fresh_sample_diagnostic_report.md`) found the incoming message
   already lacked topic identity (Case C) and surfaced two unexplained raw fields; (b) a static
   transport/endpoint audit (`docs/telegram_transport_endpoint_diagnostic_report.md`) proved no
   custom session/proxy/local server/DNS override exists anywhere in this repository or
   environment, corrected an earlier misreading of several legitimate aiogram fields, and
   classified the remaining question as T4 (methodology insufficient to prove the raw HTTP
   boundary); (c) a one-shot raw-HTTP-versus-parsed-model capture
   (`docs/telegram_transport_raw_http_capture_report.md`) proved, directly and live, that the actual
   outbound connection reaches `api.telegram.org`, and that the raw response body itself — captured
   before any aiogram parsing — already lacks `message_thread_id`/`is_topic_message`, with zero
   divergence introduced by aiogram's own deserialization. **T1.**

---

## 3. Final Transport Evidence

Re-stated from `docs/telegram_transport_raw_http_capture_report.md` §4: `DIAG hostname=
api.telegram.org`, captured directly from the live outbound `aiohttp.ClientSession.post()` call
during the one-shot diagnostic — not inferred from static configuration alone (which had already,
separately, shown no code-level override exists).

## 4. Raw vs Parsed Evidence

| Field | Raw HTTP JSON (Layer A) | Parsed aiogram `Message` (Layer B) | Divergence |
|---|---|---|---|
| `message_thread_id` | ABSENT | `null` | No — expected default-filling for a missing key |
| `is_topic_message` | ABSENT | `null` | No — same |
| `ephemeral_message_id` | PRESENT WITH VALUE | PRESENT WITH VALUE (identical) | No |
| `receiver_user` | PRESENT WITH VALUE | PRESENT WITH VALUE (identical) | No |

Zero divergence for every field, for the one controlled, freshly-reproduced Update.

## 5. Root-Cause Boundary

Precisely, without overclaiming: **for the specifically reproduced controlled incoming Update, the
raw response received directly from `api.telegram.org` did not contain `message_thread_id` or
`is_topic_message`. Therefore, for that Update, this application had no topic identity available to
propagate automatically.** The first proven point at which the required topic information is absent
is the upstream Telegram HTTP response itself — before this repository's code, and before aiogram's
own parsing, ever see the data. This is **not** a claim that "Telegram topics do not work" or that
"Telegram can never provide `message_thread_id`" — only that, for this reproduced case, it did not.

## 6. Application-Code Exoneration

No proven data-loss defect exists in: `bot/handlers/news.py` (unchanged since M3, re-confirmed
byte-identical after every diagnostic's temporary instrumentation was reverted); `bot/formatting.py`
(untouched throughout this entire investigation); aiogram's parsing (proven faithful, field-for-
field, in §4 above); this repository's transport configuration (proven to use aiogram's own
unmodified default `AiohttpSession`/`PRODUCTION` API server, confirmed live). `message.answer()`'s
own logic (`message_thread_id = message.message_thread_id if message.is_topic_message else None`)
was independently verified correct multiple times across this project's history (Contract F-3,
Plan Audit, M3 implementation tests, and this diagnostic) and is not implicated.

## 7. Upstream Limitation Classification

**EXTERNAL / UPSTREAM LIMITATION**, for the reproduced Update. Confirmed to have **no** effect on:

| Concern | Affected? |
|---|---|
| Core read-only inbox correctness | **No** |
| DB query correctness (eligibility/ordering/limit) | **No** |
| Formatting correctness (escaping, template) | **No** |
| UTF-16 length safety | **No** |
| HTML escaping | **No** |
| Workflow/task state | **No** |
| Data integrity (historical or new records) | **No** |

## 8. Why No Phase 11 Workaround Is Authorized

Explicitly frozen, per this task's own instruction and consistent with Contract §10's own binding
constraint (no persisted destination configuration, no manual `message_thread_id` storage): no
hardcoded thread/topic ID, persisted topic-routing table, chat→topic mapping, fallback-to-known-
topic logic, middleware workaround, aiogram patch, custom API endpoint, or retry logic aimed at
recovering missing topic identity will be added. Each would constitute a new, un-authorized
architecture/product decision outside Phase 11's frozen scope — and, per §5–6 above, there is no
reliable data available to route by even if such a mechanism were authorized.

## 9. Phase 11 Functional Impact

**A. Core Phase 11 feature** (`/news` → DB-backed editorial inbox → Telegram cards): **fully
functional, independently proven multiple times**, including live: correct eligibility filtering,
correct newest-first ordering, correct limit enforcement (proven at the automated/integration level
with 6+ real DB rows; live-exercised with the 2 real rows currently eligible), correct escaping
(including a real Cyrillic body and a real `news_url` live), correct UTF-16 safety, zero DB
mutation, and — critically — genuinely Russian AI-generated content displayed by Phase 11 without
any transformation.

**B. Forum-topic context preservation**: does not function for the reproduced Update, for reasons
proven to originate entirely outside this repository's code (§5). Classified as a disclosed,
non-blocking, external limitation — not a defect in the shipped feature.

## 10. Current M0–M5 Verification State

Reviewed directly from existing reports and git evidence, not inferred:

- **M0–M4**: complete and passed
  (`docs/phase11_m0_repository_preparation_report.md` through
  `docs/phase11_m4_integrated_verification_report.md`) — 774/774 tests at M4 close, later 786/786
  after the language remediation (`docs/content_generation_language_remediation_implementation_
  report.md`), ruff/mypy/architecture-validator all clean throughout.
- **No separate "Final Implementation Verification" document was ever required by Phase 11's own
  Implementation Plan** (§17's verification gates are embedded per-milestone and at the M4 final
  gate — unlike Phase 10, Phase 11's Plan never named a distinct, separate document for this) — the
  M4 report plus the subsequent live acceptance report together constitute this record.
- **M5 live Telegram validation**: performed multiple times, not merely partially — the original
  attempt (3 findings), the Russian-output live acceptance (PASS, full flow including `/news`), and
  the topic diagnostics (evidence-gathering, not a repeat of the base `/news` proof) all exercised
  the real bot against real Telegram.
- **`/news` itself has been proven live**: yes, repeatedly — correct card count, correct content,
  correct ordering, clean rendering, user-confirmed visually, zero DB mutation confirmed by direct
  before/after query.
- **Only forum-topic preservation remained genuinely unresolved** at the time this diagnostic
  began — now closed per §5–9 above.

## 11. Remaining Closure Gates

**None outstanding.** Cross-checking against the original M5 task's own required checks:
command handled without exception (yes, repeatedly); cards correspond to real eligible DB records
(yes); ordering matches the query contract (yes, both automated and live); expected max-card count
respected (yes, automated with 6+ rows and live with the currently-eligible 2); no duplicate cards
(yes, confirmed — resolved per §2.3); visual rendering — title/body formatting, a real populated
`news_url`, line breaks, HTML rendering, genuine Cyrillic, the static emoji, no broken entities (yes,
user-confirmed live); multi-card delivery, correct order, no card lost or duplicated (yes). The one
item not satisfied — forum-topic preservation — is reclassified per §7–9 as an external limitation,
not a functional gate this phase's own scope can or must close.

## 12. Recommended Next Action

Recommend **Phase 11 closure** (Outcome A). No further M5 re-testing is warranted — repeating
already-proven checks would not produce new information. If forum-topic support is later desired as
a product requirement, it should be scoped as its own, separately-governed future investigation/
decision (e.g., verifying the bot's permission level in specific forum supergroups, or a possible
future Telegram-side account/API change) — not a blocker for closing the phase as currently scoped.

## 13. Git / Scope Verification

```
 M bot/handlers/news.py
 M capabilities/copywriting_capability.py
 M capabilities/executor.py
 M capabilities/intelligence_capability.py
 M capabilities/quality_capability.py
 M capabilities/research_capability.py
 M capabilities/scoring_capability.py
 M core/config.py
 M schemas/capability.py
 M tests/test_capability_executor.py
 M tests/test_copywriting_capability.py
 M tests/test_settings_phase7.py
?? bot/formatting.py
?? prompts/copywriting/v3.yaml
?? schemas/editorial_inbox.py
?? services/editorial_inbox_service.py
?? tests/test_editorial_card_formatting.py
?? tests/test_editorial_inbox_service.py
?? tests/test_news_handler.py
```
Identical to every prior accepted state — this closure document is the only new file added this
session. Nothing staged, nothing committed.
