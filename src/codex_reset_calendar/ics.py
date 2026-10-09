"""RFC 5545 output with UTC event instants and UTF-8 octet line folding."""
from datetime import datetime, timezone
from pathlib import Path

from .errors import ToolError
from .query import credit_key, eligible, iso, marker, utc_now


def escape(value):
    return value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace(
        "\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def fold(line):
    parts, current, size = [], "", 0
    for char in line:
        length = len(char.encode("utf-8"))
        if size + length > 75:
            parts.append(current)
            current, size = " ", 1
        current += char
        size += length
    parts.append(current)
    return "\r\n".join(parts)


def render(snapshot, now=None):
    now = now or utc_now()
    if snapshot["detailsState"] == "inconsistent":
        raise ToolError("inconsistent_credits_no_export")
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Codex Reset Calendar//EN", "CALSCALE:GREGORIAN"]
    email = snapshot["account"]["email"]
    rows = eligible(snapshot, now)
    for credit in rows:
        start = datetime.fromtimestamp(credit["expiresAt"], timezone.utc)
        end = datetime.fromtimestamp(credit["expiresAt"] + 60, timezone.utc)
        lines += [
            "BEGIN:VEVENT",
            "UID:" + credit_key(email, credit["creditId"]) + "@codex-reset-calendar.invalid",
            "DTSTAMP:" + stamp, "DTSTART:" + start.strftime("%Y%m%dT%H%M%SZ"),
            "DTEND:" + end.strftime("%Y%m%dT%H%M%SZ"),
            "SUMMARY:Codex reset credit expires (1)",
            "DESCRIPTION:" + escape(marker(email, credit["creditId"])),
            "CLASS:PRIVATE", "TRANSP:TRANSPARENT", "STATUS:CONFIRMED",
            "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT60M",
            "DESCRIPTION:Codex reset credit expires in one hour",
            "END:VALARM", "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n", len(rows)


def export(snapshot, output, now=None):
    contents, count = render(snapshot, now)
    target = Path(output).expanduser().resolve()
    try:
        with target.open("xb") as handle:
            handle.write(contents.encode("utf-8"))
    except FileExistsError:
        raise ToolError("output_exists_no_overwrite") from None
    return {"ok": True, "output": str(target), "exported": count, "detailsState": snapshot["detailsState"],
            "warnings": snapshot["warnings"], "observedAtUtc": snapshot["observedAtUtc"],
            "calendarWrites": 0, "recordedAsSynced": False,
            "note": "Import manually and verify the 60-minute notification in the destination calendar."}
