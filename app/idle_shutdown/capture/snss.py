"""Chrome SNSS (Session) file reader.

Scope (MVP):
- Framing: parse the well-known SNSS file header (``SNSS`` magic + version 1
  or 3) and iterate commands. All supported versions use 2-byte size prefixes.
  Each command frame: ``size`` then 1-byte command id then ``size - 1`` bytes
  of payload.
- Inner payload uses Chromium's ``base::Pickle`` wire format: a 4-byte LE
  payload-size header (which we ignore — the outer frame already bounds it),
  followed by primitives padded to 4-byte alignment. We implement
  ``read_int32``, ``read_string`` (UTF-8) and ``read_string16`` (UTF-16LE).
- Command decoding: ONLY ``UpdateTabNavigation`` (id 1 in ``Tabs_*`` files,
  id 6 in ``Session_*`` files). Payload layout: ``int32 tab_id`` then
  Chromium ``SerializedNavigationEntry`` fields beginning with
  ``int32 nav_index, string url, string16 title, ...``. We keep the latest
  URL+title per tab_id and emit one window with all surviving tabs.

Out of scope (documented gap):
- ``kCommandSetTabGroup`` / ``kCommandTabGroupMetadataChanged2`` — wire layout
  has shifted across Chromium milestones; populating ``GroupName`` correctly
  requires fixtures from a real Windows Chrome profile. ``ChromeTabInfo.group``
  stays ``None`` until those fixtures exist.
- Window/tab ordering, tab closure tracking, multiple windows. We collapse
  everything into a single window for the MVP.

The reader never raises on malformed input — it logs and returns whatever it
managed to decode. Snapshot capture must be best-effort.
"""
from __future__ import annotations

import io
import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from idle_shutdown.capture.chrome import ChromeTabInfo, ChromeWindowInfo

logger = logging.getLogger(__name__)

SNSS_MAGIC = b"SNSS"
CMD_UPDATE_TAB_NAVIGATION = 6
CMD_TAB_RESTORE_UPDATE_TAB_NAVIGATION = 1
UPDATE_TAB_NAVIGATION_COMMAND_IDS = frozenset({
    CMD_UPDATE_TAB_NAVIGATION,
    CMD_TAB_RESTORE_UPDATE_TAB_NAVIGATION,
})
# Modern Chrome (file version >= 3) writes a marker command with this id at
# the end of the "initial state" block. It carries no useful payload and must
# be ignored by readers.
CMD_INITIAL_STATE_MARKER = 255
# Supported unencrypted SNSS file versions. v2/v4 were never shipped in
# production. v5 is OSCrypt-encrypted and cannot be decoded without the
# user's per-OS key — handled separately.
SUPPORTED_VERSIONS = (1, 3)
ENCRYPTED_VERSION = 5


# ---------------------------------------------------------------------------
# base::Pickle primitive reader
# ---------------------------------------------------------------------------


class PickleReader:
    """Minimal reader for the subset of base::Pickle we need.

    Pickles align every value to 4 bytes. Strings carry an int32 length
    (count of code units), then the bytes, then alignment padding.
    """

    __slots__ = ("_buf", "_pos")

    def __init__(self, data: bytes, *, skip_pickle_header: bool = True) -> None:
        self._buf = data
        self._pos = 0
        if skip_pickle_header and len(data) >= 4:
            # base::Pickle prefixes payload with a uint32 size; we already
            # know the size from the outer SNSS frame, so just skip it.
            self._pos = 4

    def _align(self) -> None:
        rem = self._pos % 4
        if rem:
            self._pos += 4 - rem

    def remaining(self) -> int:
        return max(0, len(self._buf) - self._pos)

    def read_int32(self) -> int:
        if self.remaining() < 4:
            raise EOFError("pickle: truncated int32")
        v = struct.unpack_from("<i", self._buf, self._pos)[0]
        self._pos += 4
        return int(v)

    def read_string(self) -> str:
        n = self.read_int32()
        if n < 0 or n > self.remaining():
            raise EOFError(f"pickle: bogus string length {n}")
        raw = self._buf[self._pos : self._pos + n]
        self._pos += n
        self._align()
        return raw.decode("utf-8", errors="replace")

    def read_string16(self) -> str:
        n = self.read_int32()  # number of UTF-16 code units
        if n < 0:
            raise EOFError(f"pickle: bogus string16 length {n}")
        byte_len = n * 2
        if byte_len > self.remaining():
            raise EOFError(f"pickle: truncated string16 ({byte_len} bytes)")
        raw = self._buf[self._pos : self._pos + byte_len]
        self._pos += byte_len
        self._align()
        return raw.decode("utf-16-le", errors="replace")


# ---------------------------------------------------------------------------
# SNSS framing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RawCommand:
    command_id: int
    payload: bytes


def _iter_commands(stream: io.BufferedReader) -> Iterator[_RawCommand]:
    header = stream.read(8)
    if len(header) < 8 or header[:4] != SNSS_MAGIC:
        raise ValueError("not an SNSS file (bad magic)")
    version = struct.unpack("<I", header[4:8])[0]
    if version == ENCRYPTED_VERSION:
        raise ValueError("SNSS v5 is OSCrypt-encrypted; cannot decode")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported SNSS version {version}")
    # SessionCommand::size_type is uint16_t for ALL versions (see Chromium
    # components/sessions/core/session_command.h). The earlier 4-byte guess
    # for v3 was wrong and caused every modern session file to parse as a
    # single absurdly-large garbage frame.
    size_fmt = "<H"
    size_bytes = 2

    while True:
        sz_raw = stream.read(size_bytes)
        if not sz_raw:
            return
        if len(sz_raw) < size_bytes:
            logger.warning("event=snss_truncated_size_prefix")
            return
        size = struct.unpack(size_fmt, sz_raw)[0]
        if size == 0:
            continue
        body = stream.read(size)
        if len(body) < size:
            logger.warning("event=snss_truncated_body want=%d got=%d", size, len(body))
            return
        yield _RawCommand(command_id=body[0], payload=body[1:])


# ---------------------------------------------------------------------------
# Command decoding
# ---------------------------------------------------------------------------


@dataclass
class _TabState:
    nav_index: int = -1
    url: str = ""
    title: str = ""


def _decode_update_tab_navigation(payload: bytes) -> tuple[int, _TabState] | None:
    try:
        outer = PickleReader(payload, skip_pickle_header=True)
        tab_id = outer.read_int32()
        # Chromium writes SerializedNavigationEntry fields directly after the
        # tab id; it is not a nested pickle/blob. We only need the first three
        # fields for snapshot capture.
        nav_index = outer.read_int32()
        url = outer.read_string()
        title = outer.read_string16()
        return tab_id, _TabState(nav_index=nav_index, url=url, title=title)
    except (EOFError, struct.error) as e:
        logger.debug("event=snss_decode_skip cmd=update_tab_navigation err=%s", e)
        return None


def read_snss_file(path: Path) -> list[ChromeTabInfo]:
    """Decode one SNSS file into a flat list of tabs (latest entry per tab_id)."""
    tabs: dict[int, _TabState] = {}
    try:
        with path.open("rb") as fh:
            for cmd in _iter_commands(fh):
                if cmd.command_id == CMD_INITIAL_STATE_MARKER:
                    continue
                if cmd.command_id not in UPDATE_TAB_NAVIGATION_COMMAND_IDS:
                    continue
                decoded = _decode_update_tab_navigation(cmd.payload)
                if decoded is None:
                    continue
                tab_id, state = decoded
                # Keep the entry with the highest nav_index per tab.
                cur = tabs.get(tab_id)
                if cur is None or state.nav_index >= cur.nav_index:
                    tabs[tab_id] = state
    except (OSError, ValueError) as e:
        logger.warning("event=snss_read_failed path=%s err=%s", path, e)
        return []

    return [
        ChromeTabInfo(url=s.url, title=s.title, group=None)
        for tab_id, s in sorted(tabs.items())
        if s.url
    ]


def _latest_session_file(sessions_dir: Path) -> Path | None:
    if not sessions_dir.exists():
        return None
    candidates: list[Path] = []
    # Modern Chrome writes "Current Tabs"/"Current Session" (live) and
    # "Last Tabs"/"Last Session" (previous run) with a space. Older Chrome
    # also kept numbered backups like "Tabs_<N>"/"Session_<N>".
    for pattern in ("Current Tabs", "Last Tabs", "Tabs_*",
                    "Current Session", "Last Session", "Session_*"):
        candidates.extend(sessions_dir.glob(pattern))
    if not candidates:
        return None
    # Prefer Tabs* over Session* (smaller, tab-focused), then most recent mtime.
    def _key(p: Path):
        is_tabs = "Tabs" in p.name
        return (1 if is_tabs else 0, p.stat().st_mtime)
    return max(candidates, key=_key)


def default_snss_reader(sessions_dir: Path) -> list[ChromeWindowInfo]:
    """Default ``snss_reader`` for ``capture_chrome_session``.

    Picks the most-recently-modified ``Tabs_*`` (preferred) or ``Session_*``
    file in ``sessions_dir`` and decodes it. Returns at most one window.
    """
    target = _latest_session_file(sessions_dir)
    if target is None:
        logger.info("event=snss_no_session_file dir=%s", sessions_dir)
        return []
    tabs = read_snss_file(target)
    if not tabs:
        return []
    return [ChromeWindowInfo(tabs=tuple(tabs))]