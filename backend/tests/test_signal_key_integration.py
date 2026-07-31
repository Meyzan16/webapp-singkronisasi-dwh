"""Penjaga integrasi kunci sinyal — SPOT & FUTURES.

Latar (bug 29–31 Jul 2026): identitas sinyal sempat punya TIGA namespace yang
tak beririsan, sehingga seluruh bobot hasil belajar tak pernah dibaca saat
scoring dan `factor` selalu 1.0 — learning futures lumpuh total tanpa satu pun
error. Menyusul itu, katalog Formulas ternyata ber-kunci format lama sehingga
irisannya dengan kunci aktif NOL.

Semua kegagalan itu SENYAP. Test ini membuatnya berisik: kalau ada yang kembali
menurunkan kunci dengan cara berbeda, atau menambah aturan sinyal tanpa entri
katalog, CI langsung merah.
"""

import os
import sys

# Repo root ke path — modul `agents` hidup satu level di atas backend/ dan
# pytest.ini hanya memuat `.` (pola sama dgn test_futures_learning_policy.py).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pytest  # noqa: E402

from agents.futures.learning_policy import (  # noqa: E402
    canonical_signal_key as fut_ck,
    signal_key as fut_sk,
    learning_keys as fut_learning_keys,
    _SIGNAL_ID_RULES as FUT_RULES,
)
from agents.opportunity.learning_policy import (  # noqa: E402
    canonical_signal_key as spot_ck,
    signal_key as spot_sk,
    _SIGNAL_ID_RULES as SPOT_RULES,
)
from agents.futures import weight_updater as fwu  # noqa: E402
from app.services.signal_catalog import SIGNAL_CATALOG  # noqa: E402


def _rule_sample(rules):
    """Teks tiruan yang PASTI cocok tiap aturan — menggabung kata wajibnya."""
    return [(" ".join(parts), f"signal_id:{sid}") for parts, sid in rules]


# ── 1. Kunci SIMPAN == kunci BACA ─────────────────────────────────────────────

def test_futures_lookup_key_sama_dengan_scoring_key():
    """`normalize_signal_key` dipakai agent1/2/3/bigmover untuk MENCARI bobot di
    cache; kalau ia beda dari kunci scoring, lookup meleset diam-diam ke 1.0."""
    for raw, expected in _rule_sample(FUT_RULES):
        assert fwu.normalize_signal_key(raw) == expected, raw


def test_futures_scoring_key_sama_dengan_learning_keys():
    """`_scoring_key` (dipakai weight_updater saat MENYIMPAN) harus identik dgn
    kunci yang dihasilkan learning_keys() saat menilai kandidat."""
    for raw, expected in _rule_sample(FUT_RULES):
        cand = {"setup_type": "momentum", "signals": [raw]}
        assert expected in fut_learning_keys(cand), raw
        assert fwu._scoring_key(raw) == expected, raw


def test_spot_key_konsisten():
    for raw, expected in _rule_sample(SPOT_RULES):
        assert (spot_ck(raw) or spot_sk(raw)) == expected, raw


# ── 2. Fallback tetap ber-namespace, tak pernah telanjang ─────────────────────

@pytest.mark.parametrize("raw", ["sinyal betul-betul baru 42%", "xyz tanpa aturan"])
def test_fallback_selalu_bernamespace(raw):
    """Kunci telanjang (tanpa prefix) adalah namespace MATI — tak pernah dibaca
    scoring. Fallback wajib ber-prefix `signal:`."""
    for ck, sk in ((fut_ck, fut_sk), (spot_ck, spot_sk)):
        key = ck(raw) or sk(raw)
        assert key.startswith("signal:"), key
    assert fwu.normalize_signal_key(raw).startswith("signal:")


# ── 3. Katalog menutupi SEMUA aturan kedua market ─────────────────────────────

def test_katalog_menutupi_semua_aturan():
    """Tiap aturan sinyal wajib punya entri katalog — kalau tidak, tab Formulas
    kembali yatim seperti sebelum 31 Jul (79 kunci aktif vs 17 entri, irisan 0)."""
    expected = {f"signal_id:{sid}" for _, sid in FUT_RULES} | \
               {f"signal_id:{sid}" for _, sid in SPOT_RULES}
    missing = expected - set(SIGNAL_CATALOG)
    assert not missing, f"aturan tanpa entri katalog: {sorted(missing)[:5]}"


def test_setiap_entri_katalog_dipetakan_ke_market():
    """Tanpa `markets`, tab Formulas tak bisa menjawab 'ini punya SPOT atau
    FUTURES' — pemetaan yang diminta owner."""
    tanpa = [k for k, e in SIGNAL_CATALOG.items() if not e.get("markets")]
    assert not tanpa, f"entri tanpa pemetaan market: {tanpa[:5]}"
    for k, e in SIGNAL_CATALOG.items():
        assert set(e["markets"]) <= {"spot", "futures"}, (k, e["markets"])


def test_katalog_tidak_memakai_kunci_format_lama():
    """Semua kunci katalog harus ber-ID stabil; kunci teks lama = yatim."""
    lama = [k for k in SIGNAL_CATALOG if not k.startswith("signal_id:")]
    assert not lama, f"kunci format lama: {lama[:5]}"
