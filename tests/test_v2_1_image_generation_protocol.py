"""Phase V2.1 (docs/nnj_source_faithful_editorial_visual_recomposition_v1.md) - the provider-
neutral IMAGE_EDIT extension to ImageGenerationRequest/Response. No network, no live provider
call anywhere in this file."""
from __future__ import annotations

import pytest

from integrations.llm_gateway.image_protocol import (
    MAX_REFERENCE_IMAGES,
    MAX_REFERENCE_IMAGE_BYTES,
    MAX_TOTAL_REFERENCE_BYTES,
    ImageGenerationOperation,
    ImageGenerationRequest,
    ReferenceImage,
)
from integrations.llm_gateway.providers.mock_image_adapter import MockImageAdapter

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 100  # not a real decodable PNG - only used where the
# adapter itself never decodes it (protocol-layer tests only)


# ---------------------------------------------------------------------------------------------
# Legacy compatibility
# ---------------------------------------------------------------------------------------------


def test_prompt_only_construction_still_valid() -> None:
    """The exact construction every pre-existing call site uses - must remain valid, unchanged."""
    request = ImageGenerationRequest(prompt="A CEO on stage.")
    assert request.operation == ImageGenerationOperation.TEXT_TO_IMAGE
    assert request.reference_images == ()


def test_prompt_only_request_has_no_size_field() -> None:
    """The previous size: Literal["1024x1024"] field was confirmed dead (never read, never
    passed) and removed - this is a structural guarantee, not a runtime behavior change."""
    request = ImageGenerationRequest(prompt="test")
    assert not hasattr(request, "size")


def test_target_dimension_hints_are_optional_and_default_to_none() -> None:
    request = ImageGenerationRequest(prompt="test")
    assert request.target_aspect_ratio is None
    assert request.target_width is None
    assert request.target_height is None


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------


def test_image_edit_without_references_fails() -> None:
    with pytest.raises(ValueError, match="IMAGE_EDIT"):
        ImageGenerationRequest(prompt="edit this", operation=ImageGenerationOperation.IMAGE_EDIT)


def test_image_edit_with_a_reference_image_is_valid() -> None:
    request = ImageGenerationRequest(
        prompt="edit this", operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=_PNG_BYTES, mime_type="image/png"),),
    )
    assert request.operation == ImageGenerationOperation.IMAGE_EDIT
    assert len(request.reference_images) == 1


def test_empty_reference_image_bytes_rejected() -> None:
    with pytest.raises(ValueError):
        ReferenceImage(data=b"", mime_type="image/png")


def test_unsupported_mime_type_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        ReferenceImage(data=_PNG_BYTES, mime_type="image/gif")


def test_oversized_single_reference_image_rejected() -> None:
    with pytest.raises(ValueError):
        ReferenceImage(data=b"x" * (MAX_REFERENCE_IMAGE_BYTES + 1), mime_type="image/png")


def test_too_many_reference_images_rejected() -> None:
    refs = tuple(ReferenceImage(data=_PNG_BYTES, mime_type="image/png") for _ in range(MAX_REFERENCE_IMAGES + 1))
    with pytest.raises(ValueError, match="MAX_REFERENCE_IMAGES"):
        ImageGenerationRequest(prompt="edit", operation=ImageGenerationOperation.IMAGE_EDIT, reference_images=refs)


def test_total_reference_payload_bound_enforced() -> None:
    big = b"x" * (MAX_REFERENCE_IMAGE_BYTES - 1)
    # 3 references just under the per-image cap can still exceed the total cap
    count = (MAX_TOTAL_REFERENCE_BYTES // len(big)) + 2
    refs = tuple(ReferenceImage(data=big, mime_type="image/png") for _ in range(min(count, MAX_REFERENCE_IMAGES)))
    if sum(len(r.data) for r in refs) <= MAX_TOTAL_REFERENCE_BYTES:
        pytest.skip("bound not exceedable within MAX_REFERENCE_IMAGES at this payload size")
    with pytest.raises(ValueError, match="MAX_TOTAL_REFERENCE_BYTES"):
        ImageGenerationRequest(prompt="edit", operation=ImageGenerationOperation.IMAGE_EDIT, reference_images=refs)


def test_text_to_image_with_zero_references_remains_valid() -> None:
    request = ImageGenerationRequest(prompt="a scene", operation=ImageGenerationOperation.TEXT_TO_IMAGE)
    assert request.reference_images == ()


# ---------------------------------------------------------------------------------------------
# Security: never log raw bytes/base64
# ---------------------------------------------------------------------------------------------


def test_reference_image_repr_never_contains_raw_bytes() -> None:
    ref = ReferenceImage(data=_PNG_BYTES, mime_type="image/png")
    rendered = repr(ref)
    assert _PNG_BYTES not in rendered.encode("latin-1", errors="ignore")
    assert "bytes" in rendered  # discloses the length, never the content


def test_request_repr_never_contains_raw_reference_bytes() -> None:
    request = ImageGenerationRequest(
        prompt="edit this", operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=_PNG_BYTES, mime_type="image/png"),),
    )
    rendered = repr(request)
    assert _PNG_BYTES not in rendered.encode("latin-1", errors="ignore")


# ---------------------------------------------------------------------------------------------
# MockImageAdapter must not pretend to support IMAGE_EDIT
# ---------------------------------------------------------------------------------------------


def test_mock_adapter_capabilities_declare_no_image_edit_support() -> None:
    assert MockImageAdapter.CAPABILITIES.supports_text_to_image is True
    assert MockImageAdapter.CAPABILITIES.supports_image_edit is False


@pytest.mark.asyncio
async def test_mock_adapter_raises_for_image_edit_never_silently_downgrades() -> None:
    request = ImageGenerationRequest(
        prompt="edit this", operation=ImageGenerationOperation.IMAGE_EDIT,
        reference_images=(ReferenceImage(data=_PNG_BYTES, mime_type="image/png"),),
    )
    with pytest.raises(NotImplementedError):
        await MockImageAdapter().generate_image(request)


@pytest.mark.asyncio
async def test_mock_adapter_still_works_for_text_to_image() -> None:
    """Confirms the IMAGE_EDIT guard didn't break the existing, still-supported path."""
    request = ImageGenerationRequest(prompt="A CEO on stage.")
    response = await MockImageAdapter().generate_image(request)
    assert len(response.image_bytes) > 0
