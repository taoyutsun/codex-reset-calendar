import copy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from icalendar import Calendar

from codex_reset_calendar import cli, ics
from codex_reset_calendar.calendar import CalendarAdapter, TOOLS, event_payload
from codex_reset_calendar.errors import ToolError
from codex_reset_calendar import query as q
from codex_reset_calendar.runtime import Runtime
from codex_reset_calendar.schedule import next_eight, set_enabled, task_plan
from codex_reset_calendar.storage import State
from codex_reset_calendar.transport import AppServer

NOW = datetime(2030, 6, 1, 1, 0, 0, tzinfo=timezone.utc)
ACCOUNT = {"type": "chatgpt", "email": "codex-user@example.com", "planType": "pro"}


def credit(identifier="fictional-credit-1", expiry=None):
    return {"id": identifier, "status": "available", "resetType": "codexRateLimits",
            "expiresAt": int((NOW + timedelta(days=2)).timestamp()) if expiry is None else expiry}


def snapshot(rows=None, count=None):
    rows = [credit()] if rows is None else rows
    return q.normalize({"rateLimitResetCredits": {"availableCount": len(rows) if count is None else count,
                                                 "credits": rows}}, ACCOUNT, now=NOW)


def verified_event(config, row, identifier="fictional-event-1"):
    return dict(event_payload(config, row), id=identifier, status="confirmed",
                organizer={"email": config["calendarEmail"]})


class Remote:
    def __init__(self):
        self.rows = [credit()]
        self.count = None
        self.events = {}
        self.create_calls = 0
        self.connections = 0
        self.fail = False
        self.timeout_after_create = False
        self.calendar_email = "calendar-user@example.com"
        self.codex_email = ACCOUNT["email"]

    def factory(self, config, state, allow_create=False):
        remote = self
        class Bridge:
            attempt_id = uuid.uuid4().hex
            def __enter__(self):
                remote.connections += 1
                if remote.fail:
                    raise ToolError("offline")
                if config["codexEmail"] != remote.codex_email:
                    raise ToolError("account_mismatch")
                if config["calendarEmail"] != remote.calendar_email:
                    raise ToolError("calendar_account_mismatch")
                self.snapshot = snapshot(remote.rows, remote.count)
                return self
            def __exit__(self, *_):
                pass
            def read_event(self, event_id):
                if event_id not in remote.events:
                    raise ToolError("calendar_read_failed")
                return copy.deepcopy(remote.events[event_id])
            def find(self, row):
                value = q.marker(config["codexEmail"], row["creditId"])
                return [copy.deepcopy(e) for e in remote.events.values() if value in e["description"]]
            def create(self, row):
                if not allow_create:
                    raise ToolError("calendar_writes_disabled")
                key = q.credit_key(config["codexEmail"], row["creditId"])
                entry = state.ledger()["entries"][key]
                if entry["state"] != "pending" or entry["attemptId"] != self.attempt_id:
                    raise AssertionError("create was not preceded by durable pending")
                remote.create_calls += 1
                event = verified_event(config, row, "fictional-event-" + str(remote.create_calls))
                remote.events[event["id"]] = event
                if remote.timeout_after_create:
                    raise ToolError("timeout")
                return copy.deepcopy(event)
        return Bridge()


class StateCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="crc-offline-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state = State(self.root / "isolated state")
        self.python = self.root / "python.exe"
        self.python.write_bytes(b"fictional executable")
        self.python.with_name("pythonw.exe").write_bytes(b"fictional executable")
        self.state.initialize({
            "codexEmail": ACCOUNT["email"], "calendarEmail": "calendar-user@example.com",
            "calendarId": "primary", "timeZone": "Asia/Taipei",
            "codexExecutable": str(self.python), "pythonExecutable": str(self.python),
        })
        self.now = NOW.astimezone(ZoneInfo("Asia/Taipei"))
        self.remote = Remote()
        self.runtime = Runtime(self.state, self.remote.factory, lambda: self.now)

    def enable_daily(self):
        config = self.state.config()
        config.update(enabled=True, firstEligibleAtEpoch=int((self.now - timedelta(days=1)).timestamp()))
        self.state.atomic("config.json", config)


class QueryTests(unittest.TestCase):
    def test_complete_zero_is_distinct_from_unavailable(self):
        self.assertEqual(snapshot([])["detailsState"], "complete")
        self.assertEqual(snapshot([])["availableCount"], 0)
        missing = q.normalize({}, ACCOUNT, now=NOW)
        self.assertIsNone(missing["availableCount"])
        self.assertEqual(missing["detailsState"], "unavailable")

    def test_count_only_and_partial_details(self):
        result = q.normalize({"rateLimitResetCredits": {"availableCount": 3, "credits": None}}, ACCOUNT)
        self.assertEqual(result["availableCount"], 3)
        self.assertEqual(result["detailsState"], "unavailable")
        result = snapshot(count=3)
        self.assertEqual(result["missingDetailCount"], 2)
        self.assertEqual(result["detailsState"], "partial")

    def test_inconsistent_count(self):
        self.assertEqual(snapshot(count=0)["detailsState"], "inconsistent")

    def test_seconds_and_dst_conversion(self):
        seconds = int(datetime(2030, 7, 1, 12, 34, 56, tzinfo=timezone.utc).timestamp())
        utc, local = q.expiry_times(seconds, "America/New_York")
        self.assertEqual(utc, "2030-07-01T12:34:56Z")
        self.assertEqual(local, "2030-07-01T08:34:56-04:00")
        self.assertEqual(q.expiry_times(seconds)[1], "2030-07-01T20:34:56+08:00")

    def test_invalid_timestamp_units(self):
        for value in (True, -1, 1234567890123, 2.5):
            with self.subTest(value=value), self.assertRaises(ToolError):
                q.expiry_times(value)

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ToolError):
            snapshot([credit(), credit()])

    def test_null_expiry_not_invented(self):
        row = credit()
        row["expiresAt"] = None
        result = snapshot([row])
        self.assertIsNone(result["credits"][0]["expiresAtLocal"])
        self.assertEqual(q.eligible(result, NOW), [])

    def test_absent_detail_fields_report_missing_without_inventing_expiry(self):
        for field in ("id", "expiresAt", "resetType"):
            with self.subTest(field=field):
                row = credit()
                del row[field]
                result = snapshot([row])
                self.assertEqual(result["detailsState"], "partial")
                self.assertEqual(result["missingDetailCount"], 1)
                self.assertIn("credit_detail_fields_missing", result["warnings"])
                self.assertEqual(result["credits"], [])

    def test_unknown_reset_type_and_past_expiry_not_exported(self):
        other = credit("fictional-other")
        other["resetType"] = "unknown-type"
        result = snapshot([other, credit("fictional-past", int(NOW.timestamp()) - 1)])
        self.assertEqual(q.eligible(result, NOW), [])

    def test_account_change_during_query_rejected(self):
        class Client:
            calls = 0
            def request(self, method, params=None):
                if method == "account/read":
                    self.calls += 1
                    return {"account": dict(ACCOUNT, email=ACCOUNT["email"] if self.calls == 1 else "other@example.com")}
                return {"rateLimitResetCredits": {"availableCount": 0, "credits": []}}
        with self.assertRaises(ToolError):
            q.query(Client())

    def test_parser_options_work_on_both_sides(self):
        self.assertEqual(cli.parser().parse_args(["--time-zone", "UTC", "query"]).time_zone, "UTC")
        self.assertEqual(cli.parser().parse_args(["query", "--time-zone", "UTC"]).time_zone, "UTC")


class IcsTests(unittest.TestCase):
    def test_independent_parser_verifies_exact_instants_uid_and_alarm(self):
        result = snapshot()
        text, count = ics.render(result, NOW)
        parsed = Calendar.from_ical(text)
        event = parsed.walk("VEVENT")[0]
        alarm = parsed.walk("VALARM")[0]
        self.assertEqual(count, 1)
        self.assertEqual(int(event["dtstart"].dt.timestamp()), result["credits"][0]["expiresAt"])
        self.assertEqual(event["dtend"].dt - event["dtstart"].dt, timedelta(seconds=60))
        self.assertEqual(alarm["trigger"].dt, -timedelta(minutes=60))
        self.assertEqual(str(event["description"]), q.marker(ACCOUNT["email"], result["credits"][0]["creditId"]))
        self.assertEqual(str(event["class"]), "PRIVATE")
        self.assertEqual(str(event["transp"]), "TRANSPARENT")
        later = Calendar.from_ical(ics.render(result, NOW + timedelta(hours=1))[0]).walk("VEVENT")[0]
        self.assertEqual(event["uid"], later["uid"])

    def test_utf8_octet_folding_roundtrip(self):
        line = "DESCRIPTION:" + ics.escape("繁體中文，測試;\\\n" * 30)
        folded = ics.fold(line)
        self.assertTrue(all(len(part.encode("utf-8")) <= 75 for part in folded.split("\r\n")))
        self.assertEqual(folded.replace("\r\n ", ""), line)

    def test_partial_export_retains_warning(self):
        self.assertEqual(ics.render(snapshot(count=3), NOW)[1], 1)
        with self.assertRaises(ToolError):
            ics.render(snapshot(count=0), NOW)

    def test_existing_export_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "reminders.ics"
            first = ics.export(snapshot(), file, NOW)
            contents = file.read_bytes()
            self.assertFalse(first["recordedAsSynced"])
            with self.assertRaises(ToolError):
                ics.export(snapshot(), file, NOW)
            self.assertEqual(file.read_bytes(), contents)


class SyncTests(StateCase):
    def test_account_change_during_create_stops_remaining_candidates(self):
        self.remote.rows = [credit(), credit("fictional-credit-2")]
        preview = self.runtime.preview()
        original_factory = self.remote.factory
        calls = []
        def factory(*args, **kwargs):
            bridge = original_factory(*args, **kwargs)
            def switched_account(row):
                calls.append(row["creditId"])
                raise ToolError("calendar_account_mismatch")
            bridge.create = switched_account
            return bridge
        self.runtime.bridge_factory = factory
        result = self.runtime.synchronize(preview["previewId"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "calendar_account_mismatch")
        self.assertEqual(result["pendingCount"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.state.ledger()["entries"]), 1)

    def test_failure_after_verified_creation_keeps_truthful_counts(self):
        self.remote.rows = [credit(), credit("fictional-credit-2")]
        preview = self.runtime.preview()
        original_factory = self.remote.factory
        def factory(*args, **kwargs):
            bridge = original_factory(*args, **kwargs)
            original_create = bridge.create
            def create_then_change(row):
                event = original_create(row)
                config = self.state.config()
                config["timeZone"] = "UTC"
                self.state.atomic("config.json", config)
                return event
            bridge.create = create_then_change
            return bridge
        self.runtime.bridge_factory = factory
        result = self.runtime.synchronize(preview["previewId"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "configuration_changed_during_sync")
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["pendingCount"], 0)
        self.assertEqual(self.remote.create_calls, 1)

    def test_disabled_schedule_does_not_prevent_confirmed_manual_sync(self):
        preview = self.runtime.preview()
        self.assertEqual(self.remote.create_calls, 0)
        result = self.runtime.synchronize(preview["previewId"])
        self.assertEqual(result["created"], 1)
        self.assertTrue(result["ok"])
        self.assertFalse(self.state.path("runs.json").exists())
        self.assertFalse(self.state.config()["enabled"])
        next_preview = self.runtime.preview()
        self.assertEqual(next_preview["candidateCount"], 0)
        self.runtime.synchronize(next_preview["previewId"])
        self.assertEqual(self.remote.create_calls, 1)

    def test_missing_confirmation_and_expired_preview(self):
        with self.assertRaises(ToolError):
            self.runtime.synchronize()
        preview = self.runtime.preview()
        self.now += timedelta(minutes=15)
        with self.assertRaises(ToolError):
            self.runtime.synchronize(preview["previewId"])
        self.assertEqual(self.remote.create_calls, 0)

    def test_receipt_binds_settings(self):
        preview = self.runtime.preview()
        config = self.state.config()
        config["timeZone"] = "UTC"
        self.state.atomic("config.json", config)
        with self.assertRaises(ToolError):
            self.runtime.synchronize(preview["previewId"])
        self.assertEqual(self.remote.create_calls, 0)

    def test_changed_expiry_and_unseen_candidate_stop_before_any_create(self):
        for change in ("expiry", "new"):
            with self.subTest(change=change):
                self.remote.rows = [credit()]
                preview = self.runtime.preview()
                if change == "expiry":
                    self.remote.rows[0]["expiresAt"] += 1
                else:
                    self.remote.rows.append(credit("fictional-credit-2"))
                result = self.runtime.synchronize(preview["previewId"])
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], "manual_preview_scope_changed")
                self.assertEqual(self.remote.create_calls, 0)

    def test_incomplete_details_block_preview_and_daily_write(self):
        self.remote.count = 3
        with self.assertRaises(ToolError):
            self.runtime.preview()
        self.enable_daily()
        result = self.runtime.synchronize(daily=True)
        self.assertFalse(result["ok"])
        self.assertEqual(self.remote.create_calls, 0)

    def test_pairing_allows_different_emails_but_rejects_switches(self):
        self.assertNotEqual(self.state.config()["codexEmail"], self.state.config()["calendarEmail"])
        for field in ("codex_email", "calendar_email"):
            prior = getattr(self.remote, field)
            setattr(self.remote, field, "changed@example.com")
            with self.assertRaises(ToolError):
                self.runtime.preview()
            setattr(self.remote, field, prior)

    def test_ics_import_marker_adopted_without_create(self):
        row = snapshot()["credits"][0]
        event = verified_event(self.state.config(), row, "fictional-imported-event")
        event["reminders"] = {"useDefault": True}
        self.remote.events[event["id"]] = event
        preview = self.runtime.preview()
        self.assertEqual(preview["candidateCount"], 0)
        result = self.runtime.synchronize(preview["previewId"])
        self.assertEqual(result["adopted"], 1)
        self.assertEqual(result["reviewCount"], 1)
        self.assertEqual(self.remote.create_calls, 0)
        self.assertEqual(self.state.ledger()["entries"][q.credit_key(ACCOUNT["email"], row["creditId"])]["eventId"],
                         "fictional-imported-event")

    def test_timeout_after_commit_reconciles_without_second_send(self):
        self.remote.timeout_after_create = True
        preview = self.runtime.preview()
        first = self.runtime.synchronize(preview["previewId"])
        self.assertEqual(first["pendingCount"], 1)
        self.remote.timeout_after_create = False
        preview = self.runtime.preview()
        second = self.runtime.synchronize(preview["previewId"])
        self.assertEqual(second["adopted"], 1)
        self.assertEqual(self.remote.create_calls, 1)

    def test_pending_empty_search_is_never_resent(self):
        preview = self.runtime.preview()
        self.remote.timeout_after_create = True
        self.runtime.synchronize(preview["previewId"])
        self.remote.events = {}
        self.remote.timeout_after_create = False
        preview = self.runtime.preview()
        result = self.runtime.synchronize(preview["previewId"])
        self.assertEqual(result["pendingCount"], 1)
        self.assertEqual(self.remote.create_calls, 1)

    def test_changed_and_missing_credits_retain_events(self):
        preview = self.runtime.preview()
        self.runtime.synchronize(preview["previewId"])
        self.remote.rows[0]["expiresAt"] += 1
        self.assertEqual(self.runtime.preview()["actions"][0]["action"], "review_changed_expiry")
        self.remote.rows = []
        self.assertEqual(self.runtime.preview()["actions"][0]["action"], "retain_missing_credit")
        self.assertEqual(len(self.remote.events), 1)
        self.assertEqual(len(self.state.ledger()["entries"]), 1)

    def test_duplicate_remote_markers_do_not_create(self):
        row = snapshot()["credits"][0]
        for identifier in ("fictional-duplicate-1", "fictional-duplicate-2"):
            self.remote.events[identifier] = verified_event(self.state.config(), row, identifier)
        preview = self.runtime.preview()
        result = self.runtime.synchronize(preview["previewId"])
        self.assertEqual(result["reviewCount"], 1)
        self.assertEqual(self.remote.create_calls, 0)

    def test_daily_claim_is_durable_before_network_and_not_retried(self):
        self.enable_daily()
        self.remote.fail = True
        original_factory = self.remote.factory
        def inspect_factory(*args, **kwargs):
            self.assertEqual(json.loads(self.state.path("runs.json").read_text())["attempts"][-1]["status"], "running")
            return original_factory(*args, **kwargs)
        self.runtime.bridge_factory = inspect_factory
        self.assertFalse(self.runtime.synchronize(daily=True)["ok"])
        self.remote.fail = False
        self.assertEqual(self.runtime.synchronize(daily=True)["skipped"], "already_attempted_today")
        self.assertEqual(self.remote.connections, 1)
        self.now += timedelta(days=1)
        self.assertEqual(self.runtime.synchronize(daily=True)["created"], 1)

    def test_daily_gates_and_rollback(self):
        self.assertEqual(self.runtime.synchronize(daily=True)["skipped"], "disabled")
        self.enable_daily()
        original = self.now
        self.now = self.now.replace(hour=7)
        self.assertEqual(self.runtime.synchronize(daily=True)["skipped"], "before_today_0800")
        self.now = original
        self.runtime.synchronize(daily=True)
        self.now -= timedelta(days=1)
        self.assertIn(self.runtime.synchronize(daily=True)["skipped"], ("clock_rollback", "before_first_eligible"))

    def test_two_processes_share_one_os_lock(self):
        script = ("import sys; from codex_reset_calendar.storage import State; "
                  "from codex_reset_calendar.errors import ToolError\n"
                  "try:\n with State(sys.argv[1]).lock(): pass\n"
                  "except ToolError as e:\n print(e.code); sys.exit(7)\n")
        with self.state.lock():
            child = subprocess.run([sys.executable, "-B", "-c", script, str(self.state.root)],
                                   capture_output=True, text=True, timeout=15)
            self.assertEqual(child.returncode, 7)
            self.assertIn("another_run_in_progress", child.stdout)
            self.assertEqual(self.runtime.synchronize(daily=True)["skipped"], "another_run_in_progress")
        child = subprocess.run([sys.executable, "-B", "-c", script, str(self.state.root)],
                               capture_output=True, text=True, timeout=15)
        self.assertEqual(child.returncode, 0)

    def test_state_cannot_escape_or_silently_reset_corruption(self):
        with self.assertRaises(ToolError):
            self.state.path("../outside.json")
        self.state.path("ledger.json").write_text("invalid JSON")
        with self.assertRaises(ToolError):
            self.runtime.status()
        with self.assertRaises(ToolError):
            self.state.initialize(self.state.config())


class ScheduleTests(StateCase):
    def test_xml_uses_local_0800_interactive_user_and_disabled_registration(self):
        plan = task_plan(self.state, "S-1-5-21-111-222-333-1001", self.now)
        xml = ET.fromstring(plan["xml"])
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        boundary = xml.find(".//t:CalendarTrigger/t:StartBoundary", ns).text
        self.assertEqual(boundary, "2030-06-02T08:00:00")
        self.assertEqual(xml.find(".//t:Settings/t:Enabled", ns).text, "false")
        self.assertEqual(xml.find(".//t:LogonType", ns).text, "InteractiveToken")
        self.assertEqual(xml.find(".//t:RunLevel", ns).text, "LeastPrivilege")
        self.assertEqual(xml.find(".//t:MultipleInstancesPolicy", ns).text, "IgnoreNew")
        self.assertIsNone(xml.find(".//t:RestartOnFailure", ns))
        self.assertNotEqual(plan["taskName"], "CodexResetCalendar-Daily")
        self.assertIn("codex_reset_calendar", plan["arguments"])
        self.assertIn(str(self.state.root), plan["arguments"])

    def test_next_boundary_at_before_after_0800(self):
        before = self.now.replace(hour=7)
        at = self.now.replace(hour=8, minute=0, second=0)
        self.assertEqual(next_eight(before).date(), before.date())
        self.assertEqual(next_eight(at).date(), at.date() + timedelta(days=1))
        self.assertEqual(next_eight(self.now).date(), self.now.date() + timedelta(days=1))

    def test_installation_identity_uses_state_path(self):
        self.assertEqual(self.state.task_name, State(self.state.root).task_name)
        self.assertNotEqual(self.state.task_name, State(self.root / "different").task_name)

    def test_gate_refuses_past_boundary_and_disable_retains_ledger(self):
        with self.assertRaises(ToolError):
            set_enabled(self.state, True, int(self.now.timestamp()) - 1,
                        "S-1-5-21-111-222-333-1001", self.now)
        before = self.state.path("ledger.json").read_bytes()
        set_enabled(self.state, False)
        self.assertEqual(self.state.path("ledger.json").read_bytes(), before)

    def test_disable_can_close_gate_while_sync_lock_is_owned(self):
        self.enable_daily()
        with self.state.lock():
            set_enabled(self.state, False)
        self.assertFalse(self.state.config()["enabled"])


class RpcClient:
    def __init__(self, config):
        self.config = config
        self.calls = []
        self.tools = {name: {} for name in TOOLS}
        self.tool_error = False
        self.page_token = None
        self.events = {}
        self.create_count = 0
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def request(self, method, params=None):
        self.calls.append((method, params))
        if method == "account/read":
            return {"account": dict(ACCOUNT)}
        if method == "account/rateLimits/read":
            return {"rateLimitResetCredits": {"availableCount": 1, "credits": [credit()]}}
        if method == "model/list":
            return {"data": [{"model": "fictional-default-model", "isDefault": True}]}
        if method == "thread/start":
            return {"thread": {"id": "fictional-ephemeral-thread"}}
        if method == "mcpServerStatus/list":
            return {"data": [{"name": "codex_apps", "tools": self.tools}], "nextCursor": None}
        tool, args = params["tool"], params["arguments"]
        if self.tool_error:
            return {"isError": True, "content": [{"text": "fake sensitive backend detail"}]}
        if tool.endswith("get_profile"):
            data = {"email": self.config["calendarEmail"]}
        elif tool.endswith("search_events"):
            data = {"events": [], "next_page_token": self.page_token}
        elif tool.endswith("create_event"):
            self.create_count += 1
            row = snapshot()["credits"][0]
            data = verified_event(self.config, row)
            self.events[data["id"]] = data
        elif tool.endswith("read_event"):
            data = self.events[args["event_id"]]
        else:
            raise AssertionError(tool)
        return {"structuredContent": data, "isError": False}


class AdapterTests(StateCase):
    def test_no_model_turns_or_credential_methods_and_account_pairing(self):
        client = RpcClient(self.state.config())
        with CalendarAdapter(self.state.config(), self.state, client=client) as bridge:
            self.assertEqual(bridge.profile_email(), "calendar-user@example.com")
        methods = {method for method, _ in client.calls}
        self.assertNotIn("turn/start", methods)
        self.assertNotIn("account/login/start", methods)
        self.assertNotIn("account/rateLimitResetCredit/consume", methods)

    def test_missing_connector_and_raw_errors_fail_safely(self):
        client = RpcClient(self.state.config())
        client.tools = {}
        with self.assertRaises(ToolError) as context:
            with CalendarAdapter(self.state.config(), self.state, client=client):
                pass
        self.assertEqual(context.exception.code, "calendar_tools_unavailable")
        client = RpcClient(self.state.config())
        client.tool_error = True
        with self.assertRaises(ToolError) as context:
            with CalendarAdapter(self.state.config(), self.state, client=client):
                pass
        self.assertNotIn("sensitive", str(context.exception))

    def test_incomplete_pagination_does_not_allow_create(self):
        client = RpcClient(self.state.config())
        client.page_token = "fictional-repeated-token"
        with CalendarAdapter(self.state.config(), self.state, client=client) as bridge:
            with self.assertRaises(ToolError):
                bridge.find(bridge.snapshot["credits"][0])
        self.assertEqual(client.create_count, 0)

    def test_actual_adapter_requires_pending_and_reads_back_once(self):
        client = RpcClient(self.state.config())
        with CalendarAdapter(self.state.config(), self.state, allow_create=True, client=client) as bridge:
            row = bridge.snapshot["credits"][0]
            with self.assertRaises(ToolError):
                bridge.create(row)
            key = q.credit_key(ACCOUNT["email"], row["creditId"])
            ledger = self.state.ledger()
            ledger["entries"][key] = {"state": "pending", "creditId": row["creditId"],
                                     "expiresAt": row["expiresAt"], "attemptId": bridge.attempt_id}
            self.state.atomic("ledger.json", ledger)
            event = bridge.create(row)
            self.assertEqual(event["id"], "fictional-event-1")
            self.assertEqual(self.state.ledger()["entries"][key]["eventId"], event["id"])
            with self.assertRaises(ToolError):
                bridge.create(row)
        self.assertEqual(client.create_count, 1)


class TransportTests(unittest.TestCase):
    def test_real_stdio_subprocess_and_allowlist(self):
        script = (
            "import json,sys\n"
            "for line in sys.stdin:\n"
            " request=json.loads(line)\n"
            " if 'id' not in request: continue\n"
            " if request['method']=='account/read': result={'account': {'type':'chatgpt','email':'codex-user@example.com'}}\n"
            " else: result={'rateLimitResetCredits': {'availableCount':0,'credits':[]}}\n"
            " print(json.dumps({'id':request['id'],'result':result}),flush=True)\n")
        with AppServer([sys.executable, "-u", "-c", script]) as client:
            self.assertEqual(q.query(client)["availableCount"], 0)
            for method in ("turn/start", "account/login/start", "account/rateLimitResetCredit/consume"):
                with self.subTest(method=method), self.assertRaises(ToolError):
                    client.request(method)

    def test_host_approval_request_is_not_accepted(self):
        script = (
            "import json,sys\n"
            "for line in sys.stdin:\n"
            " r=json.loads(line)\n"
            " if 'id' not in r: continue\n"
            " if r.get('method')=='initialize': print(json.dumps({'id':r['id'],'result':{}}),flush=True)\n"
            " elif r.get('method')=='account/read': print(json.dumps({'id':999,'method':'tool/requestUserInput','params':{}}),flush=True)\n")
        with AppServer([sys.executable, "-u", "-c", script]) as client:
            with self.assertRaises(ToolError) as context:
                client.request("account/read", {"refreshToken": False})
            self.assertEqual(context.exception.code, "host_request_required")


if __name__ == "__main__":
    unittest.main()
