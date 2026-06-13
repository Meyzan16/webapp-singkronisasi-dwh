"""
Futures Scanner Scheduler — runs Agent 1 + Agent 2 every 15 minutes.

Both agents run concurrently on the same 100-symbol universe.
Results go into futures store (separate per agent).
"""

import asyncio
import time
from typing import Optional

import httpx
import structlog

from agents.futures import agent1 as a1
from app.services.binance_urls import fapi
from agents.futures import agent2 as a2
from agents.futures import store as futures_store
from agents.futures.data import fetch_top100_futures, fetch_symbol_data
from agents.futures.weight_updater import is_blacklisted   # B4: top-level import

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 2 * 60    # scan every 2 minutes — pre-gainer signals can form fast
STARTUP_DELAY = 30        # start after main scanner
TOP_N         = 30        # top results per agent
TIMEFRAMES    = ["15m", "1h", "4h"]
# Expand universe: pre-gainer hunt needs wider coverage beyond just top-100 by volume
UNIVERSE_CAP  = 150

_running     = False
_cycle_count = 0
_last_scan:  Optional[float] = None
_last_error: Optional[str]   = None


def get_state() -> dict:
    # F9: expose next_scan_in_min so API/WS don't re-derive it (and get it wrong)
    next_in = round(max(0, INTERVAL_SEC - (time.time() - (_last_scan or 0))) / 60, 1) \
              if _last_scan else None
    return {
        "running":          _running,
        "cycle_count":      _cycle_count,
        "last_scan_ts":     _last_scan,
        "last_error":       _last_error,
        "interval_minutes": INTERVAL_SEC // 60,
        "next_scan_in_min": next_in,
    }


# ── Scan runner ────────────────────────────────────────────────────────────────

async def _fetch_extreme_funding_tickers(existing: list[dict]) -> list[dict]:
    """
    Fetch coins with extreme funding rates (abs > 0.03%) using premiumIndex (weight~2).
    Returns synthetic ticker dicts compatible with the main ticker list.
    Only returns coins NOT already in the existing top-100 list.
    F101: fetches real priceChangePercent so change-based penalties work correctly.
    """
    import json as _json
    existing_syms = {t["symbol"] for t in existing}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(fapi("/fapi/v1/premiumIndex"))
        if r.status_code != 200:
            return []
        data = r.json()
        results = []
        for item in data:
            sym = item.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            if sym in existing_syms:
                continue
            fr = float(item.get("lastFundingRate", 0))
            if abs(fr) >= 0.0003:   # 0.03% threshold
                results.append({
                    "symbol": sym,
                    "priceChangePercent": "0",   # fallback, overwritten below
                    "lastFundingRate": str(fr),
                })
        results = results[:30]   # cap at 30 extra coins

        # F101: fetch real 24h price change so change-based penalties/bonuses trigger
        if results:
            try:
                syms_param = _json.dumps([r["symbol"] for r in results])
                t_r = await c.get(fapi("/fapi/v1/ticker/24hr"), params={"symbols": syms_param})
                if t_r.status_code == 200:
                    ticker_map = {t["symbol"]: t for t in t_r.json()}
                    for r in results:
                        if r["symbol"] in ticker_map:
                            r["priceChangePercent"] = ticker_map[r["symbol"]].get("priceChangePercent", "0")
            except Exception:
                pass   # keep "0" fallback if batch fetch fails

    return results


async def _run_scan() -> dict:
    """
    Full scan cycle: fetch data for all 100 symbols, run both agents.
    Returns {"agent1": {...}, "agent2": {...}}.
    """
    start = time.time()
    logger.info("futures_scan_start")

    # Step 1: top-N futures tickers by volume (expanded for pre-gainer coverage)
    tickers = await fetch_top100_futures()
    if not tickers:
        raise RuntimeError("Could not fetch Futures tickers from Binance")
    tickers = tickers[:UNIVERSE_CAP]

    # Step 1b: add extreme funding rate coins for Agent 1 (not always in top-100 volume)
    # premiumIndex endpoint is weight=~2, very cheap
    try:
        extreme_tickers = await _fetch_extreme_funding_tickers(tickers)
        if extreme_tickers:
            existing_syms = {t["symbol"] for t in tickers}
            for et in extreme_tickers:
                if et["symbol"] not in existing_syms:
                    tickers.append(et)
            logger.info("added_extreme_funding_coins", count=len(extreme_tickers))
    except Exception:
        pass  # non-critical — agent2 still scans top-100

    # Step 2: fetch klines + futures data concurrently
    # Rate limit budget: ~941 weight/scan vs 2400/min Binance limit — safe to be faster
    BATCH       = 20   # 20 symbols concurrent (was 10) — 2× faster
    BATCH_SLEEP = 0.2  # 200ms between batches (was 500ms) — still rate-limit safe
    all_tf_maps: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=20) as client:
        for i in range(0, len(tickers), BATCH):
            batch = tickers[i: i + BATCH]
            tasks = {
                t["symbol"]: asyncio.create_task(
                    fetch_symbol_data(t["symbol"], TIMEFRAMES, client=client)
                )
                for t in batch
            }
            for symbol, task in tasks.items():
                try:
                    all_tf_maps[symbol] = await task
                except Exception:
                    all_tf_maps[symbol] = {}
            await asyncio.sleep(BATCH_SLEEP)

    # Step 3: score both agents
    a1_results: list[dict] = []
    a2_results: list[dict] = []

    for ticker in tickers:
        symbol     = ticker["symbol"]
        change_24h = float(ticker.get("priceChangePercent", 0))
        tf_map     = all_tf_maps.get(symbol, {})

        if not tf_map:
            continue

        # F71: skip coins blacklisted due to 3 consecutive SL (24h cooldown)
        if is_blacklisted(symbol):
            continue

        # F34/F52: scan_symbol now returns list — extend (not append) to get all directions
        r1_list = a1.scan_symbol(symbol, tf_map, change_24h)
        if r1_list:
            a1_results.extend(r1_list)

        r2_list = a2.scan_symbol(symbol, tf_map, change_24h)
        if r2_list:
            a2_results.extend(r2_list)

    # Sort by score, take top N
    a1_results.sort(key=lambda x: x["score"], reverse=True)
    a2_results.sort(key=lambda x: x["score"], reverse=True)
    a1_results = a1_results[:TOP_N]
    a2_results = a2_results[:TOP_N]

    elapsed  = round(time.time() - start, 1)
    gen_time = int(time.time())

    result = {
        "agent1": {
            "results":      a1_results,
            "total":        len(a1_results),
            "scanned":      len(tickers),
            "generated_at": gen_time,
            "elapsed_sec":  elapsed,
        },
        "agent2": {
            "results":      a2_results,
            "total":        len(a2_results),
            "scanned":      len(tickers),
            "generated_at": gen_time,
            "elapsed_sec":  elapsed,
        },
    }

    logger.info(
        "futures_scan_done",
        agent1=len(a1_results),
        agent2=len(a2_results),
        scanned=len(tickers),
        elapsed_sec=elapsed,
    )
    return result


# ── Main loop ──────────────────────────────────────────────────────────────────

async def run_futures_loop() -> None:
    global _running, _cycle_count, _last_scan, _last_error

    _running = True
    logger.info("futures_scanner_started", interval_min=INTERVAL_SEC // 60)
    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            futures_store.set_scanning(True)
            result = await _run_scan()

            # Store results per agent — then signal scanning done (F107)
            futures_store.set_result("agent1", result["agent1"])
            futures_store.set_result("agent2", result["agent2"])
            futures_store.set_scanning(False)

            _last_scan   = time.time()
            _cycle_count += 1
            _last_error   = None

            logger.info(
                "futures_cycle_done",
                cycle=_cycle_count,
                agent1=result["agent1"]["total"],
                agent2=result["agent2"]["total"],
            )

            # Auto-open high-score positions (score >= 75)
            try:
                from agents.futures.auto_trader import auto_open_positions
                a1_auto = await auto_open_positions(result["agent1"]["results"], "futures_agent1")
                a2_auto = await auto_open_positions(result["agent2"]["results"], "futures_agent2")
                if a1_auto or a2_auto:
                    logger.info("auto_positions_opened", agent1=a1_auto, agent2=a2_auto)
            except Exception as exc:
                logger.warning("auto_open_error", error=str(exc)[:80])

            # Update regime cache + signal weights after each cycle
            try:
                from agents.futures.regime import fetch_regime
                from agents.futures.weight_updater import update_weights
                await fetch_regime()
                await update_weights()
            except Exception as exc:
                logger.warning("post_scan_learning_error", error=str(exc)[:80])

        except asyncio.CancelledError:
            futures_store.set_scanning(False)
            logger.info("futures_scanner_stopped")
            _running = False
            raise
        except Exception as exc:
            futures_store.set_scanning(False)
            _last_error = str(exc)[:120]
            logger.error("futures_scanner_error", error=_last_error)

        elapsed   = time.time() - (_last_scan or time.time())
        sleep_for = max(30, INTERVAL_SEC - elapsed)   # min 30s gap between scans
        await asyncio.sleep(sleep_for)
