---
name: codex-reset-calendar
description: Query Codex reset-credit expiry times, export ICS, preview or confirm reminders, and inspect this installed tool's status. Use the fixed CLI instead of reconstructing the workflow.
---

Use the installed helper at `scripts/Invoke-Tool.ps1`, resolved relative to this SKILL.md. The optional installer binds that helper to this installation's Python and state directory.

- Query requests: `-Mode query`. Report the observed time, time zone, available count and any missing details.
- ICS requests: `-Mode export-ics -Output <user-selected path>`. Exporting is not calendar synchronization; ask the user to verify imported reminders.
- Calendar requests: first `-Mode preview`. Present the paired accounts, primary calendar, candidate expiry times, private/free events and 60-minute popup. If candidates exist, obtain explicit user confirmation before `-Mode sync -ConfirmPreview <the returned previewId>`. With no candidates, report the result without asking for write approval.
- Diagnostics: `-Mode doctor` or `-Mode status`. A running ledger record does not establish that a process is still running.

Do not use a Calendar connector separately to create a second copy. Do not consume reset credits, start a model turn, copy credentials, edit existing events, clear pending records, or bypass confirmation through the daily entry point. A preview expires after 15 minutes; changed candidates/settings require a new preview. On approval, authentication or pending errors, report the code and stop writing.

The installed Windows schedule has its own explicitly granted authorization. This skill does not inherit that authorization for manual writes. Enable or disable it only when the user asks, using this installation's documented task scripts.
