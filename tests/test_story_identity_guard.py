"""STORY-CONTINUITY-P0.1 - the abstract-quality / stable-document-identity firewall
(services/story_identity_guard.py). Pure-function unit tests: the title semantic detector,
arXiv/DOI identity parsing + version normalization, and the ``assess_continuity_identity``
decision matrix (report Section 10, cases 1-10). The end-to-end production replay lives in
tests/test_story_continuity_arxiv_replay.py."""
from __future__ import annotations

import pytest

from services.story_identity_guard import (
    ABSTRACT_LIKE,
    ARXIV,
    DOI,
    GUARD_FAIL_OPEN,
    GUARD_SAFE,
    IDENTITY_CONFLICT,
    IDENTITY_INSUFFICIENT,
    IDENTITY_MATCH,
    TITLE_LIKE,
    TITLE_QUALITY_UNKNOWN,
    assess_continuity_identity,
    assess_title_semantic_quality,
    extract_document_identity,
)

# --- a few representative real shadow-sample abstract openings (public arXiv text) --------------
_ABS_MLLM = (
    "Multimodal Large Language Models (MLLMs) perform strongly on general visual understanding "
    "tasks such as visual question answering. However, they struggle with gigapixel pathology "
    "images. In this work we introduce a hierarchical approach. We evaluate on three public "
    "benchmarks and report consistent gains. Code and models are released."
)
_ABS_EMBODIED = (
    "Embodied visual tracking requires a robot not only to react to the current view, but to "
    "choose actions that preserve visibility of the target over a long horizon. Prior work "
    "relies on hand-tuned heuristics. We propose a learned policy trained in simulation and "
    "transferred zero-shot to a physical platform."
)


# =============================================================================================
# assess_title_semantic_quality
# =============================================================================================

@pytest.mark.parametrize(
    "title",
    [
        "Meta launches Muse, a personal AI agent with multilingual voice transcription",
        "Apple announces iPhone 17 Pro with a redesigned camera system",
        "OpenAI is testing a Persistent mode in Codex for long-running agents",
        "b10868",  # a GitHub release tag
        "An Accidental Blackboard",
    ],
)
def test_normal_headlines_are_title_like(title: str) -> None:
    assert assess_title_semantic_quality(title).quality == TITLE_LIKE


@pytest.mark.parametrize("title", [_ABS_MLLM, _ABS_EMBODIED])
def test_arxiv_abstract_openings_are_abstract_like(title: str) -> None:
    a = assess_title_semantic_quality(title)
    assert a.quality == ABSTRACT_LIKE
    assert a.reasons  # structured evidence, never a bare bool
    assert a.measurements["char_count"] >= 200


def test_title_equal_to_summary_is_abstract_like_even_if_short() -> None:
    body = (
        "We revisit a classical estimator and show a surprising bias. Our correction is cheap. "
        "Experiments confirm the theory on four datasets."
    )
    a = assess_title_semantic_quality(body, summary=body)
    assert a.quality == ABSTRACT_LIKE
    assert "title_equals_body_prefix" in a.reasons


def test_borderline_length_single_clause_is_unknown_not_abstract() -> None:
    # ~170 chars, one clause, no academic lead-in, no terminal sentences -> genuinely borderline,
    # must NOT be called ABSTRACT_LIKE (that would risk normal-news regression).
    title = (
        "The company said the new subscription tier will roll out to enterprise customers in "
        "several regions over the coming weeks after a limited early-access period this quarter"
    )
    assert assess_title_semantic_quality(title).quality == TITLE_QUALITY_UNKNOWN


def test_academic_lead_in_only_escalates_within_borderline_band() -> None:
    title = (
        "In this paper we study a new regularizer for deep networks and provide both theory and "
        "a broad empirical evaluation across vision and language benchmarks of varying scale"
    )
    assert assess_title_semantic_quality(title).quality == ABSTRACT_LIKE


def test_assessment_is_deterministic() -> None:
    a = assess_title_semantic_quality(_ABS_MLLM)
    b = assess_title_semantic_quality(_ABS_MLLM)
    assert a == b


# =============================================================================================
# extract_document_identity  (+ arXiv version semantics)
# =============================================================================================

@pytest.mark.parametrize(
    "url,identifier,version",
    [
        ("https://arxiv.org/abs/2609.06385v1", "2609.06385", "1"),
        ("https://arxiv.org/abs/2609.06385", "2609.06385", None),
        ("http://arxiv.org/pdf/2609.06385v2", "2609.06385", "2"),
        ("https://www.arxiv.org/abs/2412.01234v10", "2412.01234", "10"),
        ("https://arxiv.org/abs/hep-th/9901001", "hep-th/9901001", None),
        ("https://arxiv.org/abs/math.AG/0601001v2", "math.ag/0601001", "2"),
    ],
)
def test_arxiv_identity_parsing(url: str, identifier: str, version: str | None) -> None:
    ev = extract_document_identity(url=url)
    assert ev is not None
    assert (ev.namespace, ev.identifier, ev.version) == (ARXIV, identifier, version)


def test_arxiv_versions_share_one_base_identifier() -> None:
    v1 = extract_document_identity(url="https://arxiv.org/abs/2609.06385v1")
    v2 = extract_document_identity(url="https://arxiv.org/abs/2609.06385v2")
    bare = extract_document_identity(url="https://arxiv.org/abs/2609.06385")
    assert v1 and v2 and bare
    assert v1.identifier == v2.identifier == bare.identifier
    assert (v1.version, v2.version, bare.version) == ("1", "2", None)


def test_bare_arxiv_token_in_title_text_is_a_fallback() -> None:
    ev = extract_document_identity(url="https://example.org/paper", title="New result (arXiv:2609.06385)")
    assert ev is not None and ev.namespace == ARXIV and ev.identifier == "2609.06385"
    assert ev.source == "title_text"


def test_doi_from_url() -> None:
    ev = extract_document_identity(url="https://doi.org/10.1038/s41586-024-07123-4")
    assert ev is not None and ev.namespace == DOI and ev.identifier == "10.1038/s41586-024-07123-4"


def test_no_identity_for_ordinary_news_url() -> None:
    assert extract_document_identity(url="https://www.theverge.com/2026/9/9/meta-muse") is None
    assert extract_document_identity(url=None, title="Meta launches Muse") is None


# =============================================================================================
# assess_continuity_identity  - report Section 10 decision matrix
# =============================================================================================

def _assess(new_url, priors, *, title=_ABS_MLLM, summary=None, exact=False):
    return assess_continuity_identity(
        new_title=title, new_url=new_url, new_summary=summary,
        prior_documents=priors, match_is_exact_title_identity=exact,
    )


def test_case1_unrelated_arxiv_ids_templated_openings_fail_open() -> None:
    a = _assess(
        "https://arxiv.org/abs/2609.06245v1",
        [(_ABS_EMBODIED, "https://arxiv.org/abs/2609.06302v1")],
    )
    assert a.verdict == GUARD_FAIL_OPEN
    assert a.identity_status == IDENTITY_CONFLICT


def test_case2_mllm_style_prose_different_ids_fail_open() -> None:
    a = _assess(
        "https://arxiv.org/abs/2609.06245v1",
        [(_ABS_MLLM.replace("gigapixel pathology", "remote-sensing"), "https://arxiv.org/abs/2609.09999v1")],
    )
    assert a.verdict == GUARD_FAIL_OPEN


@pytest.mark.parametrize("lead", ["As ", "Learning "])
def test_case3_4_generic_lead_in_unrelated_abstracts_no_unsafe_duplicate(lead: str) -> None:
    new = lead + (
        "the deployment of large models expands, reliable evaluation under distribution shift "
        "becomes essential. We build a benchmark. We analyse ten systems. We release everything."
    )
    prior = lead + (
        "based control of legged robots has advanced quickly, yet sim-to-real transfer remains "
        "brittle. We propose a curriculum. We test on hardware. Results improve markedly."
    )
    a = _assess(
        "https://arxiv.org/abs/2609.05966v1",
        [(prior, "https://arxiv.org/abs/2609.02222v1")],
        title=new,
    )
    assert a.verdict == GUARD_FAIL_OPEN


def test_case5_same_arxiv_base_id_repeated_delivery_stays_safe() -> None:
    a = _assess(
        "https://arxiv.org/abs/2609.06316v1",
        [(_ABS_MLLM, "https://arxiv.org/abs/2609.06316v1")],
    )
    assert a.verdict == GUARD_SAFE
    assert a.identity_status == IDENTITY_MATCH


def test_case6_same_arxiv_id_later_version_stays_safe() -> None:
    a = _assess(
        "https://arxiv.org/abs/2609.06316v2",
        [(_ABS_MLLM, "https://arxiv.org/abs/2609.06316v1")],
    )
    assert a.verdict == GUARD_SAFE and a.identity_status == IDENTITY_MATCH


def test_case7_normal_vendor_launch_news_preserved() -> None:
    a = _assess(
        "https://techcrunch.com/2026/09/09/meta-muse",
        [("Meta unveils Muse, its personal AI agent", "https://www.theverge.com/meta-muse")],
        title="Meta launches Muse, a personal AI agent that can shop and send emails",
    )
    assert a.verdict == GUARD_SAFE
    assert a.identity_status == IDENTITY_INSUFFICIENT


def test_case8_short_news_titles_with_lexical_overlap_not_regressed() -> None:
    a = _assess(
        "https://www.bleepingcomputer.com/news/x",
        [("New Windows zero-day actively exploited, Microsoft warns", "https://arstechnica.com/y")],
        title="Windows zero-day now exploited in the wild, Microsoft confirms",
    )
    assert a.verdict == GUARD_SAFE


def test_case9_abstract_like_no_extractable_id_fails_open() -> None:
    a = _assess(
        None,
        [(_ABS_EMBODIED, None)],
        title=_ABS_MLLM,
    )
    assert a.verdict == GUARD_FAIL_OPEN
    assert a.identity_status == IDENTITY_INSUFFICIENT
    assert "abstract_like_title_unsafe_match" in a.reason_codes


def test_case9b_exact_identical_abstract_text_no_id_is_still_safe() -> None:
    a = _assess(None, [(_ABS_MLLM, None)], title=_ABS_MLLM, exact=True)
    assert a.verdict == GUARD_SAFE


def test_case10_polluted_story_many_ids_new_id_present_still_fails_open() -> None:
    # The corrupted 14-event story: several unrelated arXiv ids, and the new event's own id
    # happens to already be in the pile (the same mis-clustering happened last cycle).
    priors = [
        (_ABS_MLLM, "https://arxiv.org/abs/2609.01004v1"),
        (_ABS_EMBODIED, "https://arxiv.org/abs/2608.30653v1"),
        ("As online dating goes into salvage mode, can AI solve all its problems?", "https://www.theguardian.com/x"),
        (_ABS_MLLM, "https://arxiv.org/abs/2609.06245v1"),  # new event's own id, already here
    ]
    a = _assess("https://arxiv.org/abs/2609.06245v1", priors)
    assert a.verdict == GUARD_FAIL_OPEN
    assert "polluted_multi_document_story" in a.reason_codes


def test_clean_single_paper_cluster_is_not_flagged_as_polluted() -> None:
    priors = [
        (_ABS_MLLM, "https://arxiv.org/abs/2609.06316v1"),
        (_ABS_MLLM, "https://arxiv.org/abs/2609.06316v2"),
    ]
    a = _assess("https://arxiv.org/abs/2609.06316v1", priors)
    assert a.verdict == GUARD_SAFE and a.identity_status == IDENTITY_MATCH


def test_real_news_story_with_many_sources_is_never_polluted() -> None:
    priors = [(f"Outlet {i} covers the Meta Muse launch", f"https://outlet{i}.com/muse") for i in range(12)]
    a = _assess(
        "https://techcrunch.com/muse",
        priors,
        title="Meta launches Muse personal AI agent",
    )
    assert a.measurements["distinct_prior_identities"] == 0.0
    assert a.verdict == GUARD_SAFE
