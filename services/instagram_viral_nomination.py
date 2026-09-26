"""VIRAL NOMINATION for the KAGE viral slot (founder task 2026-09-26, after the accepted viral-strength audit). Deterministic - no model call.

The accepted gate (services.instagram_viral_story_gate) could only VETO what the legacy oddity-word read had already routed to MEME_TREND,
so the strongest current event of the audit (read as weekly_news) never reached the viral slot. Here the viral product NOMINATES from the
whole fresh KAGE pool:

    fresh KAGE candidates (+ every headline of the last 72 hours for momentum)
    -> FACTUAL event groups (copies of one event = one candidate; related but distinct incidents stay apart)
    -> the accepted six-gate verdict per event, with EVENT-level actuality and momentum
    -> zero or more eligible distinct events, strongest first  (none eligible = no viral story; the slot is never filled)

Legacy MEME / oddity reads are not a prerequisite any more; nothing else about eligibility changes - every gate still has to pass.

FACTUAL EVENT IDENTITY (the narrowest layer that avoids the audit's split / false-merge errors; Story Memory is untouched). Two articles
are one event only when they share an ACTOR (OpenAI, Google, ...), an ACTION family (access / hack, delete, leak, ban, ...) and a
DISCRIMINATING detail - a place (US, Australia), a named target (Hugging Face, the SEC) or the same measured quantity (48 000 ~ 48 218
files) - and nothing contradicts that: different places, actors, or named targets with no place in common are different incidents. Shared
generic words (OpenAI, government, agents, security) never group on their own; the headline-similarity fallback needs the ratio-based
same-headline test AND >= 2 shared SPECIFIC stems AND no contradiction.

OLD VS NEW DISCLOSURE: an event's first coverage is the earliest article of ITS factual group, including older Story Memory members that
match it factually (a rewrite of the August Hugging Face breach is OLD). A related earlier incident with a different target is not this
event - it only tells what is NEWLY disclosed (the US-government targets vs the earlier Hugging Face / Australia disclosures).

EVIDENCE PREFLIGHT (`evidence_preflight`): a nominated event is strong enough for the viral slot - that does not approve any wording. Before
any paid creative generation the event's stored BODY evidence (never headlines) must support the actor, action, target(s), any quantity,
the chronology and every loaded causal / intent term the hook uses ('went rogue', 'without OpenAI knowing'). No body evidence = PENDING
(acquisition has to supply it); body evidence that does not support the hook = FAIL. Only PASS may reach the Creative Director.
Headlines are removed per SEGMENT (an aggregator glues a headline to its lede with a dash), so a claim only a headline makes stays
unproven. The worker (worker.content_cycle._viral_evidence_copy) acquires up to a few copies of the SAME event - direct publisher URLs
before aggregator redirect shells - and stops at the first PASS; the event is never swapped for a weaker one."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from services.instagram_feed_product import FeedCandidate, _clean_title, kage_core
from services.instagram_viral_story_gate import (
    CURRENT_WINDOW,
    Actuality,
    ClusterMember,
    ViralVerdict,
    _title_stems,
    assess_actuality,
    assess_inherent_strength,
    assess_viral_story,
    chronology_requirement,
    outlet_of,
    plain_text,
    same_event,
    stated_event_dates,
)


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.IGNORECASE)


# --- factual event signature ---------------------------------------------------------------------------------------------------------
_ACTORS: dict[str, re.Pattern[str]] = {
    "openai": _rx(r"\bopenai\b", r"\bchatgpt\b", r"\bsora\b", r"\bcodex\b"),
    "google": _rx(r"\bgoogle\b", r"\bgemini\b", r"\bdeepmind\b", r"\balphabet\b", r"\bandroid\b"),
    "meta": _rx(r"\bmeta\b", r"\bfacebook\b", r"\binstagram\b", r"\bwhatsapp\b"),
    "apple": _rx(r"\bapple\b", r"\biphone\b", r"\bsiri\b", r"\bipad\b", r"\bmacos\b"),
    "anthropic": _rx(r"\banthropic\b", r"\bclaude\b"),
    "microsoft": _rx(r"\bmicrosoft\b", r"\bcopilot\b", r"\bwindows\b", r"\bxbox\b"),
    "amazon": _rx(r"\bamazon\b", r"\balexa\b", r"\baws\b"),
    "deepseek": _rx(r"\bdeepseek\b"),
    "xai": _rx(r"\bxai\b", r"\bgrok\b"),
    "nvidia": _rx(r"\bnvidia\b"),
    "samsung": _rx(r"\bsamsung\b"),
    "tesla": _rx(r"\btesla\b"),
    "huawei": _rx(r"\bhuawei\b"),
    "yandex": _rx(r"\byandex\b", r"\bяндекс\w*"),
    "sber": _rx(r"\bсбер\w*", r"\bsber\w*"),
    "telegram": _rx(r"\btelegram\b", r"\bтелеграм\w*"),
    "valve": _rx(r"\bvalve\b", r"\bsteam\b"),
    "sony": _rx(r"\bsony\b", r"\bplaystation\b"),
    "nintendo": _rx(r"\bnintendo\b"),
    "tiktok": _rx(r"\btiktok\b", r"\bbytedance\b"),
}
_ACTIONS: dict[str, re.Pattern[str]] = {
    "access": _rx(r"\bhack\w*", r"\bbreach\w*", r"\baccess(ed|es|ing)?\b", r"\binfiltrat\w*", r"\bmeddl\w*", r"\bprob(e|ed|es|ing)\b",
                  r"\battack\w*", r"\btarget(ed|s|ing)?\b", r"\bengaged with\b", r"\bвзлом\w*", r"\bатак\w*", r"\bпроник\w*",
                  r"\bдоступ\w*", r"\bхакн\w*"),
    "delete": _rx(r"\bdelet\w*", r"\bwip(e|ed|es|ing)\b", r"\berase\w*", r"\bудал(ил|ила|ило|или|ит|ять|ение)\w*", r"\bсн[её]с\w*",
                  r"\bстер\b", r"\bстёр\b", r"\bстерл\w*"),
    "leak": _rx(r"\bleak\w*", r"\bexposed\b", r"\bутеч\w*", r"\bслил\w*"),
    "ban": _rx(r"\bban(s|ned|ning)?\b", r"\bblock(s|ed|ing)?\b", r"\bprohibit\w*", r"\bзапрет\w*", r"\bзаблокир\w*"),
    "outage": _rx(r"\boutage\b", r"\bdown\b", r"\bсбо[йея]\w*"),
    "launch": _rx(r"\blaunch\w*", r"\breleas\w*", r"\bunveil\w*", r"\bannounc\w*", r"\bзапуст\w*", r"\bпредстав\w*", r"\bвыпуст\w*"),
    "legal": _rx(r"\bsue[sd]?\b", r"\blawsuit\b", r"\bcourt\b", r"\bsettle\w*", r"\bиск\w*", r"\bсуд\w*"),
    "money": _rx(r"\bdeal\b", r"\bpay(s|ing)?\b", r"\bacquir\w*", r"\bbill(s|ed|ing)\b", r"\bprice\w*", r"\bсделк\w*", r"\bподорож\w*",
                 r"\bкуп(ит|ил)\w*"),
}
# places: a DISCRIMINATING anchor (the same actor + action in two countries is two incidents). US needs care: 'us' is also a pronoun.
_PLACES: dict[str, re.Pattern[str]] = {
    # case-sensitive short forms: 'us' / 'eu' are also ordinary words
    "us": re.compile(r"\bU\.S\.(?:A\.)?|\bUSA?\b|\b[Uu]nited [Ss]tates\b|\b[Aa]merica(?:n|ns)?\b|\b[Сс][Шш][Аа]\b|\b[Аа]мерикан\w*"),
    "australia": _rx(r"\baustralia\w*", r"\bавстрал\w*"),
    "uk": re.compile(r"\bUK\b|\b[Bb]ritain\b|\b[Bb]ritish\b|\b[Бб]ритан\w*|\b[Вв]еликобритан\w*"),
    "eu": re.compile(r"\bEU\b|\b[Ee]urope(?:an)?\b|\b[Ее]вросоюз\w*|\b[Ее]вроп\w*"),
    "china": _rx(r"\bchina\b", r"\bchinese\b", r"\bкита\w*"),
    "russia": _rx(r"\brussia\w*", r"\bросси\w*", r"\bрф\b"),
    "india": _rx(r"\bindia\w*", r"\bинди\w*"),
    "japan": _rx(r"\bjapan\w*", r"\bяпон\w*"),
    "korea": _rx(r"\bkorea\w*", r"\bкоре\w*"),
    "canada": _rx(r"\bcanad\w*", r"\bканад\w*"),
    "germany": _rx(r"\bgerman\w*", r"\bгерман\w*"),
    "france": _rx(r"\bfrance\b", r"\bfrench\b", r"\bфранц\w*"),
}
# named targets: a DISCRIMINATING anchor even without a place (Hugging Face is one incident, the SEC another)
_TARGETS: dict[str, re.Pattern[str]] = {
    "hugging face": _rx(r"\bhugging ?face\b"),
    "github": _rx(r"\bgithub\b"),
    "sec": re.compile(r"\bSEC\b|\b[Ss]ecurities and [Ee]xchange [Cc]ommission\b"),
    "commerce department": _rx(r"\bcommerce (department|dept)\b", r"\bdepartment of commerce\b", r"\bминторг\w*"),
    "education department": _rx(r"\beducation (department|dept|site)\b", r"\bdepartment of education\b", r"\bминпрос\w*"),
    "pentagon": _rx(r"\bpentagon\b", r"\bпентагон\w*"),
    "nasa": _rx(r"\bnasa\b"),
    "fbi": re.compile(r"\bFBI\b|\bФБР\b"),
    "white house": _rx(r"\bwhite house\b", r"\bбел(ый|ого) дом\w*"),
    "akamai": _rx(r"\bakamai\b"),
    "strava": _rx(r"\bstrava\b"),
}


_KEYCAP = re.compile("[\ufe0f\u20e3]")
_QUANTITY = re.compile(r"(?<![\d.,])\d{1,3}(?:[ \u00a0\u202f,]\d{3})+(?![\d])|(?<![\d.,])\d{3,}(?![\d])")


def magnitudes(text: str) -> frozenset[str]:
    """Quantities >= 100 at two significant digits ('48 218' and '4️⃣8️⃣ 0️⃣0️⃣0️⃣' are both '48e3'); years are not quantities."""
    out = set()
    for raw in _QUANTITY.findall(_KEYCAP.sub("", text or "")):
        value = int(re.sub(r"\D", "", raw))
        if value < 100 or 1900 <= value <= 2100:
            continue
        digits = len(str(value))
        out.add(f"{round(value / 10 ** (digits - 2))}e{digits - 2}")
    return frozenset(out)


@dataclass(frozen=True)
class EventSignature:
    actors: frozenset[str]
    actions: frozenset[str]
    places: frozenset[str]
    targets: frozenset[str]
    magnitudes: frozenset[str] = frozenset()  # the same measured quantity: a discriminating detail when no place / target is named

    @property
    def anchors(self) -> frozenset[str]:  # what discriminates one incident from a related one
        return self.places | self.targets


def event_signature(text: str) -> EventSignature:
    def found(table: dict[str, re.Pattern[str]]) -> frozenset[str]:
        return frozenset(name for name, pattern in table.items() if pattern.search(text or ""))

    return EventSignature(found(_ACTORS), found(_ACTIONS), found(_PLACES), found(_TARGETS), magnitudes(text))


# stems too generic to prove identity on their own (the founder's list: OpenAI / government / agents / security, and their kin)
_GENERIC_STEMS = {w[:5] for w in (
    "openai chatgpt google apple meta microsoft amazon anthropic government governments federal agency agencies agents agent models model "
    "security hack hacked hacking hacks website websites sites data says said reveals report reports new news update after with from into "
    "правительств правительственных агенты агентов сайты сайтов данные взлом взломать атаковали openai ии нейросеть").split()}


def contradicts(a: EventSignature, b: EventSignature) -> bool:
    """Different incidents: different places, different actors, or different named targets with no place in common."""
    if a.places and b.places and not a.places & b.places:
        return True
    if a.actors and b.actors and not a.actors & b.actors:
        return True
    return bool(a.targets and b.targets and not a.targets & b.targets and not a.places & b.places)


def same_factual_event(a_title: str, a: EventSignature, b_title: str, b: EventSignature) -> bool:
    if contradicts(a, b):
        return False
    if a.actors & b.actors and a.actions & b.actions and (a.anchors & b.anchors or a.magnitudes & b.magnitudes):
        return True
    # headline similarity alone never groups: the ratio-based same-headline test AND >= 2 shared SPECIFIC stems AND no disjoint anchors
    specific = (_title_stems(a_title) & _title_stems(b_title)) - _GENERIC_STEMS
    return (same_event(a_title, b_title) and len(specific) >= 2
            and not (a.anchors and b.anchors and not a.anchors & b.anchors))


# --- grouping ------------------------------------------------------------------------------------------------------------------------
@dataclass
class Article:
    title: str  # outlet suffix removed
    raw_title: str
    lead: str
    outlet: str
    source_name: str
    seen_at: datetime | None
    collected_at: datetime | None
    signature: EventSignature
    candidate: FeedCandidate | None = None
    evidence: str = ""


@dataclass
class EventGroup:
    seed: Article
    members: list[Article] = field(default_factory=list)

    @property
    def places(self) -> frozenset[str]:
        return frozenset().union(*(m.signature.places for m in self.members))

    @property
    def anchors(self) -> frozenset[str]:
        return frozenset().union(*(m.signature.anchors for m in self.members))

    @property
    def candidates(self) -> list[Article]:
        return [m for m in self.members if m.candidate is not None]


def _article(title: str, lead: str, source_name: str, seen_at: datetime | None, collected_at: datetime | None,
             candidate: FeedCandidate | None = None, evidence: str = "") -> Article:
    clean = _clean_title(title or "", (source_name or "").lower())
    clean = re.sub(r"\s+[-|–]\s+[^-|–]{2,60}$", "", clean) if (source_name or "").lower().startswith("google news") else clean
    lead = plain_text(lead)
    return Article(title=clean, raw_title=title or "", lead=lead, outlet=outlet_of(source_name, title), source_name=source_name or "",
                   seen_at=seen_at, collected_at=collected_at, signature=event_signature(f"{clean}. {lead[:400]}"), candidate=candidate,
                   evidence=evidence)


def group_articles(articles: list[Article]) -> list[EventGroup]:
    """Greedy, seeded (never transitive): the most specific articles seed groups; an article joins the matching group it shares most
    anchors with, and never one whose members carry a contradicting place. Unmatched articles are their own event."""
    order = sorted(articles, key=lambda a: (-len(a.signature.anchors) - len(a.signature.actors), a.candidate is None,
                                           a.seen_at or datetime.max.replace(tzinfo=UTC)))
    groups: list[EventGroup] = []
    for article in order:
        best: tuple[int, EventGroup] | None = None
        for group in groups:
            if group.places and article.signature.places and not group.places & article.signature.places:
                continue
            if not same_factual_event(group.seed.title, group.seed.signature, article.title, article.signature):
                continue
            score = len(group.anchors & article.signature.anchors)
            if best is None or score > best[0]:
                best = (score, group)
        if best is None:
            groups.append(EventGroup(seed=article, members=[article]))
        else:
            best[1].members.append(article)
    return groups


# --- nomination ----------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ViralEvent:
    key: str  # the seed headline
    verdict: ViralVerdict  # from the member whose own facts make the strongest hook, with EVENT-level actuality and momentum
    hook_candidate: FeedCandidate  # whose headline / lead gave that hook
    evidence_candidate: FeedCandidate  # the member with the most stored source material: the evidence package is built from it
    candidate_ids: tuple[str, ...]  # every fresh candidate that is a copy of this event (never competing as separate events)
    outlets: tuple[str, ...]  # distinct outlets in the last 72 hours
    first_seen: datetime | None
    members: int
    headlines: tuple[str, ...]


@dataclass(frozen=True)
class Nomination:
    events: tuple[ViralEvent, ...]  # every distinct event that has at least one fresh candidate, strongest first

    @property
    def eligible(self) -> tuple[ViralEvent, ...]:
        return tuple(e for e in self.events if e.verdict.eligible)

    @property
    def best(self) -> ViralEvent | None:  # None is a valid outcome: NO VIRAL STORY - the slot is never filled with the best of a weak batch
        return self.eligible[0] if self.eligible else None


def _history(group: EventGroup) -> list[Article]:
    """Older Story Memory members of the group's candidates that are the SAME factual event (a rewrite of an old incident is OLD);
    members that are merely related (another target, the long-lived topic) are not this event."""
    out: list[Article] = []
    for member in group.candidates:
        for m in getattr(member.candidate, "story_history", ()) or ():
            article = _article(m.title, "", m.source_name, m.seen_at, m.collected_at)
            if same_factual_event(group.seed.title, group.seed.signature, article.title, article.signature):
                out.append(article)
    return out


def _newly_disclosed(group: EventGroup, first_seen: datetime | None, related: list[tuple[EventSignature, datetime | None]]) -> tuple[str, ...]:
    """Anchors (places / named targets) this event carries that no EARLIER related incident (same actor and action) carried."""
    sig = group.seed.signature
    prior: set[str] = set()
    for other, seen in related:
        if other.actors & sig.actors and other.actions & sig.actions and seen is not None and (first_seen is None or seen < first_seen):
            prior |= other.anchors
    return tuple(sorted(group.anchors - prior))


def nominate_viral_events(candidates: list[FeedCandidate], *, headlines: list[ClusterMember] | None = None,
                          evidence: dict[str, str] | None = None, now: datetime | None = None) -> Nomination:
    """Distinct factual events among the fresh KAGE candidates, each read by the accepted gate at event level."""
    now = now or datetime.now(UTC)
    evidence = evidence or {}
    fresh = [c for c in candidates if kage_core(_clean_title(c.title or "", (c.source_name or "").lower()))]
    articles = [_article(c.title, f"{c.summary or ''}", c.source_name, c.published_at, c.published_at or now, candidate=c,
                         evidence=evidence.get(c.id, "")) for c in fresh]
    seen_titles = {(a.outlet, a.title) for a in articles}
    for h in headlines or []:
        article = _article(h.title, "", h.source_name, h.seen_at, h.collected_at)
        if (article.outlet, article.title) not in seen_titles and h.collected_at is not None and now - h.collected_at <= CURRENT_WINDOW:
            seen_titles.add((article.outlet, article.title))
            articles.append(article)
    groups = group_articles(articles)
    group_history = {id(g): _history(g) for g in groups if g.candidates}
    first_seen_of = {id(g): min((m.seen_at for m in [*g.members, *group_history.get(id(g), [])] if m.seen_at is not None), default=None)
                     for g in groups}
    related: list[tuple[EventSignature, datetime | None]] = [(g.seed.signature, first_seen_of[id(g)]) for g in groups]
    for g in groups:  # earlier Story Memory coverage of RELATED incidents (Hugging Face in August) also says what is not new
        for member in g.candidates:
            for m in getattr(member.candidate, "story_history", ()) or ():
                related.append((event_signature(m.title), m.seen_at))

    events: list[ViralEvent] = []
    for group in groups:
        members = group.candidates
        if not members:
            continue
        recent = [m for m in group.members if m.collected_at is not None and now - m.collected_at <= CURRENT_WINDOW]
        outlets = tuple(sorted({m.outlet for m in recent}))
        first_seen = first_seen_of[id(group)]
        on_hn = any(m.source_name.lower().startswith("hacker news") for m in recent)
        events_24h = len({(m.outlet, m.title) for m in recent if now - m.collected_at <= timedelta(hours=24)})  # type: ignore[operator]
        forwards = max((m.candidate.forwards or 0 for m in members if m.candidate is not None), default=0) or None
        reactions = max((m.candidate.reactions or 0 for m in members if m.candidate is not None), default=0) or None
        # EVENT-level actuality: every copy's headline and stored lead read together (one copy says 'this summer', another 'reveals')
        context = ". ".join(dict.fromkeys(f"{m.title}. {m.lead[:300]}" for m in group.members[:40]))
        published = min((m.candidate.published_at for m in members if m.candidate is not None and m.candidate.published_at), default=None)
        actuality = assess_actuality(group.seed.title, context, published_at=published, story_first_seen=first_seen,
                                     independent_sources=max(1, len(outlets)), now=now)
        if actuality.type == "CURRENT_DISCLOSURE":
            actuality = replace(actuality, newly_disclosed=_newly_disclosed(group, first_seen, related))
        verdicts = []
        for member in members:
            assert member.candidate is not None
            candidate = replace(member.candidate, story_first_seen=first_seen, independent_sources=max(1, len(outlets)),
                                story_events_24h=max(1, events_24h), on_hacker_news=on_hn, forwards=forwards, reactions=reactions)
            verdicts.append((assess_viral_story(candidate, member.evidence, now=now, actuality=actuality), member.candidate))
        # the event's verdict: the member whose own facts make the strongest grounded hook (ties: the eligible one, then the first)
        verdict, hook_candidate = max(verdicts, key=lambda vc: (vc[0].eligible, vc[0].score))
        evidence_member = max(members, key=lambda m: (len(m.evidence), len(m.lead), m.candidate is hook_candidate))
        assert evidence_member.candidate is not None
        events.append(ViralEvent(
            key=group.seed.title, verdict=verdict, hook_candidate=hook_candidate, evidence_candidate=evidence_member.candidate,
            candidate_ids=tuple(m.candidate.id for m in members if m.candidate is not None), outlets=outlets, first_seen=first_seen,
            members=len(group.members), headlines=tuple(dict.fromkeys(m.title for m in group.members))[:20]))
    events.sort(key=lambda e: (not e.verdict.eligible, tuple(-x for x in e.verdict.score)))
    return Nomination(tuple(events))


# --- evidence preflight --------------------------------------------------------------------------------------------------------------
MIN_BODY_CHARS = 400  # below this there is no article body - a headline or a feed teaser is not evidence
_LOADED: dict[str, re.Pattern[str]] = {  # causal / intent / secrecy claims a hook may make - each must be in the BODY
    "rogue": _rx(r"\brogue\b", r"\bвышл\w* из-под контроля\b"),
    "without_knowledge": _rx(r"\bwithout (\w+'s |its |their )?(knowledge|knowing|permission|authori[sz]ation)\b", r"\bбез ведома\b",
                             r"\bunauthori[sz]ed\b", r"\bнесанкционирован\w*"),
    "tried_to_hack": _rx(r"\btried to hack\b", r"\battempted to (hack|breach)\b", r"\bпытал\w* взлом\w*"),
    "secret": _rx(r"\bsecret(ly)?\b", r"\bтайно\b"),
    "deliberate": _rx(r"\bdeliberate(ly)?\b", r"\bintentional(ly)?\b", r"\bнамеренно\b"),
}
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_DASH = re.compile(r"\s+[—–]\s+")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?…])\s+(?=[A-ZА-ЯЁ«\"“])")
_ABBREVIATION = re.compile(r"(?:\b[A-Z]\.){2,}$|\b(?:Dept|Inc|Corp|Co|Mr|Ms|Mrs|Dr|St|No|vs|Jr|Sr|Gov|Sen|Rep|Gen|Lt|Col)\.$")


def _segments(text: str) -> list[str]:
    """Dash-joined parts and real sentences - never split at an abbreviation ('Commerce Dept. and SEC', 'U.S. Government')."""
    out: list[str] = []
    for part in _DASH.split(text):
        pieces: list[str] = []
        for piece in _SENTENCE_BREAK.split(part):
            if pieces and _ABBREVIATION.search(pieces[-1]):
                pieces[-1] = f"{pieces[-1]} {piece}"  # 'U.S. Government': the abbreviation did not end the sentence
            else:
                pieces.append(piece)
        out.extend(pieces)
    return [seg.strip() for seg in out if seg.strip()]


# the body shows the disclosure / discovery is NEW (a report, an admission, 'did not learn until recently')
_DISCLOSED = _rx(r"\breveal\w*", r"\bdisclos\w*", r"\breport\w*", r"\bsaid\b", r"\bsays\b", r"\btold\b", r"\badmit\w*",
                 r"\bconfirm\w*", r"\blearn(ed|t)?\b", r"\bdiscover\w*", r"\baccording to\b", r"\bраскры\w*", r"\bсообщ\w*",
                 r"\bзаяв\w*", r"\bпризна\w*", r"\bрассказ\w*", r"\bвыясн\w*")
# ... and that the behaviour itself came EARLIER than the disclosure
_EARLIER = _rx(r"\buntil recently\b", r"\bearlier\b", r"\bpreviously\b", r"\b(weeks|months) ago\b", r"\bранее\b",
               r"\bдо недавнего\b", r"\bнесколько (недель|месяцев) назад\b")
_TIME_EXPR = _rx(r"\btoday\b", r"\byesterday\b", r"\bthis (week|month|summer|spring|year)\b", r"\blast (week|month)\b", r"\bсегодня\b",
                 r"\bвчера\b", r"\bлетом\b", r"\bна этой неделе\b", r"\bв (прошлом|этом) месяце\b")


@dataclass(frozen=True)
class EvidencePreflight:
    status: str  # PASS / FAIL / PENDING
    checks: dict[str, str]  # claim -> SUPPORTED / UNSUPPORTED / NOT_USED
    reason: str


def _key(text: str) -> str:
    return " ".join(re.findall(r"[a-zа-яё0-9]+", (text or "").lower()))


def evidence_preflight(hook: str, body_lines: list[str], *, actuality: Actuality | None = None, now: datetime | None = None,
                       headlines: tuple[str, ...] | list[str] = ()) -> EvidencePreflight:
    """Can the BODY evidence carry this hook? Headlines never count as evidence: a line that is (or is inside) any headline of the event
    is dropped, so 'the headline says X' can never become 'X is proven'."""
    now = now or datetime.now(UTC)
    head_keys = [k for k in (_key(h) for h in headlines) if k]

    def is_headline(segment: str) -> bool:  # a headline, a piece of one, or a feed 'summary' that is a headline + its outlet
        key = _key(segment)
        return any(key in k or (k in key and len(key) <= len(k) + 60) for k in head_keys)

    # read per SEGMENT: an aggregator line glues a headline to its lede ('Headline — The company did not learn ...'); only the lede is
    # evidence - a claim that appears only in the headline part stays unproven
    segments = [seg for line in body_lines for seg in _segments(" ".join(plain_text(line).split()))]
    body = " ".join(dict.fromkeys(seg for seg in segments if not is_headline(seg)))
    if len(body) < MIN_BODY_CHARS:
        return EvidencePreflight("PENDING", {}, f"only {len(body)} characters of stored body evidence - the article itself must be acquired "
                                                "before any claim can be checked")
    hook_sig, body_sig = event_signature(hook), event_signature(body)
    checks: dict[str, str] = {}

    def check(name: str, used: bool, ok: bool) -> None:
        checks[name] = "NOT_USED" if not used else "SUPPORTED" if ok else "UNSUPPORTED"

    check("actor", True, bool(hook_sig.actors <= body_sig.actors and (body_sig.actors or not hook_sig.actors)))
    check("action", True, bool(hook_sig.actions & body_sig.actions) if hook_sig.actions else bool(body_sig.actions))
    check("target", bool(hook_sig.anchors), hook_sig.anchors <= body_sig.anchors)
    numbers = set(_NUMBER.findall(hook))
    check("quantity", bool(numbers), all(n in body for n in numbers))
    dated = bool(stated_event_dates(body, now=now) or _TIME_EXPR.search(body))
    if actuality is not None and actuality.type == "CURRENT_DISCLOSURE":
        # a new disclosure of an older event: the body must show BOTH that it became known now and that the behaviour came before
        dated = bool(_DISCLOSED.search(body)) and (dated or bool(_EARLIER.search(body)))
    check("chronology", True, dated)
    for name, pattern in _LOADED.items():
        check(f"claim:{name}", bool(pattern.search(hook)), bool(pattern.search(body)))
    missing = [k for k, v in checks.items() if v == "UNSUPPORTED"]
    if missing:
        return EvidencePreflight("FAIL", checks, f"the body evidence does not support: {', '.join(missing)}")
    return EvidencePreflight("PASS", checks, "every claim the hook makes is in the stored body evidence")


def viral_evidence_preflight(event: ViralEvent | None, *, title: str, body_lines: list[str], published_at: datetime | None = None,
                             now: datetime | None = None) -> EvidencePreflight:
    """The content cycle's check AFTER evidence acquisition and BEFORE Phase A / the Creative Director / images / render: the nominated
    EVENT's own hook and actuality (never re-derived from the acquired text, which would let the evidence pick an easier hook) against
    the acquired body (the package's verbatim steps / facts / limitations). Only PASS may continue; PENDING is not permission."""
    now = now or datetime.now(UTC)
    if event is None:  # a MEME_TREND entry that did not come from nomination: read it from its own evidence (still headline-free)
        body = " ".join(body_lines)
        _strength, _mechanisms, hook = assess_inherent_strength(title, body)
        actuality = assess_actuality(title, body, published_at=published_at, story_first_seen=None, independent_sources=1, now=now)
        return evidence_preflight(hook, body_lines, actuality=actuality, now=now, headlines=[title])
    return evidence_preflight(event.verdict.hook, body_lines, actuality=event.verdict.actuality, now=now,
                              headlines=[title, event.hook_candidate.title, *event.headlines])


def chronology_fact(event: ViralEvent | None) -> str | None:
    """A CURRENT_DISCLOSURE keeps its chronology downstream - the same constraint-line pattern as the package's 'SOURCE MEDIA:' line: it
    was revealed now, it did not happen now."""
    if event is None:
        return None
    actuality = event.verdict.actuality
    requirement = chronology_requirement(actuality)
    if requirement is None:
        return None
    disclosed = f"{actuality.disclosed_at:%Y-%m-%d}" if actuality.disclosed_at else "recently"
    new = f"; newly disclosed: {', '.join(actuality.newly_disclosed)}" if actuality.newly_disclosed else ""
    return f"CHRONOLOGY: disclosed {disclosed}; behaviour {actuality.underlying_time or 'earlier (date not stated)'}{new} - {requirement}"


def nominated_reads(nomination: Nomination, limit: int) -> list[tuple[FeedCandidate, Any]]:
    """The viral slot's shortlist: ONE entry per eligible distinct event (its evidence candidate), strongest first."""
    from services.instagram_feed_product import FeedFormat, FeedRead

    out = []
    for rank, event in enumerate(nomination.eligible[:limit]):
        v = event.verdict
        out.append((event.evidence_candidate, FeedRead(
            format=FeedFormat.MEME_TREND, strong=True, kinds=("viral_nomination", *v.mechanisms),
            reason=f"viral nomination: {v.reason}"[:400], rank=float(100 - rank), viral_event=event)))
    return out
