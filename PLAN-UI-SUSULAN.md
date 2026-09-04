# PLAN — Susulan UI atas perubahan 24–25 Agu

> **Status: U1–U5 SELESAI 25 Agu (`172ce26`).**
>
> Disusun dari audit UI terhadap 12 commit kemarin (momentum dimatikan · M4b · F1–F4).
> Semua temuan diverifikasi dari kode UI **dan** payload endpoint yang berjalan, bukan
> dugaan.

## Ringkasan: apa yang sudah aman, apa yang belum

| Perubahan kemarin | Terlihat di UI? |
|---|---|
| F1 — `/agent/config` pulih | ✅ Architecture hidup kembali |
| F2 — komposisi exit di vonis canary | ✅ ikut terbawa di teks `reason` |
| F3 — canary `sl_max_pct` | ⚠️ tampil, tapi namanya mentah |
| F4 — jeda lane bertahan | ❌ **tak terlihat sama sekali** |
| Lane `momentum` dimatikan | ❌ panel kosong permanen — **harus dihilangkan** |
| M4b — usulan lebar SL | ❌ endpoint tak dipanggil UI |

Tak ada yang **rusak**. Yang bermasalah: keputusan paling menentukan justru yang paling
tak terlihat.

---

## U1 — Lane yang tidak dipakai HILANG dari UI ✅ SELESAI

> **Arahan pemilik (25 Agu):** lane yang tidak dipakai jangan ditampilkan sebagai panel
> kosong — hilangkan dari UI.

Keadaan sekarang: `momentum` mati (`lane_quota_momentum = 0`) tapi UI tetap menyediakan
tab filternya, kolom posisinya, baris breakdown-nya, dan kartu margin-nya — semuanya
permanen kosong. Panel kosong itu bukan sekadar sampah visual: ia terbaca seolah lane
sedang menunggu sinyal, padahal lane itu tak akan pernah membuka posisi.

Tempat yang menampilkan lane sebagai bagian tetap (hasil telusur):

| Berkas | Bentuknya |
|---|---|
| `futures/MonitorTab.tsx` | tab filter, `AgentColumn`, breakdown, kartu margin |
| `futures/BigMoversWatchlist.tsx` | peta label lane |
| `scanner/page.tsx` | tab lane |
| `signals/ExitSection.tsx` | `LaneBadge` di tabel |

### Dua hal yang harus diputuskan lebih dulu

**(a) Aturannya tak bisa "quota 0 = sembunyikan" begitu saja.**
`bigmover` **tidak ada** di `lane_quotas` — ia dibatasi `MAX_BIGMOVER_POSITIONS`, jalur
yang sama sekali lain. Kalau aturannya ditulis naif, bigmover akan ikut lenyap padahal
justru lane paling aktif. Aturan yang benar: *lane yang **ada** di `lane_quotas` **dan**
nilainya 0* → sembunyikan. Lane di luar daftar itu tak tersentuh.

**(b) Menyembunyikan harus dibatasi pada yang MELIHAT KE DEPAN.**
Momentum meninggalkan **14 trade tertutup** dan **14 exit event** — termasuk kerugian
−54,99 yang jadi dasar keputusan mematikannya. Kalau lane disembunyikan dari seluruh UI,
bukti itu ikut hilang, dan riwayat jadi berbohong tentang dari mana kerugian datang.

Usulan pembagian:

| Bagian | Perlakuan |
|---|---|
| Posisi terbuka, tab scanner, breakdown margin, quota | **sembunyikan** saat lane mati |
| History, win-rate per lane, analitik exit | **tetap tampil** — datanya nyata |

Kalau nanti momentum dinyalakan lagi (`quota` kembali 2), panelnya muncul sendiri tanpa
sentuhan kode — karena yang dibaca adalah keadaan, bukan daftar hardcode.

### Bagian kedua: lane yang sedang DIJEDA

Beda dari lane mati — lane dijeda itu **sementara** dan akan kembali sendiri. Sekarang
`bigmover` + `momentum` sedang dijeda 24 jam dan tak ada jejaknya di layar.

`gate.lane_pauses` dan `gate.lane_wr` **sudah dikirim** `/futures/monitor/risk`; tak ada
komponen yang membacanya (`GateBanner` hanya memakai `probe_allowed`). Karena sifatnya
sementara, lane dijeda sebaiknya **tetap tampil dengan penanda + sisa waktu**, bukan
disembunyikan — kalau hilang, orang akan mengira lane-nya dimatikan.

**Ukuran:** sedang · **Risiko:** nol (baca-saja)

### Susulan 26 Agu — halaman Scanner ikut dibereskan

Saat U1 dikerjakan 25 Agu, dua dari empat berkas di tabel di atas tersentuh
(`MonitorTab`, `ExitSection`). `scanner/page.tsx` **tertinggal**: tab 🔥 Momentum masih
ada, dan — ini yang lebih menentukan — backend **tetap memindai** lane mati, jadi
kartunya tetap muncul. Layar menawarkan peluang yang sudah pasti dilewati auto-trader
(`lane_quota_full` → `continue`). Hitungan LONG/SHORT ikut menghitungnya.

Yang dikerjakan: tab lane dibangun dari `LANE_TABS` (memetakan `agent3` → lane
`momentum`, dua nama yang selama ini beda tanpa jembatan), lane mati hilang beserta
sinyal dan hitungannya, filter yang menunjuk lane mati dikembalikan ke "Semua", dan dua
kalimat yang menyebut nama lane secara mati kini disusun dari lane yang aktif.
`PauseBadge` dipindah ke `features/shared/` — dipakai dua halaman, dan menyalinnya
berarti salah satunya akan tertinggal saat diubah.

`BigMoversWatchlist.tsx` ternyata **tidak** memuat lane sama sekali (tabel di atas
keliru) — tak ada yang perlu diubah di sana.

**Ukuran:** sedang · **Risiko:** nol (baca-saja)

---

## U2 — Usulan lebar SL berhenti di API ✅ SELESAI

Sub-tab **3· Lebar SL** sudah menampilkan kesiapan (`sl_recommendation_ready`,
`mae_n/mae_required`, `sl_utilization`) — tapi tidak menampilkan **angkanya**.

Endpoint `/{market}/exit-learning/sl-recommendation` (M4b) tak pernah dipanggil UI, jadi
kolom yang paling menentukan tak pernah sampai ke mata:

| Field yang hilang | Artinya |
|---|---|
| `proposed_sl_atr` | usulan lebarnya |
| `winners_cut` | berapa pemenang akan terpotong (**0** = aman) |
| `losers_capped` | berapa pecundang dihentikan lebih awal |
| `atr_saved_total` | penghematan |
| `step_capped` / `raw_proposed_atr` | apakah dibatasi, dan dari angka berapa |

UI kini berkata "✓ Lebar SL bisa dinilai" lalu berhenti — mengumumkan kesiapan tanpa
menunjukkan hasilnya.

**Rencana:** panggil endpoint itu di sub-tab yang sama, tampilkan usulan + counterfactual-nya.

**Ukuran:** sedang · **Risiko:** nol (baca-saja)

---

## U3 — Nama parameter tampil mentah ✅ SELESAI

Sub-tab **4· Penyalaan** merender `r.param` apa adanya: `sl_max_pct`, `failfast_min_sl_gap`,
`entry_tp_ladder`. Tak ada peta label.

Untuk `sl_max_pct` (parameter baru F3) ini bertambah menyesatkan karena **satuannya persen
harga**, sementara tetangganya di layar dinyatakan dalam **kelipatan ATR**. Angka "4,51"
tanpa satuan bisa terbaca sebagai 4,51× ATR — hampir dua kali lipat dari maksudnya.

**Rencana:** peta label + satuan per parameter; tampilkan `4,51%` bukan `4.51`.

**Ukuran:** kecil · **Risiko:** nol

---

## U4 — Komposisi exit hanya terbawa sebagai teks ✅ SELESAI

F2 menambahkan komposisi alasan tutup ke vonis canary. Karena UI merender `r.reason`
apa adanya, `[sl_hit×8, sl_plus×5, fail_fast×1]` **memang muncul** — tapi sebagai ekor
kalimat panjang berukuran 10px, bukan sebagai bukti yang menonjol.

Padahal justru komposisi itu yang kemarin membalikkan kesimpulan: canary terlihat
"memburuk" padahal parameternya hanya menyentuh 1 dari 14 exit. Respons API juga sudah
membawa `observed.close_reasons` tersendiri, tapi tipe UI belum memuat field itu.

**Rencana:** tampilkan komposisi sebagai baris tersendiri di kartu canary.

**Ukuran:** kecil · **Risiko:** nol

---

## U5 — Halaman Architecture menjelaskan sistem yang sudah berubah ✅ SELESAI

`architecture/data.ts` (700+ baris) adalah data **statis**. Sebagian pernyataannya kini
tak lagi cocok dengan keadaan, mis. lane WR-pause digambarkan "24 jam" — padahal sejak
F4 jedanya **berlipat** (24 → 48 → … → 168 j) dan bertahan melewati restart.

Ini dokumentasi, bukan kerusakan; tapi halaman yang menjelaskan cara kerja sistem justru
paling merugikan kalau isinya usang.

**Rencana:** sisir pernyataan yang menyangkut jeda lane, quota lane, dan lebar SL.

**Ukuran:** sedang · **Risiko:** nol

---

## Urutan yang disarankan

```
U1 ✅  →  U2 ✅  →  U3 ✅ + U4 ✅  →  U5 ✅   — semuanya selesai
```

**Temuan saat mengerjakan** (tak terlihat dari analisis saja):
- `close_reasons` (U4) ada di respons `evaluate()` **tapi tidak di listing** yang dipakai
  UI — tampilannya akan selamanya kosong. `status()` kini menghitungnya untuk baris canary.
- Tipe `lane_pauses` saya tulis `{lane: epoch}`; bentuk nyatanya objek
  `{paused, pause_until, wr, total}`. Ketahuan karena payload diperiksa, bukan diasumsikan.
- Sisa jeda dihitung dari `generated_at` **server**, bukan `Date.now()` klien — selain
  melanggar kemurnian render, jam klien yang meleset akan menampilkan sisa waktu yang salah.

U1 didahulukan karena satu-satunya yang bisa menyebabkan **salah tindakan**: mengira
sistem sedang mencari peluang padahal sedang berhenti. Arahan pemilik mempertegasnya —
lane yang tak dipakai dihilangkan, bukan ditandai. U3 dinaikkan di atas U5 karena
satuan yang salah baca bisa memicu keputusan tala yang keliru.

## Catatan

- Semua fase di sini **baca-saja** — tak satu pun menyentuh keputusan trading.
- Tak ada yang mendesak selama libur: sistem tetap berjalan benar, hanya sebagian
  keadaannya tak terlihat dari layar.
