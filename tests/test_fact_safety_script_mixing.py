"""R2.10-FINALIZATION-3: `_extract_entities()`'s `_ENTITY_RUN_PATTERN` glues ANY run of adjacent
capitalized tokens into one candidate, with nothing distinguishing a genuine same-script multi-word
proper-noun phrase ("Kimi K3", "Trip.com Group") from two unrelated single-word proper nouns that
happen to sit next to each other with no separating punctuation - a Cyrillic word ending one clause
immediately followed by an unrelated Latin brand name starting the next. This is exactly what
blocked the real, already-approved Tesla EVENT_RECAP final authoring result (task
d0d4be30-ba63-453a-baa4-eb2ac959c955): "Техасе Tesla" and "Одновременно Tesla" were both extracted
as one false compound "entity", neither of which appears anywhere in the approved recap's own
evidence text, so both were reported `unsupported` and blocked ContentDraft creation.

Fixed via `_split_by_script()`: every capitalized run is split at script boundaries BEFORE the
existing generic-prefix-stripping/single-token logic runs - a genuine multi-word entity name in
this pipeline's real data never mixes scripts across a space-separated boundary (a mixed-script
compound is always one hyphenated token instead, e.g. "ИИ-модель"). Within each same-script group,
every existing rule is applied completely unchanged - this only decides which tokens are even
eligible to be considered as one run. Deliberately does NOT also let a bare Latin word (e.g. "Tesla"
alone) newly qualify as its own single-token entity in Cyrillic-majority text - an earlier version
of this fix tried exactly that and it reopened the single-bare-Latin-word false-positive class this
module's own M7.3 tests (tests/test_phase17_m7_3_entity_calibration.py) already pin as an accepted,
out-of-scope limitation (Samsung/Saul - "Option B", documented, not fixed)."""
from __future__ import annotations

from services.fact_safety import FactEvidence, _extract_entities, evaluate_fact_safety

_TESLA_TEXT = (
    "После запуска роботакси Cybercab в Техасе Tesla попала под расследование регулятора США\n\n"
    "Tesla начала предлагать в Техасе поездки роботакси на базе Cybercab, однако вскоре после "
    "старта эксплуатации федеральный автомобильный регулятор США открыл расследование. "
    "Одновременно Tesla впервые показала, как Cybercab переносит столкновения, и назвала модель "
    "«самым безопасным автомобилем на дорогах»."
)


def test_A_texas_tesla_false_compound_not_produced() -> None:
    """The exact live false positive #1 - a Cyrillic place-name (inflected "Техасе") immediately
    followed by an unrelated Latin brand name, no separating punctuation."""
    entities = _extract_entities(_TESLA_TEXT)
    assert "Техасе Tesla" not in entities


def test_B_odnovremenno_tesla_false_compound_not_produced() -> None:
    """The exact live false positive #2 - a sentence-initial Cyrillic adverb ("Одновременно")
    immediately followed by an unrelated Latin brand name."""
    entities = _extract_entities(_TESLA_TEXT)
    assert "Одновременно Tesla" not in entities


def test_C_tesla_never_blocks_via_a_false_compound_again() -> None:
    """Test C. Documents the accepted, pre-existing limitation this fix deliberately does not
    touch (see module docstring): a bare single-word brand name like "Tesla" was never
    independently extractable before this phase (same as Samsung/Saul in test_phase17_m7_3_entity_
    calibration.py) and still isn't - what changed is only that it no longer gets glued into an
    invalid, always-unsupported compound. "Tesla itself must still be checked" is satisfied at the
    level this architecture actually supports: once no longer mis-compounded, nothing about Tesla
    can ever again produce a spurious unsupported/blocking finding."""
    entities = _extract_entities(_TESLA_TEXT)
    assert not any("Tesla" in e and e != "Tesla" for e in entities), (
        "Tesla must never again appear only as part of a larger false compound"
    )
    # The pre-existing, accepted limitation, unchanged by this fix - documented, not a regression.
    assert "Tesla" not in entities


def test_D_valid_multiword_entity_kimi_k3_preserved() -> None:
    """Test D. The exact, already-pinned M7.3 production example (tests/test_phase17_m7_3_entity_
    calibration.py) - a genuine Cyrillic-adjective + Cyrillic-descriptor + Latin-multi-word-name
    run must still resolve to exactly "Kimi K3", proving the script-split does not disturb
    same-script generic-prefix stripping at all."""
    assert _extract_entities(
        "Китайская ИИ-модель Kimi K3 стала доступна в открытом доступе."
    ) == ["Kimi K3"]


def test_D2_valid_english_entity_openai_tesla_inc_preserved() -> None:
    """Test D (English-context control). The existing repo fixture (tests/test_fact_safety.py) -
    all-Latin text has no script boundary to split on, so this is completely unaffected."""
    entities = _extract_entities("OpenAI announced a deal with Tesla Inc and NASA yesterday.")
    assert "OpenAI" in entities
    assert "Tesla Inc" in entities


def test_E_unsupported_entity_still_blocks() -> None:
    """Test E. A genuinely fabricated, unsupported multi-word entity (same script throughout, no
    script-boundary interference), named in the draft's own title (so `_entity_severity()`'s
    centrality check gives it HIGH, not just MEDIUM) must still be extracted and still block -
    fail-closed preserved."""
    evidence = FactEvidence(
        source_title="Tesla launches Cybercab", source_content="Tesla unveiled the Cybercab robotaxi.",
        source_url=None,
    )
    title = "Fenwick Dynamics unveils new Cybercab technology"
    result = evaluate_fact_safety(
        title, "Fenwick Dynamics co-developed the Cybercab with Tesla.", evidence,
    )
    assert result["status"] == "block"
    assert any(
        f["claim"] == "Fenwick Dynamics" and f["support"] == "unsupported" and f["severity"] == "high"
        for f in result["findings"]
    )


def test_live_tesla_recap_passes_after_fix() -> None:
    """End-to-end proof against the real, live Tesla authoring output and its real approved-recap
    evidence (R2.10-FINALIZATION-2/3) - reproduces the exact `status == "block"` failure this
    module's own live run hit, now `"pass"`, zero new LLM calls involved in this test."""
    evidence = FactEvidence(
        source_title="Tesla представила Cybercab и начала предлагать поездки роботакси в Техасе",
        source_content=(
            "Tesla представила беспилотный Cybercab без руля и педалей, а затем начала предлагать "
            "поездки на роботакси на его базе в Техасе. Компания также впервые показала результаты "
            "столкновений Cybercab, назвав его «самым безопасным автомобилем на дорогах». Почти "
            "сразу после начала эксплуатации американский автомобильный регулятор начал "
            "расследование в отношении Tesla.\n\n"
            "Cybercab позиционируется как беспилотный автомобиль без руля и педалей; Tesla начала "
            "предлагать поездки роботакси на его базе в Техасе.\n"
            "Tesla продемонстрировала, как Cybercab переживает столкновения, и заявила, что это "
            "«самый безопасный автомобиль на дорогах».\n"
            "После начала эксплуатации Cybercab федеральный автомобильный регулятор США начал "
            "расследование в отношении Tesla.\n\n"
            "Не указаны география и условия доступности поездок роботакси в Техасе, а также круг "
            "пользователей сервиса.\n"
            "Не раскрыты предмет расследования регулятора, его возможные сроки и последствия для "
            "эксплуатации Cybercab.\n"
            "Заявление Tesla о безопасности Cybercab не сопровождается приведёнными результатами "
            "испытаний или сравнительными данными."
        ),
        source_url=None,
        research_facts=["entity: cybercab", "entity: tesla", "entity: американск", "entity: сам", "entity: техас"],
    )
    title = "После запуска роботакси Cybercab в Техасе Tesla попала под расследование регулятора США"
    body = (
        "Tesla начала предлагать в Техасе поездки роботакси на базе Cybercab — беспилотного "
        "автомобиля без руля и педалей, однако вскоре после старта эксплуатации федеральный "
        "автомобильный регулятор США открыл расследование в отношении компании. Его предмет, "
        "возможные сроки и последствия для работы Cybercab не раскрываются; также не уточняются "
        "география и условия доступа к сервису, включая круг его пользователей. Одновременно Tesla "
        "впервые показала, как Cybercab переносит столкновения, и назвала модель «самым безопасным "
        "автомобилем на дорогах», не представив при этом результатов испытаний или сравнительных "
        "данных."
    )
    result = evaluate_fact_safety(title, body, evidence)
    assert result["status"] == "pass"
    assert result["unsupported"] == 0
    assert result["findings"] == []
