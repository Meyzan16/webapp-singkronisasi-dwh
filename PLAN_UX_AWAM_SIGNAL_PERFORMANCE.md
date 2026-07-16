# PLAN — UX Awam: Signal Performance harus bisa dibaca orang non-teknis

Tanggal: 2026-07-16 · Status: SELESAI (semua item U1–U5 terverifikasi live di browser)

## Masalah (feedback owner)

Halaman Signal Performance (Overview / Engine / Signals / Analysis) penuh jargon
teknis: Brier, OOS, PF, expectancy, shadow/canary/champion, mature samples,
reason code mentah (`below_auto_threshold`). Orang awam tidak bisa menjawab:

1. **Apakah sistem ini sedang bekerja atau tidak?**
2. **Apa yang sudah dipelajari / diungkapkan sistem?**
3. **Outputnya apa dan di mana melihatnya?**

## Solusi (additive — tidak menghapus info teknis, hanya menambah lapisan awam)

- [x] **U1 — Ringkasan Awam di Overview**: banner 3 kartu menjawab langsung
      "Apakah sistem bekerja?" (dari scan health), "Apa yang dipelajari?"
      (learned keys + ledger), "Apa outputnya?" (paper trades → halaman History),
      semua kalimat Bahasa Indonesia polos + indikator ✓/⚠.
- [x] **U2 — Baris "Artinya" di kedua panel engine** (SPOT & FUTURES): terjemahan
      status collecting/ready_to_train/shadow/canary/champion + learning
      warming/active ke satu kalimat awam (mis. shadow = "model AI memprediksi
      tapi TIDAK memengaruhi trading — masih diawasi, aman").
- [x] **U3 — Terjemahan reason code**: peta `below_auto_threshold` → "Skor di
      bawah ambang minimal" dst. di panel "Kenapa tidak dibuka".
- [x] **U4 — Glosarium mini di seksi Engine**: Brier, expectancy, PF, OOS,
      shadow/canary/champion, mature samples — 1 kalimat awam per istilah.
- [x] **U5 — Verifikasi browser**: lint + tsc bersih, keempat seksi dirender
      dengan data live, 0 console error, screenshot bukti.

## Guardrail

- Hanya `frontend/src/features/signals/page.tsx` (tidak menyentuh endpoint/engine).
- Semua angka tetap dari data live — tidak ada teks status yang hardcoded
  menyesatkan (kalimat dipilih dari state nyata).
