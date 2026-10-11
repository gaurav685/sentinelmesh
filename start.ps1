# One-command SentinelMesh startup: docker stack + demo seed + frontend + browser.
# Run via start.bat (double-click), or directly:
#   powershell -ExecutionPolicy Bypass -File start.ps1

Set-Location $PSScriptRoot

Write-Host "== SentinelMesh startup ==" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Write-Host "No .env found. Copy .env.example to .env and set the required values first." -ForegroundColor Red
    exit 1
}

# Load .env into this process so docker compose's variable interpolation
# (${SM_PG_PASSWORD:?...} etc.) resolves without needing a manual `export`.
Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    if ($line -match "^([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
        [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
    }
}

try {
    docker info *> $null
} catch {
    Write-Host "Docker doesn't seem to be running. Start Docker Desktop first." -ForegroundColor Red
    exit 1
}

Write-Host "Starting the stack (build on first run takes a few minutes)..." -ForegroundColor Cyan
docker compose -f deploy/docker/docker-compose.yml `
    --profile bus --profile graph --profile detect --profile oidc --profile obs --profile objects `
    up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host "docker compose failed -- see the error above." -ForegroundColor Red
    exit 1
}

Write-Host "Waiting for services to report healthy..." -ForegroundColor Cyan
$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 5
    $unhealthy = docker ps --filter "name=sentinelmesh-" --format "{{.Names}}\t{{.Status}}" |
        Select-String -Pattern "starting|unhealthy"
} while ($unhealthy -and (Get-Date) -lt $deadline)

Write-Host "Seeding the demo tenant / admin / sensor..." -ForegroundColor Cyan
& ".venv\Scripts\python.exe" "scripts\seed_demo.py"

Write-Host "Starting the frontend dev server (its own window -- closing that window stops it)..." -ForegroundColor Cyan
Start-Process cmd -ArgumentList "/k", "cd frontend\web && npm run dev" -WindowStyle Normal

# A fixed sleep here raced Next.js's real cold-compile time (commonly well
# over 8s) and opened the browser before anything was actually listening on
# :3000 -- Firefox would show "Unable to connect", repeatably, on every
# fresh start. Poll the port itself instead of guessing a duration.
Write-Host "Waiting for the frontend to start listening on :3000..." -ForegroundColor Cyan
$frontendDeadline = (Get-Date).AddMinutes(2)
$frontendUp = $false
do {
    Start-Sleep -Seconds 1
    $frontendUp = (Test-NetConnection -ComputerName "localhost" -Port 3000 -WarningAction SilentlyContinue -InformationLevel Quiet)
} while (-not $frontendUp -and (Get-Date) -lt $frontendDeadline)

if (-not $frontendUp) {
    Write-Host "Frontend didn't come up within 2 minutes -- check the npm run dev window for errors." -ForegroundColor Red
}
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "Done. http://localhost:3000" -ForegroundColor Green
Write-Host "Login -- tenant: demo-corp   email: demo-admin@sentinelmesh.demo   password: demo-password-change-me"
Write-Host "Run stop.bat (or stop.ps1) to shut everything down."
