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
# P4.2 / PLAN_v3 D1.1: expanded universe — early-stage movers have low volume but
# high change_pct. Top-change feed injects them even if they're not in top-150 by volume.
UNIVERSE_CAP  = 250

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

async def _fetch_top_change_tickers(existing: list[dict], n: int = 30) -> list[dict]:
    """
    P4.1 / PLAN_v3 D1.1: Inject top-N gainers + top-N losers (by 24h change%) into universe.

    Pulls /fapi/v1/ticker/24hr (weight=40, all-symbols endpoint) and extracts extreme movers.
    Catches early-stage movers (3-8% change) that are not in top-250 by volume — these are
    the coins most likely to become ESPORTS-type big movers within 24h.
    """
    existing_syms = {t["symbol"] for t in existing}
    try:
        async with httpx.AsyncClient(timeout=12) as c:
            r = await c.get(fapi("/fapi/v1/ticker/24hr"))
            if r.status_code != 200:
                return []
            all_tickers = r.json()

        usdt_tickers = [
            t for t in all_tickers
            if t.get("symbol", "").endswith("USDT")
            and t.get("symbol") not in existing_syms
        ]
        usdt_tickers.sort(key=lambda x: float(x.get("priceChangePercent", 0) or 0))

        # Bottom (losers) + top (gainers) — pick coins in the 3-30% move range
        # to focus on early-stage movers, not parabolic/capitulation moves.
        def _in_range(t: dict) -> bool:
            pct = abs(float(t.get("priceChangePercent", 0) or 0))
            return 3.0 <= pct <= 30.0

        losers  = [t for t in usdt_tickers[:n * 2] if _in_range(t)][:n]
        gainers = [t for t in reversed(usdt_tickers[-n * 2:]) if _in_range(t)][:n]
        return gainers + losers
    except Exception:
        return []


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

    # Step 1b2: P4.1 / PLAN_v3 D1.1 — inject top gainers+losers (early-stage movers).
    # Uses the all-symbols /ticker/24hr endpoint (weight=40). These coins are NOT in
    # top-250 volume yet but are just starting to move — prime pre-gainer territory.
    try:
        change_tickers = await _fetch_top_change_tickers(tickers)
        if change_tickers:
            existing_syms = {t["symbol"] for t in tickers}
            added_change = [t for t in change_tickers if t["symbol"] not in existing_syms]
            tickers.extend(added_change)
            logger.info("added_top_change_coins", count=len(added_change))
    except Exception:
        pass  # non-critical

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


# ── Market Pulse helper (PLAN-SIGNAL-GAP P4 + PLAN_v3 D1.4) ─────────────────────

BIG_MOVER_THRESHOLD = 10.0   # |change_24h| % — matches the screenshot's "Big Movers" panel


def _classify_tier(change_pct: float, vol_ratio: float, bb_squeeze: bool) -> str:
    """PLAN_v3 D1.4: classify coin into market pulse tier.

    Tier "big_mover"   — already ≥10% 24h (reactive)
    Tier "rising_star" — 6-10% 24h AND volume 2×+ (early-stage gainer)
    Tier "coiling"     — |change_24h| ≤ 3% AND BB squeeze detected (pre-breakout)
    Tier "other"       — everything else (no special tier)
    """
    abs_chg = abs(change_pct)
    if abs_chg >= BIG_MOVER_THRESHOLD:
        return "big_mover"
    if 6 <= abs_chg < BIG_MOVER_THRESHOLD and vol_ratio >= 2.0:
        return "rising_star"
    if abs_chg <= 3.0 and bb_squeeze:
        return "coiling"
    return "other"


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

        # PLAN_v3 D1.4: compute tier for market pulse classification
        try:
            vol_24h   = float(ticker.get("quoteVolume", 0) or 0)
            vol_avg   = float(ticker.get("volume", 0) or 0)
            vol_ratio = vol_24h / (vol_avg * 20) if vol_avg > 0 else 1.0  # rough 24h vs avg
        except Exception:
            vol_ratio = 1.0
        tier = _classify_tier(change_24h, vol_ratio, bb_squeeze=False)  # bb_squeeze deferred (no kline here)

        movers.append({
            "symbol":       symbol,
            "change_24h":   round(change_24h, 2),
            "price":        price,
            "funding_rate": funding,
            "status":       status,
            "reason":       reason,
            "matches":      matches,
            "tier":         tier,   # PLAN_v3 D1.4: "big_mover" | "rising_star" | "coiling" | "other"
        })

    movers.sort(key=lambda x: abs(x["change_24h"]), reverse=True)
    return movers[:60]


# ── Predictive log helpers (PLAN_v3 P4 D4.1) ─────────────────────────────────

async def _log_predictive_snapshot(scan_result: dict) -> None:
    """Log top scoring candidates from each agent to predictive_log for accuracy tracking."""
    import json as _json
    from app.database import AsyncSessionLocal, is_db_available
    from app.models.predictive_log import PredictiveLog

    if not is_db_available():
        return

    now = time.time()
    rows_to_add = []

    for agent_key in ["agent1", "agent2", "agent3", "agent_bigmover"]:
        agent_data = scan_result.get(agent_key, {})
        # Log top 10 per agent (don't flood the DB)
        for r in agent_data.get("results", [])[:10]:
            rows_to_add.append(PredictiveLog(
                symbol       = r["symbol"],
                agent        = r.get("agent", f"futures_{agent_key}"),
                direction    = r.get("direction", "LONG"),
                regime       = r.get("regime"),
                score        = r.get("score", 0.0),
                signals_json = _json.dumps(r.get("signals", [])[:5]),
                price_at_scan= r.get("price", 0.0),
                oi_change    = r.get("oi_change"),
                funding_rate = r.get("funding_rate"),
                change_24h   = r.get("change_24h"),
                scanned_at   = now,
            ))

    if not rows_to_add:
        return

    async with AsyncSessionLocal() as session:
        session.add_all(rows_to_add)
        await session.commit()

    # Prune predictive_log entries older than 30 days every 1000 cycles
    global _cycle_count
    if _cycle_count % 1000 == 0:
        from sqlalchemy import delete as _del
        async with AsyncSessionLocal() as session:
            await session.execute(
                _del(PredictiveLog).where(PredictiveLog.scanned_at < now - 30 * 86400)
            )
            await session.commit()


async def _resolve_predictive_logs() -> None:
    """Resolve predictions older than 4h by fetching current prices from Binance."""
    import httpx as _httpx
    import json as _json
    from sqlalchemy import select as _sel, update as _upd
    from app.database import AsyncSessionLocal
    from app.models.predictive_log import PredictiveLog
    from app.services.binance_urls import fapi

    now = time.time()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            _sel(PredictiveLog).where(
                PredictiveLog.resolved_at.is_(None),
                PredictiveLog.scanned_at <= now - 4 * 3600,
            ).limit(200)
        )
        pending = result.scalars().all()

    if not pending:
        return

    symbols = list({r.symbol for r in pending})
    price_map: dict[str, float] = {}
    try:
        async with _httpx.AsyncClient(timeout=10) as client:
            syms_param = _json.dumps(symbols, separators=(",", ":"))
            resp = await client.get(fapi("/fapi/v1/ticker/price"), params={"symbols": syms_param})
            if resp.status_code == 200:
                for item in resp.json():
                    price_map[item["symbol"]] = float(item["price"])
    except Exception:
        return

    async with AsyncSessionLocal() as session:
        for row in pending:
            cp = price_map.get(row.symbol)
            if not cp or row.price_at_scan <= 0:
                continue
            age_h    = (now - row.scanned_at) / 3600
            move_pct = (cp - row.price_at_scan) / row.price_at_scan * 100
            directed = move_pct if row.direction == "LONG" else -move_pct
            hit_4h   = directed >= 1.5 if age_h >= 4 else None
            hit_24h  = directed >= 3.0 if age_h >= 24 else None
            # Only mark fully resolved once 24h window has passed.
            # If resolved_at is set at 4h, the row drops out of the unresolved query
            # and the 24h outcome is never written — data loss.
            await session.execute(
                _upd(PredictiveLog).where(PredictiveLog.id == row.id).values(
                    price_4h     = cp if age_h >= 4 else None,
                    price_24h    = cp if age_h >= 24 else None,
                    hit_4h       = hit_4h,
                    hit_24h      = hit_24h,
                    move_4h_pct  = round(directed, 3) if age_h >= 4 else None,
                    move_24h_pct = round(directed, 3) if age_h >= 24 else None,
                    resolved_at  = now if hit_24h is not None else None,
                )
            )
        await session.commit()


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
            # PLAN_v5 Group C: pull DB override for BigMover's fixed score gate.
            # a_bm.scan_symbol() is synchronous and reads the bare global
            # MIN_SCORE — reassigning the module attribute here (before _run_scan
            # calls into it) means every call this cycle sees the live value.
            try:
                from agents.shared.config_reader import cfg
                a_bm.MIN_SCORE = int(await cfg.get("futures", "bigmover_min_score", a_bm.MIN_SCORE))
            except Exception as exc:
                logger.warning("agent_config_pull_failed", scope="futures_scheduler", error=str(exc)[:120])

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

            # D4.1 (PLAN_v3): log top candidates to predictive_log for accuracy measurement
            try:
                await _log_predictive_snapshot(result)
            except Exception as exc:
                logger.warning("predictive_log_failed", error=str(exc)[:80])

            # D4.1: resolve stale predictions every 12 cycles (~24 min)
            if _cycle_count % 12 == 0:
                try:
                    from app.database import AsyncSessionLocal, is_db_available
                    if is_db_available():
                        import httpx as _httpx
                        from sqlalchemy import select as _select, update as _update
                        from app.models.predictive_log import PredictiveLog
                        await _resolve_predictive_logs()
                except Exception as exc:
                    logger.warning("predictive_resolve_failed", error=str(exc)[:80])

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
                from agents.futures.weight_updater import update_weights, flush_rejection_queue
                from agents.shared.cross_agent_learning import update_cross_agent_weights
                await fetch_regime()
                await update_weights()
                await update_cross_agent_weights()   # SP3: cross-agent blending
            except Exception as exc:
                logger.warning("post_scan_learning_error", error=str(exc)[:80])

            # P7.1: flush rejection log queue to DB
            try:
                from agents.futures.weight_updater import flush_rejection_queue
                _rejections = flush_rejection_queue()
                if _rejections:
                    from app.database import AsyncSessionLocal, is_db_available
                    from app.models.rejection_log import RejectionLog
                    if is_db_available():
                        async with AsyncSessionLocal() as _rsess:
                            for _r in _rejections:
                                _rsess.add(RejectionLog(**_r))
                            await _rsess.commit()
                        # Prune rejection_log > 7 days to keep table small
                        if _cycle_count % 100 == 0:
                            from sqlalchemy import delete as _sql_del
                            import time as _t
                            async with AsyncSessionLocal() as _rsess2:
                                await _rsess2.execute(
                                    _sql_del(RejectionLog).where(
                                        RejectionLog.rejected_at < _t.time() - 7 * 86400
                                    )
                                )
                                await _rsess2.commit()
            except Exception as exc:
                logger.warning("rejection_log_flush_failed", error=str(exc)[:80])

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

            # P7 D7.2: monthly threshold calibration — 1st of each month 00:00-00:10 UTC
            try:
                import datetime as _dt2
                _now2 = _dt2.datetime.utcnow()
                if _now2.day == 1 and _now2.hour == 0 and _now2.minute < 10:
                    from agents.learning.monthly_calibration import run_monthly_calibration
                    _cal = await run_monthly_calibration()
                    if _cal.get("changes"):
                        logger.info("monthly_calibration_done", changes=_cal["changes"])
            except Exception as exc:
                logger.warning("monthly_calibration_error", error=str(exc)[:80])

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
