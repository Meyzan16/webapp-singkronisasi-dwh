# PLAN-FUTURES-REFACTOR.md — Desain Penyederhanaan Arsitektur Futures

> **Jenis dokumen:** Rancangan desain (narasi). **Tidak ada kode.**
> **Tujuan:** menyederhanakan modul Futures dari 3 scanner-agent yang tumpang tindih
> menjadi arsitektur 2-agent yang jelas: **1 Scanner** + **1 Monitor**.
>
> **Konvensi status (agar model tidak baca/kerja 2 kali):**
> - `✅ SELESAI` → sudah dikerjakan + commit. Lewati.
> - `🔧 PROSES` → sedang dikerjakan.
> - `❌ BELUM` → belum disentuh.
>
> **Status dokumen: 📐 DESAIN — belum ada implementasi.**
>
> ## ✅ KEPUTUSAN TERKUNCI (user, 2026-06-14)
> 1. **Arsitektur final: 1 agent Scanner + 1 agent Monitor.** Ketiga scanner-agent lama
>    (futures_agent1/2/3) dilebur jadi **SATU** Scanner dengan 3 lane internal. Tidak ada opsi
>    "berhenti di 2 agent" — itu menyisakan BUG-L1.
> 2. **Bug lama WAJIB ikut tertangani dalam refactor** — BUG-L1, BUG-L2, BUG-L3 dari
>    [PLAN-FUTURES-LIVE.md](PLAN-FUTURES-LIVE.md) **tidak boleh tertinggal**. Pemetaan eksplisit di §6.1.

---

## 1. Analisis Arsitektur Saat Ini

### 1.1 Yang ada sekarang

Modul futures saat ini berjalan dengan **3 scanner-agent** yang men-scan **universe yang sama**
(top-150 by volume + koin funding ekstrem), lalu **1 monitor** untuk semua posisi:

| Agent | Filosofi | change_24h | Arah |
|-------|----------|-----------|------|
| **agent1** Pre-Gainer/Pre-Dump | Cari koin SEBELUM bergerak (coiling, BB squeeze, OI naik, funding netral) | PENALTI >8% | LONG + SHORT |
| **agent2** Accumulation | Cari fase akumulasi Wyckoff SEBELUM markup (T0-T4, kompresi) | PENALTI >7% | LONG (SHORT bonus) |
| **agent3** Momentum Capture | Masuk SETELAH gerakan dimulai (volume+OI+RSI konfirmasi) | REWARD 5-20% | LONG + SHORT |

Orkestrasi ([scheduler.py:155-187](agents/futures/scheduler.py:155)): satu for-loop per ticker memanggil
`a1.scan_symbol() → a2.scan_symbol() → a3.scan_symbol()`, hasil disimpan **terpisah per agent**,
auto-open dipanggil **terpisah per agent** ([scheduler.py:262-264](agents/futures/scheduler.py:262)).

### 1.2 Masalah inti yang ditemukan

**A. Agent 1 dan Agent 2 tumpang tindih ~90%.**
Keduanya mengejar filosofi yang **identik**: "koin datar yang akan bergerak." Docstring agent2 sendiri
menyebut hasilnya *"the highest-probability pre-pump signal"* — itu **persis tujuan agent1**. Bedanya
hanya kosmetik (agent1 framing "BB squeeze", agent2 framing "Wyckoff T0-T4"). [PLAN-FUTURES.md](PLAN-FUTURES.md)
F3 sudah mencatat `agent2._calc_levels()` adalah **copy-paste 80 baris** dari agent1. Jadi nyatanya
hanya ada **2 filosofi berbeda**, bukan 3:
- "Sebelum gerakan" (agent1 = agent2)
- "Saat gerakan" (agent3)

**B. 3 agent = 3x komputasi, 3 ranking terpisah, 3 jalur auto-open.**
Karena tiap agent buka posisi independen dengan dedup **per-agent**
([auto_trader.py:122-128](agents/futures/auto_trader.py:122)), koin yang sama bisa terbuka di >1 agent
→ **BUG-L1** (ALLUSDT duplikat di Agent 1 & 2, cross-margin dobel — lihat [PLAN-FUTURES-LIVE.md](PLAN-FUTURES-LIVE.md)).
Wallet tidak pernah membandingkan "setup terbaik secara global" — tiap agent egois.

**C. Permintaan user belum terpenuhi oleh struktur sekarang:**
- **Top gainers/losers eksplisit** → tidak ada lane khusus; agent3 dekat tapi berbasis change_24h 5-20%, bukan ranking gainer/loser murni.
- **New listing** → tidak ada deteksi sama sekali (`grep` onboard/listing = kosong).
- **Market cap** → tidak ada di data layer ([data.py:34-40](agents/futures/data.py:34) hanya OHLCV+funding+OI+liq).

**D. Monitor & SL.**
Monitor sudah tunggal & sehat secara struktur, TAPI SL awal terlalu ketat (0.5-0.7% @ 12x) → **BUG-L3**,
win rate 0%. SL+ (breakeven/trail) hampir tak pernah aktif karena harga kena SL duluan.

### 1.3 Kesimpulan analisis

Sistem 3-agent adalah **over-engineering**: dua dari tiga agent mengerjakan hal yang sama. Nilai
sesungguhnya dari "multi-agent" — yaitu **atribusi win-rate per strategi** — bisa dipertahankan tanpa
3 agent terpisah, cukup dengan **menandai setiap sinyal dengan `setup_type`**. Konsolidasi ke
**1 Scanner (multi-lane) + 1 Monitor** menghilangkan duplikasi, BUG-L1 hilang by-design, dan permintaan
user (gainers/losers/new-listing) dapat tempat yang jelas.

> **Ambiguitas — SUDAH DIPUTUSKAN (terkunci):** target adalah **2 agent total** (1 Scanner + 1 Monitor),
> di mana **Scanner punya 3 lane deteksi** internal (Pre-Move / Gainers-Losers / New-Listing). Angka "3" = 3 lane,
> bukan 3 agent. Ketiga scanner-agent lama dilebur jadi satu (bukan berhenti di 2) — lihat keputusan terkunci di header.

---

## 2. Arsitektur Target: 2 Agent

```
┌─────────────────────────────────────────────────────────────┐
│  AGENT 1 — FUTURES SCANNER (penemuan peluang)                │
│  1 agent, 1 universe, 1 ranking global, 1 jalur auto-open    │
│                                                              │
│   Lane A: Pre-Move     (gabungan agent1+agent2 lama)        │
│   Lane B: Gainers/Losers (gabungan + perluas agent3 lama)   │
│   Lane C: New Listing   (BARU)                             │
│            │                                                │
│            ▼  satu daftar ranked, tiap item ber-setup_type  │
│   Dedup GLOBAL per-symbol → auto-open setup terbaik         │
└─────────────────────────────────────────────────────────────┘
                          │ posisi terbuka
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  AGENT 2 — FUTURES MONITOR (risk-adjusted return)           │
│  Satu sumber kebenaran semua posisi terbuka                 │
│   • SL floor sadar-leverage (perbaiki BUG-L3)              │
│   • Lifecycle SL+ : breakeven → trail → lock               │
│   • Metrik: size, fee, liq price, market cap, SL/SL+, TP1/2 │
│   • Manajemen risiko: heat, RAR gate, circuit breaker      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Agent 1 — Futures Scanner

### 3.1 Tanggung jawab

Memindai pasar futures dan menghasilkan **satu daftar peluang ter-ranking secara global**. Setiap
kandidat membawa label `setup_type` (`pre_move` / `gainer` / `loser` / `new_listing`) untuk atribusi
win-rate dan untuk parameter risiko yang berbeda per tipe. **Tidak ada lagi 3 daftar terpisah.**

### 3.2 Tiga lane deteksi

**Lane A — Pre-Move (gabungan agent1 + agent2 lama).**
Mengejar koin yang masih datar/coiling sebelum ledakan. Sinyal: BB squeeze di support/resistance,
volume terakumulasi dengan harga flat, OI naik stabil, funding netral/negatif (LONG) atau tinggi
(SHORT), RSI di zona sweet (40-55 LONG / 55-70 SHORT), harga dekat level breakout. Menghasilkan
LONG (pre-pump) dan SHORT (pre-dump). **Ini menyatukan dua agent yang selama ini redundan** — satu
pipeline skoring, bukan dua.

**Lane B — Gainers & Losers (perluasan agent3 lama).**
Eksplisit me-ranking **top gainers** (kandidat LONG) dan **top losers** (kandidat SHORT) dari universe,
lalu **memfilter dengan konfirmasi** agar bukan sekadar "sudah naik": volume surge searah, OI naik
bersama harga (konviksi, bukan short-squeeze kosong), funding belum overcrowded, RSI belum ekstrem,
break dari high/low terbaru. Tujuan user "momentum kuat, idealnya sebelum gerakan besar" dijembatani
di sini: gainer yang **baru** mulai (mis. +5% dengan OI/volume meledak) lebih tinggi skornya daripada
gainer yang sudah +20% (exhausted).

**Lane C — New Listing (BARU).**
Mendeteksi koin yang baru listing di Binance Futures (via `onboardDate` dari exchangeInfo). New listing
punya karakter unik: volatilitas ekstrem, belum ada struktur S/R, funding liar. Lane ini **wajib pakai
parameter risiko sendiri**: leverage rendah (≤3x), SL lebih lebar, size lebih kecil. Tanpa penanganan
khusus, new listing akan selalu kena SL ketat (memperparah BUG-L3).

### 3.3 Alur kerja

1. **Fetch universe** — top-N by volume (perlebar untuk pre-move) + koin funding ekstrem + daftar
   new-listing dari exchangeInfo.
2. **Fetch data per symbol** — OHLCV multi-TF (15m/1h/4h), funding, OI, liquidation. **Tambah market cap**
   (lihat §5 dependensi data).
3. **Skoring per lane** — tiap symbol dievaluasi oleh lane yang relevan. Satu symbol bisa memenuhi >1 lane;
   ambil skor tertinggi + setup_type-nya (jangan emit duplikat symbol).
4. **Ranking global** — gabung semua kandidat lintas lane jadi **satu daftar**, urut by skor (atau by
   EV-per-risk seperti pola spot — lebih baik karena membandingkan apel-ke-apel lintas tipe setup).
5. **Auto-open dengan dedup GLOBAL** — iterasi daftar global; skip symbol yang **sudah terbuka di posisi
   manapun** (bukan per-agent). Ini menghapus BUG-L1 secara struktural. Gate risiko (heat, RAR, circuit
   breaker) tetap berlaku sebelum buka.

### 3.4 Data/metrik yang diproses

OHLCV multi-TF, funding rate (+ rata-rata 8h), open interest + perubahan, likuidasi long/short,
change_24h, volume ratio, RSI/EMA/BB/ATR, jarak ke S/R, **market cap** (baru), **onboardDate** (baru).

### 3.5 Alasan desain

- **Hapus redundansi:** agent1≈agent2 → satu Lane A. Hemat ~⅓ komputasi, satu tempat untuk tuning.
- **Ranking global > ranking per-agent:** wallet mengalokasikan modal ke setup terbaik secara absolut,
  bukan ke "juara lokal" tiap agent. Lebih sesuai realita satu wallet cross-margin.
- **`setup_type` mempertahankan nilai multi-agent:** win-rate per strategi tetap terukur untuk
  learning/adaptive threshold, tanpa ongkos 3 agent.
- **Dedup global = BUG-L1 mati by-design**, bukan ditambal.
- **Lane C menutup permintaan new-listing** yang sebelumnya tidak ada sama sekali.

---

## 4. Agent 2 — Futures Monitor

### 4.1 Tanggung jawab

Satu sumber kebenaran untuk **semua** posisi terbuka: memantau tren, mengelola SL/SL+/TP, menghitung
metrik risiko, dan menegakkan manajemen risiko portofolio. Fokus pada **risk-adjusted return**, bukan
sekadar menang/kalah.

### 4.2 Perbaikan utama — SL tidak boleh ketat (BUG-L3)

Akar masalah: SL awal di-set scanner tanpa lantai minimum relatif leverage; 0.7% @ 12x = noise.
Desain monitor baru menegakkan **SL floor sadar-leverage**: jarak SL minimum berbanding terbalik dengan
leverage (leverage tinggi → butuh ruang napas lebih, bukan lebih sempit) **dan** menghormati ATR koin.
Jika scanner mengusulkan SL lebih ketat dari floor, monitor melebarkannya (atau scanner menolak sinyal
yang R:R-nya tak masuk setelah SL dilebarkan). New listing (Lane C) pakai floor lebih lebar lagi.

### 4.3 Lifecycle SL+ (break-even & trailing) yang jelas

Definisikan kapan SL berpindah ke profit, dan pastikan **tercapai** (dengan SL awal yang tidak ketat):
- **Breakeven:** saat harga mencapai sebagian jalan ke TP1 → SL ke entry (modal aman).
- **Trail TP1:** saat TP1 tersentuh → SL naik ke "entry + sebagian gain TP1" (kunci profit).
- **Lock:** saat harga menuju TP2 → SL naik ke TP1 (kunci profit TP1).

Dengan SL awal yang sehat (§4.2), tahap-tahap ini benar-benar bisa aktif — sekarang tidak pernah.

### 4.4 Metrik yang dipantau per posisi

Size (notional), fee (round-trip + akrual funding), **liquidation price + jarak**, **market cap**
(konteks likuiditas/risiko), SL saat ini, **status SL+** (breakeven/trail/lock), TP1/TP2/TP3 + progres,
unrealized PnL ($ dan %), hold time, kesehatan tren (EMA/RSI/taker flow), regime pasar.

### 4.5 Manajemen risiko

- **Portfolio heat:** total risiko terbuka dibatasi terhadap satu wallet (sudah ada via `compute_futures_sizing`).
- **RAR gate & circuit breaker:** pertahankan, tapi perbaiki **BUG-L2** — naikkan sampel minimum
  (5 → 10-15) agar Sharpe tidak noise; opsi de-risking (tighten SL posisi profit) saat gate aktif.
- **Stagnant/max-age:** tinjau ulang untuk futures agar tidak menutup posisi yang SL-nya baru saja
  diberi ruang napas (sinkron dengan §4.2).

### 4.6 Alasan desain

- Monitor sudah tunggal — pertahankan, fokus perbaikan ke **kualitas exit** (SL floor + SL+ lifecycle),
  karena di situlah win-rate 0% lahir.
- Memisahkan "penemuan" (Scanner) dari "pengelolaan" (Monitor) dengan tegas: Scanner tidak mengurus
  posisi hidup, Monitor tidak mencari peluang baru. Tidak ada tumpang tindih tanggung jawab.

---

## 5. Dependensi & Dampak

### 5.1 Data baru yang dibutuhkan
- **Market cap** — Binance tidak menyediakan langsung. Perlu sumber luar (mis. CoinGecko) atau proksi
  `circulating_supply × harga`. Perlu keputusan sumber + caching (jangan fetch tiap siklus).
- **onboardDate** — tersedia di `/fapi/v1/exchangeInfo` (murah, cache harian).

### 5.2 Yang dihapus/digabung
- `agent2.py` dilebur ke Lane A (Pre-Move) bersama `agent1.py`.
- `agent3.py` menjadi Lane B (Gainers/Losers), diperluas dengan ranking gainer/loser eksplisit.
- Penyimpanan hasil per-agent (`store.set_result("agent1"/"agent2"/"agent3")`) → satu daftar global
  ber-`setup_type`.
- Auto-open per-agent → satu jalur dengan dedup global.

### 5.3 Dampak ke frontend & learning
- Tab Scanner: dari 3 tab agent → 1 daftar dengan filter `setup_type` (Pre-Move/Gainer/Loser/New).
- History/Analytics: win-rate per `setup_type` menggantikan win-rate per agent (informasi setara, lebih jujur).
- Migrasi data: trade lama ber-`style` futures_agent1/2/3 tetap dibaca; trade baru pakai satu style
  + `setup_type` di meta. Perlu pemetaan agar history lama tidak hilang.

---

## 6. Urutan Implementasi (saat disetujui)

> Belum dikerjakan. Tiap langkah = commit terpisah (aturan user).

| # | Langkah | Status |
|---|---------|--------|
| R-1 | Dedup global per-symbol (quick win, tutup BUG-L1) | ❌ BELUM |
| R-2 | SL floor sadar-leverage + SL+ lifecycle (tutup BUG-L3) | ❌ BELUM |
| R-3 | Lebur agent1+agent2 → Lane A Pre-Move | ❌ BELUM |
| R-4 | agent3 → Lane B + ranking gainers/losers eksplisit | ❌ BELUM |
| R-5 | Lane C New-Listing (+ data onboardDate) | ❌ BELUM |
| R-6 | Tambah data market cap + tampilkan di Monitor | ❌ BELUM |
| R-7 | Satukan store + auto-open jadi satu jalur ber-setup_type | ❌ BELUM |
| R-8 | RAR_MIN_TRADES naik + de-risk on gate (BUG-L2) | ❌ BELUM |
| R-9 | Frontend: 3 tab → 1 daftar + filter setup_type | ❌ BELUM |
| R-10 | Migrasi win-rate per-agent → per-setup_type | ❌ BELUM |

> **Catatan:** R-1 dan R-2 bisa dikerjakan lebih dulu sebagai perbaikan bug mendesak (sudah terdaftar
> juga di [PLAN-FUTURES-LIVE.md](PLAN-FUTURES-LIVE.md)) tanpa menunggu refactor besar R-3..R-10.

### 6.0 Pembagian Phase Eksekusi (6 phase, tiap phase = commit)

> Urutan: hentikan pendarahan dulu → refactor struktur → wiring → UI → validasi.
> Tiap phase berdiri sendiri dan bisa di-test sebelum lanjut.

| Phase | Nama | Cakupan bug | Output |
|-------|------|-------------|--------|
| **P1** ✅ SELESAI | 🩸 Stop Pendarahan (risiko/SL) | L3 L4 L5 L6 L7 L8 L9 L16 L17 L19 L23 | SL floor sadar-leverage, leverage↔SL direkonsiliasi, monitor wick detection, margin/liq dari posisi nyata. **3 agent lama berhenti bleed** — 6 commit |
| **P2** | 🔀 Konsolidasi Scanner 3→1 | L1 L18 L12 L24 | 1 Scanner, 3 lane (Pre-Move/Gainers-Losers/New-Listing), ranking global, dedup global, setup_type tagging |
| **P3** | 📡 Data Baru (Lane B/C) | L14 L15 | onboardDate (new-listing), market cap, handling data OI/liq absen |
| **P4** | 🧠 Learning & Regime & Gate | L2 L10 L11 L13 | recency window, persist state, regime per-coin, RAR sample diperbesar |
| **P5** | 🔌 Backend Wiring 1-jalur | L20 L21 L22 | satu store/WS/status/auto-open ber-setup_type (bukan per-agent), P&L dari wallet nyata |
| **P6** | 🖥️ Frontend 1-Scanner | UI-1..UI-8 | Scanner 3-tab→1 daftar + filter setup_type, Analytics per setup_type, pakai nilai backend, threshold dinamis |
| **P7** | ✅ Validasi | (DoD) | reset DB → jalankan siklus → konfirmasi: tak ada dup, tak ada SL <floor, WR terukur, agent3/momentum stabil di UI |

> **Quick-win opsional sebelum P1:** L20 (WS agent3) + UI-2 (dep array) bisa difix 5 menit untuk
> hentikan "agent3 kedip" — tapi keduanya hilang by-design di P5/P6, jadi opsional.
>
> **Catatan dependensi:** P2 butuh P1 (SL/sizing harus sehat dulu sebelum logika lane disatukan).
> P6 butuh P5 (frontend baca bentuk data baru). P3 bisa paralel dengan P2.

### 6.1 Jaminan bug lama IKUT tertangani (tidak boleh tertinggal)

Keputusan user #2: bug dari [PLAN-FUTURES-LIVE.md](PLAN-FUTURES-LIVE.md) **wajib** ikut dalam refactor.
Pemetaan eksplisit bug → langkah, agar tidak ada yang lolos:

| Bug (PLAN-FUTURES-LIVE.md) | Severity | Ditangani oleh | Status |
|----------------------------|----------|----------------|--------|
| **BUG-L1** — coin dobel lintas agent (cross-margin) | 🔴 | R-1 (dedup global) + R-7 (satu jalur auto-open) | ❌ BELUM |
| **BUG-L3** — SL terlalu ketat → WR 0% | 🔴 | R-2 (SL floor sadar-leverage + SL+ lifecycle) | ❌ BELUM |
| **BUG-L4** — SL ketat bengkakkan notional | 🔴 | R-2 (gabung) | ❌ BELUM |
| **BUG-L5** — SL floor cuma 0.3% (flat) | 🔴 | R-2 (floor sadar-leverage) | ❌ BELUM |
| **BUG-L6** — leverage & SL dihitung terpisah | 🔴 | R-3/R-4 (satukan penetapan SL+lev di lane scanner) | ❌ BELUM |
| **BUG-L7** — ATR rendah → lev maks + SL terketat | 🔴 | R-3/R-4 (balik logika leverage) | ❌ BELUM |
| **BUG-L8** — monitor tanpa wick detection | 🔴 | R-2 (port wick 1m dari spot) | ❌ BELUM |
| **BUG-L9** — margin cap timpa risk 1% | 🟡 | R-2 (kecilkan size, bukan naikkan risk) | ❌ BELUM |
| **BUG-L2** — RAR gate pasif + sampel 5 trade terlalu kecil | 🟡 | R-8 (RAR_MIN_TRADES naik + de-risk on gate) | ❌ BELUM |
| **BUG-L18** — discovery gainers/losers/new-listing terputus dari trading | 🔴 | R-4 + R-5 + R-7 (Lane B/C tersambung) | ❌ BELUM |
| **BUG-L10** — learning tanpa jendela waktu | 🟡 | R-11 (recency window + decay) | ❌ BELUM |
| **BUG-L11** — state learning hilang saat restart | 🟡 | R-12 (persist blacklist/threshold) | ❌ BELUM |
| **BUG-L12** — volatile blokir momentum | 🟡 | R-4 (gate per setup_type) | ❌ BELUM |
| **BUG-L13** — regime BTC-only utk semua alt | 🟡 | R-13 (regime per-coin/sektor) | ❌ BELUM |
| **BUG-L14** — data likuidasi sintetis | 🟡 | R-6 (sumber data nyata / drop dari scoring) | ❌ BELUM |
| **BUG-L15** — OI/liq kosong utk coin baru/kecil | 🟢 | R-5/R-6 (handling data absen) | ❌ BELUM |
| **BUG-L16** — liq_guard tutup di sl bukan liq | 🟢 | R-2 (exit realistis) | ❌ BELUM |
| **BUG-L17** — TP1 partial tak kecilkan size | 🟡 | R-2 (locked margin dari sisa fraksi) | ❌ BELUM |
| **BUG-L19** — P&L expired hilang dari balance | 🟡 | R-2 (balance sertakan expired) | ❌ BELUM |

> Langkah baru dari audit: **R-11** recency learning · **R-12** persist learning state · **R-13** regime per-coin.

#### UI (audit frontend) — ditangani R-9 + R-10

| Bug UI | Severity | Ditangani oleh |
|--------|----------|----------------|
| **UI-1** — tab Analytics seluruhnya 2-agent | 🔴 | R-9 + R-10 (analytics per setup_type) |
| **UI-2** — `filtered` useMemo tanpa dep agent3 | 🔴 | R-9 (quick fix; hilang total saat 1 daftar) |
| **UI-3** — loading/empty hanya cek agent1+2 | 🟡 | R-9 |
| **UI-4** — threshold AUTO hardcode 72 | 🟡 | R-9 (ambil threshold efektif dari API) |
| **UI-5** — notional/margin/liq dihitung di client | 🟡 | R-9 (pakai nilai backend) |
| **UI-6** — penamaan agent tak konsisten antar-tab | 🟢 | R-9 (nama per setup_type) |
| **UI-7** — copy Scanner masih "Pre-Gainer/2 agent" | 🟢 | R-9 |
| **UI-8** — liq sintetis ditampilkan seolah nyata | 🟡 | R-6 + R-9 |

> **Catatan:** UI-2 (dependency array agent3) adalah bug React murni yang bisa diperbaiki segera
> sebagai quick-fix, terlepas dari refactor.

#### Audit final pra-refactor — ditangani R-7 + R-9

| Bug | Severity | Ditangani oleh |
|-----|----------|----------------|
| **BUG-L20** — WS stream buang agent3 | 🔴 | R-7 (satu stream ber-setup_type) |
| **BUG-L23** — risk dashboard margin dari $1000 | 🔴 | R-2 (pakai position_size tersimpan) |
| **BUG-L21** — status tak laporkan agent3 | 🟡 | R-7 |
| **BUG-L22** — notional/pnl hardcode $1000 | 🟡 | R-2 |
| **BUG-L24** — agent3 dorong SL ketat | 🟢 | R-3/R-4 (SL floor di lane momentum) |

> **Saat refactor 1 Scanner:** WS, status, store cukup kirim SATU daftar (tak ada lagi agent1/2/3
> terpisah) → BUG-L20/L21 hilang by-design.

> **Definition of Done refactor:** ketiga bug di atas berstatus ✅ SELESAI **sebelum** refactor dianggap
> tuntas. Validasi akhir: reset DB futures → jalankan beberapa siklus → konfirmasi tidak ada symbol dobel,
> tidak ada SL <floor, dan win-rate terukur per `setup_type` (bukan 0% akibat SL ketat).
