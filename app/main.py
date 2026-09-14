"""FastAPI application entry point."""
import logging

from fastapi import FastAPI

from app.routes.instagram_media import router as instagram_media_router
from core.config import settings
from core.logging import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)
# INSTAGRAM-PRODUCTION-READINESS-CLOSURE-1 §6: the ONLY new route this phase adds - serves exactly
# one registered publication asset per request, by exact id (services/instagram_media_hosting.py).
# Read-only, no auth-bearing behavior change to any other route.
app.include_router(instagram_media_router)

logger.info("Starting %s in '%s' environment", settings.app_name, settings.app_env)


@app.get("/")
async def health_check() -> dict[str, str]:
    """Confirm that the application is running."""
    return {"status": "Application running"}
