# Idle Shutdown & Session Restore — Spec Index

Authoritative specification. Implementations MUST treat each section as binding. Conflicts between sections are resolved in favor of the lower-numbered section, except `12-config-and-paths/` which always wins for paths, registry keys, and exit codes.

| # | Section | Purpose |
|---|---|---|
| 00 | [Glossary](./00-glossary/README.md) | Shared terminology and state names |
| 01 | [Overview](./01-overview/README.md) | Stack, target environment, distribution |
| 02 | [Activity Monitor](./02-activity-monitor/README.md) | Idle detection algorithm |
| 03 | [Idle Popup](./03-idle-popup/README.md) | Tk Toplevel UX contract |
| 04 | [Snapshot Capture](./04-snapshot-capture/README.md) | Transactional capture + sub-areas |
| 04a | [Chrome Tabs](./04-snapshot-capture/chrome-tabs/README.md) | Detection + capture + skip rules |
| 04b | [Running Apps](./04-snapshot-capture/running-apps/README.md) | psutil filter rules |
| 04c | [Virtual Desktops](./04-snapshot-capture/virtual-desktops/README.md) | pyvda capture |
| 04d | [Shutdown Log](./04-snapshot-capture/shutdown-log/README.md) | Counter + log semantics |
| 05 | [Shutdown Sequence](./05-shutdown-sequence/README.md) | WM_CLOSE → shutdown.exe |
| 06 | [Startup & Restore](./06-startup-and-restore/README.md) | Boot flow + duplicate-prevention |
| 07 | [SQLite Schema](./07-sqlite-schema/README.md) | Authoritative DDL + ERD |
| 08 | [CLI Commands](./08-cli-commands/README.md) | Command surface + exit codes |
| 09 | [Enums](./09-enums/README.md) | IntEnum ↔ lookup-table sync rule |
| 10 | [Acceptance Criteria](./10-acceptance-criteria/README.md) | The 11 user-visible outcomes |
| 11 | [Build & Packaging](./11-build-and-packaging/README.md) | PyInstaller artifact |
| 12 | [Config, Paths, Exit Codes](./12-config-and-paths/README.md) | Single source of paths + codes |
| 13 | [Test Plan](./13-test-plan/README.md) | Unit + integration + manual QA |
| — | [Error Management](./error-manage/README.md) | Exception taxonomy, logging, retry |

## "Build blindly" guarantee
An AI or engineer who reads this folder top-to-bottom should be able to produce `idle-shutdown.exe` without contacting the spec author. If you must guess, the spec is buggy — open an issue and patch the relevant section.