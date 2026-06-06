"""
Opportunity API — rekomendasi posisi SPOT dengan Entry, SL, TP.

Layer 1 (Scanner): GET  /opportunity/scan          — cached scan results
Layer 2 (Analyzer): GET /opportunity/analyze/{sym} — deep on-demand analysis
Layer 3 (Position): POST /opportunity/trade        — open a paper position
                    GET  /opportunity/positions    — list open positions
"""

import asyncio
import json
import time

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.services.binance_urls import spot as _spot_url

router = APIRouter(tags=["opportunity"])
logger = structlog.get_logger(__name__)


# ── Layer 1: Scanner cache ─────────────────────────────────────────────────────

def _has_trade_levels(cached: dict) -> bool:
    results = cached.get("results", [])
    return bool(results) and "entry" in results[0]


@router.get("/opportunity/scan")
async def get_opportunities(
    min_score:  float = Query(default=30),
    alert_type: str   = Query(default="ALL"),
    limit:      int   = Query(default=30, ge=1, le=100),
) -> dict:
    """Cached scan results. Auto-rescans if cache is old format (no Entry/SL/TP)."""
    from agents.opportunity import store as opp_store
    from agents.opportunity.scanner import run_opportunity_scan

    cached = opp_store.get_result()

    if cached is None or not _has_trade_levels(cached):
        logger.info("opportunity_scan_triggered",
                    reason="cache_miss" if cached is None else "old_format")
        opp_store.set_scanning(True)
        try:
            cached = await run_opportunity_scan()
            opp_store.set_result(cached)
        except Exception as exc:
            opp_store.set_scanning(False)
            logger.error("opportunity_scan_error", error=str(exc))
            if cached is None:
                raise

    return _filter(cached, min_score, alert_type, limit)


@router.post("/opportunity/scan")
async def force_scan_opportunities(
    min_score:  float = Query(default=30),
    alert_type: str   = Query(default="ALL"),
    limit:      int   = Query(default=30, ge=1, le=100),
) -> dict:
    """Force fresh scan, clearing cache. Takes ~25s."""
    from agents.opportunity import store as opp_store
    from agents.opportunity.scanner import run_opportunity_scan

    opp_store.clear_result()
    opp_store.set_scanning(True)
    try:
        fresh = await run_opportunity_scan()
        opp_store.set_result(fresh)
        return _filter(fresh, min_score, alert_type, limit)
    except Exception as exc:
        opp_store.set_scanning(False)
        logger.error("force_scan_error", error=str(exc))
        raise


# ── Layer 2: Coin Analyzer ────────────────────────────────────────────────────

@router.get("/opportunity/analyze/{symbol}")
async def analyze_coin(symbol: str) -> dict:
    """
    Deep on-demand analysis for one coin.
    Fetches 200 candles, computes ATR-based SL and resistance-based TPs.
    ~2–4 seconds.
    """
    from agents.opportunity.analyzer import analyze_coin as _analyze
    result = await _analyze(symbol.upper())
    if "error" in result:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


# ── Layer 3: Position Logger ──────────────────────────────────────────────────

class OpenTradeRequest(BaseModel):
    symbol:            str
    entry:             float
    sl:                float
    tp1:               float
    tp2:               float
    tp3:               float
    risk_pct:          float
    tp1_pct:           float
    tp2_pct:           float
    tp3_pct:           float
    rr_ratio:          float
    opportunity_score: float = 0.0
    alert_type:        str   = "squeeze"
    signals:           list[str] = []
    taker_ratio:       float = 0.5
    confidence:        int   = 50


@router.post("/opportunity/trade")
async def open_opportunity_trade(body: OpenTradeRequest) -> dict:
    """
    Open a paper SPOT position from opportunity scanner/analyzer.
    Saves to paper_trades with style='opportunity_spot'.
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade

    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    # ── Entry price validation: must be within 2% of current market price ──────
    market_prices = await _fetch_spot_prices([body.symbol.upper()])
    market_price  = market_prices.get(body.symbol.upper())
    if market_price:
        diff_pct = abs(body.entry - market_price) / market_price * 100
        if diff_pct > 2.0:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Entry ${body.entry:,.4f} terlalu jauh dari harga pasar "
                    f"${market_price:,.4f} (selisih {diff_pct:.1f}%). "
                    f"Maksimal 2% dari harga saat ini."
                ),
            )

    # ── Per-coin rule: reject if THIS coin already has an open position ────────
    async with AsyncSessionLocal() as check_session:
        existing_result = await check_session.execute(
            select(PaperTrade).where(
                PaperTrade.style  == "opportunity_spot",
                PaperTrade.status == "open",
                PaperTrade.symbol == body.symbol.upper(),
            ).limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"{body.symbol.upper()} sudah ada posisi terbuka "
                       f"pada entry ${existing.entry_price:,.2f}. "
                       f"Tunggu TP/SL sebelum entry ulang.",
            )

    # Store tp1/tp2/tp3 + extra data in signals_json
    meta = {
        "signals":           body.signals,
        "tp1":               body.tp1,
        "tp2":               body.tp2,
        "tp3":               body.tp3,
        "tp1_pct":           body.tp1_pct,
        "tp2_pct":           body.tp2_pct,
        "tp3_pct":           body.tp3_pct,
        "risk_pct":          body.risk_pct,
        "rr_ratio":          body.rr_ratio,
        "opportunity_score": body.opportunity_score,
        "alert_type":        body.alert_type,
        "taker_ratio":       body.taker_ratio,
        "confidence":        body.confidence,
    }

    async with AsyncSessionLocal() as session:
        trade = PaperTrade(
            symbol       = body.symbol.upper(),
            direction    = "LONG",
            style        = "opportunity_spot",
            entry_price  = body.entry,
            stop_loss    = body.sl,
            take_profit  = body.tp2,          # primary target
            risk_reward  = f"1:{body.rr_ratio}",
            probability  = body.opportunity_score,
            alert_type   = body.alert_type,
            sl_method    = f"Swing low - ATR buffer | SL {body.sl} (-{body.risk_pct}%)",
            tp_method    = f"TP1 +{body.tp1_pct}% | TP2 +{body.tp2_pct}% | TP3 +{body.tp3_pct}%",
            signals_json = json.dumps(meta),
            entry_type   = "market",
            entry_at     = time.time(),
            status       = "open",
        )
        session.add(trade)
        await session.commit()
        await session.refresh(trade)

    logger.info("opportunity_trade_opened",
                symbol=body.symbol, entry=body.entry, sl=body.sl,
                tp2=body.tp2, rr=body.rr_ratio)

    return {
        "id":      trade.id,
        "symbol":  trade.symbol,
        "entry":   trade.entry_price,
        "sl":      trade.stop_loss,
        "tp2":     trade.take_profit,
        "status":  "open",
        "message": f"Posisi {body.symbol} berhasil dibuka",
    }


async def _fetch_spot_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch current spot prices for a batch of symbols concurrently."""
    prices: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=8) as client:
        tasks = {
            sym: asyncio.create_task(
                client.get(_spot_url(f"/api/v3/ticker/price?symbol={sym}"))
            )
            for sym in symbols
        }
        for sym, task in tasks.items():
            try:
                r = await task
                if r.status_code == 200:
                    prices[sym] = float(r.json()["price"])
            except Exception:
                pass
    return prices


@router.get("/opportunity/positions")
async def get_open_positions() -> dict:
    """All open opportunity_spot positions with current prices."""
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from sqlalchemy import select

    if not is_db_available():
        return {"positions": [], "total": 0}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade)
            .where(PaperTrade.style == "opportunity_spot")
            .order_by(PaperTrade.entry_at.desc())
            .limit(50)
        )
        trades = result.scalars().all()

    # Fetch live prices for all open positions in one batch
    open_symbols = list({t.symbol for t in trades if t.status == "open"})
    live_prices: dict[str, float] = {}
    if open_symbols:
        try:
            live_prices = await _fetch_spot_prices(open_symbols)
        except Exception:
            pass

    positions = []
    for t in trades:
        try:
            meta = json.loads(t.signals_json or "{}")
        except Exception:
            meta = {}

        # Live P&L for open positions
        current_price:      float | None = live_prices.get(t.symbol) if t.status == "open" else None
        unrealized_pnl_pct: float | None = None
        if current_price and t.entry_price > 0:
            unrealized_pnl_pct = round(
                (current_price - t.entry_price) / t.entry_price * 100, 2
            )

        positions.append({
            "id":                 t.id,
            "symbol":             t.symbol,
            "status":             t.status,
            "entry":              t.entry_price,
            "sl":                 meta.get("current_sl", t.stop_loss),  # trailed SL if any
            "tp1":                meta.get("tp1"),
            "tp2":                t.take_profit,
            "tp3":                meta.get("tp3"),
            "risk_pct":           meta.get("risk_pct", 0),
            "tp1_pct":            meta.get("tp1_pct", 0),
            "tp2_pct":            meta.get("tp2_pct", 0),
            "tp3_pct":            meta.get("tp3_pct", 0),
            "rr_ratio":           meta.get("rr_ratio", 0),
            "score":              t.probability,
            "alert_type":         t.alert_type,
            "signals":            meta.get("signals", []),
            "entry_type":         t.entry_type,           # "market" | "auto"
            "auto_open":          meta.get("auto_open", t.entry_type == "auto"),
            "close_reason":       meta.get("close_reason"),
            "entry_at":           t.entry_at,
            "close_price":        t.close_price,
            "closed_at":          t.closed_at,
            "pnl_pct":            t.pnl_pct,
            "current_price":      current_price,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "tp1_hit":            meta.get("tp1_hit", False),
            "tp1_hit_price":      meta.get("tp1_hit_price"),
        })

    return {"positions": positions, "total": len(positions)}


# ── Manual close ──────────────────────────────────────────────────────────────

@router.post("/opportunity/positions/{position_id}/close")
async def close_position_manually(position_id: int) -> dict:
    """
    Manually close an open position at the current market price.
    Sets status='manual' so it can be distinguished from TP/SL closes.
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade

    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.id    == position_id,
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status == "open",
            )
        )
        trade = result.scalar_one_or_none()
        if not trade:
            raise HTTPException(status_code=404,
                                detail="Posisi tidak ditemukan atau sudah tertutup")

        # Fetch live price; fall back to entry if Binance unreachable
        prices = await _fetch_spot_prices([trade.symbol])
        close_price = prices.get(trade.symbol) or trade.entry_price
        pnl = round((close_price - trade.entry_price) / trade.entry_price * 100, 2)

        trade.status      = "manual"
        trade.close_price = close_price
        trade.pnl_pct     = pnl
        trade.closed_at   = time.time()

        await session.commit()
        await session.refresh(trade)

    logger.info("opportunity_position_manual_close",
                id=position_id, symbol=trade.symbol,
                close_price=close_price, pnl_pct=pnl)

    return {
        "id":          trade.id,
        "symbol":      trade.symbol,
        "status":      "manual",
        "close_price": close_price,
        "pnl_pct":     pnl,
        "message":     f"Posisi {trade.symbol} ditutup manual @ ${close_price:,.4f}",
    }


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/opportunity/status")
async def get_opportunity_status() -> dict:
    from agents.opportunity.scheduler import get_state
    from agents.opportunity import store as opp_store
    from agents.opportunity.monitor import get_state as monitor_state

    state   = get_state()
    last_ts = opp_store.last_scan_ts()
    next_in = None
    if last_ts:
        next_in = max(0, round((900 - (time.time() - last_ts)) / 60, 1))

    return {
        **state,
        "next_scan_in_min": next_in,
        "monitor": monitor_state(),
    }


# ── Internal helper ────────────────────────────────────────────────────────────

def _filter(cached: dict, min_score: float, alert_type: str, limit: int) -> dict:
    results = cached.get("results", [])
    if min_score > 0:
        results = [r for r in results if r["opportunity_score"] >= min_score]
    if alert_type != "ALL":
        results = [r for r in results if r.get("alert_type") == alert_type]
    return {
        "results":      results[:limit],
        "total":        len(results),
        "scanned":      cached.get("scanned", 0),
        "generated_at": cached.get("generated_at", 0),
        "elapsed_sec":  cached.get("elapsed_sec", 0),
    }
