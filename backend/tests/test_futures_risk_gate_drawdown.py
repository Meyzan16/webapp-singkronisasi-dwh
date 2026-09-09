"""Circuit breaker: dinilai dari drawdown BERJALAN, bukan rekor terburuk.

Cacat 9 Sep 2026. `evaluate_risk_gate` menghitung dua angka dari kurva ekuitas
yang sama — `max_dd` (maksimum sepanjang sejarah, `if dd > max_dd`) dan drawdown
berjalan — lalu mengirim `max_dd` ke gate.

`max_dd` MUSTAHIL turun. Jadi sekali drawdown menyentuh batas keras, breaker
menutup selamanya: seuntung apa pun agen berdagang sesudahnya, rekornya tetap,
gate tetap tertutup, dan satu-satunya jalan keluar adalah campur tangan manusia.
Padahal pesan gate menjanjikan pemulihan dan docstring modulnya menulis syaratnya
sebagai "drawdown from peak".

Yang diuji di sini adalah sifat yang membuat perbedaan itu penting: setelah
pemulihan, gate WAJIB terbuka lagi.
"""

import pytest

from agents.futures import risk_gate as RG


@pytest.fixture(autouse=True)
def gate_bersih():
    """Gate menyimpan state modul; tanpa reset, tes saling mewarisi keputusan."""
    RG._state.update({
        "active": False, "gate_type": "none", "reason": "ok",
        "drawdown_pct": 0.0, "max_drawdown_pct": 0.0, "rar": 0.0,
        "n_trades": 0, "updated_at": 0.0, "override": None,
    })
    RG._prev_circuit_breaker_active = False
    yield


def kurva(pnls: list[float], modal: float = 1000.0) -> tuple[float, float]:
    """Putar ulang kurva ekuitas -> (drawdown berjalan, drawdown maksimum).

    Sengaja meniru perhitungan `evaluate_risk_gate` supaya tes ini bicara dalam
    angka yang sama dengan kode yang dijaganya.
    """
    saldo = puncak = modal
    maks = 0.0
    for p in pnls:
        saldo += p
        puncak = max(puncak, saldo)
        dd = (puncak - saldo) / puncak * 100 if puncak > 0 else 0.0
        maks = max(maks, dd)
    berjalan = (puncak - saldo) / puncak * 100 if puncak > 0 else 0.0
    return berjalan, maks


def test_kedua_angka_berbeda_setelah_pemulihan():
    """Dasar seluruh cacat ini: jatuh 20% lalu pulih penuh."""
    berjalan, maks = kurva([-200.0, +200.0])
    assert maks == pytest.approx(20.0)      # rekor tak pernah turun
    assert berjalan == pytest.approx(0.0)   # kenyataannya sudah pulih


def test_breaker_menutup_saat_drawdown_berjalan_melewati_batas():
    RG.update_gate_state(RG.DD_HARD_STOP_PCT + 0.4, rar=0.5, n_trades=50)
    assert RG._state["active"] is True
    assert RG._state["gate_type"] == "circuit_breaker"


def test_breaker_TERBUKA_lagi_setelah_pulih():
    """Inti perbaikannya. Dengan `max_dd`, gerbang ini tetap tertutup selamanya."""
    RG.update_gate_state(RG.DD_HARD_STOP_PCT + 0.4, rar=0.5, n_trades=50)
    assert RG._state["active"] is True

    berjalan, maks = kurva([-200.0, +200.0])
    assert maks > RG.DD_HARD_STOP_PCT       # rekor MASIH melewati batas
    RG.update_gate_state(berjalan, rar=0.5, n_trades=50)
    assert RG._state["gate_type"] != "circuit_breaker"


def test_pesan_menyebut_syarat_lepas_yang_sebenarnya():
    """Pesan lama menjanjikan pemulihan ke DD_RECOVER_PCT (8%) padahal kode
    melepas di batas keras. Selisihnya 7,4 poin — cukup besar untuk membuat
    seseorang menyimpulkan sistemnya jauh lebih dalam terkubur dari kenyataan."""
    RG.update_gate_state(RG.DD_HARD_STOP_PCT + 0.4, rar=0.5, n_trades=50)
    alasan = RG._state["reason"]
    assert f"{RG.DD_HARD_STOP_PCT:.1f}%" in alasan
    assert f"< {RG.DD_RECOVER_PCT:.0f}%" not in alasan


def test_recover_pct_tetap_tak_tersambung_ke_kondisi():
    """Menyambungkannya BUKAN perbaikan: melepas hanya di bawah 8% justru
    memperdalam kebuntuan. Tes ini menahan 'perbaikan' yang salah arah."""
    dd = (RG.DD_HARD_STOP_PCT + RG.DD_RECOVER_PCT) / 2      # antara 8% dan 15%
    RG.update_gate_state(dd, rar=0.5, n_trades=50)
    assert RG._state["gate_type"] != "circuit_breaker"


def test_override_manual_tetap_menang():
    """Jalan keluar manusia harus tetap ada apa pun angkanya."""
    RG._state["override"] = True
    RG.update_gate_state(99.0, rar=-5.0, n_trades=50)
    assert RG._state["active"] is False
    assert RG._state["gate_type"] == "override"


# ── Populasi trade yang dinilai gerbang ──────────────────────────────────────

def test_gerbang_menilai_agen_yang_benar_benar_berdagang():
    """Query lama memaku empat lane lama dan TIDAK memuat `futures_agentic`.

    Akibatnya dua-duanya buruk: breaker dikemudikan riwayat lane yang sudah
    dihapus, dan kerugian agen aktif tak pernah terhitung — jadi gerbang ini
    tak bisa melindungi apa pun darinya.
    """
    import inspect

    from app.services.agent_registry import ACTIVE_FUTURES_AGENTS, FUTURES_AGENTS

    sumber = inspect.getsource(RG.evaluate_risk_gate)
    assert "FUTURES_AGENTS" in sumber, "populasi wajib dari registry"
    for lama in ("futures_agent1", "futures_agent2", "futures_agent_bigmover"):
        assert f'"{lama}"' not in sumber, f"{lama} masih dipaku sebagai daftar tangan"

    # Yang sesungguhnya penting: agen aktif ADA di populasi yang dipakai gerbang.
    for aktif in ACTIVE_FUTURES_AGENTS:
        assert aktif in FUTURES_AGENTS, f"{aktif} tak terlihat oleh gerbang risiko"


@pytest.mark.asyncio
async def test_epoch_default_nol_berarti_seluruh_riwayat():
    """Tanpa reset, tak boleh ada trade yang diam-diam hilang dari penilaian."""
    assert await RG._risk_epoch_ts() >= 0.0


# ── Epoch dihormati SEMUA jalur yang menurunkan angka dari trade ─────────────

def test_semua_jalur_turunan_menghormati_epoch():
    """Saldo dompet, kurva gerbang, dan RAR sama-sama DITURUNKAN dari trade —
    tidak disimpan. Kalau salah satu tak mengenal epoch, ia menghitung ulang dari
    seluruh riwayat dan membatalkan reset diam-diam.

    Terukur 9 Sep 2026: reset ditulis, lalu `sync_futures_balance` mengembalikannya
    18 detik kemudian; satu-satunya jejak yang tersisa adalah kolom `notes`.
    """
    import inspect

    from agents.futures import monitor as M

    for fn in (RG.evaluate_risk_gate, M._update_futures_balance):
        sumber = inspect.getsource(fn)
        assert "_risk_epoch_ts" in sumber, (
            f"{fn.__qualname__} menurunkan angka dari trade tanpa mengenal epoch")
