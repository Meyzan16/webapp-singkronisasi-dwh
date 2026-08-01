# PLAN — MONITOR FUTURES

Agen MONITOR adalah penentu **alasan tutup posisi** (TP / SL / SL+ / trail /
fail-fast / rotasi / umur). Fokus rencana ini: membuat keputusan keluar bisa
**diukur, ditala, dan dipelajari** — bukan terkunci di konstanta kode.

## Kenapa monitor, bukan scanner

Bukti dari 44 trade futures tertutup (dinormalkan ke ATR):

| Ukuran | Angka |
|---|---|
| TP tersentuh | **1 dari 44** (SPOT 29/65) |
| R:R realisasi | 0,81 → butuh WR 55,4%, dapat 43,2% |
| Expectancy keseluruhan | −0,76% · PF 0,612 |
| MFE median | 0,61× ATR, sementara TP dipasang 4–13× ATR |

Model scanner masih *shadow* (nol pengaruh keputusan), jadi kerugian futures
tidak bisa dibebankan ke sana. Sebabnya ada di konstruksi keluar.

---

## Fase

### M0 — Ambang keputusan terpusat + ledger keluar ✅ `af416cc`
- `agents/futures/monitor_config.py`: 21 ambang keputusan jadi satu sumber
  (dulu ~40 konstanta, hanya 5 bisa di-override DB).
- Tabel `futures_exit_events`: keputusan KELUAR dulu **tak punya ledger sama
  sekali**, jadi tak ada bahan belajar. Kini tiap penutupan tercatat dengan
  `mfe_atr`, `tp_dist_atr`, `sl_dist_atr`, `realized_atr`, `close_reason`.
- `effective_take_profit()` — batas TP relatif ATR, **flag default MATI**.

### M1 — Adaptive Learning untuk keputusan keluar ✅ `c72dce8`
- `agents/learning/exit_learning.py`: backfill, agregasi per alasan/lane/regime,
  usulan TP dari sebaran MFE nyata.
- Batas TP **per lane** di balik `monitor_exit_learning_enabled`, default MATI.
- 5 endpoint `/api/v1/futures/exit-learning/*`.

### M2 — Sambungkan monitor.py ke monitor_config ✅ `b0a59f0`
**Temuan:** `monitor_config.refresh()` dipanggil tiap siklus sejak M0, tapi
`monitor.py` **tak pernah membaca hasilnya** — 20 dari 21 ambang masih dari
konstanta lokalnya sendiri, sehingga menala dari UI tidak berpengaruh apa pun.
M0 ternyata baru dekorasi; M2 yang menyambungkan kabelnya.

Hasil:
- 24 konstanta keputusan dihapus dari `monitor.py`; semua titik keputusan
  membaca `mcfg.X`. Default dibandingkan satu per satu → **nol perubahan perilaku**.
- Ambang yang belum tersentral ikut masuk: time-stop per lane, lane fail-fast,
  tangga kunci profit, jendela rug-pull, dan 3 ambang eskalasi fast-loop yang
  sebelumnya angka telanjang di tengah fungsi.
- `MAX_LOSS_PCT_OF_MARGIN_BY_LANE` — gerbang keluar paling keras (force-close) —
  ternyata **satu-satunya yang sama sekali tak bisa ditala dari DB**. Kini bisa.
- Baris config per-lane **dibangkitkan dari registry**, bukan diketik tangan.
- Default dibaca dari salinan **beku** supaya satu override tak menjadi
  "default" permanen.

Verifikasi live: 4 jalur tala diubah lewat DB → keputusan ikut berubah → pulih
saat dikembalikan. 176 test lulus.

### M3 — Perbaiki `fail_fast` ✅ `d63dbf2`
Bukti dari ledger (8 exit `fail_fast`, 0% menang):

| Lane | SL | Realisasi | `sl_gap` | Tanpa-selamat |
|---|---|---|---|---|
| bigmover (4) | 1,504× ATR | 1,299× ATR | **1,15** | 25% |
| momentum (4) | 5,412× ATR | 1,742× ATR | **3,05** | 0% |

Pemicu yang **sama** menyelamatkan ~3,7× ATR di momentum tapi cuma ~0,2× ATR di
bigmover — dan di bigmover seperempatnya rugi sebesar atau lebih dari jarak SL.
Pembedanya persis satu angka: `sl_gap` = jarak SL ÷ ambang pemicu.

Hasil:
- `failfast_allowed()` — syarat `jarak_SL ≥ gap × ambang`. Gap global + gap per
  lane hasil belajar, dua-duanya **default MATI**.
- Pemotongan yang **ditolak dicatat** (`fail_fast_suppressed` + pencacah), supaya
  penjaga ini bisa diaudit, bukan bekerja dalam diam.
- `analyze_exit_triggers()` — mengadili tiap pemicu exit dini dengan membandingkan
  kerugian yang direalisasi terhadap **alternatifnya** (jarak SL), bukan
  untung/rugi mentah.

**Belum diusulkan otomatis:** kedua lane baru punya n=4, di bawah ambang 5 sampel.
Ambangnya sengaja tidak diturunkan agar cocok dengan data.

### M4 — Lebar SL per lane ⬅ **BERIKUTNYA**
Temuan sampingan M3: SL bigmover 1,5× ATR vs momentum 5–6× ATR. Selisih 4×
membuat setiap gate yang diskalakan ke `risk_pct` (time-stop, fail-fast progress)
berperilaku sangat berbeda antar lane tanpa itu pernah diniatkan.

### M5 — Nyalakan bertahap
Ledger tumbuh → verifikasi rekomendasi → nyalakan satu lane dulu (bigmover,
sampel terbanyak), amati, baru lanjut. Bukan menyalakan semua sekaligus.

### M6 — Tab MONITOR di Adaptive Learning Engine
Analisa keluar sudah punya endpoint tapi belum punya halaman. Menyusul setelah
angkanya terbukti stabil.

---

## Aturan yang berlaku di semua fase

- Apa pun yang menyentuh keputusan trading masuk **di belakang flag, default MATI**.
- Rekomendasi mesin boleh ditulis; **penyalaan tetap keputusan pemilik**.
- Lane bersampel < 8 tidak menghasilkan rekomendasi.
- Gagal mencatat ledger **tak boleh** menggagalkan penutupan posisi.
