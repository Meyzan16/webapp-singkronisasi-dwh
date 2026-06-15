# Dev Runner — agents-trading

Quick reference to run the full stack locally.

---

## TL;DR (One-command start)

```powershell
# Windows PowerShell
.\run.ps1

# Bash / WSL / Git Bash
./run.sh
```

---

## Scripts

| Script | Platform | Description |
|--------|----------|-------------|
| `run.ps1` | Windows PowerShell | Full stack runner with colored output |
| `run.sh`  | Bash / WSL / Git Bash | Same, for Unix-like shells |

### Commands

```powershell
.\run.ps1 all        # Start everything (default)
.\run.ps1 infra      # Postgres + Redis only
.\run.ps1 backend    # Infra + FastAPI backend
.\run.ps1 frontend   # Next.js frontend only
.\run.ps1 stop       # Stop all services
.\run.ps1 logs       # Tail backend logs
.\run.ps1 status     # Show what's running
```

---

## Manual Step-by-Step

### 1. Infrastructure (Docker)

```powershell
docker compose up postgres redis -d
```

Postgres: `localhost:5432` · Redis: `localhost:6379`

### 2. Backend (FastAPI)

```powershell
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

- API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs
- Logs: `backend/uvicorn_stdout.log` / `uvicorn_stderr.log`

### 3. Frontend (Next.js)

```powershell
cd frontend
npm run dev
```

- App: http://localhost:3000

---

## First-time Setup

```powershell
# 1. Install Python deps
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. Install Node deps
cd frontend
npm install

# 3. Copy env (already exists in repo)
# backend/.env — edit BINANCE_API_KEY etc.
```

---

## Ports

| Service  | Port  |
|----------|-------|
| Frontend | 3000  |
| Backend  | 8000  |
| Postgres | 5432  |
| Redis    | 6379  |

---

## Useful Commands

```powershell
# Check backend health
curl http://localhost:8000/health

# View backend logs live
.\run.ps1 logs

# Stop everything
.\run.ps1 stop

# Rebuild Docker containers
docker compose up --build postgres redis -d
```
