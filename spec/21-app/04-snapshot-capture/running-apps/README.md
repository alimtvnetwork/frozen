# 04b — Running Applications

## Source
`psutil.process_iter(['pid','name','exe','cwd','username','cmdline'])`

## Filter rules
Include only user-facing GUI processes:
- `username` matches current user
- `exe` is set and not under `C:\Windows\System32`, `C:\Windows\SysWOW64`, `C:\Windows\WinSxS`
- has at least one visible top-level window (enumerate via `EnumWindows` + `IsWindowVisible` + `GetWindowThreadProcessId`)
- not in deny-list: `explorer.exe`, `SearchHost.exe`, `StartMenuExperienceHost.exe`, `TextInputHost.exe`, `ApplicationFrameHost.exe`, `RuntimeBroker.exe`, `dwm.exe`, `csrss.exe`, this app's own exe

## Captured fields
| Schema field | Source |
|---|---|
| `ExecutablePath` | `proc.exe()` |
| `WorkingDirectory` | `proc.cwd()` (nullable on permission error) |
| `DocumentPath` | best-effort: parse `proc.cmdline()` for path-like args; null otherwise |
| `VirtualDesktopId` | from desktop mapping in `04c` |

## Errors
Per-process `AccessDenied` / `NoSuchProcess` are skipped silently and counted in the log line.
