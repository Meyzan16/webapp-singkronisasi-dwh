# PLAN — Signal Repair Live: Agen Perbaikan + Progress (FUTURES)

Tanggal: 2026-07-17 · Status: **DRAFT — analisa selesai, implementasi belum**
Lanjutan: engine 10X (F0–F6, selesai & takeout 16 Jul) + PLAN_UX_PIPELINE_SIGNALS
(P4 tab 🔧 Perbaikan + P6 tab 💡 Saran Engine — selesai, keduanya di-takeout di
commit ini). Guardrail tetap: **nol file engine SPOT disentuh**.

## 1. Analisa — apa yang sudah ada vs yang diminta owner

**Sudah ada (perbaikan otomatis, LIVE):** bobot trade-based per cycle (step-cap
0.1, bounds 0.7–1.5), learning ban (weight<0.8 n≥10 → veto), blacklist koin 3-SL,
lane WR-pause & consec-SL pause, weekly signal review (predictive → bobot, tiap
SENIN, lower-only s/d 7 Agu), predictive blend 0.85/0.15 (refresh 15 mnt),
challenger model shadow→canary (self-gating). UI: tab 🔧 Perbaikan (state bobot
naik/turun sekarang) + 💡 Saran Engine (`GET /signals/recommendations`, read-only)
— keduanya subtab di DALAM Analysis.

**Gap vs permintaan:**
1. Perbaikan predictive **menunggu hari Senin** — owner minta AGEN yang memperbaiki
   LIVE dari data predictive.
2. Tidak ada **repair log persisten + verifikasi before/after** — tab Perbaikan
   menampilkan *keadaan sekarang*, bukan *progress* (deteksi → aksi → terbukti
   membaik/tidak). Aksi bobot/ban terjadi senyap tanpa jejak "kenapa".
3. 🔧 Perbaikan & 💡 Saran Engine terkubur di Analysis — owner minta jadi
   **seksi sendiri di sebelah Analysis**.
4. Saran Engine read-only — tidak ada tombol Terapkan untuk saran yang aman
   di-otomasi (knob agent_config / aksi bobot).

## 2. Fase implementasi

### R1 — Repair ledger (`futures_repair_actions`)
Model baru: id, detected_at, source (`predictive_agent|weekly_review|learning_ban|
lane_pause|suggestion`), target_key (signal_id/lane/koin), issue
(`hit_rate_low|wr_low|weight_extreme|...`), evidence_json (n, hit_rate, wr,
before_weight — bukti saat deteksi), action (`weight_down|weight_up|ban|unban|
config_change|suggest_only`), applied_at, before/after metrics, status
(`applied|suggested|verified_improved|verified_no_change|reverted|dismissed`).
Penulis: semua mekanisme MATERIAL (bukan drift 0.01 per-cycle): aksi agen R2,
weekly review, transisi ban/unban, pause lane, saran yang di-approve.

### R2 — Predictive Repair Agent (permintaan #2) — `agents/learning/predictive_repair.py`
Loop live (scheduler futures, tiap ~30 mnt; bukan menunggu Senin):
- Sumber: futures_decision_events (outcome 4h, era ≥ 1783698144) + predictive_log
  per canonical signal_id.
- n≥15 & hit_rate_4h < 25% → **weight −0.10 langsung** (floor 0.70) + catat R1.
- hit_rate_4h > 60% → +0.10 HANYA setelah 7 Agu (hormati lock lower-only).
- Guard anti-osilasi: max 1 aksi per key per 24 jam (cooldown di ledger),
  step-cap tetap, TIDAK menyentuh rumus skor dasar, veto-only tetap berlaku.
- Weekly review Senin tetap jalan (jaring pengaman lebar); agen ini reflex cepatnya.

### R3 — Verifier progress (jantung "progress sinyal perbaikan")
Pass tiap ~6 jam: untuk aksi `applied` berumur ≥24h, hitung metrik SESUDAH
(hit-rate/WR pada sampel pasca-applied_at) vs evidence SEBELUM →
`verified_improved` / `verified_no_change`; memburuk signifikan (> ambang) →
**auto-revert satu step** + status `reverted` + cooldown revert 48h.
Inilah yang membuat tab Progress bermakna: setiap perbaikan terbukti atau dibatalkan.

### R4 — API
- `GET /signals/repairs`: funnel (deteksi→aksi→verifikasi, angka live), log aksi
  (before→after), status agen (last run, aksi 24h), saran pending.
- `POST /signals/recommendations/apply`: eksekusi saran yang AMAN di-otomasi
  (knob agent_config via API existing + aksi bobot bounded) → tercatat di R1
  source=`suggestion`. Saran level kode (ubah poin scoring/universe) TETAP
  manual — tidak pernah auto-apply.

### R5 — UI: seksi level-1 baru "🔧 Improve" (permintaan #1)
Di sebelah Analysis (seksi ke-5): subtab **📈 Progress** (funnel + tabel repair
log + badge improved/no-change/reverted, default), **🔧 Perbaikan Live**
(pindahan dari Analysis), **💡 Saran Engine** (pindahan + tombol Terapkan utk
saran auto-applicable). Analysis kembali murni diagnostik (regime/formulas/
rejections/predictive). Panduan tutorial → 5 seksi.

## 3. Guardrails (terkunci)
- Semua aksi bounded: weight 0.70–1.50, step 0.10, cooldown 24h/key, revert 48h.
- Era filter 1783698144 wajib di semua deteksi.
- Veto-only: perbaikan tak pernah mempromosikan kandidat di bawah ambang.
- Repair agent = FUTURES only; saran SPOT tetap read-only (nol file engine SPOT).
- Tidak ada lagi perbaikan senyap: aksi material tanpa baris R1 = bug.

## 4. Urutan
R1 → R2 → R3 (inti nilai) → R4 → R5 UI. R2 berguna sejak hari pertama;
R3 mulai bermakna 24 jam setelah aksi pertama.
