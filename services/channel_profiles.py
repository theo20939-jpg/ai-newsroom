"""Concrete ChannelProfile instances - Phase 17 M2. Data only, never imported by anything that
would treat it as classifier logic (`services/channel_relevance.py` reads these, never the
reverse).

The AI/Gadgets profile below is calibrated against this project's real, existing category
vocabulary - `services/event_category.py::_CATEGORY_TAG_PRIORITY` (the only other place this
codebase already encodes an editorial topic policy) - and Phase 17 M0's own manual-audit findings
(docs/phase17_m0_output_quality_discovery_report.md §11/§12), not invented from scratch:
`primary_topics` roughly mirrors the AI/GADGETS/SOFTWARE/HARDWARE(->CHIPS)/CYBERSECURITY buckets
already live in `EventCategory`; `allowed_adjacent_topics` mirrors the STARTUPS bucket
(business/funding); `excluded_topics` covers exactly M0's own Netflix/Walking Dead regression
case (ENTERTAINMENT) plus the other non-tech categories this taxonomy defines.
"""
from schemas.channel_profile import ChannelProfile
from schemas.topic_taxonomy import ArticleTopic

AI_GADGETS_CHANNEL_PROFILE = ChannelProfile(
    profile_id="ai_gadgets_channel",
    schema_version="v1",
    display_name="AI & Gadgets",
    primary_topics=[
        ArticleTopic.AI, ArticleTopic.GADGETS, ArticleTopic.CONSUMER_TECH,
        ArticleTopic.SOFTWARE, ArticleTopic.CHIPS,
    ],
    secondary_topics=[
        ArticleTopic.BIG_TECH, ArticleTopic.CYBERSECURITY, ArticleTopic.SCIENCE_TECH,
    ],
    allowed_adjacent_topics=[
        ArticleTopic.BUSINESS_TECH, ArticleTopic.REGULATION_TECH,
    ],
    excluded_topics=[
        ArticleTopic.ENTERTAINMENT, ArticleTopic.POLITICS, ArticleTopic.SPORTS,
        ArticleTopic.LIFESTYLE, ArticleTopic.CRIME,
    ],
    conditional_topics=[
        ArticleTopic.GAMING_TECH, ArticleTopic.GAMING_CONTENT,
    ],
    required_relationships=[
        # Recognized by services/channel_relevance.py::assess_channel_fit() - a conditional
        # topic (e.g. GAMING_CONTENT) is only ACCEPT-eligible when a primary/secondary tech
        # topic's evidence also co-occurs (the "gaming hardware, if it relates to gadgets/tech"
        # example from this milestone's own task brief) - never on its own.
        "conditional_topic_requires_tech_centrality",
        # A dominant excluded-topic match can only be overridden into ACCEPT/REVIEW (rather than
        # REJECT) when a primary/secondary tech topic's evidence is independently strong (not
        # merely NewsEvent.category being tech-inherited) - the exact Netflix/Walking Dead
        # discipline (M0 §12): source category alone is never sufficient evidence of fit.
        "excluded_topic_requires_independent_tech_evidence_to_avoid_reject",
    ],
    language="ru",
    audience="tech-interested general readers (AI, gadgets, consumer technology)",
    editorial_notes=(
        "Primary/secondary/allowed-adjacent topics mirror this project's own EventCategory "
        "buckets (AI, GADGETS, SOFTWARE, HARDWARE->CHIPS, CYBERSECURITY, STARTUPS->BUSINESS_TECH) "
        "- see services/event_category.py. Excluded topics cover the Netflix/Walking Dead "
        "regression case (docs/phase17_m0_output_quality_discovery_report.md §12) and the other "
        "clearly non-tech categories this taxonomy defines."
    ),
)

# Keyed by profile_id - the only lookup services/channel_relevance.py needs. A single entry today
# (this project has one live channel); adding a second channel later is a data-only addition here,
# never a classifier-logic change.
CHANNEL_PROFILES: dict[str, ChannelProfile] = {
    AI_GADGETS_CHANNEL_PROFILE.profile_id: AI_GADGETS_CHANNEL_PROFILE,
}

DEFAULT_CHANNEL_PROFILE_ID = AI_GADGETS_CHANNEL_PROFILE.profile_id
