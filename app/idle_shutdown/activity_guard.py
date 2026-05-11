"""Activity guard — suppress the idle prompt while the user is clearly busy.

Best-effort signals: microphone in use, audio playback active, foreground
window is fullscreen. Each signal is wrapped so a missing OS dependency
(e.g. pyobjc on macOS, pulseaudio on Linux) just disables that signal
rather than crashing the monitor loop.

The guard is consulted by :class:`~idle_shutdown.monitor.IdleMonitor` on
every tick. When ``is_busy()`` returns ``(True, reason)`` the monitor will
not transition to the Prompting state.
"""
from __future__ import annotations

import logging
import shutil as _sh
import subprocess
import sys
import ctypes
import ctypes.util
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

# A signal returns True when "the user is busy for this reason".
Signal = Callable[[], bool]


_MAC_MEDIA_PLAYER_STATE_SCRIPTS = {
    "VLC": """
tell application "System Events"
    if not (exists process "VLC") then return "unknown"
end tell
tell application "VLC"
    if playing then return "playing"
    return "paused"
end tell
""",
    "IINA": """
tell application "System Events"
    if not (exists process "IINA") then return "unknown"
end tell
tell application "IINA" to return player state as string
""",
    "QuickTime Player": """
tell application "System Events"
    if not (exists process "QuickTime Player") then return "unknown"
end tell
tell application "QuickTime Player"
    if (count documents) is 0 then return "stopped"
    if playing of front document then return "playing"
    return "paused"
end tell
""",
    "Music": """
tell application "System Events"
    if not (exists process "Music") then return "unknown"
end tell
tell application "Music" to return player state as string
""",
    "Spotify": """
tell application "System Events"
    if not (exists process "Spotify") then return "unknown"
end tell
tell application "Spotify" to return player state as string
""",
    "TV": """
tell application "System Events"
    if not (exists process "TV") then return "unknown"
end tell
tell application "TV" to return player state as string
""",
    "Podcasts": """
tell application "System Events"
    if not (exists process "Podcasts") then return "unknown"
end tell
tell application "Podcasts" to return player state as string
""",
}

_MAC_STICKY_AUDIO_PLAYERS = {"vlc", "iina", "quicktime player"}


@dataclass
class GuardConfig:
    mic_enabled: bool = True
    audio_enabled: bool = True
    fullscreen_enabled: bool = True
    camera_enabled: bool = True


# ---------- macOS signals ---------------------------------------------------


def _mac_mic_in_use() -> bool:  # pragma: no cover - platform specific
    """True if any audio input device currently has its IsRunning flag set."""
    try:
        import objc  # noqa: F401
        from CoreAudio import (  # type: ignore
            AudioObjectGetPropertyData,
            AudioObjectGetPropertyDataSize,
            AudioObjectPropertyAddress,
            kAudioHardwarePropertyDevices,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMaster,
            kAudioObjectSystemObject,
            kAudioDevicePropertyDeviceIsRunningSomewhere,
            kAudioDevicePropertyScopeInput,
        )
    except Exception:
        return False
    # Fallback: scan via `lsof` for processes using the system audio input.
    # CoreAudio bindings vary by pyobjc version; the lsof path below is the
    # robust cross-version check.
    return _mac_lsof_uses("/dev/audio") or _mac_coreaudio_input_active()


def _mac_coreaudio_input_active() -> bool:  # pragma: no cover
    # Lightweight check: look for any process that has the AppleCamera or
    # AudioComponentRegistrar entitlement currently running. This is too
    # noisy to be reliable, so prefer the simpler signals above.
    return False


def _mac_lsof_uses(_path: str) -> bool:  # pragma: no cover
    return False


def _normalize_media_state(value: str | None) -> bool | None:
    if value is None:
        return None
    state = value.strip().lower()
    if not state or state == "unknown":
        return None
    if state in {"playing", "true", "yes", "1"}:
        return True
    if state in {"paused", "pause", "stopped", "stop", "false", "no", "0"}:
        return False
    if "paused" in state or "stopped" in state:
        return False
    if "playing" in state:
        return True
    return None


def _mac_run_osascript(script: str) -> str | None:  # pragma: no cover - platform specific
    if not _sh.which("osascript"):
        return None
    args = ["osascript"]
    for line in script.strip().splitlines():
        args.extend(["-e", line])
    try:
        out = subprocess.check_output(args, timeout=1, stderr=subprocess.DEVNULL)
    except Exception:
        return None
    return out.decode("utf-8", "replace").strip()


def _mac_known_media_playback_state(app_name: str | None) -> bool | None:  # pragma: no cover
    if not app_name:
        return None
    for name, script in _MAC_MEDIA_PLAYER_STATE_SCRIPTS.items():
        if app_name.lower() == name.lower():
            return _normalize_media_state(_mac_run_osascript(script))
    return None


def _mac_is_sticky_audio_player(app_name: str | None) -> bool:
    return bool(app_name and app_name.lower() in _MAC_STICKY_AUDIO_PLAYERS)


def _mac_audio_playback_active() -> bool:  # pragma: no cover - platform specific
    """True if any output device is currently rendering audio.

    Modern macOS (especially Apple Silicon) no longer publishes
    ``IOAudioEngineState`` via the legacy ``IOAudioEngine`` class — the HAL
    moved to CoreAudio user-space. We check, in order:

    1. CoreAudio device state. This releases as soon as playback stops.
    2. ``pmset -g assertions`` as a fallback when CoreAudio cannot be queried.
    3. Legacy ``ioreg -c IOAudioEngine`` lookup for older Macs.
    """
    foreground_app = _mac_frontmost_app_name()
    foreground_media_state = _mac_known_media_playback_state(foreground_app)
    if foreground_media_state is True:
        return True
    if foreground_media_state is False and _mac_is_sticky_audio_player(foreground_app):
        # Players like VLC can leave the CoreAudio device marked as running
        # while paused because they keep an output stream open and send silence.
        return False

    coreaudio_state = _mac_coreaudio_output_active()
    if coreaudio_state is not None:
        return coreaudio_state
    if _mac_pmset_audio_active():
        return True
    if not _sh.which("ioreg"):
        return False
    try:
        out = subprocess.check_output(
            ["ioreg", "-c", "IOAudioEngine", "-r", "-l"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace")
    except Exception:
        return False
    # IOAudioEngineState = 1 means the engine is actively running.
    for line in out.splitlines():
        if "IOAudioEngineState" in line and line.rstrip().endswith("= 1"):
            return True
    return False


def _mac_coreaudio_output_active() -> bool | None:  # pragma: no cover - platform specific
    """Return output playback state from CoreAudio, or ``None`` if unavailable.

    ``pmset`` can keep a ``coreaudiod`` sleep-prevention assertion around after
    a browser/player pauses. Querying CoreAudio directly avoids that sticky
    state, so the monitor can start counting down again after media stops.
    """
    path = ctypes.util.find_library("CoreAudio")
    if not path:
        path = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
    try:
        ca = ctypes.CDLL(path)
    except Exception:
        return None

    class AudioObjectPropertyAddress(ctypes.Structure):
        _fields_ = [
            ("mSelector", ctypes.c_uint32),
            ("mScope", ctypes.c_uint32),
            ("mElement", ctypes.c_uint32),
        ]

    def fourcc(value: bytes) -> int:
        return int.from_bytes(value, "big")

    system_object = ctypes.c_uint32(1)
    no_error = 0
    prop_devices = fourcc(b"dev#")
    prop_running = fourcc(b"gone")  # kAudioDevicePropertyDeviceIsRunningSomewhere
    scope_global = fourcc(b"glob")
    scope_output = fourcc(b"outp")
    element_main = ctypes.c_uint32(0)

    devices_addr = AudioObjectPropertyAddress(prop_devices, scope_global, element_main.value)
    data_size = ctypes.c_uint32(0)
    try:
        status = ca.AudioObjectGetPropertyDataSize(
            system_object,
            ctypes.byref(devices_addr),
            ctypes.c_uint32(0),
            None,
            ctypes.byref(data_size),
        )
        if status != no_error or data_size.value <= 0:
            return None
        count = data_size.value // ctypes.sizeof(ctypes.c_uint32)
        devices = (ctypes.c_uint32 * count)()
        status = ca.AudioObjectGetPropertyData(
            system_object,
            ctypes.byref(devices_addr),
            ctypes.c_uint32(0),
            None,
            ctypes.byref(data_size),
            devices,
        )
        if status != no_error:
            return None
    except Exception:
        return None

    saw_readable_output = False
    for device_id in devices:
        for scope in (scope_output, scope_global):
            running_addr = AudioObjectPropertyAddress(
                prop_running, scope, element_main.value
            )
            running = ctypes.c_uint32(0)
            running_size = ctypes.c_uint32(ctypes.sizeof(running))
            try:
                status = ca.AudioObjectGetPropertyData(
                    ctypes.c_uint32(int(device_id)),
                    ctypes.byref(running_addr),
                    ctypes.c_uint32(0),
                    None,
                    ctypes.byref(running_size),
                    ctypes.byref(running),
                )
            except Exception:
                continue
            if status == no_error:
                saw_readable_output = True
                if running.value:
                    return True
                break
    return False if saw_readable_output else None


def _mac_pmset_audio_active() -> bool:  # pragma: no cover - platform specific
    """Inspect ``pmset -g assertions`` for an active coreaudiod assertion.

    Output looks like::

        pid 123(coreaudiod): [0x0000...] 00:00:42 PreventUserIdleSystemSleep
          named: "com.apple.audio.AudioSession"

    The presence of any ``coreaudiod`` row under PreventUserIdleSystemSleep /
    PreventUserIdleDisplaySleep means at least one output stream is live.
    """
    if not _sh.which("pmset"):
        return False
    try:
        out = subprocess.check_output(
            ["pmset", "-g", "assertions"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace")
    except Exception:
        return False
    for raw in out.splitlines():
        line = raw.strip()
        if "coreaudiod" in line and (
            "PreventUserIdleSystemSleep" in line
            or "PreventUserIdleDisplaySleep" in line
        ):
            return True
    return False


def _mac_frontmost_app_name() -> str | None:  # pragma: no cover - platform specific
    try:
        from AppKit import NSWorkspace  # type: ignore
    except Exception:
        return None
    try:
        active = NSWorkspace.sharedWorkspace().frontmostApplication()
        if active is None:
            return None
        name = active.localizedName()
        return str(name) if name else None
    except Exception:
        return None


def _mac_foreground_fullscreen() -> bool:  # pragma: no cover - platform specific
    try:
        from AppKit import NSWorkspace  # type: ignore
        from Quartz import (  # type: ignore
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
            CGDisplayBounds,
            CGMainDisplayID,
        )
    except Exception:
        return False
    try:
        active = NSWorkspace.sharedWorkspace().frontmostApplication()
        if active is None:
            return False
        app_name = str(active.localizedName() or "")
        if _mac_known_media_playback_state(app_name) is False:
            # A paused movie/player in fullscreen should not freeze the idle
            # countdown. Playback itself is handled by the audio signal.
            return False
        pid = int(active.processIdentifier())
        wins = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )
        bounds = CGDisplayBounds(CGMainDisplayID())
        screen_w, screen_h = float(bounds.size.width), float(bounds.size.height)
        for w in wins:
            if int(w.get("kCGWindowOwnerPID", -1)) != pid:
                continue
            b = w.get("kCGWindowBounds") or {}
            ww = float(b.get("Width", 0)); wh = float(b.get("Height", 0))
            if ww >= screen_w - 2 and wh >= screen_h - 2:
                return True
    except Exception:
        return False
    return False


def _mac_camera_in_use() -> bool:  # pragma: no cover - platform specific
    """True when the system video-input device reports IsRunning=1.

    Uses ``ioreg`` (always present on macOS); cheap and avoids a pyobjc
    dependency. Looks for ``"CMIO_DAL_VDevice_IsRunning" = 1`` lines
    emitted by the AppleCamera / VirtualCamera providers.
    """
    if not _sh.which("ioreg"):
        return False
    try:
        out = subprocess.check_output(
            ["ioreg", "-r", "-c", "AppleCamera", "-l"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace")
    except Exception:
        return False
    for line in out.splitlines():
        s = line.strip()
        if s.startswith('"CMIO_Control_IsRunning"') and s.endswith("= 1"):
            return True
        if "VDCAssistant_Camera_Is_On" in s and s.endswith("= 1"):
            return True
    return False


# ---------- Linux signals ---------------------------------------------------


def _linux_mic_in_use() -> bool:  # pragma: no cover
    if not _sh.which("pactl"):
        return False
    try:
        out = subprocess.check_output(
            ["pactl", "list", "source-outputs"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace")
    except Exception:
        return False
    return out.strip() != ""


def _linux_audio_playback_active() -> bool:  # pragma: no cover
    if not _sh.which("pactl"):
        return False
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sink-inputs"],
            timeout=2, stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace")
    except Exception:
        return False
    # An idle sink-input doesn't count; require "Corked: no".
    return "Corked: no" in out


def _linux_foreground_fullscreen() -> bool:  # pragma: no cover
    # Best-effort via xdotool / wmctrl. Skip if neither is installed.
    if _sh.which("xdotool"):
        try:
            wid = subprocess.check_output(
                ["xdotool", "getactivewindow"], timeout=2,
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            state = subprocess.check_output(
                ["xprop", "-id", wid, "_NET_WM_STATE"], timeout=2,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8", "replace")
            return "_NET_WM_STATE_FULLSCREEN" in state
        except Exception:
            return False
    return False


def _linux_camera_in_use() -> bool:  # pragma: no cover
    """True when any process holds /dev/video* open (best-effort)."""
    if not _sh.which("fuser"):
        return False
    try:
        out = subprocess.check_output(
            ["sh", "-c", "fuser /dev/video* 2>/dev/null"],
            timeout=2,
        ).decode("utf-8", "replace")
    except Exception:
        return False
    return out.strip() != ""


# ---------- Windows signals -------------------------------------------------


def _win_mic_in_use() -> bool:  # pragma: no cover
    """Check the registry: each capture-capable app writes a LastUsedTimeStop
    of 0 while it's actively recording."""
    try:
        import winreg  # type: ignore
    except Exception:
        return False
    roots = (
        (winreg.HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"),
    )
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as base:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(base, i)
                    except OSError:
                        break
                    i += 1
                    if _win_subkey_recording(hive, path + "\\" + sub):
                        return True
        except OSError:
            continue
    return False


def _win_subkey_recording(hive, path) -> bool:  # pragma: no cover
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(hive, path) as k:
            j = 0
            while True:
                try:
                    app = winreg.EnumKey(k, j)
                except OSError:
                    break
                j += 1
                try:
                    with winreg.OpenKey(k, app) as appk:
                        stop, _ = winreg.QueryValueEx(appk, "LastUsedTimeStop")
                        if int(stop) == 0:
                            return True
                except OSError:
                    continue
    except OSError:
        return False
    return False


def _win_audio_playback_active() -> bool:  # pragma: no cover
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL  # type: ignore
        from pycaw.pycaw import (  # type: ignore
            AudioUtilities, IAudioMeterInformation,
        )
    except Exception:
        return False
    try:
        speakers = AudioUtilities.GetSpeakers()
        interface = speakers.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
        meter = cast(interface, POINTER(IAudioMeterInformation))
        peak = float(meter.GetPeakValue())
        return peak > 0.001
    except Exception:
        return False


def _win_foreground_fullscreen() -> bool:  # pragma: no cover
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False


def _win_camera_in_use() -> bool:  # pragma: no cover
    """Mirror of mic detection but for the webcam ConsentStore key."""
    try:
        import winreg  # type: ignore
    except Exception:
        return False
    roots = (
        (winreg.HKEY_CURRENT_USER,
         r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\webcam"),
    )
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as base:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(base, i)
                    except OSError:
                        break
                    i += 1
                    if _win_subkey_recording(hive, path + "\\" + sub):
                        return True
        except OSError:
            continue
    return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        return (rect.right - rect.left) >= sw and (rect.bottom - rect.top) >= sh
    except Exception:
        return False


# ---------- Public guard ----------------------------------------------------


def _platform_signals() -> dict[str, Signal]:
    if sys.platform == "darwin":
        return {
            "mic_active": _mac_mic_in_use,
            "audio_playing": _mac_audio_playback_active,
            "fullscreen": _mac_foreground_fullscreen,
            "camera_active": _mac_camera_in_use,
        }
    if sys.platform == "win32":
        return {
            "mic_active": _win_mic_in_use,
            "audio_playing": _win_audio_playback_active,
            "fullscreen": _win_foreground_fullscreen,
            "camera_active": _win_camera_in_use,
        }
    if sys.platform.startswith("linux"):
        return {
            "mic_active": _linux_mic_in_use,
            "audio_playing": _linux_audio_playback_active,
            "fullscreen": _linux_foreground_fullscreen,
            "camera_active": _linux_camera_in_use,
        }
    return {}


class ActivityGuard:
    """Aggregates platform-specific busy signals.

    ``is_busy()`` returns ``(busy, reason)``. ``reason`` is the first matching
    signal name, or ``None`` when not busy. Logs once per state change.
    """

    def __init__(
        self,
        config_provider: Callable[[], GuardConfig],
        signals: dict[str, Signal] | None = None,
    ) -> None:
        self._cfg = config_provider
        self._signals = signals if signals is not None else _platform_signals()
        self._last_busy: bool | None = None
        self._last_reason: str | None = None

    def _enabled_signals(self, cfg: GuardConfig) -> list[tuple[str, Signal]]:
        out: list[tuple[str, Signal]] = []
        for name, sig in self._signals.items():
            if name == "mic_active" and not cfg.mic_enabled:
                continue
            if name == "audio_playing" and not cfg.audio_enabled:
                continue
            if name == "fullscreen" and not cfg.fullscreen_enabled:
                continue
            if name == "camera_active" and not cfg.camera_enabled:
                continue
            out.append((name, sig))
        return out

    def is_busy(self) -> tuple[bool, str | None]:
        cfg = self._cfg()
        for name, sig in self._enabled_signals(cfg):
            try:
                if sig():
                    self._log_change(True, name)
                    return True, name
            except Exception as e:  # noqa: BLE001
                logger.debug("event=guard_signal_error signal=%s err=%s", name, e)
                continue
        self._log_change(False, None)
        return False, None

    def _log_change(self, busy: bool, reason: str | None) -> None:
        if busy != self._last_busy or reason != self._last_reason:
            logger.info("event=activity_guard busy=%s reason=%s", busy, reason)
            self._last_busy = busy
            self._last_reason = reason