"""Article-level topic taxonomy - Phase 17 M2 (docs/phase17_m2_channel_topic_relevance_shadow_report.md).

Deliberately separate from `database.models.news_event.EventCategory` (M0 §9/§10's own finding:
`EventCategory` is assigned once, deterministically, from the *source's* static config tags -
never from an individual article's actual content). `ArticleTopic` is the article-level signal
`EventCategory` was never designed to be; the two are compared, never merged, by
`schemas.article_relevance.ArticleTopicAssessment.category_match`.

A small, curated, closed taxonomy (M2's own explicit instruction: cover this project's real
sources without becoming a universal ontology) - adding a topic here is a deliberate, reviewed
change, not something a classifier can invent.
"""
from enum import Enum


class ArticleTopic(str, Enum):
    """Tech-relevant topics (candidates for a technology-focused channel's primary/secondary/
    allowed-adjacent lists) first, then non-tech topics a technology channel would typically
    exclude, then the two fallbacks."""

    AI = "AI"
    GADGETS = "GADGETS"
    CONSUMER_TECH = "CONSUMER_TECH"
    SOFTWARE = "SOFTWARE"
    BIG_TECH = "BIG_TECH"
    CHIPS = "CHIPS"
    CYBERSECURITY = "CYBERSECURITY"
    GAMING_TECH = "GAMING_TECH"
    SCIENCE_TECH = "SCIENCE_TECH"
    BUSINESS_TECH = "BUSINESS_TECH"
    REGULATION_TECH = "REGULATION_TECH"

    ENTERTAINMENT = "ENTERTAINMENT"
    GAMING_CONTENT = "GAMING_CONTENT"
    POLITICS = "POLITICS"
    SPORTS = "SPORTS"
    LIFESTYLE = "LIFESTYLE"
    CRIME = "CRIME"

    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


# Topics that are, by construction, never a technology channel's primary subject matter - used by
# the classifier to identify a "dominant excluded topic" (services/channel_relevance.py). Kept
# here, next to the enum, rather than duplicated per-channel-profile, since this split is a
# property of the taxonomy itself, not of any one channel's editorial policy.
NON_TECH_TOPICS: frozenset[ArticleTopic] = frozenset({
    ArticleTopic.ENTERTAINMENT, ArticleTopic.GAMING_CONTENT, ArticleTopic.POLITICS,
    ArticleTopic.SPORTS, ArticleTopic.LIFESTYLE, ArticleTopic.CRIME,
})

TECH_TOPICS: frozenset[ArticleTopic] = frozenset({
    ArticleTopic.AI, ArticleTopic.GADGETS, ArticleTopic.CONSUMER_TECH, ArticleTopic.SOFTWARE,
    ArticleTopic.BIG_TECH, ArticleTopic.CHIPS, ArticleTopic.CYBERSECURITY,
    ArticleTopic.GAMING_TECH, ArticleTopic.SCIENCE_TECH, ArticleTopic.BUSINESS_TECH,
    ArticleTopic.REGULATION_TECH,
})
