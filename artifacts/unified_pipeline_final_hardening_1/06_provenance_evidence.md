# Provenance Evidence (§7)

`services/editorial_pipeline/subject_match.py::classify_subject_match()` never discards or
overwrites the candidate's own existing provenance — it only READS `candidate.provenance.
caption_or_alt` and returns a new `SubjectMatchValidation`, which itself already carries the
required provenance-adjacent fields (all pre-existing schema fields, none added by this phase):

| Field | Source | Retained? |
|---|---|---|
| Source URL | `ResolvedMediaCandidate.provenance.origin_url`/`asset_url` | Unchanged — this module never touches `provenance` itself, only reads `caption_or_alt` from it |
| Originating article/source | `provenance.origin_url`, `provenance.publisher_domain` | Unchanged |
| Official/editorial/contextual origin | `provenance.discovery_tier` (`TIER1_CURRENT_SOURCE` ... `TIER5_SAFE_FALLBACK`) | Unchanged |
| Candidate identity | `ResolvedMediaCandidate.candidate_id` | Unchanged |
| Match classification | `SubjectMatchValidation.subject_match` (`EXACT_SUBJECT`/`STRONG_CONTEXT`/`GENERIC_CONTEXT`/`MISMATCH`) | **New, real value** — this is what this phase adds |
| Reason/evidence for classification | `SubjectMatchValidation.reason` (always set, human-readable, cites the exact matched term(s) or explains why no evidence was found) | **New, real value** |
| Final selection reason | `MediaSelectionResult.rejection_reasons`/`notes` (unmodified `services/media_research_selection.py` logic, now fed real classifications) | Unchanged mechanism, now populated with real, meaningful entries (e.g. `"candidate-a-ordinary-iphone: subject_match=mismatch (...)"`, proven in the foldable iPhone replay test) |

## No large payloads, no credentials

`SubjectMatchValidation.depicted_subject_description` is bounded (`raw_text[:500]`, matching the
schema's own `max_length=500` field constraint). `reason` is a short, templated string citing only
matched term names, never the full candidate text verbatim beyond what the description field
already bounds. No credential, token, or secret of any kind is read, logged, or returned anywhere
in `classify_subject_match()` — it touches only `MediaIntent` (story-editorial identity fields) and
`ResolvedMediaCandidate.provenance.caption_or_alt` (public-facing descriptive text already resolved
by earlier, unmodified discovery code).
