"""Explicitly scoped state, atomic writes and one OS-managed process lock."""
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile

from .errors import ToolError
from .query import credit_key, iso, utc_now, zone

APP_ID = "codex-reset-calendar"


def default_state_dir():
    return Path.home() / ".codex-reset-calendar"


def read_json(path, default=None):
    if not path.exists() and default is not None:
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise ToolError("state_unreadable_do_not_overwrite") from None
    if not isinstance(value, dict):
        raise ToolError("state_format_invalid")
    return value


class FileLock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise ToolError("another_run_in_progress") from None
        return self

    def __exit__(self, *_):
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


class State:
    def __init__(self, root=None):
        self.root = Path(root or default_state_dir()).expanduser().resolve()
        if self.root.exists() and self.root.is_symlink():
            raise ToolError("state_root_invalid")

    def path(self, name):
        target = (self.root / name).resolve()
        if self.root not in target.parents:
            raise ToolError("state_path_outside_root")
        return target

    @property
    def installation_id(self):
        return hashlib.sha256(os.path.normcase(str(self.root)).encode("utf-8")).hexdigest()[:12]

    @property
    def task_name(self):
        return "CodexResetCalendar-{}-Daily".format(self.installation_id)

    def lock(self):
        self.config()
        return FileLock(self.path("run.lock"))

    def config_lock(self):
        self.config()
        return FileLock(self.path("config.lock"))

    def atomic(self, name, value):
        target = self.path(name)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.root,
                                             prefix=".crc-", suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def config(self, optional=False):
        path = self.path("config.json")
        if optional and not path.exists():
            return None
        value = read_json(path)
        required = ("codexEmail", "calendarEmail", "codexExecutable", "pythonExecutable", "timeZone")
        if (value.get("appId") != APP_ID or value.get("schemaVersion") != 1
                or value.get("stateRoot") != str(self.root)
                or any(not isinstance(value.get(k), str) or not value[k] for k in required)
                or value.get("calendarId") != "primary" or value.get("taskName") != self.task_name
                or type(value.get("enabled")) is not bool):
            raise ToolError("configuration_scope_or_schema_mismatch")
        zone(value["timeZone"])
        return value

    def empty_ledger(self, config):
        return {"appId": APP_ID, "schemaVersion": 1, "codexEmail": config["codexEmail"],
                "calendarEmail": config["calendarEmail"], "calendarId": "primary", "entries": {}}

    def ledger(self):
        config = self.config()
        value = read_json(self.path("ledger.json"))  # Missing installed state is corruption, not a fresh install.
        expected = self.empty_ledger(config)
        if (any(value.get(k) != expected[k] for k in expected if k != "entries")
                or not isinstance(value.get("entries"), dict)):
            raise ToolError("ledger_scope_or_schema_mismatch")
        for key, entry in value["entries"].items():
            if (not isinstance(entry, dict) or not isinstance(entry.get("creditId"), str)
                    or not entry["creditId"] or key != credit_key(config["codexEmail"], entry["creditId"])
                    or type(entry.get("expiresAt")) is not int
                    or entry.get("state") not in ("pending", "completed")
                    or (entry["state"] == "completed" and not entry.get("eventId"))):
                raise ToolError("ledger_entry_invalid")
        return value

    def initialize(self, config):
        if self.root.exists() and any(self.root.iterdir()):
            raise ToolError("state_directory_exists_no_overwrite")
        self.root.mkdir(parents=True, exist_ok=True)
        config = dict(config, appId=APP_ID, schemaVersion=1, stateRoot=str(self.root),
                      taskName=self.task_name, enabled=False, firstEligibleAtEpoch=None,
                      installedAtUtc=iso(utc_now()))
        self.atomic("config.json", config)
        self.atomic("ledger.json", self.empty_ledger(config))
        self.atomic("verification.json", {"ok": True, "calendarReadVerified": True,
                                          "calendarWriteVerified": False, "observedAtUtc": iso(utc_now())})
        return self.config()

    def log(self, code, created=0, pending=0):
        # Only controlled codes and scalar counts. No account, event, token or backend text.
        handler = RotatingFileHandler(self.path("runtime.log"), maxBytes=262144,
                                      backupCount=3, encoding="utf-8")
        logger = logging.Logger(APP_ID, level=logging.INFO)
        logger.addHandler(handler)
        try:
            logger.info(json.dumps({"atUtc": iso(utc_now()), "code": code,
                                    "created": created, "pending": pending}))
        finally:
            handler.close()


def settings_digest(config):
    fields = ("codexEmail", "calendarEmail", "calendarId", "timeZone",
              "codexExecutable", "pythonExecutable", "stateRoot")
    return hashlib.sha256(json.dumps({k: config[k] for k in fields}, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()
