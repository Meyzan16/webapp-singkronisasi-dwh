"""
Central Binance URL resolver.

All API files import from here — never hardcode Binance URLs directly.
Change BINANCE_SPOT_URL / BINANCE_FAPI_URL in .env to switch regions.
"""

from app.config import get_settings


# ── Failover host SPOT ────────────────────────────────────────────────────────
# `fallback_spot()` ADA sejak lama tapi TIDAK PERNAH dipanggil siapa pun — jadi
# saat host utama diblokir, tak ada yang beralih. Terukur 11 Agu: mirror
# www.binance.bh diblokir jaringan ~12 jam, kedua scanner mati diam-diam,
# sementara data-api.binance.vision (sudah tertulis sbg BINANCE_FALLBACK_URL)
# menjawab 200 sepanjang waktu itu.
#
# Failover ditaruh DI SINI, bukan di tiap pemanggil: `spot()` dipakai di banyak
# tempat, dan menambal satu per satu memastikan ada yang terlewat.
#
# CATATAN: hanya SPOT yang punya cadangan. data-api.binance.vision melayani
# /api/v3 saja — tak ada padanan untuk /fapi, jadi futures tetap bergantung pada
# satu host. Itu batasan nyata, bukan kelalaian.

_active_spot: str | None = None      # None = pakai host utama
_probe_at: float = 0.0
PROBE_INTERVAL_SEC = 300.0


def get_spot_url() -> str:
    """Base URL Spot yang SEDANG dipakai — ikut hasil failover terakhir."""
    return _active_spot or get_settings().binance_spot_url


async def refresh_spot_host(force: bool = False) -> dict:
    """Cek host utama; alihkan ke cadangan bila mati, kembalikan bila pulih.

    Dipanggil berkala oleh loop agen. Gagal total = biarkan pilihan terakhir —
    pemadaman jaringan sesaat tak boleh memicu perpindahan bolak-balik.
    """
    global _active_spot, _probe_at
    import time

    import httpx

    now = time.time()
    if not force and (now - _probe_at) < PROBE_INTERVAL_SEC:
        return {"status": "dilewati", "aktif": get_spot_url()}
    _probe_at = now

    s = get_settings()
    utama, cadangan = s.binance_spot_url, s.binance_fallback_url

    async def _hidup(base: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                return (await c.get(f"{base}/api/v3/ping")).status_code == 200
        except Exception:
            return False

    if await _hidup(utama):
        pindah = _active_spot is not None
        _active_spot = None
        return {"status": "pulih" if pindah else "utama_sehat", "aktif": utama}

    if cadangan and cadangan != utama and await _hidup(cadangan):
        pindah = _active_spot != cadangan
        _active_spot = cadangan
        return {"status": "beralih" if pindah else "cadangan_aktif",
                "aktif": cadangan, "utama_mati": utama}

    return {"status": "dua_duanya_mati", "aktif": get_spot_url()}


def get_fapi_url() -> str:
    """Base URL for Futures API (/fapi/v1/...)."""
    return get_settings().binance_fapi_url


def get_fallback_url() -> str:
    """Fallback URL when primary is unreachable."""
    return get_settings().binance_fallback_url


def spot(path: str) -> str:
    """Build full Spot URL: spot('/api/v3/ticker/price')."""
    return f"{get_spot_url()}{path}"


def fapi(path: str) -> str:
    """Build full Futures URL: fapi('/fapi/v1/klines?...')."""
    return f"{get_fapi_url()}{path}"


def fallback_spot(path: str) -> str:
    """Build fallback Spot URL."""
    return f"{get_fallback_url()}{path}"


def testnet_url() -> str:
    """Testnet URL for Binance Spot."""
    return "https://testnet.binance.vision"
