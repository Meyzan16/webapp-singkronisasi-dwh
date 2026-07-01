# PLAN_v4 — Deferred Items + Data-Driven Evolution

Tanggal: 2026-06-29  
**Review terakhir: 2026-07-01** — Phase 1 & Phase 5 sudah SELESAI + verified, dihapus dari dokumen ini. Yang tersisa hanya Phase 2–4 yang masih **menunggu prerequisite data** (`predictive_log` ≥ 7 hari; sistem live sejak ~2026-06-29).

Kelanjutan PLAN_v2 + PLAN_v3. Item di sini adalah deferred yang belum bisa dieksekusi sampai runtime data cukup.

## Status Prerequisite (per 2026-07-01)

| Kondisi | Status | Cek cara |
|---|---|---|
| predictive_log ≥ 7 hari data | ❌ ~2 hari — cek ulang **2026-07-08** | `GET /predictive/recent?limit=10` → `scanned_at` tertua |
| predictive_log ≥ 20 resolved entries per agent | ❌ belum cukup | `GET /predictive/hit_rate` → `resolved_count` |
| hit_rate_4h stabil (< 5% delta antar 2 run) | ❌ belum | Run `/predictive/hit_rate` dua hari berturut lalu bandingkan |

**Catatan (sudah ada, JANGAN dianggap menggantikan item di bawah):**
- `agents/learning/monthly_calibration.py` — adjust threshold bulanan by hit rate. Beda dari P2.2 (per-regime/direction, berbasis predictive_log).
- `agents/learning/weekly_backtest.py` — backtest threshold by `big_mover_log`. Beda dari P2.1 (signal-level, berbasis predictive_log).
- `_early_breakout_confirmed` flag di agent3.py (~line 296) — internal branch D2.4. Bagian dari P3.3, tapi data-driven calibration (P3.3 proper) masih pending.

---

## PHASE 2 — Feedback Loop Expansion ⏳ PENDING (butuh 2026-07-08+)

**Prerequisite**: `predictive_log` terisi ≥ 7 hari, ≥ 20 resolved entries per agent.

### P2.1 — Weekly signal hit rate review job (D7.1)

**Tujuan**: Identifikasi sinyal yang hit rate < 25% → turunkan max_pts di scoring secara otomatis.

- [ ] Buat `agents/learning/weekly_signal_review.py`:
  - Trigger: Setiap Senin jam 00:10 UTC (cek via scheduler: `weekday==0 and hour==0 and minute<15`).
  - Query `predictive_log` resolved 7 hari terakhir.
  - Hitung per-signal hit rate dari `signals_json` field.
  - Sinyal dengan `hit_rate_4h < 25%` dan `n >= 10`: log warning + simpan ke `AgentSignalWeight` dengan weight turun 0.1 (floor 0.7).
  - Sinyal dengan `hit_rate_4h > 60%` dan `n >= 10`: naikkan weight 0.1 (cap 1.5).
- [ ] Wire ke scheduler: panggil di `run_futures_loop` setiap Senin pagi.
- [ ] Endpoint `GET /predictive/signal_review` → return adjustments yang dibuat minggu ini.

### P2.2 — Regime modifier re-tuning (D7.3)

**Tujuan**: Tune `regime_modifier` di agent1/agent2/agent3 berdasarkan data per-regime hit rate dari `predictive_log`.

- [ ] Query `predictive_log` group by `(agent, regime, direction)`.
- [ ] Hitung hit_rate_4h per kombinasi.
- [ ] Bandingkan: apakah `trending_up + LONG` memang hit rate lebih tinggi vs rata-rata?
- [ ] Jika `trending_up + LONG` hit rate > avg + 10%: konfirmasi modifier +5 pts sudah tepat. Jika tidak signifikan: turunkan ke +3.
- [ ] Implementasi: simpan regime modifier ke `AgentSignalWeight` dengan `signal_key="_regime_{regime}_{direction}_"` (special key pattern). Weight = multiplier pts (default 5.0).
- [ ] Agents baca via: `weight_updater.get_weight_cache(agent)["_regime_trending_up_LONG_"]` → gunakan sebagai modifier pts (fallback ke default jika belum ada data).

### P2.3 — Weight updater secondary loop dari predictive_log (D4.4)

**Tujuan**: Signal yang terbukti predictive (tinggi hit_rate) mendapat boost weight, walau trade-nya belum pernah di-open. Saat ini weight_updater hanya belajar dari closed trades.

**Design** (perlu careful agar tidak conflict):
- [ ] Secondary loop di `weight_updater.update_weights()`: setelah update dari trades, tambahkan adjustment kecil dari predictive hit rates.
- [ ] Formula: `predictive_adjustment = (hit_rate_4h - 0.50) × 0.05` → range ±0.025 per update cycle.
- [ ] Gunakan **decayed blend**: `new_w = 0.85 × trade_w + 0.15 × predictive_adj_w` agar tidak override trade signal.
- [ ] Gate: hanya apply jika signal punya `n_predictive >= 20` (cukup sample).
- [ ] Floor/cap: tetap 0.7–1.5 (sama dengan trade-based).

**Catatan risiko**: Predictive hit rate bisa misleading kalau universe bias (misal semua coin scanned saat bull market → semua hit LONG). Perlu normalize by baseline hit rate. Implement conservatively dulu.

**Gate review P2**: weight_updater mulai bergeser dari neutral lebih cepat. Distribusi weights tidak lagi 0.95–1.05 flat. Check `/signals` page Growth tab — harus visible trajectory.

---

## PHASE 3 — Early Breakout Agent Decision ⏳ PENDING (butuh 2026-07-15+)

**Prerequisite**: D5.1 spike analysis — predictive_log harus punya 14+ hari data untuk `change_24h` 3–7% range di agent3.

### P3.1 — Spike analysis: early breakout hit rate (D5.1)

- [ ] Query manual atau endpoint: `GET /predictive/hit_rate?agent=futures_agent3&hours=336` (14 hari).
- [ ] Filter predictions di `change_24h` range 3–7% (dari `signals_json` atau tambah `change_24h` kolom query).
- [ ] Hitung: berapa % coin dengan `_early_breakout_confirmed = True` → jadi big mover (>10% in 24h)?
- [ ] **Decision gate**:
  - hit_rate_4h > 40% dalam sample ≥ 30 → proceed ke P3.2 (new agent)
  - hit_rate_4h ≤ 40% → P3.3 (tuning branch saja, skip new agent)

### P3.2 — New agent: `agent_early_breakout.py` (D5.2) — jika hit rate > 40%

- [ ] Buat `agents/futures/agent_early_breakout.py`:
  - `setup_type = "early_breakout"`
  - Universe: coin dengan `3.0 <= change_24h <= 8.0`
  - Signals: breakout fresh + vol_z >= 1.5 + OI acceleration + 15m momentum
  - `MIN_SCORE` adaptif via weight_updater (start 60)
  - Leverage cap: max 5x (posisi early = volatile, perlu headroom)
  - Stagnant timeout: 12h (bukan 48h — early breakout harus bergerak cepat)
- [ ] Register di `scheduler.py` scan loop.
- [ ] Tambah quota di `auto_trader.LANE_QUOTAS["early_breakout"] = 1`.

### P3.3 — Tuning early breakout branch (D5.3 enhancement)

Jika hit rate ≤ 40% → tidak perlu agent baru, tapi branch existing di agent3 perlu di-tune:
- [ ] Review threshold: apakah `oi_chg >= 1.0` terlalu longgar? Naikkan ke 2.0?
- [ ] Review breakout pct threshold: `bo_pct >= 0.3` — apakah false positives tinggi?
- [ ] Adjust berdasarkan data actual.

**Gate review P3**: Kalau P3.2 dikerjakan — early_breakout lane mulai trades. Monitor WR rolling 7d. Jika WR < 30% setelah 20 trades → matikan lane.

---

## PHASE 4 — UI Enhancement ⏳ PENDING (butuh 2026-07-08+)

**Prerequisite**: predictive_log ≥ 7 hari, hit_rate endpoint mengembalikan data bermakna.

### P4.1 — Probability badge di Pre-Move Radar (D6.2)

**Tujuan**: Tiap coin card di Pre-Move Radar menampilkan "hit rate prediktif" sebagai badge.

- [ ] Fetch `GET /predictive/hit_rate` saat Radar tab dibuka.
- [ ] Build lookup: `{ "futures_agent1:LONG": { hit_rate_4h: 42.3, ... } }`.
- [ ] Per coin card: tampilkan badge `🎯 42% (4h)` kalau ada match, atau `–` kalau belum ada data.
- [ ] Color code: > 50% → hijau, 35–50% → kuning, < 35% → merah.
- [ ] Tooltip: "Dari X predictions, Y hit ±1.5% dalam 4h".

### P4.2 — "Detected at" badge di Top Gainers/Losers (D6.3)

**Tujuan**: Kalau coin yang sekarang jadi Big Mover sudah terdeteksi di predictive_log sebelum bergerak → tampilkan badge `🎯 predicted T-Xh`.

- [ ] Backend: endpoint `GET /predictive/pre_detection?symbol=BTCUSDT` → cari entry di predictive_log sebelum coin naik > 10%.
  - Query: entry dengan `scanned_at < (now - 10800)` dan `symbol = X` dan `score >= 60`.
  - Return: earliest detection timestamp + score saat itu.
- [ ] Frontend: di Top Gainers/Losers panel, setelah data load, parallel fetch `/predictive/pre_detection?symbol=X` untuk setiap big mover.
- [ ] Display: badge `🎯 detected T-6h` kalau ada, atau nothing kalau tidak.

**Gate review P4**: UI Pre-Move Radar menampilkan probability badge untuk setidaknya 20% coin (butuh data cukup). Detected-at badge muncul untuk ≥ 1 big mover.

---

## Timeline & Dependencies (sisa)

```
2026-07-08+  P2 (hari ke-7)  — P2.1 Weekly job + P2.2 Regime re-tune + P2.3 Predictive→weights
             P4 (paralel)     — P4.1 Probability badge + P4.2 Detected-at badge
2026-07-15+  P3 (hari ke-14)  — P3.1 Spike analysis → P3.2 ATAU P3.3 (conditional)
```

## Keputusan Terkunci (relevan untuk phase tersisa)

| Pertanyaan | Keputusan |
|---|---|
| Agent baru `agent_early_breakout.py`? | **Conditional** — hanya buat jika D5.1 spike menunjukkan hit rate > 40% dalam ≥ 30 samples. Default: tuning branch saja. |
| Predictive → weight blend ratio? | **0.85 × trade + 0.15 × predictive** (konservatif). Eskalasi ke 0.7/0.3 hanya jika predictive terbukti uncorrelated dengan trade signal (additive value). |
| Weekly signal review apply direction? | **Lower weight only** saat pertama berjalan (conservative). Setelah 4 minggu data: enable raise juga. |
