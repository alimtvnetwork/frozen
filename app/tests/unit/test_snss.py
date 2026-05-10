"""Synthetic-fixture tests for the SNSS framing + UpdateTabNavigation decoder."""
from __future__ import annotations

import struct
from pathlib import Path

from idle_shutdown.capture.snss import (
    CMD_UPDATE_TAB_NAVIGATION,
    SNSS_MAGIC,
    PickleReader,
    default_snss_reader,
    read_snss_file,
)


# --- Pickle building helpers (mirror base::Pickle wire format) ----------------


def _align4(b: bytes) -> bytes:
    rem = len(b) % 4
    return b if rem == 0 else b + (b"\x00" * (4 - rem))


def p_int32(v: int) -> bytes:
    return struct.pack("<i", v)


def p_string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return _align4(p_int32(len(raw)) + raw)


def p_string16(s: str) -> bytes:
    raw = s.encode("utf-16-le")
    return _align4(p_int32(len(s)) + raw)


def pickle_blob(*parts: bytes) -> bytes:
    body = b"".join(parts)
    return p_int32(len(body)) + body  # 4-byte size header + payload


def update_tab_nav_payload(tab_id: int, nav_index: int, url: str, title: str) -> bytes:
    inner_body = p_int32(nav_index) + p_string(url) + p_string16(title)
    # Outer pickle: tab_id, then inner pickle as length-prefixed blob.
    outer_body = p_int32(tab_id) + p_int32(len(inner_body)) + inner_body
    return pickle_blob(*[outer_body])  # whole outer pickle (with its size header)


def make_snss(version: int, commands: list[tuple[int, bytes]]) -> bytes:
    out = bytearray(SNSS_MAGIC + struct.pack("<I", version))
    size_fmt = "<H" if version == 1 else "<I"
    for cmd_id, payload in commands:
        body = bytes([cmd_id]) + payload
        out += struct.pack(size_fmt, len(body)) + body
    return bytes(out)


# --- PickleReader primitives --------------------------------------------------


def test_pickle_reader_string_and_string16_roundtrip():
    blob = pickle_blob(p_int32(42) + p_string("hello") + p_string16("héllo"))
    r = PickleReader(blob)
    assert r.read_int32() == 42
    assert r.read_string() == "hello"
    assert r.read_string16() == "héllo"


def test_pickle_reader_alignment_padding_consumed():
    # 1-char UTF-8 string → 4-byte length + 1 byte + 3 padding
    blob = pickle_blob(p_string("x") + p_int32(7))
    r = PickleReader(blob)
    assert r.read_string() == "x"
    assert r.read_int32() == 7


# --- Framing + decode end-to-end ---------------------------------------------


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_v1_single_command(tmp_path: Path):
    payload = update_tab_nav_payload(1, 0, "https://example.com/", "Example")
    snss = make_snss(1, [(CMD_UPDATE_TAB_NAVIGATION, payload)])
    tabs = read_snss_file(_write(tmp_path, "Tabs_1", snss))
    assert len(tabs) == 1
    assert tabs[0].url == "https://example.com/"
    assert tabs[0].title == "Example"
    assert tabs[0].group is None


def test_v3_multi_command_keeps_latest_per_tab(tmp_path: Path):
    cmds = [
        (CMD_UPDATE_TAB_NAVIGATION, update_tab_nav_payload(1, 0, "https://a/", "A0")),
        (CMD_UPDATE_TAB_NAVIGATION, update_tab_nav_payload(1, 5, "https://a/v5", "A5")),
        (CMD_UPDATE_TAB_NAVIGATION, update_tab_nav_payload(2, 0, "https://b/", "B")),
        # Unknown command id — must be ignored, not crash framing.
        (99, b"\x00\x00\x00\x00garbage"),
    ]
    snss = make_snss(3, cmds)
    tabs = sorted(read_snss_file(_write(tmp_path, "Tabs_2", snss)), key=lambda t: t.url)
    assert [(t.url, t.title) for t in tabs] == [
        ("https://a/v5", "A5"),
        ("https://b/", "B"),
    ]


def test_bad_magic_returns_empty(tmp_path: Path):
    p = _write(tmp_path, "Tabs_3", b"NOPEv1bodybody")
    assert read_snss_file(p) == []


def test_truncated_command_stops_cleanly(tmp_path: Path):
    payload = update_tab_nav_payload(1, 0, "https://ok/", "ok")
    snss = make_snss(3, [(CMD_UPDATE_TAB_NAVIGATION, payload)])
    # Append a size prefix promising 200 bytes, then provide nothing.
    snss += struct.pack("<I", 200)
    tabs = read_snss_file(_write(tmp_path, "Tabs_4", snss))
    assert len(tabs) == 1


def test_default_reader_picks_latest_session_file(tmp_path: Path):
    sessions = tmp_path / "Sessions"
    sessions.mkdir()
    older = make_snss(3, [(CMD_UPDATE_TAB_NAVIGATION,
                           update_tab_nav_payload(1, 0, "https://old/", "old"))])
    newer = make_snss(3, [(CMD_UPDATE_TAB_NAVIGATION,
                           update_tab_nav_payload(1, 0, "https://new/", "new"))])
    o = sessions / "Tabs_100"; o.write_bytes(older)
    n = sessions / "Tabs_200"; n.write_bytes(newer)
    import os, time
    past = time.time() - 100
    os.utime(o, (past, past))
    windows = default_snss_reader(sessions)
    assert len(windows) == 1
    assert [t.url for t in windows[0].tabs] == ["https://new/"]


def test_default_reader_missing_dir_returns_empty(tmp_path: Path):
    assert default_snss_reader(tmp_path / "nope") == []
