# Phase 11 — M2 Telegram Renderer Report

## Files changed

- `bot/formatting.py` (new) — `render_editorial_card()`, `CardTooLongError`,
  `_telegram_utf16_length()`, `_escape()`, `_truncate_at_word_boundary()`, `_render_once()`.
- `tests/test_editorial_card_formatting.py` (new) — 24 tests.

## Implementation summary

`render_editorial_card()` implements the frozen Contract §12 template with every dynamic field
HTML-escaped via `html.escape(value, quote=False)` (no field is ever interpolated into an HTML
attribute — `news_url` is plain escaped text, never `<a href>`). Length safety uses
`_telegram_utf16_length(text) = len(text.encode("utf-16-le")) // 2` as the sole authoritative check
at every decision point — Python `len()` is never used to gate a pass/fail decision. On overflow,
only `draft_body` shrinks: a fixed-step (200-char) word-boundary truncation of the **raw** body,
re-escaped and re-rendered from scratch on every iteration, so an HTML entity can never be split.
If the card still exceeds `SAFE_LIMIT` even with `draft_body` fully exhausted, `render_editorial_card()`
raises `CardTooLongError` rather than returning an oversized string — the handler (M3) will map this
to Contract §16 Case E.

## Tests

24/24 passed, covering: per-field escaping (title, body, category, news_title, hashtags, `news_url`
including a literal `&`); `news_url` never inside `<a href>`; hashtag join/omission (`None` and `[]`
both omit the line identically); title/body placeholders for `None`; optional-field omission
(`news_url`, `news_published_at`); BMP-vs-`len()` parity; astral-character UTF-16 doubling
(`"📰"` → 2 units, `len()` → 1); the `len()<=4096`-but-`telegram_utf16_length()>4096` trap
(3000 astral emoji: `len()=3000` reports safe, `telegram_utf16_length()=6000` correctly flags
oversized, and the renderer's actual output is proven to still land `<=4096`); static-emoji
inclusion in every measurement; AI-generated-emoji counting (5 body emoji + 1 static header emoji =
+6 delta between the two measures); worst-case escaping expansion (5000 literal `&` characters);
entity-safety (every `&` in the output starts a complete, valid entity — never a dangling
fragment); untruncated-body no-op path; truncation touching only `draft_body`; the terminal
`CardTooLongError` fallback; and a general "every successful render satisfies `<=4096`" sweep
across 5 varied worst-case bodies.

## Deviation

One test assertion was corrected during implementation (`test_ai_generated_emoji_in_body_counts_correctly`
initially expected a `+5` UTF-16/`len()` delta for 5 body emoji, actual result was `+6` — the card's
own static header emoji, `📰`, is itself astral and contributes its own `+1`; the test's expected
value was fixed to `6`, not the renderer). No other change.

## Gates

- Focused pytest: `tests/test_editorial_card_formatting.py` — **24/24 passed**.
- Combined M1+M2 regression: `tests/test_editorial_inbox_service.py
  tests/test_editorial_card_formatting.py` — **34/34 passed**.
- `ruff check`: clean.
- `mypy` (targeted, `bot/formatting.py`): clean.
- `scripts.validate_architecture`: 0 violations.
- Git scope: exactly the 4 files from M1+M2 — matches Contract §23/Plan §4.

## Self-audit

No `aiogram`/`Bot`/`Message` import anywhere in `bot/formatting.py`. `len()` never gates a pass/
fail length decision. Truncation always operates on raw text. One card = one string; no
multi-message split logic exists. No Phase 5–10 file touched.

## Verdict

**M2 PASSED — CONTINUING TO M3**
