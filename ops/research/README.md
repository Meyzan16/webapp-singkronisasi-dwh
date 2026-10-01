# ops/research — analisis edge kandidat futures (PLAN-OKT-2026)

Semua skrip bekerja di satu folder kerja `<dir>` (scratch), bukan di repo.

1. Ekspor kandidat matang agen tunggal → `<dir>/cand.tsv`:
   `psql -At -F $'\t' -c "select scan_ts, symbol, direction, coalesce(cost_floor_pct,0.3), pnl_1h_pct, pnl_4h_pct, pnl_24h_pct, feature_snapshot_json from futures_decision_events where agent='futures_agentic' and pnl_4h_pct is not null order by scan_ts"`
2. `python candidate_edge.py <dir>/cand.tsv` — tersil fitur scanner, latih 60% / uji 40% kronologis.
3. `backend/.venv/Scripts/python.exe ops/research/fetch_ratios.py <dir>` (dari repo root) — histori 1j
   rasio taker, long/short trader besar & semua akun, basis (Binance simpan ±30 hari).
4. `cd <dir> && python <repo>/ops/research/ratio_edge.py` — tersil fitur rasio, tanpa lookahead
   (hanya periode 1j yang sudah selesai sebelum scan).

Kriteria irisan "ber-edge": net 4j > +0,25% di latih DAN uji, n ≥ 20/15.
