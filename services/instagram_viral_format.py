"""VIRAL STORIES EXPAND INTO CAROUSELS (founder product decision, 2026-09-26).

Single stays a valid format - for straightforward product updates, narrow factual announcements, short hard news and stories with one
useful editorial beat. But a story that is strange, funny, provocative, highly discussable or naturally "retellable" no longer defaults
to Single just because it has one core fact: it is retold as a swipeable Carousel of editorial beats.

The decision is deterministic and reads only what Phase A itself already decided (services.instagram_creative_director
.generate_editorial_decision - the frozen, grounded decision prompt is not touched):
  - Phase A chose `single`, and `carousel` is executable for this post;
  - the story carries a viral signal: the feed planner planned it as the TREND product (the internet-native slot), or Phase A read its
    angle as MEME / REACTION / DEBATE.
Everything else stays exactly as Phase A decided: a BREAKING / IMPACT / EXPLAINER / HOW_TO / PRODUCT_USE_CASE / COMPARISON /
EVERGREEN_VALUE single on a NEWS_INSIGHT or AI_HACK post remains a Single."""
from __future__ import annotations

import re
from typing import Any

from services.instagram_media_first import MediaFirstContractError

VIRAL_INTENTS = frozenset({"MEME", "REACTION", "DEBATE"})
VIRAL_PRODUCTS = frozenset({"TREND"})

# Founder copy review (2026-09-26): the first viral carousels sounded like an AI trying to be funny - an attitude line bolted onto almost
# every slide ('Очень серьёзный подход к жизни', 'Полноценная смена'), technical facts dramatised ('терминал' -> 'свобода'), translated
# syntax ('физик MRI'). The note asked for 'punchy' copy and a 'punchline' beat; it now asks for the principle instead:
# NATURAL RUSSIAN + CONCRETE FACT + OPTIONAL DRY PUNCH - never FACT + MANDATORY MEME LINE.
VIRAL_CAROUSEL_NOTE = (
    "VIRAL STORY - A RETELLING IN BEATS: this story is a carousel because it is unusual, funny, absurd or highly discussable - not because it "
    "has many facts. Retell it in 4-7 editorial beats, never as fact boxes: a strong factual hook, the concrete setup, what exactly happened, the "
    "surprising concrete detail, one clean conclusion. VOICE: write like a sharp human tech editor in natural contemporary Russian - short, "
    "concrete, precise, clear on first read. The humour comes from the event itself and from plain factual juxtaposition, never from lines "
    "added to sound witty: at most ONE dry punch in the whole carousel, and a straight factual line is usually stronger. Every headline states "
    "one clear idea; every body adds a NEW grounded fact (never a paraphrase of its headline, never an attitude line with no information). Keep "
    "technical facts technical: access to a terminal is access to a terminal, not 'freedom'; do not give software or animals human motives. "
    "No invented dialogue in quotation marks - quotation marks mean a real quote from the evidence. No marketing slogans, motivational lines, "
    "bureaucratic nouns or translated-English syntax: translate roles and terms into Russian (an MRI physicist is 'физик, специалист по МРТ'), "
    "and a foreign person's name never opens a sentence as untranslated Latin text - name the role, or put the name where it reads naturally. "
    "Every factual claim comes ONLY from the evidence. Visuals: a suitable real photo where one exists; otherwise a GENERATED editorial image "
    "per slide - expressive, ironic, meme-adjacent scenes with clear negative space for the copy - never fact cells, stacked info boxes, step "
    "rectangles or dashboard panels."
)


class ViralCopyQualityError(MediaFirstContractError):
    """A viral carousel's copy broke the voice contract in a way a deterministic editor can prove. A MediaFirstContractError, so the
    trigger's existing single bounded correction retry names exactly what to fix."""


_QUOTED = re.compile("[\u00ab\"\u201c]([^\u00bb\"\u201d]+)[\u00bb\"\u201d]")
_NORMALISE = re.compile(r"[^\w]+")
# the editorial critic's own findings that, for a viral retelling, mean a slide carries no new information
_VIRAL_BLOCKING = frozenset({"body_repeats_headline", "body_restates_headline_claim", "card_adds_no_new_information"})


def _norm(text: str) -> str:
    return _NORMALISE.sub(" ", text.lower().replace("ё", "е")).strip()


def invented_quotes(texts: list[str], evidence: list[str]) -> list[str]:
    """Quoted multi-word phrases that are not in the evidence: quotation marks promise a real quote. A single quoted word (a UI label,
    a product name) is a label, not dialogue, and is left alone."""
    corpus = _norm(" ".join(evidence))
    found = []
    for text in texts:
        for phrase in _QUOTED.findall(text or ""):
            if len(phrase.split()) >= 2 and _norm(phrase) not in corpus:
                found.append(phrase.strip())
    return found


def assert_viral_copy_quality(slides: list[Any], evidence: list[str], *, caption: str = "") -> None:
    """NATURAL RUSSIAN + CONCRETE FACT + OPTIONAL DRY PUNCH, as far as a deterministic editor can prove it without a phrase list:
    no invented quotes, and every body adds information (services.instagram_editorial_critic's own findings, blocking here)."""
    from services.instagram_editorial_critic import critique

    texts = [*(_get(s, "slide_copy") or "" for s in slides), *(_get(s, "slide_body") or "" for s in slides), caption]
    problems = [f"invented quote (not in the evidence): '{q}' - retell it as narration without quotation marks"
                for q in invented_quotes(texts, evidence)]
    problems += [f.render() + " - a viral slide's body must add a new grounded fact" for f in critique(slides, evidence, caption=caption)
                 if f.code in _VIRAL_BLOCKING]
    if problems:
        raise ViralCopyQualityError("viral copy review: " + "; ".join(problems))


def _get(decision: Any, name: str) -> Any:
    return decision.get(name) if isinstance(decision, dict) else getattr(decision, name, None)


def viral_signals(decision: Any, *, planned_product: str | None) -> list[str]:
    """Why a story reads as viral / meme-worthy (empty: it does not)."""
    signals = []
    if planned_product in VIRAL_PRODUCTS:
        signals.append(f"planned_product={planned_product}")
    intent = _get(decision, "angle_intent")
    if intent in VIRAL_INTENTS:
        signals.append(f"angle_intent={intent}")
    return signals


def viral_carousel_upgrade(decision: Any, *, planned_product: str | None, executable_formats: list[str]) -> list[str]:
    """The viral signals that turn Phase A's `single` into a Carousel - empty when the Single stays (non-viral, not a single, or carousel
    not executable for this post)."""
    if _get(decision, "recommended_format") != "single" or "carousel" not in executable_formats:
        return []
    return viral_signals(decision, planned_product=planned_product)
