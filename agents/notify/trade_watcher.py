"""Notifier LIVE — pantau paper_trades, kirim Telegram saat posisi dibuka/ditutup.

Zero-touch terhadap logika trading: hanya MEMBACA tabel ``paper_trades`` tiap
~30 detik dan mendeteksi baris baru (open) & baris yang baru punya ``closed_at``
(close). Watermark diinisialisasi ke kondisi DB saat notifier start, jadi histori
lama TIDAK di-blast — hanya event setelah notifier hidup yang dikirim.

Dijalankan sebagai task asyncio dari lifespan backend (lihat backend/app/main.py).
"""

from __future__ import annotations

import asyncio
import time

import structlog

from agents.notify.telegram import notifier_enabled, send_telegram

logger = structlog.get_logger(__name__)

POLL_SEC = 30            # jeda antar cek (keputusan owner: ~30 dtk)
_MAX_DETAIL = 6          # >N event dalam 1 poll → dirangkum jadi 1 pesan
_IDLE_RESLEEP = 60       # kalau DB down / notifier disabled, cek ulang tiap 60 dtk

# ── State internal (in-memory) ───────────────────────────────────────────────────
_running = False
_last_error: str | None = None
_last_open_id: int = 0          # id paper_trade terakhir yang sudah diberitahu (open)
_last_close_ts: float = 0.0     # closed_at terakhir yang sudah diberitahu (close)


def get_state() -> dict:
    """Status untuk /health — sejajar dgn agent lain."""
    return {
        "running": _running,
        "last_error": _last_error,
        "last_open_id": _last_open_id,
        "last_close_ts": _last_close_ts,
    }


# ── Pemformatan pesan ────────────────────────────────────────────────────────────

def _pretty_style(style: str) -> str:
    """`futures_agent_bigmover` → `Futures · BigMover`, dst. Ringkas & terbaca."""
    s = style or "?"
    market = "Futures" if s.startswith("futures") else "Spot"
    tail = s.replace("futures_agent_", "").replace("futures_", "")
    tail = tail.replace("agent_", "").replace("_", " ").strip()
    # kapitalisasi ringan
    label = {
        "bigmover": "BigMover", "agent1": "Agent1", "agent2": "Agent2",
        "agent3": "Agent3",
    }.get(tail, tail.title() if tail else market)
    return f"{market} · {label}"


def _fmt_price(v) -> str:
    if v is None:
        return "-"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if v >= 1000:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:.4f}"
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _open_line(t) -> str:
    arrow = "🔺" if (t.direction or "").upper() == "LONG" else "🔻"
    lev = f" · {int(t.leverage)}x" if t.leverage else ""
    regime = f" · {t.regime}" if t.regime else ""
    return (
        f"🟢 OPEN {t.symbol} {arrow}{t.direction} — {_pretty_style(t.style)}{lev}{regime}\n"
        f"   entry {_fmt_price(t.entry_price)} · SL {_fmt_price(t.stop_loss)} · "
        f"TP {_fmt_price(t.take_profit)} · RR {t.risk_reward}"
    )


def _close_line(t) -> str:
    icon = "✅" if t.status == "tp" else ("❌" if t.status == "sl" else "⚪")
    tag = {"tp": "TP", "sl": "SL"}.get(t.status, (t.status or "CLOSE").upper())
    pnl_pct = f"{t.pnl_pct:+.2f}%" if t.pnl_pct is not None else "-"
    pnl_usd = f" ({t.pnl_dollar:+.2f}$)" if t.pnl_dollar is not None else ""
    return (
        f"{icon} {tag} {t.symbol} {t.direction} — {_pretty_style(t.style)}\n"
        f"   PnL {pnl_pct}{pnl_usd} · close {_fmt_price(t.close_price)}"
    )


# ── Poll DB ──────────────────────────────────────────────────────────────────────

async def _init_watermarks() -> None:
    """Set watermark ke kondisi DB SEKARANG supaya histori lama tak di-blast."""
    global _last_open_id, _last_close_ts
    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models.paper_trade import PaperTrade

    async with AsyncSessionLocal() as s:
        max_id = (await s.execute(select(func.max(PaperTrade.id)))).scalar()
        max_close = (
            await s.execute(select(func.max(PaperTrade.closed_at)))
        ).scalar()
    _last_open_id = int(max_id or 0)
    _last_close_ts = float(max_close or 0.0)


async def _poll_once() -> None:
    """Satu putaran: kirim notif utk open & close baru sejak watermark terakhir."""
    global _last_open_id, _last_close_ts
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.paper_trade import PaperTrade

    async with AsyncSessionLocal() as s:
        opens = (
            await s.execute(
                select(PaperTrade)
                .where(PaperTrade.id > _last_open_id)
                .order_by(PaperTrade.id.asc())
            )
        ).scalars().all()

        closes = (
            await s.execute(
                select(PaperTrade)
                .where(
                    PaperTrade.closed_at.is_not(None),
                    PaperTrade.closed_at > _last_close_ts,
                    PaperTrade.status != "open",
                )
                .order_by(PaperTrade.closed_at.asc())
            )
        ).scalars().all()

    # Kirim OPEN
    if opens:
        if len(opens) > _MAX_DETAIL:
            longs = sum(1 for t in opens if (t.direction or "").upper() == "LONG")
            await send_telegram(
                f"🟢 {len(opens)} posisi baru dibuka "
                f"({longs} LONG / {len(opens) - longs} SHORT)."
            )
        else:
            await send_telegram("\n\n".join(_open_line(t) for t in opens))
        _last_open_id = max(t.id for t in opens)

    # Kirim CLOSE
    if closes:
        if len(closes) > _MAX_DETAIL:
            tp = sum(1 for t in closes if t.status == "tp")
            sl = sum(1 for t in closes if t.status == "sl")
            pnl = sum(t.pnl_dollar or 0.0 for t in closes)
            await send_telegram(
                f"🔔 {len(closes)} posisi ditutup — ✅{tp} TP / ❌{sl} SL · "
                f"net {pnl:+.2f}$."
            )
        else:
            await send_telegram("\n\n".join(_close_line(t) for t in closes))
        _last_close_ts = max(t.closed_at for t in closes)


# ── Loop utama ───────────────────────────────────────────────────────────────────

async def run_notifier_loop() -> None:
    """Task asyncio: notifikasi Telegram open/close posisi (spot + futures)."""
    global _running, _last_error

    if not notifier_enabled():
        logger.info("notifier_disabled_no_config")
        # tetap hidup & cek berkala — kalau owner mengisi config nanti, aktif sendiri
        while not notifier_enabled():
            await asyncio.sleep(_IDLE_RESLEEP)

    from app.database import is_db_available

    # Tunggu DB siap sebelum set watermark
    while not is_db_available():
        await asyncio.sleep(5)

    try:
        await _init_watermarks()
    except Exception as exc:  # noqa: BLE001
        logger.warning("notifier_init_failed", error=str(exc)[:160])

    _running = True
    await send_telegram(
        "🚀 Notifier hidup — akan mengabari tiap posisi DIBUKA & DITUTUP "
        "(spot + futures)."
    )
    logger.info("notifier_started", open_id=_last_open_id, close_ts=_last_close_ts)

    while True:
        try:
            if is_db_available():
                await _poll_once()
                _last_error = None
        except asyncio.CancelledError:
            _running = False
            logger.info("notifier_stopped")
            raise
        except Exception as exc:  # noqa: BLE001 — jangan pernah jatuhkan task
            _last_error = str(exc)[:160]
            logger.warning("notifier_poll_error", error=_last_error)
        await asyncio.sleep(POLL_SEC)
