"""Editorial critic for Instagram carousels (content pass v10.8) - deterministic, no model call.

The v10.7 paid validation showed the Creative Director learned the FORM (every card has a body, no empty slogans) but not the editorial
JUDGMENT: it led with a weaker fact while the strongest one (the most extreme supported number/comparison) never appeared; it paraphrased
the exact prompts that were the post's save value; it restated the same information across cards and between headline and body; it
changed a fact's tense ("already trained" -> "plan to train"); and it wrote Russian that was understandable but unnatural.

This module finds those failure classes in a finished plan, against the post's own evidence. It is general - no story-specific rules:
  - salience: every evidence line is scored for how strongly it can make a reader stop (extreme ratios/percentages, prices, big numbers,
    a comparison against another named product, cost/price); the hook must carry the strongest line's anchor, and no top-tier fact may
    vanish from the carousel;
  - usable content: an evidence line that tells the reader to ASK or WRITE something must survive as quotable wording, not a paraphrase;
  - repetition: a card must add new content words; headline and body must not say the same thing; no card may repeat another;
  - fact fidelity: completed <-> planned tense shifts on the same subject, and generalisations that drop the evidence's attribution;
  - Russian editorial lint: a small set of general, high-precision patterns (temporal "где", "в ... неделе", stated tautologies,
    calqued "принял <standard>", pronoun-led headlines with no referent, empty label headlines, bureaucratic participle chains, filler).
Blocking findings reject the plan (MediaFirstContractError subclass - the one existing contract retry receives the exact findings);
advisory findings are reported for editorial review only. A heuristic can never approve content - only reject known failure shapes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from services.instagram_media_first import MediaFirstContractError

BLOCKING = "blocking"
ADVISORY = "advisory"
HOOK_DISPLAY_MAX_CHARS = 60
# the only findings that reject a plan: the post would be false, its core value would be lost, or it cannot be displayed
GATING_CODES = frozenset({
    "completed_fact_turned_into_plan", "claim_stronger_than_evidence", "launch_after_discussion",  # false
    "strongest_fact_dropped", "usable_instruction_paraphrased", "card_repeats_card",                # core value lost
    "hook_too_long_for_display",                                                                      # cannot be set at display size
})

_WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9$%€£₽][A-Za-zА-Яа-яЁё0-9$%€£₽.\-]*")
_STOP = frozenset(
    "и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее её мне было вот от меня еще ещё нет о из ему "
    "теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где "
    "есть надо ней для мы тебя их чем была сам чтобы без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем "
    "ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше "
    "тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им "
    "более всегда конечно всю между это эта это также именно который которая которые которую своя свой своё свои".split()
)
_COMPLETED = r"(?:ена|ено|ены|ен|ана|ано|аны|ан|ила|ило|или|ил|ала|ало|али|ал|ела|ели|ел|ыла|ыли|ыл)"
_PLANNED = re.compile(r"\b(?:планиру\w*|план\w*|готов\w*|собира\w*|хот\w*|намерен\w*|будет|будут|скоро|вскоре)\b", re.IGNORECASE)
_ATTRIBUTION = re.compile(r"\b(?:заявля\w*|заявил\w*|заявлен\w*|утвержда\w*|якобы|по словам|по данным|обеща\w*|говорит)\b", re.IGNORECASE)
_INSTRUCTION = re.compile(r"\b(?:попросить|попроси|спросить|спроси|написать|напиши|ввести|введи|вставить|вставь|команд\w*|запрос\w*)\b",
                          re.IGNORECASE)
_IMPERATIVE_2SG = re.compile(r"\b\w+(?:и|й|ь)(?:те)?\b")


@dataclass(frozen=True)
class EditorialFinding:
    code: str
    severity: str
    card: int | None
    detail: str

    def render(self) -> str:
        where = "post" if self.card is None else f"card {self.card + 1}"
        return f"[{self.severity}] {self.code} ({where}): {self.detail}"


class EditorialQualityError(MediaFirstContractError):
    """The plan repeats a known editorial failure shape (weakest angle, lost usable content, repetition, fact drift, bad Russian)."""


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _words(text: str) -> list[str]:
    return [w.strip(".-") for w in _WORD.findall(text or "") if w.strip(".-")]


def _stem(word: str) -> str:
    """Crude Russian stem: the first four letters of a longer word (умных/умные, веса/весами, дешёвым/дешёвые match)."""
    w = word.lower().replace("ё", "е")
    return w[:4] if len(w) > 4 else w


def content_stems(text: str) -> set[str]:
    """Russian content words (4+ letters, not stopwords, not Latin names or numbers - those are anchors, legitimately repeated)."""
    return {_stem(w) for w in _words(text) if len(w) >= 4 and w.lower() not in _STOP and re.search(r"[А-Яа-яЁё]", w) and not re.search(r"\d", w)}


def anchors(text: str) -> set[str]:
    """The concrete things a reader holds on to: numbers (with %/currency/scale words) and Latin-script names."""
    found = set()
    for m in re.finditer(r"(?<![A-Za-z\-.\d])[$€£₽]?\d[\d.,]*\s?(?:%|млн|млрд|тыс)?", text or ""):  # never a model version (GPT-5.6)
        found.add(re.sub(r"\s", "", m.group(0)).rstrip(".,"))
    for word in ("вдвое", "втрое", "вчетверо", "бесплатн"):
        if word in (text or "").lower():
            found.add(word)
    for m in re.finditer(r"\b[A-Za-z][A-Za-z0-9\-]*(?:\.\d+)?\b", text or ""):
        if len(m.group(0)) >= 2:
            found.add(m.group(0).lower())
    return found


def _is_quantity(anchor: str) -> bool:
    """A real quantity (1%, $149, 600 млн, вдвое) - never a model or product version such as gpt-5.6."""
    return bool(re.fullmatch(r"[$€£₽]?[\d.,]+(?:%|млн|млрд|тыс)?|вдвое|втрое|вчетверо|бесплатн", anchor))


def _strip_story_tag(line: str) -> str:
    return re.sub(r"^\[story_\d+\]\s*", "", line)


def salience(line: str) -> int:
    """How strongly one supported fact can stop the scroll. General signals only - no topic knowledge."""
    text = _strip_story_tag(line).lower()
    score = 0
    if re.search(r"\d\s?%|\bвдвое\b|\bвтрое\b|в \d+ раз|\bпримерно в \d", text):
        score += 3  # an extreme ratio or percentage
    if re.search(r"[$€£₽]|\bдоллар|\bруб", text):
        score += 2  # a price
    if re.search(r"\d[\d\s.,]*\s?(?:млн|млрд|тыс|миллион|миллиард)", text):
        score += 2  # a big number
    if re.search(r"\d", text):
        score += 1
    if re.search(r"соответству|на уровне|уровн|\bчем\b|сравним|не уступа|как у\b", text):
        score += 2  # compared against another named product
    if re.search(r"стоимост|\bцен|дешев|дешёв|дорог|бесплатн", text):
        score += 2  # cost / price: the reader's own stake
    return score


def _cards(slides: list[Any]) -> list[dict[str, Any]]:
    out = []
    for slide in slides:
        steps = []
        layout = _get(slide, "layout")
        regions = _get(layout, "regions") if layout is not None else None
        for region in regions or []:
            fs = _get(region, "flow_steps")
            if fs:
                steps.extend(fs)
        out.append({"head": str(_get(slide, "slide_copy") or ""), "body": str(_get(slide, "slide_body") or ""),
                    "steps": " ".join(steps), "evidence": str(_get(slide, "source_evidence") or "")})
    return out


def _unquoted(text: str) -> str:
    """Quoted wording is the reader's usable content (an exact prompt), not a restatement - repetition checks never count it
    (real v10.8 AI_HACK card 3: the quoted prompt shares the step headline's words by design and was wrongly rejected)."""
    return re.sub(r"«[^»]*»|\"[^\"]*\"", " ", text or "")


def _full(card: dict[str, Any]) -> str:
    return f"{card['head']} {card['body']} {card['steps']}"


def critique(slides: list[Any], evidence: list[str], *, archetype: str | None = None, caption: str = "") -> list[EditorialFinding]:
    cards = _cards(slides)
    findings: list[EditorialFinding] = []
    add = findings.append
    if not cards:
        return findings
    post_text = " ".join(_full(c) for c in cards)
    post_anchors = anchors(post_text)

    # 1. ANGLE: the strongest supported fact leads, and no top-tier fact disappears
    scored = sorted(((salience(line), i, line) for i, line in enumerate(evidence)), reverse=True)
    top = scored[0][0] if scored else 0
    if top >= 5:
        hook_anchors = anchors(cards[0]["head"] + " " + cards[0]["body"])
        leaders = [line for s, _, line in scored if s == top]

        def key_anchors(line: str) -> set[str]:
            # what makes THIS fact strong is its number / price / ratio; shared product names do not prove the fact itself leads
            found = anchors(_strip_story_tag(line))
            numeric = {a for a in found if _is_quantity(a)}
            return numeric or found

        if not any(key_anchors(line) & hook_anchors for line in leaders):
            add(EditorialFinding("hook_misses_strongest_fact", BLOCKING, 0,
                                 f"the strongest supported fact is not what the post leads with: {_strip_story_tag(leaders[0])!r}"))
        for s, _, line in scored:
            if s < top - 1 or s < 5:
                break
            numeric = {a for a in anchors(_strip_story_tag(line)) if _is_quantity(a)}
            if numeric and not numeric & post_anchors:
                add(EditorialFinding("strongest_fact_dropped", BLOCKING, None,
                                     f"a top-tier supported fact never appears on any card: {_strip_story_tag(line)!r}"))

    # 2. HOOK: concrete, framed strongly, short enough for display type
    hook = cards[0]["head"]
    fragments = [f for f in re.split(r"[.!?]\s*", hook) if f.strip()]
    if len(fragments) >= 3 and all(len(_words(f)) <= 3 for f in fragments) and "?" not in hook:
        add(EditorialFinding("hook_is_a_label_chain", BLOCKING, 0,
                             f"three short noun fragments state the topic, not why it is interesting: {hook!r}"))
    if len(hook) > HOOK_DISPLAY_MAX_CHARS:
        add(EditorialFinding("hook_too_long_for_display", BLOCKING, 0,
                             f"{len(hook)} characters cannot be set at display size ({HOOK_DISPLAY_MAX_CHARS} max): {hook!r}"))

    # 3. USABLE CONTENT: an instruction to ask/write something must survive as quotable wording
    instruction_lines = [line for line in evidence if _INSTRUCTION.search(line)]
    if instruction_lines and not re.search(r"«[^»]{8,}»|\"[^\"]{8,}\"", post_text):
        add(EditorialFinding("usable_instruction_paraphrased", BLOCKING, None,
                             "the evidence gives exact things to ask/write, but no card quotes them - the save value was summarised away"))
    for idx, card in enumerate(cards):
        for line in instruction_lines:
            ask = re.search(r"(?:попросить|попроси|спросить|спроси)\s+(.+)", line, re.IGNORECASE)
            if not ask:
                continue
            if len(content_stems(ask.group(1)) & content_stems(card["body"])) >= 2 and not re.search(
                    r"попрос|напиш|спрос|запрос|«|модел|\bии\b", card["body"], re.IGNORECASE):
                add(EditorialFinding("instruction_actor_changed", BLOCKING, idx,
                                     "the evidence says to ASK the model to do this; the card tells the reader to do it themselves"))
                break

    # 4. REPETITION: every card adds something; headline and body do not restate each other
    seen: set[str] = set()
    for idx, card in enumerate(cards):
        head, body = content_stems(card["head"]), content_stems(_unquoted(card["body"]))
        stems = head | body | content_stems(card["steps"])
        if idx > 0 and len(stems) >= 5:
            new = stems - seen
            if len(new) / len(stems) < 0.34:
                add(EditorialFinding("card_adds_no_new_information", BLOCKING, idx,
                                     f"only {len(new)} of {len(stems)} content words are new - the card restates earlier cards"))
        for prev in range(idx):
            other = content_stems(_unquoted(cards[prev]["body"]))
            if len(body) >= 5 and len(other) >= 5 and len(body & other) / len(body | other) >= 0.45:
                add(EditorialFinding("card_repeats_card", BLOCKING, idx, f"its body repeats card {prev + 1}'s body"))
        if head and body:
            overlap = head & body
            if len(head) >= 2 and len(overlap) / len(head) >= 0.6 and len(body - head) <= 4:
                add(EditorialFinding("body_repeats_headline", BLOCKING, idx, f"the body restates the headline instead of developing it: {card['body']!r}"))
            elif len(head) >= 2 and head <= body and re.search(r"[A-Za-z]{2,}", card["head"]):  # a named claim restated, not a step label
                add(EditorialFinding("body_restates_headline_claim", BLOCKING, idx,
                                     f"every content word of the headline is restated in the body instead of being developed: {card['body']!r}"))
            elif len(overlap) >= 2:
                add(EditorialFinding("phrase_repeated_in_card", ADVISORY, idx,
                                     f"headline and body repeat the same words: {sorted(overlap)}"))
        seen |= stems
    for idx, card in enumerate(cards):
        mine = content_stems(card["body"]) | {a for a in anchors(card["body"]) if not re.search(r"^\d", a)}
        for prev in range(idx):
            theirs = content_stems(_full(cards[prev])) | {a for a in anchors(_full(cards[prev])) if not re.search(r"^\d", a)}
            shared = mine & theirs
            if len(shared) >= 4 and len(shared) / max(1, len(mine)) >= 0.5:
                add(EditorialFinding("list_repeated_from_earlier_card", ADVISORY, idx, f"repeats card {prev + 1}'s list: {sorted(shared)}"))
                break
    for stem in set.intersection(*[content_stems(_full(c)) for c in cards]) if len(cards) >= 3 else set():
        add(EditorialFinding("same_point_on_every_card", ADVISORY, None, f"'{stem}...' appears on every card"))

    # 5. FACT FIDELITY: tense/aspect of a fact, attribution of a claim, launch order
    for line in evidence:
        text = _strip_story_tag(line)
        subjects = {a for a in anchors(text) if not re.search(r"\d", a)}
        for m in re.finditer(rf"\b([а-яё]{{3,}}?){_COMPLETED}\b", text.lower()):
            stem = m.group(1)[:4]
            if len(stem) < 4 or _PLANNED.search(text.lower()[: m.start()][-40:]):
                continue
            for idx, card in enumerate(cards):
                copy = _full(card).lower()
                if subjects & anchors(_full(card)) and re.search(rf"{_PLANNED.pattern}[^.]{{0,25}}\b{stem}\w*", copy):
                    add(EditorialFinding("completed_fact_turned_into_plan", BLOCKING, idx,
                                         f"the evidence states it as done ({m.group(0)!r}); the card turns it into a plan"))
    for idx, card in enumerate(cards):
        if re.search(r"\b(?:ии|технологии|рынок|индустрия)\s+(?:стал|стали|становит|становят|движ)", _full(card).lower()):
            add(EditorialFinding("claim_stronger_than_evidence", BLOCKING, idx,
                                 "a generalisation about AI/technology as a whole - the evidence only supports specific companies' claims"))
    launched: set[str] = set()
    for idx, card in enumerate(cards):
        names = {a for a in anchors(card["head"]) if not re.search(r"^\d", a)}
        if idx > 0 and names & launched and re.search(r"\b(?:запущен\w*|представил\w*|вышл\w*|анонсир\w*)", card["head"].lower()):
            add(EditorialFinding("launch_after_discussion", BLOCKING, idx, "announces the launch of something earlier cards already discussed"))
        launched |= names

    # 6. RUSSIAN EDITORIAL LINT: general, high-precision patterns only
    def lint(idx: int | None, text: str) -> None:
        low = text.lower()
        rules = [
            (r"\b(?:неделя|неделе|неделю|год|месяц|день),?\s+где\b", BLOCKING, "temporal_where", "time words take «когда», not «где»"),
            (r"\bв\s+(?:этой|прошлой|следующей|эту|прошлую)\s+недел", BLOCKING, "wrong_preposition_week", "«на этой неделе», not «в этой неделе»"),
            (r"\bстартов\w*\s+цен\w*[^.]{0,20}\bначина", BLOCKING, "tautology", "«стартовая цена начинается от» says the same thing twice"),
            (r"\bприня(?:л|ла|ли)\s+[A-Za-z]", BLOCKING, "calque_adopted", "«принял <standard>» is a calque of 'adopted' - «поддерживает», «перешёл на»"),
            (r"^это\s+(?:ещё|еще|и|же|не|тоже)\b", BLOCKING, "pronoun_without_referent", "a headline that opens with «Это ...» has no referent"),
            (r"\bможно использовать для\b", ADVISORY, "bureaucratic_phrase", "«можно использовать для» reads as a manual"),
            (r"\bсво(?:я|й|ё|и)\s+(?:заявленн\w+\s+)?рол", ADVISORY, "empty_filler", "«своя роль» says nothing concrete"),
            (r"стоит следить|движутся не в одну сторону|обычно хочется|в этом (?:как раз )?(?:и )?(?:её|его) смысл", ADVISORY, "empty_filler",
             "a filler sentence with no fact in it"),
            (r"\b(?:варианты|аспекты|моменты)\b", ADVISORY, "vague_noun", "a vague noun where a concrete one belongs"),
            (r"\w+(?:нной|енной|анной|ённой)\b[^.]{0,40}\bи\s+\w+(?:нной|енной|анной|ённой)\b", ADVISORY, "participle_chain",
             "two passive participles in a row read as bureaucratic Russian"),
        ]
        for pattern, severity, code, why in rules:
            if re.search(pattern, low.strip()):
                add(EditorialFinding(f"russian_{code}", severity, idx, f"{why}: {text.strip()!r}"))

    for idx, card in enumerate(cards):
        lint(idx, card["head"])
        lint(idx, card["body"])
        if idx > 0 and re.match(r"^(?:что именно|главный вопрос|главное здесь|вот что|вот почему|и это ещё)\b", card["head"].lower().strip()):
            add(EditorialFinding("label_headline", BLOCKING, idx, f"a teaser label, not information: {card['head']!r}"))
    if caption:
        lint(None, caption)

    # 7. PRACTICAL VALUE for how-to / insight posts: at least one card tells the reader what to do
    if archetype in ("ai_hack", "news_insight"):
        imperative = re.compile(r"\b(?:возьми|посчитай|сравни|попробуй|проверь|попроси|напиши|вставь|сохрани|выбирай|спроси|открой|включи|оцени)\b",
                                re.IGNORECASE)
        if not any(imperative.search(c["body"]) or imperative.search(c["head"]) for c in cards[1:]):
            add(EditorialFinding("no_practical_takeaway", BLOCKING, None,
                                 "a how-to/insight post with no card telling the reader what to actually do"))
    # The critic is a safety net, not the editor (founder, after the v10.8 run): it BLOCKS only what makes a post false, loses its core
    # value or cannot be displayed; every taste / language judgment is reported as advisory for the editorial review instead.
    return [EditorialFinding(f.code, BLOCKING if f.code in GATING_CODES else ADVISORY, f.card, f.detail) for f in findings]


def blocking(findings: list[EditorialFinding]) -> list[EditorialFinding]:
    return [f for f in findings if f.severity == BLOCKING]


def assert_editorial_quality(slides: list[Any], evidence: list[str], *, archetype: str | None = None, caption: str = "") -> list[EditorialFinding]:
    findings = critique(slides, evidence, archetype=archetype, caption=caption)
    hard = blocking(findings)
    if hard:
        raise EditorialQualityError("editorial review rejected the plan: " + "; ".join(f.render() for f in hard))
    return findings
