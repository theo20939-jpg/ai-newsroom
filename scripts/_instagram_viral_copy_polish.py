"""Founder copy review (2026-09-26): VIRAL CAROUSEL COPY POLISH ONLY - zero provider calls.

The accepted DeepSeek and Hamster viral carousels keep everything but their audience-facing text: same evidence, facts, slide order and
count, generated pictures, layouts and typography. The rewrite (an editor's pass, below) goes through the Creative Director's OWN live
validation (services.instagram_creative_director._validate_carousel_output with the same viral director input - evidence handles,
fact safety, output policy, meta language, media-first contract, hook contract, clickbait, information density, editorial critic,
Russian-prose check and the new viral copy check), then renders over the exact same pictures. The previous copy is validated the same way
so the report shows what the new check catches.
Usage: python scripts/_instagram_viral_copy_polish.py <out dir>
"""
from __future__ import annotations

import copy
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "artifacts/instagram_feed_product/viral_carousel_20260926"
STORIES = {
    "deepseek": {"run": ROOT / "artifacts/instagram_feed_product/daily_media_cleanliness_20260926/live/2026-08-05_2_meme_trend",
                 "call": "01_director.json"},
    "hamster": {"run": ROOT / "artifacts/instagram_feed_product/e2e_week_2026-08-05_11/canary_run/2026-08-08_2_meme_trend",
                "call": "02_director.json"},
}

# NATURAL RUSSIAN + CONCRETE FACT + OPTIONAL DRY PUNCH (one per carousel, on the last slide). Every line maps to an evidence item.
POLISHED = {
    "deepseek": {
        "slides": [
            ("460 целей. Ни одного взлома.", "Так закончилась серия атак, которую почти целиком провёл ИИ-агент на DeepSeek."),
            ("Злоумышленник отправил в Telegram одну задачу.", "Это было в мае 2026 года. Других его сообщений восстановить не удалось."),
            ("После первой команды агент действовал сам.",
             "Искал в интернете цели, скачивал готовый код для атаки и пробовал его. Если не получалось — переходил к следующей."),
            ("У агента был доступ к терминалу и инструментам.",
             "Злоумышленник подключил DeepSeek к открытому фреймворку Hermes Agent. Фреймворк позволял агенту работать без надзора."),
            ("Работал сам. Не взломал ничего.",
             "Сессию целиком восстановили исследователи Unit 42 из Palo Alto Networks. Разбор вышел 30 июля."),
        ],
        "caption": ("В мае 2026 года злоумышленник отправил в Telegram одну задачу — дальше ИИ-агент на DeepSeek действовал сам. Он искал "
                    "цели, скачивал готовый код для атаки, пробовал его и переходил к следующей цели. Итог: больше 460 целей под атакой и ни "
                    "одной взломанной системы. Сессию восстановили исследователи Unit 42 из Palo Alto Networks."),
    },
    "hamster": {
        "slides": [
            ("Хомяк пробежал 6,06 мили.", "Столько хомячиха Mollie набегала за одну тренировку."),
            ("Колесо подключено к Strava.",
             "Физик из Утрехта, специалист по МРТ, собрал для него трекер скорости и дистанции. Об этом он рассказал на Reddit."),
            ("Хомячихе Mollie 10 месяцев.", "Она бегает каждую ночь. Дистанция, темп и время сами уходят в её аккаунт."),
            ("На эту тренировку ушло 4 часа 37 минут.", "Это одна из её недавних активностей в Strava."),
            ("У Mollie есть свой Strava.", "Колесо, трекер и отдельный аккаунт — всё как у настоящего бегуна."),
        ],
        "caption": ("Физик из Утрехта, специалист по МРТ, собрал трекер скорости и дистанции для колеса своего 10-месячного хомяка Mollie. "
                    "Данные автоматически уходят в её собственный аккаунт Strava: дистанция, темп и время каждой ночной пробежки. Одна из "
                    "недавних — 6,06 мили за 4 часа 37 минут."),
    },
}


def _director_input(name: str, cfg: dict):
    """The same viral director input the review used (persisted input + the review's overrides; media fields from its report)."""
    import scripts._instagram_viral_carousel_review as review
    from services.instagram_viral_format import VIRAL_CAROUSEL_NOTE

    persisted = json.loads((cfg["run"] / "director_input.json").read_text(encoding="utf-8"))
    decision = {**json.loads(persisted["editorial_decision"]), "recommended_format": "carousel"}
    media = json.loads((REVIEW / "report.json").read_text(encoding="utf-8"))[name].get("source_suitability") or {}
    report_run = json.loads((REVIEW / "report.json").read_text(encoding="utf-8")).get("previous_runs") or []
    media = media or next((r[name].get("source_suitability") for r in report_run if name in r and r[name].get("source_suitability")), {})
    return review._director_input(
        persisted, format="carousel", media_first=True, generated_media_available=True, fatigue_note="",
        editorial_decision=json.dumps(decision, ensure_ascii=False, sort_keys=True),
        available_media_subjects=tuple(media.get("available") or ("source",)), unsuitable_media_subjects=tuple(media.get("unsuitable") or ("source",)),
        planned_format="TREND", planned_archetype="trend_generative", viral_carousel_note=VIRAL_CAROUSEL_NOTE, contract_retry_note="")


def _validate(raw: dict, director_input) -> tuple[str, object]:
    import services.instagram_creative_director as cd

    try:
        outcome = cd._validate_carousel_output(copy.deepcopy(raw), None, director_input=director_input, archetype="trend_generative")
        return "PASS", outcome
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:600]}", None


def main() -> None:
    from services.instagram_art_validator import validate_instagram_art
    from services.instagram_content_package import InstagramContentPackage
    from services.instagram_creative_media import derive_image_identity
    from services.instagram_editorial_critic import critique
    from services.instagram_format_director import ContentFormat
    from services.instagram_generated_fallback import viral_generated_heroes
    from services.instagram_platform_renderer import render_instagram_carousel

    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    report, table = {"provider_calls": 0}, []
    for name, cfg in STORIES.items():
        raw = json.loads((REVIEW / name / "calls" / cfg["call"]).read_text(encoding="utf-8"))["response"]["structured_output"]
        polished = copy.deepcopy(raw)
        assert len(polished["slides"]) == len(POLISHED[name]["slides"])  # same slides, same order
        for slide, (head, body) in zip(polished["slides"], POLISHED[name]["slides"]):
            slide["slide_copy"], slide["slide_body"] = head, body
        polished["final_caption"] = POLISHED[name]["caption"]
        director_input = _director_input(name, cfg)
        before, _ = _validate(raw, director_input)
        after, outcome = _validate(polished, director_input)
        advisory = [f.render() for f in critique(list(outcome.carousel.slides), list(director_input.allowed_evidence),
                                                 caption=outcome.carousel.final_caption or "")] if outcome else []
        report[name] = {"before_validation_now": before, "after_validation": after, "after_critic_advisory": advisory}
        for i, (old, new) in enumerate(zip(raw["slides"], polished["slides"]), 1):
            table.append((name, i, old["slide_copy"], old.get("slide_body") or "", new["slide_copy"], new["slide_body"]))
        table.append((name, "caption", raw.get("final_caption") or "", "", polished["final_caption"], ""))
        if outcome is None:
            continue
        # the SAME package, pictures and layouts: only the slide text / body / caption change
        data = json.loads((REVIEW / name / "package.json").read_text(encoding="utf-8"))
        data = {k: v for k, v in data.items() if k in {f.name for f in dataclasses.fields(InstagramContentPackage)}}
        data["content_format"] = ContentFormat(data["content_format"])
        pkg = InstagramContentPackage(**data)
        slides, _heroes = viral_generated_heroes(copy.deepcopy(pkg.media_plan["slides"]))
        for slide, new in zip(slides, outcome.carousel.slides):
            slide["text"], slide["body"] = new.slide_copy, new.slide_body
        pkg = dataclasses.replace(pkg, caption=outcome.carousel.final_caption, media_plan={**pkg.media_plan, "slides": slides})
        pictures = {int(p.stem.split("_")[1]) - 1: Image.open(p).convert("RGB") for p in sorted((REVIEW / name / "generated").glob("slide_*.png"))}
        renders = render_instagram_carousel(
            pkg, slide_images=pictures, asset_identities={i: derive_image_identity(im) for i, im in pictures.items()},
            slide_subject_assets={i: {"generated": (im, derive_image_identity(im))} for i, im in pictures.items()})
        folder = out / name / "slides"
        folder.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(renders, 1):
            (folder / f"slide_{i:02d}.png").write_bytes(r.image_bytes)
        art = validate_instagram_art(pkg, renders)
        report[name].update(art_passed=art.passed, art_blocking=list(art.blocking_issues), same_pictures=sorted(pictures))
        (out / name / "polished_director_output.json").write_text(json.dumps(polished, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["| story | slide | BEFORE headline | BEFORE body | AFTER headline | AFTER body |", "|---|---|---|---|---|---|"]
    lines += [f"| {n} | {i} | {a} | {b} | {c} | {d} |" for n, i, a, b, c, d in table]
    (out / "before_after_copy.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        from services.instagram_text_fit import ig_font
    except ImportError:  # pragma: no cover
        ig_font = None
    rows = []
    for name in STORIES:
        rows.append((f"BEFORE - {name}: accepted copy", sorted((REVIEW / name / "slides").glob("slide_*.png"))))
        rows.append((f"AFTER - {name}: polished copy, same pictures and layouts (art gate {report[name].get('art_passed')})",
                     sorted((out / name / "slides").glob("slide_*.png"))))
    th, label = 380, 44
    width = max(sum(round(Image.open(p).width * th / Image.open(p).height) + 12 for p in files) for _, files in rows if files) + 24
    sheet = Image.new("RGB", (width, sum(th + label + 20 for _ in rows) + 16), (246, 246, 246))
    draw, y = ImageDraw.Draw(sheet), 14
    font = ig_font(24, "black") if ig_font else None
    for title, files in rows:
        draw.text((14, y + 8), title, font=font, fill=(170, 30, 30) if title.startswith("BEFORE") else (20, 20, 20))
        x = 14
        for p in files:
            im = Image.open(p).convert("RGB")
            w = round(im.width * th / im.height)
            sheet.paste(im.resize((w, th)), (x, y + label))
            x += w + 12
        y += th + label + 20
    sheet.save(out / "copy_polish_contact_sheet.png")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
