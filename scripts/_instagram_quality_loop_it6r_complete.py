"""Loop iteration 6r COMPLETION (founder-authorized 2026-09-23). The real iteration-6r run stopped when the OpenAI account ran out of
credit (429 insufficient_quota): AI_HACK and NEWS_INSIGHT finished, NEWS_RECAP and TREND_GENERATIVE got real Creative Director plans but no
images. This script finishes ONLY that missing media, through the unchanged trigger -> media -> render path at the current HEAD:

- no Creative Director call: every archetype's persisted real plan is replayed byte-for-byte (replay gateway; nothing else reaches a model);
- no vision call: the persisted source-suitability verdicts are re-applied (the vision checker is made to raise if touched);
- AI_HACK / NEWS_INSIGHT: their already-paid images are re-attached from disk, only after the prompt compiled now equals the persisted one;
- NEWS_RECAP / TREND_GENERATIVE: one live gpt-image-2 call per generated slide, only for a prompt fixed by the zero-cost dry-run pass that
  runs first in the same process. Retries 0. Hard new-spend cap B51_COMPLETE_CAP_USD (default 0.60) as the diagnostic ledger's budget.

Inputs are pinned, never re-selected: the recap bundle is rebuilt from the persisted evidence handles plus the stored image each story had
(read-only lookup 2026-09-23: rank-1 editorial candidate of the event with that exact title); the rebuilt deterministic media note must equal
the note the real run passed to the model, byte for byte, or nothing is generated.

Replacement attempt r1 (founder-approved after the first launch SAFE STOPPED on a deleted story_5 binary): a pinned recap binary may be
absent ONLY when no slide consumes it, the preserved note had it available-but-unsuitable, and the image prompt builder reads text only
(missing_source_block_reason). It is never substituted; only its preserved note line and available/unsuitable status are restored, and
the whole note must still equal the preserved one. Any other missing binary still stops the run.

Usage: python scripts/_instagram_quality_loop_it6r_complete.py <preserved it6r dir> <out dir> preflight|live
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

from PIL import Image
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts._instagram_phase_b51_acceptance as acc  # noqa: E402
import services.instagram_automatic_trigger as trigger  # noqa: E402
import services.instagram_creative_director as cd_module  # noqa: E402
import services.instagram_creative_media as media_mod  # noqa: E402
import services.instagram_source_suitability as suit_module  # noqa: E402
from core.config import settings  # noqa: E402
from integrations.llm_gateway.image_protocol import ImageGenerationOperation, ImageGenerationRequest  # noqa: E402
from integrations.llm_gateway.providers.openai_image_adapter import GPT_IMAGE_2, OpenAIImageAdapter  # noqa: E402
from integrations.prompts.file_repository import FilePromptRepository  # noqa: E402
from services.image_pricing import ImageExecutionProfile, ImagePricingCatalog  # noqa: E402
from services.instagram_recap_bundle import InstagramRecapBundle, RecapStory  # noqa: E402

REUSE = ("ai_hack", "news_insight")
COMPLETE = ("news_recap", "trend_generative")
ORDER = (*REUSE, *COMPLETE)
NAMESPACE = os.environ.get("B51_DIAG_NAMESPACE", "instagram_quality_loop_it6r_complete")
CAP = Decimal(os.environ.get("B51_COMPLETE_CAP_USD", "0.60"))
CUMULATIVE_BEFORE = Decimal("3.1119")
CUMULATIVE_CEILING = Decimal("5.00")
STORE_ROOT = Path(os.environ.get("B51_STORE_ROOT", "/data/image_storage"))

# story key -> (event id, editorial candidate id, storage key). Read-only production lookup, 2026-09-23: exactly one event carries each
# story's title, and its rank-1 non-expired candidate is what build_instagram_recap_bundle._story_media returned.
PINNED = {
    "story_1": ("6e5908e7-d7f1-4b50-bf6b-7fbf03b107f0", "ac1a92e8df2ab7dbf527e9f82866581446301f2621f81e3270e35d59d1b77fbf",
                "images/22/22f125ebedcd0a5d806b1aaec67429141fff9f20ada044d52cf24b9e0109c85c.jpg"),
    "story_2": ("f66c568a-3d4a-49b1-9152-f9acecf6449a", "c7eab8d639b584cfbc72b00bf0330138e86152b70db3a75737498de0d276b16f",
                "images/d2/d2fb55dc06f679a10937b51bbf2a08e3360cdccd0314d37a7b9a14116f7a66dd.jpg"),
    "story_3": ("002507ae-24c8-4ee8-bff8-93e6aa0b754e", "c4ca1ccb2812aa1cda18c1e2bc40bba8643ee548a84ea0d8dae0d18caa4def84",
                "images/26/263b87f469b51fe3ae090aa1a0899e309de9f19327f0121c86b8f1e2a631480f.jpg"),
    "story_4": ("36e17ed6-359e-4b1b-a180-cc04d1f20ad3", "b9239768f24ced2bc14c8a777beeee19c4add60000232af4cd489cfada4acc8c",
                "images/28/2840d4eea9709eb81ae98bb10af8dc0ff2ef8c2ddafa944fca9ad1d0c03018ad.jpg"),
    "story_5": ("0506783f-2053-4e89-be7b-cbaadfe5e8f3", "1108c9cbb0b8105ea91c4cc64aa9788a5d19ffbc6b2dee8139bff94dd52adc91",
                "images/8f/8f8eae3acf28f5851bd5b3b3875096a7613e550ad265e97ca48bb16558d9b3ae.png"),
    "story_6": ("54fc0ebb-8a67-4cb6-bd0c-5c172d9bbead", "190c3fcb6ab8a86f1646023ed7340963beb18ee9153ba2d1e1a3c1a202ab2aa3",
                "images/87/875a6e7f22d73619001c8cc3e68a70b5ef36546b4cbea0fbf3e8702c12af3486.jpg"),
}


class SafeStop(RuntimeError):
    pass


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


# The generated-image prompt is compiled from text only (plan, story summary, evidence lines, format, slide). A source image can never
# reach it; if the builder ever grows another input, the missing-file exception below is refused.
PROMPT_INPUTS = frozenset({"plan", "opportunity_summary", "evidence", "content_format", "slide"})


def note_segment(note: str, key: str) -> str | None:
    """The preserved note's block for one subject: its `subject key '<key>'` line plus any indented profile lines under it."""
    lines = note.split("\n")
    for i, line in enumerate(lines):
        if line.startswith(f"subject key '{key}':"):
            block = [line]
            for follow in lines[i + 1:]:
                if not follow.startswith("  "):
                    break
                block.append(follow)
            return "\n".join(block)
    return None


def missing_source_block_reason(key: str, plan_slides: list[dict], saved_note: str) -> str | None:
    """None only when a recap story's stored binary may be absent without changing anything the real run used: no slide consumes that
    story's image, the preserved note had it available-but-unsuitable (so the plan was made knowing it was evidence only), and the image
    prompt builder cannot read an image. Otherwise the reason it must SAFE STOP."""
    for i, slide in enumerate(plan_slides):
        layout = slide.get("layout") or {}
        refs = [r.get("content_ref") for r in layout.get("regions") or [] if r.get("kind") == "media"]
        if key in refs:
            return f"slide {i} has a media region consuming {key}"
        if slide.get("media_subject") == key and slide.get("media_source") == "source":
            return f"slide {i} plans {key}'s own source media"
        if not layout and slide.get("media_subject") == key:
            return f"slide {i} has no declarative layout, so its asset resolves from media_subject {key}"
    segment = note_segment(saved_note, key)
    if segment is None:
        return f"{key} is absent from the preserved media note"
    if "\n" in segment or "SOURCE_AVAILABLE: yes." not in segment or "SOURCE_SUITABLE_FOR_FINAL_VISUAL: NO" not in segment:
        return f"{key} was not preserved as available-but-unsuitable"
    extra = set(inspect.signature(media_mod.compile_instagram_generation_prompt).parameters) - PROMPT_INPUTS
    if extra:
        return f"the image prompt builder takes inputs beyond text: {sorted(extra)}"
    return None


def restore_preserved_note_lines(rebuilt: str, saved_note: str, missing: list[str]) -> str:
    """With a missing binary the note builder writes `<key>: SOURCE_AVAILABLE: no...`; put back that key's preserved line (and only that).
    The caller still requires the WHOLE note to equal the preserved one byte for byte."""
    lines = rebuilt.split("\n")
    for key in missing:
        hits = [i for i, line in enumerate(lines) if line.startswith(f"{key}: SOURCE_AVAILABLE: no.")]
        if len(hits) != 1:
            raise SafeStop(f"{key}: expected exactly one 'no image' note line to restore, found {len(hits)}")
        lines[hits[0]] = note_segment(saved_note, key) or ""
    return "\n".join(lines)


def _pinned_inputs(src: Path, *, allow_unused_missing: bool = True) -> tuple[InstagramRecapBundle, RecapStory, dict[str, dict]]:
    """allow_unused_missing=False is the first launch's behaviour: any missing pinned binary stops the run."""
    handles = _json(src / "news_recap" / "raw_creative_director_output.json")["evidence_handles"]
    plan_slides = _json(src / "news_recap" / "creative_director_output.json")["slides"]
    saved_note = _json(src / "news_recap" / "render_manifest.json")["media_note_passed_to_model"]
    groups: dict[str, list[str]] = {}
    for line in handles.values():
        groups.setdefault(re.match(r"\[(story_\d)\]", line).group(1), []).append(line)
    stories = []
    missing: dict[str, dict] = {}
    for key, lines in groups.items():
        event_id, candidate_id, storage_key = PINNED[key]
        path = STORE_ROOT / storage_key
        data = path.read_bytes() if path.exists() else None
        if data is None:
            if not allow_unused_missing:
                raise SafeStop(f"{key}: pinned source file {storage_key} is missing")
            reason = missing_source_block_reason(key, plan_slides, saved_note)
            if reason is not None:
                raise SafeStop(f"{key}: pinned source file {storage_key} is missing and {reason}")
            missing[key] = {"storage_key": storage_key, "event_id": event_id, "candidate_id": candidate_id, "title": lines[0],
                            "preserved_note_line": note_segment(saved_note, key), "slides_consuming_image": [],
                            "substituted_image": None}
        stories.append(RecapStory(key=key, story_id=event_id, event_id=event_id, title=re.sub(r"^\[story_\d\]\s*", "", lines[0]), evidence=lines,
                                  image_bytes=data, source_ref=candidate_id))
    bundle = InstagramRecapBundle(stories=tuple(stories))
    if bundle.evidence != list(handles.values()):
        raise SafeStop("rebuilt recap evidence differs from the persisted handle map")
    trend = next(s for s in stories if s.key == "story_4")  # acc._trend_inputs: first pool story with an image, >=2 facts and a Cyrillic title
    if trend.image_bytes is None:
        raise SafeStop("the trend story's own source image is missing")
    if list(trend.evidence) != list(_json(src / "trend_generative" / "raw_creative_director_output.json")["evidence_handles"].values()):
        raise SafeStop("trend evidence differs from the persisted handle map")
    return bundle, trend, missing


def _saved(src: Path, name: str) -> dict:
    manifest = _json(src / name / "render_manifest.json")
    prompts_path = src / name / "generation_prompts.json"
    return {
        "raw": _json(src / name / "raw_creative_director_output.json"),
        "media_note": manifest["media_note_passed_to_model"],
        "unsuitable": frozenset(v["subject_key"] for v in manifest.get("source_suitability_verdicts") or [] if v.get("suitable") is False),
        "verdicts": manifest.get("source_suitability_verdicts") or [],
        "prompts": _json(prompts_path) if prompts_path.exists() else {},
    }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _run_pass(src: Path, out: Path, *, live: bool, approved: dict[str, str] | None) -> dict:
    """One pass over all four archetypes. live=False: generation in dry_run (no provider call) - collects the exact prompts."""
    bundle, trend_story, missing = _pinned_inputs(src)
    saved = {name: _saved(src, name) for name in ORDER}
    state: dict = {"prompts": {}, "provider_calls": 0, "notes_checked": {}, "reused": {}, "missing_sources": missing}
    current: dict = {}
    real_note, real_subjects = trigger._carousel_media_note, trigger._carousel_media_subjects

    def note_with_preserved(**kw):
        note = real_note(**kw)
        return restore_preserved_note_lines(note, saved["news_recap"]["media_note"], list(missing)) if kw.get("recap_bundle") is not None and missing else note

    def subjects_with_preserved(**kw):
        # The real run listed every missing-binary story as available AND unsuitable (proven from its preserved note line).
        available, unsuitable = real_subjects(**kw)
        recap = kw.get("recap_bundle")
        if recap is None or not missing:
            return available, unsuitable
        order = [s.key for s in recap.stories]
        return (tuple(k for k in order if k in set(available) | set(missing)), tuple(k for k in order if k in set(unsuitable) | set(missing)))

    async def saved_vision(**_kw):
        return saved[current["name"]]["unsuitable"]

    async def no_vision(*_a, **_kw):
        raise SafeStop("a vision call was attempted - this completion pass reuses the persisted verdicts only")

    captured_holder: dict = {}
    real_call = cd_module._call_creative_director

    async def replay_call(gw, repo, *, prompt_name, director_input, prompt_version):
        name = current["name"]
        if director_input.media_note != saved[name]["media_note"]:
            raise SafeStop(f"{name}: rebuilt media note differs from the note the real run passed to the model")
        if list(director_input.allowed_evidence) != list(saved[name]["raw"]["evidence_handles"].values()):
            raise SafeStop(f"{name}: rebuilt evidence differs from the persisted evidence")
        state["notes_checked"][name] = True
        cap = captured_holder["c"]
        cap["director_input"] = director_input
        output, call = await real_call(gw, repo, prompt_name=prompt_name, director_input=director_input, prompt_version=prompt_version)
        cap["model_output"], cap["call"] = output, call
        return output, call

    real_generate = media_mod._execute_generated_asset

    async def generate(**kw):
        name, key = current["name"], kw["asset_key"]
        prompt = media_mod.compile_instagram_generation_prompt(plan=kw["plan"], opportunity_summary=kw["opportunity_summary"], evidence=kw["evidence"],
                                                              content_format=kw["content_format"], slide=kw["slide"])
        state["prompts"][f"{name}:{key}"] = prompt
        if name in REUSE:
            if prompt != saved[name]["prompts"].get(key):
                raise SafeStop(f"{name} slide {key}: prompt compiled now differs from the persisted prompt of the paid image")
            raw = (src / name / f"generated_slide_{int(key) + 1:02d}.png").read_bytes()
            image = media_mod._decode_publishable_image(raw)
            state["reused"][f"{name}:{key}"] = hashlib.sha256(raw).hexdigest()
            ref = f"generated:reused:{hashlib.sha256(raw).hexdigest()[:16]}"
            return media_mod.InstagramMediaExecutionAsset(
                asset_key=key, media_mode=media_mod.InstagramMediaMode.GENERATED, status="generated_media", image=image, asset_ref=ref,
                generated_asset_ref=ref, provider="openai", model=GPT_IMAGE_2, prompt=prompt, prompt_sha256=_sha(prompt), size="1024x1536",
                quality="medium", raw_image_bytes=raw, source_treatment="generated_base_art_reused_from_paid_iteration_6r",
                final_compositor_treatment="exact_russian_typography_canonical_logo_safe_zones")
        if live and approved.get(f"{name}:{key}") != _sha(prompt):
            raise SafeStop(f"{name} slide {key}: prompt not fixed by the dry-run preflight - refusing the paid call")
        return await real_generate(**kw)

    real_adapter_generate = OpenAIImageAdapter.generate_image

    async def counted_generate(self, request):
        if not live:
            raise SafeStop("provider image call attempted during the dry-run pass")
        if state["provider_calls"] >= len(approved):
            raise SafeStop("provider image call beyond the approved set")
        state["provider_calls"] += 1
        return await real_adapter_generate(self, request)

    diag = acc._diag_redis()
    from services.budget_guard import RedisBudgetGuard
    from services.budgeted_image_execution import BudgetedImageExecutor
    from integrations.storage.image_storage import LocalImageStorage as _Store

    diag_settings = settings.model_copy(update={"llm_budget_mode": "enforce", "llm_daily_budget_usd": float(CAP)})
    guard = RedisBudgetGuard(diag, diag_settings, ledger_namespace=NAMESPACE)
    store = out / "generated_store"
    store.mkdir(parents=True, exist_ok=True)
    patches = [
        (trigger, "_vision_unsuitable_subjects", saved_vision), (trigger, "_carousel_media_note", note_with_preserved),
        (trigger, "_carousel_media_subjects", subjects_with_preserved), (suit_module, "check_primary_suitability", no_vision), (suit_module, "_call_vision", no_vision),
        (cd_module, "_call_creative_director", replay_call), (media_mod, "_execute_generated_asset", generate),
        (media_mod, "build_budgeted_image_executor", lambda: BudgetedImageExecutor(budget_guard=guard)),
        (media_mod, "LocalImageStorage", lambda _root: _Store(str(store))), (OpenAIImageAdapter, "generate_image", counted_generate),
    ]
    originals = [(obj, attr, getattr(obj, attr)) for obj, attr, _ in patches]
    for obj, attr, value in patches:
        setattr(obj, attr, value)
    settings.instagram_image_generation_mode = "live" if live else "dry_run"  # in-process only
    if not live and settings.openai_api_key is None:
        settings.openai_api_key = SecretStr("dry-run-placeholder-never-sent")  # dry_run returns before any adapter call
    prompt_repo = FilePromptRepository(acc._PROMPTS)
    records = []
    engine = create_async_engine(f"postgresql+asyncpg://postgres:postgres@{os.environ.get('B5_SHADOW_DB_HOST', 'igpq_pg')}:5432/ai_newsroom_test")
    try:
        async with engine.connect() as connection:
            await connection.begin()
            async with AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False) as session:
                for name in ORDER:
                    current["name"] = name
                    captured: dict = {}
                    captured_holder["c"] = captured
                    replay = {"output": saved[name]["raw"]["structured_output"],
                              "sha256": hashlib.sha256((src / name / "raw_creative_director_output.json").read_bytes()).hexdigest()}
                    try:
                        rec = await acc._run_one(name, session, None, prompt_repo, None, out, bundle if name == "news_recap" else None, trend_story,
                                                 captured, True, replay)
                    except Exception as exc:  # noqa: BLE001 - record; never retry
                        rec = {"archetype": name, "VALIDATION": "FAIL", "status": "EXCEPTION", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
                    rec["MODEL_SOURCE"] = "REPLAY OF ITERATION-6R REAL PLAN (0 new Creative Director calls)"
                    rec["source_suitability_verdicts"] = saved[name]["verdicts"]
                    rec["vision_verdicts_reused_from_iteration_6r"] = True
                    rec["vision_calls"] = 0
                    records.append(rec)
            await connection.rollback()
        ledger = await diag.get(f"phase7:cost_ledger:{NAMESPACE}")
    finally:
        for obj, attr, value in originals:
            setattr(obj, attr, value)
        await engine.dispose()
        await diag.aclose()
    return {"records": records, "prompts": state["prompts"], "provider_calls": state["provider_calls"], "notes_checked": state["notes_checked"],
            "reused": state["reused"], "missing_sources": state["missing_sources"], "ledger": ledger}


def _worst_cases(prompts: dict[str, str]) -> dict:
    profile = ImageExecutionProfile(provider="openai", model=GPT_IMAGE_2, quality="medium", size="1024x1536", operation=ImageGenerationOperation.TEXT_TO_IMAGE)
    rows = {}
    for key, prompt in prompts.items():
        request = ImageGenerationRequest(prompt=prompt, operation=ImageGenerationOperation.TEXT_TO_IMAGE, preferred_provider="openai", preferred_model=GPT_IMAGE_2,
                                         target_aspect_ratio="2:3", target_width=1024, target_height=1536)
        quote = ImagePricingCatalog().quote(profile, request)
        # Every token has at least one UTF-8 byte, so output charge + (prompt bytes x input rate) bounds THIS prompt's cost; the catalog's
        # reservation instead assumes a 16,000-byte prompt for every call.
        rows[key] = {"prompt_bytes": len(prompt.encode("utf-8")), "prompt_sha256": _sha(prompt), "exact_prompt_worst_usd": str(quote.expected_cost_usd),
                     "catalog_reservation_usd": str(quote.worst_case_cost_usd)}
    return rows


def _raw_sheet(out: Path) -> None:
    from services.instagram_visual_profiles import ig_font
    from PIL import ImageDraw

    tiles = []
    for name in COMPLETE:
        for path in sorted((out / name).glob("generated_slide_*.png")):
            im = Image.open(path).convert("RGB")
            im.thumbnail((400, 600))
            tiles.append((f"{name} {path.stem.replace('generated_', '')} (RAW, before render)", im))
    if not tiles:
        return
    cols = 4
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 420 + 20, rows * 650 + 70), (16, 17, 21))
    d = ImageDraw.Draw(sheet)
    d.text((20, 18), "Iteration 6r completion - FRESH raw generated media (NEWS_RECAP + TREND_GENERATIVE)", font=ig_font(26, "black"), fill=(240, 241, 244))
    for i, (label, im) in enumerate(tiles):
        x, y = 20 + (i % cols) * 420, 70 + (i // cols) * 650
        sheet.paste(im, (x, y))
        d.text((x, y + im.height + 8), label, font=ig_font(15, "bold"), fill=(150, 155, 166))
    sheet.save(out / "raw_generated_sheet.png")


async def main() -> None:
    src, out, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    if mode not in ("preflight", "live"):
        raise SystemExit("mode must be preflight or live")
    out.mkdir(parents=True, exist_ok=True)
    dry = await _run_pass(src, out / "_dry_run", live=False, approved=None)
    wanted = {f"{name}:{i}" for name in COMPLETE for i, s in enumerate(_json(src / name / "creative_director_output.json")["slides"])
              if s.get("media_source") == "generated"}
    missing = {k: v for k, v in dry["prompts"].items() if k.split(":")[0] in COMPLETE}
    rows = _worst_cases(missing)
    exact_total = sum((Decimal(r["exact_prompt_worst_usd"]) for r in rows.values()), Decimal(0))
    catalog_total = sum((Decimal(r["catalog_reservation_usd"]) for r in rows.values()), Decimal(0))
    reuse_ok = all(r.get("VALIDATION") == "PASS" for r in dry["records"] if r["archetype"] in REUSE)
    preflight = {
        "missing_generated_slots": sorted(wanted), "prompts_compiled": sorted(missing), "slots_match": set(missing) == wanted,
        "media_notes_verified": dry["notes_checked"], "missing_source_exceptions": dry["missing_sources"], "reuse_archetypes_render_pass": reuse_ok, "reused_paid_images": dry["reused"],
        "per_call": rows, "exact_prompt_worst_total_usd": str(exact_total), "catalog_reservation_total_usd": str(catalog_total),
        "completion_cap_usd": str(CAP), "cumulative_before_usd": str(CUMULATIVE_BEFORE),
        "cumulative_worst_usd": str(CUMULATIVE_BEFORE + exact_total), "cumulative_worst_catalog_usd": str(CUMULATIVE_BEFORE + catalog_total),
        "dry_run_provider_calls": dry["provider_calls"], "dry_run_ledger": dry["ledger"],
    }
    preflight["safe"] = (preflight["slots_match"] and len(dry["notes_checked"]) == 4 and reuse_ok and dry["provider_calls"] == 0
                         and exact_total <= CAP and CUMULATIVE_BEFORE + catalog_total <= CUMULATIVE_CEILING)
    (out / "completion_preflight.json").write_text(json.dumps(preflight, indent=2, ensure_ascii=False), encoding="utf-8")
    print("PREFLIGHT", json.dumps({k: v for k, v in preflight.items() if k not in ("per_call", "reused_paid_images")}, ensure_ascii=False))
    if mode == "preflight":
        return
    if not preflight["safe"]:
        print("SAFE_STOP: preflight failed; no provider call was made")
        return
    if settings.openai_api_key is None or settings.openai_api_key.get_secret_value().startswith("dry-run"):
        print("SAFE_STOP: no provider credential in this process")
        return
    approved = {k: r["prompt_sha256"] for k, r in rows.items()}
    final = out / "final"
    live = await _run_pass(src, final, live=True, approved=approved)
    for rec in live["records"]:
        if rec["archetype"] in REUSE:
            rec["provider_image_calls"] = 0
            rec["image_generation_cost_usd"] = "0 (reused paid iteration-6r images)"
    _raw_sheet(final)
    cost = sum((Decimal(str(r.get("image_generation_cost_usd") or 0)) for r in live["records"] if r["archetype"] in COMPLETE), Decimal(0))
    summary = {"new_creative_director_calls": 0, "new_vision_calls": 0, "new_image_provider_calls": live["provider_calls"],
               "new_image_accounted_cost_usd": str(cost), "diagnostic_ledger_usd": live["ledger"], "completion_cap_usd": str(CAP),
               "cumulative_conservative_usd": str(CUMULATIVE_BEFORE + Decimal(str(live["ledger"] or 0))), "retries": 0,
               "runs": live["records"]}
    (final / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (final / "media_execution_manifest.json").write_text(json.dumps(
        {r["archetype"]: {"hook": r.get("hook_text"), "media_slides": r.get("media_slides")} for r in live["records"]},
        ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("DONE", json.dumps({k: v for k, v in summary.items() if k != "runs"}))
    for rec in live["records"]:
        print("ARCHETYPE", rec["archetype"], rec.get("VALIDATION"), rec.get("outcome_reason"), rec.get("generated_images_ok"), rec.get("error"))


if __name__ == "__main__":
    asyncio.run(main())
