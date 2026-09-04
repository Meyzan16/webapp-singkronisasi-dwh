"""
WebSocket Real-Time Big Mover Feed — PLAN-BIG-MOVERS Phase 2 BM4 / G21.

Subscribe Binance Futures `!ticker@arr` stream (1s update, all symbols).
Filter symbols dengan abs(price_change_1m) ≥ 1% (or change_24h ≥ 5%) → push ke store.

Latency target: market move → store cache < 2 detik (vs 2 min scan cycle).

Heartbeat tiap 10s; fallback ke REST polling kalau no msg > 30s (EC3).
Auto-reconnect dengan exponential backoff.

KENYATAAN DI JARINGAN INI (diukur 5 Sep 2026): tidak ada satu pun endpoint WS
futures Binance yang terjangkau. Domain utama `fstream.binance.com` di-resolve
ke 198.54.100.22 — host parkir, bukan Binance — sehingga sertifikat yang muncul
memang bukan milik Binance dan ditolak. Mirror pun tak menyediakan penggantinya:
`fstream/stream.binance.bh` memutus koneksi, `:9443` timeout, `www.binance.bh/ws`
menjawab HTTP 202. Jadi WS di sini adalah OPTIMASI YANG TAK PERNAH AKTIF, bukan
jalur utama.

Konsekuensinya untuk pembaca kode: jangan tergoda "memperbaiki" error sertifikat
dengan mematikan verifikasi TLS. Verifikasi justru sedang bekerja benar — ia
menolak sambungan yang dialihkan. Yang menjaga feed tetap hidup adalah REST-poll
ke mirror tiap ~30 detik (terbukti: 149 movers, 0 error), dan `get_state()`
melaporkannya sebagai `degraded=True, healthy=True` — bukan sebagai kerusakan.
"""

import asyncio
import json
import time
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Binance Futures WebSocket — combined stream
WS_URL = "wss://fstream.binance.com/ws/!ticker@arr"

# Filter thresholds
MIN_ABS_CHANGE_24H = 5.0    # show coins with ≥5% move (catches early moves)
MIN_ABS_CHANGE_1M  = 1.0    # spike: ≥1% in 1 min

# Heartbeat / fallback
HEARTBEAT_SEC      = 10
STALE_FALLBACK_SEC = 30
RECONNECT_BASE_SEC = 5
# Mirror binance.bh (dipakai dari Indonesia) TIDAK menyediakan WS futures, dan
# domain utama fstream.binance.com geo-blocked → WS praktis selalu gagal di sini.
# Maks backoff dinaikkan 60→300 dtk supaya percobaan WS tak membanjiri log; feed
# tetap segar lewat REST-poll mirror (lihat _rest_fallback_poll + watchdog).
RECONNECT_MAX_SEC  = 300

# State
_running:        bool                       = False
_last_msg_ts:    float                      = 0.0
_last_error:     Optional[str]              = None
_msg_count:      int                        = 0
_ws_reason:      Optional[str]              = None   # kenapa WS tak tersambung (hasil diagnosa)
_ws_fail_count:  int                        = 0
_last_rest_ok:   float                      = 0.0
_movers_live:    dict[str, dict]            = {}   # symbol -> ticker snapshot
_prev_prices:    dict[str, tuple[float, float]] = {}  # symbol -> (price, ts) for 1m delta
_subscribers:    list[asyncio.Queue]        = []


def get_state() -> dict:
    """Status feed untuk /health dan dasbor.

    Yang diukur adalah KESEGARAN DATA, bukan hidup-matinya WebSocket. Dari
    jaringan ini WS futures memang tak terjangkau (lihat _diagnose_ws_failure),
    dan itu bukan kerusakan: REST-poll mirror menjaga movers tetap segar.
    Melaporkan "error" hanya karena WS mati membuat dasbor merah terus-menerus
    dan menyembunyikan kegagalan yang benar-benar penting — yaitu ketika REST
    pun berhenti bekerja.
    """
    age = round(time.time() - _last_msg_ts, 1) if _last_msg_ts else None
    transport = "websocket" if _msg_count else ("rest_fallback" if _last_rest_ok else "none")
    return {
        "running":         _running,
        "last_msg_ts":     _last_msg_ts,
        "age_sec":         age,
        "last_error":      _last_error,
        "msg_count":       _msg_count,
        "movers_tracked":  len(_movers_live),
        "is_stale":        bool(age and age > STALE_FALLBACK_SEC),
        # Baru: pisahkan "WS tak terjangkau" dari "feed rusak".
        "transport":       transport,
        "ws_connected":    bool(_msg_count),
        "ws_reason":       _ws_reason,
        "ws_fail_count":   _ws_fail_count,
        "last_rest_ok":    _last_rest_ok or None,
        "degraded":        transport == "rest_fallback",   # jalan, tapi bukan realtime
        "healthy":         bool(age is not None and age <= STALE_FALLBACK_SEC),
    }


def get_live_movers(limit: int = 50) -> list[dict]:
    """
    Return current snapshot of live big movers, sorted by abs(change_1m) desc.
    Returns [] if feed is stale (age > STALE_FALLBACK_SEC) — caller falls back to REST.
    """
    if not _last_msg_ts or (time.time() - _last_msg_ts) > STALE_FALLBACK_SEC:
        return []
    movers = sorted(
        _movers_live.values(),
        key=lambda m: abs(m.get("change_1m_pct", 0)),
        reverse=True,
    )
    return movers[:limit]


def subscribe() -> asyncio.Queue:
    """Subscribe to per-coin alert events (spike crossings)."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


def _broadcast(msg: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            pass


# ── Processing ─────────────────────────────────────────────────────────────────

def _process_tickers(tickers: list[dict]) -> None:
    """Parse one `!ticker@arr` batch — update internal state, emit spike events."""
    global _last_msg_ts, _msg_count
    now = time.time()
    _last_msg_ts = now
    _msg_count  += 1

    for t in tickers:
        sym = t.get("s", "")
        if not sym.endswith("USDT"):
            continue
        try:
            price       = float(t.get("c", 0))   # last price
            change_24h  = float(t.get("P", 0))   # percent change 24h
            quote_vol   = float(t.get("q", 0))   # quote volume
        except (TypeError, ValueError):
            continue

        # 1-minute delta
        change_1m = 0.0
        prev = _prev_prices.get(sym)
        if prev:
            prev_price, prev_ts = prev
            if (now - prev_ts) >= 50 and prev_price > 0:   # ≥50s — close enough to "1m"
                change_1m = (price - prev_price) / prev_price * 100
                _prev_prices[sym] = (price, now)
            # else: keep old reference until 1m elapses
        else:
            _prev_prices[sym] = (price, now)

        # Filter: keep coins above either threshold
        if abs(change_24h) < MIN_ABS_CHANGE_24H and abs(change_1m) < MIN_ABS_CHANGE_1M:
            _movers_live.pop(sym, None)
            _prev_prices.pop(sym, None)  # prune stale price ref when symbol leaves tracking
            continue

        prev_state = _movers_live.get(sym, {})
        _movers_live[sym] = {
            "symbol":          sym,
            "price":           price,
            "change_24h":      round(change_24h, 2),
            "change_1m_pct":   round(change_1m, 3),
            "quote_vol":       round(quote_vol, 0),
            "ts":              now,
        }

        # Emit spike crossing event (change_1m crosses threshold)
        was_spike = abs(prev_state.get("change_1m_pct", 0)) >= MIN_ABS_CHANGE_1M
        is_spike  = abs(change_1m) >= MIN_ABS_CHANGE_1M
        if is_spike and not was_spike:
            _broadcast({
                "type":          "spike",
                "symbol":        sym,
                "price":         price,
                "change_1m_pct": round(change_1m, 3),
                "change_24h":    round(change_24h, 2),
                "ts":            now,
            })

        # G12: broadcast push notification when coin crosses ±20% 24h threshold
        was_big = abs(prev_state.get("change_24h", 0)) >= 20.0
        is_big  = abs(change_24h) >= 20.0
        if is_big and not was_big:
            try:
                from app.ws.big_mover_alerts import broadcast_big_mover as _bma
                asyncio.create_task(_bma(sym, change_24h, price, quote_vol))
            except Exception:
                pass


# ── EC3: REST fallback + heartbeat watchdog ────────────────────────────────────

def _rest_url() -> str:
    """Ticker 24h via resolver terpusat → ikut mirror binance.bh (bukan domain
    utama fapi.binance.com yang geo-blocked). Dipanggil saat poll agar menghormati
    config .env terbaru."""
    try:
        from app.services.binance_urls import fapi
        return fapi("/fapi/v1/ticker/24hr")
    except Exception:
        return "https://www.binance.bh/fapi/v1/ticker/24hr"


async def _rest_fallback_poll() -> None:
    """EC3: Populate _movers_live via REST saat WS diam >30s ATAU tak pernah konek.

    Uses the same field names as _process_tickers so consumers see consistent data.
    change_1m_pct is unknown from REST → set to 0.0. Menandai _last_msg_ts supaya
    get_live_movers() menganggap data segar & watchdog tak poll tiap 10 dtk.
    """
    global _last_msg_ts
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(_rest_url())
            if r.status_code != 200:
                return
            now  = time.time()
            kept = 0
            for t in r.json():
                sym = t.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                try:
                    change_24h = float(t.get("priceChangePercent", 0))
                    price      = float(t.get("lastPrice", 0))
                    quote_vol  = float(t.get("quoteVolume", 0))
                except (TypeError, ValueError):
                    continue
                if abs(change_24h) >= MIN_ABS_CHANGE_24H:
                    _movers_live[sym] = {
                        "symbol":        sym,
                        "price":         price,
                        "change_24h":    round(change_24h, 2),
                        "change_1m_pct": 0.0,
                        "quote_vol":     round(quote_vol, 0),
                        "ts":            now,
                    }
                    kept += 1
            # Tandai feed segar (REST dianggap "pesan") — get_live_movers() jadi
            # mengembalikan movers & watchdog menahan poll berikutnya ~30 dtk.
            _last_msg_ts = now
            global _last_rest_ok
            _last_rest_ok = now
            logger.info("ws_rest_fallback_done", movers=kept, src="mirror")
    except Exception as exc:
        logger.warning("ws_rest_fallback_error", error=str(exc)[:80])


async def _heartbeat_watchdog() -> None:
    """EC3: tiap 10s cek umur pesan; REST-poll fallback saat WS basi >30s.

    BUG-FIX 28 Jul 2026: dulu `if not _last_msg_ts: continue` → saat WS TAK PERNAH
    konek (fstream.binance.com geo-blocked/SSL disadap), _last_msg_ts tetap 0
    selamanya → fallback tak pernah jalan → feed mati total, bukan degrade. Kini
    saat belum ada pesan sama sekali, umur dihitung dari start proses → setelah
    ~30 dtk WS senyap, REST-poll mirror tetap menghidupkan feed.
    """
    started = time.time()
    while True:
        await asyncio.sleep(HEARTBEAT_SEC)
        age = (time.time() - _last_msg_ts) if _last_msg_ts else (time.time() - started)
        if age > STALE_FALLBACK_SEC:
            logger.info("ws_feed_stale_rest_poll", age_sec=round(age, 1),
                        connected=bool(_last_msg_ts))
            await _rest_fallback_poll()


# ── Connection loop ────────────────────────────────────────────────────────────

# Alamat yang dipakai pembajak DNS/parkir domain saat sebuah host diblokir.
# fstream.binance.com dari jaringan Indonesia menunjuk ke sini, bukan ke Binance —
# itulah kenapa sertifikat yang muncul BUKAN milik Binance dan verifikasi gagal.
_HIJACK_HINT_NETS = ("198.54.100.",)


async def _diagnose_ws_failure(exc: Exception) -> str:
    """Terjemahkan kegagalan koneksi WS menjadi sebab yang sebenarnya.

    Dibuat 5 Sep 2026. Sebelumnya loop ini hanya mencatat pesan mentah
    "A certificate chain processed, but terminated in a root certificate which
    is not trusted by the trust provider" — dan itu MENYESATKAN: terbaca seperti
    trust store salah pasang, padahal REST ke mirror binance.bh jalan mulus lewat
    truststore yang sama. Sebab nyatanya: DNS fstream.binance.com dibajak ke
    198.54.100.22 (host parkir), jadi sertifikat yang disodorkan memang bukan
    milik Binance. Verifikasi sertifikat justru BEKERJA BENAR di sini — ia
    menolak sambungan yang disadap. Karena itu jangan pernah "memperbaikinya"
    dengan mematikan verifikasi.

    Terukur 5 Sep 2026, tak ada satu pun WS futures yang terjangkau dari sini:
      fstream.binance.com   -> DNS 198.54.100.22, sertifikat ditolak
      fstream/stream.binance.bh -> koneksi diputus (ConnectionReset)
      fstream.binance.bh:9443   -> timeout saat handshake
      www.binance.bh/ws         -> HTTP 202 (bukan endpoint WS)
    """
    import socket
    from urllib.parse import urlparse

    host = urlparse(WS_URL).hostname or ""
    ip = ""
    try:
        # DNS di thread: getaddrinfo memblokir, dan loop ini berbagi proses
        # dengan seluruh API.
        ip = await asyncio.to_thread(socket.gethostbyname, host)
    except Exception:
        return f"DNS {host} tak bisa di-resolve — jaringan memblokir domainnya"

    if any(ip.startswith(net) for net in _HIJACK_HINT_NETS):
        return (f"DNS {host} dibajak ke {ip} (host parkir, bukan Binance) — "
                f"sertifikatnya memang bukan milik Binance, jadi ditolak. "
                f"Ini pemblokiran jaringan, BUKAN masalah trust store.")

    name = type(exc).__name__
    if "Certificate" in name or "SSLCert" in name:
        return (f"Sertifikat {host} ({ip}) ditolak — sambungan tampaknya disadap "
                f"atau dialihkan. Verifikasi sengaja TIDAK dimatikan.")
    if isinstance(exc, ConnectionResetError) or "ConnectionReset" in name:
        return f"{host} ({ip}) memutus koneksi — diblokir di jaringan ini"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return f"{host} ({ip}) tak menjawab handshake — kemungkinan difilter"
    return f"{name}: {str(exc)[:90]}"


async def _connect_once() -> None:
    """One connection lifetime — yields when disconnected."""
    import websockets  # local import to avoid module-load failure if not installed

    async with websockets.connect(
        WS_URL,
        ping_interval=HEARTBEAT_SEC,
        ping_timeout=HEARTBEAT_SEC * 2,
        max_size=None,
    ) as ws:
        global _ws_reason, _ws_fail_count
        if _ws_reason is not None:
            logger.info("ws_big_mover_recovered", url=WS_URL,
                        after_failures=_ws_fail_count, previous_reason=_ws_reason)
        _ws_reason, _ws_fail_count = None, 0
        logger.info("ws_big_mover_connected", url=WS_URL)
        async for raw in ws:
            try:
                data = json.loads(raw)
                # Combined `!ticker@arr` returns a LIST of ticker dicts
                if isinstance(data, list):
                    _process_tickers(data)
                elif isinstance(data, dict) and "data" in data:
                    # Stream-wrapped form (combined endpoint shape)
                    inner = data["data"]
                    if isinstance(inner, list):
                        _process_tickers(inner)
            except json.JSONDecodeError:
                continue


async def run_ws_big_mover_feed() -> None:
    """Main loop with exponential backoff reconnect + EC3 heartbeat watchdog."""
    global _running, _last_error
    _running = True
    backoff  = RECONNECT_BASE_SEC
    logger.info("ws_big_mover_feed_started")

    # EC3: start watchdog as a sibling task so it survives individual reconnects
    _watchdog = asyncio.create_task(_heartbeat_watchdog())

    try:
        while True:
            try:
                await _connect_once()
                # Clean disconnect — small wait then reconnect
                backoff = RECONNECT_BASE_SEC
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                global _ws_reason, _ws_fail_count
                _last_error = str(exc)[:120]
                _ws_fail_count += 1
                reason = await _diagnose_ws_failure(exc)

                # Sebab yang SAMA berulang tiap 5 menit tak perlu diteriakkan
                # terus. Dulu tiap percobaan menulis warning berisi pesan
                # sertifikat mentah, sehingga log penuh alarm untuk kondisi yang
                # sudah diketahui dan permanen — dan kegagalan yang benar-benar
                # baru jadi tenggelam di antaranya. Sebab baru tetap warning.
                if reason != _ws_reason:
                    _ws_reason = reason
                    logger.warning("ws_big_mover_unavailable", reason=reason,
                                   url=WS_URL, fail_count=_ws_fail_count,
                                   fallback="REST poll mirror tiap ~30 dtk")
                else:
                    logger.info("ws_big_mover_retry", fail_count=_ws_fail_count,
                                backoff=backoff)

                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_SEC)
    except asyncio.CancelledError:
        _running = False
        _watchdog.cancel()
        try:
            await _watchdog
        except asyncio.CancelledError:
            pass
        logger.info("ws_big_mover_feed_stopped")
        raise
