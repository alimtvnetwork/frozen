# Idle Shutdown

**Windows idle-detection, session-snapshot, and graceful-shutdown utility**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2B-0078D6?style=flat-square&logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](./LICENSE)
[![Build](https://img.shields.io/badge/build-PyInstaller%20%C2%B7%20Inno%20Setup-blue?style=flat-square)](#build--release)
[![Status](https://img.shields.io/badge/status-MVP%20%E2%86%92%20go--live-orange?style=flat-square)](../docs/RUNBOOK-go-live.md)

_Detect idle, prompt the user, snapshot every open app + Chrome tab + virtual desktop to SQLite, shut down cleanly — and put it all back on next sign-in._

---

## Why Idle Shutdown?

Leaving a workstation running for hours of inactivity wastes power and (on shared machines) leaks an open session. Just shutting it down loses your context — the apps you had open, the Chrome tabs you were halfway through, the virtual-desktop layout you spent the morning arranging.

**Idle Shutdown** does both: it watches for real keyboard/mouse idleness, asks once, and on no-response captures the entire session into a single local SQLite file before invoking `shutdown.exe`. On the next sign-in it replays the snapshot — virtual desktops recreated, apps relaunched on their original desktop, Chrome reopened with every saved tab.

One binary. One `%APPDATA%\IdleShutdown\state.sqlite` file. No cloud, no telemetry, no admin rights.

---

## 🚀 Install

Idle Shutdown is a **Windows-only** desktop utility (Windows 10 build 19041+ or Windows 11, x64). The commands below install the latest release with sensible defaults — no admin prompt, per-user only.

### 🪟 Windows · Installer (recommended)

Download the latest `IdleShutdownSetup-x.y.z.exe` from the [Releases](#) page and double-click it.

SmartScreen may warn ("Unknown publisher") because the build is unsigned for now — click **More info → Run anyway**. The installer is **per-user** (no admin prompt). On the final page you can tick:

- **Start when I sign in to Windows** — wires the `HKCU\…\Run` autostart entry.
- **Initialize the local settings database now** — creates `%APPDATA%\IdleShutdown\state.sqlite` with the default thresholds.
- **Start now** — launches the background service immediately.

### 🪟 Windows · Single .exe (no installer)

```powershell
# 1. Drop the binary anywhere on disk
mkdir $env:LOCALAPPDATA\Programs\IdleShutdown
Move-Item .\idle-shutdown.exe $env:LOCALAPPDATA\Programs\IdleShutdown\

# 2. One-time setup
& $env:LOCALAPPDATA\Programs\IdleShutdown\idle-shutdown.exe init-db
& $env:LOCALAPPDATA\Programs\IdleShutdown\idle-shutdown.exe install-autostart

# 3. Start now (or sign out / back in)
& $env:LOCALAPPDATA\Programs\IdleShutdown\idle-shutdown.exe run --silent
```

### 📌 Pinned version (`v0.1.0`)

```powershell
# Windows · PowerShell — exact tag, no fallback
$tag = "v0.1.0"
$url = "https://github.com/<owner>/idle-shutdown/releases/download/$tag/IdleShutdownSetup-$tag.exe"
Invoke-WebRequest -Uri $url -OutFile "$env:TEMP\IdleShutdownSetup.exe"
Start-Process "$env:TEMP\IdleShutdownSetup.exe" -Wait
```

#### 🧭 Version matrix — `v0.1.0` release assets

| Platform | Asset | Filename |
|---|---|---|
| Windows (amd64) — installer | Inno Setup installer | `IdleShutdownSetup-0.1.0.exe` |
| Windows (amd64) — single exe | PyInstaller one-file | `idle-shutdown-0.1.0-windows-amd64.exe` |
| Windows (amd64) — checksums | SHA256 manifest | `SHA256SUMS-0.1.0.txt` |

> **Asset naming contract:** `IdleShutdownSetup-<version>.exe` for the installer, `idle-shutdown-<version>-windows-amd64.exe` for the standalone binary. Verified by the build script (`build/build.ps1`) and printed to stdout as a SHA256 line per artifact.

### 🎯 Install — Quick (custom install folder)

Use this **only** when you want a non-default install folder (e.g. `D:\Tools\IdleShutdown\`). Run the installer with the silent flag:

```powershell
.\IdleShutdownSetup-0.1.0.exe /VERYSILENT /DIR="D:\Tools\IdleShutdown" /TASKS="autostart,initdb"
```

Available `/TASKS` values:

| Task | Effect |
|---|---|
| `autostart` | Write the `HKCU\…\Run` entry so the service launches on sign-in |
| `initdb` | Create `%APPDATA%\IdleShutdown\state.sqlite` with default settings |
| `startnow` | Spawn `idle-shutdown.exe run --silent` after install completes |

> **How install resolves a version:** the installer is a single self-contained Inno Setup `.exe` baked at release time. **Strict tag mode** (downloading `IdleShutdownSetup-vX.Y.Z.exe`) installs that exact build with **no fallback whatsoever** — missing tag → HTTP 404 → exit 1. There is no online discovery, no `latest` redirect, no auto-update at install time. Updates are explicit: download the new installer.

---

## About Idle Shutdown

### What is Idle Shutdown?

**Idle Shutdown** is a lightweight Windows desktop utility that turns the gap between "I walked away from my PC" and "I'm signing back in" into a clean round-trip. It runs silently in the background, watches the OS-level idle timer, prompts the user when the threshold trips, and on no-response captures a full session snapshot to SQLite before invoking the standard Windows shutdown sequence. On next sign-in it restores everything.

One PyInstaller-frozen `idle-shutdown.exe`. One `%APPDATA%\IdleShutdown\` data folder. Every command in [`USER_GUIDE.md`](USER_GUIDE.md) is a subcommand of that single binary.

### Why Idle Shutdown?

Because the alternatives are all worse:

- **Doing nothing** — the PC runs all night, burns power, and stays unlocked.
- **Windows' built-in "Sleep after N minutes"** — sleep is not shutdown. The session is still resident, the disk is still mounted, and waking from S3/S4 has its own reliability problems.
- **A Task Scheduler `shutdown /s` job** — fires blind. No prompt, no snapshot, no restore. Loses your work.
- **Hand-rolled scripts** — a different one per machine, no audit trail, no idempotent restore.

Idle Shutdown replaces all of that with a single, deterministic, observable workflow:

- **One idle monitor** that uses Windows' own `GetLastInputInfo` (no polling for keystrokes).
- **One always-on-top popup** with a countdown — Yes/No/auto-shutdown.
- **One transactional snapshot** to SQLite (apps + Chrome tabs + virtual desktops) committed before any process is touched.
- **One graceful shutdown** — `WM_CLOSE` to every visible window, then `shutdown.exe /s /t 5` so the user has a 5-second cancel window.
- **One idempotent restore** on the next sign-in — duplicate-prevention by exe + DocumentPath, safe to run twice.

### Why it exists — the origin story

Idle Shutdown started as a one-evening fix for a very ordinary problem: a workstation that I kept walking away from with **a dozen apps and forty Chrome tabs open**, only to either find it still running the next morning or — when I tried "Sleep after 30 minutes" — find that the machine had locked up overnight and lost the session anyway.

So in a couple of focused sessions, with the help of AI coding tools, the first version was built: detect idle, prompt, dump the open windows and Chrome tabs to SQLite, run `shutdown /s /t 5`, and on next boot relaunch everything from the snapshot.

That tiny utility worked. Then it kept growing. After **months of dogfooding, refactors, and feature additions** (per-virtual-desktop placement, Chromium-variant detection, JSON logging, tray icon, snapshot-failure toasts, `doctor` / `self-test` diagnostics) it has turned into the all-in-one Windows session-management CLI you see today.

### What Idle Shutdown actually does

At its heart `idle-shutdown` does one thing extremely well: it treats your **session as a serializable object** and lets you snapshot, shut down, and restore it as a single atomic operation. Every command flows from that idea.

#### 🕒 Idle detection & popup
- Polls `GetLastInputInfo` (no global keyboard hook — no AV false positives).
- Configurable threshold (`settings set-idle MINUTES`, default 15).
- Always-on-top Tk popup with a countdown (`settings set-countdown SECONDS`, default 60). Yes / No / Do-nothing → auto-shutdown.
- Mouse or keyboard activity while the popup is open counts as "Yes".

#### 📸 Transactional snapshot capture
- One SQLite transaction wraps virtual desktops + running apps + Chrome windows + tabs + the `ShutdownLog` row.
- Apps captured via `psutil`: executable path, working directory, best-effort document path heuristic from the command line. System processes (`explorer.exe`, `dwm.exe`, …) are excluded.
- Chrome tabs read straight from Chrome's own session files (the `Tabs` SNSS file per profile). Multi-profile, multi-Chromium-variant aware (Chrome / Edge / Brave / Vivaldi).
- Virtual desktops captured via `pyvda` — count + best-effort window→desktop map.
- If any step throws, the whole transaction rolls back and a `ShutdownLog` row with outcome `Failed` is written in a separate transaction so failures are observable via `status` / `doctor`.

#### 🧯 Graceful shutdown sequence
- Enumerate top-level visible windows (`EnumWindows` + `IsWindowVisible`), skip own process and `explorer.exe`.
- Send `WM_CLOSE`, wait up to 5s per app for clean exit.
- Invoke `shutdown.exe /s /t 5 /f /c "Idle auto-shutdown"` — Windows handles the rest. The `/t 5` gives the user a 5-second `shutdown /a` cancel window.

#### 🔁 Idempotent restore on next sign-in
- Recreates the recorded number of virtual desktops via `pyvda`.
- For each `AppProcess`, checks live processes with `psutil`: **skip the launch** if any running process matches both the executable path AND (substring) the recorded `DocumentPath`. Result: running `restore` twice is a no-op the second time.
- Launches Chrome with `--restore-last-session`, falling back to passing every saved `ChromeTab.Url` as a positional arg if the session is stale.
- Marks `LastRestoredSnapshotId` + `LastRestoredAt` so auto-restore on boot only fires for genuinely new snapshots.

#### 🩺 Self-managing diagnostics
- `idle-shutdown doctor` — colored preflight table, exits non-zero on FAIL. Includes the consecutive-snapshot-failure streak.
- `idle-shutdown status [--json]` — one-shot health view: idle seconds, snapshot count, last heartbeat, failure streak, crash-recovery flag. JSON form is stable for scripting.
- `idle-shutdown self-test [--json] [--keep]` — round-trip sanity check: take a fresh snapshot, dry-run-restore it, report what would be relaunched, delete the test snapshot.
- `idle-shutdown reset-failures` — clear the snapshot-failure latch after fixing the root cause; re-arms the toast notification.
- `idle-shutdown export-config` / `import-config` — round-trip settings + restore exclusions as JSON, e.g. when moving setup across machines.

#### 🛎️ Optional extras
- `pip install -e ".[tray]"` — system-tray icon (`idle-shutdown tray`).
- `pip install -e ".[notify]"` — Windows toasts when N background snapshots fail in a row.

#### 🧱 Self-managing installation
- `install-autostart` / `uninstall-autostart` manage the `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` registry value. No admin rights required.
- `init-db` creates / re-seeds the SQLite file. Safe to run on a missing DB.
- The Inno Setup installer wires both of those in one click.

### TL;DR

> **A single Windows binary that watches for idle, asks once, snapshots your full session (apps + Chrome tabs + virtual desktops) to SQLite, shuts down cleanly, and restores it all on next sign-in — born from a one-evening "stop losing my session at midnight" hack, hardened into the author's daily driver.**

> **One-stop install / update reference**: [`spec/21-app/11-build-and-packaging/`](../spec/21-app/11-build-and-packaging/README.md) and [`docs/RUNBOOK-go-live.md`](../docs/RUNBOOK-go-live.md) — full Windows install · update · uninstall · verify matrix.

---

## Quick Start

> Looking for install one-liners? See **[Install](#-install)** at the top of this README.

### Uninstall — Quick

Removes the binary, the autostart registry entry, and (optionally) the `%APPDATA%\IdleShutdown\` data folder.

#### Installer build

Settings → Apps → *Idle Shutdown & Session Restore* → Uninstall. Autostart is removed automatically. Your snapshot history in `%APPDATA%\IdleShutdown\` is left in place — delete that folder by hand for a clean slate.

#### Single .exe build

```powershell
& "$env:LOCALAPPDATA\Programs\IdleShutdown\idle-shutdown.exe" uninstall-autostart
Remove-Item "$env:LOCALAPPDATA\Programs\IdleShutdown\idle-shutdown.exe"
# Optional — wipe history:
Remove-Item -Recurse -Force "$env:APPDATA\IdleShutdown"
```

Useful flags (both paths):

| Flag | Effect |
|---|---|
| `/VERYSILENT` (installer) | Skip every UI page, run unattended |
| `/SUPPRESSMSGBOXES` (installer) | Auto-answer Inno Setup message boxes with the default |
| `--keep-data` (planned) | Keep `%APPDATA%\IdleShutdown` even when uninstalling |

### Look at the current state

```powershell
idle-shutdown status
idle-shutdown doctor
```

The first prints a one-shot health view (add `--json` for a stable, scriptable payload). The second runs the colored preflight diagnostic and exits non-zero on FAIL.

### Take a snapshot right now (no shutdown)

```powershell
idle-shutdown snapshot
idle-shutdown history --limit 5
```

Useful for testing — captures the current session as `TriggerKind = Manual` and prints it in the next `history` listing.

### Restore the most recent snapshot

```powershell
idle-shutdown restore                 # latest
idle-shutdown restore --snapshot-id 12  # an older one
```

`restore` is idempotent: running it twice does nothing the second time, because the duplicate-prevention rule (same exe + same `DocumentPath` already running) skips re-launches.

Every command supports `--help` or `-h` for detailed usage. Add `--verbose` for DEBUG logging and `--db PATH` (or `IDLE_SHUTDOWN_DB=...`) to point at a different SQLite file.

---

## Installation

### One-Click Install (recommended)

The Inno Setup installer is the **default**: per-user, no admin prompt, optional autostart + DB-init in one click.

#### Windows — Installer

Double-click `IdleShutdownSetup-0.1.0.exe`, accept the SmartScreen warning, tick **autostart** + **initialize DB**, click **Install**.

#### Windows — Silent / unattended

```powershell
.\IdleShutdownSetup-0.1.0.exe /VERYSILENT /SUPPRESSMSGBOXES /TASKS="autostart,initdb,startnow"
```

#### Windows — Locked-down machines (full bootstrap)

Use when execution policy / TLS settings block a normal download:

```powershell
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
$tag = "v0.1.0"
$dst = "$env:TEMP\IdleShutdownSetup.exe"
(New-Object System.Net.WebClient).DownloadFile("https://github.com/<owner>/idle-shutdown/releases/download/$tag/IdleShutdownSetup-$tag.exe", $dst)
Start-Process $dst -ArgumentList "/VERYSILENT","/TASKS=autostart,initdb" -Wait
```

### Installer Options

**Inno Setup CLI flags:**

| Flag | Description | Example |
|---|---|---|
| `/DIR=` | Custom install directory | `/DIR="D:\Tools\IdleShutdown"` |
| `/TASKS=` | Comma-separated optional tasks | `/TASKS="autostart,initdb,startnow"` |
| `/VERYSILENT` | Run with no UI | `/VERYSILENT` |
| `/SUPPRESSMSGBOXES` | Auto-answer Inno message boxes | `/SUPPRESSMSGBOXES` |
| `/LOG="path"` | Write installer log to file | `/LOG="%TEMP%\idle-install.log"` |

**`idle-shutdown.exe` global flags (apply to every subcommand):**

| Flag | Description | Example |
|---|---|---|
| `--verbose` / `-v` | Raise log level to DEBUG | `idle-shutdown -v status` |
| `--db PATH` | Override DB path (also `IDLE_SHUTDOWN_DB`) | `idle-shutdown --db D:\test.sqlite snapshot` |
| `--log-json` | Write logs as one JSON object per line | `idle-shutdown --log-json run` |
| `--silent` | (run only) Hide the console window | `idle-shutdown run --silent` |
| `--help` / `-h` | Click default | `idle-shutdown restore --help` |

#### Non-Interactive / CI Installations

When invoking the installer over WinRM / SSH / Intune, the terminal is non-interactive. The installer **exits with code 1** if a required asset (`IdleShutdownSetup-<tag>.exe`) is missing — there is no online fallback.

To handle missing versions in automation:

1. **Pre-validate the version** — list GitHub release tags via the Releases REST API before downloading.
2. **Pin the SHA256** — every release publishes a `SHA256SUMS-<tag>.txt` next to the installer. Verify before running:
   ```powershell
   $expected = (Invoke-WebRequest "https://github.com/<owner>/idle-shutdown/releases/download/v0.1.0/SHA256SUMS-0.1.0.txt").Content
   $actual = (Get-FileHash $env:TEMP\IdleShutdownSetup.exe -Algorithm SHA256).Hash
   if ($expected -notmatch $actual) { throw "checksum mismatch" }
   ```

#### Version-Specific Install URLs

For reproducible installs, use the **per-version snapshot URLs** baked at release time:

| Asset | URL Pattern |
|---|---|
| Inno installer | `https://github.com/<owner>/idle-shutdown/releases/download/{version}/IdleShutdownSetup-{version}.exe` |
| Standalone exe | `https://github.com/<owner>/idle-shutdown/releases/download/{version}/idle-shutdown-{version}-windows-amd64.exe` |
| Checksums | `https://github.com/<owner>/idle-shutdown/releases/download/{version}/SHA256SUMS-{version}.txt` |

> **Tip:** Use `gh release list --repo <owner>/idle-shutdown` to see all available tags before pinning.

### Clone & Setup (Development)

```powershell
git clone https://github.com/<owner>/idle-shutdown.git
cd idle-shutdown\app
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

The dev install pulls `pytest`, `pytest-cov`, `ruff`, `mypy`, and `pyinstaller`. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow (pre-commit hook, branch model, fixture regeneration).

#### Optional extras

```powershell
pip install -e ".[tray]"     # adds the system-tray icon (idle-shutdown tray)
pip install -e ".[notify]"   # adds Windows toasts for snapshot-failure alerts
```

### Update Source Before Building

If you have an existing local checkout, **always pull before building** so you don't reproduce a fixed bug:

```powershell
cd C:\path\to\idle-shutdown
git fetch origin
git checkout main
git pull --ff-only origin main
git status                          # must report "working tree clean"
git log -1 --format='%H %s'         # capture the SHA you're about to build
```

#### Verify the source tree is healthy

Three quick checks before invoking PyInstaller:

```powershell
# 1. Python version is 3.11+
python --version

# 2. Schema file is present (PyInstaller reads it as a data file)
Test-Path .\idle_shutdown\db\schema.sql      # expect: True

# 3. Test suite is green
python -m pytest -q
```

If any check fails, stop and fix the source tree before building. A failing test suite must never be released.

#### Run the build

```powershell
pyinstaller build/idle-shutdown.spec --noconfirm --clean
# → produces dist/idle-shutdown.exe
Get-FileHash .\dist\idle-shutdown.exe -Algorithm SHA256
```

The reproducible-build path (`build/build.ps1`) does this end-to-end: clean → install pinned deps → PyInstaller → SHA256 to stdout.

### Install-script behavior spec (shareable with any AI)

The canonical contract every installer in this project follows lives at:

> **[`spec/21-app/11-build-and-packaging/README.md`](../spec/21-app/11-build-and-packaging/README.md)**

It defines the artifact naming contract, the PyInstaller spec invariants (hidden imports, data files, version resource), and the Inno Setup task list — so any AI working on the installer implements the same contract.

---

## What It Does

A single Windows CLI that watches for user idleness, snapshots the full desktop session to SQLite, shuts the machine down cleanly, and restores everything on next sign-in. Every shutdown produces **all outputs** automatically:

- **SQLite database** — `%APPDATA%\IdleShutdown\state.sqlite` (single source of truth: settings, snapshots, apps, Chrome tabs, virtual desktops, shutdown log, counter).
- **Rotating log file** — `%APPDATA%\IdleShutdown\Logs\app.log` (also as JSON when `--log-json` / `IDLE_SHUTDOWN_LOG_JSON=1`).
- **Snapshot artifacts** — `%APPDATA%\IdleShutdown\Snapshots\` (auxiliary captures alongside the SQLite rows).
- **Optional toast** — when N consecutive background snapshots fail (default `N = 3`, see `SnapshotFailureNotifyThreshold`), one Windows toast — not a stream.

All data lives on the local machine. The app makes **no network calls**. Delete `%APPDATA%\IdleShutdown\` to wipe history.

---

## Command Reference

Every command is a subcommand of the single `idle-shutdown.exe` binary (PyInstaller-frozen). In a development checkout, `python -m idle_shutdown <command>` is identical.

### Service & lifecycle

| Command | Description |
|---|---|
| `run [--silent]` | Foreground service: monitor + popup loop. `--silent` hides the console |
| `disable [--minutes N]` | Pause the service. With `--minutes`, auto-re-enables |
| `enable` | Resume the service |
| `install-autostart` | Write the `HKCU\…\Run` entry |
| `uninstall-autostart` | Remove the `HKCU\…\Run` entry |

```powershell
idle-shutdown run --silent              # the autostart entry runs this
idle-shutdown disable --minutes 120     # going on a long call
idle-shutdown enable
```

→ [spec/21-app/02-activity-monitor](../spec/21-app/02-activity-monitor/README.md) · [03-idle-popup](../spec/21-app/03-idle-popup/README.md) · [05-shutdown-sequence](../spec/21-app/05-shutdown-sequence/README.md)

### Snapshot & restore

| Command | Description |
|---|---|
| `snapshot` | Capture the current session right now (no shutdown) — `TriggerKind = Manual` |
| `restore [--snapshot-id N]` | Replay the latest (or given) snapshot. Idempotent |
| `history [--limit N]` | List shutdown events with timestamp + outcome |
| `counter` | Print `ShutdownCounter.TotalCount` (lifetime auto-shutdown count) |
| `self-test [--json] [--keep]` | Round-trip sanity check: snapshot → dry-run restore → report |

```powershell
idle-shutdown snapshot
idle-shutdown restore --snapshot-id 12
idle-shutdown history --limit 20
idle-shutdown self-test --json
```

→ [spec/21-app/04-snapshot-capture](../spec/21-app/04-snapshot-capture/README.md) · [06-startup-and-restore](../spec/21-app/06-startup-and-restore/README.md)

### Settings & configuration

| Command | Description |
|---|---|
| `init-db` | Create / re-seed the SQLite file. Safe on a missing DB |
| `settings show` | Print the current settings table |
| `settings set-idle <minutes>` | Change `IdleThresholdMinutes` (1..240, default 15) |
| `settings set-countdown <seconds>` | Change `PopupCountdownSeconds` (30..60, default 60) |
| `export-config` | Dump settings + restore exclusions as JSON to stdout |
| `import-config` | Read JSON from stdin, merge into settings + exclusions |

```powershell
idle-shutdown init-db
idle-shutdown settings show
idle-shutdown settings set-idle 20
idle-shutdown export-config > backup.json
Get-Content backup.json | idle-shutdown import-config
```

→ [spec/21-app/07-sqlite-schema](../spec/21-app/07-sqlite-schema/README.md) · [09-enums](../spec/21-app/09-enums/README.md) · [12-config-and-paths](../spec/21-app/12-config-and-paths/README.md)

### Health & diagnostics

| Command | Description |
|---|---|
| `status [--json]` | One-shot health view: idle, snapshots, last heartbeat, failure streak, crash-recovery flag |
| `doctor` | Colored preflight diagnostic table. Exits non-zero on FAIL |
| `reset-failures` | Clear the consecutive-snapshot-failure streak after fixing root cause. Re-arms the toast |

```powershell
idle-shutdown status --json | jq .
idle-shutdown doctor
idle-shutdown reset-failures
```

→ [spec/21-app/error-manage](../spec/21-app/error-manage/README.md) · [13-test-plan](../spec/21-app/13-test-plan/README.md)

### Optional UI

| Command | Description |
|---|---|
| `tray` | System-tray icon (requires `pip install -e ".[tray]"`) |

```powershell
pip install -e ".[tray]"
idle-shutdown tray
```

### Exit codes

The full table lives in [`spec/21-app/12-config-and-paths/README.md`](../spec/21-app/12-config-and-paths/README.md). Summary:

| Code | Meaning |
|---|---|
| `0` | Success |
| `2` | Bad CLI arguments (click default) |
| `10` | Config / argument out of range |
| `20` | Snapshot failed |
| `21` | Activity monitor failed |
| `22` | Restore failed |
| `30` | Autostart registry write failed |
| `40` | DB not initialized — run `init-db` |
| `41` | Required environment variable missing (e.g. `LOCALAPPDATA`) |
| `42` | Another instance already running |

---

## What gets saved

On every auto-shutdown (and every manual `snapshot`):

- **Virtual desktops** — count + which desktop each app is on.
- **Apps** — executable path, working directory, and a best-effort document-path heuristic from the command line. System processes (`explorer.exe`, `dwm.exe`, etc.) are excluded.
- **Chrome tabs** — executable path + every open tab's URL and title (read from Chrome's own `Tabs` SNSS file). Multi-profile, multi-Chromium-variant aware. Tab groups are not yet captured (deferred to a Phase-2 companion extension).

All data lives in **one** file: `%APPDATA%\IdleShutdown\state.sqlite`. Open it with any SQLite browser to inspect or export.

---

## Build & Release

### Build the shipping artifacts

```powershell
# 1. Standalone exe
pyinstaller build/idle-shutdown.spec --noconfirm --clean
# → dist/idle-shutdown.exe

# 2. Inno Setup installer (requires Inno Setup 6.x on PATH)
ISCC.exe build\installer.iss
# → build/Output/IdleShutdownSetup-<version>.exe

# 3. Reproducible end-to-end build
pwsh -File build\build.ps1
```

`build.ps1` does: clean → install pinned deps → PyInstaller → ISCC → SHA256 of every artifact printed to stdout.

### Test

```powershell
python -m pytest tests/unit          # cross-platform (Win32 modules mocked)
python -m pytest tests/integration   # Windows only — touches the real registry / Chrome
python -m pytest -q                  # everything
```

The full test plan (unit + integration + manual QA checklist + acceptance criteria) lives at [`spec/21-app/13-test-plan/`](../spec/21-app/13-test-plan/README.md). The 11 user-visible acceptance criteria live at [`spec/21-app/10-acceptance-criteria/`](../spec/21-app/10-acceptance-criteria/README.md).

### Go-live runbook

The production cutover playbook — real-shutdown smoke test, tray smoke test, toast smoke test, rollback procedure — lives at [`docs/RUNBOOK-go-live.md`](../docs/RUNBOOK-go-live.md).

---

## Privacy

Everything stays on your machine. Idle Shutdown makes **no network calls**. Snapshot data is plain SQLite — delete `%APPDATA%\IdleShutdown\` to wipe history.

## License

MIT — see [LICENSE](./LICENSE).
