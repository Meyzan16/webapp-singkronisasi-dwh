"""Optional provider adapter for point-in-time SPOT on-chain metrics."""

from __future__ import annotations

import asyncio
import os
import time

import httpx
import structlog

from agents.opportunity.feature_engineering import OnchainSnapshot

logger = structlog.get_logger(__name__)

PROVIDER_URL = os.getenv("ONCHAIN_PROVIDER_URL", "").rstrip("/")
PROVIDER_KEY = os.getenv("ONCHAIN_PROVIDER_API_KEY", "")
CACHE_TTL_SEC = int(os.getenv("ONCHAIN_CACHE_TTL_SEC", "900"))
MAX_AGE_SEC = int(os.getenv("ONCHAIN_MAX_AGE_SEC", "3600"))
MAPPING_VERSION = "chain-map-v1"

# Contract mapping is versioned; assets not listed remain missing, never bearish.
ASSET_CHAIN_MAP = {
    "BTC": {"chain": "bitcoin", "contract": None},
    "ETH": {"chain": "ethereum", "contract": None},
    "SOL": {"chain": "solana", "contract": None},
    "BNB": {"chain": "bsc", "contract": None},
    "AVAX": {"chain": "avalanche", "contract": None},
    "MATIC": {"chain": "polygon", "contract": None},
    "LINK": {"chain": "ethereum", "contract": "0x514910771af9ca656af840dff83e8264ecf986ca"},
}

_cache: dict[str, tuple[float, dict]] = {}
_semaphore = asyncio.Semaphore(5)
_chain_cache: tuple[float, list[dict]] | None = None


def _base_symbol(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


async def fetch_onchain(symbol: str, client: httpx.AsyncClient) -> dict:
    now = time.time()
    cached = _cache.get(symbol)
    if cached and now - cached[0] <= CACHE_TTL_SEC:
        return cached[1]
    base = _base_symbol(symbol)
    mapping = ASSET_CHAIN_MAP.get(base)
    if mapping is None:
        return {"available": False, "reason": "asset_not_mapped", "mapping_version": MAPPING_VERSION}
    if not PROVIDER_URL:
        # Built-in no-key fallback: DefiLlama chain TVL/context. This is chain-
        # level evidence (not exchange-flow evidence) and is labelled explicitly.
        global _chain_cache
        try:
            if _chain_cache is None or now - _chain_cache[0] > CACHE_TTL_SEC:
                response = await client.get("https://api.llama.fi/v2/chains", timeout=8)
                response.raise_for_status()
                _chain_cache = (now, response.json())
            aliases = {"bsc": "binance", "polygon": "polygon", "avalanche": "avalanche"}
            target = aliases.get(mapping["chain"], mapping["chain"]).casefold()
            row = next((item for item in _chain_cache[1] if str(item.get("name", "")).casefold() == target), None)
            if row is None:
                return {"available": False, "reason": "chain_not_covered", "mapping_version": MAPPING_VERSION}
            metrics = {
                "chain_tvl_usd": row.get("tvl"),
                "chain_tvl_change_1d_pct": row.get("change_1d"),
                "chain_tvl_change_7d_pct": row.get("change_7d"),
                "chain_tvl_change_30d_pct": row.get("change_1m"),
            }
            coverage = sum(value is not None for value in metrics.values()) / len(metrics)
            result = {
                "available": True, "mapping_version": MAPPING_VERSION,
                **OnchainSnapshot(symbol, now, "defillama", metrics, coverage).as_features(now, MAX_AGE_SEC),
            }
            _cache[symbol] = (now, result)
            return result
        except Exception as exc:
            logger.warning("defillama_onchain_failed", symbol=symbol, error=str(exc)[:120])
            return {"available": False, "reason": "provider_error", "mapping_version": MAPPING_VERSION}
    headers = {"Authorization": f"Bearer {PROVIDER_KEY}"} if PROVIDER_KEY else {}
    try:
        async with _semaphore:
            response = await client.get(
                f"{PROVIDER_URL}/metrics/{base}",
                params={"chain": mapping["chain"], "contract": mapping["contract"]},
                headers=headers,
                timeout=8,
            )
        response.raise_for_status()
        payload = response.json()
        snapshot = OnchainSnapshot(
            symbol=symbol,
            observed_at=float(payload["observed_at"]),
            provider=str(payload.get("provider") or PROVIDER_URL),
            metrics=payload.get("metrics") or {},
            coverage=float(payload.get("coverage", 0.0)),
        ).as_features(now=now, max_age_seconds=MAX_AGE_SEC)
        result = {"available": bool(snapshot["fresh"]), "mapping_version": MAPPING_VERSION, **snapshot}
        _cache[symbol] = (now, result)
        return result
    except Exception as exc:
        logger.warning("onchain_provider_failed", symbol=symbol, error=str(exc)[:120])
        return {"available": False, "reason": "provider_error", "mapping_version": MAPPING_VERSION}


async def enrich_candidates(candidates: list[dict]) -> None:
    """Attach optional challenger data; provider failure never blocks scanning."""
    if not candidates:
        return
    async with httpx.AsyncClient() as client:
        snapshots = await asyncio.gather(*(fetch_onchain(str(row.get("symbol") or ""), client) for row in candidates))
    for candidate, snapshot in zip(candidates, snapshots):
        candidate["onchain_features"] = snapshot
