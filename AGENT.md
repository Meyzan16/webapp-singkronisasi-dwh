# AGENT.md

> Panduan kerja saya (GitHub Copilot CLI) untuk repo **agents-trading**.
> File ini adalah *mental model* saya terhadap project — dibaca setiap kali
> mulai sesi supaya tidak salah lane, salah file, atau salah asumsi.

---

## 1. Apa project ini sebenarnya?

Sistem **paper-trading crypto** end-to-end dengan 2 pasar (Spot + Futures Binance),
pipeline TA multi-timeframe (T0–T4 + trigger), agen otonom yang scan tiap 15 menit,
monitor TP/SL, dan lapisan learning (weight updater + walk-forward backtest) yang
otomatis mengukur & mengkalibrasi win-rate per gaya trading.

Tujuan akhirnya: signal engine yang bisa **self-improve** berbasis histori paper trade
sebelum eventually dipromosikan ke live trading (`PLAN-LIVE-TRADING.md`).

---

## 2. Peta repo (state sekarang, bukan CLAUDE.md lama)

```
agents-trading/
├── frontend/                    ← Next.js 16 UI (React 19, Tailwind v4)
├── backend/                     ← FastAPI + TA engine + WS streams
│   └── app/
│       ├── main.py              ← lifespan: DB + embedded agents (kecuali AGENTS_STANDALONE=true)
│       ├── api/v1/              ← 20+ router
│       ├── models/              ← SQLAlchemy async ORM
│       ├── services/
│       │   ├── ta_engine/       ← wyckoff, ema, trend, S/R, candlestick, pattern, trigger, order_flow, stochastic, trendline
│       │   ├── signal_generator/← pipeline, risk_calculator, signal_card
│       │   ├── paper_trader/    ← eksekusi & PnL paper
│       │   ├── scheduler/       ← scan_store + scanner_scheduler helper
│       │   └── (agent_config_defaults, big_mover_logger, binance_auth/urls,
│       │        force_open_limiter, health_logger, rate_limit_tracker,
│       │        signal_catalog, slippage_sim, trading_costs)
│       └── ws/                  ← opportunity_stream, futures_stream, big_mover_alerts
├── agents/                      ← Standalone-capable async agents
│   ├── main.py                  ← entry `python -m agents` + health server :8001
│   ├── opportunity/             ← SPOT lane (scanner + monitor + analyzer + learning)
│   ├── futures/                 ← FUTURES lane
│   │   ├── agent1.py / agent2.py / agent3.py / agent_bigmover.py
│   │   ├── scheduler.py / monitor.py / auto_trader.py
│   │   ├── weight_updater.py / learning_policy.py / learning_loader.py
│   │   ├── decision_ledger.py / outcome_tracker.py / regime.py / risk_gate.py
│   │   ├── delisting_monitor.py / ws_big_mover_feed.py
│   │   └── data.py / exchange_info.py / store.py / utils.py
│   ├── learning/                ← walk-forward + calibration + backtest jobs
│   │   ├── futures_adaptive_model.py / futures_walkforward.py
│   │   ├── spot_adaptive_model.py    / spot_walkforward.py
│   │   ├── spot_portfolio_replay.py  / monthly_calibration.py
│   │   ├── weekly_backtest.py        / weekly_signal_review.py
│   └── shared/                  ← cross_agent_learning, config_reader
├── docker-compose.yml           ← postgres, redis, backend, agents, frontend
├── docker-compose.dev.yml       ← overlay hot-reload
├── CLAUDE.md                    ← dokumen awal (agak outdated dibanding realita)
├── PLAN-LIVE-TRADING.md
├── PLAN_ADAPTIVE_LEARNING_FUTURES_10X.md
├── PLAN_ADAPTIVE_SIGNAL_WEIGHTING_SPOT_10X.md
├── SCHEDULE_FUTURES.md
└── README.md
```

---

## 3. Tech stack (fakta, bukan wishlist)

| Layer     | Stack                                                      |
|-----------|------------------------------------------------------------|
| Frontend  | Next.js **16.1.6** · React 19.2 · TypeScript 5 · Tailwind v4 · lightweight-charts · lucide-react |
| Backend   | Python 3.12 · FastAPI · SQLAlchemy async · asyncpg · httpx · ccxt · structlog · pydantic v2 |
| Agents    | Python 3.12 · httpx · asyncio · structlog · sqlalchemy async |
| DB        | PostgreSQL 16 (asyncpg driver, DATABASE_URL = `postgresql+asyncpg://…`) |
| Cache     | Redis 7                                                     |
| Data      | Binance Spot + Futures REST + WebSocket                    |

---

## 4. Data flow (yang benar)

```
Binance Spot API                     Binance Futures API + WS
       │                                       │
       ▼ 15-min loop                           ▼ 15-min loop + 60s fastpass + WS realtime
agents/opportunity/scheduler.py        agents/futures/scheduler.py
       │                                       │  ├── agent1 / agent2 / agent3 / bigmover
       │                                       │  ├── ws_big_mover_feed (BM4/G21)
       │                                       │  └── delisting_monitor (G17, 6h)
       ▼                                       ▼
agents/*/store.py (in-memory cache)     agents/futures/decision_ledger + outcome_tracker
       │                                       │
       ├── FastAPI /api/v1/opportunity ─┐      ├── FastAPI /api/v1/futures_* ─┐
       └── paper_trades (Postgres)      │      └── paper_trades (Postgres)     │
                                        ▼                                     ▼
                              agents/*/monitor.py (TP/SL close)      agents/futures/weight_updater
                                        │                                     │
                                        ▼                                     ▼
                              paper_balance, balance_transaction     agents/learning/* (weekly backtest, walk-forward, monthly calibration)
                                        │
                                        ▼
                              frontend: history, scanner, futures-market, spot-market,
                                        signals, backtest, dashboards, system-health,
                                        opportunity, architecture, charts, settings
```

WebSocket ke frontend:
- `ws://…/ws/opportunity` – live spot signals
- `ws://…/ws/futures`     – live futures signals
- `ws://…/ws/big-movers`  – big mover alerts

---

## 5. Mode deployment

Dua mode, dikontrol env `AGENTS_STANDALONE`:

1. **Embedded** (`AGENTS_STANDALONE=false`, default lokal)
   - `backend/app/main.py` lifespan spawn 7 task:
     `run_opportunity_loop`, `run_opportunity_monitor`,
     `run_futures_loop`, `run_futures_monitor`,
     `run_bigmover_fastpass`, `run_ws_big_mover_feed`, `run_delisting_monitor`.
2. **Standalone** (`AGENTS_STANDALONE=true`, docker-compose default)
   - Backend hanya API. Container `agents` jalan `python -m agents` dengan
     health server FastAPI di **port 8001**.
   - `/health` di backend akan HTTP-poll `AGENTS_HEALTH_URL` (default `http://agents:8001`).

---

## 6. Konvensi kode (WAJIB diikuti saat edit)

### Backend / Agents (Python 3.12)
- Semua route & DB op **async**. Tidak boleh sync call blocking di dalam handler.
- Satu file = satu tanggung jawab.
- Type hints + docstring di setiap fungsi publik.
- **Pydantic v2 `BaseModel`** untuk semua request/response schema.
- Logging: `structlog.get_logger(__name__)` — **JANGAN `print()`**.
- Exception handling spesifik — **jangan `except:` telanjang**.
- Import agents dari backend memakai `sys.path` shim yang sudah ada di `main.py`.
- Setiap agent baru harus expose `get_state() -> dict` supaya kelihatan di `/health`.

### Frontend (Next.js 16 App Router)
- Feature-based: `src/features/{name}/{components,hooks,data}`.
- Page hanya di `src/app/(content)/{name}/page.tsx` (auth di `(auth)/`, jangan disentuh).
- Tailwind saja — no inline style, no CSS module. Primary color `primarygreen` (#14b8a6).
- Komponen fungsional saja, no class components.
- Reuse `src/components/ui/`. `useMemo`/`useCallback` untuk hindari re-render.
- Jangan tambah dependency npm tanpa nanya user dulu.

### Git
- Conventional Commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `perf:`.
- Trailer `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` (auto).

---

## 7. Aturan agent (jangan langgar)

- **Scanner agent adalah SATU-SATUNYA** yang boleh insert ke `paper_trades`.
  Endpoint `/api/v1/scanner/*` **read-only** — cuma serve cache dari
  `agents/opportunity/store.py` atau `agents/futures/store.py`.
- **R:R ≥ 1:3** dienforce di scanner dan sekali lagi di paper_trader.
- **Dedup**:
  - Spot: 1 open trade per `(coin, style)`.
  - Futures (P2+): **GLOBAL** — 1 open trade per coin lintas lane
    (agent1/2/3/bigmover share 1 cross-margin wallet, jadi 1 posisi net per symbol).
- **No cooldown** — bebas re-entry setelah trade close (TP/SL).
- **Delisting monitor** memblokir signal untuk simbol berisiko delist.
- **Force-open limiter** membatasi seberapa sering paper_trader boleh menembak
  paksa signal marginal.

---

## 8. Larangan keras

- ❌ Jangan log paper trade dari router API — hanya dari `agents/*/scheduler.py`.
- ❌ Jangan modif `frontend/src/app/(auth)/`.
- ❌ Jangan taruh secret di source — pakai `backend/.env`.
- ❌ Jangan campur logic agent ke dalam router API.
- ❌ Jangan pakai class component React.
- ❌ Jangan tambah npm/pip package tanpa konfirmasi.
- ❌ Jangan `print()` — pakai `structlog`.
- ❌ Jangan sentuh model DB tanpa migrasi manual (proyek pakai `create_db_schema()` idempotent, jadi kolom baru = tambah di ORM saja, tapi rename/drop harus dibahas dulu).

---

## 9. Perintah cepat

### Lokal (rekomendasi saat coding)
```bash
# Infra
docker compose up postgres redis -d

# Backend + embedded agents (Windows path)
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend
cd frontend
npm run dev
```

### Docker (mirroring production)
```bash
docker compose build --no-cache backend agents frontend
docker compose up -d
docker compose logs -f backend agents
```

### Docker dev (hot reload)
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

### Standalone agents saja
```bash
cd backend && python -m agents         # health :8001
```

### Verifikasi
```bash
curl http://localhost:8000/health      # DB + semua agent state
curl http://localhost:8001/health      # kalau standalone
```

---

## 10. Endpoint utama (v1)

| Router file                    | Fungsi singkat                                   |
|--------------------------------|--------------------------------------------------|
| `market.py`, `market_context.py` | data pasar umum + context (BTC regime, dsb)     |
| `spot_market.py` / `futures_market.py` | daftar simbol + metadata pasar             |
| `opportunity.py`               | SPOT scanner cache + signals                     |
| `futures_scanner.py` / `futures_learning.py` / `futures_eligibility.py` | FUTURES lane |
| `scanner.py`                   | scanner umum (legacy)                            |
| `history.py`                   | paper_trades + stats + equity curve              |
| `balance.py`                   | paper_balance + balance_transaction              |
| `signals.py`                   | signal catalog + weight                          |
| `backtest.py`                  | weekly backtest results                          |
| `predictive.py`                | predictive logs                                  |
| `big_mover_log.py`             | log big mover                                    |
| `binance_status.py`            | status API Binance + rate-limit                  |
| `diagnostics.py`               | health/log diagnostics                           |
| `agent_config.py`              | tuning per-agent runtime                         |
| `exchange_settings.py`         | tuning exchange side                             |
| `admin.py`                     | operasi admin                                    |

---

## 11. Testing / lint

- Backend: `pytest` (config di `backend/pytest.ini`, `.pytest_cache` sudah ada).
- Frontend: `npm run lint`, `npm run build`.
- **Aturan saya**: jalankan test/lint yang **sudah ada** sebelum & sesudah edit.
  Jangan pasang tool baru kecuali user minta.

---

## 12. Cara saya bekerja di repo ini

1. **Baca dulu, edit belakangan.** Selalu `view` file target sebelum `edit`.
   Untuk file > 20KB pakai `view_range`.
2. **Parallel tool calls** untuk explore (multiple `view`/`grep`/`glob` sekaligus).
3. **Hormati boundary lane**:
   - UI bug → `frontend/src/features/*` atau `frontend/src/app/(content)/*`.
   - API baru → `backend/app/api/v1/*` + schema di `backend/app/schemas/`.
   - Logic trading → `agents/{opportunity|futures}/*`.
   - TA baru → `backend/app/services/ta_engine/*`.
   - ML/backtest → `agents/learning/*`.
4. **Verifikasi**: setelah edit, cek dengan lint/build/test yang relevan.
   Untuk backend cek juga `/health` bila agent-related.
5. **Windows shell**: PowerShell, path pakai `\`, tidak ada `&&` / `||` (pakai `;` + `if ($?)`).
6. **Ask user** kalau ambigu (design decision, scope, atau nyentuh area sensitif
   seperti auth, DB schema breaking, atau live-trading path).
7. **No file spam**: jangan bikin markdown planning di repo. Notes taruh di
   session folder `plan.md`. Kecuali user minta file spesifik (mis. AGENT.md ini).

---

## 13. Referensi dokumen lain di repo

- `CLAUDE.md` — dokumen orientasi awal (mostly benar, tapi struktur `agents/`
  sudah berkembang jadi opportunity/futures/learning/shared; anggap AGENT.md ini
  sebagai versi terbaru).
- `README.md` — cara run docker/lokal + endpoint list.
- `PLAN-LIVE-TRADING.md` — roadmap ke live trading.
- `PLAN_ADAPTIVE_LEARNING_FUTURES_10X.md` — plan ML futures.
- `PLAN_ADAPTIVE_SIGNAL_WEIGHTING_SPOT_10X.md` — plan adaptive weight spot.
- `SCHEDULE_FUTURES.md` — jadwal & interval loop futures.

---

_Last updated: 2026-07-16 · maintained by Copilot CLI agent runs on this repo._
