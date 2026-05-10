# 13 — Test Plan

Three tiers: **unit** (pure-Python, OS-agnostic where possible), **integration** (Windows-only, scripted), **manual QA** (tester checklist mapped 1:1 to acceptance criteria in `10-acceptance-criteria/`).

Test runner: `pytest`. Layout: `app/tests/unit/`, `app/tests/integration/`. Coverage target: ≥80% lines on `idle_shutdown/` excluding `popup.py` (Tk) and `autostart.py` (registry).

Fixtures live in `app/tests/fixtures/`. Each test that touches the DB uses a temp file via `IDLE_SHUTDOWN_DB` env override; no test writes to the real `%LOCALAPPDATA%`.

---

## Tier 1 — Unit contracts

Every module below has at least the listed tests. Each row is one `pytest` test function.

### `db/connection.py`
| Test | Input | Expected |
|---|---|---|
| `test_init_db_creates_all_tables` | fresh path | 11 tables exist; `PRAGMA foreign_keys=1`; `journal_mode=wal` |
| `test_init_db_seeds_lookups` | fresh path | `SnapshotTriggerKind` has 3 rows; `ShutdownOutcomeStatus` has 3 rows; `ShutdownCounter` has 1 row with `TotalCount=0` |
| `test_init_db_seeds_default_settings` | fresh path | all 8 keys from `12-config-and-paths/` present with documented defaults |
| `test_init_db_idempotent` | run twice | no error, row counts unchanged |

### `db/repos.py` (`SettingsRepo`)
| Test | Expected |
|---|---|
| `test_get_returns_typed_value` | `IdleThresholdMinutes` returns `int(10)` |
| `test_set_rejects_out_of_range` | `set('IdleThresholdMinutes', 0)` raises `ConfigError` |
| `test_set_rejects_unknown_key` | `set('Bogus', 'x')` raises `ConfigError` |
| `test_set_updates_updated_at` | timestamp advances on write |

### `enums.py`
| Test | Expected |
|---|---|
| `test_enum_values_match_seed_rows` | every IntEnum value equals the lookup-table row inserted by `init-db` |

### `monitor.py`
Mock `GetLastInputInfo`. No real Win32 calls.
| Test | Expected |
|---|---|
| `test_below_threshold_no_transition` | state stays `Idle` |
| `test_at_threshold_transitions_to_prompting` | state flips on the tick where `idle_ms >= threshold_ms` |
| `test_activity_during_prompting_cancels` | back to `Idle`, popup signal cancelled |
| `test_disabled_state_skips_transitions` | even at high idle, no transition |
| `test_threshold_reload_each_tick` | changing `Setting` mid-loop is honored within 1 tick |

### `service.py` (state machine)
| Test | Expected |
|---|---|
| `test_popup_yes_returns_to_idle` | resets baseline |
| `test_popup_no_proceeds_to_snapshotting` | snapshot called once |
| `test_popup_timeout_proceeds_to_snapshotting` | snapshot called once |
| `test_snapshot_failure_writes_failed_log` | `ShutdownLog.OutcomeStatusId=Failed`; no shutdown invoked |
| `test_single_popup_instance` | second trigger while popup open is a no-op |

### `capture/apps.py`
Mock `psutil.process_iter` and `EnumWindows`.
| Test | Expected |
|---|---|
| `test_filters_system_paths` | processes under `C:\Windows\System32` excluded |
| `test_filters_deny_list` | `explorer.exe`, `dwm.exe`, own exe excluded |
| `test_requires_visible_window` | invisible processes excluded |
| `test_access_denied_skipped_silently` | per-process exception does not abort capture |
| `test_document_path_extracted_from_cmdline` | path-like arg detected |

### `capture/chrome.py`
| Test | Expected |
|---|---|
| `test_detect_chrome_via_hklm` | returns path from registry mock |
| `test_detect_chrome_via_program_files_fallback` | when registry empty, falls back |
| `test_detect_chrome_missing_returns_none` | logs warning, returns `None` |
| `test_capture_with_no_chrome_returns_empty_list` | snapshot still proceeds |
| `test_caches_path_in_settings` | `ChromeExecutablePath` written |

### `capture/desktops.py`
Mock `pyvda`.
| Test | Expected |
|---|---|
| `test_captures_desktop_count` | N desktops → N `VirtualDesktop` rows |
| `test_pyvda_failure_writes_single_default_desktop` | one row with `DesktopIndex=0` |

### `shutdown.py`
Mock `subprocess.run` and Win32 enums.
| Test | Expected |
|---|---|
| `test_skips_own_process` | own pid never receives WM_CLOSE |
| `test_skips_explorer` | `explorer.exe` never receives WM_CLOSE |
| `test_invokes_shutdown_command_with_locked_args` | `['shutdown.exe','/s','/t','5','/f','/c','Idle auto-shutdown']` exactly |
| `test_wm_close_timeout_per_app_is_5s` | per-window wait capped |

### `restore.py`
Mock `psutil.process_iter` and `subprocess.Popen`.
| Test | Expected |
|---|---|
| `test_skip_when_exe_and_doc_match` | duplicate-prevention rule honored |
| `test_launch_when_exe_matches_but_doc_differs` | new process started |
| `test_path_comparison_normalizes_case_and_slashes` | `C:/Foo\\App.EXE` matches `c:\foo\app.exe` |
| `test_chrome_skipped_when_path_unset` | no Chrome launch, no error |
| `test_per_item_failure_continues` | one Popen raise does not abort the loop |
| `test_writes_last_restored_markers` | settings updated on completion |
| `test_idempotent_second_call_skips_all` | re-run launches nothing |

### `autostart.py`
Mock `winreg`.
| Test | Expected |
|---|---|
| `test_install_writes_exact_value_name_and_data` | matches `12-config-and-paths/` |
| `test_uninstall_removes_value` | value gone |
| `test_uninstall_when_absent_is_noop` | no error |
| `test_install_failure_raises_autostart_error_exit_30` | propagates |

### `cli.py`
Use `click.testing.CliRunner`.
| Test | Expected |
|---|---|
| `test_settings_show_lists_all_keys` | output contains every key from `12-config-and-paths/` |
| `test_settings_set_idle_rejects_zero_exit_10` | exit code 10 |
| `test_history_renders_table` | rich table headers present |
| `test_snapshot_command_inserts_manual_trigger` | `Snapshot.TriggerKindId == Manual` |
| `test_disable_with_minutes_sets_disabled_until` | `Setting('DisabledUntil')` populated |
| `test_enable_clears_disabled_until` | empty string |
| `test_counter_prints_total` | matches DB |
| `test_missing_db_exits_40` | running `history` before `init-db` |

---

## Tier 2 — Integration scenarios (Windows-only)

Each scenario is one `pytest` test in `tests/integration/`. They use a real SQLite DB in a temp dir, real `tkinter`, and a stubbed `shutdown.exe` (a no-op `.bat` placed first on PATH). `pyvda` and Chrome are mocked at module boundary.

| # | Scenario | Setup | Action | Pass criteria |
|---|---|---|---|---|
| I-1 | Cold init | empty data dir | `idle-shutdown init-db` | exit 0; DB exists; all seed rows present |
| I-2 | Idle → popup → No → shutdown | `IdleThresholdMinutes=1`, threshold reduced to 2s in test override | start `run`, simulate no input for 3s, click No | `Snapshot` row inserted with `TriggerKindId=Auto`; `ShutdownLog` row `Completed`; counter incremented; stub `shutdown.exe` invoked with locked args |
| I-3 | Idle → popup → Yes | as above | start `run`, idle, click Yes | no `Snapshot` row; state returns to `Idle`; baseline reset |
| I-4 | Idle → popup → timeout | as above, countdown 3s | start `run`, idle, do nothing | same as I-2 |
| I-5 | Activity during popup | as above | idle to trigger popup, then move mouse | popup auto-dismisses; no snapshot |
| I-6 | Manual snapshot | DB initialized | `idle-shutdown snapshot` | one new `Snapshot` with `TriggerKindId=Manual`; no shutdown invoked |
| I-7 | Snapshot failure path | DB initialized; force `pyvda` raise via fixture | trigger auto-snapshot | rollback; `ShutdownLog.OutcomeStatusId=Failed`; counter unchanged; exit code of `run` remains 0 (service keeps running) |
| I-8 | Restore happy path | seed `Snapshot` with 3 fake `AppProcess` rows pointing at `notepad.exe` with distinct files | `idle-shutdown restore` | 3 `notepad.exe` processes spawned; `LastRestoredSnapshotId` updated |
| I-9 | Restore idempotency | run I-8 twice | second `restore` invocation | zero new processes; INFO logs show `skip_relaunch` for all 3 |
| I-10 | Auto-start install/uninstall | clean HKCU Run | `install-autostart` then `uninstall-autostart` | value present then absent; both exit 0 |
| I-11 | Disable/enable | initialized | `disable --minutes 5`; tick monitor | no popup during window; `enable` restores |
| I-12 | Chrome absent | unset `ChromeExecutablePath`; clear registry mock | snapshot | snapshot succeeds with 0 Chrome rows; one warning logged |
| I-13 | Single-instance | initialized | start `run`, then start second `run` | second exits 42 |
| I-14 | DB missing | delete DB | run `history` | exit 40 with actionable message |
| I-15 | Schema reset | delete DB; `init-db` | inspect | defaults restored verbatim per `12-config-and-paths/` |

Each scenario MUST run in <10s on a developer laptop. Total integration suite budget: 3 minutes.

---

## Tier 3 — Manual QA checklist

One row per acceptance criterion in `10-acceptance-criteria/`. Tester runs on a real Windows machine with a real Chrome and several apps open.

| AC# | Step | Pass condition | Pass/Fail |
|---|---|---|---|
| 1 | After `install-autostart`, sign out and back in | `idle-shutdown.exe` visible in Task Manager > Details within 30s of login | ☐ |
| 2 | Set threshold = 1 min; leave PC | popup appears between 58–62 s of inactivity | ☐ |
| 3 | Observe popup | always-on-top across other windows; countdown decrements every second; both buttons clickable | ☐ |
| 4a | Click **Yes** | popup closes; no shutdown; idle timer reset | ☐ |
| 4b | Click **No** | snapshot row appears in DB; system shuts down within 10s | ☐ |
| 4c | Let popup time out | identical to 4b | ☐ |
| 5 | After 4b, before reboot, open DB in DB Browser | `Snapshot` row exists; `ChromeWindow` + `ChromeTab` rows reflect open Chrome; `AppProcess` rows reflect open apps with `ExecutablePath` populated; `VirtualDesktop` row count equals visible desktops | ☐ |
| 6 | Run `idle-shutdown counter` and `idle-shutdown history` | counter incremented by 1 per completed shutdown; history shows latest row with correct timestamp and outcome | ☐ |
| 7 | After 4b, watch shutdown | no "this app is preventing shutdown" dialogs persist >5s; system reaches login screen cleanly | ☐ |
| 8 | Boot back in | virtual-desktop count matches; previously open apps relaunch (on desktop 1); Chrome reopens with prior tabs via `--restore-last-session` | ☐ |
| 9 | Delete `IdleShutdown.db`; run `init-db`; run `settings show` | all keys present at documented defaults | ☐ |
| 10 | Walk every command in `08-cli-commands/` | each prints expected output and exits 0 (or documented non-zero) | ☐ |
| 11 | Time-box build | total dev time ≤5h; record actual | ☐ |

Tester records actual values + screenshots in `app/tests/manual/qa-run-<date>.md`.

---

## Continuous integration
- `pytest tests/unit` runs on every commit (Linux OK; Win32 modules are mocked).
- `pytest tests/integration` runs on a Windows runner (manual trigger).
- Lint: `ruff check app/`; format: `ruff format --check app/`.
- Type check: `mypy --strict app/idle_shutdown/`.

All four checks MUST pass before tagging a release.