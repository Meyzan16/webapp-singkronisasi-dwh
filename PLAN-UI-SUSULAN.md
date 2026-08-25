# PLAN — Susulan UI atas perubahan 24–25 Agu

> **Status: BELUM DIKERJAKAN — daftar untuk ditinjau dulu.**
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
| Lane `momentum` dimatikan | ❌ **tak terlihat sama sekali** |
| M4b — usulan lebar SL | ❌ endpoint tak dipanggil UI |

Tak ada yang **rusak**. Yang bermasalah: keputusan paling menentukan justru yang paling
tak terlihat.

---

## U1 — Lane dimatikan & lane dijeda tak terlihat 🔴

Dua keputusan yang langsung menghentikan pembukaan posisi, dan **tak satu pun muncul di UI**:

| Keadaan nyata sekarang | Di UI |
|---|---|
| `lane_quota_momentum = 0` (lane mati) | tak ada |
| `bigmover` + `momentum` dijeda 24 jam | tak ada |

- **`lane_quotas` tak dirender di komponen mana pun.** Endpoint `/agent/config` sudah
  mengembalikannya (`{momentum: 0, pre_gainer: 2, accumulation: 1}`) — tinggal dipakai.
- **`gate.lane_pauses` dan `gate.lane_wr` sudah dikirim** `/futures/monitor/risk`, tapi
  tak ada satu pun komponen yang membacanya. `GateBanner` hanya membaca `probe_allowed`.

Akibatnya, seseorang yang melihat dashboard akan mengira momentum sedang menunggu sinyal,
padahal lane itu mati; dan mengira bigmover sedang cari peluang, padahal sedang dijeda.
Diamnya scanner tak bisa dibedakan dari tak adanya peluang.

**Rencana:** tampilkan quota lane (0 = MATI) dan lane yang sedang dijeda beserta sisa
waktunya. Datanya sudah tersedia di dua endpoint itu — ini murni sisi tampilan.

**Ukuran:** sedang · **Risiko:** nol (baca-saja)

---

## U2 — Usulan lebar SL berhenti di API 🟠

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

## U3 — Nama parameter tampil mentah 🟡

Sub-tab **4· Penyalaan** merender `r.param` apa adanya: `sl_max_pct`, `failfast_min_sl_gap`,
`entry_tp_ladder`. Tak ada peta label.

Untuk `sl_max_pct` (parameter baru F3) ini bertambah menyesatkan karena **satuannya persen
harga**, sementara tetangganya di layar dinyatakan dalam **kelipatan ATR**. Angka "4,51"
tanpa satuan bisa terbaca sebagai 4,51× ATR — hampir dua kali lipat dari maksudnya.

**Rencana:** peta label + satuan per parameter; tampilkan `4,51%` bukan `4.51`.

**Ukuran:** kecil · **Risiko:** nol

---

## U4 — Komposisi exit hanya terbawa sebagai teks 🟡

F2 menambahkan komposisi alasan tutup ke vonis canary. Karena UI merender `r.reason`
apa adanya, `[sl_hit×8, sl_plus×5, fail_fast×1]` **memang muncul** — tapi sebagai ekor
kalimat panjang berukuran 10px, bukan sebagai bukti yang menonjol.

Padahal justru komposisi itu yang kemarin membalikkan kesimpulan: canary terlihat
"memburuk" padahal parameternya hanya menyentuh 1 dari 14 exit. Respons API juga sudah
membawa `observed.close_reasons` tersendiri, tapi tipe UI belum memuat field itu.

**Rencana:** tampilkan komposisi sebagai baris tersendiri di kartu canary.

**Ukuran:** kecil · **Risiko:** nol

---

## U5 — Halaman Architecture menjelaskan sistem yang sudah berubah 🟢

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
U1 (yang tak terlihat) → U2 (hasil belajar sampai ke mata) → U3 + U4 (mudah disalahbaca) → U5 (dokumentasi)
```

U1 didahulukan karena satu-satunya yang bisa menyebabkan **salah tindakan**: mengira
sistem sedang mencari peluang padahal sedang berhenti. U3 dinaikkan di atas U5 karena
satuan yang salah baca bisa memicu keputusan tala yang keliru.

## Catatan

- Semua fase di sini **baca-saja** — tak satu pun menyentuh keputusan trading.
- Tak ada yang mendesak selama libur: sistem tetap berjalan benar, hanya sebagian
  keadaannya tak terlihat dari layar.
