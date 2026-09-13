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
    {"group": "futures", "key": "lane_pause_hours", "default": 24.0, "category": "risk",
     "description": "Durasi jeda PERTAMA sebuah lane saat WR-nya jatuh di bawah ambang"},
    {"group": "futures", "key": "lane_pause_escalation", "default": 2.0, "category": "risk",
     "description": ("Pengali jeda tiap lane dijeda ULANG tanpa membaik. 1,0 = jeda tetap "
                     "(perilaku lama), yang membuat lane rugi jadi pintu putar: jeda -> "
                     "kedaluwarsa -> rugi -> jeda lagi dengan irama tetap.")},
    {"group": "futures", "key": "lane_pause_max_hours", "default": 168.0, "category": "risk",
     "description": ("Batas atas jeda lane (jam). Mencegah lane terkunci selamanya — pasar "
                     "berubah, dan lane tanpa kesempatan tak akan pernah punya bukti baru.")},
    {"group": "spot", "key": "max_auto_opens_per_day", "default": 6, "category": "quota",
     "description": "Jatah auto-open SPOT per hari WIB (semua lane)"},
    {"group": "spot", "key": "bigmover_tp1_pct", "default": 5.0, "category": "threshold",
     "description": "Tangga TP1 BigMover SPOT (% harga)"},
    {"group": "spot", "key": "bigmover_tp2_pct", "default": 12.0, "category": "threshold",
     "description": "Tangga TP2 BigMover SPOT (% harga)"},
    {"group": "spot", "key": "bigmover_tp3_pct", "default": 25.0, "category": "threshold",
     "description": "Tangga TP3 BigMover SPOT (% harga)"},
    # ── FUTURES — quota ───────────────────────────────────────────────────────
    {"group": "futures", "key": "max_auto_positions", "default": 6, "category": "quota",
     "description": "Max posisi futures terbuka bersamaan (GLOBAL, semua lane)"},
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
    {"group": "futures", "key": "max_same_direction", "default": 4, "category": "quota",
     "description": "P3d: max posisi futures terbuka dengan arah sama (LONG/SHORT)"},
    # ── FUTURES — PLAN-FUTURES-AGENTIC (Fase 0 & 1a, 5 Sep 2026) ────────────
    # Saklar induk rewrite. 0 = perilaku lama (4 lane, agent1/2/3/bigmover).
    # Seluruh kode agentic bercabang dari sini, jadi menyalakannya adalah SATU
    # keputusan yang bisa dibatalkan seketika tanpa deploy.
    {"group": "futures", "key": "agentic_enabled", "default": 0, "category": "rollout",
     "description": ("Fase 0: 0=OFF (4 lane lama). 1 = agen tunggal 'agentic' "
                     "mengambil alih pemindaian & sizing. Lihat PLAN-FUTURES-AGENTIC.md.")},

    # ── FUTURES — Fase 3: agen tunggal (agentic.py) ─────────────────────────
    {"group": "futures", "key": "agentic_min_score", "default": 65, "category": "threshold",
     "description": ("Ambang skor TUNGGAL agen agentic. Menggantikan empat ambang lane "
                     "(60-72) plus adaptive threshold yang mengejar win-rate. Satu angka, "
                     "bisa diubah operator, tak bergerak sendiri.")},
    {"group": "futures", "key": "agentic_min_change_24h", "default": 5.0, "category": "threshold",
     "description": "Gerak 24h minimum agar sebuah koin punya tesis momentum"},
    {"group": "futures", "key": "agentic_max_change_24h", "default": 150.0, "category": "threshold",
     "description": "Di atas ini sudah bukan trade — koin dilewati"},
    {"group": "futures", "key": "agentic_min_liquidity_usd", "default": 5_000_000, "category": "risk",
     "description": ("Volume 24h minimum ($). Gerbang, bukan bahan skor: koin tipis melompat "
                     "melewati SL — BLUAI bergerak -8% ke -17,3% di antara dua tick sehingga "
                     "SL 7,99% jadi rugi 2,16x risiko.")},
    {"group": "futures", "key": "agentic_max_funding_pct", "default": 0.25, "category": "risk",
     "description": "Gerbang keras funding (dua arah) — biaya menahan posisi memakan tesisnya"},
    {"group": "futures", "key": "agentic_min_rr", "default": 2.0, "category": "threshold",
     "description": "Rasio R:R minimum (TP2 terhadap SL) agar kandidat layak dibuka"},

    # ── FUTURES — Fase 4: aturan keluar (exit_rules.py) ─────────────────────
    # Sembilan angka menggantikan 38 konstanta monitor + 21 kunci per lane.
    # Bawaannya dari DATA, bukan selera — lihat agents/futures/exit_config.py.
    {"group": "futures", "key": "exit_tp1_atr_mult", "default": 1.2, "category": "exit",
     "description": ("Jarak TP1 dalam kelipatan ATR. TP lama dipasang 4-8 ATR dan hanya "
                     "tersentuh 4% (5 dari 112) karena trade rata-rata cuma bergerak "
                     "0,67 ATR. 1,2 ATR adalah jarak yang MEMANG pernah dicapai.")},
    {"group": "futures", "key": "exit_tp2_atr_mult", "default": 2.5, "category": "exit",
     "description": "Jarak TP2 dalam kelipatan ATR"},
    {"group": "futures", "key": "exit_tp1_close_frac", "default": 0.50, "category": "exit",
     "description": "Porsi posisi yang dijual saat TP1 tersentuh"},
    {"group": "futures", "key": "exit_tp2_close_frac", "default": 0.25, "category": "exit",
     "description": ("Porsi yang dijual saat TP2. Sisanya (25%) jadi PELARI tanpa plafon — "
                     "satu-satunya sumber kemenangan besar; trade terbaik riwayat "
                     "(+13,04%, 3,56 ATR) persis jenis yang dibunuh TP tetap.")},
    {"group": "futures", "key": "exit_be_arm_cost_mult", "default": 3.0, "category": "exit",
     "description": ("Breakeven baru menyala setelah untung >= sekian kali biaya. Rem lama "
                     "menyala di +1,5% absolut lalu ditutup pullback rutin — 31 trade impas "
                     "rata-rata +$0,25, persis fee.")},
    {"group": "futures", "key": "exit_be_arm_atr", "default": 0.6, "category": "exit",
     "description": "…DAN untung juga harus >= sekian ATR, supaya rem tak menyala oleh derau"},
    {"group": "futures", "key": "exit_be_lock_frac", "default": 0.5, "category": "exit",
     "description": ("Saat rem breakeven menyala, SL mengunci sekian bagian untung yang "
                     "sudah dicapai (lantai: entry+biaya). Memindahkan SL tepat ke breakeven "
                     "membuat tiap sentuhan menghasilkan NOL menurut definisi — itulah 31 "
                     "trade sl_plus rata-rata +$0,25.")},
    {"group": "futures", "key": "exit_trail_lock_frac", "default": 0.75, "category": "exit",
     "description": "Sesudah TP1, trailing mengunci sekian bagian dari puncak"},
    {"group": "futures", "key": "exit_max_hold_h", "default": 8.0, "category": "exit",
     "description": ("Batas tahan (jam) sebelum time-stop menilai tesis gagal. Median hold "
                     "pemenang 7,8 jam; yang lebih lama hampir semua berakhir di SL.")},
    {"group": "futures", "key": "exit_time_stop_progress", "default": 0.5, "category": "exit",
     "description": "Progres minimum (x risiko) agar posisi lolos dari time-stop"},
    {"group": "futures", "key": "exit_sl_atr_mult", "default": 1.2, "category": "exit",
     "description": "Jarak SL awal dalam kelipatan ATR (dipakai agen saat menyusun level)"},
    {"group": "futures", "key": "exit_fast_loop_atr", "default": 1.0, "category": "exit",
     "description": ("Posisi masuk loop cepat saat harga sudah sedekat ini (x ATR) ke SL. "
                     "Pemicu lama adalah LEVERAGE >=10x, bukan kedekatan ke SL — sehingga "
                     "BLUAI (leverage 2) dijaga loop lambat dan melompat dari -8% ke -17% "
                     "di antara dua tick.")},

    # Ambang "menang" (bug B1). Sampai 5 Sep 2026 kemenangan cukup `pnl_pct > 0`,
    # sehingga 38 dari 55 "kemenangan" futures membukukan di bawah $0,50 — dan
    # weight_updater melatih tiap bobot sinyal dari label itu. Kini kemenangan
    # menuntut untung yang bermakna: lebih besar dari ambang dolar DAN dari
    # kelipatan biaya trade itu sendiri. SPOT tidak memakai kunci ini.
    {"group": "futures", "key": "win_min_profit_usd", "default": 3.0, "category": "learning",
     "description": ("Untung bersih minimum ($) agar sebuah trade futures dihitung MENANG. "
                     "Di bawah ini dan di atas negatifnya = impas: dibuang dari pelatihan "
                     "bobot dan dari penilaian jeda lane, bukan dihitung kalah.")},
    {"group": "futures", "key": "win_min_cost_mult", "default": 2.0, "category": "learning",
     "description": ("Kemenangan juga harus melebihi sekian kali biaya round-trip trade itu. "
                     "Dua syarat sekaligus: $3 pada posisi $100 itu kemenangan nyata, "
                     "$3 pada posisi $3.000 masih di dalam derau biaya.")},

    # Rantai ukuran: risk → notional → leverage → margin. Sampai 5 Sep 2026
    # bagian yang menentukan BERAPA BESAR uang masuk justru satu-satunya yang tak
    # bisa ditala (18 konstanta di balance.py + 15 di utils.py, nol dibaca dari
    # config). Nilai bawaan di bawah SAMA PERSIS dengan konstanta yang
    # digantikannya — Fase 1a tidak mengubah perilaku, hanya membuka kunci.
    # Sumber kebenaran nilainya: agents/futures/sizing_config.py::_FROZEN
    {"group": "futures", "key": "size_risk_base_pct", "default": 1.0, "category": "sizing",
     "description": "Risiko per trade sebagai %% wallet pada setup biasa (skala naik ke size_risk_max_pct mengikuti conviction)"},
    {"group": "futures", "key": "size_risk_max_pct", "default": 1.5, "category": "sizing",
     "description": "Risiko per trade sebagai %% wallet pada conviction penuh"},
    {"group": "futures", "key": "size_conviction_floor", "default": 72.0, "category": "sizing",
     "description": "Skor tempat penskalaan conviction MULAI (di bawah ini pakai risk base)"},
    {"group": "futures", "key": "size_conviction_ceil", "default": 90.0, "category": "sizing",
     "description": "Skor tempat conviction PENUH (di atas ini pakai risk max)"},
    {"group": "futures", "key": "size_min_notional_abs", "default": 50.0, "category": "sizing",
     "description": "Notional minimum ($) — di bawah ini posisi ditolak sebagai posisi debu"},
    {"group": "futures", "key": "size_portfolio_max_risk_pct", "default": 6.0, "category": "sizing",
     "description": "Portfolio heat: Σ risk posisi terbuka tak boleh lewat %% wallet ini"},
    {"group": "futures", "key": "size_max_margin_pct", "default": 35.0, "category": "sizing",
     "description": "Margin SATU posisi tak boleh lewat %% wallet ini"},
    {"group": "futures", "key": "size_max_notional_mult", "default": 1.5, "category": "sizing",
     "description": "Notional SATU posisi tak boleh lewat kelipatan wallet ini (BUG-L4: SL sempit bisa meniup ukuran)"},
    {"group": "futures", "key": "size_drawdown_cut_pct", "default": 10.0, "category": "sizing",
     "description": "Drawdown dari puncak ekuitas di atas %% ini memotong risiko per trade"},
    {"group": "futures", "key": "size_drawdown_risk_mult", "default": 0.5, "category": "sizing",
     "description": "Pengali risiko saat drawdown melewati ambang di atas"},
    {"group": "futures", "key": "size_margin_loss_at_sl_pct", "default": 20.0, "category": "sizing",
     "description": ("Fase 2 (K3): target rugi margin (%) saat SL kena. Leverage dipilih "
                     "supaya angka ini tercapai berapa pun jarak SL koinnya — inilah yang "
                     "membuat kerugian TERUKUR: satu angka sama untuk semua koin.")},
    {"group": "futures", "key": "lev_min", "default": 2.0, "category": "sizing",
     "description": "Fase 2: leverage minimum yang boleh dipilih mesin ukuran"},
    {"group": "futures", "key": "lev_max", "default": 8.0, "category": "sizing",
     "description": "Fase 2 (K4): leverage maksimum yang boleh dipilih mesin ukuran"},
    {"group": "futures", "key": "size_min_profit_usd", "default": 5.0, "category": "sizing",
     "description": ("Fase 2 (K5): TP1 bersih minimum ($) agar kandidat boleh dibuka. "
                     "Gerbang yang mencegah posisi 'masuk cuma 3 dolar'.")},
    {"group": "futures", "key": "size_min_profit_cost_mult", "default": 4.0, "category": "sizing",
     "description": ("Fase 2: TP1 wajib minimal sekian kali biaya round-trip. Tanpa ini, "
                     "posisi dibuka untuk peluang yang menang pun hanya sebesar fee.")},
    {"group": "futures", "key": "lev_liq_safety_mult", "default": 2.0, "category": "sizing",
     "description": "Jarak likuidasi wajib ≥ jarak SL × angka ini — wick ke SL tak boleh mendarat di zona likuidasi"},
    {"group": "futures", "key": "lev_max_default", "default": 6.0, "category": "sizing",
     "description": "Plafon leverage absolut untuk lane yang belum punya barisnya sendiri"},
    {"group": "futures", "key": "lev_lane_cap_default", "default": 25.0, "category": "sizing",
     "description": "Batas rugi margin di SL (%) untuk lane tanpa lane_cap sendiri"},
    {"group": "futures", "key": "lev_extended_change_24h_pct", "default": 15.0, "category": "sizing",
     "description": "|change 24h| di atas ini = entry terlambat → leverage dibagi dua"},

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

    # ── FUTURES — saklar pembelajaran keluar ──────────────────────────────────
    # Satu-satunya kunci `monitor_*` yang tersisa: ~35 ambang keputusan monitor
    # lane lama dibongkar 13 Sep 2026 bersama jalurnya. Agen tunggal membaca
    # `exit_*` (exit_config) — saklar ini yang mengizinkan `exit_tp1_atr_mult_learned`.
    {"group": "futures", "key": "monitor_exit_learning_enabled", "default": 0.0, "category": "monitor",
     "description": "PRIORITAS 2 (DEFAULT 0=MATI): izinkan agen memakai batas TP hasil belajar dari ledger keluar (exit_tp1_atr_mult_learned). Selama 0, angka hasil belajar boleh ditulis dan diamati tapi tidak mempengaruhi satu pun keputusan tutup posisi."},

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
    """Baris config yang jumlahnya ikut jumlah lane.

    FUTURES: hanya `lev_max_<lane>` untuk lane agen AKTIF. Baris per-lane monitor
    lama (time-stop, fail-fast, batas TP per lane, lane_cap, max-loss, tujuh
    parameter SL per lane) dibongkar 13 Sep 2026 bersama jalur yang membacanya —
    dulu 7 baris × 5 lane + 7 parameter SL × 4 lane = 63 tombol tala yang
    tampil di Architecture tanpa satu pun pembaca.

    Nilai bawaan diambil dari `sizing_config` — sumber yang SAMA yang dibaca
    agen saat berjalan, jadi mustahil keduanya berbeda diam-diam.
    """
    from agents.futures import sizing_config as szcfg

    rows: list[dict] = []
    for lane in szcfg.tunable_lanes():
        rows.append({
            "group": "futures", "key": f"lev_max_{lane}",
            "default": szcfg._FROZEN_LEV_MAX_LANE.get(lane, szcfg._FROZEN["lev_max_default"]),
            "category": "sizing",
            "description": (f"Lane {lane}: plafon leverage ABSOLUT, berlaku di atas "
                            "batas margin & likuidasi (yang terkecil menang)"),
        })

    # ── MONITOR SPOT ──────────────────────────────────────────────────────────
    # Sampai 8 Agu 2026 monitor SPOT punya NOL titik baca config: 16 ambang
    # keputusan keluar terkunci di kode, jadi hasil belajar sisi keluar SPOT tak
    # punya jalan untuk sampai ke agen yang membuat keputusan itu.
    from agents.opportunity import monitor_config as scfg
    _SPOT_LABEL = {
        "monitor_stagnant_check_days":     "hari sebelum posisi dinilai stagnan",
        "monitor_stagnant_drift_pct":      "±% dari entry yang dianggap tak bergerak",
        "monitor_stagnant_score_gap":      "keunggulan skor kandidat untuk rotasi stagnan",
        "monitor_urgent_rotation_days":    "hari minimum sebelum rotasi mendesak boleh",
        "monitor_urgent_score_gap":        "keunggulan skor untuk rotasi mendesak",
        "monitor_urgent_score_min":        "skor minimum kandidat rotasi mendesak",
        "monitor_rotation_min_pnl_pct":    "lantai P&L: rotasi tak boleh membukukan rugi di bawah ini",
        "monitor_max_age_fresh_setup":     "umur maksimum posisi fresh_setup (hari)",
        "monitor_max_age_momentum_chase":  "umur maksimum posisi momentum_chase (hari)",
        "monitor_max_age_bigmover":        "umur maksimum posisi bigmover (hari)",
        "monitor_gate_min_score":          "skor live minimum agar posisi dianggap masih kuat",
        "monitor_gate_min_taker":          "rasio taker-buy minimum agar dianggap masih kuat",
        "monitor_gate_min_vol_ratio":      "rasio volume minimum agar dianggap masih kuat",
        "monitor_dyn_rung_atr_mult":       "jarak rung dinamis berikutnya (kelipatan ATR)",
        "monitor_dyn_rung_step_pct":       "lantai jarak rung bila ATR terlalu kecil (%)",
        "monitor_min_hold_minutes":        "menit tahan minimum sebelum exit risk-adjusted boleh",
        "monitor_trend_reversal_min_hold_min": "trend_reversal: menit tahan minimum sebelum silang EMA dianggap sah",
        "monitor_trend_reversal_ema_buffer":   "trend_reversal: ema9 harus di bawah ema21 x nilai ini (0,998 = butuh silang 0,2%)",
        "monitor_trend_reversal_profit_floor_frac": ("trend_reversal: lantai profit sebagai porsi jarak ke TP2. "
                                            "0 = perilaku lama (keluar walau rugi). Bukti 9 Agu: pemicu ini "
                                            "menutup 10 posisi dgn WR 10% dan expectancy -1,191% - satu-satunya "
                                            "pemicu SPOT yang merugikan. Menaikkannya menyerahkan struktur patah "
                                            "saat rugi ke SL."),
        "monitor_struct_sl_buffer_frac": ("buffer di bawah struktur (EMA21 4h / swing-low) saat menghitung "
                                            "trailing SL. 0,99 = 1% di bawah. Angka ini menentukan LETAK SL."),
        "monitor_trail_lock_after_tp1_frac": ("porsi keuntungan TP1 yang dikunci saat TP1 tersentuh "
                                            "(SL -> entry + frac x gain). SPOT memakai 0,5; futures 0,75."),
        "monitor_trail_advance_tp1_tp2_frac": ("porsi jarak TP1->TP2 yang harus ditempuh sebelum SL "
                                            "naik ke TP1. 1,0 = perilaku lama (lantai baru naik saat TP2 "
                                            "benar-benar tersentuh). Diturunkan = keuntungan TP1 diamankan "
                                            "lebih awal. Futures memakai 0,5."),
        "monitor_trail_floor_max_of_price": ("batas anti-wick: lantai SL tak boleh di atas harga x nilai ini, "
                                            "kalau tidak SL langsung tersentuh sumbu candle berjalan"),
        "monitor_momentum_be_trigger_pct": "momentum_entry: untung % yang memicu SL pindah ke breakeven",
        "monitor_momentum_be_buffer_frac": ("momentum_entry: SL breakeven dipasang di entry x nilai ini "
                                            "(1,001 = 0,1% di atas entry, supaya keluar tak rugi ongkos)"),
        "monitor_exit_learning_enabled":   ("DEFAULT 0=MATI: izinkan monitor SPOT memakai batas TP "
                                            "per-lane hasil belajar. Saklar TERPISAH dari futures — "
                                            "satu perubahan diuji di satu tempat."),
    }
    for var, key in scfg._KEYS.items():
        rows.append({
            # `default_of` BUKAN `getattr`: setelah refresh menarik override,
            # nilai modul sudah bukan bawaan lagi — mencatatnya di sini akan
            # membuat bawaan hanyut mengikuti override.
            "group": "spot", "key": key, "default": scfg.default_of(var),
            "category": "monitor", "description": _SPOT_LABEL[key],
        })
    for lane in scfg.tunable_lanes():
        rows.append({
            "group": "spot", "key": scfg.tp_lane_key(lane),
            "default": 0.0, "category": "monitor",
            "description": (f"Lane {lane}: batas TP dalam kelipatan ATR hasil belajar. "
                            "0 = belum ada. Hanya berlaku bila spot."
                            "monitor_exit_learning_enabled menyala."),
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
