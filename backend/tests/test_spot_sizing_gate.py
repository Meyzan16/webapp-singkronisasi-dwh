"""Jaring pengaman gerbang ukuran posisi SPOT (9 Agu 2026).

Gerbang ini sempat memblokir 100% auto-open: scanner menemukan kandidat berskor
90–108, tapi notional yang dihitung ($54–70) selalu di bawah ambang $161. Karena
tak ada trade baru, SELURUH mesin belajar ikut macet — bobot adaptif, model, dan
canary sama-sama kelaparan data (15 entry dalam 14 hari, nol posisi terbuka).

CATATAN saat menulis test ini: versi pertama memodelkan sendiri rantai risiko
(`balance × 1%`) dan salah — fungsi sebenarnya memakai conviction scaling DAN rem
drawdown (risiko dibagi dua saat drawdown >10%, yang sedang aktif). Karena itu
test di bawah menguji GERBANGNYA langsung dengan notional yang sudah jadi, bukan
menebak berapa notional yang akan dihasilkan.
"""

import pytest

from app.api.v1.balance import (
    MIN_NOTIONAL_ABS, MIN_NOTIONAL_FRACTION,
    MAX_CONCURRENT_POSITIONS, MAX_NOTIONAL_FRACTION,
)

#: Balance nyata saat temuan ini diukur — dipakai agar angka punya makna.
BALANCE = 1070.0


def _min_notional(balance: float) -> float:
    """Salinan rumus gerbang. Yang berlaku adalah yang TERBESAR dari keduanya."""
    return max(MIN_NOTIONAL_ABS, balance * MIN_NOTIONAL_FRACTION)


def test_kedua_lantai_harus_turun_bersama():
    """Menurunkan salah satu saja sering tak berefek: dengan balance $1.070,
    ABS 150→50 sambil membiarkan FRACTION 15% tetap menghasilkan max(50, 160)=160.
    Itu membuat perbaikan tampak selesai padahal gerbangnya tak bergerak."""
    assert _min_notional(BALANCE) < 100, "gerbang masih setinggi sebelum perbaikan"
    # Keduanya harus sebanding; kalau ABS jauh di atas fraksi, fraksi jadi hiasan.
    assert MIN_NOTIONAL_ABS <= BALANCE * MIN_NOTIONAL_FRACTION * 2


def test_notional_lane_nyata_lolos_gerbang():
    """Notional yang BENAR-BENAR dihasilkan tiap lane (diukur langsung dari
    compute_spot_sizing pada 9 Agu, dengan rem drawdown aktif) harus lolos.
    Kalau tidak, sistem kembali ke kondisi nol trade."""
    minimum = _min_notional(BALANCE)
    for lane, notional in (("accumulation", 75.28), ("bigmover", 129.0), ("breakout", 251.0)):
        assert notional >= minimum, f"lane {lane} terblokir: ${notional} < ${minimum:.0f}"


def test_penjaga_debu_masih_menolak_posisi_patologis():
    """Melonggarkan gerbang tak boleh berarti mematikannya: SL sangat lebar tetap
    menghasilkan posisi terlalu kecil untuk menutup biaya. Angka di bawah juga
    diukur langsung dari compute_spot_sizing."""
    minimum = _min_notional(BALANCE)
    for sl_pct, notional in ((15.0, 35.68), (25.0, 21.41)):
        assert notional < minimum, f"SL {sl_pct}% seharusnya diblokir"


def test_konsentrasi_saat_portofolio_penuh_masuk_akal():
    """Argumen utama perubahan ini: minimum $161 pada batas 5 posisi berarti 75%
    akun terpakai saat penuh. Lantai yang lebih rendah MENGURANGI konsentrasi —
    jadi ini bukan melonggarkan disiplin, melainkan memperbaikinya."""
    porsi_penuh = _min_notional(BALANCE) * MAX_CONCURRENT_POSITIONS / BALANCE
    assert porsi_penuh <= 0.40, f"portofolio penuh memakai {porsi_penuh:.0%} akun"
    assert MIN_NOTIONAL_FRACTION < MAX_NOTIONAL_FRACTION


@pytest.mark.asyncio
async def test_gerbang_hidup_memang_meloloskan_lane_nyata():
    """Uji terhadap fungsi SEBENARNYA, bukan salinan rumus — supaya perubahan di
    rantai risiko (conviction scaling, rem drawdown) ikut tertangkap."""
    from app.database import is_db_available
    if not is_db_available():
        pytest.skip("butuh DB hidup")
    from app.api.v1.balance import compute_spot_sizing
    hasil = await compute_spot_sizing(score=90, risk_pct=7.11)   # accumulation
    assert hasil["can_open"], hasil["reason"]
