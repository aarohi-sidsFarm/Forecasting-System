param(
    [int]$TrainingQueryId = 3269,
    [string]$StartDate = "2025-05-01",
    [string]$EndDate = "",
    [int]$BacktestDays = 7,
    [switch]$SkipTraining,
    [switch]$SkipBacktest
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Python executable not found at $Python. Activate/create venv first."
}

if ([string]::IsNullOrWhiteSpace($EndDate)) {
    $EndDate = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
}

$BacktestStartDate = ([datetime]::ParseExact($EndDate, "yyyy-MM-dd", $null)).AddDays(-1 * ($BacktestDays - 1)).ToString("yyyy-MM-dd")

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Command
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    Write-Host ($Command -join " ")
    if ($Command.Length -gt 1) {
        & $Command[0] @($Command[1..($Command.Length - 1)])
    } else {
        & $Command[0]
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

Set-Location $ProjectRoot

Write-Host "Daily refresh starting..." -ForegroundColor Green
Write-Host "Project root       : $ProjectRoot"
Write-Host "Training query ID  : $TrainingQueryId"
Write-Host "Training window    : $StartDate -> $EndDate"
Write-Host "Backtest window    : $BacktestStartDate -> $EndDate"

if (-not $SkipTraining) {
    Invoke-Step "Fetch Redash training export" @(
        $Python,
        "scripts\fetch_redash_training_export.py",
        "--query-id", "$TrainingQueryId",
        "--start-date", "$StartDate",
        "--end-date", "$EndDate"
    )

    Invoke-Step "Process raw training data" @($Python, "ml_pipeline\process_all_data.py")
    Invoke-Step "Fill zero-demand gaps" @($Python, "ml_pipeline\fill_gaps.py")
    Invoke-Step "Build features" @($Python, "ml_pipeline\build_features.py")
    Invoke-Step "Train general model" @($Python, "ml_pipeline\train_general_lgbm.py")
    Invoke-Step "Train HYD model" @($Python, "ml_pipeline\train_hyd_lgbm.py")
} else {
    Write-Host "Skipping training stages." -ForegroundColor Yellow
}

if (-not $SkipBacktest) {
    Invoke-Step "Refresh accuracy cache" @(
        $Python,
        "scripts\backtest_recent_forecasts.py",
        "--start-date", "$BacktestStartDate",
        "--end-date", "$EndDate",
        "--refresh"
    )
} else {
    Write-Host "Skipping backtest cache refresh." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Daily refresh complete." -ForegroundColor Green
Write-Host "Restart backend to load newly trained model artifacts:"
Write-Host "cd $ProjectRoot\backend"
Write-Host "..\venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"
