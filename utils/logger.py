"""Logging configuration for the bot process."""

import logging
from pathlib import Path


def configure_logging(level: str, log_directory: Path) -> None:
    """Configure UTF-8 console and file logging exactly once."""
    log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_directory / "bot.log", encoding="utf-8"),
        ],
        force=True,
    )

