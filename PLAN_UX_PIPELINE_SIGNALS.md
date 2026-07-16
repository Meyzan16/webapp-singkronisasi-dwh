# PLAN — UX Pipeline Live + Konsistensi Signals + Tab Perbaikan

Tanggal: 2026-07-16 · Status: SELESAI (terverifikasi live di browser) · Lanjutan PLAN_UX_AWAM_SIGNAL_PERFORMANCE

## Masalah (feedback owner)

1. Tidak ada gambaran PIPELINE bagaimana SPOT & FUTURES bekerja dari collect
   sampai model dipakai — status tiap tahap harus live.
2. Seksi Signals tidak konsisten: SPOT (tabel polos) vs Futures (panel engine +
   tabel) vs Cross-Agent (kartu) — pola beda-beda, tanpa penjelasan kolom.
3. Seksi Analysis tidak jelas fungsinya (regime/formulas/rejections/predictive
   untuk apa?), dan TIDAK ADA tab "perbaikan live" yang menunjukkan apa yang
   sedang diperbaiki sistem untuk SPOT & FUTURES.

## Solusi (frontend only — `frontend/src/features/signals/page.tsx`)

- [x] **P1 — PipelineLive di seksi Engine**: dua baris (SPOT & FUTURES), tahap
      Scan → Catat Keputusan → Cek Hasil → Belajar Bobot → Latih Model →
      Shadow → Canary → Champion; tiap tahap berisi angka live + status
      (hijau=berjalan, biru=posisi model sekarang, abu=belum).
- [x] **P2 — Signals konsisten**: ketiga subtab pakai pola sama
      (banner "Untuk apa?" + kontrol + tabel). Panel engine futures DIPINDAH
      dari Signals→Futures (sudah ada di Engine & Overview — duplikat).
- [x] **P3 — Banner "Untuk apa?"** di keempat tab Analysis (regime, formulas,
      rejections, predictive) dalam bahasa awam.
- [x] **P4 — Tab baru Analysis → 🔧 Perbaikan (default)**: bobot yang sedang
      dinaikkan/diturunkan (SPOT & FUTURES), kandidat veto futures (weight<0.8
      n≥10), koin blacklist, lane dijeda, hasil review mingguan
      (/predictive/signal_review) bila sudah jalan.
- [x] **P5 — Verifikasi browser**: tsc+lint bersih, semua seksi live, 0 console
      error.

## Tambahan (permintaan lanjutan owner, 16 Jul)

- [x] **P6 — Tab Analysis → 💡 Saran Engine**: rekomendasi perbaikan yang
      dihasilkan engine dari datanya sendiri, terkategori SPOT + 4 lane futures
      (Pre-Gainer, Accumulation, Momentum, BigMover) supaya scanner terus
      bertumbuh. Backend baru `GET /signals/recommendations` (read-only,
      rule-based): trade 7 hari (WR/PnL), near-miss rejection 48 jam, akurasi
      predictive per arah 7 hari, bobot sinyal ekstrem, status pause lane.
      Severity: action / watch / good. Frontend: subtab + kartu per kategori,
      selalu di-fetch segar saat tab dibuka.
