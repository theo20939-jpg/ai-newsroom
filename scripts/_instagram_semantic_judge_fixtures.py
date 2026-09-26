"""Neutral (non-GTA) fixtures for the viral-carousel semantic editorial judge (founder task 2026-09-26, offline items 4-10).

Each fixture is (slides, caption, evidence, expectation). `expect` names what the semantic judge must report (or not), and `deterministic`
what the zero-cost deterministic rules must report: "fail" = at least one finding, "pass" = none, "judge_only" = beyond deterministic
reach (the reason the judge exists), so the deterministic result is recorded, not asserted."""
from __future__ import annotations


def s(head: str, body: str, ref: str = "E1") -> dict:
    return {"role": "beat", "slide_copy": head, "slide_body": body, "source_evidence": ref}


BRIDGE_EVIDENCE = ["Мэрия закрыла Южный мост на ремонт: движение по нему остановлено до сентября.",
                   "На время ремонта запущены два дополнительных автобусных маршрута через Северный мост."]
VACUUM_EVIDENCE = ["Робот-пылесос выехал из квартиры в Сеуле через открытую дверь.",
                   "Через два часа пылесос нашли в парке у дома с почти разряженной батареей.",
                   "Соседка узнала пылесос по наклейке с адресом и вернула его хозяйке."]
APP_EVIDENCE = ["В приложение добавили поддержку новых форматов изображений: WebP, AVIF и HEIC.",
                "Фотографии с iPhone теперь открываются без конвертации."]

FIXTURES: dict[str, dict] = {
    # 4. no shared vocabulary, one thesis (the bridge is closed until September)
    "4_paraphrase_no_shared_words": {
        "slides": [s("Мэрия закрыла Южный мост", "Движение остановили на всё лето."),
                   s("Переправа недоступна до сентября", "Городские власти перекрыли её для ремонтных работ."),
                   s("Для объезда пустили два автобуса", "Новые маршруты идут через Северный мост.", "E2")],
        "caption": "Южный мост закрыт на ремонт до сентября, на время работ запустили два автобусных маршрута.",
        "evidence": BRIDGE_EVIDENCE, "expect": {"pairs": [(1, 2)], "aphorism": False}, "deterministic": "judge_only"},
    # 5. many shared words, different facts (escape -> found)
    "5_shared_words_different_facts": {
        "slides": [s("Робот-пылесос сбежал из квартиры", "Хозяйка оставила дверь открытой - и пылесос уехал."),
                   s("Через два часа пылесос нашли", "Пылесос из той же квартиры стоял в парке у дома с почти пустой батареей.", "E2"),
                   s("Вернула его соседка", "Она узнала пылесос по наклейке с адресом.", "E3")],
        "caption": "В Сеуле робот-пылесос выехал из квартиры и через два часа нашёлся в парке у дома.",
        "evidence": VACUUM_EVIDENCE, "expect": {"pairs": [], "aphorism": False}, "deterministic": "pass"},
    # 6. a generic claim, then only its component list
    "6_generic_claim_then_component_list": {
        "slides": [s("Приложение обновили", "Разработчики добавили поддержку новых форматов изображений."),
                   s("Какие форматы", "Разработчики добавили поддержку форматов WebP, AVIF и HEIC."),
                   s("Что это даёт", "Фотографии с iPhone теперь открываются без конвертации.", "E2")],
        "caption": "Приложение научилось открывать фотографии с iPhone без конвертации.",
        "evidence": APP_EVIDENCE, "expect": {"pairs": [(1, 2)], "aphorism": False}, "deterministic": "fail"},
    # 7. one evidence item, two genuinely distinct facts
    "7_same_evidence_two_facts": {
        "slides": [s("Южный мост закрыли до сентября", "Мэрия начала там ремонт."),
                   s("Объезжать придётся на автобусе", "Пустили два маршрута через Северный мост.")],
        "caption": "Южный мост закрыт на ремонт до сентября.",
        "evidence": ["Мэрия закрыла Южный мост на ремонт до сентября; на время работ запущены два автобусных маршрута через Северный мост."],
        "expect": {"pairs": [], "aphorism": False}, "deterministic": "pass"},
    # 8. a caption that is only a factual summary
    "8_caption_factual_summary": {
        "slides": [s("Робот-пылесос сбежал из квартиры", "Хозяйка оставила дверь открытой - и пылесос уехал."),
                   s("Через два часа пылесос нашли", "Он стоял в парке у дома с почти пустой батареей.", "E2"),
                   s("Вернула его соседка", "Она узнала пылесос по наклейке с адресом.", "E3")],
        "caption": "Робот-пылесос из Сеула сбежал через открытую дверь и нашёлся в парке через два часа.",
        "evidence": VACUUM_EVIDENCE, "expect": {"pairs": [], "aphorism": False, "repeats": False}, "deterministic": "pass"},
    # 9. slides already carry the dry payoff; the caption adds a generic moral
    "9_caption_moral_after_payoff": {
        "slides": [s("Робот-пылесос сбежал из квартиры", "Хозяйка оставила дверь открытой - и пылесос уехал."),
                   s("Через два часа пылесос нашли", "Он стоял в парке у дома с почти пустой батареей.", "E2"),
                   s("Домой его привела соседка", "Узнала по наклейке с адресом. Прогулка удалась.", "E3")],
        "caption": "Робот-пылесос из Сеула сбежал через открытую дверь и нашёлся в парке. Иногда свобода заканчивается там, где садится батарея.",
        "evidence": VACUUM_EVIDENCE, "expect": {"pairs": [], "aphorism": True}, "deterministic": "judge_only"},
    # 10. a caption with new grounded context the slides do not give
    "10_caption_new_context": {
        "slides": [s("Мэрия закрыла Южный мост", "Ездить по нему нельзя до сентября."),
                   s("Для объезда пустили автобусы", "Два новых маршрута идут через Северный мост.", "E2")],
        "caption": "Ремонт Южного моста продлится до сентября; обычный транспорт до Северного моста ходит без изменений.",
        "evidence": [*BRIDGE_EVIDENCE, "Остальные маршруты до Северного моста работают без изменений."],
        "expect": {"pairs": [], "aphorism": False, "repeats": False}, "deterministic": "pass"},
}
