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
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.services.binance_urls import spot as _spot_url
from app.services.trading_costs import EXECUTION_COST_PCT

router = APIRouter(tags=["opportunity"])
logger = structlog.get_logger(__name__)

# §16.2: single-flight — N request bersamaan saat cache kosong tidak boleh
# memicu N full-scan paralel
_scan_lock = asyncio.Lock()
_last_force_scan: float = 0.0
FORCE_SCAN_COOLDOWN_SEC = 60


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
        # §16.2: single-flight — pemegang lock pertama scan, sisanya pakai hasilnya
        async with _scan_lock:
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
    """Force fresh scan, clearing cache. Takes ~25s. Cooldown 60s (§16.2)."""
    global _last_force_scan
    from agents.opportunity import store as opp_store
    from agents.opportunity.scanner import run_opportunity_scan

    if time.time() - _last_force_scan < FORCE_SCAN_COOLDOWN_SEC:
        cached = opp_store.get_result()
        if cached:
            return _filter(cached, min_score, alert_type, limit)
        raise HTTPException(status_code=429,
                            detail="Force scan cooldown — coba lagi sebentar lagi")

    async with _scan_lock:
        _last_force_scan = time.time()
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


@router.get("/opportunity/config")
async def get_scanner_config() -> dict:
    """
    §11.1: konstanta engine sebagai satu sumber kebenaran — UI merender aturan
    dari sini sehingga header/legend tidak pernah bisa berbohong lagi.
    """
    from agents.opportunity import scanner as _sc
    from app.api.v1 import balance as _bal

    return {
        "min_score":          _sc.MIN_SCORE,
        "auto_open_score":    _sc.AUTO_OPEN_SCORE,
        "top_n":              _sc.TOP_N,
        "rr_min":             3.5,
        "sl_buffer_pct":      0.8,
        "risk_pct_range":     [1.5, 5.0],
        "tp2_rule":           "max(4×risk, +6%)",
        "tp3_rule":           "max(7×risk, +10%)",
        "execution_cost_pct": EXECUTION_COST_PCT,
        "direction_gate":     f"taker ≥ {_sc.DIRECTION_TAKER_MIN} atau EMA9>EMA21 1h",
        "btc_regime_gate":    f"BTC 24h < {_sc.BTC_REGIME_24H_MIN}% → auto-open OFF",
        "max_concurrent":     _bal.MAX_CONCURRENT_POSITIONS,
        "max_portfolio_risk": _bal.MAX_PORTFOLIO_RISK,
        "min_notional":       _bal.MIN_NOTIONAL_ABS,
        "max_notional_frac":  _bal.MAX_NOTIONAL_FRACTION,
        "risk_fraction_range": [_bal.RISK_BASE_FRACTION, _bal.RISK_MAX_FRACTION],
        "scan_interval_min":  3,
    }


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
    """§14.1: server-side validation — client input is untrusted."""
    symbol:            str   = Field(..., min_length=5, max_length=20)
    entry:             float = Field(..., gt=0)
    sl:                float = Field(..., gt=0)
    tp1:               float = Field(..., gt=0)
    tp2:               float = Field(..., gt=0)
    tp3:               float = Field(..., gt=0)
    risk_pct:          float = Field(..., ge=1.0, le=6.0)
    tp1_pct:           float = Field(..., ge=0)
    tp2_pct:           float = Field(..., ge=0)
    tp3_pct:           float = Field(..., ge=0)
    rr_ratio:          float = Field(..., gt=0)
    opportunity_score: float = Field(default=0.0, ge=0, le=200)
    alert_type:        str   = "squeeze"
    signals:           list[str] = []
    taker_ratio:       float = Field(default=0.5, ge=0, le=1)
    confidence:        int   = Field(default=50, ge=0, le=100)
    entry_mode:        str   = Field(default="fresh_setup")
    force_open:        bool  = False         # Phase 1 T2 — manual override
    session_id:        str   | None = None   # B1.2 — rate limit

    @model_validator(mode="after")
    def _validate_levels(self) -> "OpenTradeRequest":
        # Struktur level LONG yang sah: 0 < sl < entry < tp1 ≤ tp2 ≤ tp3
        if not (self.sl < self.entry):
            raise ValueError("SL harus di bawah entry (posisi LONG)")
        if not (self.entry < self.tp1 <= self.tp2 <= self.tp3):
            raise ValueError("Urutan target salah: entry < tp1 ≤ tp2 ≤ tp3")
        # TP2 harus melebihi biaya eksekusi — kalau tidak, trade net-minus by design
        tp2_net = (self.tp2 - self.entry) / self.entry * 100 - EXECUTION_COST_PCT
        if tp2_net <= 0:
            raise ValueError(
                f"TP2 net {tp2_net:.2f}% ≤ 0 setelah biaya eksekusi {EXECUTION_COST_PCT}%"
            )
        return self


@router.post("/opportunity/trade")
async def open_opportunity_trade(body: OpenTradeRequest) -> dict:
    """
    Open a paper SPOT position from opportunity scanner/analyzer.
    Saves to paper_trades with style='opportunity_spot'.
    Position size is calculated from actual current paper balance
    (fixed-fractional risk, conviction-scaled). Entry is rejected when
    available balance cannot fund the full notional.
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from app.api.v1.balance import compute_spot_sizing

    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    # Phase 1 B1.2: DB-persistent force-open rate limit (5/jam per session)
    if body.force_open:
        from app.services.force_open_limiter import can_force_open, record_force_open
        sess = (body.session_id or "default").strip()[:64] or "default"
        allowed, used, _ = await can_force_open(sess)
        if not allowed:
            await record_force_open(sess, body.symbol, "LONG", "spot", accepted=False)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit force-open: {used}/5 dipakai dalam 1 jam terakhir.",
            )

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

    # ── Balance-aware sizing: full notional must fit in available balance ──────
    sizing = await compute_spot_sizing(
        score    = body.opportunity_score,
        risk_pct = body.risk_pct,
    )
    if not sizing["can_open"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Balance tidak cukup: {sizing['reason']}. "
                f"Tutup posisi lain atau deposit dulu — tidak ada partial entry."
            ),
        )
    current_balance = sizing["balance"]
    risk_dollar     = sizing["risk_dollar"]
    position_size   = sizing["position_size"]

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
        "entry_mode":        body.entry_mode,
        "manual":            bool(body.force_open),
    }

    async with AsyncSessionLocal() as session:
        trade = PaperTrade(
            symbol           = body.symbol.upper(),
            direction        = "LONG",
            style            = "opportunity_spot",
            entry_price      = body.entry,
            stop_loss        = body.sl,
            take_profit      = body.tp2,          # primary target
            risk_reward      = f"1:{body.rr_ratio}",
            probability      = body.opportunity_score,
            alert_type       = body.alert_type,
            sl_method        = f"Swing low - ATR buffer | SL {body.sl} (-{body.risk_pct}%)",
            tp_method        = f"TP1 +{body.tp1_pct}% | TP2 +{body.tp2_pct}% | TP3 +{body.tp3_pct}%",
            signals_json     = json.dumps(meta, ensure_ascii=False),
            entry_type       = "market",
            entry_at         = time.time(),
            status           = "open",
            position_size    = round(position_size, 2),
            risk_dollar      = round(risk_dollar, 2),
            balance_snapshot = round(current_balance, 2),
        )
        session.add(trade)
        try:
            await session.commit()
        except Exception:
            # §13.5: unique index — race dengan auto-open agent di simbol sama
            await session.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"{body.symbol.upper()} baru saja dibuka oleh agent. "
                       f"Satu posisi per koin.",
            )
        await session.refresh(trade)

    logger.info("opportunity_trade_opened",
                symbol=body.symbol, entry=body.entry, sl=body.sl,
                tp2=body.tp2, rr=body.rr_ratio, force_open=body.force_open)

    # Phase 1 B1.2: record successful force-open against rate limit
    if body.force_open:
        from app.services.force_open_limiter import record_force_open
        sess = (body.session_id or "default").strip()[:64] or "default"
        await record_force_open(sess, body.symbol, "LONG", "spot", accepted=True)

    return {
        "id":             trade.id,
        "symbol":         trade.symbol,
        "entry":          trade.entry_price,
        "sl":             trade.stop_loss,
        "tp2":            trade.take_profit,
        "status":         "open",
        "position_size":  round(position_size, 2),
        "risk_dollar":    round(risk_dollar, 2),
        "balance_used":   round(current_balance, 2),
        "message":        f"Posisi {body.symbol} dibuka @ ${body.entry:,.4f} | Notional ${position_size:,.0f} | Risk ${risk_dollar:.2f}",
    }


# §13.6: harga di-share semua poller lewat cache TTL pendek — History (15 dtk)
# + halaman Opportunity (30 dtk) + multi-tab tidak lagi menghasilkan ratusan
# request per menit. Batch endpoint dengan separator compact (pelajaran §1.8).
_price_cache: dict[str, float] = {}
_price_cache_at: float = 0.0
PRICE_CACHE_TTL_SEC = 8.0


async def _fetch_spot_prices(symbols: list[str]) -> dict[str, float]:
    """Batch spot prices with short TTL cache."""
    global _price_cache, _price_cache_at
    if not symbols:
        return {}

    now = time.time()
    if now - _price_cache_at < PRICE_CACHE_TTL_SEC and all(
        s in _price_cache for s in symbols
    ):
        return {s: _price_cache[s] for s in symbols}

    prices: dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            syms_param = json.dumps(sorted(symbols), separators=(",", ":"))
            r = await client.get(_spot_url("/api/v3/ticker/price"),
                                 params={"symbols": syms_param})
            if r.status_code == 200 and isinstance(r.json(), list):
                for item in r.json():
                    prices[item["symbol"]] = float(item["price"])
            else:
                # Fallback per-simbol (jarang — mis. simbol delisted dalam batch)
                tasks = {
                    sym: asyncio.create_task(
                        client.get(_spot_url(f"/api/v3/ticker/price?symbol={sym}"))
                    )
                    for sym in symbols
                }
                for sym, task in tasks.items():
                    try:
                        resp = await task
                        if resp.status_code == 200:
                            prices[sym] = float(resp.json()["price"])
                    except Exception:
                        pass
    except Exception:
        pass

    if prices:
        _price_cache.update(prices)
        _price_cache_at = now
    return prices


@router.get("/opportunity/positions")
async def get_open_positions(days: int = Query(default=30, ge=1, le=365)) -> dict:
    """
    Open positions (always) + closed positions from the last `days` days (§6.3).
    Full history lives in /history/trades (paginated).
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from sqlalchemy import or_, select

    if not is_db_available():
        return {"positions": [], "total": 0}

    cutoff = time.time() - days * 86400
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade)
            .where(
                PaperTrade.style == "opportunity_spot",
                or_(
                    PaperTrade.status == "open",
                    PaperTrade.closed_at >= cutoff,
                ),
            )
            .order_by(PaperTrade.entry_at.desc())
            .limit(500)
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
            # Kurangi biaya eksekusi agar konsisten dengan P&L saat posisi ditutup monitor
            unrealized_pnl_pct = round(
                (current_price - t.entry_price) / t.entry_price * 100 - EXECUTION_COST_PCT, 2
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
            "manual":             bool(meta.get("manual", False)),   # PLAN_v8 P5: force-open marker
            "entry_mode":         meta.get("entry_mode"),            # PLAN_v8 P2: lane hint (bigmover_chase, etc.)
            "close_reason":       meta.get("close_reason"),
            "entry_at":           t.entry_at,
            "close_price":        t.close_price,
            "closed_at":          t.closed_at,
            "pnl_pct":            t.pnl_pct,
            "current_price":      current_price,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "tp1_hit":            meta.get("tp1_hit", False),
            "tp1_hit_price":      meta.get("tp1_hit_price"),
            "confidence":         meta.get("confidence", 50),
            "position_size":      t.position_size,
            "risk_dollar":        t.risk_dollar,
            "balance_snapshot":   t.balance_snapshot,
            "pnl_dollar":         t.pnl_dollar,
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

        # §13.1: tanpa harga live, JANGAN tutup — close di harga entry = P&L fiktif
        prices = await _fetch_spot_prices([trade.symbol])
        close_price = prices.get(trade.symbol)
        if close_price is None or close_price <= 0:
            raise HTTPException(
                status_code=503,
                detail="Harga pasar tidak tersedia (Binance unreachable). Coba lagi.",
            )

        # §13.2: konsisten dengan monitor — P&L net biaya eksekusi penuh.
        # Honor partial sell TP1 (§15.3) bila ada.
        try:
            meta = json.loads(trade.signals_json or "{}")
            if not isinstance(meta, dict):
                meta = {}
        except (json.JSONDecodeError, TypeError):
            meta = {}

        pnl_net_pct = round(
            (close_price - trade.entry_price) / trade.entry_price * 100
            - EXECUTION_COST_PCT, 2
        )
        remaining   = meta.get("remaining_fraction", 1.0)
        partial_dlr = meta.get("tp1_partial_dollar", 0.0)
        pos_size    = trade.position_size or 0.0
        pnl_dollar  = round((pnl_net_pct / 100) * pos_size * remaining + partial_dlr, 2)
        blended_pct = round(pnl_dollar / pos_size * 100, 2) if pos_size > 0 else pnl_net_pct

        meta["close_reason"] = "manual"
        meta["fee_pct"]      = EXECUTION_COST_PCT
        trade.status       = "manual"
        trade.close_price  = close_price
        trade.pnl_pct      = blended_pct
        trade.pnl_dollar   = pnl_dollar
        trade.closed_at    = time.time()
        trade.signals_json = json.dumps(meta, ensure_ascii=False)

        # §13.3: commit TRADE dulu — balance menyusul (recalc idempotent dari SUM)
        await session.commit()
        await session.refresh(trade)
        pnl = blended_pct

    # Balance: recalc penuh via monitor helper (konsisten satu rumus)
    from agents.opportunity.monitor import _update_paper_balance
    await _update_paper_balance()

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
    from agents.opportunity.scheduler import INTERVAL_SEC, get_state
    from agents.opportunity import store as opp_store
    from agents.opportunity.monitor import get_state as monitor_state

    state   = get_state()
    last_ts = opp_store.last_scan_ts()
    next_in = None
    if last_ts:
        next_in = max(0, round((INTERVAL_SEC - (time.time() - last_ts)) / 60, 1))

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
        "btc_regime":   cached.get("btc_regime"),
        "error":        cached.get("error"),
        "generated_at": cached.get("generated_at", 0),
        "elapsed_sec":  cached.get("elapsed_sec", 0),
    }
