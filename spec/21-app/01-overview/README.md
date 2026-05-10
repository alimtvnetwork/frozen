# 01 — Overview

## Purpose
Lightweight Windows desktop utility that detects user inactivity, prompts the user, and on no-response performs a graceful shutdown after capturing a complete session snapshot to SQLite. On next boot it restores virtual desktops, applications, and Chrome tabs.

## Stack
- **Language**: Python 3.11+
- **GUI**: `tkinter` (stdlib) for the inactivity popup
- **CLI**: `click`
- **Activity hook**: `pywin32` `GetLastInputInfo`
- **Process info**: `psutil`
- **Virtual desktops**: `pyvda`
- **Storage**: `sqlite3` (stdlib) — single source of truth
- **Autostart**: `HKCU\...\Run` registry value via `winreg`
- **Distribution**: PyInstaller-frozen single-file `idle-shutdown.exe`. No Python required on target machine.

## Entrypoint (locked)
The shipped artifact is `idle-shutdown.exe` (Windows x64). All commands in `08-cli-commands/` are invoked as `idle-shutdown.exe <command> [args]`. Source-tree development still works via `python -m idle_shutdown <command>`; both paths must produce identical behavior and exit codes.

## Target environment
- Windows 10 build 19041+ or Windows 11 (any build). x64 only.
- Single user session. Multi-session/RDP not supported in MVP.
- Standard user privileges sufficient. No admin rights required for any command.

## MVP scope (4–5h)
Core flow first: idle detection → popup → snapshot → shutdown → restore. CLI commands wrap the same internals.

## Cut-lines (deferred past MVP)
- Chrome tab **group** fidelity — needs companion browser extension. MVP stores URL + title per window only.
- Per-virtual-desktop application restore mapping — `pyvda` can read but window→desktop attach on relaunch is fragile. MVP recreates N desktops and launches all apps on desktop 1.
- Per-application graceful quit beyond WM_CLOSE.

## Non-goals
- Multi-user / multi-machine sync.
- Cloud backup. SQLite file is local only.
- Cross-browser support (Firefox/Edge) — Chrome only.
