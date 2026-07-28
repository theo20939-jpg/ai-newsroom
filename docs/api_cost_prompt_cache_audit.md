# Prompt Size and Caching Audit (Step 5)

Status: **AUDIT COMPLETE — NO CACHING CHANGE RECOMMENDED (evidence-based, not a default refusal).**

## 1. Static prefix size per capability (real prompt template files, measured directly)

The static, repeated portion of every request is the `system` message
(`prompt.system + "\n\nRULES:\n" + rules`, `capabilities/*_capability.py::_build_request()`) —
the JSON `response_schema` travels as a *separate* payload field
(`text.format.schema`, `openai_adapter.py::_build_payload()`), not inside the cached `input`
message sequence, so it is excluded from this measurement (the schema itself is small anyway,
counted separately in §2).

| Capability | Active prompt version | System+rules chars | ≈ tokens (÷4) |
|---|---|---|---|
| Research | v2 | 616 | 154 |
| Intelligence | v2 | 682 | 170 |
| Engagement | v1 | 572 | 143 |
| Scoring | v2 | 386 | 96 |
| Copywriting | v3 | 801 | 200 |
| Quality | v3 | 812 | 203 |

## 2. Finding: every static prefix is far below the ~1024-token prompt-caching threshold

OpenAI's automatic prompt caching (a provider-side mechanism, not something this application
enables/disables via a flag) only engages for a shared prefix of roughly 1024+ tokens. **Every
one of this codebase's 6 real system prompts is 96-203 tokens — 5-10× below that floor** even
before considering that the prefix must additionally be *repeated* (which it structurally is,
per capability, across every call), and even before considering that the `response_schema`
field (which would add a further ~150-350 tokens if it does participate in prefix matching -
unconfirmed, see §4) is sent separately from the cached `input` sequence.

**No prompt in this codebase is currently long enough for OpenAI's own automatic prompt caching
to help, regardless of call volume or repetition rate.** This is a structural fact about prompt
length, not a traffic-volume problem — even at very high call volume, a 150-token prefix stays
below the minimum caching unit.

## 3. Repeated-prefix content identified (for future reference, not acted on now)

The repeated elements across calls to the same capability are: the `system` role text
(governance rules, output format instructions) and the `response_schema` JSON. There is **no**
category-definition or fact-safety-instruction text embedded in any of these 6 active prompts
today (Fact Safety and category assignment are both deterministic, non-LLM code paths -
`services/fact_safety.py`, `services/category_mapping.py`-equivalent - never prompt text), so
there is no "governance boilerplate bloat" to trim here; the prompts are already lean.

## 4. What was not verified

Whether OpenAI's Responses API extends prefix-cache matching to the `text.format.schema` payload
field (as opposed to only the `input` message array) is not confirmed from this environment (no
official-doc access verified live, and no paid probe was spent confirming it - out of scope
given §2's conclusion already holds regardless of this detail: even system+rules+schema combined,
per the earlier byte-count pass across the full YAML files, tops out at ~580 tokens for the
longest capability (Copywriting) - still under the ~1024 floor).

## 5. Recommendation

**Do not add prompt-caching-specific code.** No cache-write policy, no prefix restructuring, no
"pin the system prompt to hit the cache" reshuffling — there is nothing to activate that would
have any effect at current prompt lengths. If a future capability's prompt grows substantially
(e.g. a long few-shot example set, an embedded style guide), re-run this same measurement before
assuming caching would help - the answer today is a clean "not applicable," not "not
worthwhile."

This audit required no code change and no test change (nothing was activated or deactivated).

---

**PROMPT/CACHE AUDIT COMPLETE — ALL PROMPTS TOO SHORT TO BENEFIT FROM PROMPT CACHING TODAY**
