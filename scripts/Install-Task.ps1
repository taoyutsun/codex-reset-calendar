[CmdletBinding()]
param([string]$StateDir = (Join-Path $env:USERPROFILE '.codex-reset-calendar'), [switch]$Apply)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$taskState = [IO.Path]::GetFullPath($StateDir)
$taskConfig = Get-Content -LiteralPath (Join-Path $taskState 'config.json') -Raw -Encoding utf8 | ConvertFrom-Json
if ($taskConfig.appId -ne 'codex-reset-calendar') { throw 'Unrecognized state; no changes made.' }
$taskPython = [string]$taskConfig.pythonExecutable
$taskSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$taskRaw = & $taskPython -B -m codex_reset_calendar --state-dir $taskState schedule-plan --owner-sid $taskSid
if ($LASTEXITCODE -ne 0) { throw 'Unable to build the task plan.' }
$taskPlan = ($taskRaw -join "`n") | ConvertFrom-Json
if (-not $Apply) { $taskPlan | ConvertTo-Json -Depth 5; exit 0 }
if (Get-ScheduledTask -TaskPath '\' -TaskName $taskPlan.taskName -ErrorAction SilentlyContinue) {
    throw 'Task already exists; no overwrite.'
}
# Successful reads do not prove unattended writes will be approved.
& $taskPython -B -m codex_reset_calendar --state-dir $taskState doctor --format json
if ($LASTEXITCODE -ne 0) { throw 'Read-only preflight failed; no task registered.' }
$taskRegistered = $false
try {
    Register-ScheduledTask -TaskPath '\' -TaskName $taskPlan.taskName -Xml $taskPlan.xml -ErrorAction Stop | Out-Null
    $taskRegistered = $true
    & $taskPython -B -m codex_reset_calendar --state-dir $taskState schedule-enable --owner-sid $taskSid --first-eligible-epoch $taskPlan.firstEligibleAtEpoch
    if ($LASTEXITCODE -ne 0) { throw 'Unable to enable the local gate.' }
    Enable-ScheduledTask -TaskPath '\' -TaskName $taskPlan.taskName -ErrorAction Stop | Out-Null
    Write-Output ('Enabled ' + $taskPlan.taskName + '; first eligible run: ' + $taskPlan.firstEligibleLocal)
} catch {
    if ($taskRegistered) {
        Disable-ScheduledTask -TaskPath '\' -TaskName $taskPlan.taskName -ErrorAction SilentlyContinue | Out-Null
    }
    & $taskPython -B -m codex_reset_calendar --state-dir $taskState schedule-disable | Out-Null
    throw
}
