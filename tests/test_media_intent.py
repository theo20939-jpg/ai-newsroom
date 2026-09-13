"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1: schemas.media_intent.MediaIntent."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType


def _base(**overrides) -> MediaIntent:
    defaults = dict(subject_type=MediaSubjectType.PRODUCT, primary_entity="iPhone Duo", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO)
    defaults.update(overrides)
    return MediaIntent(**defaults)


def test_identity_terms_orders_most_specific_first() -> None:
    intent = _base(model_name="iPhone Duo", product_name="iPhone", company="Apple")
    assert intent.identity_terms[0] == "iPhone Duo"
    assert "Apple" in intent.identity_terms


def test_identity_terms_skips_absent_fields_never_emits_none() -> None:
    intent = _base(company="Apple")
    assert None not in intent.identity_terms
    assert intent.identity_terms == ["Apple"]


def test_frozen_never_mutable() -> None:
    intent = _base()
    with pytest.raises(ValidationError):
        intent.primary_entity = "something else"


def test_primary_entity_required_and_bounded() -> None:
    with pytest.raises(ValidationError):
        MediaIntent(subject_type=MediaSubjectType.PRODUCT, primary_entity="", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO)


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        MediaIntent(
            subject_type=MediaSubjectType.PRODUCT, primary_entity="x",
            desired_visual_type=DesiredVisualType.PRODUCT_PHOTO, unexpected_field="y",
        )
