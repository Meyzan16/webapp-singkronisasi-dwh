"""Rantai Adaptive Learning Engine → agen MONITOR, dijaga untuk kedua market.

Penyakit paling mahal di proyek ini bukan angka yang salah, tapi angka yang
BENAR di tempat yang tak pernah dibaca:

  * lane SPOT menyimpan `squeeze`, config memakai `accumulation` → usulan TP
    mendarat di kunci yang tak pernah ada (8 Agu);
  * monitor SPOT tak pernah memanggil `effective_take_profit` → canary terlihat
    aktif dengan efek NOL (8 Agu);
  * `monitor_tp_max_atr_mult` dst. punya baris config rapi tapi tak satu pun
    keputusan membacanya.

Semua gagal SENYAP. Berkas ini menutup celah itu secara struktural: bukan
memeriksa satu-satu, tapi menuntut SETIAP kunci config bisa dicapai dari monitor.
"""

import inspect

import pytest

from agents.futures import monitor_config as mcfg, monitor as fut_mon
from agents.opportunity import monitor_config as scfg, monitor as spot_mon

PASANGAN = [
    pytest.param(mcfg, fut_mon, "mcfg", "futures", id="futures"),
    pytest.param(scfg, spot_mon, "scfg", "spot", id="spot"),
]


def _fungsi_config(cfgmod):
    return {n: f for n, f in vars(cfgmod).items()
            if callable(f) and getattr(f, "__module__", None) == cfgmod.__name__
            and hasattr(f, "__code__")}


def _tercapai_dari_monitor(cfgmod, mon, alias):
    """Fungsi config yang bisa dicapai monitor — langsung ATAU lewat fungsi lain.

    Penelusuran harus dari pemanggil ke YANG DIPANGGIL. Arah terbalik akan
    menandai fungsi yang justru tak pernah dipakai sebagai "tercapai".
    """
    fns = _fungsi_config(cfgmod)
    msrc = inspect.getsource(mon)
    tercapai = {n for n in fns if f"{alias}.{n}(" in msrc}
    berubah = True
    while berubah:
        berubah = False
        for n in list(tercapai):
            src = inspect.getsource(fns[n])
            for m in fns:
                if m not in tercapai and f"{m}(" in src:
                    tercapai.add(m)
                    berubah = True
    return fns, tercapai, msrc


@pytest.mark.parametrize("cfgmod,mon,alias,market", PASANGAN)
def test_setiap_kunci_config_sampai_ke_keputusan(cfgmod, mon, alias, market):
    """Kunci config yang tak terbaca siapa pun = tombol palsu.

    Ia tampil di UI, bisa diubah, dicatat di ledger — dan tak mengubah apa pun.
    Terukur 10 Agu: `monitor_time_stop_default_min` begitu, karena monitor
    memanggil `.get(lane)` tanpa default sehingga nilainya mustahil terpakai.
    """
    fns, tercapai, msrc = _tercapai_dari_monitor(cfgmod, mon, alias)
    mati = []
    for var, key in cfgmod._KEYS.items():
        if f"{alias}.{var}" in msrc:
            continue
        if any(var in inspect.getsource(fns[n]) for n in tercapai):
            continue
        mati.append(key)
    assert not mati, f"{market}: kunci config tak pernah sampai ke keputusan: {mati}"


@pytest.mark.parametrize("cfgmod,mon,alias,market", PASANGAN)
def test_lane_tak_terdaftar_memakai_default_bukan_dilewati(cfgmod, mon, alias, market):
    """Peta per-lane WAJIB punya nilai jatuh. `.get(k)` polos mengembalikan None,
    dan `if nilai:` sesudahnya MELEWATI perlindungan itu diam-diam — persis
    kebalikan dari yang didokumentasikan."""
    # Pemeriksaan harus lintas-baris: panggilannya boleh dipecah ke baris baru,
    # dan versi berbasis baris akan melaporkan kegagalan palsu untuk itu.
    src = " ".join(inspect.getsource(mon).split())
    for peta in ("TIME_STOP_MIN_BY_LANE", "FAILFAST_SL_GAP_BY_LANE"):
        pola = f"{alias}.{peta}.get("
        posisi = 0
        while (i := src.find(pola, posisi)) != -1:
            argumen = src[i + len(pola):src.find(")", i)]
            assert "," in argumen, (
                f"{market}: {peta}.get({argumen}) tanpa default -> lane baru "
                f"kehilangan perlindungan ini tanpa satu pun error")
            posisi = i + len(pola)


@pytest.mark.parametrize("cfgmod,mon,alias,market", PASANGAN)
def test_monitor_memanggil_kompresi_tp_hasil_belajar(cfgmod, mon, alias, market):
    """Nilai hasil belajar yang tak pernah DIPANGGIL berefek nol — canary bisa
    terlihat 'aktif' di config sambil tak mengubah satu keputusan pun."""
    assert f"{alias}.effective_take_profit(" in inspect.getsource(mon), \
        f"{market}: monitor tak memanggil kompresi TP"


@pytest.mark.parametrize("cfgmod,mon,alias,market", PASANGAN)
def test_kosakata_lane_config_dan_rollout_sama(cfgmod, mon, alias, market):
    """Kunci per-lane dibentuk dari nama lane. Beda kosakata = usulan mendarat di
    kunci yang tak pernah dibaca (kejadian nyata pada lane SPOT)."""
    from agents.learning import exit_rollout as er
    for lane in cfgmod.tunable_lanes():
        grup, key = er.param_config_key("tp_atr_mult", lane, market)
        assert grup == market
        assert key == cfgmod.tp_lane_key(lane)


@pytest.mark.parametrize("cfgmod,mon,alias,market", PASANGAN)
def test_saklar_hasil_belajar_default_mati(cfgmod, mon, alias, market):
    """Bawaan WAJIB mati. Menyala hanya boleh lewat keputusan sadar di DB —
    kalau tidak, satu deploy bisa mengubah perilaku tanpa ada yang memilihnya."""
    # Dibaca dari SUMBER, bukan dari nilai modul: `refresh()` yang dipanggil
    # test lain sudah menimpa nilai runtime-nya dengan angka dari DB.
    src = inspect.getsource(cfgmod)
    assert "EXIT_LEARNING_ENABLED = 0.0" in src, \
        f"{market}: bawaan saklar hasil belajar bukan MATI"


def test_rollout_shadow_tak_menulis_config():
    """Shadow = mengamati. Kalau ia menulis config, tahapan aman shadow→canary
    kehilangan seluruh maknanya."""
    from agents.learning import exit_rollout as er
    src = inspect.getsource(er.propose)
    assert "value_num" not in src, "propose() menulis config — shadow bocor jadi aktif"
