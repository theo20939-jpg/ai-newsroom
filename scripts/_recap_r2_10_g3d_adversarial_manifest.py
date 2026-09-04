"""R2.10G3-D - adversarial validation manifest for the deterministic eventness rejector (RULE_A /
RULE_C / RULE_D / RULE_COMBINED, frozen from G3-B - never tuned here, per this phase's own §4/§5).

Every entry below is a REAL Story row in the current dev DB (verified to exist, story_id and
member-event titles read directly - see the manifest's own `subtype`/`rationale` fields, which
quote or closely paraphrase the actual observed member-event titles), NOT overlapping any
story_id already used by G3-A's calibration manifest (scripts/_recap_r2_10_g3_eventness_manifest.py)
or G3-B's holdout (scripts/_recap_r2_10_g3_eventness_holdout.py) - verified by direct set-difference
check (`used_story_ids_overlap_with_prior_sets()` below must return the empty set).

Labels were assigned by direct reading of each Story's real member-event titles/URLs/timestamps
BEFORE any rule (RULE_A/RULE_C/RULE_D/RULE_COMBINED) was run against this file - §12's own explicit
"manual labels first" requirement. Once assigned, a label is never edited after seeing a rule's
verdict; a later correction would be recorded as a new manifest revision and excluded from this
frozen run, never silently changed in place (§12).

`manual_class` is one of the same six labels used throughout G3-A/G3-B/G3-C:
    REAL_SINGLE_EVENT | EVENT_LIFECYCLE | TOPIC_CLUSTER | DIGEST | NOISE | UNCLEAR

`desired_eventness` maps per §13: REAL_SINGLE_EVENT/EVENT_LIFECYCLE -> ACCEPT (positive),
TOPIC_CLUSTER/DIGEST/NOISE -> REJECT (negative), UNCLEAR -> AMBIGUOUS (excluded from binary safety
scoring, exactly like every prior phase's own UNCLEAR treatment).

`subtype` records which of §8's critical positive subtypes (or a negative/ambiguous descriptor) a
fixture represents - used for the class-specific metrics §16 requires (SHORT_MULTI_SOURCE_REAL,
LONG_LIFECYCLE, GITHUB_REAL_EVENT, etc.), and for full transparency about WHY a fixture was chosen,
not merely what class it landed in.

Honest, disclosed gaps (§7's own explicit allowance - "do not fabricate fixtures just to satisfy
counts"):
  CATEGORY_UNDERREPRESENTED=EVENT_LIFECYCLE (2 found against a target of >=8 - genuine multi-stage
    real-world event lifecycles are rare in this dev DB's current snapshot; most real single-fact
    announcements do not develop further within the snapshot window. A real, broad search was
    performed - scripts used to find these are not part of this commit, per this phase's own
    scratchpad-vs-committed-artifact discipline mirroring G3-B's own holdout-search precedent.)
  CATEGORY_UNDERREPRESENTED=DIGEST (3 found against a target of >=5 - genuine digest/roundup-
    template posts are a small minority of this dev DB's real content.)
  CATEGORY_UNDERREPRESENTED=GITHUB_OR_PRIMARY_SOURCE_REAL_NEWS (§8-F, "if available" - none found;
    every github.com-only Story inspected was either PyTorch CI/build-bot noise or a Story-Memory
    false-merge junk case - see `b78594d5`'s own rationale below. Explicitly NOT assumed unfindable
    without looking - a real, targeted search was performed across all 11 github.com-only Stories in
    the current DB.)
  CATEGORY_UNDERREPRESENTED=FRAGMENTED_BUT_REAL_EVENT (0 new - no new Story in this DB shows the
    specific G2 title-case-entity-extraction fragmentation pattern the `nvidia_hf_main` control
    already demonstrates; that control is re-run for continuity instead, per §17.)
  CATEGORY_UNDERREPRESENTED=REPETITIVE_HEADLINE_REAL_EVENT (0 new beyond the existing
    `vk_apple_real_3publisher` shape from G3-A/G3-B, which is out of scope for this phase's NEW set.)
"""
from __future__ import annotations

from dataclasses import dataclass

MANUAL_CLASSES = frozenset({
    "REAL_SINGLE_EVENT", "EVENT_LIFECYCLE", "TOPIC_CLUSTER", "DIGEST", "NOISE", "UNCLEAR",
})
DESIRED_EVENTNESS_VALUES = frozenset({"ACCEPT", "REJECT", "AMBIGUOUS"})

MANIFEST_VERSION = "1"
LABEL_TIMESTAMP = "2026-09-04"


@dataclass(frozen=True)
class AdversarialEntry:
    fixture_id: str
    story_id: str
    title_snapshot: str
    manual_class: str
    desired_eventness: str
    subtype: str
    rationale: str
    manifest_version: str = MANIFEST_VERSION
    label_timestamp: str = LABEL_TIMESTAMP

    def __post_init__(self) -> None:
        assert self.rationale, f"{self.fixture_id}: rationale must not be empty"
        assert self.manual_class in MANUAL_CLASSES, f"{self.fixture_id}: unknown manual_class {self.manual_class!r}"
        assert self.desired_eventness in DESIRED_EVENTNESS_VALUES, f"{self.fixture_id}: unknown desired_eventness {self.desired_eventness!r}"
        if self.manual_class == "UNCLEAR":
            assert self.desired_eventness == "AMBIGUOUS", f"{self.fixture_id}: UNCLEAR must map to AMBIGUOUS"
        if self.manual_class in ("REAL_SINGLE_EVENT", "EVENT_LIFECYCLE"):
            assert self.desired_eventness == "ACCEPT", f"{self.fixture_id}: positive class must map to ACCEPT"
        if self.manual_class in ("TOPIC_CLUSTER", "DIGEST", "NOISE"):
            assert self.desired_eventness == "REJECT", f"{self.fixture_id}: negative class must map to REJECT"


ADVERSARIAL_MANIFEST: tuple[AdversarialEntry, ...] = (
    # ============================================================================================
    # TOPIC_CLUSTER (13) - real Story-Memory generic-word/domain false merges, non-editorial-event
    # ============================================================================================
    AdversarialEntry(
        fixture_id="g3d_hypothesis_testing_cluster", story_id="ceca3930-65ff-4c06-ac3a-f7bcd7f71f47",
        title_snapshot="Modern data science increasingly gives rise to hypothesis-testing problems that are not naturally formulated in terms",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="ADVERSARIAL_RULE_A_TARGET",
        rationale=(
            "7 arXiv preprints merged via the generic sentence-opener 'Modern' - hypothesis testing, "
            "end-to-end driving agents, driving world-simulators, technical debt migration, "
            "score-based generative models, agent-composition systems. Wildly different research "
            "subjects, not one event. span=431.4h, sources=1 (arxiv.org) - exact RULE_A shape."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_robot_policy_cluster", story_id="6d77e752-ff42-481e-a895-9dfe0b682594",
        title_snapshot="Robot policy evaluation and deployment remain fragmented by model-specific software dependencies, data representations,",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="ADVERSARIAL_RULE_A_TARGET",
        rationale=(
            "7 arXiv preprints merged via 'Robot' - policy evaluation, heterogeneous observations, "
            "manipulator motion stacks, co-design, embodiment-specific actions, continual learning, "
            "crowd navigation. span=404.5h, sources=1 - exact RULE_A shape."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_timely_cluster", story_id="20006309-e614-4144-8d7a-d6ceff6b7e32",
        title_snapshot="Timely risk classification is essential in many clinical monitoring settings, where decisions must balance the benefit",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION",
        rationale=(
            "4 arXiv preprints merged via 'Timely' - clinical risk classification, crop-stress "
            "detection, post-disaster building damage assessment. Different domains entirely."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_model_routing_cluster", story_id="c76760aa-8e3d-4e49-a3c2-dca10622bb3d",
        title_snapshot="Model routing aims to select the most suitable model from a candidate pool for each query, balancing quality and cost.",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION",
        rationale="3 arXiv preprints merged via 'Model' - model routing, model cards, model selection under uncertainty. Different subjects, span=350.2h, sources=1.",
    ),
    AdversarialEntry(
        fixture_id="g3d_feature_cluster", story_id="55ad9737-2bd9-4a19-b088-66a547ee60d1",
        title_snapshot="Feature selection is one of the most important and fundamental tasks in data mining, tackled by a family of methods",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION",
        rationale=(
            "Merged via 'Feature': a data-mining feature-selection paper, a model-interpretability "
            "feature-attribution paper, AND an unrelated blog post comparing grep tools "
            "('Feature comparison of ack, ag, git-grep, grep and ripgrep') - the most egregious "
            "false merge in this batch, entirely unrelated domains."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_ml_cluster", story_id="d0cd5936-0b71-46fb-bbda-7f3ccef54494",
        title_snapshot="Machine learning models are widely used in financial fraud and credit-risk detection, yet their adversarial robustness",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION",
        rationale="4 arXiv preprints merged via 'Machine learning' - fraud detection, statistical-individual theory, renormalization, runtime correction. Different subjects.",
    ),
    AdversarialEntry(
        fixture_id="g3d_robots_times_cluster", story_id="45118064-b3e2-42a3-b947-095e0cb18f99",
        title_snapshot="Robots operating in human environments need memories that capture not only what objects exist and where, but also how",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION_MIXED_SOURCE",
        rationale=(
            "5 items merged via 'Robots' - 3 distinct arXiv robotics papers PLUS an unrelated Times "
            "opinion column ('Robots are like children - one day they will make us proud') pulled in "
            "via a Google News wrapper. Shows the generic-word defect pulls in real editorial content "
            "too, not just arXiv. sources=2 (arxiv.org, news.google.com), span=480.9h."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_advanced_multiyear_cluster", story_id="bf0750a4-fce6-410b-adb4-9b29b93cff82",
        title_snapshot="Advanced air mobility operations hold the potential to enhance and expand regional transportation of both people and",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION_EXTREME",
        rationale=(
            "3 items merged via 'Advanced' spanning OVER TWO YEARS (span=20953.8h): a 2024-04-05 "
            "replit.com blog post about port configuration, plus two unrelated Aug-2026 arXiv papers "
            "(air-mobility operations, ground-operations automation). The most extreme false-merge "
            "case found in this dataset - not merely a different subject, a different multi-year era."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_digital_ruble_cluster", story_id="0188ba4d-7a19-47b0-8a28-3aeed8881c9a",
        title_snapshot="«Цифровой камуфляж»: дизайнер создал одежду, которая сбивает с толку системы видеонаблюдения",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION_NON_ARXIV",
        rationale=(
            "4 real (non-arXiv) Russian items merged via the shared word-stem 'Цифров-' (Digital-): "
            "'digital camouflage clothing', 'digital transformation + AI + finance', 'digital "
            "transformation ≠ business growth', 'digital ruble mass rollout'. Four unrelated real "
            "stories, valuable non-academic generalization evidence for the same generic-word defect."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_bridging_cluster", story_id="72903e57-1298-4405-98f3-ad690e9ca97f",
        title_snapshot="Bridging the weather and climate divide with artificial intelligence - Nature",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION_MIXED_SOURCE",
        rationale=(
            "Merged via 'Bridging': a real Nature journalism piece on weather/climate AI, plus an "
            "unrelated arXiv robotics-control paper (appearing twice). span=323.0h, sources=2."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_navigating_cluster", story_id="f3291f4f-ded1-4992-a1e6-20856b79a2a5",
        title_snapshot="Navigating large, photorealistic 3D apartments from raw pixels is widely considered infeasible for plain reinforcement",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION_MIXED_SOURCE",
        rationale=(
            "Merged via 'Navigating': an arXiv RL/navigation paper plus an unrelated NBC Boston "
            "education-and-AI news piece (appearing twice). span=101.0h, sources=2."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_ai_kills_support_cluster", story_id="400bf9ef-b0de-4500-8b75-1a4aa7abf411",
        title_snapshot="ИИ убивает службу поддержки — даже несмотря на зелёные метрики - Хабр",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION_NON_ARXIV",
        rationale=(
            "3 genuinely different real Habr articles merged (likely a feed-level ingestion "
            "artifact): 'AI kills customer support', '[Translation] 6 AI agents in a coding contest "
            "decided to kill each other', '[Translation] AI used to verify the hardest math proof "
            "to date'. Three unrelated real stories, span=98.8h, sources=2."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_instead_of_cluster", story_id="2b301d88-cab2-485e-a760-e4f8f91188b9",
        title_snapshot="Вместо того чтобы пытаться найти работу, которую не заменит искусственный интеллект, сосредоточьтесь на улучшении своих",
        manual_class="TOPIC_CLUSTER", desired_eventness="REJECT", subtype="TOPIC_COLLECTION_NON_ARXIV",
        rationale=(
            "Merged via 'Вместо' (Instead): 2 near-duplicate career-advice pieces plus one entirely "
            "unrelated item ('Instead of monetization - party approval', a business/political story). "
            "span=189.7h, sources=2."
        ),
    ),

    # ============================================================================================
    # REAL_SINGLE_EVENT (16) - genuine single real-world events, several deliberately thin/adversarial
    # ============================================================================================
    AdversarialEntry(
        fixture_id="g3d_amd_cisco_saudi", story_id="e742fdae-d21f-47e9-99b6-db1f6df53fac",
        title_snapshot="AMD и Cisco запустили ИИ-инфраструктуру в Саудовской Аравии — следующий этап рассчитан на 250 МВт",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="THIN_BUT_REAL_EVENT",
        rationale="1 real direct source (ixbt.com) + 1 same-article Google-News wrapper, identical timestamp. A real corporate AI-infrastructure launch, thinly sourced.",
    ),
    AdversarialEntry(
        fixture_id="g3d_aws_agent_registry", story_id="c91750d0-d276-4e89-b379-49a882b3615c",
        title_snapshot="Manage agents, tools and skills at scale with AWS Agent Registry",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="THIN_BUT_REAL_EVENT",
        rationale="1 real direct source (aws.amazon.com official blog) + Google-News wrapper of the same post. A real product-feature announcement, single-source.",
    ),
    AdversarialEntry(
        fixture_id="g3d_openai_softbank_stargate", story_id="5197be25-8618-4916-9b7a-df424218ea9d",
        title_snapshot="OpenAI, SoftBank и Oracle вложат до $500 млрд в ИИ-инфраструктуру США: Project Stargate рассчитан на 4 года",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="THIN_BUT_REAL_EVENT",
        rationale=(
            "A major real financial/industry announcement ($500B AI infrastructure commitment) "
            "represented by only 1 real direct source (ixbt.com) + its own Google-News wrapper - "
            "importance of the underlying fact does not correlate with source count in this corpus."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_apple_sept9_event", story_id="3711dbec-71a6-4ae6-8b02-0c94524be7d3",
        title_snapshot="Apple officially announces iPhone 18 Pro and foldable iPhone event: 'Surprise and shine'",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale="9to5mac.com and techmeme.com, ~6 minutes apart, both real independent outlets reporting Apple's real event announcement.",
    ),
    AdversarialEntry(
        fixture_id="g3d_dolly_parton_died", story_id="71aa1b51-358e-4fb2-8d40-c33a9b48d405",
        title_snapshot="Dolly Parton has died",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale="theguardian.com and en.wikipedia.org, ~41 minutes apart - a major real-world news event, unconventional but genuine 2-source corroboration.",
    ),
    AdversarialEntry(
        fixture_id="g3d_tplink_wifi8", story_id="9daeec0f-1bc7-4044-ac39-9bd27d7ad247",
        title_snapshot="TP-Link announces its first consumer Wi-Fi 8 routers — Archer 8 Ultra preorder commences September 30, in select regions",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale="tomshardware.com (EN) and 3dnews.ru (RU translation/coverage), ~2.75h apart - genuine cross-language corroboration of one real product announcement.",
    ),
    AdversarialEntry(
        fixture_id="g3d_microsoft_copilot_merge", story_id="93f6f608-f3a9-44fd-884c-c008da1660bb",
        title_snapshot="Microsoft is merging Copilot and Copilot 365 into one unified app - and retiring 3 features",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale="zdnet.com and techmeme.com, ~13 minutes apart - real independent corroboration of a real product-strategy announcement.",
    ),
    AdversarialEntry(
        fixture_id="g3d_ai_doom_custom_cpu", story_id="d889bfe5-1ede-4d18-a711-54c00075fa60",
        title_snapshot="AI coder gets Doom running on a custom CPU designed by GPT-5.6 Sol — game viewport is overlaid on a pulsing schematic",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="THIN_BUT_REAL_EVENT",
        rationale="1 real direct source (tomshardware.com) + its own Google-News wrapper, identical timestamp. A real, if quirky, tech-curiosity single event.",
    ),
    AdversarialEntry(
        fixture_id="g3d_plaud_earbuds", story_id="a65ae9de-1b44-46df-8811-190a8bc69a0c",
        title_snapshot="Plaud's first AI earbuds have arrived - what they can do",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale="zdnet.com and 9to5google.com, ~1.75h apart - genuine independent corroboration of a real product launch.",
    ),
    AdversarialEntry(
        fixture_id="g3d_samsung_s26fe", story_id="9e4d6378-c12a-4732-bfe7-5d3a7b27a1d2",
        title_snapshot="The Samsung Galaxy S26 FE looks like a perfectly cromulent budget flagship",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale="engadget.com and a Samsung-newsroom item via Google News wrapper, ~25 minutes apart - real product coverage.",
    ),
    AdversarialEntry(
        fixture_id="g3d_openai_bans_russian_accounts", story_id="227327ed-cc24-44a7-9bef-9c96f342bd84",
        title_snapshot="OpenAI bans Russian ChatGPT accounts posing as a fake Israeli think tank — used VPNs to push pro-Kremlin narratives and",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="THIN_BUT_REAL_EVENT",
        rationale="1 real direct source (tomshardware.com) + its own Google-News wrapper, identical timestamp. A real, notable platform-policy/security enforcement action.",
    ),
    AdversarialEntry(
        fixture_id="g3d_pixel11_fold_embargo", story_id="5db99dd0-52b5-417f-bac8-ce261ceb8609",
        title_snapshot="This is the $1,900 Google Pixel 11 Pro Fold",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale=(
            "CRITICAL RULE_D ADVERSARIAL TARGET (§9). 3 real, independent outlets (engadget.com, "
            "zdnet.com, 3dnews.ru) publish their OWN distinct hands-on articles ('Stagnating instead "
            "of innovating' / '3 key reasons to buy it over Samsung' / a straightforward RU spec "
            "writeup) at the exact same review-embargo-lift moment (span=0.0h). This is a real, "
            "extremely common tech-journalism pattern (coordinated embargo lift), not syndication - "
            "each outlet wrote substantively different editorial content about one real product. "
            "Deterministic features (measured, not assumed): effective_event_count=3, "
            "announcement_count=3 (titles differ enough that cluster_announcements() does not merge "
            "them), unique_source_count=3, story_span_hours=0.0 - this is EXACTLY RULE_D's trigger "
            "shape (span<=1h AND sources>=3 AND announcement_count==effective_event_count)."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_memory_crisis_wrapper_dup", story_id="90841fb8-5475-4078-b37d-afd9803b3298",
        title_snapshot="Кризис памяти ударит по его инициаторам: память съест две трети капзатрат на ИИ-инфраструктуру",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="THIN_BUT_REAL_EVENT",
        rationale=(
            "1 real direct source (3dnews.ru) plus the SAME Google-News wrapper article ingested "
            "twice (identical title/timestamp, a duplicate-ingestion artifact, not 2 real "
            "corroborating outlets). A real memory-market analysis story, effectively single-sourced "
            "despite event_count=3 - useful evidence-scarcity example for §22."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_arc_agi_blog_dup", story_id="d8d2e3f3-ecb9-4cb3-8cc3-881e508d91e3",
        title_snapshot="44% on ARC-AGI-1 in 67 cents",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="THIN_BUT_REAL_EVENT",
        rationale=(
            "A real, notable technical blog post (an efficient ARC-AGI-1 benchmark result) hosted on "
            "mvakde.github.io, re-ingested twice (same URL/title, 7.4h apart - a re-scrape artifact, "
            "not 2 sources). NOTE: domain is 'mvakde.github.io' (GitHub Pages), NOT 'github.com' "
            "itself - RULE_C's exact-domain-match ('github.com') does not fire on this fixture; a "
            "genuine boundary case worth recording for §11's own domain-precision concern."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_honor_robot_phone", story_id="0529e06f-bd46-4b07-8b99-abff087749ca",
        title_snapshot="Honor официально представила Robot Phone — смартфон с подвижной камерой-«компаньоном»",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale=(
            "4 real independent outlets (9to5google.com, engadget.com, t.me, vc.ru), each with "
            "genuinely different wording, span=5.5h - real simultaneous multi-outlet coverage of one "
            "real product launch, not duplicate syndication of one headline."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_yandexpay_appstore_removed", story_id="fbb4f251-f45d-4b94-8f8a-b0060dbe3db1",
        title_snapshot="Приложение «Яндекс Пэй» удалили из App Store",
        manual_class="REAL_SINGLE_EVENT", desired_eventness="ACCEPT", subtype="THIN_BUT_REAL_EVENT",
        rationale="t.me + vc.ru (same publisher's own channel and site), span=6.0h - a real single fact (app removal), self-syndicated across one publisher's own properties.",
    ),

    # ============================================================================================
    # EVENT_LIFECYCLE (2) - CATEGORY_UNDERREPRESENTED, disclosed (target >=8)
    # ============================================================================================
    AdversarialEntry(
        fixture_id="g3d_flock_surveillance_lifecycle", story_id="e44e588d-ad27-4f88-9da7-adb2e065c2be",
        title_snapshot="Flock boss admits surveillance firm took too long to act over police abuse",
        manual_class="EVENT_LIFECYCLE", desired_eventness="ACCEPT", subtype="SHORT_MULTI_SOURCE_REAL_EVENT",
        rationale=(
            "3 real, independent major outlets (bbc.co.uk, engadget.com, technologyreview.com), "
            "span=4.4h, each reporting a GENUINELY DIFFERENT angle of one fast-developing real "
            "controversy: the company admitting fault, then tightening its rules in response, then a "
            "separate piece on making cameras harder to misuse. Real development, not corroboration "
            "of one static fact - a compact but genuine EVENT_LIFECYCLE."
        ),
    ),
    AdversarialEntry(
        fixture_id="g3d_whatsapp_feature_lifecycle", story_id="d18ab9fb-f45f-4aa1-8403-ba9c11768711",
        title_snapshot="WhatsApp starts rolling out username support when creating new contacts",
        manual_class="EVENT_LIFECYCLE", desired_eventness="ACCEPT", subtype="LONG_RUNNING_EVENT_LIFECYCLE",
        rationale=(
            "Two GENUINELY DIFFERENT real WhatsApp feature announcements 13 days apart (username "
            "support on Aug 12; three account-security features on Aug 25), the second corroborated "
            "by a same-day RU translation (ixbt.com, Aug 26). span=321.3h, sources=2 - a real "
            "long-running product-feature lifecycle, not repeated coverage of one fact."
        ),
    ),

    # ============================================================================================
    # DIGEST (3) - CATEGORY_UNDERREPRESENTED, disclosed (target >=5)
    # ============================================================================================
    AdversarialEntry(
        fixture_id="g3d_ai_digest_3", story_id="24bb8db3-ba1e-4f60-b017-9c6691cd2776",
        title_snapshot="AI-дайджест #3",
        manual_class="DIGEST", desired_eventness="REJECT", subtype="DIGEST",
        rationale="An explicit, numbered recurring digest post ('AI-дайджест #3') on habr.com - template roundup format, not a single event.",
    ),
    AdversarialEntry(
        fixture_id="g3d_selectel_product_roundup", story_id="0cd2b9f0-a68e-42cd-b44d-324d7edfe237",
        title_snapshot="Новые модели в ИИ-роутере, GPU-хост с 4хH200 NVLink и другие новости продуктов Selectel",
        manual_class="DIGEST", desired_eventness="REJECT", subtype="DIGEST",
        rationale="Title itself is explicit multi-topic: 'new models in the AI router, a 4xH200 GPU host, AND OTHER Selectel product news' - a company product-roundup post, not one event.",
    ),
    AdversarialEntry(
        fixture_id="g3d_ml_digest_deepseek", story_id="d58c2d4b-c390-4fd0-b2dd-b6fe712dfef1",
        title_snapshot="Токены больше не дешевеют? DeepSeek подняла цены на 355%, а память съедает 90% кремния в ускорителе: ML-дайджест",
        manual_class="DIGEST", desired_eventness="REJECT", subtype="DIGEST",
        rationale="Explicitly labelled 'ML-дайджест' (ML digest), covering two unrelated facts (DeepSeek pricing AND accelerator memory/silicon economics) in one roundup post.",
    ),

    # ============================================================================================
    # NOISE (7)
    # ============================================================================================
    AdversarialEntry(
        fixture_id="g3d_pytorch_ci_1", story_id="c50a838f-495a-4d81-a82a-a3065e980218",
        title_snapshot="trunk/797f28597661a371a2f0b2d242e7d8f917c4acd3: Port 3 distributed/_shard tests to Intel GPU. (#189337)",
        manual_class="NOISE", desired_eventness="REJECT", subtype="ADVERSARIAL_RULE_C_TARGET",
        rationale="3 PyTorch GitHub CI/build-bot release-tag notices (trunk + viable/strict + a revert), all github.com - automated, non-editorial content, same pattern as ciflow_ci_noise/holdout_pytorch_trunk_noise.",
    ),
    AdversarialEntry(
        fixture_id="g3d_pytorch_ci_2", story_id="9cceae17-c67b-471f-919b-69e242ad0b0f",
        title_snapshot="viable/strict/1787844352: [3/N][Test] Enable `torch_ao_sparsity.py` for XPU (#191202)",
        manual_class="NOISE", desired_eventness="REJECT", subtype="ADVERSARIAL_RULE_C_TARGET",
        rationale="2 PyTorch CI tag notices, all github.com - automated build/test content.",
    ),
    AdversarialEntry(
        fixture_id="g3d_pytorch_ci_3", story_id="91d3af11-fbfb-4ef6-a9ed-a399233d4fec",
        title_snapshot="trunk/0a3b42d96e5bdb8fa909efdc3154d002616be25d: Add IPC support for XPUEvent (#191182)",
        manual_class="NOISE", desired_eventness="REJECT", subtype="ADVERSARIAL_RULE_C_TARGET",
        rationale="2 PyTorch CI tag notices, all github.com - automated build/test content.",
    ),
    AdversarialEntry(
        fixture_id="g3d_pytorch_ci_rocm", story_id="85c71772-0756-4ae1-a9e3-5cece02a7af1",
        title_snapshot="ciflow/trunk/191557: [Inductor][ROCm] Bound OpInfo numerical parity by dtype",
        manual_class="NOISE", desired_eventness="REJECT", subtype="ADVERSARIAL_RULE_C_TARGET",
        rationale="2 PyTorch CI tag notices (ROCm variant), all github.com - automated build/test content.",
    ),
    AdversarialEntry(
        fixture_id="g3d_motley_fool_etf", story_id="ee09b2d2-f8c3-4563-8bf4-53dbdd8cdf22",
        title_snapshot="1 No-Brainer Artificial Intelligence (AI) ETF to Buy With $50 and Hold for the Long Term",
        manual_class="NOISE", desired_eventness="REJECT", subtype="TEMPLATE_FINANCIAL_CLICKBAIT",
        rationale="4 near-duplicate syndicated republications (Yahoo Finance, Globe and Mail x2, Motley Fool) of one templated stock-advice column - not real single-event news, evergreen financial clickbait.",
    ),
    AdversarialEntry(
        fixture_id="g3d_motley_fool_stocks", story_id="32d800aa-29f9-4c46-8bab-3194089bdf7e",
        title_snapshot="3 Top Artificial Intelligence (AI) Stocks to Buy Before 2027 Arrives",
        manual_class="NOISE", desired_eventness="REJECT", subtype="TEMPLATE_FINANCIAL_CLICKBAIT",
        rationale="4 near-duplicate syndicated republications of one templated stock-advice column - same pattern as g3d_motley_fool_etf.",
    ),
    AdversarialEntry(
        fixture_id="g3d_version_tag_false_merge", story_id="b78594d5-768a-40d6-8b4d-d731eb6186c1",
        title_snapshot="v0.33.0",
        manual_class="NOISE", desired_eventness="REJECT", subtype="ADVERSARIAL_RULE_A_AND_C_TARGET",
        rationale=(
            "A NEW noise pattern, distinct from CI-bot noise: two COMPLETELY DIFFERENT GitHub "
            "projects (Comfy-Org/ComfyUI and ollama/ollama) whose release tags happen to coincide at "
            "'v0.33.0' were merged into one Story purely by matching version-tag string - not a real "
            "single event, both from github.com (RULE_C shape) and span=274.7h with sources=1 (also "
            "brushes RULE_A's shape, though sources=1/announcements=1 falls short of RULE_A's "
            "announcement_count>=4 floor). A bare release tag carries no article content at all. "
            "REJECT is the correct answer here (it is not one real event) - included to show RULE_C "
            "correctly catches this different failure mode too, not as a RULE_C counterexample."
        ),
    ),

    # ============================================================================================
    # UNCLEAR (5)
    # ============================================================================================
    AdversarialEntry(
        fixture_id="g3d_vlm_perestruct_dup", story_id="c0b8e74a-40a0-41da-813d-a05ede362f76",
        title_snapshot="Где VLM не читали старых газет: разбираем PereStruct, открытый датасет и модульный парсер",
        manual_class="UNCLEAR", desired_eventness="AMBIGUOUS", subtype="UNCLEAR_MARKETING_OR_NEWS",
        rationale="A single Yandex company-blog post about an open dataset/parser tool, ingested twice (same URL). Genuinely unclear whether a vendor technical explainer counts as reportable single-event news or is closer to marketing/documentation content.",
    ),
    AdversarialEntry(
        fixture_id="g3d_xiaomi_cyberone_teaser", story_id="9be7028b-10dd-4012-82d4-6930ebc5b57c",
        title_snapshot="Xiaomi покажет всему миру робота CyberOne и сотни других устройств. Экосистема превысила более 1,1 млрд устройств",
        manual_class="UNCLEAR", desired_eventness="AMBIGUOUS", subtype="UNCLEAR_FUTURE_TENSE_TEASER",
        rationale="A single Google-News-wrapped item, future-tense ('will show the world...') - genuinely unclear whether this describes a confirmed real event or a vague forward-looking marketing teaser; no second source to disambiguate.",
    ),
    AdversarialEntry(
        fixture_id="g3d_strategic_deception_single_paper", story_id="cf68664e-ec37-48d8-b1f4-9287da5bb1a6",
        title_snapshot="Strategic deception by LLM and VLM agents has emerged as a central AI alignment and safety concern. Social-deduction",
        manual_class="UNCLEAR", desired_eventness="AMBIGUOUS", subtype="UNCLEAR_SINGLE_PAPER",
        rationale="A single arXiv preprint (event_count=1, not a cluster). Genuinely unclear whether one unpublicized research paper should count as REAL_SINGLE_EVENT editorial content or is simply not newsworthy on its own.",
    ),
    AdversarialEntry(
        fixture_id="g3d_gpu_world_vague", story_id="e6bb16f5-3ac9-43d0-a873-e056ef89e03d",
        title_snapshot="GPU World",
        manual_class="UNCLEAR", desired_eventness="AMBIGUOUS", subtype="UNCLEAR_VAGUE_TITLE",
        rationale="A vague, generic title (gpuworld.org) with no clear event content visible from the title/URL alone - genuinely unclear what real-world fact, if any, this represents.",
    ),
    AdversarialEntry(
        fixture_id="g3d_six_ai_services_listicle", story_id="c9f67724-2459-4089-8bda-01a6031370b1",
        title_snapshot="6 AI-сервисов, которыми сейчас можно пользоваться бесплатно или почти бесплатно",
        manual_class="UNCLEAR", desired_eventness="AMBIGUOUS", subtype="UNCLEAR_LISTICLE",
        rationale="A '6 free AI tools' listicle (habr.com, duplicate-ingested). Genuinely unclear whether evergreen listicle content should count as reportable news or is closer to non-editorial noise - not confidently one or the other.",
    ),
)


def used_story_ids() -> set[str]:
    return {e.story_id for e in ADVERSARIAL_MANIFEST}


def used_story_ids_overlap_with_prior_sets() -> set[str]:
    """Pure sanity check - must return the empty set. Exposed for the test suite."""
    from scripts._recap_r2_10_g3_eventness_holdout import HOLDOUT
    from scripts._recap_r2_10_g3_eventness_manifest import MANIFEST

    prior_ids = {e.story_id for e in MANIFEST if e.story_id} | {h.story_id for h in HOLDOUT}
    return used_story_ids() & prior_ids
