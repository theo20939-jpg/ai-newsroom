"""One-shot, no-Telegram OpenAI image acceptance for the saved message-2865 lineage.

Requires a fresh isolated Redis database and an explicit confirmation flag. It makes at most one
paid image dispatch, never retries, never sends Telegram, and writes a self-contained manifest plus
the raw provider image and the final KAGE-branded image when successful.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from core.config import settings
from core.redis import get_redis_client
from services.brand_renderer import render_news_hero
from services.budget_guard import image_execution_key
from services.cost_tracker import global_ledger_key
from services.kage_telegram_canary_envelope import (
    CANARY_HARD_CAP_USD,
    TelegramCanaryEnvelope,
    telegram_canary_envelope,
)
from services.kage_visual_fallback import (
    GENERATION_MAX_DISPATCHES,
    GENERATION_MODEL,
    GENERATION_QUALITY,
    GENERATION_SIZE,
    build_generation_brief,
    generate_editorial_image,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "kage_lineage_msg2865.json"
USEFUL_BODY = (
    "Решение приняли после того, как её агенты неожиданным образом обращались "
    "к сайтам правительства США."
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dimensions(path: Path) -> list[int]:
    with Image.open(path) as image:
        return [image.width, image.height]


async def _run(output_dir: Path) -> dict[str, Any]:
    if GENERATION_MAX_DISPATCHES != 1:
        raise RuntimeError("acceptance requires exactly one configured visual dispatch")
    if output_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing acceptance artifacts: {output_dir}")
    output_dir.mkdir(parents=True)

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    title = fixture["copywriting"]["title"]
    brief = build_generation_brief(
        title=title,
        body=USEFUL_BODY,
        research=fixture["research"],
        intelligence=fixture["intelligence"],
        source_headline=fixture["source_headline"],
    )
    prompt = brief["prompt"]
    prompt_sha = _sha256(prompt.encode("utf-8"))
    execution_id = f"news-generated:{prompt_sha}"

    redis = get_redis_client()
    if await redis.dbsize() != 0:
        raise RuntimeError("acceptance Redis database is not fresh/empty")
    namespace = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ledger_key = global_ledger_key(namespace)
    ledger_before = await redis.get(ledger_key)

    envelope = TelegramCanaryEnvelope(hard_cap_usd=CANARY_HARD_CAP_USD)
    started = time.perf_counter()
    with telegram_canary_envelope(envelope):
        raw, reason = await generate_editorial_image(prompt)
    duration_seconds = time.perf_counter() - started

    accounting_key = image_execution_key(namespace, execution_id)
    accounting_record = await redis.hgetall(accounting_key)
    ledger_after = await redis.get(ledger_key)
    dispatch = (envelope.dispatch_records or [{}])[-1]
    real_call_count = int(accounting_record.get("status") in {"success", "failed", "cost_bound_exceeded"})

    manifest: dict[str, Any] = {
        "fixture": "telegram_message_2865",
        "telegram_send": False,
        "real_openai_call_count": real_call_count,
        "request": {
            "model": GENERATION_MODEL,
            "size": GENERATION_SIZE,
            "quality": GENERATION_QUALITY,
            "n": 1,
            "output_format": "jpeg",
            "output_compression": 90,
            "partial_images": "omitted_default_off",
            "sdk_retries": 0,
            "prompt": prompt,
            "prompt_utf8_bytes": len(prompt.encode("utf-8")),
            "prompt_sha256": prompt_sha,
        },
        "duration_seconds": round(duration_seconds, 3),
        "result_reason": reason,
        "provider_response_status": dispatch.get("provider_status_code"),
        "provider_request_id": dispatch.get("provider_request_id"),
        "usage": {
            "input_tokens": dispatch.get("actual_input_tokens"),
            "text_input_tokens": dispatch.get("actual_text_input_tokens"),
            "image_input_tokens": dispatch.get("actual_image_input_tokens"),
            "output_tokens": dispatch.get("actual_output_tokens"),
        },
        "actual_cost_usd": dispatch.get("actual_cost_usd"),
        "story_ledger_record": dispatch,
        "redis_accounting_key": accounting_key,
        "redis_accounting_record": accounting_record,
        "isolated_ledger_before_usd": ledger_before or "0",
        "isolated_ledger_after_usd": ledger_after or "0",
        "raw_image": None,
        "final_kage_image": None,
    }

    if raw is not None:
        raw_path = output_dir / "message_2865_openai_raw.jpg"
        raw_path.write_bytes(raw)
        final = render_news_hero(raw, category="AI", editorial_code="NP-2865", branding_strength="MINIMAL")
        final_path = output_dir / "message_2865_kage_final.jpg"
        final_path.write_bytes(final)
        manifest["raw_image"] = {
            "path": str(raw_path.resolve()), "bytes": len(raw),
            "dimensions": _dimensions(raw_path), "sha256": _sha256(raw),
        }
        manifest["final_kage_image"] = {
            "path": str(final_path.resolve()), "bytes": len(final),
            "dimensions": _dimensions(final_path), "sha256": _sha256(final),
        }

    manifest_path = output_dir / "acceptance_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    await redis.aclose()
    return {"manifest_path": str(manifest_path.resolve()), **manifest}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--confirm-one-paid-call", action="store_true")
    args = parser.parse_args()
    if not args.confirm_one_paid_call:
        raise SystemExit("refusing paid call without --confirm-one-paid-call")
    if settings.openai_api_key is None:
        raise SystemExit("OPENAI_API_KEY is absent")
    if settings.redis_unavailable_policy != "fail_closed":
        raise SystemExit("REDIS_UNAVAILABLE_POLICY must be fail_closed")
    print(json.dumps(asyncio.run(_run(args.output_dir)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
