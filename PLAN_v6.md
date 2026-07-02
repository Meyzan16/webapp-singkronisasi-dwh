# PLAN_v6 — FUTURES Fix: Sisa Validasi (P7)

Tanggal: 2026-07-01 · **Update: 2026-07-02** — P1–P6 SELESAI + deployed + verified,
dihapus dari dokumen ini (pola PLAN_v4). Tersisa hanya P7 yang menunggu data.

## Yang Sudah Ship (ringkasan 1 baris per fase)

| Fase | Isi | Bukti verifikasi |
|---|---|---|
| Bug#1/#2 | `style` VARCHAR 20→30 (auto-open futures mati total) + `predictive_log.regime` | 2 posisi bigmover terbuka pertama kalinya; auto_open_error=0 |
| P1 | Leverage hard-cap per lane (accum 10×→5×), extended-entry −½, time-stop 90m/6h, breakeven arm 40% | unit test numerik + runtime bersih |
| P2 | TP1=1×risk, TP2=min(resistance, 2.5×risk), MIN_RR 3→2 (ke TP2 ter-cap) | 4 skenario geometri lulus |
| P3 | Entry timing gate: wick-exhaustion + fresh-pullback + OI-confirm (momentum) | 8 unit test + scan bersih |
| P4 | Anti-momentum paradox dibongkar: bigmover terima s/d 300% (extreme ½ size), guard price==high dihapus, G18→size-reduce, penalti health-scaled, funding dua-zona | bigmover 3→7 kandidat/cycle |
| P5 | Wick lookback 3→6 candle (gap poll 120s+), big-mover reasons diperbarui akurat | audit kode + empiris |
| P6 | Deposit research: **deposit TIDAK diperlukan sekarang** — 0 blokir sizing di wallet $955; binding = portfolio heat 6% (scale-invariant). Jika P7 lolos → wallet kerja $1.500–2.000 | log + matematika sizing |

Semua live di Docker. Detail historis: git log `feat/data-pipeline` (commit P1-P6) + task list sesi.

---

## PHASE 7 — Validasi ⏳ MENUNGGU DATA (gate wajib sebelum "fixed" & sebelum deposit)

**Status per 2026-07-02:**
- ✅ P7b AKTIF — per-lane WR auto-pause: threshold 35%, **sampel diturunkan 20→10**
  via `agent_config` (`futures.lane_wr_min_sample=10`, tanpa redeploy) → lane busuk
  terdeteksi 2× lebih cepat selama periode validasi.
- ⏳ P7a/P7c — kohort validasi = trade yang DIBUKA sistem baru
  (`entry_at ≥ 2026-07-02 09:55 UTC` = deploy P5, sistem lengkap). Posisi legacy
  (AERGO/SPORTFUN, dibuka pre-P4) DIKECUALIKAN dari kohort tapi tetap dikelola monitor.

**Kriteria lolos (P7c)** per lane, min **10 closed trades**:
> expectancy = WR×avg_win − (1−WR)×avg_loss **> 0**  ATAU  **WR > 40%**

**Query evaluasi** (jalankan kapan pun; ganti cutoff bila perlu):
```sql
SELECT setup_type,
  count(*) n,
  round(100.0*sum((pnl_pct>0)::int)/count(*),1) wr_pct,
  round(avg(CASE WHEN pnl_pct>0 THEN pnl_pct END)::numeric,2) avg_win,
  round(avg(CASE WHEN pnl_pct<=0 THEN pnl_pct END)::numeric,2) avg_loss,
  round((avg(CASE WHEN pnl_pct>0 THEN pnl_pct END)*sum((pnl_pct>0)::int)/count(*)
       + avg(CASE WHEN pnl_pct<=0 THEN pnl_pct END)*sum((pnl_pct<=0)::int)/count(*))::numeric,2) expectancy
FROM paper_trades
WHERE style LIKE 'futures%' AND status IN ('sl','tp','expired')
  AND entry_at >= extract(epoch from timestamptz '2026-07-02 09:55:00+00')
GROUP BY setup_type ORDER BY n DESC;
```

**Jadwal:** evaluasi pertama **2026-07-05** (3 hari), keputusan gate **2026-07-09** (7 hari).
Jika lane gagal gate → auto-pause 24h sudah melindungi; tindak lanjut = tuning lane itu
(bukan rollback semua — tiap fase independen).

**Setelah P7 lolos:** (a) pertimbangkan deposit ke $1.500–2.000 (hasil P6),
(b) knob yang terbukti penting → `agent_config` (keputusan PLAN_v7-deferred).
