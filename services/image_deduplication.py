"""Phase 16 M3: exact and perceptual near-duplicate clustering, scoped to one event only (docs/
phase16_m3_quality_and_deduplication_report.md §15/§18). Pure clustering logic - no networking, no
decode (perceptual hashes are computed once, per candidate, by services/image_quality.py; this
module only compares already-computed hashes).

Distance thresholds were calibrated empirically against a synthetic fixture set (identical,
resized, JPEG-recompressed at three quality levels, small crop, large crop, brightness-adjusted,
text-overlaid, rotated, and two distinct scenes) - not adopted from an external library default
(M3 report §17 has the full measured distribution). Identical/resized/recompressed/small-crop/
brightness variants all measured at Hamming distance <=4; a moderate text overlay measured at 5;
a 25%-edge crop measured at 15; unrelated images measured 22-43. This is why the automatic
near-duplicate threshold is 4 (not the commonly-cited "10" default some libraries use) and the
review band extends to 12: it is deliberately conservative, erring toward `review` over silently
merging two editorially distinct images (the M3 task brief's own explicit priority).
"""
import hashlib
from collections import defaultdict
from dataclasses import dataclass

from schemas.image_candidate import DeduplicationInfo, ImageCandidate
from services.image_quality import QualityAnalysis, hamming_distance

# Calibrated against real measured distances (module docstring) - never adopted blindly.
AUTO_DUPLICATE_MAX_DISTANCE = 4
REVIEW_MAX_DISTANCE = 12


def _cluster_id(kind: str, seed: str) -> str:
    """Deterministic, stable across reruns for the same input - mirrors services/image_
    intelligence.py's own sha256-based candidate-identity precedent."""
    return hashlib.sha256(f"{kind}:{seed}".encode("utf-8")).hexdigest()[:16]


def _representative_sort_key(candidate: ImageCandidate, analysis: QualityAnalysis) -> tuple:
    """Documented representative-selection ordering (M3 report §19): technically valid first
    (guaranteed true for every input here - only VALIDATED candidates reach this module), higher
    resolution, better (more editorial) aspect ratio, stronger discovery-method provenance, larger
    byte size as a weak tie-breaker, earlier discovery order, then candidate_id for full
    determinism. Sorted ascending, so this returns values where "smaller is better"."""
    technical = candidate.technical_validation
    pixel_count = technical.pixel_count if technical and technical.pixel_count else 0
    byte_size = technical.byte_size if technical and technical.byte_size else 0
    # aspect-ratio quality proxy: reuse the same component table quality analysis already computed
    aspect_component = analysis.quality_components.get("aspect_ratio", 0)
    return (
        -pixel_count,
        -aspect_component,
        -analysis.quality_components.get("metadata_confidence", 0),
        -byte_size,
        candidate.discovery_order,
        candidate.candidate_id,
    )


@dataclass(frozen=True)
class _ExactGroup:
    sha256: str
    representative: ImageCandidate
    representative_analysis: QualityAnalysis
    member_ids: list[str]
    cluster_id: str


def _build_exact_groups(
    items: list[tuple[ImageCandidate, QualityAnalysis]],
) -> dict[str, _ExactGroup]:
    by_sha: dict[str, list[tuple[ImageCandidate, QualityAnalysis]]] = defaultdict(list)
    for candidate, analysis in items:
        sha = candidate.technical_validation.sha256 if candidate.technical_validation else None
        if sha:
            by_sha[sha].append((candidate, analysis))

    groups: dict[str, _ExactGroup] = {}
    for sha, members in by_sha.items():
        ordered = sorted(members, key=lambda pair: _representative_sort_key(pair[0], pair[1]))
        representative_candidate, representative_analysis = ordered[0]
        groups[sha] = _ExactGroup(
            sha256=sha,
            representative=representative_candidate,
            representative_analysis=representative_analysis,
            member_ids=[c.candidate_id for c, _ in members],
            cluster_id=_cluster_id("exact", sha),
        )
    return groups


@dataclass(frozen=True)
class _NearCluster:
    cluster_id: str
    representative_sha: str
    representative_candidate_id: str
    phash: str
    member_shas: list[str]
    member_distances: dict[str, int]


def _build_near_clusters(exact_groups: dict[str, _ExactGroup]) -> list[_NearCluster]:
    """Representative-based ("star") clustering, processed in quality-descending order, so every
    merge decision compares against an already-established cluster's own representative - never a
    transitive A~B~C chain that could merge A and C despite them being distant (M3 report §18's
    explicit avoidance of naive transitive over-merging)."""
    pool = [
        (sha, group.representative, group.representative_analysis)
        for sha, group in exact_groups.items()
        if group.representative_analysis.perceptual_hash is not None
    ]
    pool.sort(key=lambda item: _representative_sort_key(item[1], item[2]))

    clusters: list[_NearCluster] = []
    for sha, candidate, analysis in pool:
        phash = analysis.perceptual_hash
        assert phash is not None
        best_cluster_index: int | None = None
        best_distance: int | None = None
        for index, cluster in enumerate(clusters):
            distance = hamming_distance(phash, cluster.phash)
            if distance <= AUTO_DUPLICATE_MAX_DISTANCE and (best_distance is None or distance < best_distance):
                best_cluster_index, best_distance = index, distance
        if best_cluster_index is not None:
            cluster = clusters[best_cluster_index]
            cluster.member_shas.append(sha)
            cluster.member_distances[sha] = best_distance  # type: ignore[assignment]
        else:
            clusters.append(
                _NearCluster(
                    cluster_id=_cluster_id("near", phash),
                    representative_sha=sha,
                    representative_candidate_id=candidate.candidate_id,
                    phash=phash,
                    member_shas=[],
                    member_distances={},
                )
            )
    return clusters


def _nearest_review_neighbor(sha: str, phash: str, clusters: list[_NearCluster]) -> tuple[str, int] | None:
    """For a representative that did not auto-merge into any cluster, find the closest cluster
    within the review band (if any) - used to mark `review` rather than silently `accepted` when
    similarity is uncertain (M3 report §18)."""
    best: tuple[str, int] | None = None
    for cluster in clusters:
        if cluster.representative_sha == sha:
            continue
        distance = hamming_distance(phash, cluster.phash)
        if distance <= REVIEW_MAX_DISTANCE and (best is None or distance < best[1]):
            best = (cluster.representative_candidate_id, distance)
    return best


def cluster_candidates(
    items: list[tuple[ImageCandidate, QualityAnalysis]],
) -> dict[str, DeduplicationInfo]:
    """The sole entry point. `items` must already be scoped to one event and filtered to
    candidates with a usable perceptual hash (i.e., ones `services.image_quality.analyze_candidate`
    successfully decoded) - callers filter this themselves (services/image_intelligence.py).
    Returns one `DeduplicationInfo` per candidate_id, covering every input candidate exactly once.
    """
    exact_groups = _build_exact_groups(items)
    near_clusters = _build_near_clusters(exact_groups)

    sha_to_exact_group = {sha: group for sha, group in exact_groups.items()}
    sha_to_near_cluster_as_member: dict[str, tuple[_NearCluster, int]] = {}
    sha_to_near_cluster_as_representative: dict[str, _NearCluster] = {}
    for cluster in near_clusters:
        sha_to_near_cluster_as_representative[cluster.representative_sha] = cluster
        for member_sha in cluster.member_shas:
            sha_to_near_cluster_as_member[member_sha] = (cluster, cluster.member_distances[member_sha])

    result: dict[str, DeduplicationInfo] = {}
    for candidate, analysis in items:
        sha = candidate.technical_validation.sha256 if candidate.technical_validation else None
        phash = analysis.perceptual_hash

        if sha is None:
            result[candidate.candidate_id] = DeduplicationInfo(perceptual_hash=phash)
            continue

        exact_group = sha_to_exact_group[sha]
        is_exact_representative = candidate.candidate_id == exact_group.representative.candidate_id

        if not is_exact_representative:
            # An exact duplicate of this event's own exact-cluster representative - never itself
            # analyzed for near-duplicate membership (that only ever runs on one representative
            # per distinct sha256), inherits exact status only.
            result[candidate.candidate_id] = DeduplicationInfo(
                exact_hash=sha, perceptual_hash=phash, exact_cluster_id=exact_group.cluster_id,
                duplicate_of=exact_group.representative.candidate_id, hamming_distance=0,
                is_representative=False,
            )
            continue

        # This candidate IS its exact-group representative - resolve its near-duplicate status.
        if sha in sha_to_near_cluster_as_member:
            near_cluster, distance = sha_to_near_cluster_as_member[sha]
            result[candidate.candidate_id] = DeduplicationInfo(
                exact_hash=sha, perceptual_hash=phash, exact_cluster_id=exact_group.cluster_id,
                perceptual_cluster_id=near_cluster.cluster_id,
                duplicate_of=near_cluster.representative_candidate_id, hamming_distance=distance,
                is_representative=False,
            )
            continue

        own_cluster = sha_to_near_cluster_as_representative.get(sha)
        review_distance = None
        if own_cluster is not None and phash is not None:
            nearest = _nearest_review_neighbor(sha, phash, near_clusters)
            if nearest is not None:
                review_distance = nearest[1]

        result[candidate.candidate_id] = DeduplicationInfo(
            exact_hash=sha, perceptual_hash=phash, exact_cluster_id=exact_group.cluster_id,
            perceptual_cluster_id=own_cluster.cluster_id if own_cluster else None,
            duplicate_of=None, hamming_distance=review_distance, is_representative=True,
        )

    return result
