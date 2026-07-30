"""Tests for integrations.storage.image_storage's Phase 16 M5 local backend (docs/
phase16_m5_persistence_and_retention_report.md §7-8). Pure filesystem tests against a tmp_path
root - no database, no network.
"""
import hashlib

import pytest

from integrations.storage.image_storage import (
    LocalImageStorage,
    StorageError,
    build_storage_key,
)

_DATA = b"fake-jpeg-bytes-not-a-real-image"
_SHA256 = hashlib.sha256(_DATA).hexdigest()


def test_build_storage_key_is_deterministic_and_sharded() -> None:
    key = build_storage_key(_SHA256, "JPEG")
    assert key == f"images/{_SHA256[:2]}/{_SHA256}.jpg"
    assert build_storage_key(_SHA256, "jpeg") == key  # case-insensitive format


def test_build_storage_key_rejects_bad_sha256() -> None:
    with pytest.raises(ValueError):
        build_storage_key("not-a-hash", "JPEG")


def test_build_storage_key_rejects_unsupported_format() -> None:
    with pytest.raises(ValueError):
        build_storage_key(_SHA256, "SVG")


def test_store_and_read_roundtrip(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)

    assert stored.byte_size == len(_DATA)
    assert stored.sha256 == _SHA256
    assert storage.exists(stored.storage_key)
    assert storage.read(stored.storage_key) == _DATA
    assert storage.stat(stored.storage_key) == len(_DATA)


def test_store_is_idempotent_for_identical_bytes(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    first = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    second = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    assert first == second


def test_store_rejects_hash_mismatch(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    wrong_hash = "0" * 64
    with pytest.raises(StorageError) as excinfo:
        storage.store_validated_image(_DATA, sha256=wrong_hash, image_format="JPEG", max_bytes=10_000)
    assert excinfo.value.code == "hash_verification_failed"


def test_store_rejects_oversized_payload(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    with pytest.raises(StorageError) as excinfo:
        storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=1)
    assert excinfo.value.code == "max_bytes_exceeded"


def test_store_rejects_content_hash_key_conflict(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    key = build_storage_key(_SHA256, "JPEG")
    (tmp_path / key).write_bytes(_DATA + b"more-bytes-different-size")

    with pytest.raises(StorageError) as excinfo:
        storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    assert excinfo.value.code == "hash_key_conflict"


def test_delete_is_idempotent(tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)

    assert storage.delete(stored.storage_key) is True
    assert storage.delete(stored.storage_key) is False
    assert not storage.exists(stored.storage_key)
    assert storage.stat(stored.storage_key) is None


@pytest.mark.parametrize(
    "bad_key",
    [
        "/etc/passwd",
        "../../etc/passwd",
        "images/../../../etc/passwd",
        "\\windows\\system32",
    ],
)
def test_path_traversal_and_absolute_paths_are_rejected(tmp_path, bad_key: str) -> None:
    storage = LocalImageStorage(tmp_path)
    with pytest.raises(StorageError):
        storage.exists(bad_key)


def test_no_public_url_method_exists() -> None:
    """Docs §7 - internal storage only, never a public file server."""
    for name in dir(LocalImageStorage):
        assert "url" not in name.lower()
