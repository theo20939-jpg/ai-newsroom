# Telegram Transport Raw HTTP Capture Report

One-shot, controlled diagnostic. No production file was modified — the entire capture mechanism
lived in a standalone script outside the repository
(`.../scratchpad/telegram_transport_diag.py`, deleted after use). No bot token, credential, or
token-bearing URL was logged or printed at any point. Not committed or staged.

---

## 1. Executive Verdict

**T1 — Direct, official Telegram API confirmed by live capture; the raw HTTP response itself,
before any aiogram parsing, already lacks `message_thread_id`/`is_topic_message`.** There is no
divergence anywhere in this codebase's control: the destination host is genuinely
`api.telegram.org` (captured directly from the live outbound connection, not inferred from static
config), and aiogram's parsed `Message` object matches the raw JSON field-for-field, with zero loss
or transformation. The missing topic identity originates entirely upstream of this repository, in
whatever Telegram (or Telegram-adjacent) system generates this specific message's Bot API payload.

## 2. Diagnostic Method

A standalone script (not part of the repository, run directly with the ai-newsroom directory
inserted onto `sys.path`) that:
1. Temporarily wrapped `aiohttp.ClientSession.post` to capture the request's destination
   **hostname only** (via `urlparse(url).hostname`) before delegating to the real implementation.
2. Temporarily wrapped `aiogram.client.session.base.BaseSession.check_response` — the exact method
   that receives `content: str`, the literal HTTP response body text, **before** aiogram
   deserializes it into `Response`/`Update`/`Message` objects — to extract and log only the four
   target fields (plus `update_id`/`message_id`/`chat_id`/`chat_is_forum` for correlation) from
   whichever `getUpdates` result contained a message starting with `/news`, then delegated to the
   real implementation unchanged.
3. Registered one temporary `aiogram.BaseMiddleware` on `dp.message` (via `dp.message.middleware(...)`,
   an ordinary, supported aiogram API — not a modification to any router file) to capture the same
   four fields from the corresponding **parsed** `aiogram.types.Message` object, reading
   undeclared/extra fields via Pydantic's `model_extra` (populated because `Message.model_config`
   has `extra="allow"`, confirmed in the prior report).
4. Stopped automatically (`asyncio.Event`, one-shot) the instant one `/news` update was captured at
   both layers — no repeated or extended polling beyond that.

Before running, the pre-existing production bot process was stopped (`Stop-Process`) to avoid a
`getUpdates` conflict — confirmed only one poller was ever active at a time.

## 3. Safety / Secret Handling

No bot token, `Authorization` header, cookie, or `.env` content was read, logged, or printed at any
point. The only URL-derived value ever logged was the bare hostname string (`api.telegram.org`),
extracted via `urlparse(url).hostname` — the token-bearing path segment (`/bot<TOKEN>/<method>`)
was never captured, formatted, or written to any log line.

## 4. Actual Destination Hostname

```
DIAG hostname=api.telegram.org
```
Captured directly from the live `aiohttp.ClientSession.post()` call the running process actually
made — not inferred from static configuration (which the prior report already established points
here) — this is the literal destination of a real, in-flight HTTP request during this diagnostic.

## 5. Raw HTTP Evidence (Layer A — `content: str`, before any aiogram model construction)

```json
{
  "update_id": 837679393,
  "message_id": 0,
  "chat_id": -1004297182444,
  "chat_is_forum": true,
  "message_thread_id": "<ABSENT>",
  "is_topic_message": "<ABSENT>",
  "ephemeral_message_id": 261271085,
  "receiver_user": {"id": 7688429343, "is_bot": true, "first_name": "Ninja Newsroom", "username": "nnj_newsroombot"}
}
```
(`<ABSENT>` is this report's own sentinel for "key not present in the parsed JSON dict at all" —
distinct from a present key whose value is JSON `null`.)

## 6. Aiogram Parsed Evidence (Layer B — the `aiogram.types.Message` object aiogram constructed)

```json
{
  "update_id": 837679393,
  "message_id": 0,
  "chat_id": -1004297182444,
  "chat_is_forum": true,
  "message_thread_id": null,
  "is_topic_message": null,
  "ephemeral_message_id": 261271085,
  "receiver_user": {"id": 7688429343, "is_bot": true, "first_name": "Ninja Newsroom", "username": "nnj_newsroombot"}
}
```

## 7. Field-by-Field Comparison

| Field | Raw state | Parsed state | Divergence |
|---|---|---|---|
| `message_thread_id` | **ABSENT** (key not in JSON) | **PRESENT WITH NULL** (`None`) | **No** — this is the correct, expected Pydantic behavior for a declared `Optional[int] = None` field when the source key is missing; aiogram fills in its schema default, it does not "lose" a value that was never there. |
| `is_topic_message` | **ABSENT** | **PRESENT WITH NULL** | **No** — identical reasoning; expected default-filling, not data loss. |
| `ephemeral_message_id` | **PRESENT WITH VALUE** (`261271085`) | **PRESENT WITH VALUE** (`261271085`) | **No** — faithfully preserved via `extra="allow"`, unchanged end to end. |
| `receiver_user` | **PRESENT WITH VALUE** (full nested object) | **PRESENT WITH VALUE** (identical object) | **No** — faithfully preserved, unchanged end to end. |

**Zero divergence for every field.** Aiogram's parsing introduces no loss, no transformation, and
no unexpected default — it does exactly what a correct Pydantic deserialization should do given
this exact raw input.

## 8. First Proven Divergence Point

**There is no divergence point inside this codebase or inside aiogram.** The absence of
`message_thread_id`/`is_topic_message` is already present in the raw HTTP response body, captured
directly from a confirmed, live connection to `api.telegram.org`, before any Python object
construction occurs. The "divergence" — if the word applies at all — is between (a) what a
non-General forum topic message is normally expected to carry per Telegram's documented Bot API
behavior, and (b) what this specific live message actually arrived with. That gap exists entirely
on the Telegram/platform side of the network boundary, not anywhere this investigation, aiogram,
or this repository's code can observe or influence.

## 9. Classification

**T1** — direct, official Telegram API (hostname proven live, not just inferred), and the raw
payload itself already lacks the topic fields.

## 10. Implications for Phase 11

**No Phase 11 code defect exists, and none can be constructed to fix this from within the
repository's authorized files.** `bot/handlers/news.py` and `bot/formatting.py` already behave
correctly given their input (re-confirmed, unchanged since M3). The Contract's own binding
constraints (§10: no persisted destination configuration, no manual `message_thread_id` storage)
correctly anticipated that this phase must not invent a routing workaround — and this diagnostic
confirms there is no reliable data to route by, even if such a workaround were authorized. This is
now a fully closed application-code question. Whatever further action is warranted (e.g.,
investigating the bot's admin/permission level in this specific supergroup, since some Telegram
Bot API behaviors are permission-dependent, or accepting this as a known platform limitation for
this deployment) is an operational/Telegram-configuration matter, explicitly outside this
diagnostic's authorized scope and outside Phase 11's own code boundary.

## 11. Cleanup Verification

- Both temporary monkeypatches (`aiohttp.ClientSession.post`, `BaseSession.check_response`) were
  restored to their original bound methods in the script's own `finally` block, and the process
  that held them has fully exited (confirmed: `Polling stopped` logged, process exit code 0).
- The one-shot script itself was deleted after use
  (`.../scratchpad/telegram_transport_diag.py`) — it was never part of the git-tracked
  repository, so no diff was ever possible from it.
- No bot process is currently running (the pre-existing one was stopped before this diagnostic;
  the diagnostic's own process has since exited) — confirmed via `Get-CimInstance Win32_Process`,
  zero `python.exe` processes remain.
- No token, credential, or `.env` content appears in any log line produced by this diagnostic.

## 12. Git Scope

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
Identical to every prior accepted state — this diagnostic added zero lines to any tracked file.
Nothing staged, nothing committed.

## 13. Recommended Next Step

Since this is now proven T1 (a platform-level fact, not a code defect), no further code-level
diagnostic or fix belongs in this repository's scope. The only remaining productive avenues, both
explicitly operational rather than code-related, are: (a) verify the bot's actual role/permission
level in this specific supergroup (some Bot API behaviors are documented to depend on admin status),
and (b) treat the current behavior as a known, disclosed limitation of this deployment for now,
consistent with Contract §10's own honest disclosure discipline, rather than continuing to search
for a code-side cause that this diagnostic has now ruled out.

---

No fix was implemented. No Phase 11 file was touched. Awaiting human review.
