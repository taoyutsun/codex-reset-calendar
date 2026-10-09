"""Exercise Windows apply scripts against a fake CLI and fake scheduler only."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from codex_reset_calendar.storage import State

PROJECT = Path(__file__).resolve().parents[1]
PS5 = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
SHELLS = [str(p) for p in (PS5, shutil.which("pwsh")) if p and Path(p).is_file()]


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(os.name == "nt" and SHELLS, "Windows PowerShell integration")
class PowerShellTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="crc-ps-offline-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        # The project source installers intentionally bind to its own .venv.
        self.project_python = PROJECT / ".venv/Scripts/python.exe"
        if not self.project_python.is_file():
            self.skipTest("Source installer checks require a project .venv; runtime tests still run in CI.")
        fake = self.root / "fictional-cli.py"
        fake.write_text(
            "import json,sys\n"
            "tools={name:{} for name in ('google_calendar.get_profile','google_calendar.read_event',"
            "'google_calendar.search_events','google_calendar.create_event')}\n"
            "for line in sys.stdin:\n"
            " r=json.loads(line); m=r.get('method'); p=r.get('params',{})\n"
            " if 'id' not in r: continue\n"
            " if m=='initialize': data={}\n"
            " elif m=='account/read': data={'account':{'type':'chatgpt','email':'codex-user@example.com'}}\n"
            " elif m=='account/rateLimits/read': data={'rateLimitResetCredits':{'availableCount':0,'credits':[]}}\n"
            " elif m=='model/list': data={'data':[{'model':'fictional-default-model','isDefault':True}]}\n"
            " elif m=='thread/start': data={'thread':{'id':'fictional-thread'}}\n"
            " elif m=='mcpServerStatus/list': data={'data':[{'name':'codex_apps','tools':tools}]}\n"
            " elif m=='mcpServer/tool/call' and p['tool']=='google_calendar.get_profile': data={'structuredContent':{'email':'calendar-user@example.com'}}\n"
            " else: raise RuntimeError('Unexpected or mutating call in offline installation test')\n"
            " print(json.dumps({'id':r['id'],'result':data}),flush=True)\n", encoding="utf-8")
        self.fake_cmd = self.root / "fictional-codex.cmd"
        # Keep batch source ASCII: cmd.exe decodes literal paths with its local code page.
        self.fake_cmd.write_text('@echo off\n"%CRC_OFFLINE_PYTHON%" -u "%~dp0fictional-cli.py"\n', encoding="ascii")
        self.state = State(self.root / "isolated state 測試")
        self.state.initialize({
            "codexEmail": "codex-user@example.com", "calendarEmail": "calendar-user@example.com",
            "calendarId": "primary", "timeZone": "Asia/Taipei", "codexExecutable": str(self.fake_cmd),
            "pythonExecutable": str(self.project_python),
        })
        self.environment = dict(os.environ, CODEX_HOME=str(self.root / "isolated codex home"),
                                CRC_OFFLINE_PYTHON=str(self.project_python))

    def run_ps(self, shell, script):
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                env=self.environment, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0,
                         result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace"))
        return result.stdout.decode("utf-8-sig", errors="replace")

    def test_plan_scripts_do_not_change_state_or_install_skill(self):
        before = {p.name: p.read_bytes() for p in self.state.root.iterdir()}
        for shell in SHELLS:
            with self.subTest(shell=shell):
                for name in ("Install-Task.ps1", "Disable-Task.ps1", "Install-Skill.ps1"):
                    self.run_ps(shell, "& {} -StateDir {}".format(quote(PROJECT / "scripts" / name),
                                                                quote(self.state.root)))
        after = {p.name: p.read_bytes() for p in self.state.root.iterdir()}
        self.assertEqual(before, after)
        self.assertFalse((self.root / "isolated codex home").exists())

    def test_apply_registration_is_disabled_first_and_uses_only_own_task(self):
        for shell in SHELLS:
            with self.subTest(shell=shell):
                script = r"""
$ErrorActionPreference = 'Stop'
$global:crcMockCalls = [System.Collections.Generic.List[string]]::new()
function Get-ScheduledTask { [CmdletBinding()]param($TaskPath,$TaskName) return $null }
function Register-ScheduledTask {
    [CmdletBinding()]param($TaskPath,$TaskName,$Xml)
    if ($TaskName -eq 'CodexResetCalendar-Daily') { throw 'Production task must never be addressed' }
    [xml]$definition = $Xml
    if ($definition.Task.Settings.Enabled -ne 'false') { throw 'Task must register disabled' }
    $global:crcMockCalls.Add('register-disabled')
}
function Enable-ScheduledTask { [CmdletBinding()]param($TaskPath,$TaskName) $global:crcMockCalls.Add('enable') }
function Disable-ScheduledTask { [CmdletBinding()]param($TaskPath,$TaskName,$InputObject) $global:crcMockCalls.Add('disable') }
& __INSTALL__ -StateDir __STATE__ -Apply
if (($global:crcMockCalls -join ',') -ne 'register-disabled,enable') { throw 'Unexpected scheduler operations' }
"""
                self.run_ps(shell, script.replace("__INSTALL__", quote(PROJECT / "scripts/Install-Task.ps1"))
                            .replace("__STATE__", quote(self.state.root)))
                self.assertTrue(self.state.config()["enabled"])
                config = self.state.config()
                config["enabled"] = False
                self.state.atomic("config.json", config)

    def test_existing_task_rejected_without_registration(self):
        for shell in SHELLS:
            script = r"""
function Get-ScheduledTask { [CmdletBinding()]param($TaskPath,$TaskName) return [pscustomobject]@{TaskName=$TaskName} }
function Register-ScheduledTask { throw 'Must not overwrite a task' }
$caught = $false
try { & __INSTALL__ -StateDir __STATE__ -Apply } catch { $caught = $true }
if (-not $caught) { throw 'Expected conflict stop' }
"""
            self.run_ps(shell, script.replace("__INSTALL__", quote(PROJECT / "scripts/Install-Task.ps1"))
                        .replace("__STATE__", quote(self.state.root)))
        self.assertFalse(self.state.config()["enabled"])

    def test_generated_skill_uses_isolated_paths_and_rejects_overwrite(self):
        shell = SHELLS[0]
        script = "& {} -StateDir {} -Apply".format(quote(PROJECT / "scripts/Install-Skill.ps1"),
                                                  quote(self.state.root))
        self.run_ps(shell, script)
        skill = self.root / "isolated codex home/skills/codex-reset-calendar"
        self.assertTrue((skill / "SKILL.md").exists())
        helper = skill / "scripts/Invoke-Tool.ps1"
        self.assertIn(str(self.project_python), helper.read_text(encoding="utf-8"))
        self.assertIn(str(self.state.root), helper.read_text(encoding="utf-8"))
        out = self.run_ps(shell, "& {} -Mode query".format(quote(helper)))
        self.assertEqual(json.loads(out)["availableCount"], 0)
        before = helper.read_bytes()
        self.run_ps(shell, "$caught=$false; try { " + script +
                    " } catch { $caught=$true }; if (-not $caught) { throw 'Expected skill conflict' }")
        self.assertEqual(helper.read_bytes(), before)

    def test_disable_closes_gate_without_deleting_ledger(self):
        before = self.state.path("ledger.json").read_bytes()
        config = self.state.config()
        config["enabled"] = True
        self.state.atomic("config.json", config)
        script = ("function Get-ScheduledTask { [CmdletBinding()]param($TaskPath,$TaskName) return $null }\n"
                  "& __SCRIPT__ -StateDir __STATE__ -Apply").replace(
                      "__SCRIPT__", quote(PROJECT / "scripts/Disable-Task.ps1")).replace(
                      "__STATE__", quote(self.state.root))
        self.run_ps(SHELLS[0], script)
        self.assertFalse(self.state.config()["enabled"])
        self.assertEqual(self.state.path("ledger.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
