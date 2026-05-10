import json
import logging

from idle_shutdown.logging_setup import JsonFormatter


def _record(msg: str, level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="idle_shutdown.test", level=level, pathname=__file__,
        lineno=1, msg=msg, args=(), exc_info=None,
    )


def test_json_formatter_basic():
    out = json.loads(JsonFormatter().format(_record("hello world")))
    assert out["level"] == "INFO"
    assert out["msg"] == "hello world"
    assert out["logger"] == "idle_shutdown.test"
    assert "ts" in out
    assert "fields" not in out


def test_json_formatter_extracts_event_kv_pairs():
    msg = "event=snapshot_started trigger=Manual apps=3"
    out = json.loads(JsonFormatter().format(_record(msg)))
    assert out["event"] == "snapshot_started"
    assert out["fields"] == {"event": "snapshot_started",
                              "trigger": "Manual", "apps": "3"}


def test_json_formatter_includes_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        rec = logging.LogRecord(
            name="x", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="failed", args=(), exc_info=sys.exc_info(),
        )
    out = json.loads(JsonFormatter().format(rec))
    assert "ValueError: boom" in out["exc"]
