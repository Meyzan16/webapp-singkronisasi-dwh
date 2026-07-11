# SCHEDULE_FUTURES — Jadwal Eksekusi Menuju Live Trading

Update 2026-07-11 — pengganti PLAN_FUTURES.md (di-rename: semua fase yang bisa
dikerjakan sudah SELESAI; yang tersisa hanya eksekusi bertanggal). Sejarah lengkap
fase yang sudah ship (v15 anti loss-day, v16 true-cost, item H scanner overhaul,
item C learning loop): git log `feat/data-pipeline`.

**Target:** 26–27 hari win : ≤3 hari loss / 30 hari (gate keras 25:5), NET semua
biaya. **Era data = epoch 1783698144** (10 Jul 22:42 WIB) — semua kalibrasi skor
filter ≥ ini. Baseline validasi: 2026-07-11.

---

## JADWAL EKSEKUSI

### 📅 14 Jul — Item B: kalibrasi agent1/agent2 (hanya bila masih dormant)
Cek near-miss 3 hari era-H; H mungkin sudah cukup (bukti dini: a2 near-miss 63).
```sql
SELECT agent, count(*) n, round(avg(score)::numeric,1) avg_s, round(max(score)::numeric,1) max_s
FROM rejection_log WHERE reject_reason='below_auto_threshold' GROUP BY agent;
-- + cek: SELECT count(*) FROM paper_trades WHERE style IN ('futures_agent1','futures_agent2');
```
Dormant = a1 tanpa near-miss & tanpa trade → kalibrasi bobot sinyal inti supaya
setup bagus realistis capai 65. JANGAN turunkan ambang (v14 terbukti sia-sia).

### 📅 17 Jul — Item D: keputusan arah BigMover
7 hari data exact-horizon (`last_backfill_at > 1783600000`): jika BM LONG tetap
≥ 1:5 SL:TP bahkan saat breadth sehat → **BM SHORT-bias** (LONG hanya force-open
manual). Kandidat tuning: `BM_BE_ARM_ABS_PCT` 1.5 → 1.2. Pantau efek zona funding
0.12-0.25 (open ½-size sejak H1.3).

### 📅 18 Jul — Cek mingguan Gate A pertama (7 hari era-H)
Query §Referensi. Lolos-jalur: day-WR ≥ 80%, churn < 20%, tak ada hari < −2.5%.
Day-WR < 70% → jangan tunggu — diagnosa sekarang.

### 📅 18–24 Jul — Item E: early-breakout decision (conditional)
`GET /predictive/hit_rate?agent=futures_agent3&hours=336`, filter change_24h 3-7%
era-H. hit_rate_4h > 40% (n≥30) → buat `agent_early_breakout.py` (universe 3-8%,
lev ≤5×, stagnant 12h, quota 1). ≤40% → tuning branch D2.4 saja. Sampel tipis →
mundur ke 24 Jul.

### 📅 Senin 20 Jul — review hasil weekly signal review pertama
`GET /predictive/signal_review` (otomatis jalan Senin 00:10 UTC; `?run=true` untuk
manual). Periksa: (a) adjustment bobot masuk akal, (b) `regime_report` → keputusan
P2.2: modifier regime ±5 di a1/a2/a3 dikonfirmasi/dikecilkan berdasar rekomendasi.

### 📅 ~25 Jul — KEPUTUSAN GATE LIVE (14 hari era-H)
Semua NET true-cost: day-WR ≥ 80% · tak ada hari < −2.5% · expectancy ≥ +$2/trade ·
PF ≥ 1.8 · churn < 20% · per lane (≥10 closed): expectancy > 0 atau WR > 40%.
Sekalian: **aturan 14-hari** — lane expectancy negatif DIMATIKAN (2 lane sehat >
4 saling ganggu). LOLOS → Item G:
1. Maker-first execution (post-only 0.02%, chase 30-60s; taker hanya BM-fastpass;
   TP limit; SL stop-market; BNB discount).
2. Kalibrasi `trading_costs.py` dari ≥20 fill **testnet** (1 minggu wajib).
3. Deposit kecil → risk 0.25-0.5%/trade, lev cap 3×, hanya lane lolos gate.
GAGAL → diagnosa per lane, ulang 14 hari.

### 📅 ~10 Agu — GATE HARI-30
Keras: ≥25 WIN : ≤5 loss. Aspiratif: 26-27 : ≤3. Proksi mingguan < 70% dua minggu
berturut → review desain lebih awal.

**Otomatis (tanpa tindakan):** weekly signal review tiap Senin 00:10 UTC ·
raise-bobot aktif otomatis 7 Agu (4 minggu lower-only) · weekly backtest Minggu ·
monthly calibration tgl 1.

**Opsional tanpa tanggal:** Item F UI (probability badge, detected-at badge,
cost breakdown di history).

---

## Referensi operasional

**Peran lane (item H):** a3 momentum 5-15% (harian, jam) · BM ≥15% (extreme,
SHORT-edge, 1-3 jam) · a1 pre-gainer ≤8% (pre-breakout, 6-24 jam) · a2
accumulation ≤8% (support bounce, 1-3 hari).

**Keputusan terkunci:**
| Hal | Keputusan |
|---|---|
| Era data | Epoch 1783698144 — kalibrasi skor filter ≥ ini; big_mover_log pakai `last_backfill_at > 1783600000` |
| Bank profit sukarela | Dilarang < 3× cost_floor (v16 F3) |
| BM LONG | Hanya di belakang guard breadth/budget/weekend/direction-cap; re-eval 17 Jul |
| Blend predictive→weight | 0.85/0.15, gate n≥20 (item C, live) |
| Weekly review | Lower-only s/d 7 Agu, lalu raise aktif |
| Agent early-breakout | Conditional: hit>40%, n≥30 |
| dd_hard_stop | Otomatis dari ukuran wallet — jangan jadikan config |

**Query monitor:**
```sql
-- Day-level W/L
SELECT to_char(to_timestamp(closed_at) AT TIME ZONE 'Asia/Jakarta','YYYY-MM-DD') AS d,
       count(*) n, round(sum(pnl_dollar)::numeric,2) pnl,
       CASE WHEN sum(pnl_dollar) > 0 THEN 'WIN' ELSE 'LOSS' END result
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('tp','sl','expired') AND pnl_dollar IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC;

-- Expectancy per lane
SELECT setup_type, count(*) n,
  round(100.0*sum((pnl_dollar>0)::int)/count(*),1) wr_pct,
  round(avg(pnl_dollar)::numeric,2) expectancy_d
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('tp','sl','expired') AND pnl_dollar IS NOT NULL
GROUP BY 1 ORDER BY n DESC;

-- Churn ratio (target < 20%)
SELECT round(100.0 * count(*) FILTER (WHERE (signals_json::json->>'close_reason')
         IN ('breakeven_stop','cost_exceeds_profit','funding_window_exit','rotation_stagnant')
         AND abs(pnl_pct) < 3 * coalesce((signals_json::json->>'cost_floor_pct')::float, 0.3))
       / nullif(count(*),0), 1) churn_pct
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('tp','sl','expired');
```
