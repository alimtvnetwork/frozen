"""Rotating file logger. No console handler by default (silent service).

Two formats:
- ``text`` (default) — one line per record, human-readable.
- ``json`` — one JSON object per record (RFC 8259, NDJSON-friendly). Enable
  via ``--log-json`` on the CLI or ``IDLE_SHUTDOWN_LOG_JSON=1``. Useful for
  ingesting into Event Viewer / OpenTelemetry / log aggregators.

Event-style log lines (``event=foo key=val``) are parsed into structured
fields when JSON mode is on, so existing call sites stay unchanged.
"""
from __future__ import annotations

import json
import logging
import os
import re
from logging.handlers import RotatingFileHandler

from idle_shutdown.config import ensure_app_dirs, log_path

_CONFIGURED = False


_KV_RE = re.compile(r"(\w+)=([^\s]+)")


class JsonFormatter(logging.Formatter):
    """One JSON object per record. Parses ``event=`` / ``key=value`` pairs."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": msg,
        }
        # Extract structured fields from `key=value` tokens.
        kvs = dict(_KV_RE.findall(msg))
        if kvs:
            payload["fields"] = kvs
            if "event" in kvs:
                payload["event"] = kvs["event"]
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(verbose: bool = False, *, json_format: bool | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    ensure_app_dirs()
    level_name = os.environ.get("IDLE_SHUTDOWN_LOG_LEVEL")
    level = logging.DEBUG if verbose else getattr(
        logging, (level_name or "INFO").upper(), logging.INFO
    )
    if json_format is None:
        json_format = os.environ.get("IDLE_SHUTDOWN_LOG_JSON", "").lower() in (
            "1", "true", "yes", "on",
        )
    handler = RotatingFileHandler(
        str(log_path()), maxBytes=1_048_576, backupCount=5, encoding="utf-8"
    )
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    _CONFIGURED = True