# PLAN-FUTURES-LIVE.md — Bug dari Dashboard Live (Sesi 2026-06-14)

> Bug ditemukan saat user inspeksi **dashboard History Futures live** (bukan audit statik).
> Beda asal dari [PLAN-FUTURES.md](PLAN-FUTURES.md) (audit kode statik F1–F113).
>
> **Konvensi status — WAJIB dibaca model sebelum kerja:**
> - `✅ SELESAI` → sudah dikerjakan + commit. **JANGAN baca/kerjakan ulang.** Lewati.
> - `🔧 PROSES` → sedang dikerjakan sesi ini.
> - `❌ BELUM` → belum disentuh, butuh kerja.
>
> Severity: 🔴 CRITICAL · 🟡 MEDIUM · 🟢 LOW

---

## Konteks Snapshot Live (saat bug ditemukan)

```
Wallet futures: Saldo $957.71 · Bebas $323.52 · Terkunci $634.19
Simulasi:       $946.68 (-$50.07) · 4 Open · 5 Closed · 0 Win / 5 Loss · WR 0%
RAR Gate:       AKTIF — Sharpe -2.391 < -0.5 (5 trade tertutup) · DD 5.3%

Posisi terbuka (4):
  Agent 1: XAUUSDT  12x  SL -0.5%  (WARNING)
  Agent 1: ALLUSDT  12x  SL -0.7%  (WARNING)   ← DUPLIKAT
  Agent 2: ALLUSDT  12x  SL -0.7%  (WARNING)   ← DUPLIKAT (entry/SL/TP identik)
  Agent 3: CHIPUSDT  5x  SL -2.8%  (SAFE)

Closed (semua SL): ENJ -11.41 · WLFI -3.06 · MANA -13.92 · HIVE -13.90
```

---

## BUG-L1 — 🔴 CRITICAL — Coin sama ke-open di >1 agent (cross-margin dobel)

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P2) |
| **Bukti** | ALLUSDT terbuka di Agent 1 DAN Agent 2 — entry `0.4936`, SL `0.4901`, TP2 `0.5468` identik |
| **Akar** | [auto_trader.py:122-128](agents/futures/auto_trader.py:122) — dedup `existing_q` filter `PaperTrade.style == agent` (per-agent), bukan lintas-agent |
| **Dampak** | Sejak Phase 9 ketiga agent berbagi 1 wallet cross-margin. Binance cross-margin nyata = 1 posisi netto per symbol. Duplikat → margin & risk dihitung 2x untuk pergerakan korelasi 100%, liq price salah, risk gate & portfolio heat lihat 2x eksposur |
| **Fix** | Dedup GLOBAL per-symbol lintas semua agent. Ganti cek `style == agent` → `style.in_(list(_FUTURES_STYLES))` di query `existing_syms`. Karena loop per-agent, perlu kandidat agent ber-skor tertinggi yang menang (skip symbol jika sudah open di agent manapun). Pertimbangkan juga cooldown SL jadi lintas-agent |
| **Catatan** | CLAUDE.md menyatakan "cross-style trades are independent" — itu desain PRA-Phase-9. Perlu update CLAUDE.md juga setelah fix |
| **Commit** | `fix(futures-live): global per-symbol dedup across agents (cross-margin)` |
| **BUKTI DB (2026-06-14)** | ALLUSDT ke-open dobel agent1+agent2, entry/SL/hold **identik (524m)**. Satu gerak harga = rugi dobel -$12.61 + -$11.66 = **-$24.27** (~27% total loss hari itu) |

---

## BUG-L3 — 🔴 CRITICAL — SL terlalu ketat → win rate 0%

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Bukti** | SL hanya 0.5% / 0.7% / 2.8% dari entry. Leverage 12x → 0.7% = noise pasar biasa. 5/5 trade closed = SL. WR 0% |
| **Akar 1** | SL awal di-set scanner (`agent1/agent2 _calc_levels`) tanpa floor minimum relatif terhadap leverage. SL 0.7% @ 12x kena duluan sebelum harga capai 50% jarak ke TP1 |
| **Akar 2** | Breakeven baru aktif saat harga capai **50% jarak ke TP1** — [monitor.py:163,179](agents/futures/monitor.py:163). Dengan SL ketat, harga keburu kena SL -0.7% sebelum naik +0.5% |
| **Akar 3** | Stagnant 48h check ([monitor.py:337-347](agents/futures/monitor.py:337)) + `MAX_AGE_DAYS=3` ([monitor.py:43](agents/futures/monitor.py:43)) → futures dipaksa resolve cepat, tabrakan dengan SL ketat |
| **Fix** | (a) SL floor scaled by leverage di scanner — mis. min jarak SL = `k / leverage` (12x → min ~1.5-2%); (b) breakeven lebih cepat / SL awal lebih lebar; (c) tinjau ulang stagnant 48h untuk futures |
| **Kapan "SL+" terjadi sekarang** | breakeven (SL→entry) saat 50% ke TP1 · tp1_trail (SL→entry+75%×TP1) saat TP1 hit · tp1_lock (SL→TP1) saat 50% TP1→TP2. **Hampir tak pernah tercapai** karena SL ketat |
| **Commit** | `fix(futures-live): leverage-aware SL floor + faster breakeven` |
| **BUKTI DB (2026-06-14)** | 8 trade closed, **semua `sl_hit`**, total **-$88.24 (≈-9%)**. SL dist: 0.34/0.40/0.43/0.66/0.72/0.72/1.27/2.77%. 6 dari 8 di bawah 0.75% @ 12-13x. HIVE SL 0.34% mati 45m. Tidak ada yang capai breakeven |

---

## BUG-L4 — 🔴 CRITICAL — SL ketat membengkakkan notional (sizing interaction) [BARU]

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Bukti** | HIVE harga turun -0.44% tapi rugi **-$13.90**; MANA -0.50% → -$13.92. Loss $ jauh lebih besar dari move % |
| **Akar** | `notional = risk_dollar / (SL_dist%)` di `compute_futures_sizing`. SL 0.34% → notional membengkak **~290x** untuk jaga risk_dollar konstan |
| **Dampak** | SL ketat TIDAK mengurangi risiko dolar — malah bikin posisi raksasa. Noise sekecil apa pun = rugi penuh risk_dollar, sangat cepat (death by a thousand cuts). Tiap trade ~-1.5% balance dalam menit |
| **Fix** | Terkait erat BUG-L3: SL floor sadar-leverage otomatis membatasi pembengkakan notional. Tambahan: cap notional maksimum absolut + cap risk_dollar per trade. Tolak sinyal yang SL-nya di bawah floor (jangan paksa size) |
| **Commit** | (gabung dengan BUG-L3) `fix(futures-live): leverage-aware SL floor + faster breakeven` |

---

## BUG-L2 — 🟡 MEDIUM — RAR gate pasif + sample 5 trade terlalu kecil

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Bukti** | RAR gate aktif (Sharpe -2.391) tapi 4 posisi tetap jalan tanpa de-risking |
| **Perilaku skrg** | Gate HANYA blokir open baru ([auto_trader.py:82-89](agents/futures/auto_trader.py:82)). Posisi terbuka dibiarkan sampai TP/SL/expired. Tidak ada force-close (desain wajar) |
| **Celah 1** | `RAR_MIN_TRADES=5` ([risk_gate.py:25](agents/futures/risk_gate.py:25)) terlalu kecil — Sharpe -2.391 dari 5 SL beruntun = noise, bukan sinyal andal |
| **Celah 2** | Saat gate aktif, tidak ada de-risking posisi existing (mis. tighten SL ke breakeven untuk yang profit) |
| **Fix** | (a) Naikkan `RAR_MIN_TRADES` 5 → 10-15; (b) opsional: saat gate aktif, tighten SL posisi yang sudah profit ke breakeven |
| **Commit** | `fix(futures-live): raise RAR_MIN_TRADES + optional de-risk on gate active` |

---

## ═══ AUDIT MENDALAM 2026-06-14 (data untuk refactor agent) ═══

> Investigasi rantai akar "kenapa SL selalu ketat". Ditemukan 5 bug saling terkait di
> **scanner (penetapan SL & leverage)**, **sizing**, dan **monitor**. Ini bukti teknis
> untuk dipakai saat refactor R-2..R-7.

### BUG-L5 — 🔴 CRITICAL — SL floor minimum cuma 0.3% (jauh terlalu ketat)

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | [agent1.py:550](agents/futures/agent1.py:550) (LONG) & [agent1.py:574](agents/futures/agent1.py:574) (SHORT): `if risk_pct > 8.0 or risk_pct < 0.3:` — SL hanya dilebarkan jika < **0.3%**. SL hasil swing 0.34/0.40/0.66% semua LOLOS |
| **Bukti** | 6 dari 8 trade SL < 0.75% (HIVE 0.34%, MANA 0.40%, WLFI 0.43%) — semua di atas floor 0.3% jadi tidak pernah dikoreksi |
| **Fix** | Floor minimum SL harus **sadar-leverage**, bukan 0.3% flat. Mis. min risk_pct ≈ `k × (1/leverage)` atau minimal 1.5-2% untuk lev ≥10x |

### BUG-L6 — 🔴 CRITICAL — leverage & SL dihitung TERPISAH, tak pernah direkonsiliasi

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | `calc_leverage()` ([agent1.py:157](agents/futures/agent1.py:157)) pilih leverage dari ATR%. `_calc_levels()` ([agent1.py:523](agents/futures/agent1.py:523)) pilih SL dari struktur swing. **Keduanya tidak saling tahu** |
| **Dampak** | Bisa keluar leverage 12x + SL 0.34% bersamaan — tidak ada constraint "SL ketat → kecilkan leverage" atau sebaliknya |
| **Fix** | Satukan: hitung SL dulu, lalu leverage dibatasi oleh jarak SL (atau tolak kombinasi tak aman). Ini constraint inti yang hilang |

### BUG-L7 — 🔴 CRITICAL — coupling terbalik: ATR rendah → leverage MAKS + SL TERKETAT

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | [agent1.py:159-163](agents/futures/agent1.py:159): `atr_pct < 1.0 → base=10` (tertinggi, +skor → 15x). [agent3.py:54-58](agents/futures/agent3.py:54): pola sama (→8-10x). Koin ATR rendah = swing-SL paling rapat |
| **Dampak** | Sistem **secara sistematis memasangkan leverage maksimum dengan SL paling ketat**. Koin volatilitas rendah dapat 12-15x + SL 0.34% = dijamin kena noise. Terkonfirmasi data: SL kecil (low ATR) semua dapat 12x; CHIP (ATR tinggi 2.77%) cuma 5x |
| **Fix** | Logika leverage harus dibalik/dibatasi jarak SL, bukan murni anti-ATR. Bagian dari rekonsiliasi BUG-L6 |

### BUG-L8 — 🔴 CRITICAL — futures monitor TANPA wick detection (poll 2 menit)

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | `agents/futures/monitor.py` **0 match** untuk wick/1m/eff_low (spot monitor punya 23). Pakai mark price langsung tiap 2 menit |
| **Dampak** | TP/SL yang tersentuh ANTAR-poll **terlewat**: harga wick ke TP lalu balik → TP terlewat, posisi lanjut sampai SL → tercatat LOSS padahal harusnya WIN. **Win-rate jadi tidak andal & bias ke SL**. SL fill di harga `sl` persis (abaikan gap/slippage) |
| **Fix** | Port wick detection 1m dari spot monitor ([opportunity/monitor.py](agents/opportunity/monitor.py)) ke futures monitor |

### BUG-L9 — 🟡 MEDIUM — margin cap diam-diam menimpa target risk 1%

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | [balance.py:257-261](backend/app/api/v1/balance.py:257): saat `margin > max_margin` (35%), notional & **risk_dollar dihitung ulang naik**. Dengan SL ketat, notional intended (1%) lampaui cap → risk_dollar re-derive jadi ~1.4% |
| **Bukti** | HIVE risk_dollar seharusnya ~$9.5 (1%), nyatanya -$13.90 (~1.46%) — persis hasil margin cap × SL ketat (mekanisme BUG-L4) |
| **Fix** | Setelah BUG-L5 (SL tidak lagi ketat), notional tidak membengkak → cap jarang kena. Tambahan: kalau kena cap, **kecilkan size**, jangan naikkan risk_dollar |

> **Kesimpulan rantai:** L7 (ATR rendah → lev maks + SL terketat) → L5 (floor 0.3% tak menangkapnya) →
> L6 (tak ada rekonsiliasi lev↔SL) → L4/L9 (SL ketat bengkakkan notional, margin cap timpa risk 1%) →
> L8 (monitor lewatkan TP, catat sbg SL). **Satu rantai = win rate 0%.** Refactor scanner WAJIB
> menyatukan penetapan SL+leverage+sizing sebagai satu keputusan, bukan 3 perhitungan terpisah.

---

## ═══ SAPU BERSIH MENYELURUH 2026-06-14 (L10-L19) ═══

> Audit penuh seluruh subsistem futures sebelum refactor: learning, regime, data layer,
> monitor lifecycle, dan disconnect discovery↔trading. Data untuk refactor 1 Scanner + 1 Monitor.

### BUG-L10 — 🟡 MEDIUM — learning pakai SEMUA trade (tanpa jendela waktu) → tak pernah adaptif

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [weight_updater.py:160-164](agents/futures/weight_updater.py:160): query closed trades **tanpa filter waktu**. Signal weight & adaptive threshold dihitung dari seluruh sejarah |
| **Dampak** | Sinyal yang gagal 50x sebulan lalu tetap dihukum selamanya; sistem "learning" tidak pernah beradaptasi ke perubahan regime. Bertentangan dengan tujuan adaptif |
| **Fix** | Tambah jendela recency (mis. 30 hari / N trade terakhir) + decay bobot lama |

### BUG-L11 — 🟡 MEDIUM — state learning in-memory, hilang saat restart

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [weight_updater.py:35-41](agents/futures/weight_updater.py:35): `_weight_cache`, `_adaptive_thresholds`, `_coin_blacklist` semua dict in-memory |
| **Dampak** | Tiap restart backend: blacklist 24h hilang, threshold balik ke default 72, bobot kosong sampai siklus pertama. Coin yang baru 3x SL bisa langsung di-open lagi pasca-restart |
| **Fix** | Persist ke DB (atau Redis) — blacklist & threshold harus survive restart |

### BUG-L12 — 🟡 MEDIUM — regime "volatile" blokir SEMUA auto-open, termasuk momentum

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P2) |
| **Akar** | [auto_trader.py:29,78](agents/futures/auto_trader.py:78): `AUTO_DISABLED_REGIMES={"volatile"}` → return 0 untuk semua agent |
| **Dampak** | Saat BTC volatile (justru saat big-movers terbanyak — screenshot: 29 coin >10%), agent3 momentum **diblokir total** tepat saat peluang momentum paling kaya |
| **Fix** | Lane momentum (Lane B refactor) jangan diblanket-block di volatile; sesuaikan per setup_type |

### BUG-L13 — 🟡 MEDIUM — regime BTC-only diterapkan ke SEMUA altcoin

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [regime.py](agents/futures/regime.py) deteksi hanya BTCUSDT; gate `ranging→+5 threshold`, `volatile→block` ([auto_trader.py:93-94](agents/futures/auto_trader.py:93)) dipakai untuk semua coin |
| **Dampak** | Altcoin sering decouple dari BTC — setup alt yang valid salah di-gate karena regime BTC |
| **Fix** | Pertimbangkan regime per-coin atau per-sektor, bukan murni BTC |

### BUG-L14 — 🟡 MEDIUM — data likuidasi SINTETIS (×1.000.000 arbitrer) memberi makan scoring

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P3) (= F1 di PLAN-FUTURES.md) |
| **Akar** | [data.py:96-121](agents/futures/data.py:96): `_fetch_liquidations` pakai `globalLongShortAccountRatio` × 1.000.000 sebagai proksi, bukan `/fapi/v1/forceOrders` (butuh auth) |
| **Dampak** | `liq_long`/`liq_short` bukan USDT nyata; bonus/penalti skor agent1 berbasis angka tak bermakna. Dashboard tampilkan nilai liq palsu |
| **Fix** | Pertimbangkan sumber likuidasi nyata, atau hapus dari scoring jika tak bisa diandalkan |

### BUG-L15 — 🟢 LOW — proksi liq & OI kosong untuk coin baru/kecil

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P3) |
| **Akar** | `globalLongShortAccountRatio` & `openInterestHist` hanya tersedia untuk coin besar → new listing & small-cap return 0 |
| **Dampak** | Justru coin yang ingin ditarget (new/momentum) tak punya data OI/liq → scoring pincang. Penting untuk Lane C |
| **Fix** | Fallback/handling khusus saat OI/liq data absen (jangan beri penalti karena data kosong) |

### BUG-L16 — 🟢 LOW — liq_guard menutup di harga `sl`, bukan harga likuidasi

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | [monitor.py:375-378](agents/futures/monitor.py:375): saat liq_guard trip, `close_price = sl` (optimistik) |
| **Dampak** | P&L liq-guard dicatat seolah kena SL, padahal mendekati likuidasi (rugi lebih besar). Win/loss & balance sedikit bias optimis |
| **Fix** | Tutup di harga realistis dekat liq, bukan sl |

### BUG-L17 — 🟡 MEDIUM — TP1 partial tidak mengecilkan position_size → margin/heat overstated

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | [monitor.py:443-465](agents/futures/monitor.py:443): TP1 partial book 33% profit, tapi `trade.position_size` tetap penuh sampai close |
| **Dampak** | Locked margin & portfolio heat ([compute_futures_sizing](backend/app/api/v1/balance.py:223)) menghitung posisi penuh padahal 33% sudah dijual → over-estimate eksposur, blokir open baru yang sebenarnya boleh |
| **Fix** | Kurangi position_size saat partial, atau hitung locked margin dari sisa fraksi |

### BUG-L18 — 🔴 HIGH — discovery (gainers/losers/new-listing) TERPUTUS dari trading

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P3) |
| **Akar** | [futures_market.py:240-246](backend/app/api/v1/futures_market.py:240) hitung top_gainers/losers/new_listings/big_movers — **hanya untuk dashboard**. Scanner ([scheduler.py:110](agents/futures/scheduler.py:110)) jalan di universe **volume** + funding ekstrem, tak konsumsi daftar itu |
| **Dampak** | (a) Top gainer di luar top-150 volume tak pernah dilihat agent; (b) top loser ekstrem (−59%) di luar rentang agent3; (c) **new listing ditampilkan tapi TIDAK ADA agent yang trading**; discovery yang sudah ada terbuang |
| **Fix** | Inti refactor Lane B + Lane C: sambungkan discovery futures_market.py ke logika open-posisi (R-4, R-5, R-7) |

### BUG-L19 — 🟡 MEDIUM — P&L trade "expired" (termasuk TP1 partial terkunci) hilang dari balance

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | `FUTURES_CLOSED_STATUSES=("tp","sl")` kecualikan "expired" dari [_update_futures_balance:198-204](agents/futures/monitor.py:198). Tapi trade expired tetap punya `pnl_dollar` (apalagi jika TP1 partial sudah jual 33%) |
| **Dampak** | Profit/rugi nyata dari trade expired tak tercermin di wallet — balance divergen dari realita. Exclude dari win-rate OK, tapi exclude dari BALANCE salah |
| **Fix** | Balance sum harus sertakan expired (uang nyata bergerak); win-rate tetap exclude |

---

## ═══ AUDIT UI FUTURES 2026-06-14 (UI-1..UI-8) ═══

> Audit frontend: Scanner page, History (Overview/Monitor/Analytics). Data untuk refactor UI
> mengikuti 1 Scanner + 1 Monitor. File: [scanner/page.tsx](frontend/src/features/scanner/page.tsx),
> [FuturesTab.tsx](frontend/src/features/history/components/FuturesTab.tsx),
> [FuturesAnalytics.tsx](frontend/src/features/history/components/FuturesAnalytics.tsx).

### UI-1 — 🔴 HIGH — Tab Analytics SELURUHNYA masih 2-agent (agent3 hilang total)

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [FuturesAnalytics.tsx](frontend/src/features/history/components/FuturesAnalytics.tsx): `LearningStats` (baris 10-11) tanpa agent3; `wAgent` state (168) `"all"\|"agent1"\|"agent2"`; header "Agent 1 vs Agent 2" (262); head-to-head cards (268-272); BarCompare (314-323); per-agent progress (397-400); weight filter (534) tanpa agent3; aBadge (573) agent3→ungu; label (581) agent3→"T4" |
| **Dampak** | Seluruh analitik agent3 (Momentum) tak terlihat — win-rate, signal weight, perbandingan semua abaikan agent3. Tab Analytics dirender via subTab "analytics" → aktif dipakai |
| **Fix** | Saat refactor 1 Scanner: analytics jadi per-`setup_type` (Pre-Move/Gainer/Loser/New), bukan per-agent. Untuk sementara: tambah agent3 |

### UI-2 — 🔴 HIGH — `filtered` useMemo TIDAK punya `agent3` di dependency array

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [scanner/page.tsx:562](frontend/src/features/scanner/page.tsx:562): deps `[agent1, agent2, activeAgent, minScore, dirFilter, search]` — `agent3` dipakai di body (554-555) tapi **tak ada di deps** |
| **Dampak** | Saat data agent3 update via WS/scan, daftar sinyal tidak re-compute → sinyal momentum basi/tak muncul sampai trigger lain |
| **Fix** | Tambah `agent3` ke dependency array |

### UI-3 — 🟡 MEDIUM — kondisi loading/empty hanya cek agent1+agent2

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [scanner/page.tsx:747,781,789](frontend/src/features/scanner/page.tsx:747): `!agent1.length && !agent2.length` dan `(agent1.length > 0 \|\| agent2.length > 0)` — agent3 diabaikan |
| **Dampak** | Jika hanya agent3 yang punya sinyal: spinner loading tetap tampil / pesan "belum ada data" salah muncul |
| **Fix** | Sertakan agent3 di semua kondisi |

### UI-4 — 🟡 MEDIUM — threshold AUTO hardcode "≥72" (tak ikut adaptive)

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | SignalCard badge `s.score >= 72` ([scanner/page.tsx:124](frontend/src/features/scanner/page.tsx:124)); teks auto-trade "Score ≥ 72pt" (699); MIN select "72pt Auto" (729) |
| **Dampak** | Threshold sebenarnya adaptif 70-77 per-agent ([weight_updater.py:120-131](agents/futures/weight_updater.py:120)). UI selalu tampil 72 → menyesatkan kapan coin benar-benar auto-open |
| **Fix** | Ambil threshold efektif dari API (sudah ada `autoThreshold` state di FuturesTab F26/F10) dan tampilkan dinamis |

### UI-5 — 🟡 MEDIUM — kartu posisi hitung notional/margin/liq di CLIENT (bukan dari backend)

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [FuturesTab.tsx:261-263](frontend/src/features/history/components/FuturesTab.tsx:261): `calcNotional(p.risk_pct)`, `calcMargin`, `calcLiqPrice` hitung ulang dari `risk_pct` + fallback `$10`, bukan pakai `position_size`/`margin` tersimpan dari backend |
| **Dampak** | Margin & liq yang ditampilkan **divergen** dari nilai sebenarnya (apalagi setelah BUG-L4: notional nyata membengkak). User lihat angka margin/liq palsu |
| **Fix** | Pakai `position_size`/`margin`/`risk_dollar` dari API, jangan hitung ulang di client |

### UI-6 — 🟢 LOW — penamaan agent tidak konsisten antar-tab

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | Analytics pakai "Agent 1 — AI Knowledge", "Agent 2 — T0-T4" ([FuturesAnalytics.tsx:269-272](frontend/src/features/history/components/FuturesAnalytics.tsx:269)); Scanner pakai "Pre-Gainer/Accumulation/Momentum" |
| **Dampak** | Agent yang sama bernama beda di tab berbeda → membingungkan |
| **Fix** | Satu sumber penamaan (saat refactor: nama per setup_type) |

### UI-7 — 🟢 LOW — judul & teks Scanner masih framing "Pre-Gainer / 2 agent"

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [scanner/page.tsx:595-596](frontend/src/features/scanner/page.tsx:595) judul "Futures Pre-Gainer Scanner"; loading text "Agent 1 + Agent 2 · 150 pairs" (753) |
| **Dampak** | Tak mencerminkan momentum/agent3 maupun new-listing |
| **Fix** | Update copy saat refactor jadi 1 Scanner multi-lane |

### UI-8 — 🟡 MEDIUM — data likuidasi sintetis ditampilkan seolah USDT nyata

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | SignalCard [scanner/page.tsx:167,172](frontend/src/features/scanner/page.tsx:167): `Liq L ${s.liq_long.toFixed(1)}M` — tampilkan proksi sintetis (BUG-L14) sebagai "$X.XM" |
| **Dampak** | User percaya itu likuidasi USDT nyata, padahal angka arbitrer dari ratio × 1jt |
| **Fix** | Sembunyikan/labeli sebagai proksi sampai BUG-L14 (sumber data nyata) beres |

---

## ═══ AUDIT FINAL PRA-REFACTOR 2026-06-14 (L20-L24) ═══

> Sapu area terakhir: WebSocket stream, endpoint status, trading_costs, risk dashboard, agent scoring.

### BUG-L20 — 🔴 CRITICAL — WebSocket stream BUANG agent3 → agent3 terhapus dari UI live

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [futures_stream.py:33-39,55-61,70-71](backend/app/ws/futures_stream.py:33): snapshot & heartbeat hanya kirim `agent1`+`agent2`; `next_scan_in` hanya cek `["agent1","agent2"]` |
| **Dampak** | **PALING PARAH untuk UI**: frontend `applySnapshot` baca `data.agent3 ?? []` → tiap update WS, agent3 di-set `[]` (terhapus). Momentum (agent3) cuma muncul sekejap setelah manual scan, lalu hilang pada heartbeat WS berikutnya. Inilah kenapa agent3 "kedip-kedip"/hilang di scanner live |
| **Fix** | Kirim agent3 di snapshot + heartbeat; `next_scan_in` sertakan agent3 |

### BUG-L21 — 🟡 MEDIUM — `get_futures_status` tak laporkan agent3

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM (edit dulu ditolak user) |
| **Akar** | [futures_scanner.py:362-380](backend/app/api/v1/futures_scanner.py:362): tak ada `agent3_last_scan`/`agent3_results`; `last_ts = max(ts_a1, ts_a2)` abaikan timing agent3 |
| **Dampak** | Widget status scanner & countdown next-scan tidak akurat untuk agent3 |
| **Fix** | Tambah agent3_last_scan/results + sertakan di max() last_ts |

### BUG-L22 — 🟡 MEDIUM — `futures_notional`/`futures_pnl_dollar` hardcode $1000

| Field | Detail |
|-------|--------|
| **Status** | ❌ BELUM |
| **Akar** | [trading_costs.py:36-46](backend/app/services/trading_costs.py:36): hitung notional/pnl dari `FUTURES_STARTING_BALANCE=1000` flat |
| **Dampak** | Fallback legacy & sebagian path P&L abaikan wallet nyata (jika deposit, wallet >1000). Divergen dari Phase 9 real-balance |
| **Fix** | Saat refactor: semua P&L/notional dari position_size tersimpan + wallet nyata, bukan konstanta |

### BUG-L23 — 🔴 HIGH — Risk dashboard hitung margin/liq dari $1000, bukan position_size tersimpan

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P1) |
| **Akar** | [futures_scanner.py:461-463](backend/app/api/v1/futures_scanner.py:461): `risk_pct=meta.get(...,2.0)`, `notional=_notional(risk_pct)` (=$1000 helper), `margin=_margin(...)` — abaikan `t.position_size` nyata |
| **Dampak** | Tab Monitor (Posisi Terbuka) tampilkan margin, total_margin, liq, heat dihitung off $1000 — **divergen dari realita**, apalagi setelah BUG-L4 notional membengkak. Ini akar BACKEND dari UI-5 |
| **Fix** | Pakai `t.position_size`/`t.risk_dollar` tersimpan untuk semua perhitungan dashboard |

### BUG-L24 — 🟢 LOW — agent3 secara desain mendorong "SL ketat"

| Field | Detail |
|-------|--------|
| **Status** | ✅ SELESAI (P2) |
| **Akar** | [agent3.py:159](agents/futures/agent3.py:159): teks sinyal "Momentum kuat — ikuti dengan SL ketat" |
| **Dampak** | Filosofi agent3 membakukan SL ketat (memperkuat BUG-L3/L7 untuk momentum) |
| **Fix** | Lane momentum tetap pakai SL floor sadar-leverage; jangan "SL ketat" untuk leverage tinggi |

---

## Urutan Eksekusi (disarankan)

1. **BUG-L1** (dedup global) — paling merusak data, perbaiki dulu
2. **BUG-L3** (SL floor) — penyebab utama WR 0%
3. **BUG-L2** (RAR gate) — paling tidak mendesak, sample kecil bikin gate noise

> Setiap bug = commit terpisah (aturan user: "setiap phase di commit").
> Reset DB futures sebelum validasi WR (data lama tercemar SL ketat + duplikat):
> ```sql
> DELETE FROM paper_trades   WHERE style LIKE 'futures%';
> DELETE FROM paper_balance  WHERE style = 'futures';
> DELETE FROM balance_transactions WHERE style = 'futures';
> ```
