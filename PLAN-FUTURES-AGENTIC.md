# PLAN-FUTURES-AGENTIC — satu agen futures, sedikit posisi, tiap posisi terukur

Disusun 5 Sep 2026 dari audit kode + DB nyata. Direvisi hari yang sama setelah audit bug
jalur uang dan penegasan owner. Status: **RENCANA, belum dikerjakan.**

Tujuan owner, dikutip apa adanya:

> hapus semua kategori FUTURES jadikan hanya agentic trading FUTURES … size + lev itu masuk
> yang paling optimal jangan hanya masuk 3 dolar … profit yang terukur dan sl yang terukur
> … gak ada orang 0% di tutup nanti kemakan fee … semua parameternya tidak hardcode.
>
> size yang masuk itu terlalu kecil dan TP itu juga terlalu kecil. saya mau size dan lev
> itu yang paling optimal dan terukur — **bukan paling banyak posisi yang terbuka tapi
> posisi yang paling optimal dan terukur secara profit dan loss.**

---

## 0. Kenyataan hari ini (angka dari DB, 5 Sep 2026)

Wallet futures **$854,39** (mulai $1.000, realized **−$145,61**). 112 trade tertutup, 0 terbuka.

### 0.1 Ukuran posisi memang sekecil yang dikeluhkan

| ukuran | median |
|---|---|
| risk per trade (`risk_dollar`) | **$4,98** |
| jarak SL (harga) | 5,28 % (p25 4,5 · p75 8,0) |
| notional | **$95,8** |
| margin | **$32,3** |
| leverage rata-rata | 2,6 – 3,8× |

Aritmetikanya: notional = risk ÷ SL% = $5 ÷ 5,28 % ≈ $95. Pada +1 % harga untung kotor $0,96;
fee bolak-balik 0,10 % + slippage ≈ $0,25 → bersih ±$0,70. **59 % trade tak pernah bergerak
lebih dari $2.**

Kenapa risk hanya $5 padahal aturannya 1 % × $854 = $8,5? Karena pengali dikalikan **bertumpuk**
di [agents/futures/auto_trader.py:605-640](agents/futures/auto_trader.py): probe ½ × profit-lock ½
× weekend ½ × funding-soft ½ × lane-throttle ½ × tier bigmover (risk 0,5 % sejak awal). Enam
pengali yang bisa menurunkan ukuran sampai 1/32 tanpa satu pun angka yang "memutuskan".

### 0.2 "TP terlalu kecil" — dalam dolar ya, dalam harga justru mustahil

Ini yang perlu diluruskan supaya perbaikannya tepat sasaran. TP **dalam persen harga** hari ini
**bukan kecil — median 18,4 %**, dipasang di **4–8 ATR**. Tapi trade rata-rata hanya bergerak
**0,67 ATR** ke arah untung lalu ditutup. Hanya 5 dari 112 (4 %) yang pernah menyentuh TP.

Jadi "TP kecil" yang Anda lihat di layar ($0,06 – $1,53) adalah hasil dua hal sekaligus:
1. notional $96 → +1 % harga hanya $0,96;
2. TP yang tak pernah tercapai, sehingga keluar sesungguhnya terjadi di breakeven +0,25 %.

Memperbesar TP dalam persen **tidak akan** memperbesar TP dalam dolar — ia hanya makin tak
tercapai. Yang memperbesar dolarnya: notional lebih besar **dan** TP di jarak yang pernah dicapai,
dengan pelari (trail) tanpa plafon untuk gerak besar. Itu desain §2.

### 0.3 Ledger keluar (107 baris) — mekanisme yang membuang untung

| alasan keluar | n | rata pnl% | total $ | MFE (ATR) | jarak TP (ATR) |
|---|---|---|---|---|---|
| `sl_plus` (breakeven/plus) | 31 | +0,25 | **+$9,41** (= $0,30/trade = fee) | 0,67 | 4,19 |
| `sl_hit` | 25 | −3,16 | −$58,48 | 0,14 | 4,00 |
| `hist:sl` | 35 | −0,51 | −$36,51 | 0,92 | 6,46 |
| `fail_fast` (+hist) | **11** | −3,6 / −9,0 | **−$79,09** | 0,3 | 8,5 |
| `tp2_hit` | 4 | +2,75 | +$11,70 | — | 4,00 |
| `hist:tp` | 1 | +13,04 | +$14,29 | 3,56 | 4,02 |

### 0.4 Empat kategori itu, dalam praktik, sudah satu

| lane | trade | hasil |
|---|---|---|
| bigmover | 91 | 86 SL / 5 TP, −$87 |
| momentum | 15 | 15 SL / 0 TP, −$55 — kuotanya sudah **0** |
| pre_gainer | 3 | −$13 |
| accumulation | 3 | +$10 |

81 % trade dari satu lane; tiga lainnya 21 trade dalam 2 bulan — tapi menyeret 4 pemindai
(2.764 baris), 4 set bobot (85 kunci), dan ⅔ dari 141 kunci config.

### 0.5 Yang sudah dinamis, yang belum

Mekanisme config dinamis **sudah ada**: `agent_config` (141 kunci futures), pembaca TTL 60 dtk
([agents/shared/config_reader.py](agents/shared/config_reader.py)), editor UI. Yang tertinggal
justru **rantai ukuran**:

| berkas | hardcode | dari config |
|---|---|---|
| [backend/app/api/v1/balance.py](backend/app/api/v1/balance.py) (sizing) | **18** | **0** |
| [agents/futures/utils.py](agents/futures/utils.py) (leverage cap) | **15** | **0** |
| [agents/futures/agent_bigmover.py](agents/futures/agent_bigmover.py) | 19 | 1 |
| [agents/futures/monitor_config.py](agents/futures/monitor_config.py) | 38 | 7 |
| [agents/futures/risk_gate.py](agents/futures/risk_gate.py) | 23 | 10 |

---

## 1. BUG yang ditemukan audit jalur uang (5 Sep 2026)

Diurutkan dari yang paling merusak. Tiap bug punya bukti, dampak, dan fase perbaikannya.

### B1 — "Menang" = `pnl_pct > 0`, jadi scratch selevel fee dihitung kemenangan ★★★

[agents/shared/trade_outcome.py](agents/shared/trade_outcome.py) (dibuat 10 Agu untuk memperbaiki
bug sebaliknya). Bukti DB:

| | |
|---|---|
| "menang" menurut `is_win` | 55 dari 110 → **WR resmi 50 %** |
| di antaranya hasil **< $0,50** | **38 (69 %)** |
| $0,50 – $1 | 5 |
| ≥ $3 | 7 |
| **WR bermakna (≥ $1)** | **10,9 %** |
| **WR ≥ $3** | **6,4 %** |

Dampak — label ini **dimakan tiga pengambil keputusan**:
- `weight_updater` ([:335-504](agents/futures/weight_updater.py)) melatih **setiap** bobot sinyal
  dengan label ini → sinyal yang menghasilkan +$0,30 dihargai sama dengan yang +$14.
- `risk_gate.update_lane_wr` → keputusan jeda lane berdasar WR 50 % fiktif.
- Ledger `outcome_tracker` → `realized_pnl` benar, tapi semua turunan WR-nya ikut fiktif.

Inilah kenapa engine belajar "tidak pernah mengalahkan baseline" (catatan 1 Agu): ia diajari
bahwa impas itu sukses. **Perbaikan → Fase 1** (definisi menang bersyarat `min_profit_usd`
dan `≥ K × biaya`, per market lewat config; SPOT tetap memakai definisinya sendiri).

### B2 — SL tidak dieksekusi di levelnya; rugi sampai 2,16× risiko yang direncanakan ★★★

| trade | lev | SL rencana | tutup di | rugi | risk | × risk | alasan tercatat |
|---|---|---|---|---|---|---|---|
| BLUAIUSDT (SHORT) | 2 | 7,99 % | **−17,30 %** | −$19,97 | $9,24 | **2,16×** | `fail_fast` |
| ARXUSDT | 3 | 4,29 % | −6,42 % | −$8,13 | $5,38 | 1,51× | `fail_fast` |
| SNXXUSDT | 3 | 6,63 % | −6,91 % | −$7,03 | $5,07 | 1,39× | `sl_hit` |

Mekanismenya, dari [agents/futures/monitor.py](agents/futures/monitor.py):
1. `fail_fast` dievaluasi di **baris 939**, cek SL/TP baru di **baris 1208** — dalam satu
   iterasi, harga yang sudah menembus SL ditangkap `fail_fast` dulu dan **dilabeli salah**.
2. Loop cepat (`FAST_INTERVAL_SEC`) hanya menyala bila lev ≥ 10, rugi margin ≥ 30 %, atau
   jarak likuidasi < 10 % — **bukan** kedekatan harga ke SL. BLUAI lev 2 dijaga loop lambat;
   koin kecil melompat +8 % → +17 % di antara dua tick.
3. `monitor_max_loss_pct_bigmover = 40 %` margin: −17,3 % × 2 = 34,6 % → penjaga ketiga pun lolos.

Rata-rata rugi di SL $3,97 vs risk $6,73 (0,62×) — jadi umumnya keluar **lebih dini** dari
rencana (fail_fast/time-stop), tapi ekornya **lebih dalam** dari rencana. Dua-duanya berarti
"kerugian tidak terukur". **Perbaikan → Fase 4** (SL selalu dicek **pertama**; loop cepat
dipicu oleh jarak ke SL ≤ 1 ATR; catat `sl_breach_pct` tiap tutup agar penyimpangan terukur).

### B3 — Ledger keluar bolong: 5 dari 112 trade tertutup tak punya `exit_events` ★★

`exit_events` hanya ditulis oleh `backfill_exit_events()`
([agents/learning/exit_learning.py:108](agents/learning/exit_learning.py)), bukan oleh monitor
saat menutup. Trade id 2967, 3000, 3032, 3097, 3119 (dua `expired`, tiga `sl`, termasuk 27 &
31 Agu) hilang dari ledger → exit-learning belajar dari 107, bukan 112. **Perbaikan → Fase 4**
(monitor menulis `ExitEvent` **di transaksi yang sama** dengan penutupan; backfill hanya untuk
baris warisan).

### B4 — Enam pengali ukuran bertumpuk ★★

Lihat §0.1. Tak ada satu tempat yang menjawab "kenapa ukurannya segini". **Perbaikan → Fase 2.**

### B5 — Breakeven dipersenjatai di +1,5 % lalu menutup di +0,25 % ★★

[`_compute_trail`](agents/futures/monitor.py) baris 459-488: bigmover `be_frac` 0,40 ke TP1
**atau** +1,5 % absolut (`BM_BE_ARM_ABS_PCT`), mana yang lebih dulu; SL lalu dipindah ke
`entry + cost`. Karena TP1 di 4 ATR tak pernah dekat, yang selalu menang adalah +1,5 % — dan
pullback 1,2 % pada koin volatil itu rutin. Ini pabrik 31 `sl_plus` +$0,30. **Perbaikan → Fase 4.**

### B6 — Fee partial-close kurang hitung (kecil) ★

Baris 1403: partial TP1 memotong `ROUND_TRIP × 0,5` (fee keluar saja) untuk fraksi yang dijual;
fee **masuk** untuk fraksi itu tak pernah dipotong — tutup akhir memotong RT penuh hanya atas
sisa. Selisih ≈ 0,05 % × 33 % notional ≈ $0,02/trade. Salah tapi kecil. **Perbaikan → Fase 4.**

### B7 — `futures_notional()` masih menghitung dari $1.000 × 1 % hardcode ★

[trading_costs.py:49](backend/app/services/trading_costs.py). Untuk 112 trade nyata **tidak
terpakai** (0 baris tanpa `position_size`) — hanya fallback baris purba. Tapi ia satu-satunya
"sumber kebenaran" bernama `futures_notional` yang bohong. **Dihapus → Fase 2.**

### Yang DIPERIKSA dan terbukti BUKAN bug
- `leverage` di `signals_json` vs kolom: 0 dari 112 berbeda.
- `pnl_dollar` tersimpan konsisten dengan wallet: Σ = −$145,61 = `realized_pnl` persis.
- `futures_learning._trade_pnl_dollar` memakai `pnl_dollar` tersimpan; fallback $1.000 mati.
- `close_reason` tersimpan di meta untuk 112/112.

---

## 2. Prinsip yang mengikat rencana ini

**P1 — Ukuran naik SETELAH ekspektasi positif, bukan sebelumnya.** WR bermakna hari ini 10,9 %.
Memperbesar ukuran pada sistem berekspektasi negatif hanya mempercepat rugi. Urutan: perbaiki
label & keluar → buktikan di paper → baru ukuran penuh. Ini bukan menunda; ini satu-satunya cara
"terukur" bisa diukur.

**P2 — Sedikit posisi, tiap posisi optimal.** Bukan 6 + 2 slot × $32 margin. Target **3 posisi**
× risk **2 %** — panas portofolio tetap 6 % (sama dengan plafon hari ini), tapi tiap posisi
6× lebih bermakna. Kandidat terbaik saja yang masuk; sisanya ditolak, bukan dikecilkan.

**P3 — Tiga angka dari SATU rumus yang bisa dibaca:** `risk $ → notional → leverage → margin`,
tanpa pengali bertumpuk. Setiap trade bisa dijelaskan satu kalimat.

**P4 — Menang berarti membukukan untung yang bermakna**, bukan sekadar > 0.

**P5 — Tak ada keluar yang hasilnya < K × biaya.** Breakeven baru boleh aktif bila jaraknya
dari entry ≥ K × biaya bolak-balik (default 3).

**P6 — TP1 di tempat yang PERNAH dicapai; TP2 dan pelari untuk gerak besar.** Bukan ATR×4 impian.

**P7 — SL adalah janji.** Dicek pertama, dijaga loop cepat saat dekat, penyimpangannya dicatat.

**P8 — Satu agen, satu lane, satu set bobot.** Kolom `lane` tetap ada demi riwayat.

**P9 — Semua ambang dari `agent_config`.** Konstanta modul hanya default.

**P10 — Riwayat tidak dihapus.** Era lane tetap terbaca sebagai "Legacy".

---

## 3. Rancangan target

### 3.1 Satu agen: `agents/futures/agentic.py`

Satu pipeline skor 0–100 dari blok yang terbukti punya sinyal:

| blok | sumber | catatan |
|---|---|---|
| momentum & arah | bigmover (change_24h + change_1h searah, B2.1) | satu-satunya lane dengan TP tersentuh |
| konfirmasi volume/OI/funding | agent3 T-blok, agent2 OI-confirm | funding hard-gate ±0,25 % tetap |
| filter derau & jebakan puncak | bigmover G14/G18 | tetap |
| **likuiditas minimum** (baru) | `quote_vol_24h ≥ min_liquidity_usd` | B2: koin tipis melompat melewati SL |
| struktur (S/R, ATR, swing) | helper `utils` | tetap |
| **dibuang** | anti-momentum penalty, quiet-coil pre-gainer, Wyckoff pre-markup | 6 trade / 2 bulan |

Ambang auto-open **tunggal** `futures.agentic_min_score` (default 65). Adaptive threshold
(death-spiral A2) dimatikan. **Pemilihan kandidat: peringkat**, bukan "semua yang lolos" —
tiap siklus hanya `max_positions − terbuka` kandidat teratas yang dibuka.

### 3.2 Mesin ukuran: `agents/futures/sizing.py`

Fungsi murni, semua parameter dari config, keluaran menjelaskan diri:

```
input : balance, sl_pct, tp1_pct, atr_pct, cost_floor_pct, quote_vol_24h
config: risk_pct (2,0), margin_loss_at_sl_pct (20), lev_min/max (2/8),
        liq_safety_mult (2,0), max_margin_frac (0,35), max_notional_frac (1,5),
        min_profit_cost_mult (4,0), min_profit_usd (5), max_positions (3)

1. risk_usd  = balance × risk_pct                     ← SATU angka. Tak ada pengali.
2. notional  = risk_usd / sl_pct
3. leverage  = clamp( margin_loss_at_sl_pct / sl_pct , lev_min , lev_max )
               lalu ≤ (95 / liq_safety_mult) / sl_pct  ← likuidasi selalu > 2× SL
4. margin    = notional / leverage  (≤ balance × max_margin_frac)
5. notional ≤ balance × max_notional_frac
6. GERBANG LABA  : tp1_pct ≥ min_profit_cost_mult × cost_floor_pct
7. GERBANG DOLAR : tp1_pct × notional − biaya ≥ min_profit_usd
8. GERBANG SLOT  : posisi terbuka < max_positions; kalau penuh → TOLAK, bukan kecilkan
9. keluaran: {risk_usd, notional, leverage, margin, tp1_net_usd, tp2_net_usd, sl_net_usd,
              cost_usd, profit_to_cost, reason}  → paper_trades.sizing_json, ledger, UI
```

Contoh dengan wallet nyata $854, risk 2 % = **$17,09**:

| SL % | notional | lev (20 %/SL) | margin | TP1 (1,2 ATR) bersih | TP2 (2,5 ATR) bersih | rugi di SL | untung:biaya |
|---|---|---|---|---|---|---|---|
| 3,0 (ATR 2,5 %) | $570 | 6 | $95 | **+$15,6** | +$34,1 | −$18,6 | 11× |
| 4,0 (ATR 3,3 %) | $427 | 5 | $85 | +$15,6 | +$34,1 | −$18,2 | 11× |
| 5,3 (ATR 4,4 %, median kini) | $322 | 4 (3,8→4) | $81 | +$15,6 | +$34,1 | −$18,0 | 11× |
| 8,0 (ATR 6,7 %, BLUAI) | $214 | 2 (2,5→2) | $107 | +$15,4 | +$33,9 | −$17,7 | 10× |
| **hari ini** | $96 | 3 | $32 | +$0,7 (pada +1 %) | — | −$5,3 | 2,8× |

Bacaannya: **rugi di SL selalu ≈ $18 = 2 % wallet, apa pun koinnya** — itulah "kerugian
terukur". Leverage adalah **akibat** dari SL (rugi margin di SL selalu ≈ 20 %), bukan angka per
lane. TP1 selalu ≈ +$15 bersih (1,2 ATR ≈ 1,0× SL), TP2 ≈ +$34 (2,5 ATR ≈ 2,1× SL); pelari
setelah TP2 tak berplafon. Tiga posisi penuh = margin ≈ $260 (30 % wallet), panas 6 %.

Kalau ingin lebih agresif: satu kunci `risk_pct` 2 → 3 menaikkan semua baris 50 %. **Tidak ada
jalan lain** untuk memperbesar ukuran — disengaja.

### 3.3 Keluar: monitor 6 mekanisme, SL selalu pertama

| # | mekanisme | aturan (`futures.exit_*`) | mengganti |
|---|---|---|---|
| 0 | **`sl_hit` — dicek PERTAMA** setiap iterasi; loop cepat (5 dtk) aktif saat `|price − sl| ≤ fast_loop_atr` (1 ATR) atau lev ≥ `fast_loop_lev_min` | B2 | fail_fast sebelum SL, fast-loop hanya lev ≥ 10 |
| 1 | SL awal = ATR × `sl_atr_mult` (1,2), floor/ceiling % | | sl_config per lane |
| 2 | `tp1_hit` parsial `tp1_close_frac` (50 %) di `tp1_atr_mult` × ATR (**1,2**) | dari MFE | ATR×2–4 |
| 3 | `tp2_hit` parsial (25 %) di `tp2_atr_mult` (**2,5**); sisa 25 % = pelari trail, tanpa plafon | | ATR×4–6 |
| 4 | `breakeven` → `sl_plus`: **hanya** bila untung ≥ `be_arm_cost_mult` × cost_floor (3×) **dan** ≥ `be_arm_atr` (0,6 ATR); SL = entry + biaya | B5 | be_frac 40 % / +1,5 % abs |
| 5 | `trail`: setelah TP1 kunci `trail_lock_frac` (0,75) dari puncak | | tetap |
| 6 | `time_stop`: hold > `max_hold_h` (8) tanpa ≥ `time_stop_progress` × risk → tutup | | max_age + rotation + stagnant ×3 |
| — | `liq_guard`, `emergency_close` — tetap | | |
| — | **`fail_fast` DIHAPUS** (−$79, 0 % WR, dan pelabel salah B2) | | |
| — | rugpull/flash, funding_window, cost_exceeds_*, profit_lock_tier ×5, age_extend, rotation, stagnant ×2, absolute_profit_lock — **dihapus** | | |

Ditambah dua **pencatatan** wajib tiap tutup: `sl_breach_pct` (seberapa jauh fill melewati SL)
dan `ExitEvent` ditulis **sinkron** (B3). Fee partial = fraksi × RT penuh (B6).

### 3.4 Definisi menang (B1)

`agents/shared/trade_outcome.py` → `is_win(trade, market)`:
```
futures: pnl_dollar ≥ max( cfg futures.win_min_profit_usd (3),
                          cfg futures.win_min_cost_mult (2) × cost_usd )
spot   : tetap definisi sekarang (pnl_pct > 0) — engine spot tak disentuh
```
Ditambah `is_scratch(trade)` untuk |pnl| di bawah ambang — dilaporkan terpisah di UI ("impas"),
**tidak** dihitung menang maupun kalah oleh weight_updater/risk_gate.

### 3.5 Learning: yang IKUT diubah

| modul | hari ini | target |
|---|---|---|
| `weight_updater` | 4 namespace, 85 kunci, label B1 | 1 namespace `futures_agentic`, label §3.4; bobot lama **tidak dimigrasi** (dilatih dari label salah) — mulai netral, veto-only sampai n≥30 |
| `risk_gate` | jeda/WR/kuota per lane (81 rujukan), label B1 | jeda & WR **global + per arah**, label §3.4; kuota lane → `max_positions` (3) + `max_same_direction` (2) |
| `learning_policy`/`loader` | per lane | satu kebijakan |
| `decision_ledger` | `agent`,`lane` | `agent=futures_agentic`; **+ snapshot sizing** (risk_usd, notional, leverage, margin, tp1_net_usd, cost_usd) |
| `futures_adaptive_model` | fitur pasar (0 rujukan lane) | tak berubah; `FEATURE_SCHEMA_VERSION=v2`, model v1 diretire, latih ulang dari ledger baru |
| `exit_learning`/`exit_rollout` | per lane (66+81) | satu set `futures.exit_*`; rollout canary tetap |
| `sl_config` | per lane (39) | satu set `sl_*` |
| `outcome_tracker`, `regime`, walkforward, shadow_compare, predictive_repair, `learning/runner.py` | | tak berubah |

### 3.6 API & FE

BE: `store` satu kunci; `/futures/learning/stats` → `agentic` + `legacy`; `/futures/monitor/risk`
`agent_breakdown` → `direction_breakdown`; **baru** `GET /futures/sizing/preview`; `/futures/positions`
mengembalikan `sizing_json` + `sl_breach_pct` + `is_scratch`.

FE: [lib/agents.ts](frontend/src/lib/agents.ts) tambah `futures_agentic`; OverviewTab/FuturesTab/
FuturesAnalytics filter agen → arah, kartu Legacy; **tabel posisi** (tangkapan layar owner) kolom
`MARGIN·LEV` → `RISK $ · NOTIONAL · LEV · MARGIN`, `P&L $` didampingi `BIAYA $` dan `UNTUNG:BIAYA`,
status baru **"Impas"** (kuning) untuk scratch — bukan "SL+ Profit" hijau untuk +$0,06; scanner
tab lane hilang; architecture 4 → 1; settings grup `futures.size_*`/`exit_*`/`win_*`.

---

## 4. Fase pekerjaan

Tiap fase punya **takeout** (bukti selesai) dan **gerbang** (syarat lanjut). Fase 1 mengubah
perilaku learning **hari ini juga** (B1 terlalu merusak untuk menunggu); Fase 2–3 di balik flag;
perilaku trading berubah di Fase 7.

### Fase 0 — Bekukan & garis dasar (½ hari)
- Snapshot `agent_config` futures → `ops/config-snapshots/2026-09-05-pre-agentic.json`.
- Metrik §0 + §1 → `docs/futures-baseline-2026-09-05.md`.
- Flag `futures.agentic_enabled` (default 0).
- Takeout: dua berkas + flag di AgentConfigEditor.

### Fase 1 — Label menang (B1) + rantai ukuran jadi dinamis (1 hari)
- §3.4 di `trade_outcome.py`, kunci `futures.win_min_profit_usd`, `win_min_cost_mult`.
  `weight_updater` & `risk_gate` memakai `is_win`/`is_scratch` baru; **recompute paksa** bobot
  (pelajaran B1-rollback 8 Agu: matikan/ubah label TIDAK memulihkan bobot sendiri).
- 33 konstanta rantai ukuran → `agent_config` (grup `futures`): `size_risk_pct`,
  `size_margin_loss_at_sl_pct`, `size_max_margin_frac`, `size_max_notional_frac`,
  `size_min_notional_abs`, `size_min_profit_usd`, `size_min_profit_cost_mult`, `max_positions`,
  `portfolio_max_risk_pct`, `lev_min`, `lev_max`, `liq_safety_mult`, `extended_change_24h_pct`,
  `min_liquidity_usd`. Pengali `PROFIT_LOCK_SIZE_MULT`, `FUNDING_SOFT_SIZE_MULT`,
  `weekend_size_mult`, probe ½, lane-throttle ½ **dihapus** (menjadi tolak/terima, bukan kecilkan).
- Takeout: tabel §0.5 baris balance/utils → 0; `/futures/learning/stats` menampilkan `wr`,
  `wr_meaningful`, `scratch_count` berdampingan.
- Gerbang: nilai default = nilai lama → perilaku sizing live identik; hanya label yang berubah.

### Fase 2 — `sizing.py` (1 hari)
- Fungsi murni §3.2 + tes tabel (baris contoh = kasus uji). `compute_futures_sizing` jadi pembungkus.
- `futures_notional()` (B7) dihapus; pemakai fallback → `position_size` wajib.
- Kolom `paper_trades.sizing_json`. Endpoint `/futures/sizing/preview`.
- Gerbang: hitung ulang 112 trade lama **offline** dengan sizing baru → laporan rata notional,
  rugi di SL, untung di TP1 — bukti "terukur" sebelum satu pun trade baru.

### Fase 3 — Agen tunggal + taksonomi (2 dari)
- `agentic.py` per §3.1 (≤ 600 baris). `FUTURES_AGENTS=["futures_agentic"]` +
  `LEGACY_FUTURES_AGENTS`; audit ≈30 pemakaian `style.in_(...)`: riwayat memakai keduanya,
  keputusan hanya yang baru. `scheduler` memanggil satu pemindai; **peringkat kandidat**.
- Gerbang: shadow 48 jam (`action=shadow`, tak membuka posisi); bandingkan sebaran skor & jumlah
  kandidat/hari vs 4 agen lama.

### Fase 4 — Keluar: monitor 6 mekanisme + B2/B3/B5/B6 (2 hari)
- Jalur kedua di monitor, dipilih `trade.style == "futures_agentic"`; jalur lama tetap untuk
  trade era lane sampai tutup.
- SL dicek pertama; loop cepat dipicu jarak ≤ 1 ATR; `sl_breach_pct`; `ExitEvent` sinkron;
  fee partial fraksi × RT; `fail_fast` tak ada.
- `REAL_LOSS_REASONS` diperbarui ke 8 kosakata.
- Takeout: **replay** 107 exit_events lewat aturan baru → berapa jadi `tp1_hit`, berapa
  breakeven yang **tidak lagi** aktif < 3× biaya, berapa `sl_breach` > 0,5 %.
- Gerbang: replay Σ `sl_plus` < 3× biaya = **0**; simulasi BLUAI dengan loop cepat 1 ATR
  menutup ≤ 1,2× risk.

### Fase 5 — Learning & risk mengikuti (1,5 hari)
- Per §3.5. Ledger v2 + kolom sizing; model v1 retired.
- Gerbang: 84 tes + tes baru hijau; `/signals/adaptive-engine/futures` engine `collecting` dari
  ledger baru; `LEARNING_STANDALONE` runner memproses v2.

### Fase 6 — API + FE (2 hari)
- Per §3.6. Urutan: registry → endpoint → `lib/agents.ts` → history → tabel posisi (kolom
  ukuran, biaya, status Impas) → scanner → architecture → settings.
- Gerbang: `tsc`/`eslint`/`next build` 0; audit FE↔openapi 0 endpoint mati; tangkapan layar tabel.

### Fase 7 — Nyalakan & buktikan (2–3 minggu kalender, kerja ~1 hari)
1. `agentic_enabled=1`, `size_risk_pct=1.0` (**separuh** target), `max_positions=3`.
2. Gerbang naik ke 2 %, **semua** pada n ≥ 40 trade tertutup (bukan scratch):
   - ekspektasi bersih setelah biaya > 0
   - `tp1_hit` ≥ 30 % (kini 4 %)
   - jumlah scratch (|pnl| < 2× biaya) ≤ 10 % (kini 35 %)
   - WR bermakna (≥ $3 pada risk 1 %) ≥ 35 % (kini 6,4 %)
   - rata `profit_to_cost` pemenang ≥ 5×
   - maks `sl_breach_pct` ≤ 0,5 % ATR-normal; tak ada rugi > 1,3× risk
   - drawdown puncak ≤ `dd_hard_stop_pct`
3. Lulus → `size_risk_pct=2.0`. Gagal → laporan otomatis gerbang mana yang gagal; ukuran tidak naik.
- Takeout: `docs/futures-gate-<tgl>.md` dihasilkan skrip.

### Fase 8 — Bersih-bersih (½ hari)
- Hapus agent1/2/3/bigmover, ≈90 kunci config per-lane, jalur monitor lama (setelah trade era
  lane terakhir tutup), tipe FE `AgentKey` lama.

**Total kerja ≈ 12 hari orang** — direvisi jadi **≈ 19 hari** setelah inventaris lengkap §8 (11 komponen tak terlihat di sapuan pertama). **Kalender ≈ 6–7 minggu.**

---

## 5. Keputusan yang butuh owner (sebelum Fase 2)

Usulan default — bisa diubah di UI kapan saja, tapi nilai awal menentukan uang:

| # | keputusan | usulan | alternatif |
|---|---|---|---|
| K1 | `size_risk_pct` — risiko per trade | **2,0 %** ($17) | 1,5 % / 3 % |
| K2 | `max_positions` | **3** | 2 (lebih terkonsentrasi) / 4 |
| K3 | `size_margin_loss_at_sl_pct` | **20 %** → lev 2–6× | 30 % → lev 4–10× |
| K4 | `lev_max` | **8×** | 5× / 10× |
| K5 | `size_min_profit_usd` — TP1 bersih minimum agar kandidat boleh masuk | **$5** | $3 / $10 |
| K6 | `win_min_profit_usd` — ambang "menang" | **$3** | $2 / $5 |
| K7 | `tp1_atr_mult` / `tp2_atr_mult` | **1,2 / 2,5** | 1,5 / 3,0 |
| K8 | `tp1_close_frac` / `tp2_close_frac` | **50 % / 25 %**, 25 % pelari | 33/33/33 |
| K9 | bobot sinyal lama | **mulai netral** (dilatih dari label salah) | migrasi |
| K10 | Fase 7 mulai di risk 1 % | **ya** | langsung 2 % (melanggar P1) |
| K11 | `fail_fast` dihapus | **ya** | matikan via config saja |
| K12 | `min_liquidity_usd` (B2, koin tipis) | **$5 jt** vol 24 j | $2 jt / $10 jt |

## 6. Yang SENGAJA tidak diubah
Proses pembelajaran terpisah (6ddff44); `evaluate_risk_gate` DD/RAR/harian; model adaptif
(mekanisme); SPOT sama sekali; notifier, delisting, ws big-mover.

## 7. Risiko
- **Rugi per hari naik** walau terukur: 3 × $17 = $51 risiko terbuka; `daily_loss_limit_pct`
  2,5 % ($21) akan **lebih sering** menahan — benar dan disengaja, owner harus tahu.
- **Sedikit posisi = variansi harian lebih tinggi**; itu harga dari "optimal, bukan banyak".
- **Agen tunggal bias searah pasar** — `max_same_direction=2` jadi rem penting.
- **TP1 1,2 ATR di koin volatil** bisa tersentuh derau lalu berbalik — karena itu parsial 50 % + trail.
- **Ledger 7.418 keputusan era lane tak bisa melatih model v2** — engine mulai `collecting`
  lagi, ±60 sampel matang ≈ 2–3 minggu.
- **B1 diperbaiki di Fase 1 = bobot & jeda lane berubah hari itu juga** pada sistem yang masih
  jalan dengan agen lama. Risiko: lane yang tadinya "WR 50 %" jadi "WR 11 %" dan langsung
  dijeda. Itu **benar** — tapi berarti agen lama praktis berhenti membuka posisi sampai Fase 7.

---

## 8. INVENTARIS LENGKAP — semua yang menyentuh FUTURES

Disusun 5 Sep 2026 atas permintaan owner: *"pastikan tidak ada tersisa … baik itu agent scanner,
monitoring dan adaptive weightening FUTURES"*. Sapuan pertama (§3.5) **melewatkan 11 komponen**,
ditandai ⚠️ di bawah. Tiga di antaranya **mengubah bobot futures secara otomatis** — kalau
tertinggal, rewrite akan menabraknya diam-diam.

### 8.1 Layer AGENT — `agents/futures/` (24 berkas, 9.269 baris)

| berkas | baris | peran | nasib |
|---|---|---|---|
| `monitor.py` | 2.175 | keluar & trailing (19 alasan) | **rewrite** F4 → 6 mekanisme |
| `scheduler.py` | 962 | loop pindai + **penjadwal tersembunyi** (§8.6) | **rewrite** F3 |
| `agent1.py` | 871 | pemindai Pre-Gainer | **hapus** F8 |
| `risk_gate.py` | 833 | DD/RAR/harian + jeda & WR per lane | **rewrite sebagian** F5 |
| `auto_trader.py` | 760 | 17 gerbang entri + 6 pengali ukuran | **rewrite** F2/F3 |
| `weight_updater.py` | 744 | bobot sinyal per agen, blacklist koin, ambang adaptif | **rewrite** F5 |
| `agent2.py` | 695 | pemindai Accumulation | **hapus** F8 |
| `agent3.py` | 673 | pemindai Momentum | **hapus** F8 |
| `agent_bigmover.py` | 525 | pemindai BigMover | **sumber utama** `agentic.py`, lalu hapus F8 |
| `ws_big_mover_feed.py` ⚠️ | 419 | feed WS/REST big mover → `store` | **sentuh**: kunci store berubah |
| `monitor_config.py` | 419 | 38 konstanta + 21 kunci per lane | **rewrite** F4 |
| `data.py` ⚠️ | 324 | ambil top-100, kline, listing baru | **tetap** (tak lane-aware) |
| `utils.py` | 267 | plafon leverage per lane, LIQ_SAFETY | **rewrite** F1/F2 |
| `learning_policy.py` ⚠️ | 263 | **`canonical_signal_key`** — ±90 aturan regex teks sinyal → kunci kanonik, bersumber dari salinan agent1/2/3/bigmover | **rewrite** F5 — kalau tidak, bobot baru tak pernah cocok (bug namespace 29 Jul terulang) |
| `outcome_tracker.py` | 224 | label 30m/1h/4h/24h ke ledger | **tetap** |
| `learning_loader.py` | 192 | terapkan hasil belajar per lane | **rewrite** F5 |
| `decision_ledger.py` | 189 | tulis keputusan pindai | **tambah snapshot sizing** F5 |
| `regime.py` | 158 | rezim pasar (4h/1h) | **tetap** |
| `sl_config.py` | 143 | SL per lane (39 rujukan) | **rewrite** F4 |
| `store.py` ⚠️ | 142 | cache hasil pindai, big movers, breadth, learning status | **rewrite kunci** F3 |
| `delisting_monitor.py` ⚠️ | 127 | pantau delisting 6 jam | **tetap** |
| `repair_log.py` ⚠️ | 92 | ledger aksi perbaikan bobot | **rewrite** F5 (§8.4) |
| `exchange_info.py` | 86 | tickSize/minNotional/maxLeverage | **tetap** (dipakai sizing) |

### 8.2 Layer LEARNING — `agents/learning/` yang menyentuh futures

| berkas | baris | peran | nasib |
|---|---|---|---|
| `exit_learning.py` | 1.180 | belajar dari `exit_events` per lane (66 rujukan) | **rewrite** F5 |
| `exit_rollout.py` | 786 | canary parameter keluar per lane (81 rujukan) | **rewrite** F5 |
| `futures_adaptive_model.py` | 575 | model logistic+Platt, lifecycle canary | **skema v2** F5 |
| `weekly_backtest.py` ⚠️ | 229 | tiap Minggu: replay `big_mover_log` market=futures | **rewrite** F5 |
| `weekly_signal_review.py` ⚠️ | 214 | tiap Senin: tinjau sinyal, sesuaikan bobot, catat ke `repair_log` | **rewrite** F5 |
| `repair_verifier.py` ⚠️ | 205 | verifikasi & auto-revert aksi perbaikan | **rewrite** F5 |
| `monthly_calibration.py` ⚠️ | 169 | tiap tanggal 1: kalibrasi ambang adaptif | **rewrite** F5 |
| `predictive_repair.py` ⚠️ | 164 | **agen perbaikan bobot otomatis tiap 5 mnt** — memakai `FUTURES_AGENTS` + `canonical_signal_key` | **rewrite** F5 |
| `futures_walkforward.py` | 157 | walkforward + cost-stress | **tetap** |
| `runner.py` | 126 | proses pembelajaran terpisah (6ddff44) | **tambah**: panggil juga pekerjaan §8.6 |
| `futures_shadow_compare.py` | 112 | bandingkan shadow vs champion | **tetap** |

### 8.3 Layer SHARED — `agents/shared/`

| berkas | peran | nasib |
|---|---|---|
| `cross_agent_learning.py` ⚠️ | **blending bobot lintas agen** — `FUTURES_AGENTS` dipatok di baris 43-45, dan **keempat pemindai** memanggil `get_cross_weight`+`blend_weights` saat menilai | **rewrite** F5 — tertinggal = skor `agentic` dicampur bobot lane mati |
| `trade_outcome.py` | definisi menang (B1) | **rewrite** F1 |
| `exit_ledger.py` | penulis `ExitEvent` dua-market | **dipakai** F4 (B3) |
| `trail_tracker.py` | jejak gerak sesudah TP1 | **tetap** |
| `config_reader.py` | pembaca config TTL 60 dtk | **tetap** (fondasi F1) |

### 8.4 Rantai Predictive Repair FUTURES ⚠️ — seluruhnya terlewat di §3.5

Rantai lengkap yang **mengubah bobot futures tanpa campur tangan manusia**:

```
scheduler tiap 5 mnt ──> predictive_repair.run_predictive_repair()
                          ├─ collect_predictive_stats()  ← PredictiveLog (agent futures)
                          ├─ canonical_signal_key()      ← learning_policy
                          ├─ _apply_weight_step()        ← AgentSignalWeight
                          └─ record_action()             ← futures_repair_actions
scheduler tiap 30 mnt ─> repair_verifier.verify_repairs()
                          └─ auto-revert bila memburuk
UI  /signals (Improve) ─> GET /signals/repairs · /signals/recommendations
                          POST /signals/recommendations/apply → _apply_weight_step
```

Model `futures_repair_action`, endpoint `/signals/repairs`, `/signals/recommendations[/apply]`,
dan seksi "Improve" di FE semuanya bergantung pada `FUTURES_AGENTS` + kunci kanonik.
**Kalau namespace berubah tanpa ini ikut diubah, seluruh saran perbaikan jadi nol dampak** —
persis bug 29 Jul 2026 (`project_repair_namespace_bug`, 49/49 bobot terkunci 1.0).

### 8.5 Layer BACKEND — API & services

| berkas | baris | futures-hit | nasib |
|---|---|---|---|
| `api/v1/signals.py` ⚠️ | 1.280 | 91 | **rewrite sebagian** F6 — Signal Performance, repairs, adaptive-engine |
| `api/v1/futures_scanner.py` | 936 | 92 | **rewrite** F6 (14 rujukan kunci store, 6 daftar agen) |
| `api/v1/balance.py` | 652 | 38 | **rewrite** F2 (sizing) |
| `api/v1/futures_learning.py` | 569 | 49 | **rewrite** F6 (20 endpoint exit-learning/rollout) |
| `api/v1/history.py` | 468 | 20 | **sentuh** F6 (3 daftar agen) |
| `services/agent_config_defaults.py` | 446 | 102 | **rewrite** F1 (seed kunci baru, pensiun ±90 kunci lane) |
| `api/v1/market.py` | 411 | 21 | **tetap** (`/market/futures-positions` = akun nyata) |
| `api/v1/agent_config.py` | 394 | 38 | **sentuh** F6 (grup kunci baru) |
| `api/v1/futures_market.py` | 371 | 11 | **sentuh** F6 (1 kunci store) |
| `services/signal_catalog.py` ⚠️ | 315 | 32 | **rewrite** F5 — **10 daftar agen dipatok**, memetakan tiap sinyal → `agent1/2/3/bigmover` + berkas + nama fungsi. Tab Analysis membacanya |
| `api/v1/predictive.py` ⚠️ | 299 | 8 | **sentuh** F5 (PredictiveLog agent futures) |
| `api/v1/futures_eligibility.py` | 281 | 16 | **rewrite** F6 (+ perbaikan gerbang fail-open) |
| `services/big_mover_logger.py` ⚠️ | 272 | 2 | **sentuh** F5 — forward-PnL big mover, dipakai `weekly_backtest` |
| `api/v1/binance_status.py` | 193 | 29 | **tetap** |
| `api/v1/admin.py` ⚠️ | 182 | 12 | **sentuh** F6 (`reset_simulation` membersihkan cache 4 agen) |
| `api/v1/diagnostics.py` ⚠️ | 174 | 9 | **sentuh** F6 (baca cache bobot & gate) |
| `api/v1/big_mover_log.py` ⚠️ | 153 | 1 | **tetap** (3 endpoint) |
| `services/binance_urls.py` | 130 | 3 | **tetap** |
| `ws/big_mover_alerts.py` ⚠️ | 116 | 1 | **sentuh** F6 (baca `get_live_movers`) |
| `services/engine_gates.py` ⚠️ | ~90 | — | **tetap** (gerbang bersama SPOT — jangan diubah) |
| `ws/futures_stream.py` ⚠️ | 78 | 7 | **rewrite** F6 (snapshot dari kunci store) |
| `services/slippage_sim.py` ⚠️ | ~80 | — | **tetap** (dipakai cost floor & sizing) |
| `services/agent_registry.py` | 88 | 26 | **rewrite** F3 |
| `services/trading_costs.py` | 59 | 16 | **rewrite** F2 (B7) |
| `notify/trade_watcher.py` ⚠️ | — | — | **sentuh** F6 — `_pretty_style` mengurai `futures_agent_*` untuk pesan Telegram |

**Model DB futures** (15 tabel): `paper_trades`, `paper_balances`, `balance_transactions`,
`futures_decision_events`, `exit_events`, `futures_exit_rollouts`, `futures_model_versions`,
`futures_repair_actions`, `agent_signal_weights`, `signal_weight_history`, `agent_config`,
`predictive_log`, `rejection_log`, `big_mover_log`, `force_open_log`.
**Migrasi baru** (F2/F5): `paper_trades.sizing_json`, `paper_trades.sl_breach_pct`,
`futures_decision_events` + 6 kolom sizing.

### 8.6 Penjadwal tersembunyi di `scheduler.py` ⚠️

`run_futures_loop` bukan sekadar pemindai — ia **penjadwal seluruh pembelajaran futures**, dipicu
`_cycle_count % N`. Rewrite `scheduler.py` tanpa memindahkan ini = pekerjaan berikut **mati senyap**:

| pemicu | pekerjaan |
|---|---|
| tiap siklus | `update_weights`, `flush_rejection_queue`, `log_big_movers`, `update_cross_agent_weights`, `fetch_regime` |
| `% 10 == 5` | `update_decision_outcomes`, `backfill_closed_futures_trades` |
| `% 12 == 0` | pembersihan `PredictiveLog` |
| `% 100 == 50` / outcome baru | latihan model + walkforward + lifecycle (kini di proses terpisah) |
| tiap ±5 mnt | `run_predictive_repair` |
| tiap ±30 mnt | `verify_repairs` |
| `% 100 == 0` | ringkasan rejection |
| `% 1000 == 0` | pemeliharaan berkala |
| Minggu 00:00 UTC | `run_weekly_backtest` |
| Senin 00:10 UTC | `run_weekly_signal_review` |
| tanggal 1 | `run_monthly_calibration` |
| berkala | `backfill_pending` (big mover forward-PnL) |

**Aksi F3**: pindahkan seluruh baris ini ke `agents/futures/jobs.py` dengan jadwal **eksplisit
berbasis waktu**, bukan modulo siklus — supaya jeda pindai tak lagi menggeser jadwal belajar.

### 8.7 Layer FRONTEND — 46 berkas menyentuh futures (bukan 12)

| berkas | baris | hit | nasib |
|---|---|---|---|
| `features/signals/page.tsx` ⚠️ | **3.316** | 138 | **rewrite sebagian** — 4 kartu agen, `AGENT_LABEL`, pipeline, Improve |
| `features/signals/components/ExitSection.tsx` ⚠️ | 930 | 17 | **rewrite** — exit-learning per lane |
| `features/scanner/page.tsx` | 845 | 32 | **rewrite** — tab lane |
| `features/architecture/data.ts` ⚠️ | 770 | 20 | **rewrite** — katalog 4 agen + lane |
| `features/health/components/DBHistoryTable.tsx` ⚠️ | 715 | 40 | **sentuh** — filter agen |
| `features/futures-market/page.tsx` | 562 | 9 | **sentuh** |
| `features/history/components/FuturesAnalytics.tsx` | 466 | 5 | **rewrite** |
| `.../futures/BigMoversWatchlist.tsx` | 430 | 16 | **sentuh** |
| `.../futures/OverviewTab.tsx` | 393 | 14 | **rewrite** — 4 kartu lane |
| `features/dashboard/page.tsx` | 350 | 16 | **sentuh** |
| `features/health/page.tsx` | 331 | 13 | **sentuh** |
| `.../futures/MonitorTab.tsx` | 322 | 8 | **rewrite** — jeda lane |
| `features/architecture/components/FuturesSection.tsx` | 298 | 16 | **rewrite** |
| `features/architecture/components/LearningSection.tsx` ⚠️ | 265 | 7 | **sentuh** |
| `features/history/components/FuturesTab.tsx` | 244 | 23 | **rewrite** |
| `.../futures/OpenPosCard.tsx` | 174 | 2 | **rewrite** — kolom ukuran & biaya |
| `.../futures/types.ts` | 171 | 3 | **rewrite** |
| `components/MarketIntelBanner.tsx` ⚠️ | 167 | 9 | **sentuh** |
| `features/dashboard/components/SystemHealthPanel.tsx` ⚠️ | 147 | 14 | **sentuh** |
| `lib/agents.ts` | 92 | 27 | **rewrite** |
| `features/shared/useLaneStatus.ts` | 66 | 3 | **rewrite** |
| `types/health.ts` ⚠️ | 41 | 8 | **sentuh** |
| + 24 berkas lain (≤ 130 baris) | | | **sentuh ringan** |

### 8.8 Daftar agen futures yang DITULIS ULANG (19 tempat)

Meski `agent_registry.py` ada sebagai "satu sumber kebenaran", literal `"futures_agent1"` masih
ditulis ulang di **19 berkas** — 10 di antaranya di `signal_catalog.py` saja. Semua wajib diaudit
di F3, karena inilah pola kegagalan senyap yang sudah dua kali memakan waktu proyek ini
(`project_signal_perf_agent_coverage` 30 Jul, `project_repair_namespace_bug` 29 Jul).

### 8.9 Dampak ke fase

| fase | dari | jadi | sebab |
|---|---|---|---|
| F3 agen tunggal | 2 hari | **3 hari** | + `jobs.py` (§8.6), audit 19 daftar agen |
| F5 learning | 1,5 hari | **4 hari** | + rantai repair (§8.4), `cross_agent_learning`, `signal_catalog`, `learning_policy`, 3 pekerjaan berkala |
| F6 API+FE | 2 hari | **4,5 hari** | 46 berkas FE, bukan 12; 20 endpoint exit-learning; ws stream; notifier |
| **total** | 12 hari | **≈ 19 hari** | |

### 8.10 Yang TIDAK tersentuh (dipastikan)

`agents/opportunity/**` (SPOT — haram disentuh), `agents/learning/spot_*`, `engine_gates.py`
(bersama SPOT), `slippage_sim.py`, `binance_urls.py`, `exchange_info.py`, `data.py`, `regime.py`,
`delisting_monitor.py`, `trail_tracker.py`, `config_reader.py`, `learning/runner.py` (selain
menambah panggilan §8.6), notifier Telegram (selain `_pretty_style`).
