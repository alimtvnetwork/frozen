# 03 — Idle Popup

## UI
- `tk.Toplevel`, `attributes('-topmost', True)`.
- Title text: **"Are you still at your desk?"**
- Two buttons: **Yes** / **No**.
- Live countdown label (e.g. `Auto-shutdown in 27s`), updated every 250ms via `after()`.
- Non-blocking: runs on the Tk main thread; the monitor thread signals via `queue.Queue`.

## Countdown
- Default 30s, configurable via `Setting.KeyName = 'PopupCountdownSeconds'`, range 30–60.
- On expiry: dispatch `PopupResult.Timeout`.

## Outcomes
| Result | Action |
|---|---|
| `Yes` | reset idle baseline (treat as fresh activity), close popup |
| `No` | proceed to snapshot + shutdown |
| `Timeout` | proceed to snapshot + shutdown |
| `ActivityDuringPrompt` | same as `Yes` |

## Single instance
If a popup is already open, monitor must not spawn another.
