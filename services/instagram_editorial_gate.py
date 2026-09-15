"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 13: platform-neutral-where-possible editorial routing
for Instagram output. Does NOT reuse `services/director_editorial_gate.py::EditorialGateInput` -
that contract's own fields (`story_facts_summary`, `is_potential_breaking`,
`feed_topic_distribution`, News category tiers) are shaped for the NEWS ingestion gate, not a
Growth/creative package (section 13's own explicit "do not reuse Telegram-specific objects that
encode Telegram assumptions" instruction). It DOES reuse the one genuinely platform-neutral piece
that already exists: `services/instagram_format_director.py::validate_package_claims()` /
`ClaimViolationError` - restricted-claim enforcement is a business-safety rule, not a Telegram or
News concept.

Outcome vocabulary is the three states section 13 asks for - READY_FOR_EDITOR / HOLD / BLOCK -
deliberately NOT `database/models/director_editorial_decision.py::EditorialGateDecision`'s own
SEND_TO_EDITOR/PRIORITY/BREAKING/HOLD/DROP vocabulary (that enum's BREAKING/PRIORITY concepts are
News-triage concepts an Instagram Growth post does not have)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
import re
from typing import Any

from services.instagram_art_validator import InstagramArtValidationResult
from services.instagram_content_package import InstagramContentPackage
from services.instagram_format_director import ClaimViolationError, validate_package_claims


class InstagramGateDecision(str, enum.Enum):
    READY_FOR_EDITOR = "ready_for_editor"
    HOLD = "hold"
    BLOCK = "block"


@dataclass(frozen=True)
class InstagramGateOutcome:
    decision: InstagramGateDecision
    reason_codes: list[str] = field(default_factory=list)
    short_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"decision": self.decision.value, "reason_codes": list(self.reason_codes), "short_reason": self.short_reason}

    @property
    def permits_publication(self) -> bool:
        """BLOCK/HOLD must never permit the publish adapter to run (section 13's own explicit
        instruction) - only READY_FOR_EDITOR does, and even then the publish adapter still
        requires an explicit human approval signal on top (see services/instagram_publish_adapter.py)."""
        return self.decision is InstagramGateDecision.READY_FOR_EDITOR


def evaluate_instagram_editorial_gate(
    package: InstagramContentPackage, art_result: InstagramArtValidationResult, *, launch_state: str | None = None,
) -> InstagramGateOutcome:
    reasons: list[str] = []

    # 1. Art validation failures are a hard BLOCK - never route unreadable/miscomposed/duplicate-
    #    mark/mismatched content to a human as if it were ready.
    if not art_result.passed:
        reasons.extend(f"art_validation_failed:{issue}" for issue in art_result.blocking_issues)
        return InstagramGateOutcome(
            decision=InstagramGateDecision.BLOCK, reason_codes=reasons,
            short_reason="Art validation failed - " + "; ".join(art_result.blocking_issues[:3]),
        )

    # 2. Draft copy and incomplete Reel scripts are HOLD, never READY_FOR_EDITOR.
    finality_issues = _content_finality_issues(package)
    if finality_issues:
        return InstagramGateOutcome(
            decision=InstagramGateDecision.HOLD, reason_codes=finality_issues,
            short_reason="Content is not final - " + "; ".join(finality_issues[:3]),
        )

    # 3. Restricted-claim re-check (platform-neutral, shared enforcement point) across every
    #    free-text field the package actually carries.
    try:
        validate_package_claims(
            text_fields=package.text_fields_for_claim_check, restricted_claims=package.restricted_claims,
        )
    except ClaimViolationError as exc:
        reasons.append(f"restricted_claim_violation:{exc}")
        return InstagramGateOutcome(decision=InstagramGateDecision.BLOCK, reason_codes=reasons, short_reason=str(exc))

    # 3. Product-mention safety: a not-yet-allowed product mention is a BLOCK, never a soft HOLD.
    if not package.product_mention_allowed and package.restricted_claims:
        for claim in package.restricted_claims:
            if claim and claim.lower() in " ".join(package.text_fields_for_claim_check).lower():
                reasons.append(f"product_mention_not_allowed:{claim}")
                return InstagramGateOutcome(
                    decision=InstagramGateDecision.BLOCK, reason_codes=reasons,
                    short_reason=f"product mention {claim!r} not allowed for this opportunity",
                )

    # 4. Launch-state caution: PRE_LAUNCH/TRANSITION content is real but the account may not exist
    #    yet or be mid-transition - HOLD for explicit human timing judgement, never auto-block (the
    #    content itself is not unsafe, only its TIMING is uncertain).
    if launch_state in ("pre_launch", "transition"):
        reasons.append(f"launch_state:{launch_state}")
        return InstagramGateOutcome(
            decision=InstagramGateDecision.HOLD, reason_codes=reasons,
            short_reason=f"account launch_state={launch_state} - hold for human timing judgement",
        )

    # 5. Non-blocking Art warnings (e.g. a truncated secondary line) still reach the editor - they
    #    are disclosed on the review package, not gated here.
    if art_result.warnings:
        reasons.extend(f"art_warning:{w}" for w in art_result.warnings)

    return InstagramGateOutcome(
        decision=InstagramGateDecision.READY_FOR_EDITOR, reason_codes=reasons,
        short_reason="passed Art validation and claim safety" if not reasons else "passed with non-blocking warnings",
    )


def _subject_is_represented(subject: str, text: str) -> bool:
    if subject.casefold() in text.casefold():
        return True
    tokens = [token for token in re.findall(r"[\w\d]+", subject.casefold()) if len(token) >= 3]
    if not tokens:
        return False
    present = sum(token in text.casefold() for token in set(tokens))
    return present >= min(2, len(set(tokens)))


def _content_finality_issues(package: InstagramContentPackage) -> list[str]:
    issues: list[str] = []
    caption = package.caption.strip()
    if package.caption_is_draft or not caption:
        issues.append("final_caption_missing_or_draft")
    kind = package.content_format.value
    plan = package.media_plan if isinstance(package.media_plan, dict) else {}
    if kind in ("single", "reel"):
        subject = str(plan.get("source_subject") or "").strip()
        if not subject:
            issues.append("source_subject_missing")
        elif caption and subject.casefold() not in caption.casefold():
            issues.append("source_subject_absent_from_caption")
    if kind != "reel":
        return issues
    if package.reel_script_readiness != "production_script":
        issues.append("reel_not_production_script")
    hook = str(plan.get("hook") or "").strip()
    if not hook or hook.casefold() == "null":
        issues.append("reel_hook_missing")
    duration = plan.get("target_duration_seconds")
    if not isinstance(duration, int) or duration <= 0:
        issues.append("reel_duration_missing")
    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or len(scenes) < 2:
        issues.append("reel_timed_scenes_missing")
    else:
        previous_end = 0
        for scene in scenes:
            if not isinstance(scene, dict):
                issues.append("reel_scene_invalid")
                break
            start, end = scene.get("start_seconds"), scene.get("end_seconds")
            if not isinstance(start, int) or not isinstance(end, int) or start != previous_end or end <= start:
                issues.append("reel_scene_timing_invalid")
                break
            if not str(scene.get("spoken_line") or "").strip():
                issues.append("reel_spoken_line_missing")
            if not str(scene.get("visual_direction") or "").strip():
                issues.append("reel_scene_visual_missing")
            previous_end = end
        if isinstance(duration, int) and previous_end != duration:
            issues.append("reel_timing_does_not_cover_duration")
        spoken = " ".join(str(scene.get("spoken_line") or "") for scene in scenes if isinstance(scene, dict))
        subject = str(plan.get("source_subject") or "").strip()
        if subject and not _subject_is_represented(subject, spoken):
            issues.append("source_subject_absent_from_spoken_script")
    if not str(plan.get("loop_ending_concept") or "").strip():
        issues.append("reel_closing_beat_missing")
    return issues
