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
from dataclasses import dataclass
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
    "has many facts. Before finalising, assign ONE distinct factual beat to each slide; if one slide is only the generic or the specific "
    "version of another (a claim, then the same claim with names or numbers), merge them - a new detail is not a new beat. "
    "Use as many slides as there are DISTINCT grounded beats (at least 4, at most 7) - never stretch one fact over several "
    "slides, and never let two slides make the same point. Typical beats: the surprising concrete hook, how it started, what actually happened, "
    "the strongest extra detail, the result or one dry payoff. HOOK: slide 1 states the STRANGEST CONCRETE FACT of the event itself (the event "
    "and its surprising result), never how the story spread - no 'became a meme', 'went viral', 'the internet is discussing'; if the words meme / "
    "viral / internet were removed, the hook must still be interesting; it is a complete natural Russian phrase, never telegraphic fragments "
    "glued with colons and dashes. Product and company names stay as they are, but a list of names is never a slide's copy - say it as a "
    "Russian sentence; prefer a Russian word to an anglicism (обновление, not апгрейд). The CAPTION summarises the story in natural Russian "
    "and adds context the slides do not already give; it never re-lists the slides' names or features. Its ending is factual or contextual: "
    "a closing dry line only when it is the carousel's ONLY dry payoff and never a generalised moral or lesson - if the slides already have the "
    "dry payoff, the caption adds no second one; a shorter factual caption beats a second joke. "
    "HUMOUR: find the joke already present in the facts (factual absurdity, "
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
    "unidentifiable (hands, backs, silhouettes) and are never described as the named person or their role in the event. "
    "FACTUAL STATUS: when the evidence gives targets different statuses (confirmed / still investigated / attempted / reported), each keeps "
    "its own status on every slide and in the caption - never one list or count that mixes them; 'which parts are confirmed' is its own beat. "
    "THE LAST SLIDE is a grounded point - a confirmed consequence, the company's response or the open factual question - never an invented "
    "debate, ethics question or poll the evidence does not raise."
)


class EditorialCorrectionRequired(MediaFirstContractError):
    """Founder decision 2026-09-26: correctable COPY problems of a viral carousel (language, clipped hook, product-name lists, redundancy,
    filler, anglicisms, ...) are collected - never fail-fast on the first - and sent back as ONE structured correction to the trigger's one
    existing correction retry. A MediaFirstContractError, so exactly that retry path applies; a second failure is terminal."""

    def __init__(self, findings: list[str], *, factual_contract: list[str] | None = None, factual_invariants: dict | None = None,
                 factual_repair: list[str] | None = None):
        self.findings = list(findings)
        # founder task 2026-09-27: what the version sent to the correction got right factually - the correction may not lose it
        self.factual_contract = list(factual_contract or [])
        self.factual_invariants = dict(factual_invariants or {})
        # founder decision 2026-09-27: REPAIRABLE target-status findings of the first version (services.instagram_factual_status
        # .repair_contract) - the corrected version must pass the same hard gate, or the post stops
        self.factual_repair = list(factual_repair or [])
        super().__init__("editorial correction required: " + "; ".join(self.findings))

    @property
    def correction_note(self) -> str:
        lines = "\n".join(f"{i}. {finding}" for i, finding in enumerate(self.findings, 1))
        ledger = ("\nTARGET STATUS (from the evidence, keep exactly): " + "; ".join(self.factual_contract)) if self.factual_contract else ""
        if self.factual_repair:
            ledger += ("\nFACTUAL STATUS REPAIR (the previous version stated a target's status wrongly; the corrected version is checked by the "
                       "same hard status gate and stops if any claim below is still wrong). Fix ONLY these claims plus the editorial findings "
                       "listed after them: do not introduce new facts, do not merge targets, do not strengthen verbs, do not remove the "
                       "chronology, do not paraphrase precise status language merely for stylistic uniqueness.\n"
                       + "\n".join(f"- {line}" for line in self.factual_repair))
        return ("EDITORIAL CORRECTION (your one correction attempt). The previous version was rejected by the editorial review. Rewrite the "
                "copy so that EVERY finding below is fixed - and change ONLY what the findings name. You may merge, reorder or drop slides to "
                "remove repetition (4-7 slides, each a distinct grounded beat) - never keep a slide only to preserve the count. Keep product and "
                "company names as they are; turn a list of names into a natural Russian sentence. Do not add any fact the evidence does not "
                "contain, and do not replace a finding with a new slogan.\nFACTUAL PRESERVATION (binding - a correction that breaks it is "
                "rejected): preserve every target's status exactly; never merge a confirmed and a not-confirmed target into one claim, list or "
                "count; never strengthen a verb (interaction or access is not 'взлом'); never remove the chronology (when it happened, when it "
                "was disclosed); keep short exact status wording ('подтвердила доступ', 'расследование продолжается', names, dates) instead of "
                "paraphrasing it only to avoid overlap with the source; a closing slide stays a grounded fact, the company's response or the "
                "open factual question - never an invented debate or poll." + ledger + "\n" + lines)


class ViralCopyQualityError(MediaFirstContractError):
    """A viral carousel's copy broke the voice contract in a way a deterministic editor can prove. A MediaFirstContractError, so the
    trigger's existing single bounded correction retry names exactly what to fix."""


_QUOTED = re.compile("[\u00ab\"\u201c]([^\u00bb\"\u201d]+)[\u00bb\"\u201d]")
_NORMALISE = re.compile(r"[^\w]+")
# the editorial critic's own findings that, for a viral retelling, mean a slide carries no new information
_VIRAL_BLOCKING = frozenset({"body_repeats_headline", "body_restates_headline_claim", "card_adds_no_new_information", "label_headline"})


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


# QUOTE-USE CLASSIFICATION (founder task 2026-09-27, after the seventh paid viral canary). Quote provenance is unchanged - a quoted
# multi-word span is supported only when the evidence contains it verbatim - but an UNSUPPORTED span is now classified by how it is used:
#   ATTRIBUTED (hard / terminal): the text presents it as someone's literal wording - a reporting or naming verb of a speaker in the same
#     sentence ('OpenAI заявила', 'Компания назвала произошедшее', 'said'), a source frame ('по словам', 'в заявлении', 'according to',
#     'дословно'), a colon introducing it ('Сэм Альтман: «...»') or dialogue ('— «...»'). No correction may launder a fabricated quote.
#   EDITORIAL TERM MENTION (repairable): no speaker, no attribution - the marks label or contrast concepts ('не перепрыгивать от «X» к «Y»',
#     'это ещё не «подтверждённый взлом»', 'не стоит называть это «атакой»'). It goes to the ONE existing Director correction as
#     UNSUPPORTED_EDITORIAL_QUOTED_TERM / REMOVE_QUOTES_OR_PARAPHRASE - never a silent PASS.
# Naming verbs are attribution only when a subject performs them ('назвала', 'называют'); the editorial forms ('называть', 'называем',
# 'назовём') mention a term. Everything is sentence-scoped and conservative: any attribution signal in the sentence makes the span hard.
_ATTRIBUTION = re.compile(
    r"(?i)(?<![\w])(сказал\w*|скажет|говор(?:ит|ят|ил\w*)|заяв\w*|сообщ\w*|написал\w*|пиш(?:ет|ут)|отмет\w*|отмеча\w*|подчеркн\w*|"
    r"подч[её]ркива\w*|добав(?:ил\w*|ляет|ляют)|признал\w*|призна[её]т|признают|поясн\w*|ответ(?:ил\w*|ила)|цитир\w*|процитирова\w*|"
    r"утвержда\w*|объяв(?:ил\w*|ляет|ляют)|выразил\w*|выражается|назвал\w*|называ(?:ет|ют|л\w*)|окрестил\w*|охарактеризовал\w*|"
    r"по\s+словам|со\s+слов|по\s+заявлению|по\s+версии|в\s+(?:своём\s+|своем\s+)?(?:заявлении|сообщении|пресс-релизе|посте|блоге|письме|"
    r"отч[её]те|интервью|твите)|дословно|цитат\w*|"
    r"said|says|told|wrote|writes|stated|states|claimed|claims|called|calls|described|according\s+to|quoted|in\s+a\s+statement|put\s+it)"
    r"(?![\w])")
_SENTENCE_END = re.compile(r"[.!?…]+(?=\s|$)")
_DIALOGUE_START = re.compile(r"(?:^|\n)\s*[—–-]\s*$")


@dataclass(frozen=True)
class QuoteFindings:
    terminal: list[str]  # unsupported spans presented as someone's literal wording - a hard CreativeFactSafetyError
    repairable: list[str]  # UNSUPPORTED_EDITORIAL_QUOTED_TERM findings for the one Director correction


def _sentence_bounds(text: str, start: int, end: int) -> tuple[str, str, str]:
    """(prefix, sentence, suffix) of the sentence that holds text[start:end] - sentence ends inside the quote itself do not count."""
    before = [m.end() for m in _SENTENCE_END.finditer(text, 0, start)]
    s_start = before[-1] if before else 0
    after = _SENTENCE_END.search(text, end)
    s_end = after.end() if after else len(text)
    return text[s_start:start], text[s_start:s_end].strip(), text[end:s_end]


def classify_quote_use(fields: list[tuple[str, str]], evidence: list[str]) -> QuoteFindings:
    """Every unsupported quoted multi-word span in the copy, classified as ATTRIBUTED (terminal) or an EDITORIAL term mention (repairable).
    A span the evidence contains verbatim passes; a single quoted word is a label and is left alone (as in invented_quotes)."""
    corpus = _norm(" ".join(evidence))
    terminal: list[str] = []
    repairable: list[str] = []
    for where, text in fields:
        text = text or ""
        for match in _QUOTED.finditer(text):
            phrase = match.group(1).strip()
            if len(phrase.split()) < 2 or _norm(phrase) in corpus:
                continue
            prefix, sentence, suffix = _sentence_bounds(text, match.start(), match.end())
            attributed = (_ATTRIBUTION.search(prefix) or _ATTRIBUTION.search(suffix) or prefix.rstrip().endswith(":")
                          or _DIALOGUE_START.search(text[:match.start()]))
            if attributed:
                terminal.append(phrase)
            else:
                repairable.append(
                    f"UNSUPPORTED_EDITORIAL_QUOTED_TERM ({where}): «{phrase}» in \"{sentence}\" - REMOVE_QUOTES_OR_PARAPHRASE: this wording is "
                    "not in the evidence verbatim and nobody is quoted, so it must not look like a quotation. Remove the quotation marks or "
                    "paraphrase it faithfully; keep everything else that is already correct. Do not invent a speaker or verbatim wording, do "
                    "not add facts, do not strengthen the claim, do not change any target's status, keep the chronology and keep every hook "
                    "within the display limit.")
    return QuoteFindings(terminal=terminal, repairable=repairable)


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
                          r"engineer|developer|artist|singer|rapper|actor|actress|politician|minister|president|host|owner|chief\s+executive|"
                          r"стример\w*|блогер\w*|игрок\w*|основател\w*|глав[аеуы]|физик\w*|исследовател\w*|учён\w*|инженер\w*|"
                          r"разработчик\w*|художник\w*|певиц\w*|певец\w*|актёр\w*|актер\w*|спортсмен\w*|политик\w*|министр\w*|"
                          r"президент\w*|ведущ\w*|владел\w*)\b")
_NAME = r"(?:[A-ZА-ЯЁ][\w'’\-]+(?:\s+(?:de|van|von|da|di|le|la)\b)?(?:\s+[A-ZА-ЯЁ][\w'’\-]+){0,2})"
_ROLE_THEN_NAME = re.compile(_PERSON_ROLE.pattern[4:] + r"(?:\s+(?:and|и)\s+\w+)?\s+(" + _NAME + r")")
_NAME_THEN_ROLE = re.compile(r"(" + _NAME + r"),\s+(?:an?\s+|the\s+)?(?:[\w\-]+\s+){0,2}" + _PERSON_ROLE.pattern[4:], re.IGNORECASE)
# NAMED-PERSON IMAGE SAFETY (founder task 2026-09-27, after the sixth paid viral canary): the gate asks two separate questions -
#   A. does the EVIDENCE name a real person (named_people)?   B. does the picture BRIEF positively ask to depict that person / identity?
# Only B blocks. Canary 6 was stopped by raw keywords: 'face' in 'a blank clock face', 'person' / 'people' inside 'without depicting a real
# person' and 'No ... identifiable people are visible'. B is now read per clause, with polarity and word sense, never by a word list:
#   - the person's name (or surname) mentioned positively;
#   - a role that resolves to the named person ('Sam Altman, CEO of OpenAI' -> 'the named CEO', 'OpenAI CEO');
#   - a likeness instruction (lookalike / resembling / likeness / impersonating) or a positive 'recognizable face / person';
#   - a pronoun object of a depiction verb ('show him') once the brief names the person;
#   - a whole, individual, non-anonymous human figure (a man, a woman, a skater...) - a re-enactment of the named person's story.
# A term is negated only inside a prohibition's scope in its own clause ('no / without / never / avoid / do not [show] ...'); a negated
# REMOVAL ('do not hide') and 'not only' stay positive. 'face' is a human face only with a human possessor or a human adjective ('his
# face', 'a man's face', 'human / realistic / recognizable face'); a figure word that heads an object compound ('person icon') or is
# anonymised ('anonymous', 'faceless', 'silhouette', 'from behind') is not a person. Hands are anonymous and allowed.
_HUMAN_FIGURE = re.compile(r"(?i)\b(person|man|woman|boy|girl|guy|gentleman|lady|businessman|businesswoman|lookalike|look-alike|"
                           r"streamer\w*|skater\w*|player\w*|celebrity|human\s+(?:figure|being)|человек\w*|мужчин\w*|женщин\w*|парн\w*|"
                           r"парен\w*|девушк\w*|стример\w*|игрок\w*)\b")
_FACE = re.compile(r"(?i)\b(faces?|лиц[оа])\b")
# a possessor may take one adjective in between ('his tired face'); a human adjective sits directly on the noun ('realistic face')
_FACE_HUMAN_BEFORE = re.compile(r"(?i)(?:\b(?:his|her|their|его|её|ее)\s+(?:[\w\-]+\s+)?|"
                                r"\b(?:person|man|woman|boy|girl|guy|streamer|skater|player|ceo|founder)['’]s\s+(?:[\w\-]+\s+)?|"
                                r"\b(?:human|real|realistic|photo-?realistic|lifelike|life-like|recogni[sz]able|identifiable|человеческ\w*|"
                                r"реалистичн\w*)\s+)$")
_FACE_HUMAN_AFTER = re.compile(r"(?i)^\s+of\s+(?:an?\s+|the\s+)?(?:[\w\-]+\s+)?(?:person|man|woman|boy|girl|guy|him|her|them|streamer|skater|"
                               r"player|ceo|founder|celebrity|real\b)")
_LIKENESS = re.compile(r"(?i)\b(lookalike|look-alike|resembl\w*|likeness\w*|impersonat\w*|doppelg\w*|двойник\w*|похож\w*)")
_RECOGNIZABLE = re.compile(r"(?i)\b(recogni[sz]able|identifiable|узнаваем\w*)\s+(?:[\w\-]+\s+)?(face|faces|features|person|people|figure|"
                           r"individual|depiction|portrait|likeness|человек\w*|люд\w*|лиц\w*)\b")
_PRONOUN_DEPICTION = re.compile(r"(?i)\b(show\w*|depict\w*|portray\w*|draw\w*|render\w*|paint\w*|feature\w*|photograph\w*|recreat\w*|"
                                r"re-creat\w*|reproduc\w*|include\w*|put)\s+(him|her|them|his\s+face|her\s+face)\b")
_CLAUSE_SPLIT = re.compile(r"(?i)[.;:!?]+(?=\s|$)|\s[–—-]\s|\bbut\b|\bhowever\b|\binstead\b|\bно\b|\bа\s+не\b")
_PROHIBITION = re.compile(r"(?i)\b(no|not|without|never|avoid\w*|exclud\w*|omit\w*|nor|don['’]t|doesn['’]t|mustn['’]t|shouldn['’]t|"
                          r"без|не|нет|никак\w*|ни)\b")
_NEW_PHRASE = re.compile(r"(?i),\s*(?:and\s+|with\s+)?(?:a|an|the|one|two|three)\s")
_NOT_ONLY = re.compile(r"(?i)^\s*(only|just|merely|simply|только|лишь)\b")
# a prohibited REMOVAL is an instruction to show ('do not hide his face')
_REMOVAL = re.compile(r"(?i)\b(hid(?:e|es|ing|den)|blur\w*|obscur\w*|crop\w*|cut\w*|remov\w*|mask\w*|cover\w*|conceal\w*|anonymi[sz]\w*|"
                      r"leave\s+out|скрыва\w*|скры\w*|размыва\w*|закрыва\w*)\b")
_REVERSAL = re.compile(r"(?i)\b(but|only|except|instead|rather|yet|а|но|кроме)\b")
_POSTPOSED_NEGATION = re.compile(r"(?i)^[\s'’s]*(?:[\w\-]+\s+){0,3}?(?:must|should|does|do|is|are|will|shall|may|can)?\s*(?:not|never|n['’]t)\s+"
                                 r"(?:be\s+)?(appear\w*|shown|show\w*|visible|depict\w*|includ\w*|pictured|present|featured|identifiable|"
                                 r"recogni[sz]able)")
_ANONYMISED = re.compile(r"(?i)\b(anonymous|anonymi[sz]ed|faceless|unidentifiable|unrecogni[sz]able|featureless|silhouett\w*|from\s+behind|"
                         r"back\s+view|seen\s+from\s+the\s+back|stick[\s-]figure|out\s+of\s+focus|blurred|анонимн\w*|безлик\w*|силуэт\w*|"
                         r"со\s+спины)")
# a figure / role word heading an OBJECT compound is a thing, not a person ('person icon', 'icon of a person')
_OBJECT_HEAD_AFTER = re.compile(r"(?i)^[\s\-]*(icons?|symbols?|pictograms?|emoji\w*|avatars?|glyphs?|badges?|logos?|outlines?|shapes?|"
                                r"placeholders?|signs?|markers?|silhouettes?|consoles?|portals?|dashboards?|accounts?|interfaces?|"
                                r"иконк\w*|значк\w*|пиктограмм\w*)\b")
_OBJECT_HEAD_BEFORE = re.compile(r"(?i)\b(icons?|symbols?|pictograms?|emoji|avatars?|glyphs?|outlines?|placeholders?|иконк\w*|значк\w*)\s+"
                                 r"(?:of\s+)?(?:an?\s+|the\s+)?$")
_SIMILE_BEFORE = re.compile(r"(?i)\b(like|as|как|словно|будто)\s+(an?\s+)?(\w+\s+)?$")
_ROLE_CANON = {"chief executive": "ceo"}
# a role that only possesses an anonymous body part ('an MRI physicist's hands') shows hands, not the person - the NAME is never excused
_ANONYMOUS_PART_AFTER = re.compile(r"(?i)^['’]s\s+(?:[\w\-]+\s+)?(hands?|fingers?|palms?|arms?|wrists?)\b")


# a verb-like Russian word (past / present / reflexive endings) - a hook of telegraphic fragments has none
_VERB_LIKE = re.compile(r"(?i)\b[а-яё]{2,}(?:л|ла|ло|ли|ет|ют|ит|ят|ат|ут|ется|ются|ится|ятся|ешь|ишь|ем|им|ал|ил|ыл)\b")
# a small, principled set of generalising subjects: a sentence built only on them (and no concrete anchor) says nothing new
_ABSTRACT_SUBJECT = re.compile(r"(?i)\b(классик\w*|сообществ\w*|индустри\w*|будущ\w*|эпох\w*|человечеств\w*|поколени\w*)")
# anglicisms that have a natural Russian word (the suggestion is a hint, the Director writes the sentence)
_ANGLICISMS = {"апгрейд": "обновление / улучшение", "фейл": "провал", "хайп": "шум / ажиотаж", "фича": "функция", "фичи": "функции",
               "юзер": "пользователь", "лайфхак": "приём / совет", "кейс": "случай / пример", "вайб": "настроение", "кринж": "неловкость",
               "хейт": "критика"}
_ANGLICISM = re.compile(r"(?i)\b(" + "|".join(sorted(_ANGLICISMS, key=len, reverse=True)) + r")\w*")
_LIST_SEPARATORS = re.compile(r"\s[·•|/]\s|,\s")


def clipped_hook(hook: str) -> bool:
    """A hook assembled from telegraphic fragments ('GTA IV: «лесенки» — всё, через 18 лет'): split at ':' / '—' it gives several
    verbless pieces, one of them a scrap of one or two words. A plain nominal sentence ('460 целей. Ни одного взлома.') is not clipped."""
    pieces = [p.strip(" .,«»\"") for p in re.split(r"[:—]", hook) if p.strip(" .,«»\"")]
    return len(pieces) >= 3 and not _VERB_LIKE.search(hook) and any(len(p.split()) <= 2 for p in pieces)


def product_list(text: str) -> bool:
    """An audience-facing field that is a bare list of (Latin) names, not Russian prose: several list separators and fewer than two
    Russian words."""
    cyrillic_words = re.findall(r"[А-Яа-яЁё]{3,}", text or "")
    return len(_LIST_SEPARATORS.findall(text or "")) >= 2 and len(cyrillic_words) < 2


def generic_filler(sentence: str) -> bool:
    """A generalising sentence with no concrete anchor (no number, no name): 'Классика получила апгрейд от сообщества'."""
    from services.instagram_editorial_critic import anchors

    return bool(_ABSTRACT_SUBJECT.search(sentence)) and not anchors(sentence) and not re.search(r"\d", sentence)


# PROPOSITION-AWARE THESIS COMPARISON (founder task 2026-09-27, after the canary-7 offline continuation). The old comparison used
# services.instagram_editorial_critic.content_stems - a 4-letter prefix per word - so 'Компания' and 'компрометации' were both 'комп',
# and 'нашли' / 'не нашли' were both 'нашл': slides 3 ('found during the review') and 4 ('no compromise found at the SEC') shared
# {комп, нашл, обна} plus the name OpenAI and were called the same point. The thesis layer now compares PROPOSITIONS:
#   - tokens: a conservative Russian suffix stripper (the stem keeps >= 4 letters, so 'компани' != 'компрометаци'), stopwords dropped;
#   - polarity: a word governed by не / ни / нет / без / no / not is its own token ('¬нашл' != 'нашл');
#   - concepts: the few predicates a news carousel re-words - find / disclose / interact / the AI actor / the company / a site / a check -
#     count as one token each, so a paraphrase ('раскрыла' / 'рассказала', 'агент' / 'ИИ') is still the same claim;
#   - roles: what each slide DOES (discovery mechanism, target status, event time, disclosure time, ongoing check, company statement,
#     reader consequence, commercial detail); two different specific roles are two theses whatever words they share.
_RU_ENDINGS = tuple(sorted((
    "иями", "ями", "ами", "ией", "ого", "его", "ому", "ему", "ыми", "ими", "иях", "ых", "их", "ым", "им", "ил", "ыл", "ях", "ах", "ая", "яя", "ое", "ее", "ые", "ие", "ый",
    "ий", "ой", "ую", "юю", "ам", "ям", "ом", "ем", "ов", "ев", "ей", "ия", "ию", "ии", "ть", "ться", "лась", "лись", "ила", "или", "ило",
    "ыла", "ыли", "ала", "али", "ет", "ют", "ит", "ят", "ут", "ешь", "ишь", "ла", "ли", "ло", "ся", "сь", "а", "я", "о", "е", "ы",
    "и", "у", "ю", "ь", "й"), key=len, reverse=True))
_NEGATOR = frozenset({"не", "ни", "нет", "без", "no", "not", "never", "without"})
_CONCEPTS = (
    ("FIND", re.compile(r"^(?:наш[её]?л|найд|найт|обнаруж|выяв|found|find|discover|detect)")),
    ("DISCLOSE", re.compile(r"^(?:раскр[ыо]|рассказ|сообщ|объяв|обнарод|disclos|reveal|announc)")),
    ("INTERACT", re.compile(r"^(?:взаимодейств|обращ|заход|заш[её]?л|посещ|ходил|interact|access|visit)")),
    ("AI", re.compile(r"^(?:агент|ии$|ai$|нейросет|agent)")),
    ("ORG", re.compile(r"^(?:компани|company)")),
    ("SITE", re.compile(r"^(?:сайт|site|портал|website)")),
    ("CHECK", re.compile(r"^(?:провер|расследов|аудит|review|investig|audit)")),
)
_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё]+|\d+")
_EVENT_TIME = re.compile(r"(?i)\b(летом|весной|осенью|зимой|в\s+(?:январе|феврале|марте|апреле|мае|июне|июле|августе|сентябре|октябре|"
                         r"ноябре|декабре)|произош\w*|случил\w*|this summer|last (?:summer|month|year))\b")
_ONGOING = re.compile(r"(?i)\b(продолжа\w*|ещё идёт|еще идет|пока идёт|пока идет|не завершен\w*|ongoing|continu\w*|still under)\b")
_DURING = re.compile(r"(?i)\b(в ходе|во время|при|during|in the course of)\b")
_READER = re.compile(r"(?i)\b(стоит|нужно|следует|проверьте|обновите|пользовател\w*|вам|вы|читател\w*|you|your)\b")
_COMMERCIAL = re.compile(r"(?i)(\d\s?%|[$€£₽]\s?\d|\d\s?(?:руб|долл))")
_COMMERCIAL_WORD = re.compile(r"(?i)\b(скидк\w*|цен\w*|стоим\w*|дешев\w*|дешёв\w*|price\w*|discount\w*|продаж\w*|продают)")
_STATEMENT = re.compile(r"(?i)\b(заяви\w*|сообщи\w*|пообеща\w*|извини\w*|ответи\w*|поддержива\w*|said|stated|promised)\b")
SPECIFIC_THESIS_ROLES = frozenset({"DISCOVERY_MECHANISM", "TARGET_STATUS", "CHRONOLOGY_EVENT", "CHRONOLOGY_DISCLOSURE",
                                   "INVESTIGATION_ONGOING", "COMPANY_STATEMENT", "READER_CONSEQUENCE", "COMMERCIAL_DETAIL"})


def ru_stem(word: str) -> str:
    """Conservative suffix stripping: the longest inflectional ending whose removal leaves at least four letters."""
    w = word.lower().replace("ё", "е")
    for ending in _RU_ENDINGS:
        if w.endswith(ending) and len(w) - len(ending) >= 4:
            w = w[: -len(ending)]
            break
    # the -ени- / -ани- / -ци- noun stems keep a trailing 'и' in some cases only ('столкновение' / 'столкновением'): drop it
    return w[:-1] if w.endswith("и") and len(w) > 4 else w


def thesis_tokens(text: str) -> set[str]:
    """The proposition-bearing tokens of a text: concepts / Russian stems, each marked '¬' when a negator governs it. Numbers and
    Latin-script names are anchors (services.instagram_editorial_critic.anchors), compared separately - as in content_stems."""
    from services.instagram_editorial_critic import _STOP

    tokens: set[str] = set()
    negate = False
    for raw in _TOKEN.findall(text or ""):
        low = raw.lower().replace("ё", "е")
        if low in _NEGATOR:
            negate = True
            continue
        concept = next((name for name, pattern in _CONCEPTS if pattern.search(low)), None)
        if concept is None and (low in _STOP or len(low) < 4) and not low.isdigit():
            continue  # a stopword does not end the negation's reach ('не для всех нашли'); a content word does
        if concept is None and not re.search(r"[а-я]", low):
            negate = False
            continue  # numbers and Latin-script names are ANCHORS (compared as names / specificity), not content words
        token = concept or ru_stem(low)
        tokens.add(("¬" if negate else "") + token)
        negate = False
    return tokens


def _slide_text(slide: Any) -> str:
    return f"{_copy(slide)} {_body(slide)}"


def proposition_role(slide: Any) -> str:
    """What the slide DOES editorially - one of SPECIFIC_THESIS_ROLES, or 'GENERAL' when nothing specific is recognised."""
    from services.instagram_factual_status import mentioned_targets

    text = _slide_text(slide)
    tokens = thesis_tokens(text)
    if mentioned_targets(text) and ({"¬FIND"} & tokens or re.search(r"(?i)\b(подтвержд\w*|компрометац\w*|признак\w*|confirmed|compromis\w*)", text)):
        return "TARGET_STATUS"
    if "FIND" in tokens and _DURING.search(text) and "CHECK" in tokens:
        return "DISCOVERY_MECHANISM"
    if _ONGOING.search(text) and "CHECK" in tokens:
        return "INVESTIGATION_ONGOING"
    event, disclosure = bool(_EVENT_TIME.search(text)), "DISCLOSE" in tokens
    if event and not disclosure:
        return "CHRONOLOGY_EVENT"
    if disclosure and not event and re.search(r"\d", text):
        return "CHRONOLOGY_DISCLOSURE"
    if _COMMERCIAL.search(text) and _COMMERCIAL_WORD.search(text):
        return "COMMERCIAL_DETAIL"
    if _READER.search(text):
        return "READER_CONSEQUENCE"
    if _STATEMENT.search(text):
        return "COMPANY_STATEMENT"
    return "GENERAL"


def distinct_propositions(prev: Any, cur: Any) -> bool:
    """Two different SPECIFIC roles, or a polarity conflict on the same concept ('нашли' vs 'не нашли'), are two theses."""
    a, b = proposition_role(prev), proposition_role(cur)
    if a != b and a in SPECIFIC_THESIS_ROLES and b in SPECIFIC_THESIS_ROLES:
        return True
    ta, tb = thesis_tokens(_slide_text(prev)), thesis_tokens(_slide_text(cur))
    return any(("¬" + t) in tb for t in ta if not t.startswith("¬")) or any(("¬" + t) in ta for t in tb if not t.startswith("¬"))


def same_proposition(prev: Any, cur: Any) -> str | None:
    """Two adjacent cards that state substantially the same proposition, in any words: the smaller card's content is mostly (>= 60 %,
    at least two tokens) contained in the other's, they share a concrete entity, and the smaller card brings no new number or name."""
    from services.instagram_editorial_critic import anchors

    pa, pb = _slide_text(prev), _slide_text(cur)
    entities_a = {a for a in anchors(pa) if not re.search(r"\d", a)} | ({"ORG"} & thesis_tokens(pa))
    entities_b = {a for a in anchors(pb) if not re.search(r"\d", a)} | ({"ORG"} & thesis_tokens(pb))
    # a Latin-script company name and 'компания' refer to the same kind of actor
    if any(not re.search(r"\d", a) for a in anchors(pa)):
        entities_a.add("ORG")
    if any(not re.search(r"\d", a) for a in anchors(pb)):
        entities_b.add("ORG")
    ta = thesis_tokens(pa) - {"ORG"}
    tb = thesis_tokens(pb) - {"ORG"}
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    shared = small & large
    if not (entities_a & entities_b) or len(shared) < 2 or len(shared) < 0.6 * len(small):
        return None
    new_anchors = (anchors(pb) - anchors(pa)) if small is tb else (anchors(pa) - anchors(pb))
    if {a for a in new_anchors if a not in {"ai-", "ai"}}:
        return None
    return f"both state the same claim ({', '.join(sorted(shared))})"


def thesis_relation(prev: Any, cur: Any, *, earlier_slides: list[Any]) -> str | None:
    """Founder rule 2026-09-26: EVERY SLIDE ADDS A NEW IDEA, NOT MORE SPECIFIC WORDS FOR THE PREVIOUS IDEA. A slide's claim is its body (its
    headline too when that carries a name or a number, or when the body is too short to state one). Compared with the previous slide - never by
    evidence ids, never by a term list:
      - REPETITION: the claim brings no new content word and no new concrete detail;
      - SUBSUMPTION: the claim's content words all already appear in the previous slide and it only adds names / numbers - it enumerates or
        specifies the previous claim (a new detail, not a new beat: no new event, actor, consequence, result, limitation or mechanism);
      - RESTATED THESIS: it shares several content words with the previous claim and brings no new concrete fact at all.
    Returns the explanation, or None when the slide is a new beat."""
    from services.instagram_editorial_critic import anchors

    head = _copy(cur)
    body = _body(cur)
    # the headline joins the claim when it carries a name / number, or when the body alone is too short to state a thesis
    claim = body + (f" {head}" if anchors(head) or re.search(r"\d", head) or len(thesis_tokens(body)) < 2 else "")
    prev_text = f"{_copy(prev)} {_body(prev)}"
    claim_words = thesis_tokens(claim)
    prev_words = thesis_tokens(prev_text)
    if len(claim_words) < 2:
        return None  # too little Russian text to judge a thesis
    new_words = claim_words - prev_words
    shared = claim_words & prev_words
    new_vs_prev = anchors(claim) - anchors(prev_text)
    new_vs_all = anchors(claim) - set().union(*(anchors(f"{_copy(s)} {_body(s)}") for s in earlier_slides))
    if len(new_words) <= 1 and shared and not new_vs_all:
        return "the second slide repeats the first slide's point (no new content word, no new concrete detail)"
    if not new_words and shared and new_vs_prev:
        return (f"the second slide only specifies the first slide's claim ({', '.join(sorted(shared))}) by naming "
                f"{', '.join(sorted(new_vs_prev))} - it adds specificity, not a new beat (no new event, actor, consequence, result, "
                "limitation or mechanism)")
    if len(shared) >= 2 and len(new_words) <= len(shared) and not new_vs_all:
        return (f"the second slide restates the first slide's thesis ({', '.join(sorted(shared))}) without a new concrete fact")
    return None


_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9\-]+")


_MASKED = "¦"
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9\-]+|¦")


def lifted_wording(text: str, evidence: list[str], *, run: int = 6) -> str | None:
    """A sentence that copies a long run of the SOURCE's own wording ('требуется глобальная техническая модификация ...') instead of saying it
    in natural words: `run` or more consecutive words identical to an evidence item, at least 3 of them long Russian words (a copied run
    of product names or numbers is not wording; a short plain sentence in the same words is not source register). Returns the run.
    Founder calibration 2026-09-27: short status-critical wording - target / agency names, 'подтвердила', 'расследование продолжается',
    dates, numbers, Latin names (services.instagram_factual_status.factual_term_spans) - is masked identically on both sides: a masked term
    still continues a run but never counts as the source's formal wording, so precision is never traded for paraphrase while the prose AROUND
    those terms is still compared (copied sentence structure still fails)."""
    from services.instagram_factual_status import mask_factual_terms

    words = [w.lower() for w in _TOKEN_RE.findall(mask_factual_terms(text or "", f" {_MASKED} "))]
    for item in evidence:
        source = [w.lower() for w in _TOKEN_RE.findall(mask_factual_terms(item or "", f" {_MASKED} "))]
        grams = {tuple(source[i:i + run]) for i in range(len(source) - run + 1)}
        for i in range(len(words) - run + 1):
            gram = tuple(words[i:i + run])
            # a run of names / numbers is not lifted WORDING (product names stay allowed), and a short plain sentence retold in the same
            # words is fine: the copied run must carry the source's formal register - at least 3 long (8+ letter) Russian words
            if gram in grams and sum(1 for w in gram if re.fullmatch(r"[а-яё\-]{8,}", w)) >= 3:
                return " ".join(gram)
    return None


def caption_findings(caption: str, slides: list[Any]) -> list[str]:
    """The caption is audience-facing copy too: never a product-name list, a re-list of what the slides already say, or abstract filler."""
    from services.instagram_editorial_critic import anchors

    slide_text = " ".join(f"{_copy(s)} {_body(s)}" for s in slides)
    slide_anchors = anchors(slide_text)
    problems = []
    for sentence in re.split(r"(?<=[.!?…])\s+", caption or ""):
        sentence = sentence.strip()
        if not sentence:
            continue
        names = anchors(sentence)
        if product_list(sentence) or (len(re.findall(r"[А-Яа-яЁё]{3,}", sentence)) <= 2 and len(names) >= 3):
            repeated = " - it repeats the slides' list" if names and names <= slide_anchors else ""
            problems.append(f"caption sentence is a list of names, not a sentence that adds context: {sentence!r}{repeated}")
        elif generic_filler(sentence):
            problems.append(f"caption: generic filler with no new fact: {sentence!r}")
    return problems


def _role_key(role: str) -> str:
    key = re.sub(r"\s+", " ", role.lower().strip())
    return _ROLE_CANON.get(key, key)


def named_identities(evidence: list[str]) -> dict[str, set[str]]:
    """Real people the evidence NAMES, each with the role(s) that identify them ('Sam Altman, CEO of OpenAI' -> {'Sam Altman': {'ceo'}})."""
    found: dict[str, set[str]] = {}
    for line in evidence:
        for match in _ROLE_THEN_NAME.finditer(line):
            found.setdefault(match.group(match.lastindex or 0).strip(), set()).add(_role_key(match.group(1)))
        for match in _NAME_THEN_ROLE.finditer(line):
            candidate = match.group(1).strip()
            if candidate.split()[0].lower() not in ("the", "a", "an", "this", "that", "his", "her"):
                found.setdefault(candidate, set()).add(_role_key(match.group(2)))
    return {name: roles for name, roles in found.items() if len(name) >= 3}


def named_people(evidence: list[str]) -> set[str]:
    """Real people the evidence NAMES (a proper name next to a person role: 'streamer and YouTuber IShowSpeed', 'NHL player Cole Caufield',
    'Thijs de Buck, an MRI physicist'). Organisations after a preposition ('researchers from Unit 42') are not people."""
    return set(named_identities(evidence))


def _clauses(brief: str) -> list[str]:
    text = re.sub(r"[“”\"«»„]", " ", brief).replace("’", "'")
    return [c for c in _CLAUSE_SPLIT.split(text) if c and c.strip()]


def _negated(clause: str, start: int, end: int) -> bool:
    """True when the term at clause[start:end] sits inside a prohibition's scope in its own clause."""
    prefix = clause[:start]
    last = None
    for last in _PROHIBITION.finditer(prefix):
        pass
    if last is not None:
        between = prefix[last.end():]
        # a new article-led noun phrase after a comma ('without logos, a man at a desk') is outside the prohibition (conservative)
        if not (_NOT_ONLY.match(between) or _REMOVAL.search(between) or _REVERSAL.search(between) or _NEW_PHRASE.search(between)):
            return True
    return bool(_POSTPOSED_NEGATION.match(clause[end:]))


def _object_sense(clause: str, start: int, end: int) -> bool:
    return bool(_OBJECT_HEAD_AFTER.match(clause[end:]) or _OBJECT_HEAD_BEFORE.search(clause[:start]))


def _anonymised(clause: str, start: int, end: int) -> bool:
    before = " ".join(clause[:start].split()[-4:])
    after = " ".join(clause[end:].split()[:6])
    return bool(_ANONYMISED.search(before) or _ANONYMISED.search(after))


def _positive(clause: str, match: re.Match) -> bool:
    return not _negated(clause, match.start(), match.end())


def depiction_findings(brief: str, identities: dict[str, set[str]]) -> list[str]:
    """What in ONE generated-picture brief positively asks to depict a named real person (question B); empty when nothing does."""
    if not identities:
        return []
    findings: list[str] = []
    patterns = []
    for name in sorted(identities):
        patterns.append((name, re.compile(r"(?i)(?<![\w])" + re.escape(name) + r"(?![\w])")))
        surname = name.split()[-1]
        if surname != name and len(surname) >= 4:
            patterns.append((name, re.compile(r"(?<![\w])" + re.escape(surname) + r"(?![\w])")))  # case-sensitive: 'Buck', not 'buck'
    roles = {role: name for name, rs in identities.items() for role in rs}
    role_pattern = re.compile(r"(?i)\b(" + "|".join(re.escape(r).replace(r"\ ", r"\s+") for r in sorted(roles, key=len, reverse=True))
                              + r")\b") if roles else None
    clauses = _clauses(brief)
    names_in_brief = any(p.search(c) for c in clauses for _n, p in patterns)
    for clause in clauses:
        for name, pattern in patterns:
            if any(_positive(clause, m) for m in pattern.finditer(clause)) and name not in findings:
                findings.append(name)
        if role_pattern is not None:
            for m in role_pattern.finditer(clause):
                if (_positive(clause, m) and not _object_sense(clause, m.start(), m.end()) and not _SIMILE_BEFORE.search(clause[:m.start()])
                        and not _ANONYMOUS_PART_AFTER.match(clause[m.end():])):
                    findings.append(f"role '{m.group(0)}' ({roles[_role_key(m.group(0))]})")
                    break
        for m in _LIKENESS.finditer(clause):
            if _positive(clause, m):
                findings.append(f"likeness '{m.group(0)}'")
                break
        for m in _RECOGNIZABLE.finditer(clause):
            if _positive(clause, m):
                findings.append(f"'{m.group(0)}'")
                break
        if names_in_brief:
            for m in _PRONOUN_DEPICTION.finditer(clause):
                if _positive(clause, m):
                    findings.append(f"'{m.group(0)}'")
                    break
        for m in _FACE.finditer(clause):
            human = _FACE_HUMAN_BEFORE.search(clause[:m.start()]) or _FACE_HUMAN_AFTER.match(clause[m.end():])
            if human and _positive(clause, m) and not _anonymised(clause, m.start(), m.end()):
                findings.append(f"human face '{(human.group(0).strip() + ' ' + m.group(0)).strip()}'")
                break
        for m in _HUMAN_FIGURE.finditer(clause):
            if (_positive(clause, m) and not _SIMILE_BEFORE.search(clause[max(0, m.start() - 24):m.start()])
                    and not _object_sense(clause, m.start(), m.end()) and not _anonymised(clause, m.start(), m.end())):
                findings.append(repr(m.group(0)))
                break
    return list(dict.fromkeys(findings))


def generated_person_risks(slides: list[Any], evidence: list[str]) -> list[str]:
    """A generated picture whose brief POSITIVELY asks to depict a named real person (see depiction_findings): by name, by a role that
    resolves to them, as a likeness, or as a whole non-anonymous human figure re-enacting their story. Negated mentions ('without
    depicting a real person'), object senses ('a blank clock face', 'a person icon') and anonymous human elements (hands, silhouettes)
    are not depictions. Real source photos are not affected."""
    identities = named_identities(evidence)
    if not identities:
        return []
    people = ", ".join(sorted(identities))
    risks = []
    for index, slide in enumerate(slides, 1):
        if _get(slide, "media_source") != "generated":
            continue
        # what the PICTURE is asked to show (story_anchor states the story's fact, which may legitimately name the person)
        brief = " ".join(str(_get(slide, key) or "") for key in ("generation_brief", "visual_direction"))
        found = depiction_findings(brief, identities)
        if found:
            names = [f for f in found if f in identities]
            risks.append(f"slide {index}: generated picture risks a likeness / re-enactment of a named real person ({people})"
                         f" - brief mentions {names or found[0]}; show objects, places or a metaphor, people only anonymous")
    return risks


def viral_copy_findings(slides: list[Any], evidence: list[str], *, caption: str = "", include_quotes: bool = True) -> list[str]:
    """NATURAL RUSSIAN + CONCRETE FACT + OPTIONAL DRY PUNCH, as far as a deterministic editor can prove it without a phrase list.
    `include_quotes=False`: the Director validation treats an invented quote as a HARD grounding failure of its own, not a copy finding."""
    from services.instagram_editorial_critic import critique

    texts = [*(_copy(s) for s in slides), *(_body(s) for s in slides), caption]
    problems = [f"invented quote (not in the evidence): '{q}' - retell it as narration without quotation marks"
                for q in invented_quotes(texts, evidence)] if include_quotes else []
    if slides and clipped_hook(_copy(slides[0])):
        problems.append(f"slide 1 hook is a clipped fragment, not natural Russian: {_copy(slides[0])!r} - state the strongest concrete fact "
                        "as a complete phrase")
    for index, slide in enumerate(slides, 1):
        for field, text in (("headline", _copy(slide)), ("body", _body(slide))):
            if product_list(text):
                problems.append(f"slide {index} {field} is a list of product names, not Russian prose: {text!r} - say it as a sentence")
            for sentence in re.split(r"(?<=[.!?…])\s+", text or ""):
                if sentence.strip() and generic_filler(sentence):
                    problems.append(f"slide {index} {field}: generic filler with no new fact: {sentence.strip()!r} - end on the real fact or "
                                    "its plain irony")
    problems += caption_findings(caption, slides)
    for index, slide in enumerate(slides, 1):
        for sentence in re.split(r"(?<=[.!?…])\s+", _body(slide)):
            copied = lifted_wording(sentence, evidence)
            if copied:
                problems.append(f"slide {index} body copies the source's wording verbatim ('{copied}') - say it in plain natural Russian")
    for text in texts:
        for match in _ANGLICISM.finditer(text or ""):
            word = match.group(1).lower()
            problems.append(f"anglicism '{match.group(0)}' where Russian has a natural word ({_ANGLICISMS[word]}): {text.strip()[:80]!r}")
    problems += [f.render() + (" - state the slide's own fact instead of a teaser" if f.code == "label_headline"
                                else " - a viral slide's body must add a new grounded fact")
                 for f in critique(slides, evidence, caption=caption) if f.code in _VIRAL_BLOCKING]
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
    from services.instagram_factual_status import abstract_question_findings, distinct_by_role

    problems += abstract_question_findings(slides, caption, evidence)
    for index in range(1, len(slides)):
        prev, cur = slides[index - 1], slides[index]
        if distinct_by_role(prev, cur, index) or distinct_propositions(prev, cur):
            continue  # founder calibration 2026-09-27: two different editorial roles (or opposite polarity) are two theses, whatever words they share
        beat = thesis_relation(prev, cur, earlier_slides=slides[:index])
        if beat:
            problems.append(f"slides {index} and {index + 1}: {beat} - merge them into one slide, then use the freed slide for another "
                            "distinct grounded fact or make the carousel shorter")
            continue
        same = same_proposition(prev, cur)
        if same:
            problems.append(f"slides {index} and {index + 1} make the same point ({same}) - merge them or give the second a new fact")
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
