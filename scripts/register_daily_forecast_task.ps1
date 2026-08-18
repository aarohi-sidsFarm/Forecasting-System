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
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Atomically issues HYD/VGA D-2 and BLR/PNQ D-3 forecasts." `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings | Out-Null

Write-Host "Registered '$TaskName' daily at $DailyAt." -ForegroundColor Green
