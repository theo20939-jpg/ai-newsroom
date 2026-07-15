"""Centralized logging configuration for the application."""
import logging
import sys

from core.config import settings


def setup_logging() -> None:
    """Configure the root logger with a consistent format for all services."""
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
        force=True,
    )
