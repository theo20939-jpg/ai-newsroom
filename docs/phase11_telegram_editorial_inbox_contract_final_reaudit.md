# Phase 11 — Final Targeted Contract Re-Audit

Verifies Correction Pass 2 (§1, §14, §16, §24 of
`docs/phase11_telegram_editorial_inbox_architecture_contract.md`), which addressed N-1 (MAJOR) and
N-2 (MINOR) from `docs/phase11_telegram_editorial_inbox_contract_reaudit.md`. This is a narrow,
final targeted re-audit of the corrected sections and their direct dependents — not a full re-run
of the original 24-area audit. The Contract, Discovery, Decision Resolution, production code,
tests, and migrations were not modified to produce this document.

---

## 1. Executive Verdict

Both remaining findings — N-1 (Python `len()` used as the authoritative Telegram-length safety
check instead of UTF-16 code units) and N-2 (the terminal oversize case not explicitly mapped to
§16) — are **fully and correctly resolved**. The corrected §14 algorithm is deterministic, provably
terminating, and now measures length in the unit Telegram actually enforces against. §14 and §16
now form one consistent, cross-referenced failure path for the terminal-oversize case (§16 Case E).
Test obligations (§24) are sufficient to prove the corrected behavior, not merely the happy path.
No new CRITICAL or MAJOR defect was introduced by Correction Pass 2. Two narrow, non-blocking
observations are noted (one pre-existing and out of this pass's scope, one a theoretical
degenerate case with no realistic path through this application) — neither is a MINOR finding
requiring correction. **CRITICAL = 0, MAJOR = 0, MINOR = 0.**

---

## 2. N-1 Resolution Verification

Re-read §14 in full (current lines 506–612). Confirmed:

- The authoritative invariant is now frozen as `telegram_utf16_length(rendered) <= SAFE_LIMIT`,
  used at both check points (algorithm steps 2 and 4) — not `len(rendered)`.
- `SAFE_LIMIT = 4096` is explicitly stated in **UTF-16 code units** (not bare "characters").
- The Contract explicitly states: **"Python's built-in `len()` MUST NOT be used as the sole,
  authoritative Telegram-length safety check"** — the exact prohibition requested.
- `len()` is still permitted for one explicitly-scoped, non-safety-critical purpose (picking the
  next truncation candidate, step 3) — the Contract is careful to distinguish this from the binding
  safety decision, so there is no ambiguity about which use of `len()` (if any) is acceptable.
- The "why this matters" rationale is technically accurate and correctly tied to concrete, verified
  evidence: astral-plane characters (code point `> U+FFFF`) occupy one Python code point but two
  UTF-16 code units, and the card template's own static `📰` (§12) is itself such a character —
  this is stated as a real, already-triggered fact, not a hypothetical.

**Result: N-1 fully resolved.**

---

## 3. UTF-16 Measurement Verification

**Check 1 (what the invariant covers)**: §14's "what 'final rendered' means for measurement
purposes" paragraph explicitly requires the measured string to include every dynamic value *after*
HTML-escaping, all static structural markup (including the `📰` decoration), the hashtags line, any
optional metadata line, and the truncation marker if present — "No component of the card may be
measured in isolation or omitted from the measured string." This directly satisfies every sub-item
of the audit's Check 1 (static markup, static emoji, AI-generated emoji — covered by "every dynamic
value" — hashtags, metadata, truncation marker, all transmitted characters).

**Check 2 (reference implementation correctness)**: independently re-executed this session:
```
tlen(s) = len(s.encode("utf-16-le")) // 2
tlen("A")                    -> 1
tlen("Я")  (BMP Cyrillic)    -> 1
tlen("📰") (astral emoji)    -> 2
tlen("A📰Я") (mixed)         -> 4   (vs. Python len() of the same string -> 3)
```
This matches the Contract's illustrative helper and the audit's own expected values exactly,
confirming `len(text.encode("utf-16-le")) // 2` is a correct UTF-16-code-unit counter for every
case relevant here. No realistic edge case in this application's data path (LLM-generated JSON
strings, RSS-sourced titles/URLs — both produce well-formed Unicode `str` objects, never lone
surrogates or invalid code points) invalidates this guarantee. No theoretical blocker is manufactured
here, consistent with the audit's own instruction not to invent unrealistic corner cases.

**Result: measurement semantics are technically sound.**

---

## 4. Truncation and Termination Verification

Traced the full algorithm (§14, numbered steps 1–5) end to end:

- Step 1 renders the complete card, fully escaped, with the untruncated `draft_body` — the
  first measurement always reflects genuine final content.
- Step 2's check uses `telegram_utf16_length`, not `len()`.
- Step 3 truncates **only** the raw, pre-escape `draft_body`, appends the truncation marker to the
  raw text, then re-escapes and re-renders from scratch — escaping is never applied twice and never
  applied to an already-escaped string, so entities cannot be split (confirmed by the "why this is
  safe by construction" paragraph, which explicitly states this).
- Ordinary Python `str` slicing operates on whole Unicode code points, so truncation cannot produce
  invalid Unicode (e.g. an unpaired surrogate) — the Contract explicitly acknowledges a cut may
  visually separate a multi-code-point grapheme cluster (e.g. an emoji + modifier), and explicitly,
  correctly declines to require grapheme-cluster-aware truncation for this MVP, matching the
  instruction not to overengineer.
- Only `draft_body` is ever shrunk; `news_title`/`news_category`/`hashtags`/`news_url`/structural
  markup are named as never touched (§14, "field priority preserved").
- No multi-message splitting exists anywhere in §14; one card remains one Telegram message,
  restated explicitly and consistent with Decision Resolution §8 (unchanged).

**Termination proof (Check 4, high scrutiny)**: step 4 requires the raw-body budget to strictly
decrease on every iteration that repeats step 3 ("reduce the raw-body budget further... and repeat
step 3"), and step 5 defines the floor: the budget is bounded below by zero, at which point the
terminal fallback triggers unconditionally. A strictly-decreasing, non-negative integer sequence
must reach zero in a finite number of steps regardless of whether a fixed step size or a binary
search is chosen (both are explicitly permitted, deterministic choices) — so the loop is
**guaranteed to terminate**, either by fitting (step 2/4's check passing) or by reaching the
terminal fallback (step 5). There is no possible infinite loop from truncation-marker re-addition,
escaping expansion, or unit-counting, because none of these affect the strictly-decreasing budget
variable that drives termination. Planning does not need to invent anything to guarantee progress —
the decreasing-budget requirement is already the thing that guarantees it, and it is already frozen.

**Result: the algorithm is deterministic and provably terminating.**

---

## 5. N-2 / Terminal Failure Verification

Re-read §14 step 5's terminal-fallback clause and §16 Case E (current line 638) together.

- §14 states, precisely: if the card still exceeds `SAFE_LIMIT` even with `draft_body` fully
  exhausted, the renderer "**MUST NOT** return that oversized string for sending" and instead
  "raises a dedicated, well-defined rendering-failure signal."
- §14 explicitly names the target: **"treated as exactly one concrete trigger of §16 Case E."**
- §16 Case E's table row was itself updated to name this exact trigger in return: "One card's
  formatting fails (a genuinely malformed `EditorialInboxCard`, e.g. an escaping bug, **or** the
  §14 terminal length-safety fallback...)." The cross-reference is bidirectional and unambiguous —
  a reader arriving at either section is pointed at the other.
- §14 explicitly states: no `EditorialTask`/`ContentDraft`/workflow state is touched by this path,
  and "a `COMPLETED` workflow remains `COMPLETED`" — restated even though §16's own critical
  invariant already guarantees this by construction (no write path exists anywhere in this design),
  so the restatement is redundant-but-harmless emphasis, not a contradiction.
- No retry, regeneration, or workflow call is introduced anywhere in this path — confirmed absent
  from both §14 and §16.

**Result: N-2 fully resolved.** §14 and §16 now define exactly one, consistent, bidirectionally
cross-referenced failure path for the terminal-oversize case — not two competing mechanisms.

---

## 6. Multi-Card Failure Verification

Applying §16 Case E to a hypothetical 5-card `/news` result where card #3 hits the terminal
rendering failure: cards #1 and #2 are unaffected (already handled/sent before #3 is reached in the
handler's per-card loop); card #3's renderer raises the dedicated signal, which the handler's
per-card try/except (§16 Case E, explicit) catches, logs, and skips; the loop then proceeds to
cards #4 and #5, which "must not [be] abort[ed]" per Case E's explicit wording. This sequencing is
unambiguous.

**One narrow, pre-existing textual tension noted, out of this pass's scope**: §16's own "logging
vs. user-facing boundary" DECISION states "only the short, generic, static message reaches the
Telegram user, in every failure case (B/D/E above)" — read literally, this could be interpreted as
requiring an additional, distinct user-facing message for each skipped card (on top of the
successfully-sent ones), whereas Case E's own row only says "skipped/logged" without naming a
specific user-facing text. Both readings are defensible (send a generic per-card notice, or skip
silently and only log). **This ambiguity predates Correction Pass 2** — it exists in §16 text that
Pass 2 did not rewrite (only Case E's *trigger* list was extended, not its resolution/wording), and
the task's own scope instruction directs not to reopen already-approved architecture unless the
corrected sections directly contradict it. This does not. Recorded as an **OBSERVATION** (§11),
not a MINOR finding — it does not block approval and is not a product of this correction pass.

**Result: the skip-and-continue sequencing itself is fully unambiguous; a narrow, pre-existing,
out-of-scope textual nuance about per-card user notification is noted for a future documentation
pass, not this one.**

---

## 7. Test Obligation Verification

Re-read §24's Renderer and Handler test additions (current lines 814–877) against the audit's
11-point checklist:

| # | Required proof | Present in §24? |
|---|---|---|
| 1 | BMP measurement correctness | Yes — "BMP-only... equals its Python `len()`" |
| 2 | Astral/emoji measurement correctness | Yes — "measured... as 2 code units per astral character" |
| 3 | `len() <= 4096` but `telegram_utf16_length() > 4096` correctly rejected | Yes — explicit constructed-payload obligation |
| 4 | Static card emoji counted | Yes — explicit obligation naming `📰` |
| 5 | AI-generated emoji counted correctly | Yes — "emoji injected into `draft_title`/`draft_body`/`hashtags`" |
| 6 | Escaping expansion + UTF-16 semantics together | Yes — explicit combined worst-case obligation |
| 7 | Every successful render satisfies `<= 4096` | Yes — explicit general-invariant obligation |
| 8 | Truncation doesn't break escaped HTML/entities | Yes — pre-existing entity-safety obligation, unchanged |
| 9 | Terminal oversize raises dedicated failure | Yes — explicit "Terminal fallback" obligation |
| 10 | Handler skips the failed card | Yes — explicit handler-test obligation |
| 11 | Handler continues remaining cards | Yes — same obligation, "still sends the other 4" |

**No gap found.** Every binding behavior in the corrected §14/§16 has a corresponding, specific test
obligation — these obligations are capable of proving the frozen algorithm's actual behavior
(including the specific failure mode a naive `len()`-based implementation would exhibit), not
merely a happy path.

---

## 8. F-1 / F-3 Non-Regression

Quick regression grep and read confirm both remain intact, unaffected by Pass 2:
- **F-1**: `news_url` remains in §13's binding escaping list; §12 still freezes it as plain escaped
  text, never an `<a href>`; §24 still requires the literal-`&` escaping test. No raw/unescaped URL
  interpolation was reintroduced anywhere.
- **F-3**: §10's corrected forum-topic text is untouched by Pass 2 (Pass 2 only modified §1, §14,
  §16, §24); `Message.answer()`'s automatic `message_thread_id` propagation for the pinned
  `aiogram==3.29.1` remains documented exactly as corrected in Pass 1, still scoped to the pinned
  version, still requiring no persisted thread configuration.

**Result: no regression on either finding.**

---

## 9. File Scope Verification

§23's authorized file scope (current lines 768–796) is unchanged by Pass 2. The UTF-16 length
helper and the new dedicated rendering-failure exception type both belong inside the already-
authorized `bot/formatting.py` — a helper function plus one small exception class is ordinary
content for a single module and does not warrant, and was not given, a new file. No Telegram
utility/config file, no `aiogram` patch/wrapper, and no new production file of any kind is required
by either N-1's or N-2's correction. **No silent scope expansion.**

---

## 10. Architecture / MVP Non-Regression

Re-checked all sections outside §14/§16's corrected content: read-only (§7/§9/§17, untouched),
pull-only (§20, untouched), `/news` entry point (§9, untouched), latest-5 (§6, untouched),
COMPLETED-only eligibility (§6, untouched), no pagination (§15, untouched), no in-app auth (§11,
untouched), no callbacks (§10/§15/§19, untouched), no Approve/Reject/Rework (§19, untouched), no
scheduler/push (§20, untouched), no publication (§20/§21, untouched), no memes/images (§21,
untouched), no migration (§22, untouched), and every frozen Phase 5–10 file (§18) — none of which
appears in Pass 2's diff (§1, §14, §16, §24 only). **No architectural or MVP-scope regression.**

---

## 11. Findings

### CRITICAL

None.

### MAJOR

None.

### MINOR

None.

### OBSERVATIONS

- **O-1**: §16's "logging vs. user-facing boundary" line ("only the short, generic, static message
  reaches the Telegram user, in every failure case (B/D/E above)") admits two defensible readings
  for the per-skipped-card UX (a distinct generic notice per skipped card, vs. a silent skip with
  only server-side logging). This predates Correction Pass 2, is not part of the corrected
  sections' substance, and does not block approval — noted for a possible future documentation
  clarity pass, not required now.
- **O-2**: the truncation loop's "cut at the last complete word boundary before a shrinking
  character budget" step does not name a fallback for the theoretical case of a `draft_body`
  containing one unbroken run of non-whitespace longer than the entire shrink range (no word
  boundary exists to cut at). This has no realistic path through this application — AI-generated
  editorial body text (`CopywritingCapability`, Phase 10, unchanged) is structured prose, not a
  single unbroken token — and the loop still terminates regardless (§4 above) via the terminal
  fallback if this ever occurred. Not a finding; noted only as a theoretical completeness remark.

---

## 12. Readiness Score

**9/10.** Both remaining findings from the prior re-audit (N-1, N-2) are fully, precisely, and
verifiably resolved, with sound technical reasoning and correct reference semantics (independently
re-executed and confirmed this session). The corrected algorithm is deterministic, provably
terminating, and closes the exact gap between Python string semantics and Telegram's actual
UTF-16-based limit — including in the one place (the frozen template's own emoji) where the defect
was guaranteed to manifest. Test obligations are complete against an 11-point checklist with no
gaps. The two observations are both explicitly out of this pass's scope or explicitly
non-realistic, not defects requiring correction. The single point withheld from a perfect score
reflects O-1's genuine (if narrow and pre-existing) textual ambiguity, which a future documentation
pass could close in one sentence, not any defect introduced by this correction round.

---

## 13. Final Verdict

PHASE 11 CONTRACT APPROVED — READINESS SCORE: 9/10
