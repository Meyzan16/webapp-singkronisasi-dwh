"""Agen tunggal harus benar-benar TERSAMBUNG ke pembukaan posisi.

Cacat 9 Sep 2026, dan bentuknya yang paling berbahaya: tak ada error, tak ada
penolakan, tak ada satu baris log pun yang janggal.

`result["agentic"]` disimpan ke store dan dicatat ke log, tapi TIDAK pernah
masuk kolam kandidat `auto_open_positions` — dan tak ada jalur pembukaan lain
di seluruh repo. Jadi agen tunggal memindai 290 simbol, memberi skor,
memeringkat, menampilkan 9-18 kandidat tiap siklus, lalu berhenti di layar.

Dari luar ia tampak bekerja sempurna: saklar menyala, gerbang risiko terbuka,
saldo penuh, kandidat berlimpah — nol posisi. Yang hilang bukan pengaman yang
menolak, melainkan sambungan yang tak pernah ada.
"""

import inspect

import pytest

from agents.futures import auto_trader as AT


# ── Sambungannya sendiri ─────────────────────────────────────────────────────

def test_kandidat_agentic_masuk_kolam_auto_open():
    """Tanpa ini, seluruh rantai Fase 7 berjalan tanpa pernah membuka posisi."""
    from agents.futures import scheduler as S

    sumber = inspect.getsource(S.run_futures_loop)
    assert 'result["agentic"]["results"]' in sumber, (
        "kandidat agen tunggal tak pernah sampai ke auto_open_positions")


# ── Batas-batas harus MELIHAT posisi agen tunggal ────────────────────────────

def test_gaya_futures_memuat_agen_aktif():
    """`_FUTURES_STYLES` dipakai untuk dedup simbol, hitungan posisi terbuka,
    cooldown SL, dan kuota lane. Kalau agen aktif tak ada di dalamnya, posisinya
    tak terhitung oleh SATU PUN batas itu: dua posisi pada simbol yang sama jadi
    mungkin, dan MAX_AUTO_POSITIONS bisa terlampaui tanpa ada yang menahan."""
    from app.services.agent_registry import ACTIVE_FUTURES_AGENTS

    for agen in ACTIVE_FUTURES_AGENTS:
        assert agen in AT._FUTURES_STYLES, f"{agen} tak terlihat oleh batas posisi"


def test_gaya_futures_tetap_memuat_lane_lama():
    """Lane lama masih memegang posisi era sebelumnya sampai yang terakhir tutup
    (syarat Fase 8). Mengeluarkannya membuat posisi itu lolos dari dedup."""
    for lama in ("futures_agent1", "futures_agent2", "futures_agent3",
                 "futures_agent_bigmover"):
        assert lama in AT._FUTURES_STYLES


# ── Ambang skor: penggaris yang benar ────────────────────────────────────────

def test_ambang_agen_aktif_dari_konfigurasinya_sendiri():
    """Skor agen tunggal lahir dari fungsi penilai yang BERBEDA. Menilainya
    dengan ambang adaptif lane lama (72) berarti memakai penggaris agen lain."""
    from agents.futures.agentic import get as ag_get

    assert AT._effective_threshold("futures_agentic") == int(ag_get("agentic_min_score"))


def test_agen_tak_dikenal_jatuh_ke_jalur_adaptif():
    """Fase 8 membuang cabang khusus lane lama. Yang tersisa harus turun anggun
    ke jalur adaptif biasa — bukan melempar."""
    assert isinstance(AT._effective_threshold("futures_entah_apa"), int)


# ── Plafon overekstensi: dikalibrasi untuk penilai yang lain ─────────────────

def test_plafon_overekstensi_tak_memveto_agen_aktif():
    """Plafon 80 dikalibrasi atas skor lane lama (diagnostik 23 Jul: >=80
    berekspektasi -11,28%). Agen tunggal memakai skala berbeda dan menangani
    overekstensi dengan MENGECILKAN ukuran (`size_mult` 0,5), bukan memveto —
    mekanisme yang tak dimiliki lane lama."""
    sumber = inspect.getsource(AT.auto_open_positions)
    assert "_AGEN_AKTIF" in sumber, "plafon masih diterapkan ke agen aktif"


def test_agen_aktif_diturunkan_dari_registry():
    from app.services.agent_registry import ACTIVE_FUTURES_AGENTS

    assert set(AT._AGEN_AKTIF) == set(ACTIVE_FUTURES_AGENTS)


# ── Kandidat agentic cocok dengan yang diharapkan auto_trader ────────────────

def test_bentuk_kandidat_agentic_dikenali_auto_trader():
    """Nama agen dan lane harus persis — `_AGEN_AKTIF` mencocokkan string.
    Salah satu huruf saja dan kandidatnya diam-diam dinilai sebagai lane lama."""
    from agents.futures import agentic as AG

    assert AG.AGENT_NAME in AT._AGEN_AKTIF
    assert AG.AGENT_NAME in AT._FUTURES_STYLES


def test_lane_agentic_tak_terkunci_kuota_lane_lama():
    """`LANE_QUOTAS` hanya memuat lane lama. Agen tunggal sengaja dibatasi
    `MAX_AUTO_POSITIONS` saja — tapi kalau namanya kebetulan masuk kuota lama,
    ia akan terpotong oleh angka yang bukan untuknya."""
    from agents.futures import agentic as AG

    assert AG.LANE not in AT.LANE_QUOTAS


@pytest.mark.parametrize("field", ["agent", "setup_type", "score", "direction", "symbol"])
def test_kandidat_agentic_punya_field_wajib(field):
    """Field yang dibaca `auto_open_positions` dari tiap kandidat."""
    sumber = inspect.getsource(__import__("agents.futures.agentic",
                                          fromlist=["scan_symbol"]).scan_symbol)
    assert f'"{field}"' in sumber


# ── Lane ditulis saat trade dibuat ───────────────────────────────────────────

def test_setup_type_ditulis_saat_pembuatan_trade():
    """Sampai 9 Sep 2026 kolom `setup_type` dibiarkan NULL di sini dan diisi
    backfill di loop monitor LAMA. Posisi agen tunggal lewat `_monitor_agentic`
    — jalur terpisah sejak Fase 7 — jadi tak pernah kebagian backfill itu.

    Akibatnya senyap: `risk_gate` mengelompokkan win-rate per lane lewat
    `t.setup_type or ""`, sehingga trade agen tunggal tak pernah terhitung dan
    proteksi jeda-lane tak melihatnya sama sekali.
    """
    sumber = inspect.getsource(AT.auto_open_positions)
    assert "setup_type       = sig.get" in sumber, (
        "lane tak ditulis saat trade dibuat — kolomnya akan NULL selamanya "
        "untuk agen yang tak lewat loop monitor lama")


def test_jalur_monitor_agentic_menambal_baris_lama():
    """Baris yang sudah terlanjur dibuat tanpa lane harus ikut tertambal."""
    from agents.futures import monitor as M

    sumber = inspect.getsource(M._monitor_agentic)
    assert "trade.setup_type" in sumber
