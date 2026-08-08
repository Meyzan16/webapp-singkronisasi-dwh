"""Penjaga penggabungan bobot lintas-lane (audit adaptive weighting, 8 Agu 2026).

Kontrak bobot futures adalah SATU peta yang diterapkan ke semua lane. Sebelum
perbaikan, baris dipetakan `{signal_key: row}` sehingga saat dua lane memiliki
kunci yang sama, satu baris menimpa yang lain dan pemenangnya ditentukan urutan
baris dari database — bukan bukti, dan bisa berbeda antar restart.
"""

from agents.futures.learning_loader import _Agg


class _Row:
    """Baris bobot minimal, meniru kolom `AgentSignalWeight` yang dipakai loader."""

    def __init__(self, agent, signal_key, weight, win_count, total_count):
        self.agent = agent
        self.signal_key = signal_key
        self.weight = weight
        self.win_count = win_count
        self.total_count = total_count


def _merge(items):
    """Salinan logika penggabungan loader untuk diuji tanpa menyentuh DB."""
    grouped = {}
    for row in items:
        grouped.setdefault(row.signal_key, []).append(row)
    out = {}
    for key, group in grouped.items():
        total = sum(g.total_count for g in group) or 1
        out[key] = _Agg(
            weight=sum(g.weight * g.total_count for g in group) / total,
            win_count=sum(g.win_count for g in group),
            total_count=sum(g.total_count for g in group),
        )
    return out


def test_kunci_dua_lane_digabung_bukan_ditimpa():
    """Kasus nyata: flow.volume_momentum dimiliki agent3 (n=14) dan bigmover (n=15)."""
    merged = _merge([
        _Row("futures_agent3", "k", 0.848, 6, 14),
        _Row("futures_agent_bigmover", "k", 0.829, 7, 15),
    ])
    agg = merged["k"]
    assert agg.total_count == 29, "bukti kedua lane harus dijumlahkan, bukan dibuang"
    assert agg.win_count == 13
    # Rata-rata berbobot sampel — lane dengan bukti lebih banyak berpengaruh lebih besar.
    assert abs(agg.weight - (0.848 * 14 + 0.829 * 15) / 29) < 1e-9


def test_urutan_baris_tak_mengubah_hasil():
    """Inti bug lama: hasilnya bergantung urutan baris dari database."""
    a = _Row("futures_agent3", "k", 0.848, 6, 14)
    b = _Row("futures_agent_bigmover", "k", 0.829, 7, 15)
    assert _merge([a, b])["k"] == _merge([b, a])["k"]


def test_kunci_tunggal_tak_berubah_nilainya():
    """Mayoritas kunci hanya dimiliki satu lane — nilainya harus lewat apa adanya."""
    merged = _merge([_Row("futures_agent1", "k", 0.75, 3, 10)])
    assert merged["k"].weight == 0.75
    assert merged["k"].total_count == 10


def test_total_nol_tak_membagi_nol():
    """Baris ber-total 0 tak boleh membuat loader melempar ZeroDivisionError —
    kegagalan di sini mematikan SELURUH kontrak learning, bukan satu kunci."""
    merged = _merge([_Row("futures_agent1", "k", 0.9, 0, 0)])
    assert merged["k"].total_count == 0


def test_ban_dibaca_dari_kunci_peta_bukan_atribut_baris():
    """`own` kini berisi agregat, bukan baris ORM. Membaca `.signal_key` darinya
    membuat loader gagal total — terjadi sekali saat perbaikan ini dibuat."""
    import inspect
    from agents.futures import learning_loader
    src = inspect.getsource(learning_loader.load_futures_learning)
    assert "for key, agg in own.items()" in src
    assert "r.signal_key) for r in own.values()" not in src
