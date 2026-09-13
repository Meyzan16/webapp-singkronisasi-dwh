"""
Futures Monitor — jalur agen tunggal saja.

Dua loop di atas satu himpunan posisi:
  * loop utama (120 dtk): harga → `_monitor_agentic` → aturan keluar `exit_rules`
    (SL dulu, lalu TP parsial, trailing, breakeven, time-stop), heartbeat per
    posisi, sinkron dompet.
  * jalur cepat (30 dtk): SEMUA posisi agen aktif dengan aturan yang sama —
    terukur 12-13 Sep 2026 tujuh dari 23 penutupan menembus SL >1% pada jeda
    120 detik.
  * rekonsiliasi offline: posisi yang tak berdenyut >15 menit diputar ulang
    dari lilin 15m — hanya persilangan SL (parsial/trailing tak disimulasikan).

Jalur lane lama (agent1/2/3/bigmover: liq-guard, TP extension, rotasi,
fail-fast, rug-pull, funding-window, stagnant-48h, ~1.300 baris) DIHAPUS
13 Sep 2026 — nol posisi lane lama terbuka, dan tak ada yang akan membukanya.
Aturan keluar agen tunggal ada di `exit_rules.py` (murni, teruji dengan angka);
berkas ini hanya menerjemahkan keputusan itu ke perubahan baris DB.
"""

import asyncio
import json
import time
from decimal import Decimal
from typing import Optional

import httpx
import structlog
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_balance import PaperBalance
from app.models.paper_trade import PaperTrade
from app.services.binance_urls import fapi
from app.services.trading_costs import (
    FUTURES_STARTING_BALANCE,
    FUTURES_BALANCE_STATUSES,
    FUTURES_SL_SLIPPAGE_PCT,                      # PLAN_v16 F1: stop-market fill slippage
)
from agents.shared import trail_tracker

logger = structlog.get_logger(__name__)

INTERVAL_SEC  = 120   # every 2 minutes
STARTUP_DELAY = 60    # start after main scanner

# Futures taker fee: 0.05% per side = 0.10% round trip
TAKER_FEE     = 0.0005   # 0.05% per side
ROUND_TRIP    = TAKER_FEE * 2  # 0.10% total

# ── PLAN_v16 F1/F3 — true-cost accounting & anti-churn exits ──────────────────
# Diagnosa: 77% close = churn scratch/breakeven yang bayar RT fee $0.28-0.30 untuk
# bank ≈$0, sementara paper tidak memotong slippage & funding (lebih murah dari live).
# Close-reasons yang eksekusinya stop-MARKET (kena FUTURES_SL_SLIPPAGE_PCT ekstra):
_STOP_MARKET_REASONS = {
    "sl_hit", "sl_hit_fast_loop",
    "max_margin_loss", "max_margin_loss_fast_loop",
    "liq_guard", "fail_fast",
    "flash_dump_exit", "flash_pump_exit",
    "offline_reconcile_sl",
    "emergency_close_circuit_breaker",
}


def _true_close_costs(meta: dict, close_reason: str) -> tuple[float, float]:
    """PLAN_v16 F1 — biaya live yang selama ini tak dipotong dari pnl paper.
    Returns (extra_cost_pct, funding_dollar):
      extra_cost_pct = entry slippage (market entry, dari slippage_sim vol-tier)
                       + SL-fill slippage utk close bertipe stop-market;
      funding_dollar = akumulasi funding G6 (cumulative_funding_paid) — dipotong $ di close.
    Fee RT 0.10% TIDAK di sini (sudah lama dipotong sebagai ROUND_TRIP)."""
    slip_entry = float(meta.get("entry_slippage_pct") or 0.0)
    slip_sl    = FUTURES_SL_SLIPPAGE_PCT if close_reason in _STOP_MARKET_REASONS else 0.0
    funding    = float(meta.get("cumulative_funding_paid") or 0.0)
    return slip_entry + slip_sl, funding


def _cost_floor_pct(meta: dict) -> float:
    """PLAN_v16 F2/F3 — biaya round-trip total (%) satu trade. Prefer nilai yang
    dihitung auto_trader saat open; fallback utk row lama: fee RT + 2× slippage."""
    cf = float(meta.get("cost_floor_pct") or 0.0)
    if cf <= 0:
        cf = ROUND_TRIP * 100 + 2 * float(meta.get("entry_slippage_pct") or 0.1)
    return cf


_running     = False
_cycle_count = 0
_last_check: Optional[float] = None
_last_error: Optional[str]   = None
_closed_today      = 0
_today: Optional[str] = None  # F61: track date for daily closed_today reset

# Himpunan posisi agen aktif yang terakhir dilihat jalur cepat — dicatat ke log
# hanya saat berubah, supaya ada bukti jalur ini hidup tanpa banjir log.
_fast_loop_agentic_seen: frozenset[int] = frozenset()
FAST_INTERVAL_SEC = 30

# EC5: server-time drift check
NTP_CHECK_INTERVAL_SEC = 1800   # every 30 min
_last_ntp_check: float = 0.0

def _semua_gaya_futures() -> tuple[str, ...]:
    """Gaya yang DIAWASI monitor — dari registry, termasuk agen aktif.

    Terukur 9 Sep 2026, dan ini kegagalan paling berbahaya yang ditemukan
    sepanjang penulisan ulang FUTURES: daftar ini dipaku empat gaya lama, dan
    query monitor menyaring dengan daftar itu. Posisi `futures_agentic` karena
    itu TIDAK PERNAH masuk loop — `agentic_trades` selalu kosong dan
    `_monitor_agentic` tak pernah dipanggil satu kali pun.
    Tiga posisi nyata berjalan tanpa pengecekan SL, TP, trailing, maupun
    time-stop. Tak ada error, tak ada log, tak ada satu pun tanda: monitor
    melaporkan dirinya "aktif" karena loopnya memang berputar — hanya saja
    daftar yang diawasinya tak memuat posisi yang sedang hidup.

    Diturunkan dari registry supaya agen aktif berikutnya ikut terawasi tanpa
    ada yang perlu mengingat menyunting baris ini.
    """
    try:
        from app.services.agent_registry import FUTURES_AGENTS
        return tuple(FUTURES_AGENTS)
    except Exception:      # noqa: BLE001 — monitor tak boleh mati karena impor
        return ("futures_agent1", "futures_agent2", "futures_agent3",
                "futures_agent_bigmover", "futures_agentic")


_FUTURES_STYLES = _semua_gaya_futures()


def get_state() -> dict:
    return {
        "running":         _running,
        "cycle_count":     _cycle_count,
        "last_check":      _last_check,
        "last_error":      _last_error,
        "closed_today":    _closed_today,
    }


# ── PLAN_v2 P1.4 — per-trade event log helper ─────────────────────────────────

_EVENT_LOG_CAP = 30


#: Gaya trade yang dikelola aturan keluar BARU (Fase 4). Diturunkan dari
#: registry supaya agen aktif berikutnya ikut otomatis, bukan lewat daftar
#: tangan yang bisa ketinggalan.
def _agentic_styles() -> tuple[str, ...]:
    try:
        from app.services.agent_registry import ACTIVE_FUTURES_AGENTS
        return tuple(ACTIVE_FUTURES_AGENTS)
    except Exception:
        return ("futures_agentic",)


_AGENTIC_STYLES = _agentic_styles()


async def _monitor_agentic(session, trades: list, prices: dict,
                           wicks: dict | None = None) -> tuple[int, int]:
    """Kelola posisi agen tunggal dengan `exit_rules` — enam mekanisme, SL dulu.

    Sengaja TIPIS: seluruh keputusan ada di `exit_rules.evaluate` yang murni dan
    bisa diuji dengan angka. Fungsi ini hanya menerjemahkan keputusan itu jadi
    perubahan baris DB. Pembagian ini yang membuat aturan keluar bisa diputar
    ulang atas ledger historis sebelum mengelola satu pun posisi nyata.

    `wicks`: {symbol: (low, high)} ekstrem lilin 1m sejak tick terakhir. SL dan
    TP dinilai dari sumbu, bukan harga sesaat — stop order nyata terisi di
    sumbu. Sampai 13 Sep 2026 `ExitState.low/high` (B2) tak pernah diisi
    jalur ini: PONSUSDT SHORT bertahan di paper melewati sumbu 0,5630 ≥ SL
    0,5627 yang di live pasti menutupnya.
    """
    wicks = wicks or {}
    if not trades:
        return 0, 0

    from agents.futures import exit_config as _ecfg
    from agents.futures import exit_rules as _er

    await _ecfg.refresh()
    params = _er.params_from_config()
    closed = updated = 0

    for trade in trades:
        price = prices.get(trade.symbol)
        if price is None:
            continue
        # Dua loop (utama 120 dtk, cepat 30 dtk) mengelola baris yang sama dari
        # sesi berbeda. Muat ulang dulu supaya keputusan dibuat atas keadaan
        # terkini — bukan menutup dua kali posisi yang baru saja ditutup loop
        # lain, dengan angka yang berbeda.
        await session.refresh(trade)
        if trade.status != "open":
            continue
        try:
            meta = json.loads(trade.signals_json or "{}")
        except (TypeError, ValueError):
            meta = {}

        entry = float(trade.entry_price or 0.0)
        if entry <= 0:
            continue
        sl = float(trade.trail_sl or trade.stop_loss or 0.0)
        direction = trade.direction or "LONG"

        pnl_now = ((price - entry) if direction == "LONG" else (entry - price)) / entry * 100
        peak = max(float(meta.get("peak_pnl_pct", 0.0)), pnl_now)
        if peak != meta.get("peak_pnl_pct"):
            meta["peak_pnl_pct"] = round(peak, 3)
        # Gerak MELAWAN terjauh (MAE) → kolom `mae_atr` di ledger keluar — satu-
        # satunya bahan usulan lebar SL. Sampai 13 Sep 2026 hanya loop lama yang
        # mencatatnya; setiap exit agen tunggal masuk ledger dengan MAE kosong.
        trough = min(float(meta.get("trough_pnl_pct", 0.0)), pnl_now)
        if trough != meta.get("trough_pnl_pct"):
            meta["trough_pnl_pct"] = round(trough, 3)
        # Gerak dua arah SESUDAH TP1 (kolom fav_min/max di ledger) — bahan
        # pembanding perilaku trailing. Idempoten bila belum TP1.
        if meta.get("tp1_partial_done"):
            trail_tracker.arm_tp1(meta, entry=entry, tp1=float(meta.get("tp1") or 0.0),
                                  tp2=meta.get("tp2"), direction=direction)
            trail_tracker.track(meta, price)

        w_low, w_high = wicks.get(trade.symbol, (None, None))
        state = _er.ExitState(
            direction=direction,
            entry=entry,
            price=price,
            sl=sl,
            low=w_low,
            high=w_high,
            atr_pct=float(meta.get("atr_pct") or 0.0),
            cost_pct=_cost_floor_pct(meta),
            risk_pct=float(meta.get("risk_pct") or 0.0),
            hold_minutes=(time.time() - float(trade.entry_at or time.time())) / 60,
            peak_pnl_pct=peak,
            tp1_done=bool(meta.get("tp1_partial_done")),
            tp2_done=bool(meta.get("tp2_partial_done")),
            trail_active=bool(trade.trail_active),
        )

        keputusan = _er.evaluate(state, params)

        # Baris lama bisa punya `setup_type` kosong (sebelum penulisan saat
        # dibuat). Tambal di sini juga supaya pengelompokan per-lane di
        # `risk_gate` tak melewatkannya diam-diam.
        if not trade.setup_type:
            trade.setup_type = str(meta.get("setup_type") or "agentic")

        # Denyut per posisi. Sampai 13 Sep 2026 hanya loop lama yang menulisnya,
        # jadi posisi agen tunggal tak pernah punya `last_tick_at` — dan
        # `reconcile_offline_positions` menganggapnya tak terpantau SEJAK ENTRY:
        # tiap restart ia memutar ulang seluruh riwayat lilin terhadap SL yang
        # SEKARANG (sudah dinaikkan trailing), lalu menutup posisi sehat sebagai
        # `offline_reconcile_sl`. Tujuh dari 13 penutupan dini berasal dari sana.
        trade.last_tick_at      = time.time()
        trade.last_tick_price   = round(price, 8)
        trade.last_tick_pnl_pct = round(pnl_now, 3)
        trade.last_tick_event   = keputusan.reason if keputusan.action != "hold" else "tick"

        if keputusan.action == "hold":
            trade.signals_json = json.dumps(meta, ensure_ascii=False)
            continue

        if keputusan.action == "move_sl" and keputusan.new_sl:
            trade.trail_sl = round(keputusan.new_sl, 8)
            trade.trail_active = True
            meta["sl_moved_at"] = time.time()   # sumbu SEBELUM ini tak boleh menilai SL baru
            _append_trade_event(meta, keputusan.reason, {
                "new_sl": trade.trail_sl, "note": keputusan.note})
            trade.signals_json = json.dumps(meta, ensure_ascii=False)
            updated += 1
            logger.info("agentic_sl_moved", symbol=trade.symbol,
                        reason=keputusan.reason, new_sl=trade.trail_sl,
                        note=keputusan.note)
            continue

        if keputusan.action == "partial":
            # Parsial: bank sebagian, kecilkan notional sisanya, majukan SL.
            frac = max(0.0, min(1.0, keputusan.close_frac))
            harga_tp = float(keputusan.close_price or price)
            kotor = ((harga_tp - entry) if direction == "LONG"
                     else (entry - harga_tp)) / entry * 100
            # Fee dipotong PENUH untuk fraksi yang dijual (masuk + keluar) —
            # perbaikan B6: jalur lama hanya memotong separuh, sehingga fee
            # masuk untuk fraksi itu tak pernah terbayar.
            bersih = kotor - ROUND_TRIP * 100
            notional = float(trade.position_size or 0.0)
            dibank = round(bersih / 100 * notional * frac, 2)

            kunci = "tp1_partial_done" if keputusan.reason == _er.TP1_HIT else "tp2_partial_done"
            meta[kunci] = True
            meta[f"{kunci}_pnl_dollar"] = dibank
            trade.pnl_dollar = (trade.pnl_dollar or 0.0) + dibank
            trade.position_size = round(notional * (1 - frac), 2)
            if keputusan.new_sl:
                trade.trail_sl = round(keputusan.new_sl, 8)
                trade.trail_active = True
                meta["sl_moved_at"] = time.time()
            _append_trade_event(meta, keputusan.reason, {
                "frac": frac, "banked_dollar": dibank, "note": keputusan.note})
            trade.signals_json = json.dumps(meta, ensure_ascii=False)
            updated += 1
            logger.info("agentic_partial", symbol=trade.symbol,
                        reason=keputusan.reason, frac=frac, banked=dibank)
            continue

        # action == "close"
        harga_tutup = float(keputusan.close_price or price)
        kotor = ((harga_tutup - entry) if direction == "LONG"
                 else (entry - harga_tutup)) / entry * 100
        extra, funding = _true_close_costs(meta, keputusan.reason)
        bersih = kotor - ROUND_TRIP * 100 - extra
        notional = float(trade.position_size or 0.0)
        total = round((trade.pnl_dollar or 0.0) + bersih / 100 * notional - funding, 2)

        meta["close_reason"] = keputusan.reason
        meta["pnl_gross_pct"] = round(kotor, 3)
        meta["fee_pct"] = round(ROUND_TRIP * 100, 3)
        meta["cost_slippage_pct"] = round(extra, 4)
        meta["cost_funding_dollar"] = round(funding, 4)

        # Fase 4: seberapa jauh fill melewati SL yang direncanakan. Tanpa angka
        # ini, rugi 2,16x risiko hanya bisa ditemukan lewat forensik manual.
        if keputusan.note.startswith("sl_breach_pct="):
            try:
                trade.sl_breach_pct = round(float(keputusan.note.split("=", 1)[1]), 4)
            except ValueError:
                pass

        trade.status = "tp" if keputusan.reason in (_er.TP1_HIT, _er.TP2_HIT) else "sl"
        trade.close_price = round(harga_tutup, 8)
        trade.closed_at = time.time()
        trade.pnl_pct = round(bersih, 2)
        trade.pnl_dollar = total
        trade.signals_json = json.dumps(meta, ensure_ascii=False)

        # B3: ledger ditulis di transaksi yang SAMA dengan penutupan.
        await _log_exit_event(session, trade, meta, lane=str(meta.get("setup_type") or "agentic"),
                              close_reason=keputusan.reason, status=trade.status,
                              pnl_net=bersih, pnl_dollar=total)
        closed += 1
        logger.info("agentic_closed", symbol=trade.symbol, reason=keputusan.reason,
                    pnl_pct=round(bersih, 2), pnl_dollar=total, note=keputusan.note)

    return closed, updated


async def _log_exit_event(session, trade, meta: dict, *, lane: str, close_reason: str,
                          status: str, pnl_net: float, pnl_dollar: float) -> None:
    """Catat satu keputusan KELUAR. M7: implementasinya bersama dengan monitor
    SPOT (`agents/shared/exit_ledger.py`) supaya kedua market mustahil menyimpang
    diam-diam. Pembungkus tipis ini dipertahankan agar pemanggil tak berubah."""
    from agents.shared.exit_ledger import log_exit

    await log_exit(session, trade, meta, market="futures", lane=lane,
                   close_reason=close_reason, status=status,
                   pnl_net=pnl_net, pnl_dollar=pnl_dollar)


def _append_trade_event(meta: dict, kind: str, payload: dict | None = None) -> None:
    """Append an event to signals_json.events[] (FIFO-capped). Used by monitor to
    build a per-trade timeline visible from the UI."""
    events = meta.get("events")
    if not isinstance(events, list):
        events = []
    entry = {"ts": time.time(), "kind": kind}
    if payload:
        entry.update(payload)
    events.append(entry)
    if len(events) > _EVENT_LOG_CAP:
        events = events[-_EVENT_LOG_CAP:]
    meta["events"] = events


# ── Price fetcher ─────────────────────────────────────────────────────────────

async def _fetch_futures_prices(symbols: list[str]) -> dict[str, float]:
    """Fetch futures mark prices — batch endpoint to minimize weight usage."""
    if not symbols:
        return {}
    import json as _json
    prices: dict[str, float] = {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Batch: /fapi/v1/ticker/price?symbols=[...] — weight=2 for all
            syms_param = _json.dumps(symbols, separators=(",", ":"))  # BUG-L25: compact (Binance rejects spaces)
            r = await client.get(
                fapi("/fapi/v1/ticker/price"),
                params={"symbols": syms_param},
            )
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        prices[item["symbol"]] = float(item["price"])
                    return prices
            # Fallback: semaphore-limited individual requests
            _sem = asyncio.Semaphore(10)
            async def _fetch_one(sym: str) -> None:
                async with _sem:
                    try:
                        resp = await client.get(fapi(f"/fapi/v1/ticker/price?symbol={sym}"))
                        if resp.status_code == 200:
                            prices[sym] = float(resp.json()["price"])
                    except Exception:
                        pass
            await asyncio.gather(*[_fetch_one(s) for s in symbols])
    except Exception:
        pass
    return prices


async def _fetch_wicks(since: dict[str, float], candles: int = 3) -> dict[str, tuple[float, float]]:
    """Ekstrem (low, high) lilin 1m per simbol — HANYA lilin yang dibuka pada
    atau sesudah `since[symbol]`.

    Batas waktu itu bukan hiasan. IOTXUSDT 13 Sep 2026: SL dinaikkan ke
    breakeven 13:39:16, loop utama 13:39:30 membaca low tiga lilin terakhir —
    termasuk menit-menit SEBELUM SL naik — dan menutup posisi dengan
    "breach 2,03%" yang tak pernah terjadi terhadap SL baru. Sumbu yang sah
    hanya yang terbentuk sejak tick terakhir DAN sejak SL terakhir dipindah.
    Lilin yang dibuka sebelum batas dibuang seluruhnya (ekstrem sebagiannya
    tak bisa dipilah). Fail-open: simbol tanpa lilin sah → dinilai dari harga.
    """
    out: dict[str, tuple[float, float]] = {}
    if not since:
        return out
    sem = asyncio.Semaphore(6)

    async def _satu(client: httpx.AsyncClient, sym: str, batas: float) -> None:
        async with sem:
            try:
                r = await client.get(fapi("/fapi/v1/klines"),
                                     params={"symbol": sym, "interval": "1m", "limit": candles})
                if r.status_code != 200:
                    return
                ks = [k for k in r.json() if float(k[0]) / 1000 >= batas]
                if not ks:
                    return
                out[sym] = (min(float(k[3]) for k in ks), max(float(k[2]) for k in ks))
            except Exception:
                pass

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await asyncio.gather(*[_satu(client, sym, b) for sym, b in since.items()])
    except Exception:
        pass
    return out


async def _check_server_time_drift() -> None:
    """EC5: Warn if this server's clock drifts >5s from Binance serverTime.

    Funding windows are calculated with server time; a drift of >5s can cause
    the G9 funding-window exit to fire at the wrong moment.  Runs at most every
    30 min so the overhead is negligible.
    """
    global _last_ntp_check
    now = time.time()
    if now - _last_ntp_check < NTP_CHECK_INTERVAL_SEC:
        return
    _last_ntp_check = now
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(fapi("/fapi/v1/time"))
            if r.status_code == 200:
                binance_ms = r.json().get("serverTime", 0)
                drift = abs(time.time() - binance_ms / 1000)
                if drift > 5.0:
                    logger.warning("server_time_drift",
                                   drift_sec=round(drift, 2),
                                   msg="funding window timing may be off — check NTP")
                else:
                    logger.debug("server_time_ok", drift_sec=round(drift, 3))
    except Exception:
        pass  # non-critical — skip silently


# ── Balance sync ──────────────────────────────────────────────────────────────

async def _update_futures_balance() -> None:
    """
    Phase 9: recompute the SINGLE `futures` wallet (both agents share it).
    balance = initial + deposited − withdrawn + Σ pnl_dollar (tp/sl only, F15/F33).
    Mirrors the spot pattern (agents/opportunity/monitor.py::_update_paper_balance) —
    deposits/withdrawals are preserved, so "deposit and the agent works" holds.
    """
    if not is_db_available():
        return

    # Saldo dompet DITURUNKAN dari trade, tidak disimpan — jadi ia harus
    # menghormati epoch risiko yang sama dengan gerbang.
    #
    # Terukur 9 Sep 2026: reset dompet ditulis ke DB, lalu fungsi ini menjumlahkan
    # SELURUH riwayat dan mengembalikannya ke angka lama 18 detik kemudian.
    # Resetnya tak "gagal" — ia dibatalkan diam-diam, dan satu-satunya jejak yang
    # tersisa adalah kolom `notes` yang tak ikut dihitung ulang.
    #
    # Tanpa ini ada dua kebenaran sekaligus: gerbang menilai dari basis pasca-epoch
    # sementara penentuan ukuran memakai saldo pra-epoch. Keduanya masuk akal
    # sendiri-sendiri, dan justru itu yang membuat selisihnya sulit terlihat.
    from agents.futures.risk_gate import _risk_epoch_ts

    epoch = await _risk_epoch_ts()

    async with AsyncSessionLocal() as session:
        syarat = [
            PaperTrade.style.in_(list(_FUTURES_STYLES)),
            PaperTrade.status.in_(list(FUTURES_BALANCE_STATUSES)),   # BUG-L19: include expired
            PaperTrade.pnl_dollar.isnot(None),
        ]
        if epoch > 0:
            syarat.append(PaperTrade.closed_at >= epoch)
        total = (await session.execute(
            select(func.coalesce(func.sum(PaperTrade.pnl_dollar), 0.0)).where(*syarat)
        )).scalar() or 0.0

        bal = (await session.execute(
            select(PaperBalance).where(PaperBalance.style == "futures")
        )).scalar_one_or_none()
        now = time.time()
        if bal is None:
            bal = PaperBalance(
                style           = "futures",
                balance         = round(FUTURES_STARTING_BALANCE + total, 2),
                initial_balance = FUTURES_STARTING_BALANCE,
                deposited_total = 0.0,
                withdrawn_total = 0.0,
                realized_pnl    = round(total, 2),
                updated_at      = now,
                created_at      = now,
            )
            session.add(bal)
        else:
            bal.balance = round(
                bal.initial_balance + bal.deposited_total - bal.withdrawn_total + total, 2
            )
            bal.realized_pnl = round(total, 2)
            bal.updated_at   = now
        await session.commit()
        logger.info("futures_balance_synced", balance=bal.balance, realized_pnl=bal.realized_pnl)


# ── Main check ────────────────────────────────────────────────────────────────

async def check_futures_positions() -> tuple[int, int]:
    """Satu siklus atas seluruh posisi terbuka agen aktif. Returns (closed, updated)."""
    if not is_db_available():
        return 0, 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(list(_AGENTIC_STYLES)),
                PaperTrade.status == "open",
            )
        )
        trades = list(result.scalars().all())
        if not trades:
            return 0, 0

        # EC2: stale price guard — if fetch takes >30s (network stall / retry loop),
        # the prices could already be stale by the time we use them.  Skip the cycle
        # rather than fire a false SL/TP close on stale data.
        _pf_start = time.time()
        prices    = await _fetch_futures_prices(list({t.symbol for t in trades}))
        if time.time() - _pf_start > 30.0:
            logger.warning("monitor_stale_price_skipped",
                           age_sec=round(time.time() - _pf_start, 1),
                           msg="price fetch took >30s — skipping cycle")
            return 0, 0

        # Sumbu lilin 1m sejak tick terakhir / SL terakhir dipindah: SL/TP
        # dinilai dari ekstrem, bukan harga sesaat. Hanya loop utama yang
        # mengambilnya (1 request/posisi/2 mnt); jalur cepat memakai harga saja.
        since: dict[str, float] = {}
        for t in trades:
            try:
                _m = json.loads(t.signals_json or "{}")
            except (TypeError, ValueError):
                _m = {}
            batas = max(float(t.last_tick_at or 0.0), float(_m.get("sl_moved_at") or 0.0))
            since[t.symbol] = max(since.get(t.symbol, 0.0), batas)
        wicks = await _fetch_wicks(since)
        closed, updated = await _monitor_agentic(session, trades, prices, wicks)
        # Commit selalu: keputusan `hold` pun menulis `peak_pnl_pct` (bahan
        # trailing DAN kolom mfe_atr di ledger) serta denyut per posisi.
        await session.commit()

    return closed, updated



# ── PLAN_v15 P5: offline catch-up reconciliation ──────────────────────────────
# Laptop sleep / backend mati: posisi tak terpantau sementara harga jalan terus.
# Saat kembali, putar ulang lilin 15m dalam jeda itu; bila SL tersentuh, tutup
# retroaktif di harga SL dengan waktu lilin — bukan harga sekarang.

RECONCILE_GAP_MIN = 15.0   # minutes without a tick before a position is reconciled


async def _fetch_futures_klines_15m(client: "httpx.AsyncClient", symbol: str,
                                    start_ts: float) -> list:
    """15m klines from start_ts → now (limit 1000 ≈ 10.4 days of gap coverage)."""
    try:
        r = await client.get(
            fapi(f"/fapi/v1/klines?symbol={symbol}&interval=15m"
                 f"&startTime={int(start_ts * 1000)}&limit=1000")
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return []


async def _reconcile_apply_close(session, trade, meta: dict, close_price: float,
                                 reason: str, closed_ts: float) -> None:
    """Tutup retroaktif dengan akuntansi yang SAMA dengan `_monitor_agentic`:
    `position_size` sudah ukuran pasca-parsial dan `pnl_dollar` sudah memuat
    yang dibank di TP1/TP2 — jadi total = bank + sisa × pnl bersih − funding.

    BUG B3 (5 Sep 2026): jalur ini menutup posisi tapi TIDAK PERNAH menulis
    `exit_events`; ledger keluar adalah satu-satunya bahan `exit_learning`.
    Ledger ditulis di transaksi yang SAMA dengan penutupannya."""
    _entry_d = Decimal(str(trade.entry_price))
    _close_d = Decimal(str(close_price))
    pnl_gross = (
        (_close_d - _entry_d) / _entry_d * 100 if trade.direction == "LONG"
        else (_entry_d - _close_d) / _entry_d * 100
    )
    _xc_pct, _fund_d = _true_close_costs(meta, reason)
    pnl_net   = pnl_gross - Decimal(str(ROUND_TRIP * 100)) - Decimal(str(_xc_pct))
    _notional = Decimal(str(trade.position_size or 0.0))
    _banked   = Decimal(str(trade.pnl_dollar or 0.0))

    meta["close_reason"]        = reason
    meta["pnl_gross_pct"]       = float(round(pnl_gross, 3))
    meta["fee_pct"]             = round(ROUND_TRIP * 100, 3)
    meta["cost_slippage_pct"]   = round(_xc_pct, 4)
    meta["cost_funding_dollar"] = round(_fund_d, 4)
    _append_trade_event(meta, "offline_reconcile", {
        "reason": reason, "close_price": close_price, "closed_ts": closed_ts,
    })
    trade.signals_json = json.dumps(meta, ensure_ascii=False)
    trade.status       = "sl"
    trade.close_price  = round(close_price, 8)
    trade.closed_at    = min(closed_ts, time.time())
    trade.pnl_pct      = float(round(pnl_net, 2))
    trade.pnl_dollar   = float(round(
        _banked + pnl_net / 100 * _notional - Decimal(str(_fund_d)), 2))

    await _log_exit_event(
        session, trade, meta,
        lane=str(meta.get("setup_type") or "agentic"), close_reason=reason,
        status="sl", pnl_net=float(pnl_net), pnl_dollar=trade.pnl_dollar,
    )


async def reconcile_offline_positions() -> int:
    """Replay the gap for every open position without a recent tick.
    Returns count of retroactively closed positions. Fail-open: klines errors
    leave the position alone (the normal cycle takes over from here anyway).

    Lingkup: HANYA persilangan SL. Tangga TP agen tunggal adalah PARSIAL
    (50% di TP1, 25% di TP2) dengan trailing sesudahnya — menutup penuh di TP2
    akan mencatat hasil yang tak pernah diambil aturan mana pun. Bila TP
    tersentuh dalam jeda, loop berikutnya menilainya dari harga sekarang."""
    if not is_db_available():
        return 0

    closed = 0
    now    = time.time()
    async with AsyncSessionLocal() as session:
        trades = list((await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(list(_AGENTIC_STYLES)),
                PaperTrade.status == "open",
            )
        )).scalars().all())
        if not trades:
            return 0

        async with httpx.AsyncClient(timeout=20) as client:
            for trade in trades:
                gap_start = trade.last_tick_at or trade.entry_at
                if not gap_start or (now - gap_start) < RECONCILE_GAP_MIN * 60:
                    continue

                try:
                    meta = json.loads(trade.signals_json or "{}")
                except Exception:
                    meta = {}
                sl = trade.trail_sl or trade.stop_loss
                if not sl:
                    continue

                klines = await _fetch_futures_klines_15m(client, trade.symbol, gap_start)
                for k in klines:
                    try:
                        k_open_ts = float(k[0]) / 1000
                        k_high    = float(k[2])
                        k_low     = float(k[3])
                    except (IndexError, ValueError):
                        continue
                    if k_open_ts + 900 < (trade.entry_at or 0):
                        continue
                    tembus = (k_low <= sl) if trade.direction == "LONG" else (k_high >= sl)
                    if not tembus:
                        continue
                    await _reconcile_apply_close(
                        session, trade, meta, sl, "offline_reconcile_sl", k_open_ts + 900)
                    closed += 1
                    logger.warning(
                        "offline_reconcile_closed",
                        symbol=trade.symbol, direction=trade.direction,
                        gap_hours=round((now - gap_start) / 3600, 1),
                        close_price=trade.close_price, pnl_pct=trade.pnl_pct,
                    )
                    break   # trade closed — stop walking candles

        if closed:
            await session.commit()

    if closed:
        await _update_futures_balance()
        logger.warning("offline_reconcile_done", closed=closed)
    return closed



# ── Jalur cepat 30 detik ──────────────────────────────────────────────────────

async def _run_fast_loop() -> None:
    """SEMUA posisi terbuka agen aktif diperiksa tiap 30 detik dengan aturan
    keluar yang sama (`_monitor_agentic`).

    Terukur malam 12-13 Sep 2026 (23 penutupan): tujuh menembus SL lebih dari
    1% sebelum loop 120 detik sempat melihatnya — 3,1%, 3,9%, 1,9%, 5,7%, 4,8%,
    1,7%. Penandaan "berisiko" tak akan menolong: ARKUSDT jatuh dari +10% ke SL
    dalam SATU jeda. Dampaknya asimetris — pada `sl_plus` hanya mengurangi
    untung, pada `sl_hit` rugi melampaui risiko yang direncanakan (GRIFFAINUSDT
    −$7,81 dari rencana ~−$5,4), mematahkan jaminan "rugi di SL = 1% modal".
    """
    global _fast_loop_agentic_seen
    await asyncio.sleep(STARTUP_DELAY + 30)   # stagger to avoid startup race
    while True:
        await asyncio.sleep(FAST_INTERVAL_SEC)
        try:
            if not is_db_available():
                continue
            async with AsyncSessionLocal() as session:
                trades = list((await session.execute(
                    select(PaperTrade).where(
                        PaperTrade.style.in_(list(_AGENTIC_STYLES)),
                        PaperTrade.status == "open",
                    )
                )).scalars().all())

                _kini = frozenset(t.id for t in trades)
                if _kini != _fast_loop_agentic_seen:
                    logger.info("fast_loop_agentic_watch", n=len(_kini),
                                symbols=sorted(t.symbol for t in trades),
                                interval_sec=FAST_INTERVAL_SEC)
                    _fast_loop_agentic_seen = _kini
                if not trades:
                    continue

                prices = await _fetch_futures_prices(list({t.symbol for t in trades}))
                closed, _ = await _monitor_agentic(session, trades, prices)
                await session.commit()
                if closed:
                    logger.info("fast_loop_agentic_closed", closed=closed)
                    await _update_futures_balance()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("fast_loop_error", error=str(exc)[:80])



# ── Background loop ───────────────────────────────────────────────────────────

async def run_futures_monitor() -> None:
    global _running, _cycle_count, _last_check, _last_error, _closed_today, _today

    _running = True
    logger.info("futures_monitor_started", interval_sec=INTERVAL_SEC)
    await asyncio.sleep(STARTUP_DELAY)

    # Rebuild the single futures wallet on startup so /balance/futures is accurate after restarts
    await _update_futures_balance()

    # PLAN_v15 P5: reconcile positions that went unmonitored while the backend was down
    try:
        await reconcile_offline_positions()
    except Exception as exc:
        logger.warning("offline_reconcile_failed", error=str(exc)[:120])

    _fast_task = asyncio.create_task(_run_fast_loop())

    while True:
        # F61: reset closed_today counter at midnight
        _today_str = time.strftime("%Y-%m-%d")
        if _today != _today_str:
            _today        = _today_str
            _closed_today = 0

        try:
            # Fase 1a: rantai ukuran — dipakai monitor untuk menilai batas rugi
            # margin & jarak likuidasi. Kedua loop menyegarkannya sendiri supaya
            # tak ada yang bergantung pada loop lain sudah jalan.
            try:
                from agents.futures import sizing_config
                await sizing_config.refresh()
            except Exception as exc:
                logger.warning("sizing_config_pull_failed", scope="futures_monitor",
                               error=str(exc)[:120])

            await _check_server_time_drift()   # EC5: NTP drift warning (no-op if < 30 min since last)

            # PLAN_v15 P5: if the previous cycle is unexpectedly old (laptop sleep,
            # long stall), replay the gap before acting on current prices.
            if _last_check and (time.time() - _last_check) > RECONCILE_GAP_MIN * 60:
                try:
                    await reconcile_offline_positions()
                except Exception as exc:
                    logger.warning("offline_reconcile_failed", error=str(exc)[:120])

            closed_n, updated_n = await check_futures_positions()
            _cycle_count += 1
            _last_check   = time.time()
            _last_error   = None
            if closed_n or updated_n:
                _closed_today += closed_n
                logger.info("futures_monitor_cycle", closed=closed_n, updated=updated_n,
                            cycle=_cycle_count)
            # Refresh the wallet after any close, plus a periodic safety resync
            if closed_n > 0 or _cycle_count % 10 == 0:
                await _update_futures_balance()

        except asyncio.CancelledError:
            logger.info("futures_monitor_stopped")
            _running = False
            _fast_task.cancel()
            raise
        except Exception as exc:
            _last_error = str(exc)[:120]
            logger.error("futures_monitor_error", error=_last_error)

        await asyncio.sleep(INTERVAL_SEC)
