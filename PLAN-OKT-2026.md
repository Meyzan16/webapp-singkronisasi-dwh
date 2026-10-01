# PLAN-OKT-2026 — inventaris pekerjaan tertunda + fase

Disusun 1 Okt 2026 dari: riwayat sesi, `paper_trades`, `futures_decision_events`
(3.800 kandidat matang sejak 9 Sep), `ops/logs/health.log`, dan rencana lama
(PLAN-FUTURES-AGENTIC, PLAN_ADAPTIVE_ENGINE_BOOST, SCHEDULE_FUTURES, PLAN-UI-SUSULAN).

## Kenyataan per 1 Okt 2026

| | n | P&L | PF |
|---|---|---|---|
| Futures, 14 hari sebelum 18 Sep | 81 | −$3,48 | 0,98 |
| Futures, 18 Sep – 1 Okt | 39 | **−$49,87** | **0,60** |
| Spot opportunity, sebelum 18 Sep | 28 | +$3,89 | 1,08 |
| Spot opportunity, 18 Sep – 1 Okt | 37 | **−$21,92** | **0,60** |

Sejak 21 Sep futures hanya 0–4 trade/hari: LONG dijeda otomatis
(`direction_paused`, 936×), SHORT dimatikan manual (`direction_disabled`).
Gerbang itu **melindungi**: kandidat yang ditahan rata −0,85% di 4 jam; yang
dibuka justru −1,93%.

## P0 — Runtime utuh

| # | Item | Status |
|---|---|---|
| 0.1 | Stack ganda: Docker Desktop menyalakan container `backend/agents/frontend` (kode 5 Jul, `restart: unless-stopped`) di samping stack lokal — dua scanner/auto-trader ke DB yang sama | ✅ dihentikan; `profiles: ["app"]` di compose; `start-night` menghentikan container aplikasi bila hidup |
| 0.2 | 31× "backend tidak merespon" | ✅ didiagnosis: bukan bug kode — log berhenti di tengah scan tanpa traceback; mesin hanya punya *S0 Modern Standby* yang menangguhkan proses desktop |
| 0.3 | Scan futures 132 dtk rata (maks 289) > interval 120 dtk | ✅ fetch berpagar → semaphore; `universe_sec`/`fetch_sec` di log. Terukur: fetch 48–141 dtk = latensi mirror Binance, bukan kode |
| 0.4 | **Downtime 191 jam dari ~300 jam sejak 19 Sep (≈64%)** — task `AgentsTrading-Stop` 07:00 masih aktif + mesin tidur | ⛔ **owner**: nonaktifkan task Stop, matikan sleep saat dicolok |

## P1 — Edge entry futures

Analisis kronologis (latih s/d 22 Sep 20:15, uji sesudahnya; dedup per
simbol+arah per 4 jam → 1.321 kandidat):

- Semesta kandidat: net 4 jam **−0,86% (latih) / −0,98% (uji)**, 37–39% positif.
- **Tak satu pun tersil fitur** (skor, change_24h/1h/30m, RSI, OI, funding, ATR,
  volume, breadth, probabilitas model) positif di latih DAN uji.
- **Skor lebih tinggi lebih buruk**: skor ≥72 −0,96% / −1,23%. Menaikkan
  `agentic_min_score` tidak menolong.
- Hipotesis kebalikan (memudarkan pump) tidak kokoh: +0,13% total, tanda
  berganti tiap minggu; median LONG −0,94% vs rata −0,43% → ekor kanan tebal.

**Kesimpulan:** agen memilih koin yang sudah naik 10–15% dengan RSI 67–74 —
mengejar pump. Tak ada parameter yang bisa disetel untuk membalik itu;
butuh hipotesis sinyal baru. Sampai ada edge terbukti di ledger: **jangan
menaikkan ukuran, jangan mengaktifkan kontribusi skor adaptive (P4).**

### P1a — Riset sinyal shadow ✅ HIDUP sejak 1 Okt 2026 22:44 WIB

`agents/futures/shadow_signals.py` → tabel sendiri `futures_shadow_signals`
(BUKAN `futures_decision_events`, yang dibaca pelatihan model/walkforward/UI).
Dipanggil scanner sesudah fetch, memakai data yang sama; nol efek keputusan.

| Hipotesis | Arah | Aturan (ditetapkan sebelum ada hasil) |
|---|---|---|
| `control` | LONG | 1 simbol acak per scan — garis dasar drift |
| `pullback_ema` | LONG | 4j > EMA50, EMA20 1j > EMA50 1j, harga ≤ 0,5 ATR dari EMA20 1j, RSI 1j 40–55, lilin 1j hijau |
| `squeeze_breakout` | L/S | lebar Bollinger 1j ≤ persentil 20 (100 bar) dalam 5 bar terakhir, close tembus pita 2σ, volume ≥ 1,5× |
| `dip_in_uptrend` | LONG | 4j > EMA50, RSI 1j < 32, close 1j > close sebelumnya |

Penilaian: pnl 1j/4j/24j + simulasi bracket SL 1,5 ATR / TP 3 ATR (2R), 24 jam,
SL&TP satu lilin = SL; `bracket_r` net biaya 0,3%. Dedup per hipotesis+simbol+arah 4 jam.

**Aturan lulus** (di `ops/shadow_report.py`, jangan diubah setelah melihat angka):
≥300 berlabel · rata > +0,10 R di paruh awal DAN akhir · ≥0,15 R di atas kontrol ·
satu minggu ≤40% total R.

Laporan: `backend/.venv/Scripts/python.exe ops/shadow_report.py` (dari root).
Perkiraan: ±300 per hipotesis dalam 1–3 minggu **asal sistem hidup** (lihat P0.4).
Ulangi juga analisis edge kandidat agen tunggal tiap 2 minggu.

## P2 — Exit futures

20 SL rugi sejak 18 Sep: **16 benar** (harga terus turun −5% s/d −16% di 4 jam),
3 berbalik (XTZ, PTB, IOTX). Banyak kena SL dalam 2–13 menit = masuk di pucuk.
Rugi per SL ≈ 1,15× risiko (fee + slippage); outlier COAI breach 5,2%.
**Exit bukan masalahnya.** Tak ada perubahan.

## P3 — Spot opportunity (engine SPOT — butuh izin owner)

Lane `accumulation` (PF 1,92 sebelum 18 Sep): 15 dari 25 penutupan kini
`urgent_rotation`, total +$1,84 (rata +$0,12, ditahan ~29 jam) — posisi dipotong
sebelum matang. Sebelum 18 Sep rotasi rata +$1,9/trade. `bigmover`: 8 SL −$22,60.

✅ **Diputuskan 1 Okt 2026: rotasi TETAP AKTIF.** Kontrafaktual 32 rotasi
accumulation (60 hari, SL/TP asli, tahan s/d 7 hari): dirotasi **+$14,79** vs
ditahan **−$0,17** (2 TP, 10 SL, 20 menggantung). Temuan "+$0,12/trade" di atas
bukan kerugian — alternatifnya lebih buruk. Saklar per-lane
`spot.monitor_urgent_rotation_{accumulation,breakout,bigmover,early_radar}`
(default 1) tersedia bila bukti berubah.

## P4 — Adaptive engine (PLAN_ADAPTIVE_ENGINE_BOOST Fase B/D/E)

**Ditahan.** Menaikkan bobot/kontribusi skor atas strategi tanpa edge hanya
memperkuat noise. Dibuka kembali bila P1 menemukan edge.

## Rencana lama — status

- PLAN-UI-SUSULAN: U1–U5 selesai.
- SCHEDULE_FUTURES: gate Live & Hari-30 gagal (dicatat 24 Agu); belum layak live.
- PLAN_ADAPTIVE_ENGINE_BOOST: Fase A (validasi forward) gagal 24 Agu → B/C/D/E menunggu edge.

## Diagnosis menyeluruh "kenapa futures belum untung" (1 Okt 2026, 23:00)

Seluruh riwayat: **234 trade sejak 10 Jul, −$198,28.** Tiap generasi agen rugi
(agent3 −$54 Jul, bigmover −$74 Agu, agentic −$53 Sep).

Agen `agentic` (122 trade) dalam satuan R:

| Penutupan | n | rata R | total R |
|---|---|---|---|
| `sl_plus` (trailing) | 55 | +0,67 | +36,9 |
| `sl_hit` | 35 | −1,12 | −39,2 |
| `offline_reconcile_sl` | 27 | −0,39 | −10,7 |
| TP tersentuh | 1 | +2,02 | +2,0 |

Menang 58%, tapi rata menang $3,66 vs kalah $6,00 → butuh WR ≥62% untuk impas.

**Kontrafaktual exit** (lilin 5m, risiko dolar sama, dipisah paruh awal/akhir):
- Tahan ke TP tetap: −11,3R (aktual −10,3R) → trailing bukan masalah.
- 20 kombinasi lebar SL (1–3×) × target (1–3R): **tak satu pun positif di kedua paruh.**
- MFE besar (58/122 sempat ≥2R) hanya volatilitas dua arah — bukan untung yang terbuang.

**Kesimpulan:** sebabnya ENTRY tanpa edge (lihat P1), ditambah ±27% trade
ditutup offline karena mesin mati. Bukan exit, bukan sizing, bukan threshold.
Konfirmasi independen: `ForwardValidate` 69 jam berturut "MEMBURUK"
(exp −0,73%, PF 0,74, n=1.895).

### Perlu API tambahan (DexScreener / CoinMarketCap)?

**Tidak, untuk sekarang.**
- Scanner sudah memakai data Binance futures yang paling relevan untuk perp:
  klines, funding, OI (+ histori), rasio long/short global, likuidasi, 24h ticker.
- **DexScreener** = pasangan DEX on-chain (likuiditas pool, pair baru, meme).
  Koin yang ditradingkan di sini adalah perp Binance; sinyal DEX baru relevan
  untuk strategi "hype DEX → listing CEX", yang bukan strategi agen ini.
- **CoinMarketCap** (gratis ±10rb kredit/bulan) = kapitalisasi, peringkat,
  kategori, dominasi. Hampir semuanya turunan harga×suplai; tak ada bukti di
  ledger bahwa ukuran pasar membedakan kandidat menang/kalah (volume 24j —
  proksi terdekat — tak positif di tersil mana pun).
- Yang LAYAK diuji lebih dulu, gratis dari Binance: `takerlongshortRatio`,
  `topLongShortPositionRatio`, basis. Cara mengujinya: catat sebagai fitur di
  ledger/shadow, nilai dengan analisis tersil kronologis yang sama — **sebelum**
  membayar atau mengintegrasikan API luar.

## Tugas tersangkut — status 1 Okt 2026

| Item | Status |
|---|---|
| Stack docker ganda | ✅ selesai (72304d9) |
| Durasi scan / timing | ✅ selesai (72304d9) |
| Riset sinyal shadow | ✅ hidup, menunggu ≥300/hipotesis (a6efe3e) |
| Saklar urgent_rotation per lane | ✅ selesai, tetap aktif (781cabe) |
| `B1Watch` melapor vonis harian atas flag yang mati sejak 8 Agu | ✅ skrip kini diam selama flag mati |
| B7 notional $1.000 hardcode | ✅ bukan masalah: cadangan mati, 0/234 trade memakainya |
| `IPWatch` nonaktif sejak 23 Jul | dibiarkan (sengaja nonaktif) |
| **P0.4 uptime: task Stop 07:00 + sleep** | ⛔ owner — satu-satunya blocker yang tersisa |
| P4 adaptive engine | ditahan sampai ada edge |

### Hasil uji data gratis Binance (1 Okt 2026, 23:45)

1.321 kandidat agen tunggal (dedup), latih s/d 22 Sep 20:15, uji sesudahnya.
Fitur dari histori 1 jam (periode yang sudah selesai sebelum scan — tanpa lookahead):
rasio taker buy/sell (1j & rata 4j), rasio long/short trader besar (+ perubahan 4j),
rasio long/short semua akun (+ perubahan 4j), trader besar vs kerumunan, basis.

**Hasil: tidak ada irisan yang positif (> +0,25% net 4j) di latih DAN uji.**
Sinyal terkuat hanya memperkecil rugi, bukan membalik:
- LONG dengan `basis_rate` tersil teratas paling buruk (−1,00% / −2,01%) — premi
  futures tinggi = pasar sudah terlalu panas, konsisten dengan temuan "mengejar pump".
- LONG dengan taker buy/sell tinggi sedikit lebih baik (+0,17% / −0,78%) — tetap negatif di uji.

Kesimpulan: rasio taker/long-short/basis **tidak** menyelamatkan strategi mengejar
pump. Bersama hasil DexScreener/CMC di atas: masalahnya hipotesis entry, bukan
kekurangan data. Jalan yang tersisa = riset shadow P1a (hipotesis entry berbeda).
Skrip ulang: `ops/research/` (README).
