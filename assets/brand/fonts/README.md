# Bundled runtime fonts — NINJA PULSE DATA renderer

FOUNDER-VISUAL-BOARD-REBUILD-6 §7/§19: the DATA hero-metric renderer must produce **identical
output on Windows (dev) and Linux (production)**, so it uses a font bundled here as a project
runtime asset — never `C:/Windows/Fonts/*` or a Linux system fallback.

## Fira Sans Condensed

| Role | File | PostScript weight |
|---|---|---|
| `DATA_FONT_BLACK`  (hero value + unit) | `FiraSansCondensed-Black.ttf` | Black (900) |
| `DATA_FONT_BOLD`   (label)             | `FiraSansCondensed-Bold.ttf` | Bold (700) |
| `DATA_FONT_SEMIBOLD` (delta pill)      | `FiraSansCondensed-SemiBold.ttf` | SemiBold (600) |
| `DATA_FONT_MEDIUM`                     | `FiraSansCondensed-Medium.ttf` | Medium (500) |
| `DATA_FONT_REGULAR` (secondary grey)   | `FiraSansCondensed-Regular.ttf` | Regular (400) |

* **Source:** the Google Fonts distribution of Mozilla's Fira Sans Condensed
  (`https://github.com/google/fonts/tree/main/ofl/firasanscondensed`).
* **Licence:** SIL Open Font License, Version 1.1 — full text in `OFL.txt`.
  Copyright (c) 2012-2015, The Mozilla Foundation and Telefónica S.A.
  The OFL explicitly permits bundling the font, unmodified, inside application software; the
  font files are **not** redistributed to end users as standalone artifacts.
* **Why this face:** condensed grotesque with a Black weight, near-circular numerals, full
  Cyrillic (`МЛН` / `ПОЛЬЗОВАТЕЛЕЙ` / `СООБЩЕНИЙ`), modern editorial/tech character — the closest
  legally-bundlable match to the Founder board's DATA typography (see
  `07_TYPOGRAPHY_FINAL.png` in the review package).

`services/brand_renderer.py::_data_font()` resolves these paths relatively from the repo root, so
`WINDOWS_RENDER_FONT == LINUX_RENDER_FONT` by construction (same committed file).
