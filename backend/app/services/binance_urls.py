"""
Central Binance URL resolver.

All API files import from here — never hardcode Binance URLs directly.
Change BINANCE_SPOT_URL / BINANCE_FAPI_URL in .env to switch regions.
"""

from app.config import get_settings


def get_spot_url() -> str:
    """Base URL for Spot API (/api/v3/...)."""
    return get_settings().binance_spot_url


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
