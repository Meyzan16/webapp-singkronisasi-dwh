"""
Agent Config — live runtime constants from all trading agents (PLAN_v5 Group B)
plus the DB-editable subset (PLAN_v5 Group C).

GET   /agent/config              — live snapshot read straight from agent modules
GET   /agent/config/all          — every agent_config row (for the Settings editor)
PATCH /agent/config/{group}/{key} — update a value (agents pick it up within 60s)
POST  /agent/config/{group}/{key}/reset — revert a row to its hardcoded default

Reads constants DIRECTLY from agent modules (scanner.py, scheduler.py, monitor.py,
agent1/2/3/bigmover.py, auto_trader.py, risk_gate.py, weight_updater.py,
cross_agent_learning.py) — no duplication, no data.ts drift. Whatever the agents
actually run with is what this endpoint reports.

Each section is wrapped independently so one broken import doesn't 500 the whole
response — the architecture page can still render partial data.
"""

import time

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(tags=["agent-config"])
logger = structlog.get_logger(__name__)


async def _spot_config() -> dict:
    from agents.opportunity import scanner as sc
    from agents.opportunity import scheduler as sched
    from agents.opportunity import monitor as mon
    from agents.shared.config_reader import cfg

    # PLAN_v5 Group C fix: backend and agents run in SEPARATE processes/containers
    # (docker-compose has a dedicated `agents` service) — module attributes here
    # never see the `global` reassignment agents apply to THEIR OWN process
    # memory. Reading through cfg.get() queries the DB directly, so this stays
    # accurate regardless of process topology or how long ago the agent last
    # refreshed its own cache.
    min_quote_volume    = await cfg.get("spot", "min_quote_volume", sc.MIN_QUOTE_VOLUME)
    breakout_min_volume = await cfg.get("spot", "breakout_min_volume", sc.BREAKOUT_MIN_VOLUME)
    bigmover_min_volume = await cfg.get("spot", "bigmover_min_volume", sc.BIGMOVER_MIN_VOLUME)
    weekly_min_volume   = await cfg.get("spot", "weekly_min_volume", sc.WEEKLY_SCAN_MIN_VOLUME)
    early_radar_min_vol = await cfg.get("spot", "early_radar_min_volume", sc.EARLY_RADAR_VOL_MIN)
    min_score           = await cfg.get("spot", "min_score", sc.MIN_SCORE)
    auto_open_score      = await cfg.get("spot", "auto_open_score", sc.AUTO_OPEN_SCORE)
    breakout_min_score   = await cfg.get("spot", "breakout_min_score", sc.BREAKOUT_MIN_SCORE)
    breakout_auto_score  = await cfg.get("spot", "breakout_auto_score", sc.BREAKOUT_AUTO_SCORE)
    bigmover_min_score   = await cfg.get("spot", "bigmover_min_score", sc.BIGMOVER_MIN_SCORE)
    bigmover_auto_score  = await cfg.get("spot", "bigmover_auto_score", sc.BIGMOVER_AUTO_SCORE)
    early_radar_min_score  = await cfg.get("spot", "early_radar_min_score", sc.EARLY_RADAR_MIN_SCORE)
    early_radar_auto_score = await cfg.get("spot", "early_radar_auto_score", sc.EARLY_RADAR_AUTO_SCORE)
    max_opens_per_cycle  = await cfg.get("spot", "max_opens_per_cycle", sched.MAX_OPENS_PER_CYCLE)
    max_bigmover_opens   = await cfg.get("spot", "max_bigmover_opens", sched.MAX_BIGMOVER_OPENS)
    early_radar_max_open = await cfg.get("spot", "early_radar_max_open", sc.EARLY_RADAR_MAX_OPEN)
    daily_loss_limit_pct = await cfg.get("spot", "daily_loss_limit_pct", sched.DAILY_LOSS_LIMIT_FRACTION * 100)

    return {
        "scan_interval_sec": sched.INTERVAL_SEC,
        "monitor_interval_sec": mon.INTERVAL_SEC,
        "fastpass": {
            "bigmover_interval_sec": sched.BIGMOVER_FASTPASS_SEC,
            "bigmover_min_change_pct": sched.BIGMOVER_FASTPASS_MIN_PCT,
        },
        "min_volume": {
            "accumulation": min_quote_volume,
            "breakout":     breakout_min_volume,
            "bigmover":     bigmover_min_volume,
            "weekly":       weekly_min_volume,
            "early_radar":  early_radar_min_vol,
        },
        "score_thresholds": {
            "accumulation": {"min": min_score,          "auto": auto_open_score},
            "breakout":     {"min": breakout_min_score, "auto": breakout_auto_score},
            "bigmover":     {"min": bigmover_min_score, "auto": bigmover_auto_score},
            "early_radar":  {"min": early_radar_min_score, "auto": early_radar_auto_score},
        },
        "bigmover": {
            "min_change_24h_pct":      sc.BIGMOVER_MIN_CHANGE_24H,
            "max_change_24h_pct":      sc.BIGMOVER_MAX_CHANGE_24H,
            "explosive_threshold_pct": sc.BIGMOVER_EXPLOSIVE_THRESHOLD,
            "tp_standard_pct":  [sc.BIGMOVER_TP1_PCT, sc.BIGMOVER_TP2_PCT, sc.BIGMOVER_TP3_PCT],
            "tp_explosive_pct": [sc.BIGMOVER_EXPLOSIVE_TP1_PCT, sc.BIGMOVER_EXPLOSIVE_TP2_PCT, sc.BIGMOVER_EXPLOSIVE_TP3_PCT],
        },
        "early_radar": {
            "vol_range":        [early_radar_min_vol, sc.EARLY_RADAR_VOL_MAX],
            "surge_min":        sc.EARLY_RADAR_SURGE_MIN,
            "surge_strong":     sc.EARLY_RADAR_SURGE_STRONG,
            "near_high_pct":    sc.EARLY_RADAR_NEAR_HIGH_PCT,
            "risk_pct":         sc.EARLY_RADAR_RISK_PCT,
            "max_open":         int(early_radar_max_open),
            "rr_min":           sc.EARLY_RADAR_RR_MIN,
            "tp_pct":           [sc.EARLY_RADAR_TP1_PCT, sc.EARLY_RADAR_TP2_PCT, sc.EARLY_RADAR_TP3_PCT],
        },
        "regime_gates": {
            "closed_btc_24h_pct":  sc.BTC_REGIME_CLOSED_24H,
            "reduced_btc_24h_pct": sc.BTC_REGIME_REDUCED_24H,
        },
        "quota": {
            "max_opens_per_cycle":          int(max_opens_per_cycle),
            "max_opens_per_cycle_reduced":  sched.MAX_OPENS_PER_CYCLE_REDUCED,
            "max_bigmover_opens":           int(max_bigmover_opens),
            "daily_loss_limit_pct":         round(daily_loss_limit_pct, 2),
        },
        "monitor": {
            "min_hold_minutes":         mon.MIN_HOLD_MINUTES,
            "max_age_fresh_setup_days": mon.MAX_AGE_DAYS_FRESH_SETUP,
            "max_age_momentum_days":    mon.MAX_AGE_DAYS_MOMENTUM_CHASE,
            "profit_lock_tiers": [
                {"peak_pct": p, "lock_frac": f} for p, f in mon._PROFIT_LOCK_TIERS_SPOT
            ],
        },
    }


async def _futures_config() -> dict:
    from agents.futures import scheduler as fsched
    from agents.futures import monitor as fmon
    from agents.futures import auto_trader as at
    from agents.futures import risk_gate as rg
    from agents.futures import agent1, agent2, agent3, agent_bigmover
    from agents.futures import weight_updater as fwu
    from agents.futures.utils import MAX_SL_MARGIN_PCT_BY_LANE
    from agents.shared.config_reader import cfg

    # pre_gainer/accumulation score thresholds are adaptive (F69) — read the LIVE
    # value from weight_updater, not a hardcoded default. Falls back to 52/72
    # (weight_updater's own default) when no adaptive data has accumulated yet.
    t1 = fwu.get_adaptive_thresholds(agent1.AGENT_NAME)
    t2 = fwu.get_adaptive_thresholds(agent2.AGENT_NAME)

    # PLAN_v5 Group C fix: read through cfg.get() (queries DB directly) rather
    # than the module attribute — backend and the `agents` container are
    # separate processes, so a `global` reassignment in the agents process
    # never reaches this one. See _spot_config() for the full rationale.
    bigmover_min_score  = await cfg.get("futures", "bigmover_min_score", agent_bigmover.MIN_SCORE)
    max_auto_positions  = await cfg.get("futures", "max_auto_positions", at.MAX_AUTO_POSITIONS)
    lane_quota_momentum = await cfg.get("futures", "lane_quota_momentum", at.LANE_QUOTAS["momentum"])
    lane_quota_pregain  = await cfg.get("futures", "lane_quota_pre_gainer", at.LANE_QUOTAS["pre_gainer"])
    lane_quota_accum    = await cfg.get("futures", "lane_quota_accumulation", at.LANE_QUOTAS["accumulation"])
    max_bigmover_pos    = await cfg.get("futures", "max_bigmover_positions", at.MAX_BIGMOVER_POSITIONS)
    cooldown_hours      = await cfg.get("futures", "cooldown_hours", at.FUTURES_COOLDOWN_HOURS)
    max_wallet_margin   = await cfg.get("futures", "max_wallet_margin_pct", at.MAX_WALLET_MARGIN_PCT)
    lane_cap_accum      = await cfg.get("futures", "lane_cap_accumulation", MAX_SL_MARGIN_PCT_BY_LANE["accumulation"])
    lane_cap_pregain    = await cfg.get("futures", "lane_cap_pre_gainer", MAX_SL_MARGIN_PCT_BY_LANE["pre_gainer"])
    lane_cap_momentum   = await cfg.get("futures", "lane_cap_momentum", MAX_SL_MARGIN_PCT_BY_LANE["momentum"])
    lane_cap_bigmover   = await cfg.get("futures", "lane_cap_bigmover", MAX_SL_MARGIN_PCT_BY_LANE["bigmover"])
    rar_threshold       = await cfg.get("futures", "rar_threshold", rg.RAR_GATE_THRESHOLD)
    lane_wr_pause       = await cfg.get("futures", "lane_wr_pause_threshold", rg.LANE_WR_PAUSE_THRESHOLD)
    lane_wr_min_sample  = await cfg.get("futures", "lane_wr_min_sample", rg.LANE_WR_MIN_SAMPLE)
    # PLAN_v15 — daily gates & fade-day knobs
    daily_loss_limit    = await cfg.get("futures", "daily_loss_limit_pct", rg.DAILY_LOSS_LIMIT_PCT)
    daily_profit_lock   = await cfg.get("futures", "daily_profit_lock_pct", rg.DAILY_PROFIT_LOCK_PCT)
    lane_consec_sl      = await cfg.get("futures", "lane_consec_sl_pause", rg.CONSEC_SL_LANE_LIMIT)
    bm_daily_sl_stop    = await cfg.get("futures", "bigmover_daily_sl_stop", at.BIGMOVER_DAILY_SL_STOP)
    weekend_size_mult   = await cfg.get("futures", "weekend_size_mult", agent_bigmover.WEEKEND_SIZE_MULT)
    max_same_direction  = await cfg.get("futures", "max_same_direction", at.MAX_SAME_DIRECTION)
    failfast_atr_mult   = await cfg.get("futures", "failfast_atr_mult", fmon.FAILFAST_ATR_MULT)

    return {
        "scan_interval_sec": fsched.INTERVAL_SEC,
        "monitor_interval_sec": fmon.INTERVAL_SEC,
        "universe_cap": fsched.UNIVERSE_CAP,
        "big_mover_threshold_pct": fsched.BIG_MOVER_THRESHOLD,
        "agents": {
            "pre_gainer":   {"min_score": t1["min_score"], "auto_score": t1["auto_threshold"], "min_rr": agent1.MIN_RR, "adaptive": True},
            "accumulation": {"min_score": t2["min_score"], "auto_score": t2["auto_threshold"], "min_rr": 3.0, "adaptive": True},
            "momentum":     {"min_score": agent3.MIN_SCORE, "min_rr": agent3.MIN_RR, "leverage_max": agent3._MAX_LEV, "adaptive": False},
            "bigmover":     {
                "min_score": bigmover_min_score,
                "min_rr": agent_bigmover.MIN_RR,
                "leverage_fixed": agent_bigmover.FIXED_LEVERAGE,
                "risk_pct": agent_bigmover.RISK_PCT_DEFAULT,
                "min_change_24h_pct": agent_bigmover.MIN_CHANGE_24H,
                "max_change_24h_pct": agent_bigmover.MAX_CHANGE_24H,
                "adaptive": False,
            },
        },
        "auto_trader": {
            "max_positions_global": int(max_auto_positions),
            "lane_quotas": {
                "momentum":     int(lane_quota_momentum),
                "pre_gainer":   int(lane_quota_pregain),
                "accumulation": int(lane_quota_accum),
            },
            "max_bigmover_positions": int(max_bigmover_pos),
            "cooldown_hours":        cooldown_hours,
            "max_wallet_margin_pct": max_wallet_margin,
            "funding_gate_long_pct":  at.MAX_LONG_FUNDING_PCT,
            "funding_gate_short_pct": at.MIN_SHORT_FUNDING_PCT,
            "auto_open_threshold_fallback": at.AUTO_OPEN_THRESHOLD,
        },
        "monitor": {
            "max_age_days":       fmon.MAX_AGE_DAYS,
            "max_age_extensions": fmon.MAX_AGE_EXTENSIONS,
            "lane_margin_caps_pct": {
                "accumulation": lane_cap_accum,
                "pre_gainer":   lane_cap_pregain,
                "pre_move":     lane_cap_pregain,   # legacy alias
                "momentum":     lane_cap_momentum,
                "bigmover":     lane_cap_bigmover,
            },
        },
        "risk_gate": {
            "dd_hard_stop_pct":       rg.DD_HARD_STOP_PCT,   # computed live from wallet size — see PLAN_v5
            "dd_recover_pct":         rg.DD_RECOVER_PCT,
            "rar_threshold":          rar_threshold,
            "rar_min_trades":         rg.RAR_MIN_TRADES,
            "lane_wr_pause_threshold": lane_wr_pause,
            "lane_wr_min_sample":      int(lane_wr_min_sample),
        },
        "plan_v15": {   # anti loss-day / target 25 win-day : 5 loss-day
            "daily_loss_limit_pct":      daily_loss_limit,
            "daily_profit_lock_pct":     daily_profit_lock,
            "profit_giveback_floor_pct": rg.PROFIT_GIVEBACK_FLOOR_PCT,
            "lane_consec_sl_pause":      int(lane_consec_sl),
            "consec_sl_window_h":        rg.CONSEC_SL_WINDOW_H,
            "bigmover_daily_sl_stop":    int(bm_daily_sl_stop),
            "bigmover_daily_budget":     at.BIGMOVER_DAILY_BUDGET,
            "weekend_size_mult":         weekend_size_mult,
            "max_same_direction":        int(max_same_direction),
            "failfast_atr_mult":         failfast_atr_mult,
            "breadth_fade_frac":         at.BREADTH_FADE_FRAC,
            "daily_gates":               rg.get_daily_gates(),
        },
    }


async def _learning_config() -> dict:
    from agents.opportunity import weight_updater as wu
    from agents.shared import cross_agent_learning as cal
    from agents.shared.config_reader import cfg

    training_window_days = await cfg.get("learning", "training_window_days", wu.TRAINING_WINDOW_D)
    decay_half_life_days  = await cfg.get("learning", "decay_half_life_days", wu.DECAY_HALF_LIFE_D)
    step_cap              = await cfg.get("learning", "step_cap", wu.STEP_CAP)
    cross_blend           = await cfg.get("learning", "cross_blend", cal.CROSS_BLEND)

    return {
        "training_window_days": training_window_days,
        "decay_half_life_days": decay_half_life_days,
        "step_cap": step_cap,
        "stale_key_max_days": wu.STALE_KEY_MAX_D,
        "cross_agent": {
            "blend_pct": round(cross_blend * 100, 1),
            "min_sample": cal.MIN_CROSS_SAMPLE,
        },
    }


@router.get("/agent/config")
async def get_agent_config() -> dict:
    """
    Live runtime constants for the architecture page — read directly from
    agent modules so this endpoint can never drift from what agents run.
    """
    result: dict = {"spot": {}, "futures": {}, "learning": {}, "errors": []}

    for section, loader in (
        ("spot", _spot_config),
        ("futures", _futures_config),
        ("learning", _learning_config),
    ):
        try:
            result[section] = await loader()
        except Exception as exc:
            logger.warning("agent_config_section_failed", section=section, error=str(exc)[:120])
            result["errors"].append(f"{section}: {str(exc)[:120]}")

    return result


# ── DB-editable subset (PLAN_v5 Group C — Settings UI) ───────────────────────

@router.get("/agent/config/all")
async def list_agent_config_rows() -> list[dict]:
    """Every agent_config row — powers the Settings > Agent Config editor table."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.agent_config import AgentConfig

    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AgentConfig).order_by(AgentConfig.agent_group, AgentConfig.category, AgentConfig.key)
        )).scalars().all()
        return [
            {
                "id": r.id,
                "agent_group": r.agent_group,
                "key": r.key,
                "value": r.value_num,
                "default": r.default_num,
                "modified": r.value_num != r.default_num,
                "description": r.description,
                "category": r.category,
                "updated_at": r.updated_at,
                "updated_by": r.updated_by,
            }
            for r in rows
        ]


class ConfigUpdateBody(BaseModel):
    value: float = Field(..., description="New numeric value")
    updated_by: str = Field(default="settings_ui", max_length=40)


@router.patch("/agent/config/{group}/{key}")
async def update_agent_config(group: str, key: str, body: ConfigUpdateBody) -> dict:
    """
    Update a config value. Agents pick it up within 60s (config_reader TTL cache) —
    no redeploy needed. Sanity-checked against the default to catch fat-fingers:
    rejects values more than 10x the default's magnitude away from it.
    """
    from sqlalchemy import select
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.agent_config import AgentConfig

    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(AgentConfig).where(AgentConfig.agent_group == group, AgentConfig.key == key)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No config row for {group}.{key}")

        # Sanity bound: keep the new value within a generous multiple of the
        # default's magnitude — catches "typed an extra zero" without being so
        # strict it blocks legitimate retuning.
        bound = abs(row.default_num) * 10 + 100
        if not (-bound <= body.value <= bound):
            raise HTTPException(
                status_code=400,
                detail=f"Value {body.value} out of sane range for {group}.{key} "
                       f"(default {row.default_num}, allowed ±{bound})",
            )

        row.value_num  = body.value
        row.updated_at = time.time()
        row.updated_by = body.updated_by
        await session.commit()

        logger.info("agent_config_updated", group=group, key=key, value=body.value, by=body.updated_by)
        return {"ok": True, "group": group, "key": key, "value": row.value_num}


@router.post("/agent/config/{group}/{key}/reset")
async def reset_agent_config(group: str, key: str) -> dict:
    """Revert a config row to its hardcoded default."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.agent_config import AgentConfig

    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(AgentConfig).where(AgentConfig.agent_group == group, AgentConfig.key == key)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail=f"No config row for {group}.{key}")

        row.value_num  = row.default_num
        row.updated_at = time.time()
        row.updated_by = "reset"
        await session.commit()

        logger.info("agent_config_reset", group=group, key=key, value=row.value_num)
        return {"ok": True, "group": group, "key": key, "value": row.value_num}
