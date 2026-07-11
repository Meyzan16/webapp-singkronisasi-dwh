# PLAN_FUTURES — Roadmap Tunggal Futures Agents → Live Trading

Dibuat 2026-07-10 — **menggantikan & menyatukan PLAN_v4 + PLAN_v6 + PLAN_v15 +
PLAN_v16** (keempat file dihapus; sejarah lengkap ada di git). Satu dokumen hidup:
yang sudah ship diringkas satu tabel, yang tersisa diurutkan sebagai backlog tunggal
dengan SATU kerangka validasi (dulu tersebar redundan di v6 P7, v15 §5, v16 F6).

**Tujuan akhir (update 2026-07-10):** 26–27 hari win : ≤3 hari loss per 30 hari
(day-WR ≥ 87%), profit NET semua biaya (fee+slippage+funding), 4 lane berkontribusi
dengan tugas masing-masing TANPA saling mengganggu, lolos gate → live trade dari
wallet Binance nyata. (Gate keras hari-30 tetap 25:5 — 26-27:3 adalah target
aspiratif setelah item H landing; lihat §2A.)

---

## 1. Sudah ship (ringkasan — detail di git log)

| Asal | Isi | Commit |
|---|---|---|
| v2/v3/v6 P1-P6 | Leverage caps per lane, TP1=1×risk & TP2 cap 2.5×, entry timing gate (wick/chase/OI), anti-momentum paradox dibongkar, wick lookback 6 | pre-`84669af` |
| v15 P1-P5,P7-P9 | Daily loss breaker 2.5% WIB · profit lock 1% + giveback stop · consecutive-SL pause (3/lane, 5/global) · BM fade guards (breadth, 2-SL/hari, weekend ×0.5, max 4 searah) · BM be-arm +1.5% + partial 50%@1×ATR · fail-fast −1×ATR/10-45m · offline reconcile · 7 knob agent_config | `84669af` |
| v15 R0 | Backfill big_mover_log exact-horizon; BM LONG chase 1TP:9SL (EV −1,4%) vs SHORT EV +4,1%; skor tak menolong LONG; near-miss log agent1/2 | `84669af` |
| v16 F1-F3,F5 | True-cost pnl (slippage entry + SL-fill 0.08% + funding G6 dibayar) · cost-floor gate TP1 ≥ 3× biaya · anti-churn (time_stop → tighten, breakeven = entry±cost, bank-gate 3×) · lane throttle WR<40% → ½ size | `a7b5e1a` |
| Item H (2026-07-10) | Scanner audit: a1 ATH-break bonus hidup lagi (`[-42:-1]`, dulu unreachable & penalti −10 kena semua koin cetak high) · BM funding veto 0.12→0.25 (two-zone P4c hidup) · universe eksklusif a1/a2 ≤8% / a3 5-15% / BM ≥15% (bracket 18-50% a3 + penalti terkait dihapus; change_1h salah-3-jam ikut hilang bersama konsumennya) · a2 T2 → support-bounce 14pt (near-resistance milik a1) · a1 dedup LONG+SHORT (aturan D2.3) · rejection_log hanya skor ≥40 · dead code a1/a2 | smoke test: gates ✓, ATH fire ✓, guard ✓; koin quiet sintetis a1 skor 47 (historis max 51) |
| Ops | History futures direset 2026-07-10 (backup `backups/paper_trades_futures_pre_v16_reset_20260710.csv`), balance $1.000 | — |
| Purge §1b (2026-07-10) | Data yatim turunan trade lama dihapus (konfirmasi owner): `agent_signal_weights` futures+cross 72 · `signal_weight_history` futures 4.551 · `rejection_log` pre-reset 284rb. Bocor bobot lama via `get_cross_weight()` tertutup; spot tak tersentuh | `0bfb232` |

Fakta kunci yang mendasari desain: winner nyata fee-nya 1–3% dari profit; kerugian
datang dari (a) churn exit mikro (77% close pre-reset), (b) BM LONG serial di hari
fade, (c) posisi tak termonitor saat backend mati. Ketiganya sudah ditutup di atas.

**Snapshot era baru (11 Jul 11:17 WIB, ~12 jam pasca-H):** 10 closed, **+$3.62**,
balance $1.003,62. Avg loss BM **−$1,36**/trade (era lama: −$11) — fail-fast P9 +
anti-churn F3 terbukti bekerja. Near-miss a2 skor 63 sudah muncul (a1 belum).

---

## 2. BACKLOG AKTIF

**⏱ Next steps (di-refresh 2026-07-11 — SEMUA agent diperbarui item H pada 10 Jul
22:42 WIB = epoch 1783698144; data skor sebelum itu mencerminkan scoring LAMA, maka
jam data untuk kalibrasi di-restart dari titik itu):**

| Kapan | Apa |
|---|---|
| Sekarang (bisa kapan saja) | **Item C**: bangun kode learning loop — self-gating pada sampel, jadi aman dibangun sebelum data matang; efek nyata pertama Senin 20 Jul |
| 14 Jul | **Item B**: cek near-miss 3 hari era-H — kalibrasi HANYA bila a1/a2 masih dormant (H mungkin sudah cukup; bukti dini a2=63) |
| 17 Jul | **Item D**: keputusan arah BigMover (big_mover_log independen dari perubahan agent — jam TIDAK di-restart) |
| 18 Jul | Cek mingguan pertama Gate A (7 hari era-H) |
| 18–24 Jul | **Item E**: analisis early-breakout — mulai 18 Jul bila sampel 3-7% era-H cukup, mundur ke 24 Jul bila tipis |
| ~25 Jul | **Keputusan Gate LIVE** (14 hari era-H) → lolos = item G |

### A. Kerangka validasi TUNGGAL (menyatukan v6 P7 + v15 §5 + v16 F6)
**Baseline = era-H (2026-07-11)** — reset + semua perubahan agent selesai 10 Jul
malam, jadi hari validasi penuh pertama = 11 Jul. Semua angka NET true-cost.
Cek mingguan, dua keputusan:

**Gate LIVE (hari ke-14, ≈ 2026-07-25):**
- Day-WR ≥ 80%; tidak ada hari < −2.5% wallet; tidak ada breaker-day tak tertangani.
- Expectancy per trade ≥ +$2 net; profit factor ≥ 1.8.
- Churn ratio: exit sukarela |net| < 3× cost_floor harus < 20% dari close (pre-reset: 77%).
- Per lane (min 10 closed): expectancy > 0 ATAU WR > 40% — lane gagal → tetap
  auto-pause, TIDAK ikut live.
- LOLOS → kerjakan item G (live rollout). GAGAL → diagnosa per lane, ulang 14 hari.

**Gate hari ke-30 (≈ 2026-08-10):** keras ≥ 25 hari WIN : ≤ 5 loss dari 30 hari WIB
ber-trade; **aspiratif 26–27 : ≤3** (item H sudah landing — tinggal butuh
churn <20% + ≥3 lane expectancy positif). Proksi mingguan < 70% dua minggu
berturut → review desain.

### B. Kalibrasi skor agent1/agent2 — v15 P6 · **due 2026-07-14** (jam di-restart era-H)
Item H mengubah scoring a1/a2 secara material (ATH fix, universe gate, a2 T2 →
support-bounce) — near-miss pra-H tak lagi mewakili sistem. Langkah:
1. 14 Jul: cek `rejection_log` `below_auto_threshold` era-H (`rejected_at ≥
   1783698144`) — **H mungkin sudah menghidupkan lane ini sendiri** (bukti dini
   11 Jul: a2 near-miss 63; sintetis a1 kini 47 vs max historis 51).
2. Kalibrasi bobot sinyal inti HANYA bila masih dormant (belum ada near-miss
   a1 / belum ada trade a1/a2). JANGAN turunkan ambang (v14 sudah membuktikan sia-sia).

### C. Learning loop dari predictive_log — v4 P2 · **kode bisa dibangun SEKARANG,
efek pertama Senin 2026-07-20**
Semua kalibrasi WAJIB filter `scanned_at ≥ 1783698144` — prediksi pra-H dibuat
oleh scoring lama (data lama tetap disimpan untuk pembanding, tapi tidak untuk
menyetel bobot). Kode aman dibangun sekarang karena tiap penyesuaian self-gating
pada sampel (n≥10/20 per sinyal era-H):
1. **P2.1 weekly signal review** (`agents/learning/weekly_signal_review.py`, Senin
   00:10 UTC): hit_rate_4h < 25% (n≥10) → weight −0.1 (floor 0.7); > 60% → +0.1
   (cap 1.5; 4 minggu pertama lower-only). Endpoint `GET /predictive/signal_review`.
2. **P2.2 regime modifier re-tune**: hit rate per (agent, regime, direction) —
   konfirmasi/koreksi modifier ±5 via key `_regime_{regime}_{dir}_`.
3. **P2.3 predictive→weights blend**: `0.85×trade + 0.15×predictive`, gate n≥20,
   floor/cap tetap. Risiko universe-bias → normalize baseline, konservatif.

### D. Keputusan arah BigMover — tindak lanjut R0c · **due 2026-07-17** (jam TIDAK
di-restart — big_mover_log merekam SEMUA big mover terlepas dari perubahan agent)
Dengan 7 hari data exact-horizon (`last_backfill_at > 1783600000` WAJIB — data lama
endpoint-biased): jika BM LONG tetap ≥ 1:5 SL:TP bahkan saat breadth sehat →
BM SHORT-bias (LONG hanya force-open manual). Kandidat tuning: `BM_BE_ARM_ABS_PCT`
1.5 → 1.2 (GWEI peak +1.35% lolos tipis). Pantau juga efek H1.3: zona funding
0.12-0.25 kini menghasilkan open ½-size — masuk ke analisis arah.

### E. Early-breakout decision — v4 P3 · **due 2026-07-18, mundur ke ~24 Jul bila
sampel era-H tipis** (conditional)
`GET /predictive/hit_rate?agent=futures_agent3&hours=336`, filter change_24h 3-7%
(branch D2.4 tidak berubah oleh H, tapi preferensi tetap `scanned_at ≥ 1783698144`):
- hit_rate_4h > 40% (n≥30) → agent baru `agent_early_breakout.py` (universe 3-8%,
  lev cap 5×, stagnant 12h, quota lane 1, MIN_SCORE adaptif start 60).
- ≤ 40% → tuning branch D2.4 di agent3 saja (oi_chg 1.0→2.0? bo_pct 0.3?).
- Jika dibuat: WR < 30% setelah 20 trade → matikan lane.

### F. UI transparansi — v4 P4 · prioritas rendah, paralel kapan saja
- Probability badge di Pre-Move Radar (hit rate per agent:direction, color-coded).
- Badge `🎯 predicted T-Xh` di Top Gainers (endpoint `/predictive/pre_detection`).
- Tambahan v16: tampilkan breakdown `cost_slippage_pct`/`cost_funding_dollar`/
  `cost_floor_pct` di history detail.

### H. ✅ SELESAI 2026-07-10 — dipindah ke tabel shipped §1. Yang tersisa dari H
hanya **peran per lane** (pegangan operasional):

| Lane | Universe | Tugas | Horizon |
|---|---|---|---|
| a3 momentum | 5-15% | penghasil harian utama — wave terkonfirmasi | jam |
| BM | ≥15% | specialist extreme mover, size kecil, guard ketat (SHORT-edge per R0c) | 1-3 jam |
| a1 pre-gainer | ≤8% | sniper pre-breakout (dekat resistance) | 6-24 jam |
| a2 accumulation | ≤8% | swing Wyckoff bounce-from-support | 1-3 hari |

Aturan 14-hari: lane ber-expectancy negatif → matikan (2 lane sehat > 4 saling ganggu).

### G. Live rollout — v16 F4+F6 · **hanya setelah Gate LIVE (A) lolos**
1. Maker-first execution: entry post-only limit (0.02%) + chase 30-60 dtk; fallback
   taker hanya BM-fastpass; TP limit; SL stop-market; BNB discount.
2. Kalibrasi `trading_costs.py` dari ≥20 fill **testnet** (1 minggu wajib).
3. Deposit kecil → risk 0.25–0.5%/trade, leverage cap 3×, HANYA lane yang lolos
   gate → naik bertahap. Ledger deposit/withdraw (Phase 9) sudah siap.

---

## 3. Keputusan terkunci (gabungan)

| Pertanyaan | Keputusan |
|---|---|
| Agent early-breakout baru? | Conditional — hanya jika hit rate > 40%, n ≥ 30 (item E) |
| Blend predictive→weight | 0.85/0.15 konservatif; 0.7/0.3 hanya jika terbukti additive |
| Weekly review arah apply | Lower-only 4 minggu pertama |
| Bank profit sukarela | Dilarang < 3× cost_floor (v16 F3) — permanen |
| BM LONG | Diizinkan HANYA di belakang guard breadth/budget/weekend/direction-cap; re-eval item D |
| dd_hard_stop | Otomatis dari ukuran wallet (risk_gate) — jangan expose sebagai config |
| Riset big_mover_log | WAJIB filter `last_backfill_at > 1783600000` |
| **Era data baru** | Epoch **1783698144** (10 Jul 22:42 WIB = reset + item H). Semua kalibrasi skor (rejection_log, predictive_log) WAJIB filter ≥ ini; big_mover_log pakai filter backfill-nya sendiri; jam item D tidak di-restart |

## 4. Query monitor (jalankan kapan pun)

```sql
-- Day-level W/L (gate A)
SELECT to_char(to_timestamp(closed_at) AT TIME ZONE 'Asia/Jakarta','YYYY-MM-DD') AS d,
       count(*) n, round(sum(pnl_dollar)::numeric,2) pnl,
       CASE WHEN sum(pnl_dollar) > 0 THEN 'WIN' ELSE 'LOSS' END result
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('tp','sl','expired') AND pnl_dollar IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC;

-- Expectancy per lane (gate A per-lane)
SELECT setup_type, count(*) n,
  round(100.0*sum((pnl_dollar>0)::int)/count(*),1) wr_pct,
  round(avg(CASE WHEN pnl_dollar>0 THEN pnl_dollar END)::numeric,2) avg_win,
  round(avg(CASE WHEN pnl_dollar<=0 THEN pnl_dollar END)::numeric,2) avg_loss,
  round(avg(pnl_dollar)::numeric,2) expectancy_d
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('tp','sl','expired') AND pnl_dollar IS NOT NULL
GROUP BY 1 ORDER BY n DESC;

-- Churn ratio (gate A #3): exit sukarela dgn |net| kecil
SELECT round(100.0 * count(*) FILTER (WHERE (signals_json::json->>'close_reason')
         IN ('breakeven_stop','cost_exceeds_profit','funding_window_exit','rotation_stagnant')
         AND abs(pnl_pct) < 3 * coalesce((signals_json::json->>'cost_floor_pct')::float, 0.3))
       / nullif(count(*),0), 1) churn_pct
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('tp','sl','expired');
```
