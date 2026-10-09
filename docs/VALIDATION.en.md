# 0.1.0 validation record

繁體中文 / Traditional Chinese: [VALIDATION.md](VALIDATION.md)

Date: 2026-10-04. Environment: Windows, Python 3.10.6, PowerShell 5.1/7. Inspected Codex CLI protocol baseline: 0.144.3.

| Check | Result and scope |
|---|---|
| Automated tests | 48 passed, using fictional accounts, credits and events |
| Query | Zero credits, count-only data, missing fields, null expiry, invalid timestamp units, exact UTC seconds and time-zone conversion |
| Synchronization | Stop on account changes; incomplete details, expired/changed previews, repeated triggers, timeout pending, reconciliation and duplicate markers |
| Daily schedule | Next future 08:00, logon catch-up, durable claim before network, cross-process lock, no same-day retries or clock-rollback reruns |
| ICS | Independent iCalendar parser verifies seconds, stable UID, private/free policy, one-minute duration, 60-minute alarm and UTF-8 folding |
| PowerShell | 5.1/7 mocked deployment; conflicts stop, disabled registration before enabling, retained ledger on disable, optional skill, Chinese paths and spaces |
| Clean source installation | Offline installation with cached packages into a fresh environment from a copy with Chinese characters and spaces in its path |
| Independent package | Wheel/sdist builds, clean wheel installation and CLI entry point from another working directory |
| Complete CLI flow | Fake stdio app-server exercises query, ICS, init, preview, confirmed sync, repeated triggers and status |
| Public content | Source/build scans found no original private paths, accounts or fixed credit/event IDs; relative documentation links are valid |
| Original installation | Personal source, existing skills, state files and Windows task XML match their pre-implementation baseline |

Deployment tests use isolated directories and fake scheduling APIs. They register no real new task and install no skill into the actual user profile. The package does not import the parent project's code or personal state.

The new CLI's read-only query/doctor successfully read Codex account and credit details and the Google Calendar profile. No model-generation turn or live calendar create/update/delete call was performed.

Calendar writes, the reader's permissions and unattended execution remain unverified for their account. Fake success and successful reads do not prove live write approval.

Windows CI is configured for Python 3.10/3.12 with fake services. Cloud CI had not run at the initial delivery on 2026-10-04; results after publication are available in [GitHub Actions](https://github.com/taoyutsun/codex-reset-calendar/actions). Dependency downloads require internet access; cached packages allow offline local installation and acceptance checks.

The initial delivery on 2026-10-04 initialized Git only in the shareable directory, without a push, GitHub repository creation or release. This record preserves that validation scope; repository publication does not establish a live Calendar write test.
