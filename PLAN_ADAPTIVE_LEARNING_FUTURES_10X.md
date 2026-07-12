# PLAN — Adaptive Learning Engine FUTURES 10X

Tanggal: 2026-07-11 · Status: **SEMUA FASE KODE (F0–F6) SELESAI + LIVE** — tersisa
acceptance gates (self-gating: menunggu ledger matang; model shadow otomatis
promosi hanya bila lolos, TANPA menyentuh keputusan sampai champion).
Pola: MIRROR dari SPOT engine (PLAN_ADAPTIVE_SIGNAL_WEIGHTING_SPOT_10X) yang sudah
diimplementasi. **Guardrail keras: TIDAK menyentuh satu pun file engine SPOT** —
futures mendapat modul & tabel paralel sendiri (terverifikasi: suite SPOT tetap hijau).

Commit F0 ad389e8 · F1 56b159c · F2 3411478 · F3 dd1a072 · F4 ac7babc ·
F6 d89a6c4 (+ basis SPOT UI 646a216) · F5 di commit ini.

Terkait: SCHEDULE_FUTURES.md (jadwal gate live — engine ini adalah mesin
pertumbuhannya, bukan pengganti jadwal).

---

## 1. Analisa gap — komponen SPOT engine vs kondisi FUTURES sekarang

| Komponen (pola SPOT) | SPOT (sudah jadi) | FUTURES sekarang | Gap |
|---|---|---|---|
| Pure policy module (no-DB, testable) | `learning_policy.py`: stable signal IDs, deterministic_weight, Wilson bound, apply_learning_policy (veto-only) | Logika tersebar di `weight_updater` + inline di 4 agent; key sinyal = regex dari copy UI | **F0** |
| Stable signal IDs | `canonical_signal_key` registry — identitas fitur TIDAK ikut berubah saat copy/emoji/angka UI berubah | `normalize_signal_key` regex — ganti teks sinyal = bobot ter-reset diam-diam | **F0** |
| Decision ledger immutable | `spot_decision_events`: SEMUA kandidat + veto + reason code + feature snapshot + outcome multi-horizon, decision_key deterministik (retry-safe) | `predictive_log` (top-10/agent, sinyal berupa teks, tanpa feature vector, tanpa reason) + `rejection_log` (tanpa outcome) — **tidak ada dataset keputusan→outcome yang utuh** | **F1** |
| Probability di keputusan | estimated_win_probability (Laplace) + Wilson lower bound per kandidat | Tidak ada — keputusan open murni skor | **F2** |
| Learning boleh VETO auto-open | `banned_by_learning` per signal-key | Hanya blacklist per-coin (3 SL beruntun) | **F2** |
| Challenger model terkalibrasi | `spot_adaptive_model.py`: logistic + Platt, chronological 60/20/20, ablation, metrics net-cost | Tidak ada | **F3** |
| Model registry + rollback | `spot_model_versions`: champion/shadow/last-known-good | Tidak ada | **F3** |
| Walk-forward + cost stress | `spot_walkforward.py` (replay; stress 1.5×) | `weekly_backtest` level threshold saja | **F4** |
| Shadow/canary gate | status shadow, 20 canary outcomes, auto-rollback drift | Tidak ada | **F5** |
| UI/API engine state | `/signals/adaptive-engine` + subtab adaptive (SPOT only) | Subtab futures hanya tabel bobot | **F6** |

Yang futures SUDAH punya dan DIPERTAHANKAN (engine baru = lapisan di atasnya,
bukan pengganti): weight_updater trade-based (decay/Laplace/step-cap/regime),
adaptive thresholds, cross-agent blend, weekly signal review + predictive blend
(item C), coin blacklist/bonus, rejection near-miss log.

## 2. Kekhususan FUTURES yang mengubah desain (bukan copy-paste buta)

1. **Label = NET true-cost v16** — pnl label dari trade nyata sudah memotong
   fee+slippage+funding; label counterfactual (kandidat tak dibuka) memakai
   simulasi bracket dgn `cost_floor_pct` kandidat. SPOT hanya memakai
   `EXECUTION_COST_PCT` flat.
2. **4 lane universe eksklusif** (item H) — sampel per lane kecil → **SATU model
   futures global** dengan fitur lane (one-hot) + direction, BUKAN 4 model.
3. **LONG+SHORT** — label & fitur direction-aware (pnl futures sudah direction-aware).
4. **Horizon lebih pendek** — momentum/BM hidup 1-3 jam → horizon outcome
   30m/1h/4h/24h (SPOT: 1h/4h/24h/3d/7d).
5. **Volume keputusan tinggi** — scan tiap 2 menit × 4 agent → ledger meledak.
   Dedup window 15 menit per (symbol, agent, direction) + hanya rekam kandidat
   ber-skor ≥ min lane + ringkasan hard-reject per alasan (bukan per baris).
6. **Era anchor 1783698144** — ledger mulai kosong (era-H); tidak ada backfill
   dari data lama (scoring lama ≠ sistem sekarang).
7. **Fitur on-chain sudah tersedia gratis** di dict kandidat: funding_rate,
   oi_change, atr_pct, change_24h, liq proxy, breadth, regime, leverage,
   cost_floor_pct, score — feature snapshot tinggal memetik, tanpa fetch baru.

## 3. Fase implementasi

### F0 — ✅ SELESAI 2026-07-11 — `agents/futures/learning_policy.py` + tests
Registry 70+ rule canonical_signal_key (copy persis 4 agent pasca-H, first-match-wins,
konflik urutan teruji: negatif-ekstrem/relaxed-overbought/dual-TF/Δ24h-vs-momentum/
early-breakout-vs-OI/coiling-vs-bb) · dual-read fallback identik
weight_updater.normalize_signal_key (teruji) · deterministic_weight + Wilson +
apply_learning_policy veto-only (field `score` TIDAK ditimpa; learning_auto_veto/
learning_auto_eligible terpisah — konsumsi diputuskan F2) ·
`backend/tests/test_futures_learning_policy.py` 21 test lulus (suite spot 41 +
TA 29 tetap hijau; nol file SPOT tersentuh).

### F1 — ✅ SELESAI 2026-07-11 — Decision ledger + outcome tracker
Model `FuturesDecisionEvent` (horizon 30m/1h/4h/24h, uq decision_key, kolom
realized NET) · `decision_ledger.py` (rows deterministik retry-safe, dedup 15 mnt
kecuali `opened` selalu ditulis, snapshot numerik + breadth) · auto_trader
di-instrumentasi 22 titik keputusan (`_dec()` → reason codes nyata: opened /
below_auto_threshold / dedup_lost / volatile_regime_skip / already_open /
sl_cooldown / profit_lock_skip / direction_cap / bm_daily_budget /
bm_daily_sl_stop / breadth_fade_skip / funding_hard_skip / bm_lane_full /
lane_quota_full / lane_paused / funding_flip / cost_floor_skip / sizing_blocked /
min_notional_skip / risk_gate_blocked / daily_gate_blocked /
consec_sl_global_pause) · `outcome_tracker.py` (label forward exact-horizon
pola R0a + `backfill_closed_futures_trades` realized NET + prune 45 hari) ·
wiring scheduler (ledger tiap cycle pasca-auto_open; outcome pass %10==5,
offset dari backfill BM) · 8 test pure lulus (total suite futures 29).

### F2 — ✅ SELESAI 2026-07-11 — Integrasi policy ke scan & auto_trader
`learning_loader.py` (mirror `_load_learning_weights`/`_apply_lane_learning` SPOT):
baca `agent_signal_weights` (4 agent + cross, blend 0.70/0.30), ekspos di bawah
`signal:` fallback ns, ban weight<0.8 & n≥10, status warming/active/degraded dari
kematangan ledger (≥60 pnl_24h). Diterapkan per-lane di `_run_scan` SETELAH top-N
(dict sama mengalir ke auto_open + ledger + UI) — field `score` dasar TIDAK diubah.
auto_trader: veto `learning_ban` (hard, selalu) + `learning_veto` (lunak,
adaptive<ambang, HANYA saat status active — warming tak menahan trade). Status ke
store (`set/get_learning_status`) + scan result + ledger row. Live-verified: loader
memuat 28 bobot nyata, status warming, 0 error. 5 test loader → suite 84 lulus.
Catatan cakupan didokumentasikan di learning_loader.py (bobot legacy hanya
ter-apply ke sinyal non-canonical sampai ada sumber weight canonical-keyed).
- **Sizing**: Wilson lower bound → input sizing HANYA setelah gate F5 (belum).

### F3 — ✅ SELESAI 2026-07-11 — Challenger model + registry
`agents/learning/futures_adaptive_model.py` (mirror spot_adaptive_model, dependency-
light logistic + Platt + ablation): label = profitable-NET horizon 4h (pnl_4h −
cost_floor per-sampel true-cost); fitur = snapshot F1 minus field turunan learning
& biaya (anti-bocor); self-gate ≥60 sampel 4h + step +50 evidence baru; model baru
selalu `shadow`. Model `FuturesModelVersion` (`futures_model_versions`,
shadow/canary/champion/retired). Endpoint F6 + scheduler (train %100==50) di-wire.
**Live-verified**: dilatih pada 352 sampel nyata → shadow, brier 0.39 > baseline
0.27 → `promotion_eligible=False` (gate offline BENAR menolak model awal yang belum
bagus; tetap shadow, tak menyentuh keputusan). UI Model Registry render. 5 test
pure (gate data, belajar sinyal + ablation, kalibrasi bounds, kronologis) → suite 60.

### F4 — ✅ SELESAI 2026-07-11 — Walk-forward + cost stress
`agents/learning/futures_walkforward.py` (mirror spot_walkforward): purged
chronological (boundary 60%, embargo 4h = horizon), tune threshold di train,
lapor OOS + **cost-stress 1.5×**. Biaya per-sampel true-cost (fee+2×slip+funding
via cost_floor) → 1.5× otomatis men-scale funding. promotion_eligible menuntut
OOS PF≥1.5 DAN tetap expectancy>0 & PF≥1.5 pada biaya 1.5×. Endpoint F6 (+gate
walkforward_passed, phase F4=true) + scheduler (jalan setelah train) + panel UI
(best threshold / OOS exp·PF / stress-exp / verdict). **Live**: pada ledger 4h
nyata → best_thr 55, OOS exp −9.18%, stress −9.34%, promotion_eligible=False
(gate BENAR menolak; data awal negatif). 5 test (biaya per-sampel, stress
mengurangi exp, gate data, embargo split, stress membunuh kelayakan) → suite 44.

### F5 — ✅ SELESAI 2026-07-11 — Shadow → canary → champion + rollback + drift
Lifecycle lengkap di `futures_adaptive_model.py` (mirror SPOT): `score_shadow_
candidates` (tempel shadow_probability ke kandidat di scan, disimpan di snapshot,
TANPA memengaruhi keputusan — shadow_probability di-exclude dari fitur training),
`start_canary` (shadow→canary hanya bila lolos gate OFFLINE F3 + WALK-FORWARD F4),
`evaluate_canary` (metrik dari event ber-shadow_prob≥0.55 + outcome NET 4h),
`finalize_canary` (≥20 outcome, exp>0, PF≥1.5, DD≤10% → champion; champion lama
retired), `rollback_champion` (→ last-known-good), `monitor_champion_drift`
(brier>0.30 / exp≤0 → auto-rollback), `advance_lifecycle` orchestrator self-gating.
Wiring: scheduler (shadow-score sebelum ledger; advance+drift setelah train),
endpoint (gate canary_active/champion_exists, engine_status canary/champion, phase
F5=true), panel (badge Canary). **Live**: shadow model eligible=False →
start_canary BLOCKED offline_gate_failed, advance noop, drift no_champion,
shadow_probability tertempel (rantai keamanan lengkap: shadow amati → gate tolak →
nol efek keputusan). 6 test lifecycle → suite 71 lulus, tsc bersih.

### F6 — ✅ SELESAI 2026-07-11 — UI Signal Performance
Basis SPOT UI (endpoint + subtabs) di-commit sendiri dulu (`646a216`) atas
persetujuan owner, lalu F6 futures ditambah additive (commit terpisah):
- Endpoint BARU `/signals/adaptive-engine/futures` (signals.py, endpoint SPOT
  tak disentuh): engine_status collecting/ready_to_train/degraded +
  learning_status runtime warming/active, ledger stats (total/opened/actions/
  outcomes/reasons/realized_linked/completeness/quality), progres training /60,
  phases F0-F5, acceptance gates. Live: 457 keputusan, 8 opened, quality clean.
- `FuturesAdaptiveEnginePanel` (page.tsx): kartu stat, chip progres fase F0-F5,
  bar training evidence, acceptance gates, "kenapa tidak dibuka (top reasons)".
  Dirender di: **Adaptive** (sejajar bawah panel SPOT), **Overview** (dua panel
  compact berdampingan — konsep pipeline dua market), **Futures** (di atas tabel
  bobot). Verifikasi live: render benar dgn data nyata, 0 console error, tsc bersih.

## 4. Acceptance gates (identik pola SPOT — model tak boleh memengaruhi sizing sebelum lolos)

1. **Data**: ≥60 mature samples era-H (snapshot + outcome 24h), ≥20 OOS,
   completeness ≥99%, nol duplicate/future-ts/snapshot-kosong/leakage.
2. **Promotion**: challenger > baseline empiris (kronologis), Brier lebih rendah,
   expectancy OOS positif NET (fee+slip+funding), PF ≥ 1.5, tahan stress 1.5×,
   ablation tanpa brittle dependency.
3. **Canary**: shadow ≥20 outcomes, expectancy positif, PF ≥ 1.5, DD ≤ 10%,
   tanpa rollback drift.
4. **Ops**: pytest penuh lulus, scan runtime learning `active`, registry punya
   champion + rollback target, diagnostics 0 anomali.

## 5. Guardrails & koordinasi

- **HARAM diedit** (milik engine SPOT): `agents/opportunity/learning_policy.py`,
  `decision_ledger.py`, `outcome_tracker.py`, `onchain_provider.py`,
  `agents/learning/spot_adaptive_model.py`, `spot_walkforward.py`, model
  `spot_decision_event.py`/`spot_model_version.py`, endpoint spot di signals.py.
- **⚠ KONFLIK AKTIF**: `frontend/src/features/signals/page.tsx` dan
  `backend/app/api/v1/signals.py` sedang DIMODIFIKASI sesi SPOT (uncommitted).
  F6 dikerjakan HANYA setelah sesi itu commit; perubahan bersifat additive.
- Semua query training/kalibrasi filter era `>= 1783698144`.
- Engine = lapisan di atas learning futures existing; weekly review + predictive
  blend (item C) tetap jalan — model menggantikannya HANYA setelah terbukti
  lebih baik di canary (keputusan eksplisit, bukan otomatis).

## 6. Urutan & estimasi

| # | Fase | Effort | Prasyarat |
|---|---|---|---|
| 1 | F0 policy + tests | kecil | — |
| 2 | F1 ledger + outcome | sedang | F0 |
| 3 | F2 integrasi scan/auto_trader | kecil | F0 |
| 4 | F6 UI | sedang | sesi SPOT commit page.tsx/signals.py |
| 5 | F3 model + registry | sedang | F1 jalan ≥3-5 hari (60 mature) |
| 6 | F4 walk-forward | kecil | F3 |
| 7 | F5 shadow/canary | sedang | F3+F4 |

F0-F2+F6 bisa dikerjakan segera; F3-F5 menunggu ledger matang (self-gating,
sama seperti SPOT: "training diblokir sampai minimum sample tercapai").
