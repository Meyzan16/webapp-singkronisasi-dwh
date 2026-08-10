"""Pencatat ledger keputusan KELUAR — dipakai monitor SPOT maupun FUTURES (M7).

Fungsi ini semula hidup di dalam `agents/futures/monitor.py`. Diangkat ke sini
saat MONITOR SPOT ikut mencatat, dengan alasan yang sudah terbukti mahal di
proyek ini: sisi SPOT berulang kali dibangun sebagai SALINAN lalu menyimpang
diam-diam (katalog Formulas dan tab Predictive dua-duanya sempat futures-only,
dan tak ada satu pun error yang muncul saat itu terjadi).

Satu fungsi berarti kolom yang sama, normalisasi yang sama, dan penanganan galat
yang sama untuk kedua market — penyimpangan jadi mustahil tanpa terlihat.

Aturan yang tak boleh dilanggar: **gagal mencatat TIDAK BOLEH menggagalkan
penutupan posisi.** Ledger itu bahan belajar, bukan bagian dari eksekusi.
"""

from __future__ import annotations

import time

import structlog

logger = structlog.get_logger(__name__)


async def log_exit(session, trade, meta: dict, *, market: str, lane: str,
                   close_reason: str, status: str,
                   pnl_net: float, pnl_dollar: float | None) -> None:
    """Catat satu keputusan keluar ke `exit_events`.

    Jarak dinormalkan ke kelipatan ATR supaya lintas-koin sebanding — koin
    ber-ATR 6% dan 1% tak bisa dibandingkan dalam persen mentah. Bila `atr_pct`
    tak tersedia (posisi lama sebelum ATR ikut disimpan), kolom ber-ATR dibiarkan
    KOSONG alih-alih diisi angka yang seolah-olah sebanding.
    """
    try:
        from app.models.futures_exit_event import ExitEvent

        entry = float(trade.entry_price or 0.0)
        atr_pct = float(meta.get("atr_pct") or 0.0)
        peak = float(meta.get("peak_pnl_pct") or 0.0)    # gerak favorable terjauh (%)
        trough = float(meta.get("trough_pnl_pct") or 0.0)  # gerak adverse terjauh (%)

        def _atr_units(pct_move: float | None) -> float | None:
            if pct_move is None or not atr_pct:
                return None
            return round(pct_move / atr_pct, 4)

        tp_dist = (abs(float(trade.take_profit) - entry) / entry * 100
                   if (entry and trade.take_profit) else None)
        sl_dist = (abs(entry - float(trade.stop_loss)) / entry * 100
                   if (entry and trade.stop_loss) else None)
        from agents.shared import trail_tracker
        _retrace, _ext = trail_tracker.fractions(meta)

        entry_at = float(trade.entry_at or 0.0)
        closed_at = float(trade.closed_at or time.time())

        session.add(ExitEvent(
            market=market,
            trade_id=trade.id, symbol=trade.symbol, agent=trade.style,
            lane=lane or "",
            # SPOT tak punya arah — selalu beli. Diisi "LONG" supaya query lintas
            # market tak perlu memperlakukan spot sebagai kasus khusus.
            direction=getattr(trade, "direction", None) or "LONG",
            regime=trade.regime,
            close_reason=close_reason, status=status,
            entry_at=entry_at, closed_at=closed_at,
            held_hours=round(max(0.0, (closed_at - entry_at) / 3600.0), 3),
            pnl_pct=round(float(pnl_net), 4), pnl_dollar=pnl_dollar,
            atr_pct=atr_pct or None,
            mfe_atr=_atr_units(peak) if peak else None,
            # Disimpan sebagai nilai POSITIF supaya sebanding langsung dengan
            # sl_dist_atr ("berapa jauh harga sempat melawan").
            mae_atr=_atr_units(abs(trough)) if trough else None,
            tp_dist_atr=_atr_units(tp_dist),
            sl_dist_atr=_atr_units(sl_dist),
            realized_atr=_atr_units(float(pnl_net)),
            tp_compressed=bool(meta.get("tp_compressed")),
            trail_active=bool(getattr(trade, "trail_active", False)),
            # M8: bukti trailing. Keduanya `None` untuk posisi yang tak pernah
            # menyentuh TP1 — di sana kedua parameter memang tak pernah berlaku,
            # jadi memasukkannya ke sampel akan mengencerkan buktinya.
            retrace_after_tp1_frac=_retrace,
            ext_after_tp1_frac=_ext,
            tp1_gain_pct=(float(meta["tp1_gain_pct"])
                          if meta.get("tp1_gain_pct") else None),
            leverage=getattr(trade, "leverage", None),
            score=meta.get("score") or meta.get("raw_score"),
        ))
    except Exception as exc:
        logger.warning("exit_event_log_failed", market=market,
                       symbol=getattr(trade, "symbol", "?"), error=str(exc)[:120])
