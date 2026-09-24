"""KAGE weekly news recap: "if I ignored tech news all week, what are the few things actually worth catching up on?"

Unit = the production Story (services/story_memory.py identity, persisted by the triage orchestrator). Coverage counts only CONFIRMED
membership - the same set `Story.event_count` and services/recap_event.py::load_story_events count (origin + STORY_UPDATE /
SUPPORTING_SOURCE / SEMANTIC_DUPLICATE; an uncertain "observability" link never inflates a story) - as UNIQUE outlets (aggregator copies
are not outlets).

Production Story Memory fragments one real event into several Stories (a RU and an EN copy rarely share a Latin entity; a follow-up
headline often scores below the update bar). A weekly recap must not show one event twice, nor rank it by one fragment's coverage, so
fragments of the same event are consolidated here with Story Memory's OWN confirmed-match rule (its scoring, thresholds, version
guard and distinctive-entity gate), applied across every confirmed headline of two fragments - never a title-similarity rule of its own.
Where a Russian copy spells a name in Cyrillic and shares no Latin entity, no deterministic evidence links it (no transliteration
guessing - the project's own fact-safety rule); such a fragment stays its own item and simply adds no coverage.

Selection: user-facing weight first (a capability, a launch, a platform change, a huge viral tech story); earnings / funding / deals /
executive moves / legal / industry-only stories are half-weighted unless the story defined the week (coverage close to the week's
top). No quotas, no fixed length: an item needs an absolute coverage floor AND a share of the week's top score; 3 to 8 items. A
story (or a premise) already used as a daily post is not repeated; a broader different event that merely touches the same theme is
a different item and may appear."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace

from database.models.news_event import EventCategory
from services.instagram_feed_product import FeedCandidate, FeedFormat, FeedRead, read_candidate, recap_category
from services.story_memory import (
    _HIGH_THRESHOLD,
    _NEAR_VERBATIM_TITLE_OVERLAP_THRESHOLD,
    ENTITY_GENERIC,
    _distinctive_shared_entities,
    _extract_entities_impl,
    _is_generic_token,
    _score_components,
    classify_entity,
    extract_story_signature,
)
from services.text_normalization import normalize_story_identity_title

CONSOLIDATION_WINDOW = timedelta(days=3)
ENTITY_DF_MAX = 6  # an entity carried by more than this many of the week's stories is a subject (OpenAI, Claude Code), not an event
MIN_COVERAGE = 4  # unique outlets, after consolidation
SHARE_OF_TOP = 0.35
DEFINING_SHARE = 0.7  # a business / exec / legal story this close to the week's top coverage defined the week
MAX_ITEMS = 8
MIN_ITEMS = 3
LOW_PRIORITY_WEIGHT = 0.5
_NUMBER = re.compile(r"\$?\d+(?:[.,]\d+)?\s?(?:%|[bmkмк]|млрд|млн|трлн|bn|gb|tb|гб)?", re.IGNORECASE)
_INDUSTRY = re.compile(r"\b(enterprise|partnership|partners with|data cent(er|re)|chips?|foundry|supply|b2b|investors?)\b|\bпартн[её]р|"
                       r"\bчип|\bцод\b|\bкорпоратив", re.IGNORECASE)
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)


@dataclass(frozen=True)
class RecapStory:
    """One production Story, reduced to what the recap needs (confirmed members only)."""
    story_id: str
    titles: tuple[str, ...]
    sources: frozenset[str]
    first_seen: datetime
    category: str = ""


@dataclass(frozen=True)
class RecapItem:
    """One event of the week: one or more Story fragments that share distinctive evidence."""
    stories: tuple[RecapStory, ...]
    evidence: tuple[str, ...] = field(default=())

    @property
    def story_ids(self) -> frozenset[str]:
        return frozenset(s.story_id for s in self.stories)

    @property
    def sources(self) -> frozenset[str]:
        return frozenset().union(*(s.sources for s in self.stories))

    @property
    def coverage(self) -> int:
        return len(self.sources)

    @property
    def titles(self) -> tuple[str, ...]:
        return tuple(t for s in self.stories for t in s.titles)

    @property
    def languages(self) -> frozenset[str]:
        return frozenset("RU" if _CYRILLIC.search(t) else "EN" for t in self.titles)

    @property
    def headline(self) -> str:
        english = [t for t in self.titles if not _CYRILLIC.search(t)]
        pool = english or list(self.titles)
        return max(pool, key=lambda t: (len(set(t.lower().split())), -len(t))) if pool else ""


def _entities(titles: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for title in titles:
        for entity in _extract_entities_impl(normalize_story_identity_title(title), aggressive=True):
            if classify_entity(entity) != ENTITY_GENERIC:
                out.add(entity)
    return out


def _numbers(titles: Iterable[str]) -> set[str]:
    out = set()
    for title in titles:
        for match in _NUMBER.finditer(title):
            token = match.group(0).lower().replace(" ", "").replace(",", ".")
            if len(token.strip("$%")) >= 2 and not re.fullmatch(r"20\d\d", token):  # a year is not an event's number
                out.add(token)
    return out


MAX_HEADLINES_PER_FRAGMENT = 6


def consolidate(stories: Sequence[RecapStory]) -> list[RecapItem]:
    """Merge Story fragments of the same event with Story Memory's OWN confirmed-match rule, applied retrospectively across all
    member headlines. At ingestion a new event is scored against a candidate Story's FIRST headline only, so a later framing of
    the same event often scores below the bar and starts its own Story. Here two fragments (within CONSOLIDATION_WINDOW) join
    when some pair of their confirmed member headlines would have been a CONFIRMED same-story match - `_score_components` combined
    >= the high threshold (or a near-verbatim title), no version conflict, and a distinctive shared entity under the production
    document-frequency gate over the week's pool. Linked transitively. No title-similarity shortcut of its own."""
    heads = [list(dict.fromkeys(s.titles))[:MAX_HEADLINES_PER_FRAGMENT] for s in stories]
    sigs = [[(t, extract_story_signature(t, _category(s.category)),
              _extract_entities_impl(normalize_story_identity_title(t), aggressive=True)) for t in hs] for s, hs in zip(stories, heads)]
    pool_entities = [{e for _, _, es in fs for e in es} for fs in sigs]
    df = Counter(e for es in pool_entities for e in es)
    pool_size = len(stories)
    tokens = [{tok for e in es for tok in _entity_tokens(e)} for es in pool_entities]
    postings: dict[str, list[int]] = {}
    for i, ts in enumerate(tokens):
        for t in ts:
            postings.setdefault(t, []).append(i)
    parent = list(range(len(stories)))
    why: dict[int, set[str]] = {i: set() for i in range(len(stories))}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(stories)):
        for j in sorted({j for t in tokens[i] for j in postings[t] if j < i and len(postings[t]) <= MAX_TOKEN_POSTINGS}):
            if find(i) == find(j) or abs(stories[i].first_seen - stories[j].first_seen) > CONSOLIDATION_WINDOW:
                continue
            shared = _confirmed_pair(sigs[i], sigs[j], _category(stories[j].category), df, pool_size)
            if shared:
                root_i, root_j = find(i), find(j)
                parent[root_i] = root_j
                why[root_j] |= why.pop(root_i, set()) | shared
    groups: dict[int, list[int]] = {}
    for i in range(len(stories)):
        groups.setdefault(find(i), []).append(i)
    return [RecapItem(stories=tuple(stories[i] for i in members), evidence=tuple(sorted(why.get(root, set()))))
            for root, members in groups.items()]


MAX_TOKEN_POSTINGS = 40  # a token carried by more fragments than this (OpenAI, Google) never pairs fragments on its own


def _entity_tokens(entity: str) -> set[str]:
    return {t for t in re.split(r"[\s/]+", entity) if len(t) >= 3 and not _is_generic_token(t)}


def _category(value: str):
    try:
        return EventCategory(value or "UNKNOWN")
    except ValueError:
        return EventCategory.UNKNOWN


def _confirmed_pair(a, b, category_b, df, pool_size) -> set[str]:
    """The shared distinctive entities if any headline pair of the two fragments is a confirmed same-story match; else empty."""
    for title_a, sig_a, ents_a in a:
        for title_b, sig_b, ents_b in b:
            candidate = SimpleNamespace(category=category_b, topic_bucket=sig_b.topic_bucket)
            combined, _eo, title_overlap, ev = _score_components(title_a, sig_a, category_b, title_b, candidate)
            if ev.version_incompatible:
                continue
            if combined < _HIGH_THRESHOLD and title_overlap < _NEAR_VERBATIM_TITLE_OVERLAP_THRESHOLD:
                continue  # the precise band only: a looser band chains unrelated fragments (measured on the real 5-11 Aug week)
            distinctive = _distinctive_shared_entities(ents_a, ents_b, df, pool_size)
            if distinctive:
                return set(distinctive)
    return set()


@dataclass(frozen=True)
class RecapPick:
    item: RecapItem
    read: FeedRead
    category: str
    score: float
    why: str
    used_daily: bool = False
    repeat_justification: str | None = None


def _item_read(item: RecapItem) -> tuple[FeedCandidate, FeedRead]:
    candidate = FeedCandidate(id=sorted(item.story_ids)[0], title=item.headline, category=item.stories[0].category, coverage=item.coverage)
    return candidate, read_candidate(candidate)


def _low_priority(item: RecapItem, read: FeedRead) -> bool:
    votes = sum(1 for t in item.titles if "business" in read_candidate(FeedCandidate(id="t", title=t)).kinds or _INDUSTRY.search(t))
    return votes * 2 >= len(item.titles) or "business" in read.kinds


def select_weekly_recap_items(
    items: Sequence[RecapItem], *, daily_story_ids: Iterable[str] = (), daily_titles: Iterable[str] = (),
) -> list[RecapPick]:
    """The week's recap: what defined the week for someone who ignored tech news. [] when fewer than MIN_ITEMS deserve it."""
    daily_ids = set(daily_story_ids)
    daily_entities = [(_entities([t]) , t) for t in daily_titles]
    scored: list[RecapPick] = []
    for item in items:
        candidate, read = _item_read(item)
        if read.format is FeedFormat.REJECT:
            continue
        category = recap_category(candidate, read)
        if category == "OTHER":
            continue
        if item.story_ids & daily_ids:
            continue  # this very story was a daily post
        item_entities = {e for e in _entities(item.titles) if classify_entity(e) == "distinctive"}
        if any(item_entities & (ents - {""}) for ents, _ in daily_entities):
            continue  # the same premise as a daily post (shares its distinctive entity) - not repeated
        low = _low_priority(item, read)
        score = item.coverage * (LOW_PRIORITY_WEIGHT if low else 1.0)
        scored.append(RecapPick(item, read, category, score, "", False, None))
    if not scored:
        return []
    top_coverage = max(p.item.coverage for p in scored)
    # a low-priority story that defined the week gets its full weight back
    scored = [RecapPick(p.item, p.read, p.category, float(p.item.coverage) if p.item.coverage >= DEFINING_SHARE * top_coverage else p.score,
                        "", False, None) for p in scored]
    top = max(p.score for p in scored)
    kept = [p for p in scored if p.item.coverage >= MIN_COVERAGE and p.score >= SHARE_OF_TOP * top]
    kept.sort(key=lambda p: (-p.score, -p.item.coverage))
    kept = kept[:MAX_ITEMS]
    out = []
    for p in kept:
        low = _low_priority(p.item, p.read)
        langs = "+".join(sorted(p.item.languages))
        why = (f"{p.category}: carried by {p.item.coverage} outlets ({langs}, {len(p.item.stories)} story fragment(s))"
               + ("; a business / industry story, kept because it defined the week" if low else "; user-facing"))
        out.append(RecapPick(p.item, p.read, p.category, p.score, why))
    return out if len(out) >= MIN_ITEMS else []
