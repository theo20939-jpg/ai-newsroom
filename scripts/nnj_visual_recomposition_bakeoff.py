"""NNJ Source-Faithful Editorial Visual Recomposition - Phase V2.1 provider bake-off harness
(docs/nnj_source_faithful_editorial_visual_recomposition_v1.md).

WHAT THIS IS: an isolated, standalone script that PREPARES (and, only when explicitly given
`--live`, EXECUTES) a 3-source-image x 3-model = 9-run comparison of three real, provider-neutral
image-editing models, so a human can pick a production provider with real evidence instead of a
guess. It is NOT wired into `worker/content_cycle.py`, `services/presentation_director.py`,
`services/brand_renderer.py`, Telegram, or EVENT_RECAP - nothing in this repository's production
path imports this file, and this file imports nothing from `worker/` or `services/notifiers*`.

DEFAULT IS DRY RUN. `--live` is required to make any real, paid provider call - and even then,
`--max-successful-generations` (default 9, i.e. the whole planned matrix) and the optional
`--max-cost-usd` are both hard stops. Every dry run performs ZERO network calls and reports
`network_image_generation_calls: 0`, `successful_paid_generations: 0`, `actual_cost_usd: 0` in its
manifest - a machine-checkable proof, not just a docstring claim.

BAKE-OFF CANDIDATES (authoritative, per the governing Phase V2.1 instruction - never a fourth
provider, never FLUX/Stability/Black Forest Labs):
  1. Google gemini-3.1-flash-image  (via GeminiImageAdapter)
  2. Google gemini-3-pro-image      (via GeminiImageAdapter, same adapter class, different model_id)
  3. OpenAI gpt-image-2             (via OpenAIImageAdapter)

CANONICAL PROMPT: `build_recomposition_prompt()` below returns ONE fixed string, sent byte-for-byte
identical to all 3 models across all 9 runs - "do not tune per-model" (Stage 8). It is a plain,
versionless Python function mirroring this repo's own established
`services/meme_image_generation.py::build_image_prompt()` shape (per docs/
nnj_source_faithful_editorial_visual_recomposition_v1.md §12's own instruction for exactly this
future step), literally transcribing that document's §12 prompt contract - not a new prompt
invented for this script.

NO LLM IMAGE JUDGE: per Stage 15's explicit instruction, this harness performs only mechanical,
non-AI checks on any real output (`_run_basic_automated_checks()` - decodability, MIME/dimension
sanity, byte-identity-to-source detection). The 0-5 rubric scores (`EvaluationRubric`) and the
`FidelityFailureFlag` are filled in by a HUMAN reviewer after a live run, never by a model - an
LLM judge would contaminate the exact three-model comparison this bake-off exists to produce.

COST ESTIMATES are exactly that - estimates, clearly labeled, sourced from each provider adapter's
own module docstring (which cites official/third-party pricing pages, dated 2026-08-27). Never
treated as a real invoice; `actual_cost_usd` is only ever populated from a real response's own
reported usage after a genuine `--live` call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from core.config import settings
from integrations.llm_gateway.image_protocol import (
    ImageGenerationOperation,
    ImageGenerationRequest,
    ReferenceImage,
)
from integrations.llm_gateway.providers.gemini_image_adapter import (
    GEMINI_3_1_FLASH_IMAGE,
    GEMINI_3_PRO_IMAGE,
    GeminiImageAdapter,
    GeminiImageAdapterError,
)
from integrations.llm_gateway.providers.openai_image_adapter import (
    GPT_IMAGE_2,
    OpenAIImageAdapter,
    OpenAIImageAdapterError,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SOURCES_DIR = _REPO_ROOT / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources"
_DRY_RUN_OUTPUT_DIR = _REPO_ROOT / "assets" / "brand" / "newsroom_visuals" / "v2_provider_bakeoff_dry_run"

# The exact 3x3 matrix - AUTHORITATIVE, no fourth provider/model, no fourth case.
BAKE_OFF_MODELS: tuple[tuple[str, str], ...] = (
    ("gemini", GEMINI_3_1_FLASH_IMAGE),
    ("gemini", GEMINI_3_PRO_IMAGE),
    ("openai", GPT_IMAGE_2),
)

BAKE_OFF_CASES: tuple[tuple[str, str], ...] = (
    ("case1_hero_product_iphone", "Hero product/iPhone - hardware fidelity"),
    ("case2_gadget_geometry_detail", "Second physical gadget - geometry/detail preservation"),
    ("case3_bright_promotional_scene", "Bright/saturated promotional image"),
)

# Estimates only - see each adapter's module docstring for the dated source of these numbers.
# NEVER used for anything except a disclosed, labeled ceiling estimate in the manifest.
_ESTIMATED_COST_PER_IMAGE_USD: dict[str, float] = {
    GEMINI_3_1_FLASH_IMAGE: 0.067,
    GEMINI_3_PRO_IMAGE: 0.134,
    GPT_IMAGE_2: 0.05,  # upper end of the third-party $0.03-0.05 estimate range - a ceiling, not a midpoint
}


class FidelityFailureFlag(str, Enum):
    """Separate from the 0-5 numeric rubric score (Stage 14) - a fidelity failure is a distinct,
    binary-ish signal a low numeric score alone could bury."""

    NONE = "none"
    MINOR_VISUAL_MUTATION = "minor_visual_mutation"
    MAJOR_VISUAL_MUTATION = "major_visual_mutation"
    CRITICAL_PRODUCT_MUTATION = "critical_product_mutation"


class EditStrength(str, Enum):
    """A human-observed classification of how much the model changed vs. the source - distinct
    from the rubric's "Composition Improvement" score, which judges whether the change was good."""

    MINIMAL = "minimal"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass
class EvaluationRubric:
    """All fields None until a HUMAN reviewer fills them in after a real --live run (Stage 13/15 -
    no LLM image judge). 0-5 scale, matching the governing instruction exactly."""

    factual_product_fidelity: int | None = None
    composition_improvement: int | None = None
    nnj_safe_zone_quality: int | None = None
    photorealism_artifacts: int | None = None
    prompt_adherence: int | None = None
    edit_strength: EditStrength | None = None
    fidelity_failure_flag: FidelityFailureFlag = FidelityFailureFlag.NONE
    reviewer_notes: str | None = None


@dataclass
class BasicAutomatedChecks:
    """Mechanical, non-AI checks only (Stage 15) - populated automatically for any real --live
    output, never a substitute for the human EvaluationRubric above."""

    decodable: bool
    mime_type: str
    width: int | None
    height: int | None
    output_sha256: str
    byte_identical_to_source: bool  # a decisive red flag if True - the model returned the input untouched


@dataclass
class BakeOffCase:
    case_id: str
    label: str
    file_path: str
    sha256: str
    width: int
    height: int
    mime_type: str
    size_bytes: int


@dataclass
class PlannedRun:
    run_id: str
    case_id: str
    provider: str
    model_id: str
    planned: bool = True
    executed: bool = False
    estimated_cost_usd: float | None = None
    # Populated only after a real --live execution:
    request_id: str | None = None
    actual_cost_usd: float | None = None
    output_path: str | None = None
    error: str | None = None
    automated_checks: dict | None = None
    evaluation: dict | None = None  # EvaluationRubric.__dict__, left for a human to fill in


def build_recomposition_prompt() -> str:
    """Pure, deterministic, versionless - mirrors `services/meme_image_generation.py::
    build_image_prompt()`'s own shape. Byte-identical to `services/editorial_recomposition.py::
    build_recomposition_prompt()` - see that copy's own docstring for the Phase V2.7 §6-7
    forensic finding + fix this text embodies (source-preserving editing, not illustration -
    tightened after the V2.6 canary's own observed "looks synthetic / concept-render-like"
    failure). Identical text for every one of the 9 planned runs - Stage 8's own "one canonical
    provider-neutral prompt... do not tune per-model" requirement."""
    return (
        "ROLE: You are the NNJ Source-Preserving Editorial Photo Editor.\n\n"
        "MISSION: The supplied source image is real, factual photography. Your task is "
        "source-preserving editing, not illustration or reinterpretation. Treat the photographed "
        "factual foreground subject as immutable reference content wherever technically "
        "possible. Preserving factual fidelity has absolute priority over composition.\n\n"
        "SOURCE FIDELITY: Treat the source image as the source of truth for people, devices, "
        "product appearance, event scenes, logos present in evidence, interfaces/screens, "
        "materials, colors, and the physical relationships between objects.\n\n"
        "SOURCE BRANDING PRESERVATION: If a publisher, outlet, or source credit mark - a "
        "watermark, logo, or credit line - is visible anywhere in the source image, it must "
        "remain present, in its original form, unchanged. Do not erase it, replace it, redraw "
        "it, translate it, or clean it up, even if reframing or background extension would "
        "otherwise make removing it convenient. This applies only to real, visible source/"
        "editorial branding - it does not forbid ordinary in-frame product screens or interface "
        "text, which SOURCE FIDELITY above already covers.\n\n"
        "ALLOWED: extend the existing background; clean minor clutter from the existing "
        "background; a modest whole-subject translation; a modest whole-subject uniform scale; "
        "a modest framing change; create negative space around the subject; global photographic "
        "color/exposure harmonization that does not change the factual appearance of the "
        "subject; reserve a calm lower branding zone.\n\n"
        "FORBIDDEN: rebuilding the product from scratch; redesigning the product; replacing the "
        "product with a visually similar object; changing product geometry; changing "
        "camera/sensor/button/port geometry; changing logos or labels; erasing, deleting, or "
        "redrawing a visible source/publisher watermark or credit mark; changing human identity; "
        "fabricating UI; hallucinating text; deleting real secondary physical objects merely for "
        "composition; changing hand anatomy; changing grip; inventing fingers; materially "
        "changing materials or colors; fully replacing the real background with an unrelated "
        "generic studio backdrop; restyling the photograph as a render, illustration, or concept "
        "image; changing the real light source direction or character beyond subtle, "
        "source-consistent harmonization; adding missing features; creating unsupported event "
        "details; creating fictional scenes that misrepresent the story.\n\n"
        "UNCERTAINTY RULE: If preserving the factual foreground subject while satisfying the "
        "requested composition is uncertain, preserve the source subject and make a weaker "
        "edit. Never sacrifice factual fidelity for a cleaner composition.\n\n"
        "BOTTOM SAFE ZONE: Leave a calm lower area free of crucial detail for deterministic NNJ "
        "branding applied downstream.\n\n"
        "TEXT RULE: Do not generate headlines, article text, fake interface text, exact "
        "statistics, or quote text.\n\n"
        "NNJ BRAND RULE: Do not generate NNJ branding, the NNJ logo, or the pulse line - all NNJ "
        "branding is deterministic and applied downstream, unchanged.\n\n"
        "FAIL-SAFE: If truthful recomposition is not possible, fall back conceptually to a "
        "cleaner crop-based treatment of the source image rather than fabricating details.\n\n"
        "OUTPUT: Only the recomposed visual. No explanations, no extra text, no branding."
    )


def load_bake_off_cases() -> list[BakeOffCase]:
    """Reads the 3 already-selected, already-committed source images and their recorded
    provenance (assets/brand/newsroom_visuals/v2_1_bakeoff_sources/provenance.json) - never
    re-selects or re-derives them; this function only verifies the files on disk still match."""
    from PIL import Image

    provenance_path = _SOURCES_DIR / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    cases: list[BakeOffCase] = []
    for entry in provenance["cases"]:
        file_path = _SOURCES_DIR / entry["file"]
        raw = file_path.read_bytes()
        actual_sha256 = hashlib.sha256(raw).hexdigest()
        if actual_sha256 != entry["sha256"]:
            raise ValueError(
                f"Bake-off source {entry['file']!r} sha256 mismatch - recorded {entry['sha256']!r}, "
                f"actual {actual_sha256!r}. Provenance is stale or the file was modified."
            )
        with Image.open(file_path) as im:
            width, height = im.size
        cases.append(
            BakeOffCase(
                case_id=entry["case_id"],
                label=entry["rationale"].split(":")[0],
                file_path=str(file_path.relative_to(_REPO_ROOT)),
                sha256=actual_sha256,
                width=width,
                height=height,
                mime_type=entry["mime_type"],
                size_bytes=len(raw),
            )
        )
    return cases


def build_matrix(cases: list[BakeOffCase]) -> list[PlannedRun]:
    """Prepares (never executes) the exact 3x3=9-run matrix (Stage 12)."""
    runs: list[PlannedRun] = []
    for case in cases:
        for provider, model_id in BAKE_OFF_MODELS:
            runs.append(
                PlannedRun(
                    run_id=f"{case.case_id}__{provider}__{model_id}",
                    case_id=case.case_id,
                    provider=provider,
                    model_id=model_id,
                    estimated_cost_usd=_ESTIMATED_COST_PER_IMAGE_USD.get(model_id),
                )
            )
    return runs


def credential_audit() -> dict[str, str]:
    """Presence-only report (Stage 6/7) - NEVER the raw secret value, only PRESENT/ABSENT."""
    return {
        "OPENAI_API_KEY": "PRESENT" if settings.openai_api_key is not None else "ABSENT",
        "GEMINI_API_KEY": "PRESENT" if settings.gemini_api_key is not None else "ABSENT",
    }


def estimate_max_cost_usd(runs: list[PlannedRun]) -> float:
    """Sum of each planned run's own per-model estimate (Stage 16) - an upper-bound ESTIMATE,
    not a quote from any provider's own billing system."""
    return round(sum(r.estimated_cost_usd or 0.0 for r in runs), 4)


def _run_basic_automated_checks(image_bytes: bytes, source_sha256: str, mime_type: str) -> BasicAutomatedChecks:
    """Mechanical checks only - see module docstring's "NO LLM IMAGE JUDGE" section."""
    from PIL import Image, UnidentifiedImageError
    import io

    output_sha256 = hashlib.sha256(image_bytes).hexdigest()
    width: int | None
    height: int | None
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            width, height = im.size
        decodable = True
    except UnidentifiedImageError:
        width = height = None
        decodable = False
    return BasicAutomatedChecks(
        decodable=decodable,
        mime_type=mime_type,
        width=width,
        height=height,
        output_sha256=output_sha256,
        byte_identical_to_source=(output_sha256 == source_sha256),
    )


async def _execute_live_run(run: PlannedRun, case: BakeOffCase, output_dir: Path) -> None:
    """Only reached when `--live` is passed - makes exactly one real, paid provider call. Never
    called anywhere in this session; this function exists so a FUTURE, separately-authorized run
    can use it, per Stage 10's "supports --live" requirement."""
    source_bytes = (_REPO_ROOT / case.file_path).read_bytes()
    request = ImageGenerationRequest(
        prompt=build_recomposition_prompt(),
        operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=source_bytes, mime_type=case.mime_type),),
        target_aspect_ratio="16:9",
    )

    adapter: GeminiImageAdapter | OpenAIImageAdapter
    if run.provider == "gemini":
        gemini_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        if not gemini_key:
            run.error = "GEMINI_API_KEY is ABSENT - cannot execute a live Gemini run"
            return
        adapter = GeminiImageAdapter(model_id=run.model_id, api_key=gemini_key)
    else:
        openai_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        if not openai_key:
            run.error = "OPENAI_API_KEY is ABSENT - cannot execute a live OpenAI run"
            return
        adapter = OpenAIImageAdapter(api_key=openai_key)

    try:
        response = await adapter.generate_image(request)
    except (GeminiImageAdapterError, OpenAIImageAdapterError) as exc:
        run.error = f"{type(exc).__name__}: {exc}"
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    ext = "png" if response.mime_type == "image/png" else "jpg"
    output_path = output_dir / f"{run.run_id}.{ext}"
    output_path.write_bytes(response.image_bytes)

    checks = _run_basic_automated_checks(response.image_bytes, case.sha256, response.mime_type)
    run.executed = True
    run.request_id = response.request_id
    run.actual_cost_usd = float(response.cost_usd) if response.cost_usd is not None else None
    run.output_path = str(output_path.relative_to(_REPO_ROOT))
    run.automated_checks = asdict(checks)
    run.evaluation = asdict(EvaluationRubric())  # left for a human reviewer to fill in


def _build_manifest(
    runs: list[PlannedRun], cases: list[BakeOffCase], *, live: bool, max_successful_generations: int, max_cost_usd: float | None,
) -> dict:
    successful = [r for r in runs if r.executed and r.error is None]
    return {
        "phase": "V2.1 - Provider-Neutral Image Edit Protocol & Three-Model Bake-Off Preparation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if live else "dry_run",
        "bake_off_models": [{"provider": p, "model_id": m} for p, m in BAKE_OFF_MODELS],
        "credential_audit": credential_audit(),
        "cases": [asdict(c) for c in cases],
        "planned_runs": len(runs),
        "max_successful_generations": max_successful_generations,
        "max_cost_usd_budget": max_cost_usd,
        "network_image_generation_calls": len(successful) + len([r for r in runs if r.executed and r.error is not None]),
        "successful_paid_generations": len(successful),
        "actual_cost_usd": round(sum(r.actual_cost_usd or 0.0 for r in successful), 4),
        "estimated_max_cost_usd": estimate_max_cost_usd(runs),
        "canonical_prompt": build_recomposition_prompt(),
        "runs": [asdict(r) for r in runs],
    }


async def _run(args: argparse.Namespace) -> dict:
    cases = load_bake_off_cases()
    runs = build_matrix(cases)
    output_dir = Path(args.output_dir) if args.output_dir else _DRY_RUN_OUTPUT_DIR

    if args.live:
        cases_by_id = {c.case_id: c for c in cases}
        successful_count = 0
        running_cost = 0.0
        for run in runs:
            if successful_count >= args.max_successful_generations:
                run.error = "Skipped - --max-successful-generations reached"
                continue
            if args.max_cost_usd is not None and running_cost >= args.max_cost_usd:
                run.error = "Skipped - --max-cost-usd budget reached"
                continue
            await _execute_live_run(run, cases_by_id[run.case_id], output_dir)
            if run.executed and run.error is None:
                successful_count += 1
                running_cost += run.actual_cost_usd or 0.0

    manifest = _build_manifest(
        runs, cases, live=args.live, max_successful_generations=args.max_successful_generations, max_cost_usd=args.max_cost_usd,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--live", action="store_true", default=False,
        help="Make REAL, PAID provider calls. Default is dry run (zero network calls, zero cost). "
        "Requires explicit, separate user authorization outside this script - see module docstring.",
    )
    parser.add_argument("--output-dir", default=None, help="Where to write the manifest/outputs (default: assets/brand/newsroom_visuals/v2_provider_bakeoff_dry_run/)")
    parser.add_argument("--max-successful-generations", type=int, default=9, help="Hard cap on successful paid generations (default: 9, the full planned matrix)")
    parser.add_argument("--max-cost-usd", type=float, default=None, help="Optional hard cost budget cap in USD")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import asyncio

    args = _parse_args(argv if argv is not None else sys.argv[1:])
    manifest = asyncio.run(_run(args))
    print(json.dumps({k: manifest[k] for k in (
        "mode", "planned_runs", "network_image_generation_calls", "successful_paid_generations",
        "actual_cost_usd", "estimated_max_cost_usd",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
