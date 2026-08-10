"""Satu definisi "menang", dijaga di semua titik yang menggerakkan keputusan.

Terukur 10 Agu 2026: FUTURES punya 21 trade untung dan **20 dilabeli KALAH**,
karena 15+ tempat menulis `status == "tp" and pnl > 0`. `status` menyimpan
MEKANISME penutup, bukan hasilnya — trailing stop di atas entry (`sl_plus`)
menutup dengan status="sl" walau untung.

Ini bukan salah ketik di satu tempat, melainkan satu baris yang disalin berulang
sampai tak ada lagi yang menyadarinya. Karena itu yang dijaga di sini bukan
hasilnya saja, tapi juga bahwa titik-titik itu memakai SATU fungsi bersama.
"""

import inspect
import pathlib

import pytest

from agents.shared.trade_outcome import is_win, is_closed, win_loss


class _T:
    def __init__(self, status, pnl_pct):
        self.status = status
        self.pnl_pct = pnl_pct


# ── Definisi ─────────────────────────────────────────────────────────────────

def test_trailing_stop_di_atas_entry_adalah_kemenangan():
    """`sl_plus`: 20 dari 21 kemenangan futures. Inilah kasus yang dulu hilang."""
    assert is_win(_T("sl", 2.03)) is True


def test_status_tp_dengan_pnl_negatif_bukan_kemenangan():
    """Masalah ASLI yang dulu mau diperbaiki — tetap harus tertangani."""
    assert is_win(_T("tp", -0.16)) is False


def test_impas_bukan_kemenangan():
    assert is_win(_T("sl", 0.0)) is False


def test_pnl_kosong_tak_meledak():
    assert is_win(_T("sl", None)) is False


def test_hanya_trade_selesai_yang_dihitung():
    assert is_closed(_T("open", 5.0)) is False
    menang, total = win_loss([_T("sl", 2.0), _T("tp", -0.2), _T("open", 9.9)])
    assert (menang, total) == (1, 2)


# ── Titik yang menggerakkan keputusan ────────────────────────────────────────

def test_risk_gate_memakai_definisi_bersama():
    """Ini yang paling merugikan: lane `bigmover` terlihat ber-WR 4% (nyatanya
    64%), lalu dipotong setengah ukuran dan dijeda oleh penjaganya sendiri."""
    from agents.futures import risk_gate
    src = inspect.getsource(risk_gate)
    assert "trade_outcome import is_win" in src
    assert 't.status == "tp" and (t.pnl_pct or 0) > 0' not in src


def test_weight_updater_memakai_definisi_bersama():
    """Paling dalam dampaknya: SETIAP bobot sinyal futures dilatih dari label
    ini. Terbalik di sini berarti mesin belajar mengejar arah yang salah."""
    from agents.futures import weight_updater
    src = inspect.getsource(weight_updater)
    assert "trade_outcome import is_win" in src
    assert 'status == "tp" and (t.pnl_pct or 0.0) > 0' not in src
    assert 'status == "tp" and (trade.pnl_pct or 0.0) > 0' not in src


@pytest.mark.parametrize("modul", [
    "app/api/v1/history.py",
    "app/api/v1/futures_learning.py",
    "app/services/paper_trader/paper_trader.py",
])
def test_titik_backend_memakai_definisi_bersama(modul):
    src = pathlib.Path(modul).read_text(encoding="utf-8")
    assert "trade_outcome import is_win" in src, f"{modul} punya definisi sendiri"


def test_filter_sql_history_sepakat_dengan_penghitung_python():
    """Daftar trade dan angka ringkasan dibaca dari dua jalur berbeda. Aturan
    yang berbeda membuat halaman menampilkan dua kebenaran sekaligus."""
    src = pathlib.Path("app/api/v1/history.py").read_text(encoding="utf-8")
    assert 'PaperTrade.status == "tp", PaperTrade.pnl_pct > 0' not in src
    assert 'PaperTrade.pnl_pct > 0' in src


def test_signal_performance_menghitung_menang_dari_pnl():
    src = pathlib.Path("app/api/v1/signals.py").read_text(encoding="utf-8")
    assert "case((PaperTrade.pnl_pct > 0, 1)" in src
    assert 'case((PaperTrade.status == "tp", 1)' not in src


def test_notifier_menandai_untung_sebagai_menang():
    """Ikon ❌ pada trade yang UNTUNG muncul di Telegram tiap hari."""
    from agents.notify import trade_watcher
    src = inspect.getsource(trade_watcher)
    assert 'icon = "✅" if is_win(t)' in src


def test_tak_ada_definisi_menang_tersembunyi_yang_tersisa():
    """Penjaga pola: bentuk lama tak boleh kembali lewat file mana pun."""
    akar = pathlib.Path("..")
    pola = 'status == "tp" and'
    tersisa = []
    for f in list((akar / "agents").rglob("*.py")) + list((akar / "backend/app").rglob("*.py")):
        # File definisinya sendiri MENGUTIP pola lama untuk menjelaskannya.
        if "__pycache__" in str(f) or f.name == "trade_outcome.py":
            continue
        teks = f.read_text(encoding="utf-8", errors="ignore")
        if pola in teks and "trade_outcome" not in teks:
            tersisa.append(str(f))
    assert not tersisa, f"definisi menang lama masih ada di: {tersisa}"
