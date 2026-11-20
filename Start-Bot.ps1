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

$databaseUrl = $configuredVariables['DATABASE_URL']
if ($databaseUrl -match '@(localhost|127\.0\.0\.1)(:(\d+))?') {
    $pgPort = if ($Matches[3]) { [int]$Matches[3] } else { 5432 }
    $pgTcp = Test-NetConnection -ComputerName '127.0.0.1' -Port $pgPort -WarningAction SilentlyContinue
    if (-not $pgTcp.TcpTestSucceeded) {
        $serviceName = if ($pgPort -eq 5433) { 'postgresql-x64-14' } else { 'postgresql-x64-18' }
        $pgService = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
        if ($pgService -and $pgService.Status -ne 'Running') {
            Write-Host "PostgreSQL service ($serviceName) is not running. Starting it..."
            try {
                Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -Command Start-Service -Name '$serviceName'" -Wait
            } catch {
                Write-Warning "Could not automatically elevate to start $serviceName. Please start it as Administrator."
            }
            Start-Sleep -Seconds 2
        }
    }
}

if (Test-Path -LiteralPath $pidPath -PathType Leaf) {
    $savedPidText = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    $savedPid = 0
    if (-not [int]::TryParse($savedPidText, [ref]$savedPid) -or $savedPid -le 0) {
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    } else {
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
        }
        Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    }
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
    $errorDetail = if (Test-Path -LiteralPath $stderrPath) { (Get-Content -LiteralPath $stderrPath -Raw).Trim() } else { "" }
    if ($errorDetail) {
        throw "The bot exited during startup:`n$errorDetail"
    }
    throw "The bot exited during startup. Check logs\bot-error.log for details."
}

Write-Output "Canvas notifier started (PID $($process.Id))."
Write-Output "Logs: $stdoutPath and $stderrPath"
Write-Output "Stop it with: .\Stop-Bot.ps1"
