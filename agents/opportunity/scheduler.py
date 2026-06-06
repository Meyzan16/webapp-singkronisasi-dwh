"""
Opportunity Scanner Scheduler — runs every 15 minutes.

After each scan:
  - Results stored in opp_store (for frontend)
  - Coins with score ≥ 95 → AUTO-OPEN posisi (high conviction only)
  - Others → recommendation only (manual open)
"""

import asyncio
import json
import time
from typing import Optional

import structlog

from agents.opportunity import scanner as opp_scanner
from agents.opportunity import store as opp_store

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 15 * 60
STARTUP_DELAY = 20

_running       = False
_cycle_count   = 0
_last_scan_ts: Optional[float] = None
_last_error:   Optional[str]   = None
_auto_opened   = 0   # cumulative auto-opens this session


def get_state() -> dict:
    return {
        "running":          _running,
        "cycle_count":      _cycle_count,
        "last_scan_ts":     _last_scan_ts,
        "last_error":       _last_error,
        "interval_minutes": INTERVAL_SEC // 60,
        "auto_opened":      _auto_opened,
    }


async def _auto_open_position(coin: dict) -> bool:
    """
    Auto-open a SPOT paper trade for high-conviction opportunities (score ≥ 95).
    Returns True if opened, False if skipped (already open or missing levels).
    """
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.paper_trade import PaperTrade
    from sqlalchemy import select

    if not is_db_available():
        return False

    symbol = coin["symbol"]
    entry  = coin.get("entry")
    sl     = coin.get("sl")
    tp2    = coin.get("tp2")

    if not all([entry, sl, tp2]):
        return False   # missing trade levels — skip

    # Dedup: do not open if already have open position for this symbol
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style  == "opportunity_spot",
                PaperTrade.status == "open",
                PaperTrade.symbol == symbol,
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            return False   # already open

        meta = {
            "signals":    coin.get("signals", []),
            "tp1":        coin.get("tp1"),
            "tp2":        coin.get("tp2"),
            "tp3":        coin.get("tp3"),
            "tp1_pct":    coin.get("tp1_pct", 0),
            "tp2_pct":    coin.get("tp2_pct", 0),
            "tp3_pct":    coin.get("tp3_pct", 0),
            "risk_pct":   coin.get("risk_pct", 0),
            "rr_ratio":   coin.get("rr_ratio", 0),
            "vol_ratio":  coin.get("vol_ratio", 1),
            "avg_taker":  coin.get("avg_taker", 0.5),
            "auto_open":  True,
        }

        trade = PaperTrade(
            symbol       = symbol,
            direction    = "LONG",
            style        = "opportunity_spot",
            entry_price  = entry,
            stop_loss    = sl,
            take_profit  = tp2,
            risk_reward  = f"1:{coin.get('rr_ratio', 0)}",
            probability  = coin.get("opportunity_score", 0),
            alert_type   = coin.get("alert_type", "auto"),
            sl_method    = f"Swing low + buffer | AUTO-OPEN score={coin.get('opportunity_score')}",
            tp_method    = f"TP1 +{coin.get('tp1_pct',0):.1f}% | TP2 +{coin.get('tp2_pct',0):.1f}% | TP3 +{coin.get('tp3_pct',0):.1f}%",
            signals_json = json.dumps(meta),
            entry_type   = "auto",   # distinguishes from manual opens
            entry_at     = time.time(),
            status       = "open",
        )
        session.add(trade)
        await session.commit()

    logger.info(
        "opportunity_auto_opened",
        symbol=symbol,
        score=coin.get("opportunity_score"),
        entry=entry, sl=sl, tp2=tp2,
    )
    return True


async def run_opportunity_loop() -> None:
    global _running, _cycle_count, _last_scan_ts, _last_error, _auto_opened

    _running = True
    logger.info("opportunity_agent_started", interval_min=INTERVAL_SEC // 60)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            opp_store.set_scanning(True)
            result = await opp_scanner.run_opportunity_scan()
            opp_store.set_result(result)
            _last_scan_ts = time.time()
            _cycle_count += 1
            _last_error   = None

            # Auto-open high-conviction opportunities (score ≥ 95)
            auto_candidates = [
                c for c in result.get("results", [])
                if c.get("auto_open") and c.get("entry")
            ]
            opened = 0
            for coin in auto_candidates:
                if await _auto_open_position(coin):
                    opened += 1
                    _auto_opened += 1

            logger.info(
                "opportunity_cycle_done",
                cycle=_cycle_count,
                found=result.get("found", 0),
                auto_opened=opened,
            )

        except asyncio.CancelledError:
            opp_store.set_scanning(False)
            logger.info("opportunity_agent_stopped")
            _running = False
            raise
        except Exception as exc:
            opp_store.set_scanning(False)
            _last_error = str(exc)[:120]
            logger.error("opportunity_agent_error", error=_last_error)

        elapsed   = time.time() - (_last_scan_ts or time.time())
        sleep_for = max(60, INTERVAL_SEC - elapsed)
        await asyncio.sleep(sleep_for)
