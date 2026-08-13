"""Tests for services.source_registry.load_source_pack."""
import json
from pathlib import Path

import yaml

from services.source_registry import load_source_pack

VALID_A = {
    "id": "feed_a",
    "name": "Feed A",
    "category": "media",
    "type": "rss",
    "url": "https://example.com/a.xml",
    "language": "en",
    "region": "global",
    "priority": 80,
    "reliability": 0.9,
    "fetch_interval": "15m",
    "enabled": True,
    "tags": ["ai"],
}

VALID_B = {**VALID_A, "id": "feed_b", "name": "Feed B", "url": "https://example.com/b.xml"}
DUPLICATE_OF_A = {**VALID_A, "name": "Feed A Duplicate", "url": "https://example.com/a-dup.xml"}
DUPLICATE_URL_OF_A = {**VALID_A, "id": "feed_a_same_url", "name": "Feed A Same URL"}
INVALID_PRIORITY = {**VALID_A, "id": "feed_bad_priority", "priority": 999}


def _write_package(tmp_path: Path, sources: list[dict]) -> Path:
    package_dir = tmp_path / "pack"
    sources_dir = package_dir / "sources"
    sources_dir.mkdir(parents=True)

    (package_dir / "manifest.json").write_text(
        json.dumps({"files": ["sources/sample.yaml"]}), encoding="utf-8"
    )
    (sources_dir / "sample.yaml").write_text(
        yaml.safe_dump({"version": 1, "sources": sources}), encoding="utf-8"
    )
    return package_dir


def test_loads_valid_sources(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path, [VALID_A, VALID_B])

    definitions, report = load_source_pack(package_dir)

    assert {d.id for d in definitions} == {"feed_a", "feed_b"}
    assert report.declared == 2
    assert report.valid == 2
    assert report.invalid == 0
    assert report.duplicate_ids == 0


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path, [VALID_A, DUPLICATE_OF_A])

    definitions, report = load_source_pack(package_dir)

    assert len(definitions) == 1
    assert definitions[0].id == "feed_a"
    assert report.duplicate_ids == 1


def test_rejects_duplicate_urls(tmp_path: Path) -> None:
    """Different ids, same url - url uniqueness is enforced independently of id uniqueness."""
    package_dir = _write_package(tmp_path, [VALID_A, DUPLICATE_URL_OF_A])

    definitions, report = load_source_pack(package_dir)

    assert len(definitions) == 1
    assert definitions[0].id == "feed_a"
    assert report.duplicate_urls == 1
    assert report.duplicate_ids == 0


def test_skips_invalid_entries_without_stopping(tmp_path: Path) -> None:
    package_dir = _write_package(tmp_path, [VALID_A, INVALID_PRIORITY, VALID_B])

    definitions, report = load_source_pack(package_dir)

    assert {d.id for d in definitions} == {"feed_a", "feed_b"}
    assert report.invalid == 1
    assert report.valid == 2
    assert report.declared == 3


def test_real_package_loads_without_error() -> None:
    """Smoke test against the actual newsroom_sources_v1 package shipped in the repo."""
    definitions, report = load_source_pack()

    assert report.declared == 230
    assert report.invalid == 0
    assert report.duplicate_ids == 0
    assert report.duplicate_urls == 0
    assert len(definitions) == 230
