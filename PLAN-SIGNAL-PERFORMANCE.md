# PLAN: Signal Performance — Adaptive Learning Dashboard

Tujuan: membangun siklus belajar mandiri (**Adaptive Learning Loop**) di mana setiap sinyal
yang dieksekusi agents (SPOT & Futures) dilacak hasilnya, weight-nya diperbarui otomatis,
dan agents secara aktif memprioritaskan sinyal yang terbukti profitable — **terus menerus tanpa intervensi manual**.

---

## Arsitektur Loop

```
Scan → Signal fires → Trade open
                              ↓ trade close (tp/sl/expired)
                       Weight Updater runs
                              ↓
                  agent_signal_weights (DB)
                              ↓
                  Agents baca weight saat scoring
                              ↓
                    Sinyal proven → score lebih tinggi
                    Sinyal lemah  → score lebih rendah
                              ↓
                    Hanya posisi terbaik yang masuk
                              ↓
                         WIN RATE NAIK
```

---

## Kondisi Sekarang (Audit)

### Yang sudah ada ✅
| Komponen | Status |
|----------|--------|
| `AgentSignalWeight` model (DB) | ✅ Ada — shared antara SPOT & Futures |
| SPOT weight updater (`opportunity/weight_updater.py`) | ✅ Canggih: recency decay + Laplace + step cap |
| Futures weight updater (`futures/weight_updater.py`) | ✅ Berjalan tapi lebih sederhana dari SPOT |
| Signal tracking per trade (`signals_json`) | ✅ Ada di `PaperTrade.signals_json` |
| Per-coin win rate & blacklist | ✅ Ada di futures weight updater |

### Gap yang harus ditutup ❌
| Gap | Dampak |
|-----|--------|
| **Futures updater jauh lebih sederhana dari SPOT** | Learning tidak simetris — SPOT belajar lebih cepat |
| **Tidak ada cross-agent learning** | Futures tidak belajar dari SPOT, SPOT tidak belajar dari Futures |
| **Tidak ada `avg_pnl_pct` per sinyal** | Win rate 50% tapi win-nya kecil = misleading |
| **Tidak ada Signal Performance API** | Frontend tidak bisa expose data ini |
| **Tidak ada frontend Signal Performance page** | User tidak tahu sinyal mana yang bekerja |
| **Minimum sample terlalu rendah** (Futures: `total >= 2`, SPOT sudah pakai confidence scaling) | Weight berubah dari data tidak valid |

---

## Fase Pengerjaan

---

### SP1 — Perkaya `AgentSignalWeight` dengan `avg_pnl_pct` dan `sample_count_raw`

**File:** `backend/app/models/signal_weight.py`

**Mengapa:** Win rate saja menipu. Sinyal yang menang 60% tapi avg PnL +0.5% lebih buruk
dari sinyal menang 50% tapi avg PnL +3.2%. Kolom `avg_pnl_pct` memungkinkan ranking
yang lebih akurat.

**Perubahan:**
```python
class AgentSignalWeight(Base):
    # ... kolom existing ...
    avg_pnl_pct:    Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    sample_count_raw: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # sample_count_raw = jumlah trades mentah (sebelum decay weighting)
    # total_count SPOT sudah pakai decayed effective count — tambah raw untuk display
```

**Migration:** `ALTER TABLE agent_signal_weights ADD COLUMN avg_pnl_pct FLOAT DEFAULT 0.0, ADD COLUMN sample_count_raw INT DEFAULT 0;`

---

### SP2 — Upgrade Futures Weight Updater Setara SPOT

**File:** `agents/futures/weight_updater.py`

**Mengapa:** SPOT updater lebih canggih (recency decay, Laplace smoothing, confidence scaling,
step cap ±0.10, zombie pruning). Futures updater tidak punya ini — artinya Futures belajar
lebih kasar dan lebih mudah overfit ke data kecil.

**Perubahan yang ditambahkan ke futures updater:**

```python
DECAY_HALF_LIFE_D = 14.0   # futures = trade lebih lama, decay lebih lambat dari SPOT (7d)
STEP_CAP          = 0.10   # max perubahan weight per run (anti-oscillation)
STALE_KEY_MAX_D   = 45     # zombie pruning threshold
MIN_SAMPLE        = 3      # tidak ada di current futures updater, sekarang ditambah

def _target_weight(win_rate_adj: float) -> float:
    """Smooth weight mapping, sama dengan SPOT."""
    if win_rate_adj >= 0.70: return 1.5
    if win_rate_adj >= 0.55: return 1.2
    if win_rate_adj >= 0.40: return 1.0
    return 0.7

def _weight_from_rate(win_rate: float, total: int) -> float:
    """SP2: Ganti formula lama (linear) dengan Laplace + confidence scaling."""
    if total < MIN_SAMPLE:
        return 1.0  # tidak cukup data → neutral
    wr_adj     = (win_rate * total + 1.0) / (total + 2.0)   # Laplace
    target     = _target_weight(wr_adj)
    confidence = min(1.0, total / 10.0)                      # full influence at n=10
    desired    = 1.0 + (target - 1.0) * confidence
    return round(max(0.70, min(1.50, desired)), 3)
```

Tambah `avg_pnl_pct` saat upsert:
```python
avg_pnl = sum(t.pnl_pct or 0.0 for t in wins) / len(wins) if wins else 0.0
```

---

### SP3 — Cross-Agent Learning

**File baru:** `agents/shared/cross_agent_learning.py`

**Mengapa:** Sinyal yang bekerja di SPOT sering bekerja juga di Futures (contoh: BB Squeeze,
RSI Oversold). Tapi sekarang agents belajar secara terpisah. Cross-agent learning
menyebabkan agents **saling belajar** — jika suatu sinyal terbukti di satu agen,
semua agen lain mendapat sinyal itu sebagai boost.

**Mekanisme:**
```python
CROSS_AGENT_STYLE = "cross_agent"   # virtual agent untuk agregat
MIN_CROSS_AGENT_SAMPLE = 10         # butuh 10 trades gabungan sebelum pengaruhi agen lain
CROSS_AGENT_BLEND = 0.30            # 30% weight dari cross-agent, 70% dari agen sendiri

async def compute_cross_agent_weights() -> dict[str, float]:
    """
    Baca semua closed trades dari SEMUA agen (spot + futures).
    Aggregate per signal_key (tanpa membedakan agen).
    Hasilkan weight cross-agent untuk setiap signal.
    """
    # Query semua closed trades
    # Group by signal_key (normalisasi dulu)
    # Hitung win_rate gabungan
    # Hitung weight cross-agent
    # Simpan ke agent_signal_weights dengan agent='cross_agent'
    ...

def blend_weights(own: float, cross: float, cross_blend: float = CROSS_AGENT_BLEND) -> float:
    """Blend own-agent weight dengan cross-agent weight."""
    return round(own * (1 - cross_blend) + cross * cross_blend, 3)
```

**Cara agents membaca:**
```python
# Di futures/agent1.py (dan agent2, agent3, scanner.py SPOT):
own_w   = weight_updater.get_weight_cache(agent)[signal_key]
cross_w = cross_agent_learning.get_cross_weight(signal_key)
final_w = cross_agent_learning.blend_weights(own_w, cross_w)
score  += final_w * BASE_SIGNAL_POINTS
```

---

### SP4 — Signal Performance API

**File baru:** `backend/app/api/v1/signals.py`

**Endpoints:**

```
GET  /api/v1/signals/performance   — semua signal dengan stats, filterable
GET  /api/v1/signals/cross_agent   — perbandingan antar agen per signal
GET  /api/v1/signals/top           — top N signal (default 10) per agent
GET  /api/v1/signals/weights/state — state weight updater (last run, errors)
POST /api/v1/signals/weights/force — force-run weight update (manual trigger)
```

**Query params `GET /api/v1/signals/performance`:**
```
agent       = "all" | "opportunity_spot" | "futures_agent1" | "futures_agent2" | "futures_agent3" | "cross_agent"
regime      = "all" | "trending_up" | "trending_down" | "ranging" | "volatile"
min_trades  = 1 (default 5 — jangan tampilkan sinyal dengan data sedikit)
sort_by     = "win_rate" | "avg_pnl_pct" | "total_count" | "weight"
sort_dir    = "desc" | "asc"
limit       = 20
```

**Response:**
```json
{
  "signals": [
    {
      "signal_key":    "bb_squeeze_N_timeframe",
      "agents": {
        "opportunity_spot":  { "win_rate": 0.71, "total": 14, "wins": 10, "avg_pnl_pct": 4.2, "weight": 1.42 },
        "futures_agent2":    { "win_rate": 0.67, "total": 9,  "wins": 6,  "avg_pnl_pct": 3.8, "weight": 1.35 },
        "cross_agent":       { "win_rate": 0.70, "total": 23, "wins": 16, "avg_pnl_pct": 4.0, "weight": 1.40 }
      },
      "regime_breakdown": {
        "trending_up":   { "win_rate": 0.80, "total": 10 },
        "ranging":       { "win_rate": 0.55, "total": 13 }
      }
    }
  ],
  "meta": {
    "total_signals": 42,
    "last_weight_update": 1750300000,
    "spot_trades_in_window": 47,
    "futures_trades_in_window": 23
  }
}
```

---

### SP5 — Frontend: Signal Performance Page

**File baru:** `frontend/src/app/(content)/signals/page.tsx`
**Feature folder:** `frontend/src/features/signals/`

**Layout:**

```
/signals
├── Header: "Signal Performance — Adaptive Learning"
├── Sub-tabs: [Overview | SPOT | Futures | Cross-Agent]
│
├── Overview
│   ├── Stats strip: Total Signal Keys | Avg Win Rate | Best Signal | Worst Signal
│   ├── Top 5 signals (cross-agent) — card style dengan win rate, avg PnL, weight bar
│   └── Learning loop status: kapan terakhir weight diperbarui
│
├── SPOT tab
│   ├── Filter: regime, min_trades, sort_by
│   ├── Signal table: key | win rate | total | avg PnL% | weight | trend bar
│   └── Weight history chart (opsional, Phase 2)
│
├── Futures tab
│   ├── Filter: agent (Pre-Gainer/Accum/Momentum), regime, min_trades
│   ├── Signal table: key | agen | win rate | total | avg PnL% | weight | regime best
│   └── Agent comparison: sinyal mana yang bagus di agent1 vs agent2 vs agent3
│
└── Cross-Agent tab
    ├── Signal yang bekerja di SEMUA agen → highly reliable
    ├── Signal yang HANYA bekerja di satu agen → agent-specific edge
    └── Venn diagram sederhana (opsional)
```

**Komponen kunci:**
```
signals/
├── components/
│   ├── SignalTable.tsx        — tabel utama filterable + sortable
│   ├── SignalCard.tsx         — card untuk top signals
│   ├── WeightBar.tsx          — visualisasi weight (0.7=merah, 1.0=abu, 1.5=hijau)
│   ├── CrossAgentMatrix.tsx   — grid signal × agent dengan color coding
│   └── LearningLoopStatus.tsx — kapan updater terakhir jalan, error state
├── hooks/
│   └── useSignals.ts          — fetch + filter state
└── data/
    └── types.ts               — SignalPerf, CrossAgentData, etc.
```

---

## Ringkasan Fase

| Fase | Scope | File | Tujuan |
|------|-------|------|--------|
| SP1 | Backend model | `signal_weight.py` | Tambah `avg_pnl_pct` + `sample_count_raw` |
| SP2 | Backend agent | `futures/weight_updater.py` | Upgrade ke level SPOT (decay + Laplace + step cap) |
| SP3 | Backend shared | `agents/shared/cross_agent_learning.py` *(baru)* | Cross-agent weight blending |
| SP4 | Backend API | `backend/app/api/v1/signals.py` *(baru)* | Signal performance endpoints |
| SP5 | Frontend | `frontend/src/features/signals/` *(baru)* | Signal Performance dashboard page |

---

## Urutan Prioritas

| Prioritas | Fase | Dependensi | Estimasi |
|-----------|------|------------|----------|
| P0 | SP1: model kolom baru | — | 15 mnt |
| P0 | SP2: upgrade futures weight updater | SP1 | 30 mnt |
| P1 | SP3: cross-agent learning | SP1, SP2 | 45 mnt |
| P1 | SP4: signal performance API | SP1 | 30 mnt |
| P2 | SP5: frontend Signal Performance | SP4 | 90 mnt |

---

## Catatan Arsitektur

### Normalisasi signal key
SPOT dan Futures memakai `_normalize_signal()` yang **sedikit berbeda** saat ini:
- SPOT: strip angka → `"BB Squeeze 4H"` → `"bb_squeeze_NH"` (angka jadi `N`)
- Futures: pertahankan angka → `"BB Squeeze 4H"` → `"bb_squeeze_4h"`

Untuk cross-agent learning, keduanya harus pakai **skema yang sama**. Solusi:
gunakan versi SPOT (strip angka → `N`) sebagai standar, update futures normalizer.

### Minimum sample untuk cross-agent
- Own-agent: bisa mulai dari n=3 (ada confidence scaling)
- Cross-agent influence: hanya aktif saat `total_cross >= 10`
- Ini mencegah 1 trade di SPOT langsung mempengaruhi semua Futures agents

### Weight tidak di-reset setiap run
Kedua updater sudah pakai step cap (±0.10 per run) — bukan override langsung.
Ini sudah benar dan harus dipertahankan di SP2.

### Halaman signals — data polling
Tidak perlu real-time (tidak seperti Monitor). Polling setiap 5 menit cukup,
atau manual refresh. Weight updater sendiri jalan max sekali per 5-30 menit.
