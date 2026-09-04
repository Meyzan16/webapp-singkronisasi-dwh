"use client";

/**
 * Penanda lane yang sedang DIJEDA — beda dari lane mati: sementara, kembali sendiri.
 * Karena itu lane dijeda tetap ditampilkan; kalau ikut disembunyikan, orang akan
 * mengira lane-nya dimatikan.
 *
 * `now` WAJIB diteruskan dari payload server (`generated_at`), bukan dibaca dengan
 * `Date.now()` di sini: memanggil jam saat render membuat hasilnya berubah tiap kali
 * komponen kebetulan dirender ulang, dan jam klien yang meleset menampilkan sisa
 * waktu yang salah.
 */
export function PauseBadge({ until, now }: { until?: number; now: number }) {
  if (!until) return null;
  const sisaJam = (until - now) / 3600;
  if (sisaJam <= 0) return null;
  const teks = sisaJam >= 1 ? `${sisaJam.toFixed(1)} j lagi` : `${Math.round(sisaJam * 60)} mnt lagi`;
  return (
    <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-full border bg-yellow-50 text-yellow-700 border-yellow-300"
          title="Lane dijeda otomatis karena win rate rendah — akan aktif lagi sendiri">
      ⏸ dijeda · {teks}
    </span>
  );
}
