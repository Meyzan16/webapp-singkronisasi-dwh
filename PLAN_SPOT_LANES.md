# PLAN_SPOT_LANES.md
# Audit menyeluruh SPOT scanner + SPOT monitor

**Status**: DRAFT — belum ada kode yang diubah
**Tanggal audit**: 21 Juli 2026
**Pemicu**:
- Bagian A — arsitektur mengklaim 5 design lane, History SPOT hanya menampilkan 4.
- Bagian B — akhir-akhir ini sering kena SL dan profit menurun.

**Tujuan**: (1) bersihkan bug di scanner SPOT + monitor SPOT, (2) hentikan sumber SL beruntun.

---

# BAGIAN A — Berapa lane yang sebenarnya jalan

## 0. Jawaban singkat

| Hitungan | Jumlah | Isi |
|----------|--------|-----|
| Lane di dokumen arsitektur (`frontend/src/features/architecture/data.ts` → `SPOT_LANES`) | **5** | accumulation · breakout hunter · big mover · **weekly momentum (S4)** · early radar |
| Lane yang punya fungsi scoring + `alert_type` sendiri di kode | **4** | `_score_symbol` (accumulation) · `_score_breakout` · `_score_bigmover_chase` · `_score_early_radar` |
| Lane yang benar-benar dieksekusi tiap cycle scan | **4** + 1 fastpass | 4 pass di `run_opportunity_scan()` + loop fastpass BigMover 30 detik (`_run_fastpass_cycle`) |
| Lane yang pernah menghasilkan trade (seumur hidup DB, 61 trade) | **3** | squeeze/accumulation 30 · bigmover_chase 28 · breakout_pump 3 · early_radar **0** |
| Mode eksekusi berbeda yang dikenali monitor | **3** | `momentum_chase` · `momentum_entry` · sisanya jatuh ke default `fresh_setup` |

**Weekly Momentum bukan lane.** Di kode ia adalah *universe supplement* (`WEEKLY_SCAN_*`, [scanner.py:1600](agents/opportunity/scanner.py:1600)): ambil koin ranking volume 100–250, ukur `change_7d` lewat klines 4h, lalu koin yang lolos ≥20% **dimasukkan ke `candidates`** dan di-scoring oleh lane Accumulation/BigMover. Ia tidak punya `alert_type`, tidak punya `entry_mode`, tidak punya level SL/TP sendiri. Trade apa pun yang lahir darinya tercatat sebagai `squeeze`/`accumulation`/`bigmover_chase`. Jadi Weekly Momentum **secara struktural tidak akan pernah muncul di History** — bukan bug tampilan, memang tidak ada identitasnya.

Yang ditampilkan History (4 lane) sudah benar terhadap kode. Yang salah adalah dokumen arsitektur: ia menyejajarkan sebuah feeder dengan 4 lane sungguhan, lengkap dengan `minScore: 65`, `autoScore: 85`, `maxAge: "10 hari"`, `rrMin: 3.5` — angka-angka yang tidak pernah dibaca kode mana pun.

---

## 1. Peta lane sebenarnya (sumber: kode, bukan dokumen)

| Lane | Scoring | `alert_type` | `entry_mode` | Universe | min/auto score | Level SL/TP |
|------|---------|--------------|--------------|----------|----------------|-------------|
| Accumulation | `_score_symbol` [:1042](agents/opportunity/scanner.py:1042) | `squeeze` / `accumulation` / `breakout` | `fresh_setup` **atau** `momentum_chase` | top-100 vol ≥$5M + supplement R7 + supplement Weekly | 65 / 85 (+fast-track ≥80 bila Δ24h ≥8%) | swing low, RR ≥ 2 |
| Breakout Hunter | `_score_breakout` [:545](agents/opportunity/scanner.py:545) | `breakout_pump` | `momentum_entry` | semua mover Δ24h ≥3%, vol ≥$500K, pool 50 | 60 / 75 | ATR×1.5, risk 2–12% |
| Big Mover Chase | `_score_bigmover_chase` [:701](agents/opportunity/scanner.py:701) | `bigmover_chase` | `bigmover_chase` | Δ24h ≥10% **atau** Δ7d ≥30%, vol ≥$1M | 55 / 65 | bracket tetap 5/12/25% (explosive 8/20/45%) |
| Early Radar | `_score_early_radar` [:931](agents/opportunity/scanner.py:931) | `early_radar` | `early_radar` | micro-cap vol $100K–$1M, klines 1d saja | 70 / 85 | 10/25/60%, RR ≥ 4 |
| ~~Weekly Momentum~~ | — (feeder) | — | — | ranking vol 100–250, Δ7d ≥20% | — | — |

Urutan eksekusi + dedup: Accumulation → Breakout → BigMover → Early Radar, semuanya berbagi satu set `_breakout_done`, jadi satu simbol hanya boleh dimiliki lane yang jalan lebih dulu. **Konsekuensi**: koin yang memenuhi syarat BigMover tapi kebetulan sudah masuk `candidates` dan lolos scoring Accumulation akan dicatat sebagai Accumulation. Atribusi lane adalah "siapa cepat", bukan "siapa paling cocok".

---

## 2. Temuan — diurut berdasarkan dampak

### T1. Early Radar praktis mustahil auto-open (0 trade seumur hidup)

Skala skor Early Radar maksimal **100 poin**: surge 40 + near-high 30 + momentum 15 + RSI 10 + BB 5. Ambang auto-open **85**. Artinya auto-open menuntut hampir seluruh kategori menyala sekaligus:

- surge ≥3× (40) + near-high ≤5% (30) + Δ24h 2–15% (15) = 85 → pas di ambang
- atau surge ≥3× + near-high ≤10% (15) + momentum 15 + RSI 10 + BB 5 = 85 → butuh **lima-limanya**

Satu saja meleset — misal Δ24h 16% (di luar band 2–15%) — plafonnya jatuh ke 80 dan lane itu **tidak bisa** auto-open apa pun yang terjadi. Ditambah `_calc_trade_levels_early_radar` masih menuntut RR ≥ 4 dan SL 3–10%. Hasilnya terbukti: **0 trade dari 61 trade seumur hidup**. Lane ini de facto mati sejak lahir, dan tidak ada satu pun sinyal di UI yang memberi tahu itu.

### T2. `entry_mode` dimutasi monitor → analitik per-mode bias

[monitor.py:820](agents/opportunity/monitor.py:820), [:834](agents/opportunity/monitor.py:834), [:858](agents/opportunity/monitor.py:858) menulis ulang `meta["entry_mode"] = "momentum_chase"` saat TP2/TP3 kena, atau saat `fresh_setup` kena TP1 dengan volume spike ≥5×. Jadi `entry_mode` bukan identitas entry, melainkan **state runtime**. Bukti di DB: ada trade `alert_type=bigmover_chase` dengan `entry_mode=momentum_chase`.

Dampak: setiap analitik yang dikelompokkan per `entry_mode` (termasuk kolom Lane di Export CSV) otomatis bias — hampir semua pemenang besar bermigrasi ke `momentum_chase`, sehingga mode itu akan selalu terlihat paling menguntungkan. Untung atribusi lane di UI selamat karena `laneForSpot` memeriksa `alert_type` lebih dulu; itu kebetulan yang beruntung, bukan desain.

### T3. Monitor tidak mengenal `bigmover_chase` dan `early_radar`

Monitor hanya bercabang pada tiga nilai ([monitor.py:674](agents/opportunity/monitor.py:674), [:753](agents/opportunity/monitor.py:753)): `momentum_chase`, `momentum_entry`, sisanya default `fresh_setup`. Akibatnya:

- **BigMover diperlakukan sebagai fresh_setup**: umur maksimal 10 hari (bukan 5 hari milik momentum), dan **trailing runner tidak pernah aktif di TP1** — gate `is_momentum_chase` tidak mencakup `bigmover_chase`, sementara jalur upgrade BM6 di [:855](agents/opportunity/monitor.py:855) mensyaratkan `_entry_mode == "fresh_setup"`. BigMover baru jadi runner kalau berhasil menyentuh TP2/TP3. Ini bertentangan langsung dengan tesis "Wave Rider — ride the wave longer" yang jadi alasan lane ini ada, dan lane inilah penyumbang loss terbesar sekarang (−$38.53, WR 46%).
- **Early Radar** dirancang untuk TP3 +60% tapi dipantau dengan budget umur 10 hari milik akumulasi dan tanpa trailing — seandainya ia pernah open.

Scanner berbicara dalam kosakata lane; monitor berbicara dalam kosakata mode. Keduanya tidak pernah didamaikan.

### T4. Funnel per-lane dihitung tapi dibuang sebelum sampai UI

`run_opportunity_scan()` mengembalikan `found_accumulation`, `found_breakout`, `found_bigmover`, `found_early_radar`, `regime_status` — dan `_filter()` di [opportunity.py:683](backend/app/api/v1/opportunity.py:683) membuang semuanya. UI tidak punya cara membedakan "lane tidak menemukan kandidat" dari "lane menemukan tapi tertahan quota/regime/learning-veto". Inilah sebab pertanyaan "kenapa cuma 3 lane" tidak bisa dijawab dari layar mana pun.

### T5. Tidak ada quota per lane di auto-open

[scheduler.py:475](agents/opportunity/scheduler.py:475): `auto_candidates` diurutkan global by `ev_per_risk`, dipotong `MAX_OPENS_PER_CYCLE = 3`. Yang ada hanya quota *pembatas* (BigMover ≤2, Early Radar ≤2) — tidak ada quota *penjamin*. Dengan kebijakan maksimal 3 posisi bersamaan dan modal ~$1064, lane bertiket besar (Accumulation score 99) menyerap seluruh slot. Lane kecil tidak pernah mendapat sampel, sehingga tidak pernah punya data untuk membuktikan dirinya — lingkaran tertutup.

### T6. Dokumen arsitektur menyimpan angka yang tidak dibaca kode

`SPOT_LANES` di `architecture/data.ts` menaruh angka konkret (`minScore`, `autoScore`, `slRange`, `rrMin`, `maxAge`, `tp1Partial: "50% posisi dijual"`) sebagai literal. Beberapa sudah basi: TP1 sekarang menjual 30%, bukan 50% (`LADDER_FRAC_TP1 = 0.30`). Dokumen ini adalah salinan manual dari konstanta — persis yang dilarang docstring scanner ("konstanta di bawah adalah sumber kebenaran — jangan tulis angka di docs").

### T7. `LANES.weekly` masih hidup di `frontend/src/lib/lanes.ts`

`laneForSpot` masih memetakan `alert_type` yang mengandung "weekly" ke lane Weekly — cabang mati, karena tidak ada `alert_type` seperti itu yang pernah diproduksi.

---

## 3. Rencana kerja

### S1 — Luruskan cerita lane (kecil, tanpa risiko trading)
1. Ubah `SPOT_LANES` di `architecture/data.ts`: turunkan Weekly Momentum dari "lane" jadi bagian **"Universe Feeders"** bersama supplement R7 momentum, tanpa `minScore`/`autoScore`/`rrMin` palsu. Sebutkan eksplisit: trade yang lahir dari feeder dicatat atas nama lane yang menilainya.
2. Hapus cabang mati `weekly` di `lib/lanes.ts` + entri `LANES.weekly`.
3. Ganti angka literal lane di `data.ts` dengan yang dibaca dari endpoint config yang sudah ada (`/api/v1/agent/config/all` sudah menyajikan seluruh threshold SPOT). Kalau terlalu besar untuk sekarang, minimal perbaiki `tp1Partial` 50% → 30% dan tandai blok itu "disalin manual, verifikasi ke konstanta".

**Selesai bila**: halaman Architecture menampilkan 4 lane + 2 feeder, dan tidak ada angka di layar yang berbeda dari konstanta kode.

### S2 — Buka funnel per lane ke UI (menjawab "kenapa lane ini kosong")
1. `_filter()` meneruskan `found_*` + `regime_status` + `elapsed_sec` apa adanya.
2. Scanner mencatat alasan gugur per lane, bukan hanya jumlah lolos: `{pool, scored, rejected_by_score, rejected_by_levels, rejected_by_net_ev, auto_open_eligible}` per lane.
3. Panel "Win Rate per Lane" di History memakai data itu untuk kartu lane kosong: bukan lagi "belum ada sinyal lolos threshold" (tebakan), melainkan angka nyata — mis. "12 kandidat, 3 lolos skor, 0 mencapai auto ≥85".

**Selesai bila**: untuk tiap lane kosong, layar bisa menjawab di tahap mana kandidat gugur.

### S3 — Perbaiki Early Radar (T1) — butuh keputusan owner
Pilihan, bukan rekomendasi ganda:
- **Opsi A (disarankan)**: turunkan `EARLY_RADAR_AUTO_SCORE` 85 → 75 dan lebarkan band momentum 2–15% → 2–25%. Dengan `EARLY_RADAR_MAX_OPEN = 2` dan risk ½ normal, eksposur tetap terbatas. Ini membuat lane mulai menghasilkan sampel.
- **Opsi B**: biarkan ambang, tapi naikkan plafon skor (tambah kategori sinyal) agar 85 bukan lagi nyaris-sempurna.
- **Opsi C**: matikan lane secara eksplisit dan hapus dari UI, daripada memelihara lane yang tidak pernah jalan.

Apa pun pilihannya: **jangan ubah sebelum S2 jalan**, supaya efeknya terukur, bukan ditebak.

### S4 — Damaikan kosakata scanner ↔ monitor (T3)
1. Tambahkan field `lane` yang **immutable** di meta trade saat auto-open (nilai: `accumulation|breakout|bigmover|early_radar`), terpisah dari `entry_mode` yang boleh berubah. Semua atribusi (UI, CSV, learning, `_lane_risk_multiplier`) pindah ke `lane`.
2. Monitor membaca `lane` untuk menentukan regime exit; `entry_mode` tetap dipakai sebagai state runtime tapi tidak lagi jadi identitas.
3. Beri BigMover jalur trailing sejak TP1 (sesuai tesis Wave Rider) dan budget umur sendiri, alih-alih mewarisi default fresh_setup 10 hari.
4. Backfill `lane` untuk trade lama dari `alert_type` (deterministik, sudah terbukti dari data: 3 nilai saja).

**Selesai bila**: mengubah `entry_mode` di monitor tidak lagi mengubah lane trade mana pun, dan WR per lane stabil terhadap replay.

### S5 — Quota penjamin per lane (T5)
Setelah S2 memberi data: alokasikan minimal 1 slot per cycle untuk lane non-Accumulation bila ada kandidat auto-open yang layak, mirip `lane_quota_*` yang sudah dipakai FUTURES di `agent_config`. Tujuannya bukan memaksa trade, tapi memastikan lane kecil bisa mengumpulkan sampel.

### S6 — Bersihkan bias analitik `entry_mode` (T2)
Setelah S4: kolom Lane di Export CSV dan seluruh pengelompokan learning pindah ke `lane`. Kalau analitik per-`entry_mode` tetap ingin dipertahankan, beri label jelas "mode saat ditutup", bukan "mode saat entry".

---

## 4. Urutan eksekusi yang disarankan

```
S1 (dokumen)  ─┐
                ├─→ S2 (funnel visible) ─→ S3 (Early Radar) ─→ S5 (quota)
S4 (lane immutable) ─────────────────────→ S6 (analitik)
```

S1 dan S4 tidak saling menunggu. S3 dan S5 **wajib** menunggu S2, karena tanpa funnel yang terlihat kita cuma menebak apakah perubahan ambang berhasil.

---

## 5. Yang sengaja TIDAK diusulkan

- **Menambah lane baru.** Empat lane sudah lebih banyak dari yang bisa diberi sampel oleh kebijakan 3 posisi bersamaan.
- **Menghidupkan Weekly Momentum sebagai lane.** Ia bekerja baik sebagai feeder; menjadikannya lane berarti menduplikasi scoring Accumulation dengan universe berbeda.
- **Menyentuh file engine SPOT lain di luar daftar di atas** sebelum S2 memberi bukti.

---
---

# BAGIAN B — Forensik: kenapa sering kena SL dan profit menurun

Semua angka di bawah dihitung dari 61 trade SPOT (58 selesai) di DB per 21 Juli 2026,
lewat `GET /opportunity/positions?days=365`. Tidak ada angka yang ditebak.

## B0. Ringkasan satu paragraf

Sistem tidak rusak merata — **kerugian terkonsentrasi di satu lane, satu pita skor, dan satu
periode**. Lane BigMover pada skor 65–70 membukukan **−$74.85 dari 16 trade (WR 31%)**,
sementara BigMover skor 71+ justru **+$36.32 dari 12 trade (WR 67%)**. Ambang auto-open lane
itu `BIGMOVER_AUTO_SCORE = 65` — jadi mesin sengaja membeli tepat di pita yang merugi.
Diperparah tiga hal: SL BigMover selalu menabrak lantai −5% (13 dari 13 stop), TP1-nya juga
+5% sehingga anak tangga pertama cuma 1:1, dan monitor tidak pernah mengaktifkan trailing
untuk lane ini di TP1 karena tidak mengenal `entry_mode="bigmover_chase"`. Hasilnya pola klasik:
**pemenang dipotong kecil, pecundang dibiarkan sampai stop penuh**.

## B1. Bukti — pergeseran tajam pada 9 Juli

| Periode | Trade | WR | P&L | Median hold | Komposisi lane |
|---------|-------|-----|-----|-------------|----------------|
| ≤ 8 Jul | 27 | **70.4%** | **+$190.13** | 592 m | bigmover 11 · accum 15 · breakout 1 |
| ≥ 9 Jul | 31 | **25.8%** | **−$126.13** | 267 m | bigmover **17** · accum 12 · breakout 2 |

`sl_hit` di periode pertama: **1**. Di periode kedua: **15**. Porsi BigMover naik dari 41% → 55%
persis ketika lane itu berhenti bekerja. Sistem menambah eksposur ke lane terburuk, bukan
menguranginya.

## B2. Bukti — di mana uang hilang (per alasan tutup)

| close_reason | n | W | L | P&L | median hold |
|--------------|---|---|---|-----|-------------|
| `sl_hit` | 16 | 0 | 16 | **−$187.94** | 45 m |
| `trend_reversal` | 6 | 1 | 5 | −$19.14 | 521 m |
| `risk_adjusted` | 2 | 0 | 2 | −$12.26 | 40 m |
| `stagnant_rotation` | 2 | 1 | 1 | +$3.99 | 6687 m |
| `max_age_expired` | 1 | 1 | 0 | +$1.50 | 360 m |
| `tp3_hit` | 1 | 1 | 0 | +$19.28 | 296 m |
| `profit_protection` | 4 | 4 | 0 | +$80.07 | 748 m |
| `tp1_breakeven` | 9 | 9 | 0 | +$83.29 | 25 m |
| `urgent_rotation` | 17 | 10 | 7 | +$95.21 | 1450 m |

**`sl_hit` sendirian −$187.94, dan 13 dari 16 milik BigMover.** Semuanya rugi ~−5.4%,
yaitu lantai SL penuh. Tujuh di antaranya kena stop **dalam 60 menit pertama** (tercepat 7.9
menit) — entri langsung merah, ciri masuk di puncak pump. Dua stop breakout bahkan tutup di
menit 1.9 dan 3.7.

## B3. Bukti — ekonomi per lane

| Lane | n | WR | avg win | avg loss | EV/trade | P&L |
|------|---|-----|---------|----------|----------|-----|
| accumulation | 27 | 48.1% | +$12.83 | −$3.43 | **+$4.40** | **+$118.79** |
| bigmover | 28 | 46.4% | +$10.11 | −$11.33 | **−$1.38** | **−$38.53** |
| breakout | 3 | 33.3% | +$1.50 | −$8.88 | −$5.42 | −$16.26 |

WR bigmover dan accumulation nyaris sama (46% vs 48%) — **yang membedakan adalah bentuk
kerugiannya**. Accumulation rugi rata-rata −$3.43 karena keluar lebih awal; BigMover rugi
−$11.33 karena selalu sampai stop penuh. Win rate bukan masalahnya; asimetri yang masalah.

## B4. Bukti — pita skor BigMover

| Skor | n | WR | P&L |
|------|---|-----|-----|
| 65–70 | 16 | **31.2%** | **−$74.85** |
| 71–80 | 10 | 60.0% | +$9.50 |
| 81+ | 2 | 100.0% | +$26.82 |

Menaikkan `BIGMOVER_AUTO_SCORE` dari 65 → 71 akan menghapus −$74.85 kerugian dan
mempertahankan +$36.32 keuntungan, di data yang sama. Ini perubahan satu konstanta dengan
dampak terbesar dari seluruh dokumen ini.

## B5. Bukti — re-entry ke simbol yang baru saja gagal

Cooldown setelah SL hanya **2 jam** (`COOLDOWN_SL_HOURS = 2.0`, breakout 0.5 jam).
Terjadi **9 kali re-entry setelah SL — 8 di antaranya rugi lagi**:

```
TONUSDT   SL -0.3% -> masuk lagi  2.0 jam kemudian -> SL -0.3%   (berulang 6x)
TUSDT     SL -2.8% -> masuk lagi  9.5 jam kemudian -> SL -5.4%
ALLOUSDT  SL -5.3% -> masuk lagi  144  jam kemudian -> SL -5.4%
SXTUSDT   SL -5.4% -> masuk lagi 12.8 jam kemudian -> TP +2.9%   (satu-satunya yang selamat)
```

Cooldown juga hanya melihat **penutupan terakhir** simbol itu, sehingga rantai SL beruntun
tidak pernah memperpanjang jeda.

## B6. Akar masalah — diurut berdasarkan dampak dolar

### R1. `BIGMOVER_AUTO_SCORE = 65` membeli di pita yang terbukti merugi — **−$74.85**
Lihat B4. Tidak ada gradasi ukuran atau kuota berdasarkan skor di dalam lane.

### R2. Monitor tidak mengenal `bigmover_chase` → trailing tak pernah aktif di TP1
Sudah dicatat sebagai **T3** di Bagian A; di sini terlihat harganya. Gate runner
`is_momentum_chase` ([monitor.py:675](agents/opportunity/monitor.py:675)) tidak mencakup
`bigmover_chase`, dan jalur upgrade BM6 ([:855](agents/opportunity/monitor.py:855))
mensyaratkan `_entry_mode == "fresh_setup"`. Jadi BigMover — lane yang seluruh tesisnya
"ride the wave" — hanya menjual 30% di TP1 lalu **membiarkan sisanya kembali ke SL awal**.
Ini yang membuat avg loss (−$11.33) lebih besar dari avg win (+$10.11).

### R3. Struktur level BigMover 1:1 di anak tangga pertama
`BIGMOVER_TP1_PCT = 5.0` melawan `BIGMOVER_SL_PCT_MAX = 5.0`, dan
`_calc_trade_levels_bigmover` hanya menolak bila `rr < 1.2`
([scanner.py:472](agents/opportunity/scanner.py:472)) — jauh di bawah kebijakan proyek
"R:R ≥ 1:3" di CLAUDE.md. Data mengonfirmasi: **13 dari 13 stop BigMover tepat di risk 5.00%**,
artinya swing-low 15m selalu lebih dalam dari lantai dan lantai −5% yang selalu dipakai.

### R4. Rotasi mendesak boleh merealisasi kerugian
`urgent_rotation` ([monitor.py:905](agents/opportunity/monitor.py:905)) hanya bersyarat
`hold_days >= 1.0` + ada kandidat jauh lebih baik. **Tidak ada syarat drift dan tidak ada
syarat P&L** — berbeda dari jalur `stagnant_rotation` yang mensyaratkan harga diam ±3%.
Akibatnya posisi yang sedang merah ditutup di pasar dan kerugiannya dibukukan: **7 dari 17
rotasi tutup rugi**. Secara agregat rotasi masih +$95.21, jadi mekanismenya tidak salah
total — yang salah adalah ia tidak membedakan "posisi diam" dari "posisi sedang drawdown".

### R5. Rem lane bisa terlewat diam-diam
`_lane_risk_multiplier` (0.5× saat ekspektasi 20 trade terakhir negatif) hanya dipakai di
dalam cabang `if lower_p is not None` ([scheduler.py:331](agents/opportunity/scheduler.py:331)).
Kalau `lower_confidence_probability` tidak tersedia — mis. sinyal belum punya sampel di tabel
learning — **seluruh cabang Kelly + lane multiplier dilewati** dan sizing kembali ke 1–2% penuh.
Bukti dari data: trade yang rugi besar dibuka dengan `risk_dollar ≈ $11` (1% penuh), sedangkan
tiga posisi terbuka sekarang memakai `$5.32` (0.5%) — rem baru bekerja belakangan.
Sizing itu sendiri **tidak** bermasalah: realisasi rugi 1.07–1.11× `risk_dollar`, selisihnya biaya
eksekusi. Yang bermasalah adalah rem yang menempel pada syarat yang tidak selalu terpenuhi.

### R6. Cooldown 2 jam + hanya melihat penutupan terakhir — **8 dari 9 re-entry rugi lagi**
Lihat B5.

### R7. Fastpass memberi lane terburuk frekuensi entri tertinggi
BigMover punya loop 30 detik sendiri (`BIGMOVER_FASTPASS_SEC = 30`, ambang Δ24h ≥8%) plus
toleransi drift harga 3% saat auto-open versus 1% untuk lane lain
([scheduler.py:236](agents/opportunity/scheduler.py:236)). Lane dengan EV negatif mendapat
kesempatan masuk terbanyak dan izin masuk terjauh dari harga hasil scan.

### R8. Gerbang regime BTC tidak pernah menyala di pasar seperti ini
`_btc_regime` butuh BTC ≤ −3% (REDUCED) atau ≤ −5% (CLOSED). Kerugian 9–18 Juli datang dari
pelemahan altcoin dengan BTC relatif datar, sehingga gate tetap OPEN sepanjang periode rugi.
Circuit breaker harian 3% mengukur P&L **terealisasi**, jadi ia baru menyala setelah kerugian
dibukukan — pada 12 Juli tercatat 10 entri dan 13 penutupan dalam satu hari (−$36.44).

## B7. Rencana perbaikan

Urutan sengaja: **R-cepat** (satu konstanta, efek terukur, bisa dibalik) lebih dulu, baru
perbaikan struktural. Semua butuh S2 dari Bagian A agar efeknya terlihat, bukan ditebak.

### B-Fix 1 — Naikkan bar BigMover ke pita yang terbukti untung *(dampak terbesar, risiko terkecil)*
- `BIGMOVER_AUTO_SCORE` 65 → **71**, lewat `agent_config` (`spot.bigmover_auto_score`) supaya
  bisa dikembalikan tanpa deploy.
- `BIGMOVER_MIN_SCORE` 55 → 65 agar daftar rekomendasi tidak menampilkan pita yang tak boleh dibeli.
- **Ukur**: WR + P&L BigMover 20 trade berikutnya vs baseline 31% / −$74.85.

### B-Fix 2 — Hentikan asimetri BigMover
- Tegakkan R:R minimum lane ini: tolak setup dengan `rr < 2.0` (sekarang 1.2).
- Naikkan TP1 BigMover 5% → 7–8% **atau** turunkan lantai SL 5% → 3.5%, sehingga anak tangga
  pertama tidak lagi 1:1. Pilih satu, jangan dua-duanya sekaligus, supaya efeknya terbaca.
- **Ukur**: rasio avg win / avg loss BigMover; target ≥ 1.3 (sekarang 0.89).

### B-Fix 3 — Sambungkan monitor ke lane (clean bug R2)
Ini bagian S4 di Bagian A, dengan prioritas naik:
- Tambah field `lane` immutable di meta trade; monitor memilih regime exit dari `lane`, bukan `entry_mode`.
- Aktifkan trailing runner untuk `lane == "bigmover"` sejak TP1, bukan menunggu TP2.
- Beri BigMover budget umur sendiri (kandidat: 3 hari) alih-alih mewarisi 10 hari milik akumulasi.
- **Ukur**: berapa persen BigMover yang selesai lewat trailing/ladder vs `sl_hit` penuh.

### B-Fix 4 — Rotasi tidak boleh membukukan kerugian tanpa alasan struktur
- Tambahkan syarat pada jalur `urgent_rotation`: hanya rotasi bila `pnl_net >= -0.5%`
  **atau** struktur sudah patah (EMA cross bearish). Posisi merah tanpa patah struktur dibiarkan
  sampai SL/TP-nya sendiri yang memutuskan.
- **Ukur**: jumlah rotasi yang tutup rugi; target 0–1 dari 17.

### B-Fix 5 — Cooldown progresif per simbol (clean bug R6)
- Cooldown setelah SL: 2 jam → **6 jam**, dan **dikalikan 2 untuk tiap SL beruntun** pada simbol
  yang sama dalam 48 jam terakhir (6 → 12 → 24 jam). Hitung dari rangkaian penutupan, bukan
  hanya penutupan terakhir.
- **Ukur**: jumlah re-entry-setelah-SL yang rugi lagi; baseline 8 dari 9.

### B-Fix 6 — Rem lane selalu aktif (clean bug R5)
- Pindahkan `lane_multiplier` ke luar cabang `if lower_p is not None` sehingga selalu mengalikan
  sizing akhir, dengan atau tanpa probabilitas learning.
- Turunkan syarat sampel `_lane_risk_multiplier` dari 10 → 8 trade agar rem menyala lebih cepat.
- **Ukur**: `risk_dollar` rata-rata lane rugi harus turun ke 0.5% dalam ≤ 5 trade setelah
  ekspektasi berbalik negatif.

### B-Fix 7 — Rem harian yang melihat ke depan
- Circuit breaker harian juga menghitung **unrealized** P&L posisi terbuka, bukan hanya realized,
  supaya jeda datang sebelum kerugian dibukukan.
- Tambahkan pembatas frekuensi: maksimal 6 entri auto per hari WIB (12 Juli tercatat 10 entri /
  13 penutupan / −$36.44).
- **Ukur**: tidak ada lagi hari dengan >8 penutupan.

### B-Fix 8 — Regime gate berbasis alt, bukan hanya BTC
- Tambahkan sinyal breadth: persentase koin USDT yang naik dalam 24 jam. Bila breadth < 35%,
  perlakukan seperti REDUCED walaupun BTC datar. Ini yang absen sepanjang 9–18 Juli.
- **Ukur**: berapa hari REDUCED menyala di replay periode 9–18 Juli (harusnya beberapa).

## B7b. Status implementasi — 21 Juli 2026

| Fix | Status | Perubahan | Efek terukur di data historis |
|-----|--------|-----------|-------------------------------|
| B-Fix 1 | **LIVE** | `agent_config` `spot.bigmover_auto_score` 65→**71**, `spot.bigmover_min_score` 55→**65** (`updated_by=plan_spot_lanes_bfix1`). Kode tidak diubah — reset lewat `POST /agent/config/spot/{key}/reset`. | Menghapus pita 65–70: **−$74.85 dari 16 trade (WR 31%)**; pita 71+ yang dipertahankan **+$36.32 dari 12 trade (WR 67%)** |
| B-Fix 5 | **LIVE** | [scheduler.py](agents/opportunity/scheduler.py) — cooldown SL 2→6 jam, digandakan tiap SL beruntun dalam 48 jam (6→12→24, plafon 24), dihitung dari 6 penutupan terakhir simbol, bukan satu | Replay: aturan LAMA memblokir **0** entri sepanjang riwayat (praktis mati). Aturan baru memblokir **2** entri, −$2.46. Efek kecil di belakang; nilainya memotong rantai SL beruntun ke depan |
| B-Fix 6 | **LIVE** | `lane_multiplier` pindah dari cabang Kelly di scheduler ke parameter `risk_multiplier` di [compute_spot_sizing](backend/app/api/v1/balance.py:91) — kini selalu berlaku. Ambang sampel `_lane_risk_multiplier` 10→8 | **Ini yang paling menggigit.** Rem bigmover seharusnya menyala 12 Jul 18:32, tapi **6 entri BigMover sesudahnya tetap dibuka pada risk 1.00% penuh** karena `lower_p` None. Enam trade itu −$53.30; pada 0.5% menjadi −$26.65 → **≈$27 terhindar**. Perubahan 10→8 sampel sendiri **tidak berdampak** di data ini (rem menyala di trade yang sama) |

| B-Fix 2 | **LIVE** | [scanner.py](agents/opportunity/scanner.py) — `BIGMOVER_TP1_RR_MIN = 1.5`: TP1 kini `max(TP1 dasar, risk × 1.5)`, dibatasi `≤ 0.75 × TP2`. Plus pagar `BIGMOVER_RR_MIN = 2.0` (dari 1.2) | Stop lebar (risk 5%): TP1 5% → **7.5%**, anak tangga pertama 1:1 → **1.5:1**. Stop sempit (risk 2.98%): TP1 tetap 5% (sudah 1.68:1). Explosive: TP1 tetap 8%. **Tidak bisa di-backtest** dari data yang ada — butuh data harga intra-trade |
| B-Fix 3 | **LIVE** | [monitor.py](agents/opportunity/monitor.py) — `lane_of()` (identitas lane immutable, fallback deterministik dari `alert_type`), trailing 4h kini aktif untuk `lane == "bigmover"` sejak TP1, `MAX_AGE_DAYS_BIGMOVER = 3`. Scheduler menulis `meta["lane"]` saat auto-open; snapshot monitor + tipe frontend ikut sadar lane | Sisa 70% posisi BigMover pasca-TP1 tidak lagi jatuh kembali ke SL awal. Umur maks 10 hari → 3 hari (ADAUSDT dulu tertahan 4.9 hari lalu SL penuh) |

| B-Fix 4 | **LIVE** (perlu restart backend) | [monitor.py](agents/opportunity/monitor.py) — `ROTATION_MIN_PNL_PCT = -0.5`: rotasi (stagnant **dan** urgent) dibatalkan bila P&L bersih di bawah lantai itu; dicatat sebagai `rotation_skipped_in_drawdown` | 19 rotasi historis, **8 tutup rugi**. Aturan baru mencegah **2** yang nyata: XPL −2.07% (−$6.19) dan LTC −0.62% (−$2.29) = **−$8.48**. Enam sisanya TONUSDT −0.31%, di bawah biaya eksekusi 0.26% — itu keluar datar, bukan kerugian |
| B-Fix 7 | **LIVE** (perlu restart backend) | [scheduler.py](agents/opportunity/scheduler.py) — breaker harian kini realized + **rugi mengambang** posisi terbuka (laba mengambang sengaja diabaikan); `MAX_AUTO_OPENS_PER_DAY = 6`; fastpass BigMover kini tunduk pada **kedua** rem itu | Batas harian hanya mengikat sekali: 12 Juli (10 entri). **Jujur: 4 entri yang akan ditolak justru bernilai +$1.76** — cap ini pengendali varians, bukan perbaikan EV. Lubang yang lebih penting: fastpass 30 detik **tidak pernah** memeriksa breaker harian sama sekali |
| B-Fix 8 | **LIVE** (perlu restart backend) | [scanner.py](agents/opportunity/scanner.py) — `_alt_breadth_pct()` + gerbang `BREADTH_REDUCED_PCT = 35`, diperiksa sebelum jalur BTC-bullish; `alt_breadth_pct` ikut di payload scan | Uji gerbang: breadth 60% + BTC +1% → OPEN · breadth 30% + BTC +1% → **REDUCED** (dulu OPEN — persis kondisi 9–18 Juli) · BTC −6% tetap CLOSED · sampel <50 pair → tidak memutuskan |

**Restart diperlukan**: `uvicorn --reload` hanya mengawasi direktori `backend/`, sementara B-Fix 4/7/8
seluruhnya di `agents/`. B-Fix 1/2/3 sudah aktif di proses yang berjalan (terverifikasi lewat API);
tiga yang terakhir baru hidup setelah backend dijalankan ulang.

Keputusan yang saya ambil di dalam B-Fix 2 (plan meminta pilih satu, TP1 **atau** SL):
- **Menaikkan TP1, bukan menurunkan lantai SL.** Alasannya terbukti dari data: sizing di sini
  fixed-fractional (`risk_dollar = balance × fraksi`), jadi `risk_pct` hanya mengubah notional —
  **bukan** besar kerugian dolar. Semua stop rugi 1.07–1.11× `risk_dollar` tanpa peduli SL-nya
  2.14% atau 5.00%. Menyempitkan SL karena itu tidak mengecilkan kerugian sepeser pun, hanya
  memperbesar peluang tersentuh.
- **TP1 adaptif, bukan angka tetap 7–8%.** Setup ber-stop sempit sudah punya rasio sehat dan tidak
  perlu diganggu; yang diperbaiki hanya yang memakai lantai −5%.
- **Pagar R:R 2.0 belum pernah mengikat** (rasio terburuk yang mungkin 12/5.5 = 2.18). Ia
  ditulis sebagai pagar untuk perubahan konstanta di masa depan, bukan diklaim sebagai perbaikan.

Keputusan di dalam B-Fix 3: **runner dinamis TIDAK diperluas ke BigMover**. Kalau lane itu masuk
jalur runner sejak TP1, ia melewati rung TP2 (20%) dan TP3 (15%) dan langsung ke rung dinamis 5% —
mengurangi profit yang dikunci. Yang diperluas hanya *ratchet trailing SL*-nya; BigMover tetap
menaiki tangga ladder dan berubah jadi runner sendirinya di TP2 seperti sebelumnya.

Catatan jujur atas B-Fix 5: basis 6 jam tidak akan memblokir re-entry TUSDT (jeda 9.5 jam → rugi −5.4%).
Basis 10 jam akan memblokirnya, tapi itu berarti menyetel angka ke 2 titik data dan nyaris memblokir
SXTUSDT (jeda 12.8 jam → TP +2.9%). Biarkan 6 jam, nilai ulang setelah 20 trade.

## B8. Urutan eksekusi

```
S2 (funnel terlihat, Bagian A)
   └─→ B-Fix 1 ──→ ukur 20 trade ──→ B-Fix 2
   └─→ B-Fix 5, B-Fix 6  (clean bug, independen, boleh paralel)
   └─→ B-Fix 3 (butuh S4: field lane immutable)
   └─→ B-Fix 4
   └─→ B-Fix 7, B-Fix 8 (paling struktural, terakhir)
```

**Aturan main**: satu perubahan konstanta per gelombang, minimal 20 trade sebelum menilai.
Kalau dua diubah bersamaan, kita kehilangan kemampuan tahu mana yang bekerja — persis kondisi
yang membuat plan ini perlu ditulis.

## B9. Yang sengaja TIDAK diusulkan untuk masalah SL

- **Mematikan lane BigMover.** Pita skor 71+ menghasilkan +$36 dari 12 trade; yang rusak
  ambangnya, bukan lananya.
- **Memperlebar SL supaya "tidak kena stop".** Itu memindahkan kerugian, bukan menghilangkannya —
  dan data menunjukkan masalahnya di kualitas entri (9 stop dalam <60 menit), bukan di jarak stop.
- **Menaikkan risk per trade untuk "balas dendam".** Sizing sekarang sudah jujur (realisasi
  1.07–1.11× `risk_dollar`); menaikkannya hanya memperbesar varians pada EV yang masih negatif
  di dua dari tiga lane.
