"""SEMANTIC EDITORIAL JUDGE for viral carousels (founder task 2026-09-26).

The deterministic redundancy rules (services.instagram_viral_format.thesis_relation) compare 4-character content stems. They cannot see the
same thesis said in other words - the live GTA retest (786ed3e) had slide 1 «И сделал это моддер, а не Rockstar Games.» and slide 2
«Улучшение пришло не благодаря усилиям Rockstar Games.» with ZERO shared stems - and a caption that closes on a generalised moral reads as
clean Russian to every lint. Both are questions of MEANING, so this module asks ONE bounded model call.

The judge only CLASSIFIES. It never rewrites copy, adds facts, chooses the format, touches grounding or produces user-facing text: it
returns a small structure (same-thesis slide pairs, caption repetition, caption aphorism, unsupported interpretation) that becomes
correctable findings for the EXISTING one editorial correction. It reuses the narrowest existing mechanism - the one-shot gateway call of
services.instagram_semantic_matching (a published prompt, json_schema output, a synthetic RuntimeContext) - with two differences: an explicit
output cap, and FAIL CLOSED (any technical failure or malformed structure raises SemanticJudgeUnavailableError, a terminal
CreativeDirectorUnavailableError; the judge is never retried and a result is never invented).

Input bound: at most 7 slides (the viral carousel's own maximum), each headline <= 200 and body <= 260 characters (the Director schema's
maxLength), the caption <= 1,200, and the post's own evidence lines (<= 10, media placeholders dropped), each cut to a 400-character
window centred on what the copy uses. A slide's body and the caption routinely state facts from lines the slide does not cite (the
accepted DeepSeek carousel: Unit 42 / 30 July come from E4, cited by no slide), so the cited line alone is not enough. No source documents."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext
from services.instagram_creative_director import CreativeDirectorUnavailableError

JUDGE_PROMPT_NAME = "instagram_viral_editorial_judge"
JUDGE_PROMPT_VERSION = "5"  # v1-v4 = the calibration rounds (kept published, untouched); v5 = thesis roles (founder task 2026-09-27)
MAX_SLIDES = 7
MAX_HEADLINE_CHARS = 200
MAX_BODY_CHARS = 260
MAX_CAPTION_CHARS = 1200
MAX_EVIDENCE_CHARS = 400  # a window of each line, centred on what the copy uses (acquired lines can open with page chrome)
MAX_EVIDENCE_LINES = 10  # real viral posts carry <= 7 fact lines (GTA, DeepSeek: 7 + a media placeholder)
# the output is a handful of short reasons (schema: <= 6 pairs + <= 4 interpretations, every string capped); reasoning runs at "low" effort.
# 1,500 tokens is the ceiling for reasoning + JSON together - a response cut there is a technical failure (fail closed), never a verdict.
JUDGE_MAX_OUTPUT_TOKENS = 1500
JUDGE_REASONING_EFFORT = "low"
CHARS_PER_TOKEN_WORST = 2.0  # conservative for Russian text (o200k averages ~3 Cyrillic chars per token)


class SemanticJudgeUnavailableError(CreativeDirectorUnavailableError):
    """The semantic judge could not return a well-formed verdict (gateway error, truncation, malformed structure). Terminal for the
    post: an unjudged viral carousel is not published as if it had passed, and the judge is not retried."""


@dataclass(frozen=True)
class JudgeVerdict:
    same_thesis_pairs: list[tuple[int, int, str]] = field(default_factory=list)
    caption_repeats_slides: str | None = None  # the reason, when present
    caption_aphorism: tuple[str, str] | None = None  # (sentence, reason), when present
    unsupported_interpretation: list[tuple[str, str, str]] = field(default_factory=list)  # (where, sentence, reason)
    raw: dict = field(default_factory=dict)
    slide_roles: list[str] = field(default_factory=list)  # the judge's own thesis role per slide (v5; empty for an older verdict)
    dropped_pairs: list[dict] = field(default_factory=list)  # same-thesis pairs the role guard removed, with both role readings

    def findings(self) -> list[str]:
        """The verdict as correctable findings for the one editorial correction (English instructions; the copy stays Russian)."""
        out = [f"semantic review: slides {a} and {b} make the same point in different words ({reason.rstrip('.')}) - merge them into one "
               "slide, then use the freed slide for another distinct grounded fact or make the carousel shorter"
               for a, b, reason in self.same_thesis_pairs]
        if self.caption_repeats_slides:
            out.append(f"semantic review: the caption only restates the slides ({self.caption_repeats_slides.rstrip('.')}) - keep it short "
                       "and add context the slides do not give, or one factual summary sentence")
        if self.caption_aphorism:
            sentence, reason = self.caption_aphorism
            out.append(f"semantic review: the caption ends on a generalised moral / second punchline ({sentence!r}: {reason.rstrip('.')}) - "
                       "end the caption on a concrete fact; the carousel keeps at most one dry payoff")
        out += [f"semantic review: unsupported interpretation in {where} ({sentence!r}: {reason.rstrip('.')}) - say only what the evidence "
                "supports" for where, sentence, reason in self.unsupported_interpretation]
        return out


def _cut(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _get(slide: Any, name: str) -> str:
    return str((slide.get(name) if isinstance(slide, dict) else getattr(slide, name, None)) or "")


def _evidence_window(text: str, slide_text: str, limit: int = MAX_EVIDENCE_CHARS) -> str:
    """The cited evidence line, cut to `limit` characters around what the slide actually uses: an acquired line can open with unrelated
    page chrome (real GTA E6: other articles' headlines before the modder sentence), and a head cut would hide the supporting fact."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    words = {w[:4] for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", slide_text.lower())}
    span = limit - 2  # room for the two ellipses; the text scored is exactly the text sent
    scores = {}
    for start in sorted({*range(0, len(text) - span + 1, 20), len(text) - span}):  # the last window too: the fact can close the line
        # DISTINCT copy stems the window covers: page chrome repeating one word must not outscore the sentence the copy actually uses
        scores[start] = len({w[:4] for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", text[start:start + span].lower())} & words)
    tied = [start for start, score in scores.items() if score == max(scores.values())]
    best = tied[len(tied) // 2]  # the middle of the tied range: the matched text sits centred, never cut at a window edge
    return ("…" if best else "") + text[best:best + span].strip() + ("…" if best + span < len(text) else "")


def _evidence_label(ref: str, allowed_evidence: list[str]) -> tuple[str, str] | None:
    ref = ref.strip()
    match = re.fullmatch(r"E(\d+)", ref)
    if match and 1 <= int(match.group(1)) <= len(allowed_evidence):
        return ref, allowed_evidence[int(match.group(1)) - 1]
    if ref in allowed_evidence:
        return f"E{allowed_evidence.index(ref) + 1}", ref
    return None


def build_judge_input(slides: list[Any], caption: str, allowed_evidence: list[str]) -> str:
    """The bounded user text: numbered slides (headline, body, the label of the evidence each cites), the post's evidence lines (windowed),
    the caption."""
    lines = ["SLIDES:"]
    for index, slide in enumerate(slides[:MAX_SLIDES], 1):
        label = _evidence_label(_get(slide, "source_evidence"), allowed_evidence)
        lines.append(f"{index}. headline: {_cut(_get(slide, 'slide_copy'), MAX_HEADLINE_CHARS)}")
        lines.append(f"   body: {_cut(_get(slide, 'slide_body'), MAX_BODY_CHARS)}")
        lines.append(f"   evidence: {label[0] if label else 'none'}")
    copy_text = " ".join([*(f"{_get(s, 'slide_copy')} {_get(s, 'slide_body')}" for s in slides[:MAX_SLIDES]), caption or ""])
    facts = [(f"E{i}", line) for i, line in enumerate(allowed_evidence, 1) if not str(line).startswith("SOURCE MEDIA:")][:MAX_EVIDENCE_LINES]
    lines.append("EVIDENCE (the only facts the carousel may state):")
    lines += [f"{key}: {_evidence_window(text, copy_text)}" for key, text in facts] or ["(none)"]
    lines.append(f"CAPTION: {_cut(caption, MAX_CAPTION_CHARS)}")
    return "\n".join(lines)


def worst_case_input_chars(prompt_repository: PromptRepository) -> int:
    """The largest judge request this module can build: the prompt, 7 slides at the schema's maxLength, 10 evidence windows, the caption."""
    prompt = prompt_repository.resolve(JUDGE_PROMPT_NAME, JUDGE_PROMPT_VERSION)
    slides = [{"slide_copy": "я" * MAX_HEADLINE_CHARS, "slide_body": "я" * MAX_BODY_CHARS, "source_evidence": f"E{i}"} for i in range(1, 8)]
    user = build_judge_input(slides, "я" * MAX_CAPTION_CHARS, ["я" * 2000] * MAX_EVIDENCE_LINES)
    return len(_system_text(prompt)) + len(user)


def worst_case_cost_usd(prompt_repository: PromptRepository, *, input_per_million: float, output_per_million: float) -> dict:
    input_tokens = math.ceil(worst_case_input_chars(prompt_repository) / CHARS_PER_TOKEN_WORST)
    cost = (input_tokens * input_per_million + JUDGE_MAX_OUTPUT_TOKENS * output_per_million) / 1_000_000
    return {"input_chars": worst_case_input_chars(prompt_repository), "input_tokens_worst": input_tokens,
            "output_tokens_cap": JUDGE_MAX_OUTPUT_TOKENS, "worst_case_usd": round(cost, 6)}


def _system_text(prompt: Any) -> str:
    return prompt.system + "\n\nRULES:\n" + "\n".join(f"- {rule}" for rule in prompt.rules)


def parse_verdict(output: Any, slide_count: int) -> JudgeVerdict:
    """Validate the structure strictly; anything malformed raises (fail closed) - a verdict is never guessed."""
    if not isinstance(output, dict):
        raise SemanticJudgeUnavailableError("semantic judge: no structured output")
    try:
        pairs = []
        for item in output["same_thesis_pairs"]:
            a, b = (int(x) for x in item["slides"])
            if not (1 <= a <= slide_count and 1 <= b <= slide_count and a != b):
                raise ValueError(f"slide pair {item['slides']} out of range 1..{slide_count}")
            if abs(a - b) == 1:  # the task scopes distinctness to ADJACENT slides; a non-adjacent echo is recorded in raw, not a finding
                pairs.append((min(a, b), max(a, b), str(item["reason"]).strip()))
        repeats = output["caption_repeats_slides"]
        aphorism = output["caption_aphorism"]
        if not isinstance(repeats["present"], bool) or not isinstance(aphorism["present"], bool):
            raise ValueError("present flags must be booleans")
        interpretations = [(str(i["where"]), str(i["sentence"]), str(i["reason"])) for i in output["unsupported_interpretation"]]
        roles = [str(r) for r in output.get("slide_roles") or []]  # optional: a v4 verdict has none
    except (KeyError, TypeError, ValueError) as exc:
        raise SemanticJudgeUnavailableError(f"semantic judge: malformed structured output ({exc})") from exc
    return JudgeVerdict(
        same_thesis_pairs=sorted(dict.fromkeys(pairs)),
        caption_repeats_slides=str(repeats["reason"]).strip() if repeats["present"] else None,
        caption_aphorism=(str(aphorism["sentence"]).strip(), str(aphorism["reason"]).strip()) if aphorism["present"] else None,
        unsupported_interpretation=interpretations, raw=output, slide_roles=roles)


def apply_role_guard(verdict: JudgeVerdict, slides: list[Any]) -> JudgeVerdict:
    """Founder calibration 2026-09-27: 'what happened' and 'which parts are confirmed / investigated' (or 'what the company said', 'when it
    happened vs when it became known') are two theses. A same-thesis pair is dropped only when the deterministic roles
    (services.instagram_factual_status.slide_thesis_role) put the two slides in different roles, one of them a status / chronology /
    company-response role, AND the judge's own roles - when it gave them - do not put both slides in one role. Same-role pairs stay."""
    from services.instagram_factual_status import DISTINCT_ROLES, slide_thesis_role

    kept, dropped = [], []
    for a, b, reason in verdict.same_thesis_pairs:
        if a > len(slides) or b > len(slides):
            kept.append((a, b, reason))
            continue
        local = (slide_thesis_role(slides[a - 1], a), slide_thesis_role(slides[b - 1], b))
        judged = (verdict.slide_roles[a - 1], verdict.slide_roles[b - 1]) if len(verdict.slide_roles) >= b else None
        if local[0] != local[1] and set(local) & DISTINCT_ROLES and (judged is None or judged[0] != judged[1]):
            dropped.append({"slides": [a, b], "reason": reason, "roles": list(local), "judge_roles": list(judged) if judged else None})
        else:
            kept.append((a, b, reason))
    return replace(verdict, same_thesis_pairs=kept, dropped_pairs=dropped)


async def judge_viral_copy(gateway: LLMGateway, prompt_repository: PromptRepository, *, slides: list[Any], caption: str,
                           allowed_evidence: list[str]) -> JudgeVerdict:
    """ONE bounded classification call. Never retried; every failure raises SemanticJudgeUnavailableError."""
    try:
        prompt = prompt_repository.resolve(JUDGE_PROMPT_NAME, JUDGE_PROMPT_VERSION)
    except Exception as exc:
        raise SemanticJudgeUnavailableError(f"semantic judge prompt unavailable: {exc}") from exc
    request = GenerateRequest(
        messages=[Message(role="system", content=[ContentPart(type="text", text=_system_text(prompt))]),
                  Message(role="user", content=[ContentPart(type="text", text=build_judge_input(slides, caption, allowed_evidence))])],
        response_mode="json_schema", response_schema=prompt.output_schema, max_tokens=JUDGE_MAX_OUTPUT_TOKENS,
        reasoning_effort=JUDGE_REASONING_EFFORT,
    )
    runtime = RuntimeContext(task_id=uuid4(), event_id=uuid4(), capability_name=JUDGE_PROMPT_NAME, priority=TaskPriority.S,
                             attempt=1, iteration_count=0)
    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        raise SemanticJudgeUnavailableError(f"semantic judge gateway call failed: {exc}") from exc
    if outcome.error is not None:
        raise SemanticJudgeUnavailableError(f"semantic judge: {outcome.error}")
    response = outcome.response
    if response is None or response.finish_reason == "length":
        raise SemanticJudgeUnavailableError("semantic judge: response truncated at the output cap")
    return apply_role_guard(parse_verdict(response.structured_output, min(len(slides), MAX_SLIDES)), slides)
