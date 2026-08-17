"""Logging configuration for the scraper scheduler."""

import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from config import LOGS_DIR, LOGGING_CONFIG


def setup_logger(name: str, log_file: str | None = None) -> logging.Logger:
    """Set up a logger with file and console handlers."""
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, LOGGING_CONFIG["level"]))

    formatter = logging.Formatter(
        LOGGING_CONFIG["format"],
        datefmt=LOGGING_CONFIG["date_format"],
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        log_path = LOGS_DIR / log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=7,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


scheduler_logger = setup_logger("scheduler", "scheduler.log")
scraper_logger = setup_logger("scraper", "scraper.log")
error_logger = setup_logger("errors", "errors.log")
