# Shuts down the SentinelMesh docker stack (frontend dev window is separate --
# close that window, or Ctrl+C in it, to stop the frontend).

Set-Location $PSScriptRoot

Get-Content ".env" | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    if ($line -match "^([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
        [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
    }
}

Write-Host "Stopping the SentinelMesh stack..." -ForegroundColor Cyan
docker compose -f deploy/docker/docker-compose.yml `
    --profile bus --profile graph --profile detect --profile oidc --profile obs --profile objects `
    down
Write-Host "Done." -ForegroundColor Green
