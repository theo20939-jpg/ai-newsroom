"""INSTAGRAM-VISUAL-SYSTEM-V1-1 section 18/19/25: the realistic review canary. Produces the 8
required examples (NEWS-gadget/product, NEWS-AI/software, BREAKING, DATA-with-graph,
DATA-metric-only, QUOTE-with-portrait, a 6-slide CAROUSEL, REEL COVER) plus one combined contact
sheet, so the Founder can judge the new Instagram visual system in one board. Cyrillic/Russian
NINJA PULSE copy is used throughout (section 18's own instruction) - no English placeholder
headlines like "500 MILLION USERS" or "This changes everything" anywhere in this script.

Uses only real, already-approved local image fixtures (section 18's "realistic fixture content and
imagery already legally/locally available in the project") - no image generation, no network calls.
STOPS after writing the renders + contact sheet (section 25) - no publish, no credentials."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_carousel_layouts import render_carousel_slide
from services.instagram_data_layouts import render_data_layout
from services.instagram_editorial_layouts import render_breaking_layout, render_news_layout
from services.instagram_quote_layouts import render_quote_layout
from services.instagram_reel_layouts import render_reel_cover
from services.instagram_visual_profiles import InstagramRenderProfile, profile_spec

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SOURCES = _REPO_ROOT / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources"
_PORTRAIT = _REPO_ROOT / "tests" / "fixtures" / "portrait_public_figure.jpg"
OUT = _REPO_ROOT / "artifacts" / "instagram_visual_system_v1_1"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    feed_spec = profile_spec(InstagramRenderProfile.PORTRAIT_FEED)
    carousel_spec = profile_spec(InstagramRenderProfile.CAROUSEL_SLIDE)
    reel_spec = profile_spec(InstagramRenderProfile.REEL_COVER)

    iphone = Image.open(_SOURCES / "case1_hero_product_iphone.jpg")
    duolingo = Image.open(_SOURCES / "case2_gadget_geometry_detail.jpg")
    snap_event = Image.open(_SOURCES / "case3_bright_promotional_scene.jpg")
    portrait = Image.open(_PORTRAIT)

    # 01 - NEWS, gadget/product (portrait source -> full_bleed variant)
    r1 = render_news_layout(
        spec=feed_spec, source_image=iphone, kicker="Технологии",
        headline="Apple представила новый iPhone 17 Pro",
        dek="Новый дизайн, более быстрый чип и увеличенная яркость экрана.",
        package_identity="canary-news-gadget",
    )
    r1.image.save(OUT / "01_NEWS_GADGET.jpg", quality=92)

    # 02 - NEWS, AI/software (landscape source -> split_panel variant)
    r2 = render_news_layout(
        spec=feed_spec, source_image=duolingo, kicker="Искусственный интеллект",
        headline="Бум ИИ-приложений для изучения языков продолжает расти",
        dek=None, package_identity="canary-news-ai",
    )
    r2.image.save(OUT / "02_NEWS_AI_SOFTWARE.jpg", quality=92)

    # 03 - BREAKING
    r3 = render_breaking_layout(
        spec=feed_spec, source_image=iphone,
        headline="Apple объявила о неожиданном снижении цен",
        dek="Акции компании отреагировали сразу после новости.",
        package_identity="canary-breaking",
    )
    r3.image.save(OUT / "03_BREAKING.jpg", quality=92)

    # 04 - DATA, with a real supplied series (never fabricated - these are the canary's own fixture
    # numbers, not a claim about any real company)
    r4 = render_data_layout(
        spec=feed_spec, kicker="Рынки", metric_value="4.2", metric_unit="x",
        metric_label="Рост корпоративного внедрения ИИ с 2023 года",
        context="Темпы внедрения ускоряются каждый квартал.",
        series=[("2023", 1.0), ("2024", 1.8), ("2025", 3.1), ("2026", 4.2)],
        package_identity="canary-data-graph",
    )
    r4.image.save(OUT / "04_DATA_WITH_GRAPH.jpg", quality=92)

    # 05 - DATA, metric only (no series supplied - the metric-only variant, never a fabricated chart)
    r5 = render_data_layout(
        spec=feed_spec, kicker="Рынки", metric_value="142", metric_unit="млрд",
        metric_label="Мировые расходы на инфраструктуру ИИ в этом году",
        context="Показатель обновил максимум на фоне расширения дата-центров.",
        series=None, package_identity="canary-data-metric",
    )
    r5.image.save(OUT / "05_DATA_METRIC_ONLY.jpg", quality=92)

    # 06 - QUOTE, with a real portrait (attribution matches the person actually pictured - the same
    # discipline the prior FOUNDER-VISUAL-POLISH-2 precedent established for this fixture)
    r6 = render_quote_layout(
        spec=feed_spec, quote="Технологии сами по себе ничего не значат. Важно то, во что мы верим и что создаём вместе.",
        speaker="Тим Кук", role="CEO, Apple", source_image=portrait,
        package_identity="canary-quote-portrait",
    )
    r6.image.save(OUT / "06_QUOTE_PORTRAIT.jpg", quality=92)

    # 07 - CAROUSEL, 6 slides spanning hook / context / data / comparison / explanation / cta -
    # exercising every slide-layout bucket in one real deck (section 11's own grammar requirement).
    slides = [
        ("hook", "Почему все вдруг заговорили о локальном ИИ на устройствах"),
        ("context", "Производители смартфонов десять лет делали ставку на облачный ИИ. Это быстро меняется."),
        ("data", "Локальные модели уже обрабатывают 78% повседневных запросов ассистента без обращения к серверу."),
        ("comparison", "Облачный ИИ: быстро обновляется, нужен интернет vs Локальный ИИ: мгновенно, работает офлайн"),
        ("explanation", "Уменьшенные модели работают прямо на чипе, сокращая задержку до миллисекунд."),
        ("cta", "Этот сдвиг уже у вас в кармане. Рассказываем, что будет дальше."),
    ]
    total = len(slides)
    for i, (role, copy) in enumerate(slides):
        hero = iphone if role == "hook" else None
        rc = render_carousel_slide(
            spec=carousel_spec, role=role, index=i, total=total, slide_copy=copy, source_evidence=None,
            package_identity="canary-carousel", hero_image=hero,
        )
        rc.image.save(OUT / f"07_CAROUSEL_{i:02d}_{role}.jpg", quality=92)

    # 08 - REEL COVER, real vertical-friendly promotional scene, grid/profile-crop-safe hook
    r8 = render_reel_cover(
        spec=reel_spec, kicker="Культура", hook="Новое мероприятие Snapchat бьёт рекорды посещаемости",
        source_image=snap_event, package_identity="canary-reel-cover",
    )
    r8.image.save(OUT / "08_REEL_COVER.jpg", quality=92)

    _contact_sheet(total_carousel_slides=total)
    print(f"wrote 8 canary formats ({7 + total} files) + 00_CONTACT_SHEET.jpg to {OUT}")
    return 0


def _contact_sheet(*, total_carousel_slides: int) -> None:
    order = [
        ("01_NEWS_GADGET.jpg", "01 NEWS - gadget/product (full_bleed)"),
        ("02_NEWS_AI_SOFTWARE.jpg", "02 NEWS - AI/software (split_panel)"),
        ("03_BREAKING.jpg", "03 BREAKING"),
        ("04_DATA_WITH_GRAPH.jpg", "04 DATA - with real series"),
        ("05_DATA_METRIC_ONLY.jpg", "05 DATA - metric only"),
        ("06_QUOTE_PORTRAIT.jpg", "06 QUOTE - real portrait"),
        ("07_CAROUSEL_00_hook.jpg", "07 CAROUSEL - slide 1 (hook)"),
        ("07_CAROUSEL_02_data.jpg", "07 CAROUSEL - slide 3 (fact)"),
        ("07_CAROUSEL_03_comparison.jpg", "07 CAROUSEL - slide 4 (comparison)"),
        (f"07_CAROUSEL_{total_carousel_slides - 1:02d}_cta.jpg", "07 CAROUSEL - last slide (closing)"),
        ("08_REEL_COVER.jpg", "08 REEL COVER"),
    ]
    cols, cw, ch, pad, cap = 3, 420, 500, 22, 30
    W = cols * (cw + pad) + pad
    rows = (len(order) + cols - 1) // cols
    H = rows * (ch + cap + pad) + pad
    sheet = Image.new("RGB", (W, H), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    for i, (name, title) in enumerate(order):
        cx = pad + (i % cols) * (cw + pad)
        cy = pad + (i // cols) * (ch + cap + pad)
        p = OUT / name
        if p.exists():
            with Image.open(p) as im:
                t = im.convert("RGB")
                t.thumbnail((cw, ch))
                sheet.paste(t, (cx, cy + cap))
        d.text((cx, cy + 6), title, fill=(230, 230, 230))
    sheet.save(OUT / "00_CONTACT_SHEET.jpg", quality=90)


if __name__ == "__main__":
    raise SystemExit(main())
