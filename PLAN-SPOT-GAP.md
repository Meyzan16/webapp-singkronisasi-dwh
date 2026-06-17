# PLAN — Spot Top Gainer: Tangkap Koin Naik Puluhan-Ratusan % dengan Return Maksimal

**Tanggal analisis**: 2026-06-16
**Konteks awal**: Screenshot menunjukkan posisi terbuka cuma LINK & XAUT (skor 99, setup BB Squeeze). User bertanya kenapa koin-koin yang naik puluhan persen dalam 1 minggu tidak pernah ditemukan oleh scanner/monitor Spot.
**Tujuan akhir (diperjelas user)**: bukan cuma "perbaiki bug", tapi **dapatkan top gainers SPOT (puluhan-ratusan %) dengan return maksimal**. Ini mengubah arah plan dari "patch scanner existing" jadi "bangun lane baru yang dirancang khusus untuk tujuan ini" — lihat [Strategi Baru](#strategi-baru--top-gainer-hunter-lane-terpisah-untuk-return-maksimal) di bawah.

**Catatan penting**: `agents/opportunity/monitor.py` **tidak melakukan discovery** — dia cuma mengelola posisi yang SUDAH terbuka (trail SL, TP partial, risk-adjusted close). Semua logic "menemukan koin baru" ada di `agents/opportunity/scanner.py::_score_symbol()` dan `run_opportunity_scan()`. Jadi root cause 100% ada di scanner, bukan monitor.

---

## Root Cause

### RC-1: Hard skip RSI(4h) > 82 — koin hilang TOTAL, bukan cuma turun skor

```python
# scanner.py — _score_symbol()
d4h_rsi = tf_data["4h"].rsi if "4h" in tf_data else None
if d4h_rsi is not None and d4h_rsi > 82:
    return None   # skip total — jangan tampil sebagai rekomendasi pun
```

Koin yang naik puluhan persen dalam seminggu hampir pasti RSI(4h)-nya berada di 70-90 selama proses itu — bahkan saat sedang konsolidasi/pause, karena RSI 14-period di TF 4h ≈ 2.3 hari, belum sempat "cooling" penuh. `return None` di sini berarti koin itu **tidak pernah muncul** sebagai rekomendasi manual sekalipun — bukan cuma gagal auto-open.

### RC-2: RSI(4h) 75-82 → penalty -15 pts (penalty terbesar di sistem)

```python
if d4h_rsi is not None and d4h_rsi > 75:
    score -= 15
```

Kalau tidak full-skip, penalty -15 ini adalah yang TERBESAR di seluruh scoring (lebih besar dari bonus apa pun kecuali BB Squeeze 35pt).

### RC-3: Tidak ada sinyal "change 7 hari" sama sekali

Scanner hanya kenal:
- `change_24h` — dari `ticker.priceChangePercent` (24 jam, bawaan Binance)
- `change_1h` — dihitung manual dari klines 1h

**Tidak ada `change_7d` di mana pun.** Padahal data klines 4h ditarik 100 candle (`CANDLE_LIMIT=100`) = ~16 hari history — datanya SUDAH ada di memory, cuma tidak pernah dipakai untuk menghitung performa mingguan. Sistem tidak punya cara untuk bilang "koin ini +40% minggu ini" — satu-satunya yang dia tahu adalah grak gerak 24 jam terakhir.

### RC-4: Discovery koin di luar top-100 volume cuma pakai gate 24h, bukan mingguan

```python
# R7: Momentum priority supplement
momentum_supplement = sorted(
    [t for t in tickers[100:] if float(t.get("priceChangePercent", 0)) >= MOMENTUM_SCAN_MIN_PCT],
    ...
)[:MOMENTUM_SCAN_EXTRA]
```

Koin kecil yang sempat moon 30-40% lalu sekarang sepi (1-2% hari ini) — volume sudah turun balik dari top-100 by volume, DAN gagal gate `change_24h ≥ 5%` juga. Akibatnya koin itu **tidak pernah ditarik datanya sama sekali**, apalagi di-score. Ini blind spot paling parah — bukan cuma "skor rendah", tapi "tidak pernah dilihat".

### RC-5: Penalty change_24h > 20% (-10 pts) — versi ringan dari bug Futures Agent1

```python
elif change_24h > 20:
    score -= 10
    signals.append(f"⚠️ Sudah naik {change_24h:.1f}% (entry terlambat?)")
```

Tidak separah Futures (yang stacking sampai -40), tapi tetap menambah beban di atas RC-1/RC-2 untuk koin yang TODAY masih bergerak besar.

### RC-6: "Momentum Chase" (R8) cuma lihat jendela 24 jam, bukan mingguan

```python
if change_24h >= MOMENTUM_CHASE_MIN_24H:  # 10.0
    ...
    rsi_cooling  = 45 <= d1h.rsi <= 65
    ema_holding  = d1h.ema9 > d1h.ema21 * 0.99
```

Mode ini didesain UNTUK skenario "sudah naik, sekarang pullback sehat, siap second leg" — persis yang user maksud. Tapi gate-nya `change_24h >= 10` (24 JAM), bukan mingguan. Koin yang pump besar di hari ke-2/3 minggu ini lalu flat 2 hari terakhir (change_24h kecil) **tidak akan pernah trigger mode ini**, padahal itu setup continuation paling sehat yang justru ingin dicari sistem.

### RC-7 (temuan sampingan, di luar pertanyaan inti): XAUT tidak di-blacklist di Spot

Futures punya `_COMMODITY` blacklist (PAXG, XAUT, XAU, dst) dengan komentar eksplisit "instrumen ini tidak respon ke sinyal TA crypto (Wyckoff/EMA/BB)". Spot scanner **tidak punya exclude list yang sama** — `STABLECOIN_BLACKLIST` cuma berisi stablecoin/wrapped token, tidak ada token komoditas. Terlihat di screenshot: posisi XAUT/USDT dibuka pakai BB Squeeze + taker-ratio yang didesain untuk crypto, bukan emas tokenized. Ini inkonsistensi antara dua scanner yang seharusnya sama prinsipnya.

---

## Simulasi Matematis

Koin hipotetis: naik 35% dalam seminggu, sekarang konsolidasi flat 2 hari terakhir.

```
EMA Alignment (uptrend masih jalan)                     : +10
Multi-TF bullish bonus                                   : +5
Taker buy ratio (masih ada minat beli, ~58%)             : +10
RSI(4h) ≈ 78 (belum cooling penuh dari pump minggu ini)  : −15
BB Squeeze?  TIDAK ADA — baru habis trending, BB lebar    : +0
Momentum 24h (today flat ±2%, di luar 3-20% band)        : +0
Momentum Chase (R8)? GAGAL — change_24h jauh < 10        : +0
─────────────────────────────────────────────────────────
TOTAL ≈ +10 pts  →  JAUH di bawah MIN_SCORE 65  ❌
```

Kalau RSI(4h) sempat tembus 82 di titik manapun saat scan jalan → `return None`, koin hilang total dari hasil, bahkan tidak tercatat sebagai "ditolak" (tidak ada visibility sama sekali, beda dengan Futures yang sudah punya Big Movers panel).

---

## Strategi Baru — "Top Gainer Hunter" (Lane Terpisah untuk Return Maksimal)

### Kenapa lane terpisah, bukan patch `scanner.py` existing?

`scanner.py` existing (Opportunity Spot) dituning serius untuk filosofi "cari SEBELUM naik, disiplin R:R, TP dibatasi" — komentar `§12.1`, `§14.5`, `§14.7`, dst menunjukkan banyak iterasi tuning dari pengalaman nyata. Tujuan user sekarang BEDA: bukan "perbaiki yang ada", tapi **strategi baru yang fokus nangkap top gainer dengan return maksimal**. Kalau dipaksa satu scanner, dua filosofi ini akan tarik-menarik (reward besar utk koin naik vs penalty besar utk koin naik) dan merusak tuning yang sudah jalan baik untuk lane akumulasi.

**Rekomendasi**: bangun lane baru `opportunity_gainer` — paralel dengan `opportunity_spot`, wallet terpisah, scoring terpisah, exit logic terpisah. Sama seperti Futures yang punya 3 lane (Pre-Gainer/Accumulation/Momentum) berbagi 1 wallet — bedanya di sini saya rekomendasikan WALLET TERPISAH karena Spot tidak pakai leverage/cross-margin sehingga tidak ada alasan teknis untuk berbagi modal, dan supaya performa strategi agresif ini bisa dipantau murni tanpa campur dengan lane konservatif.

### 1. Discovery — universe dari % gain langsung, bukan dari volume

```python
# Ambil SEMUA ticker 24hr, sort langsung by priceChangePercent — ranking
# "Top Gainers" asli, bukan "top volume yang kebetulan naik"
gainers_24h = sorted(tickers, key=lambda t: float(t["priceChangePercent"]), reverse=True)

# + hitung change_7d dari klines 4h (42 candle mundur) untuk SEMUA kandidat —
# menangkap koin yang pump-nya sudah terjadi tapi belum cooling penuh
```

Threshold likuiditas direlaksasi dibanding lane akumulasi (mis. $1-2M, bukan $5M) — top gainer baru sering likuiditasnya baru terbentuk dari volume spike, belum punya histori volume besar.

### 2. Scoring — dibalik total dari lane akumulasi

| Sinyal | Lane Akumulasi (existing) | Lane Top Gainer (baru) |
|---|---|---|
| `change_24h` besar | Penalty −10 (>20%) | **Bonus bertingkat** — semakin besar semakin tinggi (dengan cap wajar untuk hindari FOMO di puncak parabolic) |
| `change_7d` | Tidak ada sinyal ini | **Sinyal utama** — ini yang mendefinisikan "top gainer minggu ini" |
| RSI(4h) tinggi | Skip total (>82) / penalty −15 | Bukan filter keras — dipakai mendeteksi **divergence** (RSI menurun saat price masih naik = waspada exhaustion), bukan untuk membuang kandidat |
| BB Squeeze | Sinyal utama (35pt) | Tidak relevan — coin sudah breakout, BB lebar itu memang seharusnya begitu |
| Breakout di atas resistance | +15 kalau BARU mendekati | Bonus kalau SUDAH tembus & bertahan di atasnya ("clear air", tidak ada resistance dekat) |
| Volume | Penting — volume nyata bukan wash trading | Sama pentingnya, bobot dipertahankan |

### 3. Exit logic — bagian PALING PENTING untuk "return maksimal"

Lane akumulasi existing pakai TP1/TP2/TP3 **tetap** (TP3 cap ~10%, lihat `_calc_trade_levels`). Itu cocok untuk swing kecil disiplin, tapi **membatasi upside** kalau coin lanjut ke 50-100%+ — bertentangan langsung dengan tujuan "return maksimal".

Desain baru — **trailing structure stop, tanpa TP akhir tetap**:
1. **TP1 kecil** (mis. +15-20%) → jual sebagian (20-30%) untuk amankan modal & kunci sebagian profit, sisanya tetap terbuka.
2. Setelah TP1, **SL diganti jadi trailing**: di bawah swing-low terbaru di 4h ATAU di bawah EMA21(4h), pilih mana yang lebih ketat. Setiap swing-low baru yang lebih tinggi → SL naik mengikuti (ratchet — hanya naik, tidak pernah turun).
3. **Tidak ada TP2/TP3 angka tetap** — posisi terus berjalan selama trend utuh. Exit penuh hanya kalau:
   - SL trailing tersentuh, ATAU
   - EMA9(4h) cross di bawah EMA21(4h) — trend structure rusak, ATAU
   - RSI bearish divergence terkonfirmasi + momentum melemah tajam

Ini memungkinkan satu posisi menangkap 50%, 100%, bahkan 300%+ kalau trend-nya memang panjang — sesuai tujuan, dibanding dibatasi target 10% seperti lane akumulasi.

### 4. Risk control (tetap perlu walau filosofi agresif)

- Risk per trade **lebih kecil** dari lane akumulasi (mis. 0.5-1%, bukan 1-2%) — volatilitas per-trade jauh lebih tinggi di top gainer
- Max posisi bersamaan dibatasi (mis. 3-4) — jangan all-in di satu rejimen pump market-wide yang bisa berbalik serentak
- SL awal tetap WAJIB ada (ATR-based, lebih lebar dari lane akumulasi) — tidak pernah entry tanpa stop walau filosofinya agresif
- Blacklist coin 24h setelah 3x SL berturut — reuse pattern yang sudah ada di `weight_updater.py`/futures

### 5. Struktur kode (mengikuti pola existing)

| File baru | Peran |
|---|---|
| `agents/opportunity/gainer_scanner.py` | Discovery + scoring + trade levels khusus top-gainer |
| `agents/opportunity/gainer_monitor.py` | Monitor dengan trailing-structure-stop (beda dari `monitor.py` yang pakai TP tetap) |
| `agents/opportunity/gainer_scheduler.py` | Loop terpisah dari `scheduler.py` existing — interval & logic tidak campur |
| `backend/app/api/v1/opportunity_gainer.py` | Endpoint API (scan, positions, trade) |
| Style DB baru: `"opportunity_gainer"` | Reuse model `PaperTrade`/`PaperBalance` yang sudah generic per-style — tidak perlu migrasi schema |

**Satu perubahan kecil dibutuhkan** di `backend/app/api/v1/balance.py::compute_spot_sizing()` — saat ini hardcoded ke style `"opportunity_spot"` (baris 88-103). Perlu diparameterisasi jadi `compute_spot_sizing(score, risk_pct, style="opportunity_spot")` supaya lane baru bisa pakai sizing-engine yang sama dengan wallet berbeda. Perubahan backward-compatible, tidak mengubah behavior lane existing.

Frontend: tab/halaman baru "Top Gainer" di scanner & history — pola sama dengan filter tab Futures yang sudah ada, render via `DBHistoryTable` (sudah generic per-style) + panel baru mirip `BigMoversPanel`.

---

## Alternatif Minimal — Patch Scanner Existing (Bukan Direkomendasikan)

Kalau TIDAK ingin lane baru dan cuma mau scanner existing sedikit lebih toleran terhadap koin yang sudah naik (tanpa exit logic baru, tetap pakai TP tetap existing), berikut patch minimal S1-S6 — tapi ini **tidak akan memaksimalkan return** karena TP tetap dibatasi ~10% (lihat `_calc_trade_levels`). Disarankan hanya kalau prioritas-nya "lebih banyak sinyal masuk", bukan "return maksimal per posisi".

### S1 — Hitung `change_7d` dari klines 4h yang sudah ada `[HIGH]`

**File**: `agents/opportunity/scanner.py` — `_analyze_tf()` atau `_score_symbol()`

Data 4h sudah ditarik 100 candle. Tambahkan:
```python
change_7d = 0.0
d4h = tf_data.get("4h")
if d4h and len(d4h.closes) >= 42:   # 42 candle 4h ≈ 7 hari
    change_7d = (d4h.closes[-1] - d4h.closes[-42]) / d4h.closes[-42] * 100
```

### S2 — Relax RSI(4h) skip/penalty kalau ada bukti konsolidasi sehat `[HIGH]`

Jangan `return None` mutlak di RSI>82 — cek dulu apakah BB width 4h sedang menyempit (konsolidasi) ATAU price_slope 4h mendatar (bukan masih parabolic). Kalau iya, turunkan jadi penalty biasa (-15) bukan skip total. Sejalan dengan filosofi "Momentum Chase" yang sudah ada tapi salah jendela waktu (lihat S3).

### S3 — Perluas "Momentum Chase" (R8) pakai jendela 7 hari, bukan cuma 24h `[HIGH]`

```python
# Tambahan kondisi: trigger juga kalau change_7d besar TAPI change_24h kecil
# (artinya pump-nya sudah terjadi beberapa hari lalu, sekarang konsolidasi)
if change_7d >= 20 and abs(change_24h) <= 5:
    rsi_cooling = 40 <= d1h.rsi <= 60   # band lebih lebar karena weekly pump
    ema_holding = d1h.ema9 > d1h.ema21 * 0.98
    if rsi_cooling and ema_holding:
        score += 15
        entry_mode = "weekly_continuation"
        signals.append(f"📅 Weekly momentum +{change_7d:.1f}%, konsolidasi sehat — siap continuation")
```

### S4 — Tambah koin ke universe scan berdasar `change_7d`, bukan cuma `change_24h` `[MED]`

Perluas R7 momentum supplement: ambil juga koin di luar top-100 volume yang `change_7d >= 15%` meski `change_24h` kecil hari ini — supaya koin yang sudah "selesai moon" minggu ini tapi sekarang sepi tetap ditarik datanya dan di-score (sekarang dia tidak pernah ditarik sama sekali).

### S5 — Tambah Big Movers panel versi Spot (mirror Futures P4) `[MED]`

Sama seperti `BigMoversPanel.tsx` di Futures — tampilkan koin dengan `change_7d` besar yang TIDAK lolos scoring, beserta alasannya (RSI overbought, bukan momentum chase karena gate 24h, dst). Supaya user bisa lihat sendiri kenapa koin tertentu tidak masuk, bukan cuma "hilang diam-diam".

### S6 — Tambah token komoditas (XAUT, PAXG, dst) ke blacklist Spot `[LOW]`

Samakan dengan `_COMMODITY` set di `agents/futures/data.py::fetch_top100_futures()` — token-token ini tidak merespons sinyal TA crypto, harus dikeluarkan dari universe Spot juga.

---

## Apa yang SUDAH BENAR (Tidak Perlu Diubah)

- **MIN_QUOTE_VOLUME filter ($5M)** — benar, supaya rekomendasi tetap eksekutable
- **STABLECOIN_BLACKLIST** — benar untuk stablecoin/wrapped token (kecuali commodity, lihat S6)
- **R8 Momentum Chase EXISTS** — arsitekturnya sudah benar untuk kasus "sudah naik, sekarang sehat", cuma jendela waktunya salah (24h, bukan 7d) — S3 memperbaiki ini, bukan membangun dari nol
- **Regime gate BTC (§12.5)** — tidak perlu diubah, di luar scope masalah ini

---

## Urutan Implementasi — Jalur Direkomendasikan (Lane Baru "Top Gainer Hunter")

```
G1  change_7d helper + discovery by-%-gain  → fondasi data, dipakai G2-G5
G2  gainer_scanner.py (scoring + universe)  → core discovery & ranking
G3  trade-levels TP1-partial + trailing SL  → bagian PALING penting utk return maksimal
G4  gainer_monitor.py (trailing structure)  → eksekusi exit logic G3
G5  gainer_scheduler.py + wallet terpisah   → jalankan loop, balance.py parameterized
G6  backend/api/v1/opportunity_gainer.py    → endpoint
G7  frontend tab "Top Gainer" + history     → terakhir, tidak blocking backend
```

## Urutan Implementasi — Jalur Alternatif Minimal (Patch S1-S6 di atas)

```
S1 (hitung change_7d)         → fondasi data untuk S2/S3/S4
S2 (relax RSI skip)            → quick win, low risk
S3 (Momentum Chase 7d window)  → dampak terbesar, butuh S1 dulu
S4 (universe expansion 7d)     → butuh S1 dulu, paralel dengan S3
S5 (frontend Big Movers Spot)  → terpisah, tidak blocking backend
S6 (commodity blacklist)       → quick win, tidak terkait yang lain
```
