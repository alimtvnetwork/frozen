# 02 — Activity Monitor

## Approach
Use Win32 `GetLastInputInfo` (via `pywin32` / `ctypes`) polled on a 1-second interval. This is the lowest-overhead way to read the system-wide idle time and covers mouse, keyboard, and touch input without installing global hooks.

`pynput` is held in reserve only if `GetLastInputInfo` proves unreliable on a target machine.

## Algorithm
```
loop every 1s:
    idle_ms = GetTickCount() - LastInputInfo.dwTime
    if idle_ms >= threshold_ms and state == Idle:
        transition -> Prompting
    if state == Prompting and idle_ms < threshold_ms:
        cancel popup, transition -> Idle
```

## Threshold source
`Setting.KeyName = 'IdleThresholdMinutes'` (default `10`). Reloaded each tick (cheap; row-level read).

## Accuracy target
Idle detection within ±2 seconds of configured threshold (acceptance criterion #2). 1-second poll comfortably meets this.

## Service state
Mirrors `ServiceState` enum (`Enabled`, `Disabled`). When `Disabled`, monitor still runs but skips state transitions.
