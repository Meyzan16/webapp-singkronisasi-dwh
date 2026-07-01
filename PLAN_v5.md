# PLAN_v5 — DB Dynamic Config + Early Radar + Architecture Live

Tanggal: 2026-07-01  
Kelanjutan PLAN_v4. Tiga inisiatif besar berdasarkan analisis mendalam semua agent files (scanner, scheduler, monitor, weight_updater, agent1-3, bigmover, auto_trader, risk_gate, cross_agent_learning).

---

## Temuan Utama — Analisis Agent (2026-07-01)

> **✅ DELIVERED ke fitur arsitektur (2026-07-01):** Temuan Utama sudah dituangkan akurat ke architecture page. Koreksi yang diterapkan:
> - Volume kini **per-lane** (5M / 500K / 1M / 1M) — bukan lagi "$5M" tunggal. UniverseBar tampil "Vol Range $500K–$5M", tiap kartu lane punya baris "Min Volume".
> - Futures scan interval **2 menit** (sebelumnya salah "5 menit"), + "Fast Monitor 30 detik".
> - Futures cap **6 posisi global** (lane quota 2/2/1 + bigmover 2) — bukan "3 per cycle".
> - Risk Gate states diperbaiki (OPEN / LANE PAUSED / CLOSED) sesuai risk_gate.py, bukan semantik SPOT regime.
> - Verified live di container (tsc clean, rebuild + restart, DOM confirmed).

### SPOT System (4 lanes, akan jadi 5)

| Lane | Min Volume | Score Min | Auto-Open | SL Method | TP Targets |
|------|-----------|-----------|-----------|-----------|------------|
| Accumulation | $5M | 65 | 85 | Swing Low 4h -0.8% | 2.5×/4×/7× risk |
| Breakout Hunter | $500K | 60 | 75 | ATR(14) × 1.5 | 2×/3.5×/6× risk |
| BigMover Chase | $1M | 55 | 65 | Swing Low -1.5% | 5/12/25% atau 8/20/45% |
| Weekly Momentum | $1M | 65 | 85 | Swing Low 4h | 2.5×/4×/7× risk |
| **[NEW] Early Radar** | **$100K–$1M** | **70** | **85** | **30d Low -1%** | **10/25/60%** |

**Gap kritis:** Volume $100K–$500K = blind spot total. SYN-type coins mulai di sini sebelum masuk radar manapun.

**Monitor: 5 layers per 60 detik**
- L0: Profit lock G5b — peak ≥ 40/25/15% lock @ 75/70/60%
- L1: Hard exits SL/TP dengan wick detection (1m candles)
- L2: Risk exits — trend_reversal, profit_protection, flow_reversal
- L3: Max age 10d (fresh_setup), 5d (momentum_chase)
- L4: Stagnant rotation — tutup posisi idle jika ada kandidat lebih baik (+10 pts / +25 pts urgent)

**Learning:** Training window 90d, decay half-life 7d, step cap 10%, Laplace smoothing, cross-agent blend 30%.

---

### FUTURES System (4 agents)

| Agent | Setup Type | Min Score | Direction | Leverage | SL Margin Cap |
|-------|-----------|-----------|-----------|---------|--------------|
| agent1 | pre_gainer | 52 | LONG+SHORT | ATR-based, max 18% margin | 18% |
| agent2 | accumulation | 52 | LONG+SHORT | ATR-based, cap 15% margin | 15% |
| agent3 | momentum | 65 | LONG+SHORT | ATR-based, max 10×, cap 25% | 25% |
| agent_bigmover | bigmover | 60 | LONG+SHORT | FIXED 3×, risk 0.5% | 20% |

**Auto-trader:** Max 6 positions global. Lane quotas: momentum 2, pre_gainer 2, accumulation 1, bigmover 2 (separate). Cooldown 3h setelah SL. Funding gates: LONG ≤ 0.12%, SHORT ≥ -0.12%.

**Monitor: per 120 detik**
- Regime SL adjustment (volatile → widen 0.5× ATR)
- Max age 3d + 2 extensions (max 5d)
- Stagnant 48h check → close jika < 20% progress ke TP1
- TP4 extension jika TP3 hit + score ≥ 65
- Hard exits: SL/TP2/TP3/TP4 + wick detection
- Liquidation guard: ≤5× 8%, ≤10× 6%, ≤20× 4%, >20× 3%
- Hard max-loss gate per lane margin cap
- G4 flash dump detection (max adverse 5× 1m window)
- G5b profit lock (identik dengan SPOT)
- Trailing SL ratchet (post-TP1, jenis per entry_mode)
- G9 funding degradation check tiap 10 cycles

**Risk Gate:** Drawdown thresholds per wallet size (10-20% hard stop). RAR Sharpe < -0.5. Per-lane WR auto-pause < 35% rolling 20 trades.

---

### Semua Konstanta Hardcoded (perlu jadi DB config)

**SPOT — 17 params**
```
MIN_QUOTE_VOLUME            = 5_000_000   scanner.py
MIN_SCORE                   = 65          scanner.py
AUTO_OPEN_SCORE             = 85          scanner.py
BREAKOUT_AUTO_SCORE         = 75          scanner.py
BREAKOUT_MIN_SCORE          = 60          scanner.py
BREAKOUT_MIN_VOLUME         = 500_000     scanner.py
BIGMOVER_MIN_CHANGE_24H     = 10.0        scanner.py
BIGMOVER_MAX_CHANGE_24H     = 200.0       scanner.py
BIGMOVER_AUTO_SCORE         = 65          scanner.py
BTC_REGIME_CLOSED_24H       = -5.0        scanner.py
BTC_REGIME_REDUCED_24H      = -3.0        scanner.py
MAX_OPENS_PER_CYCLE         = 3           scheduler.py
MAX_BIGMOVER_OPENS          = 2           scheduler.py
DAILY_LOSS_LIMIT_FRACTION   = 0.03        scheduler.py
BIGMOVER_FASTPASS_SEC       = 30          scheduler.py
MIN_HOLD_MINUTES            = 30          monitor.py
MAX_AGE_DAYS_FRESH_SETUP    = 10          monitor.py
MAX_AGE_DAYS_MOMENTUM_CHASE = 5           monitor.py
```

**FUTURES — 18 params**
```
agent1_min_score            = 52          agent1.py
agent2_min_score            = 52          agent2.py
agent3_min_score            = 65          agent3.py
bigmover_min_score          = 60          agent_bigmover.py
MAX_AUTO_POSITIONS          = 6           auto_trader.py
lane_quota_momentum         = 2           auto_trader.py
lane_quota_pre_gainer       = 2           auto_trader.py
lane_quota_accumulation     = 1           auto_trader.py
MAX_BIGMOVER_POSITIONS      = 2           auto_trader.py
funding_gate_long           = 0.12        auto_trader.py
funding_gate_short          = -0.12       auto_trader.py
FUTURES_COOLDOWN_HOURS      = 3           auto_trader.py
MAX_AGE_DAYS                = 3           monitor.py
lane_cap_accumulation       = 15.0        monitor.py
lane_cap_pre_gainer         = 18.0        monitor.py
lane_cap_momentum           = 25.0        monitor.py
lane_cap_bigmover           = 20.0        monitor.py
BIGMOVER_FIXED_LEVERAGE     = 3           agent_bigmover.py
```

**LEARNING — 7 params**
```
TRAINING_WINDOW_D           = 90          weight_updater.py (spot+futures)
DECAY_HALF_LIFE_D           = 7           weight_updater.py
STEP_CAP                    = 0.10        weight_updater.py
STALE_KEY_MAX_D             = 30          weight_updater.py
CROSS_BLEND                 = 0.30        cross_agent_learning.py
LANE_WR_PAUSE_THRESHOLD     = 0.35        risk_gate.py
LANE_WR_MIN_SAMPLE          = 20          risk_gate.py
```

---

## GROUP A — Early Radar Lane (SPOT Lane 5)

**Tujuan:** Tangkap explosive coins di $100K–$1M volume SEBELUM mereka masuk radar existing.  
**Independent dari Group B dan C — bisa dikerjakan langsung.**

### A1 — Constants + scan_early_radar() di scanner.py

**Constants baru:**
```python
EARLY_RADAR_VOL_MIN        = 100_000     # $100K minimum
EARLY_RADAR_VOL_MAX        = 1_000_000   # $1M ceiling
EARLY_RADAR_SURGE_MIN      = 2.0         # current_vol_24h / vol_7d_avg ≥ 2×
EARLY_RADAR_SURGE_STRONG   = 3.0         # ≥ 3× = strong signal
EARLY_RADAR_NEAR_HIGH_PCT  = 10.0        # dalam 10% dari 30d high
EARLY_RADAR_NEAR_HIGH_STR  = 5.0         # dalam 5% = near breakout
EARLY_RADAR_POOL           = 50          # top-50 positif dari range ini
EARLY_RADAR_MIN_SCORE      = 70          # bar tinggi (micro-cap = risiko lebih)
EARLY_RADAR_AUTO_SCORE     = 85          # auto-open threshold
EARLY_RADAR_RISK_PCT       = 0.5         # 0.5% risk per trade (setengah normal)
EARLY_RADAR_MAX_OPEN       = 2           # max 2 posisi aktif sekaligus
```

**Scoring _score_early_radar() — max 100 pts:**
```
Vol surge ≥ 3×               → +40 pts
Vol surge ≥ 2×               → +25 pts
Price near 30d high ≤ 5%     → +30 pts
Price near 30d high ≤ 10%    → +15 pts
change_24h 2–15% (sehat)     → +15 pts
RSI 4h = 40–65               → +10 pts
BB squeeze (1d klines)       → +5  pts
PENALTY: change_24h > 30%    → -20 pts (sudah lari)
```

**Data fetch strategy (efficient — tidak fetch 3 TF):**
- Ticker 24hr sudah ada → filter vol $100K–$1M, sort by priceChangePercent, ambil top-50 gainers
- Fetch **1d klines (30 candles)** per coin — untuk vol_7d_avg + 30d_high + 30d_low
- 30 candles × 50 coins = 1,500 klines total (sangat ringan)

**_calc_trade_levels_early_radar():**
```
SL  = 30d_low − 1% buffer     → min 3%, max 10%
TP1 = entry + 10%              → target pertama
TP2 = entry + 25%              → primary target (nilai harapan)
TP3 = entry + 60%              → explosive scenario
R:R to TP2 ≥ 4.0 required     → micro-cap needs big asymmetry
entry_mode = "early_radar"
```

### A2 — Integrasi ke scan_market() + scheduler cap

Di `scan_market()` (scanner.py):
- Panggil `scan_early_radar(tickers_all, _done_syms)` setelah BigMover pass
- Dedup via shared `_breakout_done` set

Di `scheduler.py` (`_auto_open_position`):
- Hitung `early_radar_open_count` sebelum open
- Skip jika `>= EARLY_RADAR_MAX_OPEN (2)`
- Risk override: `risk_pct = EARLY_RADAR_RISK_PCT (0.5%)`

### A3 — Update architecture page

- `data.ts`: tambah early_radar ke SPOT_LANES array (Lane 5)
- Fix `SYSTEM_OVERVIEW.spot.minVolume`: ganti `"$5,000,000"` → per-lane dict
- `SpotSection.tsx`: stats bar ganti "Min Volume" → tampilkan per-lane
- Rebuild Docker + restart container

---

## GROUP B — Architecture Page Live Data

> **✅ DELIVERED (2026-07-01):** Endpoint `GET /api/v1/agent/config` live, membaca langsung dari
> module Python agents (bukan hardcode duplikat). Semua 3 section (spot/futures/learning) return
> `errors: []` — tidak ada kegagalan import. Frontend hook `useAgentConfig()` terpasang di
> `UniverseBar` (SpotSection), `FuturesStatsBar` + `AgentsSection` (FuturesSection), dan
> `WeightFormula` (LearningSection) — masing-masing menampilkan badge **"🟢 Live dari agent"**
> dan fallback **"⚪ Static"** kalau API gagal/loading. Diverifikasi end-to-end lewat dev-server
> preview: badge live + nilai (3 menit, 60 detik, 30 detik, 2 menit, 6 global, 90 hari, 7 hari,
> 10%/run, 30% blend) semuanya cocok persis dengan response API. pre_gainer/accumulation pakai
> **threshold adaptif live** dari `weight_updater.get_adaptive_thresholds()` (bukan angka statis
> 52) — lebih akurat dari rencana awal.

**Tujuan:** Halaman arsitektur selalu akurat — pull dari runtime, bukan `data.ts` statis.

### B1 — Backend: GET /api/v1/agent/config

Buat `backend/app/api/v1/agent_config.py`:

```python
@router.get("/agent/config")
async def get_agent_config():
    """Return all runtime constants from all agent modules."""
    from agents.opportunity import scanner, scheduler, monitor
    from agents.futures import auto_trader, risk_gate
    from agents.opportunity.weight_updater import TRAINING_WINDOW_D, DECAY_HALF_LIFE_D, STEP_CAP
    from agents.shared.cross_agent_learning import CROSS_BLEND
    
    return {
      "spot": {
        "scan_interval_sec": scheduler.INTERVAL_SEC,
        "min_volume": {
          "accumulation": scanner.MIN_QUOTE_VOLUME,
          "breakout": scanner.BREAKOUT_MIN_VOLUME,
          "bigmover": scanner.BIGMOVER_MIN_VOLUME,
          "weekly": scanner.WEEKLY_SCAN_MIN_VOLUME,
          "early_radar": scanner.EARLY_RADAR_VOL_MIN,
        },
        "score_thresholds": {
          "accumulation": { "min": scanner.MIN_SCORE, "auto": scanner.AUTO_OPEN_SCORE },
          "breakout": { "min": scanner.BREAKOUT_MIN_SCORE, "auto": scanner.BREAKOUT_AUTO_SCORE },
          "bigmover": { "min": scanner.BIGMOVER_MIN_SCORE, "auto": scanner.BIGMOVER_AUTO_SCORE },
          "early_radar": { "min": scanner.EARLY_RADAR_MIN_SCORE, "auto": scanner.EARLY_RADAR_AUTO_SCORE },
        },
        "bigmover": {
          "min_change_24h": scanner.BIGMOVER_MIN_CHANGE_24H,
          "max_change_24h": scanner.BIGMOVER_MAX_CHANGE_24H,
          "explosive_threshold": scanner.BIGMOVER_EXPLOSIVE_THRESHOLD,
          "tp_standard": [scanner.BIGMOVER_TP1_PCT, scanner.BIGMOVER_TP2_PCT, scanner.BIGMOVER_TP3_PCT],
          "tp_explosive": [scanner.BIGMOVER_EXPLOSIVE_TP1_PCT, scanner.BIGMOVER_EXPLOSIVE_TP2_PCT, scanner.BIGMOVER_EXPLOSIVE_TP3_PCT],
        },
        "regime_gates": {
          "closed_pct": scanner.BTC_REGIME_CLOSED_24H,
          "reduced_pct": scanner.BTC_REGIME_REDUCED_24H,
        },
        "monitor": {
          "interval_sec": monitor.INTERVAL_SEC,
          "max_age_fresh_days": monitor.MAX_AGE_DAYS_FRESH_SETUP,
          "max_age_momentum_days": monitor.MAX_AGE_DAYS_MOMENTUM_CHASE,
          "min_hold_minutes": monitor.MIN_HOLD_MINUTES,
          "profit_lock_tiers": monitor._PROFIT_LOCK_TIERS_SPOT,
        },
        "quota": {
          "max_opens_per_cycle": scheduler.MAX_OPENS_PER_CYCLE,
          "max_bigmover_opens": scheduler.MAX_BIGMOVER_OPENS,
          "daily_loss_limit_pct": scheduler.DAILY_LOSS_LIMIT_FRACTION * 100,
        },
      },
      "futures": {
        "scan_interval_sec": 120,
        "agents": {
          "pre_gainer":   { "min_score": 52, "leverage_max": 15, "sl_margin_cap": 18 },
          "accumulation": { "min_score": 52, "leverage_max": 12, "sl_margin_cap": 15 },
          "momentum":     { "min_score": 65, "leverage_max": 10, "sl_margin_cap": 25 },
          "bigmover":     { "min_score": 60, "leverage_fixed": 3, "sl_margin_cap": 20, "risk_pct": 0.5 },
        },
        "auto_trader": {
          "max_positions": auto_trader.MAX_AUTO_POSITIONS,
          "lane_quotas": auto_trader.LANE_QUOTAS,
          "max_bigmover": auto_trader.MAX_BIGMOVER_POSITIONS,
          "funding_gate_long": auto_trader.FUNDING_GATE_LONG,
          "funding_gate_short": auto_trader.FUNDING_GATE_SHORT,
          "cooldown_hours": auto_trader.FUTURES_COOLDOWN_HOURS,
        },
        "risk_gate": {
          "dd_hard_stop_pct": risk_gate.DD_HARD_STOP_PCT,
          "dd_recover_pct": risk_gate.DD_RECOVER_PCT,
          "rar_threshold": risk_gate.RAR_GATE_THRESHOLD,
          "lane_wr_pause_threshold": risk_gate.LANE_WR_PAUSE_THRESHOLD,
          "lane_wr_min_sample": risk_gate.LANE_WR_MIN_SAMPLE,
        },
      },
      "learning": {
        "training_window_d": TRAINING_WINDOW_D,
        "decay_half_life_d": DECAY_HALF_LIFE_D,
        "step_cap": STEP_CAP,
        "cross_blend": CROSS_BLEND,
      },
    }
```

Register di `main.py`.

### B2 — Frontend: hook + live pull + badge "🟢 Live"

- Buat `frontend/src/features/architecture/hooks/useAgentConfig.ts`
- Fetch dari `GET /api/v1/agent/config` (via existing API proxy)
- `SpotSection`, `FuturesSection`, `LearningSection` terima `config` prop dari hook
- data.ts menjadi **fallback skeleton** (dipakai saat loading atau API error)
- Tambah badge `🟢 Live` di setiap stats bar
- Rebuild Docker + restart container

---

## GROUP C — DB Dynamic Config

> **✅ DELIVERED + AUDITED (2026-07-01):** 38 param kritis (17 spot + 17 futures + 4 learning)
> kini DB-dynamic via tabel `agent_config`. Komponen: model `AgentConfig` + seed idempotent
> (`agent_config_defaults.py`), `AgentConfigReader` (TTL 60s, fallback ke default), reassignment
> `global` di tiap entry-point agent (scanner/scheduler/monitor/auto_trader/risk_gate/weight_updater/
> cross_agent), Admin UI editor di `/settings` (inline edit + reset), badge `🔵 DB`/`⚪ static` di
> architecture page. **Verifikasi:** seed 38 row OK, PATCH→modified=true OK, reset→default OK,
> endpoint `/agent/config` reflect DB value (77) OK, embedded agent run `agent_config_pull_failed=0`
> (reassignment bersih, zero Traceback).
>
> **Audit "tidak ada pola berubah":** default seed === nilai hardcoded lama → behavior identik saat
> tanpa override. Nilai di-read once-per-cycle (frozen dalam cycle = sama seperti konstanta lama).
> `int()` di-wrap pada semua param yang masuk slice/quota/range; comparison/arithmetic float-safe.
>
> **3 param SENGAJA tidak diwire** (mencegah override menyesatkan): `dd_hard_stop_pct`/`dd_recover_pct`
> (dihitung otomatis dari ukuran wallet di `_scaled_dd_threshold`), `agent1/2/3 min_score` (adaptif
> dari weight_updater, bukan konstanta), `futures decay_half_life` (14d ≠ spot 7d, tak boleh 1 key).
>
> **Cross-process fix:** backend & agents jalan di proses/container terpisah, jadi endpoint
> `/agent/config` di-ubah baca DB langsung via `cfg.get()` (bukan module attribute) supaya akurat
> lintas-proses.

**Tujuan:** Ubah semua 42 konstanta kritis tanpa redeploy Docker.

### C1 — Schema: tabel agent_config

```sql
CREATE TABLE agent_config (
    id           SERIAL PRIMARY KEY,
    agent_group  TEXT NOT NULL,   -- 'spot', 'futures', 'learning'
    key          TEXT NOT NULL,
    value_type   TEXT NOT NULL,   -- 'float', 'int', 'bool', 'json'
    value_num    FLOAT,
    value_text   TEXT,
    default_num  FLOAT,           -- original hardcoded default
    default_text TEXT,
    description  TEXT NOT NULL,
    category     TEXT NOT NULL,   -- 'threshold', 'volume', 'timing', 'risk', 'quota'
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_by   TEXT DEFAULT 'system',
    UNIQUE (agent_group, key)
);
```

Migration file: `backend/alembic/versions/xxx_agent_config.py`  
SQLAlchemy model: `backend/app/models/agent_config.py`  
Seed: insert semua 42 default values saat migration.

### C2 — Config reader utility

Buat `agents/shared/config_reader.py`:

```python
class AgentConfigReader:
    """In-memory cache dengan TTL 60s. Fallback ke default jika DB down."""
    _cache: dict[str, float] = {}
    _loaded_at: float = 0
    TTL = 60  # seconds
    
    async def get(self, group: str, key: str, default: float) -> float:
        ...
    
    async def _reload(self) -> None:
        """Fetch semua rows dari agent_config ke _cache."""
        ...

cfg = AgentConfigReader()  # singleton
```

Usage di scanner.py (contoh):
```python
from agents.shared.config_reader import cfg

MIN_QUOTE_VOLUME = await cfg.get("spot", "min_quote_volume", 5_000_000)
```

### C3 — Migrate SPOT params (17 params, 3 files)

Files: `scanner.py`, `scheduler.py`, `monitor.py`  
Pattern: konstanta jadi `async def get_X()` atau baca saat scan start.  
Constants tetap ada sebagai fallback default value.

### C4 — Migrate FUTURES params (18 params, 4 files)

Files: `agent1.py`, `agent2.py`, `agent3.py`, `agent_bigmover.py`, `auto_trader.py`, `monitor.py`

### C5 — Migrate LEARNING params (7 params, 3 files)

Files: `weight_updater.py` (spot+futures), `cross_agent_learning.py`, `risk_gate.py`

### C6 — Admin UI: Config Editor di /settings

Tab baru "⚙️ Agent Config" di halaman `/settings`:
- Table view: Group | Key | Current Value | Default | Description | Category | [Edit] [Reset]
- Inline edit field dengan validasi (range check per category)
- Tombol Reset to Default per row
- API: `GET /api/v1/agent/config/all` → semua rows dengan metadata
- API: `PATCH /api/v1/agent/config/{group}/{key}` → update value
- Perubahan efektif setelah TTL cache expire (≤ 60s)
- Badge "modified" (warna beda) jika value ≠ default

### C7 — Architecture page: badge sumber data

- Setiap parameter yang sudah ada di DB → badge `🔵 DB` (klik → buka config editor row itu)
- Yang masih hardcode → badge `⚪ static`
- Upgrade otomatis dari `⚪` ke `🔵` seiring C3-C5 selesai

---

## Urutan Eksekusi

```
A1 → A2 → A3       Early Radar (independent, high value langsung)
         ↓
B1 → B2             Architecture live data (A3 jadi B2 sudah include)
         ↓
C1 → C2 → C3 → C4 → C5 → C6 → C7   DB Dynamic (big refactor)
```

**Kenapa urutan ini:**
- A = nilai tertinggi, independent. Early Radar buka peluang coins yang sebelumnya invisible.
- B = quick win. Endpoint 1 file, FE 1 hook. Architecture page langsung akurat tanpa manual update.
- C = terbesar tapi optional. Bisa dilakukan bertahap. Tanpa C pun sistem sudah berfungsi baik.

---

## Tasks Terdaftar

| Task | Grup | Status |
|------|------|--------|
| #24 scan_early_radar() + constants | A1 | pending |
| #25 Integrasi scan_market() + scheduler | A2 | pending |
| #26 Architecture page Lane 5 | A3 | pending |
| #27 Backend /agent/config endpoint | B1 | pending |
| #28 Frontend hook + live pull | B2 | pending |
| #29 Schema agent_config | C1 | pending |
| #30 Config reader utility | C2 | pending |
| #31 Migrate SPOT params | C3 | pending |
| #32 Migrate FUTURES params | C4 | pending |
| #33 Migrate LEARNING params | C5 | pending |
| #34 Admin UI Config Editor | C6 | pending |
| #35 Architecture page DB badges | C7 | pending |

---

## Keputusan Terkunci

| Pertanyaan | Keputusan |
|---|---|
| Early Radar masuk bigmover_chase existing atau lane baru? | **Lane baru** — scoring berbeda (vol surge + near high, bukan BigMover magnitude). Entry mode = "early_radar". |
| Architecture page: API atau DB? | **API dulu (Group B)** — baca dari module konstanta Python. DB nanti (Group C). |
| Config reader: reload per-call atau TTL cache? | **TTL cache 60s** — balance antara freshness dan DB load. |
| DB dynamic scope: semua 42 params atau subset? | **Critical params saja dulu** (score thresholds, volumes, quotas, risk caps). Fine-grained scoring points tetap hardcode. |
| Early Radar R:R minimum? | **≥ 4.0** — micro-cap butuh asymmetry lebih besar untuk kompensasi slippage dan noise. |
