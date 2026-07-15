"""FastAPI application entry point."""
import logging

from fastapi import FastAPI

from core.config import settings
from core.logging import setup_logging

setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)

logger.info("Starting %s in '%s' environment", settings.app_name, settings.app_env)


@app.get("/")
async def health_check() -> dict[str, str]:
    """Confirm that the application is running."""
    return {"status": "Application running"}
