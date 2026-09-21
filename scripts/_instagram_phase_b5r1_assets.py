"""Phase B.5R.1: the REAL-MEDIA asset registry for the family fidelity reconstruction.

Only existing, already-available raster media is used: git-tracked repository fixtures and existing stored
Newsroom source imagery (read-only copies of the production image storage volume). Nothing is generated, no
image provider is called, nothing is fetched from the web, and the reference board's own imagery is never used
as content. Several stored Newsroom images are themselves illustrations that the newsroom pipeline produced
earlier; this phase makes no new generation call and cannot tell which ones, so provenance is reported as
'stored newsroom image' rather than 'photograph'.

Storage-volume copies live OUTSIDE git (artifacts/instagram_phase_b5r1/real_media/, git-excluded); tracked
repository assets are always available. `resolve()` returns None for an asset that is not present locally."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

_REPO = Path(__file__).resolve().parent.parent
MEDIA_DIR = Path(os.environ.get("B5R1_MEDIA_DIR", str(_REPO / "artifacts" / "instagram_phase_b5r1" / "real_media")))


@dataclass(frozen=True)
class Asset:
    asset_id: str
    source_type: str            # "repository" | "newsroom_storage"
    key: str                    # repo path, or storage key (images/<xx>/<sha256>.<ext>)
    subject: str
    families: tuple[str, ...]
    why: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def local_name(self) -> str:
        return f"{self.asset_id}{Path(self.key).suffix.lower()}"


IMM, HERO, COL = "immersive_image_field", "hero_object_stage", "culture_collage"


def _s(asset_id, key, subject, families, why, tags=()):
    return Asset(asset_id, "newsroom_storage", key, subject, tuple(families), why, tuple(tags))


ASSETS: list[Asset] = [
    # ------------------------------------------------------------------ immersive candidates (dark, scene-like)
    _s("imm_lunar_lander", "images/74/7452a8bfddd8ba11414c399e836b50a5278d123706efcf4631375a89d6e07dca.jpg",
       "A lunar lander standing on grey regolith under a black sky; the vehicle sits left of centre.", [IMM], "Naturally dark scene with a large empty black sky the copy can use."),
    _s("imm_red_mecha", "images/0b/0bbb5b4498b217767512af85d8503e42ed93d8036b8f01b09937dafef8881a2e.png",
       "A red armoured mecha towering over a lone figure seen from behind in a dark hall.", [IMM], "Cinematic, dark, subject high in the frame with dark lower area."),
    _s("imm_earth_horizon", "images/83/83405700324067f6c7cee2718f973a173ab2960c4007745e620c840b540c8937.png",
       "Earth's limb with a bright sun flare seen from orbit against black space.", [IMM], "Vertical depth from glowing horizon into empty black space."),
    _s("imm_dna_helix", "images/9f/9fce210482fd1f30686bd29b8e28335bc4c1c63967f4b93d94ac2e01f20d9c4f.jpg",
       "A glowing blue DNA helix with floating particles on a deep blue-black field.", [IMM], "Square, dark, diagonal subject leaving calm areas on one side."),
    _s("imm_purple_phone", "images/1c/1c7fd488398a98f993eb636daf8632b9ffe2d3cd6d98d7a7086263b39db7b17b.jpg",
       "A purple phone bursting through dark rock shards with lightning.", [IMM], "Dark high-contrast hero scene with neon accent."),
    _s("imm_planets", "images/67/673e390da463bc5c4441eb70e741b315463c2108a1ad6f6abf59013fcd7d9b1e.jpg",
       "Ringed planets and moons in a dark star field.", [IMM], "Large calm dark regions and a bright subject off to one side."),
    _s("imm_white_house_night", "images/6b/6bafe912d58cd49628f244c350cffd4e62a539249064d45d5b3fb1e49f34b8ab.jpg",
       "A white columned government building at night under a glowing arc, one figure in the foreground.", [IMM], "Night scene, subject in the lower half, dark sky above."),
    _s("imm_gamer_reaction", "images/6b/6b6fbb396b34a1a98ec50ae9afb5391b900746350a47ff0fdef09874fbf285c1.png",
       "A person in a red-lit dark room covering their face with both hands.", [IMM, COL], "Emotional reaction image in a naturally dark, red-lit frame."),
    _s("imm_rocket_launch", "images/4e/4e4145b52367bfbe4c0e923fdf9ab2a404f4d038b354d28fc1f23f8a0e7194da.jpg",
       "A rocket lifting off in a wall of orange fire against a dark sky.", [IMM], "Dark, dramatic, bright subject low with dark upper area."),
    _s("imm_black_object", "images/c3/c37edc5e8e963d5d85a4017b9e95a46ae9a4dbf351fe4ab18c30882ccd48da1e.jpg",
       "The corner of a black phone-like device lit softly in near-total darkness.", [IMM, HERO], "Almost entirely dark with one soft-lit object edge."),
    _s("imm_blacksmith", "images/23/235e1eaebf86ae25bfd777791af40097135aa44c9a798e39fd8af56daa33882e.jpg",
       "A muscular blacksmith hammering at a glowing forge among circuit boards.", [IMM], "Dark red-lit scene, busy centre with darker edges."),
    _s("imm_data_hall_worker", "images/12/122c4032bebb2b852209bfeadebbc286362cbcf3dce40c1b02b54885a533f674.jpg",
       "A technician in cleanroom gear inspecting a chip beside a long server corridor.", [IMM], "Blue-toned technical scene with depth; likely to be a hard case for text."),
    # ------------------------------------------------------------------ hero object candidates (isolated subjects)
    _s("hero_moon_on_black", "images/09/09604ccd1af8b7386eb3bb89a6640f1883bc7840da34af4b7030f13a64e2a3e5.jpg",
       "The Moon, a large round grey body, isolated on a pure black ground.", [HERO], "A round recognisable object on a uniform black ground - true isolation."),
    _s("hero_dark_phone_on_white", "images/72/721a1726aefd1bc4ee3a513119af50729bb4b389e3c0d962f452710bf7c62eec.webp",
       "A dark grey smartphone with an orange glowing camera module, seen from the back on white.", [HERO], "Tall product shot on a uniform white ground; strong dark-on-light contrast."),
    _s("hero_white_phone_on_white", "images/00/00411272d2542ea71b94f5f10a91af1cb2610c194e9637b39e9f0df2e1f38c28.webp",
       "A white smartphone with a teal glowing camera module, seen from the back on white.", [HERO], "Tall, near full-height product shot on a uniform white ground."),
    _s("hero_power_bank", "images/03/0338d903f6966d9faeba65ff947fa3c39c285b8e16cde434e2dd3cfe403db55c.png",
       "A white power bank with a looped cable, isolated on white.", [HERO], "Small everyday object on a uniform white ground."),
    _s("hero_red_foldable", "images/4e/4e7c421000ff8a788d7033e457d944de95912db3f5cbd8dc6961e5f71d413c13.png",
       "Two red foldable phones, one closed and one open, isolated on white.", [HERO], "Wide two-object product shot on white."),
    _s("hero_suv", "images/a6/a6e63dc3ae9e04b44d1bbe185aad2fcd1e3139272a4587830583e6088d5be8a1.webp",
       "A light blue SUV in side profile, isolated on white.", [HERO], "A wide object that bleeds well off a frame edge."),
    _s("hero_gpu_on_black", "images/a3/a3b93224cde304f781d095af223719ab31cb882d11f7dbd9f17412f71c62ca7d.jpg",
       "A black hardware component lit along its edges on a black ground.", [HERO], "Dark object on a dark ground, a dark-family hero stage."),
    # ------------------------------------------------------------------ collage fragments (heterogeneous)
    _s("col_reaction_gamer", "images/4e/4e7825589a8f8e179bdd5dcd2dc0a4c00a82ff350b6779b089f15e488837a1db.png",
       "A person in a red gaming chair pressing both hands to their face (wider crop of the same scene).", [COL], "Reaction-image energy for the primary fragment."),
    _s("col_comic_panels", "images/06/06ad565873f813ccfc820b1b08171f9b6fbfd29a5884755e0baad57be2d89a3d.png",
       "A four-panel cartoon of worried shoppers with baskets.", [COL], "Meme-style illustrated fragment with a different visual language."),
    _s("col_wallet_ui", "images/21/21003d0ffd66c0509e3660f3a1398b6a3e38bf15b6582c0217d7d894e1c82bb2.png",
       "A phone screenshot of a finance app: balance, action buttons and a transaction list.", [COL], "Real UI screenshot fragment."),
    _s("col_dashboard_ui", "images/4e/4e6bc0f1632850eac64306b45c0ec19322daffb1db7607cf9287b6537bf54175.jpg",
       "An analytics dashboard screenshot with charts, bars and a handwritten-style red annotation.", [COL], "Dense real screenshot fragment with an annotation."),
    _s("col_three_phone_ui", "images/23/230dc7843ea127cbcb45878b317945372a6f61742a8fb4f0c670ad43bb52fe32.jpg",
       "Three phone app screens showing health metrics on a pink-blue gradient.", [COL], "Colourful UI fragment for a light collage."),
    _s("col_table_screenshot", "images/0d/0d3d9d457a87a8c5dc8b52b7d3d4358e61073d7006795234769546555b2ae612.png",
       "A dense spreadsheet-style table screenshot with rows of small text.", [COL], "Real text fragment / screenshot texture."),
    _s("col_chart", "images/62/62cec7753681769cb023f5a94fe434bdaf3739c610b9e5383b9803afbf2acc98.png",
       "A bar-chart benchmark table with coloured bars.", [COL], "Real chart fragment."),
    _s("col_teardown", "images/1a/1a4d8c1016bf45b2b1294d2d4dfc5459b16fc6e722a8576bec9f5633a4c7d791.jpg",
       "An opened phone showing internal components and camera modules.", [COL], "Product-detail fragment."),
    _s("col_portrait_cutout", "images/e6/e6004fd3f7719b09fd3e81fcb4ee40655ddeb52bc89660f866f79360ebd68e4f.png",
       "A smiling man in a suit, a real transparent-background cutout (alpha channel).", [COL, HERO], "A real transparent cutout: exercises alpha staging."),
    _s("col_chip_macro", "images/52/52f2102b754928dd7f1ac8acd119817763acb2c3ba5780fd5704ff44524aaf61.jpg",
       "A macro of a memory chip with a grid of solder balls on a green board.", [COL], "Small tertiary detail fragment."),
    _s("col_flow_diagram", "images/4a/4a418b3807b71483f18e296d0d3a2b197043a57514bffd4de7c5e87813885b1f.png",
       "A light flow-diagram screenshot with boxes and arrows.", [COL], "Light UI/diagram fragment."),
    # ------------------------------------------------------------------ git-tracked repository fixtures (always available)
    Asset("repo_orange_phone", "repository", "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case1_hero_product_iphone.jpg",
          "Two phones (back and front) on an orange studio ground.", (HERO,), "A real product hero on a single-colour ground - staging on a media-derived ground."),
    Asset("repo_keyboard_app", "repository", "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case2_gadget_geometry_detail.jpg",
          "A keyboard corner beside a phone showing a language-learning app screen.", (COL,), "Photo fragment mixing hardware and UI."),
    Asset("repo_yellow_kiosk", "repository", "assets/brand/newsroom_visuals/v2_1_bakeoff_sources/case3_bright_promotional_scene.jpg",
          "A person at a bright yellow photo kiosk with a glowing screen.", (COL,), "Bright promotional scene: a high-key fragment (and a hard case for immersive text)."),
    Asset("repo_ev_infographic", "repository", "tests/fixtures/external_source_infographic.jpg",
          "A light bar-chart infographic about EV adoption.", (COL,), "Real infographic screenshot fragment."),
    Asset("repo_portrait", "repository", "tests/fixtures/portrait_public_figure.jpg",
          "A man in a dark jacket raising a hand, on a light grey studio ground.", (IMM, COL), "Light-ground portrait: a deliberate NOT-suitable-for-immersive test case."),
]
BY_ID = {a.asset_id: a for a in ASSETS}


def local_path(asset: Asset) -> Path:
    if asset.source_type == "repository":
        return _REPO / asset.key
    return MEDIA_DIR / asset.local_name


def resolve(asset_id: str) -> Image.Image | None:
    """The real image (RGB, or RGBA for real cutouts) or None when that copy is not present locally."""
    asset = BY_ID[asset_id]
    path = local_path(asset)
    if not path.is_file():
        return None
    img = Image.open(path)
    img.load()
    return img.convert("RGBA") if (img.mode in ("RGBA", "LA") or "transparency" in img.info) else img.convert("RGB")


def available_ids() -> list[str]:
    return [a.asset_id for a in ASSETS if local_path(a).is_file()]


def prepare_media_dir(store_dir: Path) -> int:
    """Copy the selected stored-newsroom images (by storage key) from a local read-only copy of the image
    storage volume into MEDIA_DIR (outside git). Returns the number copied."""
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for a in ASSETS:
        if a.source_type != "newsroom_storage":
            continue
        src = store_dir / Path(a.key).relative_to("images")
        if src.is_file():
            shutil.copyfile(src, MEDIA_DIR / a.local_name)
            copied += 1
    return copied
