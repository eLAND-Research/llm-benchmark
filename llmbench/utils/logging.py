"""Logging utilities using rich for colored output."""
from __future__ import annotations
import logging
from rich.logging import RichHandler

_LOGGER_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    global _LOGGER_CONFIGURED
    if _LOGGER_CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    _LOGGER_CONFIGURED = True


def get_logger(name: str):  # noqa: D401
    setup_logging()
    return logging.getLogger(name)

