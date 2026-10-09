[CmdletBinding()]
param([string]$StateDir = (Join-Path $env:USERPROFILE '.codex-reset-calendar'), [switch]$Apply)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$taskProject = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskProject '.venv\Scripts\python.exe'
$taskCodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }
$taskDestination = Join-Path $taskCodexHome 'skills\codex-reset-calendar'
$taskState = [IO.Path]::GetFullPath($StateDir)
$taskPlan = [ordered]@{skill='codex-reset-calendar';destination=$taskDestination;python=$taskPython;state=$taskState;exists=(Test-Path -LiteralPath $taskDestination)}
if (-not $Apply) { $taskPlan | ConvertTo-Json; exit 0 }
if (Test-Path -LiteralPath $taskDestination) { throw 'Skill already exists; no overwrite.' }
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Run Setup.ps1 -Apply first.' }
$taskTemplate = Get-Content -LiteralPath (Join-Path $taskProject 'skills\codex-reset-calendar\SKILL.md') -Raw -Encoding utf8
$taskHelper = Get-Content -LiteralPath (Join-Path $taskProject 'skills\codex-reset-calendar\scripts\Invoke-Tool.ps1.template') -Raw -Encoding utf8
$taskHelper = $taskHelper.Replace('__PYTHON__', $taskPython.Replace("'", "''")).Replace('__STATE__', $taskState.Replace("'", "''"))
New-Item -ItemType Directory -Path (Join-Path $taskDestination 'scripts') -ErrorAction Stop | Out-Null
$taskUtf8 = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText((Join-Path $taskDestination 'SKILL.md'), $taskTemplate, $taskUtf8)
# Windows PowerShell 5.1 parses BOM-less scripts using the local ANSI code page.
# This helper embeds user paths, so include a UTF-8 BOM even when paths are Chinese.
[IO.File]::WriteAllText((Join-Path $taskDestination 'scripts\Invoke-Tool.ps1'), $taskHelper, [Text.UTF8Encoding]::new($true))
Write-Output ('Installed optional skill at ' + $taskDestination)
