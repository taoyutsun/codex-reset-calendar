"""Normalize only official account/rateLimits/read responses."""
import hashlib
import json
import os
from pathlib import Path
import shutil
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ToolError

UTC = timezone.utc


def utc_now():
    return datetime.now(UTC)


def iso(value):
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ToolError("timezone_unavailable") from None


def expiry_times(seconds, time_zone="Asia/Taipei"):
    if seconds is None:
        return None, None
    if type(seconds) is not int or not 0 <= seconds <= 253402271999:
        raise ToolError("invalid_timestamp")
    try:
        value = datetime.fromtimestamp(seconds, UTC)
        return iso(value), value.astimezone(zone(time_zone)).isoformat(timespec="seconds")
    except (ValueError, OverflowError, OSError):
        raise ToolError("invalid_timestamp") from None


def resolve_codex(executable=None):
    if executable:
        path = Path(executable).expanduser().resolve()
        if not path.is_file():
            raise ToolError("cli_not_found")
        return str(path)
    names = ("codex.cmd", "codex.exe", "codex") if os.name == "nt" else ("codex",)
    for name in names:
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())
    raise ToolError("cli_not_found")


def checked_account(response, expected_email=None):
    account = response.get("account")
    if not isinstance(account, dict) or account.get("type") != "chatgpt":
        raise ToolError("auth_unavailable")
    email = account.get("email")
    if not isinstance(email, str) or not email.strip():
        raise ToolError("account_unverified")
    if expected_email and email.strip().casefold() != expected_email.strip().casefold():
        raise ToolError("account_mismatch")
    return account


def normalize(response, account, time_zone="Asia/Taipei", now=None):
    now = now or utc_now()
    zone(time_zone)
    result = {
        "ok": True, "schemaVersion": 1, "observedAtUtc": iso(now),
        "account": {"email": account["email"].strip().casefold(), "type": "chatgpt",
                    "planType": account.get("planType"), "verified": True},
        "timeZone": time_zone, "timestampUnit": "seconds", "availableCount": None,
        "detailsState": "unavailable", "availableDetailCount": 0,
        "missingDetailCount": None, "credits": [], "warnings": [],
    }
    reset = response.get("rateLimitResetCredits")
    if reset is None:
        result["warnings"].append("reset_credits_unavailable")
        return result
    if not isinstance(reset, dict):
        raise ToolError("invalid_response")
    count = reset.get("availableCount")
    if type(count) is not int or count < 0:
        raise ToolError("invalid_response")
    result["availableCount"] = count
    rows = reset.get("credits")
    if rows is None:
        result["warnings"].append("details_unavailable")
        return result
    if not isinstance(rows, list):
        raise ToolError("invalid_response")
    seen = set()
    incomplete = False
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("status"), str):
            raise ToolError("invalid_response")
        if row["status"] != "available":
            continue
        credit_id = row.get("id")
        if not credit_id or "expiresAt" not in row or "resetType" not in row:
            incomplete = True
            result["warnings"].append("credit_detail_fields_missing")
            continue
        if not isinstance(credit_id, str) or credit_id in seen:
            raise ToolError("invalid_response")
        seen.add(credit_id)
        expires_utc, expires_local = expiry_times(row["expiresAt"], time_zone)
        result["credits"].append({
            "creditId": credit_id, "resetType": row.get("resetType"),
            "status": "available", "expiresAt": row["expiresAt"],
            "expiresAtUtc": expires_utc, "expiresAtLocal": expires_local,
        })
        if row.get("resetType") != "codexRateLimits":
            result["warnings"].append("unsupported_reset_type")
        if row["expiresAt"] is not None and row["expiresAt"] <= now.timestamp():
            result["warnings"].append("available_past_expiry")
    result["credits"].sort(key=lambda c: (c["expiresAt"] is None, c["expiresAt"] or 0, c["creditId"]))
    detail_count = len(result["credits"])
    result.update(availableDetailCount=detail_count, missingDetailCount=max(0, count - detail_count),
                  detailsState="complete" if count == detail_count and not incomplete else "partial")
    if detail_count != count:
        result["warnings"].append("partial_details" if detail_count < count else "inconsistent_count")
        if detail_count > count:
            result["detailsState"] = "inconsistent"
    return result


def query(client, expected_email=None, time_zone="Asia/Taipei"):
    before = checked_account(client.request("account/read", {"refreshToken": False}), expected_email)
    raw = client.request("account/rateLimits/read")
    after = checked_account(client.request("account/read", {"refreshToken": False}), before["email"])
    if before != after:
        raise ToolError("account_changed")
    return normalize(raw, before, time_zone)


def credit_key(codex_email, credit_id):
    # Destination-independent, so an ICS import can later be adopted by the bridge.
    data = [codex_email.strip().casefold(), credit_id]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def marker(codex_email, credit_id):
    return "codex-reset-calendar:credit:v1:" + credit_key(codex_email, credit_id)


def eligible(snapshot, now=None):
    now = now or utc_now()
    return [c for c in snapshot["credits"] if c["resetType"] == "codexRateLimits"
            and c["expiresAt"] is not None and c["expiresAt"] > now.timestamp()]


def text_summary(snapshot):
    count = snapshot["availableCount"]
    lines = [
        "Codex reset credits / Codex 重置額度",
        "Account / 帳號: " + snapshot["account"]["email"],
        "Available / 可用: " + ("unknown / 未知" if count is None else str(count)),
        "Observed / 查詢時間: " + snapshot["observedAtUtc"],
        "Time zone / 時區: " + snapshot["timeZone"],
        "Details / 明細: " + snapshot["detailsState"],
    ]
    for c in snapshot["credits"]:
        lines.append("{} | {} | UTC {}".format(c["creditId"], c["expiresAtLocal"] or "no expiry / 無到期時間",
                                               c["expiresAtUtc"] or "null"))
    lines.extend("Warning / 注意: " + warning for warning in snapshot["warnings"])
    return "\n".join(lines)
