# 04c — Virtual Desktops

## Library
`pyvda` (wraps the undocumented IVirtualDesktopManager COM interfaces).

## Capture
```
desktops = pyvda.get_virtual_desktops()
for idx, d in enumerate(desktops):
    insert VirtualDesktop(SnapshotId, DesktopIndex=idx)
for hwnd in EnumWindows():
    pid  = GetWindowThreadProcessId(hwnd)
    desk = pyvda.AppView(hwnd=hwnd).desktop
    map[pid] = desk.number
```
Use `map[pid]` to set `AppProcess.VirtualDesktopId` during 04b insertion.

## Restore (deferred to Phase 4)
- Recreate N desktops via `pyvda.VirtualDesktop.create()` until count matches.
- MVP: launch all apps on current (desktop 0). Stretch: after launch, find the new HWND and `AppView(hwnd=...).move(target_desktop)`.

## Failure modes
If `pyvda` raises (e.g. Windows build mismatch), record one `VirtualDesktop` row with `DesktopIndex=0` and proceed.
