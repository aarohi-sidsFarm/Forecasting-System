param(
    [string]$IssueDate = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$LogDirectory = Join-Path $ProjectRoot "reports\logs"

if (-not (Test-Path $Python)) {
    throw "Python executable not found at $Python"
}

if ([string]::IsNullOrWhiteSpace($IssueDate)) {
    $IssueDate = (Get-Date).ToString("yyyy-MM-dd")
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$LogPath = Join-Path $LogDirectory "daily_issuance_$IssueDate.log"
Start-Transcript -Path $LogPath -Append | Out-Null

Set-Location $ProjectRoot
try {
    Write-Host "Validating festival calendar and reviewing the next 45 days..." -ForegroundColor Cyan
    & $Python "scripts\audit_festival_calendar.py" --as-of $IssueDate --lookahead-days 45
    if ($LASTEXITCODE -ne 0) {
        throw "Festival calendar validation failed with exit code $LASTEXITCODE. Forecast issuance was not started."
    }

    Write-Host "Issuing immutable procurement forecasts..." -ForegroundColor Cyan
    Write-Host "Issue date: $IssueDate"

    & $Python "scripts\issue_daily_forecasts.py" --issue-date $IssueDate
    if ($LASTEXITCODE -ne 0) {
        throw "Forecast issuance failed with exit code $LASTEXITCODE. Existing issued forecasts were not changed."
    }

    Write-Host "Forecast issuance complete." -ForegroundColor Green
}
finally {
    Write-Host "Issuance log: $LogPath"
    Stop-Transcript | Out-Null
}
