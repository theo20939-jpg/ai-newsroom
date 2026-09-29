"""VIRAL STORY STRENGTH + ACTUALITY gate for the KAGE viral slot (founder task 2026-09-26). Deterministic - no model call.

KAGE viral content is a genuinely strong CURRENT tech / AI / gadget / gaming / platform story whose facts are already shareable - not
"the most viral-looking item available", not "the best story we can turn into a carousel". The creative layer amplifies a strong story;
it never manufactures virality for a weak one.

Six criteria, read IN ORDER; the first failure decides, and a later criterion never rescues an earlier one (visual potential is recorded,
never a gate):
  1. KAGE CORE RELEVANCE     - the accepted KAGE-first rule (services.instagram_feed_product.kage_core), unchanged;
  2. EVENT ACTUALITY         - the age of the EVENT, not of the article (actuality_type):
                               CURRENT_EVENT      - it happened now: a stated date / explicit time expression within 72 hours, or
                                                    independent corroboration inside 72 hours;
                               CURRENT_DISCLOSURE - the behaviour happened earlier ('this summer', 'in May') but a disclosure of it is
                                                    new: a disclosure verb, the stated behaviour date is not the disclosure's own date,
                                                    and nothing covered this same FACTUAL event before. Any hook must keep the
                                                    chronology (it was revealed now - it did not happen now);
                               RECENT_EVENT       - 3-7 days old: not current, fails the viral slot (still good KAGE news) and momentum
                                                    cannot lift it back;
                               OLD_EVENT          - a retrospective / resurfacing cue, a stated date older than 7 days with no new
                                                    disclosure, or this same factual event already covered more than 7 days ago (a
                                                    rewrite of an old incident; a related EARLIER incident is not this one -
                                                    services.instagram_viral_nomination groups by factual identity);
                               UNCERTAIN          - no date stated: the article timestamp is never assumed to be the event's; it must be
                                                    resolved by corroboration at the momentum step;
  3. BROAD INTEREST          - understandable from one sentence without following a niche: specialist / niche markers (mods, patches,
                               repositories, APIs, rendering techniques, ...) need a real-world consequence; otherwise the story needs an
                               everyday-life, mass-product or security/AI-behaviour anchor;
  4. INHERENT VIRAL STRENGTH - the strongest factual one-sentence hook (title or the first lead sentences, with distribution words such as
                               viral / meme / trend removed) must itself carry a mechanism: absurd measurable outcome, contradiction,
                               unexpected AI behaviour, real failure, consumer consequence, surprising security incident, bizarre
                               product behaviour, human-vs-technology conflict, controversy. Words that only name an actor (modder,
                               enthusiast) or say how a story spread are never a mechanism;
  5. CURRENT MOMENTUM        - a band (NONE / WEAK / MODERATE / STRONG) from signals that exist in production data only: distinct outlets
                               of this same factual event (services.instagram_viral_nomination; cluster_signals for a lone candidate)
                               in the last 72 hours, its growth in the last 24 hours, Hacker News front-page presence, Telegram forwards
                               / reactions (Telegram sources only). A long-lived Story Memory topic's age and old sources are not this
                               event's. Momentum SUPPORTS and never rescues a failed gate 1-4 (a MODERATE, one-mechanism story stays
                               ordinary news however many outlets carry it); no outlet count is a threshold. A strong story with no
                               momentum still qualifies when its TEXT dates it as current (an event, or a disclosure dated in the
                               text); an UNCERTAIN date, or a disclosure whose novelty rests only on one outlet's publication time,
                               needs at least one corroborating outlet - a single article can be delayed coverage;
  6. VISUAL / CREATIVE POTENTIAL - recorded for ordering only.
When nothing clears the bar, the viral slot stays EMPTY (no best-of-a-weak-batch)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from services.instagram_feed_product import _DISTRIBUTION, _clean_title, kage_core

CURRENT_WINDOW = timedelta(hours=72)
OLD_CLUSTER_AGE = timedelta(days=7)


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.IGNORECASE)


_TAG = re.compile(r"<[^>]*>")
_URL = re.compile(r"https?://\S+|www\.\S+")
_ENTITY = re.compile(r"&(#\d+|[a-z]+);", re.IGNORECASE)


def plain_text(text: str) -> str:
    """Stored summaries can be raw feed HTML (Techmeme, MacRumors): tags, attributes and URLs carry numbers and dates of their own
    (hspace="4", /2026/09/25/) that are not the story's - they are removed before any reading."""
    return " ".join(_ENTITY.sub(" ", _URL.sub(" ", _TAG.sub(" ", text or ""))).split())


# --- 2. actuality --------------------------------------------------------------------------------------------------------------------
_OLD_CUES = _rx(
    r"\b\d+\s+(years?|months?)\s+ago\b", r"\b\d+\s+(лет|года|год|месяц\w*)\s+назад\b", r"\bback in (19|20)\d\d\b",
    r"\bresurfac\w*", r"\bold (video|clip|post|tweet|story)\b", r"\bвновь (всплыл|завирус)\w*", r"\bстар(ое|ый|ая) (видео|ролик|пост)\b",
    r"\bвтор(ую|ой) жизн\w*", r"\bretrospective\b", r"\blook(ing)? back\b", r"\bremember when\b", r"\banniversary\b", r"\bгодовщин\w*",
    r"\bретроспектив\w*",
)
_RECENT_CUES = _rx(
    r"\btoday\b", r"\byesterday\b", r"\bthis (week|morning)\b", r"\btonight\b", r"\bon (monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    r"\bjust (announced|launched|released|revealed)\b", r"\bсегодня\b", r"\bвчера\b", r"\bна этой неделе\b", r"\bтолько что\b",
    r"\bв (понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\b",
)  # time expressions only - a development ("launches investigation") is not a date
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
           "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10,
           "ноябр": 11, "декабр": 12}
_MONTH_WORD = (r"(январ[яье]|феврал[яье]|март[ае]?|апрел[яье]|ма[яйе]|июн[яье]|июл[яье]|август[ае]?|сентябр[яье]|октябр[яье]|ноябр[яье]|декабр[яье]|"
               r"january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|"
               r"oct|nov|dec)")
_DAY_MONTH = re.compile(rf"\b(\d{{1,2}})\s+{_MONTH_WORD}\.?(?:\s+((?:19|20)\d\d))?\b", re.IGNORECASE)  # 30 июля, 30 July 2026
_MONTH_DAY = re.compile(rf"\b{_MONTH_WORD}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+((?:19|20)\d\d))?", re.IGNORECASE)  # July 30, 2026
_IN_MONTH = re.compile(rf"\b(?:в|in)\s+{_MONTH_WORD}\b(?:\s+((?:19|20)\d\d))?", re.IGNORECASE)  # в мае 2026 года, in August


def _month_of(word: str) -> int | None:
    word = word.lower()
    for prefix, month in sorted(_MONTHS.items(), key=lambda kv: -len(kv[0])):
        if word.startswith(prefix):
            return month
    return None


def stated_event_dates(text: str, *, now: datetime) -> list[tuple[datetime, str]]:
    """Day- and month-level dates stated in the text (a month alone counts as its LAST day - the latest it can mean). Future dates are
    plans, not events, and are ignored; a bare year is ignored too (it is usually background: 'the game came out in 2008')."""
    found: list[tuple[datetime, str]] = []

    def add(year: int | None, month: int | None, day: int | None, raw: str) -> None:
        if month is None:
            return
        year = year or now.year
        try:
            if day is None:
                following = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC)
                date = following - timedelta(seconds=1)
            else:
                date = datetime(year, month, day, 23, 59, tzinfo=UTC)
        except ValueError:
            return
        if day is None and (year, month) == (now.year, now.month):
            date = now  # "this month": as recent as it can be
        if date <= now + timedelta(days=1):
            found.append((min(date, now), raw.strip()))

    for m in _DAY_MONTH.finditer(text):
        add(int(m.group(3)) if m.group(3) else None, _month_of(m.group(2)), int(m.group(1)), m.group(0))
    for m in _MONTH_DAY.finditer(text):
        add(int(m.group(3)) if m.group(3) else None, _month_of(m.group(1)), int(m.group(2)), m.group(0))
    for m in _IN_MONTH.finditer(text):
        add(int(m.group(2)) if m.group(2) else None, _month_of(m.group(1)), None, m.group(0))
    for m in _SEASON.finditer(text):  # 'this summer': at the latest the season's last month (only once that month has begun)
        month = _SEASON_END[(m.group(1) or m.group(2)).lower()]
        if month <= now.month:
            add(now.year, month, None, m.group(0))
    return found


_STATUS_BY_TYPE = {"CURRENT_EVENT": "CURRENT", "CURRENT_DISCLOSURE": "CURRENT", "RECENT_EVENT": "RECENT", "OLD_EVENT": "OLD",
                   "UNCERTAIN": "UNCERTAIN"}


@dataclass(frozen=True)
class Actuality:
    type: str  # CURRENT_EVENT / CURRENT_DISCLOSURE / RECENT_EVENT (3-7 days) / OLD_EVENT / UNCERTAIN (no date)
    date_source: str
    underlying_time: str | None = None  # CURRENT_DISCLOSURE: when the disclosed behaviour happened, as the text states it
    disclosed_at: datetime | None = None  # CURRENT_DISCLOSURE: the disclosure's first coverage (or its stated date)
    newly_disclosed: tuple[str, ...] = ()  # CURRENT_DISCLOSURE: targets / scope no earlier related coverage carried (nomination layer)
    stated: bool = False  # the TEXT dates the event (or its disclosure) as current - not an article timestamp or coverage timing

    @property
    def status(self) -> str:  # the coarse reading the gate decides on: CURRENT / RECENT / OLD / UNCERTAIN
        return _STATUS_BY_TYPE[self.type]


# a disclosure: the news is that something became PUBLIC (a report, an admission, researchers' findings), not that it happened now
_DISCLOSURE = _rx(
    r"\breveal\w*", r"\bdisclos\w*", r"\bsays? (its|it|that)\b", r"\badmit\w*", r"\bconfirm(s|ed)\b", r"\breports? (that|finds|found)\b",
    r"\bresearchers?\s*(:|say|said|found|discovered|showed)", r"\bnew (disclosure|report|details)\b",
    r"\bpublish(es|ed)? (a |an |its |the )?(official |technical )?(report|research|analysis|findings)\b", r"\bраскры\w*", r"\bпризнал\w*",
    r"\bвыяснил\w*", r"\bстало известно\b", r"\bопубликовал\w* (отч|исслед|анализ)\w*", r"\bисследовател\w*",
)
_SEASON = re.compile(r"\b(?:this|earlier this) (summer|spring|winter)\b|\b(?:этим )?(летом|весной|зимой)(?: этого года)?\b", re.IGNORECASE)
_SEASON_END = {"summer": 8, "летом": 8, "spring": 5, "весной": 5, "winter": 2, "зимой": 2}


def _sentence_with(text: str, fragment: str) -> str:
    return next((s for s in _SENTENCE.split(text) if fragment in s), text)


# HISTORICAL CONTEXT vs AN OLD EVENT (founder decision 2026-09-29): 'ChatGPT-6 Astra cracks 1941 Enigma-coded message in two days' was
# read as OLD because its lead says 'A German Army Enigma transmission from 85 years ago' - the age of the OBJECT, not of the event. A
# NUMERIC age cue ('N years ago', 'N лет назад', 'back in 19xx') attached to a noun - 'from / of N years ago', or after an origin participle
# ('sent / written / encrypted / built ... N years ago') - is historical context and does not date the event. The event's own verb carrying
# the age ('AI decoded the message 85 years ago') stays OLD; media participles (filmed / taken / recorded) stay old-event evidence (the
# resurfaced-video case); every other cue (resurfaced, anniversary, retrospective, old video ...) and the time window are unchanged.
_NUMERIC_AGE = re.compile(r"(?i)^(\d|back in)")
_OBJECT_AGE_BEFORE = re.compile(
    r"(?i)(?:\b(?:from|of|dating from|dating back|dated)\s+|\b(?:sent|written|encrypted|encoded|enciphered|built|created|made|lost|hidden|"
    r"buried|intercepted|designed|invented|discovered|posed|proposed|formulated|conceived|отправленн\w*|написанн\w*|зашифрованн\w*|"
    r"созданн\w*|потерянн\w*|сделанн\w*|спрятанн\w*|построенн\w*|изобретенн\w*|изобретённ\w*|поставленн\w*|сформулированн\w*|"
    r"предложенн\w*)\s+(?:\w+\s+){0,2})$")


def _object_age(head: str, cue: re.Match[str]) -> bool:
    """True when a numeric age cue describes the age / origin of an object in the story, not when the event happened."""
    return bool(_NUMERIC_AGE.search(cue.group(0)) and _OBJECT_AGE_BEFORE.search(head[max(0, cue.start() - 60):cue.start()]))


def assess_actuality(title: str, text: str, *, published_at: datetime | None, story_first_seen: datetime | None,
                     independent_sources: int, now: datetime) -> Actuality:
    """The age of the EVENT (article recency is not event recency). `story_first_seen` is the first coverage of this same FACTUAL event
    (never of a long-lived topic or of a related earlier incident). A disclosure is news when it is new, even when what it discloses
    happened earlier ('in May ... the analysis published on 30 July'); when the latest stated date is the disclosure's OWN date, that
    date is the disclosure's age."""
    head = f"{title}. {text[:1500]}"
    cue = next((m for m in _OLD_CUES.finditer(head) if not _object_age(head, m)), None)
    if cue:
        return Actuality("OLD_EVENT", f"text: retrospective / resurfacing cue {cue.group(0)!r}")
    if story_first_seen is not None and now - story_first_seen > OLD_CLUSTER_AGE:
        return Actuality("OLD_EVENT", f"coverage: this same factual event was first covered {story_first_seen:%Y-%m-%d} "
                                      f"({(now - story_first_seen).days} days ago) - a rewrite, not a new fact")
    if published_at is not None and now - published_at > CURRENT_WINDOW:
        return Actuality("OLD_EVENT", f"article: published {published_at:%Y-%m-%d %H:%M} UTC, older than 72 hours")
    disclosure = _DISCLOSURE.search(head)
    dates = stated_event_dates(head, now=now)
    if dates:
        latest, raw = max(dates)
        earliest, earliest_raw = min(dates)
        if now - latest <= CURRENT_WINDOW:
            if disclosure and now - earliest > CURRENT_WINDOW:
                return Actuality("CURRENT_DISCLOSURE", f"text: a disclosure dated {raw!r} of an earlier event ({earliest_raw!r})",
                                 underlying_time=earliest_raw, disclosed_at=latest, stated=True)
            return Actuality("CURRENT_EVENT", f"text: the event is dated {raw!r}", stated=True)
        disclosed_at = story_first_seen or published_at
        if disclosure and not _DISCLOSURE.search(_sentence_with(head, raw)) and disclosed_at is not None:
            # the stated date belongs to the behaviour, the disclosure verb to now - and nothing covered this same fact before
            return Actuality("CURRENT_DISCLOSURE", f"text: the behaviour is dated {raw!r}; the disclosure ({disclosure.group(0)!r}) is new - "
                                                   f"first covered {disclosed_at:%Y-%m-%d %H:%M} UTC",
                             underlying_time=raw, disclosed_at=disclosed_at)
        age = now - latest
        if age > OLD_CLUSTER_AGE:
            return Actuality("OLD_EVENT", f"text: the latest date the text gives for the event is {raw!r} ({age.days} days ago)")
        return Actuality("RECENT_EVENT", f"text: the latest stated date is {raw!r} ({age.days} days ago) - recent, not current")
    recent = _RECENT_CUES.search(head)
    if recent:
        return Actuality("CURRENT_EVENT", f"text: explicit recent time expression {recent.group(0)!r}", stated=True)
    if independent_sources >= 2 and story_first_seen is not None and now - story_first_seen <= CURRENT_WINDOW:
        return Actuality("CURRENT_EVENT", f"coverage: {independent_sources} independent outlets since {story_first_seen:%Y-%m-%d %H:%M} UTC")
    return Actuality("UNCERTAIN", "article timestamp only - the event date is not stated and no independent source corroborates it")


# --- 3. broad interest ---------------------------------------------------------------------------------------------------------------
_NICHE = _rx(
    r"\bmod(s|ded|der|ders|ding)?\b", r"\bмоддер\w*", r"\bмод(ы|ов|ом|ами|е)?\b", r"\bpatch notes\b", r"\bchangelog\b", r"\bv\d+\.\d+",
    r"\bgithub\b", r"\brepo(sitory)?\b", r"\bрепозитори\w*", r"\bpull request\b", r"\bcommit\b", r"\bapi\b", r"\bsdk\b", r"\bcli\b",
    r"\blibrary\b", r"\bбиблиотек\w*", r"\bframework\b", r"\bфреймворк\w*", r"\bplugin\b", r"\bплагин\w*", r"\bextension\b",
    r"\bdrivers?\b", r"\bдрайвер\w*", r"\bbeta build\b", r"\bбенчмарк\w*", r"\bbenchmark\w*", r"\bkernel\b", r"\bcompiler\b",
    r"\bкомпилятор\w*", r"\bdlss\b", r"\bfsr\b", r"\bdlaa\b", r"\bray[- ]tracing\b", r"\bтрассировк\w*", r"\bupscal\w*",
    r"\bмасштабировани\w*", r"\banti-?alias\w*", r"\bсглаживани\w*", r"\bemulator\b", r"\bэмулятор\w*", r"\bligature\b", r"\bopentype\b",
    r"\bfont\w*\b", r"\bшрифт\w*", r"\bstatus page\b", r"\bapi key\b", r"\bdistro\b", r"\bдистрибутив\w*", r"\bopen[- ]source\b",
)
_CONSEQUENCE = _rx(
    r"\bmillions?\b", r"\bмиллион\w*", r"\busers?\b.*\b(lost|affected|exposed|banned)\b", r"\bпользовател\w*.*\b(потерял|пострадал|лишил)",
    r"\boutage\b", r"\bban(s|ned)?\b", r"\bзапрет\w*", r"\blawsuit\b", r"\bsued\b", r"\bиск\b", r"\barrest\w*", r"\bарест\w*", r"\brecall\b",
    r"\bleak\w*\b", r"\bутечк\w*", r"\bbreach\b", r"\bprice\b", r"\bподорож\w*", r"\bshut(s|ting)? down\b", r"\bзакрыва\w*",
)
_BROAD = _rx(
    r"\b(hamster|cat|dog|pet|bird|horse|cow|хомяк\w*|кот(?:а|у|ом|ы|ов|ик\w*|ёнок|енок|ята|ят)?|кошк\w*|собак\w*|питом\w*)\b", r"\b(police|court|judge|school|hospital|bank|"
    r"airline|airport|flight|car|cars|government|minister|prime minister|election|parliament|полици\w*|суд\w*|школ\w*|больниц\w*|банк\w*|"
    r"авиа\w*|самол[её]т\w*|машин\w*|автомобил\w*|правительств\w*|министр\w*|госструктур\w*|выбор\w*)\b",
    r"\b(iphone|android|windows|whatsapp|telegram|youtube|tiktok|instagram|facebook|chatgpt|openai|google|apple|samsung|tesla|amazon|netflix|"
    r"spotify|uber|playstation|xbox|nintendo|starlink|gmail|maps)\b", r"\b(medicare|health|здравоохранени\w*|medical|медицин\w*)\b",
    r"\b(hack(ed|s|ing)?|взлом\w*|hacker\w*|хакер\w*)\b", r"\$\s?\d", r"\d\s?(руб|долл|\$|€)",
)
_AI_ACTOR = _rx(r"\b(ai|ии|agent\w*|агент(?!ств)\w*|chatbot|чат-?бот\w*|нейросет\w*|robot\w*|робот\w*)\b")


# OWN-EVENT READING (founder selection review 2026-09-29, after canary 10): a story is judged on what ITS event is, never on a different
# event it mentions as background. Canary 10's winner ('Anthropic will not appear at Senate inquiry ... amid fallout from OpenAI hack')
# owed both viral mechanisms and its broad-interest anchor to the OpenAI breach it only referred to. A background-attribution clause
# ('amid ...', 'in the wake of ...', 'following reports that ...', 'на фоне ...') is removed - up to the end of its sentence - before
# mechanisms and anchors are read; the event's own words stay.
_BACKGROUND = re.compile(
    r"(?i)(?:\bamid(?:st)?\b|\bin the wake of\b|\bin the aftermath of\b|\bfollowing (?:the )?(?:revelations?|reports?|news|disclosures?)\b|"
    r"\bafter (?:the )?(?:revelations?|reports?|news|disclosures?) (?:that|of|about)\b|\bна фоне\b|\bвслед за\b|"
    r"\bпосле (?:сообщени\w*|новост\w*|публикаци\w*|того,? как стало известно)\b)[^.!?…]*")
# a PROCEDURAL action as the headline's own event: a hearing, an inquiry, a committee appearance, testimony, a summons / invitation -
# institutional mechanics, not an event a reader feels. Such a headline needs a real-world CONSEQUENCE to be broad: the name of a famous
# company or of an institution alone is not a reason to care (the brand-name trap). Not a ban - a ban, a lawsuit, a breach, millions of
# users, an outage or a recall in the same headline still make it broad.
_PROCEDURAL = re.compile(
    r"(?i)\b(hearings?|inquir(?:y|ies)|committees?|testif(?:y|ies|ied)|testimony|summon(?:s|ed)?|subpoena\w*|"
    r"(?:called|invited|asked|declines?|declined|refuses?|refused|will not|won'?t) (?:to )?appear\w*|appear (?:before|at)|"
    r"consultations?|submissions?|слушани\w*|комитет\w*|парламентск\w* расследовани\w*|сенатск\w* расследовани\w*|"
    r"выступ\w* (?:перед|в) (?:сенат|парламент|комитет)\w*|вызва\w* (?:в|на) (?:сенат|парламент|комитет|слушани)\w*|дать показания)\b")


def own_event_text(text: str) -> str:
    """The text with every background-attribution clause removed (the event's own words only)."""
    return " ".join(_BACKGROUND.sub(" ", text or "").split())


def assess_broad_interest(title: str, lead: str) -> tuple[str, str]:
    """BROAD / NARROW / UNCLEAR, with the reason. A normal KAGE reader must see why it matters from one sentence - from the story's OWN
    event (background clauses removed); a procedural headline needs a real-world consequence, a famous name alone is not enough."""
    title, lead = own_event_text(title), own_event_text(lead)
    head = f"{title} {lead[:300]}"
    niche = _NICHE.search(head)
    consequence = _CONSEQUENCE.search(head)
    if _MECHANISMS["ai_launch"].search(title) and _VERSIONED_MODEL.search(title) and not _NOT_A_LAUNCH.search(title):
        # a flagship model release ('GPT-6 Sol and GPT-6 Luna in the API') - the API / SDK it ships through is its channel, not a niche
        return "BROAD", "a new flagship AI model release"
    if niche and not consequence:
        return "NARROW", f"specialist / niche subject ({niche.group(0)!r}) with no real-world consequence in the headline or lead"
    procedural = _PROCEDURAL.search(title)
    if procedural and not consequence:
        return ("NARROW", f"procedural event ({procedural.group(0)!r}) with no real-world consequence - a famous company or institution named "
                          "in it is not, by itself, a reason for a reader to care")
    broad = _BROAD.search(head)
    if broad:
        return "BROAD", f"everyday-life / mass-product / security anchor ({broad.group(0)!r})"
    if _MECHANISMS["unexpected_ai_behaviour"].search(title):
        # 'AI' alone proves nothing, but an AI system DOING something unexpected is understood from one sentence without any niche context
        return "BROAD", "unexpected behaviour of an AI system, stated in the headline"
    # founder decision 2026-09-29: a real launch (a new AI model / product, a consumer device), an unusual device someone built, or a tech
    # moment in mass pop culture is understood from one sentence - the EVENT is the anchor, not a famous name (953e77d stays: a name alone
    # never counts)
    family = next((m for m in ("ai_launch", "device_launch", "device_novelty", "pop_culture_crossover") if _MECHANISMS[m].search(head)), None)
    if family and not (family in ("ai_launch", "device_launch") and _NOT_A_LAUNCH.search(head)):
        return "BROAD", {"ai_launch": "a new AI model / product launch", "device_launch": "a consumer device launch or leak",
                         "device_novelty": "an unusual device and what it does", "pop_culture_crossover": "a tech moment in mass pop culture"}[family]
    if consequence:
        return "BROAD", f"a real-world consequence ({consequence.group(0)!r})"
    return "UNCLEAR", "no everyday-life, mass-product or consequence anchor a general reader would recognise"


# --- 4. inherent viral strength ------------------------------------------------------------------------------------------------------
_ACTOR_ONLY = _rx(r"\bмоддер\w*", r"\bэнтузиаст\w*", r"\bmodder\w*", r"\benthusiast\w*", r"\bjust a guy\b", r"\bнеобычн\w*", r"\bunusual\b",
                  r"\bweird\b", r"\bстранн\w*", r"\bstrange\b")  # adjectives / actors that only CLAIM strangeness
_AI_ACTOR_RX = (r"(?:\ba\.i\.(?=\W|$)|\b(?:ai|agents?|bots?|chatbots?|models?|ии|нейросет\w*|агент(?!ств)\w*|бот\w*|chatgpt|claude|gemini|"
                r"deepseek|grok)\b)")
_MECHANISMS: dict[str, re.Pattern[str]] = {
    # an unlikely actor (an animal, a household device) behind a measured result: '6.06 miles in one night'
    "absurd_measurable_outcome": _rx(
        r"\b(hamsters?|cats?|dogs?|parrots?|pigeons?|goats?|cows?|squirrels?|vacuums?|roombas?|toasters?|fridges?|хомяк\w*|кот(?:а|у|ом|ы|ов|ик\w*|ёнок|енок|ята|ят)?|кошк\w*|"
        r"собак\w*|попуга\w*|голуб(?:ь|я|ю|ем|и|ей)|коз(?:а|ы|у|ой|ёл|ел|ла|лы)|коров\w*|бел(ка|ки|ку)|пылесос\w*|тостер\w*|холодильник\w*)\b[^!?]{0,160}"
        r"\d+(?:[.,]\d+)?\s?(miles?|km|км|километр\w*|мил[иья]\w*|hours?|час\w*|times|раз\w*|%|kg|кг)"),
    "measurable_contradiction": _rx(r"\b(zero|ноль|ни одного|ни одной|none|nothing)\b[^.;:]{0,80}\d",
                                    r"\d[^.;:]{0,80}\b(zero|ноль|ни одного|ни одной|none|nothing)\b"),
    # the hook is already one sentence, so the gap may cross abbreviations ('A.I.', 'U.S.'); an AI actor, then what it unexpectedly did
    "unexpected_ai_behaviour": _rx(
        _AI_ACTOR_RX + r"[^!?]{0,80}\b(hack(ed|s|ing)?|deleted|escaped|lied|cheated|refused|faked|colluded|invented|went rogue|meddl\w*|"
        r"probed|infiltrat\w*|взлом\w*|удалил\w*|сбежал\w*|обманул\w*|изобрел\w*|сговор\w*|отказал\w*|подставил\w*|хакнул\w*|проник\w*)",
        r"\b(hack(ed|s)?|взломал\w*|rogue)\b[^!?]{0,80}" + _AI_ACTOR_RX),
    "real_failure": _rx(r"\baccidentally\b", r"\bby mistake\b", r"\bслучайно\b", r"\bпо ошибке\b", r"\bcrash(ed|es)\b",
                        r"\b(deleted|wiped)\b.*\b(database|data|files|production)\b", r"\bудалил\w*\b.*\b(баз\w*|данн\w*|файл\w*)"),
    "consumer_consequence": _rx(r"\b(price hike|подорож\w*|outage|сбой\w*|shut(s|ting)? down|recall|отзыв\w* (партии|устройств))\b",
                                r"\b(banned|запретил\w*|blocked|заблокирова\w*)\b"),
    "security_surprise": _rx(r"\b(hack(ed|s)?|взломал\w*|взлом\w*|breach(ed)?|leak(ed)?|утечк\w*|meddl\w*|accessed|probed|infiltrat\w*|"
                             r"attacked|атаковал\w*|хакнул\w*|проник\w*)\b[^!?]{0,80}\b(government|госструктур\w*|правительств\w*|"
                             r"hospital|больниц\w*|health|medicare|здравоохранени\w*|police|полици\w*|bank|банк\w*|election|выбор\w*|"
                             r"сайт\w*|sites?|websites?|portals?|портал\w*|databases?|баз\w*)"),
    # an unlikely actor (an animal, a household object) wired to consumer technology: a pet on a fitness app, a toaster on the internet
    "unlikely_pairing": _rx(
        r"\b(hamsters?|cats?|dogs?|parrots?|pigeons?|goats?|cows?|squirrels?|toasters?|fridges?|хомяк\w*|кот(?:а|у|ом|ы|ов|ик\w*|ёнок|енок|ята|ят)?|кошк\w*|собак\w*|попуга\w*|"
        r"голуб(?:ь|я|ю|ем|и|ей)|коз(?:а|ы|у|ой|ёл|ел|ла|лы)|коров\w*|тостер\w*|холодильник\w*)\b[^!?]{0,80}\b(strava|fitbit|apps?|trackers?|gps|wi-?fi|bluetooth|sensors?|"
        r"accounts?|internet|online|ai|chatgpt|robots?|приложени\w*|трекер\w*|аккаунт\w*|интернет\w*|ии|датчик\w*)\b",
        r"\b(strava|fitbit|apps?|trackers?|gps|приложени\w*|трекер\w*)\b[^!?]{0,80}\b(hamsters?|cats?|dogs?|хомяк\w*|кот(?:а|у|ом|ы|ов|ик\w*|ёнок|енок|ята|ят)?|кошк\w*|собак\w*)\b"),
    "bizarre_event": _rx(r"\bran\b.*\b(miles?|km|километр\w*)\b", r"\bпробежал\w*\b", r"\bturned (a|an|his|her|their)?\s?\w+ into\b",
                         r"\bпревратил\w* .{0,40}\b(в|into)\b", r"\bcan .* run doom\b", r"\bзапустил\w* doom\b", r"\bsecret language\b",
                         r"\bтайн\w+ язык\w*", r"\bdoubles as\b"),
    "human_vs_tech": _rx(r"\b(sued|lawsuit|fired|arrested|replaced by (ai|a robot))\b.*\b(ai|robot|algorithm)\b",
                         r"\b(уволил\w*|засудил\w*|арестова\w*|заменил\w*)\b.*\b(ии|робот\w*|алгоритм\w*)\b"),
    "controversy": _rx(r"\bbacklash\b", r"\boutrage\b", r"\bboycott\b", r"\bвозмущ\w*", r"\bскандал\w*", r"\bбойкот\w*", r"\beveryone hates\b",
                       r"\bextreme concern\b"),
    # founder decision 2026-09-29 (DAILY STORY SELECTION): major AI launches, devices and pop-culture moments are story families of their
    # own - they compete for the daily post on what happened, not through a weekly-only bucket. A LAUNCH is a real product being released
    # (a named AI model / product, a consumer device) - never a plan, a roadmap, a deal or a sale (see _NOT_A_LAUNCH).
    "ai_launch": _rx(
        r"\b(launch(es|ed)?|unveil(s|ed)?|releas(es|ed)|introduc(es|ed)|debut(s|ed)?|rolls? out|rolled out|ships?|shipped|выпустил\w*|"
        r"представил\w*|запустил\w*|анонсировал\w*|релиз\w*)\b[^!?]{0,80}\b(gpt[- ]?\d[\w.]*|chatgpt|gemini|claude|llama|grok|copilot|sora|"
        r"midjourney|deepseek|qwen|mistral|kimi|apple intelligence|galaxy ai|notebooklm|perplexity)\b",  # a NAMED AI product - 'models' alone is not one
        r"\b(gpt[- ]?\d[\w.]*|gemini \d[\w.]*|claude \w+ \d[\w.]*|llama \d[\w.]*|grok \d[\w.]*)\b[^!?]{0,40}\b(is out|arrives|launch\w*|"
        r"вышл\w*|вышел|доступн\w*)"),
    "device_launch": _rx(
        r"\b(launch(es|ed)?|unveil(s|ed)?|releas(es|ed)|introduc(es|ed)|debut(s|ed)?|announc(es|ed)|rolls? out|выпустил\w*|представил\w*|"
        r"запустил\w*|анонсировал\w*|показал\w*)\b[^!?]{0,80}\b(iphone\w*|ipad\w*|macbook\w*|pixel \d\w*|galaxy \w+|smartphones?|phones?|"
        r"смартфон\w*|laptops?|ноутбук\w*|glasses|очк(и|ов)|smart ?watch\w*|часы|headsets?|гарнитур\w*|consoles?|консол\w*|tablets?|"
        r"планшет\w*|robots?|робот\w*|drones?|дрон\w*|humanoids?|гуманоид\w*|gadgets?|гаджет\w*)\b",
        r"\b(iphone \d+\w*|pixel \d+\w*|galaxy s\d+\w*|vision pro|quest \d)\b[^!?]{0,60}\b(leak\w*|утечк\w*|слив\w*|запустил\w*|запустили|runs?)\b"),
    # an unusual device someone BUILT and what it does ('запилили робота-паука, который занимается сваркой ... хоть по потолку')
    "device_novelty": _rx(
        r"\b(built|made|created|developed|запилил\w*|собрал\w*|создал\w*|разработал\w*|сделал\w*)\b[^!?]{0,60}\b(robots?|робот\w*|drones?|"
        r"дрон\w*|humanoids?|гуманоид\w*|exoskeleton\w*|экзоскелет\w*|машин\w*-\w+)\b",
        r"\b(robots?|робот\w*|drones?|дрон\w*|humanoids?|гуманоид\w*)\b[^!?]{0,80}\b(crawls?|climbs?|walks? on|ползат\w*|лаза\w*|по потолку|"
        r"сварк\w*|welds?|cooks?|готовит|folds?|играет|plays?|dances?|танцу\w*)\b"),
    # an AI system achieving something astonishing - cracking, solving, deciphering, beating, a record (founder: unexpected tech records)
    "ai_feat": _rx(_AI_ACTOR_RX + r"[^!?]{0,60}\b(crack(s|ed)|solv(es|ed)|decod(es|ed)|deciphe\w*|beat(s)?|won|wins|broke (the |a )?record|"
                   r"расшифровал\w*|разгадал\w*|обыграл\w*|побил\w* рекорд\w*)\b"),
    # a tech figure / product crossing into mass pop culture - a sketch, a parody, a meme the whole internet quotes
    "pop_culture_crossover": _rx(r"\b(snl|saturday night live|the simpsons|симпсон\w*|south park|parod(y|ies|ied)|пароди\w*|спародировал\w*)\b",
                                 r"\bgets? the \w+ treatment\b"),
}
# a 'launch' that is not one: a plan, a roadmap, a partnership, a funding round, a deal / sale / discount
_NOT_A_LAUNCH = _rx(r"\bplans?\b", r"\bwill\b", r"\broadmap\b", r"\bexpansion\b", r"\bdeals?\b", r"\bsale\b", r"\bdiscount\w*",
                    r"\bpartnership\b", r"\bfunding\b", r"\bplanned\b", r"\bскидк\w*", r"\bпланиру\w*", r"\bраунд\w*", r"\bпартн[её]рств\w*",
                    r"\bфинансировани\w*")
# a GENERIC release - 'a new <product> model / feature / update / version' with nothing named - is weak for ANY audience; a named or
# versioned model / product launch is strong for any audience (founder 2026-09-29: an enterprise label alone never excludes a launch)
_GENERIC_RELEASE = _rx(r"\b(?:a|an) new \w+ (?:model|feature|update|version|tool|option|setting)s?\b",
                       r"\bнов(?:ую|ая|ый|ое|ые) (?:функци\w*|модел\w*|верси\w*|настройк\w*|обновлени\w*)\b")
_LAUNCH_FAMILIES = ("ai_launch", "device_launch", "device_novelty")
# how much each kind of reason to care weighs for a social-first feed (founder decision 2026-09-29): relatable / absurd / surprising events
# and real launches weigh 2, institutional signals 1 - wider coverage (momentum) only breaks ties AFTER this, so a clearly stronger story
# is never beaten merely by being less covered
SHAREABLE_MECHANISMS = frozenset({"unexpected_ai_behaviour", "real_failure", "absurd_measurable_outcome", "bizarre_event", "unlikely_pairing",
                                  "measurable_contradiction", "pop_culture_crossover", "ai_feat"})
_WEIGHT = {**{m: 2 for m in SHAREABLE_MECHANISMS}, **{m: 2 for m in _LAUNCH_FAMILIES},
           "security_surprise": 1, "consumer_consequence": 1, "controversy": 1, "human_vs_tech": 1}
# a flagship model release named with its version ('GPT-6 Sol', 'Claude Opus 5.5', 'Gemini 4') is the biggest kind of AI launch
_VERSIONED_MODEL = _rx(r"\bgpt[- ]?\d", r"\bclaude (opus|sonnet|haiku|fable)\b", r"\bgemini \d", r"\bllama \d", r"\bgrok \d", r"\bflagship\b",
                       r"\bфлагманск\w*")
_LARGE_MAGNITUDE = _rx(r"\d[\d\s.,]*\s?(million|billion|trillion|млн|млрд|трлн|миллион\w*|миллиард\w*|триллион\w*)\b",
                       r"(?<![\d.,])\d{1,3}(?:[\s,.]\d{3})+(?![\d.,])", r"(?<![\d.,])\d{5,}(?![\d.,])")
_ANY_NUMBER = re.compile(r"\d")


def story_points(mechanisms: list[str], hook: str) -> int:
    """The story's own editorial strength: weighted reasons to care (launch families of one event never add up - one launch is one
    launch), plus a concrete magnitude (a large one - millions, 48 000 files, 17 trillion rows - counts double)."""
    text = hook.replace("\ufe0f\u20e3", "").replace("\u20e3", "")  # keycap digits ('4️⃣8️⃣ 0️⃣0️⃣0️⃣') are digits
    launch = [m for m in mechanisms if m in _LAUNCH_FAMILIES]
    points = sum(_WEIGHT.get(m, 1) for m in mechanisms if m not in _LAUNCH_FAMILIES)
    if launch:
        if "ai_launch" in launch and _VERSIONED_MODEL.search(text):
            points += 3  # a flagship, versioned model release
        elif launch == ["ai_launch"] and _GENERIC_RELEASE.search(text):
            points += 1  # 'a new ChatGPT model' with nothing named: a routine release, whoever it is for
        else:
            points += 2
    if _LARGE_MAGNITUDE.search(text):
        points += 2
    elif _ANY_NUMBER.search(text):
        points += 1
    return points
HOOK_LEAD_SENTENCES = 12  # every sentence of the stored lead (itself capped at the summary + 1,500 chars of article text)
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def _hook_sentences(title: str, lead: str) -> list[str]:
    """Candidate one-line hooks: the headline alone, or the headline's subject joined with ONE of the first lead sentences - the strongest
    grounded fact is often a few sentences in ('One recent activity showed 6.06 miles in 4 hours and 37 minutes' under a hamster headline)."""
    sentences = [s for s in _SENTENCE.split(" ".join((lead or "").split())) if len(s) > 20][:HOOK_LEAD_SENTENCES]
    return [" ".join(_DISTRIBUTION.sub(" ", s).split()) for s in [title, *(f"{title} — {s}" for s in sentences)]]


# a headline that frames or discusses an event instead of stating one: its 'hook' is an opinion, never a grounded fact
_COMMENTARY = _rx(r"\braises? (\w+ )?questions\b", r"\bis a warning\b", r"\breveals? (\w+ )?anxiety\b", r"\bwhat (it|this) means\b",
                  r"\bwhy (it|this) matters\b", r"^\s*(opinion|analysis|explainer|editorial)\b", r"\bheres? what\b",
                  r"\bbigger than (it|they|we) (let on|thought)\b", r"\bвызывает вопрос\w*", r"\bэто предупреждение\b", r"\bчто это значит\b",
                  r"\bпочему это важно\b", r"\bмнение\b", r"\bколонка\b",
                  # a roundup / digest bundles several items - it is not one event (founder daily selection review 2026-09-29)
                  r"^\s*top stories\b", r"\band more\s*$", r"\broundup\b", r"\bthis week in\b", r"\bweek in review\b", r"\bдайджест\w*",
                  r"\bитоги недели\b",
                  # a headline that only denies a phenomenon ('There are no rogue AI agents') argues a view, it reports no event
                  r"^\s*there (?:is|are) no\b")
# an AI actor DOING something (the action form of unexpected_ai_behaviour) - a lone mechanism qualifies only as an event, never as the
# bare topic word 'rogue' ('Nvidia's answer to rogue agents' is a product story, 'There are no rogue agents' an opinion)
_AI_EVENT = _rx(_AI_ACTOR_RX + r"[^!?]{0,80}\b(hack(ed|s|ing)?|deleted|escaped|lied|cheated|refused|faked|colluded|invented|went rogue|"
                r"meddl\w*|probed|infiltrat\w*|взлом\w*|удалил\w*|сбежал\w*|обманул\w*|изобрел\w*|сговор\w*|отказал\w*|подставил\w*|хакнул\w*|"
                r"проник\w*)")


def assess_inherent_strength(title: str, lead: str) -> tuple[str, list[str], str]:
    """STRONG / MODERATE / NONE, the mechanisms, and the strongest factual hook sentence (distribution words removed). A commentary
    headline (an event framed as a question, a warning, an analysis) has no factual hook of its own: NONE."""
    if _COMMENTARY.search(title):
        return "NONE", [], title
    title, lead = own_event_text(title), own_event_text(lead)  # mechanisms must belong to the story's own event, never to its background
    best: tuple[int, list[str], str] = (0, [], _hook_sentences(title, lead)[0])
    for sentence in _hook_sentences(title, lead):
        text = _ACTOR_ONLY.sub(" ", sentence)
        found = [name for name, pattern in _MECHANISMS.items() if pattern.search(text)]
        if _NOT_A_LAUNCH.search(text):
            found = [m for m in found if m not in ("ai_launch", "device_launch")]
        points = story_points(found, sentence)
        if points > best[0]:
            best = (points, found, sentence)
    points, found, hook = best
    # founder decision 2026-09-29: ONE clearly strong idea is enough - a relatable / absurd / surprising event, a real launch, or any
    # signal carried by a large concrete magnitude - it no longer needs two separate formal mechanisms (every earlier STRONG stays STRONG)
    # a magnitude only AMPLIFIES a reason to care - '$11.6 billion cloud deal' has none, so it never qualifies on its number alone
    single_strong = bool(found) and points >= 2 and (bool(set(found) & (SHAREABLE_MECHANISMS | set(_LAUNCH_FAMILIES))) or bool(
        _LARGE_MAGNITUDE.search(hook.replace("\ufe0f\u20e3", "").replace("\u20e3", ""))))
    if found == ["unexpected_ai_behaviour"] and not _AI_EVENT.search(_ACTOR_ONLY.sub(" ", hook)):
        single_strong = False  # the bare topic word ('rogue agents'), not an AI actor doing something
    strong = len(found) >= 2 or "measurable_contradiction" in found or single_strong
    strength = "STRONG" if strong else "MODERATE" if found else "NONE"
    return strength, found, hook


# --- 5. momentum ---------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ClusterMember:
    title: str
    source_id: str
    source_name: str
    seen_at: datetime | None  # published_at, else collected_at
    collected_at: datetime | None


def _title_stems(title: str) -> set[str]:
    title = re.sub(r"\s+[-|–]\s+[^-|–]{2,60}$", "", title or "")  # "Headline - Outlet"
    return {w[:5] for w in re.findall(r"[a-zа-яё0-9]{4,}", title.lower())}


def same_event(a: str, b: str) -> bool:
    """Two headlines about the SAME event, not merely the same person or long-running topic ('Bill Gates warns ...' twice about different
    things): most of their content stems are shared."""
    sa, sb = _title_stems(a), _title_stems(b)
    shared, union = len(sa & sb), max(1, len(sa | sb))
    return (shared >= 3 and shared / union >= 0.3) or (shared >= 2 and shared / union >= 0.45)


def outlet_of(source_name: str, title: str) -> str:
    """The real outlet: an aggregator copy ('Google News: ...') names its outlet in the headline suffix ('... - The Washington Post')."""
    if (source_name or "").lower().startswith("google news"):
        match = re.search(r"\s[-–|]\s([^-–|]{2,60})$", title or "")
        if match:
            return _SECTION.sub("", match.group(1).strip().lower())
    return _SECTION.sub("", (source_name or "").strip().lower())


# a publication's section feeds are one outlet ('The Guardian Technology' = 'The Guardian')
_SECTION = re.compile(r"(\s*[:\-]?\s*(technology|tech|science|ai|artificial intelligence|business|news|world|front page|machine learning))+$")


def cluster_signals(event_title: str, members: list[ClusterMember], *, now: datetime,
                    recent_headlines: list[ClusterMember] | None = None) -> dict:
    """Momentum and first coverage of THIS event. Two production sources, both counted by the same same-event test:
      - its confirmed Story Memory cluster - a long-lived topic (a new development joins as a story_update, a distinct event can be linked
        to an older topic), so only title-similar members count, never the topic's age or its old sources;
      - every headline collected in the last 72 hours (cross-feed corroboration): a fast-breaking story is often FRAGMENTED by Story Memory
        (the US-government disclosure of 2026-09-25/26: ten outlets, almost all uncertain_match or one-member stories), so cluster
        membership alone under-counts it. Outlets are distinct publishers (aggregator copies resolved to their outlet)."""
    same = [m for m in [*members, *(recent_headlines or [])] if same_event(event_title, m.title)]
    recent = [m for m in same if m.collected_at is not None and now - m.collected_at <= CURRENT_WINDOW]
    first = min((m.seen_at for m in same if m.seen_at is not None), default=None)
    return {"independent_sources": max(1, len({outlet_of(m.source_name, m.title) for m in recent})),
            "story_events_24h": max(1, len({(outlet_of(m.source_name, m.title), m.title) for m in same
                                            if m.collected_at is not None and now - m.collected_at <= timedelta(hours=24)})),
            "on_hacker_news": any(m.source_name.lower().startswith("hacker news") for m in recent),
            "story_first_seen": first}



def assess_momentum(*, independent_sources: int, story_events_24h: int, on_hacker_news: bool, forwards: int | None,
                    reactions: int | None) -> tuple[str, list[str]]:
    """A band - NONE / WEAK / MODERATE / STRONG - from signals that exist in production data only. Supporting evidence, never a
    threshold: grouping is imperfect, so 10 vs 13 outlets changes nothing; only NONE vs corroborated matters to the gate."""
    signals = []
    if independent_sources >= 2:
        signals.append(f"{independent_sources} independent outlets carried this same event in the last 72 hours")
    if story_events_24h >= 3:
        signals.append(f"{story_events_24h} articles on it in the last 24 hours")
    if on_hacker_news:
        signals.append("on the Hacker News front page")
    if forwards and forwards >= 20:
        signals.append(f"{forwards} Telegram forwards")
    if reactions and reactions >= 100:
        signals.append(f"{reactions} Telegram reactions")
    if independent_sources >= 5 or (on_hacker_news and independent_sources >= 3) or (forwards or 0) >= 100:
        band = "STRONG"
    elif independent_sources >= 3 or on_hacker_news or (forwards or 0) >= 20 or (reactions or 0) >= 100:
        band = "MODERATE"
    elif independent_sources >= 2:
        band = "WEAK"
    else:
        band = "NONE"
    return band, signals or ["single source, no engagement signal"]


# --- 6. visual potential (recorded, never a gate) ------------------------------------------------------------------------------------
_PHYSICAL = _rx(r"\b(robot|drone|hamster|cat|dog|car|phone|iphone|guitar|satellite|rocket|device|gadget|console|watch|glasses)\w*",
                r"\b(робот|дрон|хомяк|собак|машин|смартфон|гитар|спутник|ракет|устройств|гаджет|консол|часы|очки)\w*",
                r"\bкот(?:а|у|ом|ы|ов|ик\w*|ёнок|енок|ята|ят)?\b")  # a cat - never который / которые


@dataclass(frozen=True)
class ViralVerdict:
    eligible: bool
    failed_gate: str | None  # the FIRST failed criterion (later ones are not allowed to rescue it)
    reason: str
    kage_core: tuple[str, ...]
    actuality: Actuality
    broad_interest: str
    broad_reason: str
    strength: str
    mechanisms: tuple[str, ...]
    hook: str
    momentum: str
    momentum_signals: tuple[str, ...]
    visual_potential: str
    good_kage_news: bool  # relevant and current: usable as ordinary news even when it is not viral
    details: dict = field(default_factory=dict)
    points: int = 0  # story_points: the story's own weighted editorial strength (founder decision 2026-09-29)

    @property
    def score(self) -> tuple[int, int, int, int]:
        """Ranking among eligible stories: strength band, then the story's own editorial points, then momentum (wider coverage only
        breaks ties - founder decision 2026-09-29: a clearly more surprising / relatable / shareable story may beat a more covered one),
        then visual potential."""
        strength = {"STRONG": 2, "MODERATE": 1, "NONE": 0}
        momentum = {"STRONG": 3, "MODERATE": 2, "WEAK": 1, "NONE": 0}
        return strength[self.strength], self.points, momentum[self.momentum], 1 if self.visual_potential == "HIGH" else 0


def assess_viral_story(candidate: Any, evidence: str = "", *, now: datetime | None = None,
                       actuality: Actuality | None = None) -> ViralVerdict:
    """The six criteria in order for one FeedCandidate (its momentum fields come from its factual event group). `actuality` - the
    EVENT-level reading from services.instagram_viral_nomination (all copies of the event read together) - replaces the single-article
    reading when given."""
    now = now or datetime.now(UTC)
    source = (candidate.source_name or "").lower()
    title = _clean_title(candidate.title or "", source)
    lead = plain_text(f"{candidate.summary or ''} {(evidence or '')[:1500]}")
    core = tuple(kage_core(title))
    actuality = actuality or assess_actuality(title, lead, published_at=getattr(candidate, "published_at", None),
                                 story_first_seen=getattr(candidate, "story_first_seen", None),
                                 independent_sources=int(getattr(candidate, "independent_sources", 1) or 1), now=now)
    broad, broad_reason = assess_broad_interest(title, lead)
    strength, mechanisms, hook = assess_inherent_strength(title, lead)
    points = story_points(list(mechanisms), hook)
    momentum, signals = assess_momentum(independent_sources=int(getattr(candidate, "independent_sources", 1) or 1),
                                        story_events_24h=int(getattr(candidate, "story_events_24h", 1) or 1),
                                        on_hacker_news=bool(getattr(candidate, "on_hacker_news", False)),
                                        forwards=getattr(candidate, "forwards", None), reactions=getattr(candidate, "reactions", None))
    visual = "HIGH" if _PHYSICAL.search(f"{title} {lead[:300]}") else "MEDIUM"

    def verdict(failed: str | None, reason: str) -> ViralVerdict:
        return ViralVerdict(eligible=failed is None, failed_gate=failed, reason=reason, kage_core=core, actuality=actuality,
                            broad_interest=broad, broad_reason=broad_reason, strength=strength, mechanisms=tuple(mechanisms), hook=hook,
                            momentum=momentum, momentum_signals=tuple(signals), visual_potential=visual, points=points,
                            good_kage_news=bool(core) and actuality.status != "OLD",  # RECENT is still usable news
                            details={"actuality_type": actuality.type, "underlying_time": actuality.underlying_time,
                                     "disclosed_at": actuality.disclosed_at.isoformat() if actuality.disclosed_at else None,
                                     "newly_disclosed": list(actuality.newly_disclosed),
                                     "hook_chronology": chronology_requirement(actuality)})

    if not core:
        return verdict("1_kage_relevance", "technology is not central to the event (KAGE-first rule)")
    if actuality.status in ("OLD", "RECENT"):
        return verdict("2_event_actuality", f"not a current event - {actuality.date_source}")
    if broad != "BROAD":
        return verdict("3_broad_interest", broad_reason)
    if strength == "NONE":
        return verdict("4_inherent_virality", "the strongest factual sentence carries no viral mechanism - the story would need invented framing")
    if strength != "STRONG":
        # if the story has to be MADE viral it is not strong enough: one mechanism is good news, and momentum never lifts it (gate 5 supports)
        return verdict("4_inherent_virality", f"only one viral mechanism {mechanisms} - the Director would have to stretch it; momentum "
                                              f"({momentum.lower()}) cannot lift a moderate story into the viral slot")
    if momentum == "NONE" and not (actuality.status == "CURRENT" and actuality.stated):
        # one uncorroborated source may carry an exceptionally strong event, but only when its TEXT dates the event (or the disclosure)
        # as current: an undated article - or a disclosure whose novelty rests only on when one outlet published it - can be delayed
        # coverage (the article date is not the event date)
        return verdict("5_momentum", f"single source, no momentum, and nothing in the text dates it as current ({actuality.type}: "
                                     f"{actuality.date_source})")
    return verdict(None, f"current ({actuality.date_source}); broad ({broad_reason}); {strength.lower()} mechanisms {mechanisms}; "
                         f"momentum {momentum.lower()} ({'; '.join(signals)})")


def chronology_requirement(actuality: Actuality) -> str | None:
    """What any hook for this event must keep true about time. A CURRENT_DISCLOSURE was REVEALED now - it did not HAPPEN now."""
    if actuality.type != "CURRENT_DISCLOSURE":
        return None
    return (f"the disclosure is new, the behaviour is not ({actuality.underlying_time or 'earlier, date unstated'}): the hook must say it "
            "was revealed / disclosed / reported and must not imply the action happened today")


def best_viral_story(verdicts: list[tuple[Any, ViralVerdict]]) -> tuple[Any, ViralVerdict] | None:
    """The strongest eligible story, or None - an EMPTY viral slot is a valid outcome (no best-of-a-weak-batch)."""
    eligible = [(c, v) for c, v in verdicts if v.eligible]
    return max(eligible, key=lambda cv: cv[1].score) if eligible else None
