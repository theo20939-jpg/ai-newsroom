"""Phase B.5.1: deterministic PROFILE of a real post asset, told to the Creative Director so it plans visual families the media can
honestly support (and never fakes media). Measured from the actual pixels with the SAME functions the renderer uses:

  * immersive_image_field  - the quiet-zone measurement (services/instagram_quiet_zones.py) on the image fitted to the slide canvas,
                             at several crops: which named text zone is calm and high-contrast, and at what crop focus
  * hero_object_stage      - uniform ground (or real alpha) => the object can be staged by its measured extent
  * internet_culture_collage - a fragment source; a collage needs three or more media regions (crops of one image are allowed)
  * dark_type_number_statement / interface_cards / light_utility_editorial - never need media

No ML, no provider call. The text lines are advisory guidance; the renderer still validates every plan and fails closed."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from PIL import Image

from services.instagram_declarative_layout import _object_bbox, ground_of
from services.instagram_image_handling import fit_image_cover
from services.instagram_quiet_zones import NAMED_ZONES, select_text_zone
from services.instagram_visual_profiles import INSTAGRAM_RENDER_PROFILES, InstagramRenderProfile

_SPEC = INSTAGRAM_RENDER_PROFILES[InstagramRenderProfile.CAROUSEL_SLIDE]
_CROP_FOCI = (0.1, 0.3, 0.5, 0.7, 0.9)
_MIN_SIDE = 640
_MAX_OPTIONS = 3
FLAT_GRAPHIC_MAX_DOMINANT_COLOURS = 12  # <= this many 4-bit colours cover 90% of the pixels: a flat article / text / social card, not a photograph or object
LOGO_ZONE_RIGHT = (0.83, 0.82, 0.94, 0.93)


@dataclass(frozen=True)
class ImmersiveOption:
    focus_x: float
    zone: str
    box: tuple[float, float, float, float]
    text_colour: str


@dataclass(frozen=True)
class AssetProfile:
    subject_key: str
    width: int
    height: int
    tone: str                      # dark | mid | light
    has_alpha: bool
    uniform_ground: bool
    ground_is_dark: bool
    object_share: float            # measured object area / image area (1.0 = no isolated object)
    immersive_options: tuple[ImmersiveOption, ...] = field(default_factory=tuple)
    dominant_colours_90: int = 999

    @property
    def suitable_for_final_visual(self) -> bool:
        """Phase B.6 SOURCE_SUITABLE_FOR_FINAL_VISUAL. Deterministic, no OCR: a flat few-colour image is almost always an article / headline / social
        card whose main content is baked-in text. A false 'unsuitable' is safe (a contextual visual is generated instead)."""
        return self.dominant_colours_90 > FLAT_GRAPHIC_MAX_DOMINANT_COLOURS

    @property
    def hero_ready(self) -> bool:
        return self.has_alpha or (self.uniform_ground and 0.06 <= self.object_share <= 0.92)

    @property
    def immersive_ready(self) -> bool:
        return bool(self.immersive_options)

    def compatible_families(self, *, pool_size: int) -> list[str]:
        families: list[str] = []
        if self.immersive_ready:
            families.append("immersive_image_field")
        if self.hero_ready:
            families.append("hero_object_stage")
        families.append("internet_culture_collage")  # as fragment / crops - the plan must still hold 3+ media regions
        return families


def dominant_colours_90(rgb: Image.Image) -> int:
    small = rgb.resize((96, 96), Image.Resampling.BOX)
    counts = Counter((r >> 4, g >> 4, b >> 4) for r, g, b in small.getdata())
    total, acc = sum(counts.values()), 0
    for used, (_colour, k) in enumerate(counts.most_common(), start=1):
        acc += k
        if acc >= 0.90 * total:
            return used
    return len(counts)


def profile_asset(image: Image.Image, *, subject_key: str) -> AssetProfile:
    rgb = image.convert("RGB")
    has_alpha = image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 250
    small = rgb.resize((48, 48))
    lumas = [sum(px) / 3 for px in small.getdata()]
    mean = sum(lumas) / len(lumas)
    tone = "dark" if mean < 85 else "light" if mean > 170 else "mid"
    ground, std = ground_of(rgb)
    uniform = std <= 10.0
    box = _object_bbox(image if has_alpha else rgb)
    share = ((box[2] - box[0]) * (box[3] - box[1])) / max(1, rgb.width * rgb.height)
    options: list[ImmersiveOption] = []
    if min(rgb.size) >= _MIN_SIDE:
        seen: set[str] = set()
        for fx in _CROP_FOCI:
            fitted = fit_image_cover(rgb, width=_SPEC.width, height=_SPEC.height, focus_x=fx, focus_y=0.5).image
            selection = select_text_zone(fitted, avoid=LOGO_ZONE_RIGHT, subject_focus=(fx, 0.5))
            if selection.selected is not None and selection.selected.name not in seen:
                seen.add(selection.selected.name)
                options.append(ImmersiveOption(fx, selection.selected.name, tuple(round(v, 3) for v in NAMED_ZONES[selection.selected.name]),
                                               str(selection.selected.text_colour)))
            if len(options) >= _MAX_OPTIONS:
                break
    return AssetProfile(subject_key, rgb.width, rgb.height, tone, has_alpha, uniform, sum(ground) / 3 < 60,
                        round(min(1.0, share), 2), tuple(options), dominant_colours_90(rgb))


def render_profile_lines(profile: AssetProfile, *, pool_size: int, allowed_functions: str, include_suitability: bool = False,
                         suitable_override: bool | None = None) -> str:
    """`suitable_override`: a narrower verdict about this image (services.instagram_source_suitability) replacing the deterministic one."""
    families = profile.compatible_families(pool_size=pool_size)
    suitable = profile.suitable_for_final_visual if suitable_override is None else suitable_override
    if include_suitability and not suitable:
        return (f"subject key '{profile.subject_key}': SOURCE_AVAILABLE: yes. SOURCE_SUITABLE_FOR_FINAL_VISUAL: NO - a flat article / text / social card whose content is "
                "baked-in text. Keep it as evidence only: do NOT use it as a hero, an immersive field or a primary image, and do not plan text on it. Plan a GENERATED "
                "contextual visual for this subject instead (it may appear only as a small supporting collage fragment when that genuinely helps).")
    lines = [
        f"subject key '{profile.subject_key}': REAL image {profile.width}x{profile.height}, tone={profile.tone} (valid media_function: {allowed_functions}). "
        f"Families this image can honestly support: {', '.join(families)}."
    ]
    if include_suitability:
        lines[0] = lines[0].replace(": REAL image", ": SOURCE_AVAILABLE: yes. SOURCE_SUITABLE_FOR_FINAL_VISUAL: yes. REAL image", 1)
    if profile.immersive_ready:
        opts = "; ".join(
            f"crop focus_x={o.focus_x} -> calm text zone '{o.zone}' box x={o.box[0]} y={o.box[1]} w={o.box[2]} h={o.box[3]} ({o.text_colour} type)"
            for o in profile.immersive_options
        )
        lines.append(f"  immersive_image_field: full-canvas media region + on_media text ONLY inside a calm zone: {opts}.")
    else:
        lines.append("  immersive_image_field: NOT available (no calm, high-contrast text zone at any tested crop) - do not plan text on this image.")
    if profile.hero_ready:
        lines.append(f"  hero_object_stage: available - uniform {'dark' if profile.ground_is_dark else 'light'} ground, the object is about "
                     f"{int(profile.object_share * 100)}% of the frame (use a media_ground surface + object_contain/object_cover).")
    else:
        lines.append("  hero_object_stage: NOT available (no isolated object on a uniform ground or alpha) - do not stage it as an object.")
    lines.append("  internet_culture_collage: only as one fragment among 3+ media regions (crops of this same image at different focus/scale are allowed).")
    return "\n".join(lines)
