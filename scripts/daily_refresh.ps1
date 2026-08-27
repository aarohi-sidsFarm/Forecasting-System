param(
    [int]$TrainingQueryId = 3269,
    [string]$StartDate = "",
    [string]$EndDate = "",
    [int]$OverlapDays = 7,
    [double]$MaximumOverlapWape = 30,
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

$TrainingExport = Join-Path $ProjectRoot "data\raw\redash_exports\procurement_final_total_training.csv"
$LatestTrainingDate = $null
if ([string]::IsNullOrWhiteSpace($StartDate)) {
    if (Test-Path $TrainingExport) {
        $latestRow = Import-Csv $TrainingExport |
            Sort-Object { [datetime]::ParseExact($_.target_date, "yyyy-MM-dd", $null) } -Descending |
            Select-Object -First 1
        if ($latestRow) {
            $LatestTrainingDate = [datetime]::ParseExact($latestRow.target_date, "yyyy-MM-dd", $null)
            $StartDate = $LatestTrainingDate.AddDays(-1 * ([math]::Max(1, $OverlapDays) - 1)).ToString("yyyy-MM-dd")
        }
    }
    if ([string]::IsNullOrWhiteSpace($StartDate)) {
        $StartDate = "2025-05-01"
        Write-Host "No existing training export found; using full bootstrap window." -ForegroundColor Yellow
    }
}

if ([datetime]::ParseExact($StartDate, "yyyy-MM-dd", $null) -gt [datetime]::ParseExact($EndDate, "yyyy-MM-dd", $null)) {
    $StartDate = $EndDate
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
if ($LatestTrainingDate) {
    Write-Host "Latest stored date : $($LatestTrainingDate.ToString('yyyy-MM-dd'))"
}
Write-Host "Incremental window : $StartDate -> $EndDate"
Write-Host "Backtest window    : $BacktestStartDate -> $EndDate"

if (-not $SkipTraining) {
    Invoke-Step "Fetch Redash training export" @(
        $Python,
        "scripts\fetch_redash_training_export.py",
        "--query-id", "$TrainingQueryId",
        "--start-date", "$StartDate",
        "--end-date", "$EndDate",
        "--append",
        "--maximum-overlap-wape", "$MaximumOverlapWape"
    )

    Invoke-Step "Process raw training data" @($Python, "ml_pipeline\process_all_data.py")
    Invoke-Step "Fill zero-demand gaps" @($Python, "ml_pipeline\fill_gaps.py")
    Invoke-Step "Build features" @($Python, "ml_pipeline\build_features.py")
    Invoke-Step "Train general model" @($Python, "ml_pipeline\train_general_lgbm.py")
    Invoke-Step "Train HYD model" @($Python, "ml_pipeline\train_hyd_lgbm.py")
    Invoke-Step "Train cutoff-safe HYD D-2 model" @(
        $Python,
        "ml_pipeline\train_city_direct.py",
        "--city", "HYD",
        "--lead-days", "2",
        "--holdout-days", "90"
    )
    Invoke-Step "Train cutoff-safe BLR D-3 model" @(
        $Python,
        "ml_pipeline\train_city_direct.py",
        "--city", "BLR",
        "--lead-days", "3",
        "--holdout-days", "90"
    )
} else {
    Write-Host "Skipping training stages." -ForegroundColor Yellow
}

if (-not $SkipBacktest) {
    Invoke-Step "Reconcile completed Query 1968 actuals" @(
        $Python,
        "scripts\reconcile_forecast_actuals.py",
        "--start", "$BacktestStartDate",
        "--end", "$EndDate"
    )

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
