# Laporan CO harian

Diisi otomatis oleh **AgentsTrading-CO** (Task Scheduler, tiap 06:15 WIB) yang menjalankan
Claude Code headless (Opus 5) dengan brief di `ops/co-brief.md`.

Satu berkas per hari: `YYYY-MM-DD.md`, berisi:

1. **Angka hari ini** — hasil query nyata ke API/DB (bukan perkiraan)
2. **Temuan** + apa yang diubah + hasil verifikasi (py_compile / tsc / build)
3. **Flag yang menunggu persetujuan owner** — perubahan yang menyentuh keputusan
   trading selalu dipasang default OFF
4. **Yang belum bisa disimpulkan** dan butuh data lebih

Folder ini sengaja **tracked di git** (berbeda dari `ops/` yang di-gitignore) supaya
riwayat keputusan agent bisa ditelusuri lewat sejarah commit.

Jadwal dipilih 06:15 karena backend masih hidup (berhenti 07:00), sehingga CO bisa
membaca API + PostgreSQL + log semalam penuh. Setelah 07:00 hanya DB yang tersedia.
