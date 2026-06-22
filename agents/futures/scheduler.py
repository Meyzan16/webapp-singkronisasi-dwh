"""
Futures Scanner Scheduler — runs Agent 1 + Agent 2 every cycle.

Both agents score the same universe sequentially per symbol (F113: not concurrent —
one for-loop calls a1.scan_symbol() then a2.scan_symbol() per ticker).
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
from agents.futures import agent3 as a3
from agents.futures import agent_bigmover as a_bm   # Phase 2 BM1
from agents.futures import store as futures_store
from agents.futures.data import fetch_top100_futures, fetch_symbol_data, fetch_new_listings
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
                syms_param = _json.dumps([r["symbol"] for r in results], separators=(",", ":"))  # BUG-L25: compact
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

    # Step 1c (P3, Lane C / BUG-L18): add recent new-listings — they're rarely in the
    # top-volume universe, so the agents never saw them. Wires discovery → trading.
    try:
        new_listings = await fetch_new_listings(max_age_days=14)
        if new_listings:
            existing_syms = {t["symbol"] for t in tickers}
            added = [nl for nl in new_listings if nl["symbol"] not in existing_syms]
            tickers.extend(added)
            logger.info("added_new_listings", count=len(added))
    except Exception:
        pass  # non-critical — universe still has volume + funding coins

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

    # Step 3: score all agents
    a1_results: list[dict] = []
    a2_results: list[dict] = []
    a3_results: list[dict] = []
    bm_results: list[dict] = []   # Phase 2 BM1

    for ticker in tickers:
        symbol     = ticker["symbol"]
        change_24h = float(ticker.get("priceChangePercent", 0))
        tf_map     = all_tf_maps.get(symbol, {})

        if not tf_map:
            continue

        # F71: skip coins blacklisted due to 3 consecutive SL (24h cooldown)
        if is_blacklisted(symbol):
            continue

        # F34/F52: scan_symbol returns list — extend (not append) to get all directions
        r1_list = a1.scan_symbol(symbol, tf_map, change_24h)
        if r1_list:
            a1_results.extend(r1_list)

        r2_list = a2.scan_symbol(symbol, tf_map, change_24h)
        if r2_list:
            a2_results.extend(r2_list)

        # Phase 11: Agent 3 — Momentum Capture (already-moving coins)
        r3_list = a3.scan_symbol(symbol, tf_map, change_24h)
        if r3_list:
            a3_results.extend(r3_list)

        # Phase 2 BM1: Big Mover lane (≥±15% only — early gate avoids wasted scoring)
        if abs(change_24h) >= a_bm.MIN_CHANGE_24H:
            quote_vol = float(ticker.get("quoteVolume", 0) or 0)
            r_bm = a_bm.scan_symbol(symbol, tf_map, change_24h, quote_vol_24h=quote_vol)
            if r_bm:
                bm_results.extend(r_bm)

    # Sort by score, take top N
    a1_results.sort(key=lambda x: x["score"], reverse=True)
    a2_results.sort(key=lambda x: x["score"], reverse=True)
    a3_results.sort(key=lambda x: x["score"], reverse=True)
    bm_results.sort(key=lambda x: x["score"], reverse=True)
    a1_results_full = a1_results            # PLAN-SIGNAL-GAP P4: keep full list for big-movers match
    a2_results_full = a2_results
    a3_results_full = a3_results
    bm_results_full = bm_results
    a1_results = a1_results[:TOP_N]
    a2_results = a2_results[:TOP_N]
    a3_results = a3_results[:TOP_N]
    bm_results = bm_results[:TOP_N]

    # PLAN-SIGNAL-GAP P4: Big Movers — every scanned coin with |change_24h| >= threshold,
    # tagged with whether it qualified for any lane (and at what score) or not.
    # Lets the frontend show WHY a 50%+ gainer didn't open a position, instead of nothing.
    big_movers = _build_big_movers(
        tickers,
        a1_results_full + a2_results_full + a3_results_full + bm_results_full,
    )

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
        "agent3": {
            "results":      a3_results,
            "total":        len(a3_results),
            "scanned":      len(tickers),
            "generated_at": gen_time,
            "elapsed_sec":  elapsed,
        },
        "agent_bigmover": {
            "results":      bm_results,
            "total":        len(bm_results),
            "scanned":      len(tickers),
            "generated_at": gen_time,
            "elapsed_sec":  elapsed,
        },
        "big_movers": big_movers,   # PLAN-SIGNAL-GAP P4
    }

    logger.info(
        "futures_scan_done",
        agent1=len(a1_results),
        agent2=len(a2_results),
        agent3=len(a3_results),
        agent_bigmover=len(bm_results),
        big_movers=len(big_movers),
        scanned=len(tickers),
        elapsed_sec=elapsed,
    )
    return result


# ── Big Movers helper (PLAN-SIGNAL-GAP P4) ─────────────────────────────────────

BIG_MOVER_THRESHOLD = 10.0   # |change_24h| % — matches the screenshot's "Big Movers" panel


def _build_big_movers(tickers: list[dict], all_results: list[dict]) -> list[dict]:
    """
    Build the Big Movers list: every scanned ticker with |change_24h| >= threshold,
    tagged with whether it qualified for any lane this cycle (and at what score),
    or a heuristic reason why not — so the frontend can explain "kenapa tidak masuk posisi"
    instead of just showing nothing.
    """
    matched: dict[str, list[dict]] = {}
    for r in all_results:
        matched.setdefault(r["symbol"], []).append({
            "agent":     r["agent"],
            "direction": r["direction"],
            "score":     r["score"],
        })

    movers = []
    for ticker in tickers:
        symbol = ticker.get("symbol", "")
        try:
            change_24h = float(ticker.get("priceChangePercent", 0))
        except (TypeError, ValueError):
            continue
        if abs(change_24h) < BIG_MOVER_THRESHOLD:
            continue

        matches = matched.get(symbol, [])
        if matches:
            best   = max(matches, key=lambda m: m["score"])
            status = "lolos"
            reason = f"Lolos {best['agent']} ({best['direction']}) score {best['score']}"
        else:
            status = "tidak_lolos"
            if abs(change_24h) > 50:
                reason = "24h change >50% — di luar jangkauan scoring saat ini (parabolic, risk reversal tinggi)"
            elif abs(change_24h) > 25:
                reason = "24h change >25% — extended move, kemungkinan RSI overbought/oversold atau volume sudah turun dari peak"
            else:
                reason = "Sinyal lain (volume/OI/RSI/breakout) belum cukup kuat untuk lolos threshold"

        # Phase 1 T1: include last price + funding so the watchlist can populate
        # the force-open modal without an extra Binance browser call.
        try:
            price = float(ticker.get("lastPrice", 0) or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            funding = float(ticker.get("lastFundingRate", 0) or 0)
        except (TypeError, ValueError):
            funding = 0.0

        movers.append({
            "symbol":       symbol,
            "change_24h":   round(change_24h, 2),
            "price":        price,
            "funding_rate": funding,
            "status":       status,
            "reason":       reason,
            "matches":      matches,
        })

    movers.sort(key=lambda x: abs(x["change_24h"]), reverse=True)
    return movers[:60]


# ── Main loop ──────────────────────────────────────────────────────────────────

async def run_futures_loop() -> None:
    global _running, _cycle_count, _last_scan, _last_error

    _running = True
    logger.info("futures_scanner_started", interval_min=INTERVAL_SEC // 60)

    # BUG-L11: warm the in-memory learning caches (weights, adaptive thresholds, blacklist)
    # from DB-persisted trades immediately on startup, so a restart doesn't reset thresholds
    # to defaults / drop the coin blacklist until the first scan cycle runs.
    try:
        from agents.futures.weight_updater import update_weights
        await update_weights()
        logger.info("learning_caches_warm_started")
    except Exception as exc:
        logger.warning("warm_start_failed", error=str(exc)[:80])

    await asyncio.sleep(STARTUP_DELAY)

    while True:
        try:
            futures_store.set_scanning(True)
            result = await _run_scan()

            # Store results per agent — then signal scanning done (F107)
            futures_store.set_result("agent1", result["agent1"])
            futures_store.set_result("agent2", result["agent2"])
            futures_store.set_result("agent3", result["agent3"])   # Phase 11
            futures_store.set_result("agent_bigmover", result["agent_bigmover"])   # Phase 2 BM1
            futures_store.set_big_movers(result["big_movers"])     # PLAN-SIGNAL-GAP P4
            futures_store.set_scanning(False)

            # Phase 1 T4b: persist big movers to DB for ground-truth analytics
            try:
                from app.services.big_mover_logger import log_big_movers
                from agents.futures.weight_updater import get_adaptive_thresholds
                a3_thr = get_adaptive_thresholds("futures_agent3").get("auto_threshold", 72)
                await log_big_movers(result["big_movers"], market="futures", threshold=a3_thr)
            except Exception as exc:
                logger.warning("big_mover_log_insert_failed", error=str(exc)[:80])

            _last_scan   = time.time()
            _cycle_count += 1
            _last_error   = None

            logger.info(
                "futures_cycle_done",
                cycle=_cycle_count,
                agent1=result["agent1"]["total"],
                agent2=result["agent2"]["total"],
                agent3=result["agent3"]["total"],
            )

            # P2: UNIFIED auto-open — one ranked pool across all lanes, global dedup (BUG-L1)
            # Phase 2 BM3: include agent_bigmover candidates
            try:
                from agents.futures.auto_trader import auto_open_positions
                all_candidates = (
                    result["agent1"]["results"]
                    + result["agent2"]["results"]
                    + result["agent3"]["results"]
                    + result["agent_bigmover"]["results"]
                )
                total_auto = await auto_open_positions(all_candidates)
                if total_auto:
                    logger.info("auto_positions_opened", opened=total_auto,
                                pool=len(all_candidates))
            except Exception as exc:
                logger.warning("auto_open_error", error=str(exc)[:80])

            # Update regime cache + signal weights after each cycle
            try:
                from agents.futures.regime import fetch_regime
                from agents.futures.weight_updater import update_weights
                from agents.shared.cross_agent_learning import update_cross_agent_weights
                await fetch_regime()
                await update_weights()
                await update_cross_agent_weights()   # SP3: cross-agent blending
            except Exception as exc:
                logger.warning("post_scan_learning_error", error=str(exc)[:80])

            # Phase 1 T4: backfill forward-pnl on big_mover_log every 10 cycles (~20 min)
            if _cycle_count % 10 == 0:
                try:
                    from app.services.big_mover_logger import backfill_pending
                    await backfill_pending(max_rows=100)
                except Exception as exc:
                    logger.warning("big_mover_backfill_failed", error=str(exc)[:80])

            # P3: weekly backtest — Sunday 00:00-00:02 UTC
            try:
                import datetime as _dt
                _now_utc = _dt.datetime.utcnow()
                if _now_utc.weekday() == 6 and _now_utc.hour == 0 and _now_utc.minute < 2:
                    from agents.learning.weekly_backtest import run_weekly_backtest
                    await run_weekly_backtest()
            except Exception as exc:
                logger.warning("weekly_backtest_error", error=str(exc)[:80])

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
