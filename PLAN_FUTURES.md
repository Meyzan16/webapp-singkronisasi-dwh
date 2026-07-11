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
| Ops | History futures direset 2026-07-10 (backup `backups/paper_trades_futures_pre_v16_reset_20260710.csv`), balance $1.000 — **baseline validasi dimulai 10 Jul** | — |

Fakta kunci yang mendasari desain: winner nyata fee-nya 1–3% dari profit; kerugian
datang dari (a) churn exit mikro (77% close pre-reset), (b) BM LONG serial di hari
fade, (c) posisi tak termonitor saat backend mati. Ketiganya sudah ditutup di atas.

---

## 1b. Basis data pasca-reset 10 Jul (audit 2026-07-10 malam)

Reset `scope=futures` menghapus trade+balance, TAPI tidak semua turunannya. Audit:

**SELAMAT & tetap VALID (independen dari trade — backlog C/D/E aman):**
- `predictive_log` (6 hari, resolved a2=431/BM=371/a3=161/a1=17) — mengukur akurasi
  SKOR vs harga, bukan trade → basis item C & E tetap sah.
- `big_mover_log` (33rb) — outcome harga; riset WAJIB filter
  `last_backfill_at > 1783600000` (baris lama endpoint-biased).
- `rejection_log` pasca-reset (`rejected_at ≥ 1783698144`) — basis item B.

**YATIM (turunan trade yang sudah dihapus) — PERLU PURGE, menunggu konfirmasi
eksplisit owner (auto-mode menolak mass-delete tanpa penyebutan tabel):**
- `agent_signal_weights` rows agent futures + `cross_agent` (70 baris) — bobot
  hasil belajar dari trade lama. **BOCOR AKTIF**: `cross_agent_learning` membacanya
  tiap cycle → `get_cross_weight()` menyuntik learning lama ke scoring baru.
  Zombie-prune internal baru membersihkan setelah 45 hari — terlalu lambat.
- `signal_weight_history` rows futures (4.471 baris) — trajectory chart tanpa induk.
- `rejection_log` pre-reset (445rb baris) — mencerminkan bobot/threshold sistem
  lama; auto-prune 7 hari akan menghapusnya sendiri ±17 Jul, purge hanya mempercepat.

SQL purge (jalankan setelah dikonfirmasi):
```sql
DELETE FROM agent_signal_weights WHERE agent IN
  ('futures_agent1','futures_agent2','futures_agent3','futures_agent_bigmover','cross_agent');
DELETE FROM signal_weight_history WHERE agent IN
  ('futures_agent1','futures_agent2','futures_agent3','futures_agent_bigmover');
DELETE FROM rejection_log WHERE rejected_at < 1783698144;
```
(`cross_agent` aman dihapus: dibangun ulang otomatis tiap cycle dari tabel yang
sudah bersih; baris spot tidak disentuh.)

---

## 2. BACKLOG AKTIF (urut jatuh tempo)

### A. Kerangka validasi TUNGGAL (baseline 2026-07-10, menyatukan v6 P7 + v15 §5 + v16 F6)
Semua angka NET true-cost. Cek mingguan, dua keputusan:

**Gate LIVE (hari ke-14, ≈ 2026-07-24):**
- Day-WR ≥ 80%; tidak ada hari < −2.5% wallet; tidak ada breaker-day tak tertangani.
- Expectancy per trade ≥ +$2 net; profit factor ≥ 1.8.
- Churn ratio: exit sukarela |net| < 3× cost_floor harus < 20% dari close (pre-reset: 77%).
- Per lane (min 10 closed): expectancy > 0 ATAU WR > 40% — lane gagal → tetap
  auto-pause, TIDAK ikut live.
- LOLOS → kerjakan item G (live rollout). GAGAL → diagnosa per lane, ulang 14 hari.

**Gate hari ke-30 (≈ 2026-08-09):** keras ≥ 25 hari WIN : ≤ 5 loss dari 30 hari WIB
ber-trade; **aspiratif 26–27 : ≤3** (item H sudah landing 10 Jul — tinggal butuh
churn <20% + ≥3 lane expectancy positif). Proksi mingguan < 70% dua minggu
berturut → review desain.

### B. Kalibrasi skor agent1/agent2 — v15 P6 · **due ~2026-07-13**
Agent1 0 trade sepanjang sejarah (max skor ~51/190rb evaluasi). Data near-miss
(`rejection_log` reason `below_auto_threshold`) terkumpul sejak 10 Jul → setelah
≥3 hari: kalibrasi bobot sinyal inti supaya setup bagus realistis capai 65.
JANGAN turunkan ambang lagi (v14 sudah 72→65 tanpa efek — masalahnya di skor).
Pasca-reset: query kalibrasi WAJIB `rejected_at >= 1783698144` (lihat §1b).

### C. Learning loop dari predictive_log — v4 P2 · **due ~2026-07-11**
Status data 10 Jul: 6 hari; resolved a2=431, BM=371, a3=161 ✓, a1=17 (tunggu ≥20).
1. **P2.1 weekly signal review** (`agents/learning/weekly_signal_review.py`, Senin
   00:10 UTC): hit_rate_4h < 25% (n≥10) → weight −0.1 (floor 0.7); > 60% → +0.1
   (cap 1.5; 4 minggu pertama lower-only). Endpoint `GET /predictive/signal_review`.
2. **P2.2 regime modifier re-tune**: hit rate per (agent, regime, direction) —
   konfirmasi/koreksi modifier ±5 via key `_regime_{regime}_{dir}_`.
3. **P2.3 predictive→weights blend**: `0.85×trade + 0.15×predictive`, gate n≥20,
   floor/cap tetap. Risiko universe-bias → normalize baseline, konservatif.

### D. Keputusan arah BigMover — tindak lanjut R0c · **due ~2026-07-17**
Dengan 7 hari data exact-horizon (`last_backfill_at > 1783600000` WAJIB — data lama
endpoint-biased): jika BM LONG tetap ≥ 1:5 SL:TP bahkan saat breadth sehat →
BM SHORT-bias (LONG hanya force-open manual). Kandidat tuning: `BM_BE_ARM_ABS_PCT`
1.5 → 1.2 (GWEI peak +1.35% lolos tipis).

### E. Early-breakout decision — v4 P3 · **due ~2026-07-18** (conditional)
`GET /predictive/hit_rate?agent=futures_agent3&hours=336`, filter change_24h 3-7%:
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
