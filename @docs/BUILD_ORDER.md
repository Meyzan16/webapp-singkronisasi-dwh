# Build order — strict sequence

IMPORTANT: Build in this EXACT order. Every step depends on the previous one. Do NOT skip ahead.

---

## Step 1: Data pipeline - COMPLETE

**Goal:** Fetch and store Binance klines for 5 pairs × 5 timeframes.

**Files to create:**
```
backend/
├── app/
│   ├── main.py                          # FastAPI app + lifespan
│   ├── config.py                        # Settings (pairs, timeframes, DB URL)
│   ├── database.py                      # async SQLAlchemy + session
│   ├── models/
│   │   └── kline.py                     # Kline SQLAlchemy model
│   ├── schemas/
│   │   └── kline.py                     # Kline Pydantic schemas
│   ├── services/
│   │   └── data_pipeline/
│   │       ├── __init__.py
│   │       ├── binance_client.py        # CCXT async Binance wrapper
│   │       ├── kline_fetcher.py         # Fetch historical + polling
│   │       └── kline_repository.py      # DB read/write operations
│   └── api/
│       └── v1/
│           └── klines.py                # GET /api/v1/klines/{pair}/{timeframe}
├── requirements.txt
├── .env.example
└── Dockerfile
```

**What this step does:**
1. Connect to Binance via CCXT (no API key needed for public data)
2. Fetch 6 months of historical klines for: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, SUIUSDT
3. Timeframes: 1w, 1d, 4h, 1h, 15m
4. Store in PostgreSQL `klines` table
5. Expose REST endpoint to query klines
6. Background task polls new candles every 60 seconds

**Acceptance criteria:**
- [x] Backend code exposes `GET /api/v1/klines/{pair}/{timeframe}` with Pydantic response schema
- [x] Historical fetcher pages raw Binance klines from about 6 months back
- [x] Background task backfills once, then polls new candles every 60 seconds
- [x] Repository uses PostgreSQL upsert on pair+timeframe+open_time
- [ ] Live endpoint verified against running PostgreSQL and Binance data

**Dependencies:** PostgreSQL running (via docker-compose), ccxt, fastapi, sqlalchemy[asyncio]

**Implementation commit:** `1a42c7a feat: add data pipeline backend`

**Verification:** backend tests pass (`3 passed`), `docker compose config` passes. Frontend lint still fails on pre-existing non-Step-1 files.

---

## Step 2: TA engine - T1 (Trend) ← CURRENT STEP

**Goal:** Calculate EMA 13/21 and detect trendline for each pair/timeframe.

**Files to create:**
```
backend/app/services/ta_engine/
├── __init__.py
├── ema.py                    # EMA 13, 21 calculation
├── trendline.py              # Swing point detection + trendline validation
└── trend_analyzer.py         # Combines EMA + trendline → trend state
```

**Acceptance criteria:**
- [ ] Given klines for BTCUSDT 1W, returns: trend direction (up/down/sideways), EMA values, trendline touches
- [ ] Backtest: compare EMA crossover signals against actual price movement for 6 months

---

## Step 3: TA engine — T0 (Wyckoff)

**Goal:** Detect market cycle phase per coin.

**Files:** `backend/app/services/ta_engine/wyckoff.py`

**Depends on:** Step 2 (needs trend data + price structure)

---

## Step 4: TA engine — T2 (S/R Areas)

**Goal:** Scan 30-100 day historical bounce zones.

**Files:** `backend/app/services/ta_engine/support_resistance.py`

**Depends on:** Step 1 (needs klines data)

---

## Step 5: TA engine — T3 (Pattern)

**Goal:** Detect chart patterns and market structure.

**Files:** `backend/app/services/ta_engine/pattern_detector.py`

**Depends on:** Step 4 (needs S/R context)

---

## Step 6: TA engine — T4 (Trigger)

**Goal:** Candlestick patterns + Stochastic 5,3,3 + volume confirmation.

**Files:**
```
backend/app/services/ta_engine/
├── candlestick.py            # Engulfing, hammer, star patterns
├── stochastic.py             # Stochastic (5,3,3) calculation + cross detection
└── trigger_analyzer.py       # Combines candle + stoch + volume → trigger signal
```

**Depends on:** Step 1 (needs klines with volume data)

---

## Step 7: Signal generator + risk engine

**Goal:** Combine T0-T4, calculate SL/TP, filter by R:R >= 1:3.

**Files:**
```
backend/app/services/signal_generator/
├── __init__.py
├── pipeline.py               # Runs T0→T1→T2→T3→T4 waterfall
├── risk_calculator.py        # SL placement, position sizing, R:R check
└── signal_card.py            # Output signal with reasoning chain
```

---

## Step 8: Frontend — take out old features + new navigation

**Goal:** Remove all existing features except sign-in. Set up new navigation for trading agent.

**What to remove from `src/`:**
- `app/(content)/dashboards/` — remove page content (keep route)
- `app/(content)/sync-jobs/` — DELETE entirely
- `app/(content)/data-mapping/` — DELETE entirely
- `app/(content)/monitoring/` — DELETE entirely
- `app/(content)/settings/` — remove content (keep route for new settings)
- `features/dashboard/` — DELETE entirely
- `features/sync-jobs/` — DELETE entirely
- `features/data-mapping/` — DELETE entirely
- `types/dashboard.ts` — DELETE
- `types/sync-jobs.ts` — DELETE
- `types/sync-jobs-extended.ts` — DELETE
- `types/data-mapping.ts` — DELETE
- `components/sync-jobs-table.tsx` — DELETE

**What to KEEP:**
- `app/(auth)/` — sign-in flow, untouched
- `app/(content)/layout.tsx` — content layout with sidebar
- `components/ui/` — all shared UI components (button, card, badge, alert, etc.)
- `components/sidebar.tsx` — update navigation items
- `components/navbar.tsx` — update route map
- `components/navigation.tsx` — update routes
- `app/context/` — global context provider
- `hooks/` — shared hooks
- `app/layout.tsx` — root layout
- `app/globals.css` — all styling

**New navigation (6 items):**
1. Dashboard → `/dashboards`
2. Scanner → `/scanner`
3. Signal feed → `/signals`
4. Charts → `/charts`
5. Backtest → `/backtest`
6. Settings → `/settings`

---

## Step 9: Frontend — Scanner page

**Goal:** Volume heatmap, top movers, token table. Connect to backend API.

**Depends on:** Step 1 (backend data) + Step 8 (navigation ready)

---

## Step 10: Frontend — Signal feed page

**Goal:** Display signal cards from backend. Expandable TA reasoning.

**Depends on:** Step 7 (signal generator) + Step 8 (navigation ready)

---

## Step 11: Frontend — Charts page

**Goal:** TradingView lightweight charts with EMA overlay, Stoch panel, S/R zones.

**Depends on:** Steps 2-6 (TA data) + Step 8

---

## Step 12: Frontend — Dashboard home

**Goal:** Portfolio summary, active signals count, Wyckoff phase per coin.

**Depends on:** Steps 7 + 9 + 10

---

## Step 13: Backtest engine

**Goal:** Run strategy against historical data, generate equity curve and stats.

**Depends on:** Steps 1-7 (full pipeline working)

---

## Step 14: Frontend — Backtest page

**Depends on:** Step 13

---

## Step 15: Settings page

**Goal:** Agent config, TA parameters, risk rules, API keys.

---

## Step 16 (FUTURE): Onchain layer

DexScreener + GoPlus integration. Only after Steps 1-15 are complete and paper trading is proven.
