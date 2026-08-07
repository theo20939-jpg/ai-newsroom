# Phase 19 M6 — Real/Human-Review Calibration Packet

Status: **ready for human review — every `human_decision`/`human_notes` field below is
intentionally blank.** Nothing in this document was filled in automatically. Machine predictions
only; no ground truth exists for these items until a human fills them in.

**80 stratified real-event items** (Part 1) + **20 cross-category
candidate groups** (Part 2), drawn from a real, read-only replay of
**9450 real `NewsEvent` rows**
(`scripts/_phase19_m6_real_data_replay.py`, generated 2026-08-07) through the real
`services.story_memory.match_story()` against a disposable database - the real ai_newsroom
database was never written to. Selection was a deterministic random sample (seed `19.6`,
reproducible via `scripts/_phase19_m6_build_calibration_packet.py`).

This packet does **not** by itself establish real-world precision/recall - see
`docs/phase19_m6_story_memory_calibration_report.md` for why (blank human labels cannot yet be
compared against anything) and for the separately-computed synthetic-fixture metrics
(`scripts/_phase19_m6_synthetic_fixtures.py`), which use designed, not blank, ground truth.

## How to use this packet

**Part 1** — for each item, record:

- **human_decision** — one of `correct_match` / `incorrect_match` / `missed_match` / `unsure`
- **human_notes** — free text: why, what evidence would change your mind

**Part 2** — for each group, record whether it is genuinely one real-world story split across
topic_buckets (`same_story`), genuinely unrelated (`different_stories`), or `unsure`.

---

## Part 1 — stratified sample by system outcome

### SEMANTIC_DUPLICATE (system says: near-identical rehash) — 15 items

### 1. ciflow/inductor/190637: [XPU] Skip CUDA stream event codegen in AOTI cpp_wrapper for XPU

- **real_event_id**: `25fab37c-c570-4cb1-8c0e-e0d97c5f571a`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-08-02T19:45:11.828055+00:00
- **system outcome**: `semantic_duplicate` (confidence 0.97)
- **system reasoning**: near-identical title (title_overlap=0.92) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "ciflow/trunk/190637: [XPU] Skip CUDA stream event codegen in AOTI cpp_wrapper for XPU" (`d8c6e330-91b0-4bbd-95fe-cba9b7071893`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 2. Beyond Moore’s Law: The Full Stack Driving AI in 2026 - ETF Database

- **real_event_id**: `c6412816-918d-43b2-8f71-fb92e311cdf3`
- **category**: AI
- **topic_bucket**: legal_regulatory
- **collected_at**: 2026-07-30T14:33:44.324806+00:00
- **system outcome**: `semantic_duplicate` (confidence 0.72)
- **system reasoning**: near-identical title (title_overlap=0.90) - same event, likely a different source's coverage (entity_overlap=0.60, topic_bucket=legal_regulatory match)
- **matched story: "Beyond Moore’s Law: The Full Stack Driving AI in 2026 - ETF Trends" (`d7ee07f1-7fb0-492e-852a-feeaa0a21d56`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 3. Recent advances in reward modeling show a paradigm shift from discriminative reward models to generative reward models.

- **real_event_id**: `d1654903-8a74-4044-966e-a8c603db5b5b`
- **category**: AI
- **topic_bucket**: product
- **collected_at**: 2026-08-07T10:08:51.204037+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=product match)
- **matched story: "Recent advances in reward modeling show a paradigm shift from discriminative reward models to generative reward models." (`ab84ae82-a0d1-493a-a7c0-b70c94da88a7`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 4. Many dexterous manipulation tasks require the object to remain securely held throughout the interaction. From the

- **real_event_id**: `c075086d-70d2-46a8-8bc4-4a0805177a0f`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-31T01:56:31.351140+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "Many dexterous manipulation tasks require the object to remain securely held throughout the interaction. From the" (`063a6f83-9a22-4c07-82b3-4199c6aa237c`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 5. «Ученый-пионер» покинет ИИ-лабораторию Google. В ней также сменится руководитель - Oninvest

- **real_event_id**: `7dbb0442-bcd7-472c-9f13-0561638f87a6`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-05T17:33:36.534712+00:00
- **system outcome**: `semantic_duplicate` (confidence 0.96)
- **system reasoning**: near-identical title (title_overlap=0.89) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "«Ученый-пионер» покинет ИИ-лабораторию Google. В ней сменится руководитель - Oninvest" (`f85fe2af-6fb4-4775-81f3-3c39f0d50a1a`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 6. Chemistry literature synthesis often requires assembling specific findings scattered across many publications, yet

- **real_event_id**: `c39eb09b-2378-4193-985a-81eca43e9403`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-31T11:08:12.638857+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "Chemistry literature synthesis often requires assembling specific findings scattered across many publications, yet" (`86e10e67-ce54-433d-9f4e-a630ed3cdafe`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 7. Microsoft скоро позволит пользователям отключить аппаратную клавишу Copilot в Windows 11 - Хабр

- **real_event_id**: `989123e3-293b-4448-9920-db31ba7ce114`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-25T13:19:35.299408+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "Microsoft скоро позволит пользователям отключить аппаратную клавишу Copilot в Windows 11 - Хабр" (`4005da83-8126-44fe-956c-66bbc2cc8bf7`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 8. UNESCO Peru to Promote Dialogues on Artificial Intelligence and - UNESCO

- **real_event_id**: `a072c614-0235-4254-8b74-f9e18267c755`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-28T10:51:54.720423+00:00
- **system outcome**: `semantic_duplicate` (confidence 0.70)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=0.50, topic_bucket=other match)
- **matched story: "UNESCO Peru to Promote Dialogues on Artificial Intelligence and Indigenous Language Revitalization at the 2026 Lima" (`8937433c-6a01-470f-9fb3-3084fd50d5a2`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 9. Представлен открытый проект whatbroke для сравнения поведения ИИ-агента между двумя запусками - Хабр

- **real_event_id**: `1da0f77f-b08a-464e-a103-256b14a3beee`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-25T20:19:03.970442+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "Представлен открытый проект whatbroke для сравнения поведения ИИ-агента между двумя запусками - Хабр" (`d54b5e16-aa73-4f74-b308-f492ac88bbbe`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 10. Multimodal large language models (MLLMs) hold immense potential to revolutionize clinical practice, yet deploying them

- **real_event_id**: `a59afa73-81e9-4ad7-a610-3b764189bb1a`
- **category**: AI
- **topic_bucket**: product
- **collected_at**: 2026-07-28T10:52:00.895692+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=product match)
- **matched story: "Multimodal large language models (MLLMs) hold immense potential to revolutionize clinical practice, yet deploying them" (`e6a7c524-18b0-4732-b698-634b58996800`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 11. Chemistry literature synthesis often requires assembling specific findings scattered across many publications, yet

- **real_event_id**: `e93551c9-3b94-4d26-a68a-db092d761ced`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-31T11:08:12.031853+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "Chemistry literature synthesis often requires assembling specific findings scattered across many publications, yet" (`86e10e67-ce54-433d-9f4e-a630ed3cdafe`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 12. AI safety questions grow after testing incident raises concerns about system controls - wach.com

- **real_event_id**: `da4e51dd-b73a-4bb0-96c1-edaa017ce936`
- **category**: AI
- **topic_bucket**: financial
- **collected_at**: 2026-08-05T23:57:16.430941+00:00
- **system outcome**: `semantic_duplicate` (confidence 0.97)
- **system reasoning**: near-identical title (title_overlap=0.92) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=financial match)
- **matched story: "AI safety questions grow after testing incident raises concerns about system controls - kmph.com" (`f8c44ac9-40d9-4b37-b3ea-9538fe46a765`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 13. Nvidia vs. Planet Labs: Comparing Revenue Trends Between an Artificial Intelligence Giant and a Rising Star of the

- **real_event_id**: `7d267d24-84bc-4f81-906b-01f818c63bcd`
- **category**: AI
- **topic_bucket**: financial
- **collected_at**: 2026-07-25T21:25:47.261150+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=financial match)
- **matched story: "Nvidia vs. Planet Labs: Comparing Revenue Trends Between an Artificial Intelligence Giant and a Rising Star of the" (`7fc41716-7100-4c87-86b8-7a8cfb8274f2`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 14. Inspirery Interviews Dr. Linda Pajoel on Artificial Intelligence, Entrepreneurship and the Mission Behind Diembassy -

- **real_event_id**: `a91e12a5-2726-4c0c-9320-e0d6cd0e2f1c`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-29T12:31:28.553765+00:00
- **system outcome**: `semantic_duplicate` (confidence 1.00)
- **system reasoning**: near-identical title (title_overlap=1.00) - same event, likely a different source's coverage (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "Inspirery Interviews Dr. Linda Pajoel on Artificial Intelligence, Entrepreneurship and the Mission Behind Diembassy -" (`d89907d1-6c86-4e3d-8557-2d34533271cf`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 15. Meta Artificial Intelligence Is the Latest AI Technology to Hack Another Company During Testing - AOL.com

- **real_event_id**: `ed700f59-5200-4d74-8ff8-facc376eb33a`
- **category**: AI
- **topic_bucket**: security_incident
- **collected_at**: 2026-08-07T10:08:46.304432+00:00
- **system outcome**: `semantic_duplicate` (confidence 0.73)
- **system reasoning**: near-identical title (title_overlap=0.92) - same event, likely a different source's coverage (entity_overlap=0.60, topic_bucket=security_incident match)
- **matched story: "Meta Artificial Intelligence Is the Latest AI Technology to Hack Another Company During Testing - People.com" (`62d39d48-3619-4c6f-83eb-194b4ebd34f9`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### STORY_UPDATE (system says: confident match, new substance) — 15 items

### 16. Brain-Machine Interfaces (BMIs) provide a direct communication pathway between the brain and external devices, enabling

- **real_event_id**: `e9677dd9-3d0e-4d70-8af7-af541b23bb3a`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-28T10:52:03.301103+00:00
- **system outcome**: `story_update` (confidence 0.80)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.50, topic_bucket=other match)
- **matched story: "Brain-Machine Interfaces (BMIs), which link the brain to external devices, hold great potential in rehabilitation," (`f2688d62-1224-4681-85cf-54d0e7b1c149`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 17. Anthropic says its own AI models breached three companies during security tests

- **real_event_id**: `37ea874e-570a-454c-b427-72632c7b20c1`
- **category**: STARTUPS
- **topic_bucket**: security_incident
- **collected_at**: 2026-07-31T01:22:02.243893+00:00
- **system outcome**: `story_update` (confidence 0.82)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.55, topic_bucket=security_incident match)
- **matched story: "Anthropic says AI models hacked three firms during tests" (`9fd26ebf-a9a1-4176-a4d3-831b5f614404`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 18. Apple TV’s fall lineup reveals every new show and movie coming soon

- **real_event_id**: `091ffa85-d21f-42b0-8575-94d2469cda6d`
- **category**: GADGETS
- **topic_bucket**: other
- **collected_at**: 2026-08-06T18:58:47.302504+00:00
- **system outcome**: `story_update` (confidence 0.67)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.17, topic_bucket=other match)
- **matched story: "Apple TV’s surprise hit series is making the jump to theaters for one night only" (`540fbf48-7912-4a5f-8983-89d274557a0e`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 19. Final Fantasy 7 remake director says he hopes Revelation will get 'some kind of physical edition' despite the industry

- **real_event_id**: `cc36bc28-8a93-4299-920f-9d99f99eb5d0`
- **category**: HARDWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-30T11:34:44.762693+00:00
- **system outcome**: `story_update` (confidence 0.70)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.25, topic_bucket=other match)
- **matched story: "Final Fantasy 7 Revelation boss has been thinking about ways to make a mysterious boss suitable for the upcoming" (`6e83ed8b-97ff-4f5b-a98f-ea7121588d74`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 20. Как выстроить работу с выделенной командой

- **real_event_id**: `e5c3f840-fd27-4d8b-975c-6273210616d0`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-28T13:35:13.968909+00:00
- **system outcome**: `story_update` (confidence 0.68)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.20, topic_bucket=other match)
- **matched story: "Как модели упаковывают концепты в многообразия: смотрим на теорию, рушим идеальный мир и ищем кружочки" (`799b76be-8059-44ea-ad12-0c7c102aa14a`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 21. Large language models (LLMs) can generate fluent and convincing text at scale, creating growing risks for

- **real_event_id**: `dd806bfd-24d0-4158-849c-38e8dc74061d`
- **category**: AI
- **topic_bucket**: product
- **collected_at**: 2026-08-07T10:08:50.458106+00:00
- **system outcome**: `story_update` (confidence 0.71)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.27, topic_bucket=product match)
- **matched story: "Large language models (LLMs) increasingly support complex professional tasks, yet their capabilities in rule-intensive" (`3861bf7f-4d63-4e1e-8d54-1fe842b7f8a9`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 22. trunk/8cb8d533afc61ecbfc6cd2ffe8086a05b197399d: [Test] Refactor test/test_out_dtype_op.py (#185802)

- **real_event_id**: `1cc4045d-2482-4d6d-b297-3fb631c0cb6f`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-25T07:38:01.394643+00:00
- **system outcome**: `story_update` (confidence 0.80)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.50, topic_bucket=other match)
- **matched story: "trunk/9214bab82ff483d1795d45a33670a474d255d832: [Test] Refactor test/test_nn.py to be device-agnostic [6/N] (#189535)" (`da0e3b92-402b-4b06-808f-ba4801c4a16f`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 23. trunk/8d3008087ab8509a0eea67b7887672a9424b8ddc: Update third_party/kineto submodule to 6f446fe (#191526)

- **real_event_id**: `603748ed-00b6-4a76-99de-8852db735ed0`
- **category**: SOFTWARE
- **topic_bucket**: product
- **collected_at**: 2026-07-30T08:01:28.287221+00:00
- **system outcome**: `story_update` (confidence 0.65)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.12, topic_bucket=product match)
- **matched story: "ciflow/torchtitan/186100: Update" (`46fac1d3-7171-49ca-9c3a-6b7d12b835da`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 24. Vision-Language-Action (VLA) models have shown strong potential for general robot manipulation, but most existing

- **real_event_id**: `6783eb05-7d6b-46c7-a8f7-0cfc53c4d54d`
- **category**: AI
- **topic_bucket**: product
- **collected_at**: 2026-07-29T10:46:11.101126+00:00
- **system outcome**: `story_update` (confidence 0.69)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.21, topic_bucket=product match)
- **matched story: "Vision-language-action (VLA) models predict sequential actions to execute tasks specified by language instructions," (`2e05f796-b609-4432-b93e-918ebcf64673`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 25. Vision-Language-Action (VLA) models have become the dominant recipe for generalist manipulation, yet they are almost

- **real_event_id**: `58eadc3e-cf83-4a8c-b980-03e46fb2617e`
- **category**: AI
- **topic_bucket**: product
- **collected_at**: 2026-08-07T10:08:52.616711+00:00
- **system outcome**: `story_update` (confidence 0.68)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.20, topic_bucket=product match)
- **matched story: "Vision-language-action (VLA) models often treat main-view and wrist-view observations as parallel visual inputs," (`0a5ae973-3b36-476d-aa86-1108cf1b923e`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 26. ciflow/trunk/187870: Update

- **real_event_id**: `a11fd230-3796-4de5-b978-fb46c7996bdd`
- **category**: SOFTWARE
- **topic_bucket**: product
- **collected_at**: 2026-08-07T01:00:37.572356+00:00
- **system outcome**: `story_update` (confidence 0.70)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.25, topic_bucket=product match)
- **matched story: "viable/strict/1785967941: Update torch-xpu-ops commit pin (#192199)" (`00cb0d07-37dc-4406-9584-6498e9d81b47`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 27. X-ray computed tomography (CT) reconstructs volumetric representations of objects from projection images obtained by

- **real_event_id**: `fda99ee2-c52a-42cf-a5c8-fd376cb2bab3`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-06T01:39:44.925661+00:00
- **system outcome**: `story_update` (confidence 0.78)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.45, topic_bucket=other match)
- **matched story: "X-ray computed tomography (CT) suffers from severe metal artifacts when high-attenuation objects such as dental" (`faf3bd2b-ccf1-4408-9c89-e6ad4b487c1b`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 28. The development and testing of advanced aerial robots require experiments in controlled environments with tailored

- **real_event_id**: `7a96ccb8-4fcc-48ef-8b1d-fc3c4789f688`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-05T11:22:35.767085+00:00
- **system outcome**: `story_update` (confidence 0.66)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.15, topic_bucket=other match)
- **matched story: "The proliferation of low-altitude intelligent agents is increasing the demand for timely and socially responsible" (`52e49be1-75fe-4342-877a-e833822475cc`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 29. ciflow/trunk/191357: Update

- **real_event_id**: `4335df22-bcb0-433e-beed-638f3e293560`
- **category**: SOFTWARE
- **topic_bucket**: product
- **collected_at**: 2026-07-30T00:07:30.070350+00:00
- **system outcome**: `story_update` (confidence 0.80)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.50, topic_bucket=product match)
- **matched story: "ciflow/torchtitan/186100: Update" (`46fac1d3-7171-49ca-9c3a-6b7d12b835da`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 30. ciflow/torchtitan/181781: Update

- **real_event_id**: `12e52614-7125-42d5-a7c0-47f9ea89e67a`
- **category**: SOFTWARE
- **topic_bucket**: product
- **collected_at**: 2026-08-07T00:26:50.053822+00:00
- **system outcome**: `story_update` (confidence 0.70)
- **system reasoning**: confident match, materially different title (entity_overlap=1.00, title_overlap=0.25, topic_bucket=product match)
- **matched story: "viable/strict/1785967941: Update torch-xpu-ops commit pin (#192199)" (`00cb0d07-37dc-4406-9584-6498e9d81b47`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### SUPPORTING_SOURCE (system says: confident match, corroborating) — 15 items

### 31. Deploying Kimi K3 on AWS - aws.amazon.com

- **real_event_id**: `d3d1ecb1-dae0-40b2-b5a3-7f5d055cee79`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-30T19:08:50.901393+00:00
- **system outcome**: `supporting_source` (confidence 0.84)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.60) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "Deploying Kimi K3 on AWS" (`3f92a603-1d0a-4626-91cf-97de4536a579`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 32. Лаборатория нейронаук Сбера: как изменилось отношение россиян к ИИ за шесть лет - Независимая газета

- **real_event_id**: `06093ca3-a9c9-4c9d-8f37-044b11e01ffc`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-24T22:18:17.459616+00:00
- **system outcome**: `supporting_source` (confidence 0.65)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.73) - likely a corroborating source, not new substance (entity_overlap=0.60, topic_bucket=other match)
- **matched story: "Лаборатория нейронаук Сбера изучила, как за 6 лет изменилось отношение россиян к ИИ - Rostovgazeta.ru" (`fe37d8dd-efc2-485e-9b5f-d53fa46854c6`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 33. viable/strict/1785323240: Also include manual AOTI shims in our linter (#191266)

- **real_event_id**: `8344dda4-e07a-4baa-8aa6-65d9f5b88c19`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-29T11:22:33.208055+00:00
- **system outcome**: `supporting_source` (confidence 0.89)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.73) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "trunk/65ccd81bfef17f8f4a6a18835325732d65cdca25: Also include manual AOTI shims in our linter (#191266)" (`3e246ffb-7a52-4ec9-86cc-3f86325be14e`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 34. Here Are My 3 Top Artificial Intelligence (AI) Stocks to Buy in August - The Motley Fool

- **real_event_id**: `b5bdd188-fe1c-4597-a065-57a165b7adb8`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-02T19:47:41.891375+00:00
- **system outcome**: `supporting_source` (confidence 0.74)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.73) - likely a corroborating source, not new substance (entity_overlap=0.75, topic_bucket=other match)
- **matched story: "Here Are My 3 Top Artificial Intelligence (AI) Stocks to Buy in August - AOL.com" (`d18f230b-d139-4a1d-914d-f6ab6297e5fb`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 35. viable/strict/1784969858: Speed up CPU quantile/nanquantile with partial selection (#188394)

- **real_event_id**: `dacf88f3-6576-4c70-911f-cb1bdc24eb8e`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-25T09:22:21.478410+00:00
- **system outcome**: `supporting_source` (confidence 0.89)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.73) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "trunk/545b05f5cc448065f725ad8e1e01df5aab3b9c06: Speed up CPU quantile/nanquantile with partial selection (#188394)" (`e3bd55d6-d030-4cac-82b0-a2149f2983aa`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 36. Beast of Reincarnation review

- **real_event_id**: `cec60315-b65a-407e-952a-15fb098fb89d`
- **category**: HARDWARE
- **topic_bucket**: other
- **collected_at**: 2026-08-05T11:20:31.255320+00:00
- **system outcome**: `supporting_source` (confidence 0.67)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.67) - likely a corroborating source, not new substance (entity_overlap=0.67, topic_bucket=other match)
- **matched story: "If you hate parrying, projectiles in Beast of Reincarnation are ridiculously overpowered if you focus on leveling them" (`7fe74ab2-ae49-4eb8-95d9-9a846370547e`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 37. viable/strict/1784931044: [distributed] Return NON_GROUP_MEMBER from split_group (#190725)

- **real_event_id**: `b778347d-b856-4725-8101-bd6e72c72434`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-24T22:16:25.848934+00:00
- **system outcome**: `supporting_source` (confidence 0.87)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.67) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "trunk/2713bfd3da4af8e1998af7ef1cfd6d91c426bebd: [distributed] Return NON_GROUP_MEMBER from split_group (#190725)" (`9af381cc-3c68-4b9e-ad3d-d96b42a9191e`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 38. viable/strict/1785478925: Always reset Dynamo if it was imported (#184568)

- **real_event_id**: `d23eb878-f24a-43f9-ba47-2fff4892b4d9`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-31T11:05:46.312751+00:00
- **system outcome**: `supporting_source` (confidence 0.87)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.67) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "trunk/f613b2a0a05cebc8f0b0095458f6f2219008b0dd: Always reset Dynamo if it was imported (#184568)" (`ae01a8ab-0114-4b2b-9d59-db75db230a25`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 39. viable/strict/1785451480: [dynamo, 3.15] Fix pygen_yf (#190312)

- **real_event_id**: `fa0416a6-afcf-48f7-90b6-53252ed58f6c`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-30T23:08:37.772126+00:00
- **system outcome**: `supporting_source` (confidence 0.83)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.57) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "trunk/786b0e553cb7a9c926690f087a4220cef544ed4b: [dynamo, 3.15] Fix pygen_yf (#190312)" (`19125054-fd6d-4ca4-be9a-12efb75e439b`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 40. LinkedIn actually adds a ‘seems like AI slop’ button

- **real_event_id**: `3d812863-6fa6-4891-8902-5fd1d7ea3672`
- **category**: GADGETS
- **topic_bucket**: other
- **collected_at**: 2026-07-30T19:06:17.931239+00:00
- **system outcome**: `supporting_source` (confidence 0.83)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.57) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "LinkedIn is testing a 'seems like AI slop' reporting tool" (`efdd7ed6-e79e-4427-9e12-c9e0672376d1`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 41. viable/strict/1784959561: Fix PP composability skip decorator ordering (#191039)

- **real_event_id**: `561c8472-0794-49f6-b470-f7d870383f5e`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-25T07:38:01.394643+00:00
- **system outcome**: `supporting_source` (confidence 0.87)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.67) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "trunk/82bc638aed026de85a280054159821abef3b1d39: Fix PP composability skip decorator ordering (#191039)" (`bb99b0fd-6a62-42af-9b73-9f35e3c3871e`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 42. How one kidney care company built a solid AI foundation - Healthcare IT News

- **real_event_id**: `306aab20-a0f8-46fa-a35c-925e72870370`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-30T19:08:50.901393+00:00
- **system outcome**: `supporting_source` (confidence 0.88)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.70) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "How one nephrology practice built a solid AI foundation - Healthcare IT News" (`6dccb9c1-71df-4517-aecd-034b541d9de1`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 43. viable/strict/1784976449: [Test] Refactor test/test_nn.py to be device-agnostic [6/N] (#189535)

- **real_event_id**: `38854c85-18e1-4c99-9f7a-726405f30bda`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-25T11:01:55.446214+00:00
- **system outcome**: `supporting_source` (confidence 0.85)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.62) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=other match)
- **matched story: "trunk/9214bab82ff483d1795d45a33670a474d255d832: [Test] Refactor test/test_nn.py to be device-agnostic [6/N] (#189535)" (`da0e3b92-402b-4b06-808f-ba4801c4a16f`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 44. WhatsApp launches three new features to upgrade group chats

- **real_event_id**: `3d42853e-a814-4caa-bfda-e8c4e43f5513`
- **category**: GADGETS
- **topic_bucket**: product
- **collected_at**: 2026-08-05T11:20:03.696479+00:00
- **system outcome**: `supporting_source` (confidence 0.85)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.62) - likely a corroborating source, not new substance (entity_overlap=1.00, topic_bucket=product match)
- **matched story: "WhatsApp updates group chats with new features including ‘@all’ tag" (`e647503b-053e-4304-8bcd-18c092b9fb6a`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 45. My 3 Favorite Artificial Intelligence (AI) Stocks to Buy Right Now - The Motley Fool

- **real_event_id**: `7dfab0d9-5ba9-4885-a576-1464221d4c06`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-28T10:51:54.720423+00:00
- **system outcome**: `supporting_source` (confidence 0.71)
- **system reasoning**: confident match, substantially similar but not identical title (title_overlap=0.70) - likely a corroborating source, not new substance (entity_overlap=0.71, topic_bucket=other match)
- **matched story: "My 3 Favorite Artificial Intelligence (AI) Stocks to Buy Right Now - Yahoo Finance" (`861b757e-1d27-4f66-b292-51d4e5f6901c`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### UNCERTAIN_MATCH (system says: borderline, not confident either way) — 15 items

### 46. СК предложил отнести использование ИИ и VPN к отягчающим обстоятельствам при преступлениях - Frank Media

- **real_event_id**: `fac9bd18-7fdb-41c8-bfd1-e276b7aa3d4c`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-28T13:45:01.498899+00:00
- **system outcome**: `uncertain_match` (confidence 0.40)
- **system reasoning**: borderline score 0.40 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.33, title_overlap=0.50)
- **matched story: "Глава СК предложил считать использование ИИ, VPN и прокси отягчающим обстоятельством при совершении преступлений - Хабр" (`98b6624e-4cd3-466c-a2ae-d0d19e5d2e8c`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 47. What Is Open-Weights A.I.? - The New York Times

- **real_event_id**: `d338ffdd-2d95-4915-bd5a-0487b1f072d3`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-29T10:10:13.676842+00:00
- **system outcome**: `uncertain_match` (confidence 0.42)
- **system reasoning**: borderline score 0.42 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.25, title_overlap=0.67)
- **matched story: "Mark Zuckerberg Blasts Centralization of A.I. Power - The New York Times" (`40215da7-ec3b-485f-bd44-f933776aed49`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 48. We study asynchronous optimization for finite-sum eigenspace computation in heterogeneous distributed systems. The

- **real_event_id**: `a98f05fa-46cc-415c-8662-9b3118abe177`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-06T02:49:00.844681+00:00
- **system outcome**: `uncertain_match` (confidence 0.37)
- **system reasoning**: borderline score 0.37 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.50, title_overlap=0.18)
- **matched story: "The abundance of casually captured monocular videos and images on social media provides a valuable source for immersive" (`5213aab5-7bd2-4cec-b4ab-2e52822849bc`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 49. Phase 14 M6 live validation event - synthetic, not real news, created 2026-07-23T17:37:52.414246+00:00, see docs/phase14_m6_live_validation_plan.md

- **real_event_id**: `03c98f8b-4c1f-4ced-9a00-9134fbd606cd`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-23T17:37:52.342038+00:00
- **system outcome**: `uncertain_match` (confidence 0.43)
- **system reasoning**: borderline score 0.43 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.20, title_overlap=0.79)
- **matched story: "Phase 13 M7 live validation event - synthetic, not real news, created 2026-07-23T16:20:08.467363+00:00, see docs/phase13_m7_authorization_check.md" (`10990979-ac4c-477c-9e15-5c60cc2ad1ef`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 50. As Multimodal Large Language Models (MLLMs) are increasingly deployed in decision-critical pipelines such as robotics,

- **real_event_id**: `f2fbebb2-10bd-4363-ae90-c7080140c7ff`
- **category**: AI
- **topic_bucket**: product
- **collected_at**: 2026-07-30T08:06:45.517461+00:00
- **system outcome**: `uncertain_match` (confidence 0.37)
- **system reasoning**: borderline score 0.37 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.33, title_overlap=0.42)
- **matched story: "Multimodal Large Language Models (MLLMs) rely on a projector to align visual representations with the language" (`92ae3ba2-50dc-4636-abfc-af1c7ebd5144`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 51. In partially observable reinforcement learning, agents face a dual bottleneck: they must explore to encounter rewarding

- **real_event_id**: `39ebd6fb-2b32-419f-8260-fa3ecd9f3a05`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-06T03:56:32.006993+00:00
- **system outcome**: `uncertain_match` (confidence 0.60)
- **system reasoning**: borderline score 0.60 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=1.00, title_overlap=0.00)
- **matched story: "In 3D reconstruction, camera calibration is an essential element for achieving high fidelity and accuracy of the" (`de757274-152a-44da-82df-bca688957b14`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 52. We present a novel approach to regression tasks using classification which is motivated by the mechanism used by

- **real_event_id**: `3412373d-3a60-466d-a467-fa273a7a0371`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-30T08:06:44.892003+00:00
- **system outcome**: `uncertain_match` (confidence 0.60)
- **system reasoning**: borderline score 0.60 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=1.00, title_overlap=0.00)
- **matched story: "We propose amortized moment matching, utilizing neural networks to learn data moments as distributional training" (`9d2fba77-92a9-45dd-a45a-74e97e0bb943`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 53. Large Language Models (LLMs) are transforming database interaction paradigms, evolving from simple query translators to

- **real_event_id**: `6ff7110e-e402-4b72-a3eb-904dd71eb0ef`
- **category**: AI
- **topic_bucket**: product
- **collected_at**: 2026-08-05T11:22:31.038801+00:00
- **system outcome**: `uncertain_match` (confidence 0.41)
- **system reasoning**: borderline score 0.41 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.50, title_overlap=0.29)
- **matched story: "Vision-Language Models (VLMs), like Large Language Models (LLMs), may memorize sensitive, copyrighted, or harmful" (`ae95ac27-0379-49b1-b7ee-dfe83a21aab9`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 54. О естественной реакции властей на искусственный интеллект / От редакции - Независимая газета

- **real_event_id**: `890c8b57-7f91-4cd7-83cb-38c252ea8070`
- **category**: AI
- **topic_bucket**: legal_regulatory
- **collected_at**: 2026-07-29T18:13:41.477973+00:00
- **system outcome**: `uncertain_match` (confidence 0.35)
- **system reasoning**: borderline score 0.35 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.25, title_overlap=0.50)
- **matched story: "Сбер и Самарская область будут вместе развивать искусственный интеллект в регионе - Независимая газета" (`b9543eaa-f6b5-482f-bf00-dc18c9d67701`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 55. Today’s NYT Connections: Sports Edition Hints and Answers for July 29, #674

- **real_event_id**: `47225c3c-fae1-449e-a06b-88160766cfa2`
- **category**: GADGETS
- **topic_bucket**: other
- **collected_at**: 2026-07-28T21:54:23.169659+00:00
- **system outcome**: `uncertain_match` (confidence 0.59)
- **system reasoning**: borderline score 0.59 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.50, title_overlap=0.73)
- **matched story: "Today’s NYT Connections Hints and Answers for July 29, #1144" (`219b9726-9938-42e5-b4a5-c3ffeaa29f75`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 56. I'm switching my phone from Android to Linux

- **real_event_id**: `b0395a91-aa0b-418b-a7d5-85173f707d05`
- **category**: STARTUPS
- **topic_bucket**: other
- **collected_at**: 2026-08-05T21:40:28.221627+00:00
- **system outcome**: `uncertain_match` (confidence 0.46)
- **system reasoning**: borderline score 0.46 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.50, title_overlap=0.40)
- **matched story: "I ran a dumpstate analysis on my Android phone - 3 system diagnostics to check for free" (`6b44e486-337d-46f3-a962-679795eb0103`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 57. We develop a fully nonlinear structural vector autoregressive framework in which the contemporaneous structural mapping

- **real_event_id**: `69072c31-a9ab-4727-b9aa-e4ee1dffc75e`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-05T11:22:37.294372+00:00
- **system outcome**: `uncertain_match` (confidence 0.60)
- **system reasoning**: borderline score 0.60 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=1.00, title_overlap=0.00)
- **matched story: "We present a biconvex approach for minimum-time motion planning around convex obstacles that is guaranteed to converge," (`77f1d290-bde1-4529-864c-aef61b3e90af`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 58. Gears of War: E-Day devs are embracing 'old-school' multiplayer in 2026: 'No battle pass, no tour of duty, no gimmicks,

- **real_event_id**: `d614bc27-e9c9-42db-9b3f-817bd1fc27e3`
- **category**: HARDWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-30T18:34:15.330125+00:00
- **system outcome**: `uncertain_match` (confidence 0.56)
- **system reasoning**: borderline score 0.56 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.75, title_overlap=0.29)
- **matched story: "Gears of War: E-Day multiplayer is so old, it feels new again" (`33bec05b-f6d1-4ea8-aa94-ea65ee0af9c2`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 59. Meta introduces Muse Code, its take on a coding agent

- **real_event_id**: `005f4c48-fc2b-417b-b243-d331233d6268`
- **category**: GADGETS
- **topic_bucket**: product
- **collected_at**: 2026-08-05T22:12:18.377871+00:00
- **system outcome**: `uncertain_match` (confidence 0.37)
- **system reasoning**: borderline score 0.37 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.20, title_overlap=0.62)
- **matched story: "Meta launches Muse Code AI coding agent for macOS and Linux" (`6d6187e4-ef1a-4d65-be03-e245d67895c7`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 60. Искусственный интеллект страшнее ядерного оружия - заявление ученых - Cursorinfo

- **real_event_id**: `105d3544-a253-4f41-b351-046a780fb1d1`
- **category**: AI
- **topic_bucket**: legal_regulatory
- **collected_at**: 2026-08-05T15:53:28.112284+00:00
- **system outcome**: `uncertain_match` (confidence 0.40)
- **system reasoning**: borderline score 0.40 between thresholds [0.35, 0.65) - not confidently new or matched (entity_overlap=0.50, title_overlap=0.25)
- **matched story: "Искусственный интеллект как основа технологического лидерства: практика внедрения и национальные приоритеты -" (`cb65963a-186f-4d89-a8e7-00135894022f`)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### NEW_STORY spot-check (system says: unrelated to anything seen before) — 20 items

### 61. Разработан бесплатный шрифт ShieldFont, подменяющий в глазах ИИ осмысленный контент чушью

- **real_event_id**: `94c464aa-db3c-4e0b-885a-ee333e4a68d7`
- **category**: GADGETS
- **topic_bucket**: other
- **collected_at**: 2026-08-02T19:46:42.991848+00:00
- **system outcome**: `new_story` (confidence 0.90)
- **system reasoning**: best same-bucket candidate score 0.10 below low threshold 0.35 (entity_overlap=0.17, title_overlap=0.00)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 62. Substack writers, you need a website

- **real_event_id**: `03ca0929-6698-4f4a-89f8-551cd9aa8217`
- **category**: STARTUPS
- **topic_bucket**: other
- **collected_at**: 2026-07-28T21:18:30.833090+00:00
- **system outcome**: `new_story` (confidence 0.84)
- **system reasoning**: best same-bucket candidate score 0.16 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.40)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 63. Roku Hikes Hardware Prices by Up to 60%

- **real_event_id**: `5c9faa4a-9cc2-449d-9ec5-fcfd3b607421`
- **category**: GADGETS
- **topic_bucket**: other
- **collected_at**: 2026-07-24T22:16:39.341271+00:00
- **system outcome**: `new_story` (confidence 1.00)
- **system reasoning**: best same-bucket candidate score 0.00 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.00)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 64. Jinjiang OriginHub Intelligent Technology Co., Ltd., And Shenzhen Institute Of Artificial Intelligence And Robotics For

- **real_event_id**: `d71a2409-8b54-4b5d-85ae-eb927bec0aa2`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-24T22:18:16.076885+00:00
- **system outcome**: `new_story` (confidence 0.87)
- **system reasoning**: best same-bucket candidate score 0.13 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.33)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 65. Акции Intel выросли после прогноза роста на фоне спроса на ИИ - Рамблер

- **real_event_id**: `03244545-e57a-42d8-a0cf-65d1ad3bf591`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-25T16:57:22.780271+00:00
- **system outcome**: `new_story` (confidence 0.66)
- **system reasoning**: best same-bucket candidate score 0.34 below low threshold 0.35 (entity_overlap=0.50, title_overlap=0.11)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 66. Франшиза КОМЭКСПО AI — готовая модель для старта успешного бизнеса | СберБизнес - Сбербанк

- **real_event_id**: `cc4985f0-79ed-4d0a-a08b-9d3199c4fcdd`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-07T10:08:47.223776+00:00
- **system outcome**: `new_story` (confidence 0.96)
- **system reasoning**: best same-bucket candidate score 0.04 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.10)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 67. MkLinux and the pimped-out Apple Workgroup Server 9150

- **real_event_id**: `6e1437ad-ad6e-4fd4-b55f-3148e7310309`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-08-02T19:46:35.270267+00:00
- **system outcome**: `new_story` (confidence 0.90)
- **system reasoning**: best same-bucket candidate score 0.10 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.25)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 68. EPIPE on write might mean you're doing it wrong

- **real_event_id**: `df13919e-4549-4ced-958e-1a3f15b0ff02`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-08-02T19:46:35.270267+00:00
- **system outcome**: `new_story` (confidence 0.94)
- **system reasoning**: best same-bucket candidate score 0.06 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.14)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 69. Tim Cook sees Apple's hybrid AI strategy as a 'competitive weapon' - CNBC

- **real_event_id**: `66b64858-d1b0-47a5-9cf0-2f25b2375733`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-31T00:50:24.425704+00:00
- **system outcome**: `new_story` (confidence 0.85)
- **system reasoning**: best same-bucket candidate score 0.15 below low threshold 0.35 (entity_overlap=0.25, title_overlap=0.00)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 70. Катастрофического роста цен на видеокарты пока не было, но всё ещё впереди

- **real_event_id**: `4eb0259c-2467-4f64-90b8-42137516d203`
- **category**: GADGETS
- **topic_bucket**: other
- **collected_at**: 2026-08-02T20:37:45.735110+00:00
- **system outcome**: `new_story` (confidence 0.96)
- **system reasoning**: best same-bucket candidate score 0.04 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.11)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 71. v0.32.6

- **real_event_id**: `af6385f6-cfdb-43f5-8262-fd738ece6f1b`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-08-05T17:31:22.485591+00:00
- **system outcome**: `new_story` (confidence 1.00)
- **system reasoning**: best same-bucket candidate score 0.00 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.00)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 72. Abode Expands Into the New Age of Home Security With Unique Outdoor Sensors

- **real_event_id**: `2e1b7dbd-3580-46f5-a111-7576566ff82e`
- **category**: GADGETS
- **topic_bucket**: other
- **collected_at**: 2026-08-06T01:03:18.650358+00:00
- **system outcome**: `new_story` (confidence 0.93)
- **system reasoning**: best same-bucket candidate score 0.07 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.17)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 73. Learn the good, bad and creative about artificial intelligence at upcoming Maui AARP workshop - Maui Now

- **real_event_id**: `032a39eb-678b-4906-9b6a-4708229f826c`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-29T10:10:13.676842+00:00
- **system outcome**: `new_story` (confidence 0.89)
- **system reasoning**: best same-bucket candidate score 0.11 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.29)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 74. Spec Kit без тяжёлого CLI: как адаптировать Spec-Driven подход под свой проект в Cursor

- **real_event_id**: `fac1a39d-f3bb-477f-bda2-7481f8ae0c20`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-08-05T11:20:55.330675+00:00
- **system outcome**: `new_story` (confidence 0.90)
- **system reasoning**: best same-bucket candidate score 0.10 below low threshold 0.35 (entity_overlap=0.11, title_overlap=0.08)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 75. ИИ-генератор музыки Suno будет помечать композиции водяными знаками - Rozetked.me

- **real_event_id**: `7ed27c6c-cc35-4e46-8473-75067d09633b`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-08-06T21:39:05.736748+00:00
- **system outcome**: `new_story` (confidence 1.00)
- **system reasoning**: best same-bucket candidate score 0.00 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.00)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 76. Sources: ByteDance is pretraining an AI model with up to 10T parameters, roughly 3x larger than Kimi K3 and larger than

- **real_event_id**: `18c563c1-18bd-4019-bc85-5b9fc49fdef7`
- **category**: TECH
- **topic_bucket**: product
- **collected_at**: 2026-08-07T10:07:55.361497+00:00
- **system outcome**: `new_story` (confidence 0.91)
- **system reasoning**: best same-bucket candidate score 0.09 below low threshold 0.35 (entity_overlap=0.10, title_overlap=0.08)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 77. Для отечественных ИИ-моделей вводится единая правовая основа - Главгосэкспертиза России

- **real_event_id**: `98d056e8-91c5-40a7-a0c5-55d997988f6d`
- **category**: AI
- **topic_bucket**: other
- **collected_at**: 2026-07-31T19:13:30.160039+00:00
- **system outcome**: `new_story` (confidence 0.96)
- **system reasoning**: best same-bucket candidate score 0.04 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.11)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 78. Bandit algorithms generate data for downstream inference, but adaptive sampling biases post-bandit sample means. We

- **real_event_id**: `06a0a8b8-3f9f-4a28-b1b9-99134b9eebb2`
- **category**: AI
- **topic_bucket**: legal_regulatory
- **collected_at**: 2026-08-05T11:22:37.294372+00:00
- **system outcome**: `new_story` (confidence 0.97)
- **system reasoning**: best same-bucket candidate score 0.03 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.07)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 79. trunk/7894205ea9fcb7fe475bd21854310cd868f479de: [dynamo] enable generic attribute mutation on non-UDOV VTs (#187531)

- **real_event_id**: `43a4974a-2926-4592-af83-3a46af2eb0b6`
- **category**: SOFTWARE
- **topic_bucket**: other
- **collected_at**: 2026-07-30T17:59:52.972934+00:00
- **system outcome**: `new_story` (confidence 0.96)
- **system reasoning**: best same-bucket candidate score 0.04 below low threshold 0.35 (entity_overlap=0.00, title_overlap=0.10)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### 80. Granola meeting notepad comes to watchOS as Apple Watch becomes an AI device

- **real_event_id**: `334efb6e-95c5-4523-bd9b-2513014f8068`
- **category**: GADGETS
- **topic_bucket**: other
- **collected_at**: 2026-07-28T14:33:17.308260+00:00
- **system outcome**: `new_story` (confidence 0.76)
- **system reasoning**: best same-bucket candidate score 0.24 below low threshold 0.35 (entity_overlap=0.40, title_overlap=0.00)
- **no matched story (this is a NEW_STORY spot-check item - check whether it should actually have matched something the system has already seen)**

**human_decision** (`correct_match` / `incorrect_match` / `missed_match` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---


## Part 2 — cross-category / cross-topic-bucket entity-overlap candidates (20 groups)

Heuristic-only surfacing (never a scored claim - see docs/phase19_m6_story_memory_calibration_report.md's own explicit separation of this from the synthetic fixtures' real precision/recall numbers): real event pairs sharing a distinctive, multi-word entity within a 72-hour window that landed in *different* topic_buckets - exactly the shape of the known Muse-Code failure class (docs/phase18_10_editorial_intelligence_report.md sec7-9), applied to real, current production data. A human reviewer's job here is to say whether each group is genuinely one real-world story the topic_bucket gate incorrectly split apart, or a coincidental entity collision across unrelated stories.


### Group 1: shared entity "life ru" across topic_buckets ['legal_regulatory', 'other']

  - "На «ГорИИзонтах» призвали не ограничивать ИИ, а развивать свои технологии - Life.ru" — category=AI, topic_bucket=other, collected_at=2026-07-25T15:01:38.074216+00:00, system outcome=`new_story` (`165139eb-2440-400c-9484-ecc25b7bb90d`)
  - "ChatGPT в роли адвоката помог немцу выиграть суд и закрыть уголовное дело - Life.ru" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-26T02:25:21.546385+00:00, system outcome=`new_story` (`65ed61f3-b3e9-4632-9628-dbf9530e2c12`)
  - "ChatGPT в роли адвоката помог немцу выиграть суд и закрыть уголовное дело - Life.ru" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-26T02:58:25.413125+00:00, system outcome=`semantic_duplicate` (`e5c50577-6e34-4315-a6ab-a6c83fb27a90`)
  - "В России выйдет первый полностью созданный с помощью ИИ фильм о Кутузове - Life.ru" — category=AI, topic_bucket=other, collected_at=2026-07-28T10:51:56.329755+00:00, system outcome=`uncertain_match` (`e98763e9-6fab-404d-a3d3-44f694f64f76`)
  - "Интенсив «ГорИИзонты» собрал 350 профессионалов медиа - Life.ru" — category=AI, topic_bucket=other, collected_at=2026-07-28T21:17:36.675599+00:00, system outcome=`new_story` (`62553f81-b9d0-4c85-b87b-5ade6ab793d9`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 2: shared entity "new york" across topic_buckets ['legal_regulatory', 'other']

  - "New York school district halts plan to use humanoid robot amid backlash" — category=AI, topic_bucket=other, collected_at=2026-07-28T10:48:51.110516+00:00, system outcome=`new_story` (`8948a4ec-41f9-4a70-b492-b89548f1cd47`)
  - "New York school pauses plan to deploy humanlike AI robot teacher after backlash - AP News" — category=AI, topic_bucket=other, collected_at=2026-07-29T10:10:13.676842+00:00, system outcome=`new_story` (`7aa547b2-be64-4839-b178-92b1abdccf55`)
  - "Communities Fear the Toll of Data Centers Built to Handle Astronomical Growth of Artificial Intelligence - New York" — category=AI, topic_bucket=other, collected_at=2026-07-31T00:16:33.768270+00:00, system outcome=`new_story` (`b5af435c-b33f-41a3-a623-68afb2377cbc`)
  - "New York sues Kalshi for alleged violations of its gambling laws; the CFTC files an emergency motion to stop the" — category=TECH, topic_bucket=legal_regulatory, collected_at=2026-07-31T11:07:05.858622+00:00, system outcome=`new_story` (`e3b1d036-ee15-4a2d-a47c-d20f107e10ad`)
  - "New York alleges Kalshi is running an 'illegal gambling operation' in new lawsuit" — category=GADGETS, topic_bucket=legal_regulatory, collected_at=2026-07-31T19:44:30.329718+00:00, system outcome=`new_story` (`9f0344ab-5440-41a3-b260-da0514a1b90e`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 3: shared entity "gpt-5 6" across topic_buckets ['other', 'product']

  - "У криптографов была «одна пуля в барабане». GPT-5.6 нашел вторую" — category=AI, topic_bucket=other, collected_at=2026-07-28T10:49:09.284170+00:00, system outcome=`new_story` (`7e763981-a81e-4a59-8ccb-6e49c5666879`)
  - "Как создать сайт с помощью Codex и GPT-5.6 — пошаговый гайд для новичка" — category=SOFTWARE, topic_bucket=other, collected_at=2026-07-29T18:12:09.320944+00:00, system outcome=`new_story` (`8a3d3eb6-d83c-4645-b9ec-232e1bbc854b`)
  - "GPT-5.6 vs. Claude Fable 5 for Physical AI, which performs best?" — category=STARTUPS, topic_bucket=other, collected_at=2026-07-29T18:13:43.320431+00:00, system outcome=`new_story` (`aefce5c1-0506-46f7-ae5a-57e23321d630`)
  - "GPT-5.6 и ChatGPT Work разогнали выручку OpenAI — компания догоняет Anthropic" — category=GADGETS, topic_bucket=other, collected_at=2026-07-30T11:36:32.946369+00:00, system outcome=`new_story` (`869d7457-1602-4fa3-9943-86767f93c482`)
  - "OpenAI makes two GPT-5.6 models cheaper, expanding usage in ChatGPT" — category=GADGETS, topic_bucket=product, collected_at=2026-07-30T17:26:36.009980+00:00, system outcome=`new_story` (`4d0f8ae1-8869-4d5e-bdbe-a2deb3fe723c`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 4: shared entity "nvidia blackwell" across topic_buckets ['legal_regulatory', 'other']

  - "Sources: Moonshot is seeking access to more Nvidia Blackwell chips to prepare for Kimi K4's development, after training" — category=TECH, topic_bucket=other, collected_at=2026-07-28T14:39:30.987630+00:00, system outcome=`new_story` (`b69addb7-9d29-4cc9-86da-2fbad86335d4`)
  - "China's Moonshot AI reportedly used Nvidia Blackwell chips for training Kimi K3 — company circumvented both U.S. export" — category=AI, topic_bucket=other, collected_at=2026-07-29T10:46:05.450700+00:00, system outcome=`new_story` (`d0692b77-de27-4ceb-8b10-9f8e20c31951`)
  - "Нашумевшую ИИ-модель Kimi K3 обучали на чипах Nvidia Blackwell вопреки запретам США и Китая, но это не точно" — category=GADGETS, topic_bucket=legal_regulatory, collected_at=2026-07-29T18:12:17.129010+00:00, system outcome=`new_story` (`6cecb359-bb5d-43d0-951d-e140b0da930a`)
  - "Moonshot ищет чипы Nvidia Blackwell для обучения Kimi K4" — category=SOFTWARE, topic_bucket=other, collected_at=2026-07-29T18:48:37.661261+00:00, system outcome=`new_story` (`a1de7472-b632-4e4a-b2ef-b25d61ad1801`)
  - "Нашумевшую ИИ-модель Kimi K3 обучали на чипах Nvidia Blackwell вопреки запретам США и Китая, но это не точно - 3DNews" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-29T18:51:30.860872+00:00, system outcome=`new_story` (`5d589ed0-662d-42f2-b45a-09bad8ba717b`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 5: shared entity "алис ai" across topic_buckets ['legal_regulatory', 'other']

  - "Быстрые ответы «Алисы AI» в «Поиске» набрали 49,5 млн ежемесячной аудитории / Комментарии / Хабр - Хабр" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-29T10:46:06.638623+00:00, system outcome=`new_story` (`6e2b96ec-d07a-463a-bfc7-84b09a6c2b4f`)
  - "«Алиса AI» набирает аудиторию: быстрые ответы в поиске Яндекса используют уже почти 50 миллионов человек - ixbt.com" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-29T10:46:06.638623+00:00, system outcome=`new_story` (`a73d7acc-344e-44be-a1f8-06f786dfe566`)
  - "Быстрые ответы «Алисы AI» в «Поиске» набрали 49,5 млн ежемесячной аудитории - Хабр" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-29T10:46:06.638623+00:00, system outcome=`semantic_duplicate` (`7827e42b-4e5f-4645-9011-aee597791505`)
  - "Быстрые ответы «Алисы AI» в «Поиске» набрали 49,5 млн ежемесячной аудитории - CNews.ru" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-29T11:24:11.757261+00:00, system outcome=`new_story` (`ad13b43a-6367-43a5-84f2-546654f22014`)
  - "Как быстро загнать страницу в индекс Яндекса — и почему для Алисы AI этого мало" — category=SOFTWARE, topic_bucket=other, collected_at=2026-07-31T20:19:46.760212+00:00, system outcome=`new_story` (`6068319a-6004-4021-9ff8-856a060a1b5e`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 6: shared entity "акци spacex" across topic_buckets ['legal_regulatory', 'other']

  - "Акции SpaceX опустились на 20 % ниже цены июньского размещения" — category=GADGETS, topic_bucket=other, collected_at=2026-08-02T19:46:42.991848+00:00, system outcome=`new_story` (`385ed761-4ec1-4d90-926d-c19b387674b4`)
  - "Акции SpaceX рухнули на 10% из-за рекордных расходов на искусственный интеллект - Финансы Mail" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-08-05T11:22:27.782500+00:00, system outcome=`new_story` (`28ff968d-f258-4b24-a5b8-f91c86c4df5f`)
  - "Акции SpaceX рухнули на 12% на отчете о росте расходов на ИИ - Эксперт" — category=AI, topic_bucket=other, collected_at=2026-08-05T13:38:27.706156+00:00, system outcome=`new_story` (`55fd56ca-5eeb-4888-9c5a-1c1fc85f12a6`)
  - "Акции SpaceX вошли в крутое пике — инвесторов напугали беспрецедентные расходы на ИИ" — category=GADGETS, topic_bucket=other, collected_at=2026-08-05T15:19:21.754227+00:00, system outcome=`new_story` (`48d8259e-d422-40a0-a57c-04cb21a98734`)
  - "Акции SpaceX вошли в крутое пике — инвесторов напугали беспрецедентные расходы на ИИ - 3dnews.ru" — category=AI, topic_bucket=other, collected_at=2026-08-05T19:16:39.345111+00:00, system outcome=`new_story` (`0e8b4622-3bb0-4797-baba-a90b1f54f332`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 7: shared entity "в ес" across topic_buckets ['legal_regulatory', 'other']

  - "В ЕС заработали требования к маркировке ИИ-контента - DW.com" — category=AI, topic_bucket=other, collected_at=2026-08-02T19:47:43.231767+00:00, system outcome=`new_story` (`7adaf286-3517-431b-b651-6242b0d5988a`)
  - "В ЕС вступили в силу требования об обязательной маркировке ИИ-контента - Incrussia" — category=AI, topic_bucket=other, collected_at=2026-08-02T19:47:43.231767+00:00, system outcome=`uncertain_match` (`94a34aa1-89b6-491b-a37f-b8aea01fac87`)
  - "В ЕС вступили в силу новые правила в отношении искусственного интеллекта - Європейська правда" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-08-02T19:47:43.231767+00:00, system outcome=`new_story` (`9957a608-777a-4f8c-8af9-91b60e29d768`)
  - "В ЕС вступили в силу требования об обязательной маркировке ИИ-контента - Реальное время" — category=AI, topic_bucket=other, collected_at=2026-08-02T19:47:43.231767+00:00, system outcome=`uncertain_match` (`6e5a3a42-5022-46e6-b99b-cf12abc3add4`)
  - "В ЕС заработали нормы о маркировке продуктов ИИ - Inbusiness.kz" — category=AI, topic_bucket=other, collected_at=2026-08-02T19:47:43.231767+00:00, system outcome=`new_story` (`09999e9c-7745-4bfe-af45-213ec0f76490`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 8: shared entity "marketpower pro" across topic_buckets ['legal_regulatory', 'other']

  - "Сбер оценил уровень опасений молодых специалистов из-за внедрения ИИ - Marketpower.pro" — category=AI, topic_bucket=other, collected_at=2026-07-24T22:18:17.459616+00:00, system outcome=`new_story` (`097b1686-49e1-4385-8bc1-c8316e647337`)
  - "Alphabet увеличила расходы на ИИ до $205 млрд: акции бигтеха падают на фоне роста затрат - Marketpower.pro" — category=AI, topic_bucket=other, collected_at=2026-07-25T08:18:32.352924+00:00, system outcome=`new_story` (`000de1bb-98d1-48bb-ae60-96ad00d29284`)
  - "Техгиганты США вступили в спор из-за нового метода обучения ИИ и кражи технологий - Marketpower.pro" — category=AI, topic_bucket=other, collected_at=2026-07-25T13:19:35.299408+00:00, system outcome=`new_story` (`3d28ad73-32ad-4ac9-ace1-80ed69c3eaf4`)
  - "Разработчики искусственного интеллекта запросили у государства 72 млрд ₽ - Marketpower.pro" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-28T10:51:56.329755+00:00, system outcome=`new_story` (`09828fd2-ad05-4633-bb2d-adf88c0e7893`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 9: shared entity "big data" across topic_buckets ['legal_regulatory', 'other']

  - "Обсуждено использование искусственного интеллекта и BIG DATA в биоинформатике, физике и климатических моделях - АМИТ" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-25T07:44:13.368330+00:00, system outcome=`new_story` (`d3f68658-09b3-477c-98c1-140ab78dbd27`)
  - "Можно ли подготовить инженера по Big Data и Machine Learning за один год? Опыт МАИ" — category=AI, topic_bucket=other, collected_at=2026-07-25T16:22:41.321547+00:00, system outcome=`new_story` (`441b9023-6f9e-43ca-803a-d83a1a9faa25`)
  - "Можно ли подготовить инженера по Big Data и Machine Learning за один год? Опыт МАИ - Хабр" — category=AI, topic_bucket=other, collected_at=2026-07-25T20:53:01.700110+00:00, system outcome=`semantic_duplicate` (`a80e9131-891b-4c12-a90b-881b2414761b`)
  - "In the Big Data era, the scalability of clustering algorithms constitutes a key challenge. Traditional density-based" — category=AI, topic_bucket=other, collected_at=2026-07-28T10:52:01.689852+00:00, system outcome=`new_story` (`544daf30-996d-4a6c-b2fa-7edeb411a0b7`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 10: shared entity "samsung galaxy z fold" across topic_buckets ['other', 'product']

  - "Samsung Galaxy Z Fold 8 Ultra vs. Z Fold 7: How the first 'Ultra' foldable compares to last year's model" — category=STARTUPS, topic_bucket=product, collected_at=2026-07-25T11:02:11.213383+00:00, system outcome=`new_story` (`b8ba80a0-5f05-4193-9535-e91290ab204f`)
  - "Samsung Galaxy Z Fold 8 vs. Z Flip 8: How Samsung's two new foldables compare" — category=STARTUPS, topic_bucket=other, collected_at=2026-07-28T10:48:19.654605+00:00, system outcome=`new_story` (`fdf7bb4d-b571-43d6-8066-fbd915389aa6`)
  - "Samsung Galaxy Z Fold 8 review: Wider really is better" — category=GADGETS, topic_bucket=other, collected_at=2026-07-28T20:54:08.882569+00:00, system outcome=`new_story` (`5e894a9f-14ac-483e-bbd5-7a12d4a8665a`)
  - "Samsung Galaxy Z Fold 8 review: comfortable when shut, 4:3 inner display is great, and impressive battery life, but no" — category=TECH, topic_bucket=other, collected_at=2026-07-29T13:04:23.573180+00:00, system outcome=`new_story` (`ccbab72b-622c-40f5-bbcf-aeab94f045cb`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 11: shared entity "x money" across topic_buckets ['other', 'product']

  - "X Money begins limited US rollout" — category=GADGETS, topic_bucket=other, collected_at=2026-07-28T10:48:18.956563+00:00, system outcome=`new_story` (`c761efd7-ddbc-4751-ab88-8a59e582e993`)
  - "X Money officially launches in the US with Apple Wallet support after invite-only beta" — category=GADGETS, topic_bucket=product, collected_at=2026-07-28T10:48:38.054012+00:00, system outcome=`new_story` (`485da09d-2d50-4f1d-a923-48c24e9b05e6`)
  - "X полноценно запустила банковский сервис X Money в США для подписчиков Premium и Premium+" — category=STARTUPS, topic_bucket=product, collected_at=2026-07-28T10:49:12.552721+00:00, system outcome=`new_story` (`c7331245-3d8c-4c6c-b2c9-7229d1a20d7e`)
  - "Илон Маск запустил платёжный сервис X Money" — category=GADGETS, topic_bucket=product, collected_at=2026-07-28T10:49:30.029463+00:00, system outcome=`new_story` (`18a48945-b231-44af-aea7-f838f2df10e7`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 12: shared entity "le monde fr" across topic_buckets ['legal_regulatory', 'other']

  - "EU tells firms to label AI-generated content from Sunday - Le Monde.fr" — category=AI, topic_bucket=other, collected_at=2026-07-28T10:51:54.720423+00:00, system outcome=`new_story` (`7417a539-2e48-4ec2-bb65-c0e9624a4081`)
  - "Elon Musk's xAI sues Minnesota over its first-in-the-nation law banning 'nudification' technology - Le Monde.fr" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-29T21:47:13.255998+00:00, system outcome=`new_story` (`773d513e-bb60-458a-9a8a-46cfe5a62eb7`)
  - "AI: Europe commits €5 billion to fund seven megafactories and catch up with the US and China - Le Monde.fr" — category=AI, topic_bucket=other, collected_at=2026-07-30T22:36:55.597121+00:00, system outcome=`new_story` (`2c893b75-173e-4085-a0c0-e706f1e08451`)
  - "'I don't let my AI talk to me like that' - Le Monde.fr" — category=AI, topic_bucket=other, collected_at=2026-08-02T19:47:41.891375+00:00, system outcome=`new_story` (`4cb72b66-0f1e-43db-8ee7-b22294f8cbba`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 13: shared entity "фонтанк ру" across topic_buckets ['legal_regulatory', 'other']

  - "Как нейросети помогают лечить животных, изучать космос и оживлять историю - ФОНТАНКА.ру" — category=AI, topic_bucket=other, collected_at=2026-07-28T10:51:56.329755+00:00, system outcome=`new_story` (`1299efbb-0c1b-41a5-95d4-ac387f11634e`)
  - "ИИ наблюдал за сдающими ЕГЭ. Нейросеть выявила более 2 тысяч нарушений - ФОНТАНКА.ру" — category=AI, topic_bucket=other, collected_at=2026-07-28T11:59:34.625883+00:00, system outcome=`new_story` (`4871be2c-059b-4338-a401-f0d38e375c6e`)
  - "По секрету GPT. Закон и нейропаранойя - ФОНТАНКА.ру" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-30T11:37:18.813524+00:00, system outcome=`new_story` (`c28eb1f5-8fa9-4e18-8554-73bd5239d610`)
  - "В Гарант Коннект появилась новая возможность — поддержка MCP - ФОНТАНКА.ру" — category=AI, topic_bucket=other, collected_at=2026-07-30T15:16:05.325785+00:00, system outcome=`new_story` (`a4ea19f3-e52d-4dbd-b570-41154f16628f`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 14: shared entity "steam machine" across topic_buckets ['legal_regulatory', 'other']

  - "Valve says Steam Machine reservation-holders aren't being leapfrogged" — category=GADGETS, topic_bucket=other, collected_at=2026-07-29T10:07:45.760536+00:00, system outcome=`new_story` (`374ffeb1-3879-4f57-b673-720337f4c45b`)
  - "Valve добавила Steam Machine поддержку FSR 4.1 и открыла путь к кастомным корпусам" — category=GADGETS, topic_bucket=other, collected_at=2026-07-29T18:12:17.129010+00:00, system outcome=`new_story` (`62fe5bf5-54a6-48be-8f1f-bedf2187819c`)
  - "Steam Machine reservation queue should be caught up by the end of 2026, Valve says" — category=HARDWARE, topic_bucket=other, collected_at=2026-07-29T21:46:09.261082+00:00, system outcome=`new_story` (`980dd77e-39a4-4bc5-8d5b-f96850e5ad57`)
  - "Dbrand unveils Steam Machine customization 'backup plan' after its Companion Cube got confined to the test chamber" — category=HARDWARE, topic_bucket=legal_regulatory, collected_at=2026-07-30T16:54:11.127780+00:00, system outcome=`new_story` (`ce415a16-1276-45e8-b27a-c0eb931a9d8b`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 15: shared entity "security affairs" across topic_buckets ['other', 'security_incident']

  - "OpenAI’s Rogue AI Agent Breached Second Company, Report Says - Security Affairs" — category=AI, topic_bucket=security_incident, collected_at=2026-07-29T10:10:13.676842+00:00, system outcome=`new_story` (`9e6d521a-80bd-4f90-84f7-ab4f2bac28d2`)
  - "Claude Mythos Shows AI Can Outpace Human Cryptography Research - Security Affairs" — category=AI, topic_bucket=other, collected_at=2026-07-29T23:03:10.867321+00:00, system outcome=`new_story` (`5352a9d6-309b-4449-a337-09348d94daa5`)
  - "What an LLM Can Find: A Practical, Cheap Path to Code-level Threat Discovery - Security Affairs" — category=AI, topic_bucket=other, collected_at=2026-07-31T19:13:28.878439+00:00, system outcome=`new_story` (`f0ee4235-cba5-41dc-b49b-8d34480f2ed8`)
  - "Google AI Supercharges Chrome Security, Fixing 1,072 Bugs - Security Affairs" — category=AI, topic_bucket=other, collected_at=2026-07-31T19:13:28.878439+00:00, system outcome=`new_story` (`65102c6b-71a6-4539-b1c7-8a4f5c7c1bb2`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 16: shared entity "gemini robotics" across topic_buckets ['other', 'product']

  - "Gemini Robotics 2 Brings Google's AI Into the Physical World" — category=STARTUPS, topic_bucket=other, collected_at=2026-07-30T15:47:22.079311+00:00, system outcome=`new_story` (`de43824a-da6f-461c-b6ca-d6aeafc7469e`)
  - "Google DeepMind releases Gemini Robotics 2, which combines several different AI models into a single system to control" — category=TECH, topic_bucket=product, collected_at=2026-07-30T15:48:09.817874+00:00, system outcome=`new_story` (`8eb24c1b-1b06-47f4-8add-387ea03eb695`)
  - "Gemini Robotics 2 brings whole body intelligence to robots" — category=STARTUPS, topic_bucket=other, collected_at=2026-07-30T15:48:52.524708+00:00, system outcome=`new_story` (`dc705364-fb94-4e21-870c-35ff44ac94c1`)
  - "Google's new Gemini Robotics 2 platform allows for 'intelligent whole-body control'" — category=GADGETS, topic_bucket=other, collected_at=2026-07-30T18:00:45.092854+00:00, system outcome=`new_story` (`ad1fdffc-fd7e-421d-8317-0f87f1357a6b`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 17: shared entity "m5 macbook air" across topic_buckets ['legal_regulatory', 'other']

  - "Deals: M5 MacBook Air $240 off straight from Apple, AirPods Pro 3, AirTag 2, transparent metal power bank, more" — category=GADGETS, topic_bucket=legal_regulatory, collected_at=2026-07-31T16:19:04.535428+00:00, system outcome=`new_story` (`55408a00-b6aa-4556-b15d-2c9a9a142de7`)
  - "Apple weekend deals: AirPods Pro 3, Apple Studio Display $540 off, M5 MacBook Air $240 off, AirTag 2, more" — category=GADGETS, topic_bucket=other, collected_at=2026-08-02T19:45:39.398747+00:00, system outcome=`new_story` (`dc299ccd-ecf2-439e-be0d-bcc4eb94ac53`)
  - "Deals: M5 MacBook Air up to $300 off, AirPods Max 2 $100 off, Beats Solo Buds from $41, AirTag 2, more" — category=GADGETS, topic_bucket=other, collected_at=2026-08-05T11:20:03.696479+00:00, system outcome=`new_story` (`b5ebf722-44fb-45b0-a35a-8e8a3054f535`)
  - "Deals: AirPods Pro 3 now even lower at 25% off, M5 MacBook Air $190 off, iPhone Air $150+ off, more" — category=GADGETS, topic_bucket=other, collected_at=2026-08-06T15:35:06.799609+00:00, system outcome=`new_story` (`43c87c54-556f-43b7-a0d9-0f43f4e2949c`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 18: shared entity "automated reasoning" across topic_buckets ['legal_regulatory', 'other']

  - "Automated Reasoning policy refinement in Amazon Bedrock" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-08-05T11:22:00.053413+00:00, system outcome=`new_story` (`f18e4583-abb2-44fe-8348-3ef0089d04f4`)
  - "Automated Reasoning policy refinement in Amazon Bedrock | Artificial Intelligence - Amazon Web Services (AWS)" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-08-05T11:57:11.390617+00:00, system outcome=`new_story` (`36caf96a-7b10-45b9-abb6-cceb503e9276`)
  - "Agent Skills for Automated Reasoning policies in Amazon Bedrock" — category=AI, topic_bucket=other, collected_at=2026-08-06T16:43:16.522739+00:00, system outcome=`new_story` (`2177a734-d211-4248-a618-0110dc1b8d27`)
  - "Agent Skills for Automated Reasoning policies in Amazon Bedrock - Amazon Web Services (AWS)" — category=AI, topic_bucket=other, collected_at=2026-08-07T10:08:46.304432+00:00, system outcome=`new_story` (`adad635d-2a40-4394-a841-e682c15de444`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 19: shared entity "google chrome" across topic_buckets ['legal_regulatory', 'other', 'product']

  - "Google Chrome now supports Netflix in 4K, just not on all machines" — category=GADGETS, topic_bucket=other, collected_at=2026-08-05T15:18:43.732668+00:00, system outcome=`new_story` (`8f3cfcba-c51f-4a67-ac7a-19105e7c0928`)
  - "Google Chrome slowly starts rolling out updated navigation bar with Gemini button on Android [Gallery]" — category=GADGETS, topic_bucket=product, collected_at=2026-08-06T17:16:29.918002+00:00, system outcome=`new_story` (`793fdd02-a052-42e4-8136-a4033ac5b676`)
  - "Google Chrome теперь потребует до 20 Гбайт на диске — ради локального ИИ" — category=GADGETS, topic_bucket=legal_regulatory, collected_at=2026-08-07T10:08:03.460228+00:00, system outcome=`new_story` (`4822b4b5-39b3-4093-a19b-aaeebbcf0142`)
  - "Google Chrome теперь потребует до 20 Гбайт на диске — ради локального ИИ - 3dnews.ru" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-08-07T10:08:47.223776+00:00, system outcome=`new_story` (`f806460d-6ca2-4f0c-9081-b2315f02310f`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---

### Group 20: shared entity "ict-online ru" across topic_buckets ['legal_regulatory', 'other']

  - "На ULCAMP'26 главным разговором стал не искусственный интеллект, а человек в эпоху ИИ - ICT-Online.ru" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-24T22:18:17.459616+00:00, system outcome=`new_story` (`2e47c9ea-e9cb-4efe-9bb5-65e0d42bd3bb`)
  - "РЕД СОФТ и ДС-Софт потдвердили совместимость Consul AI с РЕД ОС 8 - ICT-Online.ru" — category=AI, topic_bucket=other, collected_at=2026-07-25T12:45:17.190921+00:00, system outcome=`new_story` (`33126a39-2eaf-4e62-9b18-b91fe2efda3c`)
  - "В России принят базовый закон об искусственном интеллекте: что изменится с 2026 года - ICT-Online.ru" — category=AI, topic_bucket=legal_regulatory, collected_at=2026-07-28T10:51:56.329755+00:00, system outcome=`new_story` (`95b6fd76-9576-46dc-bad1-99ce3da8e7f5`)

**human_decision** (is this genuinely the same real-world story split across topic_buckets? `same_story` / `different_stories` / `unsure`): _[ not yet reviewed ]_

**human_notes**: _[ not yet reviewed ]_

---
