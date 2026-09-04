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


# --- R2.10-FINALIZATION-1 §9/§29: shared-storage cross-process invariant --------------------------
#
# RUNTIME-4's own real canary found that automation_worker's Tier-2B EVENT_RECAP media discovery
# wrote finalist bytes to a container-local, non-shared filesystem path - storage_status=STORED in
# the database, but the bytes themselves were gone the moment that one-shot container exited. The
# actual production fix is a docker-compose.yml volume mount (automation_worker now mounts the same
# `image_storage_data` named volume content_worker/telegram_bot already share) - not a code change,
# since `LocalImageStorage`/`_get_storage()` were already a correct, generic, shared-filesystem-
# ready abstraction the whole time. These tests prove that abstraction-level claim directly: two
# INDEPENDENT `LocalImageStorage` instances constructed over the SAME root directory (simulating two
# separate containers each mounting the same named volume) round-trip identical bytes/SHA256 with no
# cross-instance state - the volume mount is therefore sufficient, no storage-layer code is missing.


def test_A_write_uses_canonical_storage_abstraction(tmp_path) -> None:
    """Test A. `store_validated_image()` is the one, sole write path - no parallel/bespoke writer
    exists anywhere in this module (a structural fact already true; this test just proves the
    canonical path itself works exactly as every writer, including services.event_recap_processor's
    own Tier-2B discovery, actually calls it)."""
    storage = LocalImageStorage(tmp_path)
    stored = storage.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)
    assert stored.sha256 == _SHA256


def test_B_downstream_reader_in_a_different_instance_can_read_persisted_bytes(tmp_path) -> None:
    """Test B. Simulates the real production topology: one `LocalImageStorage` instance (the
    "writer container", e.g. automation_worker) stores bytes; a SEPARATE, independently-constructed
    instance over the SAME root (the "reader container", e.g. a future review/render process, or
    telegram_bot's own read-only mount) reads them back - proving the shared named-volume mount
    (this phase's own docker-compose.yml change) is what was actually missing, not any code path."""
    writer = LocalImageStorage(tmp_path)
    stored = writer.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)

    reader = LocalImageStorage(tmp_path)  # a genuinely separate instance - no shared Python state
    assert reader.exists(stored.storage_key)
    assert reader.read(stored.storage_key) == _DATA


def test_C_storage_sha256_preserved_across_instances(tmp_path) -> None:
    """Test C. The SHA256 recorded by the writer and independently recomputed from the reader's own
    bytes are identical - the same invariant `store_validated_image()`'s own hash-verification
    already enforces on write, now proven to survive a genuinely separate read."""
    writer = LocalImageStorage(tmp_path)
    stored = writer.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)

    reader = LocalImageStorage(tmp_path)
    read_back = reader.read(stored.storage_key)
    assert hashlib.sha256(read_back).hexdigest() == stored.sha256 == _SHA256


def test_D_missing_bytes_despite_stored_status_fails_visibly(tmp_path) -> None:
    """Test D. The exact failure mode RUNTIME-4 actually hit, reproduced directly: a storage_key
    that a database row might legitimately claim is STORED, but whose bytes are absent from THIS
    root (e.g. the writer's ephemeral filesystem was never shared) - `read()` must raise, never
    return empty/None/silently-wrong bytes, so the gap is loud, not a silent corruption."""
    reader = LocalImageStorage(tmp_path)  # a root that was never written to - the ephemeral-storage scenario
    never_written_key = build_storage_key(_SHA256, "JPEG")
    assert reader.exists(never_written_key) is False
    with pytest.raises(FileNotFoundError):
        reader.read(never_written_key)


def test_E_no_silent_ephemeral_storage_success_when_roots_differ(tmp_path) -> None:
    """Test E. Two DIFFERENT roots (simulating automation_worker's own container filesystem vs. the
    shared volume it was NOT mounting before this phase's own compose fix) - a write to one root
    must NOT be visible from the other. This is the negative control proving test B's own success is
    genuinely about the SHARED root, not an accidental global/class-level cache inside
    `LocalImageStorage` itself."""
    root_a = tmp_path / "container_a_ephemeral"
    root_b = tmp_path / "container_b_ephemeral"
    writer = LocalImageStorage(root_a)
    stored = writer.store_validated_image(_DATA, sha256=_SHA256, image_format="JPEG", max_bytes=10_000)

    other_container_reader = LocalImageStorage(root_b)
    assert other_container_reader.exists(stored.storage_key) is False
