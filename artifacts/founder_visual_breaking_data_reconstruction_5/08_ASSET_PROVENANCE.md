# 08 — ASSET PROVENANCE (FOUNDER-VISUAL-BREAKING-DATA-RECONSTRUCTION-5)

Exactly which assets / measurements each reconstructed visual comes from.

## BREAKING pulse

    source        : docs/founder_telegram_board.png  (VISUAL AUTHORITY #1)
    method        : pixel-trace of the board's own BREAKING-photo pulse (red-channel column scan)
    measured      : baseline at the photo's bottom edge; QRS apex at ~0.33 of the drawn span;
                    R apex +20 px, S trough -15 px  ->  S/R ~= 0.70 ; P ~= 0.26 R ; T ~= 0.29 R ;
                    drawn span ~= 0.46 of the photo width ; thin clean stroke
    baked as      : services/brand_renderer.py :: _PULSE_WAVEFORM_UNIT  (23-point P-QRS-T)
    rendered by   : _draw_recovered_pulse()  - 4x supersample -> LANCZOS -> alpha_composite,
                    LEFT-anchored, span/amplitude as fractions of the source (aspect-safe)
    NOT used      : assets/.../overlays/breaking/breaking_minimal_01.png  (FOUND_REJECTED)
                    assets/.../overlays/universal/universal_minimal_01.png (RECOVERY-4 geometry,
                    Founder-rejected as "still crude"); no raster composited
    evidence      : renderer_version "pulse-breaking-v5-board" ; placement_zone "lower_left" ;
                    notes.overlay_asset names docs/founder_telegram_board.png

## DATA generated - background + grid

    source        : docs/founder_telegram_board.png DATA card, pixel-measured
    measured      : bg mean RGB ~= (6,7,9) ; grid peak brightness ~= +11 over bg ; grid step ~= 1/9
    baked as      : _HERO_BG=(6,7,9) ; _HERO_GRID_COLOR=(17,18,22) ; _HERO_GRID_STEP=144
    NOT used      : no background/grid asset exists anywhere in the repo or its history

## DATA generated - typography  (07_TYPOGRAPHY_COMPARISON.png)

    board face    : a heavy / black-weight geometric grotesque (near-circular zeros) - not
                    identifiable, and NO font file has ever been committed to this repo
    DATA_FONT_FAMILY        = Arial  (OS-provided; the family already used for the regular face)
    DATA_FONT_HEAVY (value/unit) = C:/Windows/Fonts/ariblk.ttf  (Arial Black)
                    Linux VPS fallback: DejaVuSans-Bold.ttf / LiberationSans-Bold.ttf
    DATA_FONT_BOLD  (label)      = C:/Windows/Fonts/arialbd.ttf  (Arial Bold) + Linux bold fallbacks
    DATA_FONT_REGULAR (secondary/grey) = C:/Windows/Fonts/arial.ttf + DejaVu/Liberation regular
    resolvers     : services/brand_renderer.py :: _resolve_heavy_font_path / _resolve_bold_font_path
                    (heavy -> bold -> regular graceful degradation; never downloads)
    FONT_MATCH_CONFIDENCE = MEDIUM
                    Arial Black matches the board's weight and near-circular digit shapes well; a
                    true CONDENSED black grotesque would still need a Founder-supplied font asset.

## DATA generated - graph

    curve         : monotone cubic (Fritsch-Carlson) through the REAL DataCandidate.series points -
                    visual interpolation only, provably non-overshooting (cannot imply a value
                    outside the series). No synthetic points, no axes, no invented labels.
    area fill     : a restrained red glow - vgrad ** 3.0 (fades fast downward) x hgrad (dimmer to
                    the left) - not a hard red triangular block (§17).
    end-dot       : white, at the series max.
    NOTE          : the board's curve reads more organic/jagged because it plots a denser series;
                    with a sparse 4-7-point series a smooth monotone curve is the honest render.

## DATA generated - small pulse motif

    same primitive as BREAKING: _draw_recovered_pulse() with _PULSE_WAVEFORM_UNIT. The retired
    hand-coded _draw_pulse_line (flat->spike->valley) is NOT used here any more.

## DATA source

    treatment     : source CONTAIN of the fitted infographic + adaptive bottom-only pulse+mark
                    signature IF _select_data_signature places it safely, else BRAND SUPPRESSION.
    never         : a rectangular logo badge / dark plate (the RECOVERY-4 fallback chip is now
                    gated OUT of MINIMAL_SOURCE_PRESERVING).
    adaptive      : white / red mark per local background (_select_data_signature.red).
    safety        : source pixels above the bottom signature band are byte-for-byte preserved;
                    third-party publisher logos are never touched. FINAL_VISIBLE_NNJ_COUNT <= 1
                    (0 when suppressed).
