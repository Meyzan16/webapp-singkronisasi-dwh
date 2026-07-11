"""Event-driven SPOT portfolio replay with conservative intrabar ordering."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time

import httpx
from sqlalchemy import select

from app.services.trading_costs import EXECUTION_COST_PCT
from app.database import AsyncSessionLocal
from app.models.spot_decision_event import SpotDecisionEvent
from agents.opportunity.outcome_tracker import _fetch_klines


@dataclass(frozen=True)
class ReplayTrade:
    symbol: str
    opened_at: float
    closed_at: float
    notional: float
    pnl_pct: float
    pnl_dollar: float
    reason: str


def simulate_trade(event: dict, cost_stress: float = 1.0) -> tuple[float, float, str]:
    """Return (exit_ts, net_pnl_pct, reason); SL wins ambiguous same-bar ties."""
    entry = float(event["entry"])
    sl = float(event["stop_loss"])
    targets = [
        (float(event.get("tp1") or 0), 0.30, "tp1"),
        (float(event.get("tp2") or 0), 0.20, "tp2"),
        (float(event.get("tp3") or 0), 0.15, "tp3"),
    ]
    candles = sorted(event.get("candles", []), key=lambda row: float(row[6]))
    remaining = 1.0
    gross_weighted_pct = 0.0
    hit: set[str] = set()
    exit_ts = float(event["scan_ts"])
    reason = "no_data"
    last_close = entry

    for candle in candles:
        high, low, close = float(candle[2]), float(candle[3]), float(candle[4])
        exit_ts = float(candle[6]) / 1000
        last_close = close
        if low <= sl and remaining > 0:
            gross_weighted_pct += ((sl - entry) / entry * 100) * remaining
            remaining = 0.0
            reason = "sl_hit"
            break
        for target, fraction, label in targets:
            if target > entry and label not in hit and high >= target and remaining > 0:
                sold = min(fraction, remaining)
                gross_weighted_pct += ((target - entry) / entry * 100) * sold
                remaining -= sold
                hit.add(label)
                reason = label
        if remaining <= 0:
            break

    if remaining > 0:
        gross_weighted_pct += ((last_close - entry) / entry * 100) * remaining
        reason = "replay_end" if reason == "no_data" else f"{reason}_runner_end"
    net_cost = EXECUTION_COST_PCT * max(0.0, cost_stress)
    return exit_ts, round(gross_weighted_pct - net_cost, 4), reason


def replay_portfolio(
    events: list[dict],
    initial_balance: float = 1000.0,
    max_positions: int = 4,
    max_allocation_fraction: float = 0.25,
    cost_stress: float = 1.0,
) -> dict:
    """Replay chronological entries with capital lock and symbol deduplication."""
    balance = initial_balance
    available = initial_balance
    peak = initial_balance
    max_drawdown = 0.0
    active: list[ReplayTrade] = []
    completed: list[ReplayTrade] = []
    skipped = {"capital": 0, "slots": 0, "duplicate_symbol": 0, "invalid": 0}

    def settle(until: float) -> None:
        nonlocal balance, available, peak, max_drawdown
        due = sorted((trade for trade in active if trade.closed_at <= until), key=lambda trade: trade.closed_at)
        for trade in due:
            active.remove(trade)
            balance += trade.pnl_dollar
            available += trade.notional + trade.pnl_dollar
            peak = max(peak, balance)
            max_drawdown = max(max_drawdown, peak - balance)
            completed.append(trade)

    for event in sorted(events, key=lambda row: float(row["scan_ts"])):
        scan_ts = float(event["scan_ts"])
        settle(scan_ts)
        if not event.get("candles") or float(event.get("entry") or 0) <= 0:
            skipped["invalid"] += 1
            continue
        if any(trade.symbol == event["symbol"] for trade in active):
            skipped["duplicate_symbol"] += 1
            continue
        if len(active) >= max_positions:
            skipped["slots"] += 1
            continue
        notional = min(balance * max_allocation_fraction, available)
        if notional <= 0:
            skipped["capital"] += 1
            continue
        exit_ts, pnl_pct, reason = simulate_trade(event, cost_stress)
        pnl_dollar = round(notional * pnl_pct / 100, 4)
        available -= notional
        active.append(ReplayTrade(
            symbol=str(event["symbol"]), opened_at=scan_ts, closed_at=exit_ts,
            notional=notional, pnl_pct=pnl_pct, pnl_dollar=pnl_dollar, reason=reason,
        ))

    settle(float("inf"))
    wins = [trade for trade in completed if trade.pnl_dollar > 0]
    losses = [trade for trade in completed if trade.pnl_dollar < 0]
    gross_win = sum(trade.pnl_dollar for trade in wins)
    gross_loss = abs(sum(trade.pnl_dollar for trade in losses))
    return {
        "initial_balance": round(initial_balance, 2),
        "final_balance": round(balance, 2),
        "net_pnl": round(balance - initial_balance, 2),
        "trades": len(completed),
        "win_rate": round(len(wins) / len(completed), 4) if completed else None,
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
        "max_drawdown_dollar": round(max_drawdown, 2),
        "cost_stress": cost_stress,
        "skipped": skipped,
        "trade_log": [trade.__dict__ for trade in completed],
    }


async def run_historical_portfolio_replay(limit: int = 100) -> dict:
    """Reconstruct actual decision paths from Binance closed hourly candles."""
    async with AsyncSessionLocal() as session:
        rows = list((await session.execute(
            select(SpotDecisionEvent).where(
                SpotDecisionEvent.opened.is_(True),
                SpotDecisionEvent.scan_ts <= time.time() - 24 * 3600,
            ).order_by(SpotDecisionEvent.scan_ts.desc()).limit(max(20, min(limit, 200)))
        )).scalars().all())
    rows.reverse()
    replay_events = []
    async with httpx.AsyncClient() as client:
        for row in rows:
            try:
                snapshot = json.loads(row.feature_snapshot_json or "{}")
                entry = float(snapshot.get("entry") or snapshot.get("current_price") or 0)
                stop_loss = float(snapshot.get("stop_loss") or 0)
                if entry <= 0 or stop_loss <= 0:
                    continue
                candles = await _fetch_klines(client, row, time.time())
                replay_events.append({
                    "symbol": row.symbol, "scan_ts": row.scan_ts,
                    "entry": entry, "stop_loss": stop_loss,
                    "tp1": snapshot.get("tp1"), "tp2": snapshot.get("tp2") or snapshot.get("take_profit"),
                    "tp3": snapshot.get("tp3"), "candles": candles,
                })
            except (TypeError, ValueError, json.JSONDecodeError, httpx.HTTPError):
                continue
    return {
        "source_events": len(rows),
        "replayable_events": len(replay_events),
        "normal_cost": replay_portfolio(replay_events, cost_stress=1.0),
        "stress_1_5x": replay_portfolio(replay_events, cost_stress=1.5),
    }
