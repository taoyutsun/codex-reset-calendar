[CmdletBinding()]
param([string]$PythonExecutable = 'python.exe', [switch]$Apply)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$taskProject = Split-Path -Parent $PSScriptRoot
$taskVenv = Join-Path $taskProject '.venv'
$taskPython = Join-Path $taskVenv 'Scripts\python.exe'
$taskInterpreter = (Get-Command $PythonExecutable -ErrorAction Stop).Source
$taskPlan = [ordered]@{
    project = $taskProject
    virtualEnvironment = $taskVenv
    python = $taskInterpreter
    actions = @('Create a new project virtual environment', 'Install only this project and its dependencies')
    conflicts = if (Test-Path -LiteralPath $taskVenv) { @($taskVenv) } else { @() }
    initializesCalendar = $false
    enablesSchedule = $false
}
if (-not $Apply) { $taskPlan | ConvertTo-Json -Depth 4; exit 0 }
if (Test-Path -LiteralPath $taskVenv) { throw 'Virtual environment already exists; no overwrite. Use its Python directly.' }
& $taskInterpreter -X utf8 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.10+ is required.' }
& $taskInterpreter -X utf8 -m venv $taskVenv
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed; inspect the partial installation.' }
& $taskPython -X utf8 -m pip install $taskProject
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed; no schedule was enabled.' }
Write-Output 'Installed. Use .venv\Scripts\python.exe -m codex_reset_calendar query.'
