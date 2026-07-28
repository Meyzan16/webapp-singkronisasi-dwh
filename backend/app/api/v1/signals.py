"""
Signal Performance API — SP4 + PLAN_v2 P3.

GET /api/v1/signals/performance           — all signal weights with stats, filterable
GET /api/v1/signals/cross_agent           — cross-agent comparison per signal
GET /api/v1/signals/{signal_key}/history  — weight trajectory timeseries (P3.1)
GET /api/v1/signals/{signal_key}/explain  — explain current weight for a signal (P3.2)
GET /api/v1/signals/catalog               — signal → formula → agent mapping (P3.3)
GET /api/v1/signals/regime_heatmap        — weight per (signal, regime) heatmap (P3.5)
GET /api/v1/signals/updater/state         — state of weight updaters
POST /api/v1/signals/updater/run          — force-run all weight updaters
"""

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, require_db
from app.models.signal_weight import AgentSignalWeight
from app.models.signal_weight_history import SignalWeightHistory
from app.models.spot_decision_event import SpotDecisionEvent
from app.models.spot_model_version import SpotModelVersion

router = APIRouter(tags=["signals"])

ALL_AGENTS = [
    "opportunity_spot",
    "futures_agent1",
    "futures_agent2",
    "futures_agent3",
    "cross_agent",
]

AGENT_LABELS = {
    "opportunity_spot": "SPOT",
    "futures_agent1":   "Pre-Gainer",
    "futures_agent2":   "Accumulation",
    "futures_agent3":   "Momentum",
    "cross_agent":      "Cross-Agent",
}

# TTL cache endpoint adaptive-engine: agregasi ledger puluhan-ribu baris mahal
# (dulu ~8 dtk -> ECONNRESET). Poll UI berulang dilayani dari cache; recompute
# paling sering tiap _ENGINE_TTL detik. Data engine berubah lambat (jam-an) jadi aman.
_ENGINE_CACHE: dict = {"spot": {"ts": 0.0, "data": None}, "futures": {"ts": 0.0, "data": None}}
_ENGINE_TTL = 45.0


@router.get("/signals/adaptive-engine", dependencies=[Depends(require_db)])
async def get_adaptive_engine() -> dict:
    """Current SPOT Adaptive Learning Engine state for Signal Performance UI."""
    _c = _ENGINE_CACHE["spot"]
    if _c["data"] is not None and (time.time() - _c["ts"]) < _ENGINE_TTL:
        return _c["data"]
    now = time.time()
    async with AsyncSessionLocal() as session:
        models = list((await session.execute(
            select(SpotModelVersion).order_by(SpotModelVersion.trained_at.desc())
        )).scalars().all())
        total_decisions = int(await session.scalar(select(func.count(SpotDecisionEvent.id))) or 0)
        unique_keys = int(await session.scalar(select(func.count(func.distinct(SpotDecisionEvent.decision_key)))) or 0)
        action_counts = dict((await session.execute(
            select(SpotDecisionEvent.action, func.count(SpotDecisionEvent.id)).group_by(SpotDecisionEvent.action)
        )).all())
        outcome_counts = dict((await session.execute(
            select(SpotDecisionEvent.outcome_status, func.count(SpotDecisionEvent.id)).group_by(SpotDecisionEvent.outcome_status)
        )).all())
        due_24h = int(await session.scalar(select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts <= now - 24 * 3600
        )) or 0)
        labelled_24h = int(await session.scalar(select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts <= now - 24 * 3600,
            SpotDecisionEvent.pnl_24h_pct.isnot(None),
        )) or 0)
        # mature_feature_samples via SQL count (dulu: muat ~puluhan-ribu blob JSON
        # lalu parse di Python -> ~8 detik/request -> ECONNRESET). feature_snapshot_json
        # ditulis json.dumps(sort_keys=True) default separators -> `"key": value`.
        # Hitung baris matang yang punya challenger_features NON-KOSONG.
        mature_feature_samples = int(await session.scalar(
            select(func.count(SpotDecisionEvent.id)).where(
                SpotDecisionEvent.pnl_24h_pct.isnot(None),
                SpotDecisionEvent.feature_snapshot_json.like('%"challenger_features": %'),
                SpotDecisionEvent.feature_snapshot_json.notlike('%"challenger_features": {}%'),
                SpotDecisionEvent.feature_snapshot_json.notlike('%"challenger_features": []%'),
                SpotDecisionEvent.feature_snapshot_json.notlike('%"challenger_features": null%'),
            )
        ) or 0)
        missing_snapshots = int(await session.scalar(select(func.count(SpotDecisionEvent.id)).where(
            (SpotDecisionEvent.feature_snapshot_json.is_(None)) |
            (SpotDecisionEvent.feature_snapshot_json == "")
        )) or 0)
        future_events = int(await session.scalar(select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.scan_ts > now + 60
        )) or 0)
        invalid_closes = int(await session.scalar(select(func.count(SpotDecisionEvent.id)).where(
            SpotDecisionEvent.closed_at.isnot(None),
            SpotDecisionEvent.closed_at < SpotDecisionEvent.scan_ts,
        )) or 0)

    model_payload = []
    for model in models[:10]:
        try:
            metrics = json.loads(model.metrics_json or "{}")
        except (TypeError, json.JSONDecodeError):
            metrics = {}
        model_payload.append({
            "version": model.version,
            "status": model.status,
            "trained_at": model.trained_at,
            "promoted_at": model.promoted_at,
            "training_n": metrics.get("training_n", 0),
            "promotion_eligible": bool(metrics.get("promotion_eligible")),
            "test": metrics.get("test", {}),
            "canary": metrics.get("canary"),
        })

    try:
        from agents.learning.spot_walkforward import run_spot_walkforward
        walkforward = await run_spot_walkforward()
    except Exception as exc:
        walkforward = {"status": "error", "error": str(exc)[:120]}

    try:
        from agents.opportunity.onchain_provider import get_state as onchain_state
        onchain = onchain_state()
    except Exception as exc:
        onchain = {"configured": False, "error": str(exc)[:120]}

    try:
        from agents.opportunity.weight_updater import get_state as spot_weight_state
        weight_state = spot_weight_state()
    except Exception as exc:
        weight_state = {"last_error": str(exc)[:120]}

    quality = {
        "duplicate_keys": total_decisions - unique_keys,
        "missing_snapshots": missing_snapshots,
        "future_events": future_events,
        "invalid_closes": invalid_closes,
    }
    outcome_completeness = round(labelled_24h / due_24h * 100, 1) if due_24h else 100.0
    latest_model = model_payload[0] if model_payload else None
    gates = {
        "training_data": mature_feature_samples >= 60,
        "test_samples": bool(
            latest_model and int((latest_model.get("test") or {}).get("n", 0)) >= 20
        ),
        "promotion_eligible": bool(latest_model and latest_model.get("promotion_eligible")),
        "outcome_completeness": outcome_completeness >= 99.0,
        "data_quality": all(value == 0 for value in quality.values()),
        "champion_exists": any(model.status == "champion" for model in models),
        "rollback_ready": any(model.status == "retired" for model in models),
    }
    result = {
        "engine_status": (
            "degraded" if weight_state.get("last_error") or not gates["data_quality"]
            else "collecting" if not gates["training_data"]
            else "shadow" if not gates["promotion_eligible"]
            else "canary" if not gates["champion_exists"]
            else "champion"
        ),
        "decision_ledger": {
            "total": total_decisions,
            "actions": action_counts,
            "outcomes": outcome_counts,
            "due_24h": due_24h,
            "labelled_24h": labelled_24h,
            "outcome_completeness_pct": outcome_completeness,
            "quality": quality,
        },
        "training": {
            "mature_feature_samples": mature_feature_samples,
            "required_samples": 60,
            "progress_pct": round(min(100.0, mature_feature_samples / 60 * 100), 1),
        },
        "models": model_payload,
        "walkforward": walkforward,
        "onchain": onchain,
        "weights": weight_state,
        "gates": gates,
        "updated_at": now,
    }
    _ENGINE_CACHE["spot"]["ts"] = time.time()
    _ENGINE_CACHE["spot"]["data"] = result
    return result


@router.get("/signals/adaptive-engine/futures", dependencies=[Depends(require_db)])
async def get_adaptive_engine_futures() -> dict:
    """FUTURES Adaptive Learning Engine state (PLAN_ADAPTIVE_LEARNING_FUTURES_10X F6).

    Panel paralel dari versi SPOT — sumber tabel futures_decision_events. Model
    registry belum ada (F3 menunggu 60 mature samples), jadi bagian `models`
    kosong dan gate promosi/canary belum aktif; itu memang status sebenarnya.
    """
    from app.models.futures_decision_event import FuturesDecisionEvent
    from app.models.futures_model_version import FuturesModelVersion

    _cf = _ENGINE_CACHE["futures"]
    if _cf["data"] is not None and (time.time() - _cf["ts"]) < _ENGINE_TTL:
        return _cf["data"]
    now = time.time()
    required = 60   # gate training model F3 (horizon 4h). Catatan: learning_loader
    # pakai 24h utk aktivasi soft-veto runtime — sengaja lebih konservatif.
    async with AsyncSessionLocal() as session:
        fmodels = list((await session.execute(
            select(FuturesModelVersion).order_by(FuturesModelVersion.trained_at.desc())
        )).scalars().all())
        total_decisions = int(await session.scalar(select(func.count(FuturesDecisionEvent.id))) or 0)
        unique_keys = int(await session.scalar(
            select(func.count(func.distinct(FuturesDecisionEvent.decision_key)))) or 0)
        action_counts = dict((await session.execute(
            select(FuturesDecisionEvent.action, func.count(FuturesDecisionEvent.id))
            .group_by(FuturesDecisionEvent.action)
        )).all())
        outcome_counts = dict((await session.execute(
            select(FuturesDecisionEvent.outcome_status, func.count(FuturesDecisionEvent.id))
            .group_by(FuturesDecisionEvent.outcome_status)
        )).all())
        reason_counts = dict((await session.execute(
            select(FuturesDecisionEvent.reason_code, func.count(FuturesDecisionEvent.id))
            .group_by(FuturesDecisionEvent.reason_code)
        )).all())
        opened_total = int(await session.scalar(select(func.count(FuturesDecisionEvent.id))
            .where(FuturesDecisionEvent.opened.is_(True))) or 0)
        # mature = punya outcome forward 4h (horizon label utama model F3 —
        # posisi futures hidup jam-an, bukan hari-an; jangan pakai 24h di sini)
        mature_samples = int(await session.scalar(select(func.count(FuturesDecisionEvent.id))
            .where(FuturesDecisionEvent.pnl_4h_pct.isnot(None))) or 0)
        realized_linked = int(await session.scalar(select(func.count(FuturesDecisionEvent.id))
            .where(FuturesDecisionEvent.realized_pnl_pct.isnot(None))) or 0)
        due_24h = int(await session.scalar(select(func.count(FuturesDecisionEvent.id))
            .where(FuturesDecisionEvent.scan_ts <= now - 24 * 3600)) or 0)
        labelled_24h = int(await session.scalar(select(func.count(FuturesDecisionEvent.id)).where(
            FuturesDecisionEvent.scan_ts <= now - 24 * 3600,
            FuturesDecisionEvent.pnl_24h_pct.isnot(None),
        )) or 0)
        # data-quality diagnostics (mirror SPOT)
        missing_snapshots = int(await session.scalar(select(func.count(FuturesDecisionEvent.id)).where(
            (FuturesDecisionEvent.feature_snapshot_json.is_(None)) |
            (FuturesDecisionEvent.feature_snapshot_json == "")
        )) or 0)
        future_events = int(await session.scalar(select(func.count(FuturesDecisionEvent.id))
            .where(FuturesDecisionEvent.scan_ts > now + 60)) or 0)
        invalid_closes = int(await session.scalar(select(func.count(FuturesDecisionEvent.id)).where(
            FuturesDecisionEvent.closed_at.isnot(None),
            FuturesDecisionEvent.closed_at < FuturesDecisionEvent.scan_ts,
        )) or 0)
        oldest_ts = await session.scalar(select(func.min(FuturesDecisionEvent.scan_ts)))
        latest_ts = await session.scalar(select(func.max(FuturesDecisionEvent.scan_ts)))

    # Status engine langsung dari runtime scanner (single source of truth)
    try:
        from agents.futures import store as futures_store
        runtime_status = futures_store.get_learning_status()
    except Exception:
        runtime_status = "warming"

    # F4: walk-forward + cost-stress 1.5× (diagnostik counterfactual)
    try:
        from agents.learning.futures_walkforward import run_futures_walkforward
        walkforward = await run_futures_walkforward()
    except Exception as exc:
        walkforward = {"status": "error", "error": str(exc)[:120], "promotion_eligible": False}

    # Fase 1 shadow-compare (READ-ONLY): apakah pakai adaptive_score membaik vs raw
    try:
        from agents.learning.futures_shadow_compare import run_futures_shadow_compare
        shadow_compare = await run_futures_shadow_compare()
    except Exception as exc:
        shadow_compare = {"status": "error", "error": str(exc)[:120]}

    # F3: model registry futures
    model_payload = []
    for m in fmodels[:10]:
        try:
            mm = json.loads(m.metrics_json or "{}")
        except (TypeError, json.JSONDecodeError):
            mm = {}
        model_payload.append({
            "version": m.version, "status": m.status,
            "trained_at": m.trained_at, "promoted_at": m.promoted_at,
            "training_n": mm.get("training_n", 0),
            "promotion_eligible": bool(mm.get("promotion_eligible")),
            "label_horizon": mm.get("label_horizon", "4h"),
            "test": mm.get("test") or {},
        })
    latest_model = model_payload[0] if model_payload else None

    quality = {
        "duplicate_keys": total_decisions - unique_keys,
        "missing_snapshots": missing_snapshots,
        "future_events": future_events,
        "invalid_closes": invalid_closes,
    }
    outcome_completeness = round(labelled_24h / due_24h * 100, 1) if due_24h else 100.0
    gates = {
        "training_data": mature_samples >= required,        # ≥60 mature (F3)
        "outcome_completeness": outcome_completeness >= 99.0,
        "data_quality": all(v == 0 for v in quality.values()),
        "model_trained": bool(model_payload),                        # F3
        "promotion_eligible": bool(latest_model and latest_model["promotion_eligible"]),
        "walkforward_passed": bool(walkforward.get("promotion_eligible")),  # F4 (+1.5× stress)
        "canary_active": any(m.status == "canary" for m in fmodels),        # F5
        "champion_exists": any(m.status == "champion" for m in fmodels),    # F5
    }
    engine_status = (
        "degraded" if not gates["data_quality"]
        else "collecting" if not gates["training_data"]
        else "champion" if gates["champion_exists"]
        else "canary" if gates["canary_active"]
        else "shadow" if gates["model_trained"]
        else "ready_to_train"
    )
    result = {
        "market": "futures",
        "engine_status": engine_status,          # collecting|ready_to_train|shadow|champion|degraded
        "learning_status": runtime_status,       # warming | active | degraded (runtime scan)
        "decision_ledger": {
            "total": total_decisions,
            "opened": opened_total,
            "actions": action_counts,
            "outcomes": outcome_counts,
            "reasons": reason_counts,
            "realized_linked": realized_linked,
            "due_24h": due_24h,
            "labelled_24h": labelled_24h,
            "outcome_completeness_pct": outcome_completeness,
            "quality": quality,
            "oldest_scan_ts": oldest_ts,
            "latest_scan_ts": latest_ts,
        },
        "training": {
            "mature_feature_samples": mature_samples,
            "required_samples": required,
            "progress_pct": round(min(100.0, mature_samples / required * 100), 1),
        },
        "models": model_payload,     # F3 model registry
        "walkforward": walkforward,  # F4 (termasuk test_stressed_1_5x)
        "shadow_compare": shadow_compare,  # Fase 1: raw vs adaptive (read-only)
        "phases": {
            "F0_policy": True, "F1_ledger": True, "F2_integration": True,
            "F3_model": True, "F4_walkforward": True, "F5_canary": True,
        },
        "gates": gates,
        "updated_at": now,
    }
    _ENGINE_CACHE["futures"]["ts"] = time.time()
    _ENGINE_CACHE["futures"]["data"] = result
    return result


# ── GET /signals/performance ──────────────────────────────────────────────────

@router.get("/signals/performance", dependencies=[Depends(require_db)])
async def get_signal_performance(
    agent:      str = Query("all",      description="all | opportunity_spot | futures_agent1 | futures_agent2 | futures_agent3 | cross_agent"),
    regime:     str = Query("all",      description="all | trending_up | trending_down | ranging | volatile"),
    min_trades: int = Query(3,          description="Minimum raw trade count"),
    sort_by:    str = Query("win_rate", description="win_rate | avg_pnl_pct | total_count | weight"),
    sort_dir:   str = Query("desc",     description="desc | asc"),
    limit:      int = Query(30,         ge=1, le=100),
) -> dict:
    """
    Return signal performance rows from agent_signal_weights.
    Groups by signal_key and returns per-agent breakdown.
    """
    async with AsyncSessionLocal() as session:
        q = select(AgentSignalWeight)

        if agent != "all":
            q = q.where(AgentSignalWeight.agent == agent)
        else:
            q = q.where(AgentSignalWeight.agent.in_(ALL_AGENTS))

        if regime != "all":
            q = q.where(AgentSignalWeight.regime == regime)
        else:
            q = q.where(AgentSignalWeight.regime == "all")

        result = await session.execute(q)
        rows   = list(result.scalars().all())

    # Filter by min_trades
    rows = [r for r in rows if (r.sample_count_raw or r.total_count) >= min_trades]

    # Group by signal_key — build per-agent breakdown
    signal_map: dict[str, dict] = {}
    for r in rows:
        entry = signal_map.setdefault(r.signal_key, {
            "signal_key": r.signal_key,
            "agents":     {},
            "best_win_rate":  0.0,
            "best_avg_pnl":   0.0,
            "total_trades":   0,
            "cross_weight":   None,
        })
        agent_label = AGENT_LABELS.get(r.agent, r.agent)
        entry["agents"][r.agent] = {
            "label":       agent_label,
            "win_rate":    round(r.win_rate * 100, 1),
            "total":       r.sample_count_raw or r.total_count,
            "wins":        r.win_count,
            "avg_pnl_pct": round(r.avg_pnl_pct or 0.0, 2),
            "weight":      round(r.weight, 3),
        }
        if r.agent == "cross_agent":
            entry["cross_weight"] = round(r.weight, 3)
        else:
            entry["total_trades"]  += r.sample_count_raw or r.total_count
            if r.win_rate > entry["best_win_rate"]:
                entry["best_win_rate"] = round(r.win_rate * 100, 1)
            if (r.avg_pnl_pct or 0.0) > entry["best_avg_pnl"]:
                entry["best_avg_pnl"] = round(r.avg_pnl_pct or 0.0, 2)

    signals = list(signal_map.values())

    # Sort
    reverse = sort_dir == "desc"
    sort_key_map = {
        "win_rate":    lambda x: x["best_win_rate"],
        "avg_pnl_pct": lambda x: x["best_avg_pnl"],
        "total_count": lambda x: x["total_trades"],
        "weight":      lambda x: x.get("cross_weight") or x["best_win_rate"],
    }
    signals.sort(key=sort_key_map.get(sort_by, lambda x: x["best_win_rate"]), reverse=reverse)
    signals = signals[:limit]

    return {
        "signals": signals,
        "meta": {
            "total":       len(signal_map),
            "shown":       len(signals),
            "agent_filter": agent,
            "regime_filter": regime,
            "min_trades":  min_trades,
        },
    }


# ── GET /signals/cross_agent ──────────────────────────────────────────────────

@router.get("/signals/cross_agent", dependencies=[Depends(require_db)])
async def get_cross_agent_signals(
    min_trades: int = Query(10, description="Minimum cross-agent trade count"),
    limit:      int = Query(20, ge=1, le=50),
) -> dict:
    """
    Return cross-agent aggregated signal performance.
    Shows signals proven across multiple agent types.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentSignalWeight).where(
                AgentSignalWeight.agent  == "cross_agent",
                AgentSignalWeight.regime == "all",
            )
        )
        cross_rows = list(result.scalars().all())

        # Also fetch per-agent data for these signal keys
        keys = [r.signal_key for r in cross_rows]
        per_agent_rows = []
        if keys:
            pa_result = await session.execute(
                select(AgentSignalWeight).where(
                    AgentSignalWeight.signal_key.in_(keys),
                    AgentSignalWeight.agent.in_(ALL_AGENTS[:-1]),  # exclude cross_agent
                    AgentSignalWeight.regime == "all",
                )
            )
            per_agent_rows = list(pa_result.scalars().all())

    # Build per-key agent map
    pa_map: dict[str, dict] = {}
    for r in per_agent_rows:
        pa_map.setdefault(r.signal_key, {})[r.agent] = {
            "label":    AGENT_LABELS.get(r.agent, r.agent),
            "win_rate": round(r.win_rate * 100, 1),
            "total":    r.sample_count_raw or r.total_count,
            "weight":   round(r.weight, 3),
        }

    signals = []
    for r in cross_rows:
        if (r.sample_count_raw or r.total_count) < min_trades:
            continue
        agents_data = pa_map.get(r.signal_key, {})
        agent_count = len(agents_data)
        signals.append({
            "signal_key":   r.signal_key,
            "cross_weight": round(r.weight, 3),
            "cross_win_rate": round(r.win_rate * 100, 1),
            "cross_total":  r.sample_count_raw or r.total_count,
            "avg_pnl_pct":  round(r.avg_pnl_pct or 0.0, 2),
            "agent_count":  agent_count,
            "agents":       agents_data,
            "reliability":  "high" if agent_count >= 3 else "medium" if agent_count == 2 else "low",
        })

    signals.sort(key=lambda x: (x["agent_count"], x["cross_win_rate"]), reverse=True)
    return {
        "signals": signals[:limit],
        "meta":    {"total": len(signals), "min_trades": min_trades},
    }


# ── GET /signals/catalog ─────────────────────────────────────────────────────

@router.get("/signals/catalog")
async def get_signal_catalog() -> dict:
    """Return signal → formula → agent mapping (P3.3). No DB required."""
    from app.services.signal_catalog import SIGNAL_CATALOG, get_all_categories
    return {
        "catalog": SIGNAL_CATALOG,
        "categories": get_all_categories(),
        "total": len(SIGNAL_CATALOG),
    }


# ── GET /signals/regime_heatmap ───────────────────────────────────────────────

@router.get("/signals/regime_heatmap", dependencies=[Depends(require_db)])
async def get_regime_heatmap(
    agent:  str = Query("all",  description="all | futures_agent1 | futures_agent2 | futures_agent3"),
    limit:  int = Query(20, ge=1, le=100),
) -> dict:
    """Weight per (signal, regime) for heatmap visualization (P3.5)."""
    REGIMES = ["all", "trending_up", "trending_down", "ranging", "volatile"]
    async with AsyncSessionLocal() as session:
        q = select(AgentSignalWeight)
        if agent != "all":
            q = q.where(AgentSignalWeight.agent == agent)
        else:
            q = q.where(AgentSignalWeight.agent.in_(ALL_AGENTS))
        result = await session.execute(q)
        rows   = list(result.scalars().all())

    # Group by signal_key: collect weight per regime
    sig_map: dict[str, dict] = {}
    for r in rows:
        entry = sig_map.setdefault(r.signal_key, {
            "signal_key":   r.signal_key,
            "regimes":      {reg: None for reg in REGIMES},
            "max_deviation": 0.0,
        })
        if r.regime in REGIMES:
            entry["regimes"][r.regime] = round(r.weight, 3)
        # Track max deviation from neutral (1.0) across regimes for sort
        dev = abs(r.weight - 1.0)
        if dev > entry["max_deviation"]:
            entry["max_deviation"] = round(dev, 3)

    signals = sorted(sig_map.values(), key=lambda x: x["max_deviation"], reverse=True)[:limit]
    return {"signals": signals, "regimes": REGIMES, "total": len(sig_map)}


# ── GET /signals/{signal_key}/history ────────────────────────────────────────

@router.get("/signals/{signal_key}/history", dependencies=[Depends(require_db)])
async def get_signal_history(
    signal_key: str,
    agent:      str = Query("all",  description="all | futures_agent1 | opportunity_spot | …"),
    days:       int = Query(30,     ge=1, le=90),
) -> dict:
    """Weight trajectory timeseries for a signal (P3.1)."""
    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as session:
        q = select(SignalWeightHistory).where(
            SignalWeightHistory.signal_key == signal_key,
            SignalWeightHistory.snapshot_at >= cutoff,
        )
        if agent != "all":
            q = q.where(SignalWeightHistory.agent == agent)
        q = q.order_by(SignalWeightHistory.snapshot_at)
        result = await session.execute(q)
        rows   = list(result.scalars().all())

    # Group by agent
    by_agent: dict[str, list[dict]] = {}
    for r in rows:
        by_agent.setdefault(r.agent, []).append({
            "ts":          round(r.snapshot_at),
            "weight":      round(r.weight, 3),
            "win_rate":    round(r.win_rate * 100, 1),
            "total_count": r.total_count,
        })

    return {
        "signal_key": signal_key,
        "days":       days,
        "agents":     by_agent,
        "total_snapshots": len(rows),
    }


# ── GET /signals/{signal_key}/explain ────────────────────────────────────────

@router.get("/signals/{signal_key}/explain", dependencies=[Depends(require_db)])
async def explain_signal(signal_key: str) -> dict:
    """Explain current weight, score impact, regime breakdown, catalog info (P3.2)."""
    from app.services.signal_catalog import get_catalog_entry
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentSignalWeight).where(AgentSignalWeight.signal_key == signal_key)
        )
        rows = list(result.scalars().all())

    # Partition by regime
    all_row   = next((r for r in rows if r.regime == "all"), None)
    regimes   = {r.regime: round(r.weight, 3) for r in rows}
    agents_using = list({r.agent for r in rows if r.agent != "cross_agent"})
    cross_row = next((r for r in rows if r.agent == "cross_agent" and r.regime == "all"), None)

    current_weight = all_row.weight if all_row else 1.0
    delta_30d: float | None = None

    # Fetch 30d-ago snapshot for delta
    cutoff = time.time() - 30 * 86400
    async with AsyncSessionLocal() as session:
        hist_result = await session.execute(
            select(SignalWeightHistory).where(
                SignalWeightHistory.signal_key == signal_key,
                SignalWeightHistory.regime     == "all",
                SignalWeightHistory.snapshot_at >= cutoff,
            ).order_by(SignalWeightHistory.snapshot_at).limit(1)
        )
        oldest = hist_result.scalar_one_or_none()
    if oldest:
        delta_30d = round(current_weight - oldest.weight, 3)

    catalog = get_catalog_entry(signal_key)
    return {
        "signal_key":    signal_key,
        "current_weight": round(current_weight, 3),
        "delta_30d":     delta_30d,
        "win_rate":      round((all_row.win_rate or 0) * 100, 1) if all_row else None,
        "total_trades":  all_row.total_count if all_row else 0,
        "score_impact_pts": round((current_weight - 1.0) * 7.0, 2),
        "regime_breakdown": regimes,
        "agents_using":  agents_using,
        "cross_weight":  round(cross_row.weight, 3) if cross_row else None,
        "catalog":       catalog,
    }


# ── GET /signals/updater/state ────────────────────────────────────────────────

@router.get("/signals/updater/state")
async def get_updater_state() -> dict:
    """State of all weight updaters (last run, errors, cache sizes)."""
    try:
        from agents.futures.weight_updater import get_state as fut_state
    except Exception:
        fut_state = lambda: {}  # noqa: E731

    try:
        from agents.opportunity.weight_updater import get_state as spot_state
    except Exception:
        spot_state = lambda: {}  # noqa: E731

    try:
        from agents.shared.cross_agent_learning import get_state as cross_state
    except Exception:
        cross_state = lambda: {}  # noqa: E731

    return {
        "futures": fut_state(),
        "spot":    spot_state(),
        "cross":   cross_state(),
    }


# ── POST /signals/updater/run ─────────────────────────────────────────────────

@router.post("/signals/updater/run", dependencies=[Depends(require_db)])
async def force_run_updaters() -> dict:
    """Force-run all weight updaters immediately (bypass rate limit)."""
    results = {}

    try:
        from agents.futures.weight_updater import update_weights
        results["futures"] = await update_weights()
    except Exception as e:
        results["futures"] = f"error: {e}"

    try:
        from agents.opportunity.weight_updater import update_spot_weights
        results["spot"] = await update_spot_weights()
    except Exception as e:
        results["spot"] = f"error: {e}"

    try:
        from agents.shared.cross_agent_learning import update_cross_agent_weights
        results["cross"] = await update_cross_agent_weights()
    except Exception as e:
        results["cross"] = f"error: {e}"

    return {"updated": results}


# ── GET /signals/agent_health ────────────────────────────────────────────────

@router.get("/signals/agent_health")
async def get_agent_health() -> dict:
    """
    Aggregate health dashboard for all futures agents.
    Combines: scan timing, risk gate state, per-lane WR/pause, weight updater stats.
    Powers the Signal Performance Overview Agent Intelligence panel.
    """
    from agents.futures import scheduler as futures_scheduler
    from agents.futures import risk_gate
    from agents.futures import weight_updater as wu

    scan_state = futures_scheduler.get_state()
    gate_state = risk_gate.get_gate_state()
    wu_state   = wu.get_state()

    lane_map = {
        "pre_gainer":   ("futures_agent1", "Pre-Gainer"),
        "accumulation": ("futures_agent2", "Accumulation"),
        "momentum":     ("futures_agent3", "Momentum"),
        "bigmover":     ("futures_agent_bigmover", "BigMover"),
    }
    lanes = []
    for lane, (agent, label) in lane_map.items():
        paused_info = gate_state.get("lane_pauses", {}).get(lane, {})
        wr_info     = gate_state.get("lane_wr", {}).get(lane, {})
        lanes.append({
            "lane":        lane,
            "agent":       agent,
            "label":       label,
            "paused":      paused_info.get("paused", False),
            "pause_until": paused_info.get("pause_until"),
            "wr":          wr_info.get("wr", 0.0),
            "trades":      wr_info.get("total", 0),
        })

    blacklisted = wu_state.get("blacklisted_coins", [])
    bl_dir      = wu_state.get("blacklisted_directional", [])

    return {
        "scan": {
            "running":          scan_state.get("running"),
            "cycle_count":      scan_state.get("cycle_count"),
            "last_scan_ts":     scan_state.get("last_scan_ts"),
            "next_scan_in_min": scan_state.get("next_scan_in_min"),
            "last_error":       scan_state.get("last_error"),
            "interval_minutes": scan_state.get("interval_minutes"),
        },
        "gate": {
            "active":       gate_state.get("active"),
            "gate_type":    gate_state.get("gate_type"),
            "reason":       gate_state.get("reason"),
            "drawdown_pct": gate_state.get("drawdown_pct"),
            "dd_threshold": gate_state.get("dd_threshold"),
            "rar":          gate_state.get("rar"),
            "n_trades":     gate_state.get("n_trades"),
            "stale":        gate_state.get("stale"),
        },
        "lanes": lanes,
        "learning": {
            "cached_keys":       wu_state.get("cached_keys", 0),
            "cached_agents":     wu_state.get("cached_agents", []),
            "blacklisted_count": len(blacklisted),
            "blacklisted_coins": blacklisted[:10],
            "bl_directional":    bl_dir[:10],
            "last_run":          wu_state.get("last_run"),
            "last_error":        wu_state.get("last_error"),
        },
    }


# ── GET /signals/rejections ───────────────────────────────────────────────────

@router.get("/signals/rejections", dependencies=[Depends(require_db)])
async def get_rejections(
    symbol: str = Query("", description="filter by symbol"),
    agent:  str = Query("all", description="all | futures_agent1 | futures_agent2 | futures_agent3"),
    hours:  int = Query(24, ge=1, le=168, description="lookback window in hours"),
    limit:  int = Query(50, ge=1, le=200),
) -> dict:
    """P7.2: Return recent signal rejections for the Rejections tab."""
    from app.models.rejection_log import RejectionLog
    import json as _json
    cutoff = time.time() - hours * 3600
    async with AsyncSessionLocal() as session:
        q = select(RejectionLog).where(RejectionLog.rejected_at >= cutoff)
        if symbol:
            q = q.where(RejectionLog.symbol == symbol.upper())
        if agent != "all":
            q = q.where(RejectionLog.agent == agent)
        q = q.order_by(RejectionLog.rejected_at.desc()).limit(limit)
        result = await session.execute(q)
        rows = list(result.scalars().all())

    rejections = []
    for r in rows:
        try:
            weak = _json.loads(r.weak_signals or "[]")
        except Exception:
            weak = []
        rejections.append({
            "id":            r.id,
            "symbol":        r.symbol,
            "agent":         r.agent,
            "direction":     r.direction,
            "score":         r.score,
            "threshold":     r.threshold,
            "gap":           round(r.threshold - r.score, 1),
            "regime":        r.regime,
            "reject_reason": r.reject_reason,
            "weak_signals":  weak,
            "rejected_at":   r.rejected_at,
        })

    return {
        "rejections": rejections,
        "total": len(rejections),
        "hours": hours,
        "filters": {"symbol": symbol, "agent": agent},
    }


# ── GET /signals/recommendations ──────────────────────────────────────────────

_RECO_CATEGORIES = [
    # (agent_key, label, lane_key or None, market)
    ("opportunity_spot",       "SPOT",         None,           "spot"),
    ("futures_agent1",         "Pre-Gainer",   "pre_gainer",   "futures"),
    ("futures_agent2",         "Accumulation", "accumulation", "futures"),
    ("futures_agent3",         "Momentum",     "momentum",     "futures"),
    ("futures_agent_bigmover", "BigMover",     "bigmover",     "futures"),
]


@router.get("/signals/recommendations", dependencies=[Depends(require_db)])
async def get_recommendations() -> dict:
    """
    Saran perbaikan per kategori (SPOT + 4 lane futures), dihasilkan rule-based
    dari data engine: trade 7 hari, near-miss rejection 48 jam, akurasi
    predictive 7 hari, bobot sinyal yang dipelajari, dan status pause lane.
    Read-only — tidak mengubah apa pun; tujuannya agar scanner terus bertumbuh.
    """
    from sqlalchemy import case

    from agents.futures import risk_gate
    from app.models.paper_trade import PaperTrade
    from app.models.predictive_log import PredictiveLog
    from app.models.rejection_log import RejectionLog

    now = time.time()
    cutoff_7d = now - 7 * 86400
    cutoff_48h = now - 48 * 3600
    agent_keys = [c[0] for c in _RECO_CATEGORIES]

    async with AsyncSessionLocal() as session:
        # Trade tertutup 7 hari per style
        tr = await session.execute(
            select(
                PaperTrade.style,
                func.count().label("n"),
                func.sum(case((PaperTrade.status == "tp", 1), else_=0)).label("wins"),
                func.avg(PaperTrade.pnl_pct).label("avg_pnl"),
            )
            .where(PaperTrade.style.in_(agent_keys))
            .where(PaperTrade.status.in_(["tp", "sl"]))
            .where(PaperTrade.closed_at >= cutoff_7d)
            .group_by(PaperTrade.style)
        )
        trades = {
            r.style: {"n": r.n, "wins": r.wins or 0, "avg_pnl": float(r.avg_pnl or 0)}
            for r in tr
        }

        # Near-miss 48 jam per agent (gap <= 8 poin dari ambang)
        nm = await session.execute(
            select(
                RejectionLog.agent,
                func.count().label("n"),
                func.avg(RejectionLog.threshold - RejectionLog.score).label("avg_gap"),
            )
            .where(RejectionLog.rejected_at >= cutoff_48h)
            .where((RejectionLog.threshold - RejectionLog.score) <= 8)
            .group_by(RejectionLog.agent)
        )
        nearmiss = {r.agent: {"n": r.n, "avg_gap": float(r.avg_gap or 0)} for r in nm}

        # Akurasi predictive 7 hari per (agent, direction)
        pr = await session.execute(
            select(
                PredictiveLog.agent,
                PredictiveLog.direction,
                func.count().label("n"),
                func.sum(case((PredictiveLog.hit_4h.is_(True), 1), else_=0)).label("hits4"),
            )
            .where(PredictiveLog.resolved_at.isnot(None))
            .where(PredictiveLog.scanned_at >= cutoff_7d)
            .group_by(PredictiveLog.agent, PredictiveLog.direction)
        )
        predictive: dict[str, list] = {}
        for r in pr:
            predictive.setdefault(r.agent, []).append({
                "direction": r.direction,
                "n": r.n,
                "hit4": round(100 * (r.hits4 or 0) / r.n, 1) if r.n else 0.0,
            })

        # Bobot sinyal yang dipelajari (regime all, sampel cukup)
        wrows = await session.execute(
            select(AgentSignalWeight)
            .where(AgentSignalWeight.agent.in_(agent_keys))
            .where(AgentSignalWeight.regime == "all")
            .where(AgentSignalWeight.total_count >= 10)
        )
        weights: dict[str, list] = {}
        for w in wrows.scalars().all():
            weights.setdefault(w.agent, []).append(w)

    gate_state = risk_gate.get_gate_state()
    lane_pauses = gate_state.get("lane_pauses", {})
    lane_wr = gate_state.get("lane_wr", {})

    def _wr_pct(v: float) -> float:
        """win_rate tersimpan kadang 0-1, kadang 0-100 — normalisasi ke persen."""
        return v * 100 if v <= 1 else v

    categories = []
    for agent_key, label, lane_key, market in _RECO_CATEGORIES:
        sugg: list[dict] = []
        t = trades.get(agent_key)
        n_ = nearmiss.get(agent_key)
        pd = predictive.get(agent_key, [])
        ws = weights.get(agent_key, [])

        # 1) Lane dijeda (futures)
        paused = bool(lane_key and lane_pauses.get(lane_key, {}).get("paused"))
        if paused:
            until = lane_pauses.get(lane_key, {}).get("pause_until")
            until_s = time.strftime("%H:%M", time.localtime(until)) if until else "?"
            wrinfo = lane_wr.get(lane_key, {})
            sugg.append({
                "severity": "action", "source": "lane",
                "title": "Lane sedang dijeda otomatis",
                "detail": (
                    f"Win rate rolling {wrinfo.get('wr', 0) * 100:.0f}% dari "
                    f"{wrinfo.get('total', 0)} trade di bawah ambang - sistem menahan "
                    f"trade baru sampai {until_s}. Jangan tambah eksposur; tunggu "
                    "evaluasi otomatis."
                ),
            })

        # 2) Hasil trade 7 hari
        if t and t["n"] >= 10:
            wr = 100 * t["wins"] / t["n"]
            if wr < 40:
                sugg.append({
                    "severity": "action", "source": "trades",
                    "title": f"Win rate 7 hari rendah: {wr:.0f}% ({t['wins']}/{t['n']})",
                    "detail": (
                        f"Rata-rata PnL {t['avg_pnl']:+.2f}%. Bobot sinyal yang rugi "
                        "sudah diturunkan otomatis - cek daftar bobot turun/veto di tab "
                        "Perbaikan; bila berlanjut, lane akan dijeda otomatis."
                    ),
                })
            elif wr >= 55:
                sugg.append({
                    "severity": "good", "source": "trades",
                    "title": f"Win rate 7 hari sehat: {wr:.0f}% ({t['wins']}/{t['n']})",
                    "detail": (
                        f"Rata-rata PnL {t['avg_pnl']:+.2f}%. Pertahankan - jangan ubah "
                        "ambang saat sedang menang."
                    ),
                })
        elif (t is None or t["n"] < 5) and not paused:
            nm_txt = ""
            if n_ and n_["n"] >= 10:
                nm_txt = (
                    f" Padahal ada {n_['n']} kandidat nyaris lolos dalam 48 jam "
                    f"(rata-rata kurang {n_['avg_gap']:.1f} poin) - kalibrasi bobot "
                    "sinyal inti agar setup bagus realistis mencapai ambang, JANGAN "
                    "menurunkan ambang."
                )
            sugg.append({
                "severity": "action" if nm_txt else "watch", "source": "nearmiss",
                "title": f"Lane sepi: {t['n'] if t else 0} trade tertutup dalam 7 hari",
                "detail": "Belum cukup data untuk menilai kualitas lane." + nm_txt,
            })

        # 3) Near-miss menumpuk meski lane aktif
        if n_ and n_["n"] >= 30 and t and t["n"] >= 5:
            sugg.append({
                "severity": "watch", "source": "nearmiss",
                "title": f"{n_['n']} kandidat nyaris lolos (48 jam)",
                "detail": (
                    f"Rata-rata hanya kurang {n_['avg_gap']:.1f} poin dari ambang. "
                    "Banyak peluang tertahan di depan pintu - pantau tab Rejections; "
                    "bila kandidat yang tertolak ternyata bergerak bagus (cek "
                    "Predictive), bobot sinyal intinya layak dinaikkan."
                ),
            })

        # 4) Akurasi predictive per arah
        for p in sorted(pd, key=lambda x: x["hit4"]):
            if p["n"] < 30:
                continue
            if p["hit4"] < 40:
                sugg.append({
                    "severity": "action", "source": "predictive",
                    "title": (
                        f"Akurasi arah {p['direction']} lemah: "
                        f"{p['hit4']:.0f}% dari {p['n']} prediksi"
                    ),
                    "detail": (
                        f"Kurang dari 40% prediksi {p['direction']} benar dalam 4 jam. "
                        "Sinyal masuk arah ini perlu direview - pertimbangkan perketat "
                        "syarat atau bias ke arah sebaliknya."
                    ),
                })
            elif p["hit4"] >= 55:
                sugg.append({
                    "severity": "good", "source": "predictive",
                    "title": (
                        f"Akurasi arah {p['direction']} bagus: "
                        f"{p['hit4']:.0f}% dari {p['n']} prediksi"
                    ),
                    "detail": (
                        "Di atas 55% - arah ini sumber pertumbuhan; biarkan bobot "
                        "sinyal pendukungnya naik."
                    ),
                })

        # 5) Bobot sinyal ekstrem
        bad = sorted([w for w in ws if w.weight < 0.9], key=lambda w: w.weight)
        good = sorted([w for w in ws if w.weight >= 1.2], key=lambda w: -w.weight)
        if bad:
            worst = bad[0]
            _item = {
                "severity": "watch", "source": "weights",
                "title": f"{len(bad)} sinyal berkinerja buruk sudah diturunkan otomatis",
                "detail": (
                    f"Terlemah: '{worst.signal_key}' x{worst.weight:.2f} "
                    f"(WR {_wr_pct(worst.win_rate):.0f}%, {worst.total_count} trades). "
                    "Engine terus menekan pengaruhnya; di bawah x0.80 akan diveto."
                ),
            }
            # PLAN_SIGNAL_REPAIR_LIVE R4: saran yang AMAN di-otomasi membawa payload
            # apply (futures only; bounded −0.10, floor 0.70, cooldown 24h di endpoint).
            if agent_key.startswith("futures") and worst.weight > 0.70 + 1e-9:
                _item["apply"] = {
                    "type": "weight", "agent": agent_key,
                    "signal_key": worst.signal_key, "delta": -0.10,
                    "label": f"Turunkan bobot '{worst.signal_key}' −0.10",
                }
            sugg.append(_item)
        if good:
            best = good[0]
            sugg.append({
                "severity": "good", "source": "weights",
                "title": f"{len(good)} sinyal andalan (bobot >= x1.20)",
                "detail": (
                    f"Terkuat: '{best.signal_key}' x{best.weight:.2f} "
                    f"(WR {_wr_pct(best.win_rate):.0f}%, {best.total_count} trades). "
                    "Sinyal seperti ini yang membuat skor kandidat naik."
                ),
            })

        if not sugg:
            sugg.append({
                "severity": "good", "source": "none",
                "title": "Tidak ada perbaikan mendesak",
                "detail": (
                    "Lane berjalan normal - data terus dikumpulkan dan bobot "
                    "diperbarui otomatis tiap trade selesai."
                ),
            })

        order = {"action": 0, "watch": 1, "good": 2}
        sugg.sort(key=lambda s: order.get(s["severity"], 3))

        wr7 = round(100 * t["wins"] / t["n"], 1) if t and t["n"] else None
        categories.append({
            "agent": agent_key,
            "label": label,
            "market": market,
            "paused": paused,
            "stats": {
                "closed_7d": t["n"] if t else 0,
                "wr_7d": wr7,
                "avg_pnl_7d": round(t["avg_pnl"], 2) if t else None,
                "near_miss_48h": n_["n"] if n_ else 0,
                "predictive_n": sum(p["n"] for p in pd),
            },
            "suggestions": sugg,
        })

    return {"categories": categories, "generated_at": now}


# ── PLAN_SIGNAL_REPAIR_LIVE R4 — repair log + apply saran ─────────────────────

@router.get("/signals/repairs", dependencies=[Depends(require_db)])
async def get_repairs(limit: int = Query(100, ge=1, le=300)) -> dict:
    """Progress perbaikan sinyal futures: funnel deteksi→aksi→verifikasi, log aksi
    (before→after), dan status agen perbaikan + verifier."""
    from app.models.futures_repair_action import FuturesRepairAction

    now = time.time()
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(FuturesRepairAction).order_by(
                FuturesRepairAction.detected_at.desc()).limit(limit)
        )).scalars().all())
        status_counts = dict((await session.execute(
            select(FuturesRepairAction.status, func.count(FuturesRepairAction.id))
            .group_by(FuturesRepairAction.status)
        )).all())
        actions_24h = int(await session.scalar(
            select(func.count(FuturesRepairAction.id)).where(
                FuturesRepairAction.applied.is_(True),
                FuturesRepairAction.applied_at >= now - 86400,
            )) or 0)
        total = int(await session.scalar(select(func.count(FuturesRepairAction.id))) or 0)

    try:
        from agents.learning.predictive_repair import get_repair_agent_status
        agent_status = get_repair_agent_status()
    except Exception:
        agent_status = {}
    try:
        from agents.learning.repair_verifier import get_verifier_status
        verifier_status = get_verifier_status()
    except Exception:
        verifier_status = {}

    def _row(r) -> dict:
        try:
            evidence = json.loads(r.evidence_json or "{}")
        except (TypeError, json.JSONDecodeError):
            evidence = {}
        return {
            "id": r.id, "detected_at": r.detected_at, "source": r.source,
            "target_key": r.target_key, "agent": r.agent, "issue": r.issue,
            "action": r.action, "delta": r.delta, "applied": r.applied,
            "applied_at": r.applied_at, "evidence": evidence,
            "before_metric": r.before_metric, "after_metric": r.after_metric,
            "status": r.status, "verified_at": r.verified_at,
            "revert_of": r.revert_of, "note": r.note,
        }

    verified_total = (status_counts.get("verified_improved", 0)
                      + status_counts.get("verified_no_change", 0)
                      + status_counts.get("reverted", 0))
    return {
        "funnel": {
            "total": total,
            "applied": status_counts.get("applied", 0),
            "verified": verified_total,
            "improved": status_counts.get("verified_improved", 0),
            "no_change": status_counts.get("verified_no_change", 0),
            "reverted": status_counts.get("reverted", 0),
            "suggested": status_counts.get("suggested", 0),
            "actions_24h": actions_24h,
        },
        "agent": agent_status,
        "verifier": verifier_status,
        "actions": [_row(r) for r in rows],
        "updated_at": now,
    }


class ApplySuggestionBody(BaseModel):
    type: str = Field(..., description="'weight' — aksi bobot bounded (satu-satunya yang auto-applicable)")
    agent: str = Field(..., max_length=40)
    signal_key: str = Field(..., max_length=100)
    delta: float = Field(..., description="±0.10 saja")
    label: str = Field(default="", max_length=160)


_FUTURES_AGENT_SET = {
    "futures_agent1", "futures_agent2", "futures_agent3", "futures_agent_bigmover",
}


@router.post("/signals/recommendations/apply", dependencies=[Depends(require_db)])
async def apply_recommendation(body: ApplySuggestionBody) -> dict:
    """Terapkan saran yang AMAN di-otomasi (R4): hanya aksi bobot bounded pada
    agent FUTURES. Bounds & cooldown ditegakkan di sini; aksi tercatat di repair
    ledger source='suggestion'. Saran level kode TIDAK pernah bisa lewat sini."""
    if body.type != "weight":
        raise HTTPException(status_code=400, detail="Hanya type 'weight' yang auto-applicable")
    if body.agent not in _FUTURES_AGENT_SET:
        raise HTTPException(status_code=400, detail="Hanya agent futures (SPOT read-only)")
    if abs(abs(body.delta) - 0.10) > 1e-9:
        raise HTTPException(status_code=400, detail="Delta wajib ±0.10 (step-cap terkunci)")

    from agents.futures.repair_log import has_recent_action, record_action
    from agents.learning.predictive_repair import _apply_weight_step

    target = f"{body.agent}:{body.signal_key}"
    if await has_recent_action(target):
        raise HTTPException(status_code=429,
                            detail="Cooldown: sudah ada aksi bobot untuk sinyal ini dalam 24 jam")
    applied = await _apply_weight_step(body.agent, body.signal_key, body.delta, time.time())
    if applied is None:
        raise HTTPException(status_code=409, detail="Bobot sudah di floor/cap — tidak ada perubahan")
    old_w, new_w = applied
    rid = await record_action(
        source="suggestion", target_key=target, agent=body.agent,
        issue="suggestion_applied",
        action="weight_down" if body.delta < 0 else "weight_up",
        evidence={"before_weight": old_w, "after_weight": new_w,
                  "label": body.label[:160]},
        delta=body.delta,
        note=(body.label[:200] or None),
    )
    return {"ok": True, "id": rid, "target": target,
            "weight": {"before": old_w, "after": new_w}}
