"""Editorial judgment reset: generate prompts/instagram_creative_director_carousel/v10.8.yaml from the (untouched) v10.7 file.

The v10.7 paid validation (4 real calls) learned the FORM (every card has a body) but not the JUDGMENT. First failures, per output:
  - NEWS_RECAP led with a weaker claim; the strongest supported fact (an extreme price/performance ratio) never appeared; 7 generated
    slides against a bound of 6 that NO prompt ever stated; a completed fact was rewritten as a plan;
  - AI_HACK paraphrased the exact prompts that were the post's whole save value and repeated the two steps on four cards;
  - NEWS_INSIGHT used label headlines ("Что именно изменилось...") and gave the reader nothing to do;
  - TREND_GENERATIVE padded one fact over four cards with tautologies and a pronoun-led headline.
v10.8 makes angle selection an explicit, compared decision (angle_candidates -> editorial_angle), states the real output bounds up front,
and adds the editing rules the deterministic critic (services/instagram_editorial_critic.py) enforces - so the FIRST output fits.

Usage: python scripts/_instagram_make_prompt_v10_8.py"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
V107 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.7.yaml"
V108 = ROOT / "prompts" / "instagram_creative_director_carousel" / "v10.8.yaml"

_SYSTEM_ADD = (
    " Your output is checked by an editorial reviewer that rejects: a post that does not lead with its strongest supported fact, exact"
    " usable wording summarised away, cards that repeat each other, a body that restates its headline, facts whose tense or attribution"
    " changed, and unnatural Russian. Write it right the first time."
)

_NEW_RULES = [
    "ANGLE SELECTION IS A COMPARISON, NOT A SUMMARY. In angle_candidates list 2 to 4 genuinely different angles the evidence supports, each"
    " with its evidence handle(s) and why it would stop a reader. Rank them by stop value: an extreme ratio or percentage, a price, a big"
    " number, a price-versus-performance or product-versus-product comparison, something the reader can use today, or a real contradiction"
    " beats a plain 'X launched Y' / 'X announced Y'. Ask which fact a reader would forward to a friend. editorial_angle is the winner, and the"
    " hook carries ITS specific number, price or name. In a recap the post opens with the week's single strongest fact, even when it is not"
    " the first story in the list, and no top fact (an extreme number or comparison) may be missing from the carousel.",
    "HOOK: frame the FACT strongly - do not bolt 'Серьёзно?', 'Неожиданно' or 'Вот это поворот' onto a weak line. A hook that is three"
    " noun fragments ('Длинный текст. Два шага. Чек-лист.') names a topic, not a reason; rewrite it around the stake or the number. The hook"
    " is at most 60 characters so it can be set at display size; context goes in its one-sentence slide_body.",
    "USABLE CONTENT SURVIVES VERBATIM. When the evidence contains something the reader can use directly - the exact thing to ask a model,"
    " a command, a setting, a concrete method - quote it in «...» on the card where it is used. Never summarise away the part a reader"
    " would save. Keep who does what: if the evidence says to ASK the model to do something, the card says to ask the model, not to do it by hand.",
    "EVERY CARD ADDS NEW VALUE. A card after the hook must bring something the earlier cards did not: a new fact, why it matters, a"
    " practical use, a limitation, a comparison, the answer to the hook. Never restate an earlier card's list or point in other words. If the"
    " story supports only three strong cards, make three - three strong cards beat five repetitive ones. How-to and insight posts include at"
    " least one card that tells the reader exactly what to do.",
    "HEADLINE AND BODY DIVIDE THE WORK: the headline says what happened; the body says why it is interesting or what else matters. The body"
    " never restates the headline ('Xiaomi открыла веса' / 'Xiaomi выпускает серию с открытыми весами' adds nothing). Headlines carry"
    " information - never a teaser label such as 'Что именно изменилось', 'Главный вопрос теперь звучит иначе', 'Главное здесь - ...'.",
    "FACT FIDELITY. Keep each fact's tense and status exactly as the evidence gives it: what is done stays done, what is planned stays"
    " planned (an already trained model is never 'planned to be trained'). Keep attribution for claims ('OpenAI заявляет', 'утверждается')."
    " Never generalise one company's claim into 'ИИ стал ...' or 'технологии ...'. Keep chronology: never announce the launch of something"
    " an earlier card already discussed.",
    "RUSSIAN EDITING. Write modern, natural, conversational Russian that a good editor would sign off - correct, never formal-for-safety"
    " (conversational words such as 'выкатили', 'где подвох?', 'ты бы взял?' are welcome when natural). Before you output, reread every"
    " card as a Russian editor and fix: time words take 'когда', not 'где' ('неделя, когда'); 'на этой неделе', never 'в этой неделе';"
    " no tautology ('стартовая цена начинается от'); no calques ('принял стандарт' -> 'поддерживает'); no headline that opens with a"
    " bare 'Это ...'; no chains of passive participles ('..., предложенной ... и переданной ...'); no vague nouns ('варианты', 'моменты')"
    " where a concrete word belongs; no filler sentences without a fact ('за этим стоит следить', 'движутся не в одну сторону'); no"
    " repeated words or sentence shapes on neighbouring lines; every 'это', 'она', 'они' has an obvious referent.",
    "OUTPUT BOUNDS (the renderer and contract enforce these; plan within them): at most 6 slides with media_source 'generated' in one"
    " post - in a recap with more stories than that, use a story's own suitable source image or a substantive graphic for the rest;"
    " at most 10 slides in total; the hook headline at most 60 characters; a body at most 3 short sentences.",
]


def build() -> dict:
    doc = copy.deepcopy(yaml.safe_load(V107.read_text(encoding="utf-8")))
    doc["version"] = "10.8"
    doc["system"] = doc["system"].rstrip() + _SYSTEM_ADD
    doc["rules"] = list(doc["rules"]) + _NEW_RULES
    schema = doc["output_schema"]
    candidate = {
        "type": "object", "additionalProperties": False, "required": ["angle", "evidence", "stop_value"],
        "properties": {"angle": {"type": "string", "maxLength": 240}, "evidence": {"type": "string", "maxLength": 60},
                       "stop_value": {"type": "string", "maxLength": 240}},
    }
    schema["properties"] = {"angle_candidates": {"type": "array", "minItems": 2, "maxItems": 4, "items": candidate}, **schema["properties"]}
    schema["required"] = ["angle_candidates", *schema["required"]]
    schema["properties"]["slides"]["maxItems"] = 10  # Instagram's platform ceiling, now part of the output shape itself
    return doc


def main() -> None:
    header = (
        "# Editorial judgment reset: v10.8 = v10.7 + compared angle selection (angle_candidates), stated output bounds, verbatim usable content,\n"
        "# new-value-per-card, headline/body division, fact fidelity and Russian editing rules. v10.7 stays published and untouched.\n"
    )
    V108.write_text(header + yaml.safe_dump(build(), allow_unicode=True, sort_keys=False, width=240), encoding="utf-8")
    print("wrote", V108)


if __name__ == "__main__":
    main()
