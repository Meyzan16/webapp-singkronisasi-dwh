"""M8 — recommender dua parameter trailing.

Yang dijaga di sini bukan "kodenya jalan", tapi tiga cara spesifik fitur ini bisa
GAGAL SENYAP — ketiganya sudah pernah terjadi di proyek ini dalam bentuk lain:

1. bukti dikumpulkan dalam satuan yang tak sepadan dengan parameternya,
2. usulan mendarat di kunci config yang tak dibaca siapa pun,
3. rekomendasi terbit dari data yang tersensor oleh nilai yang berlaku sekarang.
"""

import inspect

import pytest

from agents.learning import exit_learning as el
from agents.learning import exit_rollout as er
from agents.shared import trail_tracker as tt


# ── Satuan bukti ─────────────────────────────────────────────────────────────

def test_bukti_dikumpulkan_dalam_satuan_parameternya():
    """Kedua parameter adalah PECAHAN dari (TP1−entry) dan (TP2−TP1). Bukti dalam
    persen harga atau ATR tak bisa diubah jadi usulan tanpa TP1/TP2 tiap trade —
    dan itu tak ada di ledger."""
    meta: dict = {}
    tt.arm_tp1(meta, entry=100.0, tp1=110.0, tp2=130.0, direction="LONG")
    assert meta["tp1_ref_span"] == 10.0
    assert meta["tp1_gain_pct"] == 10.0
    assert meta["tp2_fav"] == 3.0          # (130−100)/10

    tt.track(meta, 107.5)                  # turun ke 0,75×TP1 — tepat level kunci
    tt.track(meta, 120.0)                  # naik ke fav 2,0 = separuh TP1→TP2
    retrace, ext = tt.fractions(meta)
    assert retrace == 0.75
    assert ext == 0.5                      # (2,0−1,0)/(3,0−1,0)


def test_short_dihitung_dengan_arah_terbalik():
    """Tanpa ini seluruh sampel SHORT akan tercatat sebagai retrace ekstrem dan
    menarik usulan ke arah yang salah."""
    meta: dict = {}
    tt.arm_tp1(meta, entry=100.0, tp1=90.0, tp2=70.0, direction="SHORT")
    tt.track(meta, 92.5)                   # bergerak MELAWAN posisi short
    retrace, _ = tt.fractions(meta)
    assert retrace == 0.75


def test_acuan_dibekukan_karena_take_profit_dimutasi_sesudah_tp1():
    """Monitor menaikkan `trade.take_profit` ke TP2 lalu TP3 setelah TP1. Membaca
    acuan saat penutupan akan mengukur terhadap target yang sudah berpindah."""
    meta: dict = {}
    tt.arm_tp1(meta, entry=100.0, tp1=110.0, tp2=130.0)
    tt.arm_tp1(meta, entry=100.0, tp1=130.0, tp2=160.0)   # "TP naik" — harus diabaikan
    assert meta["tp1_ref_span"] == 10.0


def test_posisi_tanpa_tp1_tak_masuk_sampel():
    """Kedua parameter tak pernah berlaku di posisi yang tak sampai TP1 —
    memasukkannya hanya mengencerkan bukti."""
    assert tt.fractions({}) == (None, None)


def test_tp1_tak_masuk_akal_tak_mencemari_ledger():
    meta: dict = {}
    tt.arm_tp1(meta, entry=100.0, tp1=100.0, tp2=120.0)   # span 0
    assert tt.fractions(meta) == (None, None)


def test_tp2_tak_di_luar_tp1_membuat_ext_kosong_bukan_nol():
    """Penyebut (TP2−TP1) yang nol/negatif akan menghasilkan angka karangan."""
    meta: dict = {}
    tt.arm_tp1(meta, entry=100.0, tp1=110.0, tp2=105.0)
    _, ext = tt.fractions(meta)
    assert ext is None


# ── Jalur penerapan ──────────────────────────────────────────────────────────

def test_kunci_config_yang_diusulkan_benar_benar_dibaca_monitor():
    """Penyakit berulang: hasil belajar tersimpan rapi di kunci yang tak dibaca
    siapa pun (lane SPOT `squeeze` vs `accumulation`, 8 Agu)."""
    from agents.futures import monitor_config as mcfg
    import agents.futures.monitor as fut_mon
    src = inspect.getsource(fut_mon)
    for param, key in er.GLOBAL_PARAMS.items():
        grup, k = er.param_config_key(param, er.GLOBAL_LANE)
        assert (grup, k) == ("futures", key)
        var = next(v for v, kk in mcfg._KEYS.items() if kk == key)
        assert f"mcfg.{var}" in src, f"{key} tak pernah dibaca monitor futures"


def test_parameter_trailing_terdaftar_di_rollout_futures():
    for p in er.GLOBAL_PARAMS:
        assert p in er.SUPPORTED_PARAMS_BY_MARKET["futures"]
        # SPOT belum punya kunci config — mendaftarkannya = menulis ke kunci mati.
        assert p not in er.SUPPORTED_PARAMS_BY_MARKET["spot"]


@pytest.mark.asyncio
async def test_parameter_global_menolak_lane_per_koin():
    """Pemeriksaan duplikat memakai (market, lane, param). Tanpa sentinel, empat
    lane bisa punya baris sendiri yang semuanya menulis SATU kunci config."""
    hasil = await er.propose("bigmover", "trail_lock_after_tp1", 0.9)
    assert hasil["status"] == "lane_salah"
    assert hasil["harus"] == er.GLOBAL_LANE


def test_baseline_parameter_global_tak_memfilter_lane_ke_sentinel():
    """`lane == "all"` tak pernah cocok dengan baris ledger mana pun — canary-nya
    akan mengumpulkan NOL outcome dan macet selamanya tanpa error."""
    src = inspect.getsource(er._lane_exits)
    assert "GLOBAL_LANE" in src


# ── Kejujuran rekomendasi ────────────────────────────────────────────────────

def test_hanya_arah_menaikkan_yang_dinilai():
    """Nilai yang berlaku memotong posisi begitu tersentuh, jadi tak ada data
    tentang apa yang terjadi DI BAWAHNYA. Mengevaluasi kandidat yang lebih rendah
    berarti menyimpulkan dari ketiadaan bukti."""
    src = inspect.getsource(el.recommend_trail_params)
    assert "lock_now + i * 0.05" in src
    assert "adv_now + i * 0.10" in src
    assert "TERSENSOR" in src


def test_usulan_ditahan_sampai_sampel_cukup():
    assert el.TRAIL_MIN_SAMPLES >= 25
    src = inspect.getsource(el.recommend_trail_params)
    assert "recommendation_ready" in src
    assert "TRAIL_MIN_LIFT" in src


def test_spot_mengukur_tapi_tak_menerbitkan_usulan():
    """SPOT masih memakai 0,5 tertanam di monitor. Menerbitkan usulan untuknya
    akan mengulang persis kesalahan kunci-mati."""
    cfg = el._trail_config("spot")
    assert cfg["applicable"] is False
    assert el._trail_config("futures")["applicable"] is True


def test_nilai_berjalan_dibaca_dari_config_bukan_disalin():
    """Angka pembanding yang disalin akan basi diam-diam begitu canary berjalan,
    dan seluruh perhitungan lift jadi salah tanpa ada yang tahu."""
    src = inspect.getsource(el._trail_config)
    assert "mcfg.TRAIL_LOCK_AFTER_TP1_FRAC" in src
    assert "mcfg.TRAIL_ADVANCE_TP1_TP2_FRAC" in src


def test_counterfactual_memakai_biaya_bersih():
    """Keuntungan di TP1 tersimpan KOTOR; membandingkannya dengan `pnl_pct` yang
    sudah bersih akan melebihkan tiap kandidat secara sistematis."""
    for fn in (el.lock_curve_for, el.adv_curve_for):
        assert "- cost" in inspect.getsource(fn), f"{fn.__name__} memakai P&L kotor"
    assert el._cost_pct("futures") > 0
    assert el._cost_pct("spot") > el._cost_pct("futures")   # spot: spread+slippage


# ── Matematika counterfactual ────────────────────────────────────────────────

class _Baris:
    def __init__(self, retrace, ext, tp1_gain, pnl):
        self.retrace_after_tp1_frac = retrace
        self.ext_after_tp1_frac = ext
        self.tp1_gain_pct = tp1_gain
        self.pnl_pct = pnl


def test_kurva_kunci_menghitung_hasil_bukan_menebak():
    """Satu posisi turun ke 0,6×TP1 lalu berakhir −1%. Kunci di 0,8 akan
    menghentikannya di 0,8×10% = 8% kotor, 7,9% bersih."""
    pop = [_Baris(0.6, 0.9, 10.0, -1.0)]
    kurva = el.lock_curve_for(pop, [0.5, 0.8], cost=0.1)
    assert kurva[0]["expectancy_pct"] == -1.0     # 0,6 > 0,5 → tak tersentuh
    assert kurva[0]["n_terpengaruh"] == 0
    assert kurva[1]["expectancy_pct"] == 7.9      # 0,8 × 10 − 0,1
    assert kurva[1]["n_terpengaruh"] == 1


def test_maju_ke_tp1_hanya_menggigit_kalau_harga_memang_balik():
    """Posisi yang mencapai pemicu tapi TAK PERNAH balik ke bawah TP1 tak
    terpengaruh sama sekali. Tanpa syarat kedua ini, tiap kandidat rendah akan
    terlihat unggul secara palsu dan usulannya selalu 'turunkan'."""
    lolos = _Baris(1.4, 0.9, 10.0, 25.0)          # tak pernah balik (retrace ≥ 1)
    balik = _Baris(0.8, 0.9, 10.0, -2.0)          # sempat balik ke bawah TP1
    kurva = el.adv_curve_for([lolos, balik], [0.5], cost=0.1)
    assert kurva[0]["n_terpengaruh"] == 1
    assert kurva[0]["expectancy_pct"] == round((25.0 + 9.9) / 2, 4)


def test_baris_tanpa_ext_tak_dipakai_untuk_parameter_maju():
    """TP2 tak diketahui → `ext` kosong. Menghitungnya sebagai 0 akan membuat
    posisi itu seolah tak pernah maju sama sekali."""
    kurva = el.adv_curve_for([_Baris(0.8, None, 10.0, -2.0)], [0.5], cost=0.1)
    assert kurva[0]["n"] == 0


# ── Perekaman di kedua monitor ───────────────────────────────────────────────

def test_kedua_monitor_merekam_gerak_sesudah_tp1():
    """MAE global tak bisa menggantikan ini: titik terdalamnya hampir selalu
    jatuh SEBELUM TP1, saat kedua parameter belum berlaku sama sekali."""
    import agents.futures.monitor as fut_mon
    import agents.opportunity.monitor as spot_mon
    for mod in (fut_mon, spot_mon):
        src = inspect.getsource(mod)
        assert "trail_tracker.arm_tp1(" in src, f"{mod.__name__} tak membekukan acuan"
        assert "trail_tracker.track(" in src, f"{mod.__name__} tak melacak sesudah TP1"


def test_ledger_menulis_ketiga_kolom():
    from agents.shared import exit_ledger
    src = inspect.getsource(exit_ledger.log_exit)
    for kol in ("retrace_after_tp1_frac", "ext_after_tp1_frac", "tp1_gain_pct"):
        assert kol in src


def test_kolom_baru_punya_migrasi():
    """Kolom model tanpa ALTER TABLE = seluruh penulisan ledger gagal di DB lama,
    dan gagalnya SENYAP karena log_exit menelan galat."""
    import pathlib
    src = pathlib.Path("app/database.py").read_text(encoding="utf-8")
    for kol in ("retrace_after_tp1_frac", "ext_after_tp1_frac", "tp1_gain_pct"):
        assert f"ADD COLUMN IF NOT EXISTS {kol}" in src
