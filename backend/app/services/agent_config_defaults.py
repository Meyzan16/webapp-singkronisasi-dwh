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
    {"group": "futures", "key": "lane_cap_accumulation", "default": 15.0, "category": "risk",
     "description": "Max margin loss %% untuk lane accumulation sebelum force-close"},
    {"group": "futures", "key": "lane_cap_pre_gainer", "default": 18.0, "category": "risk",
     "description": "Max margin loss %% untuk lane pre_gainer sebelum force-close"},
    {"group": "futures", "key": "lane_cap_momentum", "default": 25.0, "category": "risk",
     "description": "Max margin loss %% untuk lane momentum sebelum force-close"},
    {"group": "futures", "key": "lane_cap_bigmover", "default": 20.0, "category": "risk",
     "description": "Max margin loss %% untuk lane bigmover sebelum force-close"},
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
    {"group": "futures", "key": "expectancy_aware_weights", "default": 0, "category": "learning",
     "description": "Fase B1 (DEFAULT 0=OFF): 1=target bobot sinyal berbasis EXPECTANCY realized (reward sinyal profit walau win-rate rendah — cocok R:R 1:3), 0=win-rate murni (perilaku lama). Nyalakan HANYA setelah shadow-compare membuktikan lift positif konsisten — mengubah veto auto-open live."},

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

        for d in DEFAULTS:
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
