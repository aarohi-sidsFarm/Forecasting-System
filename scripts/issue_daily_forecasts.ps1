param(
    [string]$IssueDate = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
# Use the project-root venv when present, otherwise the backend venv.
$PythonCandidates = @(
    (Join-Path $ProjectRoot "venv\Scripts\python.exe"),
    (Join-Path $ProjectRoot "backend\venv\Scripts\python.exe")
)
$Python = $PythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
$LogDirectory = Join-Path $ProjectRoot "reports\logs"

if (-not $Python) {
    throw "Python executable not found at $($PythonCandidates -join ' or ')"
}

if ([string]::IsNullOrWhiteSpace($IssueDate)) {
    $IssueDate = (Get-Date).ToString("yyyy-MM-dd")
}
$CompletedDate = ([datetime]::ParseExact(
    $IssueDate, "yyyy-MM-dd", $null
)).AddDays(-1).ToString("yyyy-MM-dd")

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

    Write-Host "Reconciling completed Query 1968 actuals for $CompletedDate..." -ForegroundColor Cyan
    & $Python "scripts\reconcile_forecast_actuals.py" `
        --start $CompletedDate --end $CompletedDate --refresh
    if ($LASTEXITCODE -ne 0) {
        Write-Warning (
            "Actual reconciliation failed with exit code $LASTEXITCODE. " +
            "Today's issuance will continue; the accuracy gate remains incomplete."
        )
    }

    Write-Host "Issuing immutable procurement forecasts..." -ForegroundColor Cyan
    Write-Host "Issue date: $IssueDate"

    & $Python "scripts\issue_daily_forecasts.py" --issue-date $IssueDate
    if ($LASTEXITCODE -ne 0) {
        throw "Forecast issuance failed with exit code $LASTEXITCODE. Existing issued forecasts were not changed."
    }

    Write-Host "Updating immutable forecast accuracy evidence..." -ForegroundColor Cyan
    & $Python "scripts\evaluate_official_forecasts.py" `
        --minimum-days 28 `
        --maximum-city-wape 4 `
        --maximum-product-wape 8
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Official accuracy report failed with exit code $LASTEXITCODE."
    }

    Write-Host "Forecast issuance complete." -ForegroundColor Green
}
finally {
    Write-Host "Issuance log: $LogPath"
    Stop-Transcript | Out-Null
}
