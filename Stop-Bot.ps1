$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$botPath = Join-Path $projectRoot 'bot.py'
$pidPath = Join-Path $projectRoot 'bot.pid'

if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
    Write-Output 'Canvas notifier is not running (no bot.pid file).'
    exit 0
}

$savedPidText = (Get-Content -LiteralPath $pidPath -Raw).Trim()
$savedPid = 0
if (-not [int]::TryParse($savedPidText, [ref]$savedPid) -or $savedPid -le 0) {
    throw "The bot PID file is invalid. Inspect bot.pid before removing it."
}

$process = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
if (-not $process) {
    Remove-Item -LiteralPath $pidPath
    Write-Output 'Removed a stale bot.pid file; the bot was not running.'
    exit 0
}

$samePython = $process.ExecutablePath -and
    [string]::Equals(
        $process.ExecutablePath,
        $pythonPath,
        [StringComparison]::OrdinalIgnoreCase
    )
$sameBot = $process.CommandLine -and
    $process.CommandLine.IndexOf(
        $botPath,
        [StringComparison]::OrdinalIgnoreCase
    ) -ge 0
if (-not ($samePython -and $sameBot)) {
    throw "PID $savedPid belongs to another process. No process was stopped."
}

Stop-Process -Id $savedPid
Remove-Item -LiteralPath $pidPath
Write-Output "Canvas notifier stopped (PID $savedPid)."
