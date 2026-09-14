"""INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §6: serves EXACTLY one registered publication asset per
request, by its exact content-hash id - never a directory listing, never an arbitrary filesystem
path, never a fallback to any other file. See `services/instagram_media_hosting.py`'s own module
docstring for the full design rationale (this route is the "serving" half of that module)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from services.instagram_media_hosting import get_publication_asset

router = APIRouter()


@router.get("/media/instagram/{asset_id}.jpg")
async def get_instagram_media(asset_id: str) -> Response:
    """`asset_id` is validated by `get_publication_asset()` itself (exact 32-hex-char match only,
    never touching the filesystem for anything else) - this handler never constructs a path from
    the raw request value itself, so there is no path-traversal surface regardless of what a
    caller sends. A missing/expired/malformed id is indistinguishable from any other 404 - no
    signal is ever given about whether an id merely doesn't exist yet vs. has expired."""
    asset = get_publication_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="not found")
    data = asset.local_path.read_bytes()
    return Response(
        content=data, media_type=asset.mime_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
