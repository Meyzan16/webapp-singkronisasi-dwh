"""
Futures Scanner Scheduler — menjalankan AGEN TUNGGAL tiap siklus.

Fase 8: empat lane lama (pre_gainer, accumulation, momentum, bigmover) dihapus
setelah trade era mereka tutup semuanya. Riwayatnya tidak ikut hilang —
`FUTURES_AGENTS` di registry tetap memuat nama lane pensiun, jadi monitor dan
endpoint riwayat masih bisa membaca 112 trade tertutup itu.
"""

import asyncio
import time
from typing import Optional

import httpx
import structlog

from app.services.binance_urls import fapi
from agents.futures import agentic as ag            # Fase 3 — agen tunggal
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
    Returns {"agentic": {...}, "big_movers": [...]}.
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
        pass  # non-critical — pemindaian utama tetap jalan

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
    ag_results: list[dict] = []   # Fase 3 — agen tunggal (kosong selama saklar mati)

    # Dibaca SEKALI per scan, bukan per simbol: saklar yang berubah di tengah
    # siklus akan menghasilkan setengah scan lama + setengah scan baru.
    _agentic_aktif = ag.enabled()

    # PLAN_v15 P3a: market breadth — of the top gainers (24h > +10%) we scanned,
    # how many are already fading on 1h? High fraction = pump-and-fade day →
    # auto_trader blocks new BigMover LONGs. Uses data already in hand (no extra API).
    _breadth_gainers = 0
    _breadth_fading  = 0

    for ticker in tickers:
        symbol     = ticker["symbol"]
        change_24h = float(ticker.get("priceChangePercent", 0))
        tf_map     = all_tf_maps.get(symbol, {})

        if not tf_map:
            continue

        # PLAN_v15 P3a: breadth sample — gainer >+10% 24h, 1h candle direction
        _d1h_b = tf_map.get("1h")
        if change_24h > 10.0 and _d1h_b and len(_d1h_b.closes) >= 2 and _d1h_b.closes[-2] > 0:
            _breadth_gainers += 1
            if _d1h_b.closes[-1] < _d1h_b.closes[-2]:
                _breadth_fading += 1

        # F71: skip coins blacklisted due to 3 consecutive SL (24h cooldown)
        if is_blacklisted(symbol):
            continue

        # Fase 7: begitu agen tunggal menyala, empat pemindai lama BERHENTI
        # menghasilkan kandidat baru. Tanpa gerbang ini keduanya memindai
        # bersamaan dan sama-sama membuka posisi dari SATU dompet — kuota dan
        # panas portofolio akan terisi dua sumber yang tak saling tahu.
        #
        # Fase 8: agen tunggal adalah SATU-SATUNYA yang memindai.
        # Empat lane lama (pre_gainer, accumulation, momentum, bigmover) dihapus
        # setelah trade era mereka tutup semua. Riwayatnya tetap utuh: monitor
        # dan endpoint riwayat memakai `FUTURES_AGENTS` yang masih memuat nama
        # lane pensiun, jadi 112 trade tertutup tetap terbaca.
        r_ag = ag.scan_symbol(symbol, tf_map, change_24h,
                              quote_vol_24h=float(ticker.get("quoteVolume", 0) or 0))
        if r_ag:
            ag_results.extend(r_ag)

    # Sort by score, take top N
    ag_results.sort(key=lambda x: x["score"], reverse=True)
    ag_results_full = ag_results            # PLAN-SIGNAL-GAP P4: daftar penuh utk pencocokan big-movers
    ag_results = ag_results[:TOP_N]

    # PLAN_ADAPTIVE_LEARNING_FUTURES_10X F2: terapkan learning policy per-lane —
    # menempelkan adaptive_score/probability/ban ke tiap kandidat (dict yang sama
    # mengalir ke auto_open + ledger + UI). TIDAK mengubah field `score` dasar.
    learning_status = "warming"
    try:
        from agents.futures.learning_loader import load_futures_learning, apply_lane_learning
        from agents.futures.weight_updater import get_adaptive_thresholds
        _lw, _lp, _lsc, _lban, learning_status, _lerr = await load_futures_learning()
        # Veto & skor pembelajaran diterapkan ke agen yang BENAR-BENAR berdagang.
        # Sampai Fase 8 loop ini hanya menyentuh empat lane lama, sehingga
        # `banned_by_learning` tak pernah berlaku untuk agen tunggal — auto_trader
        # memeriksanya, tapi tak ada yang pernah menyalakannya.
        for _res, _agent in ((ag_results, "futures_agentic"),):
            _thr = get_adaptive_thresholds(_agent).get("auto_threshold", 72)
            apply_lane_learning(_res, _lw, _lp, _lsc, _lban, _thr, learning_status)
        if _lerr:
            logger.warning("futures_learning_apply_degraded", error=_lerr)
    except Exception as exc:
        logger.warning("futures_learning_apply_failed", error=str(exc)[:160])

    # PLAN-SIGNAL-GAP P4: Big Movers — every scanned coin with |change_24h| >= threshold,
    # tagged with whether it qualified for any lane (and at what score) or not.
    # Lets the frontend show WHY a 50%+ gainer didn't open a position, instead of nothing.
    big_movers = _build_big_movers(
        tickers,
        ag_results_full,
    )

    # PLAN_v15 P3a: publish breadth for auto_trader's fade-day gate
    _fade_frac = round(_breadth_fading / _breadth_gainers, 3) if _breadth_gainers else 0.0
    futures_store.set_market_breadth({
        "gainers":   _breadth_gainers,
        "fading":    _breadth_fading,
        "fade_frac": _fade_frac,
    })
    if _breadth_gainers >= 5 and _fade_frac >= 0.6:
        logger.warning("market_breadth_fade_day", gainers=_breadth_gainers,
                       fading=_breadth_fading, fade_frac=_fade_frac)

    elapsed  = round(time.time() - start, 1)
    gen_time = int(time.time())

    result = {
        "agentic": {
            "results":      ag_results,
            "total":        len(ag_results),
            "scanned":      len(tickers),
            "generated_at": gen_time,
            "elapsed_sec":  elapsed,
        },
        "big_movers": big_movers,   # PLAN-SIGNAL-GAP P4
        "learning_status": learning_status,   # F2: warming | active | degraded
    }

    logger.info(
        "futures_scan_done",
        agentic=len(ag_results),
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
            # PLAN_v6 P5b: reasons updated for P4 reality — big movers are now
            # tradeable up to 300% (extreme tier at half size) and extended-move
            # penalties are health-scaled. The old ">50% out of scoring range"
            # text described pre-P4 behavior and misled the owner.
            if abs(change_24h) > 300:
                reason = "24h change >300% — blow-off territory, sengaja di-skip (satu-satunya hard cap tersisa)"
            elif abs(change_24h) >= 150:
                reason = ("Masuk jangkauan EXTREME tier (150-300%, size ½) tapi score/health belum lolos — "
                          "cek OI turun / funding crowded / volume memudar, atau slot bigmover penuh (2)")
            else:
                reason = ("Score belum lolos threshold lane manapun — momentum-health (OI/volume/funding), "
                          "timing gate (wick/chase), slot penuh, atau cooldown SL")

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

    for agent_key in ["agentic"]:
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

    # Pemangkasan predictive_log kini pekerjaan berjadwal (jobs.prune_predictive_log).
    # Dulu dipicu `% 1000` siklus — dengan hitungan yang kembali nol tiap restart,
    # ia praktis tak pernah sampai giliran.


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
                # PLAN_v15 P3c: weekend size damper — DB-overridable like MIN_SCORE
                a_bm.WEEKEND_SIZE_MULT = await cfg.get(
                    "futures", "weekend_size_mult", a_bm.WEEKEND_SIZE_MULT)
                # Lantai target SHORT. Cadangannya nilai BEKU, bukan nilai modul
                # yang baru saja ditimpa siklus sebelumnya — kalau tidak, bawaan
                # ikut hanyut dan tak ada lagi titik pulang yang benar.
                a_bm.SHORT_TP_MAX_DROP_FRAC = await cfg.get(
                    "futures", "bigmover_short_tp_max_drop_frac",
                    a_bm._FROZEN_SHORT_TP_MAX_DROP_FRAC)
                # Tangga TP (kelipatan ATR). Ditarik SEBELUM scan supaya setiap
                # level yang disusun siklus ini memakai tala yang sama — bukan
                # campuran nilai lama dan baru dalam satu putaran.
                for _v, _k in (("TP1_ATR_MULT", "bigmover_tp1_atr_mult"),
                               ("TP2_ATR_MULT", "bigmover_tp2_atr_mult"),
                               ("TP3_ATR_MULT", "bigmover_tp3_atr_mult")):
                    setattr(a_bm, _v, float(await cfg.get(
                        "futures", _k, a_bm._FROZEN_TP[_v])))
            except Exception as exc:
                logger.warning("agent_config_pull_failed", scope="futures_scheduler", error=str(exc)[:120])

            # M4: lebar SL per lane. Ditarik SEBELUM scan supaya setiap level yang
            # disusun siklus ini memakai tala yang sama — bukan campuran nilai
            # lama dan baru di tengah jalan.
            try:
                from agents.futures import sl_config
                await sl_config.refresh()
            except Exception as exc:
                logger.warning("sl_config_pull_failed", scope="futures_scheduler",
                               error=str(exc)[:120])

            # Fase 1a: rantai ukuran (risk/notional/leverage/margin). Ditarik DI
            # SINI, bukan menumpang loop monitor. Sampai 5 Sep 2026 plafon
            # leverage scanner memang datang dari mutasi dict oleh loop monitor —
            # jadi kalau monitor mati atau siklus pertamanya belum selesai,
            # scanner memakai angka hardcode sementara UI menampilkan angka lain.
            try:
                from agents.futures import agentic as _ag_cfg
                await _ag_cfg.refresh()
            except Exception as exc:
                logger.warning("agentic_config_pull_failed", scope="futures_scheduler",
                               error=str(exc)[:120])

            try:
                from agents.futures import exit_config as _ecfg
                await _ecfg.refresh()
            except Exception as exc:
                logger.warning("exit_config_pull_failed", scope="futures_scheduler",
                               error=str(exc)[:120])

            try:
                from agents.futures import sizing_config
                await sizing_config.refresh()
            except Exception as exc:
                logger.warning("sizing_config_pull_failed", scope="futures_scheduler",
                               error=str(exc)[:120])

            futures_store.set_scanning(True)
            result = await _run_scan()

            # Store results per agent — then signal scanning done (F107)
            futures_store.set_result("agentic", result["agentic"])                 # Fase 3
            futures_store.set_big_movers(result["big_movers"])     # PLAN-SIGNAL-GAP P4
            futures_store.set_learning_status(result.get("learning_status", "warming"))  # F2
            futures_store.set_scanning(False)

            # Phase 1 T4b: persist big movers to DB for ground-truth analytics
            try:
                from app.services.big_mover_logger import log_big_movers
                from agents.futures.weight_updater import get_adaptive_thresholds
                a3_thr = get_adaptive_thresholds("futures_agentic").get("auto_threshold", 72)
                await log_big_movers(result["big_movers"], market="futures", threshold=a3_thr)
            except Exception as exc:
                logger.warning("big_mover_log_insert_failed", error=str(exc)[:80])

            _last_scan   = time.time()
            _cycle_count += 1

            # ── Pekerjaan berkala ────────────────────────────────────────────
            # Dulu sembilan blok terpisah di sepanjang loop ini, masing-masing
            # dipicu `_cycle_count % N` atau jendela kalender dua menit. Dua-duanya
            # gagal SENYAP: hitungan siklus kembali nol tiap restart, dan jendela
            # kalender hanya menyala bila sebuah siklus scan kebetulan mendarat di
            # dalamnya — kalau scanner sedang berhenti, backtest mingguan terlewat
            # SEMINGGU PENUH tanpa satu baris log pun.
            #
            # Sekarang jadwalnya dinyatakan dalam WAKTU dan waktu jalan terakhirnya
            # disimpan di DB. Lihat agents/futures/jobs.py.
            try:
                from agents.futures import jobs as _jobs
                from agents.learning.mode import LEARNING_STANDALONE

                # Kerja belajar berat (backtest mingguan, kalibrasi bulanan)
                # BUKAN milik proses ini. Terukur 8 Sep 2026: dijalankan di sini
                # ia membekukan event loop lima menit penuh — denyut `ws_feed`
                # sepuluh detik pun berhenti. Proses `agents.learning` yang
                # menjalankannya; lihat catatan `Pekerjaan.berat`.
                _hasil_jobs = await _jobs.run_due(
                    lingkup="ringan" if LEARNING_STANDALONE else "semua")
                if _hasil_jobs["dijalankan"]:
                    # Durasinya ikut DI SETIAP kali jalan, bukan hanya saat sudah
                    # terlanjur lambat. Ambang WARNING memberi tahu ketika sesuatu
                    # sudah buruk; ia tak pernah memberi tahu bahwa perbaikan
                    # BERHASIL — sukses hanya tampak sebagai hilangnya peringatan,
                    # dan kesunyian sama saja bentuknya dengan pekerjaan yang tak
                    # pernah jalan.
                    logger.info("futures_jobs_ran", jobs=_hasil_jobs["dijalankan"],
                                total_detik=_hasil_jobs.get("total_detik"),
                                durasi=_hasil_jobs.get("durasi"))
                if _jobs.ambil_outcome_baru():
                    _outcomes_baru = True
            except Exception as exc:
                logger.warning("futures_jobs_failed", error=str(exc)[:200])
            _last_error   = None

            logger.info(
                "futures_cycle_done",
                cycle=_cycle_count,
                agentic=result["agentic"]["total"],   # Fase 3
            )

            # D4.1 (PLAN_v3): log top candidates to predictive_log for accuracy measurement
            try:
                await _log_predictive_snapshot(result)
            except Exception as exc:
                logger.warning("predictive_log_failed", error=str(exc)[:400])

            # P2: UNIFIED auto-open — one ranked pool across all lanes, global dedup (BUG-L1)
            # Fase 8: hanya agen tunggal yang mengisi kolam
            try:
                from agents.futures.auto_trader import auto_open_positions
                # Kandidat agen tunggal WAJIB ikut kolam ini.
                #
                # Sampai 9 Sep 2026 baris `result["agentic"]` hanya disimpan ke
                # store dan dicatat ke log — tak pernah diteruskan ke sini, dan
                # tak ada jalur pembukaan lain di seluruh repo. Jadi agen tunggal
                # memindai 290 simbol, memberi skor, memeringkat, menampilkan
                # 9-18 kandidat tiap siklus, lalu hasilnya berhenti di layar.
                #
                # Ia terlihat bekerja sempurna dari luar: saklar menyala, gerbang
                # risiko terbuka, kandidat berlimpah, nol posisi. Yang hilang
                # bukan pengaman yang menolak — melainkan sambungan yang tak
                # pernah ada.
                all_candidates = result["agentic"]["results"]
                total_auto = await auto_open_positions(all_candidates)
                if total_auto:
                    logger.info("auto_positions_opened", opened=total_auto,
                                pool=len(all_candidates))

                # PLAN_ADAPTIVE_LEARNING_FUTURES_10X F1+F5: ledger keputusan —
                # SETELAH auto_open (peta keputusan final). F5: tempelkan prediksi
                # shadow ke kandidat SEBELUM log supaya tersimpan di snapshot
                # (tak memengaruhi keputusan — murni observasi utk canary/drift).
                try:
                    from agents.futures.decision_ledger import log_scan_decisions
                    from agents.learning.futures_adaptive_model import score_shadow_candidates
                    await score_shadow_candidates(all_candidates)
                    await log_scan_decisions(
                        all_candidates,
                        scan_ts=result["agentic"].get("generated_at"),
                    )
                except Exception as exc:
                    logger.warning("futures_decision_ledger_failed", error=str(exc)[:200])
            except Exception as exc:
                # PLAN_v6 P5: was [:80] which hid the failing column — widen so a
                # DB insert failure (blocking ALL futures opens) is diagnosable.
                logger.warning("auto_open_error", error=str(exc)[:400])

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
                        # Pemangkasan rejection_log kini pekerjaan berjadwal
                        # (jobs.prune_rejection_log) — lihat catatan di jobs.py.
            except Exception as exc:
                logger.warning("rejection_log_flush_failed", error=str(exc)[:80])

            # Ditegaskan per siklus: blok outcome di bawah hanya jalan tiap ~10
            # cycle, jadi tanpa nilai awal ini siklus lain akan menabrak NameError
            # saat memeriksanya.
            _outcomes_baru = False

            # PLAN_ADAPTIVE_LEARNING_FUTURES_10X F3: coba latih challenger.
            # Self-gating: no-op sampai ≥60 sampel 4h-matang & +50 evidence baru.
            # Model baru selalu 'shadow' — tak memengaruhi keputusan.
            #
            # TEMUAN 6 Agu 2026: pemicunya dulu HANYA `_cycle_count % 100 == 50`,
            # padahal `_cycle_count` adalah variabel di memori yang KEMBALI NOL
            # setiap backend restart. Dengan stop/start harian 07:00–19:00 plus
            # dua malam START-NIGHT gagal, scanner futures nyaris tak pernah
            # menyelesaikan 100 menit berturut-turut pada fase yang tepat —
            # akibatnya model futures tak dilatih ulang selama 91,8 jam meski
            # sudah ada 411 keputusan baru yang memenuhi syarat.
            #
            # Sisi SPOT tak pernah kena masalah ini karena dipicu dari kedatangan
            # outcome (`if outcomes_updated:`), bukan dari counter. Di bawah kini
            # sama: counter dipertahankan sebagai jaring pengaman berkala, tapi
            # kedatangan bukti baru sudah cukup untuk memicu.
            # Seluruh blok berat ini pindah ke proses terpisah saat
            # LEARNING_STANDALONE=true: melatih model atas ledger ratusan ribu
            # baris menahan event loop 94-129 detik sehingga SELURUH API berhenti
            # menjawab. Lihat [agents/learning/mode.py].
            from agents.learning.mode import LEARNING_STANDALONE
            if (_outcomes_baru or _cycle_count % 100 == 50) and not LEARNING_STANDALONE:
                try:
                    from agents.learning.futures_adaptive_model import train_and_register
                    _mres = await train_and_register()
                    if _mres.get("status") == "registered":
                        logger.info("futures_challenger_registered",
                                    version=_mres["version"],
                                    n=_mres["metrics"].get("training_n"))
                    elif _mres.get("status") not in ("insufficient_data", "no_new_evidence"):
                        logger.info("futures_challenger_train", status=_mres.get("status"))
                    # F4: walk-forward + cost-stress 1.5× (diagnostik; catat kelayakan)
                    from agents.learning.futures_walkforward import run_futures_walkforward
                    _wf = await run_futures_walkforward()
                    if _wf.get("status") == "ok":
                        logger.info("futures_walkforward",
                                    best_threshold=_wf.get("best_threshold"),
                                    test_exp=(_wf.get("test") or {}).get("expectancy_pct"),
                                    stressed_exp=(_wf.get("test_stressed_1_5x") or {}).get("expectancy_pct"),
                                    promotion_eligible=_wf.get("promotion_eligible"))
                    # F5: lifecycle otomatis (semua self-gating — no-op sampai model
                    # lolos gate offline+walkforward, lalu canary butuh ≥20 outcome).
                    from agents.learning.futures_adaptive_model import (
                        advance_lifecycle, monitor_champion_drift,
                    )
                    _lc = await advance_lifecycle()
                    if _lc.get("status") not in ("noop", "collecting", None):
                        logger.info("futures_model_lifecycle", **_lc)
                    _drift = await monitor_champion_drift()
                    if _drift.get("status") == "rolled_back":
                        logger.warning("futures_model_auto_rollback", **_drift)
                except Exception as exc:
                    logger.warning("futures_challenger_train_failed", error=str(exc)[:200])

                # M5: evaluasi canary parameter KELUAR di irama yang sama dengan
                # verifier sisi masuk. Hanya MENGEVALUASI dan membalik bila
                # memburuk — menaikkan shadow→canary tetap butuh perintah
                # eksplisit, karena itu memberlakukan perubahan ke uang sungguhan.
                try:
                    from agents.learning.exit_rollout import (
                        advance, propose_from_recommendations,
                    )
                    # Market DISEBUT: loop ini hanya mengurus canary futures.
                    # Sebelumnya `advance()` polos ikut menilai canary SPOT, jadi
                    # sisi SPOT diam-diam bergantung pada loop ini tetap hidup.
                    _adv = await advance(market="futures")
                    for _r in _adv.get("evaluated", []):
                        if _r.get("stage") in ("active", "rolled_back"):
                            logger.info("exit_rollout_decided", lane=_r.get("lane"),
                                        param=_r.get("param"), stage=_r.get("stage"))

                    # Alirkan usulan baru ke antrean. SEMUA masuk sebagai
                    # `shadow` — tak satu pun menyentuh config, jadi tak ada
                    # keputusan trading yang berubah tanpa perintah eksplisit.
                    #
                    # Tanpa panggilan ini mesin belajar menghitung angka lalu
                    # berhenti sebagai laporan: sampai 12 Agu usulan hanya lahir
                    # bila seseorang menekan endpoint API secara manual.
                    _pro = await propose_from_recommendations(market="futures")
                    for _p in _pro.get("diusulkan", []) or []:
                        if _p.get("status") == "ok":
                            logger.info("exit_rollout_proposed_auto", market="futures",
                                        lane=_p.get("lane"), param=_p.get("param"),
                                        value=_p.get("proposed_value"))
                except Exception as exc:
                    logger.warning("exit_rollout_advance_failed", error=str(exc)[:160])


        except asyncio.CancelledError:
            futures_store.set_scanning(False)
            logger.info("futures_scanner_stopped")
            _running = False
            raise
        except Exception as exc:
            futures_store.set_scanning(False)
            # str(exc) bisa KOSONG utk sejumlah exception (mis. httpx/asyncio tanpa
            # message) → error="" tak terdiagnosis. Fallback repr + simpan tipe
            # supaya penyebab selalu terbaca (Fase 4 verifikasi bebas-bug).
            _last_error = (str(exc) or repr(exc))[:160]
            logger.error("futures_scanner_error", error=_last_error,
                         exc_type=type(exc).__name__)

        elapsed   = time.time() - (_last_scan or time.time())
        sleep_for = max(30, INTERVAL_SEC - elapsed)   # min 30s gap between scans
        await asyncio.sleep(sleep_for)
