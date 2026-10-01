"""Offline proof of generated-scene diversity. 0 provider calls, 0 image calls: only prompt text is compiled.

Real fixtures: the saved 29 Sep Sonnet carousel (monotone blocks) and the saved 30 Sep controlled Sonnet carousel (current evidence).
Synthetic fixtures (clearly labelled in the report) for the gadget / viral / incident stories - they exercise the rules, they are not model output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.instagram_creative_media import compile_instagram_generation_prompt  # noqa: E402
from services.instagram_scene_diversity import diversify_slide_briefs, dominant_scene_concepts, slide_scene_plan  # noqa: E402

OUT = ROOT / "artifacts" / "instagram_feed_product" / "scene_diversity_20261001"
A29 = ROOT / "artifacts/instagram_feed_product/final_natural_acceptance_20260929/attempt_2/post/package.json"
A30 = ROOT / "artifacts/instagram_feed_product/sonnet_editorial_acceptance_20260930/resume/post/director_raw_output.json"


def _slides_29() -> tuple[list[dict], dict]:
    pk = json.loads(A29.read_text(encoding="utf-8"))
    slides = [
        {"role": s["role"], "slide_copy": s["text"], "slide_body": s.get("body") or "", "media_source": s["media_source"],
         "generation_brief": s["generation_brief"], "visual_direction": s["visual_direction"], "slide_purpose": s.get("slide_purpose")}
        for s in pk["media_plan"]["slides"]
    ]
    return slides, pk["media_plan"]["creative_execution_plan"]


def _slides_30() -> tuple[list[dict], dict]:
    so = json.loads(A30.read_text(encoding="utf-8"))["structured_output"]
    slides = [
        {"role": s["role"], "slide_copy": s["slide_copy"], "slide_body": s.get("slide_body") or "", "media_source": s["media_source"],
         "generation_brief": s["generation_brief"], "visual_direction": s.get("visual_direction") or "", "slide_purpose": s.get("slide_purpose")}
        for s in so["slides"]
    ]
    return slides, so["creative_execution_plan"]


def _g(role: str, copy: str, body: str, brief: str) -> dict:
    return {"role": role, "slide_copy": copy, "slide_body": body, "media_source": "generated", "generation_brief": brief,
            "visual_direction": "synthetic fixture", "slide_purpose": role}


# SYNTHETIC: what a Director could write for each story. `monotone` = the failure mode; `diverse` = one beat -> its own scene.
GENRES = {
    "gadget_launch": {
        "plan": {"main_idea": "Часы как набор одинаковых металлических дисков", "visual_treatment": "Brushed metal discs photographed like jewellery"},
        "monotone": [
            _g("hook", "Новые часы за $249", "Экран AMOLED, 14 дней без зарядки.", "Editorial still life: one brushed metal disc on a dark ground, no text or logos."),
            _g("context", "Экран ярче прежнего", "До 3000 нит на улице.", "Editorial still life: two brushed metal discs, one brighter, on a pale surface, no text or logos."),
            _g("evidence", "Две недели без зарядки", "Заявленный ресурс — 14 дней.", "Editorial still life: a stack of brushed metal discs, tallest on the left, no text or logos."),
            _g("takeaway", "Цена — от $249", "Продажи стартуют в сентябре.", "Editorial still life: metal discs arranged in a row on a graphite ground, no text or logos."),
        ],
        "diverse": [
            _g("hook", "Новые часы за $249", "Экран AMOLED, 14 дней без зарядки.", "Editorial still life: a blank wrist-sized dark glass slab resting on warm paper, one violet reflection, no text or logos."),
            _g("context", "Экран ярче прежнего", "До 3000 нит на улице.", "Editorial scene: a hard beam of sunlight cutting across a dark stone ledge with a faint glare bloom, no text or logos."),
            _g("evidence", "Две недели без зарядки", "Заявленный ресурс — 14 дней.", "Editorial still life: a long row of identical unlit candles, only the last one still burning, no text or logos."),
            _g("takeaway", "Цена — от $249", "Продажи стартуют в сентябре.", "Editorial scene: an empty shop shelf with a single blank paper card catching window light, no readable writing."),
        ],
    },
    "viral_meme": {
        "plan": {"main_idea": "Интернет-мем про кота за клавиатурой", "visual_treatment": "Playful cat-on-keyboard scenes"},
        "monotone": [
            _g("hook", "Чат-бот извинился перед тостером", "Скриншот разошёлся по соцсетям.", "Ironic editorial scene: a cat sitting on a blank keyboard, no text or logos."),
            _g("context", "Всё началось с шутки", "Пользователь попросил бота извиниться.", "Ironic editorial scene: a cat pressing keys on a blank keyboard, no text or logos."),
            _g("evidence", "Бот извинился дважды", "Сообщения набрали тысячи реакций.", "Ironic editorial scene: two cats on a blank keyboard, no text or logos."),
            _g("takeaway", "Тостер не ответил", "Шутка живёт своей жизнью.", "Ironic editorial scene: a cat asleep on a blank keyboard, no text or logos."),
        ],
        "diverse": [
            _g("hook", "Чат-бот извинился перед тостером", "Скриншот разошёлся по соцсетям.", "Ironic editorial still life: a toaster on a kitchen counter receiving a tiny formal bow from a blank paper-craft figure, no text or logos."),
            _g("context", "Всё началось с шутки", "Пользователь попросил бота извиниться.", "Editorial scene: a speech-bubble-shaped cutout of frosted glass lifted over a dark slab, no readable writing."),
            _g("evidence", "Бот извинился дважды", "Сообщения набрали тысячи реакций.", "Editorial scene: a wall of identical small blank enamel hearts multiplying across a dark corkboard, no text or numbers."),
            _g("takeaway", "Тостер не ответил", "Шутка живёт своей жизнью.", "Ironic editorial still life: a lone toaster in a spotlight on a stage facing an empty row of chairs, no text or logos."),
        ],
    },
    "serious_incident": {
        "plan": {"main_idea": "Утечка как трещина в стеклянной стене", "visual_treatment": "Cracked glass walls, cold light"},
        "monotone": [
            _g("hook", "Утекли данные 2 млн клиентов", "Компания подтвердила взлом.", "Editorial still life: a cracked glass wall in cold light, no text or logos."),
            _g("context", "Как это произошло", "Злоумышленники получили доступ через подрядчика.", "Editorial still life: a larger crack spreading through a glass wall, no text or logos."),
            _g("evidence", "Что именно утекло", "Имена и почтовые адреса, без паролей.", "Editorial still life: shards of a cracked glass wall on a floor, no text or logos."),
            _g("takeaway", "Что делать клиентам", "Сменить пароли и включить двойную защиту.", "Editorial still life: a repaired glass wall with a visible seam, no text or logos."),
        ],
        "diverse": [
            _g("hook", "Утекли данные 2 млн клиентов", "Компания подтвердила взлом.", "Editorial still life: a heavy blank archive box with its lid slightly open and loose blank paper slips spilling out, cold light, no text."),
            _g("context", "Как это произошло", "Злоумышленники получили доступ через подрядчика.", "Editorial scene: a service-corridor door propped open with a wedge, daylight spilling into a dark hall, no people, no text."),
            _g("evidence", "Что именно утекло", "Имена и почтовые адреса, без паролей.", "Editorial still life: rows of blank envelopes fanned on a desk beside a small locked blank case left untouched, no writing."),
            _g("takeaway", "Что делать клиентам", "Сменить пароли и включить двойную защиту.", "Editorial still life: a hand turning a key in a second lock on an already-locked blank door, no text or logos."),
        ],
    },
}


def _prompts(slides: list[dict], plan: dict, *, new: bool, summary: str) -> list[dict]:
    work, notes = diversify_slide_briefs(slides) if new else (slides, [])
    rows = []
    for i, s in enumerate(work):
        p = slide_scene_plan(plan, work, i) if new else plan
        prompt = compile_instagram_generation_prompt(
            plan=p, opportunity_summary=summary, evidence=[s["slide_body"] or s["slide_copy"]], content_format="carousel", slide=s,
        )
        rows.append({"slide": i, "brief": s["generation_brief"], "prompt": prompt, "note": next((n for n in notes if n["slide"] == i), None)})
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    s29, plan29 = _slides_29()
    report["sonnet_29sep_old_behavior"] = _prompts(s29, plan29, new=False, summary="Sonnet 5.5 заменит Sonnet 5")
    report["sonnet_29sep_new_behavior"] = _prompts(s29, plan29, new=True, summary="Sonnet 5.5 заменит Sonnet 5")
    report["sonnet_29sep_dominant_concepts"] = dominant_scene_concepts([s["generation_brief"] for s in s29])
    s30, plan30 = _slides_30()
    report["sonnet_30sep_dominant_concepts"] = dominant_scene_concepts([s["generation_brief"] for s in s30])
    report["sonnet_30sep_new_behavior"] = _prompts(s30, plan30, new=True, summary="Sonnet 5.5: быстрее и дешевле для рабочих задач")
    for name, g in GENRES.items():
        report[name] = {
            "synthetic_fixture": True,
            "monotone_dominant": dominant_scene_concepts([s["generation_brief"] for s in g["monotone"]]),
            "monotone_after": [{"slide": r["slide"], "brief": r["brief"], "note": r["note"]} for r in _prompts(g["monotone"], g["plan"], new=True, summary=name)],
            "diverse_dominant": dominant_scene_concepts([s["generation_brief"] for s in g["diverse"]]),
            "diverse_unchanged": all(a["generation_brief"] == b["generation_brief"] for a, b in zip(g["diverse"], diversify_slide_briefs(g["diverse"])[0])),
        }
    (OUT / "scene_diversity_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("29sep dominant:", report["sonnet_29sep_dominant_concepts"], "| 30sep dominant:", report["sonnet_30sep_dominant_concepts"])
    for r in report["sonnet_29sep_new_behavior"]:
        print(r["slide"], r["note"], "\n   ", r["brief"][:230])
    for name in GENRES:
        g = report[name]
        print(name, "monotone dominant:", g["monotone_dominant"], "| diverse dominant:", g["diverse_dominant"], "| diverse unchanged:", g["diverse_unchanged"])
        for r in g["monotone_after"]:
            print("   ", r["slide"], (r["note"] or {}).get("action"), "|", r["brief"][:120])


if __name__ == "__main__":
    main()
