# ============================================================
#  agents-trading — Windows PowerShell Runner
#  Usage: .\run.ps1 [command]
#
#  Commands:
#    all       Start infra + backend + frontend (default)
#    infra     Start postgres + redis only
#    backend   Start backend only
#    frontend  Start frontend only
#    stop      Stop all docker containers
#    logs      Tail backend logs
#    status    Show running services
# ============================================================

param(
    [string]$Command = "all"
)

$Root     = $PSScriptRoot
$Backend  = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Python   = Join-Path $Backend ".venv\Scripts\python.exe"

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host ""
}

function Start-Infra {
    Write-Header "Starting Infrastructure (Postgres + Redis)"
    Set-Location $Root
    docker compose up postgres redis -d
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Docker failed. Is Docker Desktop running?" -ForegroundColor Red
        exit 1
    }
    Write-Host "[OK] Infra started" -ForegroundColor Green

    # Wait for postgres to be healthy
    Write-Host "Waiting for Postgres to be ready..."
    $retries = 0
    do {
        Start-Sleep -Seconds 2
        $health = docker inspect --format='{{.State.Health.Status}}' (docker compose ps -q postgres) 2>$null
        $retries++
    } while ($health -ne "healthy" -and $retries -lt 15)

    if ($health -eq "healthy") {
        Write-Host "[OK] Postgres healthy" -ForegroundColor Green
    } else {
        Write-Host "[WARN] Postgres may not be ready yet, proceeding anyway..." -ForegroundColor Yellow
    }
}

function Start-Backend {
    Write-Header "Starting Backend (FastAPI :8000)"
    if (-not (Test-Path $Python)) {
        Write-Host "[ERROR] Python venv not found at $Python" -ForegroundColor Red
        Write-Host "  Run: cd backend && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt" -ForegroundColor Yellow
        exit 1
    }
    Set-Location $Backend
    Start-Process -NoNewWindow -FilePath $Python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload" `
        -RedirectStandardOutput "uvicorn_stdout.log" `
        -RedirectStandardError  "uvicorn_stderr.log"
    Write-Host "[OK] Backend started — logs: backend/uvicorn_stdout.log" -ForegroundColor Green
    Write-Host "     API docs: http://localhost:8000/docs" -ForegroundColor DarkCyan
    Start-Sleep -Seconds 3
}

function Start-Frontend {
    Write-Header "Starting Frontend (Next.js :3000)"
    if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
        Write-Host "node_modules not found, running npm install..." -ForegroundColor Yellow
        Set-Location $Frontend
        npm install
    }
    Set-Location $Frontend
    Start-Process -NoNewWindow -FilePath "npm" -ArgumentList "run", "dev"
    Write-Host "[OK] Frontend started" -ForegroundColor Green
    Write-Host "     App: http://localhost:3000" -ForegroundColor DarkCyan
}

function Stop-All {
    Write-Header "Stopping all services"
    Set-Location $Root
    docker compose down
    # Kill uvicorn and node processes
    Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -match "uvicorn" -or $_.CommandLine -match "uvicorn" } | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name "node"   -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] All services stopped" -ForegroundColor Green
}

function Show-Status {
    Write-Header "Service Status"
    Write-Host "Docker containers:"
    docker compose ps
    Write-Host ""
    Write-Host "Backend (port 8000):" -ForegroundColor Cyan
    $be = netstat -ano | Select-String ":8000"
    if ($be) { Write-Host "  [RUNNING]" -ForegroundColor Green } else { Write-Host "  [STOPPED]" -ForegroundColor Red }
    Write-Host "Frontend (port 3000):" -ForegroundColor Cyan
    $fe = netstat -ano | Select-String ":3000"
    if ($fe) { Write-Host "  [RUNNING]" -ForegroundColor Green } else { Write-Host "  [STOPPED]" -ForegroundColor Red }
}

function Show-Logs {
    Write-Header "Backend Logs (Ctrl+C to stop)"
    $logFile = Join-Path $Backend "uvicorn_stdout.log"
    if (Test-Path $logFile) {
        Get-Content $logFile -Wait
    } else {
        Write-Host "[ERROR] Log file not found: $logFile" -ForegroundColor Red
    }
}

# ── Main ──────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  agents-trading runner" -ForegroundColor Cyan
Write-Host "  command: $Command" -ForegroundColor DarkGray
Write-Host ""

switch ($Command.ToLower()) {
    "all" {
        Start-Infra
        Start-Backend
        Start-Frontend
        Write-Header "All services started!"
        Write-Host "  Frontend  → http://localhost:3000" -ForegroundColor Green
        Write-Host "  Backend   → http://localhost:8000" -ForegroundColor Green
        Write-Host "  API Docs  → http://localhost:8000/docs" -ForegroundColor Green
        Write-Host "  Postgres  → localhost:5432" -ForegroundColor Green
        Write-Host "  Redis     → localhost:6379" -ForegroundColor Green
        Write-Host ""
        Write-Host "  Logs: backend\uvicorn_stdout.log" -ForegroundColor DarkGray
        Write-Host "  Stop: .\run.ps1 stop" -ForegroundColor DarkGray
        Write-Host ""
    }
    "infra"    { Start-Infra }
    "backend"  { Start-Infra; Start-Backend }
    "frontend" { Start-Frontend }
    "stop"     { Stop-All }
    "logs"     { Show-Logs }
    "status"   { Show-Status }
    default {
        Write-Host "Unknown command: $Command" -ForegroundColor Red
        Write-Host "Usage: .\run.ps1 [all|infra|backend|frontend|stop|logs|status]"
    }
}
