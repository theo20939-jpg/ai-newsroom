# Phase 11 — Targeted Contract Re-Audit

Verifies the targeted correction applied to
`docs/phase11_telegram_editorial_inbox_architecture_contract.md` in response to
`docs/phase11_telegram_editorial_inbox_contract_audit.md`'s three MAJOR findings (F-1, F-2, F-3).
This is a narrow re-audit of the corrected sections and their dependents, not a full re-run of the
original 24-area audit. The Contract, Discovery, Decision Resolution, production code, tests, and
migrations were not modified to produce this document.

---

# Executive Summary

F-1 and F-3 are fully and correctly resolved — no further action needed on either. F-2 is resolved
for the specific defect it identified (pre-escape truncation budget not accounting for HTML-escape
expansion) — the new render→verify→shrink→re-render→re-verify algorithm is sound and closes that
gap. However, this re-audit's high-scrutiny character-count check (instructed Check 2B) surfaced a
**new, previously-undetected MAJOR issue in the same section**: the algorithm's frozen length
check, `len(rendered) <= SAFE_LIMIT`, uses Python's built-in `len()` — which counts Unicode code
points, not the UTF-16 code units Telegram's own 4096-character limit is actually measured in. This
is not a theoretical corner case: it is directly, verifiably triggered by the frozen card template's
own literal "📰" emoji (§12), confirmed this session by direct execution (`len('📰') == 1` in
Python, but its real UTF-16 encoding is 2 code units). The Contract's own claim that "no separate,
softer internal margin is needed... because the algorithm verifies the *actual* final rendered
length directly" is therefore not true as specified. **CRITICAL = 0, MAJOR = 1, MINOR = 1.**
Approval requires CRITICAL = 0 AND MAJOR = 0 — **not yet met.**

---

# Previous Findings Resolution

## F-1

**Original finding**: §13's escaping invariant omitted `news_url`, despite §12's template
interpolating it directly.

**Verification performed**: re-read §12 and §13 in full (current line ranges 418–499).

**Result: FULLY RESOLVED.**
- §13's binding escaping invariant now explicitly lists `news_url` alongside `draft_title`,
  `draft_body`, `hashtags`, `news_title`, `news_category` — "all dynamic content... MUST be
  HTML-escaped... including `news_url`" (§13, corrected paragraph).
- §12 explicitly freezes the design choice this audit's original finding asked for: `news_url` is
  rendered as **plain, HTML-escaped text**, never as an `<a href="...">` anchor. No clickable link
  is introduced.
- §13 explicitly states no href-attribute-escaping rule is needed, and states why (no href
  attribute exists anywhere in the frozen card) — this directly answers the original audit's "be
  precise about URL handling" instruction rather than leaving it ambiguous.
- Consistency confirmed across dependents: §24's renderer tests now require `news_url` escaping
  (including a literal-`&` case) and require confirming `news_url` is never wrapped in an `<a>` tag.
  §23's file scope is unaffected (no new file required to add one field to an existing escaping
  routine).
- **No other dynamic field used by the frozen card template was found unprotected.** `news_title`,
  `news_category`, `draft_title`, `draft_body`, `hashtags`, `news_url` are all now covered. The one
  remaining interpolated value, `news_published_at`, is formatted via a fixed `%Y-%m-%d` strftime
  pattern (§12) that can only ever produce ASCII digits and hyphens — it cannot contain `<`, `>`, or
  `&` by construction, so its omission from the escaping invariant is safe, not a gap (noted as an
  OBSERVATION below since the Contract does not state this exemption explicitly).

**Conclusion**: F-1 requires no further correction.

## F-2

**Original finding**: §14's truncate-raw-then-escape design used a flat pre-escape character budget
that was not provably safe against worst-case HTML-escaping expansion.

**Verification performed**: re-read §14 in full (current lines 501–561); traced the algorithm's five
numbered steps against the audit's expected "render → measure final escaped HTML → if over limit,
shrink raw `draft_body` → re-render → re-measure → repeat" shape; re-read §24's corresponding
renderer test additions.

**Result: RESOLVED for the specific defect originally identified.**
- `SAFE_LIMIT = 4096` is explicitly defined (§14).
- The measurement point is the **final, fully-rendered, fully-escaped card string** — step 1 renders
  with every field escaped and the *complete* `draft_body` before any length check occurs; steps 2
  and 4 both check `len(rendered)`, i.e., the assembled, post-escape, post-template string — not raw
  text. Static markup, optional metadata, and the truncation marker are all included in this
  measurement because they are part of the one string being measured (§14 step 1's "render the full
  card... with every field HTML-escaped").
- Truncation acts only on `draft_body`; `news_title`/`news_category`/`hashtags`/`news_url`/
  structural markup are explicitly named as never shortened (§14, "field priority preserved"
  paragraph).
- Truncation is applied to the **raw**, pre-escape string, with escaping re-applied fresh on every
  iteration (§14 step 3–4) — this structurally prevents cutting inside an HTML entity, exactly as
  the audit required. §24 adds an explicit test for "no partial/dangling entity sequence."
- One card remains one Telegram message; no multi-message splitting was introduced (§14, explicit
  closing paragraph; consistent with Decision Resolution §8, unchanged).
- The algorithm terminates deterministically in the ordinary case (loop shrinks a bounded
  `draft_body` toward zero, each iteration strictly reducing the budget) — see edge-case analysis
  below for the one boundary condition worth naming precisely.

**However**, this re-audit's character-count check (instructed Check 2B) found that the *specific
defect originally reported* (pre-escape truncation ignoring escape expansion) is fixed, but a
**different, adjacent defect in the same measurement mechanism** was not caught by either the
original correction or the original audit. See **Finding N-1** below — this is why F-2's area is not
fully closed even though the originally-reported problem is fixed.

**Conclusion**: the specific F-2 defect (escape-expansion-unaware pre-escape budget) is resolved.
A new, related MAJOR defect (measurement-unit mismatch) remains open in the same section — reported
as N-1, not as a re-opening of F-2 itself, since it is a distinct root cause.

## F-3

**Original finding**: §10 claimed forum-topic thread preservation was "not guaranteed," contradicted
by the pinned `aiogram==3.29.1`'s actual `Message.answer()` source.

**Verification performed**: re-read §10 in full (current lines 349–384); re-ran, this session,
```
python -c "import aiogram; print(aiogram.__version__)"        -> 3.29.1
python -c "import inspect; from aiogram.types import Message; print(inspect.getsource(Message.answer))"
```
confirming the same source the original audit found:
```python
message_thread_id=self.message_thread_id if self.is_topic_message else None,
```
still present, unchanged, in the installed package. Also re-read §9 to confirm the handler's send
path.

**Result: FULLY RESOLVED.**
- §10 now states the corrected fact precisely: `Message.answer()` already, automatically,
  unconditionally threads `message_thread_id` for topic messages under the pinned version, with the
  exact source line quoted.
- The correction is explicitly scoped to the **currently pinned** `aiogram==3.29.1` — §10's closing
  INFERENCE paragraph explicitly disclaims any guarantee "about `aiogram`'s API contract across
  arbitrary future versions" and states the assumption would need re-verification after any future
  aiogram upgrade. This is exactly the calibration the re-audit instruction asked for — no
  overclaiming.
- No persisted thread configuration, manual `message_thread_id` storage, or destination-routing
  table was introduced — §10 explicitly states this remains true ("it is a property of the existing
  call, not new Phase 11 code").
- Private-chat and group/supergroup behavior is unchanged and stated as such.
- **Single send-path check**: §9's handler semantics show exactly one send construct —
  `message.answer(html, parse_mode=ParseMode.HTML)` — used for every one of the up-to-5 cards, with
  no alternate `bot.send_message()` or raw API call anywhere in the Contract's handler design. There
  is no second, inconsistent sending path that would bypass this guarantee.

**Conclusion**: F-3 requires no further correction.

---

# Message Length Edge-Case Verification

**Check 2A (pathological case: static markup + required non-body fields + escaped metadata alone
exceed `SAFE_LIMIT` even with an empty `draft_body`).**

§14 step 5 names this case explicitly: "In the theoretical extreme where even an empty-body card
would exceed `SAFE_LIMIT`... the card is still sent in its empty-body form — a defensive last
resort, not an anticipated path, and not a new failure case beyond §16's existing table."

This is a real, named edge case, not silently ignored — but tracing it further: if that empty-body
card is still over `SAFE_LIMIT` when actually sent, Telegram's `sendMessage` call will itself fail
(HTTP 400, "message is too long"). §14 asserts this is "not a new failure case beyond §16's existing
table" but does not explicitly say **which** row of §16's table governs it. Tracing it independently:
this is a `message.answer()` exception at send time, which is precisely §16 **Case D** ("Telegram
send failure... logged; does not raise further"), combined with **Case E**'s per-card
skip-and-continue discipline (the oversized card is skipped/logged, the remaining cards in the same
`/news` invocation are unaffected). So a fully deterministic behavior **does** already exist for
this edge case once §14 and §16 are read together — Planning does not need to invent new failure
handling. The gap is textual, not architectural: §14 should say "governed by §16 case D/E" instead
of the vaguer "not a new failure case beyond §16's existing table." Classified as **MINOR** (N-2)
below — non-blocking, obvious narrow correction (add the explicit cross-reference).

Separately: is this edge case actually reachable? `news_category` is a short, bounded enum string.
`news_title`, `hashtags`, and `news_url` are backed by `Text`/`JSON` columns with **no DB-enforced
maximum length** (confirmed again this session, `database/models/news_event.py` and
`database/models/content_draft.py`) — so the Contract's own "not expected in practice" framing is an
inference about realistic data, not a proven bound. This is consistent with how §14 itself already
frames it (a named, honestly-disclosed, low-probability defensive fallback) — not a new
contradiction, just worth confirming the disclosure is accurate, which it is.

**Termination**: the shrink loop (§14 steps 3–4) is deterministic and terminates — each iteration
strictly reduces the raw-body character budget, bounded below by zero (step 5), so the loop cannot
run unboundedly. No infinite-loop risk exists.

---

# Forum Topic Verification

Re-confirmed independently this session (not merely re-trusting the prior audit's evidence):
`aiogram.__version__ == "3.29.1"` (same as before — dependency unchanged since the original audit).
`inspect.getsource(Message.answer)` still shows the identical
`message_thread_id=self.message_thread_id if self.is_topic_message else None` construction.

§10's corrected text accurately reflects this pinned/current behavior, explicitly avoids
over-claiming future-version guarantees, requires no persisted thread configuration or manual
`message_thread_id` storage, and remains fully compatible with private-chat and group/supergroup use
(unchanged, since forum-topic handling is additive to, not a replacement for, the existing
`message.answer()` call). §9 confirms the handler uses `message.answer()` consistently for every
card sent — no alternate or bypassing send path exists in the Contract. **No inconsistency found.**

---

# Test Contract Verification

§24's Renderer tests (current lines 762–782) now explicitly require:
- `news_url` escaping, including a literal-`&` case (F-1).
- Confirmation `news_url` is never wrapped in an `<a href>` (F-1 design choice).
- A worst-case escaping-expansion `draft_body` case, verifying the **final, fully-rendered payload**
  is `<= 4096` after truncation — this exercises the render-verify-shrink loop end to end, not just
  the pre-escape truncation step in isolation (F-2's originally-reported defect).
- Entity-safety of truncation (no dangling `&`, `&a`, `&am`, `&amp`, no unclosed tag).
- A "fits without truncation" case, confirming the loop performs zero iterations and no field other
  than `draft_body` is ever touched.

§24's Handler tests (current lines 784–798) now explicitly require a forum-topic
(`is_topic_message=True` + `message_thread_id` set) case, confirming the handler does not interfere
with `aiogram`'s automatic propagation (F-3).

**Gap found**: none of these new obligations require a test asserting the length check itself is
computed in **UTF-16 code units** rather than Python code points (consistent with Finding N-1 below
— the test obligations faithfully mirror the algorithm as currently specified, so they would pass
against an implementation that has the same latent defect the algorithm itself has). This is not a
new, independent test-contract defect — it is a direct, expected consequence of N-1 and will resolve
automatically once N-1's correction is made and the render-verify-shrink algorithm's own definition
of "length" is fixed.

Overall, the test obligations are capable of proving the frozen algorithm's *intended* behavior, not
merely a happy path — a good outcome, contingent on N-1 being corrected first.

---

# File Scope Verification

Re-confirmed directly: all three corrections (F-1, F-2, F-3) are text/specification changes to
sections describing behavior inside modules already authorized by §23 —
`bot/formatting.py` (escaping + length algorithm) and `bot/handlers/news.py` (forum-topic behavior,
which requires zero new code since it is inherited from the existing `message.answer()` call). No
new production file, Telegram utility/config file, or `aiogram` patch/wrapper module is required by
any of the three corrections. §23's authorized file list is unchanged and remains sufficient.
**Confirmed: file scope did not silently expand.**

---

# Invariant Preservation

Re-checked §§1–9, 11, 15–22, 25, 27–29 (the sections *not* targeted by the correction) for any
drift introduced as a side effect of the correction pass: read-only (§7/§9/§17, unchanged),
pull-only (§20, unchanged), `/news` entry point (§9, unchanged), latest-5 (§6, unchanged),
COMPLETED-only eligibility (§6, unchanged), no auth (§11, unchanged), no callbacks (§10/§15/§19,
unchanged), no Approve/Reject/Rework (§19, unchanged), no push/scheduler (§20, unchanged), no
publication (§20/§21, unchanged), no memes/images (§21, unchanged), no migration (§22, unchanged),
no frozen Phase 5–10 file requires modification (§18, unchanged — none of the three corrections
touch any capability, workflow, or model file). **No invariant was altered.**

---

# Findings

## CRITICAL

None.

## MAJOR

### N-1
**SEVERITY**: MAJOR
**LOCATION**: §14 (Message Length), algorithm steps 1–2, 4, and the "why this is safe by
construction" paragraph.
**EVIDENCE**: directly executed this session:
```
>>> len('📰')
1
>>> len('📰'.encode('utf-16-be')) // 2
2
```
Telegram's Bot API message-length limit (4096, cited correctly in §14 as "UTF-16 code units") is
measured in UTF-16 code units, in which every character outside the Basic Multilingual Plane (any
code point above `U+FFFF` — the overwhelming majority of emoji, including the frozen card template's
own leading `📰`, `U+1F4F0`) occupies **two** code units (a surrogate pair), not one. §14's algorithm
performs its safety check as `len(rendered) <= SAFE_LIMIT`, and Python's built-in `len()` on a `str`
counts Unicode code points, not UTF-16 code units — so `len()` **undercounts** the true,
Telegram-relevant length by one for every astral-plane character present.
**PROBLEM**: this is not a hypothetical corner case — the frozen card template (§12) itself begins
with the `📰` emoji, so this undercount occurs on literally every card the Contract's design
renders, before even considering AI-generated emoji that may appear in `draft_body`/`hashtags` (a
realistic possibility for social-media-style generated content, which would compound the
undercount by one per emoji). §14 explicitly claims "no separate, softer internal margin is needed...
because the algorithm verifies the *actual* final rendered length directly, rather than estimating
it" — this claim is false as specified, since the chosen measurement (`len()`) is not the actual
length Telegram enforces against.
**IMPACT**: a card whose Python-code-point length is measured as `<= 4096` can, in reality, exceed
Telegram's true 4096 UTF-16-code-unit limit whenever the rendered text contains enough astral-plane
characters — causing an unexpected `sendMessage` rejection for a card the Contract's own algorithm
asserts is "provably safe," reproducing a milder version of the exact class of bug F-2 was raised to
close.
**REQUIRED CORRECTION**: specify the length check in UTF-16 code-unit terms, not Python `len()` —
e.g. `len(rendered.encode('utf-16-le')) // 2 <= SAFE_LIMIT`, or an equivalent, explicitly-named
UTF-16-aware length function — and apply this measurement consistently everywhere §14 currently says
`len(rendered)`.

## MINOR

### N-2
**SEVERITY**: MINOR
**LOCATION**: §14 step 5 (empty-body-still-over-limit fallback).
**PROBLEM**: the fallback path asserts it is "not a new failure case beyond §16's existing table"
without naming which case. Tracing it independently (see Message Length Edge-Case Verification,
above), it resolves cleanly to §16 Case D (Telegram send failure) combined with Case E's per-card
skip-and-continue — so no invention is actually required of Planning, but the Contract does not say
so explicitly.
**IMPACT**: none if a reader traces §14/§16 together, as this audit did; a small, avoidable ambiguity
if they don't.
**REQUIRED CORRECTION** (non-blocking): add an explicit cross-reference in §14 step 5, e.g. "this
oversized-send case is governed by §16 Case D (logged Telegram send failure) and Case E (the
affected card is skipped; remaining cards in the same invocation are unaffected)."

## OBSERVATIONS

- `news_published_at`'s `%Y-%m-%d` strftime formatting can only ever produce ASCII digits and
  hyphens, so its omission from §13's explicit escaping list is safe by construction, not a gap.
  Stating this exemption explicitly in §13 (one sentence) would remove any doubt for a future reader
  but is not required for correctness.
- N-1's root cause (Python `len()` vs. UTF-16 code units) is a well-known, general pitfall in any
  Telegram Bot API integration — not specific to this repository's own code — and is the same class
  of unit-mismatch the original audit's Check 9 (Telegram message length, high scrutiny) was
  designed to catch; it was not caught in the first audit pass because that pass focused on the
  escaping-expansion mechanism (the defect that became F-2) rather than the measurement primitive
  itself. Worth noting for future audit calibration, not a defect in this revision.

---

# Readiness Score

**7/10.** Two of the three original MAJOR findings (F-1, F-3) are cleanly and completely resolved
with no side effects. The third (F-2) is resolved for its originally-identified root cause, and the
replacement algorithm's overall shape (render → verify → shrink → re-render → re-verify) is sound
and well-specified. The one new MAJOR finding (N-1) is narrow, precisely located, and correctable
with a one-line measurement-function change — it does not require reopening the algorithm's
structure, only fixing its unit of measurement. No CRITICAL issue exists anywhere; file scope,
invariants, and test-contract completeness (contingent on N-1) all check out cleanly.

---

# Final Verdict

PHASE 11 CONTRACT NOT READY — CORRECTIONS REQUIRED
