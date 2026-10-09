"""Confirmation receipts, conservative synchronization and daily claiming."""
from datetime import datetime, timedelta, timezone
import uuid

from .calendar import CalendarAdapter, event_issues
from .errors import ToolError
from . import query as q
from .storage import read_json, settings_digest


def local_now():
    return datetime.now().astimezone()


def actions(state, bridge, now=None):
    now = now or q.utc_now()
    if bridge.snapshot["detailsState"] != "complete":
        raise ToolError("credits_incomplete_no_sync")
    config, ledger = state.config(), state.ledger()
    rows, seen = [], set()
    for credit in bridge.snapshot["credits"]:
        key = q.credit_key(config["codexEmail"], credit["creditId"])
        seen.add(key)
        entry = ledger["entries"].get(key)
        row = {"key": key, "creditId": credit["creditId"], "expiresAt": credit["expiresAt"],
               "expiresAtLocal": credit["expiresAtLocal"], "eventId": entry.get("eventId") if entry else None}
        if entry and entry["expiresAt"] != credit["expiresAt"]:
            row["action"] = "review_changed_expiry"
        elif entry and entry["state"] == "completed":
            event = bridge.read_event(entry["eventId"])
            row["issues"] = event_issues(event, config, credit)
            row["action"] = "review_event" if row["issues"] else "already_completed"
        elif (credit["resetType"] != "codexRateLimits" or credit["expiresAt"] is None
              or credit["expiresAt"] <= now.timestamp()):
            row["action"] = "retain_pending" if entry else "skip_no_future_expiry"
        else:
            if entry and entry.get("eventId"):
                # A known id from an uncertain create is stronger than search indexing.
                event = bridge.read_event(entry["eventId"])
                matches = [event]
            else:
                matches = bridge.find(credit)
            if len(matches) > 1:
                row["action"] = "review_duplicate_markers"
            elif matches:
                event = matches[0]
                row.update(action="adopt_existing", event=event,
                           issues=event_issues(event, config, credit))
            else:
                row["action"] = "pending_no_match_no_retry" if entry else "new_candidate"
        rows.append(row)
    for key, entry in ledger["entries"].items():
        if key not in seen:
            rows.append({"key": key, "creditId": entry["creditId"],
                         "eventId": entry.get("eventId"), "action": "retain_missing_credit"})
    return rows


class Runtime:
    def __init__(self, state, bridge_factory=CalendarAdapter, clock=local_now):
        self.state, self.bridge_factory, self.clock = state, bridge_factory, clock
        self.config = state.config()

    def bridge(self, writes=False):
        return self.bridge_factory(self.state.config(), self.state, allow_create=writes)

    def preview(self):
        with self.state.lock():
            config = self.state.config()
            with self.bridge() as bridge:
                plan = actions(self.state, bridge, self.clock())
                candidates = [{k: a[k] for k in ("key", "creditId", "expiresAt", "expiresAtLocal")}
                              for a in plan if a["action"] == "new_candidate"]
                now = self.clock()
                receipt = {"id": uuid.uuid4().hex, "createdAtUtc": q.iso(now),
                           "expiresAtUtc": q.iso(now + timedelta(minutes=15)),
                           "settingsDigest": settings_digest(config), "candidates": candidates}
                self.state.atomic("preview.json", receipt)
                # Do not include raw event bodies in a preview or log.
                clean_plan = [{k: v for k, v in a.items() if k != "event"} for a in plan]
                return {"ok": True, "previewId": receipt["id"], "previewExpiresAtUtc": receipt["expiresAtUtc"],
                        "codexEmail": config["codexEmail"], "calendarEmail": config["calendarEmail"],
                        "calendarId": "primary", "timeZone": config["timeZone"],
                        "eventPolicy": {"visibility": "private", "transparency": "transparent",
                                        "durationSeconds": 60, "popupMinutesBefore": 60,
                                        "attendees": [], "addGoogleMeet": False},
                        "candidateCount": len(candidates), "needsUserConfirmation": bool(candidates),
                        "candidates": candidates, "actions": clean_plan, "calendarWrites": 0, "modelTurns": 0}

    def receipt(self, preview_id):
        value = read_json(self.state.path("preview.json"), {})
        if not preview_id or value.get("id") != preview_id:
            raise ToolError("manual_preview_required")
        from .calendar import parse_time
        now = self.clock()
        if not parse_time(value["createdAtUtc"]) <= now < parse_time(value["expiresAtUtc"]):
            raise ToolError("manual_preview_expired")
        if value.get("settingsDigest") != settings_digest(self.state.config()):
            raise ToolError("manual_preview_settings_changed")
        return {(c["key"], c["expiresAt"]) for c in value["candidates"]}

    def daily_due(self, config, runs):
        now = self.clock()
        if not config["enabled"]:
            return "disabled"
        first = config.get("firstEligibleAtEpoch")
        if type(first) is not int or now.timestamp() < first:
            return "before_first_eligible"
        if now.hour < 8:
            return "before_today_0800"
        date = now.date().isoformat()
        if runs.get("highWaterDate", "") > date:
            return "clock_rollback"
        if any(a.get("localDate") == date for a in runs["attempts"]):
            return "already_attempted_today"
        return None

    def synchronize(self, preview_id=None, daily=False):
        if not daily and not preview_id:
            raise ToolError("manual_preview_required")
        try:
            with self.state.lock():
                config = self.state.config()
                approved = None if daily else self.receipt(preview_id)
                runs = read_json(self.state.path("runs.json"),
                                 {"schemaVersion": 1, "attempts": [], "highWaterDate": ""})
                if (runs.get("schemaVersion") != 1 or not isinstance(runs.get("attempts"), list)
                        or any(not isinstance(a, dict) for a in runs["attempts"])):
                    raise ToolError("runs_state_invalid")
                attempt = None
                if daily:
                    reason = self.daily_due(config, runs)
                    if reason:
                        return {"ok": True, "skipped": reason, "created": 0}
                    date = self.clock().date().isoformat()
                    attempt = {"localDate": date, "startedAtUtc": q.iso(self.clock()), "status": "running"}
                    runs["attempts"] = (runs["attempts"] + [attempt])[-30:]
                    runs["highWaterDate"] = max(date, runs.get("highWaterDate", ""))
                    self.state.atomic("runs.json", runs)  # Durable claim before any network operation.
                try:
                    progress = {"created": 0, "adopted": 0, "reviewCount": 0}
                    result = self._sync(config, approved, daily, progress)
                except ToolError as error:
                    result = dict(progress, ok=False, error=error.code)
                except Exception:
                    result = dict(progress, ok=False, error="sync_failed")
                result["pendingCount"] = sum(e["state"] == "pending"
                                             for e in self.state.ledger()["entries"].values())
                if attempt is not None:
                    attempt.update(status="completed" if result["ok"] else "error",
                                   finishedAtUtc=q.iso(self.clock()))
                    self.state.atomic("runs.json", runs)
                self.state.atomic("last-result.json", result)
                self.state.log("sync_completed" if result["ok"] else "sync_failed",
                               result["created"], result.get("pendingCount", 0))
                return result
        except ToolError as error:
            if error.code == "another_run_in_progress":
                return {"ok": True, "skipped": error.code, "created": 0}
            raise

    def _sync(self, config, approved, daily, progress):
        created, adopted, review = 0, 0, 0
        with self.bridge(writes=True) as bridge:
            plan = actions(self.state, bridge, self.clock())
            candidates = {(a["key"], a["expiresAt"]) for a in plan if a["action"] == "new_candidate"}
            if approved is not None and not candidates.issubset(approved):
                raise ToolError("manual_preview_scope_changed")
            if settings_digest(config) != settings_digest(self.state.config()):
                raise ToolError("configuration_changed_during_sync")
            by_id = {c["creditId"]: c for c in bridge.snapshot["credits"]}
            for action in plan:
                kind, key = action["action"], action["key"]
                if kind == "adopt_existing":
                    event = action["event"]
                    # A read known by id must also have an exact identity marker.
                    if q.marker(config["codexEmail"], action["creditId"]) not in (event.get("description") or ""):
                        review += 1
                        progress["reviewCount"] = review
                        continue
                    ledger = self.state.ledger()
                    ledger["entries"][key] = {
                        "creditId": action["creditId"], "expiresAt": action["expiresAt"], "state": "completed",
                        "eventId": event["id"], "source": "marker_reconciliation",
                        "verifiedAtUtc": q.iso(self.clock()), "policyIssues": action["issues"],
                    }
                    self.state.atomic("ledger.json", ledger)
                    adopted += 1
                    review += bool(action["issues"])
                    progress.update(adopted=adopted, reviewCount=review)
                elif kind == "new_candidate":
                    current_config = self.state.config()
                    if settings_digest(config) != settings_digest(current_config):
                        raise ToolError("configuration_changed_during_sync")
                    if daily and not current_config["enabled"]:
                        raise ToolError("disabled_during_run")
                    ledger = self.state.ledger()
                    ledger["entries"][key] = {
                        "creditId": action["creditId"], "expiresAt": action["expiresAt"], "state": "pending",
                        "attemptId": bridge.attempt_id, "attemptedAtUtc": q.iso(self.clock()),
                    }
                    self.state.atomic("ledger.json", ledger)
                    try:
                        event = bridge.create(by_id[action["creditId"]])
                    except ToolError:
                        raise  # Stop this run; preserve pending and never automatically resend.
                    except Exception:
                        raise ToolError("calendar_create_unverified") from None
                    if (not isinstance(event, dict) or not event.get("id")
                            or q.marker(config["codexEmail"], action["creditId"]) not in (event.get("description") or "")):
                        raise ToolError("created_event_unverified")
                    issues = event_issues(event, config, by_id[action["creditId"]])
                    ledger = self.state.ledger()
                    ledger["entries"][key].update(state="completed", eventId=event["id"],
                                                  verifiedAtUtc=q.iso(self.clock()), policyIssues=issues)
                    self.state.atomic("ledger.json", ledger)
                    created += 1
                    review += bool(issues)
                    progress.update(created=created, reviewCount=review)
                elif kind.startswith("review") or kind in ("pending_no_match_no_retry", "retain_pending"):
                    review += 1
                    progress["reviewCount"] = review
        pending = sum(e["state"] == "pending" for e in self.state.ledger()["entries"].values())
        return {"ok": review == 0 and pending == 0, "created": created, "adopted": adopted,
                "reviewCount": review, "pendingCount": pending, "modelTurns": 0}

    def status(self):
        ledger = self.state.ledger()
        return {"ok": True, "stateRoot": str(self.state.root), "taskName": self.state.task_name,
                "enabled": self.config["enabled"], "firstEligibleAtEpoch": self.config["firstEligibleAtEpoch"],
                "codexEmail": self.config["codexEmail"], "calendarEmail": self.config["calendarEmail"],
                "timeZone": self.config["timeZone"], "ledgerEntries": len(ledger["entries"]),
                "pendingEntries": sum(e["state"] == "pending" for e in ledger["entries"].values()),
                "runs": read_json(self.state.path("runs.json"), {}),
                "lastResult": read_json(self.state.path("last-result.json"), {}),
                "verification": read_json(self.state.path("verification.json"), {}),
                "logLimitBytes": 1048576}
