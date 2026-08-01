"""
Default seed values for agent_config (PLAN_v5 Group C).

This is the single source of truth for which constants are DB-dynamic and what
their hardcoded fallback is. Scope is deliberately narrow ("Keputusan Terkunci"
in PLAN_v5.md): score thresholds, volume gates, quotas, and risk caps that agents
check as simple top-level gates — NOT fine-grained per-signal scoring points.

Each entry's `default` must match the hardcoded constant it shadows exactly —
`agents/shared/config_reader.py` uses these as the fallback when the DB has no
row yet or is unavailable, and call sites also pass the same constant as their
own `default` argument for a second layer of safety.
"""

DEFAULTS: list[dict] = [
    # ── SPOT — volume gates ──────────────────────────────────────────────────
    {"group": "spot", "key": "min_quote_volume", "default": 5_000_000, "category": "volume",
     "description": "Accumulation lane — likuiditas minimum 24h (scanner.MIN_QUOTE_VOLUME)"},
    {"group": "spot", "key": "breakout_min_volume", "default": 500_000, "category": "volume",
     "description": "Breakout Hunter lane — likuiditas minimum 24h"},
    {"group": "spot", "key": "bigmover_min_volume", "default": 1_000_000, "category": "volume",
     "description": "BigMover Chase lane — likuiditas minimum 24h"},
    {"group": "spot", "key": "weekly_min_volume", "default": 1_000_000, "category": "volume",
     "description": "Weekly Momentum supplement — likuiditas minimum 24h"},
    {"group": "spot", "key": "early_radar_min_volume", "default": 100_000, "category": "volume",
     "description": "Early Radar lane — likuiditas minimum 24h (floor)"},
    # ── SPOT — score thresholds ──────────────────────────────────────────────
    {"group": "spot", "key": "min_score", "default": 65, "category": "threshold",
     "description": "Accumulation — score minimum untuk tampil sebagai rekomendasi"},
    {"group": "spot", "key": "auto_open_score", "default": 85, "category": "threshold",
     "description": "Accumulation — raw_score minimum untuk auto-open"},
    {"group": "spot", "key": "breakout_min_score", "default": 60, "category": "threshold",
     "description": "Breakout Hunter — score minimum untuk tampil"},
    {"group": "spot", "key": "breakout_auto_score", "default": 75, "category": "threshold",
     "description": "Breakout Hunter — score minimum untuk auto-open"},
    {"group": "spot", "key": "bigmover_min_score", "default": 55, "category": "threshold",
     "description": "BigMover Chase — score minimum untuk tampil"},
    {"group": "spot", "key": "bigmover_auto_score", "default": 65, "category": "threshold",
     "description": "BigMover Chase — score minimum untuk auto-open"},
    {"group": "spot", "key": "early_radar_min_score", "default": 70, "category": "threshold",
     "description": "Early Radar — score minimum untuk tampil (micro-cap = bar tinggi)"},
    {"group": "spot", "key": "early_radar_auto_score", "default": 85, "category": "threshold",
     "description": "Early Radar — score minimum untuk auto-open"},
    # ── SPOT — quota & risk ───────────────────────────────────────────────────
    {"group": "spot", "key": "max_opens_per_cycle", "default": 3, "category": "quota",
     "description": "Max auto-open posisi baru per cycle scan (regime OPEN)"},
    {"group": "spot", "key": "max_bigmover_opens", "default": 2, "category": "quota",
     "description": "Max posisi bigmover_chase terbuka bersamaan"},
    {"group": "spot", "key": "early_radar_max_open", "default": 2, "category": "quota",
     "description": "Max posisi early_radar terbuka bersamaan"},
    {"group": "spot", "key": "daily_loss_limit_pct", "default": 3.0, "category": "risk",
     "description": "Circuit breaker — rugi harian (WIB) sebagai %% balance yang menghentikan auto-open"},

    # ── FUTURES — score threshold ────────────────────────────────────────────
    {"group": "futures", "key": "bigmover_min_score", "default": 60, "category": "threshold",
     "description": "BigMover agent — score minimum (fixed, tanpa adaptive threshold)"},
    # ── FUTURES — quota ───────────────────────────────────────────────────────
    {"group": "futures", "key": "max_auto_positions", "default": 6, "category": "quota",
     "description": "Max posisi futures terbuka bersamaan (GLOBAL, semua lane)"},
    {"group": "futures", "key": "lane_quota_momentum", "default": 2, "category": "quota",
     "description": "Max posisi momentum (agent3) dalam quota global"},
    {"group": "futures", "key": "lane_quota_pre_gainer", "default": 2, "category": "quota",
     "description": "Max posisi pre_gainer (agent1) dalam quota global"},
    {"group": "futures", "key": "lane_quota_accumulation", "default": 1, "category": "quota",
     "description": "Max posisi accumulation (agent2) dalam quota global"},
    {"group": "futures", "key": "max_bigmover_positions", "default": 2, "category": "quota",
     "description": "Max posisi bigmover terbuka (slot terpisah dari quota global)"},
    {"group": "futures", "key": "lane_wr_min_sample", "default": 20, "category": "quota",
     "description": "Jumlah trade rolling sebelum lane WR auto-pause dievaluasi"},
    # ── FUTURES — risk caps ───────────────────────────────────────────────────
    {"group": "futures", "key": "cooldown_hours", "default": 3, "category": "risk",
     "description": "Jam cooldown sebelum re-entry simbol yang baru SL"},
    {"group": "futures", "key": "max_wallet_margin_pct", "default": 70.0, "category": "risk",
     "description": "Cap utilisasi margin wallet cross-margin (%%)"},
    # CATATAN: baris `lane_cap_*` TIDAK ditulis di sini — dibangkitkan per lane
    # oleh `_monitor_lane_defaults()` di bawah, supaya lane baru tak bisa lahir
    # tanpa baris config-nya.
    # NOTE: dd_hard_stop_pct/dd_recover_pct SENGAJA tidak ada di sini —
    # risk_gate._scaled_dd_threshold() menghitungnya otomatis dari ukuran wallet
    # (4 tier: <$500, $500-750, $750-1500, ≥$1500) dan akan menimpa override
    # statis manapun. Lihat risk_gate.py evaluate_risk_gate().
    {"group": "futures", "key": "rar_threshold", "default": -0.5, "category": "risk",
     "description": "Sharpe proxy minimum — di bawah ini RAR gate menutup auto-open"},
    {"group": "futures", "key": "lane_wr_pause_threshold", "default": 0.35, "category": "risk",
     "description": "Win rate lane di bawah ini men-trigger auto-pause 24 jam"},
    # ── FUTURES — PLAN_v15 (anti loss-day / target 25:5) ─────────────────────
    {"group": "futures", "key": "daily_loss_limit_pct", "default": 2.5, "category": "risk",
     "description": "P1: rugi harian realized (WIB) sebagai %% balance yang menghentikan auto-open"},
    {"group": "futures", "key": "daily_profit_lock_pct", "default": 1.0, "category": "risk",
     "description": "P8: day-peak profit (WIB, %% balance) yang mengunci hari — open baru hanya score≥80 @ ½ size"},
    {"group": "futures", "key": "lane_consec_sl_pause", "default": 3, "category": "risk",
     "description": "P2: jumlah loss nyata beruntun per lane (window 6h) sebelum lane pause 12 jam"},
    {"group": "futures", "key": "bigmover_daily_sl_stop", "default": 2, "category": "risk",
     "description": "P3b: jumlah SL nyata BigMover per hari (WIB) sebelum lane BM tutup sampai besok"},
    {"group": "futures", "key": "weekend_size_mult", "default": 0.5, "category": "risk",
     "description": "P3c: pengali size BigMover di Sabtu/Minggu WIB (pump-and-fade risk)"},
    {"group": "futures", "key": "max_same_direction", "default": 4, "category": "quota",
     "description": "P3d: max posisi futures terbuka dengan arah sama (LONG/SHORT)"},
    {"group": "futures", "key": "failfast_atr_mult", "default": 1.0, "category": "risk",
     "description": "P9: kelipatan ATR adverse (10-45 mnt pertama, tanpa progres) yang memicu fail-fast exit"},
    # ── FUTURES — PLAN_v16 (true-cost profit engine) ─────────────────────────
    {"group": "futures", "key": "min_tp1_cost_mult", "default": 3.0, "category": "threshold",
     "description": "F2: TP1 minimum sebagai kelipatan cost_floor (fee+slippage+funding) sebelum posisi boleh dibuka"},
    # ── FUTURES — PLAN_ADAPTIVE_ENGINE_BOOST (Fase B1) ───────────────────────
    {"group": "futures", "key": "expectancy_weighted_training", "default": 0, "category": "learning",
     "description": "DEFAULT 0=OFF. 1 = tiap sampel latih dibobot |net PnL| sehingga model mengejar EXPECTANCY, bukan win-rate. Label biner net>0 membuat model memilih setup yang sering menang tapi menang KECIL — terbukti slice paling diyakini model justru paling rugi (top 20% exp -1,85% PF 0,35; bottom 20% exp +2,98% PF 6,11). Akar sama dgn temuan bobot sinyal B1."},
    {"group": "futures", "key": "drop_order_features", "default": 0, "category": "learning",
     "description": "DEFAULT 0=OFF. 1 = buang fitur parameter ORDER (leverage, risk_pct, rr_ratio, tp1/2/3_pct) dari input model. Parameter itu KITA yang tentukan saat membuka posisi, bukan kondisi pasar — model diminta menebak hasil dari keputusannya sendiri, wajar tak ada sinyal (ablation dampak terbesar cuma 0,0007 vs brier 0,244)."},
    {"group": "futures", "key": "relative_selection_gate", "default": 0, "category": "learning",
     "description": "DEFAULT 0=OFF. 1 = slice 'yang dipilih model' diukur dari kuantil teratas prediksi (relatif), bukan ambang mati 0.55. Ambang absolut mustahil tercapai karena base-rate futures ~44%: terbukti selected_n=0 dari 595 baris uji, sehingga 2 dari 4 syarat promosi gagal permanen apa pun kualitas modelnya. Menyalakan ini membuat syarat promosi BISA dinilai — model tetap harus lolos brier + walk-forward + canary sebelum dipakai."},
    {"group": "futures", "key": "selection_top_frac", "default": 0.20, "category": "learning",
     "description": "Porsi prediksi TERATAS yang dianggap 'dipilih model' saat mode relatif menyala (0.20 = 20% teratas). Hanya berlaku bila relative_selection_gate=1."},
    {"group": "futures", "key": "unified_signal_keys", "default": 1, "category": "learning",
     "description": "BUGFIX (DEFAULT 1=ON): bobot hasil belajar dari trade disimpan memakai kunci SCORING (canonical signal_id:*) sehingga benar-benar dibaca saat menilai kandidat. 0 = perilaku lama (kunci telanjang → bobot tak pernah terpakai, factor selalu 1.0)."},
    {"group": "futures", "key": "repair_weights_persist", "default": 1, "category": "learning",
     "description": "BUGFIX (DEFAULT 1=ON): bobot kunci canonical hasil Adaptive Learning Engine (predictive_repair/weekly_review) TIDAK ditarik balik ke netral 1.0 oleh zombie-pruning, sehingga saran perbaikan benar-benar dipakai agent. 0 = perilaku lama (repair terhapus dalam 1 run 5 menit)."},
    {"group": "futures", "key": "expectancy_aware_weights", "default": 0, "category": "learning",
     "description": "Fase B1 (DEFAULT 0=OFF): 1=target bobot sinyal berbasis EXPECTANCY realized (reward sinyal profit walau win-rate rendah — cocok R:R 1:3), 0=win-rate murni (perilaku lama). Nyalakan HANYA setelah shadow-compare membuktikan lift positif konsisten — mengubah veto auto-open live."},

    # ── FUTURES — MONITOR (ambang keputusan keluar) ──────────────
    {"group": "futures", "key": "monitor_max_age_days", "default": 3.0, "category": "monitor",
     "description": "Umur maksimum posisi futures (hari) sebelum ditutup paksa"},
    {"group": "futures", "key": "monitor_max_age_extensions", "default": 2, "category": "monitor",
     "description": "Berapa kali umur boleh diperpanjang 1 hari untuk posisi yang sedang menang"},
    {"group": "futures", "key": "monitor_rotation_min_days", "default": 1.0, "category": "monitor",
     "description": "Usia minimum sebelum posisi stagnan boleh dirotasi"},
    {"group": "futures", "key": "monitor_rotation_drift_pct", "default": 3.0, "category": "monitor",
     "description": "Gerak <= sekian %% dari entry dianggap stagnan"},
    {"group": "futures", "key": "monitor_rotation_score_gap", "default": 10.0, "category": "monitor",
     "description": "Kandidat pengganti harus unggul skor sebanyak ini"},
    {"group": "futures", "key": "monitor_time_stop_progress_frac", "default": 0.5, "category": "monitor",
     "description": "Kelipatan risk yang harus tercapai agar lolos time-stop"},
    {"group": "futures", "key": "monitor_time_stop_loss_guard_frac", "default": 0.5, "category": "monitor",
     "description": "Bila rugi melewati kelipatan risk ini, serahkan ke SL (jangan scratch)"},
    {"group": "futures", "key": "monitor_rugpull_base_pct", "default": 5.0, "category": "monitor",
     "description": "Ambang minimum gerak melawan untuk deteksi flash dump"},
    {"group": "futures", "key": "monitor_rugpull_min_hold_min", "default": 10.0, "category": "monitor",
     "description": "Menit minimum ditahan sebelum deteksi flash dump aktif"},
    {"group": "futures", "key": "monitor_rugpull_confirm_mult", "default": 1.2, "category": "monitor",
     "description": "Gerak melawan harus sekian kali ambang agar dianggap flash asli"},
    {"group": "futures", "key": "monitor_failfast_min_hold_min", "default": 10.0, "category": "monitor",
     "description": "Menit minimum sebelum fail-fast boleh menutup posisi"},
    {"group": "futures", "key": "monitor_failfast_max_hold_min", "default": 45.0, "category": "monitor",
     "description": "Sesudah menit ini fail-fast berhenti, time-stop yang berwenang"},
    {"group": "futures", "key": "monitor_failfast_progress_frac", "default": 0.3, "category": "monitor",
     "description": "Tak pernah capai kelipatan risk ini = tesis tak berjalan"},
    {"group": "futures", "key": "monitor_failfast_confirm_frac", "default": 0.8, "category": "monitor",
     "description": "Candle sebelumnya harus ikut melawan sebanyak ini (hindari 1 wick)"},
    {"group": "futures", "key": "monitor_min_bank_cost_mult", "default": 3.0, "category": "monitor",
     "description": "Dilarang ambil profit sukarela di bawah sekian kali biaya"},
    {"group": "futures", "key": "monitor_cost_to_profit_gate", "default": 0.3, "category": "monitor",
     "description": "Tutup bila biaya kumulatif melebihi porsi profit ini"},
    {"group": "futures", "key": "monitor_cost_abs_loss_gate_pct", "default": 0.003, "category": "monitor",
     "description": "Tutup posisi rugi bila biaya melebihi porsi notional ini"},
    {"group": "futures", "key": "monitor_bm_be_arm_abs_pct", "default": 1.5, "category": "monitor",
     "description": "BigMover: jarak minimum sebelum breakeven diaktifkan"},
    {"group": "futures", "key": "monitor_bm_half_partial_frac", "default": 0.5, "category": "monitor",
     "description": "BigMover: porsi posisi yang di-de-risk di separuh jalan ke TP1"},
    {"group": "futures", "key": "monitor_tp_max_atr_mult", "default": 0.0, "category": "monitor",
     "description": "PRIORITAS 1 (DEFAULT 0=MATI): batasi jarak TP ke sekian kali ATR. Temuan 1 Agu: TP terpasang 4-13x ATR sementara gerak untung terjauh bermedian 0,41x ATR, sehingga TP tersentuh hanya 1 dari 44 trade. Simulasi: TP 0,5x ATR akan tersentuh 48%, 1x ATR 27%. CATATAN: memperpendek TP saja belum tentu untung karena SL ada di ~1,5x ATR - uji dulu."},
    {"group": "futures", "key": "monitor_rugpull_candles", "default": 5, "category": "monitor",
     "description": "Jumlah candle 1m yang dipindai untuk mendeteksi rug-pull / flash dump"},
    {"group": "futures", "key": "monitor_time_stop_default_min", "default": 360.0, "category": "monitor",
     "description": "Menit time-stop untuk lane yang belum punya angka sendiri (lane baru tidak mewarisi angka lane lain)"},
    {"group": "futures", "key": "monitor_fast_loop_leverage_min", "default": 10.0, "category": "monitor",
     "description": "Leverage minimum yang membuat posisi dipindah ke loop cepat 30 detik"},
    {"group": "futures", "key": "monitor_fast_loop_margin_loss_pct", "default": 30.0, "category": "monitor",
     "description": "Rugi (% margin) yang membuat posisi dipindah ke loop cepat 30 detik"},
    {"group": "futures", "key": "monitor_fast_loop_liq_dist_pct", "default": 10.0, "category": "monitor",
     "description": "Jarak ke harga likuidasi (%) yang membuat posisi dipindah ke loop cepat 30 detik"},
    {"group": "futures", "key": "monitor_failfast_min_sl_gap", "default": 0.0, "category": "monitor",
     "description": "M3 (DEFAULT 0=MATI): fail-fast hanya boleh memotong dini bila jarak SL minimal sekian kali ambang fail-fast. Bukti 1 Agu: di lane ber-SL sempit (bigmover, SL 1,5x ATR vs pemicu 1,0x ATR) pemotongan dini tak menyelamatkan apa pun - 8 exit, 0 menang, satu di antaranya malah rugi lebih besar daripada bila SL dibiarkan bekerja."},
    {"group": "futures", "key": "monitor_exit_learning_enabled", "default": 0.0, "category": "monitor",
     "description": "PRIORITAS 2 (DEFAULT 0=MATI): izinkan monitor memakai batas TP per-lane hasil belajar dari ledger keluar (monitor_tp_atr_mult_lane_*). Selama 0, angka hasil belajar boleh ditulis dan diamati tapi tidak mempengaruhi satu pun keputusan tutup posisi."},

    # ── LEARNING ──────────────────────────────────────────────────────────────
    {"group": "learning", "key": "training_window_days", "default": 90, "category": "timing",
     "description": "Window hari trade yang dipakai untuk update signal weight"},
    {"group": "learning", "key": "decay_half_life_days", "default": 7.0, "category": "timing",
     "description": "Half-life recency decay untuk bobot trade lama"},
    {"group": "learning", "key": "step_cap", "default": 0.10, "category": "threshold",
     "description": "Max perubahan weight per run update (anti-oscillation)"},
    {"group": "learning", "key": "cross_blend", "default": 0.30, "category": "threshold",
     "description": "Porsi pengaruh cross-agent pada weight sinyal final"},
]


def _monitor_lane_defaults() -> list[dict]:
    """Baris config MONITOR yang jumlahnya ikut jumlah lane.

    Ditulis sebagai fungsi, bukan daftar literal, supaya **lane baru otomatis
    dapat barisnya sendiri**. Sebelumnya nama lane diketik tangan empat kali per
    ambang; lane `bigmover` sempat lahir tanpa sebagian barisnya dan tak ada satu
    pun error yang muncul — kegagalannya senyap.

    Nilai bawaannya diambil dari `monitor_config` (sumber yang sama yang dibaca
    monitor saat berjalan), jadi mustahil keduanya berbeda diam-diam.
    """
    from agents.futures import monitor_config as mcfg
    from agents.futures.monitor import _LANE_CAP_DEFAULTS, _MAX_LOSS_DEFAULTS
    from agents.futures.utils import DEFAULT_LANE_CAP, DEFAULT_MAX_LOSS_PCT

    rows: list[dict] = []
    ts_defaults = mcfg._FROZEN["TIME_STOP_MIN_BY_LANE"]
    for lane in mcfg.tunable_lanes():
        rows.append({
            "group": "futures", "key": f"monitor_time_stop_min_{lane}",
            "default": ts_defaults.get(lane, mcfg.TIME_STOP_DEFAULT_MIN),
            "category": "monitor",
            "description": f"Lane {lane}: menit tahan sebelum time-stop menilai tesis gagal",
        })
        rows.append({
            "group": "futures", "key": f"monitor_failfast_enabled_{lane}",
            "default": mcfg.FAILFAST_LANE_DEFAULTS.get(lane, 0.0),
            "category": "monitor",
            "description": (f"Lane {lane}: 1=tunduk fail-fast, 0=tidak. Bukti 1 Agu: "
                            "fail-fast 0% menang di lane ber-SL sempit (bigmover) "
                            "karena pemicunya nyaris berimpit dengan SL."),
        })
        rows.append({
            "group": "futures", "key": mcfg.tp_lane_key(lane),
            "default": 0.0, "category": "monitor",
            "description": (f"Lane {lane}: batas TP dalam kelipatan ATR hasil belajar. "
                            "0 = belum ada, pakai batas global. Hanya berlaku bila "
                            "monitor_exit_learning_enabled menyala."),
        })
        rows.append({
            "group": "futures", "key": mcfg.failfast_gap_key(lane),
            "default": 0.0, "category": "monitor",
            "description": (f"Lane {lane}: gap SL minimum untuk fail-fast, hasil belajar. "
                            "0 = belum ada, pakai gap global. Hanya berlaku bila "
                            "monitor_exit_learning_enabled menyala."),
        })
        rows.append({
            "group": "futures", "key": f"lane_cap_{lane}",
            "default": _LANE_CAP_DEFAULTS.get(lane, DEFAULT_LANE_CAP),
            "category": "risk",
            "description": f"Lane {lane}: batas maksimum jarak SL terhadap margin (%)",
        })
        rows.append({
            "group": "futures", "key": f"monitor_max_loss_pct_{lane}",
            "default": _MAX_LOSS_DEFAULTS.get(lane, DEFAULT_MAX_LOSS_PCT),
            "category": "risk",
            "description": (f"Lane {lane}: rugi maksimum (% margin) sebelum posisi "
                            "di-force-close. Gerbang keluar paling keras."),
        })

    # M4 — lebar SL per lane. Tadinya konstanta di tiga file agen berbeda dan
    # tak satu pun bisa ditala; akibatnya 61% posisi bigmover SL-nya mentok
    # plafon tanpa ada yang bisa melihat, apalagi mengubahnya.
    from agents.futures import sl_config
    _SL_LABEL = {
        "swing_buffer_atr":   "jarak tambahan di bawah/atas swing (kelipatan ATR); 0 = lane ini tak pakai swing",
        "max_pct":            "batas lebar SL (% harga). Lane swing: pemicu hitung-ulang pakai ATR. BigMover: plafon keras",
        "fallback_atr_mult":  "kelipatan ATR saat SL swing terlalu lebar (lane swing) atau rumus utama (BigMover)",
        "floor_pct":          "SL tak boleh lebih sempit dari ini (% harga)",
        "floor_atr_mult":     "lantai kedua: SL tak boleh lebih sempit dari ATR x ini; 0 = tak berlaku",
        "quiet_fallback_pct": "SL tetap untuk koin terlalu sepi; 0 = tak berlaku",
        "quiet_atr_pct":      "ambang koin terlalu sepi (ATR%); 0 = tak berlaku",
    }
    for lane in sl_config.tunable_lanes():
        base = sl_config._FROZEN.get(lane, sl_config.SL_DEFAULTS)
        for param in sl_config.PARAM_NAMES:
            rows.append({
                "group": "futures", "key": sl_config.sl_key(param, lane),
                "default": base[param], "category": "risk",
                "description": f"Lane {lane}: {_SL_LABEL[param]}",
            })

    # Tangga kunci profit — tiap anak tangga satu pasang baris, jumlahnya ikut
    # panjang tangga sehingga menambah/mengurangi tier tak perlu edit di sini.
    for i, (peak, keep) in enumerate(mcfg._FROZEN["PROFIT_LOCK_TIERS"], start=1):
        rows.append({
            "group": "futures", "key": f"monitor_profit_lock_peak_t{i}",
            "default": peak, "category": "monitor",
            "description": f"Kunci profit tier {i}: puncak P&L (% margin) yang memicu tier ini",
        })
        rows.append({
            "group": "futures", "key": f"monitor_profit_lock_keep_t{i}",
            "default": keep, "category": "monitor",
            "description": (f"Kunci profit tier {i}: porsi puncak yang wajib dipertahankan "
                            f"(0.90 = boleh dikembalikan 10%)"),
        })
    return rows


def all_defaults() -> list[dict]:
    """Seluruh baris config bawaan — yang statis maupun yang tumbuh per lane/tier.

    Pakai ini, bukan `DEFAULTS` langsung: `DEFAULTS` saja tidak memuat baris
    per-lane sehingga apa pun yang membacanya akan melihat gambaran yang kurang.
    """
    return DEFAULTS + _monitor_lane_defaults()


async def seed_agent_config_defaults() -> int:
    """
    Insert missing default rows. Never overwrites an existing (group, key) —
    an operator's saved value always wins over the hardcoded default.
    Returns the number of rows inserted.
    """
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_config import AgentConfig

    inserted = 0
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(AgentConfig.agent_group, AgentConfig.key))
        existing_keys = {(g, k) for g, k in existing.all()}

        # Baris statis + baris yang tumbuh mengikuti jumlah lane / tier.
        for d in all_defaults():
            if (d["group"], d["key"]) in existing_keys:
                continue
            session.add(AgentConfig(
                agent_group=d["group"],
                key=d["key"],
                value_num=d["default"],
                default_num=d["default"],
                description=d["description"],
                category=d["category"],
            ))
            inserted += 1

        if inserted:
            await session.commit()

    return inserted
