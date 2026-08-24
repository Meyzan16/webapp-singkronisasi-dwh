# PLAN — MONITOR (FUTURES + SPOT)

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

### M4 — Lebar SL per lane ✅ `b44acaa`
Dugaan awal "SL momentum kelewat lebar" **ternyata salah arah**. Sebaran SL dalam
harga% jauh lebih rapat (CV **0,231**) daripada dalam kelipatan ATR (CV **0,724**):
lebar SL sebenarnya disusun terhadap **harga**, bukan volatilitas. Perbedaan
1,3× vs 4,0× ATR antar lane adalah **efek samping** dari koin yang diperdagangkan.

| Lane | n | ATR% | SL harga% | SL/ATR | Mentok plafon | SL/MFE |
|---|---|---|---|---|---|---|
| bigmover | 28 | 6,07 | 7,99 | 1,32 | **61%** | 3,41 |
| momentum | 13 | 1,54 | 6,29 | 4,00 | 8% | 4,86 |
| accumulation | 2 | 1,18 | 4,20 | 3,60 | 0% | 1,21 |
| pre_gainer | 2 | 2,13 | 6,06 | 3,26 | 0% | 4,12 |

**61% posisi bigmover SL-nya mentok plafon 8%** — `ATR × 1,5` yang dimaksudkan
jarang berlaku. Di lane paling bergejolak, rancangan sadar-volatilitas mati diam-diam.

Hasil: `sl_config.py` (7 parameter × per lane, dibangkitkan dari registry),
`analyze_sl_width()`, 2 endpoint. **Nol perubahan perilaku** — dibuktikan terhadap
kode sebelum perubahan, 7.605 kasus, 0 beda.

Jebakan yang ditutup: `agent2` memakai ulang fungsi level `agent1`, jadi tanpa
meneruskan lane, accumulation akan memakai tala pre_gainer tanpa satu pun error.

### M4b — Rekam gerak merugikan terjauh (MAE) ✅ `cd153b7`
M4 mencatat SL/MFE 3,4–4,9× sebagai kandidat mempersempit SL. Saat hendak
dikerjakan, **datanya ternyata tidak cukup untuk kesimpulan itu**.

MFE menjawab "seberapa jauh harga sempat menguntungkan". Yang menentukan boleh
tidaknya SL dipersempit adalah pertanyaan **lain**: seberapa dalam harga sempat
**melawan** sebelum berbalik. Sistem tak pernah merekamnya. Mempersempit SL dari
MFE saja akan memotong posisi yang sebenarnya akan menang.

Hasil: kedua monitor merekam MAE, kolom `mae_atr` di ledger, dan
`sl_utilization` (berapa persen jarak SL yang benar-benar terpakai).
**Rekomendasi lebar SL ditahan** sampai 30 sampel MAE terkumpul — alasannya
tertulis di respons API dan di UI, bukan disembunyikan. Murni perekaman; tak satu
pun keputusan trading berubah.

### M5 — Nyalakan bertahap ✅ `5d0e18f`
Sisi MASUK sudah lama punya `shadow → canary → champion`. Sisi KELUAR tidak punya
padanannya — menyalakan berarti satu saklar biner untuk semua lane, tanpa
pembanding dan tanpa jalan pulang. M5 memberinya bentuk yang sama, per
**(lane × parameter)**:

```
shadow → canary (1 lane) → active | rolled_back
```

Tiga disiplin yang membuatnya bukan sekadar tombol:
1. **Baseline direkam sebelum angka berlaku** — pelajaran dari "116 terbukti
   membaik" yang ternyata menyesatkan.
2. **Satu lane canary pada satu waktu** — dua sekaligus membuat hasilnya mustahil
   ditafsirkan.
3. **Hanya exit sesudah aktivasi yang dihitung** — posisi yang sudah terbuka masih
   memakai parameter lama.

`advance()` berjalan di irama yang sama dengan `repair_verifier` sisi masuk, tapi
hanya **mengevaluasi dan membalik**; menaikkan ke canary tetap perintah eksplisit.

**Belum ada yang dinyalakan.** `monitor_exit_learning_enabled` masih 0.

### M6 — Seksi EXIT di Signal Performance ✅ `7d7e4d7`
Seluruh pekerjaan M0–M5 sebelumnya **hanya bisa dilihat lewat endpoint API** —
tak satu pun komponen frontend memanggilnya. Seksi baru **🚪 Exit** di
`/signals`, dengan 4 sub-tab berurut sebab→akibat:

| Sub-tab | Menjawab |
|---|---|
| 1· Alasan Tutup | Alasan mana yang menguntungkan, mana yang merugikan? |
| 2· Pemicu Dini | Pemicu ini menyelamatkan, atau justru merugikan? |
| 3· Lebar SL | SL disusun terhadap harga atau volatilitas? |
| 4· Penyalaan | Apa yang sedang diuji, dan terbukti membaik tidak? |

**Dimensi market dipasang di awal.** Saat ini hanya MONITOR FUTURES yang punya
ledger keluar; tab SPOT ada tapi menyatakan terus terang apa yang belum ada.
Menambah SPOT nanti = mengisi `endpoints` di satu peta `MARKETS`. Ini sengaja:
pola berulang di repo ini adalah SPOT ditempelkan belakangan lalu berperilaku
beda diam-diam (katalog Formulas dan Predictive dua-duanya sempat futures-only).

**Batas verifikasi:** browser dalam aplikasi tak meng-hydrate Next, jadi
klik-per-klik tak bisa diuji dari sini. Yang diverifikasi: `tsc` & `eslint` 0
error, `next build` sukses, dan payload keempat endpoint dicocokkan
field-per-field dengan kontrak TypeScript komponen (0 field hilang).

### M7 — MONITOR SPOT ✅ `19cd213`
SPOT sudah menutup 65 posisi tanpa satu pun tercatat dalam bentuk yang bisa
di-query. **Satu tabel, satu jalur kode** — bukan salinan untuk spot:

- `futures_exit_events` → `exit_events` + kolom `market`. Rename dijalankan di
  tahap **pra-`create_all`** yang baru; kalau tidak, `create_all` lebih dulu
  membuat tabel kosong bernama baru dan rename pasti gagal, diam-diam
  meninggalkan 45 baris di tabel bernama usang.
- `agents/shared/exit_ledger.py` dipakai kedua monitor; `exit_learning` menerima
  argumen `market`; endpoint `/spot/exit-learning/*` memanggil fungsi yang sama.

**Tiga temuan saat mengerjakan:**
1. `atr_pct` **dibuang** saat trade spot dibuat — analyzer menghitungnya tapi
   nilainya tak pernah masuk meta, sehingga 65 posisi tertutup tak satu pun bisa
   dinormalkan terhadap volatilitas. Kini disimpan.
2. Alasan close SPOT tercatat **100%** (futures harus ditebak dari riwayat).
   Backfill memakai alasan asli bila ada; awalan `hist:` hanya untuk tebakan.
3. **Taksonomi keluar dini berbeda per market.** Memaksa istilah futures ke spot
   menghasilkan tabel kosong yang terbaca seolah "spot tak pernah keluar dini",
   padahal justru mayoritas exit-nya begitu.

Angka SPOT (65 exit): expectancy **+0,25%**, PF **1,159** — berlawanan dengan
futures (−0,76%, PF 0,612).

| Alasan close | n | Expectancy | WR |
|---|---|---|---|
| urgent_rotation | 18 | +1,876% | 61,1% |
| sl_hit | 16 | −4,978% | 0% |
| trend_reversal | 10 | −1,191% | 10,0% |
| tp1_breakeven | 9 | +3,863% | 100% |
| profit_protection | 5 | +6,778% | 100% |

### Sisa

> **Status diperbarui 24 Agu 2026** dari state live (DB + endpoint). Catatan lama
> "belum ada yang dinyalakan" sudah tidak berlaku — lihat di bawah.

**M5 sudah dinyalakan.** `monitor_exit_learning_enabled` = **1** untuk *futures*
**dan** *spot* (default 0). Rollout sudah berjalan satu putaran penuh:

| Tahap | Isi |
|---|---|
| canary (1) | `futures/bigmover/failfast_min_sl_gap` 0,000 → 1,260 (12 Agu) |
| shadow (4) | `spot/accumulation/tp_atr_mult` · `futures/bigmover/entry_tp_ladder` · `spot/bigmover/tp_atr_mult` · `futures/momentum/tp_atr_mult` |
| rolled_back (4) | 2× macet 0/15 outcome · 2× expectancy di bawah baseline |

**Canary yang berjalan sedang MEMBURUK** — dan inilah gunanya baseline direkam:

| | n | expectancy | WR |
|---|---|---|---|
| baseline | 44 | −0,664 | 61,4% |
| observed | 11 | **−2,138** | **27,3%** |

Belum diputuskan karena n=11 di bawah ambang keputusan. Kalau arah ini bertahan
sampai ambang, `advance()` akan membalikkannya sendiri. **Perlu dipantau, bukan
dibiarkan** — ini satu-satunya parameter keluar yang sedang menyentuh keputusan.

**Yang kini SIAP dikerjakan (data sudah cukup):**
- **M4b lanjutan — rekomendasi lebar SL.** MAE terkumpul **51 sampel** (ambang 30).
  Rekomendasi yang sengaja ditahan sejak `cd153b7` sekarang boleh dihitung.

**Yang masih menunggu data:**
- **M3** — usul otomatis `fail_fast`: baru **3** sampel di ledger, ambang 5 per lane.

**Temuan dari data terbaru (bahan M4b/C2), 76 exit futures:**

| Lane | n | WR | Expectancy | Total |
|---|---|---|---|---|
| bigmover | 55 | 54,5% | −1,13 | −62,35 |
| momentum | 15 | **6,7%** | −3,67 | −54,99 |
| accumulation | 3 | 66,7% | +3,26 | +9,79 |
| pre_gainer | 3 | 33,3% | −4,38 | −13,15 |

Dua hal yang dibaca dari tabel ini:
1. **bigmover menang lebih sering (54,5%) tapi tetap rugi** — bukti langsung bahwa
   masalahnya *ukuran*, bukan *arah*: rugi rata-rata melampaui untung rata-rata.
   Ini persis kandidat M4b (lebar SL) dan C2 (SL/TP asimetris).
2. **momentum WR 6,7% dari 15 exit** — jauh lebih buruk dari perkiraan sebelumnya.
   Kandidat pause lane, tapi keputusan itu milik pemilik.

---

## Aturan yang berlaku di semua fase

- Apa pun yang menyentuh keputusan trading masuk **di belakang flag, default MATI**.
- Rekomendasi mesin boleh ditulis; **penyalaan tetap keputusan pemilik**.
- Lane bersampel < 8 tidak menghasilkan rekomendasi.
- Gagal mencatat ledger **tak boleh** menggagalkan penutupan posisi.
