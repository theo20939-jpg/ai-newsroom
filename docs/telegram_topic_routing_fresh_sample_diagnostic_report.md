# Telegram Topic Fresh Sample Diagnostic Report

Investigation only, on the exact fresh `/news` invocation the user sent from inside the
newly-created, distinct `Newsroom` forum topic (not the renamed General topic — explicitly
confirmed by the user). Temporary diagnostic logging was added to
`bot/handlers/news.py`, used for exactly one capture, then fully reverted — confirmed via
`git diff` matching the pre-diagnostic (M3/M4-accepted) content exactly. No production file
change persists from this investigation. Not committed or staged.

---

## 1. Exact fresh update identification

`Update id=837679392`, logged as `"is handled. Duration 1483 ms"` at `2026-07-22 17:33:14`, with
diagnostic evidence captured at `17:33:13.688`–`17:33:14.459` immediately preceding it — this is
the freshest invocation, sent after the bot was restarted specifically for this capture, correctly
isolated from all earlier backlog noise.

## 2. Raw incoming topic fields (from the actual, live `message.model_dump_json()` dump)

```json
"message_id": 0,
"chat": { "id": -1004297182444, "type": "supergroup", "is_forum": true, ... },
"message_thread_id": null,
"is_topic_message": null,
"forum_topic_created": null,
"forum_topic_edited": null,
"forum_topic_closed": null,
"forum_topic_reopened": null,
"general_forum_topic_hidden": null,
"general_forum_topic_unhidden": null,
"direct_messages_topic": null,
"text": "/news@nnj_newsroombot"
```

`chat.is_forum = true` — the chat genuinely is a forum-enabled supergroup, consistent with the
user's confirmation. **No field anywhere in the payload identifies which topic this message
belongs to** — `message_thread_id` and `is_topic_message` are both `null`, and every other
forum-related field (`forum_topic_created`/`edited`/`closed`/`reopened`,
`general_forum_topic_hidden`/`unhidden`) is also `null` (expected — those only populate on the
service messages that create/modify a topic itself, not on ordinary messages sent inside one).
There is no recoverable topic signal anywhere else in this payload.

## 3. Deserialized aiogram fields

Matches the raw JSON exactly — `message.chat.id = -1004297182444`, `message.chat.type =
"supergroup"`, `message.chat.is_forum = True`, `message.is_topic_message = None`,
`message.message_thread_id = None`. Aiogram's `Message`/`Chat` Pydantic models deserialized the
payload faithfully; no aiogram-side transformation, default-substitution, or bug is involved —
these fields are declared as plain, undecorated `Optional` fields with no custom validator that
could alter an already-present value (re-confirmed by re-reading `Message.answer()`'s and the
underlying `Chat`/`Message` model definitions this session).

## 4. Outgoing request fields

`outgoing_chat_id = -1004297182444` (correct — same chat), `outgoing_message_thread_id = None`.
Constructed via `message.answer(html, parse_mode=ParseMode.HTML)` — the same, sole send mechanism
used for every card, unchanged since M3. `message.answer()`'s own logic
(`message_thread_id=self.message_thread_id if self.is_topic_message else None`) evaluated exactly
as its source dictates: since `self.is_topic_message` is `None` (falsy), it correctly set
`message_thread_id=None` on the outgoing request.

## 5. Case classification

**CASE C** — the fresh raw Telegram Update itself contains no valid `message_thread_id`, despite
`/news` being sent from a distinct, non-General forum topic in a genuinely forum-enabled
supergroup.

## 6. First exact divergence point

**Before this codebase's boundary entirely.** The trace is:
```
Telegram/backend raw Update  <-- message_thread_id already null HERE
    -> aiogram deserialization (faithful passthrough, confirmed no alteration)
    -> Dispatcher -> handle_news(message)  (message_thread_id still null - inherited, not newly lost)
    -> message.answer()  (correctly derives None from an already-null is_topic_message)
    -> outgoing SendMessage  (message_thread_id=None, correctly reflecting its null input)
```
There is no step, anywhere in this chain, where a **present** `message_thread_id` gets dropped,
overwritten, or ignored. The value is already absent at the first hop this codebase can observe.
`aiogram`, `bot/handlers/news.py`, and `bot/formatting.py` all behave correctly and consistently
with every prior verification (Contract F-3, Plan Audit, M3 implementation) — none of them is
where this diverges.

## 7. Root cause — concrete evidence, not assumption

Independent of the missing `message_thread_id` itself, the captured raw payload contains several
field names that **do not exist in Telegram's official Bot API `Message` object schema**:
`"ephemeral_message_id"`, `"receiver_user"`, `"guest_query_id"`, `"guest_bot_caller_user"`,
`"guest_bot_caller_chat"`, `"supports_guest_queries"` (on `from_user`), `"direct_messages_topic"`/
`"is_direct_messages"` (on `chat`), `"chat_owner_left"`/`"chat_owner_changed"`. None of these are
documented, real Telegram Bot API fields. Additionally, `"message_id": 0` is itself atypical — real
Telegram message IDs are positive, monotonically-increasing integers per chat, never `0`.

This is concrete, direct evidence — not speculation — that **the backend actually serving this
bot's `getUpdates` responses is not behaving as the standard, official Telegram Bot API**. Whatever
that backend is, its Message payload for this update simply does not populate `message_thread_id`/
`is_topic_message` for this genuinely-distinct forum topic, even though `chat.is_forum: true` is
present and correct. This is fully consistent with, and directly explains, the "General" delivery
observed by the user: there is nothing in the received data identifying the topic, so
`message.answer()`'s already-correct logic has nothing to preserve.

**This is not proven to be a specific, named backend or configuration** — that would require
inspecting the actual network endpoint the polling client connects to, which this investigation
did not yet do (see item 8).

## 8. Narrowest remaining hypothesis and exact next diagnostic required

**Hypothesis**: the bot's `Bot`/`AiohttpSession` is, for this environment, communicating with a
Telegram-Bot-API-compatible endpoint other than the real `api.telegram.org` (e.g., a local relay,
proxy, or test harness), and that endpoint's topic support is incomplete for the `message_thread_id`
field specifically, while still correctly reporting `chat.is_forum: true` and otherwise behaving
Bot-API-compatibly (real command delivery, real chat identity, successful `sendMessage` round trips
observed throughout this whole session).

**Exact next diagnostic required to confirm**: log the `Bot` instance's actual configured API base
(`bot.session.api` / the `TelegramAPIServer` in use, or the literal request URL `aiohttp` connects
to for the `getUpdates` call) for one polling cycle — this would show definitively whether requests
go to `api.telegram.org` or elsewhere. Not performed in this pass (would require another temporary-
instrumentation + restart + capture cycle, and this report is required to stop here for
authorization first, per the task's own instruction).

## 9. Why the previous synthetic test passed

`tests/test_news_handler.py::test_forum_topic_message_thread_id_is_preserved_automatically`
constructs an `aiogram.types.Message` **directly, by hand**, with `is_topic_message=True` and
`message_thread_id=777` already set as literal Python values — it never deserializes a real (or
real-shaped) Telegram Update at all, so it can only prove *"if the incoming message already has
these two fields set, `message.answer()` preserves them"* — which remains true, re-confirmed again
by this session's own evidence (§4 above: `message.answer()`'s logic is not the point of failure).
It cannot, by construction, detect that the actual serving backend never populates these fields for
this real chat/topic in the first place. This is exactly the category of gap only a real, live
round trip could expose — and did.

## 10. Is a production-code fix actually required?

**No fix inside this repository's authorized files can solve this.** `bot/handlers/news.py`,
`bot/formatting.py`, and `aiogram` (third-party, unmodified) all already behave correctly given
their input; the input itself lacks the one piece of information (`message_thread_id`) needed to
route the reply to the originating topic. There is no other field anywhere in the captured payload
that could serve as a substitute topic identifier (re-confirmed, §2). Constructing a workaround —
e.g., persisting a manual chat-to-topic mapping — would violate the frozen, binding Contract §10
constraint ("no persisted destination configuration," "no manual `message_thread_id` storage") and
would not be a "smallest architecture-preserving fix"; it would be a new, unauthorized destination-
routing mechanism.

## 11. Minimal proposed fix scope (not implemented)

None recommended within this codebase's files. If the next diagnostic (§8) confirms a
non-standard/misconfigured serving backend, the correct remediation is environmental (fixing or
replacing that backend's Bot API compatibility), not a code change in `bot/`. If, contrary to this
session's evidence, a future diagnostic instead finds the real `api.telegram.org` genuinely omits
`message_thread_id` for this specific, valid case (which would itself be surprising and
undocumented, given Telegram's own Bot API is well-established to populate this field for non-
General topics), that would warrant a fresh, separate investigation — not assumed or acted on here.

## 12. Regression test that must be added (once a fix is authorized and scoped)

Deferred until §8's diagnostic determines whether any application-level remediation is even
possible. If the backend is confirmed non-standard/environmental, no new regression test belongs
in this repository (there is nothing in application code to regress-test against). If a future
investigation instead finds a genuine, fixable gap in this codebase, the test would need to
construct a full, real-shaped `Update` object (not a hand-built `Message`) and feed it through
`Dispatcher.feed_update()`, per the task's own Step 4 guidance — not designed further here, since
no code-level root cause was found to test against.

## 13. Confirmation of zero persistent diagnostic changes / git status

```
 M bot/handlers/news.py            (unchanged from the M3/M4-accepted content - re-confirmed via
                                     git diff, byte-identical to before this investigation began)
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
Identical to the state at the end of the Russian Output Live Acceptance report — every line above
was already accepted in a prior step; this diagnostic investigation added and then fully removed
its own temporary logging, leaving zero net change. Nothing staged, nothing committed. The bot
process was stopped and restarted once during this investigation (to load the temporary
diagnostic) and remains running now with the diagnostic-free, already-accepted handler code.

---

Awaiting explicit authorization before any further diagnostic step or fix.
