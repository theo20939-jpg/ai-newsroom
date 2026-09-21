"""Phase B.5R: Visual DNA v2 authored from a DIRECT, sample-by-sample visual reading of the reference board
pixels (the 20 segmented samples), used because the planned multimodal analysis call (prompt v3) was
SAFE-STOPPED by the production budget preflight (ledger over the daily budget; nothing was bypassed or
raised). Provenance is recorded in `analysis_model`/`analysis_prompt_version`. The v3 analysis path
(`services/instagram_reference_analysis.py::analyze_reference_samples`) stays ready to cross-check this
reading once budget allows; it is not required for the reconstruction.

Usage: python scripts/_instagram_phase_b5r_manual_dna_v2.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.instagram_reference_analysis import prepare_reference_image  # noqa: E402
from services.instagram_visual_dna import DNA_DIR, REFERENCE_BOARD_PATH  # noqa: E402
from services.instagram_visual_dna_v2 import (  # noqa: E402
    InstagramVisualDNAV2,
    assert_v2_mechanics_only,
    render_visual_dna_v2_markdown,
)

# id, surface, lead, headline, body, width, align, type_is_main, media_kind, regions, dominance, density, symmetry,
# crop_and_media_relation, spatial_composition, devices, accent_use, tension
_S = [
    ("S01", "dark_image_field", "balanced", "large", "small", "narrow", "left", False, "photograph", 1, "balanced", "medium", "asymmetric",
     "A dark portrait photograph bleeds off the left edge and is cropped through the face; the subject looks toward the copy column.",
     "Two columns: the cropped portrait holds roughly the left two fifths, a stacked headline sits in the dark right column; brand mark bottom-left.",
     ["small red kicker label above the headline", "short red slash stroke near the bottom"], "Red used only for the kicker and one stroke; everything else white on black.",
     "Face crop against a tall stacked headline; strong scale contrast between headline and caption."),
    ("S02", "dark_solid", "balanced", "huge", "small", "medium", "left", True, "isolated_object", 2, "balanced", "medium", "asymmetric",
     "A black studio object is cropped hard by the right edge on a black ground; a small secondary silhouette sits low.",
     "One giant red numeral top-left, a medium white headline beneath it, the object filling the right half and leaving the lower-left dark and empty.",
     ["giant accent numeral leading the headline", "small accent year line"], "Red for the numeral and one short line; headline stays white.",
     "Numeral scale against a moderate headline, and a heavy object mass against a dark void."),
    ("S03", "dark_image_field", "media", "large", "small", "medium", "left", False, "illustration", 1, "dominant", "low", "asymmetric",
     "A red-lit night cityscape fills the whole frame with a road vanishing to a point at the bottom; nothing is boxed.",
     "Headline stacked top-left inside the darkest sky zone, a light subline below it, the vanishing point low and central, brand mark bottom-left.",
     ["small subline under the headline"], "The red is part of the scene lighting, echoed once by nothing else.",
     "Deep perspective against a stacked headline in a quiet zone of the scene."),
    ("S04", "dark_solid", "media", "small", "small", "narrow", "left", False, "isolated_object", 1, "balanced", "low", "asymmetric",
     "A single hardware object with a soft glow sits isolated on an almost pure black ground, cropped by nothing.",
     "The object floats in the upper-middle; a tiny caption stack sits bottom-left; everything else is empty black.",
     ["tiny two-line caption"], "No accent colour at all; the glow on the object is the only light.",
     "A small bright object against a very large black void."),
    ("S05", "dark_solid", "type", "large", "small", "narrow", "left", True, "illustration", 1, "minor", "medium", "asymmetric",
     "A small red smoke-like texture fragment sits in the top-right corner of a black ground and does not touch the copy.",
     "A red kicker label, a white two-line headline, a giant red numeral and a red subline stack in one left column.",
     ["red kicker label", "giant accent numeral", "accent subline"], "Red is used three times in one column; the texture fragment adds a fourth red mass.",
     "White headline above a giant red numeral; the smoke fragment breaks the black."),
    ("S06", "dark_image_field", "media", "medium", "medium", "wide", "left", False, "photograph", 1, "dominant", "high", "asymmetric",
     "A dark photo of a surprised face fills the middle of the frame; hand-drawn marks are drawn around and over the head area.",
     "A wide two-line headline at the top, the face in the middle, a coloured highlight caption low, brand mark bottom-left.",
     ["hand-drawn doodle marks (arrows, crowns, scribbles)", "coloured highlight caption"], "Yellow and pink hand-drawn marks and a yellow caption on dark.",
     "A serious face against playful hand-drawn marks."),
    ("S07", "light", "balanced", "large", "medium", "wide", "left", True, "collage_fragments", 5, "balanced", "high", "asymmetric",
     "Layered torn-paper pieces and a paper backdrop carry scribbles; two round sticker badges sit bottom-left.",
     "A large dark-red numeral and a condensed headline sit centre on the paper stack; a pink label chip carrying the brand mark bottom-right, an arrow cue at the corner.",
     ["torn-paper layers", "round sticker badges", "scribbled marks", "label chip with the brand mark"], "Multi-colour scribbles, one hot pink chip, a dark-red numeral.",
     "Layered rough paper edges and marks against a clean condensed type voice."),
    ("S08", "dark_solid", "balanced", "large", "small", "wide", "left", False, "meme_or_reaction", 1, "balanced", "low", "asymmetric",
     "A cartoon reaction image is cropped hard into the bottom-right corner of a black ground.",
     "A neon magenta headline stacked top-left; the reaction image occupies the bottom-right quarter; the bottom-left is empty black; brand mark bottom-left.",
     ["neon coloured headline"], "The headline itself is the accent colour (magenta).",
     "A diagonal between a neon headline (top-left) and a cropped reaction image (bottom-right)."),
    ("S09", "dark_solid", "media", "small", "small", "medium", "left", False, "photograph", 1, "balanced", "medium", "symmetric",
     "A dark photograph of an animal forms a horizontal band in the middle of a black ground.",
     "A short setup line above the band and a short punchline below it: type, image, type stacked in one column; brand mark bottom-left.",
     ["setup line and punchline framing an image band"], "No accent colour; white type only.",
     "The image separates the setup from the punchline."),
    ("S10", "dark_solid", "interface", "medium", "small", "medium", "left", False, "screenshot_or_ui", 3, "balanced", "high", "asymmetric",
     "Three stacked light rounded option cards read as an interface on a dark ground; neon hand-drawn marks sit in the corners.",
     "Question top-left, the card stack taking roughly the middle half of the height, a sticker badge bottom-right, brand mark bottom-left.",
     ["stack of rounded option cards", "corner scribbles", "sticker badge"], "Yellow and pink marks around the cards; the cards stay light.",
     "Bright light cards against a dark, scribbled ground."),
    ("S11", "dark_image_field", "media", "large", "small", "narrow", "left", False, "illustration", 1, "dominant", "low", "asymmetric",
     "A full-frame neon-lit illustrated portrait; the face is in the upper half and the lower half is dark.",
     "The headline stack is anchored bottom-left in the dark lower zone of the illustration; brand mark bottom-left below it.",
     [], "Red and purple rim light belongs to the artwork; type stays white.",
     "A luminous face above a heavy white headline in the dark zone."),
    ("S12", "dark_image_field", "balanced", "large", "small", "narrow", "left", True, "illustration", 1, "balanced", "medium", "asymmetric",
     "An illustrated character fills the right half and is cropped by the right edge; a dark field holds the copy on the left.",
     "A giant violet numeral top-left, a five-line white headline below it, the character on the right, a small swipe cue with arrow bottom-right.",
     ["giant accent numeral", "swipe cue with arrow"], "Violet numeral; everything else white.",
     "Numeral and tall headline column against a large character crop."),
    ("S13", "dark_image_field", "type", "huge", "small", "wide", "left", True, "illustration", 1, "dominant", "low", "asymmetric",
     "A full-frame neon city illustration with deep perspective; a tiny human silhouette stands low-centre for scale.",
     "Huge magenta display type in a non-Latin script fills the top third; a small white subline stack sits mid-left; the silhouette is bottom-centre.",
     ["huge coloured display type", "small subline stack"], "The display type is magenta; the scene is purple and pink.",
     "Enormous type against a deep scene with a tiny figure."),
    ("S14", "dark_image_field", "media", "medium", "small", "narrow", "left", False, "illustration", 1, "dominant", "low", "asymmetric",
     "An illustrated portrait fills nearly the whole frame; a red rim light outlines the face.",
     "A small stacked headline sits bottom-left in the dark clothing area; brand mark bottom-left.",
     [], "Red is only the artwork's rim light.",
     "Almost pure image with a small type block in its quietest zone."),
    ("S15", "dark_solid", "interface", "medium", "small", "medium", "left", False, "screenshot_or_ui", 4, "balanced", "high", "asymmetric",
     "Four stacked light rounded option cards read as an interface on a dark ground; violet streaks cross the top-right corner.",
     "A two-line question top-left, the card stack filling the middle to lower half, brand mark bottom-left.",
     ["stack of rounded option cards", "diagonal neon streaks"], "Violet and blue streaks in one corner; cards light.",
     "Light UI cards against a dark ground with a corner of neon streaks."),
    ("S16", "mixed", "media", "medium", "small", "medium", "left", False, "isolated_object", 1, "dominant", "low", "asymmetric",
     "A grey-black hardware object fills and is cropped by the whole frame; its surface is a soft grey gradient.",
     "The headline and a short subline sit low, in the object's quieter lower area; brand mark bottom-left.",
     [], "No accent colour.",
     "One large cropped object with type set in its calm zone."),
    ("S17", "light", "balanced", "large", "medium", "medium", "left", False, "isolated_object", 1, "balanced", "medium", "asymmetric",
     "A large dark app-icon-like object bleeds off the right edge on a white ground.",
     "A red numeral leads a heavy headline top-left, a three-line supporting block sits lower-left, the object holds the right, an arrow cue at the bottom-right.",
     ["red numeral lead-in", "arrow cue"], "Red only for the numeral and the brand mark.",
     "A heavy left text stack against one large bleeding object."),
    ("S18", "dark_solid", "media", "medium", "small", "narrow", "left", False, "isolated_object", 1, "balanced", "low", "asymmetric",
     "A single product object sits in the bottom-right of a black ground, isolated and large.",
     "A short headline and a grey subline top-left; the object bottom-right; the diagonal between them is empty black.",
     [], "No accent colour.",
     "Type top-left against an object bottom-right across a deliberate void."),
    ("S19", "dark_image_field", "media", "small", "medium", "narrow", "right", False, "isolated_object", 1, "dominant", "low", "asymmetric",
     "A dark wearable-device photograph fills and is cropped by the whole frame.",
     "A right-aligned small headline stack sits bottom-right on the object's dark area; brand mark bottom-left.",
     [], "No accent colour.",
     "Almost pure object image with a small right-aligned block."),
    ("S20", "light", "type", "large", "small", "narrow", "left", True, "none", 0, "none", "medium", "asymmetric",
     "No media; the whole tile is typography on a light ground.",
     "A tiny red kicker top-left, a heavy two-line headline, a short bullet list, a small link cue with an arrow bottom-left.",
     ["small red kicker", "short bullet list", "link cue with arrow"], "Red only for the kicker and the brand mark.",
     "A very heavy headline against a very small list."),
]

_FAMILIES = [
    dict(family_id="dark_type_number_statement", name="Dark type-and-number statement", member_samples=["S02", "S05", "S12"],
         visual_intent="Type or a single giant numeral is the hero on a solid dark surface; media, if present, is one cropped object or texture fragment that stays secondary to the type.",
         allowed_surfaces=["dark_solid", "dark_image_field"], preferred_visual_weight="type", density_min="low", density_max="medium",
         headline_scale_min="large", headline_scale_max="huge", media_regions_min=0, media_regions_max=1, media_dominance_min="none", media_dominance_max="balanced",
         allowed_media_behaviors=["one object cropped hard by the canvas edge", "a small texture fragment confined to a corner", "no media at all"],
         spatial_tendencies=["left-anchored narrow text column", "numeral stacked above or beside the headline at several times its scale", "any media confined to one side, leaving the opposite lower area as dark void"],
         graphic_devices=["giant accent numeral", "small kicker label", "short accent stroke"],
         negative_space_behavior="Dark empty space is left on the side opposite the copy column and below the text; it is deliberate, not leftover.",
         accent_behavior="One accent colour is spent on the numeral and a small kicker; the headline itself stays white.",
         dark_surface_allowed=True, compatible_content_behaviors=["counts and ranked lists", "urgent one-line claims", "single statistics"],
         what_makes_it_distinct="The numeral or the headline itself is the main visual object and its scale is several times the supporting text.",
         anti_patterns=["small text floating in a large empty field", "a centred timid headline", "a translucent layer over a photo to make text readable"],
         when_not_to_use="Content whose meaning depends on recognising a specific product or scene."),
    dict(family_id="hero_object_stage", name="Hero object stage", member_samples=["S04", "S16", "S17", "S18", "S19"],
         visual_intent="One recognisable object is the hero, either isolated on a solid ground with generous void or cropped hard by the frame; type is small and stays out of the object's way.",
         allowed_surfaces=["dark_solid", "light", "mixed", "dark_image_field"], preferred_visual_weight="media", density_min="low", density_max="medium",
         headline_scale_min="small", headline_scale_max="large", media_regions_min=1, media_regions_max=1, media_dominance_min="balanced", media_dominance_max="dominant",
         allowed_media_behaviors=["an isolated object with a large empty ground around it", "an object cropped by two or more frame edges so it fills the piece", "an object bleeding off one edge diagonally opposite the text"],
         spatial_tendencies=["text top-left with the object bottom-right across an empty diagonal", "object high and centred with a tiny caption below", "text set in the object's own quiet lower area"],
         graphic_devices=["tiny caption stack", "arrow cue", "numeral lead-in on the light variant"],
         negative_space_behavior="The empty ground around the object is large and intentional; the void is part of the composition.",
         accent_behavior="No accent or a single small one; the object provides the visual interest.",
         dark_surface_allowed=True, compatible_content_behaviors=["hardware and product news", "reviews and first looks", "single-object announcements"],
         what_makes_it_distinct="Recognising the object beats headline size; type is deliberately small next to it.",
         anti_patterns=["the object shrunk to a thumbnail inside a text page", "decorative effects on the object", "a headline competing with the object for the same area"],
         when_not_to_use="Abstract ideas or stories with no single concrete object."),
    dict(family_id="immersive_image_field", name="Immersive image field", member_samples=["S01", "S03", "S06", "S11", "S12", "S13", "S14"],
         visual_intent="The image is the scene and owns most of the frame; type sits in a quiet dark zone of the image or beside it, and the mood carries the hook.",
         allowed_surfaces=["dark_image_field", "dark_solid"], preferred_visual_weight="media", density_min="low", density_max="medium",
         headline_scale_min="medium", headline_scale_max="huge", media_regions_min=1, media_regions_max=2, media_dominance_min="balanced", media_dominance_max="dominant",
         allowed_media_behaviors=["a full-frame cinematic or illustrated scene bleeding to every edge", "a portrait cropped at one edge with the copy in the opposite column", "a tiny silhouette for scale inside a deep scene"],
         spatial_tendencies=["headline anchored in the darkest zone of the scene, top-left or bottom-left", "subject offset to one side and copy on the other", "vertical depth with a vanishing point"],
         graphic_devices=["small kicker label", "swipe cue with arrow", "giant coloured numeral"],
         negative_space_behavior="Calm space comes from the dark areas of the scene itself rather than from empty canvas.",
         accent_behavior="Neon or red accents come from the scene's own lighting and are echoed at most once in type.",
         dark_surface_allowed=True, compatible_content_behaviors=["tech culture and futurism", "big announcements", "mood-led hooks"],
         what_makes_it_distinct="The image mood dominates while the type stays very large but subordinate, placed only where the image is quiet.",
         anti_patterns=["text on busy image areas", "a translucent overlay to rescue readability", "the image reduced to a small rectangle on a white page"],
         when_not_to_use="Content without a strong, dark-toned, quiet-zoned image."),
    dict(family_id="culture_collage", name="Internet-culture collage", member_samples=["S06", "S07", "S08", "S09", "S10"],
         visual_intent="Fast, social-native and humorous: reaction imagery, hand-drawn marks, sticker badges and paper-like fragments with colourful secondary accents, dense but still hierarchical.",
         allowed_surfaces=["dark_solid", "dark_image_field", "light", "mixed"], preferred_visual_weight="balanced", density_min="medium", density_max="high",
         headline_scale_min="medium", headline_scale_max="large", media_regions_min=1, media_regions_max=5, media_dominance_min="minor", media_dominance_max="dominant",
         allowed_media_behaviors=["a reaction image cropped hard into a corner", "overlapping paper-like fragments at different scales and small tilts", "a photo band framed between a setup line and a punchline"],
         spatial_tendencies=["setup above, punchline below, image between", "a diagonal between a coloured headline and a cropped image", "layered fragments with tight overlaps and no equal grid"],
         graphic_devices=["hand-drawn scribble marks", "round sticker badges", "coloured highlight line", "torn-paper layers", "label chip"],
         negative_space_behavior="Minimal: marks and fragments fill the gaps, but one reading order stays obvious.",
         accent_behavior="Several secondary accents at once (yellow-green, magenta), used on marks and one type element.",
         dark_surface_allowed=True, compatible_content_behaviors=["humour and reactions", "memes and trends", "quick, casual lists"],
         what_makes_it_distinct="Hand-made, deliberately messy marks sit over a controlled condensed type voice.",
         anti_patterns=["identical cards in a grid", "random chaos with no reading order", "polished corporate spacing"],
         when_not_to_use="Serious or high-stakes news."),
    dict(family_id="interface_cards", name="Interface cards", member_samples=["S10", "S15"],
         visual_intent="Interaction-led: a question headline over a stack of tappable-looking option cards; the interface itself is the graphic.",
         allowed_surfaces=["dark_solid"], preferred_visual_weight="interface", density_min="medium", density_max="high",
         headline_scale_min="medium", headline_scale_max="medium", media_regions_min=3, media_regions_max=4, media_dominance_min="balanced", media_dominance_max="balanced",
         allowed_media_behaviors=["a stack of light rounded option cards under the question", "the card stack fills the middle to lower half of the height"],
         spatial_tendencies=["question top-left with cards stacked below at equal gaps", "decorative streaks or scribbles only in corners"],
         graphic_devices=["option cards", "corner neon streaks", "sticker badge"],
         negative_space_behavior="Small: the card stack dominates the frame.",
         accent_behavior="Neon streaks or scribbles in one corner; the cards stay light and neutral.",
         dark_surface_allowed=True, compatible_content_behaviors=["polls and quizzes", "choose-one prompts", "audience questions"],
         what_makes_it_distinct="Light rounded cards on a dark ground read instantly as UI.",
         anti_patterns=["cards without a question", "more than four cards", "cards mixed with a large photograph"],
         when_not_to_use="Static articles and single claims."),
    dict(family_id="light_utility_editorial", name="Light utility editorial", member_samples=["S17", "S20"],
         visual_intent="Calm and utility-led on a light ground: a very heavy condensed headline with small, precise supporting copy or a short list, and one red numeral or label as the only accent.",
         allowed_surfaces=["light"], preferred_visual_weight="type", density_min="low", density_max="medium",
         headline_scale_min="large", headline_scale_max="huge", media_regions_min=0, media_regions_max=1, media_dominance_min="none", media_dominance_max="balanced",
         allowed_media_behaviors=["one bold isolated object bleeding off one edge", "no image at all"],
         spatial_tendencies=["a left-anchored text stack", "an object on the right bleeding off the frame", "a small link cue at the bottom"],
         graphic_devices=["red numeral lead-in", "small red kicker", "short bullet list", "arrow cue"],
         negative_space_behavior="Measured and generous around the list; the space is structured, not an empty canvas.",
         accent_behavior="Red only, used sparingly on one numeral or label.",
         dark_surface_allowed=False, compatible_content_behaviors=["news digests", "feature roundups", "short factual lists"],
         what_makes_it_distinct="A very heavy headline against tiny supporting copy on a light ground.",
         anti_patterns=["small body text floating on a huge white canvas", "a thin, weak headline", "the same left-aligned layout for every slide"],
         when_not_to_use="Moody or cinematic content."),
]

_INVARIANTS = [
    "One condensed, heavy sans voice is used for headlines in every sample that carries copy; supporting copy is a much smaller, lighter sans.",
    "Hierarchy is always obvious: one headline or numeral reads first and supporting copy is several times smaller.",
    "Every piece carries the brand mark, small relative to the piece and kept clear of copy, in a corner.",
    "Copy keeps a consistent inner margin and never touches the frame edge.",
    "Accent colour is a small controlled palette per family: red for the editorial and utility families, yellow-green and magenta for culture, violet and magenta for neo-futurist imagery; a piece never uses more accents than its family's palette.",
    "Media is always shown as itself - cropped, isolated or framed - and is never blended into a translucent layer.",
]
_CONTRADICTIONS = [
    "The same giant-numeral device appears on dark solid surfaces (S02, S05, S12) and as a small red lead-in on a light surface (S17): the device is shared, the surface is not.",
    "Density spans from sparse object-on-black (S04, S18) to dense doodle and paper collage (S06, S07, S10) within one board; it is not a single density.",
    "Type is the hero in some samples (S02, S05, S13) and the image is the hero in others (S03, S14, S19).",
    "Light surfaces are a minority mode (S07, S17, S20, plus the mixed S16) beside a dark majority; light must not become the default.",
]
_MUST_NOT_COPY = [
    "Any exact wording or copy appearing on the board, including headlines, labels, captions and list items.",
    "The exact imagery, characters, memes, photographs, product renders and artwork shown on the board.",
    "The exact compositions, sample order and crop decisions as a fixed sequence or a pixel replica.",
    "The board's displayed logo artwork, which is not the approved canonical brand mark.",
    "The board as a fixed template or a repeated visual sequence.",
]
_ORIGINALITY = [
    "Learn the mechanics of each family; never reproduce a sample.",
    "Create new copy, imagery and arrangements for every publication.",
    "Two pieces from the same family must not share the same geometry.",
    "Treat every conclusion as a hypothesis from one board and verify it in founder review.",
]


def build() -> InstagramVisualDNAV2:
    _jpeg, _uri, digest = prepare_reference_image(REFERENCE_BOARD_PATH)
    samples = []
    for row in _S:
        keys = ("sample_id", "surface_tone", "visual_lead", "headline_scale", "body_scale", "text_block_width", "alignment",
                "type_is_main_visual_object", "media_kind", "media_region_count", "media_dominance", "density", "symmetry",
                "crop_and_media_relation", "spatial_composition", "graphic_devices", "accent_use", "visual_tension")
        samples.append(dict(zip(keys, row)))
    dna = InstagramVisualDNAV2(
        version="2", reference_path="docs/references/instagram/instagram_visual_reference_board_v1.png", reference_sha256=digest,
        analysis_prompt_version="direct-visual-review-1", analysis_model="claude-code assistant direct visual review (no provider call)",
        global_invariants=_INVARIANTS, samples=samples, families=_FAMILIES, contradictions_kept_distinct=_CONTRADICTIONS,
        must_not_copy=_MUST_NOT_COPY, originality_constraints=_ORIGINALITY,
    )
    assert_v2_mechanics_only(dna)
    return dna


if __name__ == "__main__":
    dna = build()
    DNA_DIR.mkdir(parents=True, exist_ok=True)
    (DNA_DIR / "v2.json").write_text(dna.model_dump_json(indent=2), encoding="utf-8")
    (DNA_DIR / "v2.md").write_text(render_visual_dna_v2_markdown(dna), encoding="utf-8")
    print("v2 written:", len(dna.samples), "samples,", len(dna.families), "families")
