"""R2.10G3-A - manual editorial ground-truth manifest for the shadow eventness evaluation harness.

Versioned, reviewable, hand-written - NOT derived from current RECAP readiness (docs/
r2_10_g3_eventness_evaluation_report.md's own §7 explicit instruction: "current readiness is not
ground truth"). Every entry's `manual_class` and `desired_eventness` were assigned by direct human
(operator) reading of the real titles during RECAP R2.10F/R2.11 forensic work - this file only
formalizes and versions those existing decisions, plus a handful of new "for balance" entries
explicitly marked with lower confidence (see `confidence` field).

Two fixture kinds:
  - "db": a real Story row, looked up by `story_id` at evaluation time. May not exist in every
    developer database (per this phase's own explicit instruction) - the harness must skip, not
    fail, a missing db fixture.
  - "offline": a fully self-contained fixture (real production titles, R2.11's own exact fixtures)
    built as in-memory NewsEvent objects - never depends on any particular DB's contents. Used for
    the VK/Apple and Marvell/Google real-title cases and the VK synthetic 4-publisher negative
    control, none of which are known to exist as Story rows in this database (checked directly -
    see docs/r2_10_g3_eventness_evaluation_report.md §0).

`manual_class` is one of the six labels already established by RECAP R2.10F - never a new taxonomy:
    REAL_SINGLE_EVENT | EVENT_LIFECYCLE | TOPIC_CLUSTER | DIGEST | NOISE | UNCLEAR

`desired_eventness` is one of: ACCEPT | REJECT | NEEDS_REVIEW | UNCERTAIN - UNCERTAIN is reserved
for UNCLEAR-class fixtures where prior research (R2.11's own explicit Marvell finding) deliberately
left the question open; do not silently strengthen it to ACCEPT/REJECT here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

MANUAL_CLASSES = frozenset({
    "REAL_SINGLE_EVENT", "EVENT_LIFECYCLE", "TOPIC_CLUSTER", "DIGEST", "NOISE", "UNCLEAR",
})
DESIRED_EVENTNESS_VALUES = frozenset({"ACCEPT", "REJECT", "NEEDS_REVIEW", "UNCERTAIN"})


@dataclass(frozen=True)
class OfflineEvent:
    title: str
    url: str
    hours_ago: float


@dataclass(frozen=True)
class ManifestEntry:
    fixture_id: str
    kind: str  # "db" | "offline"
    manual_class: str
    desired_eventness: str
    source_phase: str
    confidence: str  # "high" (individually forensically verified) | "provisional" (title-read only)
    story_id: str | None = None  # required when kind == "db"
    title_snapshot: str | None = None  # required when kind == "db" - the title observed at labeling time
    offline_events: tuple[OfflineEvent, ...] = field(default_factory=tuple)  # required when kind == "offline"
    rationale: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        assert self.rationale, f"{self.fixture_id}: rationale must not be empty"
        assert self.manual_class in MANUAL_CLASSES, f"{self.fixture_id}: unknown manual_class {self.manual_class!r}"
        assert self.desired_eventness in DESIRED_EVENTNESS_VALUES, f"{self.fixture_id}: unknown desired_eventness {self.desired_eventness!r}"
        assert self.kind in ("db", "offline"), f"{self.fixture_id}: unknown kind {self.kind!r}"
        if self.kind == "db":
            assert self.story_id, f"{self.fixture_id}: kind=db requires story_id"
            assert self.title_snapshot, f"{self.fixture_id}: kind=db requires title_snapshot"
        else:
            assert self.offline_events, f"{self.fixture_id}: kind=offline requires offline_events"
        if self.manual_class == "UNCLEAR":
            assert self.desired_eventness == "UNCERTAIN", f"{self.fixture_id}: UNCLEAR class must map to UNCERTAIN, not {self.desired_eventness!r}"


_NOW_OFFLINE = datetime(2026, 8, 21, 18, 0, 0, tzinfo=timezone.utc)


def _offline(*rows: tuple[str, str, float]) -> tuple[OfflineEvent, ...]:
    return tuple(OfflineEvent(title=t, url=u, hours_ago=h) for t, u, h in rows)


MANIFEST: tuple[ManifestEntry, ...] = (
    # --- Mandatory forensic fixtures (RECAP R2.10F, individually verified) -------------------
    ManifestEntry(
        fixture_id="vla", kind="db", story_id="ed667801-1452-4ee7-b083-bf13d05c5a22",
        title_snapshot="Vision-Language-Action (VLA) models can connect scene understanding, semantic reasoning, and trajectory generation",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="high",
        source_phase="R2.10F", rationale=(
            "19 distinct arXiv preprints about the VLA research topic, spanning ~20 days - a real, "
            "specific technical term correctly shared, but not one real-world event."
        ),
    ),
    ManifestEntry(
        fixture_id="vlm", kind="db", story_id="78cde6c9-6810-4b24-ae31-e0c34e0fb030",
        title_snapshot="Vision-language models (VLMs) achieve strong performance on video and image-sequence",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="high",
        source_phase="R2.10F", rationale="Same pattern as VLA, smaller scale (6 events).",
    ),
    ManifestEntry(
        fixture_id="utro_digest", kind="db", story_id="d093e4be-e6b5-40cd-b2be-6665d24d7a1c",
        title_snapshot="Утро среды:",
        manual_class="DIGEST", desired_eventness="REJECT", confidence="high",
        source_phase="R2.10F", rationale=(
            "4 different daily digest posts ('Утро среды'/'четверга'/'понедельника'/'вторника', 2 "
            "weeks apart) merged into one Story purely via the generic word 'утро' (fixed for "
            "future matching by G1, but this historical Story itself is untouched)."
        ),
    ),
    ManifestEntry(
        fixture_id="nvidia_hf_main", kind="db", story_id="42e4188a-3aa3-4aa0-a717-6a02eb0a2730",
        title_snapshot="Nvidia closes in on Hugging Face acquisition",
        manual_class="EVENT_LIFECYCLE", desired_eventness="ACCEPT", confidence="high",
        source_phase="R2.10F", rationale=(
            "A real, genuine acquisition event - independently confirmed fragmented across 4 Story "
            "rows by a title-case entity-extraction defect (G2, unresolved). Must not be punished "
            "into looking like noise merely because it is incomplete - the eventness question is "
            "'is this a real event', not 'is coverage complete in THIS row'."
        ),
    ),
    ManifestEntry(
        fixture_id="nvidia_mediatek", kind="db", story_id="c91404e0-c4cd-4521-8d85-9891ff97bc04",
        title_snapshot="Nvidia и MediaTek объединяют усилия: подписано многолетнее соглашение",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", confidence="high", source_phase="R2.10F",
        rationale="A real partnership announcement, clean entities, coherent coverage.",
    ),
    ManifestEntry(
        fixture_id="south_korea_policy", kind="db", story_id="28bfcd91-fddf-49fe-a5ae-669e8ce4e61b",
        title_snapshot="Правительство Южной Кореи запланировало предоставить всем гражданам",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", confidence="high", source_phase="R2.10F",
        rationale="A real government policy announcement.",
    ),
    ManifestEntry(
        fixture_id="ai_challenge_10k", kind="db", story_id="7d285c0d-3374-4ea9-9750-5b34ac79da17",
        title_snapshot="Более 10 тысяч школьников и студентов уже присоединились к конкурсу AI",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", confidence="high", source_phase="R2.10F",
        rationale="A real milestone announcement for a specific, named competition.",
    ),
    ManifestEntry(
        fixture_id="ciflow_ci_noise", kind="db", story_id="00a77347-cc36-461b-9b94-ce7459bca7eb",
        title_snapshot="ciflow/inductor/191791: Update",
        manual_class="NOISE", desired_eventness="REJECT", confidence="high", source_phase="R2.10F",
        rationale=(
            "PyTorch GitHub CI bot commit messages, not editorial content at all - passes Story "
            "Integrity's own coherence bar despite being non-news, a real disclosed gap."
        ),
    ),

    # --- R2.11 fixtures (real production titles / a synthetic negative control - none found to
    # exist as Story rows in this database; represented as offline, in-memory fixtures instead,
    # exactly mirroring feature/r2-11-announcement-identity's own test construction) -------------
    ManifestEntry(
        fixture_id="vk_apple_real_3publisher", kind="offline",
        offline_events=_offline(
            ("VK подала в суд на Apple и потребовала вернуть свои приложения в App Store", "https://ixbt.com/a", 0.47),
            ("VK подала иск против Apple в российский суд из-за удаления её приложений из App Store", "https://vc.ru/b", 0.32),
            ("VK решила засудить Apple за удаление приложений из App Store", "https://3dnews.ru/c", 0.0),
        ),
        manual_class="REAL_SINGLE_EVENT", desired_eventness="NEEDS_REVIEW", confidence="high", source_phase="R2.11",
        rationale=(
            "A real, single lawsuit-filing event, corroborated by 3 independent outlets within "
            "~30 minutes - genuinely REAL_SINGLE_EVENT, but R2.11 never rendered a final "
            "eventness verdict for this exact shape (it characterized it as report-level "
            "corroboration, not development) - marked NEEDS_REVIEW rather than silently "
            "strengthened to ACCEPT, per this phase's own explicit instruction not to invent a "
            "stronger label than prior research supported."
        ),
    ),
    ManifestEntry(
        fixture_id="vk_apple_synthetic_4publisher_false_ready", kind="offline",
        offline_events=_offline(
            ("VK sues Apple over removed App Store apps", "https://a.com/1", 3.33),
            ("VK files lawsuit against Apple seeking apps return", "https://b.com/2", 3.17),
            ("VK takes Apple to court over App Store removals", "https://c.com/3", 3.0),
            ("VK demands Apple restore its apps in Russian lawsuit", "https://d.com/4", 2.83),
        ),
        manual_class="REAL_SINGLE_EVENT", desired_eventness="REJECT", confidence="high", source_phase="R2.11",
        rationale=(
            "MANDATORY NEGATIVE CONTROL. Synthetic 4-publisher extension of the VK/Apple shape - "
            "R2.11's own proof that this exact pattern (sources=4, announcements=4, Integrity "
            "PASS) already reaches natural READY under current production readiness, despite zero "
            "real development beyond the single filing event. desired_eventness=REJECT because "
            "pure syndication volume must not be read as lifecycle depth."
        ),
    ),
    ManifestEntry(
        fixture_id="marvell_google", kind="offline",
        offline_events=_offline(
            ("Marvell and Google expand their chip development deal, with Marvell granting Google a warrant to buy up to 58M+ shares", "https://a.com/1", 3),
            ("Marvell pops 6% on AI chip deal that lets Google buy up to $12.2 billion in shares - CNBC", "https://cnbc.com/2", 2),
            ("Marvell будет разрабатывать чипы для Google и позволит ей купить собственных акций на сумму $12,2 млрд", "https://ria.ru/3", 1),
        ),
        manual_class="UNCLEAR", desired_eventness="UNCERTAIN", confidence="high", source_phase="R2.11",
        rationale=(
            "R2.11's own explicit, deliberate non-decision: 2-3 real distinguishing facts about "
            "one deal (warrant-share-count, valuation, now correctly co-identified across "
            "languages since G3-0's decimal-comma fix) - genuinely ambiguous between 'one deal, "
            "richer corroborated detail' and 'readiness-worthy development'. Not strengthened here."
        ),
    ),

    # --- Additional real Stories for balance (title-read classification only - NOT individually
    # forensically re-verified with the same depth as the mandatory fixtures above; confidence
    # marked "provisional" throughout) ----------------------------------------------------------
    ManifestEntry(
        fixture_id="galgadot_interview", kind="db", story_id="8c09ec4f-4100-4465-91b1-bb72a30582fb",
        title_snapshot="Галь Гадот об ИИ в кино: интерес и страхи актрисы",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", confidence="high", source_phase="R2.10F",
        rationale="A real celebrity-interview event, clean entities, 2 events within 1.4h.",
    ),
    ManifestEntry(
        fixture_id="divided_america_wire", kind="db", story_id="e9d58cbf-2736-40ff-a17a-ff774649c3c2",
        title_snapshot="In a divided America, the left and right unite to oppose artificial intelligence",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", confidence="high", source_phase="R2.10F",
        rationale=(
            "A real single wire story, but collected 34 times (a Google News RSS duplicate-"
            "ingestion pathology, out of RECAP's own scope) - useful as a stress fixture for "
            "features that naively trust event_count."
        ),
    ),
    ManifestEntry(
        fixture_id="bill_gates_en", kind="db", story_id="4db2690a-bbd5-475b-8513-4f24737dd6ac",
        title_snapshot="Bill Gates says tech executives are privately \"very worried\" about AI disruption",
        manual_class="EVENT_LIFECYCLE", desired_eventness="ACCEPT", confidence="provisional", source_phase="R2.10F",
        rationale="16 events, 11 announcements - a real statement story with likely genuine follow-on coverage; not individually re-verified event-by-event this phase.",
    ),
    ManifestEntry(
        fixture_id="bill_gates_ru", kind="db", story_id="f85f7df0-91cc-4e48-a0e1-2571477b6c84",
        title_snapshot="Билл Гейтс предупредил о рисках стремительного развития искусственного интеллекта",
        manual_class="EVENT_LIFECYCLE", desired_eventness="ACCEPT", confidence="provisional", source_phase="R2.10F",
        rationale=(
            "The Russian-language fragment of bill_gates_en - same real event, permanently "
            "unmergeable with the EN Story (cross-script entity mismatch, a disclosed, separate, "
            "out-of-scope limitation, not the G2 title-case defect)."
        ),
    ),
    ManifestEntry(
        fixture_id="new_york_times_digest", kind="db", story_id="77ba3255-7458-4270-ab09-10a8bd95e404",
        title_snapshot="⚡ **Новости к этому часу**",
        manual_class="DIGEST", desired_eventness="REJECT", confidence="high", source_phase="R2.10F",
        rationale="Two DIFFERENT digest sources ('Новости к этому часу' and 'Новости - Incrussia') plus one unrelated item merged via the generic word 'новост'.",
    ),
    ManifestEntry(
        fixture_id="optimizatsiya_koda", kind="db", story_id="c6e26cda-ca9e-4050-99ad-45bb69f1de29",
        title_snapshot="**Оптимизация кода под космос",
        manual_class="UNCLEAR", desired_eventness="UNCERTAIN", confidence="provisional", source_phase="R2.10F",
        rationale="Only 2 events, not individually deep-dived in R2.10F - left UNCLEAR rather than guessed.",
    ),
    ManifestEntry(
        fixture_id="recent_convex_opt_cluster", kind="db", story_id="1d0c7de0-c7c0-4d5f-b7a2-a6d70e777a66",
        title_snapshot="Recent work has shown that, for smooth convex optimization, plain gradient descent",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="high", source_phase="R2.10F",
        rationale="16 unrelated arXiv papers (optimization, TinyML, motion planning, driving, VLA, video editing...) merged via the generic word 'Recent' (fixed by G1 for future matching).",
    ),
    ManifestEntry(
        fixture_id="llm_agents_cluster", kind="db", story_id="3fc9824d-3735-453f-ada5-f45079e629f7",
        title_snapshot="LLM-based agents can interact with external environments",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10F",
        rationale="One of the 9 R2.10E/R2.10F P1 stories; not individually deep-dived - a generic-word ('llm-based') arXiv-style anchor, same failure class as the other clusters here.",
    ),
    ManifestEntry(
        fixture_id="robotic_welding_cluster", kind="db", story_id="811dc7a3-f8d2-474d-a9f0-e6276304979b",
        title_snapshot="Robotic welding is widely used in industrial manufacturing",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10F",
        rationale="Same P1 population as llm_agents_cluster - generic-word ('robotic') arXiv-style anchor, not individually deep-dived.",
    ),
    ManifestEntry(
        fixture_id="multimodal_medical_cluster", kind="db", story_id="bb501f86-0a19-4870-9b96-4192b47afce2",
        title_snapshot="Multimodal medical prediction often faces incomplete pairing",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10F",
        rationale="Same P1 population as llm_agents_cluster - generic-word ('multimodal') arXiv-style anchor, not individually deep-dived.",
    ),
    ManifestEntry(
        fixture_id="accurate_dialogue_cluster", kind="db", story_id="bb7c2272-ff94-4561-bd22-54a5d5b64cb0",
        title_snapshot="Accurate and responsive turn-taking is essential for spoken dialogue",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="high", source_phase="R2.10F",
        rationale="The single most damning G1 fixture: dialogue systems + radiotherapy + agriculture, unified only by the word 'Accurate'.",
    ),
    ManifestEntry(
        fixture_id="many_ml_systems_cluster", kind="db", story_id="e21ba039-2e7b-48b0-aa1a-456079291940",
        title_snapshot="Many machine-learning systems set a threshold at a quantile",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10F",
        rationale="Same P1 population as llm_agents_cluster - generic-word ('many') arXiv-style anchor, not individually deep-dived.",
    ),
    ManifestEntry(
        fixture_id="ai_journey_contest", kind="db", story_id="b5eec7d8-8a2d-476a-bfb3-98b125459505",
        title_snapshot="Участники AI Journey Contest 2026 поборются",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", confidence="provisional", source_phase="R2.10G3-A",
        rationale="A real, named competition announcement - added for class balance, title-read only.",
    ),
    ManifestEntry(
        fixture_id="twitch_genai_optout", kind="db", story_id="eb0fa8fb-1bfd-4e6d-93e8-4e23d3030d60",
        title_snapshot="Twitch streamers can now refuse to let Amazon train its genAI models on their content",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", confidence="provisional", source_phase="R2.10G3-A",
        rationale="A real platform-policy announcement - added for class balance, title-read only.",
    ),
    ManifestEntry(
        fixture_id="den_1631_digest", kind="db", story_id="8f9bc326-0b3a-469d-8fd9-2196601e13d8",
        title_snapshot="День 1631: доля вложений",
        manual_class="DIGEST", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10G3-A",
        rationale="Numbered recurring daily-digest post format ('День N:'), same template-title pattern as the 'Утро X' fixture - added for class balance.",
    ),
    ManifestEntry(
        fixture_id="financial_news_llm_cluster", kind="db", story_id="6e58d6af-e688-45d1-8bd6-5250af34d446",
        title_snapshot="Large language models can extract richer signals from financial news",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10G3-A",
        rationale="22-event arXiv-style research-topic cluster - added for class balance.",
    ),
    ManifestEntry(
        fixture_id="camera_motion_cluster", kind="db", story_id="ce1c8589-6980-4518-a577-5d2882572f28",
        title_snapshot="Understanding camera motion is fundamental to video perception",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10G3-A",
        rationale="13-event arXiv-style research-topic cluster, generic-word ('understanding') anchor - added for class balance, title-read only.",
    ),
    ManifestEntry(
        fixture_id="2d_deep_learning_cluster", kind="db", story_id="f07b12df-0353-497c-9069-b4cca16b07d2",
        title_snapshot="Deep learning systems perform mainly within the 2D",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10G3-A",
        rationale="11-event arXiv-style research-topic cluster - added for class balance, title-read only.",
    ),
    ManifestEntry(
        fixture_id="object_detection_cluster", kind="db", story_id="4380df56-b809-4050-9389-ff6ed4c55c24",
        title_snapshot="Object detection knowledge is fragmented across independently trained",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", confidence="provisional", source_phase="R2.10G3-A",
        rationale="5-event arXiv-style research-topic cluster - added for class balance, title-read only.",
    ),
    ManifestEntry(
        fixture_id="us_futures_wire_noise", kind="db", story_id="4052df9b-f677-4d96-bca1-dc39c719d86c",
        title_snapshot="US futures mostly higher as the artificial intelligence business booms",
        manual_class="NOISE", desired_eventness="REJECT", confidence="high", source_phase="R2.10F",
        rationale="Identical-title wire boilerplate re-served/re-indexed many times by a Google News aggregator - not real developing coverage.",
    ),
)
