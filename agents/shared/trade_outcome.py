"""Satu definisi "menang" untuk seluruh proyek.

Terukur 10 Agu 2026 — inilah sebabnya file ini ada:

    FUTURES: 21 trade untung, **20 di antaranya dilabeli KALAH**.

Penyebabnya satu baris yang diulang di 15+ tempat:

    is_win = t.status == "tp" and t.pnl_pct > 0        # SALAH

`status` menyimpan MEKANISME yang menutup posisi, bukan hasilnya. Trailing stop
yang bergerak di atas entry menutup dengan `status="sl"` walau membukukan untung
— itulah `sl_plus`, dan di futures ia menyumbang 20 dari 21 kemenangan. Syarat
`status == "tp"` karena itu membuang hampir seluruh kemenangan futures.

Akibatnya bukan sekadar angka laporan yang keliru:

  * `risk_gate` melihat lane `bigmover` ber-WR 4% (sebenarnya 64%) lalu
    memotong ukurannya setengah dan menjedanya — justru lane yang paling
    menguntungkan.
  * `weight_updater` melatih SETIAP bobot sinyal futures dari label terbalik.

Syarat `status == "tp"` dulu ditambahkan untuk memperbaiki bug lain: baris
ber-`status="tp"` tapi P&L negatif sempat terhitung menang. Itu benar sebagai
masalah, tapi obatnya salah sasaran — cukup lihat P&L-nya.

SPOT tidak terkena: monitornya menandai exit untung sebagai `status="tp"`, jadi
0 dari 30 kemenangannya salah label. Fungsi ini tetap dipakai kedua market
supaya perbedaan itu tak pernah lahir lagi.
"""

from __future__ import annotations


def is_win(trade) -> bool:
    """Menang = MEMBUKUKAN UNTUNG. Titik.

    Sengaja TIDAK melihat `status`: mekanisme penutup (tp / sl / trailing) tak
    menentukan apakah sebuah trade menguntungkan.
    """
    return (trade.pnl_pct or 0.0) > 0


def is_closed(trade) -> bool:
    """Sudah selesai — hanya trade selesai yang boleh masuk hitungan hasil."""
    return trade.status in ("tp", "sl")


def win_loss(trades) -> tuple[int, int]:
    """`(menang, total)` atas trade yang sudah selesai."""
    selesai = [t for t in trades if is_closed(t)]
    return sum(1 for t in selesai if is_win(t)), len(selesai)
