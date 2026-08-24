# PLAN — Fase Berikutnya (disusun 24 Agu 2026)

> **Status: MENUNGGU PERSETUJUAN PEMILIK. Belum ada satu pun yang dikerjakan.**
>
> Disusun dari state live (DB + endpoint), bukan dari catatan lama. Urutannya
> mengikuti satu aturan: **yang membuat buta didahulukan, lalu yang sedang
> berdarah, baru yang menunggu data.**

## Yang sudah dikerjakan hari ini (di luar rencana ini)

- **Lane `momentum` DIMATIKAN** — `lane_quota_momentum` 2 → **0**, terverifikasi
  terbaca agen. Dasarnya aturan 14-hari di `SCHEDULE_FUTURES`: WR **6,7%** dari 15
  exit, expectancy −3,67/trade, total **−54,99** (82% kerugian futures). Reversibel:
  kembalikan ke 2. Tak ada posisi momentum terbuka saat dimatikan.
- M4b — usulan lebar SL diterbitkan (`188fa32`).
- 3 plan usang disamakan dengan keadaan nyata (`3547910`).

---

## F1 — Endpoint config rusak: seluruh UI tala **buta** ✅ SELESAI `7506e20`

**Hasil.** Endpoint pulih: `errors` kosong, spot 10 kunci / futures 9 / learning 5,
bersih lewat backend maupun proxy frontend.

Audit menyeluruh menemukan **7 atribut hilang, bukan 3** — sisanya tersembunyi
karena error pertama menjatuhkan grup sebelum atribut berikutnya dievaluasi.

Sekalian diperbaiki kekeliruan yang lebih dalam: 6 nilai itu dibaca **langsung dari
atribut modul**, padahal backend dan agen jalan di proses terpisah — jadi yang
tampil selama ini adalah *default*, bukan nilai yang berlaku. Kini lewat `cfg.get()`.
Terbukti: endpoint melaporkan `max_age_fresh 10,0` / `momentum 5,0`, sama persis
dengan yang dicetak agen saat start.

Jaring pengaman 21 test: daftar atribut **dibaca dari sumber**, bukan diketik ulang,
sehingga rujukan yang ditambahkan nanti ikut terjaga. Sudah dibuktikan menangkap
regresi (rujukan sengaja dirusak → 2 test gagal di dua lapis). 370 test lulus.

<details>
<summary>Uraian masalah aslinya</summary>


**Temuan.** `GET /api/v1/agent/config` mengembalikan `{"spot":{},"futures":{},"learning":{}}`
— **kosong untuk ketiga grup** — dengan tiga error:

```
spot     : module 'agents.opportunity.monitor'        has no attribute 'MIN_HOLD_MINUTES'
futures  : module 'agents.futures.monitor'            has no attribute 'FAILFAST_ATR_MULT'
learning : module 'agents.opportunity.weight_updater' has no attribute 'STEP_CAP'
```

**Sebabnya.** M2/M7 memindahkan konstanta ke `monitor_config.py` (`mcfg`/`scfg`),
tapi `backend/app/api/v1/agent_config.py` masih membacanya dari modul lama
(`mon.MIN_HOLD_MINUTES`, `fmon.FAILFAST_ATR_MULT`, `wu.STEP_CAP`).

**Kenapa ini serius.** Justru M2 yang bertujuan "menyambungkan kabel supaya menala
dari UI berpengaruh". Kabelnya tersambung di sisi agen, tapi **jendela untuk
melihatnya pecah** — pemilik tak bisa melihat maupun menala satu pun parameter
lewat UI. Satu atribut hilang menjatuhkan seluruh grup, jadi kerusakannya total,
bukan sebagian.

**Rencana.** Arahkan ketiga rujukan ke sumbernya yang sekarang; tambahkan uji yang
memastikan endpoint ini tak pernah lagi mengembalikan grup kosong tanpa gagal
keras. Agen **tidak** terpengaruh (mereka membaca DB langsung), jadi nol risiko
keputusan trading.

**Ukuran:** kecil · **Risiko:** nol · **Dampak:** mengembalikan seluruh kendali UI

</details>

---

## F2 — Canary yang sedang berjalan sedang memburuk 🔴

`futures/bigmover/failfast_min_sl_gap` (aktif 12 Agu):

| | n | expectancy | WR |
|---|---|---|---|
| baseline | 44 | −0,664 | 61,4% |
| berjalan | 11 | **−2,138** | **27,3%** |

**Rencana.** Periksa ambang keputusan `advance()`: bila 11 sampel sudah cukup untuk
memvonis, biarkan mekanismenya membalik sendiri — itu memang gunanya. Bila
ambangnya lebih tinggi, putuskan sadar: tunggu, atau balikkan lebih awal. Yang
**tidak** boleh adalah membiarkannya tanpa keputusan sambil terus menyentuh posisi
nyata.

**Ukuran:** kecil · **Risiko:** menyentuh keputusan keluar · **Dampak:** hentikan kerugian berjalan

---

## F3 — C2: perbaiki R:R `bigmover` (prioritas #1 dari analisis) 🟠

Bukti paling tajam di seluruh sistem: **bigmover menang 54,5% tapi tetap rugi**
(n=55, expectancy −1,13, total −62,35). Yang salah **bukan seleksi**, melainkan
ukuran menang vs kalah. Karena itu Fase B (bikin seleksi lebih pintar) ditahan —
menaikkan akurasi tak menambal R:R yang rusak.

Modalnya sudah ada dari M4b hari ini:

| | sekarang | usulan | pemenang terpotong |
|---|---|---|---|
| futures/bigmover SL | 1,50× ATR | **0,90×** (−40%, dibatasi dari 0,32) | **0** |

**Rencana.** Jalankan lewat mekanisme yang sudah ada (M5: shadow → canary 1 lane →
active/rolled_back), bukan saklar langsung. Baseline direkam sebelum angka berlaku;
hanya exit sesudah aktivasi yang dihitung. **Menunggu F2 selesai** — dua canary
sekaligus membuat hasilnya mustahil ditafsirkan (disiplin yang ditulis M5 sendiri).

**Ukuran:** sedang · **Risiko:** terkendali lewat rollout · **Dampak:** menyerang sumber kerugian terbesar

---

## F4 — Jeda lane lupa ingatan tiap restart 🟡

`_lane_paused_until` dan `_lane_pause_streak` hidup **hanya di memori**. Setiap
restart backend, hitungan pengulangan kembali ke nol, sehingga jeda berlipat yang
dirancang (24 j → 48 j → … → 168 j) **tak pernah benar-benar berlipat**.

Komentar di kodenya sendiri menyebut `momentum` "menjadi pintu putar dua kali dalam
sehari" — sebagian justru karena penjaga ini kehilangan ingatannya. Pola yang sama
pernah ditemukan di state learning; obatnya juga sama: simpan.

**Catatan:** dampaknya berkurang setelah `momentum` dimatikan hari ini, tapi
penjaganya tetap tumpul untuk lane lain.

**Ukuran:** kecil–sedang · **Risiko:** rendah · **Dampak:** penjaga bekerja seperti yang dirancang

---

## F5 — Menunggu data (nol kerja kode)

| Item | Sekarang | Ambang |
|---|---|---|
| M3 — usul otomatis `fail_fast` | 3 sampel | 5 per lane |
| M4b futures — lampu hijau tingkat-market | `mae_n` 21 | 30 |
| Fase D — promosi model | 2 gate blokir (`outcome_completeness`, `walkforward_passed`) | — |
| PLAN-LIVE-TRADING | WR fut 44,7% / spot 47,1% | ≥ 55% + 100 closed |

Tak ada yang bisa dipercepat dengan menulis kode. Yang mempercepatnya: F2 + F3
membuat trade berikutnya lebih sehat.

---

## Urutan yang disarankan

```
F1 ✅ selesai  →  F2 (hentikan yang berdarah)  →  F3 (perbaiki sumbernya)  →  F4
                  ↑ berikutnya
```

F1 lebih dulu karena tanpa UI yang hidup, F2 dan F3 dinilai dari terminal saja.
F3 sengaja **setelah** F2: satu canary pada satu waktu.

## Aturan yang tetap berlaku

- Apa pun yang menyentuh keputusan trading masuk **di belakang flag, default MATI**.
- Rekomendasi mesin boleh ditulis; **penyalaan tetap keputusan pemilik**.
- Lane bersampel < 8 tidak menghasilkan rekomendasi.
