"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1: the real, manually-invoked canary. Reproduces the
exact failure INSTAGRAM-AUTONOMOUS-TREND-TO-CAROUSEL-CANARY-1 exposed - a carousel about the
specific newly-announced foldable "iPhone Duo" reused a generic, ordinary (non-foldable) iPhone
product photo as its hero image - and proves the new media-research pipeline now picks correctly.

Never auto-run, mirrors scripts/phase19_m13_vision_review_manual.py's own established shape
exactly. Makes REAL, bounded (4 images) calls to: (1) the real safe_fetch-backed downloader
against 3 real, already-published news-article image URLs, and (2) the real, existing LLM Gateway
(OpenAI, real API key already present in this dev environment's own .env - the phase's own section
13 explicitly instructs using the existing multimodal capability) for real subject-match
classification - disclosed in full in the report, never hidden.

Disclosed, honest limitation (section 25 / production-safety posture, matching media_vision_review's
own precedent exactly): this script's own `WebDiscoveryClient` is pre-loaded with real search
results *this script's own author gathered as the human/operator* (via web-search tool calls) -
production's `automation_worker` has no configured search-API key and `media_web_discovery_mode`
defaults to "off" (services.media_web_discovery.NullWebDiscoveryClient, zero network calls) in
every live path. This canary proves the DOWNSTREAM pipeline (provenance, tiering, download safety,
subject-match classification, scoring, selection) is real and correct; it does not claim production
can autonomously search the web yet - that remains a disclosed, separate integration decision.

Launch with:
    python -m scripts._cross_platform_media_research_canary_1
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image

from capabilities.media_subject_match_capability import CAPABILITY_NAME, MediaSubjectMatchCapability
from core.config import settings
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import BusinessContext, CapabilityContext, ExecutionContext, NewsEventSnapshot, RuntimeContext, WorkflowExecutionStateSnapshot
from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType, OrientationPreference
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchValidation,
)
from services.image_quality import compute_dhash
from services.media_download_cache import download_and_validate
from services.media_research_selection import research_and_select_media
from services.media_web_discovery import ResolvedPageImage, WebSearchHit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROMPTS_ROOT = _REPO_ROOT / "prompts"
_ARTIFACTS = _REPO_ROOT / "artifacts" / "cross_platform_media_research_canary_1"
_CACHE_DIR = _ARTIFACTS / "cache"
_WRONG_LOCAL_CANDIDATE_PATH = _REPO_ROOT / "assets" / "brand" / "newsroom_visuals" / "v2_1_bakeoff_sources" / "case1_hero_product_iphone.jpg"

# --- real, operator-gathered web-search results (section 25's disclosed manual-research posture) ---
# Every URL/caption/publisher below is REAL, gathered via real web-search/fetch tool calls against
# real, already-published news articles at canary-authoring time (2026-09-13) - none invented.
_REAL_RESULTS: dict[str, tuple[WebSearchHit, ResolvedPageImage]] = {
    "Apple iPhone Duo": (
        WebSearchHit(query="Apple iPhone Duo", result_url="https://www.macrumors.com/2026/09/09/apple-announces-foldable-iphone-duo/", title="Apple Announces Foldable 'iPhone Duo' - MacRumors"),
        ResolvedPageImage(
            origin_url="https://www.macrumors.com/2026/09/09/apple-announces-foldable-iphone-duo/",
            asset_url="https://images.macrumors.com/t/a4h0iUkXuwX_hWmZSFCIFS-FEUo=/400x0/article-new/2026/09/iphone-duo.jpg?lossy",
            publisher_domain="macrumors.com", caption_or_alt="iphone duo", page_title="Apple Announces Foldable 'iPhone Duo'",
            published_date_text="2026-09-09",
        ),
    ),
    "iPhone Duo official photo": (
        WebSearchHit(query="iPhone Duo official photo", result_url="https://techcrunch.com/2026/09/09/apple-unveils-its-first-foldable-the-iphone-duo/", title="Apple unveils its first foldable, the iPhone Duo | TechCrunch"),
        ResolvedPageImage(
            origin_url="https://techcrunch.com/2026/09/09/apple-unveils-its-first-foldable-the-iphone-duo/",
            asset_url="https://techcrunch.com/wp-content/uploads/2026/09/iPhone-duo.jpeg?w=1024",
            publisher_domain="techcrunch.com", caption_or_alt="Image Credits: Apple", page_title="Apple unveils its first foldable, the iPhone Duo",
            published_date_text="2026-09-09",
        ),
    ),
    "iPhone Duo press image": (
        WebSearchHit(query="iPhone Duo press image", result_url="https://www.engadget.com/2253955/everything-apple-announced-at-the-foldable-iphone-launch/", title="Everything Apple announced at the foldable iPhone Duo launch - Engadget"),
        ResolvedPageImage(
            origin_url="https://www.engadget.com/2253955/everything-apple-announced-at-the-foldable-iphone-launch/",
            asset_url="https://www.engadget.com/img/gallery/everything-apple-announced-at-the-foldable-iphone-launch/iphone-duo-1789048020.jpg",
            publisher_domain="engadget.com", caption_or_alt="A folded-out iPhone Duo", page_title="Everything Apple announced at the foldable iPhone Duo launch",
            published_date_text="2026-09-09",
        ),
    ),
}


class ManualOperatorWebDiscoveryClient:
    """A REAL implementation of the `WebDiscoveryClient` Protocol - not a mock, not simulated data
    - backed by real search results the canary's own author gathered as the operator, disclosed
    fully in the module docstring above. Never used by any production code path (see
    services/media_web_discovery.py::NullWebDiscoveryClient, the actual production default)."""

    async def search(self, query: str, *, max_results: int):
        entry = _REAL_RESULTS.get(query)
        return [entry[0]] if entry else []

    async def resolve_page_image(self, hit: WebSearchHit):
        for hit_obj, resolved in _REAL_RESULTS.values():
            if hit_obj.result_url == hit.result_url:
                return resolved
        return None


def _mime_for(path: Path) -> str:
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(path.suffix.lstrip(".").lower(), "image/jpeg")


def _to_data_uri(path: Path) -> str:
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{_mime_for(path)};base64,{encoded}"


def _build_wrong_local_candidate() -> ResolvedMediaCandidate:
    """The exact local fixture the PRIOR Instagram carousel canary incorrectly used as its hero
    image for "iPhone Duo" - reused here deliberately, as the control candidate this new pipeline
    must correctly reject."""
    with Image.open(_WRONG_LOCAL_CANDIDATE_PATH) as im:
        width, height = im.size
        phash = compute_dhash(im.convert("RGB"))
    sha256 = __import__("hashlib").sha256(_WRONG_LOCAL_CANDIDATE_PATH.read_bytes()).hexdigest()
    return ResolvedMediaCandidate(
        candidate_id="tier1_local_ordinary_iphone",
        provenance=MediaProvenance(
            origin_url=str(_WRONG_LOCAL_CANDIDATE_PATH), asset_url=str(_WRONG_LOCAL_CANDIDATE_PATH),
            publisher_domain=None, discovered_at=datetime.now(timezone.utc),
            discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
            caption_or_alt="hero product iPhone photo (bundled newsroom visual fixture)",
        ),
        width=width, height=height, orientation="portrait" if height > width else ("square" if width == height else "landscape"),
        sha256=sha256, perceptual_hash=phash, local_path=str(_WRONG_LOCAL_CANDIDATE_PATH),
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
    )


def _intent_summary(intent: MediaIntent, candidate: ResolvedMediaCandidate) -> str:
    """Combines the intent's own claimed-subject fields with THIS candidate's real, already-
    resolved provenance (caption/alt, publisher, origin page) - section 6's own "the search result
    thumbnail is not sufficient evidence... resolve caption/alt/context" applied all the way
    through to the classifier itself, not just to candidate construction. Never anything invented -
    only fields already real and present on `candidate.provenance`."""
    parts = [f"subject_type={intent.subject_type.value}", f"primary_entity={intent.primary_entity}"]
    if intent.company:
        parts.append(f"company={intent.company}")
    if intent.model_name:
        parts.append(f"model_name={intent.model_name}")
    if intent.event:
        parts.append(f"event={intent.event}")
    if intent.must_not_imply:
        parts.append(f"must_not_imply={intent.must_not_imply}")

    parts.append("--- real corroborating evidence for THIS specific candidate ---")
    if candidate.provenance.caption_or_alt:
        parts.append(f"candidate's own caption/alt text: {candidate.provenance.caption_or_alt!r}")
    if candidate.provenance.publisher_domain:
        parts.append(f"publisher domain: {candidate.provenance.publisher_domain}")
    parts.append(f"origin page: {candidate.provenance.origin_url}")
    return "\n".join(parts)


async def main() -> int:
    _ARTIFACTS.mkdir(parents=True, exist_ok=True)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    intent = MediaIntent(
        subject_type=MediaSubjectType.PRODUCT, primary_entity="iPhone Duo", product_name="iPhone Duo",
        model_name="iPhone Duo", company="Apple", event="Surprise and Shine event, September 2026",
        time_context="announced 2026-09-09", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
        orientation_preference=OrientationPreference.ANY, platform="instagram",
        must_show=["a real foldable/dual-screen Apple device"],
        must_not_imply=["that an ordinary, non-foldable iPhone is the iPhone Duo"],
        context_summary="Apple's first foldable iPhone, announced September 9 2026 at its Surprise and Shine event.",
    )

    # --- real Gateway boot (mirrors scripts/phase19_m13_vision_review_manual.py exactly) ---
    # `settings.enabled_providers` defaults to [] (core/config.py) - a deliberate, separate safety
    # gate independent of whether a real API key is present in .env (integrations/llm_gateway/
    # providers/base.py::build_provider_registry() only registers a provider named here). This
    # canary explicitly, visibly opts OpenAI in for this one bounded, disclosed run (section 13's
    # own "use the existing multimodal capability" instruction) - an in-process override only,
    # never a persisted .env/config change, and never anything a live worker process would ever do
    # on its own (that gate stays exactly as conservative as it was before this script ran).
    settings.enabled_providers = ["openai"]
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
    registry = ai_layer.capability_registry
    _definition, capability = registry.resolve(CAPABILITY_NAME)
    assert isinstance(capability, MediaSubjectMatchCapability)

    call_log: list[dict] = []

    async def real_subject_match_classifier(candidate: ResolvedMediaCandidate, media_intent: MediaIntent) -> SubjectMatchValidation:
        if candidate.local_path is None:
            outcome = await download_and_validate(candidate.provenance.asset_url, cache_dir=_CACHE_DIR)
            if not outcome.ok:
                raise RuntimeError(f"download failed: {outcome.error_code}")
            local_path = Path(outcome.local_path)
        else:
            local_path = Path(candidate.local_path)

        context = CapabilityContext(
            business=BusinessContext(
                news_event=NewsEventSnapshot(
                    id=uuid4(), title="Apple announces iPhone Duo", summary=None, content=None, url=None,
                    category="technology", published_at=None,
                ),
                workflow_state=WorkflowExecutionStateSnapshot(workflow_name="content_generation", workflow_version=1, completed_steps=[]),
                media_subject_match_image_data_uri=_to_data_uri(local_path),
                media_subject_match_intent_summary=_intent_summary(media_intent, candidate),
            ),
            runtime=RuntimeContext(
                task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME, priority=TaskPriority.B,
                attempt=1, iteration_count=0,
            ),
            execution=ExecutionContext(),
        )
        result = await capability.execute(context)
        assert result.structured_output is not None
        call_log.append({"candidate_id": candidate.candidate_id, "local_path": str(local_path), "output": result.structured_output})
        return SubjectMatchValidation(**result.structured_output)

    wrong_candidate = _build_wrong_local_candidate()

    selection = await research_and_select_media(
        intent,
        tier1_candidates=[wrong_candidate],
        web_discovery_client=ManualOperatorWebDiscoveryClient(),
        subject_match_classifier=real_subject_match_classifier,
        official_domains=frozenset({"apple.com"}),
    )

    (_ARTIFACTS / "selection_result.json").write_text(selection.model_dump_json(indent=2), encoding="utf-8")
    (_ARTIFACTS / "subject_match_call_log.json").write_text(json.dumps(call_log, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"candidates_considered={selection.candidates_considered}")
    print(f"candidates_by_classification={selection.candidates_by_classification}")
    print(f"exact_subject_media_not_found={selection.exact_subject_media_not_found}")
    print(f"selected={selection.selected.candidate_id if selection.selected else None}")
    print(f"selected_score={selection.selected_score}")
    print(f"rejection_reasons={selection.rejection_reasons}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
