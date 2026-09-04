"""R2.10G3-B - holdout manifest for eventness rule calibration.

CRITICAL PROCESS INVARIANT: every label below was assigned by direct read of each Story's real
member events (title, timestamp, source URL - see the commit history for the exact forensic query
used, `select id, title, event_count, created_at from stories where event_count >= N order by
created_at desc`, followed by `load_story_events()` inspection) BEFORE any candidate rule in
scripts/_recap_r2_10_g3_eventness_calibrate.py was measured against this file. None of these
story_ids appear in scripts/_recap_r2_10_g3_eventness_manifest.py (the calibration set) - confirmed
by direct set-difference check before this file was written. Labels here must never be edited after
seeing a candidate rule's predictions - if a label is later found to be wrong, report it as a
LABEL_CORRECTION_PROPOSED and exclude the row, per this phase's own explicit instruction; never
silently edit it to make a rule look better.

Known, disclosed composition gap: this holdout is heavy on REAL_SINGLE_EVENT (10 of 13) and has
zero EVENT_LIFECYCLE/DIGEST/UNCLEAR representation - a genuine search was made for fresher
instances of those classes (queried for moderate-event-count, multi-day-span Stories, and for new
digest-template posts) and none were found in this database's current recent window beyond the
ones already used in the calibration manifest. Not cherry-picked for ease - this is what a real,
broad search over the most recent ~400 unused Stories surfaced.
"""
from __future__ import annotations

from dataclasses import dataclass

from scripts._recap_r2_10_g3_eventness_manifest import (
    DESIRED_EVENTNESS_VALUES,
    MANUAL_CLASSES,
    MANIFEST,
)


@dataclass(frozen=True)
class HoldoutEntry:
    fixture_id: str
    story_id: str
    title_snapshot: str
    manual_class: str
    desired_eventness: str
    rationale: str

    def __post_init__(self) -> None:
        assert self.manual_class in MANUAL_CLASSES, self.fixture_id
        assert self.desired_eventness in DESIRED_EVENTNESS_VALUES, self.fixture_id
        assert self.rationale, self.fixture_id


HOLDOUT: tuple[HoldoutEntry, ...] = (
    HoldoutEntry(
        fixture_id="holdout_claude_fable_mythos", story_id="fdb2a4ab-ea6d-4b2f-89f6-58b4fb906dde",
        title_snapshot="Anthropic представила Claude Fable 5.1 и Mythos 5.1",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="2 events, 7 minutes apart, 2 independent outlets (tproger.ru, 3dnews.ru) - a real product announcement.",
    ),
    HoldoutEntry(
        fixture_id="holdout_pentagon_grok", story_id="c64825b2-1177-4dd5-a2e8-d7429ce1d47b",
        title_snapshot="Пентагон подключил Grok к военной AI-платформе США",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="2 events, identical timestamp - one direct (ixbt.com) plus a Google-News-wrapped copy of the same article; a real single announcement, thinly sourced.",
    ),
    HoldoutEntry(
        fixture_id="holdout_ai_content_marking_law", story_id="9999fa75-7c51-4b0e-8bb8-1c73ca0b98ed",
        title_snapshot="Крупные платформы должны обеспечить маркировку ИИ-контента с 1 сентября",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="1 confirmed event (declared event_count=2, a known Story.event_count-vs-confirmed-membership mismatch) - a real regulatory-deadline announcement.",
    ),
    HoldoutEntry(
        fixture_id="holdout_bailey_g20_warning", story_id="65d21e55-1fa2-42a3-8324-b6016b591fea",
        title_snapshot="AI could cause global economic downturn, Andrew Bailey warns G20",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="1 confirmed event - a real, single named-official statement.",
    ),
    HoldoutEntry(
        fixture_id="holdout_schiller_steps_down", story_id="86bc1b2e-d827-417e-9986-c5198d9c8b39",
        title_snapshot="Sources: Phil Schiller stepped down from his role leading the App Store",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="2 events, ~2h15m apart, 2 independent outlets (Techmeme, Engadget) - a real personnel-change event.",
    ),
    HoldoutEntry(
        fixture_id="holdout_pytorch_trunk_noise", story_id="10b776b3-254e-4804-b6ae-caefb3c0e40a",
        title_snapshot="trunk/736985d0de6c552c8fe2324b101cc94bd21b245b: [BE] Extend dropout support",
        manual_class="NOISE", desired_eventness="REJECT",
        rationale="A PyTorch GitHub CI release-tag title, same non-editorial pattern as the ciflow_ci_noise calibration fixture but a DIFFERENT repo/tag-naming convention - a genuine generalization test for any noise-detecting rule.",
    ),
    HoldoutEntry(
        fixture_id="holdout_video_diffusion_cluster", story_id="c66e3eaa-53e3-4252-abab-686d13cda071",
        title_snapshot="Video diffusion transformers are costly to sample",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT",
        rationale="9 confirmed arXiv preprints (video diffusion, video understanding, video generation, multimodal video LLMs, autonomous driving...), Aug 12-28 - same VLA-shaped research-topic pattern, different subject.",
    ),
    HoldoutEntry(
        fixture_id="holdout_when_predictor_cluster", story_id="5f2ca39e-690d-4a4d-a106-8b01e003683d",
        title_snapshot="When a probabilistic predictor answers many conditional-probability queries",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT",
        rationale="8 confirmed events (7 arXiv + 1 venturebeat.com editorial article), Aug 11-31, wildly different subjects (probability calibration, multi-agent governance, pragmatics, information extraction) unified only by the generic sentence-opener 'When' - already excluded from future extraction by G1, but this historical Story still exists.",
    ),
    HoldoutEntry(
        fixture_id="holdout_khabarovsk_ai", story_id="34aa87f0-b413-4408-a454-1a5d07e5d971",
        title_snapshot="Искусственный интеллект разрушит облик Хабаровска",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="1 confirmed event - a real, single regional news article.",
    ),
    HoldoutEntry(
        fixture_id="holdout_google_ai_mode_search", story_id="b90f3646-078f-4458-9b19-c4f9263e8af7",
        title_snapshot="Google начала навязывать ИИ-режим в поиске",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="2 events, identical timestamp, both Google-News-wrapped - a real single-source-shaped event.",
    ),
    HoldoutEntry(
        fixture_id="holdout_apple_beta8_seeds", story_id="d3abe582-97f0-4357-b7b9-c47b39173a66",
        title_snapshot="Apple Seeds watchOS 27 Beta 8 to Developers",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="2 events, 1 minute apart, BOTH macrumors.com (single source) but genuinely different sub-announcements (visionOS Beta 8 + tvOS Beta 8, Apple's routine same-day multi-OS beta release) - a deliberate single-source-real-event edge case.",
    ),
    HoldoutEntry(
        fixture_id="holdout_dwarf_fortress_update", story_id="0db7d297-50a4-4132-9e3e-8baeedd0898f",
        title_snapshot="Dwarf Fortress is getting the mother of all magic updates",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="2 events, ~3h apart, both pcgamer.com (single source) - real developer-interview coverage, single-source real event.",
    ),
    HoldoutEntry(
        fixture_id="holdout_cloudru_earnings", story_id="eea499f3-cf19-4fa2-8be9-184ab6ebcab2",
        title_snapshot="Cloud.ru объявил финансовые результаты за первое полугодие 2026 года",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT",
        rationale="3 events (2 Google-News-wrapped + 1 direct tproger.ru), ~10.5h span - a real quarterly-earnings announcement.",
    ),
)


def used_story_ids_overlap_with_calibration() -> set[str]:
    """Pure sanity check - must return the empty set. Exposed for the test suite."""
    calibration_ids = {e.story_id for e in MANIFEST if e.story_id}
    holdout_ids = {e.story_id for e in HOLDOUT}
    return calibration_ids & holdout_ids
