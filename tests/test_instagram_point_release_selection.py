"""Point-release false positive (founder task 2026-09-29, after the final natural canary 36b25f9).

Two routine iOS point releases of the natural pool (one of them a Face ID bug fix) read as DEVICE launches ('releases iOS 27.0.1 for
iPhone', 'released iPadOS 27.0.1') and became daily-eligible. A software release is judged on WHAT CHANGED: maintenance (fixes, patches,
stability) is never a launch; a release-level change (a redesign, the biggest update, new AI features) is a real software launch. The
vendor names below are data from real headlines or neutral fixtures - the rules name no vendor, platform or version.
"""
from __future__ import annotations

import pytest

from services.instagram_viral_story_gate import (
    assess_broad_interest,
    assess_inherent_strength,
    device_launch_found,
    routine_software_release,
)

# the two real items of the natural pool (saved pool: 49ab24e0 MacRumors, 786f08cd 9to5Mac), title + stored lead
REAL_FACE_ID = ("Apple Releases iOS 27.0.1 With Face ID Bug Fix",
                "Apple today released iOS 27.0.1, the first update for the iOS 27 update that came out two weeks ago. iOS 27.0.1 can be "
                "downloaded over the air by going to Settings > General > Software Update.")
REAL_WHATS_NEW = ("Apple releases iOS 27.0.1 for iPhone, here’s what’s new",
                  "Apple has just released iOS 27.0.1, a new iPhone software update with key bug fixes for issues introduced in iOS 27. "
                  "Here’s what’s new.")


def _strength(title: str, lead: str = "") -> tuple[str, list[str]]:
    strength, mechanisms, _hook = assess_inherent_strength(title, lead)
    return strength, mechanisms


# --- the real false positives ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("item", [REAL_FACE_ID, REAL_WHATS_NEW])
def test_real_point_releases_are_no_launch(item):
    title, lead = item
    assert routine_software_release(title, lead)
    strength, mechanisms = _strength(title, lead)
    assert strength == "NONE" and mechanisms == []


def test_releasing_software_for_a_device_is_not_a_device_launch():
    assert not device_launch_found("Apple releases iOS 27.0.1 for iPhone")
    assert not device_launch_found("Apple has also released iPadOS 27.0.1 and visionOS 27.0.1 updates")
    assert device_launch_found("Apple unveils iPhone 18 Pro with iOS 27")  # the device itself is launched


# --- routine maintenance stays out -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("title,lead", [
    ("Vendor releases PhoneOS 17.0.2 with bug fixes", "The update fixes a crash in the camera app."),
    ("Vendor rolls out 17.0.2 security patch for its phones", "The patch closes 40 vulnerabilities."),
    ("Vendor releases stability update 5.4.1 for its app", "Version 5.4.1 improves stability and performance."),
    ("Vendor releases firmware update for its X2 smartwatch", "The firmware update is a minor maintenance release with bug fixes."),
    ("Vendor launches app version 5.4.1", "This maintenance release contains performance improvements and bug fixes."),
    ("Vendor выпустила обновление прошивки 3.1.4 для смартфона", "Обновление исправляет ошибки и повышает стабильность."),
])
def test_routine_maintenance_gets_no_launch_strength(title, lead):
    assert routine_software_release(title, lead)
    strength, mechanisms = _strength(title, lead)
    assert not {"ai_launch", "device_launch", "device_novelty", "software_launch"} & set(mechanisms)
    assert strength != "STRONG"


# --- meaningful software releases still compete ------------------------------------------------------------------------------------

@pytest.mark.parametrize("title,lead", [
    ("Vendor releases PhoneOS 18 with a complete redesign", "The update brings a new home screen and new widgets."),
    ("Vendor rolls out its biggest update ever to the Nimbus app", "Version 5 changes how people book trips."),
    ("Vendor releases PhoneOS 18 with new AI features", "An assistant can now act inside apps."),
    ("Vendor launches the Nimbus app with dozens of new features", "Offline mode, shared lists and a new editor arrive."),
    ("Vendor выпустила крупнейшее обновление PhoneOS", "Появились новые ИИ-функции и новый интерфейс."),
])
def test_meaningful_software_releases_can_compete(title, lead):
    assert not routine_software_release(title, lead)
    strength, mechanisms = _strength(title, lead)
    assert "software_launch" in mechanisms and strength == "STRONG"
    assert assess_broad_interest(title, lead)[0] == "BROAD"


def test_a_significant_release_that_also_fixes_bugs_is_not_maintenance():
    title, lead = "Vendor releases PhoneOS 18 with a complete redesign", "It also fixes bugs and patches vulnerabilities."
    assert not routine_software_release(title, lead)
    assert "software_launch" in _strength(title, lead)[1]


# --- accepted launches and viral stories are untouched ------------------------------------------------------------------------------

@pytest.mark.parametrize("title,lead,family", [
    ("Батарея на 11 000 мА·ч, прошлогодний Snapdragon и камера на 200 Мп: Honor представила геймерский смартфон Magic 9 Super", "",
     "device_launch"),
    ("Anthropic выпустила нейросеть Claude Sonnet 5.5", "", "ai_launch"),
    ("OpenAI launches GPT-6 Sol and GPT-6 Luna in the API", "The update also fixes bugs in the older models.", "ai_launch"),
    ("Apple unveils iPhone 18 Pro with iOS 27", "The phone ships with a new camera.", "device_launch"),
])
def test_device_and_model_launches_keep_their_strength(title, lead, family):
    strength, mechanisms = _strength(title, lead)
    assert family in mechanisms and strength == "STRONG"


def test_a_real_failure_in_an_update_is_still_a_story():
    """Only launch strength is removed from a maintenance release - an update that deletes users' files is still a real failure."""
    strength, mechanisms = _strength("Windows update accidentally deletes users' files",
                                     "Microsoft says a bug in the 24H2 patch wiped documents; a fix is coming.")
    assert "real_failure" in mechanisms and strength == "STRONG"


def test_a_major_update_to_something_that_is_not_software_is_no_software_launch():
    """Real headline of canaries 9 / 10 (a training programme, not software)."""
    assert "software_launch" not in _strength("RSNA's AI certificate program undergoes 'major update'",
                                              "The major update adds new modules for radiologists.")[1]
