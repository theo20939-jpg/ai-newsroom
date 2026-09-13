# KNOWN_SAFE_LIMITATION_DATA_TYPOGRAPHIC_FALLBACK (§16)

Explicitly NOT addressed by this phase, per the Founder's own instruction: "Do NOT modify Telegram
V8 solely to solve the current DATA typographic fallback limitation."

## The limitation (unchanged since the prior cutover phase's own report §Q3)

The real, unmodified V8 renderer (`services/brand_renderer.py::render_branded_media()`) has no
typographic-only DATA rendering path — its DATA branch raises `ValueError("DATA presentation
requested with no source_image_bytes")` when no photo is available, even though
`services/editorial_pipeline/composition.py`'s own `DataCompositionStrategy.DATA_TYPOGRAPHIC`
strategy exists as a real, distinct, tested code path in the shared editorial pipeline.

## Current, reviewed, safe behavior

A DATA event with no resolvable photo and no real series reaches `RENDER_FAILED` — a real, bounded,
reason-coded `RecoveryJob` (`TERMINAL_HOLD` after `max_attempts`, per the normal bounded-retry
schedule this reason code already had before this hardening phase, unchanged) — never a silent
text-only send, never a fabricated visual.

## Status

`KNOWN_SAFE_LIMITATION_DATA_TYPOGRAPHIC_FALLBACK`
**Severity: MEDIUM / NON-BLOCKING.**

Not hidden: this exact limitation is disclosed in the prior cutover report (§Q3), the founder
review bundle (§08_STRUCTURED_DATA_AUDIT.md, §16_FOUNDER_RISK_TABLE.md), and again here. No code
change was made to `services/brand_renderer.py`, `services/editorial_pipeline/composition.py`, or
any other DATA-rendering-related file in this phase (confirmed zero-diff against `9e73053...` for
all of them). A future, separately-scoped phase may address it by either building a real
typographic DATA card in V8 (a Founder-approved V8 change) or by leaving the current safe HOLD
behavior as the permanent, intentional design.
