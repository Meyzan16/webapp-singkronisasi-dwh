"""
Agents entry point — run all trading agents as standalone processes.

Usage:
    # From repo root:
    cd backend
    python -m agents

    # Or via Docker:
    docker compose up agents

This starts:
  1. Scanner Agent  — scans 100 USDT pairs every 15 min, caches results
  2. Paper Trader   — monitors open trades, closes on TP/SL every 60s

Future agents (add here as they're built):
  3. Learning Agent — tunes StyleConfig based on win-rate data
  4. Risk Manager   — adjusts position sizing based on drawdown
  5. Regime Detector— detects bull/bear market, adjusts style weights
"""

import asyncio
import os
import sys

import structlog

# Allow running from repo root: `python -m agents` or `cd backend && python -m agents`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

logger = structlog.get_logger(__name__)


async def run_all_agents() -> None:
    """Start all agents concurrently."""
    from agents.scanner.scheduler import run_scanner_loop
    # paper_trader_agent runs as a rate-limited call inside scanner loop for now
    # future: from agents.paper_trader.agent import run_paper_trade_loop

    logger.info("agents_starting", agents=["scanner_scheduler"])

    try:
        await asyncio.gather(
            run_scanner_loop(),
            # run_paper_trade_loop(),   ← uncomment when standalone agent is ready
        )
    except asyncio.CancelledError:
        logger.info("agents_stopped")


if __name__ == "__main__":
    asyncio.run(run_all_agents())
