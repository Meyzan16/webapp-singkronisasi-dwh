# agents-trading

Crypto trading agent — multi-timeframe TA pipeline, Binance Futures scanner,
paper trading history with win-rate tracking.

## Architecture

```
postgres  redis  ←── infrastructure
backend         ←── FastAPI API + WebSocket (port 8000)
agents          ←── Scanner + Monitor loops (health port 8001)
frontend        ←── Next.js UI (port 3000)
```

## Running with Docker (production)

```bash
# 1. Build all images
docker compose build --no-cache backend agents frontend

# 2. Start everything
docker compose up -d

# 3. Check status
docker compose ps

# 4. View logs
docker compose logs -f backend agents
docker compose logs -f frontend
```

## Running with Docker (development — hot reload)

```bash
# Mounts source code as volumes — edits take effect without rebuild
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Changes to `backend/app/` and `agents/` reload automatically.
Frontend uses `npm run dev` with HMR.

## Running locally (without Docker)

```bash
# 1. Start infrastructure
docker compose up postgres redis -d

# 2. Backend (includes embedded agents)
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Frontend
cd frontend
npm run dev
```

## Endpoints

| Service  | URL                        |
|----------|----------------------------|
| Frontend | http://localhost:3000       |
| Backend  | http://localhost:8000       |
| Health   | http://localhost:8000/health |
| Agents health | http://localhost:8001/health |

## Optional: ELK logging overlay

```bash
docker compose -f docker-compose.yml -f docker-compose.logging.yml up -d
```

Starts Elasticsearch + Kibana + Filebeat. Kibana at http://localhost:5601.
