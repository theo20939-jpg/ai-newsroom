"""VIRAL STORY STRENGTH + ACTUALITY gate for the KAGE viral slot (founder task 2026-09-26). Deterministic - no model call.

KAGE viral content is a genuinely strong CURRENT tech / AI / gadget / gaming / platform story whose facts are already shareable - not
"the most viral-looking item available", not "the best story we can turn into a carousel". The creative layer amplifies a strong story;
it never manufactures virality for a weak one.

Six criteria, read IN ORDER; the first failure decides, and a later criterion never rescues an earlier one (visual potential is recorded,
never a gate):
  1. KAGE CORE RELEVANCE     - the accepted KAGE-first rule (services.instagram_feed_product.kage_core), unchanged;
  2. EVENT ACTUALITY         - the age of the EVENT, not of the article. OLD (rejected): a retrospective / resurfacing cue, the latest
                               date the text states older than 7 days, or this same event already covered more than 7 days ago in our
                               own data. CURRENT: a stated date or an explicit time expression within 72 hours, or independent
                               corroboration inside 72 hours. RECENT (3-7 days) is not current: it fails the viral slot here (still good
                               KAGE news) and momentum cannot lift it back. UNCERTAIN (no date stated) is recorded - the article
                               timestamp is never assumed to be the event's - and must be resolved by corroboration at the momentum step;
  3. BROAD INTEREST          - understandable from one sentence without following a niche: specialist / niche markers (mods, patches,
                               repositories, APIs, rendering techniques, ...) need a real-world consequence; otherwise the story needs an
                               everyday-life, mass-product or security/AI-behaviour anchor;
  4. INHERENT VIRAL STRENGTH - the strongest factual one-sentence hook (title or the first lead sentences, with distribution words such as
                               viral / meme / trend removed) must itself carry a mechanism: absurd measurable outcome, contradiction,
                               unexpected AI behaviour, real failure, consumer consequence, surprising security incident, bizarre
                               product behaviour, human-vs-technology conflict, controversy. Words that only name an actor (modder,
                               enthusiast) or say how a story spread are never a mechanism;
  5. CURRENT MOMENTUM        - only signals that exist in production data (cluster_signals): distinct sources covering this same event
                               in the last 72 hours, its growth in the last 24 hours, Hacker News front-page presence, Telegram forwards
                               / reactions (Telegram sources only). A long-lived Story Memory topic's age and old sources are not this
                               event's. Momentum SUPPORTS and never rescues a failed gate 1-4 (a MODERATE, one-mechanism story stays
                               ordinary news however many outlets carry it). A strong story with no momentum still qualifies when the
                               event is explicitly CURRENT; with an UNCERTAIN date it needs corroboration - a single undated article can
                               be delayed coverage of an old event;
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
    return found


@dataclass(frozen=True)
class Actuality:
    status: str  # CURRENT / RECENT (3-7 days) / UNCERTAIN (no date) / OLD
    date_source: str


def assess_actuality(title: str, text: str, *, published_at: datetime | None, story_first_seen: datetime | None,
                     independent_sources: int, now: datetime) -> Actuality:
    """The age of the EVENT (article recency is not event recency). The event date is the LATEST date the text states: a disclosure is
    the news even when what it discloses happened earlier ('an attack in May, the analysis published on 30 July')."""
    head = f"{title} {text[:1500]}"
    cue = _OLD_CUES.search(head)
    if cue:
        return Actuality("OLD", f"text: retrospective / resurfacing cue {cue.group(0)!r}")
    if story_first_seen is not None and now - story_first_seen > OLD_CLUSTER_AGE:
        return Actuality("OLD", f"cluster: this same event was first covered {story_first_seen:%Y-%m-%d} ({(now - story_first_seen).days} days ago)")
    if published_at is not None and now - published_at > CURRENT_WINDOW:
        return Actuality("OLD", f"article: published {published_at:%Y-%m-%d %H:%M} UTC, older than 72 hours")
    dates = stated_event_dates(head, now=now)
    if dates:
        latest, raw = max(dates)
        age = now - latest
        if age > OLD_CLUSTER_AGE:
            return Actuality("OLD", f"text: the latest date the text gives for the event is {raw!r} ({age.days} days ago)")
        if age > CURRENT_WINDOW:
            return Actuality("RECENT", f"text: the latest stated date is {raw!r} ({age.days} days ago) - recent, not current")
        return Actuality("CURRENT", f"text: the event is dated {raw!r}")
    recent = _RECENT_CUES.search(head)
    if recent:
        return Actuality("CURRENT", f"text: explicit recent time expression {recent.group(0)!r}")
    if independent_sources >= 2 and story_first_seen is not None and now - story_first_seen <= CURRENT_WINDOW:
        return Actuality("CURRENT", f"cluster: {independent_sources} independent sources since {story_first_seen:%Y-%m-%d %H:%M} UTC")
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


def assess_broad_interest(title: str, lead: str) -> tuple[str, str]:
    """BROAD / NARROW / UNCLEAR, with the reason. A normal KAGE reader must see why it matters from one sentence."""
    head = f"{title} {lead[:300]}"
    niche = _NICHE.search(head)
    consequence = _CONSEQUENCE.search(head)
    if niche and not consequence:
        return "NARROW", f"specialist / niche subject ({niche.group(0)!r}) with no real-world consequence in the headline or lead"
    broad = _BROAD.search(head)
    if broad:
        return "BROAD", f"everyday-life / mass-product / security anchor ({broad.group(0)!r})"
    if _MECHANISMS["unexpected_ai_behaviour"].search(title):
        # 'AI' alone proves nothing, but an AI system DOING something unexpected is understood from one sentence without any niche context
        return "BROAD", "unexpected behaviour of an AI system, stated in the headline"
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
}
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
                  r"\bпочему это важно\b", r"\bмнение\b", r"\bколонка\b")


def assess_inherent_strength(title: str, lead: str) -> tuple[str, list[str], str]:
    """STRONG / MODERATE / NONE, the mechanisms, and the strongest factual hook sentence (distribution words removed). A commentary
    headline (an event framed as a question, a warning, an analysis) has no factual hook of its own: NONE."""
    if _COMMENTARY.search(title):
        return "NONE", [], title
    best: tuple[int, list[str], str] = (0, [], _hook_sentences(title, lead)[0])
    for sentence in _hook_sentences(title, lead):
        text = _ACTOR_ONLY.sub(" ", sentence)
        found = [name for name, pattern in _MECHANISMS.items() if pattern.search(text)]
        if len(found) > best[0]:
            best = (len(found), found, sentence)
    count, found, hook = best
    strength = "STRONG" if count >= 2 or "measurable_contradiction" in found else "MODERATE" if count == 1 else "NONE"
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
    """STRONG / MODERATE / NONE from signals that exist in production data only."""
    signals = []
    if independent_sources >= 2:
        signals.append(f"{independent_sources} independent outlets carried this same event in the last 72 hours")
    if story_events_24h >= 3:
        signals.append(f"{story_events_24h} cluster events in the last 24 hours")
    if on_hacker_news:
        signals.append("on the Hacker News front page")
    if forwards and forwards >= 20:
        signals.append(f"{forwards} Telegram forwards")
    if reactions and reactions >= 100:
        signals.append(f"{reactions} Telegram reactions")
    strong = independent_sources >= 3 or (on_hacker_news and independent_sources >= 2) or (forwards or 0) >= 100
    return ("STRONG" if strong else "MODERATE" if signals else "NONE"), signals or ["single source, no engagement signal"]


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

    @property
    def score(self) -> tuple[int, int, int]:
        order = {"STRONG": 2, "MODERATE": 1, "NONE": 0}
        return order[self.strength], order[self.momentum], 1 if self.visual_potential == "HIGH" else 0


def assess_viral_story(candidate: Any, evidence: str = "", *, now: datetime | None = None) -> ViralVerdict:
    """The six criteria in order for one FeedCandidate (its momentum fields come from the story cluster)."""
    now = now or datetime.now(UTC)
    source = (candidate.source_name or "").lower()
    title = _clean_title(candidate.title or "", source)
    lead = plain_text(f"{candidate.summary or ''} {(evidence or '')[:1500]}")
    core = tuple(kage_core(title))
    actuality = assess_actuality(title, lead, published_at=getattr(candidate, "published_at", None),
                                 story_first_seen=getattr(candidate, "story_first_seen", None),
                                 independent_sources=int(getattr(candidate, "independent_sources", 1) or 1), now=now)
    broad, broad_reason = assess_broad_interest(title, lead)
    strength, mechanisms, hook = assess_inherent_strength(title, lead)
    momentum, signals = assess_momentum(independent_sources=int(getattr(candidate, "independent_sources", 1) or 1),
                                        story_events_24h=int(getattr(candidate, "story_events_24h", 1) or 1),
                                        on_hacker_news=bool(getattr(candidate, "on_hacker_news", False)),
                                        forwards=getattr(candidate, "forwards", None), reactions=getattr(candidate, "reactions", None))
    visual = "HIGH" if _PHYSICAL.search(f"{title} {lead[:300]}") else "MEDIUM"

    def verdict(failed: str | None, reason: str) -> ViralVerdict:
        return ViralVerdict(eligible=failed is None, failed_gate=failed, reason=reason, kage_core=core, actuality=actuality,
                            broad_interest=broad, broad_reason=broad_reason, strength=strength, mechanisms=tuple(mechanisms), hook=hook,
                            momentum=momentum, momentum_signals=tuple(signals), visual_potential=visual,
                            good_kage_news=bool(core) and actuality.status != "OLD")  # RECENT is still usable news

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
    if momentum == "NONE" and actuality.status != "CURRENT":
        # one uncorroborated source may carry an exceptionally strong event, but only when the event is explicitly current: an undated
        # single article can be delayed coverage of something that happened long before (the article date is not the event date)
        return verdict("5_momentum", "single source, no momentum, and the event date is uncertain - nothing shows the event itself is current")
    return verdict(None, f"current ({actuality.date_source}); broad ({broad_reason}); {strength.lower()} mechanisms {mechanisms}; "
                         f"momentum {momentum.lower()} ({'; '.join(signals)})")


def best_viral_story(verdicts: list[tuple[Any, ViralVerdict]]) -> tuple[Any, ViralVerdict] | None:
    """The strongest eligible story, or None - an EMPTY viral slot is a valid outcome (no best-of-a-weak-batch)."""
    eligible = [(c, v) for c, v in verdicts if v.eligible]
    return max(eligible, key=lambda cv: cv[1].score) if eligible else None
