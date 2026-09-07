"""Penjadwal pekerjaan berkala FUTURES (§8.6).

Yang diuji di sini adalah tiga kegagalan senyap yang jadi alasan modul ini ada:
hitungan siklus yang kembali nol saat restart, jendela kalender yang terlewat
saat scanner berhenti, dan irama scan yang menyetir irama belajar.
"""

import datetime as dt

import pytest

from agents.futures import jobs as J


def ts(y, m, d, h=0, mi=0) -> float:
    return dt.datetime(y, m, d, h, mi, tzinfo=dt.timezone.utc).timestamp()


@pytest.fixture(autouse=True)
def bersih():
    J._last_run.clear()
    J._loaded = True                 # jangan sentuh DB dari tes
    J._ada_outcome_baru = False
    yield
    J._last_run.clear()
    J._loaded = False


# ── Jadwal berulang ──────────────────────────────────────────────────────────

def test_interval_terlambat_saat_belum_pernah_jalan():
    p = J.Pekerjaan(nama="x", jadwal=J.Jadwal(every_sec=600), jalankan=None)  # type: ignore[arg-type]
    assert J.terlambat(p, ts(2026, 9, 6, 12))


def test_interval_belum_terlambat_sebelum_waktunya():
    p = J.Pekerjaan(nama="x", jadwal=J.Jadwal(every_sec=600), jalankan=None)  # type: ignore[arg-type]
    now = ts(2026, 9, 6, 12)
    J._last_run["x"] = now - 300                 # baru 5 menit lalu
    assert not J.terlambat(p, now)
    J._last_run["x"] = now - 900                 # 15 menit lalu
    assert J.terlambat(p, now)


# ── Jadwal kalender: semantik TERLAMBAT, bukan "sedang di jendelanya" ────────

def test_mingguan_batasnya_hari_yang_ditentukan():
    w = J.Jadwal(weekly_on=6, weekly_hour=0)     # Minggu 00:00
    # 6 Sep 2026 adalah hari Minggu
    assert dt.datetime(2026, 9, 6).weekday() == 6
    assert w.batas_terakhir(ts(2026, 9, 6, 12)) == ts(2026, 9, 6, 0)


def test_mingguan_masih_terlambat_saat_scanner_baru_nyala_senin():
    """Inti perbaikannya. Cara lama menuntut siklus scan mendarat di jendela
    dua menit Minggu 00:00; kalau scanner mati, backtest terlewat SEMINGGU.
    Sekarang ia tetap jalan — terlambat, tapi jalan."""
    p = J.Pekerjaan(nama="wk", jadwal=J.Jadwal(weekly_on=6, weekly_hour=0),
                    jalankan=None)  # type: ignore[arg-type]
    J._last_run["wk"] = ts(2026, 8, 30, 0)       # terakhir jalan Minggu sebelumnya
    assert J.terlambat(p, ts(2026, 9, 7, 9))     # Senin 09:00 -> masih terlambat


def test_mingguan_tidak_jalan_dua_kali_dalam_minggu_yang_sama():
    p = J.Pekerjaan(nama="wk", jadwal=J.Jadwal(weekly_on=6, weekly_hour=0),
                    jalankan=None)  # type: ignore[arg-type]
    J._last_run["wk"] = ts(2026, 9, 6, 0, 5)     # sudah jalan Minggu ini
    assert not J.terlambat(p, ts(2026, 9, 6, 12))
    assert not J.terlambat(p, ts(2026, 9, 8, 12))
    assert J.terlambat(p, ts(2026, 9, 13, 1))    # Minggu berikutnya


def test_bulanan_batasnya_tanggal_satu():
    m = J.Jadwal(monthly_day=1, monthly_hour=0)
    assert m.batas_terakhir(ts(2026, 9, 20, 12)) == ts(2026, 9, 1, 0)
    # Tepat DI batas sudah terhitung waktunya — bukan menunggu satu detik lagi.
    assert m.batas_terakhir(ts(2026, 9, 1)) == ts(2026, 9, 1, 0)
    # Sedetik SEBELUM batas, yang berlaku masih bulan sebelumnya.
    assert m.batas_terakhir(ts(2026, 9, 1) - 1) == ts(2026, 8, 1, 0)


def test_bulanan_menyeberang_tahun():
    """Cabang "mundur satu bulan" hanya tersentuh bila tanggalnya belum lewat —
    jadi diuji dengan tanggal 15, bukan 1."""
    m = J.Jadwal(monthly_day=15, monthly_hour=0)
    assert m.batas_terakhir(ts(2026, 1, 5, 12)) == ts(2025, 12, 15, 0)
    assert m.batas_terakhir(ts(2026, 1, 20, 12)) == ts(2026, 1, 15, 0)


# ── Pelaksanaan ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kegagalan_tak_menandai_sudah_jalan(monkeypatch):
    """Pekerjaan yang gagal harus DICOBA LAGI siklus berikutnya, bukan
    dianggap selesai dan terlewat sampai jadwal berikutnya."""
    async def meledak():
        raise RuntimeError("gagal")

    p = J.Pekerjaan(nama="rusak", jadwal=J.Jadwal(every_sec=60), jalankan=meledak)
    monkeypatch.setattr(J, "daftar_pekerjaan", lambda: [p])
    monkeypatch.setattr(J, "simpan_state", lambda: _noop())

    hasil = await J.run_due(ts(2026, 9, 6, 12))
    assert hasil["gagal"] == ["rusak"]
    assert "rusak" not in J._last_run


@pytest.mark.asyncio
async def test_satu_pekerjaan_gagal_tak_menghentikan_yang_lain(monkeypatch):
    jalan: list[str] = []

    async def meledak():
        raise RuntimeError("gagal")

    async def sukses():
        jalan.append("ok")

    monkeypatch.setattr(J, "daftar_pekerjaan", lambda: [
        J.Pekerjaan(nama="rusak", jadwal=J.Jadwal(every_sec=60), jalankan=meledak),
        J.Pekerjaan(nama="baik", jadwal=J.Jadwal(every_sec=60), jalankan=sukses),
    ])
    monkeypatch.setattr(J, "simpan_state", lambda: _noop())

    hasil = await J.run_due(ts(2026, 9, 6, 12))
    assert jalan == ["ok"]
    assert hasil["dijalankan"] == ["baik"] and hasil["gagal"] == ["rusak"]


@pytest.mark.asyncio
async def test_yang_belum_terlambat_dilewati(monkeypatch):
    jalan: list[str] = []

    async def kerja():
        jalan.append("x")

    p = J.Pekerjaan(nama="x", jadwal=J.Jadwal(every_sec=600), jalankan=kerja)
    monkeypatch.setattr(J, "daftar_pekerjaan", lambda: [p])
    monkeypatch.setattr(J, "simpan_state", lambda: _noop())

    now = ts(2026, 9, 6, 12)
    J._last_run["x"] = now - 60
    await J.run_due(now)
    assert jalan == []


async def _noop():
    return None


# ── Tanda outcome baru ───────────────────────────────────────────────────────

def test_tanda_outcome_baru_baca_lalu_hapus():
    """Satu kedatangan outcome tak boleh memicu latihan berkali-kali."""
    J._ada_outcome_baru = True
    assert J.ambil_outcome_baru() is True
    assert J.ambil_outcome_baru() is False


# ── Kelengkapan daftar ───────────────────────────────────────────────────────

def test_semua_pekerjaan_lama_terdaftar():
    """Kalau satu tertinggal, ia mati SENYAP — tak ada error, hanya pelajaran
    yang berhenti datang."""
    nama = {p.nama for p in J.daftar_pekerjaan()}
    for wajib in ("outcome_pass", "big_mover_backfill", "predictive_resolve",
                  "predictive_repair", "repair_verifier", "prune_old_events",
                  "prune_predictive_log", "prune_rejection_log",
                  "weekly_backtest", "weekly_signal_review", "monthly_calibration"):
        assert wajib in nama, wajib


def test_pekerjaan_pembelajaran_ditandai_kritis():
    """Kegagalannya wajib WARNING — pekerjaan mingguan/bulanan yang gagal diam
    tak akan ketahuan sampai berminggu-minggu."""
    kritis = {p.nama for p in J.daftar_pekerjaan() if p.kritis}
    for wajib in ("outcome_pass", "weekly_backtest", "weekly_signal_review",
                  "monthly_calibration"):
        assert wajib in kritis, wajib


def test_tiap_pekerjaan_punya_jadwal_dan_catatan():
    for p in J.daftar_pekerjaan():
        punya_jadwal = (p.jadwal.every_sec or p.jadwal.weekly_on is not None
                        or p.jadwal.monthly_day is not None)
        assert punya_jadwal, f"{p.nama} tanpa jadwal — akan jalan tiap siklus"
        assert p.catatan, f"{p.nama} tanpa catatan"


def test_status_melaporkan_semua_pekerjaan():
    """Cara lama tak menyediakan cara apa pun untuk mengetahui sebuah pekerjaan
    sudah lama tak jalan, selain membaca kode."""
    st = J.status()
    assert set(st) == {p.nama for p in J.daftar_pekerjaan()}
    for v in st.values():
        assert set(v) == {"terakhir_jalan", "umur_jam", "terlambat", "catatan"}
