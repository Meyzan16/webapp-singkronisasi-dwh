"""Backfill big-mover: ambil klines serentak, bukan satu per satu.

Terukur 9 Sep 2026: `backfill_pending` menahan loop scan 45,2 detik. Sebabnya
bukan kerja berat — hanya 150 permintaan HTTP yang dikirim BERURUTAN, masing-
masing ~300 ms. Docstring aslinya menyebut ini "trivial", dan itu benar untuk
bobot API; yang tidak trivial adalah waktunya, karena `run_due()` ditunggu di
dalam loop scan.

Dua sifat yang dijaga di sini, keduanya bisa rusak tanpa terlihat:
  1. Urutan hasil HARUS sama dengan urutan baris — pemanggilnya memakai `zip`,
     jadi hasil yang tertukar akan menulis P&L satu koin ke baris koin lain.
  2. Konkurensinya HARUS berbatas — `gather` tanpa semafor melepas 150 permintaan
     sekaligus dan mengundang rate-limit ban dari Binance.
"""

import asyncio

import pytest

from app.services import big_mover_logger as B


class BarisPalsu:
    def __init__(self, symbol: str, tunda: float = 0.0):
        self.symbol = symbol
        self.market = "futures"
        self.ts = 1_700_000_000.0
        self.tunda = tunda


@pytest.fixture
def catat(monkeypatch):
    """Ganti pengambil jaringan dengan yang bisa diamati."""
    keadaan = {"berjalan": 0, "puncak": 0, "urutan": []}

    async def palsu(client, symbol, market, start_ts, limit=180):
        keadaan["berjalan"] += 1
        keadaan["puncak"] = max(keadaan["puncak"], keadaan["berjalan"])
        keadaan["urutan"].append(symbol)
        await asyncio.sleep(0.01)
        keadaan["berjalan"] -= 1
        return [symbol]                      # penanda: dari simbol mana hasil ini

    monkeypatch.setattr(B, "_fetch_klines_1h", palsu)
    return keadaan


@pytest.mark.asyncio
async def test_hasil_berpasangan_dengan_barisnya(catat):
    """Kalau urutan tertukar, P&L satu koin ditulis ke baris koin lain — dan
    tak ada yang error, angkanya hanya salah."""
    rows = [BarisPalsu(f"COIN{i}USDT") for i in range(20)]
    hasil = await B._ambil_klines_serentak(None, rows)

    assert len(hasil) == len(rows)
    for baris, klines in zip(rows, hasil):
        assert klines == [baris.symbol]


@pytest.mark.asyncio
async def test_konkurensi_dibatasi_semafor(catat):
    """Tanpa batas, 150 baris melepas 150 permintaan sekaligus."""
    rows = [BarisPalsu(f"COIN{i}USDT") for i in range(60)]
    await B._ambil_klines_serentak(None, rows)

    assert catat["puncak"] <= B._BACKFILL_CONCURRENCY
    assert catat["puncak"] > 1, "tidak serentak sama sekali — perbaikannya hilang"


@pytest.mark.asyncio
async def test_benar_benar_lebih_cepat_dari_berurutan(catat):
    """Inti perbaikannya, diukur bukan diasumsikan."""
    rows = [BarisPalsu(f"COIN{i}USDT") for i in range(40)]

    mulai = asyncio.get_event_loop().time()
    await B._ambil_klines_serentak(None, rows)
    serentak = asyncio.get_event_loop().time() - mulai

    berurutan = 40 * 0.01          # kalau dikerjakan satu per satu
    assert serentak < berurutan / 2


@pytest.mark.asyncio
async def test_satu_simbol_gagal_tak_menjatuhkan_seluruh_angkatan(monkeypatch):
    """`_fetch_klines_1h` menelan kegagalannya sendiri dan mengembalikan [].
    Kalau suatu saat ia dibuat melempar, `gather` akan membatalkan sisanya —
    satu koin bermasalah menghapus 149 baris lain dari backfill siklus itu."""
    async def kadang_kosong(client, symbol, market, start_ts, limit=180):
        return [] if symbol == "RUSAKUSDT" else [symbol]

    monkeypatch.setattr(B, "_fetch_klines_1h", kadang_kosong)
    rows = [BarisPalsu("AUSDT"), BarisPalsu("RUSAKUSDT"), BarisPalsu("BUSDT")]
    hasil = await B._ambil_klines_serentak(None, rows)

    assert hasil == [["AUSDT"], [], ["BUSDT"]]


@pytest.mark.asyncio
async def test_daftar_kosong_tak_menyentuh_jaringan(catat):
    assert await B._ambil_klines_serentak(None, []) == []
    assert catat["urutan"] == []
