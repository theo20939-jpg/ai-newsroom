"""Phase 23.1N.1 Part M - offline corpus replay of the new image-relevance weights against every
real, previously-persisted image candidate set reasonably available this session. No paid calls,
no Telegram sends, no database writes - loads already-saved raw candidate JSON (each one a real,
serialized `ImageIntelligenceResult.candidates` list from an earlier live canary run) and
reconstructs real `ImageCandidate` Pydantic objects, then calls the real `rank_candidates()`
function twice per event: once with the OLD weights (QUALITY_MAX=15, METADATA_CONFIDENCE_MAX=10,
monkeypatched back in-process only) and once with the NEW weights (this phase's own code, as
currently committed to the working tree).
"""
import json

from schemas.image_candidate import ImageCandidate
from services import image_relevance
from services.image_relevance import rank_candidates

_SOURCES = [
    ("scripts/_phase23_1m_forensics_raw.json", {
        "flock_patterns": ("Специалист по безопасности разработал узоры, «невидимые» для камер с системами распознавания", "https://vc.ru/services/3071307-specialist-po-bezopasnosti-razrabotal-uzory-nevidimye-dlya-kamer-s-sistemami-raspoznavaniya?from=rss"),
        "venmo": ("Google Play now takes Venmo payments", "https://www.engadget.com/2232988/google-play-venmo/"),
        "intel": ("Intel announces a $15B common stock offering", "https://www.techmeme.com/260810/p20#a260810p20"),
    }, "copywriting", "image_intelligence"),
    ("scripts/_phase23_1n_image_forensics.json", {
        "gym_google_news": ("Частный ИИ-агент взломал систему бронирования австралийского спортзала - 3DNews", None),
        "gym_3dnews": ("Частный ИИ-агент взломал систему бронирования австралийского спортзала", None),
        "long_march_7a": ("Китайская ракета Long March 7A взорвалась в полёте через 80 секунд после старта", None),
        "anthropic_ipo": ("Sources: Anthropic is courting investors for what could be the biggest IPO ever", "https://www.techmeme.com/260811/p1#a260811p1"),
        "visa_mastercard": ("С онлайн-платежами с Visa и Mastercard будут проблемы", None),
    }, None, None),
]


def _rerank(candidates_raw: list[dict], *, title: str, url: str | None) -> list[ImageCandidate]:
    candidates = [ImageCandidate.model_validate(c) for c in candidates_raw]
    return rank_candidates(
        candidates, event_title=title, event_content=title, event_url=url,
        source_name=None, top_candidates=5,
    )


def _winner(ranked: list[ImageCandidate]) -> ImageCandidate | None:
    eligible = [c for c in ranked if c.relevance_validation and c.relevance_validation.eligible_for_editorial]
    if not eligible:
        return None
    return min(eligible, key=lambda c: c.relevance_validation.rank)


def main() -> None:
    results = {}
    old_no_image = new_no_image = 0
    unchanged = changed = 0
    image_to_no_image = no_image_to_image = 0

    for path, events, cw_key, img_key in _SOURCES:
        data = json.load(open(path, encoding="utf-8"))
        for label, (title, url) in events.items():
            if cw_key:
                candidates_raw = (data[label][cw_key] or {}).get(img_key, {}).get("candidates", [])
            else:
                img = data.get(label)
                candidates_raw = (img or {}).get("candidates", [])
            if not candidates_raw:
                results[label] = {"old_winner": None, "new_winner": None, "note": "no candidates"}
                old_no_image += 1
                new_no_image += 1
                unchanged += 1
                continue

            image_relevance.QUALITY_MAX = 15
            image_relevance.METADATA_CONFIDENCE_MAX = 10
            old_ranked = _rerank(candidates_raw, title=title, url=url)
            old_winner = _winner(old_ranked)

            image_relevance.QUALITY_MAX = 25
            image_relevance.METADATA_CONFIDENCE_MAX = 0
            new_ranked = _rerank(candidates_raw, title=title, url=url)
            new_winner = _winner(new_ranked)

            old_id = old_winner.candidate_id if old_winner else None
            new_id = new_winner.candidate_id if new_winner else None

            if old_id is None and new_id is None:
                old_no_image += 1
                new_no_image += 1
                unchanged += 1
            elif old_id is None and new_id is not None:
                no_image_to_image += 1
                changed += 1
                old_no_image += 1
            elif old_id is not None and new_id is None:
                new_no_image += 1
                image_to_no_image += 1
                changed += 1
            elif old_id == new_id:
                unchanged += 1
            else:
                changed += 1

            results[label] = {
                "old_winner": old_id, "old_winner_url": old_winner.remote_url if old_winner else None,
                "new_winner": new_id, "new_winner_url": new_winner.remote_url if new_winner else None,
                "old_score": old_winner.relevance_validation.relevance_score if old_winner else None,
                "new_score": new_winner.relevance_validation.relevance_score if new_winner else None,
            }

    print(f"total_stories_replayed: {len(results)}")
    print(f"old_image_selected_count: {len(results) - old_no_image}")
    print(f"new_image_selected_count: {len(results) - new_no_image}")
    print(f"unchanged_winner_count: {unchanged}")
    print(f"changed_winner_count: {changed}")
    print(f"image_to_no_image_count: {image_to_no_image}")
    print(f"no_image_to_image_count: {no_image_to_image}")
    print()
    for label, r in results.items():
        print(label, "->", json.dumps(r, ensure_ascii=False))

    with open("scripts/_phase23_1n1_corpus_replay_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print("WROTE scripts/_phase23_1n1_corpus_replay_results.json")


if __name__ == "__main__":
    main()
