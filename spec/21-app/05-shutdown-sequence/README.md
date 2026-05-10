# 05 — Shutdown Sequence

## Order (after snapshot commit)
1. Enumerate top-level visible windows (`EnumWindows` + `IsWindowVisible`).
2. Skip own process and `explorer.exe`.
3. Send `WM_CLOSE` to each window, wait up to 5s per app for graceful exit.
4. Invoke `shutdown.exe /s /t 5 /f /c "Idle auto-shutdown"` — Windows handles remaining processes.

## Why `shutdown /s /t 5`
- `/t 5` gives a 5-second user-visible cancel window (`shutdown /a` aborts).
- `/f` forces close of any process still hung after WM_CLOSE.
- Avoids re-implementing Windows' own shutdown choreography.

## Disable / cancel hook
If user types `shutdown /a` within 5s, snapshot remains valid; next session will use it on demand via `restore`.
