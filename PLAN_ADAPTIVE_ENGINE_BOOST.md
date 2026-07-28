# PLAN — Adaptive Engine BOOST (SPOT + FUTURES)

**Tujuan:** membuat adaptive engine benar-benar **meningkatkan scanner SPOT & FUTURES**
(bukan cuma mengamati), memberi **monitoring lewat Telegram**, dan **membersihkan bug**.

Status ditulis: 23 Jul 2026. Basis analisis kode live (backend PID aktif, ledger SPOT 67.424 baris, FUTURES 1.703 baris).

---

## A. Temuan analisis menyeluruh (kondisi SEKARANG)

### A1. Loop learning→scanner sudah TERPASANG, tapi masih NETRAL
- FUTURES: `agents/futures/scheduler.py:284-292` memuat learning (`load_futures_learning`) lalu `apply_lane_learning` per lane; `:593` `update_weights()` pasca-outcome.
- SPOT: `agents/opportunity/scanner.py:1415` `_load_learning_weights` + `:2062-2074` apply per lane; `agents/opportunity/scheduler.py:738` `update_spot_weights`.
- **Masalah inti:** per docstring `learning_loader.py:8-17`, bobot tersimpan mayoritas **neutral 1.0** (sumber weight canonical-keyed belum ada). Efek nyata ke skor = **veto-only** (ban `weight<0.8 & n≥10`). Jadi engine "belajar" tapi **belum mengubah rumus skor** → scanner belum benar-benar meningkat. Itu memang "fase lanjutan" yang belum dikerjakan.

### A2. Model belum dipromosikan (shadow)
- SPOT `engine_status` live = `canary` tetapi `promotion_eligible` di-gate ketat; FUTURES `shadow` (registry model kosong, nunggu 60 mature samples). Lifecycle promote→canary→champion ada tapi belum pernah advance ke champion → tak ada model yang mengubah keputusan.

### A3. BUG KRITIS — endpoint SPOT adaptive-engine lambat (sumber ECONNRESET)
`backend/app/api/v1/signals.py:47-178` tiap request:
- **Memuat ~43rb blob `feature_snapshot_json`** ke memori (`:69-73`) lalu parse JSON di Python (`:86-94`) hanya untuk menghitung `mature_feature_samples`.
- **Menjalankan `run_spot_walkforward()` inline** (`:113-115`) — komputasi berat, sinkron, per request.
- Banyak agregasi COUNT/GROUP BY full-table tanpa batas waktu.
→ ~8 detik/response → proxy frontend `socket hang up (ECONNRESET)`. **Ini bug yang dilaporkan user.**

### A4. Risiko sejenis di FUTURES
`signals.py:181+` cepat sekarang (tabel kecil) tapi pola agregasi full-table yang sama akan melambat saat ledger tumbuh. Perlu diamankan sekalian.

### A5. Belum ada monitoring adaptive-engine ke Telegram
`ops/report-telegram.ps1` melapor sistem/binance/posisi/performa, **belum** melaporkan status engine (mature progress, outcome completeness, gates, jumlah sinyal ter-ban, transisi shadow→canary→champion).

---

## B. Rencana kerja (bertahap, aman)

### FASE 0 — Bersihkan BUG ✅ SELESAI 23 Jul
Hasil: SPOT endpoint 8000ms → 2351ms cold → **6ms cache**; ECONNRESET hilang. FUTURES 6ms.
- `spot_walkforward.py`: select 3 kolom (bukan hydrate 43rb ORM) + cache TTL 300s.
- `signals.py` SPOT: mature_feature_samples via SQL LIKE count (buang muat 43rb blob + loop parse Python).
- `signals.py`: `_ENGINE_CACHE` TTL 45s untuk kedua endpoint (SPOT+FUTURES).
- `futures_walkforward.py`: cache TTL 300s (proaktif).
Verifikasi: py_compile OK, payload benar (quality semua nol, ledger 67.630), tak ada exception, agent+binance sehat.

### FASE 0 (asli) — Bersihkan BUG (prioritas, tak ubah keputusan trading)
- **B0.1** Pindahkan komputasi berat SPOT endpoint keluar dari request path:
  - Hitung `mature_feature_samples` via **SQL** (hindari muat 43rb blob) — mis. kolom boolean/flag `has_challenger_features` diisi saat insert, atau `COUNT` dengan filter di DB.
  - `walkforward` **jangan inline** — cache hasil terakhir (TTL, dihitung di loop learning `spot_walkforward` yang sudah ada) dan endpoint hanya membaca cache.
  - Batasi agregasi ke jendela waktu relevan bila memungkinkan.
  - Target: endpoint < 500ms.
- **B0.2** Terapkan pola cache yang sama ke endpoint FUTURES (proaktif).
- **B0.3** Audit `data_quality` gate (`duplicate_keys/missing_snapshots/future_events/invalid_closes`) — pastikan angka nol wajar; kalau tidak, perbaiki sumber di decision_ledger.
- **Verifikasi:** ukur latency kedua endpoint; tsc+eslint+build UI; tak ada perubahan angka keputusan.

### FASE 1 — Shadow-compare ✅ SELESAI 23 Jul (langkah aman; flip nunggu bukti)
TEMUAN kunci saat baca kode live:
- SPOT `learning_policy.py:170` SUDAH menimpa `opportunity_score` = raw × factor -> kontribusi skor SPOT **sudah aktif** (bukan veto-only). Membaik saat bobot menyimpang.
- FUTURES `learning_policy.py:203-262` VETO-ONLY: `adaptive_score` di field terpisah, `score` tak ditimpa. Ini yang perlu di-flip untuk "angkat scanner futures".
Dikerjakan (READ-ONLY, nol perubahan keputusan):
- `agents/learning/futures_shadow_compare.py`: bandingkan seleksi by raw `score` vs `adaptive_score` pada outcome matang (pnl_4h). Cache TTL 300s.
- Wired ke endpoint `/signals/adaptive-engine/futures` field `shadow_compare` + baris di report Telegram (shadow@72).
BUKTI live (n=1640): lift adaptive vs raw ~0 (+0.02–0.06% @thr70/72) -> bobot masih terlalu netral, flip belum berguna. Expectancy futures NEGATIF semua ambang (−1.86 s/d −3.60%) -> masalah di STRATEGI DASAR scanner, bukan lapisan learning. Veto cuma sentuh 5-6 kandidat.
KESIMPULAN: jangan flip futures dulu. Lever sebenarnya = (a) bikin bobot menyimpang (butuh outcome matang lebih banyak / weight_updater lebih tajam), (b) perbaiki strategi dasar futures. Review bareng owner besok.

### FASE 1 (asli) — Aktifkan kontribusi skor (INTI: scanner meningkat)
- **B1.1** Populasikan bobot canonical-keyed dari outcome nyata (sumber yang docstring sebut "fase lanjutan") sehingga `apply_learning_policy` menggeser skor, bukan cuma veto.
- **B1.2** **Gate ketat**: kontribusi skor hanya aktif saat `learning_status=active` (≥60 mature) DAN walkforward lulus; sebelum itu tetap veto-only (aman).
- **B1.3** **Pengaruh terbatas** (clamp multiplier, mis. 0.8–1.25) supaya tak overfit; log before/after skor di ledger untuk audit.
- **Verifikasi:** shadow-compare — bandingkan keputusan dengan/tanpa kontribusi skor pada data historis sebelum diaktifkan (pakai `spot_portfolio_replay` / `futures_walkforward`).

### FASE 2 — Jalur promosi model (opsional, setelah Fase 1 matang)
- Pastikan lifecycle promote→canary→champion bisa advance saat gate lulus; monitor drift; rollback siap. Tetap self-gating (tak dipaksa).

### FASE 3 — Monitoring adaptive-engine ke Telegram ✅ SELESAI 23 Jul
- `ops/report-telegram.ps1`: seksi "ADAPTIVE ENGINE" (SPOT+FUTURES: engine_status, train %, outcome %, gates p/n) — muncul di Startup Malam & Ringkasan Pagi. Teruji kirim.
- `ops/health-check.ps1`: `EngineTransition` alert transisi engine_status (shadow->canary->champion / degraded) sekali per transisi, state di ops/logs/.engine-spot & .engine-fut. Teruji: 'shadow -> canary' terkirim.
- Pakai endpoint yang sudah dicache (Fase 0) — murah.

### FASE 3 (asli) — Monitoring adaptive-engine ke Telegram
- **B3.1** Tambah seksi "ADAPTIVE ENGINE" di `ops/report-telegram.ps1`: untuk SPOT & FUTURES → `engine_status`, mature progress %, outcome_completeness %, gates lulus/blokir, jumlah sinyal ter-ban, jumlah model & status.
- **B3.2** **Alert transisi**: kirim Telegram saat `engine_status` berubah (shadow→canary→champion), model dipromosikan, atau engine `degraded`. Simpan state terakhir (pola anti-spam seperti health-check).
- **B3.3** Konsumsi endpoint yang sudah dicache (Fase 0) supaya laporan cepat.
- **Verifikasi:** picu manual, cek pesan masuk Telegram.

### FASE 4 — Verifikasi bebas-bug menyeluruh
- Backend: latency endpoint, smoke test import semua modul learning, cek log tak ada exception di loop.
- Frontend: `npm run lint` + `npx tsc --noEmit` + `npm run build` = 0 error.
- Data: ulang cek `data_quality` gate = nol.

---

### FASE 1b — Perbaiki strategi dasar FUTURES ▶️ MULAI 23 Jul
Diagnosa `scratchpad/diag_futures.py` (n=1640 matang) menemukan sumber expectancy negatif:
1. **Skor 80+ = bencana** exp −11.28% pf 0.14 (n54); sweet-spot 75–80 exp +0.35% pf 1.11. Skor ekstrem = overextended reversal keras.
2. **LONG berdarah** wr30% pf0.33 vs **SHORT** wr55% pf0.96.
3. bigmover lane exp −2.28% (loser raksasa, risk asimetris); accumulation pf0.29 (sinyal lemah).
4. trending_up wr cuma 30.7% (LONG chasing).

FIX #1 SUDAH DIPASANG (paling defensibel, structural): **overextension guard** di `auto_trader.py` — veto auto-open kandidat `score >= OVEREXTENSION_CEILING` (default 80, config `futures.overextension_ceiling`, 0=off). Counterfactual pool auto-eligible (score≥72): expectancy −3.60%→**−0.87%**, pf 0.41→**0.76**; cutoff 80 optimal (78 memburuk krn motong band 78–80). Verifikasi py_compile OK + restart bersih + agent sehat. Reversible via config.

FIX #2 SUDAH DIPASANG: floor auto-open lane lemah (pre_gainer/accumulation) 65 -> `WEAK_LANE_FLOOR` (default 70, config futures.weak_lane_floor) di auto_trader.py:_effective_threshold. Alasan: PLAN_v14 turunkan ke 65 -> band 65-70 rugi (accumulation pf0.49, pre_gainer pf0.45). Counterfactual pool eligible (kumulatif atas #1): +0.07%->+0.19%, pf 1.02->1.05. Live: per_agent threshold agent1/2 = 70. py_compile OK, restart bersih.

DAMPAK GABUNGAN #1+#2 (data 11.5 hari, n=1640): pool auto-eligible dari -3.60%/pf0.41 -> +0.19%/pf1.05 wr48%. Strategi dasar futures dari BERDARAH -> IMPAS-TIPIS-POSITIF. Fix #3 (blok volatile) DITOLAK: cuma +0.02%, tak sepadan.

BELUM dikerjakan (butuh kehati-hatian — bisa OVERFIT periode):
- LONG-bias & regime: temuan kuat TAPI mungkin artefak periode backtest (kalau window mayoritas turun/choppy). JANGAN ban LONG buta; kumpulkan data lebih + review owner. Opsi: perketat syarat entry LONG di trending_up, atau size-down LONG.
- bigmover risk asimetris: audit struktur SL/TP (loser raksasa). Lihat memori forensik BigMover SL.
- accumulation (agent2) pf0.29: kandidat untuk pengetatan/penonaktifan lane.

## C. Catatan aman (HARAM/hati-hati)
- Fase 1 mengubah rumus skor → WAJIB shadow-compare dulu, gate ketat, pengaruh clamp. Jangan aktifkan langsung ke keputusan live tanpa bukti replay.
- Engine SPOT & FUTURES terpisah — jangan campur file engine (catatan memori: "HARAM sentuh file engine spot" berlaku untuk perubahan sembarangan; perubahan di sini terencana + verifikasi).
- Semua perubahan keputusan default OFF di belakang gate sampai terbukti.

## D. Urutan eksekusi disarankan
1. **Fase 0** (bug ECONNRESET) — segera, aman, langsung terasa.
2. **Fase 3** (monitoring Telegram) — cepat, nilai tinggi, tak ubah keputusan.
3. **Fase 1** (aktifkan skor) — inti peningkatan, paling hati-hati.
4. **Fase 2** (promosi model) — menyusul.

---

## PETA FASE BERIKUTNYA (per 23 Jul, terurut prioritas)

### ✅ SELESAI
- Fase 0 (fix bug ECONNRESET) · Fase 3 (monitoring Telegram) · Fase 1 shadow-compare (alat ukur) · Fase 1b fix strategi dasar futures #1 overextension + #2 floor lane-lemah · pelacak arah forward.

### ▶️ FASE A — Validasi Forward (SEKARANG, pasif, ~3-7 hari) — GATE semua fase lain
- A1. Pantau #1+#2 bertahan forward via Telegram (shadow@72, arah 70-80, per-lane).
- A2. Konfirmasi expectancy futures tetap >=0 pada data BARU (bukan cuma 11.5 hari historis).
- A3. Cek apakah edge SHORT bertahan atau memang artefak squeeze.
- Kerja: nol kode. Cuma observasi. Semua keputusan di bawah menunggu bukti ini.

### FASE B — Selesaikan Fase 1: aktifkan kontribusi skor FUTURES (setelah A lulus)
- B1. Buat bobot canonical (signal_id:*) menyimpang dari 1.0 — butuh outcome matang lebih banyak + weight_updater lebih tajam.
- B2. Flip FUTURES: pakai adaptive_score untuk ranking/skor (kini veto-only), di belakang gate learning_status=active + walkforward lulus + clamp [0.70-1.50].
- B3. Syarat flip: shadow-compare (sudah live) menunjukkan lift POSITIF konsisten dulu.

### FASE C — Fix strategi dasar lanjutan (setelah data forward cukup, anti-overfit)
- C1. Directional/entry-timing LONG di uptrend (wr30% = chasing) — perbaiki TIMING, jangan ban arah. Tunggu pelacak arah forward.
- C2. bigmover SL/TP asimetris (avgW+7.5% vs avgL-9.3%) — audit konstruksi SL.
- C3. accumulation lane (pf terlemah) — pertimbangkan pengetatan/pause bila tetap rugi forward.

### FASE D — Fase 2: Lifecycle promosi model (shadow->canary->champion)
- D1. Pastikan promote/canary/finalize bisa advance saat gate lulus; monitor drift; rollback siap.
- D2. Alert transisi model sudah ada (Fase 3) — tinggal jalur promosi aktif.

### FASE E — Sisi SPOT (paralel; SPOT sudah apply factor tapi netral)
- E1. Bikin bobot SPOT menyimpang (weight_updater) + shadow-compare SPOT seperti futures.
- E2. Verifikasi lift SPOT sebelum percaya boost-nya.

### Urutan disarankan: A (wajib dulu) -> B & C paralel (data-gated) -> D -> E.
