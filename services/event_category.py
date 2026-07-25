"""Deterministic NewsEvent.category assignment from a source's own config-level tags
(Phase 15 M2 - docs/phase15_m2_category_reliability_report.md).

Root cause fixed: services/collector.py used to assign EventCategory.UNKNOWN
unconditionally to every NewsEvent (Phase 9 decision, Phase 15 M0 discovery §3). No
capability anywhere in NEWS_ANALYSIS or CONTENT_GENERATION produces a category/topic/
classification field (confirmed by inspection of every capability's output_schema:
research={facts, confidence, gaps}, intelligence={significance, angle, audience_relevance,
recommendation}, engagement={engagement_potential_score, audience_fit, reasoning},
scoring={score, rationale}) - so per the Phase 15 M2 task's priority order, there is
no existing structured AI classification (Priority A/B) to reuse.

What IS already available, deterministically, with zero new calls: every
`schemas.source_definition.SourceDefinition` the Collector loads each cycle carries a
`tags: list[str]` field, authored once per source in `config/newsroom_sources_v1/sources/
*.yaml` and already threaded through to `services.collector._process_source` via
`AdapterResolution.definition` (`services/adapter_registry.py`) - simply never read for
anything besides `SourceFetchContext`. This module is the single centralized mapping from
that already-loaded tag vocabulary to the existing `EventCategory` enum (Priority C: a
deterministic source heuristic, not a new taxonomy, not free-text keyword matching against
article content).

Priority order below is deliberate: narrower/more specific categories are checked before
the broad `AI` bucket, because the vast majority of this source pack's entries carry an
"ai" tag (this is an AI newsroom) - if `AI` were checked first, nearly everything would
resolve to AI regardless of a more specific signal being present, which is exactly the
"everything = AI" fallback the M2 contract forbids. `TECH` is checked last as the most
generic non-UNKNOWN bucket. A source/event with no recognizable tag stays `UNKNOWN` -
correct-but-unclassified is preferred over a wrong guess.
"""
from database.models.news_event import EventCategory

_CATEGORY_TAG_PRIORITY: list[tuple[EventCategory, frozenset[str]]] = [
    (EventCategory.CYBERSECURITY, frozenset({"security", "cybersecurity"})),
    (
        EventCategory.GADGETS,
        frozenset({"gadgets", "consumer-tech", "mobile", "android", "wearables"}),
    ),
    (EventCategory.HARDWARE, frozenset({"hardware", "gpu", "chips", "datacenter"})),
    (EventCategory.STARTUPS, frozenset({"startup", "business", "funding", "enterprise"})),
    (
        EventCategory.SOFTWARE,
        frozenset(
            {
                "programming",
                "coding",
                "open-source",
                "code",
                "framework",
                "ide",
                "developers",
                "api",
                "web",
                "browser",
            }
        ),
    ),
    (
        EventCategory.AI,
        frozenset(
            {
                "ai",
                "artificial-intelligence",
                "llm",
                "machine-learning",
                "ml",
                "agents",
                "nlp",
                "rag",
                "computer-vision",
                "image-generation",
                "video-generation",
                "chatgpt",
                "claude",
                "gemini",
                "local-llm",
                "inference",
                "models",
                "mcp",
                "safety",
                "robotics",
                "voice",
                "audio",
            }
        ),
    ),
    (
        EventCategory.TECH,
        frozenset(
            {
                "technology",
                "tech",
                "gaming",
                "video",
                "internet",
                "future",
                "trends",
                "society",
                "culture",
                "global",
                "news",
                "viral",
                "memes",
                "product",
                "search",
                "search-trends",
                "aggregation",
            }
        ),
    ),
]


def _normalize_tag(tag: str) -> str:
    """Case/format normalization only - never invents or corrects a tag's meaning."""
    return tag.strip().lower().replace("_", "-").replace(" ", "-")


def categorize_from_tags(tags: list[str] | None) -> EventCategory:
    """Map a source's config-level tags to the existing EventCategory enum, deterministically.

    Checked in `_CATEGORY_TAG_PRIORITY` order; the first bucket with at least one matching
    tag wins. No tags, or no tag matching any bucket, returns UNKNOWN - never a guessed
    default.
    """
    if not tags:
        return EventCategory.UNKNOWN

    normalized = {_normalize_tag(tag) for tag in tags}
    for category, bucket_tags in _CATEGORY_TAG_PRIORITY:
        if normalized & bucket_tags:
            return category

    return EventCategory.UNKNOWN
