"""Rotating file logger. No console handler by default (silent service)."""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

from idle_shutdown.config import ensure_app_dirs, log_path

_CONFIGURED = False


def setup_logging(verbose: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    ensure_app_dirs()
    level_name = os.environ.get("IDLE_SHUTDOWN_LOG_LEVEL")
    level = logging.DEBUG if verbose else getattr(
        logging, (level_name or "INFO").upper(), logging.INFO
    )
    handler = RotatingFileHandler(
        str(log_path()), maxBytes=1_048_576, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _CONFIGURED = True