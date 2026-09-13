"""INSTAGRAM-AUTONOMOUS-TREND-TO-CAROUSEL-CANARY-1.

One real, autonomous, offline shadow canary: observe recent real newsroom evidence (read-only,
pulled from the live production Postgres via `docker exec ... psql` over SSH - see
`artifacts/instagram_autonomous_trend_canary_1/raw_events_18h.jsonl`), cluster it into trend
candidates, SCORE and RANK them, autonomously SELECT ONE trend (no topic given by the Founder),
choose a carousel angle, author the full carousel editorial structure grounded only in real pulled
evidence, render it through the real INSTAGRAM-VISUAL-SYSTEM-V1-1 renderer, run Art/editorial
validation, and prove the whole thing is shadow-publish-able with zero real network writes.

Honesty disclosure (this is NOT a live Creative-Director-LLM call): no Gateway/LLM call was made
anywhere in this script (`CreativeGenerationOutcome.call=None` throughout) - the trend clustering/
scoring/selection logic below IS this script's own real, deterministic code (not a stub), but the
carousel COPY itself was authored by the author of this script, playing the Director's editorial
role, grounded exclusively in the real headlines captured in `raw_events_18h.jsonl` - no invented
facts, numbers, or quotes anywhere in the slide copy (section 15). Every real, reusable piece of
the actual Director chain that COULD be called deterministically without a live LLM (`recommend_
objective()`, `evaluate_format_shadow()`, `build_shadow_plan()`, `build_instagram_content_package()`,
`render_instagram_carousel()`, `validate_instagram_art()`, `evaluate_instagram_editorial_gate()`,
`build_instagram_review_package()`, `publish_instagram_content()` in SHADOW mode) IS actually
called, not re-implemented or faked.

READ-ONLY against production. No DB writes, no container restart, no deploy, no VisualSpec
activation, no Telegram/Instagram publish, no credentials, no config change (section 25)."""
from __future__ import annotations

import asyncio
import collections
import json
import sys
from dataclasses import asdict
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_art_validator import validate_instagram_art
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import CreativeGenerationOutcome
from services.instagram_editorial_gate import evaluate_instagram_editorial_gate
from services.instagram_format_director import ContentFormat, evaluate_format_shadow
from services.instagram_objective_selection import recommend_objective
from services.instagram_platform_renderer import render_instagram_carousel
from services.instagram_publish_adapter import ShadowInstagramPublishClient, publish_instagram_content
from services.instagram_review_package import build_instagram_review_package
from services.instagram_shadow_pipeline import build_shadow_plan
from schemas.instagram_creative import InstagramCarouselCreative, InstagramCarouselSlideCreative

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS = _REPO_ROOT / "artifacts" / "instagram_autonomous_trend_canary_1"
_RAW_EVENTS_PATH = _ARTIFACTS / "raw_events_18h.jsonl"
_HERO_IMAGE_PATH = _REPO_ROOT / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources" / "case1_hero_product_iphone.jpg"

# NINJA PULSE editorial priority (section 5) - preferred categories score higher.
_CATEGORY_PRIORITY = {
    "AI": 1.0, "GADGETS": 0.95, "SOFTWARE": 0.85, "HARDWARE": 0.8, "STARTUPS": 0.6,
    "TECH": 0.55, "CYBERSECURITY": 0.5,
}


# =================================================================================================
# 1. Load real, already-pulled evidence + cluster into trend candidates (section 6)
# =================================================================================================

def load_events() -> list[dict]:
    with open(_RAW_EVENTS_PATH, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def cluster_candidates(events: list[dict]) -> list[dict]:
    """Groups the window's events by the REAL `story_id` the live Story Memory pipeline already
    assigned them (section 6's own "reuse Story Memory identities" instruction) - this script does
    NOT invent its own clustering algorithm; it reads the clustering the production system already
    computed. A handful of very recent events with no `story_id` yet (not yet processed by Story
    Memory at pull time) are excluded from clustering, not silently merged into anything."""
    by_story: dict[str, list[dict]] = collections.defaultdict(list)
    for ev in events:
        if ev.get("story_id"):
            by_story[ev["story_id"]].append(ev)

    candidates = []
    for story_id, items in by_story.items():
        items.sort(key=lambda e: e["created_at"])
        sources = sorted({i["source_name"] for i in items})
        categories = collections.Counter(i["category"] for i in items)
        candidates.append({
            "story_id": story_id,
            "story_title": items[0]["story_title"],
            "topic_bucket": items[0]["topic_bucket"],
            "category": categories.most_common(1)[0][0],
            "window_event_count": len(items),
            "distinct_source_count": len(sources),
            "sources": sources,
            "historical_total_event_count": items[0]["story_event_count"],
            "first_seen": items[0]["created_at"],
            "last_seen": items[-1]["created_at"],
            "items": items,
        })
    return candidates


# =================================================================================================
# 2. Score + rank (section 7) - explicit dimensions, no single unexplained composite mystery number
# =================================================================================================

def score_candidate(c: dict) -> dict:
    src_diversity = min(1.0, c["distinct_source_count"] / 6.0)
    frequency = min(1.0, c["window_event_count"] / 12.0)
    category_fit = _CATEGORY_PRIORITY.get(c["category"], 0.3)
    # visual/storytelling potential - a rough, disclosed heuristic: more distinct sources
    # discussing DIFFERENT angles (title token diversity) suggests more real slide material.
    distinct_title_words = len({w.lower() for i in c["items"] for w in i["title"].split() if len(w) > 4})
    storytelling_potential = min(1.0, distinct_title_words / 40.0)
    composite = round(0.30 * src_diversity + 0.25 * frequency + 0.25 * category_fit + 0.20 * storytelling_potential, 3)
    return {
        **c,
        "score_source_diversity": round(src_diversity, 3),
        "score_frequency": round(frequency, 3),
        "score_category_fit": round(category_fit, 3),
        "score_storytelling_potential": round(storytelling_potential, 3),
        "score_composite": composite,
    }


def rank_candidates(candidates: list[dict]) -> list[dict]:
    scored = [score_candidate(c) for c in candidates]
    scored.sort(key=lambda c: c["score_composite"], reverse=True)
    return scored


# =================================================================================================
# main
# =================================================================================================

def main() -> int:
    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    events = load_events()
    candidates = cluster_candidates(events)
    ranked = rank_candidates(candidates)

    with open(_ARTIFACTS / "candidate_ranking.json", "w", encoding="utf-8") as fh:
        json.dump(
            [{k: v for k, v in c.items() if k != "items"} for c in ranked[:20]],
            fh, ensure_ascii=False, indent=2,
        )

    top = ranked[0]
    print(f"observation window: {len(events)} events, {len(candidates)} story clusters")
    print(f"top candidate: {top['story_title']!r} (sources={top['distinct_source_count']}, events={top['window_event_count']}, score={top['score_composite']})")

    # Evidence gate (section 9): >=3 items AND >=2 sources preferred threshold.
    assert top["window_event_count"] >= 3 and top["distinct_source_count"] >= 2, "evidence gate failed"

    # -- SELECTED_TREND is the top-ranked candidate: "iPhone Duo?" (GADGETS). Full selection
    # reasoning, evidence, and the honestly-disclosed novelty caveat (this exact story was already
    # delivered to Telegram twice on 2026-09-10, per a direct read-only check of
    # story_telegram_deliveries - see the report's section F) live in
    # docs/instagram_autonomous_trend_to_carousel_canary_1_report.md, not re-derived here.

    hero_image = Image.open(_HERO_IMAGE_PATH)

    opportunity = ContentOpportunity(
        id=f"canary-trend-{top['story_id']}",
        source_type=OpportunitySourceType.NEWS,
        story_id=top["story_id"],
        # news_value: real, moderate (0.5) - this is well-corroborated FOLLOW-ON/analysis coverage
        # (competitor reaction, market data, feature comparisons), not a first-report breaking item
        # (the underlying announcement itself was already covered 2 days earlier - see the report's
        # disclosed novelty caveat). Honest characterization, not tuned to hit a particular branch.
        news_value=0.5,
        audience_relevance=0.7,
        product_mention_allowed=True,  # editorial commentary on real third-party products, not a sponsored placement
        allowed_claims=[], restricted_claims=[],
        evidence=[f"{i['source_name']}: {i['title']}" for i in top["items"][:8]],
    )

    objective_rec = recommend_objective(opportunity=opportunity, has_multi_step_narrative=True)
    format_decision = evaluate_format_shadow(
        objective=objective_rec.primary_objective, has_video_asset=False, has_multi_step_narrative=True,
    )
    assert format_decision.recommended_format is ContentFormat.CAROUSEL, format_decision

    shadow_plan = build_shadow_plan(
        opportunity=opportunity, campaign_name=None, objective_recommendation=objective_rec,
        format_decision=format_decision, audience_description="tech-enthusiast NINJA PULSE followers",
    )

    slides = [
        InstagramCarouselSlideCreative(
            role="hook", slide_copy="iPhone Duo объявлен — и весь рынок складных смартфонов реагирует",
            visual_direction="Крупный, привлекающий внимание кадр iPhone-семейства как визуальный якорь слайда.",
            source_evidence="Engadget, 9to5Mac, MacRumors — 12 сент. 2026",
        ),
        InstagramCarouselSlideCreative(
            role="context",
            slide_copy="После лет слухов Apple анонсировала складной iPhone Duo — на фоне уже привычных Samsung Galaxy Z и Google Pixel Fold",
            visual_direction="Текстовый слайд-контекст, тёмный фон, без фото.",
            source_evidence="9to5Mac Overtime 081; CNET — 12 сент. 2026",
        ),
        InstagramCarouselSlideCreative(
            role="data",
            slide_copy="Только на JD.com в Китае на iPhone Duo оформлено почти 1,55 млн предзаказов",
            visual_direction="Крупная цифра-акцент, без фото.",
            source_evidence="iXBT News — 12 сент. 2026 (со ссылкой на данные JD.com)",
        ),
        InstagramCarouselSlideCreative(
            role="comparison",
            slide_copy="iPhone Duo: защита IP68, соотношение экрана 1:1.4 vs Pixel Fold: экран шире, но не такой прочный",
            visual_direction="Двухпанельное сравнение, без фото.",
            source_evidence="CNET (durability face-off); 9to5Google (aspect ratio) — 12 сент. 2026",
        ),
        InstagramCarouselSlideCreative(
            role="explanation",
            slide_copy="iPhone Duo лишился части функций iPhone 18 Pro, зато обошёл iPad по удобству разделения экрана",
            visual_direction="Текстовый слайд с деталями, без фото.",
            source_evidence="MacRumors (missing features); 9to5Mac (split screen vs iPad) — 12 сент. 2026",
        ),
        InstagramCarouselSlideCreative(
            role="cta",
            slide_copy="Samsung уже усилила рекламу Galaxy Z, а Apple, по оценкам, займёт около четверти рынка складных телефонов",
            visual_direction="Закрывающий слайд, красный акцент, без фото.",
            source_evidence="3DNews (market-share estimate + Samsung ad response) — 12 сент. 2026",
        ),
    ]
    carousel = InstagramCarouselCreative(
        objective=objective_rec.primary_objective.value, slides=slides,
        final_cta="Что думаете о новом формате Apple?",
        evidence_used=[f"story_id={top['story_id']}"] + [i["url"] for i in top["items"][:8] if i.get("url")],
    )
    creative_outcome = CreativeGenerationOutcome(carousel=carousel)  # call=None - no live LLM invoked, see module docstring

    package = build_instagram_content_package(
        opportunity=opportunity, format_decision=format_decision, shadow_plan=shadow_plan,
        creative_outcome=creative_outcome, account_key="ninja_pulse_canary",
        source_image_ref="assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case1_hero_product_iphone.jpg",
    )

    render_results = render_instagram_carousel(package, hero_image=hero_image)
    for i, r in enumerate(render_results):
        r.image_bytes and (_ARTIFACTS / f"slide_{i:02d}_{slides[i].role}.jpg").write_bytes(r.image_bytes)

    art_result = validate_instagram_art(package, render_results)
    gate_outcome = evaluate_instagram_editorial_gate(package, art_result)
    review_package = build_instagram_review_package(package=package, render_results=render_results, art_result=art_result)

    publish_result = asyncio.run(
        publish_instagram_content(
            package, gate_outcome, client=ShadowInstagramPublishClient(), account_id="canary_account",
            shadow=True, editor_approved=False,
        )
    )

    # --- persist everything for the report / Founder review ---
    (_ARTIFACTS / "package.json").write_text(json.dumps(package.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (_ARTIFACTS / "art_result.json").write_text(json.dumps(art_result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (_ARTIFACTS / "gate_outcome.json").write_text(json.dumps(gate_outcome.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (_ARTIFACTS / "review_package.json").write_text(json.dumps(review_package.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (_ARTIFACTS / "publish_result.json").write_text(json.dumps(asdict(publish_result), ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    layout_variants = [r.evidence.notes.get("layout_variant") for r in render_results]
    print("layout_variants:", layout_variants)
    print("art passed:", art_result.passed, "blocking:", art_result.blocking_issues, "warnings:", art_result.warnings)
    print("gate decision:", gate_outcome.decision.value, gate_outcome.reason_codes)
    print("publish status:", publish_result.status.value, "shadow:", publish_result.shadow)

    _contact_sheet(len(slides))
    print(f"wrote {len(slides)} slide renders + 00_CONTACT_SHEET.jpg to {_ARTIFACTS}")
    return 0


def _contact_sheet(n_slides: int) -> None:
    roles = ["hook", "context", "data", "comparison", "explanation", "cta"]
    cols, cw, ch, pad, cap = 3, 420, 500, 22, 30
    W = cols * (cw + pad) + pad
    rows = (n_slides + cols - 1) // cols
    H = rows * (ch + cap + pad) + pad
    sheet = Image.new("RGB", (W, H), (16, 16, 18))
    d = ImageDraw.Draw(sheet)
    for i in range(n_slides):
        cx = pad + (i % cols) * (cw + pad)
        cy = pad + (i // cols) * (ch + cap + pad)
        p = _ARTIFACTS / f"slide_{i:02d}_{roles[i]}.jpg"
        if p.exists():
            with Image.open(p) as im:
                t = im.convert("RGB")
                t.thumbnail((cw, ch))
                sheet.paste(t, (cx, cy + cap))
        d.text((cx, cy + 6), f"{i + 1:02d} {roles[i]}", fill=(230, 230, 230))
    sheet.save(_ARTIFACTS / "00_CONTACT_SHEET.jpg", quality=90)


if __name__ == "__main__":
    raise SystemExit(main())
