# NINJA PULSE Account Presentation Spec

DIRECTOR-CONTROL-PLANE-1 §19/§44 - account-level (not per-post) presentation requirements for the
Strategy/Creative/Visual Directors. Only states what real project evidence (assets/ + Founder
Directives + SocialLaunchContext) actually supports - everything else is explicitly marked
NEEDS_FOUNDER_INPUT rather than fabricated (spec §44's own explicit instruction).

## Telegram - NINJA PULSE

| Field | Value | Source |
|---|---|---|
| Channel name | NEEDS_FOUNDER_INPUT | No `TelegramSurface` row is registered yet (spec §0's own "No public NINJA PULSE surface is registered yet") - the real name is whatever the Founder registers via the existing `/surface` confirmation flow. |
| Description/bio | NEEDS_FOUNDER_INPUT | Same as above - not yet configured. |
| Avatar | NEEDS_FOUNDER_INPUT | No avatar reference asset found under `assets/brand/` for a channel avatar specifically (only the NNJ logo/mark assets, which are brand-mark references, not a channel-avatar composition). |
| Pinned post role | NEEDS_FOUNDER_INPUT | No project evidence states what the pinned message should contain. |
| Feed visual rhythm | Derivable once live: `services/telegram_feed_state.py::compute_feed_state()` already computes topic/entity/source streaks and presentation_mix from real channel history - this becomes real evidence once posts exist. |
| Content categories | Founder Directive infrastructure (`database/models/strategic_directive.py`) is the intended real source (see services/director_editorial_gate.py's own module docstring for the exact operational next step: create one real StrategicDirective row) - none exists yet in this environment. |
| Posting presentation | Governed today by `services/presentation_director.py` + the locked MASTER NEWS/DATA/BREAKING/QUOTE contracts (design/reference_manifest.md) - already real and enforced. |

## Instagram - NINJA PULSE

| Field | Value | Source |
|---|---|---|
| Username/display name | NEEDS_FOUNDER_INPUT | No `InstagramAccount` row registered yet (spec §0's own "Instagram account runtime is not yet connected"). |
| Bio | NEEDS_FOUNDER_INPUT | No project asset or directive states an Instagram bio. |
| Avatar | NEEDS_FOUNDER_INPUT | No Instagram-specific avatar asset found (design/reference_manifest.md's own REFERENCE_MISSING rows). |
| Profile positioning | NEEDS_FOUNDER_INPUT | No Instagram launch context has been proposed yet (`SocialLaunchContext` for platform=instagram has no rows in this environment). |
| Grid/feed visual direction | REFERENCE_MISSING - design/reference_manifest.md confirms no Instagram REEL/CAROUSEL/SINGLE reference asset exists anywhere in this project. |
| Reel cover direction | REFERENCE_MISSING |
| Carousel system | REFERENCE_MISSING |
| Recurring series | Real infrastructure exists (`database/models/instagram_series_memory.py`, `services/instagram_series.py`) but no real series has been proposed/approved yet in this environment. |

## Operational next steps to close the NEEDS_FOUNDER_INPUT rows above

1. Register the real NINJA PULSE Telegram surface (existing `/surface` confirmation flow -
   `services/telegram_surface_proposal_service.py`).
2. Create one real `StrategicDirective` row expressing the content-category preference from this
   phase's own spec §11 (AI/gadgets primary, finance rare unless major) - see
   `services/director_editorial_gate.py`'s own module docstring for why this was deliberately not
   hardcoded.
3. Connect the Instagram Graph API (`services/instagram_graph_adapter.py`'s own `is_configured()`
   gate - requires real `INSTAGRAM_ACCESS_TOKEN`/`INSTAGRAM_BUSINESS_ACCOUNT_ID` env values, never
   fabricated here) and register the account via `services/instagram_account_registry.py::
   create_account()`.
4. Supply or commission real Instagram-specific design reference assets (Reel cover, carousel,
   single-post grid direction) - none currently exist in this project.
