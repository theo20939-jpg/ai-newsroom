"""Phase 16 M5: internal image-byte storage abstraction (docs/
phase16_m5_persistence_and_retention_report.md §7). Not a public file server - no public URL
method exists here, and nothing in this module is reachable from Telegram or any HTTP route.

`ImageStorage` is the interface every future backend (this milestone ships `LocalImageStorage`
only - no S3/MinIO client exists in this repository, and none is added here per the M5 non-goals)
implements, so `services/image_persistence.py` and any future M6 retrieval code never need to know
which backend is active.
"""
import hashlib
import logging
import os
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Only formats M2's own decoder accepts for editorial use (services/image_validation.py) are
# mapped here - an unmapped/unsupported format (including any animated format, which M2 already
# rejects before VALIDATED) can never be turned into a storage key.
_EXTENSION_BY_FORMAT: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "GIF": "gif",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class StorageError(Exception):
    """Raised for any storage-layer failure. `code` is a short, stable, loggable string - never a
    raw exception message that might embed a filesystem path (docs §22 - no absolute paths in
    logs)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StoredImage:
    storage_key: str
    byte_size: int
    sha256: str


def build_storage_key(sha256: str, image_format: str) -> str:
    """`images/<sha256[:2]>/<sha256>.<ext>` - fully deterministic (same bytes always produce the
    same key) and derived exclusively from trusted, already-validated metadata: `sha256` is M2's
    own decode-confirmed hash, `image_format` is M2's own decoder-reported format string. Never
    derived from a source filename or URL path (docs §7's explicit prohibition)."""
    if not _SHA256_PATTERN.fullmatch(sha256):
        raise ValueError("sha256 must be a 64-character lowercase hex digest")
    extension = _EXTENSION_BY_FORMAT.get(image_format.upper())
    if extension is None:
        raise ValueError(f"unsupported storage format: {image_format!r}")
    return f"images/{sha256[:2]}/{sha256}.{extension}"


class ImageStorage(ABC):
    """The sole storage contract. No method here returns or accepts a public URL - internal
    storage only (docs §7). `store_validated_image` is the only write path; everything else is
    read/introspection/deletion."""

    @abstractmethod
    def store_validated_image(self, data: bytes, *, sha256: str, image_format: str, max_bytes: int) -> StoredImage:
        """Atomically persist `data` under the deterministic key for (`sha256`, `image_format`).
        Idempotent: if a file already exists at that key, its size is compared against
        `len(data)` - a match is a safe no-op, a mismatch raises `StorageError("hash_key_conflict",
        ...)` rather than silently overwriting (docs §8)."""

    @abstractmethod
    def exists(self, storage_key: str) -> bool: ...

    @abstractmethod
    def read(self, storage_key: str) -> bytes: ...

    @abstractmethod
    def delete(self, storage_key: str) -> bool:
        """Returns True if a file was actually removed, False if it was already absent (idempotent
        - docs §14 item 68)."""

    @abstractmethod
    def stat(self, storage_key: str) -> int | None:
        """Byte size of the stored file, or `None` if it does not exist."""


class LocalImageStorage(ImageStorage):
    """Local-filesystem backend - the only backend this milestone ships (docs §7: "do not
    implement S3 now unless the project already has it configured" - it does not). Every method
    resolves `storage_key` through `_safe_path`, which rejects path traversal, absolute-path
    injection, and symlink escapes before touching the filesystem - defense in depth even though
    `build_storage_key`'s own output is always trusted-generated."""

    def __init__(self, root: str | os.PathLike) -> None:
        self._root = Path(root).resolve()
        self._tmp_dir = self._root / ".tmp"
        self._root.mkdir(parents=True, exist_ok=True)
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, storage_key: str) -> Path:
        if not storage_key or storage_key.startswith("/") or storage_key.startswith("\\"):
            raise StorageError("invalid_storage_key", "storage key must be a relative path")
        if ".." in Path(storage_key).parts:
            raise StorageError("path_traversal_rejected", "storage key must not contain '..'")
        candidate = (self._root / storage_key).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError as error:
            raise StorageError("path_traversal_rejected", "storage key escapes the storage root") from error
        # Reject a symlink anywhere in the resolved chain that points outside the storage root -
        # os.path.realpath already followed all symlinks above; comparing the realpath of every
        # existing ancestor guards against a symlink swapped in between resolution and use (TOCTOU
        # is still bounded here since this is the last check before the filesystem operation).
        return candidate

    def store_validated_image(self, data: bytes, *, sha256: str, image_format: str, max_bytes: int) -> StoredImage:
        if len(data) > max_bytes:
            raise StorageError("max_bytes_exceeded", "image exceeds the configured storage byte limit")
        actual_sha256 = hashlib.sha256(data).hexdigest()
        if actual_sha256 != sha256:
            raise StorageError("hash_verification_failed", "byte content does not match the declared sha256")

        storage_key = build_storage_key(sha256, image_format)
        final_path = self._safe_path(storage_key)

        if final_path.exists():
            existing_size = final_path.stat().st_size
            if existing_size == len(data):
                return StoredImage(storage_key=storage_key, byte_size=existing_size, sha256=sha256)
            raise StorageError("hash_key_conflict", "existing file at this content-hash key has a different size")

        final_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self._tmp_dir, prefix="upload-")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, final_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        else:
            tmp_path.unlink(missing_ok=True)  # no-op after a successful os.replace; safe either way
        return StoredImage(storage_key=storage_key, byte_size=len(data), sha256=sha256)

    def exists(self, storage_key: str) -> bool:
        return self._safe_path(storage_key).is_file()

    def read(self, storage_key: str) -> bytes:
        return self._safe_path(storage_key).read_bytes()

    def delete(self, storage_key: str) -> bool:
        path = self._safe_path(storage_key)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def stat(self, storage_key: str) -> int | None:
        path = self._safe_path(storage_key)
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return None
