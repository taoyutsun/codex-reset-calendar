"""Standalone entry point. Options may precede or follow the subcommand."""
import argparse
import json
import os
from pathlib import Path
import sys

from . import __version__, ics, query as q
from .calendar import CalendarAdapter
from .errors import ToolError
from .runtime import Runtime
from .schedule import inspect_task, set_enabled, task_plan
from .storage import State
from .transport import AppServer


def parser():
    common = argparse.ArgumentParser(add_help=False)
    for flag in ("state-dir", "expected-email", "calendar-email", "codex", "time-zone"):
        common.add_argument("--" + flag, default=argparse.SUPPRESS)
    common.add_argument("--format", choices=("text", "json"), default=argparse.SUPPRESS)
    root = argparse.ArgumentParser(prog="codex-reset-calendar", parents=[common],
                                   description="Read Codex reset credits; preview calendar writes or export ICS.")
    root.add_argument("--version", action="version", version=__version__)
    modes = root.add_subparsers(dest="command", required=True)
    for mode in ("query", "preview", "status", "doctor", "daily", "schedule-disable"):
        modes.add_parser(mode, parents=[common])
    export = modes.add_parser("export-ics", parents=[common])
    export.add_argument("--output", required=True)
    init = modes.add_parser("init", parents=[common])
    init.add_argument("--apply", action="store_true")
    sync = modes.add_parser("sync", parents=[common])
    sync.add_argument("--confirm-preview", required=True)
    plan = modes.add_parser("schedule-plan", parents=[common])
    plan.add_argument("--owner-sid", required=True)
    enable = modes.add_parser("schedule-enable", parents=[common])
    enable.add_argument("--first-eligible-epoch", type=int, required=True)
    enable.add_argument("--owner-sid", required=True)
    return root


def options(args, state):
    installed = state.config(optional=True)
    config = dict(installed or {})
    defaults = {
        "codexEmail": None, "calendarEmail": None, "timeZone": "Asia/Taipei",
        "calendarId": "primary", "pythonExecutable": sys.executable,
    }
    for name, value in defaults.items():
        config.setdefault(name, value)
    for argument, field in (("expected_email", "codexEmail"), ("calendar_email", "calendarEmail"),
                            ("time_zone", "timeZone"), ("codex", "codexExecutable")):
        value = getattr(args, argument, None)
        if value is not None:
            if field.endswith("Email"):
                value = value.strip().casefold()
                if not value:
                    raise ToolError("expected_account_empty")
            if installed and value != installed.get(field):
                raise ToolError("installed_configuration_override_rejected")
            config[field] = value
    config["codexExecutable"] = q.resolve_codex(config.get("codexExecutable"))
    q.zone(config["timeZone"])
    return config, installed


def live_query(config):
    with AppServer([config["codexExecutable"], "app-server", "--stdio"], timeout=25) as client:
        return q.query(client, config["codexEmail"], config["timeZone"])


def initialize(state, config, apply=False):
    if state.root.exists() and any(state.root.iterdir()):
        raise ToolError("state_directory_exists_no_overwrite")
    with CalendarAdapter(config) as bridge:
        bound = dict(bridge.config, pythonExecutable=str(Path(sys.executable).resolve()), calendarId="primary")
    plan = {"ok": True, "mode": "apply" if apply else "plan_only",
            "stateRoot": str(state.root), "taskName": state.task_name,
            "codexEmail": bound["codexEmail"], "calendarEmail": bound["calendarEmail"],
            "timeZone": bound["timeZone"], "pythonExecutable": bound["pythonExecutable"],
            "codexExecutable": bound["codexExecutable"], "calendarReadVerified": True,
            "calendarWriteVerified": False, "calendarWrites": 0, "scheduleEnabled": False}
    if apply:
        state.initialize(bound)
        plan["initialized"] = True
    return plan


def doctor(state, config, installed):
    result = {"ok": False, "queryReady": False, "calendarReadReady": False,
              "calendarWriteVerified": False, "modelTurns": 0, "calendarWrites": 0,
              "packageVersion": __version__, "pythonVersion": sys.version.split()[0],
              "codexExecutable": config["codexExecutable"], "timeZone": config["timeZone"]}
    try:
        snapshot = live_query(config)
        result.update(queryReady=True, availableCount=snapshot["availableCount"],
                      detailsState=snapshot["detailsState"])
    except ToolError as error:
        result["queryError"] = error.code
    try:
        with CalendarAdapter(config, state if installed else None) as bridge:
            result.update(calendarReadReady=True, calendarEmail=bridge.config["calendarEmail"])
    except ToolError as error:
        result["calendarError"] = error.code
    result["ok"] = result["queryReady"] and (result["calendarReadReady"] if installed else True)
    return result


def dispatch(args):
    state = State(getattr(args, "state_dir", None))
    # Offline diagnostics and schedule operations do not need a working Codex executable.
    if args.command == "status":
        result = Runtime(state).status()
        result["windowsTask"] = inspect_task(state)
        return result
    if args.command == "schedule-plan":
        return dict(task_plan(state, args.owner_sid), ok=True, mode="plan_only")
    if args.command in ("schedule-enable", "schedule-disable"):
        return set_enabled(state, args.command == "schedule-enable",
                           getattr(args, "first_eligible_epoch", None), getattr(args, "owner_sid", None))
    if args.command == "daily":
        return Runtime(state).synchronize(daily=True)
    config, installed = options(args, state)
    if args.command == "init":
        return initialize(state, config, args.apply)
    if args.command == "query":
        return live_query(config)
    if args.command == "export-ics":
        return ics.export(live_query(config), args.output)
    if args.command == "doctor":
        return doctor(state, config, installed)
    if args.command == "preview":
        return Runtime(state).preview()
    if args.command == "sync":
        if len(args.confirm_preview) != 32 or any(c not in "0123456789abcdef" for c in args.confirm_preview):
            raise ToolError("invalid_preview_id")
        return Runtime(state).synchronize(args.confirm_preview)
    raise ToolError("unknown_command")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        result = dispatch(args)
    except ToolError as error:
        result = {"ok": False, "error": error.code}
    except KeyboardInterrupt:
        result = {"ok": False, "error": "cancelled"}
    except Exception:
        result = {"ok": False, "error": "unexpected_error"}
    if args.command != "daily" and sys.stdout is not None:
        if args.command == "query" and result["ok"] and getattr(args, "format", "text") == "text":
            print(q.text_summary(result))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1
