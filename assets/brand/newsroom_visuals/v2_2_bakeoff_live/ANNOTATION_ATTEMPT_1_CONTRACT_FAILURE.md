# Annotation — V2.2 attempt #1 status

`manifest.json` and `CONTACT_SHEET_V2_2.jpg` in this directory are preserved EXACTLY as produced
by the first live V2.2 run and have not been modified, deleted, or overwritten by Phase V2.2A.

**V2.2 attempt #1 was an ADAPTER CONTRACT FAILURE, not a completed model-quality bake-off.**

All 9 source/model pairs (18 total attempts including retries) failed before a usable image was
ever extracted, due to two adapter-side bugs — not model unavailability:

1. **Gemini** (6 pairs, 12 attempts: 6 original + 6 retries — see `manifest.json`'s own
   `results[].attempts`/`retried` fields, which are the source of truth for this count): the
   adapter assumed a synchronous `output_image` convenience field that the real Interactions API
   response did not contain. The real top-level response keys were `created, id, model, object,
   service_tier, status, steps, updated, usage` — an async job/`steps`-shaped object.
   - A `usage` key was present in the raw response on every one of these 12 attempts. Its
     contents (token counts, any dollar figure) were **never captured** in `manifest.json`
     because the parsing failure occurred before any extraction logic ran — `manifest.json`'s own
     `usage_input_tokens`/`usage_output_tokens`/`actual_cost_usd` fields are `null` for every
     Gemini row not because usage was absent, but because our code never got far enough to read
     it. **Billing impact for these 12 Gemini attempts is UNKNOWN — verify directly against the
     Google AI Studio / Cloud Billing console.** Do not treat the `null`/`$0` fields in the
     preserved manifest as evidence of zero cost.
2. **OpenAI** (3 pairs, 6 attempts: 3 original + 3 retries): every call was rejected in
   150ms-1.2s with `400 Bad Request: Unknown parameter: 'response_format'` — a fast
   request-validation-time rejection before generation work started. High confidence of no
   billable cost for these 6 attempts.

See `docs/phase_v2_2_live_bakeoff_report.md` (attempt #1 report, also unmodified) and
`docs/phase_v2_2a_protocol_repair_and_smoke_report.md` (this repair phase's own report) for full
detail.
