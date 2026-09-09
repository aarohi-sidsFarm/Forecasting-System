param(
    [string]$DailyAt = "22:05",
    [string]$TaskName = "SidsFarm-Daily-Forecast-Issuance",
    [switch]$Replace
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$IssueScript = Join-Path $ProjectRoot "scripts\issue_daily_forecasts.ps1"

if (-not (Test-Path $IssueScript)) {
    throw "Issuance script not found at $IssueScript"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing -and -not $Replace) {
    throw "Scheduled task '$TaskName' already exists. Use -Replace to update it."
}
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$runAt = [datetime]::ParseExact($DailyAt, "HH:mm", $null)
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$IssueScript`"" `
    -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $runAt
# This runs on a personal laptop, not a server: without these three flags the
# task silently no-ops on any night the machine is asleep, off, or unplugged
# at $DailyAt, and -StartWhenAvailable only helps if it's turned back on
# again before the next trigger. That produced repeated gaps in daily
# issuance (e.g. 2026-08-28, 08-31, 09-02, 09-03, 09-05, 09-07 were all
# missed), which is why the accuracy gates keep seeing incomplete actual
# coverage for BLR/PNQ.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 90)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Atomically issues HYD/VGA D-2 and BLR/PNQ D-3 forecasts." `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings | Out-Null

Write-Host "Registered '$TaskName' daily at $DailyAt." -ForegroundColor Green
