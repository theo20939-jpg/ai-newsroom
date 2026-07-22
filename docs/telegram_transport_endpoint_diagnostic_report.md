# Telegram Transport / API Endpoint Diagnostic Report

Investigation only, entirely via static code inspection and safe, read-only runtime/environment
checks (no live message was sent or captured this pass, no secret was printed). No production
file, test, or configuration was modified. Not committed or staged.

---

## 1. Runtime Bot construction path

```
bot/main.py::main()
    -> bot/loader.py::create_bot()
        -> Bot(token=settings.telegram_bot_token.get_secret_value(),
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))
```
**No `session=` argument is passed.** Re-confirmed by direct re-read of `bot/loader.py` this
session — unchanged from every prior audit.

## 2. Session class used

Since `session` is omitted, `aiogram.Bot.__init__` (re-read directly from the installed package
this session) executes `if session is None: session = AiohttpSession()`. **`AiohttpSession`, the
aiogram-bundled, real HTTP client session — no custom or test session class is constructed
anywhere in production code.**

## 3. Actual API base host (token redacted — no token was printed or logged at any point)

`AiohttpSession`'s parent, `BaseSession.__init__`, defaults `api: TelegramAPIServer = PRODUCTION`.
Directly inspected the installed `aiogram.client.telegram.PRODUCTION` constant:
```
PRODUCTION.base = "https://api.telegram.org/bot{token}/{method}"
PRODUCTION.is_local = False
```
**No code anywhere in this repository overrides this** — confirmed via
`grep -rn "TelegramAPIServer|AiohttpSession|api_url|is_local|proxy" bot/ core/ scripts/`,
which returned zero matches outside the library itself.

## 4. Polling vs. webhook

**Long-polling**, confirmed again: `bot/main.py::main()` calls `await dp.start_polling(bot)` — no
webhook route, no `set_webhook`/`delete_webhook` call, no ASGI/WSGI receiver anywhere in this
codebase.

## 5. Proxy / local / custom backend status

- **HTTP proxy**: `AiohttpSession.__init__(proxy: _ProxyType | None = None, ...)` — defaults to
  `None`; never passed a value anywhere in this codebase. Checked the shell environment and `.env`
  for `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`-style variables: **none set**.
- **Local Telegram Bot API server**: `PRODUCTION.is_local = False`; no code constructs a
  `TelegramAPIServer.from_base(...)` anywhere (that is aiogram's own documented mechanism for
  pointing at a self-hosted local Bot API server — a `grep` for it found zero uses in this repo).
- **DNS-level override**: checked the Windows hosts file
  (`%WINDIR%\System32\drivers\etc\hosts`) for any `telegram` entry — **none found.**
- **Accidental test/fake session in production**: structurally impossible by construction — the
  `FakeSession` class used in `tests/test_news_handler.py` lives only in that test file, is never
  imported by any production module (already mechanically proven by that same test file's own
  AST-based import-boundary check, and by `create_bot()` never accepting an injected session at
  all — there is no call-site seam through which a test double could reach the real bot).

**Every one of these code-level, environment-level, and OS-level checks points to the same
conclusion: nothing in this repository's own configuration redirects Telegram traffic away from
the real `https://api.telegram.org`.**

## 6. Origin analysis of the previously-observed "nonstandard" fields

Re-examined this claim rigorously rather than repeating it uncritically. Checked whether each
field is actually declared on aiogram 3.29.1's own `Message`/`User` Pydantic models:

| Field | Declared on aiogram's own model? |
|---|---|
| `guest_query_id` | **Yes** |
| `guest_bot_caller_user` | **Yes** |
| `guest_bot_caller_chat` | **Yes** |
| `supports_guest_queries` (on `User`) | **Yes** |
| `can_manage_bots` (on `User`) | **Yes** |
| `ephemeral_message_id` | **No** |
| `receiver_user` | **No** |

**Correction to the prior report**: five of the seven fields I previously flagged as "non-standard"
are, in fact, legitimate, currently-declared fields in the installed `aiogram==3.29.1` package
(reflecting real, if less commonly known, Telegram Bot API surface — my earlier unfamiliarity with
them was not evidence of anything unusual). I was wrong to include them in that list, and I am
correcting it now rather than letting it stand.

**Two fields remain genuinely unexplained**: `ephemeral_message_id` and `receiver_user` are **not**
part of aiogram's declared `Message` schema. `Message.model_config` has `extra: "allow"` (confirmed
by direct inspection), meaning Pydantic preserves any field present in the source data even if
aiogram's own schema doesn't declare it — so these two fields, with their real, non-null,
structured values (`ephemeral_message_id=210321632`; `receiver_user` a full nested object matching
this bot's own identity), were genuinely present in whatever data was used to construct the
`Message` object. This does **not**, by itself, prove they came from a non-standard *network*
backend — only that they existed somewhere in the pipeline before or at the point aiogram validated
the `Message`.

## 7. Was the previous "raw JSON" proven to be the true HTTP payload?

**No — and this is the honest, load-bearing correction this diagnostic pass exists to make.** The
prior capture was `message.model_dump_json()` called on the **already-constructed aiogram `Message`
Pydantic object** — i.e., the representation *after* aiogram's own JSON deserialization and model
validation, not a byte-for-byte capture of the HTTP response body as it arrived over the socket,
before aiogram touched it. `extra="allow"` means this representation is very likely faithful to
whatever JSON aiogram's `Bot.get_updates()` call received — but "very likely faithful" is not the
same as "proven to be the literal wire payload," and this distinction matters precisely because
of the two still-unexplained fields in item 6.

## 8. Classification

**T4** — the previous "raw payload" capture was not proven to be the true, pre-aiogram HTTP
response boundary; a deeper capture (at the `aiohttp` transport layer, before Pydantic validation)
is required to fully settle T1 vs. T2 vs. T3.

This is not a hedge to avoid a conclusion — it reflects a genuine, resolved tension in the
evidence: **every static, code-level, environment-level, and OS-level check in this report (§1–5)
points strongly toward T1** (direct, unmodified connection to the real `api.telegram.org`, no
custom backend configured anywhere this codebase controls) — **while two specific, non-aiogram-
schema fields with real, structured values (§6) remain unexplained by that conclusion alone**, and
the capture method that surfaced them was never proven to reflect the literal HTTP boundary (§7).
Declaring T1 outright would mean asserting those two fields don't matter without being able to
explain them; declaring T2 would mean asserting a custom backend exists despite finding zero
supporting configuration anywhere. T4 is the classification that accurately reflects "the
methodology has a real limitation that must be closed before either T1 or T2 can be asserted with
confidence."

## 9. Root cause

**Not yet proven.** What is proven: no application-code or environment-level configuration in this
repository redirects Telegram traffic away from `https://api.telegram.org`, and `message.answer()`'s
own logic remains correct given whatever input it receives (re-confirmed, unrelated to this specific
question). What is not yet proven: whether the two unexplained fields (and the still-unexplained
`message_id: 0` observed in the same capture) originate from the real Telegram HTTP response itself
(which would make T1 correct and mean these are simply obscure, real Bot API fields I don't
recognize) or from some layer between the socket and aiogram's model construction that this
investigation's tools cannot yet see.

## 10. Smallest proposed remediation (T4's own required next step — not implemented)

Add one temporary, narrowly-scoped `aiohttp.TraceConfig` (or an equivalent `ClientSession`
request/response trace hook) to the bot's `AiohttpSession` for exactly one capture, logging only:
the request URL's **hostname** (never the full URL, which embeds the token in its path — redact to
host-only), and the **raw response body bytes** for exactly one `getUpdates` call, before any
aiogram parsing occurs. This would definitively show whether `ephemeral_message_id`/`receiver_user`/
`message_id: 0` are present in the literal bytes Telegram (or whatever server answers) sends, fully
resolving T1 vs. T2 vs. T3. Per the "no secrets" constraint, the hook must redact the token
segment of the URL path before logging anything, and must be removed immediately after one capture,
exactly as the previous diagnostic's instrumentation was.

## 11. Files/config likely involved (for the next diagnostic, if authorized — not yet touched)

`bot/loader.py` (temporary trace-hook injection into `create_bot()`'s session construction) —
the only file that would need a temporary, fully-reverted edit for the next capture. No other file.

## 12. Is any code change actually necessary?

**Not yet determined, and not for this diagnostic to decide.** No code defect has been found in
`bot/handlers/news.py`, `bot/formatting.py`, or `aiogram` itself — every prior finding on that front
stands unchanged. Whether *any* fix is possible or appropriate depends entirely on what the next,
deeper capture (§10) reveals about where `ephemeral_message_id`/`receiver_user`/`message_id: 0`
truly originate.

## 13. Confirmation of zero persistent changes

No file was edited this pass — every check in this report was static code reading (`inspect`,
`grep`), a Python one-liner reading installed-package internals, and read-only environment/OS
checks (`.env` grep, Windows hosts file read). No temporary instrumentation was added or needed for
this pass.

## 14. Git status

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
Identical to every prior accepted state. Nothing new. Nothing staged. Nothing committed.

---

Awaiting explicit authorization for the §10 raw-transport-boundary capture before any further step.
