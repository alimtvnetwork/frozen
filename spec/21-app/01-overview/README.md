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
