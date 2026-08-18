param(
    [string]$IssueDate = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python executable not found at $Python"
}

if ([string]::IsNullOrWhiteSpace($IssueDate)) {
    $IssueDate = (Get-Date).ToString("yyyy-MM-dd")
}

Set-Location $ProjectRoot
Write-Host "Issuing immutable procurement forecasts..." -ForegroundColor Cyan
Write-Host "Issue date: $IssueDate"

& $Python "scripts\issue_daily_forecasts.py" --issue-date $IssueDate
if ($LASTEXITCODE -ne 0) {
    throw "Forecast issuance failed with exit code $LASTEXITCODE. Existing issued forecasts were not changed."
}

Write-Host "Forecast issuance complete." -ForegroundColor Green
