"""
Futures Scanner API — Agent 1 (Pre-Gainer) + Agent 2 (Accumulation) + Agent 3 (Momentum).

GET  /futures/scan             — cached results (all agents)
POST /futures/scan             — force fresh scan
GET  /futures/positions        — open futures paper trades
POST /futures/trade            — open a futures paper trade
GET  /futures/status           — scheduler + agent status
"""

import json
import time
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

router = APIRouter(tags=["futures"])
logger = structlog.get_logger(__name__)


# ── Schema ─────────────────────────────────────────────────────────────────────

class OpenFuturesTradeRequest(BaseModel):
    symbol:    str
    direction: str       # "LONG" | "SHORT"
    agent:     str       # "futures_agent1" | "futures_agent2" | "futures_agent3"
    entry:     float
    sl:        float
    tp1:       float
    tp2:       float
    tp3:       float
    risk_pct:  float
    tp1_pct:   float
    tp2_pct:   float
    tp3_pct:   float
    rr_ratio:  float
    leverage:  int       = 5
    score:     float     = 0.0
    signals:   list[str] = []
    funding_rate: float  = 0.0
    oi_change:    float  = 0.0
    liq_long:     float  = 0.0
    liq_short:    float  = 0.0


# ── Layer 1: Scan cache ────────────────────────────────────────────────────────

@router.get("/futures/scan")
async def get_futures_scan(
    agent:     str   = Query(default="all",  description="all | agent1 | agent2 | agent3"),
    direction: str   = Query(default="ALL",  description="ALL | LONG | SHORT"),
    min_score: float = Query(default=52),   # F105: match agent MIN threshold (was 55)
    limit:     int   = Query(default=30, ge=1, le=100),
) -> dict:
    """Cached scan results from both agents. Triggers fresh scan if cache empty."""
    from agents.futures import store as fs
    from agents.futures.scheduler import _run_scan

    cached = fs.get_all_results()

    if not cached:
        logger.info("futures_scan_triggered", reason="cache_miss")
        fs.set_scanning(True)
        try:
            result = await _run_scan()
            fs.set_result("agent1", result["agent1"])
            fs.set_result("agent2", result["agent2"])
            fs.set_result("agent3", result["agent3"])
            cached = fs.get_all_results()
        except Exception as exc:
            fs.set_scanning(False)
            logger.error("futures_scan_error", error=str(exc))
            raise HTTPException(status_code=503, detail="Scan gagal: " + str(exc)[:80])

    return _filter_results(cached, agent, direction, min_score, limit)


@router.post("/futures/scan")
async def force_futures_scan(
    agent:     str   = Query(default="all"),
    direction: str   = Query(default="ALL"),
    min_score: float = Query(default=52),   # F105: match agent MIN threshold (was 55)
    limit:     int   = Query(default=30, ge=1, le=100),
) -> dict:
    """Force fresh scan of 100 Futures pairs. Takes ~30–60s."""
    from agents.futures import store as fs
    from agents.futures.scheduler import _run_scan

    fs.clear_results()
    fs.set_scanning(True)
    try:
        result = await _run_scan()
        fs.set_result("agent1", result["agent1"])
        fs.set_result("agent2", result["agent2"])
        fs.set_result("agent3", result["agent3"])
        return _filter_results(fs.get_all_results(), agent, direction, min_score, limit)
    except Exception as exc:
        fs.set_scanning(False)
        logger.error("futures_force_scan_error", error=str(exc))
        raise HTTPException(status_code=503, detail=str(exc)[:100])


# ── Layer 2: Open position ─────────────────────────────────────────────────────

@router.post("/futures/trade")
async def open_futures_trade(body: OpenFuturesTradeRequest) -> dict:
    """
    Open a futures paper trade (Agent 1, 2, or 3).
    Rules: per-coin per-agent dedup, entry within 2% of market, R:R ≥ 1:3.
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade

    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    # Phase 10: risk gate — circuit-breaker + RAR gate (first check, before any other validation)
    from agents.futures.risk_gate import is_gate_open, is_state_stale, evaluate_risk_gate
    if is_state_stale():
        await evaluate_risk_gate()
    gate_open, gate_reason = is_gate_open()
    if not gate_open:
        raise HTTPException(status_code=422, detail=f"Risk gate aktif: {gate_reason}")

    symbol = body.symbol.upper()

    # Entry validation: within 2% of market price
    from agents.futures.data import fetch_top100_futures
    import httpx
    from app.services.binance_urls import fapi
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(fapi(f"/fapi/v1/ticker/price?symbol={symbol}"))
            if r.status_code == 200:
                market_price = float(r.json()["price"])
                diff = abs(body.entry - market_price) / market_price * 100
                if diff > 2.0:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Entry ${body.entry:,.4f} terlalu jauh dari market "
                               f"${market_price:,.4f} (selisih {diff:.1f}%). Max 2%."
                    )
    except HTTPException:
        raise
    except Exception:
        pass  # if price fetch fails, allow the trade

    # R:R ≥ 1:3 validation (F19)
    risk   = abs(body.entry - body.sl)
    reward = abs(body.tp2 - body.entry)
    if risk > 0 and reward / risk < 3.0:
        raise HTTPException(
            status_code=422,
            detail=f"R:R {reward/risk:.1f} terlalu kecil. Minimum R:R 1:3 — perbesar TP2 atau perkecil SL.",
        )

    # Dedup: one open position per symbol per agent
    async with AsyncSessionLocal() as check:
        existing = await check.execute(
            select(PaperTrade).where(
                PaperTrade.style  == body.agent,
                PaperTrade.status == "open",
                PaperTrade.symbol == symbol,
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"{symbol} sudah ada posisi terbuka di {body.agent}. Tunggu TP/SL."
            )

    # Store extra data in signals_json
    meta = {
        "signals":      body.signals,
        "tp1":          body.tp1,
        "tp2":          body.tp2,
        "tp3":          body.tp3,
        "tp1_pct":      body.tp1_pct,
        "tp2_pct":      body.tp2_pct,
        "tp3_pct":      body.tp3_pct,
        "risk_pct":     body.risk_pct,
        "rr_ratio":     body.rr_ratio,
        "leverage":     body.leverage,
        "score":        body.score,
        "funding_rate": body.funding_rate,
        "oi_change":    body.oi_change,
        "liq_long":     body.liq_long,
        "liq_short":    body.liq_short,
        "margin_type":  "cross",
    }

    from agents.futures.regime import get_cached_regime
    current_regime = get_cached_regime()

    # Phase 9: size from the REAL shared futures wallet (balance-aware + portfolio heat).
    from app.api.v1.balance import compute_futures_sizing
    _risk_pct = body.risk_pct or 2.0
    sizing    = await compute_futures_sizing(body.score, _risk_pct, body.leverage)
    if not sizing["can_open"]:
        raise HTTPException(status_code=422, detail=f"Wallet futures menolak: {sizing['reason']}")
    _pos_size        = sizing["position_size"]
    _risk_dollar_val = sizing["risk_dollar"]
    _bal_snapshot    = sizing["balance"]

    async with AsyncSessionLocal() as session:
        trade = PaperTrade(
            symbol           = symbol,
            direction        = body.direction,
            style            = body.agent,
            entry_price      = body.entry,
            stop_loss        = body.sl,
            take_profit      = body.tp2,
            risk_reward      = f"1:{body.rr_ratio}",
            probability      = body.score,
            alert_type       = body.direction.lower(),
            sl_method        = f"Swing {'low' if body.direction == 'LONG' else 'high'} + ATR | SL {body.sl}",
            tp_method        = f"TP1 +{body.tp1_pct}% | TP2 +{body.tp2_pct}% | TP3 +{body.tp3_pct}%",
            signals_json     = json.dumps(meta, ensure_ascii=False),
            entry_type       = "market",
            entry_at         = time.time(),
            status           = "open",
            leverage         = body.leverage,
            margin_type      = "cross",
            regime           = current_regime,
            trail_active     = False,
            position_size    = _pos_size,
            risk_dollar      = _risk_dollar_val,
            balance_snapshot = _bal_snapshot,
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)

    logger.info("futures_trade_opened",
                symbol=symbol, direction=body.direction, agent=body.agent,
                entry=body.entry, sl=body.sl, tp2=body.tp2,
                leverage=body.leverage, rr=body.rr_ratio)

    return {
        "id":      trade.id,
        "symbol":  trade.symbol,
        "agent":   body.agent,
        "direction": body.direction,
        "entry":   trade.entry_price,
        "sl":      trade.stop_loss,
        "tp2":     trade.take_profit,
        "leverage": body.leverage,
        "status":  "open",
        "message": f"Posisi {body.direction} {symbol} dibuka ({body.agent})",
    }


# ── Layer 3: Positions ─────────────────────────────────────────────────────────

@router.get("/futures/positions")
async def get_futures_positions(
    agent:  str = Query(default="all"),
    status: str = Query(default="all"),
) -> dict:
    """All futures paper trades (both agents) with live prices for open positions."""
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    import httpx
    from app.services.binance_urls import fapi

    if not is_db_available():
        return {"positions": [], "total": 0}

    # Build filter
    _ALL_STYLES = ["futures_agent1", "futures_agent2", "futures_agent3"]
    conditions = [
        PaperTrade.style.in_(_ALL_STYLES)
    ]
    if agent == "agent1":
        conditions = [PaperTrade.style == "futures_agent1"]
    elif agent == "agent2":
        conditions = [PaperTrade.style == "futures_agent2"]
    elif agent == "agent3":
        conditions = [PaperTrade.style == "futures_agent3"]
    if status != "all":
        conditions.append(PaperTrade.status == status)

    async with AsyncSessionLocal() as session:
        # F24: no limit — equity curve and balance need the full closed-trade history
        result = await session.execute(
            select(PaperTrade)
            .where(*conditions)
            .order_by(PaperTrade.entry_at.desc())
        )
        trades = result.scalars().all()

    # Fetch live prices for open positions — batch endpoint (weight=2 for all, F18)
    open_symbols = list({t.symbol for t in trades if t.status == "open"})
    live_prices: dict[str, float] = {}
    if open_symbols:
        try:
            import json as _json
            async with httpx.AsyncClient(timeout=8) as c:
                syms_param = _json.dumps(open_symbols)
                r = await c.get(fapi("/fapi/v1/ticker/price"), params={"symbols": syms_param})
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        for item in data:
                            live_prices[item["symbol"]] = float(item["price"])
        except Exception:
            pass

    positions = []
    for t in trades:
        try:
            meta = json.loads(t.signals_json or "{}")
        except Exception:
            meta = {}

        cp = live_prices.get(t.symbol) if t.status == "open" else None
        _FUTURES_FEE_PCT = 0.10  # 0.05% taker per side × 2 round-trip (F23)
        upnl = None
        if cp and t.entry_price > 0:
            if t.direction == "LONG":
                upnl = round((cp - t.entry_price) / t.entry_price * 100 - _FUTURES_FEE_PCT, 2)
            else:
                upnl = round((t.entry_price - cp) / t.entry_price * 100 - _FUTURES_FEE_PCT, 2)

        positions.append({
            "id":               t.id,
            "symbol":           t.symbol,
            "direction":        t.direction,
            "agent":            t.style,
            "status":           t.status,
            "entry":            t.entry_price,
            "sl":               t.stop_loss,
            "tp1":              meta.get("tp1"),
            "tp2":              t.take_profit,
            "tp3":              meta.get("tp3"),
            "risk_pct":         meta.get("risk_pct", 0),
            "tp2_pct":          meta.get("tp2_pct", 0),
            "rr_ratio":         meta.get("rr_ratio", 0),
            "leverage":         t.leverage or meta.get("leverage", 1),
            "margin_type":      t.margin_type or meta.get("margin_type", "cross"),
            "score":            t.probability,
            "signals":          meta.get("signals", []),
            "funding_rate":     meta.get("funding_rate", 0),
            "oi_change":        meta.get("oi_change", 0),
            "entry_at":         t.entry_at,
            "close_price":      t.close_price,
            "closed_at":        t.closed_at,
            "pnl_pct":          t.pnl_pct,
            "current_price":    cp,
            "unrealized_pnl":   upnl,
        })

    return {"positions": positions, "total": len(positions)}


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/futures/status")
async def get_futures_status() -> dict:
    from agents.futures import store as fs
    from agents.futures.scheduler import get_state

    state   = get_state()
    ts_a1   = fs.last_scan_ts("agent1")
    ts_a2   = fs.last_scan_ts("agent2")
    last_ts = max(ts_a1 or 0, ts_a2 or 0) or None
    from agents.futures.scheduler import INTERVAL_SEC as _SCHED_INTERVAL
    next_in = max(0, round((_SCHED_INTERVAL - (time.time() - last_ts)) / 60, 1)) if last_ts else None

    return {
        **state,
        "next_scan_in_min":  next_in,
        "agent1_last_scan":  ts_a1,
        "agent2_last_scan":  ts_a2,
        "agent1_results":    len((fs.get_result("agent1") or {}).get("results", [])),
        "agent2_results":    len((fs.get_result("agent2") or {}).get("results", [])),
    }


# ── Risk Monitor ──────────────────────────────────────────────────────────────

# F33/Phase 9: shared notional math; balance now comes from the real wallet
from app.services.trading_costs import futures_notional as _notional

def _liq_price(entry: float, leverage: int, direction: str) -> float:
    """Cross margin liquidation ≈ entry ± (95% of margin)."""
    dist = entry * (0.95 / max(leverage, 1))
    return (entry - dist) if direction == "LONG" else (entry + dist)


def _margin(notional: float, leverage: int) -> float:
    return notional / max(leverage, 1)


@router.get("/futures/monitor/risk")
async def get_risk_dashboard() -> dict:
    """
    Portfolio-level risk dashboard for all open futures paper trades.
    Returns per-position: liq_price, margin, SL, TP, unrealized P&L, risk status.
    Returns portfolio: total_margin, at_risk_count, risk_adjusted_return.
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    import httpx
    from app.services.binance_urls import fapi
    import math

    if not is_db_available():
        return {"error": "db_unavailable", "positions": [], "portfolio": {}}

    _ALL_STYLES = ["futures_agent1", "futures_agent2", "futures_agent3"]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(_ALL_STYLES),
                PaperTrade.status == "open",
            ).order_by(PaperTrade.entry_at.desc())
        )
        open_trades = list(result.scalars().all())

        # Also get all closed for risk-adjusted return
        closed_result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(_ALL_STYLES),
                PaperTrade.status.in_(["tp", "sl"]),
            ).order_by(PaperTrade.entry_at)
        )
        closed_trades = list(closed_result.scalars().all())

    # Fetch live prices — batch endpoint (weight=2 for all, F27)
    symbols = list({t.symbol for t in open_trades})
    live_prices: dict[str, float] = {}
    if symbols:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                syms_param = json.dumps(symbols)
                r = await c.get(fapi("/fapi/v1/ticker/price"), params={"symbols": syms_param})
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        for item in data:
                            live_prices[item["symbol"]] = float(item["price"])
        except Exception:
            pass

    positions = []
    total_margin   = 0.0
    at_risk_count  = 0
    total_unrealized = 0.0

    for t in open_trades:
        try:
            meta = json.loads(t.signals_json or "{}")
        except Exception:
            meta = {}

        leverage   = t.leverage or meta.get("leverage", 5)
        risk_pct   = meta.get("risk_pct", 2.0)
        # BUG-L23: use the trade's REAL stored notional (balance-aware at open);
        # fall back to the $1000-based helper only for legacy rows without position_size.
        notional   = t.position_size or _notional(risk_pct)
        margin     = _margin(notional, leverage)
        entry      = t.entry_price
        sl         = t.trail_sl or t.stop_loss
        tp1        = meta.get("tp1")
        tp2        = t.take_profit
        tp3        = meta.get("tp3")
        direction  = t.direction

        liq         = _liq_price(entry, leverage, direction)
        current     = live_prices.get(t.symbol, entry)

        # Unrealized P&L % — deduct 0.10% round-trip fee (F28)
        _FUTURES_FEE_PCT = 0.10
        if direction == "LONG":
            upnl_pct = (current - entry) / entry * 100 - _FUTURES_FEE_PCT if entry > 0 else 0.0
        else:
            upnl_pct = (entry - current) / entry * 100 - _FUTURES_FEE_PCT if entry > 0 else 0.0
        upnl_dollar = upnl_pct / 100 * notional

        # Distance to liquidation %
        if direction == "LONG":
            liq_dist_pct = (current - liq) / current * 100 if current > 0 else 99.0
        else:
            liq_dist_pct = (liq - current) / current * 100 if current > 0 else 99.0

        # Risk status
        if liq_dist_pct < 5.0:
            risk_status = "DANGER"   # very close to liquidation
            at_risk_count += 1
        elif liq_dist_pct < 15.0:
            risk_status = "WARNING"
        else:
            risk_status = "SAFE"

        # Distance from SL %
        if direction == "LONG":
            sl_dist_pct = (current - sl) / current * 100 if current > 0 else 0.0
        else:
            sl_dist_pct = (sl - current) / current * 100 if current > 0 else 0.0

        total_margin     += margin
        total_unrealized += upnl_dollar

        positions.append({
            "id":            t.id,
            "symbol":        t.symbol,
            "direction":     direction,
            "agent":         t.style,
            "entry":         entry,
            "current":       round(current, 8),
            "sl":            round(sl, 8),
            "tp1":           tp1,
            "tp2":           round(tp2, 8),
            "tp3":           tp3,
            "leverage":      leverage,
            "notional":      round(notional, 2),
            "margin":        round(margin, 2),
            "liq_price":     round(liq, 8),
            "liq_dist_pct":  round(liq_dist_pct, 2),
            "sl_dist_pct":   round(sl_dist_pct, 2),
            "upnl_pct":      round(upnl_pct, 2),
            "upnl_dollar":   round(upnl_dollar, 2),
            "risk_pct":      risk_pct,
            "risk_status":   risk_status,
            "trail_active":  bool(t.trail_active),
            "score":         t.probability,
            "auto_opened":   meta.get("auto_opened", False),
            "entry_at":      t.entry_at,
            "regime":        t.regime or "unknown",
        })

    # ── Risk-Adjusted Return (simplified Calmar / Sharpe proxy) ─────────────────
    # Phase 9: seed from the REAL futures wallet so current_balance matches deposits.
    from app.api.v1.balance import get_or_create_balance
    _wallet     = await get_or_create_balance("futures")
    wallet_base = _wallet.initial_balance + _wallet.deposited_total - _wallet.withdrawn_total

    pnl_series: list[float] = []
    balance     = wallet_base
    peak_bal    = wallet_base
    max_dd      = 0.0

    for t in closed_trades:
        try:
            meta     = json.loads(t.signals_json or "{}")
            risk_pct = meta.get("risk_pct", 2.0)
        except Exception:
            risk_pct = 2.0
        # Use the stored dollar P&L (real sizing); fall back to recompute for legacy rows
        pnl_d   = t.pnl_dollar if t.pnl_dollar is not None else (t.pnl_pct or 0.0) / 100 * _notional(risk_pct)
        balance += pnl_d
        pnl_series.append(pnl_d)
        if balance > peak_bal:
            peak_bal = balance
        dd = (peak_bal - balance) / peak_bal * 100 if peak_bal > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Sharpe proxy: mean / std of P&L series
    import statistics
    sharpe = 0.0
    if len(pnl_series) >= 5:
        try:
            mu  = statistics.mean(pnl_series)
            std = statistics.stdev(pnl_series)
            sharpe = round(mu / std, 3) if std > 0 else 0.0
        except Exception:
            pass

    # Phase 10: refresh risk gate state with fresh metrics (frontend polls this every 15 s)
    from agents.futures.risk_gate import update_gate_state, get_gate_state
    update_gate_state(max_dd, sharpe, len(pnl_series))
    _gate = get_gate_state()

    total_closed_pnl = balance - wallet_base

    return {
        "positions": positions,
        "portfolio": {
            "open_count":       len(positions),
            "total_margin":     round(total_margin, 2),
            "total_notional":   round(sum(p["notional"] for p in positions), 2),
            "total_unrealized": round(total_unrealized, 2),
            "at_risk_count":    at_risk_count,
            "max_drawdown_pct": round(max_dd, 2),
            "risk_adjusted_return": sharpe,
            "total_closed_pnl": round(total_closed_pnl, 2),
            "starting_balance": round(wallet_base, 2),
            "current_balance":  round(balance, 2),
        },
        "agent_breakdown": {
            "agent1": {
                "open": sum(1 for p in positions if p["agent"] == "futures_agent1"),
                "margin": round(sum(p["margin"] for p in positions if p["agent"] == "futures_agent1"), 2),
                "at_risk": sum(1 for p in positions if p["agent"] == "futures_agent1" and p["risk_status"] == "DANGER"),
            },
            "agent2": {
                "open": sum(1 for p in positions if p["agent"] == "futures_agent2"),
                "margin": round(sum(p["margin"] for p in positions if p["agent"] == "futures_agent2"), 2),
                "at_risk": sum(1 for p in positions if p["agent"] == "futures_agent2" and p["risk_status"] == "DANGER"),
            },
            "agent3": {
                "open": sum(1 for p in positions if p["agent"] == "futures_agent3"),
                "margin": round(sum(p["margin"] for p in positions if p["agent"] == "futures_agent3"), 2),
                "at_risk": sum(1 for p in positions if p["agent"] == "futures_agent3" and p["risk_status"] == "DANGER"),
            },
        },
        "generated_at": time.time(),
        "gate": _gate,   # Phase 10: full gate state — frontend reads from risk dashboard
    }


# ── Risk gate (Phase 10) ──────────────────────────────────────────────────────

@router.get("/futures/risk/gate")
async def get_risk_gate() -> dict:
    """
    Current risk gate state.
    gate_type: none | circuit_breaker | rar | override
    active=True means NO new positions are allowed.
    """
    from agents.futures.risk_gate import is_state_stale, evaluate_risk_gate, get_gate_state
    if is_state_stale():
        await evaluate_risk_gate()
    return get_gate_state()


class GateOverrideRequest(BaseModel):
    open: Optional[bool] = None  # True=force gate open | False=force closed | None=auto


@router.post("/futures/risk/gate/override")
async def override_risk_gate(body: GateOverrideRequest) -> dict:
    """
    Manual gate override. Use carefully — this bypasses or enforces the circuit-breaker.
      open=True  → force gate open (allow new positions even when metrics say stop)
      open=False → force gate closed (block new positions regardless of metrics)
      open=None  → revert to auto (clears override; next cycle re-evaluates)
    """
    from agents.futures.risk_gate import set_override, get_gate_state
    set_override(body.open)
    return {"message": "Override diset", "gate": get_gate_state()}


# ── Auto-trade toggle ──────────────────────────────────────────────────────────

class AutoTradeToggle(BaseModel):
    enabled: bool
    threshold: Optional[int] = None   # F102: optional manual override (None = adaptive)


@router.get("/futures/auto/status")
async def get_auto_status() -> dict:
    """Get auto-trade status and settings."""
    from agents.futures.auto_trader import is_auto_enabled, get_auto_threshold, MAX_AUTO_POSITIONS
    return {
        "enabled":       is_auto_enabled(),
        "threshold":     get_auto_threshold(),   # F102: reflects manual override if set
        "max_positions": MAX_AUTO_POSITIONS,
    }


@router.post("/futures/auto/toggle")
async def toggle_auto_trade(body: AutoTradeToggle) -> dict:
    """Enable or disable automatic paper trade opening (optionally override threshold)."""
    from agents.futures.auto_trader import set_auto_enabled, set_auto_threshold, get_auto_threshold
    set_auto_enabled(body.enabled)
    if body.threshold is not None:        # F102: apply manual threshold when provided
        set_auto_threshold(body.threshold)
    return {
        "enabled":   body.enabled,
        "threshold": get_auto_threshold(),
        "message":   f"Auto-trade {'enabled' if body.enabled else 'disabled'}",
    }


# ── Helper ─────────────────────────────────────────────────────────────────────

def _filter_results(
    cached: dict,
    agent: str,
    direction: str,
    min_score: float,
    limit: int,
) -> dict:
    a1 = cached.get("agent1", {})
    a2 = cached.get("agent2", {})
    a3 = cached.get("agent3", {})

    def _apply(results: list) -> list:
        out = [r for r in results if r.get("score", 0) >= min_score]
        if direction != "ALL":
            out = [r for r in out if r.get("direction") == direction]
        return out[:limit]

    return {
        "agent1":       _apply(a1.get("results", [])) if agent in ("all", "agent1") else [],
        "agent2":       _apply(a2.get("results", [])) if agent in ("all", "agent2") else [],
        "agent3":       _apply(a3.get("results", [])) if agent in ("all", "agent3") else [],
        "scanned":      max(a1.get("scanned", 0), a2.get("scanned", 0), a3.get("scanned", 0)),
        "generated_at": max(a1.get("generated_at", 0), a2.get("generated_at", 0), a3.get("generated_at", 0)),
        "elapsed_sec":  max(a1.get("elapsed_sec", 0), a2.get("elapsed_sec", 0), a3.get("elapsed_sec", 0)),
    }
