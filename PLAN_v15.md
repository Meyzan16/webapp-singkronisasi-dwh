# PLAN_v15 — Anti Loss-Day: Stop Kejadian "Sabtu 4 Juli" Terulang

Tanggal: 2026-07-09 · Status: **DIIMPLEMENTASI 2026-07-09 — semua fase kode selesai,
menunggu restart backend + validasi 30 hari (§5)**
Cakupan: 4 Futures Agents (agent1 pre-gainer, agent2 accumulation, agent3 momentum,
agent_bigmover) + Futures Monitor + Risk Gate + Auto Trader.

## Status implementasi (2026-07-09)

| Fase | Status | Lokasi utama |
|---|---|---|
| P1 daily loss breaker 2.5% | ✅ | `risk_gate.evaluate_daily_gates()` + `auto_trader` |
| P2 consecutive-SL pause (3/lane 12h, 5/global 6h) | ✅ | `risk_gate._consec_pauses()` — stateless dari DB, restart-safe |
| P3a breadth fade-day gate (BM LONG diblok bila ≥60% top gainer fading 1h) | ✅ | `scheduler._run_scan` → `store.set_market_breadth` → `auto_trader` |
| P3b BM budget 6/hari + stop setelah 2 SL/hari | ✅ | `auto_trader` |
| P3c weekend damper (size ×0.5 + MIN_SCORE+5, WIB) | ✅ | `agent_bigmover` |
| P3d direction cap (max 4 searah) | ✅ | `auto_trader` |
| P4 BM breakeven-arm floor +1.5% + partial 50% @ ½-TP1 | ✅ | `monitor._compute_trail` + blok 3a-BM |
| P5 offline reconcile (startup + gap >15 mnt) | ✅ | `monitor.reconcile_offline_positions()` |
| P7 7 knob baru di agent_config (+ seeded ke DB) + API `plan_v15` section | ✅ | `agent_config_defaults.py`, `agent_config.py` |
| P8 daily profit lock 1% (+giveback floor 0.3%) + tighten monitor | ✅ | `risk_gate` + `auto_trader` + `monitor` |
| P9 fail-fast (−1×ATR, 10-45 mnt, tanpa progres, konfirmasi 1m) | ✅ | `monitor` |
| R0a backfill exact-horizon + path-aware bracket + per-horizon repick | ✅ | `big_mover_logger.py` (catch-up berjalan; data lama pre-09-Jul TETAP ada tapi endpoint-biased — jangan dipakai riset) |
| R0b replay validasi fail-fast | ✅ hasil di bawah | scratchpad script |
| R0c analisis BM arah (data exact-horizon) | ✅ hasil di bawah | big_mover_log |
| R0d near-miss log agent1/2 (band 52-64) ke rejection_log | ✅ | `auto_trader` (`reason="below_auto_threshold"`) |
| P6 kalibrasi skor agent1/2 | ⏳ menunggu 3 hari data R0d | — |
| Bonus bugfix | ✅ atr_pct kini ikut di sinyal a1/a2/a3 (G4 rugpull sebelumnya selalu pakai ambang 5% karena atr_pct=0); fast-loop close kini menghitung partial yang sudah dibank (dulu hilang) | agents + monitor |

**Hasil R0b (replay 1m klines pada 23 trade closed):** fail-fast trigger 4×,
semuanya loser, **0 winner terbunuh** — parameter default `failfast_atr_mult=1.0`
aman. Net solo +$1.01 (2 trigger memotong lebih baik, 2 sedikit lebih buruk dari
scratch). Loser besar (ACT/GWEI/MIRA, peak +1.3-3%) tidak tersentuh fail-fast karena
sempat favorable — pola itu ditangani P4 breakeven-arm +1.5% (ACT peak +2.97% → armed).
Kandidat tuning setelah data live: BM_BE_ARM_ABS_PCT 1.5 → 1.2 (GWEI peak +1.35% lolos tipis).

**Hasil R0c (3.579 baris exact-horizon, path-aware bracket SL4%/TP12%, periode 29-30 Jun):**
- LONG chase: **203 TP : 1.830 SL (1:9), EV ≈ −1,4%/sinyal** — lebih buruk dari estimasi kasar.
- SHORT dump: **276 TP : 292 SL (WR 49%), open avg +5,3%, EV ≈ +4,1%/sinyal.**
- Skor TIDAK menyelamatkan LONG: bucket skor ≥70 pun 3 TP : 20 SL. Gate skor bukan
  jawaban untuk LONG chase — yang implemented (breadth + budget + weekend + direction
  cap) adalah jawaban yang benar.
- Keputusan: BM LONG tetap diizinkan tapi di belakang semua guard P3; JANGAN dibuka
  longgar. Re-evaluasi dengan 7 hari data exact-horizon (scheduler mengisi otomatis
  150 baris/20 mnt) — jika LONG tetap 1:5+ SL:TP di kondisi breadth sehat sekalipun,
  pertimbangkan BM SHORT-bias. Data pnl_* yang terisi sebelum 2026-07-09 malam adalah
  endpoint-biased — SELALU filter `last_backfill_at > 1783600000` untuk riset.

**Status live 2026-07-10 pagi:** backend hot-reload → seluruh PLAN_v15 AKTIF
(API `/agent/config` → futures.plan_v15.daily_gates berjalan; day 10 Jul: +$1.91, WIN).

---

## 0. Target resmi: 25 hari WIN : 5 hari LOSS per 30 hari

Update 2026-07-09 (revisi tujuan dari user): bukan "profit setiap hari", melainkan
**dari 30 hari trading, 25 hari ditutup profit dan maksimal 5 hari loss** (day-level
win rate ≥ 83%), dengan hari loss dibatasi kecil.

### Matematika target — apa yang harus benar supaya 25:5 tercapai

Kondisi aktual (26 trade closed sejak reset DB):

| Metrik | Aktual | Dibutuhkan untuk 25:5 |
|---|---|---|
| WR per trade | 26.9% | ≥ 45% win + ≥ 35% scratch (non-loss rate ≥ 80%) |
| Loss "merusak" (sl_hit/max_age/liq) | 42% dari trade, avg −$11 | ≤ 20% dari trade, avg ≤ −$5 |
| Avg win / avg loss | $7.55 / −$6.35 (≈1.2) | ≥ 1.4 dengan loss dipangkas fail-fast |
| Expectancy per trade | **−$2.61** | ≥ +$1.5 |
| Hari win : hari loss | 1 : 2 (3 hari data) | 25 : 5 |

Anatomi kerugian per close-reason (data aktual — kunci diagnosis):

```
sl_hit             7 trade  −$78.05   ← pembunuh #1 (avg −$11.15, semuanya BM/momentum)
max_age_expired    2 trade  −$28.14   ← pembunuh #2 (backend mati, posisi bleed offline)
time_stop_scratch  9 trade   −$3.55   ← SUDAH SEHAT (avg −$0.39, ini fungsi yang benar)
breakeven_stop     4 trade   −$1.55   ← SUDAH SEHAT
winners            4 trade  +$43.57
```

Kesimpulan struktural: **sistem scratch/breakeven sudah bekerja** — yang menghancurkan
hari adalah (a) full SL yang tidak pernah bergerak favorable (peak loser cuma
+0.2–3%: salah ENTRY, bukan salah exit), dan (b) posisi tak termonitor saat backend
mati. Maka jalur ke 25:5 = **cegah entry buruk masuk (P2/P3) + kunci hari hijau (P8)
+ potong loser lebih cepat (P9) + cap hari merah (P1)** — bukan memperbesar target
profit.

Simulasi day-level dengan profil sesudah fix (≈4 trade tuntas/hari; 45% win +$6,
35% scratch −$0.4, 20% loss −$5): EV hari ≈ +$8, P(hari merah) ≈ 10–17% → **25-27
hari win per 30 hari**. Profil ini yang dikejar semua fase di bawah.

---

## 1. Forensik Sabtu 2026-07-04 (data DB, WIB)

**Hasil hari itu: 22 trade ditutup, 6 menang, net −$40.81 (≈ −4.1% wallet).**

| Lane | Trades | Win | PnL | Catatan |
|---|---|---|---|---|
| bigmover (agent_bigmover) | 13 | 4 | **−$41.95** | ≈ seluruh kerugian hari itu |
| momentum (agent3) | 8 | 2 | +$1.79 | selamat karena scratch/breakeven |
| accumulation (agent2) | 1 | 0 | −$0.65 | breakeven stop |
| pre_gainer (agent1) | 0 | — | — | dormant (0 trade sepanjang sejarah) |

Pola BigMover hari itu (semua kecuali 1 = **LONG** di top-gainer):

```
14:45 VELVET  −$1.95  flash_dump_exit     peak +3.2%
15:16 BEL    −$10.23  sl_hit              peak +0.2%
16:02 NAORIS  −$4.47  time_stop_scratch   peak +0.2%
16:16 GWEI   −$10.08  sl_hit              peak +1.3%
17:47 ACT    −$10.01  sl_hit              peak +3.0%
18:02 GUN     −$9.94  sl_hit              peak +1.0%
19:39 VELVET −$11.08  sl_hit (re-entry!)  peak +1.0%
21:18 MIRA   −$10.27  sl_hit              peak —
(win: ALCH +2.80, HMSTR +8.93, OGN +12.68, EPIC +1.84)
```

Karakter hari itu: **Sabtu (likuiditas tipis), pump-and-fade** — koin top-gainer
di-pump lalu di-dump. BigMover mengambil arah dari tanda `change_24h` → membeli
puncak sepanjang hari, 6× SL penuh @ ≈ −$10, dan **terus buka posisi baru setelah
setiap SL** sampai jam 21:18.

Kerugian susulan (bukan 4 Juli tapi akar sama): XAGUSDT agent2 **−$24.89**
`max_age_expired` — dibuka 5 Juli, backend MATI 5–9 Juli, posisi tak termonitor
4,7 hari (SL tidak dieksekusi retroaktif; monitor cuma lihat wick 6 menit terakhir).

## 2. Kenapa SEMUA pengaman yang ada gagal menghentikannya

| Guard yang ada | Kenapa tidak bekerja 4 Juli |
|---|---|
| Circuit breaker DD 15% dari peak (risk_gate) | Hari −4% tidak pernah menyentuh 15% |
| RAR gate (Sharpe rolling 20 < −0.5) | 1 winner besar (+$23.9 STORJ) menjaga Sharpe di atas ambang |
| Lane WR auto-pause (WR<35%, sampel 10-20) | BM baru punya ~13 trade closed total; pause butuh sampel penuh & baru dievaluasi dari trade CLOSED — telat satu hari |
| Cooldown simbol 3 jam setelah SL | Hanya per-simbol. VELVET re-entry jam 18:34 (>3h) → SL lagi. Lane-nya sendiri bebas buka koin LAIN tanpa batas |
| Regime filter (volatile→blok) | BigMover **bypass regime** (`regime="n/a"`), by design |
| Entry timing gate P3 (wick/chase) | Hanya dipakai agent1/2/3 — BigMover tidak memanggil `entry_timing_ok` |
| Daily loss limit | **TIDAK ADA di futures.** Spot sudah punya (`spot.daily_loss_limit_pct=3`, WIB) — futures tidak pernah dapat fitur ini |
| Direction concentration | Tidak ada — 21/22 posisi hari itu LONG serentak |

Ditambah **asimetri exit** yang membuat hari choppy pasti minus:
time-stop scratch memotong winner kecil (+0.5%…+1.3%) tapi loser dibiarkan lari ke
SL penuh (−4%…−8%). Breakeven-arm BM (40% jarak ke TP1 = ~2-3% move) hampir tak
pernah tercapai — peak loser cuma 0.2–3.2%.

---

## 3. Rencana implementasi

### R0 — Riset data (SEBELUM fase parameter-sensitif; P8/P1/P2/P5 tidak menunggu ini)

Temuan awal (2026-07-09, dari `big_mover_log` 29rb sinyal, backfill 29 Jun–2 Jul):
- Simulasi bracket SL4%/TP12% semua sinyal big-mover futures:
  **LONG = 348 TP : 2.712 SL (WR 11%, EV ≈ −0,8%/sinyal)** vs
  **SHORT = 737 TP : 631 SL (WR 54%, EV ≈ +4,0%/sinyal)**.
- Forward 24h per hari: LONG negatif di SEMUA hari yang ada datanya (30 Jun avg
  −9,6%, hanya 22% positif); SHORT positif di semuanya (63–69% positif).
- Konsekuensi: bias struktural periode ini = pump di-fade, dump berlanjut. BM 4 Juli
  buka 12 LONG : 1 SHORT — kebalikan arah ber-edge. P3 harus lebih keras dari draft
  awal (pertimbangkan BM bias-SHORT / LONG hanya dengan bukti breadth sehat).

Tugas R0:
- **R0a** — Perbaiki backfill `big_mover_log`: `pnl_1h/4h/24h` saat ini diisi harga
  ketika backfill jalan, BUKAN harga eksak di horizon (nilai 1h==4h identik), dan
  backlog menumpuk (24h baru terisi s/d 2 Jul). Ganti ke klines-based exact-horizon
  + naikkan throughput backfill. Fondasi semua riset lanjutan.
- **R0b** — Replay klines 1m untuk semua trade closed: simulasikan P9 fail-fast
  (−1×ATR/30m) & P4 breakeven-arm dini → hitung berapa loser terpotong vs winner
  yang ikut terbunuh. Output: nilai `failfast_atr_mult` + be-arm yang terbukti.
- **R0c** — Analisis `big_mover_log` per max_score/funding/OI: kondisi yang membuat
  LONG chase layak (jika ada); keputusan BM bias arah per regime.
- **R0d** — Instrumentasi distribusi skor 52–64 agent1/2 (bagian P6), 3 hari data.

### P1 — Daily loss circuit breaker FUTURES (WAJIB, akar masalah #1)
Port `_daily_loss_breaker_active()` dari `agents/opportunity/scheduler.py:96-116`
ke futures:
- Hitung Σ `pnl_dollar` trade futures yang closed **hari ini (WIB)**.
- Jika ≤ −(balance × `futures.daily_loss_limit_pct`/100) → **blok semua auto-open**
  sampai ganti hari WIB. Default **2.5%** (lebih ketat dari spot karena leverage).
- Lokasi cek: awal `auto_open_positions()` (`agents/futures/auto_trader.py`),
  sebelum ranking — plus expose state ke risk dashboard (`gate_type="daily_loss"`).
- Config baru di `agent_config`: `futures.daily_loss_limit_pct` (default 2.5).
- Saat breaker aktif: monitor melakukan **tighten-to-breakeven** untuk posisi yang
  profit (pakai mekanisme `emergency_tighten` G10 yang sudah ada — panggil dengan
  flag baru, bukan hanya saat DD 15%).

### P2 — Consecutive-SL breaker per lane + global (deteksi cepat hari buruk)
Jauh lebih cepat dari WR-pause (yang butuh 10-20 sampel):
- **Per lane**: 3 close beruntun berjenis loss nyata (`sl_hit`, `max_margin_loss`,
  `liq_guard`, `flash_dump_exit` dengan pnl<0 — BUKAN `breakeven_stop`/`sl_plus`/scratch profit)
  dalam ≤ 6 jam → pause lane 12 jam. Config: `futures.lane_consec_sl_pause` (default 3).
- **Global**: 5 loss nyata beruntun lintas lane dalam ≤ 6 jam → pause SEMUA lane 6 jam.
- Implementasi di `risk_gate.py` (state in-memory + evaluasi dari `closed_at` DB
  saat startup supaya restart tidak reset hitungan). `is_lane_paused()` sudah ada —
  tinggal tambah sumber pause kedua.
- 4 Juli dengan aturan ini: BEL(15:16) → GWEI(16:16) → ACT(17:47) = pause BM 17:47.
  GUN, VELVET#2, MIRA (−$31) tidak pernah terjadi. Kerugian hari ≈ −$22, bukan −$41.

### P3 — BigMover fade-day guards (akar masalah #2)
BigMover adalah satu-satunya lane tanpa regime & tanpa timing gate. Tambahkan:
- **a. Breadth check sebelum BM LONG**: dari universe scan yang sudah ada, hitung
  fraksi top-gainer (change_24h>10%) yang `change_1h` NEGATIF. Jika > 60% top
  gainer sedang fade → tolak BM LONG baru (market sedang pump-and-fade). Murah:
  data ticker sudah ada di scheduler.
- **b. Budget harian BM**: maks 6 entry BM/hari (WIB); setelah **2 SL BM di hari
  yang sama** → BM tutup sampai ganti hari. Config: `futures.bigmover_daily_sl_stop` (default 2).
- **c. Weekend damper**: Sabtu/Minggu (WIB) → BM `size_mult ×0.5` dan `MIN_SCORE +5`.
  Config: `futures.weekend_size_mult` (default 0.5).
- **d. Direction concentration cap** (semua lane): maks 4 dari 6 slot global searah.
  Kandidat searah ke-5 ditolak. Config: `futures.max_same_direction` (default 4).

### P4 — Perbaiki asimetri exit BigMover (winner kecil vs loser penuh)
- Breakeven-arm BM: dari 40% jarak ke TP1 → **arm saat +1.0×ATR ATAU +1.5% harga**
  (mana yang tercapai duluan). Peak +3% (VELVET, ACT, DOGS) langsung terlindungi.
- Partial de-risk BM: saat +1×ATR, tutup 50% posisi (BM tidak punya TP1-partial
  33% seperti lane lain karena TP1-nya jauh, ATR×2).
- Efek 4 Juli: ACT (peak +3.0%) & VELVET#1 jadi ≈ breakeven, bukan −$10/−$2.

### P5 — Offline catch-up reconciliation di monitor (kasus XAG −$24.89)
Saat monitor start ATAU `last_tick_at` posisi > 15 menit yang lalu:
- Fetch klines 1m/5m dari `max(entry_at, last_tick_at)` s/d sekarang.
- Kalau SL/TP tersentuh selama offline → close retroaktif di harga SL/TP
  (`close_reason="offline_reconcile_sl|tp"`), bukan biarkan posisi bleed berhari-hari
  lalu `max_age_expired` di harga terburuk.
- Lokasi: `agents/futures/monitor.py` — jalankan sekali di `run_futures_monitor()`
  setelah `_update_futures_balance()`, dan per-trade bila gap tick terdeteksi.

### P6 — Hidupkan lane pre-gainer/accumulation (diversifikasi anti hari-BM-buruk)
Fakta: agent1 **0 trade sepanjang sejarah**; max score yang pernah tercatat di
rejection_log ≈ 51 dari ~190rb evaluasi (ambang 52, auto-open 65). Scoringnya
tidak pernah bisa menang → 2 dari 4 lane mati, wallet bergantung pada BM+momentum.
- Instrumen dulu: log distribusi skor 52–64 (yang lolos min tapi gagal auto-open)
  ke `rejection_log` juga (saat ini hanya <min yang di-log) — 3 hari data.
- Baru kalibrasi: turunkan bobot yang tidak pernah fire / naikkan poin sinyal inti
  supaya setup bagus realistis mencapai 65. JANGAN turunkan ambang membabi-buta
  (PLAN_v14 sudah menurunkan 72→65 tanpa efek — masalahnya di skor, bukan ambang).

### P7 — Expose semua knob baru ke agent_config + UI Architecture
`futures.daily_loss_limit_pct`, `futures.lane_consec_sl_pause`,
`futures.bigmover_daily_sl_stop`, `futures.weekend_size_mult`,
`futures.max_same_direction`, `futures.daily_profit_lock_pct`,
`futures.failfast_atr_mult` → `backend/app/services/agent_config_defaults.py`
+ tampil di halaman Architecture (pola PLAN_v5 Group C yang sudah ada).

### P8 — Daily profit lock (mesin pencetak "hari win" — inti target 25:5)
Kebalikan dari P1. Hari hijau HARUS ditutup hijau:
- Track realized PnL futures hari ini (WIB). Saat mencapai **+1.0% wallet**
  (`futures.daily_profit_lock_pct`, default 1.0):
  1. Semua posisi open yang profit → trail SL dinaikkan agar minimal breakeven+fee
     (pakai jalur `emergency_tighten` yang sudah ada di monitor, flag baru
     `profit_lock_tighten`).
  2. Auto-open baru hanya untuk kandidat A-grade (score ≥ 80) dengan size ½ —
     "main pakai uang menang", bukan berhenti total (agar hari trending besar
     tetap bisa jadi big-win day).
- Saat realized day-PnL turun kembali ke +0.3% wallet setelah lock aktif →
  stop total auto-open sampai ganti hari (proteksi giveback terakhir).
- Bukti dari data 4 Juli: pukul 15:53 (STORJ +$23.9) day-PnL sempat **+$11.7
  (+1.25%)** — profit lock akan mengubah hari −$40.81 itu menjadi hari ± breakeven
  bahkan sebelum P2/P3 bekerja.
- Lokasi: helper `_daily_pnl_wib()` dipakai bersama P1 (satu query), cek di
  `auto_open_positions()` + trigger tighten di `monitor.check_futures_positions()`.

### P9 — Fail-fast exit: potong loser sebelum jadi −$11
Data: SEMUA loser sl_hit punya peak ≤ +3% dan mayoritas ≤ +1% — thesis momentum
yang benar bergerak favorable segera; yang langsung melawan hampir tidak pernah
pulih. Maka:
- Untuk lane momentum + bigmover: jika dalam **30 menit** pertama posisi bergerak
  **−1.0×ATR melawan arah** (`futures.failfast_atr_mult`, default 1.0) DAN belum
  pernah mencapai +0.3×risk favorable → close market (`close_reason="fail_fast"`).
- Ini melengkapi time-stop (yang menunggu 90m dan hanya scratch dekat breakeven,
  PLAN_v11 B2 sengaja membiarkan loser dalam ke SL — celah itulah avg −$11).
  Fail-fast menutup di ≈ −ATR (−2-4% harga) bukan −5-8%: avg loss merusak turun
  dari −$11 → ≈ −$5, tepat profil yang dibutuhkan §0.
- Guard anti-noise: minimal hold 10 menit (selaras `RUGPULL_MIN_HOLD_MIN`),
  dan hanya bila candle 1m konsisten melawan (bukan satu wick).

---

## 4. Urutan pengerjaan & estimasi dampak

Kontribusi tiap fase ke target 25:5 — dua sisi yang berbeda:

**Sisi "kurangi hari loss" (5 hari merah maks, dan merahnya kecil):**

| Prioritas | Fase | Dampak pada 4 Juli (simulasi) |
|---|---|---|
| 1 | P8 daily profit lock | 4 Juli sempat +1.25% jam 15:53 → hari ditutup ± breakeven, bukan −$40.81 |
| 2 | P1 daily loss breaker | Hari terburuk dipatok maks −2.5% |
| 3 | P2 consecutive-SL pause | BM berhenti jam 17:47 → −$31 tak terjadi |
| 4 | P9 fail-fast exit | 6× sl_hit @ −$10 jadi @ ≈ −$4-5 → total SL hari itu ≈ −$28 lebih ringan |
| 5 | P3 BM fade-day guards | Mayoritas LONG BM sore itu tidak dibuka |
| 6 | P5 offline reconcile | XAG −$24.89 tidak terulang |

**Sisi "perbanyak hari win" (25 hari hijau):**

| Fase | Mekanisme |
|---|---|
| P8 | Hari yang SEMPAT hijau dikunci hijau (ini pengubah day-WR terbesar) |
| P4 | Breakeven-arm dini + partial → lebih banyak trade non-loss |
| P9 | Loss kecil → satu winner biasa cukup menutup 1-2 loser → hari tipis tetap hijau |
| P6 | Lane pre-gainer/accumulation hidup → sumber winner tambahan di hari BM sepi |
| P2/P3 | Entry busuk tidak masuk → WR per trade naik dari 27% ke arah 45%+ |

Gabungan (simulasi 4 Juli): P8 sendiri sudah membalik hari itu jadi ± 0; P1+P2+P3+P9
membuat skenario terburuknya −$10 s/d −$15 (−1.1 s/d −1.6%), dalam batas "hari loss
kecil" yang ditoleransi target 25:5.

## 5. Gate validasi (pola PLAN_v6 P7) — diukur terhadap target 25:5

Evaluasi mingguan setelah deploy P1–P4+P8+P9, keputusan gate di hari ke-30:
- **Gate utama (hari ke-30): ≥ 25 hari WIN dari 30 hari kalender WIB yang ada
  trade tuntas; hari loss maks 5 dan tak ada yang < −2.5% wallet.**
- Proksi mingguan (hari ke-7/14/21): day-WR berjalan ≥ 80%; jika < 70% dua minggu
  berturut → review desain, jangan tunggu hari ke-30.
- Tidak ada hari kalender (WIB) dengan realized PnL < −2.5% wallet. **(gate keras)**
- Tidak ada lane dengan >3 SL nyata beruntun tanpa ter-pause otomatis. **(gate keras)**
- Non-loss rate per trade ≥ 70% (win + scratch ±0.5%); loss merusak ≤ 20%, avg ≤ −$6.
- Expectancy per lane (query PLAN_v6 §P7c) > 0 ATAU WR > 40%, min 10 trade/lane.
- BM weekend: size ½ terverifikasi di `signals_json.size_mult` pada trade Sabtu/Minggu.

Query day-level WR (jalankan kapan pun):
```sql
SELECT to_char(to_timestamp(closed_at) AT TIME ZONE 'Asia/Jakarta','YYYY-MM-DD') day,
       round(sum(pnl_dollar)::numeric,2) pnl,
       CASE WHEN sum(pnl_dollar) > 0 THEN 'WIN' ELSE 'LOSS' END result
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('tp','sl','expired') AND pnl_dollar IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC;
```
