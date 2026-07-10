# PLAN_v15 — Anti Loss-Day (target 25 win-day : 5 loss-day)

Tanggal: 2026-07-09 · **Update 2026-07-10: SEMUA fase kode SELESAI + LIVE + committed
(`84669af`)** — detail implementasi dihapus dari dokumen ini (pola PLAN_v4/v6);
lihat git log + PLAN_v16 untuk kelanjutan (true-cost engine).

Target: dari 30 hari trading, ≥25 hari ditutup profit, ≤5 hari loss (kecil).
Lahir dari forensik Sabtu 4 Juli: −$40.81, BigMover 12× LONG serial SL di hari
pump-and-fade; semua guard lama gagal menghentikannya.

## Yang Sudah Ship (ringkasan 1 baris per fase)

| Fase | Isi | Bukti verifikasi |
|---|---|---|
| P1 | Daily loss breaker 2.5% WIB (stateless dari DB) | Replay 4 Juli: blok di −$23.30 |
| P2 | Consecutive-SL pause: 3 loss nyata/lane→12h, 5 global→6h; scratch transparan, win memutus streak | Unit replay: fire di SL#3, win break ✓ |
| P3 | BM fade guards: breadth ≥60% fading→blok LONG; budget 6/hari; stop 2 SL/hari; weekend ×0.5 +5 skor; max 4 searah | Replay: BM tutup di BEL 15:16 |
| P4 | BM breakeven-arm floor +1.5% + partial 50% @ 1×ATR (akunting partial benar di semua jalur close) | Unit test arm LONG/SHORT ✓ |
| P5 | Offline reconcile: startup/gap>15m replay klines 15m → close retroaktif SL/TP | Kasus XAG −$24.89 tak bisa terulang |
| P7 | 7 knob `futures.*` di agent_config + section `plan_v15` di API | Seeded + live di /agent/config |
| P8 | Daily profit lock 1% day-peak → A-grade ½ size; giveback ≤0.3% → stop; monitor tighten | Replay 4 Juli: engage 15:53 (+$11.73) → hari ±0 |
| P9 | Fail-fast: adverse ≥1×ATR @10-45m tanpa progres + konfirmasi 1m | Replay 23 trade: 4 trigger semua loser, 0 winner kill |
| R0a | Backfill big_mover_log exact-horizon + path-aware bracket + per-horizon repick | 5.000 baris terisi; data pre-09-Jul = endpoint-biased (filter `last_backfill_at > 1783600000`) |
| R0c | BM LONG chase 1 TP : 9 SL (EV −1,4%); SHORT dump WR 49% EV +4,1%; skor ≥70 tak menolong LONG (3:20) | 3.579 sinyal exact-horizon |
| R0d | Near-miss agent1/2 (skor 52-64) → rejection_log `below_auto_threshold` | Aktif sejak 10 Jul |
| Bugfix | atr_pct kini di meta a1/a2/a3 (G4 rugpull dulu selalu ambang 5%); fast-loop close hitung banked partials | audit + unit ✓ |

Catatan: exit `time_stop_scratch` dari P-lama telah DIGANTI oleh PLAN_v16 F3
(tighten-SL, bukan market close) — histori reason itu tak akan muncul lagi.

## ⏳ Sisa: P6 — kalibrasi skor agent1/agent2

Agent1 = 0 trade sepanjang sejarah (max skor ~51 dari 190rb evaluasi — masalah
kalibrasi, bukan ambang). Tunggu ≥3 hari data R0d di rejection_log, lalu kalibrasi
bobot sinyal inti supaya setup bagus realistis mencapai 65. JANGAN turunkan ambang
lagi (PLAN_v14 sudah 72→65 tanpa efek).

## Gate validasi (keputusan hari ke-30; baseline reset 2026-07-10)

- **Gate utama:** ≥25 hari WIN dari 30 hari WIB ber-trade; hari loss ≤5, tak ada < −2.5%.
- Proksi mingguan: day-WR ≥80%; <70% dua minggu berturut → review desain.
- Non-loss rate per trade ≥70%; loss merusak ≤20% dengan avg ≤ −$6.
- Expectancy per lane > 0 ATAU WR > 40% (min 10 trade/lane).

```sql
-- Day-level W/L
SELECT to_char(to_timestamp(closed_at) AT TIME ZONE 'Asia/Jakarta','YYYY-MM-DD') AS d,
       round(sum(pnl_dollar)::numeric,2) pnl,
       CASE WHEN sum(pnl_dollar) > 0 THEN 'WIN' ELSE 'LOSS' END result
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('tp','sl','expired') AND pnl_dollar IS NOT NULL
GROUP BY 1 ORDER BY 1 DESC;
```

Re-evaluasi BM arah (kandidat SHORT-bias) setelah 7 hari data exact-horizon —
query per PLAN_v6 §P7c dengan filter `last_backfill_at > 1783600000`.
