# 04a — Chrome Tabs

## MVP source: SNSS session files
Path: `%LOCALAPPDATA%\Google\Chrome\User Data\Default\Sessions\`
- `Current Session`, `Current Tabs` for live state
- `Last Session`, `Last Tabs` as fallback after Chrome closed

SNSS is an undocumented binary format. Reuse a community parser or fall back to the simpler approach below.

## Chrome detection (locked)
Chrome is **optional**. Resolve `chrome.exe` in this order; first hit wins:
1. `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe` — `(Default)` value.
2. `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe` — `(Default)` value.
3. `%ProgramFiles%\Google\Chrome\Application\chrome.exe`.
4. `%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe`.
5. `%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe`.

If none resolve OR the `User Data\Default` directory is absent:
- Snapshot **continues** (apps + desktops still captured).
- Zero `ChromeWindow` / `ChromeTab` rows are inserted for that snapshot.
- One `WARNING` log line: `chrome_not_detected reason=<missing_exe|missing_user_data>`.
- Restore step for Chrome is a no-op.

The detected `chrome.exe` path is cached in `Setting('ChromeExecutablePath', ...)` and re-validated each snapshot.

## Fallback (always works)
1. Trigger Chrome's session save by sending WM_CLOSE to Chrome windows (Chrome writes `Last Tabs` on clean close).
2. On restore, launch Chrome with `--restore-last-session` — Chrome rebuilds its own UI state.

SQLite still stores URL + title per window for **history viewing** and as a hard backup, parsed via DevTools Protocol when Chrome is reachable on `--remote-debugging-port=9222`. If neither path works, store empty list and rely on `--restore-last-session`.

## Tab groups
Deferred to Phase-2 companion extension that pushes tab/group state to a local HTTP endpoint exposed by this app.

## Schema target
- `ChromeWindow(WindowIndex)` per Chrome window.
- `ChromeTab(TabIndex, Url, Title, GroupName)` — `GroupName` nullable; null in MVP.
