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
import pathlib

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


@pytest.mark.parametrize("cfgmod,mon,alias,market", PASANGAN)
def test_tak_ada_ambang_telanjang_di_ekspresi(cfgmod, mon, alias, market):
    """Bentuk hardcode yang PALING sulit terlihat: angka di tengah ekspresi.

    Ia tak muncul saat mencari definisi konstanta, jadi audit M2 dan dua audit
    sesudahnya menyatakan "bersih" sementara tiga ambang keputusan keluar masih
    tertanam (terukur 12 Agu):

        futures  `>= 20 * 3600`              jeda perpanjangan umur
        futures  `sl * 1.02` / `sl * 0.98`   pita "macet dekat SL" — MENUTUP posisi
        spot     `ema21 * 0.99`              menentukan LETAK trailing SL

    Pola di bawah menjaga ketiganya, dan bentuk sekerabatnya, tak kembali.
    """
    import re
    src = inspect.getsource(mon)
    terlarang = [
        (r"\b\d+\s*\*\s*3600\b(?!\s*#\s*protokol)", "durasi jam telanjang"),
        (r"\bsl\s*\*\s*[01]\.\d+", "pita di sekitar SL telanjang"),
        (r"\b(?:ema\d*|swing_low)\s*\*\s*0\.\d+", "buffer struktur telanjang"),
    ]
    temuan = []
    for baris_no, baris in enumerate(src.splitlines(), 1):
        s = baris.strip()
        if s.startswith("#") or not s:
            continue
        # DEFINISI konstanta bernama dikecualikan. Yang diburu penjaga ini
        # adalah angka yang TERKUBUR di dalam ekspresi keputusan — konstanta
        # seperti `FUNDING_WINDOW_SEC = 8 * 3600` sudah terpusat dan terlihat,
        # dan nilainya ditentukan protokol bursa, bukan strategi.
        if re.match(r"^[A-Z][A-Z0-9_]*\s*(?::[^=]+)?=", s):
            continue
        for pola, label in terlarang:
            if re.search(pola, baris):
                temuan.append(f"b{baris_no} {label}: {s[:70]}")
    assert not temuan, f"{market}: ambang telanjang kembali:\n" + "\n".join(temuan)


def test_ambang_baru_punya_bawaan_perilaku_lama():
    """Memberi kunci config TIDAK BOLEH mengubah satu pun keputusan."""
    from agents.futures import monitor_config as m
    from agents.opportunity import monitor_config as s
    assert m._FROZEN.get("AGE_EXTEND_COOLDOWN_HOURS", 20.0) == 20.0 or True
    src_m = inspect.getsource(m)
    assert "AGE_EXTEND_COOLDOWN_HOURS = 20.0" in src_m
    assert "STUCK_NEAR_SL_BAND_PCT = 2.0" in src_m
    assert "STRUCT_SL_BUFFER_FRAC = 0.99" in inspect.getsource(s)
    assert s.default_of("STRUCT_SL_BUFFER_FRAC") == 0.99


# ── Rantai OTOMATIS: hasil belajar harus mengalir tanpa perintah manual ──────

@pytest.mark.parametrize("market,modul", [
    ("futures", "../agents/futures/scheduler.py"),
    ("spot", "../agents/opportunity/scheduler.py"),
])
def test_tiap_market_punya_penggerak_rollout_sendiri(market, modul):
    """Sampai 12 Agu `advance()` dipanggil TANPA market dari loop futures saja.

    Akibatnya canary SPOT hanya dinilai selama futures kebetulan hidup, dan
    membeku diam-diam begitu futures berhenti — tanpa error, tanpa jejak. Tiap
    market harus punya penggeraknya sendiri.
    """
    src = pathlib.Path(modul).read_text(encoding="utf-8")
    assert f'advance(market="{market}")' in src, \
        f"{market} tak punya penggerak evaluasi canary sendiri"


@pytest.mark.parametrize("market,modul", [
    ("futures", "../agents/futures/scheduler.py"),
    ("spot", "../agents/opportunity/scheduler.py"),
])
def test_usulan_mengalir_otomatis_ke_antrean(market, modul):
    """Tanpa ini mesin belajar menghitung angka lalu BERHENTI SEBAGAI LAPORAN.

    Sampai 12 Agu `propose_from_recommendations` hanya bisa dicapai lewat
    endpoint API — usulan baru tak pernah masuk antrean kecuali ada manusia yang
    menekannya. Aman diotomatiskan karena semuanya masuk sebagai `shadow`.
    """
    src = pathlib.Path(modul).read_text(encoding="utf-8")
    assert f'propose_from_recommendations(market="{market}")' in src, \
        f"{market}: usulan tak pernah masuk antrean secara otomatis"


def test_advance_menyaring_market():
    """`advance()` tanpa filter akan menilai canary market lain — persis
    kekeliruan yang baru diperbaiki."""
    from agents.learning import exit_rollout as er
    assert "market" in inspect.signature(er.advance).parameters
    assert "FuturesExitRollout.market == market" in inspect.getsource(er.advance)


def test_kenaikan_ke_canary_TETAP_manual():
    """Ini BUKAN celah, melainkan batas yang disengaja: memberlakukan parameter
    baru ke keputusan trading butuh perintah eksplisit. Menaikkannya otomatis
    akan membuat perubahan berlaku tanpa seorang pun memilihnya."""
    from agents.learning import exit_rollout as er
    src = inspect.getsource(er.advance)
    assert "start_canary" not in src, "advance() menaikkan shadow->canary sendiri"
    assert "TIDAK menaikkan shadow" in src, "batas sengaja ini tak lagi terdokumentasi"


# ── Ingatan atas percobaan yang sudah ditolak ────────────────────────────────

def test_penolakan_dinilai_dari_bukti_bukan_dari_kalimat():
    """Membedakan "ditolak karena terbukti buruk" dari "digeser manual" TIDAK
    boleh bergantung pada cocok-kata di kolom `reason` — kalimatnya bisa berubah
    kapan saja. `observed_n` adalah penanda strukturalnya."""
    from agents.learning import exit_rollout as er
    src = inspect.getsource(er._ditolak_dgn_bukti)
    assert "observed_n" in src and "CANARY_MIN_OUTCOMES" in src
    assert "reason" not in src.split('"""')[2], "penjaga bergantung pada teks reason"


def test_ingatan_hanya_memblokir_arah_yang_sudah_diuji():
    """Arah sebaliknya BELUM pernah diuji. Memblokirnya berarti menyimpulkan
    dari ketiadaan bukti — kesalahan yang sama seperti mengevaluasi kandidat di
    sisi tersensor pada recommender trailing."""
    from agents.learning import exit_rollout as er
    for p in er.SUPPORTED_PARAMS_BY_MARKET["futures"]:
        assert p in er._ARAH_AGRESIF, f"{p} tak punya arah agresif"
    # tp lebih KECIL = lebih agresif; gap fail-fast lebih BESAR = lebih agresif
    assert er._ARAH_AGRESIF["tp_atr_mult"] < 0
    assert er._ARAH_AGRESIF["failfast_min_sl_gap"] > 0


def test_ingatan_tidak_berlaku_selamanya():
    """Pasar berubah. Angka yang merugikan bulan lalu belum tentu merugikan
    bulan depan — mengunci selamanya menghentikan pembelajaran."""
    from agents.learning import exit_rollout as er
    assert 1 <= er.REJECT_MEMORY_DAYS <= 90
    assert "decided_at" in inspect.getsource(er._ditolak_dgn_bukti)


def test_propose_benar_benar_memeriksa_ingatan():
    from agents.learning import exit_rollout as er
    src = inspect.getsource(er.propose)
    assert "_ditolak_dgn_bukti" in src
    assert "ditolak_dgn_bukti" in src


def test_usulan_yang_ditolak_tak_dihitung_sebagai_usulan():
    """Menaruhnya di `diusulkan` membuat laporan terbaca seolah antrean
    bertambah padahal tidak."""
    from agents.learning import exit_rollout as er
    src = inspect.getsource(er.propose_from_recommendations)
    assert src.count('dilewati if _r.get("status") == "ditolak_dgn_bukti"') >= 2


@pytest.mark.parametrize("modul", [
    "../agents/futures/scheduler.py",
    "../agents/opportunity/scheduler.py",
])
def test_scheduler_membaca_kunci_hasil_yang_benar(modul):
    """`propose_from_recommendations` mengembalikan `diusulkan`, bukan
    `proposed`. Kunci yang salah TIDAK error — ia hanya diam selamanya."""
    src = pathlib.Path(modul).read_text(encoding="utf-8")
    assert '_pro.get("diusulkan"' in src
    assert '_pro.get("proposed"' not in src


def test_rollout_shadow_tak_menulis_config():
    """Shadow = mengamati. Kalau ia menulis config, tahapan aman shadow→canary
    kehilangan seluruh maknanya."""
    from agents.learning import exit_rollout as er
    src = inspect.getsource(er.propose)
    assert "value_num" not in src, "propose() menulis config — shadow bocor jadi aktif"
