FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# NINJA PULSE Visual System v1 - Cyrillic font packaging fix (services/brand_renderer.py's own
# _resolve_font_path() already searches /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf; this
# Debian package is the one that provides it - confirmed by inspecting `dpkg -L fonts-dejavu-core`
# against this exact base image, not assumed). Installed before COPY so this layer only rebuilds
# when the font package itself changes, not on every app code change. Shared by every service in
# docker-compose.yml (they all `build: .` from this one Dockerfile) - only content_worker actually
# renders branded media, but a single small, official Debian font package in every image is the
# minimal reproducible fix without a new per-service Dockerfile architecture.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
