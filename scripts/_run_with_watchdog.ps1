# Orchestrates scripts/run_phase1_benchmark_full.py as two SEPARATE processes
# (one per dataset) plus a merge step, with a real memory watchdog.
#
# Why two processes, not one: running both datasets in a single process lets
# CICIDS2017's ~1.9GB resident footprint stack with UNSW-NB15's load,
# tripping the script's own 3GB free-memory floor (measured, not assumed --
# see docs/ML_BENCHMARK_REPORT.md's Phase 1 section for the real numbers).
# Separate processes let the OS fully reclaim memory between datasets.
#
# Why success is checked via the output file, not $proc.ExitCode: PowerShell
# 5.1's Process.ExitCode is unreliable immediately after HasExited flips true
# on this machine (observed twice in the same session -- a process that had
# genuinely written its output file and exited 0 still read back as exit="").
# Checking for the real partial_<dataset>.json file plus an empty stderr log
# is the actual evidence of success, not a timing-sensitive property read.
#
# Usage: powershell -ExecutionPolicy Bypass -File scripts\_run_with_watchdog.ps1
# Status: $env:TEMP\phase1_full.status (RUNNING / COMPLETED / FAILED .../ ABORTED_LOW_MEMORY ...)
# Per-dataset logs: $env:TEMP\phase1_full_<dataset>.log / .err.log

$ErrorActionPreference = "Stop"
Set-Location "C:\Users\gmalh\sentinelmesh"
$statusFile = "$env:TEMP\phase1_full.status"
"RUNNING" | Out-File -Encoding ascii $statusFile

$runId = [datetime]::UtcNow.ToString("yyyyMMddTHHmmssZ") + "-manual"
$minFreeMB = 1500

function Run-OneDataset($dataset) {
    $log = "$env:TEMP\phase1_full_$dataset.log"
    $errLog = "$env:TEMP\phase1_full_$dataset.err.log"
    Remove-Item $log, $errLog -ErrorAction SilentlyContinue
    $outFile = "eval\reports\$runId\partial_$dataset.json"
    $proc = Start-Process -FilePath ".venv\Scripts\python.exe" `
        -ArgumentList "scripts\run_phase1_benchmark_full.py","--dataset",$dataset,"--run-id",$runId `
        -RedirectStandardOutput $log -RedirectStandardError $errLog -NoNewWindow -PassThru
    $proc.Id | Out-File -Encoding ascii "$env:TEMP\phase1_full_$dataset.pid"
    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 5
        $os = Get-CimInstance Win32_OperatingSystem
        $freeMB = $os.FreePhysicalMemory / 1024
        if ($freeMB -lt $minFreeMB) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            "ABORTED_LOW_MEMORY during $dataset free=$([math]::Round($freeMB,1))MB" | Out-File -Encoding ascii $statusFile
            exit 1
        }
    }
    Start-Sleep -Seconds 1  # let the filesystem settle before checking
    $errContent = Get-Content $errLog -Raw -ErrorAction SilentlyContinue
    $ok = (Test-Path $outFile) -and ([string]::IsNullOrWhiteSpace($errContent))
    return $ok
}

if (-not (Run-OneDataset "cicids2017")) {
    "FAILED cicids2017 -- see $env:TEMP\phase1_full_cicids2017.err.log" | Out-File -Encoding ascii $statusFile
    exit 1
}

if (-not (Run-OneDataset "unsw_nb15")) {
    "FAILED unsw_nb15 -- see $env:TEMP\phase1_full_unsw_nb15.err.log" | Out-File -Encoding ascii $statusFile
    exit 1
}

$mergeLog = "$env:TEMP\phase1_full_merge.log"
& ".venv\Scripts\python.exe" "scripts\run_phase1_benchmark_full.py" --dataset merge --run-id $runId 2>&1 |
    Out-File -Encoding utf8 $mergeLog
if (Test-Path "eval\reports\$runId\report.json") {
    "COMPLETED run_id=$runId" | Out-File -Encoding ascii $statusFile
} else {
    "FAILED merge -- see $mergeLog" | Out-File -Encoding ascii $statusFile
}
