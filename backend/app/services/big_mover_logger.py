"""
Big Mover Logger — Phase 1 T4 / T4b.

Insert big_mover_log row per scan cycle. Backfill forward-pnl periodically.

B1.1: multi-horizon (1h, 4h, 24h, 7d) — bukan 24h saja.
B1.1: simpan slip-adjusted entry assumption (0.3% slippage @ ATR×1.5 SL).
"""

import asyncio
import time
from typing import Optional

import httpx
import structlog
from sqlalchemy import select, update

from app.database import AsyncSessionLocal, is_db_available
from app.models.big_mover_log import BigMoverLog
from app.services.binance_urls import fapi, spot
from app.services.slippage_sim import calculate_entry_slippage

logger = structlog.get_logger(__name__)

# B4.1: ASSUMED_SL/TP kept fixed for comparability; slippage now volume-parameterized.
ASSUMED_SL_PCT = 4.0            # ATR×1.5 typical for momentum coin
ASSUMED_TP_PCT = 12.0           # 1:3 R:R

# Backfill horizons (seconds → label)
HORIZONS = [
    (3600,    "pnl_1h_pct"),
    (4*3600,  "pnl_4h_pct"),
    (24*3600, "pnl_24h_pct"),
    (7*24*3600, "pnl_7d_pct"),
]


async def log_big_movers(
    movers: list[dict],
    *,
    market: str = "futures",
    threshold: float = 72,
) -> int:
    """Insert one row per big mover this cycle. Dedup soft-window 5 min/symbol."""
    if not is_db_available() or not movers:
        return 0

    now = time.time()
    inserted = 0

    async with AsyncSessionLocal() as s:
        # Dedup window — don't double-log the same symbol within 5 min
        recent_cutoff = now - 5 * 60
        r = await s.execute(
            select(BigMoverLog.symbol).where(
                BigMoverLog.ts >= recent_cutoff,
                BigMoverLog.market == market,
            )
        )
        recent_syms = {row[0] for row in r.fetchall()}

        for m in movers:
            sym = m.get("symbol", "")
            if not sym or sym in recent_syms:
                continue

            change_24h = float(m.get("change_24h", 0))
            matches    = m.get("matches", []) or []
            best_score = max((mt.get("score", 0) for mt in matches), default=0.0)
            status_str = m.get("status", "tidak_lolos")

            # Translate to log status
            if status_str == "lolos":
                log_status = "opened" if best_score >= threshold else "missed"
            else:
                log_status = "missed"

            # Best direction inferred from matches; fallback by change_24h sign
            direction = "LONG" if change_24h >= 0 else "SHORT"
            if matches:
                direction = matches[0].get("direction", direction)

            s.add(BigMoverLog(
                ts=now,
                symbol=sym,
                market=market,
                direction=direction,
                change_24h=round(change_24h, 2),
                scan_price=float(m.get("price", 0) or 0),
                max_score=round(float(best_score), 1),
                threshold=float(threshold),
                scoring_gap=round(float(best_score) - threshold, 1),
                funding_rate=float(m.get("funding_rate", 0)),
                status=log_status,
                reason=m.get("reason", "")[:500],
            ))
            inserted += 1

        if inserted:
            await s.commit()
    if inserted:
        logger.info("big_mover_log_inserted", count=inserted, market=market)
    return inserted


#: Berapa permintaan klines boleh terbang bersamaan saat backfill.
#:
#: Sengaja konstanta, bukan kunci `agent_config`: ini soal kesopanan terhadap API
#: Binance, bukan parameter keputusan trading. Menaruhnya di config berarti
#: mengundangnya diputar tanpa memikirkan rate limit.
#:
#: 8 dipilih konservatif — bobot API-nya sama persis dengan cara berurutan
#: (2 per baris, tak peduli kapan dikirim); yang berubah hanya lama menunggunya.
_BACKFILL_CONCURRENCY = 8


async def _ambil_klines_serentak(client: httpx.AsyncClient, rows: list) -> list:
    """Ambil klines untuk semua baris sekaligus, dibatasi semafor.

    Cara lama mengambil satu per satu di dalam `for` — 150 baris x ~300 ms =
    45 detik, dan terukur 9 Sep 2026 memang persis segitu. Docstring aslinya
    menyebutnya "trivial", dan itu benar untuk BOBOT API; yang tidak trivial
    adalah waktunya, karena `run_due()` ditunggu di dalam loop scan sehingga
    tiap detik di sini adalah detik saat agen tidak menilai harga.

    Ini justru kasus di mana konkurensi benar-benar menolong: semuanya menunggu
    jaringan, bukan CPU — jadi tak terbentur GIL seperti kerja pembelajaran yang
    terpaksa dipindah ke proses sendiri.

    `_fetch_klines_1h` sudah menelan kegagalannya sendiri dan mengembalikan [],
    jadi satu simbol bermasalah tak menggagalkan seluruh angkatan. Urutan hasil
    dijamin sama dengan urutan `rows` — pemanggilnya memasangkannya dengan `zip`.
    """
    sem = asyncio.Semaphore(_BACKFILL_CONCURRENCY)

    async def satu(row) -> list:
        async with sem:
            return await _fetch_klines_1h(client, row.symbol, row.market, row.ts)

    return list(await asyncio.gather(*(satu(r) for r in rows)))


async def _fetch_klines_1h(
    client: httpx.AsyncClient, symbol: str, market: str, start_ts: float, limit: int = 180
) -> list:
    """1h klines from start_ts forward (limit 180 covers the full 7d horizon)."""
    url = fapi("/fapi/v1/klines") if market == "futures" else spot("/api/v3/klines")
    try:
        r = await client.get(url, params={
            "symbol": symbol, "interval": "1h",
            "startTime": int(start_ts * 1000), "limit": limit,
        })
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _price_at_horizon(klines: list, ts: float, horizon_sec: int) -> Optional[float]:
    """PLAN_v15 R0a: close price of the candle containing ts+horizon — EXACT horizon,
    not "whatever the price was when backfill happened to run" (the old bug that made
    pnl_1h_pct == pnl_4h_pct on late-backfilled rows)."""
    target_ms = (ts + horizon_sec) * 1000
    best = None
    for k in klines:
        try:
            if float(k[0]) <= target_ms:
                best = k
            else:
                break
        except (IndexError, ValueError):
            continue
    if best is None:
        return None
    try:
        return float(best[4])
    except (IndexError, ValueError):
        return None


def _bracket_outcome_path(
    direction: str,
    entry: float,
    klines: list,
    ts: float,
    horizon_sec: int = 24 * 3600,
) -> tuple[Optional[str], Optional[float]]:
    """
    PLAN_v15 R0a: PATH-AWARE 1:3 bracket simulation over the first `horizon_sec`.
    Walks candles in order: SL/TP touch decides the outcome the moment it happens
    (SL wins on a shared candle — conservative). The old version only looked at the
    endpoint price, so a wick-to-TP-then-dump was recorded as sl/open.
      Entry: scan_price × (1 ± slippage)   SL: ∓ASSUMED_SL_PCT   TP: ±ASSUMED_TP_PCT
    """
    if entry <= 0 or not klines:
        return None, None

    slip = calculate_entry_slippage(0.0) / 100   # no per-row volume stored — default tier
    if direction == "LONG":
        eff = entry * (1 + slip)
        sl, tp = eff * (1 - ASSUMED_SL_PCT / 100), eff * (1 + ASSUMED_TP_PCT / 100)
    else:
        eff = entry * (1 - slip)
        sl, tp = eff * (1 + ASSUMED_SL_PCT / 100), eff * (1 - ASSUMED_TP_PCT / 100)

    end_ms     = (ts + horizon_sec) * 1000
    last_close = None
    for k in klines:
        try:
            open_ms = float(k[0])
            hi, lo, cl = float(k[2]), float(k[3]), float(k[4])
        except (IndexError, ValueError):
            continue
        if open_ms >= end_ms:
            break
        if direction == "LONG":
            if lo <= sl:
                return "sl", -ASSUMED_SL_PCT
            if hi >= tp:
                return "tp", ASSUMED_TP_PCT
        else:
            if hi >= sl:
                return "sl", -ASSUMED_SL_PCT
            if lo <= tp:
                return "tp", ASSUMED_TP_PCT
        last_close = cl

    if last_close is None:
        return None, None
    pnl = (last_close - eff) / eff * 100 if direction == "LONG" else (eff - last_close) / eff * 100
    return "open", round(pnl, 2)


async def backfill_pending(max_rows: int = 50) -> int:
    """
    Fill horizon pnl columns for rows past their horizon mark.

    PLAN_v15 R0a rewrite — three fixes over the original:
      1. EXACT horizons: prices come from 1h klines at ts+1h/4h/24h/7d, not from
         the mark price at whatever moment backfill ran.
      2. Per-horizon repick: a row first backfilled at age 1h used to keep 4h/24h
         NULL until the 7d pass — now any row with a due-but-NULL horizon qualifies.
      3. Path-aware would_be bracket: SL/TP decided by walking candles, not by
         the 24h endpoint price.
    One klines request per row (weight 2) — max_rows=150 per 20-min cycle. Bobot
    API-nya memang trivial, dan kalimat itu dulu berhenti di situ; WAKTUNYA tidak.
    Berurutan, 150 baris memakan 45 detik (terukur 9 Sep 2026) di dalam loop scan.
    Pengambilannya kini serentak — lihat `_ambil_klines_serentak`.
    """
    if not is_db_available():
        return 0

    from sqlalchemy import and_, or_

    now = time.time()
    updated = 0

    async with AsyncSessionLocal() as s:
        r = await s.execute(
            select(BigMoverLog).where(
                or_(
                    and_(BigMoverLog.pnl_1h_pct.is_(None),  BigMoverLog.ts < now - HORIZONS[0][0]),
                    and_(BigMoverLog.pnl_4h_pct.is_(None),  BigMoverLog.ts < now - HORIZONS[1][0]),
                    and_(BigMoverLog.pnl_24h_pct.is_(None), BigMoverLog.ts < now - HORIZONS[2][0]),
                    and_(BigMoverLog.pnl_7d_pct.is_(None),  BigMoverLog.ts < now - HORIZONS[3][0]),
                )
            ).order_by(BigMoverLog.ts).limit(max_rows)
        )
        rows = list(r.scalars().all())
        if not rows:
            return 0

        async with httpx.AsyncClient(timeout=15) as client:
            # Jaringan dulu, serentak; sisanya tetap berurutan seperti semula.
            semua_klines = await _ambil_klines_serentak(client, rows)

            for row, klines in zip(rows, semua_klines):
                patch: dict = {"last_backfill_at": now}
                age = now - row.ts

                if klines and row.scan_price > 0:
                    for horizon_sec, col in HORIZONS:
                        if age >= horizon_sec and getattr(row, col) is None:
                            h_price = _price_at_horizon(klines, row.ts, horizon_sec)
                            if h_price is None:
                                continue
                            if row.direction == "LONG":
                                pnl = (h_price - row.scan_price) / row.scan_price * 100
                            else:
                                pnl = (row.scan_price - h_price) / row.scan_price * 100
                            patch[col] = round(pnl, 2)

                    # Path-aware TP/SL bracket, decided over the first 24h
                    if age >= HORIZONS[2][0] and row.would_be_status is None:
                        status_h, pnl_h = _bracket_outcome_path(
                            row.direction, row.scan_price, klines, row.ts
                        )
                        if status_h:
                            patch["would_be_status"] = status_h
                        if pnl_h is not None:
                            patch["would_be_pnl_pct"] = pnl_h

                await s.execute(
                    update(BigMoverLog).where(BigMoverLog.id == row.id).values(**patch)
                )
                updated += 1
        if updated:
            await s.commit()

    if updated:
        logger.info("big_mover_log_backfilled", rows=updated)
    return updated
