"""Phase B.5R: segmentation of the founder reference board into its individual samples.

The board is a 4-row x 5-column grid of format examples (single / carousel / reel cover / reel cover /
story) plus a left brand panel per row and a footer strip. Boxes are measured on the actual pixels of
`instagram_visual_reference_board_v1.png` (1536x1024) and are reviewable in
artifacts/instagram_phase_b5r/reference_map.png. Sample crops are INTERNAL analysis evidence only."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from services.instagram_visual_profiles import ig_font

# (x0, y0, x1, y1) on the 1536x1024 board, row-major: S01..S05 row 1 ... S16..S20 row 4.
SAMPLE_BOXES: tuple[tuple[int, int, int, int], ...] = (
    (433, 39, 625, 250), (641, 39, 875, 250), (891, 39, 1108, 250), (1125, 39, 1273, 250), (1299, 39, 1459, 250),
    (433, 295, 625, 501), (643, 295, 875, 501), (891, 295, 1108, 501), (1125, 295, 1273, 501), (1299, 295, 1464, 501),
    (433, 523, 625, 740), (643, 523, 875, 740), (894, 523, 1108, 740), (1128, 523, 1285, 740), (1301, 523, 1472, 740),
    (432, 781, 622, 950), (642, 781, 875, 950), (893, 781, 1105, 950), (1119, 781, 1285, 950), (1305, 781, 1457, 950),
)
ROW_COUNT, COL_COUNT = 4, 5
FORMATS = ("single_post_1x1", "carousel_4x5", "reel_cover_9x16", "reel_cover_9x16", "story_9x16")


@dataclass(frozen=True)
class ReferenceSample:
    sample_id: str
    row: int
    col: int
    box: tuple[int, int, int, int]
    board_format: str


def reference_samples() -> list[ReferenceSample]:
    return [
        ReferenceSample(f"S{i + 1:02d}", i // COL_COUNT + 1, i % COL_COUNT + 1, box, FORMATS[i % COL_COUNT])
        for i, box in enumerate(SAMPLE_BOXES)
    ]


def crop_sample(board: Image.Image, sample: ReferenceSample, *, scale: float = 2.0) -> Image.Image:
    crop = board.convert("RGB").crop(sample.box)
    return crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS)


def build_row_montages(board_path: Path, *, scale: float = 2.0) -> list[Image.Image]:
    """One labelled montage per board row (S-ids drawn on each crop) so a vision model can tie its
    per-sample findings to concrete pixels."""
    board = Image.open(board_path).convert("RGB")
    samples = reference_samples()
    montages = []
    label_font = ig_font(30, "black")
    for row in range(1, ROW_COUNT + 1):
        row_samples = [s for s in samples if s.row == row]
        crops = [crop_sample(board, s, scale=scale) for s in row_samples]
        height = max(c.height for c in crops) + 46
        width = sum(c.width for c in crops) + 16 * (len(crops) + 1)
        sheet = Image.new("RGB", (width, height), (128, 128, 128))
        draw = ImageDraw.Draw(sheet)
        x = 16
        for s, c in zip(row_samples, crops):
            draw.text((x, 6), s.sample_id, font=label_font, fill=(255, 255, 0))
            sheet.paste(c, (x, 46))
            x += c.width + 16
        montages.append(sheet)
    return montages


def draw_segmentation_overlay(board_path: Path) -> Image.Image:
    board = Image.open(board_path).convert("RGB")
    draw = ImageDraw.Draw(board)
    font = ig_font(22, "black")
    for s in reference_samples():
        draw.rectangle(s.box, outline=(0, 255, 255), width=2)
        draw.text((s.box[0] + 4, s.box[1] + 4), s.sample_id, font=font, fill=(255, 255, 0))
    return board
