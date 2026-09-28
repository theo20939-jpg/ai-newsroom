# CONTROLLED_VISUAL_FIXTURE — NOT PRODUCTION EDITORIAL OUTPUT

Acceptance fixture for the **visual / render path only**: visual source selection → image generation → art validation → render →
Telegram review packaging. It does **not** prove that the canary-10 editorial pipeline passed (that run stopped: its one Director
correction introduced a viral-blocking `body_repeats_headline` on slide 4).

- `controlled_visual_fixture.json` — the saved canary-10 corrected Director output with **one** declared change (slide 4 body), the
  supporting evidence (E5) and the rationale. Everything else is byte-identical to the saved corrected output.
- `run/` — the controlled run (`scripts/_instagram_controlled_completion.py`): every already-paid canary-10 model call replayed from its
  saved response by exact request content; ONE live final semantic judge v5 call; live image generation (capped ledger); art validation;
  render. `run/post/slides/` are the rendered slides; `run/telegram_review_payload/` is the exact review payload (NOT sent).
- No Instagram publication. No Telegram send. Founder visual review required.
