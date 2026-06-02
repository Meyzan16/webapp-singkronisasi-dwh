"""Binance Futures client for order execution and account management."""

from decimal import Decimal
from typing import Any

import ccxt.async_support as ccxt
import structlog

from app.config import Settings

logger = structlog.get_logger(__name__)


class FuturesClient:
    """Async CCXT wrapper for Binance USDT-M Futures."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        config: dict[str, Any] = {
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        }
        if settings.binance_api_key and settings.binance_api_secret:
            config["apiKey"] = settings.binance_api_key
            config["secret"] = settings.binance_api_secret

        if settings.binance_testnet:
            config["sandbox"] = True

        self._exchange: ccxt.binance = ccxt.binance(config)

    @staticmethod
    def _symbol(pair: str) -> str:
        """Convert BTCUSDT to BTC/USDT:USDT for CCXT futures."""
        base = pair.replace("USDT", "")
        return f"{base}/USDT:USDT"

    async def set_leverage(self, pair: str, leverage: int) -> dict[str, Any]:
        """Set leverage for a trading pair."""
        symbol = self._symbol(pair)
        try:
            result = await self._exchange.set_leverage(leverage, symbol)
            logger.info("leverage_set", pair=pair, leverage=leverage)
            return result
        except ccxt.ExchangeError as e:
            logger.error("leverage_set_failed", pair=pair, error=str(e))
            raise

    async def open_position(
        self,
        pair: str,
        side: str,
        quantity: Decimal,
        leverage: int = 5,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> dict[str, Any]:
        """Open a futures position with optional SL/TP."""
        symbol = self._symbol(pair)
        await self.set_leverage(pair, leverage)

        order_side = "buy" if side == "LONG" else "sell"
        logger.info("opening_position", pair=pair, side=side, quantity=str(quantity))

        # Main market order
        order = await self._exchange.create_order(
            symbol=symbol,
            type="market",
            side=order_side,
            amount=float(quantity),
        )

        # Place stop loss
        if stop_loss is not None:
            sl_side = "sell" if side == "LONG" else "buy"
            try:
                await self._exchange.create_order(
                    symbol=symbol,
                    type="stop_market",
                    side=sl_side,
                    amount=float(quantity),
                    params={"stopPrice": float(stop_loss), "reduceOnly": True},
                )
                logger.info("sl_placed", pair=pair, stop_loss=str(stop_loss))
            except ccxt.ExchangeError as e:
                logger.error("sl_placement_failed", error=str(e))

        # Place take profit
        if take_profit is not None:
            tp_side = "sell" if side == "LONG" else "buy"
            try:
                await self._exchange.create_order(
                    symbol=symbol,
                    type="take_profit_market",
                    side=tp_side,
                    amount=float(quantity),
                    params={"stopPrice": float(take_profit), "reduceOnly": True},
                )
                logger.info("tp_placed", pair=pair, take_profit=str(take_profit))
            except ccxt.ExchangeError as e:
                logger.error("tp_placement_failed", error=str(e))

        return order

    async def close_position(self, pair: str, side: str, quantity: Decimal) -> dict[str, Any]:
        """Close an existing position."""
        symbol = self._symbol(pair)
        close_side = "sell" if side == "LONG" else "buy"

        logger.info("closing_position", pair=pair, side=side, quantity=str(quantity))
        order = await self._exchange.create_order(
            symbol=symbol,
            type="market",
            side=close_side,
            amount=float(quantity),
            params={"reduceOnly": True},
        )
        return order

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get all open futures positions."""
        positions = await self._exchange.fetch_positions()
        return [p for p in positions if float(p.get("contracts", 0)) > 0]

    async def get_balance(self) -> dict[str, Any]:
        """Get futures account balance."""
        balance = await self._exchange.fetch_balance({"type": "future"})
        return balance

    async def get_ticker(self, pair: str) -> dict[str, Any]:
        """Get current price for a pair."""
        symbol = self._symbol(pair)
        return await self._exchange.fetch_ticker(symbol)

    async def close(self) -> None:
        """Close the exchange connection."""
        await self._exchange.close()
