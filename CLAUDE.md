# CLAUDE.md

## What is this project?

Crypto trading agent with multi-timeframe technical analysis. The system scans Binance for 5 L1 pairs (BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, SUI/USDT), runs a top-down TA pipeline, and generates entry/exit signals with stop loss.

**Read the full architecture before writing any code:** @docs/ARCHITECTURE.md
**Follow the build order strictly:** @docs/BUILD_ORDER.md

## Tech stack

- **Backend**: Python 3.12+ / FastAPI / CCXT / TA-Lib / pandas / PostgreSQL / Redis
- **Frontend**: Next.js 16 / TypeScript / Tailwind CSS v4 / Poppins font
- **Database**: PostgreSQL (TimescaleDB for klines), Redis (cache + pub/sub)
- **Infra**: Docker Compose for local dev

## Repository structure

```
/
├── CLAUDE.md              # You are reading this
├── docs/                  # Architecture specs (IMPORTANT — read first)
│   ├── ARCHITECTURE.md    # Full trading agent architecture
│   └── BUILD_ORDER.md     # Step-by-step implementation plan
├── backend/               # Python FastAPI (NEW — create this)
│   ├── app/
│   │   ├── main.py        # FastAPI entry point
│   │   ├── config.py      # Settings, env vars
│   │   ├── database.py    # DB connection
│   │   ├── models/        # SQLAlchemy models
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # Business logic
│   │   │   ├── data_pipeline/    # L1-L2: Binance data fetching
│   │   │   ├── ta_engine/        # T0-T4: Technical analysis
│   │   │   ├── signal_generator/ # L5-L6: Risk + signal output
│   │   │   └── scanner/          # Volume scanner
│   │   ├── api/           # Route handlers
│   │   │   └── v1/
│   │   └── ws/            # WebSocket handlers
│   ├── tests/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── src/                   # Next.js frontend (EXISTING — do NOT restructure)
│   ├── app/
│   │   ├── (auth)/        # Sign-in (KEEP)
│   │   └── (content)/     # Dashboard pages
│   │       ├── scanner/   # Scanner page
│   │       ├── signals/   # Signal feed page (NEW)
│   │       ├── charts/    # Charts page (NEW)
│   │       ├── backtest/  # Backtest page (NEW)
│   │       └── settings/  # Settings page (NEW)
│   ├── components/        # Shared UI components
│   ├── features/          # Feature-based modules
│   │   ├── auth/
│   │   ├── scanner/
│   │   ├── signals/
│   │   ├── charts/
│   │   └── settings/
│   ├── types/             # TypeScript type definitions
│   └── hooks/             # Shared hooks
├── docker-compose.yml
└── package.json
```

## Conventions — IMPORTANT

### Backend (Python)
- Use `async def` for all route handlers and DB operations
- One service file = one responsibility. Never mix data fetching with TA calculation
- Every service function must have type hints and docstring
- Use Pydantic BaseModel for ALL request/response schemas
- Environment variables via `pydantic-settings`, never hardcode
- Naming: `snake_case` for files, functions, variables. `PascalCase` for classes
- Error handling: always catch specific exceptions, never bare `except`
- Logging: use `structlog`, not `print()`

### Frontend (Next.js)
- KEEP the existing folder structure. Do NOT move or rename existing folders
- Feature-based architecture: each feature has `components/`, `hooks/`, `data/`, inside `src/features/{name}/`
- Types in `src/types/{name}.ts`
- Pages in `src/app/(content)/{name}/page.tsx`
- Components are presentational (receive props) — logic stays in hooks or page level
- Use `useMemo` and `useCallback` to prevent unnecessary re-renders
- Tailwind CSS only — no inline styles, no CSS modules
- Primary color: `primarygreen` (#14b8a6). Follow existing color scheme exactly
- Use existing UI components from `src/components/ui/` (Button, Badge, Card, etc.)

### What NOT to do
- Do NOT create API endpoints without corresponding Pydantic schemas
- Do NOT add new npm packages without asking
- Do NOT modify `src/app/(auth)/` — sign-in stays as-is
- Do NOT use class components — functional only
- Do NOT store API keys in code — use .env
- Do NOT build features out of order — follow @docs/BUILD_ORDER.md

## Workflow

1. Read `@docs/BUILD_ORDER.md` to know what step we're on
2. Create a feature branch: `feat/{step-name}`
3. Write code following the structure above
4. Run backend tests: `cd backend && pytest`
5. Run frontend lint: `npm run lint`
6. Commit with Conventional Commits: `feat:`, `fix:`, `refactor:`

## Current status

**Step 1 complete**: Data pipeline backend implemented and committed in `1a42c7a feat: add data pipeline backend`.

Do not rebuild Step 1 unless explicitly asked. Continue with **Step 2: TA engine - T1 Trend**.

Step 1 verification:
- Backend tests pass: `cd backend && .\.venv\Scripts\python.exe -m pytest` returned `3 passed`.
- `docker compose config` is valid.
- `npm run lint` still fails on pre-existing frontend/docs lint errors outside Step 1.

Step 1 runtime note:
- REST endpoint and poller are implemented, but full live acceptance still requires running PostgreSQL/Docker and Binance network access:
  `GET /api/v1/klines/BTCUSDT/1d`.

## The 5 trading pairs

| Pair | Why |
|------|-----|
| BTC/USDT | Benchmark, most liquid, cleanest TA |
| ETH/USDT | DeFi leader, textbook patterns |
| SOL/USDT | High volatility, volume spikes |
| BNB/USDT | Exchange coin, news-driven |
| SUI/USDT | New L1, momentum play |

## The 5 timeframes

| TF | Role in architecture |
|----|---------------------|
| 1W | T0 Wyckoff + T1 Trend (direction) |
| 1D | T0 Wyckoff + T1 Trend (confirm) |
| 4H | T2 Area analysis (S/R zones) |
| 1H | T3 Pattern + T4 Trigger |
| 15m | T4 Trigger (execution timing) |
