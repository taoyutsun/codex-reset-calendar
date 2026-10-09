"""Task XML only; the explicit PowerShell apply scripts own registration."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from .errors import ToolError
from .storage import read_json


def inspect_task(state):
    """Read only this installation's Windows task; never require administrator rights."""
    if os.name != "nt":
        return {"available": False, "reason": "windows_only"}
    powershell = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$task = Get-ScheduledTask -TaskName '__TASK__' -TaskPath '\' -ErrorAction SilentlyContinue
if ($null -eq $task) {
    @{available=$true; exists=$false} | ConvertTo-Json -Compress
} else {
    $info = $task | Get-ScheduledTaskInfo
    @{available=$true; exists=$true; state=[string]$task.State;
      lastTaskResult=$info.LastTaskResult; nextRunTime=$info.NextRunTime.ToString('o')} | ConvertTo-Json -Compress
}
""".replace("__TASK__", state.task_name)
    try:
        done = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode != 0:
            raise ValueError("task status unavailable")
        result = json.loads(done.stdout.decode("utf-8-sig"))
        if not isinstance(result, dict) or result.get("available") is not True:
            raise ValueError("invalid task status")
        return result
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"available": False, "reason": "task_status_unavailable"}


def next_eight(now=None):
    # A naive Windows local wall time in XML follows the computer's DST rules.
    local = now if now is not None else datetime.now()
    boundary = local.replace(hour=8, minute=0, second=0, microsecond=0)
    if local >= boundary:
        boundary += timedelta(days=1)
    return boundary.astimezone() if boundary.tzinfo is None else boundary


def metadata(state):
    config = state.config()
    pythonw = Path(config["pythonExecutable"]).with_name("pythonw.exe")
    argv = ["-B", "-m", "codex_reset_calendar", "--state-dir", str(state.root), "daily"]
    return {
        "taskName": state.task_name, "taskPath": "\\", "pythonwExecutable": str(pythonw),
        "arguments": subprocess.list2cmdline(argv), "workingDirectory": str(state.root),
    }


def task_plan(state, owner_sid, now=None):
    if re.fullmatch(r"S-1-5-21-(?:[0-9]+-){3}[0-9]+", owner_sid or "") is None:
        raise ToolError("interactive_user_sid_required")
    action = metadata(state)
    if not Path(action["pythonwExecutable"]).is_file():
        raise ToolError("pythonw_required_for_windows_schedule")
    first = next_eight(now)
    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", namespace)
    def child(parent, name, value=None, **attrs):
        node = ET.SubElement(parent, "{" + namespace + "}" + name, attrs)
        if value is not None:
            node.text = value
        return node
    root = ET.Element("{" + namespace + "}Task", version="1.4")
    child(child(root, "RegistrationInfo"), "Description",
          "Codex reset-credit reminders; one daily attempt; no model turns.")
    triggers = child(root, "Triggers")
    boundary = first.replace(tzinfo=None).isoformat(timespec="seconds")
    daily = child(triggers, "CalendarTrigger")
    child(daily, "StartBoundary", boundary)
    child(daily, "Enabled", "true")
    child(child(daily, "ScheduleByDay"), "DaysInterval", "1")
    logon = child(triggers, "LogonTrigger")
    child(logon, "StartBoundary", boundary)
    child(logon, "Enabled", "true")
    child(logon, "UserId", owner_sid)
    child(logon, "Delay", "PT30S")
    principal = child(child(root, "Principals"), "Principal", id="Author")
    child(principal, "UserId", owner_sid)
    child(principal, "LogonType", "InteractiveToken")
    child(principal, "RunLevel", "LeastPrivilege")
    settings = child(root, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"), ("StartWhenAvailable", "true"),
        ("AllowStartOnDemand", "true"), ("Enabled", "false"), ("ExecutionTimeLimit", "PT5M"),
    ):
        child(settings, name, value)
    command = child(child(root, "Actions", Context="Author"), "Exec")
    child(command, "Command", action["pythonwExecutable"])
    child(command, "Arguments", action["arguments"])
    child(command, "WorkingDirectory", action["workingDirectory"])
    return dict(action, ownerSid=owner_sid, firstEligibleAtEpoch=int(first.timestamp()),
                firstEligibleLocal=first.isoformat(timespec="seconds"),
                xml=ET.tostring(root, encoding="unicode"), enabledOnRegistration=False)


def set_enabled(state, enabled, first_epoch=None, owner_sid=None, now=None):
    now = now or datetime.now().astimezone()
    with state.config_lock():
        config = state.config()
        if enabled:
            if (type(first_epoch) is not int or first_epoch <= now.timestamp()
                    or datetime.fromtimestamp(first_epoch).strftime("%H:%M:%S") != "08:00:00"):
                raise ToolError("first_schedule_must_be_future_local_0800")
            if not read_json(state.path("verification.json"), {}).get("calendarReadVerified"):
                raise ToolError("readonly_verification_required")
            if not owner_sid or re.fullmatch(r"S-1-5-21-(?:[0-9]+-){3}[0-9]+", owner_sid) is None:
                raise ToolError("interactive_user_sid_required")
            config.update(firstEligibleAtEpoch=first_epoch, ownerSid=owner_sid)
        config["enabled"] = enabled
        state.atomic("config.json", config)
        return {"ok": True, "enabled": enabled, "taskName": state.task_name,
                "firstEligibleAtEpoch": config["firstEligibleAtEpoch"]}
