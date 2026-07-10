# PLAN_v16 — True-Cost Profit Engine: Fee-Aware Exits & Kesiapan Live Trade

Tanggal: 2026-07-10 · Status: **F1/F2/F3/F5 DIIMPLEMENTASI 2026-07-10 — tersisa
F4 (maker-first, fase live) & gate F6 (validasi 14 hari)**

## Status implementasi

| Fase | Status | Catatan |
|---|---|---|
| F1 true-cost accounting | ✅ | 3 jalur close (main/fast/reconcile) potong entry-slippage + SL-fill slippage (0.08%, stop-market saja) + funding G6; breakdown di meta `cost_slippage_pct`/`cost_funding_dollar` |
| F2 cost-floor gate | ✅ | `cost_floor = feeRT + 2×slip + funding_est(hold lane)`; open ditolak bila TP1 < 3× cost_floor (`futures.min_tp1_cost_mult`, seeded); tersimpan di meta `cost_floor_pct` |
| F3 anti-churn | ✅ | `time_stop_scratch` DIHAPUS → tighten SL ke entry−cost (rotate-eligible tetap); breakeven trail = entry±cost (guard harga); bank-gate 3× di cost-gate & funding-window (else tighten ke entry+cost); profit-lock tighten → entry+cost |
| F5 sizing | ✅ | Lane throttle: rolling WR <40% (≥10 trade) → ½ size. Upsize A-grade TIDAK ditambah — sudah ada via conviction scaling (skor 72→90 = risk 1%→1.5%) di `compute_futures_sizing` |
| F4 maker-first live | ⏳ | Fase live: post-only entry, TP limit, BNB discount, testnet |
| F6 clean-room gates | ⏳ berjalan | History direset 10 Jul; ukur 14 hari NET true-cost |
Prasyarat: PLAN_v15 live (anti loss-day). PLAN_v16 menjawab problem berikutnya:
*"close posisi profit $1 tapi rugi di fee — market order + leverage"* dan menyiapkan
sistem untuk live trade dari wallet Binance nyata.

---

## 0. Diagnosa — di mana fee memakan profit (data nyata, 26 trade)

| Close reason | n | Avg notional | Avg net $ | Avg fee $ | Fee % dari win |
|---|---|---|---|---|---|
| time_stop_scratch | 14 | $276 | **−$0.23** | $0.28 | **71%** |
| breakeven_stop | 6 | $297 | +$0.21 | $0.30 | **fee > profit** |
| sl_hit | 7 | $298 | −$11.15 | $0.30 | — |
| tp2_hit / sl_plus / flash win | 4 | — | +$10 s/d +$24 | $0.16–0.68 | **1–3%** ✓ |

**Kesimpulan diagnosa:**
1. **Winner sungguhan TIDAK bermasalah** — fee cuma 1–3% dari profit. Masalahnya
   adalah **churn**: 20 dari 26 close (77%) adalah exit sukarela mikro
   (scratch/breakeven) yang membayar round-trip fee $0.28–0.30 untuk mem-bank ≈ $0.
2. **Paper sekarang LEBIH MURAH dari live** — tiga biaya live belum masuk pnl:
   - Slippage entry market-order (0.05–0.5% per tier volume — sudah DIHITUNG di
     `slippage_sim.py` tapi hanya informasional, tidak dipotong dari pnl).
   - Slippage fill SL (stop-market di buku yang jatuh — spot pakai `SL_SLIPPAGE_PCT
     0.10%`, futures TIDAK).
   - **Funding cost**: G6 melacak `cumulative_funding_paid` di meta tapi TIDAK PERNAH
     dipotong dari `pnl_dollar` saat close.
   Estimasi: scratch avg −$0.23 di paper ≈ **−$1.0 s/d −$1.3 di live** (tambah
   slippage ~0.3% × $276). Berarti day-WR paper saat ini overstated untuk live.
3. Dengan leverage, fee dihitung dari NOTIONAL: RT taker 0.10% × leverage 3–6× =
   **0.3–0.6% dari margin per churn**. Churn 14×/minggu = 4–8% margin menguap ke fee.

## 1. Prinsip desain

> **Setiap keputusan close sukarela harus membuktikan dirinya menang melawan biaya
> round-trip-nya sendiri.** Proteksi (SL/liq/breaker) bebas biaya-gate; pengambilan
> profit tidak.

---

## 2. Fase implementasi

### F1 — True-cost accounting di paper (fidelity live) — KERJAKAN PERTAMA
Sebelum optimasi apa pun, papan skor harus jujur:
- Potong dari `pnl_dollar` saat close (semua jalur: main loop, fast loop, reconcile):
  a. `entry_slippage_pct` (sudah tersimpan di meta sejak P1/B4.1 — tinggal dipakai);
  b. slippage fill SL utk close bertipe stop-market: `FUTURES_SL_SLIPPAGE_PCT = 0.08`
     (baru, di `trading_costs.py`) — hanya untuk reason sl_hit/liq_guard/max_margin/
     fail_fast/flash_*;
  c. `cumulative_funding_paid` dari meta G6 (akhirnya benar-benar dibayar).
- Simpan breakdown di meta: `cost_fee`, `cost_slippage`, `cost_funding`, `cost_total`
  → tampil di history UI (transparansi per trade).
- Recompute balance tetap otomatis (Σ pnl_dollar).

### F2 — Cost-floor engine (satu angka biaya per trade, dihitung SEBELUM open)
- Saat open: `cost_floor_pct = fee_RT(0.10) + 2×entry_slippage(vol_tier)
  + funding_est(rate_now × expected_hold_lane / 8h)` → simpan di meta.
- Gate open baru: proyeksi **TP1 net ≥ 3× cost_floor** dan TP2 net ≥ 1.5%
  (generalisasi `MIN_TP1_NET_PCT`/`MIN_NET_EV_PCT` BigMover ke SEMUA lane).
- Expose `futures.min_tp1_cost_mult` (default 3.0) di agent_config.

### F3 — Anti-churn exits (jawaban langsung problem "$1 profit")
Exit sukarela hanya boleh close bila salah satu:
  (a) **proteksi** — SL/liq/max-margin/fail-fast/breaker (tidak berubah);
  (b) **net profit ≥ 3× cost_floor** — mem-bank profit kecil di bawah itu DILARANG;
  (c) **rotation**: kandidat pengganti punya EV > 2× total switching cost
      (fee close + fee open + 2× slippage).
Perubahan konkret:
- `time_stop_scratch` (14× churn!): JANGAN market-close posisi stagnan — ganti dengan
  **tighten SL ke entry ± cost_floor** (biar market yang memutuskan; hemat 1 leg fee
  bila ternyata jalan). Close paksa hanya jika slot penuh DAN ada kandidat (c).
- `breakeven_stop`: trail breakeven dipindah ke `entry + cost_floor` (bukan entry
  polos) — "breakeven" sejati setelah SEMUA biaya, bukan −$0.30.
- Cost-gate G6/B5.3 & funding-window exit: tambahkan syarat (b)/(c) yang sama.

### F4 — Maker-first execution (fase live)
- Entry: **post-only limit** di best bid/ask (maker 0.02% vs taker 0.05%) + chase
  30–60 dtk; fallback taker hanya utk lane bigmover fastpass (momentum tak boleh telat).
- TP: limit order (maker). SL: stop-market (taker, tak terhindarkan — sudah di F1b).
- Aktifkan BNB fee discount (−10%). Kalibrasi ulang `trading_costs.py` dari fill nyata.
- Paper mensimulasikan maker-entry: fee entry 0.02% bila lane bukan bigmover-fastpass.

### F5 — Profit maximization (sisi ukuran, setelah F1-F3 jalan bersih 7 hari)
- A-grade sizing: score ≥ 80 + momentum health "healthy" → risk 1% → 1.5%
  (cap portfolio heat tetap). B-grade tetap 1%. Probe/lock ½ tetap.
- Expectancy throttle: rolling-20 expectancy per lane > 0 → izinkan ukuran penuh;
  negatif → paksa ½ (komplemen WR-pause yang sudah ada).
- TP ladder unbounded (PLAN_v11 P3) tetap — winner besar adalah sumber profit utama
  (data: 4 winner nyata = +$49 vs 20 churn = −$0.4).

### F6 — Clean-room validation → live gates
- ✅ **2026-07-10: history futures DI-RESET** (backup dulu → `backups/`), balance
  kembali ke $1.000. Baseline bersih dimulai SEKARANG; F1–F3 harus mendarat di awal
  periode ini supaya papan skor konsisten.
- Gate sebelum live (ukur 14 hari setelah F1–F3 live, semua NET true-cost):
  1. Day-WR ≥ 80% (pace target 25:5) & tidak ada hari < −2.5%.
  2. Expectancy per trade ≥ +$2 NET semua biaya; profit factor ≥ 1.8.
  3. Churn ratio: exit sukarela dengan |net| < 3× cost_floor harus < 20% dari close
     (sekarang 77%).
  4. Slippage model tervalidasi vs 20 fill testnet.
- Live rollout: Binance Futures **testnet 1 minggu** (API order path) → deposit kecil,
  risk 0.25–0.5%/trade, leverage cap 3×, hanya lane yang lolos gate → naik bertahap.

## 3. Urutan & estimasi effort

| # | Fase | Effort | Catatan |
|---|---|---|---|
| 1 | F1 true-cost | sedang | monitor (3 jalur close) + trading_costs |
| 2 | F2 cost-floor | kecil | auto_trader + agents |
| 3 | F3 anti-churn | sedang | monitor (time-stop/breakeven/cost-gate) |
| 4 | F5 sizing | kecil | balance.compute_futures_sizing |
| 5 | F4 maker-first | besar | modul order live baru + testnet |

## 4. Catatan riset balance sheet (audit 2026-07-10, pre-reset)
- Integritas SEMPURNA: stored $933.75 = $1.000 + Σ pnl_dollar closed (−$66.25),
  0 anomali (tanpa close-tanpa-harga/pnl/reason; pnl_dollar konsisten pnl_pct×size).
- Ledger `balance_transactions` + deposit/withdraw path siap dipakai untuk pencatatan
  deposit riil saat live (Phase 9 architecture — tidak perlu diubah).
- Sesudah reset: balance $1.000, realized 0, 0 open — tervalidasi di §F6.
