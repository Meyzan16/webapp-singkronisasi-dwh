# CLAUDE.md

## What is this project?

Crypto trading agent with multi-timeframe technical analysis.
Scans Binance Futures (100 USDT pairs), runs 7-signal TA pipeline, generates entry/SL/TP signals
with R:R ≥ 1:3, and records results in paper-trading history to measure win rate per trading style.

## Monorepo structure

```
agents-trading/
├── frontend/        ← Next.js 16 UI
├── backend/         ← FastAPI API server + TA engine
├── agents/          ← Autonomous trading agents (scanner + paper trader + future ML)
├── docker-compose.yml
└── CLAUDE.md
```

## Tech stack

| Layer | Stack |
|-------|-------|
| Frontend | Next.js 16 · TypeScript · Tailwind CSS v4 |
| Backend  | Python 3.12 · FastAPI · SQLAlchemy async · asyncpg |
| Agents   | Python 3.12 · httpx · asyncio · structlog |
| Database | PostgreSQL 16 (TimescaleDB for klines) |
| Cache    | Redis 7 (cache + pub/sub) |
| Data     | Binance Futures REST API |

---

## `frontend/` — Next.js UI

```
frontend/
├── src/
│   ├── app/(content)/       ← Pages: dashboard, scanner, history, architecture
│   ├── features/            ← Feature modules (scanner, history, dashboard, ...)
│   ├── components/ui/       ← Shared UI primitives
│   ├── types/               ← TypeScript types
│   └── lib/                 ← Utilities (format, etc.)
├── package.json
├── next.config.ts
└── tsconfig.json
```

### Frontend conventions
- Feature-based: each feature in `src/features/{name}/` with `components/`, `hooks/`, `data/`
- Pages in `src/app/(content)/{name}/page.tsx`
- Tailwind CSS only — no inline styles, no CSS modules
- Primary color: `primarygreen` (#14b8a6)
- Use existing UI components from `src/components/ui/`
- `useMemo` and `useCallback` to prevent unnecessary re-renders

### Frontend dev
```bash
cd frontend && npm run dev       # start Next.js dev server
cd frontend && npm run lint      # lint check
cd frontend && npm run build     # production build
```

---

## `backend/` — FastAPI API server

```
backend/
├── app/
│   ├── main.py              ← FastAPI entry point + lifespan (starts agents)
│   ├── config.py            ← Settings via pydantic-settings
│   ├── database.py          ← SQLAlchemy async engine + session
│   ├── models/              ← SQLAlchemy ORM models
│   ├── api/v1/              ← Route handlers
│   │   ├── scanner.py       ← GET /scanner/scan (read-only, serves agents cache)
│   │   ├── history.py       ← GET /history/trades, stats, equity
│   │   ├── coin_detail.py   ← GET /coin/{symbol}/analyze (Run Analysis)
│   │   └── ...
│   ├── services/
│   │   ├── ta_engine/       ← T0-T4 TA pipeline (Wyckoff, trend, S/R, pattern, trigger)
│   │   ├── data_pipeline/   ← Binance kline fetcher
│   │   └── trading/         ← Futures position manager
│   └── ws/                  ← WebSocket (positions stream)
├── requirements.txt
├── Dockerfile
└── .env
```

### Backend conventions
- `async def` for ALL route handlers and DB operations
- One file = one responsibility
- Type hints + docstring on every function
- Pydantic BaseModel for ALL request/response schemas
- `structlog` for logging, never `print()`
- Specific exception handling, never bare `except:`

### Backend dev
```bash
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## `agents/` — Autonomous trading agents

```
agents/
├── __init__.py
├── main.py                  ← Entry point: python -m agents (standalone mode)
├── requirements.txt         ← Independent deps (can add ML libs here)
├── scanner/
│   ├── __init__.py
│   ├── scheduler.py         ← Scanner scheduler loop (15 min cycles, all 4 styles)
│   └── store.py             ← In-memory cache for last scan results
├── paper_trader/
│   ├── __init__.py
│   └── trader.py            ← Paper trade logging + TP/SL monitoring
└── learning/                ← Future: ML strategy optimizer
    └── __init__.py
```

### Agent rules
- **Scanner agent** is the ONLY source that scans + logs to paper_trades
- Scanner API is read-only — serves `agents/scanner/store.py` cache
- R:R ≥ 1:3 enforced at both scanner level and paper_trader level
- Dedup (spot): one open trade per coin+style. Dedup (futures, P2+): GLOBAL — one open trade per coin across ALL lanes (agent1/2/3 share one cross-margin wallet, so a symbol nets to one position)
- No cooldown — free re-entry after trade closes (TP/SL)

### Agent modes
```bash
# Mode 1: embedded in backend (current default)
# Agents start automatically when backend starts (via FastAPI lifespan)

# Mode 2: standalone (future — uncomment in docker-compose.yml)
cd backend && python -m agents
```

### Future learning agents (add to `agents/learning/`)
- `strategy_optimizer.py` — tune StyleConfig weights based on historical win rate
- `signal_scorer.py`       — ML model to score signal quality before logging
- `threshold_tuner.py`     — auto-adjust min_score, min_rr per market regime
- `backtester.py`          — replay historical data to validate TA engine changes

---

## Data flow

```
Binance Futures API
  │
  ▼  every 15 min (agents/scanner/scheduler.py)
Scanner Engine (backend/app/api/v1/scanner.py :: scan_market_core)
  │
  ├── agents/scanner/store.py  ← cache for Scanner API (read-only)
  │
  └── paper_trades (PostgreSQL) ← agents/paper_trader/trader.py

Scanner API  → serves store cache → frontend/scanner page
History API  → reads paper_trades → frontend/history page (win rate)
```

---

## How to start locally

```bash
# 1. Start infrastructure
docker compose up postgres redis -d

# 2. Start backend (includes agents in embedded mode)
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Start frontend
cd frontend
npm run dev
```

---

## Workflow

1. **Frontend work**: edit `frontend/src/` — pages, features, components
2. **Backend API work**: edit `backend/app/api/v1/` — add/change endpoints
3. **Agent work**: edit `agents/` — scanner logic, paper trader rules, add new agents
4. **TA engine work**: edit `backend/app/services/ta_engine/` — T0-T4 analysis
5. Commit with Conventional Commits: `feat:`, `fix:`, `refactor:`, `chore:`

---

## What NOT to do

- Do NOT log paper trades from the scanner API — only agents/scanner/scheduler.py logs
- Do NOT add new npm packages without asking
- Do NOT modify `frontend/src/app/(auth)/` — sign-in stays as-is
- Do NOT use class components in React — functional only
- Do NOT store API keys in code — use .env
- Do NOT mix agent logic into backend API routes
