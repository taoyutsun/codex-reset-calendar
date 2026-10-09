# codex-reset-calendar

繁體中文 / Traditional Chinese: [README.md](README.md)

Read the exact expiration of individual Codex reset credits, export ICS, or create reminders through an existing Codex Google Calendar connection. The fixed scripts do not start model-generation turns. Natural-language interaction with an AI agent may still use tokens.

This tool handles **earned rate-limit reset credits**, not the next reset of a five-hour or weekly usage window. It never redeems a reset credit.

## Support and limitations

- Version 1 deployment supports Windows 10/11, Python 3.10+, and PowerShell 5.1/7.
- A local Codex CLI signed in with ChatGPT is required. API-key-only accounts do not supply the required account data.
- Query and ICS work without Calendar. Direct synchronization needs callable Google Calendar tools on the CLI's `codex_apps` server and the appropriate permissions.
- The inspected protocol baseline is Codex CLI 0.144.3. Other versions must pass `doctor`; future compatibility is not guaranteed.
- The service can return only a count or partial detail rows. Missing information is reported as unknown, never as zero.
- Successful reads do not prove that writes or unattended scheduling are approved. Authentication, approval requests and uncertain outcomes stop creation.
- macOS/Linux deployment and scheduling are outside the first supported release.

## Install

Download or clone this repository and enter the directory containing `pyproject.toml`. Work only inside this repository.

```powershell
.\scripts\Setup.ps1
.\scripts\Setup.ps1 -Apply
```

The first command prints a plan. The second creates a new `.venv` and installs this project and `tzdata`. It does not alter global Python, Codex settings, sign-in or models. An existing `.venv` causes a stop without overwrite.

If PowerShell execution policy blocks the scripts, the tool does not change the policy. You can use Python directly:

```powershell
python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

The examples below require neither environment activation nor PATH changes.

## Query and ICS fallback

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar query
.\.venv\Scripts\python.exe -m codex_reset_calendar query --format json
.\.venv\Scripts\python.exe -m codex_reset_calendar query --time-zone America/New_York
.\.venv\Scripts\python.exe -m codex_reset_calendar export-ics --output .\reset-reminders.ics
```

The default display zone is `Asia/Taipei`. Output preserves seconds and includes UTC. Before initialization, query uses the current CLI account. Use `--expected-email` to check the account and `--codex` to supply a full CLI path.

ICS exports known, future, expiring Codex credits. Partial details can be exported with missing-detail warnings; inconsistent data is rejected. Events are private, free, one minute long, and include a 60-minute `VALARM`. Existing output files are never overwritten; choose a new filename.

**Exporting does not add events to a calendar.** Import the file manually and verify the time and notification. Google Calendar ICS imports do not establish continuous synchronization, and importers may not preserve alarms. Stable UIDs and description markers let the connector subsequently adopt events that retain the marker. Do not remove the identity marker, or assume every importer preserves it.

## Pair accounts and synchronize

Check connections and inspect the proposed account pairing with read-only calls:

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar doctor --format json
.\.venv\Scripts\python.exe -m codex_reset_calendar init
```

After review, use your own emails; all `example.com` addresses below are fictional:

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar init --expected-email codex-user@example.com --calendar-email calendar-user@example.com --apply
.\.venv\Scripts\python.exe -m codex_reset_calendar preview
```

Codex and Google may use different emails. `init --apply` saves only local pairing, an empty ledger and read-only verification. It creates no events, installs no skill and enables no schedule. Default state: `%USERPROFILE%\.codex-reset-calendar`. To choose another directory, consistently pass `--state-dir` to the CLI and `-StateDir` to scripts. Nonempty state directories are rejected to avoid overwriting installations.

After initialization, CLI arguments cannot override the saved accounts, time zone or executable paths. For another configuration, select a different empty state directory and verify the pairing again. Retain the original ledger and inspect possible duplicate reminders first.

Preview displays the paired accounts, primary calendar, candidates and `previewId`. If candidates exist, review them before:

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar sync --confirm-preview <previewId-from-the-previous-command>
```

Replace the placeholder with the returned 32-character hexadecimal ID. Receipts expire after 15 minutes. Changes to accounts, destination, time zone, executables or candidate expirations require another preview. Manual sync works without an enabled schedule. If there are no candidates, report that result; no creation approval is needed.

Reminders use the verified Google account's primary calendar: private, free, one minute, a custom 60-minute popup, no external attendees and no Google Meet.

### Deduplication and uncertain outcomes

- Before creation, search the credit's exact marker rather than guessing from a title or date.
- Persist durable pending before creation. Timeouts, approval requests, interruption or unverified responses retain pending.
- Subsequent runs reconcile pending; they never resend create merely because search is temporarily empty.
- Changed/cancelled events and disappeared credits are retained without automatic edits or deletion. Failed reads do not cause recreation.
- Pending/review requires human investigation. There is no general "clear ledger and retry" command. Check Calendar, sign-in and approvals; retain records if the outcome is uncertain.

Old manually created events without this tool's marker cannot be adopted automatically. If another tool already synchronizes the same account, inspect preview for duplicates and do not enable two writers.

## Windows daily schedule

Pair the accounts and inspect preview before granting recurring creation:

```powershell
.\scripts\Install-Task.ps1
.\scripts\Install-Task.ps1 -Apply
```

`-Apply` explicitly authorizes this installation to create reminders for new credits each day. The installer runs another read-only preflight, registers the task disabled, sets the local gate, then enables it. It never starts the task immediately. An existing task causes a stop without Force.

- Daily at **08:00 in the computer's local time zone**, plus a current-user logon trigger delayed 30 seconds.
- Display time zone is independent: `--time-zone` does not move the schedule to another country's 08:00.
- First eligibility is the next future 08:00; after today's boundary, begin tomorrow.
- Current-user InteractiveToken and LeastPrivilege; no SYSTEM, saved password or elevation.
- The computer must be on and the user signed in. A locked screen may retain sign-in.
- `StartWhenAvailable`, logon catch-up and daily triggers share one daily claim. Logon before 08:00 waits; later logon can catch up.
- Save the claim before network calls. Failure, interruption or offline state is not retried that day. Do not loop through missed dates or rerun after clock rollback.
- An OS lock and `IgnoreNew` prevent overlap; five-minute limit; `pythonw.exe` avoids a console.
- With no new credits there are no events or notifications. Inspect local state and Task Scheduler results for errors.

Task name: `CodexResetCalendar-<installation-id>-Daily`, derived from the physical state-directory path.

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar status
.\scripts\Disable-Task.ps1
.\scripts\Disable-Task.ps1 -Apply
```

Disabling retains events, state and logs, and does not terminate a running process. Reinstallation never overwrites an existing task; inspect the state before explicitly arranging resumption.

## AI assistance and optional skill

Complete prompts: [Traditional Chinese](docs/AI_DEPLOYMENT.md) / [English](docs/AI_DEPLOYMENT.en.md).

```powershell
.\scripts\Install-Skill.ps1
.\scripts\Install-Skill.ps1 -Apply
```

The installer adds only `codex-reset-calendar`, bound to this project's environment and selected state directory. Existing names cause a stop; other skills and AGENTS.md are untouched. Natural requests such as "check reset expirations", "preview calendar reminders" or "inspect sync status" still follow preview/confirmation rules through the fixed tool.

A dot with command access to this Windows host can call the same CLI. OpenClaw in WSL can call Windows Python:

```bash
"/mnt/c/path/to/codex-reset-calendar/.venv/Scripts/python.exe" -m codex_reset_calendar query --format json
```

Substitute your path. This uses **Windows Codex sign-in and connectors**; it does not grant WSL or other agents those permissions automatically. This release does not automatically install OpenClaw skills or edit its configuration.

## State, privacy and troubleshooting

Runtime state and bounded logs live only in the selected state directory, separately from the repository. Files include `config.json`, `ledger.json`, `preview.json`, `runs.json`, `verification.json`, `last-result.json` and up to four `runtime.log` files totaling roughly 1 MiB.

Configuration holds local paths and paired emails; the ledger holds credit/event IDs. These are private data, not publishable samples or state to synchronize between multiple computers. Logs contain controlled codes, times and counts, not tokens, raw backend diagnostics or event bodies. The tool neither reads/moves credential files nor signs in automatically. Back up source and personal state separately.

| Code/state | Action |
|---|---|
| `cli_not_found` | Install the existing Codex CLI or specify its full path with `--codex` |
| `auth_unavailable` / `account_mismatch` | Check sign-in in Codex yourself; the tool does not switch accounts |
| `timezone_unavailable` | Install project dependencies and use a valid IANA name |
| `calendar_tools_unavailable` | Check the CLI's Calendar connector; use query/ICS meanwhile |
| `host_request_required` / `calendar_tool_failed_or_approval_required` | Authentication, approval or rejection requires checking the source connection |
| `credits_incomplete_no_sync` | Details are incomplete; query later without writing |
| `manual_preview_*` | Preview again and confirm reviewed candidates/settings |
| `pending` / `reviewCount > 0` | Retain the ledger and investigate; do not repeatedly resend |
| `state_*` / `ledger_*` | Inspect backup and paths; do not delete records to make everything look new |

## Development and verification

```powershell
.\.venv\Scripts\python.exe -m pip install ".[test]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m build
```

CI runs offline tests, PowerShell syntax checks and independent wheel installation on Windows with Python 3.10/3.12. Tests use fictional accounts, fake Calendar adapters and stdio servers, without live calendar writes or task registration. Mock success does not establish your connector's create permission.

The installed package does not depend on the repository's parent. When storing this shareable copy inside a personal project, initialize, commit and publish Git only from the shareable directory containing this README.

Validation scope and results: [Traditional Chinese](docs/VALIDATION.md) / [English](docs/VALIDATION.en.md).

## References and license

- [Codex app-server: account/rateLimits/read](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)
- [Google Calendar ICS import](https://support.google.com/calendar/answer/37118)
- [iCalendar RFC 5545](https://www.rfc-editor.org/rfc/rfc5545)
- [Windows StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable)

[MIT License](LICENSE). This community tool does not promise that an account has reset credits or connector permissions.
