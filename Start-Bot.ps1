$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$botPath = Join-Path $projectRoot 'bot.py'
$envPath = Join-Path $projectRoot '.env'
$pidPath = Join-Path $projectRoot 'bot.pid'
$logDirectory = Join-Path $projectRoot 'logs'

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python environment not found. Run the setup commands in README.md first."
}
if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
    throw ".env not found. Copy .env.example to .env and configure it first."
}

$requiredVariables = @(
    'DISCORD_BOT_TOKEN',
    'DISCORD_CHANNEL_ID',
    'CANVAS_BASE_URL',
    'CANVAS_API_TOKEN',
    'DATABASE_URL'
)
$configuredVariables = @{}
foreach ($line in Get-Content -LiteralPath $envPath) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $configuredVariables[$Matches[1]] = $Matches[2].Trim()
    }
}
$missingVariables = @(
    $requiredVariables | Where-Object {
        -not $configuredVariables.ContainsKey($_) -or
        [string]::IsNullOrWhiteSpace($configuredVariables[$_])
    }
)
if ($missingVariables.Count -gt 0) {
    throw "Set these required variables in .env before starting the bot: $($missingVariables -join ', ')"
}

if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $savedPidText = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    $savedPid = 0
    if (-not [int]::TryParse($savedPidText, [ref]$savedPid) -or $savedPid -le 0) {
        throw "The bot PID file is invalid. Inspect bot.pid before removing it."
    }
    $savedProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $savedPid" -ErrorAction SilentlyContinue
    if ($savedProcess) {
        $samePython = $savedProcess.ExecutablePath -and
            [string]::Equals(
                $savedProcess.ExecutablePath,
                $pythonPath,
                [StringComparison]::OrdinalIgnoreCase
            )
        $sameBot = $savedProcess.CommandLine -and
            $savedProcess.CommandLine.IndexOf(
                $botPath,
                [StringComparison]::OrdinalIgnoreCase
            ) -ge 0
        if ($samePython -and $sameBot) {
            Write-Output "Canvas notifier is already running (PID $savedPid)."
            exit 0
        }
        throw "PID $savedPid belongs to another process. Inspect bot.pid; no process was changed."
    }
    Remove-Item -LiteralPath $pidPath
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$stdoutPath = Join-Path $logDirectory 'bot.log'
$stderrPath = Join-Path $logDirectory 'bot-error.log'
$process = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList "`"$botPath`"" `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

Set-Content -LiteralPath $pidPath -Value $process.Id -NoNewline
Start-Sleep -Seconds 2
$runningProcess = Get-Process -Id $process.Id -ErrorAction SilentlyContinue
if (-not $runningProcess) {
    Remove-Item -LiteralPath $pidPath -ErrorAction SilentlyContinue
    throw "The bot exited during startup. Check logs\bot-error.log for details."
}

Write-Output "Canvas notifier started (PID $($process.Id))."
Write-Output "Logs: $stdoutPath and $stderrPath"
Write-Output "Stop it with: .\Stop-Bot.ps1"
