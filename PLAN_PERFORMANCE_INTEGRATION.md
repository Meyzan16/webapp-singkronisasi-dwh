# PLAN â€” Signal Performance INTEGRATION (SPOT â†” FUTURES, satu bahasa)

Tanggal: 2026-07-17 Â· Status: DIKERJAKAN Â· Owner: Copilot CLI

## Konteks & Feedback Owner

Owner review halaman **Signal Performance** setelah Claude Code menyelesaikan
`PLAN_SIGNAL_REPAIR_LIVE` (FUTURES-only) + saya menambah `spot_repair_agent`
(SPOT-only). Semua repair sekarang **jalan live**, tapi ada 4 masalah UX:

| # | Masalah owner | Sebab teknis |
|---|---|---|
| 1 | Tab **Progress** hanya untuk FUTURES; SPOT tidak tampak. "Menunggu verifikasi" tidak jelas. | `/signals/repairs` hanya menerima data `futures_repair_actions`; SPOT punya ledger sendiri (`spot_repair_actions`) tapi belum diekspos dengan bentuk yang sama. |
| 2 | **Perbaikan Live** â€” data dari mana? real-time? per SPOT/FUTURES per agent? | Tab pakai `/signals/repairs` (futures saja). Tidak ada pengelompokan per lane. |
| 3 | **Saran Engine** â€” read-only untuk SPOT; hanya futures yang bisa Apply. | `/signals/recommendations/apply` panggil `predictive_repair._apply_weight_step` (futures only). SPOT belum punya jalur apply. |
| 4 | Terlalu banyak informasi duplikat antar tab. | Setiap tab fetch sumber sendiri, tidak ada state bersama. |

## Batasan â€” JANGAN ganggu Claude Code

Berdasarkan commit terakhir Claude Code (`59b405b`), dia pegang:
- `agents/futures/*`, `agents/learning/predictive_repair.py`,
  `agents/learning/repair_verifier.py`, `agents/learning/weekly_signal_review.py`
- `backend/app/api/v1/signals.py`, `backend/app/api/v1/predictive.py`
- `backend/app/models/futures_repair_action.py`
- **`frontend/src/features/signals/page.tsx`** (aktif, terakhir edit 17 Jul 22:45)

Semua kerja saya di file **BARU** atau file SPOT-only:
- `agents/learning/spot_repair_agent.py` (sudah dibuat)
- `agents/learning/spot_repair_verifier.py` (BARU)
- `backend/app/api/v1/spot_repair.py` (sudah, akan diperluas)
- `backend/app/models/spot_repair_action.py` (sudah, akan diperluas)

## Solusi (2 lapis: backend integrasi + UI terintegrasi)

### Lapis 1 â€” Backend: samakan bentuk data SPOT dengan FUTURES

Tujuan: satu komponen UI bisa render kedua scope hanya dengan ganti sumber.

- [x] **I1 â€” `spot_repair_actions` sudah punya kolom sepadan** (`before_json`
      / `after_json` = padanan `evidence_json` + `before_metric`/`after_metric`
      futures). Sudah dilakukan.

- [x] **I2 â€” Verifier SPOT** (`agents/learning/spot_repair_verifier.py`):
      pass tiap ~6 jam. Untuk aksi `applied` berumur â‰¥24h:
      - `WEIGHT_BOOST`/`WEIGHT_TRIM` â†’ hitung WR sinyal pada trade setelah
        `applied_at`. Bandingkan dengan `before.wr`.
      - `THRESHOLD_LOOSEN`/`THRESHOLD_TIGHTEN` â†’ hitung opened_24h & WR window
        setelah applied. Bandingkan dengan sebelum.
      - `OUTCOME_BACKFILL` â†’ cek `completeness_pct` sekarang vs `before`.
      - Tulis kolom `after_metric` di ledger + set status:
        `verified_improved` / `verified_no_change` / `reverted` (bila memburuk
        signifikan). Cooldown revert 48h.

- [x] **I3 â€” Endpoint `GET /spot-repair/repairs`** dengan bentuk **identik**
      `/signals/repairs`:
      ```
      { funnel:{total,applied,verified,improved,no_change,reverted,suggested,actions_24h},
        agent:{last_run,checked,actions_last_run,actions_total},
        verifier:{last_run,verified_last_run,reverted_total},
        actions:[{id,detected_at,source,target_key,agent,issue,action,delta,
                  applied,applied_at,evidence,before_metric,after_metric,
                  status,verified_at,revert_of,note}],
        updated_at }
      ```
      `agent` = "opportunity_spot" untuk semua row. `target_key` sudah ada
      (mis. `signal_key@regime` atau `spot.auto_open_score`).

- [x] **I4 â€” Endpoint apply untuk SPOT saran**: `POST /spot-repair/apply`
      body `{action_type, target_key, delta}` â€” hanya trigger aksi yang
      whitelisted (WEIGHT_BOOST/TRIM/THRESHOLD_LOOSEN dengan bounds ketat).
      Padanan `/signals/recommendations/apply`.

- [x] **I5 â€” Extend `/signals/recommendations`** â€” TIDAK EDIT signals.py
      (milik Claude Code). Sebagai gantinya buat `GET
      /spot-repair/recommendations` yang menghasilkan saran SPOT
      auto-applicable (baca dari snapshot yang sama dengan agent) dengan
      field `apply` yang menunjuk ke `/spot-repair/apply`. UI nanti bisa
      merge dua source ini.

### Lapis 2 â€” UI: satu tab Progress + satu tab Perbaikan Live yang paham scope

**Blocker**: `frontend/src/features/signals/page.tsx` masih di working-tree
Claude Code (M flag, terakhir touch 22:45 â€” 20 mnt lalu). **TIDAK saya sentuh
sampai Claude Code commit.**

Setelah Claude Code commit, saya akan:
- [x] **U1** â€” Tambah **scope switcher** (chip `SPOT` / `FUTURES` / `Semua`)
      di header seksi "ðŸ”§ Improve".
- [x] **U2** â€” **Progress tab**: dua funnel berdampingan
      (SPOT dari `/spot-repair/repairs`, FUTURES dari `/signals/repairs`).
      Kalimat penjelas "Menunggu verifikasi = aksi <24 jam, verifier belum
      punya cukup data setelah."
- [x] **U3** â€” **Perbaikan Live tab**: satu tabel gabungan, kolom `Scope`
      + `Lane/Agent`, filter chip scope + lane. Tiap baris menampilkan
      "before â†’ after" dan badge status (applied/verified_improved/reverted/
      no_change). Data-source sesuai scope.
- [x] **U4** â€” **Saran Engine tab**: tombol "Terapkan" hidup untuk BAIK
      SPOT maupun FUTURES (SPOTâ†’`/spot-repair/apply`, FUTURESâ†’`/signals/
      recommendations/apply`). Saran yang tidak auto-applicable tetap
      tampil dengan badge "manual".

### Guardrail

- Aksi SPOT tetap bounded: WEIGHT 0.70â€“1.50 step 0.05, THRESHOLD Â±1â€“2 pt TTL 6h,
  rate-limit 10 aksi/tipe/jam, DRY_RUN env override.
- Verifier tidak pernah membatalkan aksi TTL yang sudah reversed.
- Nol edit di `signals.py`, `predictive.py`, `signals/page.tsx` sampai UI phase.

## Verifikasi

- I2/I3/I4 backend: curl endpoint, konfirmasi bentuk identik futures.
- Setelah 15 mnt loop repair (jika `SPOT_REPAIR_ENABLED=true`), aksi tercatat.
- Setelah 24 jam ada aksi berumur cukup, verifier isi `after_metric` + status.
- UI phase (U1-U4): setelah Claude Code commit, jalankan Playwright + screenshot.

## Tujuan

Halaman Signal Performance jadi **dashboard perbaikan tunggal** untuk semua
agents (SPOT + 4 FUTURES). Setiap aksi punya jejak dan verifikasi. Owner
bisa lihat: "hari ini agent perbaiki 12 sinyal, 8 terbukti membaik, 2 di-revert,
2 masih tunggu verifikasi" â€” untuk kedua scope, dalam satu bahasa.
