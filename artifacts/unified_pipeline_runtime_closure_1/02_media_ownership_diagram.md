# Media ownership diagram (§44)

| Stage | Owner (module/function) | Owns | Does NOT own |
|---|---|---|---|
| MediaIntentBuilder | `media.build_visual_intent_from_evidence` + `subject_extraction.extract_media_subject` | what visual truth is required | candidate discovery, selection |
| MediaDiscovery | `telegram_integration._resolve_photo_candidate_pool` + `media_web_discovery.discover_web_candidates` | finding a bounded candidate pool | ranking, subject truth, final choice |
| SubjectVerifier | `subject_match.classify_subject_match` | EXACT/STRONG/GENERIC/MISMATCH per candidate | scoring, selection |
| MediaResearchService | `media.MediaResearchService` / `media_research_selection.research_and_select_media` / `media_candidate_scoring` | **final candidate selection - the ONE authority** | resolving bytes, rendering |
| MediaAssetResolver | `media_asset_resolver.resolve_selected_media_asset` | resolving the exact selected candidate's bytes/file_id | choosing a *different* candidate if resolution fails (never does) |
| CompositionPlanner | `composition.build_composition_plan` | truthful composition strategy | rendering pixels |
| Renderer | `telegram_integration._make_render_callback` (wraps frozen V8 renderers) | layout/typography/crop/brand treatment | media truthfulness, selection |
| QualityGate | `quality.run_quality_gate` | validating the actual output | overriding a HOLD/BLOCK |
| PlatformAdapter/Transport | `telegram_routing.send_*_to_editorial_destination` | SEND/FAIL/AMBIGUOUS reporting | any editorial fallback decision |
| RecoveryService | `recovery_service.RecoveryService` | durable, platform-scoped, concurrency-safe lifecycle state | executing retries (Option B - see `recovery_execution_policy.py`) |

**ONE MEDIA AUTHORITY (§3.4) is preserved and strengthened**: `MediaResearchService` is the only
place a final candidate is chosen. `_resolve_photo_candidate_pool` (legacy pre-ranking) supplies
candidates only; it no longer determines the winner by truncating the pool to one before
verification runs (the Founder audit's gap D).
