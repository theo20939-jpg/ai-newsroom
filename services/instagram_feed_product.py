"""KAGE Instagram feed product: what earns a daily slot, what waits for the weekly recap, what never ships.

The founder's product (2026-09-24): Instagram is an AI/tech lifestyle feed, not a newsroom.
  * UP TO 2 posts a day - a hard maximum, never a target; an empty day beats a weak post;
  * daily formats: AI_HACK (save / use: a method, prompt, workflow or concrete new capability the reader can try now)
    and MEME_TREND (send / comment: absurd AI behaviour, weird gadgets, internet culture, a true premise that sounds fake);
  * NEWS_INSIGHT only for a real evergreen method or decision principle - at most one a week;
  * ordinary news never gets a daily slot: it waits for the WEEKLY news recap (AI + GADGET + VIRAL) or is dropped.

Before this module the Instagram lane was news-first: every NEWS story the Telegram pipeline rated MAJOR went straight to the
Creative Director, and `derive_content_archetype` turned anything that was not HOW_TO / TREND into a standalone `news_insight` post.
Earnings reports, funding rounds and CI tags were rated MAJOR in the real 5-11 Aug 2026 window.

This module reads what a candidate IS before any generation (pure, deterministic, no model call): an instruction, a tool, an AI
misbehaviour story, an oddity, internet culture, business news, a release tag, a paper. That read decides which product the item may
enter and ranks the day's shortlist. It is a recall + suppression layer, not the editor: a daily slot is only used when the existing
pre-generation Director decision agrees with the planned format (see `format_from_editorial_decision`), so a weak or mis-read item
leaves the slot empty instead of becoming filler."""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FeedFormat(StrEnum):
    AI_HACK = "ai_hack"
    MEME_TREND = "meme_trend"
    NEWS_INSIGHT = "news_insight"
    WEEKLY_NEWS = "weekly_news"  # never a daily post; eligible for the weekly recap only
    REJECT = "reject"


DAILY_FORMATS = (FeedFormat.AI_HACK, FeedFormat.MEME_TREND, FeedFormat.NEWS_INSIGHT)
DAILY_MAX_POSTS = 2
DAILY_MAX_PER_FORMAT = {FeedFormat.AI_HACK: 1, FeedFormat.MEME_TREND: 1, FeedFormat.NEWS_INSIGHT: 1}
WEEKLY_MAX_NEWS_INSIGHT = 1
DAILY_SHORTLIST_PER_FORMAT = 3  # how many candidates a slot may try (each try is one Director decision) before it stays empty

# the Creative Director archetype each daily format is generated as (services.instagram_creative_director.derive_content_archetype)
ARCHETYPE_BY_FORMAT = {FeedFormat.AI_HACK: "ai_hack", FeedFormat.MEME_TREND: "trend_generative", FeedFormat.NEWS_INSIGHT: "news_insight"}
FORMAT_BY_ARCHETYPE = {v: k for k, v in ARCHETYPE_BY_FORMAT.items()}


@dataclass(frozen=True)
class FeedCandidate:
    id: str
    title: str
    summary: str = ""
    source_name: str = ""
    source_type: str = ""
    category: str = ""
    views: int | None = None
    coverage: int = 1  # how many events / sources carry this story (Story Memory event_count) - the weekly "worth remembering" proxy
    # viral story strength + actuality (services.instagram_viral_story_gate) - only signals that exist in production data
    published_at: datetime | None = None  # the ARTICLE's time (never assumed to be the event's)
    story_first_seen: datetime | None = None  # the earliest coverage of this same EVENT in its story cluster (title-similar members)
    independent_sources: int = 1  # distinct sources covering this same event in the last 72 hours
    story_events_24h: int = 1  # growth: members covering this same event collected in the last 24 hours
    on_hacker_news: bool = False  # a confirmed member came from the Hacker News front page
    forwards: int | None = None  # Telegram sources only
    reactions: int | None = None  # Telegram sources only


OUTSIDE_WORLD_REASON = "outside the account's world (not AI / tech / gadgets / internet culture)"


@dataclass(frozen=True)
class FeedRead:
    format: FeedFormat
    strong: bool
    kinds: tuple[str, ...]
    reason: str
    rank: float


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.IGNORECASE)


# --- what the item IS (title + lead; English and Russian) -------------------------------------------------------------------------
_RELEASE_TAG = _rx(r"^\s*v?\d+(\.\d+){1,3}([-.]?(rc|alpha|beta)[\w.]*)?\s*(:|$)", r"ciflow/", r"^[\w./-]+[=:]{1,2}\s*v?\d+\.\d+",
                   r"^\s*release:\s*v?\d", r"^[\w-]+/[\w.-]+:\s*v?\d")
_DIGEST = _rx(r"^(утро|вечер)\s+\w+:?\s*$", r"немного новостей", r"^\w+ новости \w+:?$", r"^другие новости", r"\bdaily:\s", r"weekly meme roundup",
              r"^следим за новостями", r"^deals?:", r"\bdeals and freebies\b", r"^today.s .*(deals|hints and answers)", r"\bpodcast\b",
              r"\bjobs roundup\b", r"^what are you (doing|working on)", r"календарь релизов", r"^tech (life|now)$")
_LISTING = _rx(r"^the best .* of 20\d\d", r"\bexpert tested\b", r"\bstocks? to buy\b", r"\bto buy (right )?now\b", r"\bshould you buy\b", r"\breview:?\s*$", r"\breview\b.*$(?<=review)", r"^\d+ .*(gadgets|apps|tools) (that|to|for)",
               r"\bon sale\b", r"\b\d+% off\b", r"\bprice drop\b", r"обзор ")
_PAPER = _rx(r"^(we|this paper|in this paper)\b", r"\bwe (propose|present|introduce)\b", r"^existing .* models? rel(y|ies)", r"\bbenchmark(ing)? llm\b")
_BUSINESS = _rx(
    r"\breports? q[1-4]\b", r"\bq[1-4] (revenue|results|earnings|profit|sales)", r"\brevenue (up|down|rose|fell)\b", r"\bearnings\b",
    r"\braised? (an? )?\$\d", r"\braises? \$\d", r"\bseries [a-h]\b", r"\bvaluation\b", r"\bipo\b", r"\bshares? (fall|sink|drop|jump|rise|plummet)",
    r"\bstock\b", r"\bbond sale\b", r"\bacquires?\b", r"\bacquisition\b", r"\bto (buy|acquire)\b", r"\bmerger\b", r"\btender offer\b",
    r"\bbought by\b", r"\btakeover\b", r"\bsells? for \$", r"\bin sales\b", r"\bmarket (cap|share)\b", r"\bprofit\b",
    r"\blays? off\b", r"\blayoffs\b", r"\bcuts? .*(jobs|staff|employees|workforce)", r"\bsteps? down\b", r"\bappoints?\b", r"\bis leaving\b",
    r"\bleaves?\b.*\b(role|company|openai|google|x)\b", r"\bsues?\b", r"\blawsuit\b", r"\bcourt\b", r"\bsettle(s|ment)?\b", r"\bfined?\b",
    r"\bantitrust\b", r"\bsanction", r"\btariff", r"\bregulat", r"\blegislation\b", r"\bsenate\b", r"\bcongress\b", r"\bgovernor\b", r"\bfcc\b",
    r"\bgdp\b", r"\binvest(s|ment|ing)? \$\d", r"\bdata cent(er|re)s?\b", r"\bfundraising\b", r"\bfund\b.*\$\d",
    r"\bвыручк", r"\bприбыл", r"\bквартал", r"\bпривл[её]к(ла|ло|ли)? .*(\$|млн|млрд)", r"\bоценк[аеиу] в\b", r"\bакци[ийяе]\b", r"\bсделк",
    r"\bкупит|\bпокупк|\bвыкуп|\bпрода(ст|ёт|ет|ла|л)\b|\bдочк", r"\bбанкрот", r"\bувольн|\bсокращ", r"\bпокинул|\bуходит|\bуш[её]л с пост", r"\bиск\b|\bсуд\b|\bсуда\b|\bсудом",
    r"\bштраф", r"\bзакон|\bрегулир|\bминцифры|\bфас\b|\bфсб\b|\bсанкци", r"\bпошлин", r"\bцод\b|\bдата-центр", r"\ballegations?\b",
)
# addressed to the READER (a method they can apply), not a maker's diary ("я собрал 33 агента", "как мы внедрили ...")
_INSTRUCTION = _rx(
    r"\bhow to\b", r"\bhere.s how\b", r"\bguide\b", r"\btips?\b", r"\btricks? (to|for|that will)\b", r"\b\d+ tricks\b",
    r"\bin \d+ (easy |simple )?steps\b", r"\bstep[- ]by[- ]step\b",
    r"\btry (it|this)\b", r"\bcut my\b", r"\bi (tried|tested)\b", r"\bwithout (a )?subscription\b", r"\bset ?up\b",
    r"\bturn (your|off|on)\b", r"\bdisable\b", r"\bfree online course\b", r"\bworkflow\b", r"\bprompts?\b", r"\bi use \w+ to\b",
    r"\bкак (сделать|настроить|включить|отключить|использовать|снизить|сэкономить|вернуть|найти|сжать|ускорить|убрать)\b", r"\bинструкци",
    r"\bгайд\b", r"\bпошагов", r"\bза \d+ шаг", r"\bнастройк", r"\bлайфхак", r"\bпромпт", r"\bя (проверил|решил проверить)\b",
    r"\bпопробуй", r"сэкономил\w* \d+", r"за \d+ минут", r"(?<![-\w])скилл", r"\bрабочий процесс", r"\bперестал\w* здороваться",
)
_PROMO = _rx(r"розыгрыш", r"промокод", r"\bскидк", r"\bреклам[аы] ", r"оплатит?ь|оплата", r"российской картой", r"\bsponsored\b", r"\bgiveaway\b",
             r"\bнаш (сервис|продукт)", r"\bour (platform|product|service)\b")
# the AI industry's own incidents (a lab, a safety test, a "rogue" cyber story) are AI news for the recap; the send-worthy AI stories
# happen to ordinary people - a gym booking, a farmer's field, a road camera
_AI_INDUSTRY = _rx(r"\brogue\b", r"\bcyber", r"\bhacking spree\b", r"\battempted hack\b", r"\bhack(ing)? attempts?\b", r"\ba hacker now\b",
                   r"\bstartup\b", r"\bsecurity\b", r"\bbreach\b", r"\bhugging ?face\b", r"\bescaped\b", r"из-под контроля",
                   r"\bсбежал\w* из\b", r"\bзаданных границ", r"\bпопытк\w* взлома")
# security news (vulnerabilities, malware, attackers) is never a meme, however it is phrased
_SECURITY = _rx(r"\bvulnerab", r"\bmalware\b", r"\bexploit", r"\bphishing\b", r"\bhackers\b", r"\bbackdoor", r"\bflaw\b", r"\bbug\b",
                r"\bcve\b", r"\buncovered\b", r"\bуязвим", r"\bвредонос", r"\bхакер", r"\bфишинг", r"\bбэкдор")
# the headline itself hands the reader the method ("how to ...", "here's how") - stronger than a guide or a diary entry
_EXPLICIT_HOWTO = _rx(r"\bhow to\b", r"\bhere.s how\b", r"\bin \d+ (easy |simple )?steps\b",
                      r"\bкак (сделать|настроить|включить|отключить|использовать|снизить|сэкономить|вернуть|найти|сжать|ускорить|убрать)\b")
# a concrete, measured result or a mainstream tool makes a hack stronger
_MEASURED = _rx(r"\d+\s?(%|x\b|раз|минут|minutes?|hours?|час|секунд|seconds?)", r"\bfrom hours\b", r"\+\d+")
_MAINSTREAM_TOOL = _rx(r"\bchatgpt\b", r"\bclaude\b", r"\bgemini\b", r"\bcopilot\b", r"\bphotoshop\b", r"\badobe\b", r"\biphone\b", r"\bgmail\b",
                       r"\bgoogle (docs|maps|photos)\b")
# a safety test in a lab is AI news, not a meme: the send-worthy stories happen to ordinary people
_LAB_SAFETY = _rx(r"\btest(s|ing|ers|ed)?\b", r"\bsandbox", r"\bcontainment\b", r"\bsafety\b", r"\bresearchers?\b", r"\baisi\b",
                  r"\bevaluat", r"\bred[- ]team", r"\bтест", r"песочниц", r"исследовател", r"безопасност")
_AI_TOOL = _rx(
    r"\bchatgpt\b", r"\bclaude\b", r"\bgemini\b", r"\bgemma\b", r"\bcopilot\b", r"\bcodex\b", r"\bcursor\b", r"\bmidjourney\b", r"\bflux\b",
    r"\bsora\b", r"\bkimi\b", r"\bdeepseek\b", r"\bqwen\b", r"\bgrok\b", r"\bperplexity\b", r"\bollama\b", r"\bllm", r"\bgpt[- ]?\d", r"\bopus\b",
    r"\bgenmoji\b", r"\bapple intelligence\b", r"\bai\b", r"\bagents?\b", r"\bnotebooklm\b", r"\bobsidian\b", r"\bwhisper\b", r"\bmuse\b",
    r"\bнейросет", r"\bнейронк", r"\bии\b", r"\bии-", r"\bагент(?!ств)", r"\bллм\b", r"\bязыков(ая|ые) модел", r"\bprompts?\b", r"\bпромпт",
)
_AI_MISBEHAVIOUR = _rx(
    r"\b(ai|agent|bot|chatbot|model|claude|chatgpt|gemini|deepseek|kimi)\b.*\b(hack(ed|s)?|deleted|escaped|broke out|went rogue|lied|cheated|"
    r"kicked|impersonat|faked|refused|started a religion|convinced people|snitch|sabotag)",
    r"\b(hack(ed|s)?|deleted|escaped|went rogue|kicked)\b.*\b(ai|agent|bot|chatbot)\b",
    r"\b(ии|нейросет\w*|агент(?!ств)\w*|модел\w*|бот\w*|claude|chatgpt|gemini|deepseek|opus|grok|kimi)\b[^.]{0,60}"
    r"\b(взломал|удалил|сбежал|убедил|перепутал|обманул|выгнал|вскрыл|подставил|отказал|испортил|уничтожил)",
    r"\b(взломал|удалил|сбежал|убедил|перепутал|выгнал)\w*[^.]{0,60}\b(ии|нейросет\w*|агент(?!ств)\w*)\b",
    r"послушав .*совет ии", r"вредн\w+ совет\w* ии", r"тайн\w+ .*доск\w* .*агент",
)
_ODDITY = _rx(
    r"\bviral\b", r"\bmeme\b", r"\bweird\b", r"\bbizarre\b", r"\bhilarious\b", r"\bfunny\b", r"\bsurreal\b", r"\bstrange\b", r"\babsurd\b",
    r"\baccidentally\b", r"\bturned into\b", r"\bturns (your )?\w+ into\b", r"\bdoubles as\b", r"\bfor the one\b", r"\bjust (for|because)\b",
    r"\bjoke\b", r"\brigged\b", r"\bcan .* run doom\b", r"\bdoom\b.*\b(runs?|ported|in)\b", r"\bported to\b", r"\bgrave\b", r"\bhamster\b",
    r"\bfake (chatbot|ai)\b", r"\bjust a guy\b", r"\bfrankenstein\b", r"\btissue box\b", r"\bwater-cooled\b", r"\bstrava\b",
    r"\beveryone hates\b", r"\bbacklash\b", r"\bwill never\b", r"\bnobody\b.*\bsurprise\b",
    r"\bзавирус", r"\bмем", r"\bшуточн", r"\bкурь[её]з", r"\bстранн", r"\bнеобычн", r"\bради одного", r"\bв шутку", r"\bэнтузиаст", r"\bмоддер",
    r"\bпревратил|\bпревращает", r"\bзапустил\w* .*\b(doom|в браузер|в paint)", r"\bмогил", r"\bхомяк",
)
# KAGE-FIRST VIRAL SELECTION (founder decision 2026-09-26). The viral slot is for TECH / AI / GADGET / PLATFORM / GAMING stories that are
# themselves weird - never 'a viral internet story that happens to be available'. Order: KAGE relevance, then story value, then viral
# potential; a meme score never compensates for missing relevance. Two things are read separately:
#   - DISTRIBUTION words say how a story SPREAD (viral, meme, brainrot, trend) - they are not an event;
#   - the KAGE CORE is technology that is part of the HEADLINE's event. Creator / distribution words (streamer, YouTube, TikTok, internet,
#     online) are where a story happened, not what it is about, so they never count as core.
_DISTRIBUTION = _rx(r"\bviral\b", r"\bgo(es|ing)? viral\b", r"\bmemes?\b", r"\bbrainrot\b", r"\btrend(ing|s)?\b", r"\bзавирус",
                    r"\bмем", r"\bтренд", r"\bбрейнрот")
_KAGE_CORE_TECH = _rx(
    r"\b(app|apps|software|firmware|update|feature|bug|glitch|algorithm|server|servers|api|chip|browser|windows|macos|ios|android|linux|"
    r"steam|console|xbox|playstation|nintendo|gpu|mod|modder|game engine|video game|emulator|robot|robots|drone|drones|satellites?|starlink|"
    r"strava|fitbit|tracker|sensor|smartwatch|gps|arduino|raspberry pi|3d[- ]print\w*|google|apple|microsoft|openai|anthropic|nvidia|"
    r"samsung|tesla|amazon|netflix|spotify|discord|telegram|whatsapp|wikipedia|doom|website|password|cyber\w*|hack(ed|er|ers|s)?|"
    r"malware|chatbot|bot|bots|algorithm|cable|cables|fiber|fibre|data ?cent(er|re)s?|5g|wi-?fi|bluetooth|usb|battery|batteries|charger)\b",
    r"\bприложени|\bпрограмм|\bобновлен|\bпрошивк|\bбаг\b|\bглюк|\bалгоритм|\bсервер|\bбраузер|\bсмартфон|\bноутбук|\bконсол|"
    r"\bвидеокарт|\bпроцессор|\bробот|\bдрон|\bспутник|\bсайт|\bмоддер|\bэмулятор|\bвзлом|\bхакер|\bтелеграм|\bбот\w*|\bчат-?бот|"
    r"\bгаджет|\bустройств|\bплатформ|\bсервис|\bstarlink|\bпароль|\bкабел|\bдата-?центр|\bаккумулятор|\bзарядк",
)


def kage_core(text: str) -> list[str]:
    """The KAGE technology families present in `text` (a headline): what makes the EVENT a tech / AI / gadget / platform story."""
    families = []
    if _has(_AI_TOOL, text) or _has(_AI_MISBEHAVIOUR, text):
        families.append("ai")
    if _has(_GADGET, text):
        families.append("gadget")
    if _has(_KAGE_CORE_TECH, text):
        families.append("software_platform_security_gaming")
    return families


def event_oddity(text: str) -> bool:
    """A strange EVENT in `text` - an oddity signal once the words that only describe spreading (viral, meme, trend) are removed."""
    return _has(_ODDITY, _DISTRIBUTION.sub(" ", text))


_CULTURE_SOURCE = _rx(r"know your meme", r"pc gamer", r"\b404 media\b", r"rozetked", r"код дурова", r"kotaku", r"polygon")
# an evergreen METHOD or decision principle (not merely an explainer): mistakes to avoid, rules, lessons, how to choose
_EVERGREEN = _rx(r"\b\d+ (ошибок|ошибки|правил|правила|уроков|принцип\w*|mistakes|lessons|rules|principles)\b", r"\bошибки,? которые\b",
                 r"\bmistakes (to avoid|you)\b", r"\blessons learned\b", r"\bhow to choose\b", r"\bкак выбрать\b", r"\bchecklist\b", r"\bчек-?лист",
                 r"\bчто учесть\b", r"\bwhat to consider\b")
_TECH = _rx(r"\b(ai|tech|app|apps|phone|iphone|android|pixel|galaxy|laptop|pc|gpu|chip|console|steam|xbox|playstation|nintendo|game|gaming|"
            r"software|internet|google|apple|microsoft|meta|openai|anthropic|spotify|tiktok|youtube|reddit|telegram|whatsapp|robot|drone|"
            r"strava|fitbit|tracker|smartwatch|gps|sensor|arduino|raspberry pi|3d[- ]print\w*|website|online|streamer|cable|satellite|server)\b",
            r"\bсмартфон|\bноутбук|\bприложени|\bигр|\bконсол|\bвидеокарт|\bпроцессор|\bинтернет|\bтелеграм|\bробот|\bгаджет|\bкабел|\bспутник|"
            r"\bсайт|\bстример")
_GADGET = _rx(r"\b(phone|iphone|pixel|galaxy|fold|flip|watch|airpods|earbuds|headphones|glasses|laptop|macbook|tablet|ipad|console|switch|"
              r"steam (deck|machine|controller)|handheld|camera|tv|speaker|keyboard|mouse|gpu|rtx|ssd|drone|robot|gadget|device)\b",
              r"\bсмартфон|\bноутбук|\bчасы\b|\bнаушник|\bочк[иов]|\bпланшет|\bконсол|\bвидеокарт|\bгаджет|\bустройств|\bколонк|\bтелевизор|"
              r"\bклавиатур|\bдрон|\bробот")


def _has(pattern: re.Pattern[str], text: str) -> bool:
    return bool(pattern.search(text))


def _clean_title(title: str, source: str) -> str:
    title = re.sub(r"[*_#]+", "", " ".join(title.split())).strip()
    if source.startswith("google news"):
        title = re.sub(r"\s+-\s+[^-]{2,60}$", "", title)  # "Headline - Outlet"
    return title


def read_candidate(candidate: FeedCandidate) -> FeedRead:
    """What this item is, and the one product it may enter - read before any generation.

    The HEADLINE must carry the hook: instruction / oddity / AI-misbehaviour signals are read from the title only. The lead adds
    context (is it about an AI tool, tech, a gadget) but can never turn an ordinary headline into a daily post - a Telegram post's
    body often bundles several stories and promos."""
    source = candidate.source_name.lower()
    title = _clean_title(candidate.title, source)
    lead = " ".join((candidate.summary or "").split())[:400]
    context = f"{title} {lead}"
    kinds: list[str] = []
    if source.startswith("arxiv") or _has(_PAPER, context):
        kinds.append("research_paper")
    if _has(_RELEASE_TAG, title) or source.endswith(("releases", "github")):
        kinds.append("release_tag")
    if _has(_DIGEST, title):
        kinds.append("digest")
    if _has(_LISTING, title):
        kinds.append("listing")
    telegram = candidate.source_type.upper() == "TELEGRAM"
    if len(title) < (45 if telegram else 18) or not re.search(r"[A-Za-zА-Яа-яЁё]{3}", title):
        kinds.append("teaser")  # "Вот это ИИ!", "Бесплатно без лимитов" - a teaser headline says nothing on its own
    if _has(_PROMO, title):
        kinds.append("promo")
    for name, pattern, text in (("business", _BUSINESS, title), ("instruction", _INSTRUCTION, title), ("ai_tool", _AI_TOOL, context),
                                ("ai_misbehaviour", _AI_MISBEHAVIOUR, title), ("lab_safety", _LAB_SAFETY, title),
                                ("ai_industry", _AI_INDUSTRY, title), ("security", _SECURITY, title), ("oddity", _ODDITY, title),
                                ("evergreen", _EVERGREEN, title),
                                ("measured", _MEASURED, title), ("mainstream_tool", _MAINSTREAM_TOOL, title),
                                ("explicit_howto", _EXPLICIT_HOWTO, title),
                                ("tech", _TECH, context), ("gadget", _GADGET, context)):
        if _has(pattern, text):
            kinds.append(name)
    if _has(_CULTURE_SOURCE, source):
        kinds.append("culture_source")
    ks = set(kinds)
    # small tie-breakers only - the read decides the product, these order equals: wider coverage, some audience response (Telegram views
    # exist for a few sources only, so they are capped), and an aggregator-only copy (no real outlet carried it) ranks below real outlets
    bonus = min(0.45, 0.15 * math.log2(max(1, candidate.coverage)))
    bonus += min(0.15, math.log10(candidate.views) / 30) if candidate.views and candidate.views > 1 else 0.0
    bonus -= 0.3 if source.startswith("google news") else 0.0

    def read(fmt: FeedFormat, strong: bool, reason: str, rank: float) -> FeedRead:
        return FeedRead(fmt, strong, tuple(kinds), reason, round(rank + bonus, 3))

    if ks & {"research_paper", "release_tag", "digest", "listing", "teaser", "promo"}:
        return read(FeedFormat.REJECT, False, "not a standalone story (paper / release tag / digest / deals, review or promo / teaser)", 0.0)
    if "ai_misbehaviour" in ks and ks & {"lab_safety", "ai_industry", "security"}:
        return read(FeedFormat.WEEKLY_NEWS, False, "an AI-industry incident (a lab, a safety test, a rogue-agent cyber story) - recap news, not a meme",
                    min(3.0, math.log2(max(1, candidate.coverage)) + 0.1))
    if "ai_misbehaviour" in ks:
        return read(FeedFormat.MEME_TREND, True, "absurd AI behaviour in ordinary life - a story people send", 2.6)
    ai_in_headline = _has(_AI_TOOL, title)
    if "instruction" in ks and ai_in_headline and "business" not in ks:
        return read(FeedFormat.AI_HACK, True, "an AI method / tool the reader can try now",
                    2.5 + 0.4 * ("measured" in ks) + 0.2 * ("mainstream_tool" in ks) + 0.2 * ("explicit_howto" in ks))
    if "instruction" in ks and "ai_tool" in ks and "business" not in ks:
        # the tool is only in the lead ("...how to live" over an AI essay): a candidate for stage 2, never a slot on its own
        return read(FeedFormat.AI_HACK, False, "a how-to whose AI side is not in the headline - needs its stored evidence", 0.9)
    if "oddity" in ks and not ks & {"business", "security"}:
        # KAGE-first: the technology must be part of the headline's event; virality alone never opens the viral slot
        core = kage_core(title)
        if not core:
            return read(FeedFormat.REJECT, False, "viral / strange, but technology is incidental - not a KAGE story (no tech core in the event)", 0.0)
        if not event_oddity(title):
            # only a DISTRIBUTION word ('... becomes a meme'): the event itself may still be strange - stage 2 reads its body
            return read(FeedFormat.MEME_TREND, False, "a tech story that SPREAD - the event itself is not yet shown to be strange", 0.9)
        return read(FeedFormat.MEME_TREND, True, "a strange / funny event whose technology is central (KAGE core: " + ", ".join(core) + ")",
                    2.3 + 0.2 * ("culture_source" in ks))
    if "evergreen" in ks and "ai_tool" in ks and "business" not in ks:
        return read(FeedFormat.NEWS_INSIGHT, True, "an evergreen explanation / principle about AI", 1.5)
    if "instruction" in ks and "business" not in ks:
        return read(FeedFormat.AI_HACK, False, "a how-to without an AI tool", 0.8)
    if ks & {"tech", "ai_tool", "gadget"}:
        return read(FeedFormat.WEEKLY_NEWS, False, "ordinary tech / AI news - weekly recap material at most, never a daily post",
                    min(3.0, math.log2(max(1, candidate.coverage)) + 0.1))
    return read(FeedFormat.REJECT, False, OUTSIDE_WORLD_REASON, 0.0)


# --- stage 2: the shortlist read again with its strongest stored evidence -----------------------------------------------------------
STAGE1_PER_FORMAT = 6  # cheap-screened candidates per daily format that get their stored evidence loaded
STAGE1_NEWS_PROBES = 4  # the widest-covered ordinary headlines: a bizarre premise can hide behind a plain headline
EVIDENCE_CHARS = 1500

# the body tells the READER to do something with a tool (the method the headline only hints at)
_BODY_METHOD = _rx(r"\bstep \d\b", r"\bfirst,? (open|go to|tap)\b", r"\b(open|tap|select|choose|type|paste|enter) (the|your|a)\b",
                   r"\bgo to settings\b", r"\bprompt\b", r"\bshortcut\b", r"\bhere.s how\b", r"\bhow to\b",
                   r"\bшаг \d", r"\b(откройте|нажмите|выберите|введите|вставьте|перейдите)\b", r"\bпромпт", r"\bинструкци")


# a body upgrade needs a NAMED AI tool or feature - a passing "AI" in an article about something else is not the method
_NAMED_AI_TOOL = _rx(r"\bchatgpt\b", r"\bclaude\b", r"\bgemini\b", r"\bcopilot\b", r"\bcodex\b", r"\bcursor\b", r"\bmidjourney\b",
                     r"\bflux\b", r"\bsora\b", r"\bperplexity\b", r"\bgenmoji\b", r"\bimage playground\b", r"\bapple intelligence\b",
                     r"\bgalaxy ai\b", r"\bnotebooklm\b", r"\bgrok\b", r"\bdeepseek\b", r"\bqwen\b", r"\bkimi\b", r"\bollama\b",
                     r"\bwhisper\b", r"\bllm\b", r"\bgpt[- ]?\d", r"\bнейросет", r"\bчат-?бот")


def stage_one_shortlist(reads: Sequence[tuple[FeedCandidate, FeedRead]]) -> list[tuple[FeedCandidate, FeedRead]]:
    """The few candidates worth loading evidence for: the top daily-format reads (strong or weak - a weak read may only lack what the
    body carries) and a handful of the widest-covered ordinary headlines. Everything else never leaves the cheap screen."""
    picked: list[tuple[FeedCandidate, FeedRead]] = []
    for fmt in DAILY_FORMATS:
        ranked = sorted((r for r in reads if r[1].format is fmt), key=lambda r: (not r[1].strong, -r[1].rank))
        picked.extend(ranked[:STAGE1_PER_FORMAT])
    news = sorted((r for r in reads if r[1].format is FeedFormat.WEEKLY_NEWS and "business" not in r[1].kinds),
                  key=lambda r: -r[0].coverage)
    picked.extend(news[:STAGE1_NEWS_PROBES])
    return picked


def read_with_evidence(candidate: FeedCandidate, first: FeedRead, evidence: str) -> FeedRead:
    """Stage 2: the same product read, now with the candidate's stored source material (article text, source body, sibling
    coverage of the same Story, research facts). The headline still decides what the item is NOT (a tag, a promo, business news);
    the body may supply what the headline lacks, or reveal that a 'hack' story is a security incident."""
    if first.format is FeedFormat.REJECT or not evidence.strip():
        return first
    body = " ".join(evidence.split())[:EVIDENCE_CHARS]
    if candidate.source_type.upper() == "TELEGRAM":
        body = body[:400]  # a channel post bundles several stories after its first paragraph
    has = {name: _has(pattern, body) for name, pattern in (
        ("ai_tool", _AI_TOOL), ("method", _BODY_METHOD), ("misbehaviour", _AI_MISBEHAVIOUR), ("lab", _LAB_SAFETY),
        ("industry", _AI_INDUSTRY), ("security", _SECURITY), ("tech", _TECH), ("gadget", _GADGET))}
    kinds = tuple(dict.fromkeys([*first.kinds, *(f"body_{k}" for k, v in has.items() if v)]))

    def upgrade(fmt: FeedFormat, reason: str, rank: float) -> FeedRead:
        return FeedRead(fmt, True, kinds, f"{reason} (stored evidence)", round(rank, 3))

    if first.strong:
        return FeedRead(first.format, True, kinds, first.reason, first.rank)
    if "security" in first.kinds:
        return FeedRead(first.format, False, kinds, first.reason, first.rank)  # a security headline never becomes a hack or a meme
    if first.format is FeedFormat.AI_HACK and _has(_NAMED_AI_TOOL, body) and has["method"]:
        return upgrade(FeedFormat.AI_HACK, "a method the reader can try - the AI feature is named in the body, not the headline",
                       first.rank + 1.7)
    if (first.format is FeedFormat.MEME_TREND and kage_core(candidate.title) and kage_core(body) and event_oddity(body)
            and not has["security"]):
        # KAGE-first: a weak viral read (a tech headline that only SPREAD) needs the body to show a genuinely strange tech event
        return upgrade(FeedFormat.MEME_TREND, "a tech story whose body shows a strange event", first.rank + 1.8)
    if first.format is FeedFormat.WEEKLY_NEWS and has["misbehaviour"] and not (has["lab"] or has["industry"] or has["security"]):
        return upgrade(FeedFormat.MEME_TREND, "an ordinary headline over absurd AI behaviour in ordinary life", 2.4)
    return FeedRead(first.format, first.strong, kinds, first.reason, first.rank)


def format_from_editorial_decision(decision: Mapping | None) -> FeedFormat | None:
    """The existing pre-generation Director decision, mapped to the feed product. `None` = no decision.

    Mirrors `services.instagram_creative_director.derive_content_archetype` exactly (a test holds them together), so the format a
    slot planned is the archetype the Creative Director will generate. The one narrowing: `news_insight` needs an EXPLAINER /
    EVERGREEN_VALUE angle - any other plain news angle maps to WEEKLY_NEWS and never takes a daily slot."""
    if not decision:
        return None
    intent, origin, kind = decision.get("angle_intent"), decision.get("origin"), decision.get("opportunity_type")
    if intent == "HOW_TO" or kind in ("PRODUCT", "EVERGREEN"):
        return FeedFormat.AI_HACK
    if kind in ("NEWS_X_TREND", "PRODUCT_X_TREND") or origin == "TREND":
        return FeedFormat.MEME_TREND
    if intent in ("EXPLAINER", "EVERGREEN_VALUE"):
        return FeedFormat.NEWS_INSIGHT
    return FeedFormat.WEEKLY_NEWS


@dataclass(frozen=True)
class SlotPlan:
    format: FeedFormat
    shortlist: tuple[tuple[FeedCandidate, FeedRead], ...]  # tried in order; the first one the Director confirms takes the slot


def plan_daily_slots(
    reads: Iterable[tuple[FeedCandidate, FeedRead]], *, published_today: Mapping[FeedFormat, int] | None = None,
    news_insight_this_week: int = 0, exclude_ids: Iterable[str] = (),
    viral_gate: Callable[[FeedCandidate], bool] | None = None,
) -> list[SlotPlan]:
    """Open slots for today, AI_HACK first. Only STRONG reads are eligible - no filler. A day never exceeds DAILY_MAX_POSTS.

    `viral_gate` (services.instagram_viral_story_gate): a MEME_TREND read enters the viral slot only when the story itself is strong and
    current enough. A strong read that fails it stays good KAGE news (weekly recap material) - and when no story clears the bar the viral
    slot stays EMPTY: the schedule never lowers the bar to fill itself."""
    published = {fmt: int((published_today or {}).get(fmt, 0)) for fmt in DAILY_FORMATS}
    remaining = DAILY_MAX_POSTS - sum(published.values())
    excluded = set(exclude_ids)
    pool: dict[FeedFormat, list[tuple[FeedCandidate, FeedRead]]] = {fmt: [] for fmt in DAILY_FORMATS}
    for candidate, read in reads:
        if read.strong and read.format in pool and candidate.id not in excluded:
            if read.format is FeedFormat.MEME_TREND and viral_gate is not None and not viral_gate(candidate):
                continue
            pool[read.format].append((candidate, read))
    plans: list[SlotPlan] = []
    for fmt in DAILY_FORMATS:  # priority order: AI_HACK, MEME_TREND, then a rare NEWS_INSIGHT
        if remaining <= 0:
            break
        if published[fmt] >= DAILY_MAX_PER_FORMAT[fmt]:
            continue
        if fmt is FeedFormat.NEWS_INSIGHT and news_insight_this_week >= WEEKLY_MAX_NEWS_INSIGHT:
            continue
        ranked = sorted(pool[fmt], key=lambda item: -item[1].rank)
        seen_titles: set[str] = set()
        shortlist = []
        for candidate, read in ranked:
            key = _title_key(candidate.title)
            if key in seen_titles:
                continue
            seen_titles.add(key)
            shortlist.append((candidate, read))
            if len(shortlist) >= DAILY_SHORTLIST_PER_FORMAT:
                break
        if shortlist:
            plans.append(SlotPlan(fmt, tuple(shortlist)))
            remaining -= 1
    return plans


def _title_key(title: str) -> str:
    words = [w for w in re.findall(r"[a-zа-яё0-9]+", title.lower()) if len(w) > 3]
    return " ".join(sorted(words)[:6])


def recap_category(candidate: FeedCandidate, read: FeedRead) -> str:
    """AI / GADGET / VIRAL, judged on the headline (a lead often mentions a phone or a model in passing)."""
    kinds = set(read.kinds)
    title = _clean_title(candidate.title, candidate.source_name.lower())
    if kinds & {"oddity", "culture_source", "ai_misbehaviour"}:
        return "VIRAL"
    if _has(_AI_TOOL, title) or re.search(r"\b(deepmind|openai|anthropic|model|модел)\w*", title, re.IGNORECASE):
        return "AI"
    if _has(_GADGET, title):
        return "GADGET"
    if candidate.category.upper() == "AI":
        return "AI"
    if candidate.category.upper() in ("GADGETS", "HARDWARE"):
        return "GADGET"
    return "VIRAL" if "tech" in kinds else "OTHER"
