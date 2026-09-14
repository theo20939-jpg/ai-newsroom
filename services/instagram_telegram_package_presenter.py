"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §7/§8/§15/§16: pure functions turning a real, already-
QA'd `InstagramContentPackage` + its render results into what a human editor should actually see in
Telegram - never a debug dump. No I/O, no database, no aiogram `Bot` call - this module only builds
plain data (bytes + HTML text); `services/instagram_telegram_delivery.py` is the one place that
actually sends anything.

Two artifacts per package:
  - `media`: ordered raw image bytes (§6 CAROUSEL_ORDER_PRESERVED - exactly the render order,
    never re-sorted or re-selected here).
  - `control_text` (+ `overflow_text` only if the caption doesn't fit): the editorial message -
    format label, the COMPLETE final Instagram caption (§16 - never silently truncated), hashtags/
    CTA, and a single compact truthfulness line - never a raw QA object, never internal prompts/
    LLM traces/token counts/database ids (§8).

REEL is presented truthfully (§7/§15): a video is only ever claimed to exist if
`external_video_asset_ref` is actually set (never true anywhere in this codebase today - confirmed
via `services/instagram_platform_renderer.py`, which has no video-rendering function at all) -
otherwise this always renders as "REEL-КОНЦЕПТ" with the real cover image plus the real storyboard/
shot-list/script already captured in `package.media_plan` (never fabricated placeholder content).
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from services.instagram_content_package import InstagramContentPackage
from services.instagram_format_director import ContentFormat
from services.instagram_platform_renderer import InstagramRenderResult

_TELEGRAM_TEXT_LIMIT = 4096
_FORMAT_LABEL = {
    ContentFormat.SINGLE: "INSTAGRAM · ПОСТ",
    ContentFormat.CAROUSEL: "INSTAGRAM · КАРУСЕЛЬ",
    ContentFormat.REEL: "INSTAGRAM · REEL",
}


def _esc(value: str) -> str:
    return html.escape(value, quote=False)


@dataclass(frozen=True)
class InstagramTelegramPresentation:
    kind: str  # "single" | "carousel" | "reel_concept" | "reel_video"
    media: list[bytes]  # already in final, intended order - never re-ordered downstream
    control_text: str  # HTML, always <= _TELEGRAM_TEXT_LIMIT
    overflow_text: str | None  # set only when the full caption did not fit in control_text
    version_label: str


def _truthfulness_line(package: InstagramContentPackage) -> str | None:
    """One compact, honest line - never the full QA/subject-match object. `None` when there is
    nothing meaningfully distinct to say (e.g. a text-only package with no selected media)."""
    if package.media_subject_match is None:
        return None
    labels = {
        "exact_subject": "точное совпадение", "strong_context": "уверенный контекст",
        "generic_context": "обобщённый контекст",
    }
    label = labels.get(package.media_subject_match, package.media_subject_match)
    return f"🔎 Медиа проверено: {label}"


def _caption_block(package: InstagramContentPackage) -> str:
    lines = [_esc(package.caption)]
    if package.hashtags:
        lines.append(" ".join(f"#{_esc(tag.lstrip('#'))}" for tag in package.hashtags))
    if package.cta:
        lines.append(f"CTA: {_esc(package.cta)}")
    return "\n\n".join(lines)


def _split_if_needed(header: str, caption_block: str, footer_lines: list[str]) -> tuple[str, str | None]:
    """Never silently truncates the caption (§16). If `header + caption + footer` fits in one
    Telegram text message, it is sent as one message; otherwise the header/footer stay in
    `control_text` and the COMPLETE caption moves to `overflow_text` as its own message - still
    directly usable by the editor, never lost, never abbreviated."""
    footer = ("\n\n" + "\n".join(footer_lines)) if footer_lines else ""
    combined = f"{header}\n\n{caption_block}{footer}"
    if len(combined) <= _TELEGRAM_TEXT_LIMIT:
        return combined, None
    short = f"{header}\n\n(Полный текст подписи ниже отдельным сообщением ⬇️){footer}"
    return short, caption_block[:_TELEGRAM_TEXT_LIMIT]


def present_single(package: InstagramContentPackage, render: InstagramRenderResult, *, version: int) -> InstagramTelegramPresentation:
    header = f"🖼 <b>{_FORMAT_LABEL[ContentFormat.SINGLE]}</b> · v{version}"
    footer = [line for line in (_truthfulness_line(package),) if line]
    control_text, overflow = _split_if_needed(header, _caption_block(package), footer)
    return InstagramTelegramPresentation(
        kind="single", media=[render.image_bytes], control_text=control_text, overflow_text=overflow,
        version_label=f"v{version}",
    )


def present_carousel(package: InstagramContentPackage, renders: list[InstagramRenderResult], *, version: int) -> InstagramTelegramPresentation:
    """§15 CAROUSEL_ORDER_PRESERVED: `renders` must already be in final slide order (exactly what
    `services.instagram_platform_renderer.render_instagram_carousel()` returns) - this function
    never sorts, reverses, or re-selects them."""
    header = f"🖼 <b>{_FORMAT_LABEL[ContentFormat.CAROUSEL]}</b> · v{version} ({len(renders)} слайдов)"
    footer = [line for line in (_truthfulness_line(package),) if line]
    control_text, overflow = _split_if_needed(header, _caption_block(package), footer)
    return InstagramTelegramPresentation(
        kind="carousel", media=[r.image_bytes for r in renders], control_text=control_text, overflow_text=overflow,
        version_label=f"v{version}",
    )


def present_caption_only(package: InstagramContentPackage, *, version: int) -> InstagramTelegramPresentation:
    """§10 "📝 Текст": no render exists for this presentation call at all - `media` is always `[]`.
    The caller (`services.instagram_telegram_delivery.deliver_text_only_new_version()`) never sends
    fresh media for this presentation; it only sends `control_text`/`overflow_text` as a reply to
    the ALREADY-delivered image(s) from the previous version."""
    header = f"📝 <b>ОБНОВЛЁН ТЕКСТ</b> · v{version}"
    footer = [line for line in (_truthfulness_line(package),) if line]
    control_text, overflow = _split_if_needed(header, _caption_block(package), footer)
    return InstagramTelegramPresentation(kind="text_update", media=[], control_text=control_text, overflow_text=overflow, version_label=f"v{version}")


def present_reel(package: InstagramContentPackage, cover: InstagramRenderResult, *, version: int) -> InstagramTelegramPresentation:
    """Truthful REEL presentation (§7/§15). `package.external_video_asset_ref` is the ONLY signal
    this function trusts for "a real video exists" - never inferred from anything else, never
    assumed. Today that field is always `None` in this codebase (no video-rendering capability
    exists), so this always takes the REEL-КОНЦЕПТ branch - disclosed here, not hidden."""
    has_real_video = bool(package.external_video_asset_ref)
    plan = package.media_plan if isinstance(package.media_plan, dict) else {}

    if has_real_video:
        header = f"🎬 <b>{_FORMAT_LABEL[ContentFormat.REEL]}</b> · v{version}"
        kind = "reel_video"
    else:
        header = f"🎬 <b>{_FORMAT_LABEL[ContentFormat.REEL]}-КОНЦЕПТ</b> · v{version} (видео ещё не создано)"
        kind = "reel_concept"

    storyboard_lines: list[str] = []
    hook = plan.get("hook")
    if hook:
        storyboard_lines.append(f"<b>Хук:</b> {_esc(str(hook))}")
    scenes = plan.get("scene_sequence") or []
    if scenes:
        storyboard_lines.append("<b>Сценарий:</b>")
        storyboard_lines.extend(f"{i}. {_esc(str(s))}" for i, s in enumerate(scenes, start=1))
    shot_list = plan.get("shot_list") or []
    if shot_list:
        storyboard_lines.append("<b>Кадры:</b> " + "; ".join(_esc(str(s)) for s in shot_list))
    voiceover = plan.get("voiceover_script")
    if voiceover:
        storyboard_lines.append(f"<b>Закадровый текст:</b> {_esc(str(voiceover))}")
    duration = plan.get("target_duration_seconds")
    if duration:
        storyboard_lines.append(f"<b>Длительность:</b> ~{duration} сек")

    footer_lines = storyboard_lines + [line for line in (_truthfulness_line(package),) if line]
    control_text, overflow = _split_if_needed(header, _caption_block(package), footer_lines)
    return InstagramTelegramPresentation(
        kind=kind, media=[cover.image_bytes], control_text=control_text, overflow_text=overflow,
        version_label=f"v{version}",
    )
