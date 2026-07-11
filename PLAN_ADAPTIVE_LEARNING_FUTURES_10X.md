# PLAN — Adaptive Learning Engine FUTURES 10X

Tanggal: 2026-07-11 · Status: **DRAFT — analisa selesai, implementasi belum**
Pola: MIRROR dari SPOT engine (PLAN_ADAPTIVE_SIGNAL_WEIGHTING_SPOT_10X) yang sudah
diimplementasi. **Guardrail keras: TIDAK menyentuh satu pun file engine SPOT** —
futures mendapat modul & tabel paralel sendiri.

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

### F1 — Decision ledger + outcome tracker
- Model `FuturesDecisionEvent` (`futures_decision_events`) — mirror kolom
  SpotDecisionEvent + `agent`, `direction`, `lane`, `leverage`, `cost_floor_pct`;
  horizon pnl_30m/1h/4h/24h; UniqueConstraint decision_key.
- `agents/futures/decision_ledger.py`: build rows deterministik dari hasil scan +
  keputusan auto_trader (reason codes nyata: `opened`, `cost_floor_skip`,
  `direction_cap`, `lane_quota`, `funding_skip`, `profit_lock_skip`,
  `breadth_fade_skip`, `bm_daily_stop`, `below_auto_threshold`, `sizing_blocked`,
  `daily_gate_blocked`); feature_snapshot_json numerik.
- `agents/futures/outcome_tracker.py`: isi harga horizon dari klines (pola
  backfill R0a yang sudah exact-horizon) + link outcome trade nyata
  (`backfill_closed_futures_trades`).
- Wiring scheduler futures (pola scheduler spot baris 526/543): log tiap cycle,
  outcome pass tiap ~10 cycle. Prune ledger > 45 hari.

### F2 — Integrasi policy ke scan & auto_trader
- Keempat `scan_symbol`: `apply_learning_policy` menempelkan adaptive_score +
  probability + lower bound + learning_keys (pakai weight cache existing — TIDAK
  mengubah rumus skor dasar).
- `auto_trader`: veto `banned_by_learning`; `learning_status`
  (warming/active) di store + scan result.
- Setelah gates F5 lolos (BUKAN sebelumnya): Wilson lower bound boleh menjadi
  input sizing (naikkan/turunkan dalam batas cap yang ada).

### F3 — Challenger model + registry
- `agents/learning/futures_adaptive_model.py` (pola spot_adaptive_model):
  logistic dependency-light + Platt + ablation; label utama = profitable-net di
  horizon 4h (trade nyata diprioritaskan, counterfactual sebagai augmentasi
  TERPISAH — jangan campur tanpa flag).
- Model `FuturesModelVersion` (`futures_model_versions`) — champion/shadow/
  last-known-good. Training gate: ≥60 mature era-H, ≥20 OOS kronologis.

### F4 — Walk-forward + cost stress
- `agents/learning/futures_walkforward.py`: replay ledger kronologis; portfolio
  replay net; **cost stress 1.5× WAJIB mencakup funding**, bukan hanya fee+slip.

### F5 — Shadow → canary → rollback
- Shadow: model menempelkan probability ke kandidat tanpa memengaruhi keputusan.
- Canary: ≥20 outcome pick-model vs baseline; PF ≥ 1.5, DD ≤ 10%; drift monitor
  auto-rollback ke last-known-good.

### F6 — UI Signal Performance (permintaan eksplisit user)
Konsep per subtab (page.tsx — lihat §5 koordinasi):
- **Adaptive**: DUA panel engine sejajar — SPOT (endpoint existing, read-only)
  dan FUTURES (endpoint BARU `/signals/adaptive-engine/futures`): status
  warming/active, progres acceptance gates (bar per gate), ledger stats
  (decisions/outcomes/completeness), model registry, tombol lihat ablation.
- **Overview**: diagram alur singkat "Keputusan → Ledger → Outcome → Bobot/Model
  → Gate → Sizing" + scorecard ringkas kedua market (day-WR, expectancy net,
  churn) — supaya konsepnya terbaca dalam 10 detik.
- **Spot**: tidak diubah strukturnya (milik engine SPOT) — hanya dirapikan
  konsisten dgn layout baru.
- **Futures**: tabel bobot existing + panel baru: sumber bobot per sinyal
  (trade / weekly-review / predictive-blend / model-shadow), near-miss era-H,
  hasil weekly signal review terakhir (endpoint `/predictive/signal_review`).
- API: HANYA menambah endpoint baru di signals.py — endpoint SPOT existing tidak
  disentuh.

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
