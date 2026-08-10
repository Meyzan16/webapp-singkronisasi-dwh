"""
Futures Learning API.

GET  /futures/learning/stats    — win rates, regime, balance sim, win rate trend
GET  /futures/learning/weights  — signal weights per agent
POST /futures/learning/update   — force weight recalculation
"""

import json
import time

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.database import require_db

router = APIRouter(tags=["futures-learning"])
logger = structlog.get_logger(__name__)

# F33/Phase 9: balance now comes from the real wallet; keep shared constants for the
# conservative-equity baseline and the legacy-row P&L fallback.
from app.services.agent_registry import FUTURES_AGENTS as _REG_FUTURES_AGENTS
from app.services.trading_costs import (
    FUTURES_RISK_PCT as RISK_PCT,
    futures_pnl_dollar as _pnl_dollar,
)


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/futures/learning/stats")
async def get_learning_stats() -> dict:
    """
    Returns:
      - Overall win rate (both agents)
      - Win rate per agent
      - Simulated balance ($1000 start, 1% risk)
      - Current market regime
      - Win rate over last 10 trades (trend)
      - Top 5 best/worst performing signals
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from app.models.signal_weight import AgentSignalWeight
    from agents.futures.regime import get_cached_regime
    from agents.futures.monitor import get_state as monitor_state
    from agents.futures.weight_updater import get_state as updater_state

    if not is_db_available():
        return {"error": "db_unavailable"}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                # Registry tunggal — lane baru otomatis ikut terhitung.
                PaperTrade.style.in_(_REG_FUTURES_AGENTS),
            ).order_by(PaperTrade.entry_at)
        )
        all_trades = list(result.scalars().all())

        weights_result = await session.execute(
            select(AgentSignalWeight).where(
                AgentSignalWeight.total_count >= 2,
                AgentSignalWeight.regime == "all",
            ).order_by(AgentSignalWeight.win_rate.desc())
        )
        weights = list(weights_result.scalars().all())

    closed  = [t for t in all_trades if t.status in ("tp", "sl")]   # win-rate: expired excluded
    open_t  = [t for t in all_trades if t.status == "open"]
    # BUG-L19: balance/equity must include expired (real money moved), sorted by close time —
    # keeps the chart aligned with the wallet (which also counts expired). Win-rate stays tp/sl.
    balance_closed = sorted(
        [t for t in all_trades if t.status in ("tp", "sl", "expired")],
        key=lambda t: t.closed_at or 0,
    )

    def _is_real_win(t) -> bool:
        """BUG FIX: status=='tp' with negative net pnl is NOT a win."""
        return t.status == "tp" and (t.pnl_pct or 0.0) > 0

    # Phase 9: seed from the REAL futures wallet (initial + deposits − withdrawals),
    # so the chart and the wallet agree and deposits are reflected.
    from app.api.v1.balance import get_or_create_balance
    _wallet      = await get_or_create_balance("futures")
    wallet_base  = _wallet.initial_balance + _wallet.deposited_total - _wallet.withdrawn_total

    def _trade_pnl_dollar(t) -> float:
        """Stored real $ P&L; prefer the trade's real notional; $1000 constant only for
        truly ancient rows that have neither pnl_dollar nor position_size (BUG-L22)."""
        if t.pnl_dollar is not None:
            return t.pnl_dollar
        if t.position_size:
            return (t.pnl_pct or 0.0) / 100 * t.position_size
        try:
            risk_pct = json.loads(t.signals_json or "{}").get("risk_pct", 2.0)
        except Exception:
            risk_pct = 2.0
        return _pnl_dollar(t.pnl_pct or 0.0, risk_pct)

    # Balance simulation
    balance = wallet_base
    equity_points = []
    for t in balance_closed:        # BUG-L19: include expired so chart matches the wallet
        balance += _trade_pnl_dollar(t)
        equity_points.append({
            "trade_n": len(equity_points) + 1,
            "balance": round(balance, 2),
            "symbol":  t.symbol,
            "win":     t.status == "tp",
            "agent":   t.style,
            "ts":      t.closed_at,
        })

    wins   = [t for t in closed if _is_real_win(t)]
    losses = [t for t in closed if not _is_real_win(t)]
    wr     = len(wins) / len(closed) * 100 if closed else 0.0

    # Per-agent
    def agent_stats(agent_name: str) -> dict:
        ag_closed = [t for t in closed if t.style == agent_name]
        ag_wins   = [t for t in ag_closed if _is_real_win(t)]
        ag_rate   = len(ag_wins) / len(ag_closed) * 100 if ag_closed else 0.0
        return {
            "total":    len(ag_closed),
            "wins":     len(ag_wins),
            "losses":   len(ag_closed) - len(ag_wins),
            "win_rate": round(ag_rate, 1),
        }

    # Win rate trend: last 10 closed trades (rolling)
    trend = []
    window = 10
    for i in range(len(closed)):
        start = max(0, i - window + 1)
        chunk = closed[start: i + 1]
        chunk_wins = sum(1 for t in chunk if _is_real_win(t))
        trend.append({
            "trade_n":  i + 1,
            "win_rate": round(chunk_wins / len(chunk) * 100, 1),
            "win":      _is_real_win(closed[i]),
        })

    # Signal performance
    top_signals    = [{"key": w.signal_key, "agent": w.agent, "win_rate": round(w.win_rate * 100, 1),
                       "weight": w.weight, "total": w.total_count, "wins": w.win_count}
                      for w in weights[:5]]
    bottom_signals = [{"key": w.signal_key, "agent": w.agent, "win_rate": round(w.win_rate * 100, 1),
                       "weight": w.weight, "total": w.total_count, "wins": w.win_count}
                      for w in sorted(weights, key=lambda x: x.win_rate)[:5]
                      if w.total_count >= 3]

    # Regime breakdown: win rate + count per regime
    regime_map: dict[str, dict] = {}
    for t in closed:
        r = t.regime or "unknown"
        entry = regime_map.setdefault(r, {"wins": 0, "total": 0, "pnl_sum": 0.0})
        entry["total"] += 1
        if _is_real_win(t):
            entry["wins"] += 1
        entry["pnl_sum"] += _trade_pnl_dollar(t)   # Phase 9: real stored $ P&L

    regime_breakdown = [
        {
            "regime":    r,
            "total":     v["total"],
            "wins":      v["wins"],
            "win_rate":  round(v["wins"] / v["total"] * 100, 1) if v["total"] > 0 else 0.0,
            "pnl_dollar": round(v["pnl_sum"], 2),
        }
        for r, v in regime_map.items()
    ]

    # Per-direction stats
    long_closed  = [t for t in closed if t.direction == "LONG"]
    short_closed = [t for t in closed if t.direction == "SHORT"]
    long_wins    = [t for t in long_closed  if _is_real_win(t)]
    short_wins   = [t for t in short_closed if _is_real_win(t)]

    # Leverage distribution: how many trades per leverage bucket
    lev_dist: dict[str, int] = {}
    for t in all_trades:
        lev = t.leverage or 1
        bucket = f"{lev}x"
        lev_dist[bucket] = lev_dist.get(bucket, 0) + 1

    # Monthly win rate per agent (last 6 months)
    # EC6: include futures_agent_bigmover as its own bucket — was silently lumped into agent3
    import datetime as dt
    monthly: dict[str, dict] = {}
    for t in closed:
        if not t.entry_at:
            continue
        month_key = dt.datetime.utcfromtimestamp(t.entry_at).strftime("%Y-%m")
        entry = monthly.setdefault(month_key, {
            "month":    month_key,
            "agent1":   {"wins": 0, "total": 0},
            "agent2":   {"wins": 0, "total": 0},
            "agent3":   {"wins": 0, "total": 0},
            "bigmover": {"wins": 0, "total": 0},
        })
        if t.style == "futures_agent1":
            ak = "agent1"
        elif t.style == "futures_agent2":
            ak = "agent2"
        elif t.style == "futures_agent3":
            ak = "agent3"
        else:
            ak = "bigmover"   # futures_agent_bigmover
        entry[ak]["total"] += 1
        if _is_real_win(t):
            entry[ak]["wins"] += 1

    def _month_bucket(v: dict, key: str) -> dict:
        b = v[key]
        return {
            "total":    b["total"],
            "wins":     b["wins"],
            "win_rate": round(b["wins"] / b["total"] * 100, 1) if b["total"] > 0 else 0.0,
        }

    monthly_stats = []
    for month_key in sorted(monthly.keys())[-6:]:  # last 6 months
        v = monthly[month_key]
        monthly_stats.append({
            "month":    month_key,
            "agent1":   _month_bucket(v, "agent1"),
            "agent2":   _month_bucket(v, "agent2"),
            "agent3":   _month_bucket(v, "agent3"),
            "bigmover": _month_bucket(v, "bigmover"),
        })

    # Conservative (flat R:R 1:3) equity — F65: derive from constants, not hardcoded $30/$10.
    # Phase 9: scale off the real wallet base so it sits alongside the actual curve.
    _risk_dollar = wallet_base * RISK_PCT   # loss per trade
    _win_dollar  = _risk_dollar * 3.0       # R:R 1:3 → win pays 3× risk
    nc_balance = wallet_base
    nc_points = []
    for ep in equity_points:
        win = ep["win"]
        nc_balance += _win_dollar if win else -_risk_dollar
        nc_points.append({"trade_n": ep["trade_n"], "balance": round(nc_balance, 2)})

    return {
        "regime":          get_cached_regime(),
        "target_win_rate": 80.0,
        "overall": {
            "total":     len(all_trades),
            "open":      len(open_t),
            "closed":    len(closed),
            "wins":      len(wins),
            "losses":    len(losses),
            "win_rate":  round(wr, 1),
        },
        "agent1":        agent_stats("futures_agent1"),
        "agent2":        agent_stats("futures_agent2"),
        "agent3":        agent_stats("futures_agent3"),
        "agent_bigmover": agent_stats("futures_agent_bigmover"),  # EC6
        "balance": {
            "starting":  round(wallet_base, 2),                     # Phase 9: real base (incl. deposits)
            "current":   round(balance, 2),
            "total_pnl": round(balance - wallet_base, 2),
            "roi_pct":   round((balance - wallet_base) / wallet_base * 100, 2) if wallet_base > 0 else 0.0,
        },
        "equity_points":   equity_points,         # F66: full journey from $start (no slice)
        "win_rate_trend":  trend[-20:],           # last 20 for trend chart
        "top_signals":     top_signals,
        "bottom_signals":  bottom_signals,
        "regime_breakdown": regime_breakdown,
        "direction_stats": {
            "long":  {"total": len(long_closed),  "wins": len(long_wins),  "win_rate": round(len(long_wins)/len(long_closed)*100, 1) if long_closed else 0.0},
            "short": {"total": len(short_closed), "wins": len(short_wins), "win_rate": round(len(short_wins)/len(short_closed)*100, 1) if short_closed else 0.0},
        },
        "leverage_dist":   lev_dist,
        "conservative_equity": nc_points,   # F66: full journey (no slice)
        "monthly_stats":   monthly_stats,
        "monitor":         monitor_state(),
        "updater":         updater_state(),
        "generated_at":    time.time(),
    }


# ── Weights ───────────────────────────────────────────────────────────────────

@router.get("/futures/learning/weights")
async def get_signal_weights(
    agent:  str = "all",
    regime: str = "all",
) -> dict:
    """All adaptive signal weights."""
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.signal_weight import AgentSignalWeight

    if not is_db_available():
        return {"weights": [], "total": 0}

    conditions = [AgentSignalWeight.total_count >= 1]
    if agent != "all":
        conditions.append(AgentSignalWeight.agent == agent)
    if regime != "all":
        conditions.append(AgentSignalWeight.regime == regime)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentSignalWeight)
            .where(*conditions)
            .order_by(AgentSignalWeight.win_rate.desc())
            .limit(100)
        )
        rows = result.scalars().all()

    return {
        "weights": [
            {
                "agent":       r.agent,
                "signal_key":  r.signal_key,
                "weight":      r.weight,
                "win_rate":    round(r.win_rate * 100, 1),
                "win_count":   r.win_count,
                "total_count": r.total_count,
                "regime":      r.regime,
                "updated_at":  r.updated_at,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ── Force update ──────────────────────────────────────────────────────────────

@router.post("/futures/learning/update")
async def force_weight_update() -> dict:
    """Trigger immediate signal weight recalculation."""
    from agents.futures.weight_updater import update_weights
    from agents.futures.regime import fetch_regime

    regime  = await fetch_regime()
    updated = await update_weights()
    return {"updated_rows": updated, "regime": regime, "ts": time.time()}


# ── Exit Learning (MONITOR) ───────────────────────────────────────────────────
# Lapisan learning selama ini hanya menyetel keputusan MASUK. Endpoint di bawah
# membuka lapisan KELUAR: ledger exit, agregasi per alasan/lane/regime, dan usulan
# jarak TP realistis yang diturunkan dari sebaran gerak NYATA (MFE), bukan tebakan.

@router.post("/futures/exit-learning/backfill", dependencies=[Depends(require_db)])
async def exit_learning_backfill() -> dict:
    """Isi ledger keluar dari posisi futures yang sudah tertutup. Idempoten."""
    from agents.learning.exit_learning import backfill_exit_events
    return await backfill_exit_events()


@router.get("/futures/exit-learning/analysis", dependencies=[Depends(require_db)])
async def exit_learning_analysis(days: int = Query(90, ge=1, le=365)) -> dict:
    """Agregasi keputusan keluar: per alasan close, per lane, per regime."""
    from agents.learning.exit_learning import analyze_exits
    return await analyze_exits(days=days)


@router.get("/futures/exit-learning/recommendations", dependencies=[Depends(require_db)])
async def exit_learning_recommendations(days: int = Query(90, ge=1, le=365)) -> dict:
    """Usulan parameter keluar per lane (TP realistis + tanda exit prematur)."""
    from agents.learning.exit_learning import recommend_exit_params
    return await recommend_exit_params(days=days)


@router.get("/futures/exit-learning/triggers", dependencies=[Depends(require_db)])
async def exit_learning_triggers(days: int = Query(90, ge=1, le=365)) -> dict:
    """Adili tiap pemicu exit dini per lane: menyelamatkan, atau justru merugikan?

    Ukurannya perbandingan terhadap alternatifnya — kerugian yang direalisasi vs
    jarak SL yang akan kena bila posisi dibiarkan.
    """
    from agents.learning.exit_learning import analyze_exit_triggers
    return await analyze_exit_triggers(days=days)


@router.get("/futures/exit-learning/failfast", dependencies=[Depends(require_db)])
async def exit_learning_failfast(days: int = Query(90, ge=1, le=365)) -> dict:
    """Usulan gap fail-fast per lane, diturunkan dari ledger keluar."""
    from agents.learning.exit_learning import recommend_failfast_params
    return await recommend_failfast_params(days=days)


@router.get("/futures/exit-learning/sl-width", dependencies=[Depends(require_db)])
async def exit_learning_sl_width(days: int = Query(90, ge=1, le=365)) -> dict:
    """Bedah lebar SL per lane: dirancang terhadap volatilitas, atau terhadap harga?"""
    from agents.learning.exit_learning import analyze_sl_width
    return await analyze_sl_width(days=days)


@router.get("/futures/exit-learning/trail", dependencies=[Depends(require_db)])
async def exit_learning_trail(days: int = Query(90, ge=1, le=365)) -> dict:
    """Usulan dua parameter trailing, dari perbandingan hasil counterfactual."""
    from agents.learning.exit_learning import recommend_trail_params
    return await recommend_trail_params(days=days)


@router.get("/spot/exit-learning/trail", dependencies=[Depends(require_db)])
async def spot_exit_learning_trail(days: int = Query(90, ge=1, le=365)) -> dict:
    """Padanan SPOT — MENGUKUR saja; usulannya tak diterbitkan selama nilai
    trailing SPOT belum punya kunci config yang dibaca monitor."""
    from agents.learning.exit_learning import recommend_trail_params
    return await recommend_trail_params(days=days, market="spot")


@router.get("/futures/sl-config", dependencies=[Depends(require_db)])
async def get_sl_config() -> dict:
    """Lebar SL per lane yang SEDANG berlaku."""
    from agents.futures import sl_config
    await sl_config.refresh()
    return {"status": "ok", "config": sl_config.snapshot()}


# ── M5: penyalaan bertahap (shadow → canary → active) ────────────────────────

@router.get("/futures/exit-rollout", dependencies=[Depends(require_db)])
async def exit_rollout_status() -> dict:
    """Semua tahapan penyalaan parameter keluar beserta posisinya."""
    from agents.learning.exit_rollout import status
    return await status()


@router.post("/futures/exit-rollout/propose", dependencies=[Depends(require_db)])
async def exit_rollout_propose(days: int = Query(90, ge=1, le=365)) -> dict:
    """Alirkan usulan mesin belajar ke antrean tahapan. Semua masuk sebagai
    `shadow` — tak ada yang berlaku."""
    from agents.learning.exit_rollout import propose_from_recommendations
    return await propose_from_recommendations(days=days)


@router.post("/futures/exit-rollout/{rollout_id}/canary", dependencies=[Depends(require_db)])
async def exit_rollout_start_canary(rollout_id: int) -> dict:
    """Berlakukan usulan untuk SATU lane. Ditolak bila baseline belum cukup atau
    ada canary lain yang sedang berjalan."""
    from agents.learning.exit_rollout import start_canary
    return await start_canary(rollout_id)


@router.post("/futures/exit-rollout/{rollout_id}/evaluate", dependencies=[Depends(require_db)])
async def exit_rollout_evaluate(rollout_id: int) -> dict:
    """Bandingkan hasil sesudah aktivasi dengan baseline, lalu putuskan."""
    from agents.learning.exit_rollout import evaluate
    return await evaluate(rollout_id)


@router.post("/futures/exit-rollout/{rollout_id}/rollback", dependencies=[Depends(require_db)])
async def exit_rollout_rollback(rollout_id: int) -> dict:
    """Kembalikan parameter ke nilai sebelumnya."""
    from agents.learning.exit_rollout import rollback
    return await rollback(rollout_id)


@router.post("/futures/exit-learning/apply", dependencies=[Depends(require_db)])
async def exit_learning_apply(days: int = Query(90, ge=1, le=365),
                              dry_run: bool = Query(True)) -> dict:
    """Tulis usulan batas TP per lane FUTURES ke config. `dry_run=true` hanya melapor.

    Menulis pun tidak mengubah keputusan apa pun sampai
    `futures.monitor_exit_learning_enabled` dinyalakan — saklarnya TERPISAH dari
    SPOT, jadi menyalakan salah satu tidak menyalakan keduanya.
    """
    from agents.learning.exit_learning import apply_exit_recommendations
    return await apply_exit_recommendations(days=days, dry_run=dry_run)


# ── M7: sisi SPOT ─────────────────────────────────────────────────────────────
# Endpoint terpisah, IMPLEMENTASI SAMA. Yang berbeda hanya argumen `market`, jadi
# perbaikan pada analisa otomatis berlaku untuk kedua market — tak ada salinan
# kedua yang bisa menyimpang diam-diam.

@router.post("/spot/exit-learning/backfill", dependencies=[Depends(require_db)])
async def spot_exit_learning_backfill() -> dict:
    """Isi ledger keluar dari posisi SPOT yang sudah tertutup. Idempoten."""
    from agents.learning.exit_learning import backfill_exit_events
    return await backfill_exit_events(market="spot")


@router.get("/spot/exit-learning/analysis", dependencies=[Depends(require_db)])
async def spot_exit_learning_analysis(days: int = Query(90, ge=1, le=365)) -> dict:
    """Agregasi keputusan keluar SPOT: per alasan close, per lane, per regime."""
    from agents.learning.exit_learning import analyze_exits
    return await analyze_exits(days=days, market="spot")


@router.get("/spot/exit-learning/triggers", dependencies=[Depends(require_db)])
async def spot_exit_learning_triggers(days: int = Query(90, ge=1, le=365)) -> dict:
    """Adili tiap pemicu exit dini SPOT terhadap alternatifnya (jarak SL)."""
    from agents.learning.exit_learning import analyze_exit_triggers
    return await analyze_exit_triggers(days=days, market="spot")


@router.get("/spot/exit-learning/sl-width", dependencies=[Depends(require_db)])
async def spot_exit_learning_sl_width(days: int = Query(90, ge=1, le=365)) -> dict:
    """Bedah lebar SL SPOT per lane."""
    from agents.learning.exit_learning import analyze_sl_width
    return await analyze_sl_width(days=days, market="spot")


@router.post("/spot/exit-learning/backfill-atr", dependencies=[Depends(require_db)])
async def spot_backfill_atr(limit: int = Query(500, ge=1, le=2000)) -> dict:
    """Isi mundur `atr_pct` trade SPOT lama dari klines Binance. Idempoten.

    Tanpa ATR, ledger keluar SPOT tak bisa dinormalkan terhadap volatilitas dan
    mesin belajar tak punya bahan untuk mengusulkan jarak TP.
    """
    from agents.learning.exit_learning import backfill_spot_atr
    return await backfill_spot_atr(limit=limit)


@router.get("/spot/exit-rollout", dependencies=[Depends(require_db)])
async def spot_exit_rollout_status() -> dict:
    """Tahapan penyalaan parameter keluar. Ledger-nya satu untuk dua market —
    daftar yang dikembalikan sudah memuat kolom `market` per baris."""
    from agents.learning.exit_rollout import status
    return await status()


@router.post("/spot/exit-rollout/propose", dependencies=[Depends(require_db)])
async def spot_exit_rollout_propose(days: int = Query(90, ge=1, le=365)) -> dict:
    """Alirkan usulan keluar SPOT ke antrean tahapan. Semua masuk sebagai shadow."""
    from agents.learning.exit_rollout import propose_from_recommendations
    return await propose_from_recommendations(days=days, market="spot")


@router.get("/spot/monitor-config", dependencies=[Depends(require_db)])
async def spot_monitor_config() -> dict:
    """Ambang keputusan keluar SPOT yang SEDANG berlaku."""
    from agents.opportunity import monitor_config as scfg
    await scfg.refresh()
    return {"status": "ok", "config": scfg.snapshot()}


@router.get("/spot/exit-learning/recommendations", dependencies=[Depends(require_db)])
async def spot_exit_learning_recommendations(days: int = Query(90, ge=1, le=365)) -> dict:
    """Usulan parameter keluar SPOT per lane."""
    from agents.learning.exit_learning import recommend_exit_params
    return await recommend_exit_params(days=days, market="spot")


@router.get("/futures/exit-learning/config", dependencies=[Depends(require_db)])
async def exit_learning_config() -> dict:
    """Ambang monitor yang SEDANG berlaku, termasuk batas TP per lane."""
    from agents.futures import monitor_config as mcfg
    await mcfg.refresh()
    return {"status": "ok", "config": mcfg.snapshot()}
