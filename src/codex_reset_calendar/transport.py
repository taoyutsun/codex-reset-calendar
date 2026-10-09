"""Bounded stdio RPC transport adapted from the original tool."""
import json
import os
import queue
import subprocess
import threading
import time

from .errors import ToolError, fail

class AppServer:
    """One owned process, a bounded session, and an explicit read-only RPC list."""

    ALLOWED = {"initialize", "account/read", "account/rateLimits/read"}

    def __init__(self, command, timeout=25):
        self.command = command
        self.timeout = timeout
        self.process = None
        self.messages = queue.Queue()
        self.next_id = 0

    def __enter__(self):
        self.deadline = time.monotonic() + self.timeout
        try:
            self.process = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError:
            fail("cli_start_failed", "無法啟動既有 Codex CLI，請確認安裝路徑與執行權限。")
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.request("initialize", {"clientInfo": {
                "name": "codex_reset_calendar", "title": "Codex Reset Calendar", "version": "0.1.0"
            }})
            self._send({"method": "initialized", "params": {}})
        except Exception:
            self.close()
            raise
        return self

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                # Ignore notifications, which may contain unrelated information.
                if isinstance(message, dict) and "id" in message:
                    self.messages.put(message)
        finally:
            self.messages.put(None)

    def _send(self, value):
        try:
            self.process.stdin.write(json.dumps(value) + "\n")
            self.process.stdin.flush()
        except (OSError, ValueError):
            fail("transport_closed", "Codex app-server 連線已關閉；未取得可用的即時結果。")

    def request(self, method, params=None):
        if method not in self.ALLOWED:
            fail("method_not_allowed", "查詢工具禁止執行這個方法。")
        if method == "account/read" and params != {"refreshToken": False}:
            fail("method_not_allowed", "帳號查詢必須使用 refreshToken=false。")
        self.next_id += 1
        request_id = self.next_id
        request = {"id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        self._send(request)
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                fail("timeout", "唯讀查詢逾時；請檢查網路及既有 Codex 登入狀態後重試。")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty:
                fail("timeout", "唯讀查詢逾時；請檢查網路及既有 Codex 登入狀態後重試。")
            if message is None:
                fail("transport_closed", "Codex app-server 已結束；未取得可用的即時結果。")
            if "method" in message:
                # Do not supply tokens, handle host requests, or trigger logins.
                self._send({"id": message["id"], "error": {
                    "code": -32601, "message": "Read-only client does not handle server requests"
                }})
                fail("host_request_required", "伺服器要求主機協助；此唯讀工具不提供認證或執行其他動作。")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                # Classify internally; never print raw backend diagnostics or tokens.
                detail = str(error.get("message", "")).lower() if isinstance(error, dict) else ""
                if any(word in detail for word in ("offline", "network", "connect", "dns", "timed out", "request error", "error sending request")):
                    fail("offline", "Codex 無法連線取得最新限額；未將舊資料當作查詢結果。")
                if any(word in detail for word in ("unauthorized", "authentication", "401", "login", "sign in")):
                    fail("auth_unavailable", "既有 Codex 登入目前無法讀取限額；本工具不變更登入。")
                fail("rpc_error", "Codex 唯讀介面回傳錯誤；未取得可用結果。")
            result = message.get("result")
            if not isinstance(result, dict):
                fail("invalid_response", "Codex 回傳的資料格式不符預期。")
            return result

    def close(self):
        if self.process is None:
            return
        try:
            self.process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            # Windows .cmd launches child processes. Only stop this owned tree.
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=3, creationflags=subprocess.CREATE_NO_WINDOW)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        if not self.reader.is_alive():
            self.process.stdout.close()

    def __exit__(self, *_):
        self.close()
