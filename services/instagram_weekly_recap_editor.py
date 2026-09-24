"""KAGE weekly recap editor: ONE LLM editorial selection call over a deterministic, recall-oriented candidate set.

Deterministic (here and in services/instagram_weekly_recap.py): candidate collection on production Story identity, eligibility,
evidence, Story references, outlet coverage, duplicate suppression (confirmed membership + `consolidate()`), and the daily-overlap
facts. The LLM only decides which of those candidates defined the week, which candidate ids are the same real-world event (an
editorial merge for this recap only - never written back to Story identity), and why. Every answer is checked against the candidate
set: an item citing an unknown or reused id, repeating a daily post, or stating a number no cited candidate carries is dropped,
never repaired by guessing.

Why a recall-oriented candidate set and not the coverage rank alone: production Story Memory fragments one event into many one-outlet
Stories (a Galaxy Z Fold 8 week is twenty fragments of coverage 1; the OpenAI speaker leak is "puck-sized", "doughnut-shaped" and
"ring-shaped" in six one-outlet Stories), so a coverage-only cut loses whole defining stories. A candidate is therefore also ranked by
its ECHO: the outlets that carried the same headline words within two days. The echo only decides which candidates the editor gets to
read - it never merges anything, and it is never written back to Story identity.

FROZEN 2026-09-24 (founder-accepted): prompt v2, gpt-5.6-terra, reasoning medium, max_tokens 8000. Known accepted limitations -
monitoring items, not blockers, deliberately NOT tuned against the validation week:
  1. the v2 calibration was validated on ONE historical week (5-11 Aug 2026), and its principles were written from that week;
  2. that week, Galaxy Z Fold 8 was an obvious miss (7 stories returned, slot 8 left empty);
  3. rogue AI agents and OpenAI's Astra safety response were not consolidated into one broader story;
  4. the Meta Muse item merged 10 candidates - broad, but one launch week of one product family;
  5. weekly selection quality must keep being observed on real future weeks (`instagram_weekly_recap_editor_call` logs)."""
from __future__ import annotations

import html
import logging
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

from capabilities.gateway_call import call_generate
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, LLMGateway, Message
from integrations.prompts.protocol import PromptRepository
from schemas.capability import RuntimeContext
from services.instagram_feed_product import OUTSIDE_WORLD_REASON, FeedFormat, recap_category
from services.instagram_weekly_recap import _CYRILLIC, RecapItem, _item_read
from services.text_normalization import normalize_story_identity_title

logger = logging.getLogger(__name__)

EDITOR_PROMPT_NAME = "instagram_weekly_recap_editor"
EDITOR_PROMPT_VERSION = "2"
# the founder-accepted runtime (validated 2026-09-24 on 5-11 Aug 2026: terra, medium reasoning, 8000 -> finish=stop, 2,459 output tokens
# incl. 1,552 reasoning, $0.062). Reasoning counts against this budget: 3000 truncated once. Instagram weekly editor ONLY.
EDITOR_MAX_TOKENS = 8000
# editorial judgment, not the router's lowest-cost pick: the strongest configured model whose worst case fits the weekly cap
# (gpt-5.6-sol cannot: ~10k input tokens alone are ~$0.05); the preference is advisory - the router still owns the choice
EDITOR_PREFERRED_MODEL = "gpt-5.6-terra"
EDITOR_REASONING_EFFORT = "medium"
EDITOR_MAX_ITEMS = 8

CULTURE_MIN_COVERAGE = 3  # an item outside the daily feed's world (games, streaming) enters only when several outlets carried it
ECHO_DF_MAX = 40  # a headline word on more of the week's items than this is a subject (OpenAI, Google), never an echo
ECHO_SHARED = 3
ECHO_STEM = 6
ECHO_WINDOW = timedelta(days=2)
ECHO_LINES_MAX = 2
CANDIDATE_CHAR_BUDGET = 27_000
EVIDENCE_TOP = 25
HEADLINE_CHARS = 110
ALT_TITLE_CHARS = 80
EVIDENCE_CHARS = 140
EVIDENCE_SHARED = 2
OUTLETS_SHOWN = 3

CATEGORIES = ("AI", "GADGET", "VIRAL")
DAILY_OVERLAP = ("NONE", "DIFFERENT_ANGLE", "REPEAT")
_DIGITS = re.compile(r"\d+")


class WeeklyRecapEditorError(RuntimeError):
    """The editor call failed or answered outside its contract - the caller falls back to the deterministic recap. `call` is the
    provider call when one was made (a truncated or unparseable answer is still paid for), so the spend can always be recorded."""

    def __init__(self, message: str, *, call: Any = None) -> None:
        super().__init__(message)
        self.call = call


@dataclass(frozen=True)
class EditorCandidate:
    candidate_id: str
    item: RecapItem
    category_hint: str  # AI / GADGET / VIRAL from the headline read, CULTURE for a widely carried story outside the daily feed's world
    daily_premise: str | None = None  # the exact premise of the daily post this very story already was
    evidence: str | None = None

    @property
    def headline(self) -> str:
        return self.item.headline

    @property
    def alt_title(self) -> str | None:
        """One headline in the other language (the Russian copy of an English story), when the item has one."""
        english = not _CYRILLIC.search(self.headline)
        return next((t for t in self.item.titles if bool(_CYRILLIC.search(t)) == english), None)


@dataclass(frozen=True)
class EditorPick:
    rank: int
    primary: EditorCandidate
    merged: tuple[EditorCandidate, ...]  # every cited candidate, the primary first
    weekly_premise: str
    category: str
    why_this_made_the_week: str
    why_now: str
    daily_overlap: str
    strongest_alternative_beaten: str = ""

    @property
    def coverage(self) -> int:
        return len(frozenset().union(*(c.item.sources for c in self.merged)))


@dataclass(frozen=True)
class EditorResult:
    picks: tuple[EditorPick, ...]
    dropped: tuple[str, ...]  # contract violations, one line each - never silently repaired
    daily_exclusions: tuple[tuple[tuple[str, ...], str], ...]


def _category_hint(item: RecapItem) -> str | None:
    candidate, read = _item_read(item)
    if read.format is FeedFormat.REJECT:
        return "CULTURE" if read.reason == OUTSIDE_WORLD_REASON and item.coverage >= CULTURE_MIN_COVERAGE else None
    category = recap_category(candidate, read)
    if category == "OTHER":
        return "CULTURE" if item.coverage >= CULTURE_MIN_COVERAGE else None
    return category


_WORD = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9+'’-]{3,}", re.IGNORECASE)
_ECHO_STOP = frozenset("that this with from have will your about after over what when their they just into more than been were says said "
                       "here heres how new review best deals deal".split())


def _words(text: str) -> frozenset[str]:
    return frozenset(w.lower()[:ECHO_STEM] for w in _WORD.findall(text) if w.lower() not in _ECHO_STOP)


def _stems(item: RecapItem) -> frozenset[str]:
    return frozenset().union(*(_words(normalize_story_identity_title(t)) for t in item.titles))


def _echo(eligible: Sequence[RecapItem]) -> list[tuple[int, frozenset[int]]]:
    """Per item: the outlets carrying the same headline words within ECHO_WINDOW (ECHO_SHARED+ shared word stems, none of them a
    week-wide subject word), and those neighbours. A RANKING signal for recall only - it never merges anything."""
    stems = [_stems(item) for item in eligible]
    df = Counter(s for ss in stems for s in ss)
    postings: dict[str, list[int]] = {}
    for i, ss in enumerate(stems):
        for stem in ss:
            if df[stem] <= ECHO_DF_MAX:
                postings.setdefault(stem, []).append(i)
    first = [min(s.first_seen for s in item.stories) for item in eligible]
    out = []
    for i, ss in enumerate(stems):
        shared = Counter(j for stem in ss if df[stem] <= ECHO_DF_MAX for j in postings[stem] if j != i)
        near = frozenset(j for j, n in shared.items() if n >= ECHO_SHARED and abs(first[j] - first[i]) <= ECHO_WINDOW)
        out.append((len(eligible[i].sources.union(*(eligible[j].sources for j in near))), near))
    return out


def build_editor_candidates(
    items: Sequence[RecapItem], *, daily_premise_by_story: Mapping[str, str] | None = None,
    char_budget: int = CANDIDATE_CHAR_BUDGET,
) -> list[EditorCandidate]:
    """The week's candidates for the editor, strongest first by max(outlets, echo outlets), until the rendered list reaches
    `char_budget`. A single-outlet fragment is skipped once ECHO_LINES_MAX of its echo neighbours are already listed, so one busy
    thread never floods the list. Items only aggregators carried are not listed. Deterministic: same items, same list."""
    daily = dict(daily_premise_by_story or {})
    eligible = [(item, hint) for item in items if item.coverage >= 1 and (hint := _category_hint(item)) is not None]
    echo = _echo([item for item, _ in eligible])
    order = sorted(range(len(eligible)), key=lambda i: (-max(eligible[i][0].coverage, echo[i][0]), -eligible[i][0].coverage,
                                                         eligible[i][0].headline))
    listed: set[int] = set()
    out: list[EditorCandidate] = []
    size = 0
    for i in order:
        item, hint = eligible[i]
        if item.coverage < 2 and len(echo[i][1] & listed) >= ECHO_LINES_MAX:
            continue
        premise = next((daily[sid] for sid in sorted(item.story_ids) if sid in daily), None)
        candidate = EditorCandidate(candidate_id=f"C{len(out) + 1:03d}", item=item, category_hint=hint, daily_premise=premise)
        line = render_candidate(candidate)
        if size + len(line) > char_budget:
            break
        size += len(line)
        listed.add(i)
        out.append(candidate)
    return out


def attach_evidence(candidates: Sequence[EditorCandidate], evidence_by_story: Mapping[str, str], *, top: int = EVIDENCE_TOP) -> list[EditorCandidate]:
    """Stored evidence for the strongest `top` candidates: the body of the Story fragment the headline comes from, and only when it
    shares EVIDENCE_SHARED+ headline words - a Story with a polluted membership must not hand the editor another event's text."""
    out = []
    for index, candidate in enumerate(candidates):
        story = next((s for s in candidate.item.stories if candidate.headline in s.titles), None)
        body = _plain(evidence_by_story.get(story.story_id) or "") if story is not None and index < top else ""
        on_topic = bool(body) and len(_words(normalize_story_identity_title(candidate.headline)) & _words(body)) >= EVIDENCE_SHARED
        out.append(replace(candidate, evidence=body if on_topic else None))
    return out


def _plain(text: str) -> str:
    """Stored bodies are often feed HTML: tags, entities and links are not evidence."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(re.sub(r"https?://\S+", " ", text).split())


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def render_candidate(candidate: EditorCandidate) -> str:
    """One compact block: `C001 AI | 5 outlets: A, B, C +2 | EN+RU | 9 fr | headline`, then the other-language headline, the stored
    evidence and the daily post this very story already was, each only when it exists."""
    item = candidate.item
    names = sorted(item.sources)
    shown = ", ".join(names[:OUTLETS_SHOWN]) + (f" +{len(names) - OUTLETS_SHOWN}" if len(names) > OUTLETS_SHOWN else "")
    lines = [f"{candidate.candidate_id} {candidate.category_hint} | {item.coverage} outlets: {shown or '-'} | "
             f"{'+'.join(sorted(item.languages))} | {len(item.stories)} fr | {_clip(candidate.headline, HEADLINE_CHARS)}"]
    if candidate.alt_title:
        lines.append(f"  also: {_clip(candidate.alt_title, ALT_TITLE_CHARS)}")
    if candidate.evidence:
        lines.append(f"  evidence: {_clip(candidate.evidence, EVIDENCE_CHARS)}")
    if candidate.daily_premise:
        lines.append(f"  DAILY=YES: {_clip(candidate.daily_premise, 90)}")
    return "\n".join(lines) + "\n"


def render_editor_input(candidates: Sequence[EditorCandidate], *, daily_premises: Sequence[str], week_label: str) -> str:
    daily = "\n".join(f"D{i}: {_clip(p, 140)}" for i, p in enumerate(daily_premises, 1)) or "(none)"
    return (f"WEEK: {week_label}\n\nDAILY POSTS THIS WEEK (already published on KAGE):\n{daily}\n\n"
            f"CANDIDATES ({len(candidates)}; id + category hint | unique outlets | languages | number of Story fragments | headline; "
            "then, when they exist: the headline in the other language, stored evidence, DAILY=YES with the daily post this very story "
            "was - every other candidate is DAILY=NO):\n" + "".join(render_candidate(c) for c in candidates))


def build_editor_request(prompt: Any, candidates: Sequence[EditorCandidate], *, daily_premises: Sequence[str], week_label: str) -> GenerateRequest:
    return GenerateRequest(
        messages=[
            Message(role="system", content=[ContentPart(type="text", text=prompt.system + "\n\nRULES:\n" + "\n".join(f"- {r}" for r in prompt.rules))]),
            Message(role="user", content=[ContentPart(type="text", text=render_editor_input(candidates, daily_premises=daily_premises, week_label=week_label))]),
        ],
        response_mode="json_schema", response_schema=prompt.output_schema, max_tokens=EDITOR_MAX_TOKENS,
        reasoning_effort=EDITOR_REASONING_EFFORT, preferred_model=EDITOR_PREFERRED_MODEL,
    )


def _grounding_text(merged: Iterable[EditorCandidate]) -> str:
    return " ".join(" ".join(c.item.titles) + " " + (c.evidence or "") for c in merged)


def validate_editor_output(output: Any, candidates: Sequence[EditorCandidate]) -> EditorResult:
    """The contract, checked item by item. A malformed answer as a whole raises; one bad item is dropped with its reason."""
    if not isinstance(output, dict) or not isinstance(output.get("items"), list):
        raise WeeklyRecapEditorError("editor answer has no items list")
    raw = output["items"]
    if len(raw) > EDITOR_MAX_ITEMS:
        raise WeeklyRecapEditorError(f"editor returned {len(raw)} items (max {EDITOR_MAX_ITEMS})")
    by_id = {c.candidate_id: c for c in candidates}
    used: set[str] = set()
    picks: list[EditorPick] = []
    dropped: list[str] = []
    for entry in sorted(raw, key=lambda e: e.get("rank", 0) if isinstance(e, dict) and isinstance(e.get("rank"), int) else 0):
        if not isinstance(entry, dict):
            dropped.append("an item that is not an object")
            continue
        label = f"rank {entry.get('rank')}"
        primary = entry.get("primary_candidate_id")
        cited = entry.get("merged_candidate_ids") if isinstance(entry.get("merged_candidate_ids"), list) else []
        ids = list(dict.fromkeys([primary, *cited]))
        texts = [entry.get(k) for k in ("weekly_premise", "why_this_made_the_week", "why_now")]
        if unknown := [i for i in ids if i not in by_id]:
            dropped.append(f"{label}: unknown candidate id(s) {unknown}")
        elif reused := [i for i in ids if i in used]:
            dropped.append(f"{label}: candidate id(s) {reused} already used by a higher-ranked item")
        elif entry.get("category") not in CATEGORIES or entry.get("daily_overlap") not in DAILY_OVERLAP:
            dropped.append(f"{label}: category / daily_overlap outside the contract")
        elif not all(isinstance(t, str) and t.strip() for t in texts):
            dropped.append(f"{label}: empty premise or reason")
        elif entry["daily_overlap"] == "REPEAT":
            dropped.append(f"{label}: the editor marked it an exact repeat of a daily post")
        elif entry["daily_overlap"] == "NONE" and any(by_id[i].daily_premise for i in ids):
            dropped.append(f"{label}: cites a daily post's own story but claims no daily overlap")
        elif stray := sorted(set(_DIGITS.findall(entry["weekly_premise"])) - set(_DIGITS.findall(_grounding_text(by_id[i] for i in ids)))):
            dropped.append(f"{label}: premise number(s) {stray} carried by no cited candidate")
        else:
            used.update(ids)
            merged = tuple(by_id[i] for i in ids)
            picks.append(EditorPick(
                rank=len(picks) + 1, primary=merged[0], merged=merged, weekly_premise=entry["weekly_premise"].strip(),
                category=entry["category"], why_this_made_the_week=entry["why_this_made_the_week"].strip(),
                why_now=entry["why_now"].strip(), daily_overlap=entry["daily_overlap"],
                strongest_alternative_beaten=str(entry.get("strongest_alternative_beaten") or "").strip(),
            ))
    exclusions = tuple(
        (tuple(str(i) for i in e.get("candidate_ids") or []), str(e.get("reason") or ""))
        for e in output.get("daily_overlap_exclusions") or [] if isinstance(e, dict)
    )
    return EditorResult(picks=tuple(picks), dropped=tuple(dropped), daily_exclusions=exclusions)


def _call_cost(call: Any) -> str | None:
    """The project's one cost formula (services/cost_tracker.py::compute_call_cost) over the static model catalog - never a guess."""
    if call is None:
        return None
    try:
        from integrations.llm_gateway.models.catalog import build_model_registry
        from services.cost_tracker import compute_call_cost
        from services.pricing_catalog import ModelRegistryPricingCatalog

        return str(compute_call_cost(call, ModelRegistryPricingCatalog(build_model_registry())))
    except Exception:  # noqa: BLE001 - observability must never break the recap; the missing figure is logged as None
        return None


def log_editor_call(request: GenerateRequest, call: Any, response: Any, *, valid: bool, error: str | None = None,
                    picks: int | None = None, dropped: int | None = None) -> dict:
    """One structured record per weekly-editor provider call, success or failure: model, reasoning, budget, token usage, finish
    reason, actual cost and whether the structured output was accepted."""
    usage = getattr(call, "usage", None)
    record = {
        "model": getattr(call, "model_used", None) or getattr(response, "model_used", None) or request.preferred_model,
        "reasoning_effort": request.reasoning_effort, "max_tokens": request.max_tokens,
        "input_tokens": getattr(usage, "input_tokens", None), "reasoning_tokens": getattr(usage, "reasoning_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None), "finish_reason": getattr(response, "finish_reason", None),
        "actual_cost_usd": _call_cost(call), "structured_output_valid": valid, "picks": picks, "dropped": dropped,
        "error": error[:300] if error else None,
    }
    (logger.info if valid else logger.warning)("instagram_weekly_recap_editor_call", extra=record)
    return record


async def run_weekly_recap_editor(
    gateway: LLMGateway, prompt_repository: PromptRepository, *, candidates: Sequence[EditorCandidate],
    daily_premises: Sequence[str], week_label: str,
) -> tuple[EditorResult, Any]:
    """Exactly one provider call (sequence 0, no retry here). Raises WeeklyRecapEditorError on any failure."""
    if not candidates:
        raise WeeklyRecapEditorError("no candidates")
    try:
        prompt = prompt_repository.resolve(EDITOR_PROMPT_NAME, EDITOR_PROMPT_VERSION)
    except Exception as exc:
        raise WeeklyRecapEditorError(f"prompt unavailable: {exc}") from exc
    request = build_editor_request(prompt, candidates, daily_premises=daily_premises, week_label=week_label)
    runtime = RuntimeContext(
        task_id=uuid4(), event_id=uuid4(), capability_name=EDITOR_PROMPT_NAME, priority=TaskPriority.S, attempt=1, iteration_count=0,
    )
    try:
        outcome = await call_generate(gateway, request, runtime=runtime, sequence=0)
    except Exception as exc:
        log_editor_call(request, None, None, valid=False, error=f"gateway call failed: {exc}")
        raise WeeklyRecapEditorError(f"gateway call failed: {exc}") from exc
    call = getattr(outcome, "call", None)
    response = outcome.response
    try:
        if outcome.error is not None:
            raise WeeklyRecapEditorError(str(outcome.error), call=call)
        if response is not None and response.finish_reason == "length":  # first: a truncated answer also has no structured output
            raise WeeklyRecapEditorError("answer truncated at the token limit (reasoning + answer exceeded max_tokens)", call=call)
        if response is None or response.structured_output is None:
            raise WeeklyRecapEditorError(
                f"no structured output returned (finish_reason={getattr(response, 'finish_reason', None)})", call=call)
        try:
            result = validate_editor_output(response.structured_output, candidates)
        except WeeklyRecapEditorError as exc:
            raise WeeklyRecapEditorError(str(exc), call=call) from exc
    except WeeklyRecapEditorError as exc:
        log_editor_call(request, call, response, valid=False, error=str(exc))
        raise
    log_editor_call(request, call, response, valid=True, picks=len(result.picks), dropped=len(result.dropped))
    return result, call
