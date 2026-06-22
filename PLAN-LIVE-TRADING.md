# PLAN-LIVE-TRADING.md
# Transisi Paper Trading → Live Binance Futures

**Status**: LOCKED — Jangan dikerjakan sebelum win rate terbukti
**Prasyarat**: Win rate ≥ 55% dengan minimum 100 closed trades di paper trading

---

## Gating Criteria (kapan boleh mulai)

Sebelum satu baris pun kode live trading ditulis, semua kondisi ini harus terpenuhi:

| Kriteria | Target | Cek di |
|----------|--------|--------|
| Total closed paper trades | ≥ 100 | `/history/stats` |
| Win rate keseluruhan | ≥ 55% | Analytics tab |
| Win rate Momentum (Agent3) | ≥ 55% | per-agent breakdown |
| Max drawdown paper | < 20% | Monitor Stats |
| Sharpe proxy | ≥ 0.5 | Analytics |
| Paper trading duration | ≥ 2 minggu | sejak deploy |

---

## Phase 1 — Testnet Integration (bukan uang nyata)

### LT1: Binance Futures Testnet Setup
- Daftarkan akun di `testnet.binancefuture.com`
- Tambah env var: `BINANCE_TESTNET_API_KEY`, `BINANCE_TESTNET_API_SECRET`
- Tambah toggle: `LIVE_TRADING=false` (default) di `.env`
- `BINANCE_TESTNET=true` di `.env`

### LT2: Order Executor (`agents/futures/order_executor.py`)
Buat modul baru dengan fungsi:

```python
async def open_position(symbol, direction, notional, leverage, sl, tp1, tp2) -> dict:
    """
    POST /fapi/v1/order — buka posisi futures
    Returns: {"order_id": ..., "avg_price": ..., "qty": ...}
    """

async def close_position(symbol, direction, qty) -> dict:
    """
    POST /fapi/v1/order (MARKET, reduceOnly=True) — tutup posisi
    """

async def set_stop_loss(symbol, direction, qty, sl_price) -> dict:
    """
    POST /fapi/v1/order (STOP_MARKET) — pasang SL order di exchange
    """
```

Semua fungsi HARUS cek `LIVE_TRADING=true` dulu sebelum mengirim ke Binance.
Jika `LIVE_TRADING=false` → log saja, jangan kirim.

### LT3: Tambah `binance_order_id` ke `PaperTrade` model
```python
binance_order_id:   Mapped[str | None] = mapped_column(String, nullable=True)
binance_avg_price:  Mapped[float | None] = mapped_column(Float, nullable=True)
binance_qty:        Mapped[float | None] = mapped_column(Float, nullable=True)
real_trade:         Mapped[bool] = mapped_column(Boolean, default=False)
```

Migration di `database.py _migrate_columns()`.

### LT4: Integrasi `auto_trader.py`
Setelah insert `PaperTrade`, tambah:
```python
if settings.live_trading and order_executor:
    result = await order_executor.open_position(...)
    trade.binance_order_id  = result["order_id"]
    trade.binance_avg_price = result["avg_price"]
    trade.binance_qty       = result["qty"]
    trade.real_trade        = True
    await session.commit()
```

### LT5: Integrasi `monitor.py`
Setelah deteksi TP/SL hit, tambah:
```python
if trade.real_trade and trade.binance_qty:
    await order_executor.close_position(symbol, direction, qty)
```

### LT6: Testnet Verification (2 minggu)
- Jalankan `LIVE_TRADING=true`, `BINANCE_TESTNET=true`
- Verifikasi: setiap paper trade punya `binance_order_id`
- Verifikasi: posisi benar-benar muncul di Binance testnet dashboard
- Verifikasi: TP/SL trigger menutup posisi di testnet

---

## Phase 2 — Live dengan Akun Real (micro sizing)

### LT7: Risk Gate untuk Live Trading
Tambah hardcoded limit yang TIDAK bisa diubah via UI:
```python
MAX_LIVE_RISK_PER_TRADE_USDT = 5.0     # max $5 per trade saat mulai
MAX_LIVE_CONCURRENT_POSITIONS = 3       # max 3 posisi real sekaligus
MAX_LIVE_DAILY_LOSS_USDT = 20.0         # circuit breaker harian $20
```

### LT8: Balance Reconciliation
Setiap cycle monitor, sync balance dari Binance:
```python
GET /fapi/v2/account → totalWalletBalance, totalUnrealizedProfit
```
Simpan di `PaperBalance` table (gunakan yang sudah ada) dengan flag `is_real=True`.

### LT9: Frontend Alert System
- Banner merah jika `LIVE_TRADING=true` — jelas terlihat
- Tampilkan `real_trade` badge di setiap posisi card
- Monitor Stats: pisah kolom "Paper" vs "Real"

### LT10: Emergency Kill Switch
Endpoint: `POST /api/v1/futures/emergency/close-all`
- Tutup semua posisi real sekaligus via Binance MARKET order
- Hanya bisa dipanggil dengan admin secret header
- Log semua action ke tabel `emergency_log`

---

## Phase 3 — Full Live (jika Phase 2 sukses)

### LT11: Trailing Stop di Exchange
Gunakan Binance native `TRAILING_STOP_MARKET` order type
(saat ini trailing dihandling di monitor.py secara software — rentan delay)

### LT12: Partial TP (TP1 sell, hold TP2)
Saat harga hit TP1: close 50% posisi via Binance, hold sisanya sampai TP2.
Saat ini TP1 hanya memperluas SL, tidak menutup partial.

### LT13: Fee-Adjusted P&L
Binance Futures fee: 0.02% maker / 0.05% taker.
Sertakan fee dalam kalkulasi `pnl_dollar` untuk win rate yang lebih akurat.

### LT14: ML Signal Optimizer (agents/learning/)
Gunakan win rate yang sudah terbukti untuk:
- Auto-tune bobot sinyal per regime (sudah ada skeleton `strategy_optimizer.py`)
- Backtest ulang dengan fee dan slippage yang realistis
- A/B test config baru vs config lama

---

## Urutan Prioritas

```
[SEKARANG]    Paper trading → kumpulkan 100+ trades
     ↓
[PHASE 1]     Testnet integration → LT1 → LT6
     ↓
[PHASE 2]     Live micro ($5/trade) → LT7 → LT10
     ↓
[PHASE 3]     Full live + ML optimizer → LT11 → LT14
```

---

## File yang Perlu Dibuat (Phase 1)

| File | Deskripsi |
|------|-----------|
| `agents/futures/order_executor.py` | Binance order placement + management |
| `agents/futures/balance_sync.py` | Sync wallet balance dari Binance |
| `backend/app/api/v1/live_trading.py` | Kill switch + live status endpoints |

## File yang Perlu Dimodifikasi (Phase 1)

| File | Perubahan |
|------|-----------|
| `agents/futures/auto_trader.py` | Tambah `order_executor.open_position()` call |
| `agents/futures/monitor.py` | Tambah `order_executor.close_position()` call |
| `backend/app/models/paper_trade.py` | Tambah `binance_order_id`, `real_trade` kolom |
| `backend/app/database.py` | Migrate kolom baru |
| `backend/app/config.py` | Tambah `LIVE_TRADING`, `BINANCE_TESTNET` settings |
| `frontend/src/features/history/` | Badge "Real" vs "Paper" di posisi |

---

## Catatan Risiko

- **Jangan skip testnet phase** — bahkan $1 loss real karena bug lebih buruk dari 2 minggu delay
- **Fee itu nyata**: 0.05% taker × 2 (open+close) = 0.1% per round trip. Trade kecil < $50 notional bisa habis di fee
- **Slippage**: Binance Futures likuid tapi coin kecil bisa 0.2-0.5% slippage saat open market order
- **Funding rate**: posisi long saat funding negatif = bayar funding tiap 8 jam. Monitor ini sudah ada (monitor.py)
- **API rate limit**: Binance limit 1200 weight/menit untuk signed requests. Saat ini scanner pakai ~941 weight/scan (public) — aman. Tapi order placement menambah signed request weight
