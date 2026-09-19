FROM python:3.12-slim

WORKDIR /app

# PYTHONPATH=/app: the `pip install .` below (non-editable, by deliberate choice - see its own
# comment) copies services/schemas/etc. into site-packages as a SECOND, physical copy of this
# project's own first-party code, missing every non-Python resource dir (assets/, prompts/) since
# [tool.hatch.build.targets.wheel] only lists Python packages. Any invocation whose own script
# lives outside /app (e.g. `python scripts/foo.py` - Python puts the SCRIPT's own directory on
# sys.path[0], never the cwd) resolves first-party imports against that installed copy instead of
# the live /app source, so services/instagram_visual_profiles.py's own `__file__`-relative
# `_FONT_DIR` silently pointed at a site-packages path with no assets/ underneath at all - the
# confirmed root cause of Phase B.2's "cannot open resource" font crash (reproduced by direct
# `__file__`/sys.path inspection, not assumed). Explicitly forcing /app first on sys.path via
# PYTHONPATH makes every invocation style resolve the SAME live source tree deterministically,
# without touching the non-editable install decision or needing per-script sys.path hacks.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# NINJA PULSE Visual System v1 - Cyrillic font packaging fix (services/brand_renderer.py's own
# _resolve_font_path() already searches /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf; this
# Debian package is the one that provides it - confirmed by inspecting `dpkg -L fonts-dejavu-core`
# against this exact base image, not assumed). Installed before COPY so this layer only rebuilds
# when the font package itself changes, not on every app code change. Shared by every service in
# docker-compose.yml (they all `build: .` from this one Dockerfile) - only content_worker actually
# renders branded media, but a single small, official Debian font package in every image is the
# minimal reproducible fix without a new per-service Dockerfile architecture.
#
# Phase V2.27A: ffmpeg added to this SAME layer (never a second apt layer) - services/hosted_
# video_download.py invokes it as a subprocess only as a bounded compatibility-transcode fallback
# when yt-dlp's own format selection cannot directly produce an H.264/AAC MP4 (see that module's
# own docstring). Only content_worker actually calls it, same reasoning as fonts-dejavu-core above
# for shipping it in every service's image rather than a new per-service Dockerfile.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
