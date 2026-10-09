"""Narrow Calendar bridge. No OAuth copying, model turns, updates or deletes."""
import re
import uuid
from datetime import datetime, timedelta, timezone

from .errors import ToolError
from . import query as q
from .transport import AppServer

TOOLS = frozenset({
    "google_calendar.get_profile", "google_calendar.read_event",
    "google_calendar.search_events", "google_calendar.create_event",
})


class CalendarServer(AppServer):
    ALLOWED = AppServer.ALLOWED | {"model/list", "thread/start", "mcpServerStatus/list", "mcpServer/tool/call"}


def event_payload(config, credit):
    start = datetime.fromtimestamp(credit["expiresAt"], timezone.utc)
    return {
        "summary": "Codex reset credit expires (1)",
        "description": q.marker(config["codexEmail"], credit["creditId"]),
        "start": start.isoformat(), "end": (start + timedelta(seconds=60)).isoformat(),
        "visibility": "private", "transparency": "transparent",
        "attendees": [], "reminders": {"use_default": False, "overrides": [{"method": "popup", "minutes": 60}]},
    }


def parse_time(value):
    if isinstance(value, dict):
        value = value.get("dateTime")
    if not isinstance(value, str):
        raise ToolError("event_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ToolError("event_time_invalid") from None
    if parsed.tzinfo is None:
        raise ToolError("event_time_invalid")
    return parsed


def event_issues(event, config, credit):
    issues = []
    if event.get("status") != "confirmed":
        issues.append("status_not_confirmed")
    try:
        start, end = parse_time(event.get("start")), parse_time(event.get("end"))
        if start.timestamp() != credit["expiresAt"]:
            issues.append("start_changed")
        if (end - start).total_seconds() != 60:
            issues.append("duration_changed")
    except ToolError:
        issues.append("time_unverifiable")
    if event.get("visibility") != "private":
        issues.append("not_private")
    if event.get("transparency") != "transparent":
        issues.append("not_free")
    reminder = event.get("reminders") or {}
    if (reminder.get("use_default", reminder.get("useDefault")) is not False
            or reminder.get("overrides") != [{"method": "popup", "minutes": 60}]):
        issues.append("reminder_changed")
    attendees = event.get("attendees", [])
    if not isinstance(attendees, list) or any(
            not isinstance(person, dict) or person.get("email", "").casefold() != config["calendarEmail"]
            for person in attendees):
        issues.append("external_or_unknown_attendees")
    if (event.get("organizer") or {}).get("email", "").casefold() != config["calendarEmail"]:
        issues.append("organizer_mismatch")
    if q.marker(config["codexEmail"], credit["creditId"]) not in (event.get("description") or ""):
        issues.append("marker_missing")
    return issues


class CalendarAdapter:
    def __init__(self, config, state=None, allow_create=False, client=None):
        self.config, self.state, self.allow_create = dict(config), state, allow_create
        self.client = client or CalendarServer([q.resolve_codex(config.get("codexExecutable")),
                                               "app-server", "--stdio"], timeout=120)
        self.attempt_id = uuid.uuid4().hex
        self.submitted, self.readable_ids = set(), set()
        self.thread_id = None

    def __enter__(self):
        self.client.__enter__()
        try:
            self.snapshot = q.query(self.client, self.config.get("codexEmail"), self.config["timeZone"])
            self.config["codexEmail"] = self.snapshot["account"]["email"]
            models = self.client.request("model/list", {"includeHidden": False}).get("data", [])
            defaults = [m["model"] for m in models if isinstance(m, dict) and m.get("isDefault") is True
                        and isinstance(m.get("model"), str)]
            if len(defaults) != 1:
                raise ToolError("unique_catalog_default_required")
            thread = self.client.request("thread/start", {
                "model": defaults[0], "ephemeral": True, "sandbox": "read-only", "approvalPolicy": "never",
            })
            self.thread_id = thread["thread"]["id"]
            if not isinstance(self.thread_id, str) or not self.thread_id:
                raise ToolError("thread_response_invalid")
            # Tool summaries are diagnostic metadata, not proof of write permission.
            self.check_tools()
            self.profile_email()
            if self.state:
                self.readable_ids.update(e["eventId"] for e in self.state.ledger()["entries"].values()
                                         if e.get("eventId"))
            return self
        except BaseException:
            self.client.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        return self.client.__exit__(*args)

    def check_tools(self):
        cursor, seen = None, set()
        for _ in range(10):
            params = {"threadId": self.thread_id, "detail": "toolsAndAuthOnly", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            response = self.client.request("mcpServerStatus/list", params)
            for server in response.get("data", []):
                if server.get("name") == "codex_apps":
                    tools = server.get("tools", {})
                    names = set(tools) if isinstance(tools, dict) else {
                        t.get("name") for t in tools if isinstance(t, dict)}
                    if not TOOLS.issubset(names):
                        raise ToolError("calendar_tools_unavailable")
                    return
            cursor = response.get("nextCursor")
            if not cursor or cursor in seen:
                break
            seen.add(cursor)
        raise ToolError("calendar_tools_unavailable")

    def _call(self, tool, arguments):
        if tool not in TOOLS or not self.thread_id:
            raise ToolError("tool_not_allowed")
        if tool == "google_calendar.create_event" and not self.allow_create:
            raise ToolError("calendar_writes_disabled")
        response = self.client.request("mcpServer/tool/call", {
            "threadId": self.thread_id, "server": "codex_apps", "tool": tool, "arguments": arguments,
        })
        if response.get("isError") is True:
            raise ToolError("calendar_tool_failed_or_approval_required")
        value = response.get("structuredContent")
        if not isinstance(value, dict):
            raise ToolError("structured_calendar_result_required")
        return value

    def profile_email(self):
        email = self._call("google_calendar.get_profile", {}).get("email")
        if not isinstance(email, str) or not email.strip():
            raise ToolError("calendar_account_unverified")
        email = email.strip().casefold()
        expected = self.config.get("calendarEmail")
        if expected and email != expected:
            raise ToolError("calendar_account_mismatch")
        self.config["calendarEmail"] = email
        return email

    def read_event(self, event_id):
        if event_id not in self.readable_ids:
            raise ToolError("event_not_known_or_reconciled")
        event = self._call("google_calendar.read_event", {"calendar_id": "primary", "event_id": event_id})
        if event.get("id") != event_id:
            raise ToolError("event_id_mismatch")
        return event

    def find(self, credit):
        value = q.marker(self.config["codexEmail"], credit["creditId"])
        if re.fullmatch(r"codex-reset-calendar:credit:v1:[0-9a-f]{64}", value) is None:
            raise ToolError("invalid_marker")
        known = {c["creditId"] for c in self.snapshot["credits"]}
        if credit["creditId"] not in known:
            raise ToolError("credit_not_in_live_snapshot")
        self.profile_email()
        token, seen_tokens, seen_ids, matches = None, set(), set(), []
        for _ in range(10):
            args = {"calendar_id": "primary", "query": value, "max_results": 50}
            if token:
                args["next_page_token"] = token
            page = self._call("google_calendar.search_events", args)
            rows = page.get("events")
            if not isinstance(rows, list):
                raise ToolError("calendar_search_invalid")
            for row in rows:
                event_id = row.get("id") if isinstance(row, dict) else None
                if not isinstance(event_id, str) or not event_id:
                    raise ToolError("calendar_search_invalid")
                if event_id in seen_ids:
                    continue
                seen_ids.add(event_id)
                self.readable_ids.add(event_id)
                event = self.read_event(event_id)
                if value in (event.get("description") or ""):
                    matches.append(event)
            token = page.get("next_page_token")
            if not token:
                self.profile_email()
                return matches
            if not isinstance(token, str) or token in seen_tokens:
                raise ToolError("calendar_search_pagination_invalid")
            seen_tokens.add(token)
        raise ToolError("calendar_search_incomplete_no_create")

    def create(self, credit):
        if not self.allow_create or self.state is None:
            raise ToolError("calendar_writes_disabled")
        key = q.credit_key(self.config["codexEmail"], credit["creditId"])
        entry = self.state.ledger()["entries"].get(key)
        if (not entry or entry["state"] != "pending" or entry.get("eventId")
                or entry.get("attemptId") != self.attempt_id or key in self.submitted):
            raise ToolError("fresh_durable_pending_required")
        fresh = q.query(self.client, self.config["codexEmail"], self.config["timeZone"])
        if fresh["detailsState"] != "complete":
            raise ToolError("fresh_complete_credits_required")
        current = next((c for c in q.eligible(fresh) if c["creditId"] == credit["creditId"]), None)
        if current is None or current["expiresAt"] != credit["expiresAt"]:
            raise ToolError("credit_no_longer_available_or_changed")
        self.profile_email()
        payload = event_payload(self.config, current)
        self.submitted.add(key)
        event = self._call("google_calendar.create_event", {
            "calendar_id": "primary", "title": payload["summary"], "description": payload["description"],
            "start_time": payload["start"], "end_time": payload["end"], "timezone_str": self.config["timeZone"],
            "attendees": [], "self_attendance": "omit", "visibility": "private", "transparency": "transparent",
            "reminders": payload["reminders"], "add_google_meet": False, "event_type": "default",
        })
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id:
            raise ToolError("created_event_id_missing")
        # Save the returned id before any subsequent read can time out.
        ledger = self.state.ledger()
        ledger["entries"][key]["eventId"] = event_id
        self.state.atomic("ledger.json", ledger)
        self.readable_ids.add(event_id)
        verified = self.read_event(event_id)
        self.profile_email()
        return verified
