"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §10/§11: the real, live dry-run evidence artifact.
Never auto-run (mirrors this repo's own established `scripts/_*_canary_*.py` convention exactly).

The 8 candidates below are REAL, recent (2026-09-14) production NewsEvents/content_drafts and
their REAL, already-persisted `image_candidates` rows - pulled read-only via SSH+psql from
production (zero writes), the same established pattern this session's own prior Instagram canary
phases already used and documented. No fact, title, or candidate id below is invented.

Launch with:
    python -m scripts._instagram_readiness_dry_run_1
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from services.instagram_dry_run import DryRunCandidateInput, DryRunImageCandidateInput, run_dry_run_batch

_ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts" / "instagram_production_readiness_closure_1"

_CANDIDATES = [
    DryRunCandidateInput(
        news_event_id="6e2f759f-0297-4df9-9f7a-fb6b6372eb1c",
        title="В России упал SkyNet: тысячи пользователей интернет-провайдера остались без связи",
        category="GADGETS",
        image_candidates=[
            DryRunImageCandidateInput("5b9064d324347ec9d471d73e161c183aaa811dd6c9acacc8de12a5b89aa8f20d", 1200, 768),
            DryRunImageCandidateInput("4d82ed6932bd8b5ac67ad5354c181b4f8acdda6f65f02302fc34bd34912584b7", 1376, 768),
        ],
    ),
    DryRunCandidateInput(
        news_event_id="586fe82e-ab60-4b92-9d1b-02796e313492",
        title="Все EUV-сканеры ASML расписаны до конца 2027 года — компания начала строительство нового завода",
        category="GADGETS",
        image_candidates=[DryRunImageCandidateInput("11eca4ff796fb34796277c633e49ce2ebb206492e445c3005ae24a8abea506ab", 800, 550)],
    ),
    DryRunCandidateInput(
        news_event_id="9d43ae59-43b5-4201-999b-3b5a06032b96",
        title="Китай предупреждает, что искусственный интеллект станет новой ареной конкуренции между крупными державами.",
        category="AI",
        image_candidates=[DryRunImageCandidateInput("3d895a75b5fff646d6e19280c889abce01c4f844c512ecebaefc0ce13ba63bee", 300, 300)],
    ),
    DryRunCandidateInput(
        news_event_id="b161b8f9-aa6f-491f-ba09-96bbd3aa12b0",
        title="New StarCraft title to launch in 2030, will be an open-world FPS",
        category="STARTUPS",
        image_candidates=[
            DryRunImageCandidateInput("a78732de7e53fc938806e1d6a59913ffcac36d666d27e6ea77454cf25d76e8a5", 1200, 900),
            DryRunImageCandidateInput("ef65b02eb307a94b2c9838af760530d3bdc80d3e69ff03bc678d5d9e585b7a2c", 1600, 900),
            DryRunImageCandidateInput("2d4ac86375252226561381e04c3fff812e442a2eaca20a3f6c2f4545a76030a8", 1200, 1200),
        ],
    ),
    DryRunCandidateInput(
        news_event_id="e1893f7f-4e55-4b19-8404-c7317da94872",
        title="«Мы опережаем Китай». Трамп выступил против замедления разработки ИИ",
        category="AI",
        image_candidates=[],  # a real, honest "no candidate resolved" case - not padded
    ),
    DryRunCandidateInput(
        news_event_id="be00cffa-c4ba-4eeb-8ab2-51c369f8cd66",
        title="Maryland data center developers offer residents biggest-ever US community benefits package as big tech seeks to quell",
        category="HARDWARE",
        image_candidates=[],
    ),
    DryRunCandidateInput(
        news_event_id="a91a1559-69df-4b04-8d70-49233280205a",
        title="In its first statement on AI, China's Ministry of State Security warns AI poses risks to the nation's political and",
        category="TECH",
        image_candidates=[
            DryRunImageCandidateInput("b601448c55f4a7ac6299e72500b365bbb6640a47fa42d1562a9c602ab1c9395c", 700, 394),
            DryRunImageCandidateInput("f54b2c044bcbb501bfb374657178e28745d7a0679d3cf504c59c54b11c73fd88", 128, 128),
        ],
    ),
    DryRunCandidateInput(
        news_event_id="9cc9c2f3-ed69-4eaf-94c3-13fea7bdae58",
        title="They raced to build AI. Now they say it's going too fast.",
        category="AI",
        image_candidates=[DryRunImageCandidateInput("5ac9d6b8b83e5d58ada59602eb11591e02fddc4da5c2b53089fb74b91477278d", 300, 300)],
    ),
]


async def main() -> None:
    results = await run_dry_run_batch(_CANDIDATES)
    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    payload = [r.__dict__ for r in results]
    (_ARTIFACTS / "dry_run_sample_1.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in results:
        print(f"{r.news_event_id[:8]} | {r.classification:5s} | subject_match={r.deterministic_and_final_subject_match} | qa={r.qa_verdict} | shadow={r.shadow_publish_status}")


if __name__ == "__main__":
    asyncio.run(main())
