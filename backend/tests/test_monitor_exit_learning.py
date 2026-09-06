"""Jaring pengaman batas TP hasil belajar (MONITOR futures, PRIORITAS 2).

Yang dijaga di sini bukan kebenaran angkanya, melainkan sifat yang membuat fitur
ini aman dinyalakan: default harus NOL efek, angka hasil belajar hanya berlaku
untuk lane pemiliknya, dan kompresi tak pernah menjauhkan target.
"""

import pytest

from agents.futures import monitor_config as mcfg


@pytest.fixture(autouse=True)
def _restore():
    """Kembalikan state modul — nilainya global, bocor antar test bila dibiarkan."""
    saved = {v: getattr(mcfg, v) for v in mcfg._KEYS}
    saved_maps = {
        "TP_ATR_BY_LANE":        dict(mcfg.TP_ATR_BY_LANE),
        "TIME_STOP_MIN_BY_LANE": dict(mcfg.TIME_STOP_MIN_BY_LANE),
        "FAILFAST_LANES":        set(mcfg.FAILFAST_LANES),
        "FAILFAST_SL_GAP_BY_LANE": dict(mcfg.FAILFAST_SL_GAP_BY_LANE),
        "PROFIT_LOCK_TIERS":     list(mcfg.PROFIT_LOCK_TIERS),
    }
    yield
    for name, value in {**saved, **saved_maps}.items():
        setattr(mcfg, name, value)


def test_default_tanpa_efek():
    """Tanpa override apa pun, TP dikembalikan apa adanya."""
    assert mcfg.TP_MAX_ATR_MULT == 0.0
    assert mcfg.EXIT_LEARNING_ENABLED == 0.0
    assert mcfg.effective_take_profit(100, 130, 3.0, "LONG", lane="bigmover") == (130, False)


def test_angka_belajar_diabaikan_saat_saklar_mati():
    """Menulis rekomendasi ke DB tak boleh mengubah perilaku sebelum disetujui."""
    mcfg.TP_ATR_BY_LANE = {"bigmover": 0.6}
    mcfg.EXIT_LEARNING_ENABLED = 0.0
    assert mcfg.tp_atr_limit("bigmover") == mcfg.TP_MAX_ATR_MULT


def test_angka_belajar_hanya_untuk_lane_pemiliknya():
    """Lane tanpa angka sendiri jatuh ke batas global, bukan meminjam lane lain."""
    mcfg.TP_MAX_ATR_MULT = 4.0
    mcfg.EXIT_LEARNING_ENABLED = 1.0
    mcfg.TP_ATR_BY_LANE = {"bigmover": 0.6}
    assert mcfg.tp_atr_limit("bigmover") == 0.6
    assert mcfg.tp_atr_limit("momentum") == 4.0
    assert mcfg.tp_atr_limit("") == 4.0


@pytest.mark.parametrize("direction,tp,expected", [("LONG", 130, 101.8), ("SHORT", 70, 98.2)])
def test_kompresi_hanya_mendekatkan(direction, tp, expected):
    mcfg.EXIT_LEARNING_ENABLED = 1.0
    mcfg.TP_ATR_BY_LANE = {"bigmover": 0.6}
    got, compressed = mcfg.effective_take_profit(100, tp, 3.0, direction, lane="bigmover")
    assert compressed
    assert got == pytest.approx(expected)
    assert abs(got - 100) < abs(tp - 100)      # tak pernah menjauh


def test_tp_sudah_dekat_tak_disentuh():
    mcfg.EXIT_LEARNING_ENABLED = 1.0
    mcfg.TP_ATR_BY_LANE = {"bigmover": 2.0}
    assert mcfg.effective_take_profit(100, 101, 3.0, "LONG", lane="bigmover") == (101, False)


def test_kunci_config_per_lane_ikut_registry():
    """Lane PENSIUN baru harus otomatis punya kunci config — tanpa mengedit
    monitor_config. Niat aslinya (lane tak boleh lahir tanpa barisnya) tetap;
    yang berubah sumbernya sejak Fase 3.

    Lane `agentic` SENGAJA di luar: seluruh parameter keluarnya datang dari
    `exit_config` sebagai satu set, bukan per lane. Memberinya baris di sini
    akan menghidupkan lagi persis yang sedang ditinggalkan — 38 konstanta
    monitor plus 21 kunci per lane untuk pertanyaan yang sama.
    """
    from app.services.agent_registry import ACTIVE_FUTURES_AGENTS, LEGACY_LANES

    lanes = mcfg._known_lanes()
    assert set(lanes) == set(LEGACY_LANES)
    assert mcfg.tp_lane_key("bigmover") == "monitor_tp_atr_mult_lane_bigmover"

    # Lane agen aktif tak boleh menyelinap masuk ke config per-lane lama.
    assert ACTIVE_FUTURES_AGENTS == ["futures_agentic"]
    assert "agentic" not in set(lanes)


def test_saklar_terdaftar_di_config_defaults():
    """Saklar wajib punya baris default, kalau tidak ia tak muncul di UI Settings."""
    from app.services.agent_config_defaults import all_defaults
    keys = {d["key"] for d in all_defaults() if d["group"] == "futures"}
    assert "monitor_exit_learning_enabled" in keys


# ── M2: monitor.py wajib membaca monitor_config, bukan salinan lokal ──────────

def test_monitor_tak_punya_salinan_ambang_keputusan():
    """Akar masalah M2: `refresh()` dipanggil tiap siklus tapi monitor memakai
    konstanta lokalnya sendiri, sehingga menala dari UI tak berpengaruh apa pun.
    Test ini gagal bila ada yang menyalin ambang keputusan kembali ke monitor.py."""
    import agents.futures.monitor as mon
    bocor = [v for v in mcfg._KEYS if hasattr(mon, v)]
    assert not bocor, f"ambang ini disalin ulang di monitor.py: {bocor}"
    for v in ("TIME_STOP_MIN_BY_LANE", "FAILFAST_LANES", "PROFIT_LOCK_TIERS",
              "_PROFIT_LOCK_TIERS", "FUTURES_ROTATION_MIN_DAYS"):
        assert not hasattr(mon, v), f"{v} masih hidup di monitor.py"


def test_refresh_tanpa_override_tak_mengubah_apa_pun(monkeypatch):
    """Menyambungkan kabel tak boleh mengubah perilaku: tanpa satu pun baris DB,
    nilai sesudah refresh harus persis sama dengan nilai bawaan."""
    import asyncio
    from agents.shared.config_reader import cfg

    async def _no_override(group, key, default):
        return default

    monkeypatch.setattr(cfg, "get", _no_override)
    before = mcfg.snapshot()
    asyncio.run(mcfg.refresh())
    assert mcfg.snapshot() == before


def test_default_tak_hanyut_setelah_override(monkeypatch):
    """Default WAJIB dibaca dari salinan beku. Kalau dibaca dari variabel modul
    yang baru saja ditimpa, satu override akan jadi 'default' selamanya dan
    menghapus baris config tak lagi memulihkan perilaku asli."""
    import asyncio
    from agents.shared.config_reader import cfg

    async def _override_bigmover(group, key, default):
        return 5.0 if key == "monitor_time_stop_min_bigmover" else default

    monkeypatch.setattr(cfg, "get", _override_bigmover)
    asyncio.run(mcfg.refresh())
    assert mcfg.TIME_STOP_MIN_BY_LANE["bigmover"] == 5.0

    async def _no_override(group, key, default):
        return default

    monkeypatch.setattr(cfg, "get", _no_override)
    asyncio.run(mcfg.refresh())
    assert mcfg.TIME_STOP_MIN_BY_LANE["bigmover"] == 90.0   # pulih, bukan 5.0


def test_setiap_lane_punya_baris_config_lengkap():
    """Pertumbuhan: lane baru harus otomatis dapat SEMUA baris config-nya.
    Lane `bigmover` dulu lahir dengan sebagian baris hilang tanpa satu pun error."""
    from app.services.agent_config_defaults import all_defaults
    keys = {d["key"] for d in all_defaults() if d["group"] == "futures"}
    for lane in mcfg.tunable_lanes():
        for prefix in ("monitor_time_stop_min_", "monitor_failfast_enabled_",
                       "monitor_tp_atr_mult_lane_", "lane_cap_"):
            assert f"{prefix}{lane}" in keys, f"lane {lane} kehilangan {prefix}*"


def test_default_baris_config_sama_dengan_nilai_runtime():
    """Baris config yang default-nya beda dari nilai kode = jebakan senyap:
    menyimpan nilai lewat UI akan menggeser perilaku walau operator merasa tak
    mengubah apa-apa."""
    from app.services.agent_config_defaults import all_defaults
    from agents.futures.monitor import _LANE_CAP_DEFAULTS, _MAX_LOSS_DEFAULTS

    by_key = {d["key"]: d["default"] for d in all_defaults() if d["group"] == "futures"}
    for var, key in mcfg._KEYS.items():
        assert by_key[key] == getattr(mcfg, var), f"{key} default tak cocok"
    for lane in mcfg.tunable_lanes():
        assert by_key[f"lane_cap_{lane}"] == _LANE_CAP_DEFAULTS[lane]
        assert by_key[f"monitor_max_loss_pct_{lane}"] == _MAX_LOSS_DEFAULTS[lane]


# ── M3: fail-fast wajib unggul jelas atas SL ─────────────────────────────────

def test_failfast_default_tak_mengubah_perilaku():
    """Tanpa gap, semua pemotongan dini tetap diizinkan seperti sebelumnya."""
    assert mcfg.FAILFAST_MIN_SL_GAP == 0.0
    allowed, gap = mcfg.failfast_allowed("bigmover", sl_dist_pct=1.5, threshold_pct=1.0)
    assert allowed and gap == 1.5


def test_failfast_padam_saat_sl_nyaris_berimpit():
    """Kasus bigmover: SL 1,5×ATR vs pemicu 1,0×ATR → gap 1,5, di bawah syarat 2,0.
    Memotong di sini nyaris tak menyelamatkan apa pun."""
    mcfg.FAILFAST_MIN_SL_GAP = 2.0
    allowed, gap = mcfg.failfast_allowed("bigmover", sl_dist_pct=1.5, threshold_pct=1.0)
    assert not allowed and gap == 1.5


def test_failfast_tetap_hidup_saat_sl_jauh():
    """Kasus momentum: SL ~5,4×ATR vs pemicu ~1,7×ATR → gap 3,2, lolos syarat 2,0.
    Satu ambang yang sama harus bisa memadamkan satu lane tanpa menyentuh lane lain."""
    mcfg.FAILFAST_MIN_SL_GAP = 2.0
    allowed, gap = mcfg.failfast_allowed("momentum", sl_dist_pct=5.4, threshold_pct=1.7)
    assert allowed and gap > 3.0


def test_gap_belajar_diabaikan_saat_saklar_mati():
    mcfg.FAILFAST_SL_GAP_BY_LANE = {"bigmover": 2.0}
    mcfg.EXIT_LEARNING_ENABLED = 0.0
    assert mcfg.failfast_sl_gap("bigmover") == mcfg.FAILFAST_MIN_SL_GAP


def test_gap_belajar_hanya_untuk_lane_pemiliknya():
    mcfg.EXIT_LEARNING_ENABLED = 1.0
    mcfg.FAILFAST_MIN_SL_GAP = 0.0
    mcfg.FAILFAST_SL_GAP_BY_LANE = {"bigmover": 2.0}
    assert mcfg.failfast_sl_gap("bigmover") == 2.0
    assert mcfg.failfast_sl_gap("momentum") == 0.0     # tak meminjam angka lane lain


def test_ambang_nol_tak_pernah_memblokir():
    """Baris lama tanpa atr_pct bisa memberi ambang 0 — jangan sampai pembagian
    itu memblokir semua pemotongan dini secara diam-diam."""
    mcfg.FAILFAST_MIN_SL_GAP = 99.0
    allowed, gap = mcfg.failfast_allowed("bigmover", sl_dist_pct=1.5, threshold_pct=0.0)
    assert allowed and gap == 0.0


def test_monitor_mencatat_pemotongan_yang_ditolak():
    """Penjaga yang menolak dalam diam mustahil diaudit — wajib ada pencacahnya."""
    import agents.futures.monitor as mon
    assert "fail_fast_suppressed" in mon.get_state()


def test_gap_failfast_punya_baris_config_tiap_lane():
    from app.services.agent_config_defaults import all_defaults
    keys = {d["key"] for d in all_defaults() if d["group"] == "futures"}
    assert "monitor_failfast_min_sl_gap" in keys
    for lane in mcfg.tunable_lanes():
        assert mcfg.failfast_gap_key(lane) in keys


def test_tangga_kunci_profit_tetap_urut_walau_ditala_terbalik(monkeypatch):
    """Tier paling ketat harus tetap menang walau operator mengisi urutan acak —
    kalau tidak, tier rendah akan menutup posisi lebih dulu dan tier tinggi mati."""
    import asyncio
    from agents.shared.config_reader import cfg

    async def _flip(group, key, default):
        return 500.0 if key == "monitor_profit_lock_peak_t5" else default

    monkeypatch.setattr(cfg, "get", _flip)
    asyncio.run(mcfg.refresh())
    peaks = [p for p, _ in mcfg.PROFIT_LOCK_TIERS]
    assert peaks == sorted(peaks, reverse=True)


def test_perpanjangan_tp3_tunduk_pada_batas_yang_sama():
    """Temuan inti M0: "TP di monitor hanya pernah DIPERPANJANG, tak pernah
    diperpendek". Kalau perpanjangan ke TP3 tak tunduk batas belajar, TP yang
    sudah dikompresi akan diperpanjang kembali begitu TP1 tersentuh — kompresinya
    batal tanpa jejak, dan asimetri yang jadi akar masalah kembali hidup.
    """
    import inspect
    from agents.futures import monitor as fut_mon
    src = inspect.getsource(fut_mon.check_futures_positions)
    assert "_tp3_eff" in src, "perpanjangan TP3 tak melewati batas belajar"
    assert "trade.take_profit = _tp3_eff" in src
    assert "trade.take_profit = tp3" not in src, "masih memasang tp3 mentah"
    # Perpanjangan hanya sah bila targetnya benar-benar LEBIH JAUH dari TP saat ini.
    assert "_lebih_jauh" in src


def test_perpanjangan_batal_saat_kompresi_aktif():
    """Bila batas belajar sudah memangkas TP2, TP3 yang dikompresi ke batas yang
    sama TIDAK lebih jauh — jadi perpanjangan otomatis jadi no-op, bukan
    membatalkan hasil belajar."""
    mcfg.EXIT_LEARNING_ENABLED = 1.0
    mcfg.TP_ATR_BY_LANE = {"bigmover": 0.566}
    entry, atr = 100.0, 6.07
    tp2, _ = mcfg.effective_take_profit(entry, entry * 1.2428, atr, "LONG", lane="bigmover")
    tp3, _ = mcfg.effective_take_profit(entry, entry * 1.40, atr, "LONG", lane="bigmover")
    assert tp3 == tp2, "keduanya harus mendarat di batas yang sama"
    assert not (tp3 > tp2), "perpanjangan tak boleh lolos saat kompresi aktif"


def test_tak_ada_ambang_keputusan_telanjang_di_monitor():
    """M2 memusatkan KONSTANTA MODUL tapi melewatkan angka di tengah ekspresi —
    bentuk hardcode paling sulit terlihat karena tak muncul saat mencari definisi
    konstanta. Delapan di antaranya ditemukan pada audit 9 Agu 2026, semuanya
    penentu kapan posisi ditutup atau SL digeser.
    """
    import inspect
    from agents.futures import monitor as mon
    src = inspect.getsource(mon)
    telanjang = [
        "_pnl_now_pct >= 5.0",              # syarat perpanjangan umur
        "age_days > 2.0",                   # mulai nilai stagnan
        "_progress < 20.0",                 # ambang progres stagnan
        "_hold_tp1_h >= 24.0",              # macet sesudah TP1
        "> 48 * 3600",                      # trailing stagnan pasca-TP1
        "score >= 65 and",                  # gerbang perpanjangan TP3
        "(tp1 - entry) * 0.75",             # kunci SL sesudah TP1
        "(tp2 - tp1) * 0.50",               # maju ke TP1 di separuh jalan
    ]
    for pola in telanjang:
        assert pola not in src, f"ambang keputusan kembali telanjang: {pola}"


def test_ambang_hasil_audit_terbaca_monitor_dan_punya_config():
    """Dipindah ke config saja tak cukup — monitor harus BENAR-BENAR membacanya,
    dan tiap ambang wajib punya baris config agar muncul di UI."""
    import inspect
    from agents.futures import monitor as mon
    from app.services.agent_config_defaults import all_defaults
    src = inspect.getsource(mon)
    keys = {d["key"] for d in all_defaults() if d["group"] == "futures"}
    for var in ("AGE_EXTEND_MIN_PNL_PCT", "STAGNANT_CHECK_DAYS", "STAGNANT_PROGRESS_PCT",
                "STUCK_AFTER_TP1_HOURS", "TRAIL_STAGNANT_TP1_HOURS", "TP_EXTEND_MIN_SCORE",
                "TRAIL_LOCK_AFTER_TP1_FRAC", "TRAIL_ADVANCE_TP1_TP2_FRAC"):
        assert f"mcfg.{var}" in src, f"{var} tak dibaca monitor"
        assert mcfg._KEYS[var] in keys, f"{var} tak punya baris config"
