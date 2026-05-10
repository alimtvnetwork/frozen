# Idle Shutdown & Session Restore — User Guide

Windows utility that watches for idle time, asks if you're still there, then
saves your open apps + Chrome tabs + virtual desktops to a local SQLite file
and shuts the PC down cleanly. On the next sign-in it puts everything back.

## Install

Two options.

### Option A — Installer (recommended)

1. Download `IdleShutdownSetup-0.1.0.exe`.
2. Double-click it. Windows SmartScreen may warn ("Unknown publisher") —
   click **More info → Run anyway**. The build is unsigned for now.
3. The installer is **per-user** (no admin prompt). Tick:
   - **Start when I sign in to Windows** — wires the autostart entry.
   - **Initialize the local settings database now** — creates
     `%APPDATA%\IdleShutdown\state.sqlite` with sane defaults.
4. Optionally tick **Start now** on the final page to launch the service.

### Option B — Single .exe

1. Copy `idle-shutdown.exe` anywhere (e.g. `%LOCALAPPDATA%\Programs\IdleShutdown\`).
2. Open a terminal in that folder and run once:
   ```cmd
   idle-shutdown.exe init-db
   idle-shutdown.exe install-autostart
   ```
3. Sign out and back in (or run `idle-shutdown.exe run`) to start the service.

## Day-to-day commands

All commands accept `--verbose` for DEBUG logging and `--db PATH` to use a
different SQLite file.

| Command | What it does |
|---|---|
| `idle-shutdown run` | Foreground service: watch for idle, prompt, snapshot, shut down. Add `--silent` to hide the console window. |
| `idle-shutdown snapshot` | Capture the current session right now (no shutdown). Useful for testing. |
| `idle-shutdown restore` | Replay the most recent snapshot — relaunch apps on their original virtual desktops, reopen Chrome with the saved tabs. Add `--snapshot-id N` to pick an older one. Idempotent: running it twice does nothing the second time. |
| `idle-shutdown settings show` | Print the current settings table. |
| `idle-shutdown settings set-idle MINUTES` | Change the idle threshold (default 15). |
| `idle-shutdown settings set-countdown SECONDS` | Change how long the popup stays open before auto-shutdown (default 60). |
| `idle-shutdown disable [--minutes N]` | Pause the service. With `--minutes`, re-enables itself automatically; otherwise stays disabled until you run `enable`. |
| `idle-shutdown enable` | Resume the service. |
| `idle-shutdown counter` | Show the lifetime auto-shutdown count. |
| `idle-shutdown history [--limit N]` | Show recent shutdown events. |
| `idle-shutdown install-autostart` / `uninstall-autostart` | Add/remove the `HKCU\…\Run` entry. |
| `idle-shutdown init-db` | Create / re-seed the SQLite file. Safe to run on a missing DB. |

## What gets saved

On every auto-shutdown (and every manual `snapshot`):

- **Virtual desktops** — count + which desktop each app is on.
- **Apps** — executable path, working directory, and a best-effort document
  path heuristic from the command line. System processes (`explorer`, `dwm`,
  etc.) are excluded.
- **Chrome** — executable path + every open tab's URL and title (read from
  Chrome's own session files). Tab groups are not yet captured.

All data lives in **one** file: `%APPDATA%\IdleShutdown\state.sqlite`.
Open it with any SQLite browser to inspect or export.

## When the popup appears

After the idle threshold elapses you'll see an always-on-top window with a
countdown:

- **Yes, I'm here** — resets the timer, no shutdown.
- **No, shut down now** — snapshots and shuts down immediately.
- **Do nothing** — when the countdown hits zero, snapshots and shuts down.
- **Move the mouse / press a key** while the popup is open — same as Yes.

## On next sign-in

If autostart is on, the service launches in the background, sees an unrestored
snapshot, and replays it: virtual desktops are recreated, apps are launched on
their original desktops, Chrome is started with `--restore-last-session` and
your saved tab list. Apps already running (matched by exe + document path)
are skipped, so re-running restore is safe.

## Pause / disable

Going on a long call and don't want a surprise shutdown?

```cmd
idle-shutdown disable --minutes 120
```

You can also flip the `ServiceState` setting to `Disabled` directly via
`settings set` if you prefer.

## Uninstall

- **Installer**: Settings → Apps → *Idle Shutdown & Session Restore* → Uninstall.
  Autostart is removed automatically. Your snapshot history in
  `%APPDATA%\IdleShutdown\` is left in place — delete that folder by hand if
  you want a clean slate.
- **Single .exe**: `idle-shutdown.exe uninstall-autostart`, then delete the exe
  and (optionally) `%APPDATA%\IdleShutdown\`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Popup never appears | Check `idle-shutdown settings show` — `ServiceState` must be `Enabled`. Then check Task Manager for `idle-shutdown.exe`. |
| Restore launched apps but on the wrong desktop | Make sure you have at least as many virtual desktops as the snapshot expected. The service will create extras automatically; some Windows builds need a brief delay. |
| Chrome reopened but the tabs are wrong | Chrome must have been closed cleanly via the shutdown sequence. Killing `chrome.exe` separately corrupts its session files. |
| Exit code reference | `0` ok • `2` bad CLI args • `10` config • `20` snapshot • `21` monitor • `22` restore • `30` autostart • `40` DB not initialized • `41` env • `42` already running. |

## Privacy

Everything stays on your machine. The app makes no network calls. Snapshot
data is plain SQLite — delete the file to wipe history.