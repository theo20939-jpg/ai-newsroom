"""Zero-cost probe: does the production Phase A duplicate guard (`check_instagram_editorial_duplicate`) stop the 5-11 Aug 2026 gym
story from running twice as a daily post - Monday's vc.ru Russian copy, then Tuesday's BBC English copy?

The real guard function runs unchanged; only its history loader is replaced by the one item Monday's post would have left (the RU gym
story's production canonical Story id, the SAME angle text and intent the Director would give both copies - the most favourable case
for the guard). No database, no provider. The canonical Story ids are the ones production Story identity (the real
`story_memory.match_story()` replay) gave the two copies that week."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import services.instagram_editorial_delivery_state as state  # noqa: E402

RU_STORY = "889105c5-75fa-4c71-ac76-c4532a3df3c0"  # vc.ru, Mon 10 Aug: "Австралиец попросил ИИ-агента записать его в спортзал..."
EN_STORY = "9cc1b7fe-c25f-4c17-b0aa-c8ac260236dc"  # BBC Technology, Tue 11 Aug: "AI agent hacks gym to get its owner spot in pilates class"
ANGLE = "An AI agent asked to book a gym class hacked the club's booking system and bumped another member off the waitlist"
INTENT = "REACTION"


async def main() -> dict:
    now = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    monday = state.InstagramEditorialHistoryItem(
        delivery_id="mon-gym", source_story_id=RU_STORY, content_format="carousel", state="DELIVERED",
        created_at=datetime(2026, 8, 10, 12, tzinfo=timezone.utc), angle=ANGLE, angle_intent=INTENT,
    )

    async def history(session, *, now=None, limit=20):
        return [monday]

    original = state.load_recent_instagram_editorial_history
    state.load_recent_instagram_editorial_history = history
    try:
        same_story = await state.check_instagram_editorial_duplicate(None, source_story_id=RU_STORY, angle=ANGLE, angle_intent=INTENT, now=now)
        other_language = await state.check_instagram_editorial_duplicate(None, source_story_id=EN_STORY, angle=ANGLE, angle_intent=INTENT, now=now)
    finally:
        state.load_recent_instagram_editorial_history = original
    return {
        "control_same_canonical_story": {"blocked": same_story.blocked, "reason": same_story.reason},
        "gym_en_after_gym_ru": {"blocked": other_language.blocked, "reason": other_language.reason},
        "verdict": "VERIFIED" if other_language.blocked else "FAILED",
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=1))
