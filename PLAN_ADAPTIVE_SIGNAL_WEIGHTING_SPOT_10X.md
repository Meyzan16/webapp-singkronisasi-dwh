# PLAN — Adaptive Signal Weighting SPOT 10X

Tanggal pembaruan: 2026-07-11  
Status: **MENUNGGU ACCEPTANCE GATE — IMPLEMENTASI F0–F6 SELESAI**

Dokumen ini hanya memuat pekerjaan yang masih terbuka. Fase dan bug yang sudah
selesai diimplementasikan telah dikeluarkan dari plan.

## Remaining acceptance gate

### 1. Kematangan training data

- [ ] Minimal 60 decision events memiliki feature snapshot dan outcome 24 jam yang matang.
- [ ] Minimal 20 sample tersedia pada chronological out-of-sample test.
- [ ] Outcome completeness minimal 99% untuk event yang horizon waktunya sudah jatuh tempo.
- [ ] Tidak ada duplicate decision key, future timestamp, snapshot kosong, atau candle leakage.

Kondisi terakhir:

- Mature feature samples untuk challenger: **0/60**.
- Decision ledger sudah aktif dan outcome tracker mengisi label otomatis.
- Model training tetap diblokir sampai minimum sample tercapai.

### 2. Challenger promotion gate

- [ ] Calibrated challenger mengalahkan empirical baseline pada chronological test.
- [ ] Brier score challenger lebih rendah daripada baseline.
- [ ] Net expectancy out-of-sample positif setelah seluruh biaya.
- [ ] Profit factor out-of-sample minimal 1,5.
- [ ] Hasil tetap positif pada cost stress 1,5×.
- [ ] Tidak ada brittle dependency berdasarkan ablation report.

### 3. Paper canary gate

- [ ] Challenger berstatus `shadow` dan mengumpulkan minimal 20 canary outcomes.
- [ ] Canary expectancy positif.
- [ ] Canary profit factor minimal 1,5.
- [ ] Canary max drawdown maksimal 10%.
- [ ] Drift monitor tidak memicu automatic rollback.

Model tidak boleh memengaruhi kenaikan sizing sebelum seluruh gate ini terpenuhi.

### 4. Final operational verification

- [ ] Full pytest tetap lulus setelah data gate tercapai.
- [ ] Compile dan `git diff --check` bersih.
- [ ] Full runtime scan berstatus learning `active`.
- [ ] On-chain provider sehat atau fail-safe tanpa menghentikan scanner.
- [ ] Model registry memiliki champion dan last-known-good rollback target.
- [ ] Diagnostics menunjukkan duplicate/future/missing snapshot = 0.

## Takeout rule

Hapus file ini hanya setelah seluruh checkbox di atas selesai dan tervalidasi dari
data runtime. Sampai saat itu, scheduler akan terus:

1. mencatat seluruh keputusan dan hard rejection;
2. mengisi outcome 1h/4h/24h/3d/7d;
3. mencoba training hanya ketika evidence baru mencukupi;
4. menjalankan shadow/canary gate;
5. melakukan rollback otomatis jika calibration atau expectancy memburuk.

## Runtime reference terakhir

- Test suite: **97 passed**.
- Full scan: learning aktif, 50/50 decision events tercatat.
- Historical portfolio replay: net +$67,68; PF 3,362.
- Cost stress 1,5×: net +$62,90; PF 3,111.
- Plan belum boleh dihapus karena training/canary sample belum matang.
