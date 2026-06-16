# PLAN — Signal Gap & SL Analysis (Futures)

**Tanggal**: 2026-06-15 — 2026-06-16
**Konteks gabungan**:
1. Screenshot 112 koin Big Movers >10% 24h (EVAA +114%, CLO +61%, JTO +43%, dst) — 0 yang masuk posisi terbuka.
2. Screenshot 10 trade futures — 4 SL Hit, 1 SL+ Profit, 5 Open. User minta cek apakah ada bug "trend reversal" yang membalik posisi profit jadi SL.

**Status implementasi**: ✅ Bagian 1 (P1-P5) dan Bagian 2 (F1-F4) selesai dikerjakan 2026-06-16 — lihat status detail di akhir masing-masing bagian.

---

# BAGIAN 1 — Kenapa Gainers Tidak Masuk Posisi

## Root Cause

### RC-1: Agent 3 ceiling terlalu rendah — blind spot >25% change

Agent 3 (Momentum) adalah satu-satunya agent yang seharusnya menangkap koin yang sudah bergerak. Tapi scoring-nya:

```python
# agent3.py — _score_momentum_long()
if 8 <= change_24h <= 12:   score += 20   # sweet spot
elif 5 <= change_24h < 8:   score += 12
elif 12 < change_24h <= 18: score += 15
elif 18 < change_24h <= 25: score += 8
# >25% → TIDAK ADA poin positif

# Penalties (terpisah, stacking):
if change_24h > 25.0: score -= 15    # overextended
if change_24h > 35.0: score -= 25    # parabolic ← stacking dengan yang atas
```

Hasil matematis untuk koin-koin di screenshot:

| Koin | 24h Change | Poin change | Penalty change | Net |
|------|-----------|-------------|----------------|-----|
| EVAA | +114% | 0 | −15 −25 = −40 | **−40** |
| CLO  | +61%  | 0 | −15 −25 = −40 | **−40** |
| JTO  | +43%  | 0 | −15 −25 = −40 | **−40** |
| BSB  | +37%  | 0 | −15 −25 = −40 | **−40** |
| ZRO  | +30%  | 0 | −15           | **−15** |
| WLD  | +23%  | +8 | 0            | **+8** |
| EIGEN| +18%  | +15 | 0           | **+15** |

Untuk EVAA +114%: butuh 95 pts dari sinyal lain (vol+OI+RSI+breakout) dengan max ~65 pts → **mustahil lolos threshold 55**.

### RC-2: RSI overbought penalty menambah beban

Koin yang sudah naik 30%+ biasanya RSI 1h = 75-90. Agent 3 menambah penalty:
```python
if rsi_val > 80: score -= 15    # overbought
elif rsi_val > 75: score -= 8
```

Koin di +30% 24h: sudah −15 dari change + −8 sampai −15 dari RSI = **total −23 sampai −30 sebelum sinyal positif apapun**.

### RC-3: Volume timing mismatch

Koin seperti EVAA +114% artinya volumenya surge 12-20 jam yang lalu. Candle 1h saat scanner jalan bisa menunjukkan volume yang sudah turun dari peak. `_volume_momentum()` mensyaratkan current candle > 2.5× average 20-candle — ini bisa gagal kalau momen volume surge sudah lewat.

### RC-4: Agent 1 dan 2 memang sengaja tidak masuk (by design)

```python
# agent1.py — _score_pregainer()
if change_24h > 15: score -= 25  # already pumped = missed the move

# agent2.py — _score_accumulation()
if change_24h > 12: score -= 20  # already in markup — dangerous late entry
```

Ini **benar dan correct** secara design — A1/A2 memang mencari SEBELUM gerakan. Yang menjadi masalah adalah A3 tidak cukup lebar untuk mengganti peran ini.

### RC-5: Tidak ada sinyal 1h/4h change

`change_24h` dari ticker Binance adalah perubahan 24 jam penuh. Tapi EVAA +114% 24h yang saat ini −3% dalam 1 jam terakhir = kondisi yang SAMA SEKALI berbeda (pullback setelah momentum, bukan chase parabolic). Scanner tidak membedakan ini.

---

## Plan Perbaikan

### P1 — Extend Agent 3 ceiling ke 50% `[HIGH]`

**File**: `agents/futures/agent3.py` — `_score_momentum_long()` dan `_score_momentum_short()`

**Perubahan scoring change_24h**:
```python
# SEKARANG:
elif 18 < change_24h <= 25: score += 8
# >25% → 0 poin + penalty -15 + penalty -25 jika >35%

# BARU:
elif 18 < change_24h <= 25: score += 8
elif 25 < change_24h <= 35: score += 5   # extended momentum, masih ada room
elif 35 < change_24h <= 50: score += 2   # high-risk extended, tapi tetap trackable

# Revisi penalty (non-stacking):
if change_24h > 50.0:   score -= 20   # parabolic >50% → exit risk tinggi
elif change_24h > 35.0: score -= 8    # extended, tapi tidak as harsh
elif change_24h > 25.0: score -= 5    # sedikit extended
```

**Impact**: Koin ZRO +30%, BASED +28%, UAI +29% bisa dapat score positif dan berpotensi lolos threshold.

---

### P2 — Hitung dan gunakan `change_1h` dari klines `[HIGH]`

**File**: `agents/futures/agent3.py`

Tambahkan kalkulasi 1h change langsung dari klines yang sudah difetch:
```python
# Di _score_momentum_long(), setelah ref = d1h or d4h or d15:
change_1h = 0.0
if d1h and len(d1h.closes) >= 5:
    change_1h = (d1h.closes[-1] - d1h.closes[-4]) / d1h.closes[-4] * 100

# Gunakan sebagai modifier:
# Koin +60% 24h tapi −3% 1h = pullback setelah momentum (masih ok untuk entry)
# Koin +60% 24h dan +5% 1h = masih parabolic (lebih berisiko)
if change_24h > 25 and change_1h < -2:
    score += 8   # pullback setelah big move = lebih aman dari chase
elif change_24h > 25 and change_1h > 3:
    score -= 5   # masih naik kencang = chase risk
```

---

### P3 — Mode "Pullback-to-Momentum" di Agent 3 `[MED]`

**File**: `agents/futures/agent3.py`

Untuk koin yang naik 30-80% 24h dan saat ini dalam fase pullback (15m candle merah 3 berturut-turut), ini adalah **re-entry setelah momentum** = setup yang lebih aman dari pure chase.

```python
# Di _score_momentum_long(), setelah change_24h scoring:
# Deteksi pullback di 15m
pullback_entry = False
if d15 and len(d15.closes) >= 5:
    last_3_change = (d15.closes[-1] - d15.closes[-3]) / d15.closes[-3] * 100
    if change_24h > 25 and -8 <= last_3_change <= -2:
        # Big move 24h + 15m pullback = ideal re-entry zone
        score += 10
        pullback_entry = True
        signals.append(f"📉 Pullback {last_3_change:.1f}% setelah momentum +{change_24h:.1f}% — re-entry zone")
```

---

### P4 — Panel "Big Movers Monitor" di frontend `[MED]`

**File baru**: `frontend/src/features/scanner/components/BigMoversPanel.tsx`

Tampilkan daftar koin >10% 24h sebagai panel informasional (bukan auto-open). Tunjukkan:
- Symbol, change_24h, funding rate, OI change
- Alasan kenapa tidak masuk posisi (score breakdown singkat)
- Status: "Terlalu tinggi untuk entry", "RSI overbought", dll.

Data source: endpoint baru `GET /api/v1/futures/big-movers` (serve dari market ticker yang sudah difetch saat scan).

---

### P5 — RSI adaptive ceiling pada strong momentum day `[LOW]`

**File**: `agents/futures/agent3.py`

Saat market sedang strong bullish (BTC +5%+ 24h), RSI 75-80 masih valid untuk momentum entry. Tambahkan regime modifier:

```python
# Di _score_momentum_long(), setelah RSI scoring:
if regime == "trending_up" and rsi_val > 75:
    # Relax overbought penalty saat pasar trending kuat
    score += 5   # offset sebagian penalty RSI overbought
```

---

## Apa Yang SUDAH BENAR (Tidak Perlu Diubah)

- **A1 dan A2 penalty untuk koin yang sudah naik** → ini benar, pre-gainer harus cari SEBELUM gerakan
- **Agent 3 MIN_SCORE = 55** → threshold ini baik untuk filter kualitas
- **RSI overbought basic penalty** → tetap dipertahankan, hanya direlaksasi saat trending
- **R:R ≥ 1:3 enforcement** → tidak perlu diubah

---

## Urutan Implementasi (Bagian 1)

```
P1 (extend ceiling A3)   → paling cepat, paling besar dampaknya
P2 (change_1h)           → setelah P1, data sudah tersedia di klines
P3 (pullback mode)       → bisa jalan bersamaan dengan P2
P4 (frontend panel)      → terpisah, tidak blocking backend
P5 (RSI adaptive)        → last, setelah P1-P3 terbukti meningkatkan catch rate
```

## Metrik Sukses (Bagian 1)

Setelah implementasi P1+P2 — perlu dipantau langsung di scanner live (belum bisa diverifikasi backtest, butuh data pasar real):
- [ ] Dari 112 Big Movers >10%, minimal 5-10 koin lolos scoring Agent 3
- [ ] Koin di range 20-40% change muncul di scanner dengan score 55+
- [ ] Win rate Agent 3 tidak turun (extended entry masih profitable)
- [ ] Tidak ada posisi yang auto-open di koin >40% tanpa pullback konfirmasi (P3 guard)

## Status Implementasi (Bagian 1)

Dikerjakan 2026-06-16. Semua item P1-P5 sudah masuk kode:

| Item | File | Status |
|---|---|---|
| P1 — ceiling 50% + penalty non-stacking | `agents/futures/agent3.py` (`_score_momentum_long` & `_score_momentum_short`) | ✅ |
| P2 — `change_1h` modifier | `agents/futures/agent3.py` | ✅ |
| P3 — pullback-to-momentum (15m) | `agents/futures/agent3.py` | ✅ |
| P4 — Big Movers Monitor panel | `agents/futures/store.py`, `agents/futures/scheduler.py` (`_build_big_movers`), `backend/app/api/v1/futures_scanner.py` (`GET /futures/big-movers`), `frontend/src/features/scanner/components/BigMoversPanel.tsx` | ✅ |
| P5 — RSI adaptive ceiling per regime | `agents/futures/agent3.py` (LONG: `trending_up`, SHORT mirror: `trending_down`) | ✅ |

**Verifikasi yang sudah dilakukan**:
- `python -m py_compile` bersih untuk semua file backend yang diubah.
- `tsc --noEmit` bersih untuk frontend.
- Sanity-check skor manual: simulasi koin "EVAA-like" +114% (dengan pullback 1h/15m) sekarang dapat skor **+15** (dulu **−40 sampai −55**, mustahil lolos). Simulasi "ZRO-like" +30% dapat skor **+35** (dulu **−15**).
- Next.js dev server jalan bersih di `/scanner` dengan panel baru terpasang, tidak ada runtime error (backend API belum jalan saat tes, panel return `null` secara graceful kalau fetch gagal/kosong).
- **Belum diverifikasi**: apakah skor ini benar-benar lolos `MIN_SCORE=55` pada data pasar real (butuh sinyal volume/OI/RSI/breakout asli, tidak bisa disimulasikan offline). Perlu dipantau di scanner live setelah deploy.

---

# BAGIAN 2 — Analisa Banyak SL & Cek Bug "Trend Reversal"

**Konteks**: Screenshot 10 trade futures — 4 SL Hit (SPX -3.00%, XAG -1.60%, AMD -1.60%, SAMSUNG -0.10%), 1 SL+ Profit (QNTX +2.15%), 5 masih Open.

## Jawaban Langsung: Apakah Ada Bug "Trend Reversal" yang Membalik Profit jadi SL?

**TIDAK ADA bug seperti itu di futures monitor** — karena mekanisme "trend reversal smart-exit" itu **tidak pernah diimplementasikan untuk futures sama sekali**.

`agents/futures/monitor.py:401-424` — futures position HANYA bisa ditutup oleh 4 jalur:
1. `sl_hit` / `sl_plus` — harga benar-benar menyentuh level SL (termasuk trailing SL)
2. `tp2_hit` — harga menyentuh TP2 (atau TP3 setelah extension, tapi reason string tetap tertulis `tp2_hit` — lihat Temuan #2)
3. `liq_guard` — guard otomatis dekat liquidasi
4. `max_age_expired` / `stagnant_48h` — posisi terlalu lama/stagnan

Tidak ada logic yang menutup posisi karena "RSI tinggi", "EMA cross turun", atau "taker ratio rendah" — itu semua HANYA ada di `agents/opportunity/monitor.py:243-258` (monitor untuk SPOT, bukan futures):

```python
if entry_ema_bullish and ema9 < ema21 * 0.998 and pnl_net >= profit_floor:
    return "trend_reversal"
if rsi > 80 and pnl_net >= profit_floor:
    ...
    return "profit_protection"
if taker < 0.38 and pnl_net >= profit_floor:
    return "flow_reversal"
if rsi > 75 and pnl_gross < -2:
    return "risk_adjusted"
```

**Kesimpulan**: posisi futures yang kena SL itu murni karena harga **benar-benar** bergerak melewati level stop loss (atau trailing stop yang sudah naik). Bukan bug — itu cara kerja stop loss yang seharusnya.

## Temuan #1 — Legenda di Frontend Menyesatkan (Bukan Bug Logic, Tapi Bug Tampilan)

Di `frontend/src/features/health/components/DBHistoryTable.tsx:105`, `CLOSE_REASON_META` adalah SATU dictionary yang dipakai bersama untuk SPOT dan FUTURES:

```ts
const CLOSE_REASON_META = {
  sl_hit: ..., sl_plus: ..., tp2_hit: ..., tp3_hit: ...,
  trend_reversal: ...,    // ← HANYA pernah muncul dari SPOT, never dari futures
  profit_protection: ..., // ← HANYA SPOT
  flow_reversal: ...,     // ← HANYA SPOT
  risk_adjusted: ...,     // ← HANYA SPOT
  ...
};
```

Legend yang muncul di screenshot (Trend Reversal, Profit Guard, Flow Reversal, Risk Adjusted, Opp Lost) **tidak akan pernah muncul untuk trade Futures** — itu legend dari fitur Spot yang ikut ditampilkan di tabel Futures karena keduanya pakai komponen yang sama. Ini membingungkan karena user jadi mengira ada mekanisme "trend reversal" yang aktif di futures, padahal tidak.

**Rekomendasi**: legend untuk tabel Futures sebaiknya hanya menampilkan reason yang BENAR-BENAR bisa terjadi di futures:
- `sl_hit`, `sl_plus`, `tp2_hit`, `liq_guard`, `max_age_expired`, `stagnant_48h`
- (Hapus/sembunyikan: `trend_reversal`, `profit_protection`, `flow_reversal`, `risk_adjusted`, `opportunity_lost` — itu khusus Spot)

## Temuan #2 — `tp3_hit` Legend Ada Tapi Tidak Pernah Dipakai (Cosmetic Bug)

Legend punya entry "TP3 Hit" (`tp3_hit`), tapi di kode `monitor.py:410-413`:

```python
elif eff_high >= tp2:
    new_status   = "tp"
    close_price  = tp2
    close_reason = "tp2_hit"   # ← hardcoded string, walau tp2 di sini bisa = TP3 setelah extension
```

Variabel `tp2` sebenarnya berisi `trade.take_profit`, yang BISA berubah jadi nilai TP3 setelah TP Extension (lihat bagian 4 di monitor.py, baris 532-569). Tapi reason yang dicatat selalu string literal `"tp2_hit"`, never `"tp3_hit"`. Jadi posisi yang sebenarnya kena extended-TP3 akan tetap tercatat sebagai "TP2 Hit" di histori — bukan salah secara P&L (uang yang dicatat tetap benar), tapi label di histori tidak akurat untuk membedakan trade biasa vs trade yang di-extend.

## Temuan #3 — Bug Tampilan Durasi: "10m 47d" Bukan 47 Hari!

Baris SPX: Entry `10:06:18`, Tutup `10:17:05`, Durasi tertulis **"10m 47d"**. Selisih waktu sebenarnya = 10 menit 47 **detik**, bukan 47 hari.

Bug ada di `DBHistoryTable.tsx:63-71`:

```ts
function fmtDuration(entry_at: number, closed_at: number | null): string {
  const secs = Math.floor(closed_at - entry_at);
  if (secs < 60)    return `${secs}d`;                              // ← "d" disini maksudnya detik, BUKAN hari
  if (secs < 3600)  return `${Math.floor(secs / 60)}m ${secs % 60}d`; // ← sama, harusnya label detik
  ...
  return h < 24 ? `${h}j ${m}m` : `${Math.floor(h / 24)}hr ${h % 24}j`; // ← "hr" disini = hari (benar)
}
```

Singkatan `d` dipakai dua arti berbeda dalam fungsi yang sama: untuk sisa detik (`secs % 60`) labelnya `d` (seharusnya `dtk` atau `s`), sedangkan untuk hari sebenarnya dipakai `hr`. Ini murni salah label, bukan salah hitung. **Rekomendasi**: ganti `d` jadi `dtk` (detik) di baris 66-67 supaya tidak ambigu dengan `hr` (hari).

## Analisa Kenapa Banyak SL (Bukan Soal Bug, Tapi Soal Performa)

Dari 5 trade yang sudah closed: 1 profit (QNTX +2.15%), 4 loss (SPX -3.00%, XAG -1.60%, AMD -1.60%, SAMSUNG -0.10%) → **win rate 20%** pada sampel kecil ini.

Breakdown loss-nya konsisten dengan desain sistem, bukan anomali:

| Symbol | Loss % | Penjelasan |
|---|---|---|
| AMD, XAG | -1.60% | Persis = `MIN_SL_PCT (1.5%) + fee round-trip (0.10%)`. Ini SL floor standar — harga gerak lawan arah dengan cepat sebelum trailing breakeven aktif. |
| SAMSUNG | -0.10% | Hampir 0 — ini **bukan SL penuh**, ini SL yang sudah sempat di-trail ke breakeven (entry price) lalu price reversal kecil. Rugi yang tercatat murni cuma fee, bukan rugi posisi. |
| SPX | -3.00% | Lebih besar dari floor 1.5% — kemungkinan SL-nya lebih lebar karena ATR coin ini tinggi (`min_sl_pct = max(1.5, atr_pct*0.8)`), jadi risk per trade lebih besar dari biasanya. |

**Catatan penting**: SAMSUNG -0.10% itu sebenarnya kasus **"breakeven stop"** — bukan kerugian riil, cuma kena fee. Tapi di UI, statusnya sama-sama merah "SL Hit" seperti AMD yang rugi -1.60% penuh. Tidak ada pembeda visual antara "SL kena di breakeven" (rugi minimal) vs "SL kena di level asli" (rugi penuh 1.5%+). Ini bikin "4 SL" kelihatan lebih buruk dari realitanya — salah satu dari 4 itu nyaris tidak rugi.

Dengan sampel cuma 5 trade closed, 20% win rate **belum bisa disimpulkan sebagai masalah sistemik** — R:R 1:3 secara teori cuma butuh ~25% win rate buat breakeven, dan 5 data point terlalu sedikit untuk statistik yang valid. Perlu pantau lebih banyak trade (30-50+) sebelum menyimpulkan ada masalah scoring/entry.

## Rekomendasi Tambahan Legenda (Untuk Tabel Futures saja)

| Reason key | Label usulan | Kapan terjadi |
|---|---|---|
| *(baru)* `breakeven_stop` | "Breakeven Stop" (abu-abu, bukan merah) | Saat SL Hit tapi `trail_active=True` dan harga close ≈ entry (rugi cuma fee, bukan rugi posisi) — beda dari `sl_hit` biasa |
| *(perbaikan)* `tp3_hit` | sudah ada di legend, tapi backend perlu benar-benar menulis string `"tp3_hit"` saat TP yang kena adalah hasil extension, bukan selalu `"tp2_hit"` |

## Ringkasan (Bagian 2)

1. ❌ **Tidak ada bug** "trend reversal membalik profit jadi SL" di futures — mekanisme itu tidak ada di futures monitor, cuma ada di spot.
2. ⚠️ **Bug tampilan**: legend Futures ikut menampilkan reason yang cuma berlaku untuk Spot (trend_reversal, profit_protection, flow_reversal, risk_adjusted, opportunity_lost) — membingungkan.
3. ⚠️ **Bug cosmetic**: `tp3_hit` tidak pernah benar-benar ditulis ke DB, selalu `tp2_hit` walau TP sudah di-extend ke TP3.
4. ⚠️ **Bug label durasi**: "47d" di durasi singkat itu seharusnya "47 detik", bukan "47 hari" — salah singkatan, bukan salah hitung.
5. ℹ️ **4 SL dari 5 closed** konsisten dengan desain (1.5% SL floor + fee), satu di antaranya (SAMSUNG -0.10%) malah breakeven stop yang nyaris tidak rugi. Sampel terlalu kecil untuk menyimpulkan ada masalah sistemik di scoring/entry.

## Status Implementasi (Bagian 2)

Dikerjakan 2026-06-16. Semua item F1-F4 sudah masuk kode:

| Item | File | Status |
|---|---|---|
| F1 — legend per-scope (spot vs futures) | `frontend/src/features/health/components/DBHistoryTable.tsx` (`CLOSE_REASON_META` + prop `reasonScope`), call sites di `OverviewTab.tsx` (`reasonScope="futures"`) dan `OppSpotTab.tsx` (`reasonScope="spot"`) | ✅ |
| F2 — `tp3_hit` ditulis benar saat TP extension | `agents/futures/monitor.py` — `close_reason = "tp3_hit" if meta.get("tp_extended") else "tp2_hit"` (LONG & SHORT) | ✅ |
| F3 — fix label durasi "d" → "dtk" | `frontend/src/features/health/components/DBHistoryTable.tsx` (`fmtDuration`) | ✅ |
| F4 — `breakeven_stop` reason baru | `agents/futures/monitor.py` — deteksi `trail_active` + SL persis di level entry (±0.1%), beda dari `sl_hit`/`sl_plus` | ✅ |

**Temuan tambahan saat implementasi F1** (di luar 5 item awal, ditemukan saat audit menyeluruh semua `close_reason` di kedua monitor):
- `opportunity_lost` di-grep ke seluruh backend — **tidak pernah diproduksi di mana pun**, dihapus dari legend (dead entry).
- `tp1_breakeven` dan `stagnant_rotation` (spot) serta `stagnant_48h` (futures) sudah diproduksi backend tapi **tidak ada di `CLOSE_REASON_META`** sama sekali — sebelumnya jatuh ke fallback badge mentah (`font-mono` raw string). Sekarang ditambahkan dengan label dan scope yang benar.

**Verifikasi yang sudah dilakukan**:
- `python -m py_compile` bersih untuk `monitor.py`.
- `tsc --noEmit` dan `npm run lint` bersih untuk semua file frontend yang diubah (warning/error yang muncul di lint semuanya pre-existing, tidak terkait perubahan ini).
- Next.js dev server di-curl ke halaman `/history` — HTTP 200, tidak ada error runtime di log server.
- **Belum diverifikasi**: tampilan visual aktual breakeven_stop/tp3_hit di browser (butuh trade futures sungguhan yang mengalami kondisi tersebut — tidak bisa disimulasikan tanpa DB + scanner live).

---

# Urutan Implementasi Gabungan

```
P1 (extend ceiling A3)        → Bagian 1, paling cepat & paling besar dampaknya
P2 (change_1h)                 → Bagian 1, setelah P1
F1 (fix legend futures)        → Bagian 2, quick win — pisahkan CLOSE_REASON_META per style
F2 (fix tp3_hit label)         → Bagian 2, quick win — tulis "tp3_hit" yang benar di monitor.py
F3 (fix durasi "d" → "dtk")    → Bagian 2, quick win — cosmetic, 1 baris
P3 (pullback mode)             → Bagian 1, bisa paralel dengan P2
P4 (frontend big movers panel) → Bagian 1, terpisah dari backend
F4 (breakeven_stop label baru) → Bagian 2, butuh sedikit logic baru di monitor.py
P5 (RSI adaptive)              → Bagian 1, last
```
