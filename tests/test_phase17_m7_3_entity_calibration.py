"""Phase 17 M7.3 - entity prefix calibration tests (docs/phase17_m7_3_entity_calibration_report.md,
discovery: docs/phase17_m7_3_entity_calibration_discovery.md).

Option A only: generic-prefix stripping. A multi-word capitalized run used to be trusted
unconditionally as a real proper-noun phrase, with no per-word check the way the single-token
path already has - so "Автономный ИИ-агент" (a generic adjective + a technology-descriptor noun,
both capitalized only from sentence-initial position) was indistinguishable from a genuine
multi-word name like "Kimi K3". This file pins the fix and its deliberately accepted limitations
- Option B (broadening single-token recall for a word left over after stripping, e.g. "Saul") is
explicitly NOT implemented here.
"""
from services.fact_safety import (
    FactEvidence,
    _extract_entities,
    _is_strong_single_token_entity,
    _strip_generic_entity_prefix,
    evaluate_fact_safety,
)

# ---------------------------------------------------------------------------
# False positives removed (tests 1-3)
# ---------------------------------------------------------------------------


def test_false_positive_removed_avtonomnyi_ii_agent() -> None:
    assert _extract_entities("Автономный ИИ-агент протестировал реальный бизнес.") == []


def test_false_positive_removed_agent_saul() -> None:
    """Both generic words are stripped ("Агент") and the remainder ("Saul") does not
    independently pass the single-token strong-entity check - the accepted Option A limitation,
    documented, not a bug."""
    assert _extract_entities("Агент Saul получил доступ к бизнесу.") == []


def test_false_positive_removed_kitaiskaya_ii_model_kimi_k3() -> None:
    """The real product name survives after both generic leading words are stripped."""
    entities = _extract_entities("Китайская ИИ-модель Kimi K3 стала доступна в открытом доступе.")
    assert entities == ["Kimi K3"]


def test_bare_generic_descriptor_phrases_stay_excluded() -> None:
    """Named explicitly in the M7.3 authorization as "should not be treated as entities" - already
    correctly excluded before this milestone (bare descriptor, no adjective prefix at all), and
    confirmed still excluded after it."""
    assert _extract_entities("ИИ-модель показала хорошие результаты.") == []
    assert _extract_entities("Языковая модель обучена на новых данных.") == []


def test_bare_ii_model_no_longer_leaks_via_alias_collapse() -> None:
    """A related, pre-existing bug found while verifying this milestone's own examples (not
    something M7.3 introduces): "ИИ-модель" alone (single hyphenated token, no adjective prefix)
    used to collapse to bare "ии" via `_normalize_entity()`'s own descriptive-suffix stripping,
    then match the existing "ИИ"/"AI" alias - making a purely generic compound look like a strong
    single-token entity signal. `_is_strong_single_token_entity()` no longer routes its alias
    check through that suffix-stripping step."""
    assert _is_strong_single_token_entity("ИИ-модель") is False


# ---------------------------------------------------------------------------
# Safety regressions - real named entities and product names unaffected (tests 6-12)
# ---------------------------------------------------------------------------


def test_safety_openai_unaffected() -> None:
    assert _extract_entities("OpenAI объявила о новом продукте.") == ["OpenAI"]


def test_safety_kimi_k3_unaffected() -> None:
    assert _extract_entities("Kimi K3 доступна для всех.") == ["Kimi K3"]


def test_safety_nasa_unaffected() -> None:
    assert _extract_entities("NASA запустила новый спутник.") == ["NASA"]


def test_safety_tesla_inc_unaffected() -> None:
    assert _extract_entities("Tesla Inc объявила о партнерстве.") == ["Tesla Inc"]


def test_safety_samsung_google_unchanged_documented_pre_existing_limitation() -> None:
    """Per the M7.3 authorization's own instruction ("Saul (if existing behavior is unchanged,
    document it)"): Samsung and Google, as ordinary capitalized single words with no internal
    capital, no ALL-CAPS styling, and no legal suffix, are NOT extracted - exactly as before this
    milestone. This is the pre-existing single-token-recall limitation the M7.3 discovery report
    identified as out of scope ("Option B", not implemented here) - documented, not fixed."""
    assert _extract_entities("Samsung сообщила об убытках.") == []
    assert _extract_entities("Google выпустила обновление.") == []


def test_safety_saul_alone_unchanged_documented_pre_existing_limitation() -> None:
    """Same pre-existing limitation as Samsung/Google above - "Saul" as a bare single word has
    never been extracted, before or after M7.3. Documented explicitly per the authorization's own
    instruction."""
    assert _extract_entities("Saul работал над задачей весь день.") == []


def test_existing_entity_tests_still_pass_multiword_acronym_camelcase() -> None:
    """Exact regression pin of tests/test_fact_safety.py::
    test_extract_claims_entity_catches_multiword_and_acronym_and_camelcase - zero change for
    genuine multi-word entities with no generic prefix."""
    entities = _extract_entities("OpenAI announced a deal with Tesla Inc and NASA yesterday.")
    assert "OpenAI" in entities
    assert "Tesla Inc" in entities
    assert "NASA" in entities


# ---------------------------------------------------------------------------
# Nationality cases - common descriptive nationality adjectives must not break valid proper
# names (tests 13-15)
# ---------------------------------------------------------------------------


def test_nationality_adjective_preserved_for_genuine_official_name() -> None:
    """"Российская Федерация" (Russian Federation) - "Российская" IS part of the genuine official
    name here, not a generic modifier. The word immediately following it ("Федерация") is not a
    recognized generic descriptor, so the adjective is correctly left in place - found and fixed
    via direct testing (the first implementation attempt incorrectly stripped this)."""
    assert _extract_entities("Российская Федерация подписала соглашение.") == ["Российская Федерация"]


def test_nationality_adjective_preserved_for_three_word_official_name() -> None:
    """"Китайская Народная Республика" (People's Republic of China) - all three words are the
    genuine official name; none of "Народная"/"Республика" is a recognized generic descriptor, so
    nothing is stripped."""
    assert _extract_entities("Китайская Народная Республика объявила о реформах.") == [
        "Китайская Народная Республика"
    ]


def test_nationality_adjective_stripped_only_when_followed_by_a_generic_descriptor() -> None:
    """The asymmetric rule directly: "Китайская" is stripped only because the very next word
    ("ИИ-модель") is itself a recognized generic descriptor - contrast with the previous two tests
    where the next word is an ordinary proper-noun component and nothing is stripped."""
    assert _strip_generic_entity_prefix("Китайская ИИ-модель Kimi K3") == "Kimi K3"
    assert _strip_generic_entity_prefix("Российская Федерация") == "Российская Федерация"


# ---------------------------------------------------------------------------
# End-to-end: severity/status effect on the real 847618cd-shaped case (tests 16-17)
# ---------------------------------------------------------------------------


def test_end_to_end_entity_only_finding_disappears_when_prefix_stripped() -> None:
    """Before M7.3: "Автономный ИИ-агент" (unsupported, medium) was the only finding, landing the
    draft at REVIEW/medium. After M7.3: no entity finding at all, so a draft with no other issue
    reaches PASS."""
    ev = FactEvidence(
        source_title="Bottleneck Labs published a report about an AI agent",
        source_content="Bottleneck Labs published a report about an autonomous AI agent named Saul.",
        source_url=None,
    )
    result = evaluate_fact_safety(
        "Автономный ИИ-агент протестировал реальный бизнес",
        "Компания довольна результатом эксперимента.", ev,
    )
    assert result["status"] == "pass"
    assert result["findings"] == []


def test_end_to_end_genuine_fabricated_entity_still_caught() -> None:
    """False-negative safety: a genuine multi-word fabricated entity with NO generic prefix must
    still be caught - the fix must never suppress a real entity-safety finding, only the
    generic-prefix-bundled false positives."""
    ev = FactEvidence(
        source_title="A company raised funding", source_content="A company raised funding today.",
        source_url=None,
    )
    result = evaluate_fact_safety("Kimi K3 привлекла funding", "Компания довольна результатом.", ev)
    finding = next(f for f in result["findings"] if f["type"] == "entity")
    assert finding["support"] == "unsupported"
    assert finding["claim"] == "Kimi K3"
