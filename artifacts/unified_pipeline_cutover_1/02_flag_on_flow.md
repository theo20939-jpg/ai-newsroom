# Flag-on flow (`unified_editorial_pipeline_enabled = True`, real V8-family output)

The single, mutually-exclusive alternative path — never alongside the legacy tree (no shadow call,
no dual-run).

```mermaid
flowchart TD
    A[run_content_cycle per event] --> B[run_content_generation_for_event]
    B --> C{editorial_delivery_mode == router\nAND unified_editorial_pipeline_enabled\nAND is_unified_router_eligible?}
    C -- no --> LEGACY[legacy decision tree, unchanged]
    C -- yes --> D[run_unified_telegram_delivery]

    D --> E[decide_presentation for FORMAT only\n data_candidate/quote_candidate discarded]
    E --> F[build_evidence_pack]
    F --> G[_resolve_single_photo_candidate\nreuses get_editorial_image_candidates]
    G --> H[wrap as Tier-1 ResolvedMediaCandidate]
    H --> I[run_editorial_production_pipeline\nsession + RecoveryService injected]

    I --> J{structured content}
    J -->|DATA| J1[build_structured_data_content]
    J -->|QUOTE| J2[build_structured_quote_content]
    J -->|NEWS/BREAKING| J3[StructuredNewsContent]

    I --> K[MediaResearchService.research\nbounded by asyncio.wait_for]
    K -->|timeout| R1[MEDIA_RESEARCH_TIMEOUT]
    K -->|require_media and none selected\nNEWS/BREAKING/QUOTE only| R2[NO_SUITABLE_MEDIA]

    I --> L[build_composition_plan]
    L --> M[render: apply_master_news_branding NEWS\nor render_branded_media DATA/QUOTE/BREAKING]
    M -->|render callback returns None| R3[RENDER_FAILED]

    I --> N[plan_telegram_caption_budget]
    N -->|does not fit even footer-stripped| R4[CAPTION_BUDGET_FAILED]

    I --> O[run_quality_gate]
    O -->|verdict != READY| R5[QUALITY_GATE_FAILED - terminal, BLOCK]

    O -->|READY| P[DeliveryPackage]
    P --> Q{photo_input is not None?}
    Q -- yes --> Q1[send_photo_to_editorial_destination]
    Q -- no --> Q2[send_to_editorial_destination]

    Q1 --> S{RoutingOutcome}
    Q2 --> S
    S -->|sent| T[notified += 1, sent_message_id/sent_chat_id set]
    S -->|dry_run| U[dry_run_rendered += 1]
    S -->|ambiguous| R6[AMBIGUOUS_TRANSPORT_RESULT]
    S -->|failed, not ambiguous| R7[MEDIA_SEND_FAILED]

    R1 & R2 & R3 & R4 & R6 & R7 --> RS[RecoveryService.create_or_retry\nPENDING/RETRYING -> RETRY,\nTERMINAL_HOLD -> HOLD]
    R5 --> RS2[RecoveryService.create_or_retry\nmax_attempts=1 -> TERMINAL_HOLD -> BLOCK]
    RS --> V[visual_required_held += 1, no send]
    RS2 --> V

    T --> W[worker: record_delivery / cycle bookkeeping]
    U --> W
    V --> W
```

Every recovery reason code (`R1`-`R7`) is a real call site producing a durable `recovery_jobs` row
via `RecoveryService` — proven in `tests/test_unified_pipeline_cutover_authority.py`'s replay tests
(A, D, F, G, H) and `tests/test_unified_pipeline_orchestrator_cutover.py`.
