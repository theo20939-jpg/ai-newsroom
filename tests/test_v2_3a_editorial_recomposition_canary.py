"""Phase V2.3A - tests for scripts/nnj_editorial_recomposition_canary.py and the runtime-
reachability proof behind it. No real network call anywhere in this file - LIVE-path tests inject
a fake `ImageGenerationGateway`-shaped double."""
from __future__ import annotations

import ast
import io

import pytest
from PIL import Image

from integrations.llm_gateway.image_protocol import ImageGenerationResponse
from schemas.capability import CapabilityUsage
from scripts.nnj_editorial_recomposition_canary import _parse_args, run_canary

_CONTENT_CYCLE_PATH = "worker/content_cycle.py"
_CANARY_PATH = "scripts/nnj_editorial_recomposition_canary.py"


def _jpeg(width: int = 1600, height: int = 900, path=None) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 120, 40)).save(buf, "JPEG")
    data = buf.getvalue()
    if path is not None:
        path.write_bytes(data)
    return data


class _FakeGateway:
    def __init__(self, response: ImageGenerationResponse | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list = []

    async def generate_image(self, request):
        self.calls.append(request)
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _valid_response(image_bytes: bytes | None = None) -> ImageGenerationResponse:
    return ImageGenerationResponse(
        image_bytes=image_bytes or _jpeg(),
        mime_type="image/jpeg",
        model_used="gemini-3.1-flash-image",
        provider="gemini",
        usage=CapabilityUsage(units=1, unit_type="image"),
        request_id="int-canary-1",
        cost_usd=None,
    )


# ---------------------------------------------------------------------------
# 1. Current runtime reachability: presentation_director_mode=off blocks recomposition
# ---------------------------------------------------------------------------


def test_content_cycle_recomposition_call_is_nested_inside_enforce_mode_only() -> None:
    """Structural proof (AST, no DB needed): the `maybe_recompose(` call in
    worker/content_cycle.py is lexically nested inside an `if` whose test compares
    `settings.presentation_director_mode` to the literal "enforce" - i.e. it is provably
    unreachable when presentation_director_mode == "off" (or "shadow"), regardless of
    editorial_recomposition_mode."""
    tree = ast.parse(open(_CONTENT_CYCLE_PATH, encoding="utf-8").read())

    def _is_presentation_mode_enforce_test(test: ast.expr) -> bool:
        if not isinstance(test, ast.Compare):
            return False
        left_src = ast.dump(test.left)
        return "presentation_director_mode" in left_src and any(
            isinstance(c, ast.Constant) and c.value == "enforce" for c in test.comparators
        )

    def _find_maybe_recompose_call(node: ast.AST) -> ast.Call | None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "maybe_recompose":
                return child
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "maybe_recompose":
                return child
        return None

    found_enforce_ancestor = False

    class _Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:  # noqa: N802 - ast.NodeVisitor's own naming convention
            nonlocal found_enforce_ancestor
            if _is_presentation_mode_enforce_test(node.test) and _find_maybe_recompose_call(node) is not None:
                found_enforce_ancestor = True
            self.generic_visit(node)

    _Visitor().visit(tree)
    assert found_enforce_ancestor, (
        "maybe_recompose( call site must be nested inside an "
        "`if settings.presentation_director_mode == \"enforce\":` block"
    )


def test_maybe_recompose_is_called_at_most_once_per_news_render_site() -> None:
    """Sanity check on call count via source text - guards against an accidental second call site
    being added outside the audited block."""
    text = open(_CONTENT_CYCLE_PATH, encoding="utf-8").read()
    assert text.count("await maybe_recompose(") == 1


# ---------------------------------------------------------------------------
# 2/3/4. Canary gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_default_zero_provider_calls(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.jpg"
    _jpeg(path=source)
    gateway = _FakeGateway(response=_valid_response())

    manifest = await run_canary(
        source_path=source, category="TECH", live=False, source_reviewed=False,
        output_dir=tmp_path / "out", gateway=gateway,
    )

    assert gateway.calls == []
    assert manifest["network_provider_calls_made"] == 0
    assert manifest["mode_used"] == "dry_run"
    assert manifest["gates"]["refusal_reason"] is None


@pytest.mark.asyncio
async def test_live_without_source_reviewed_refuses_zero_calls(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    _jpeg(path=source)
    gateway = _FakeGateway(response=_valid_response())

    manifest = await run_canary(
        source_path=source, category="TECH", live=True, source_reviewed=False,
        output_dir=tmp_path / "out", gateway=gateway,
    )

    assert gateway.calls == []
    assert manifest["network_provider_calls_made"] == 0
    assert manifest["mode_used"] == "dry_run"
    assert manifest["gates"]["live_requested"] is True
    assert manifest["gates"]["refusal_reason"] == "live_requires_source_reviewed_acknowledgement"


@pytest.mark.asyncio
async def test_source_reviewed_without_live_zero_calls(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    _jpeg(path=source)
    gateway = _FakeGateway(response=_valid_response())

    manifest = await run_canary(
        source_path=source, category="TECH", live=False, source_reviewed=True,
        output_dir=tmp_path / "out", gateway=gateway,
    )

    assert gateway.calls == []
    assert manifest["network_provider_calls_made"] == 0
    assert manifest["mode_used"] == "dry_run"


# ---------------------------------------------------------------------------
# 5. One explicit source only
# ---------------------------------------------------------------------------


def test_source_argument_is_required() -> None:
    with pytest.raises(SystemExit):
        _parse_args(["--category", "TECH"])


def test_no_batch_or_wildcard_flags_exist() -> None:
    args = _parse_args(["--source", "x.jpg", "--category", "TECH"])
    assert not hasattr(args, "sources")
    assert not hasattr(args, "batch")
    assert not hasattr(args, "limit")


# ---------------------------------------------------------------------------
# 6/7/8. Model/cap/no-fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_success_uses_gemini_flash_only_and_caps_at_one_generation(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    _jpeg(path=source)
    recomposed = _jpeg(1600, 900)
    gateway = _FakeGateway(response=_valid_response(recomposed))

    manifest = await run_canary(
        source_path=source, category="TECH", live=True, source_reviewed=True,
        output_dir=tmp_path / "out", gateway=gateway,
    )

    assert len(gateway.calls) == 1
    assert manifest["successful_generations"] == 1
    assert manifest["recomposition"]["model"] == "gemini-3.1-flash-image"
    assert manifest["recomposition"]["model"] != "gemini-3-pro-image"
    assert manifest["recomposition"]["model"] != "gpt-image-2"


def test_harness_never_imports_pro_or_gpt_adapters() -> None:
    tree = ast.parse(open(_CANARY_PATH, encoding="utf-8").read())
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "GEMINI_3_PRO_IMAGE" not in imported_names
    assert "OpenAIImageAdapter" not in imported_names
    assert "GPT_IMAGE_2" not in imported_names


# ---------------------------------------------------------------------------
# 9/10. Artifacts + raw output passed into render_branded_media
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_success_produces_all_four_artifacts_and_uses_recomposed_bytes(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    _jpeg(path=source)
    recomposed = _jpeg(1600, 900)
    gateway = _FakeGateway(response=_valid_response(recomposed))
    out_dir = tmp_path / "out"

    manifest = await run_canary(
        source_path=source, category="TECH", live=True, source_reviewed=True,
        output_dir=out_dir, gateway=gateway,
    )

    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "original.jpg").exists()
    assert manifest["artifacts"]["raw_recomposed"] is not None
    assert manifest["artifacts"]["branded_result"] is not None
    assert (out_dir / "branded_result.jpg").exists()
    assert manifest["recomposition"]["used_recomposed_image"] is True
    # The raw recomposed bytes written to disk must be exactly what the gateway returned - proof
    # the same bytes flow into render_branded_media() rather than the original being reused.
    raw_path = out_dir / next(p.name for p in out_dir.iterdir() if p.name.startswith("raw_recomposed"))
    assert raw_path.read_bytes() == recomposed


# ---------------------------------------------------------------------------
# 11. Provider failure fails safely, no Telegram
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_failure_still_produces_branded_result_from_original_bytes(tmp_path) -> None:
    from integrations.llm_gateway.providers.gemini_image_adapter import GeminiImageAdapterError

    source = tmp_path / "source.jpg"
    _jpeg(path=source)
    gateway = _FakeGateway(exc=GeminiImageAdapterError("boom"))
    out_dir = tmp_path / "out"

    manifest = await run_canary(
        source_path=source, category="TECH", live=True, source_reviewed=True,
        output_dir=out_dir, gateway=gateway,
    )

    assert manifest["recomposition"]["used_recomposed_image"] is False
    assert manifest["artifacts"]["raw_recomposed"] is None
    assert manifest["artifacts"]["branded_result"] is not None
    assert manifest["telegram_sends"] == 0
    # Retried exactly once (genuine provider failure), never more.
    assert manifest["retried"] is True
    assert manifest["attempts"] == 2
    assert len(gateway.calls) == 2


def test_harness_has_no_telegram_import_anywhere() -> None:
    tree = ast.parse(open(_CANARY_PATH, encoding="utf-8").read())
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any("telegram" in m.lower() or "aiogram" in m.lower() or "bot" in m.lower() for m in imported_modules)


# ---------------------------------------------------------------------------
# 12. No automation_worker interaction
# ---------------------------------------------------------------------------


def test_harness_never_imports_docker_or_subprocess() -> None:
    text = open(_CANARY_PATH, encoding="utf-8").read()
    assert "import subprocess" not in text
    assert "docker" not in text.lower()
