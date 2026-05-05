from __future__ import annotations

import logging
import sys

from loguru import logger


class InterceptHandler(logging.Handler):
    """Forward standard logging records to loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        level: str | int
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(log_level: str) -> None:
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    logger.remove()
    logger.add(
        sys.stdout,
        level=log_level.upper(),
        colorize=True,
        backtrace=False,
        diagnose=False,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> - "
        "<level>{message}</level>",
    )
