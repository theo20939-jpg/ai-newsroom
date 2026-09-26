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
    "has many facts. Use as many slides as there are DISTINCT grounded beats (at least 3, at most 7) - never stretch one fact over several "
    "slides, and never let two slides make the same point. Typical beats: the surprising concrete hook, how it started, what actually happened, "
    "the strongest extra detail, the result or one dry payoff. HOOK: slide 1 states the STRANGEST CONCRETE FACT of the event itself (the event "
    "and its surprising result), never how the story spread - no 'became a meme', 'went viral', 'the internet is discussing'; if the words meme / "
    "viral / internet were removed, the hook must still be interesting. HUMOUR: find the joke already present in the facts (factual absurdity, "
    "factual contrast, concise dry wording) - do not write jokes onto the story; no slogans, no 'the internet decided', no aphorisms about the "
    "internet, no 'plot twist', no claim the evidence does not make (e.g. that something happened 'again'). VOICE: write like a sharp human tech "
    "editor who is amused by the facts, in natural contemporary Russian - short, "
    "concrete, precise, clear on first read. The humour comes from the event itself and from plain factual juxtaposition, never from lines "
    "added to sound witty: at most ONE dry punch in the whole carousel, and a straight factual line is usually stronger. Every headline states "
    "one clear idea; every body adds a NEW grounded fact (never a paraphrase of its headline, never an attitude line with no information). Keep "
    "technical facts technical: access to a terminal is access to a terminal, not 'freedom'; do not give software or animals human motives. "
    "No invented dialogue in quotation marks - quotation marks mean a real quote from the evidence. No marketing slogans, motivational lines, "
    "bureaucratic nouns or translated-English syntax: translate roles and terms into Russian (an MRI physicist is 'физик, специалист по МРТ'), "
    "and a foreign person's name never opens a sentence as untranslated Latin text - name the role, or put the name where it reads naturally. "
    "Every factual claim comes ONLY from the evidence. Visuals: a suitable real photo where one exists; otherwise a GENERATED editorial image "
    "per slide - expressive, ironic, meme-adjacent scenes with clear negative space for the copy - never fact cells, stacked info boxes, step "
    "rectangles or dashboard panels. A generated picture NEVER shows a real person named in the story, a lookalike of them or a re-enactment "
    "of the reported incident: the generation_brief describes objects, places and a visual metaphor; any people in it are anonymous and "
    "unidentifiable (hands, backs, silhouettes) and are never described as the named person or their role in the event."
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


def _copy(slide: Any) -> str:
    return str(_get(slide, "slide_copy") or _get(slide, "text") or "")


def _body(slide: Any) -> str:
    return str(_get(slide, "slide_body") or _get(slide, "body") or "")


# how a story SPREAD (not what happened) - a hook built on these describes distribution, not the event (founder hook test)
_DISTRIBUTION_META = re.compile(r"(?i)\b(мем\w*|вирус\w*|завирус\w*|разош[её]л\w*|разошл\w*|тренд\w*|брейнрот\w*|brainrot|хайп\w*|"
                                r"интернет\w*|соцсет\w*|пользовател\w*|обсужда\w*|viral|meme\w*)")
# 'the internet' / 'users' / 'the audience' as the ACTOR of the story - an abstraction unless the evidence itself is about them
_COLLECTIVE_ACTOR = re.compile(r"(?i)\b(интернет\w*|соцсет\w*|пользовател\w*|аудитори\w*|зрител\w*)")
_COLLECTIVE_IN_EVIDENCE = re.compile(r"(?i)\b(internet|online|users?|social media|audience|viewers|интернет\w*|пользовател\w*|соцсет\w*|"
                                     r"аудитори\w*|зрител\w*)")
_RECURRENCE = re.compile(r"(?i)\b(снова|опять|вновь|повторно|вторую жизнь|второе дыхание|вернул\w*)\b")
_RECURRENCE_IN_EVIDENCE = re.compile(r"(?i)\b(again|back|return\w*|second|revive\w*|resurfac\w*|comeback|снова|вновь|опять|повторно|вернул\w*)")
# an incomplete construction: 'между' with a single term (no 'и' / 'с' in the clause), or a line that ends on a preposition / conjunction
_BETWEEN = re.compile(r"(?i)\bмежду\b([^.!?;:—]*)")
_DANGLING_END = re.compile(r"(?i)\b(в|на|с|со|по|к|ко|у|о|об|от|до|из|за|для|без|между|и|а|но|или)\s*[.!?…]?\s*$")
_PERSON_ROLE = re.compile(r"(?i)\b(streamer|youtuber|tiktoker|influencer|creator|player|athlete|ceo|founder|physicist|researcher|scientist|"
                          r"engineer|developer|artist|singer|rapper|actor|actress|politician|minister|president|host|owner|"
                          r"стример\w*|блогер\w*|игрок\w*|основател\w*|глав[аеуы]|физик\w*|исследовател\w*|учён\w*|инженер\w*|"
                          r"разработчик\w*|художник\w*|певиц\w*|певец\w*|актёр\w*|актер\w*|спортсмен\w*|политик\w*|министр\w*|"
                          r"президент\w*|ведущ\w*|владел\w*)\b")
_NAME = r"(?:[A-ZА-ЯЁ][\w'’\-]+(?:\s+(?:de|van|von|da|di|le|la)\b)?(?:\s+[A-ZА-ЯЁ][\w'’\-]+){0,2})"
_ROLE_THEN_NAME = re.compile(_PERSON_ROLE.pattern[4:] + r"(?:\s+(?:and|и)\s+\w+)?\s+(" + _NAME + r")")
_NAME_THEN_ROLE = re.compile(r"(" + _NAME + r"),\s+(?:an?\s+|the\s+)?(?:[\w\-]+\s+){0,2}" + _PERSON_ROLE.pattern[4:], re.IGNORECASE)
# a whole human figure in a generated picture's brief (hands alone are anonymous and allowed)
# nouns that in an image brief almost always mean a HUMAN in the picture. Left out on purpose: 'portrait' (the frame orientation) and
# metaphor-prone words ('athlete', 'figure', 'people' - 'a hamster posed like an athlete', 'the contrast between pet and athlete')
_HUMAN_FIGURE = re.compile(r"(?i)\b(person|man|woman|boy|girl|guy|face|faces|lookalike|look-alike|streamer\w*|skater\w*|player\w*|"
                           r"celebrity|человек\w*|мужчин\w*|женщин\w*|парн\w*|парен\w*|девушк\w*|лиц[оа]\b|стример\w*|игрок\w*)")


def named_people(evidence: list[str]) -> set[str]:
    """Real people the evidence NAMES (a proper name next to a person role: 'streamer and YouTuber IShowSpeed', 'NHL player Cole Caufield',
    'Thijs de Buck, an MRI physicist'). Organisations after a preposition ('researchers from Unit 42') are not people."""
    names: set[str] = set()
    for line in evidence:
        for match in _ROLE_THEN_NAME.finditer(line):
            names.add(match.group(match.lastindex).strip())
        for match in _NAME_THEN_ROLE.finditer(line):
            candidate = match.group(1).strip()
            if candidate.split()[0].lower() not in ("the", "a", "an", "this", "that", "his", "her"):
                names.add(candidate)
    return {n for n in names if len(n) >= 3}


def generated_person_risks(slides: list[Any], evidence: list[str]) -> list[str]:
    """A generated picture that could become a lookalike of / re-enactment with a NAMED real person: its brief names them, or - when the
    story names people - describes a whole human figure. Real source photos are not affected."""
    people = named_people(evidence)
    if not people:
        return []
    risks = []
    for index, slide in enumerate(slides, 1):
        if _get(slide, "media_source") != "generated":
            continue
        # what the PICTURE is asked to show (story_anchor states the story's fact, which may legitimately name the person)
        brief = " ".join(str(_get(slide, key) or "") for key in ("generation_brief", "visual_direction"))
        named = sorted(p for p in people if p.lower() in brief.lower())
        # a figure word in a simile ('a hamster posed like an athlete') describes something else, not a person in the picture
        figure = next((m for m in _HUMAN_FIGURE.finditer(brief)
                       if not re.search(r"(?i)\b(like|as|как|словно|будто)\s+(an?\s+)?(\w+\s+)?$", brief[max(0, m.start() - 24):m.start()])), None)
        if named or figure:
            risks.append(f"slide {index}: generated picture risks a likeness / re-enactment of a named real person ({', '.join(sorted(people))})"
                         f" - brief mentions {named or repr(figure.group(0))}; show objects, places or a metaphor, people only anonymous")
    return risks


def viral_copy_findings(slides: list[Any], evidence: list[str], *, caption: str = "") -> list[str]:
    """NATURAL RUSSIAN + CONCRETE FACT + OPTIONAL DRY PUNCH, as far as a deterministic editor can prove it without a phrase list."""
    from services.instagram_editorial_critic import anchors, critique

    texts = [*(_copy(s) for s in slides), *(_body(s) for s in slides), caption]
    problems = [f"invented quote (not in the evidence): '{q}' - retell it as narration without quotation marks"
                for q in invented_quotes(texts, evidence)]
    problems += [f.render() + " - a viral slide's body must add a new grounded fact" for f in critique(slides, evidence, caption=caption)
                 if f.code in _VIRAL_BLOCKING]
    if slides and (meta := _DISTRIBUTION_META.search(_copy(slides[0]))):
        problems.append(f"hook describes how the story spread ('{meta.group(0)}'), not the event - lead with its strangest concrete fact")
    corpus = " ".join(evidence)
    if not _COLLECTIVE_IN_EVIDENCE.search(corpus):
        problems += [f"abstract commentary: '{m.group(0)}' made an actor of the story, but the evidence never mentions it: {text.strip()[:90]!r}"
                     for text in texts for m in [_COLLECTIVE_ACTOR.search(text or "")] if m]
    if not _RECURRENCE_IN_EVIDENCE.search(corpus):
        problems += [f"unsupported implication: '{m.group(0)}' - the evidence does not say it happened before: {text.strip()[:90]!r}"
                     for text in texts for m in [_RECURRENCE.search(text or "")] if m]
    for text in texts:
        for clause in _BETWEEN.finditer(text or ""):
            if not re.search(r"(?i)\b(и|с|со)\b", clause.group(1)):
                problems.append(f"incomplete construction: 'между' needs two terms: {text.strip()[:90]!r}")
    problems += [f"incomplete line (ends on a preposition / conjunction): {line!r}" for line in (_copy(s) for s in slides) if _DANGLING_END.search(line)]
    for index in range(1, len(slides)):
        prev, cur = slides[index - 1], slides[index]
        prev_ref, cur_ref = str(_get(prev, "source_evidence") or "").strip(), str(_get(cur, "source_evidence") or "").strip()
        if prev_ref and prev_ref == cur_ref:
            # the same evidence item twice in a row: the second slide must bring a concrete detail NO earlier slide has shown
            earlier = set().union(*(anchors(f"{_copy(s)} {_body(s)}") for s in slides[:index]))
            new = anchors(f"{_copy(cur)} {_body(cur)}") - earlier
            if not new:
                problems.append(f"slides {index} and {index + 1} make the same point (both rest on the same evidence item and the second adds "
                                "no new concrete detail) - merge them or give the second a new fact")
    return list(dict.fromkeys(problems))


def assert_viral_copy_quality(slides: list[Any], evidence: list[str], *, caption: str = "") -> None:
    problems = viral_copy_findings(slides, evidence, caption=caption)
    if problems:
        raise ViralCopyQualityError("viral copy review: " + "; ".join(problems))


def substantive_facts(evidence: list[str]) -> list[str]:
    """Evidence items that carry a fact (not the media line, not page boilerplate)."""
    boiler = re.compile(r"(?i)^(source media:|you can help|part of a series|recent videos|\d+\s)")
    return [e for e in evidence if len(e.strip()) >= 40 and not boiler.search(e.strip())]


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


MIN_VIRAL_CAROUSEL_FACTS = 3


def viral_carousel_upgrade(decision: Any, *, planned_product: str | None, executable_formats: list[str],
                           evidence: list[str] | None = None) -> list[str]:
    """The viral signals that turn Phase A's `single` into a Carousel - empty when the Single stays (non-viral, not a single, carousel not
    executable, or - founder information rule - fewer than MIN_VIRAL_CAROUSEL_FACTS distinct facts: a carousel is never stretched)."""
    if _get(decision, "recommended_format") != "single" or "carousel" not in executable_formats:
        return []
    if evidence is not None and len(substantive_facts(evidence)) < MIN_VIRAL_CAROUSEL_FACTS:
        return []
    return viral_signals(decision, planned_product=planned_product)
