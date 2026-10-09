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
if ($LASTEXITCODE -ne 0) { throw 'Unable to verify task metadata.' }
$taskPlan = ($taskRaw -join "`n") | ConvertFrom-Json
if (-not $Apply) {
    [ordered]@{ taskName=$taskPlan.taskName; action='Disable future triggers and local gate; preserve events and state' } | ConvertTo-Json
    exit 0
}
$taskExisting = Get-ScheduledTask -TaskPath '\' -TaskName $taskPlan.taskName -ErrorAction SilentlyContinue
if ($taskExisting) {
    $taskOwner = [string]$taskExisting.Principal.UserId
    if (-not $taskOwner.StartsWith('S-1-')) {
        $taskOwner = ([Security.Principal.NTAccount]::new($taskOwner)).Translate([Security.Principal.SecurityIdentifier]).Value
    }
    if ($taskOwner -ne $taskSid -or @($taskExisting.Actions).Count -ne 1 -or
        $taskExisting.Actions.Execute -ne $taskPlan.pythonwExecutable -or
        $taskExisting.Actions.Arguments -ne $taskPlan.arguments -or
        $taskExisting.Actions.WorkingDirectory -ne $taskPlan.workingDirectory) {
        throw 'Task ownership/action mismatch; no changes made.'
    }
}
& $taskPython -B -m codex_reset_calendar --state-dir $taskState schedule-disable
if ($LASTEXITCODE -ne 0) { throw 'Unable to disable the local gate.' }
if ($taskExisting) { Disable-ScheduledTask -InputObject $taskExisting -ErrorAction Stop | Out-Null }
Write-Output 'Disabled future synchronization. Events, state and running processes are retained.'
