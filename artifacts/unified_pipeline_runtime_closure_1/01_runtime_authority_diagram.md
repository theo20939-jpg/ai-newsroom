# Runtime authority diagram (§44)

```
CONTENT NEED (event.title/content, copywriting_output)
    |
    v
MediaIntentBuilder            services.editorial_pipeline.media.build_visual_intent_from_evidence()
    | uses services.editorial_pipeline.subject_extraction.extract_media_subject()  [NEW, S9]
    v
CandidateDiscovery            services.editorial_pipeline.telegram_integration._resolve_photo_candidate_pool()
    | bounded pool (<=10), legacy-ranked but NOT reduced to 1        [FIXED, S8]
    | + services.media_web_discovery.discover_web_candidates() (Tier 2-4, structurally wired,
    |   NullWebDiscoveryClient by default - no real backend exists yet, S12)
    v
SubjectVerifier                services.editorial_pipeline.subject_match.classify_subject_match()
    | deterministic text-evidence classifier - the ONE classifier MediaResearchService ever
    | receives (unchanged from final-hardening-1; still the sole authority)
    v
MediaResearchService            services.editorial_pipeline.media.MediaResearchService.research()
    -> services.media_research_selection.research_and_select_media()
    -> services.media_candidate_scoring.{is_selectable, score_candidate}()
    |   is_selectable() now ALSO excludes EDITORIAL_REVIEW_REQUIRED               [FIXED, S14]
    | THE ONE AUTHORITY for final media selection - produces MediaSelectionResult
    v
MediaAssetResolver              services.editorial_pipeline.media_asset_resolver
                                 .resolve_selected_media_asset()                  [NEW, S7]
    | resolves EXACTLY media_selection.selected - file_id -> local bytes -> bounded
    | download (off by default) -> MediaResolutionFailure (never a substitute image)
    v
CompositionPlanner              services.editorial_pipeline.composition.build_composition_plan()
    | unchanged - DATA_WITH_GRAPH / DATA_WITH_SOURCE_IMAGE / DATA_TYPOGRAPHIC precedence
    v
Renderer (RenderCallable)       services.editorial_pipeline.telegram_integration._make_render_callback()
    | NOW receives media_selection directly (orchestrator's own new RenderCallable contract) -
    | no candidate/bytes closed over before MediaResearchService ran               [FIXED, S6]
    | wraps the FROZEN V8 renderers (apply_master_news_branding / render_branded_media) unchanged
    v
QualityGate                     services.editorial_pipeline.quality.run_quality_gate()
    | STRUCTURED_CONTENT_PRESENT (renamed from the falsely-named FACT_SUPPORT)     [FIXED, S20]
    | VISUAL_TRUTHFULNESS / MEDIA_PROVENANCE unchanged (MISMATCH/NOT_USABLE hard block)
    v
PlatformAdapter / Transport      services.telegram_routing.send_photo_to_editorial_destination()
    | dumb - SEND/FAIL/AMBIGUOUS only, never an editorial decision                (unchanged)
    | + a NEW final pre-transport visual assertion right before this call        [NEW, S18]
    v
RecoveryService                  services.editorial_pipeline.recovery_service.RecoveryService
    | now platform-scoped (content_draft_id, platform)                          [FIXED, S22]
    | now DB-concurrency-safe (partial unique index + IntegrityError recovery)  [FIXED, S23]
    | MEDIA_RESOLUTION_FAILED is a new, real reason code                        [NEW, S7]
RecoveryConsumer
    | NOT implemented this phase - Option B chosen explicitly and disclosed, see
    | services.editorial_pipeline.recovery_execution_policy.py                  [S24 - Option B]
```

Every arrow above is the SAME arrow the approved `feature/unified-editorial-pipeline-final-hardening-1`
lineage already drew - this phase closes gaps INSIDE stages, it does not redraw the chain.
