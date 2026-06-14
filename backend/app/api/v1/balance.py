"""
Balance API — paper trading balance management.

GET  /balance/{style}        — current balance + P&L summary
POST /balance/{style}/deposit — add funds (simulate deposit)
POST /balance/{style}/reset   — reset to initial (admin use)
"""

import time

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import AsyncSessionLocal, is_db_available
from app.models.paper_balance import PaperBalance
from app.models.paper_trade import PaperTrade
from app.models.balance_transaction import BalanceTransaction
from app.services.trading_costs import FUTURES_STARTING_BALANCE, FUTURES_CLOSED_STATUSES

router = APIRouter(tags=["balance"])
logger = structlog.get_logger(__name__)

# Phase 9: futures is ONE wallet ("futures") that both agents draw from.
STYLE_MAP = {
    "spot":    "opportunity_spot",
    "futures": "futures",
}

# Trades are tagged per agent, but they all settle into the single "futures" wallet.
_FUTURES_AGENT_STYLES = ["futures_agent1", "futures_agent2"]


def _wallet_trade_styles(style_key: str) -> list[str]:
    """paper_trade styles that belong to a wallet key."""
    return _FUTURES_AGENT_STYLES if style_key == "futures" else [style_key]


def _locked_margin(open_trades: list[PaperTrade]) -> float:
    """Capital locked = Σ margin. Margin = notional / leverage (leverage None→1 for spot)."""
    return sum((t.position_size or 0.0) / max(t.leverage or 1, 1) for t in open_trades)


DEFAULT_BALANCE = FUTURES_STARTING_BALANCE  # single source: trading_costs.py

# Position sizing: fixed-fractional risk with conviction scaling.
# Base 1% of balance per trade; high-conviction setups (raw score → 120+) up to 2%.
RISK_BASE_FRACTION = 0.01
RISK_MAX_FRACTION  = 0.02
CONVICTION_FLOOR   = 90.0    # raw (uncapped, pre-weight) score where scaling starts
CONVICTION_CEIL    = 120.0   # raw score for full conviction

# Portfolio discipline (§7B, §12.4, §14.3)
MAX_CONCURRENT_POSITIONS = 3      # capital concentrated in best setups only
MIN_NOTIONAL_ABS         = 150.0  # never open dust positions
MIN_NOTIONAL_FRACTION    = 0.15   # ...or 15% of balance, whichever is higher
MAX_NOTIONAL_FRACTION    = 0.40   # one position never exceeds 40% of balance
MAX_PORTFOLIO_RISK       = 0.04   # sum of open risk_dollar ≤ 4% of balance


async def get_or_create_balance(style_key: str) -> PaperBalance:
    """Get or initialize balance row for a style. Thread-safe via DB upsert."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperBalance).where(PaperBalance.style == style_key)
        )
        bal = result.scalar_one_or_none()
        if bal is None:
            now = time.time()
            bal = PaperBalance(
                style           = style_key,
                balance         = DEFAULT_BALANCE,
                initial_balance = DEFAULT_BALANCE,
                deposited_total = 0.0,
                withdrawn_total = 0.0,
                realized_pnl    = 0.0,
                updated_at      = now,
                created_at      = now,
            )
            session.add(bal)
            await session.commit()
            await session.refresh(bal)
            logger.info("paper_balance_created", style=style_key, balance=DEFAULT_BALANCE)
        return bal


async def compute_spot_sizing(score: float, risk_pct: float) -> dict:
    """
    Balance-aware position sizing for opportunity_spot.

    Fixed-fractional risk: risk_dollar = balance × risk_fraction, where
    risk_fraction scales 1% → 2% with conviction (score 95 → 100).
    Notional = risk_dollar / (risk_pct / 100).

    No partial entries: if available balance cannot fund the FULL notional,
    can_open is False — entering a big opportunity with a small margin biases
    the risk-adjusted return, so we skip instead.

    Returns dict with: can_open, position_size, risk_dollar, balance,
    available, locked_margin, risk_fraction, reason.
    """
    bal = await get_or_create_balance("opportunity_spot")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style  == "opportunity_spot",
                PaperTrade.status == "open",
            )
        )
        open_trades = list(result.scalars().all())

    locked_margin = sum((t.position_size or 0.0) for t in open_trades)
    open_risk     = sum((t.risk_dollar  or 0.0) for t in open_trades)
    available     = bal.balance - locked_margin

    # Conviction scaling from RAW pre-weight score (§7.4, §10.2)
    span       = CONVICTION_CEIL - CONVICTION_FLOOR
    conviction = max(0.0, min(1.0, (score - CONVICTION_FLOOR) / span)) if span > 0 else 0.0
    risk_fraction = RISK_BASE_FRACTION + (RISK_MAX_FRACTION - RISK_BASE_FRACTION) * conviction

    # §15.5: proteksi drawdown dari puncak ekuitas — pendarahan pelan yang tidak
    # tertangkap circuit breaker harian. Drawdown > 10% dari peak → risk dipotong
    # setengah sampai ekuitas pulih ke ≤5% dari peak.
    async with AsyncSessionLocal() as dd_session:
        closed_pnls = (await dd_session.execute(
            select(PaperTrade.pnl_dollar).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status.in_(["tp", "sl", "manual"]),
                PaperTrade.pnl_dollar.isnot(None),
                PaperTrade.closed_at >= time.time() - 90 * 86400,
            ).order_by(PaperTrade.closed_at.asc())
        )).scalars().all()
    base_equity = bal.initial_balance + bal.deposited_total - bal.withdrawn_total
    equity, peak = base_equity, base_equity
    for p in closed_pnls:
        equity += p
        peak    = max(peak, equity)
    drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
    if drawdown_pct > 10.0:
        risk_fraction *= 0.5

    risk_dollar   = bal.balance * risk_fraction
    rp            = risk_pct if risk_pct > 0 else 2.0
    position_size = risk_dollar / (rp / 100)

    # Cap notional at 40% of balance (§12.4 — biggest size must not sit on the
    # most fragile stop); risk shrinks proportionally with the cap.
    max_notional = bal.balance * MAX_NOTIONAL_FRACTION
    if position_size > max_notional:
        position_size = max_notional
        risk_dollar   = position_size * (rp / 100)

    min_notional = max(MIN_NOTIONAL_ABS, bal.balance * MIN_NOTIONAL_FRACTION)

    # Discipline checks, most binding first
    can_open = True
    reason   = "ok"
    if len(open_trades) >= MAX_CONCURRENT_POSITIONS:
        can_open = False
        reason   = f"max {MAX_CONCURRENT_POSITIONS} posisi bersamaan (sekarang {len(open_trades)})"
    elif open_risk + risk_dollar > bal.balance * MAX_PORTFOLIO_RISK:
        can_open = False
        reason   = (f"portfolio heat: risk terbuka ${open_risk:,.2f} + ${risk_dollar:,.2f} "
                    f"> {MAX_PORTFOLIO_RISK:.0%} dari balance ${bal.balance:,.0f}")
    elif position_size < min_notional:
        can_open = False
        reason   = f"notional ${position_size:,.0f} < minimum ${min_notional:,.0f} (anti-debu)"
    elif position_size > available:
        can_open = False
        reason   = (f"available ${available:,.0f} < notional ${position_size:,.0f} "
                    f"(balance ${bal.balance:,.0f}, locked ${locked_margin:,.0f})")

    return {
        "can_open":       can_open,
        "position_size":  round(position_size, 2),
        "risk_dollar":    round(risk_dollar, 2),
        "risk_fraction":  round(risk_fraction, 4),
        "balance":        round(bal.balance, 2),
        "available":      round(available, 2),
        "locked_margin":  round(locked_margin, 2),
        "open_positions": len(open_trades),
        "open_risk":      round(open_risk, 2),
        "drawdown_pct":   round(drawdown_pct, 2),
        "reason":         reason,
    }


# ── Futures sizing (Phase 9) — leverage-aware, single shared wallet ───────────
FUTURES_RISK_BASE_FRACTION  = 0.01    # 1% of wallet at risk on a baseline setup
FUTURES_RISK_MAX_FRACTION   = 0.015   # up to 1.5% for high-conviction (conservative w/ leverage)
FUTURES_CONVICTION_FLOOR    = 72.0    # auto-open threshold — where conviction scaling starts
FUTURES_CONVICTION_CEIL     = 90.0    # full conviction (futures scores cap at 100)
FUTURES_MAX_CONCURRENT      = 6       # max open positions across BOTH agents (one wallet)
FUTURES_MIN_NOTIONAL_ABS    = 50.0    # never open dust positions
FUTURES_MAX_PORTFOLIO_RISK  = 0.06    # Σ open risk_dollar ≤ 6% of wallet
FUTURES_MAX_MARGIN_FRACTION = 0.35    # one position's margin ≤ 35% of wallet


async def compute_futures_sizing(score: float, risk_pct: float, leverage: int) -> dict:
    """
    Balance-aware sizing for the unified `futures` wallet (both agents share it).

    risk_dollar = wallet × risk_fraction (conviction-scaled, halved on >10% drawdown).
    notional    = risk_dollar / (risk_pct/100);  margin = notional / leverage.

    Caps total open risk (portfolio heat) and locked margin against ONE wallet so the
    portfolio cannot over-leverage into liquidation. Returns can_open + sizing fields.
    """
    bal = await get_or_create_balance("futures")
    lev = max(int(leverage or 1), 1)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(_FUTURES_AGENT_STYLES),
                PaperTrade.status == "open",
            )
        )
        open_trades = list(result.scalars().all())

    locked_margin = _locked_margin(open_trades)
    open_risk     = sum((t.risk_dollar or 0.0) for t in open_trades)
    available     = bal.balance - locked_margin

    # Conviction scaling from score (72 → 90 maps base → max)
    span       = FUTURES_CONVICTION_CEIL - FUTURES_CONVICTION_FLOOR
    conviction = max(0.0, min(1.0, (score - FUTURES_CONVICTION_FLOOR) / span)) if span > 0 else 0.0
    risk_fraction = FUTURES_RISK_BASE_FRACTION + (FUTURES_RISK_MAX_FRACTION - FUTURES_RISK_BASE_FRACTION) * conviction

    # Drawdown cut from realized P&L across both agents (mirror of spot §15.5)
    async with AsyncSessionLocal() as dd_session:
        closed_pnls = (await dd_session.execute(
            select(PaperTrade.pnl_dollar).where(
                PaperTrade.style.in_(_FUTURES_AGENT_STYLES),
                PaperTrade.status.in_(list(FUTURES_CLOSED_STATUSES)),
                PaperTrade.pnl_dollar.isnot(None),
                PaperTrade.closed_at >= time.time() - 90 * 86400,
            ).order_by(PaperTrade.closed_at.asc())
        )).scalars().all()
    base_equity = bal.initial_balance + bal.deposited_total - bal.withdrawn_total
    equity, peak = base_equity, base_equity
    for p in closed_pnls:
        equity += p
        peak    = max(peak, equity)
    drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0.0
    if drawdown_pct > 10.0:
        risk_fraction *= 0.5

    rp          = risk_pct if risk_pct and risk_pct > 0 else 2.0
    risk_dollar = bal.balance * risk_fraction
    notional    = risk_dollar / (rp / 100)
    margin      = notional / lev

    # Cap a single position's margin; risk shrinks proportionally with the cap
    max_margin = bal.balance * FUTURES_MAX_MARGIN_FRACTION
    if margin > max_margin:
        margin      = max_margin
        notional    = margin * lev
        risk_dollar = notional * (rp / 100)

    can_open = True
    reason   = "ok"
    if len(open_trades) >= FUTURES_MAX_CONCURRENT:
        can_open = False
        reason   = f"max {FUTURES_MAX_CONCURRENT} posisi futures bersamaan (sekarang {len(open_trades)})"
    elif open_risk + risk_dollar > bal.balance * FUTURES_MAX_PORTFOLIO_RISK:
        can_open = False
        reason   = (f"portfolio heat: risk ${open_risk:,.2f} + ${risk_dollar:,.2f} "
                    f"> {FUTURES_MAX_PORTFOLIO_RISK:.0%} dari wallet ${bal.balance:,.0f}")
    elif margin > available:
        can_open = False
        reason   = (f"margin ${margin:,.0f} > available ${available:,.0f} "
                    f"(wallet ${bal.balance:,.0f}, locked ${locked_margin:,.0f})")
    elif notional < FUTURES_MIN_NOTIONAL_ABS:
        can_open = False
        reason   = f"notional ${notional:,.0f} < minimum ${FUTURES_MIN_NOTIONAL_ABS:,.0f} (anti-debu)"

    return {
        "can_open":       can_open,
        "position_size":  round(notional, 2),
        "risk_dollar":    round(risk_dollar, 2),
        "margin":         round(margin, 2),
        "risk_fraction":  round(risk_fraction, 4),
        "balance":        round(bal.balance, 2),
        "available":      round(available, 2),
        "locked_margin":  round(locked_margin, 2),
        "open_positions": len(open_trades),
        "open_risk":      round(open_risk, 2),
        "drawdown_pct":   round(drawdown_pct, 2),
        "reason":         reason,
    }


# ── Ledger helper (Phase 9) ───────────────────────────────────────────────────
async def _record_txn(session, style_key: str, kind: str, amount: float,
                      balance_after: float, note: str | None = None) -> None:
    """Append a cash event to the balance_transactions ledger (within caller's session)."""
    session.add(BalanceTransaction(
        style         = style_key,
        kind          = kind,
        amount        = round(amount, 2),
        balance_after = round(balance_after, 2),
        note          = note or None,
        created_at    = time.time(),
    ))


@router.get("/balance/{style}")
async def get_balance(style: str) -> dict:
    """
    Current balance for a trading style.
    Returns balance, open equity, total P&L, and trade summary.
    """
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    style_key = STYLE_MAP.get(style, style)
    bal = await get_or_create_balance(style_key)

    # Compute open equity from open trades (futures wallet spans both agents)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(_wallet_trade_styles(style_key)),
                PaperTrade.status == "open",
            )
        )
        open_trades = list(result.scalars().all())

    open_count    = len(open_trades)
    locked_margin = _locked_margin(open_trades)
    available     = bal.balance - locked_margin
    total_pnl     = bal.balance - bal.initial_balance - bal.deposited_total + bal.withdrawn_total

    return {
        "style":           style_key,
        "balance":         round(bal.balance, 2),
        "initial_balance": round(bal.initial_balance, 2),
        "available":       round(available, 2),
        "locked_margin":   round(locked_margin, 2),
        "deposited_total": round(bal.deposited_total, 2),
        "realized_pnl":    round(bal.realized_pnl, 2),
        "total_pnl":       round(total_pnl, 2),
        "open_positions":  open_count,
        "updated_at":      bal.updated_at,
    }


class DepositRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to deposit (USD)")
    notes:  str   = Field(default="", description="Optional note for this deposit")


@router.post("/balance/{style}/deposit")
async def deposit_balance(style: str, body: DepositRequest) -> dict:
    """Add funds to paper balance. Simulates a real deposit."""
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    style_key = STYLE_MAP.get(style, style)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperBalance).where(PaperBalance.style == style_key)
        )
        bal = result.scalar_one_or_none()
        if bal is None:
            now = time.time()
            bal = PaperBalance(
                style           = style_key,
                balance         = DEFAULT_BALANCE + body.amount,
                initial_balance = DEFAULT_BALANCE,
                deposited_total = body.amount,
                withdrawn_total = 0.0,
                realized_pnl    = 0.0,
                updated_at      = now,
                created_at      = now,
                notes           = body.notes or None,
            )
            session.add(bal)
        else:
            bal.balance         += body.amount
            bal.deposited_total += body.amount
            bal.updated_at       = time.time()
            if body.notes:
                bal.notes = body.notes

        await _record_txn(session, style_key, "deposit", body.amount, bal.balance, body.notes)
        await session.commit()
        await session.refresh(bal)

    logger.info("paper_balance_deposit",
                style=style_key, amount=body.amount,
                new_balance=bal.balance)

    return {
        "style":           style_key,
        "deposited":       round(body.amount, 2),
        "balance":         round(bal.balance, 2),
        "deposited_total": round(bal.deposited_total, 2),
        "message":         f"Deposit ${body.amount:,.2f} berhasil. Saldo sekarang ${bal.balance:,.2f}",
    }


class ResetRequest(BaseModel):
    # F110: default from single source of truth in trading_costs.py
    initial_balance: float = Field(default=FUTURES_STARTING_BALANCE, gt=0)


@router.post("/balance/{style}/reset")
async def reset_balance(style: str, body: ResetRequest) -> dict:
    """Reset paper balance to a clean state. Used for testing / new cycle."""
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    style_key = STYLE_MAP.get(style, style)

    # §14.2: refuse reset while positions are open — locked margin would
    # immediately exceed the fresh balance (the exact bug we just cleaned up)
    async with AsyncSessionLocal() as guard_session:
        open_count = (await guard_session.execute(
            select(PaperTrade).where(
                PaperTrade.style  == style_key,
                PaperTrade.status == "open",
            ).limit(1)
        )).scalar_one_or_none()
        if open_count is not None:
            raise HTTPException(
                status_code=409,
                detail="Masih ada posisi terbuka. Tutup semua posisi dulu sebelum reset balance.",
            )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PaperBalance).where(PaperBalance.style == style_key)
        )
        bal = result.scalar_one_or_none()
        now = time.time()
        if bal is None:
            bal = PaperBalance(
                style           = style_key,
                balance         = body.initial_balance,
                initial_balance = body.initial_balance,
                deposited_total = 0.0,
                withdrawn_total = 0.0,
                realized_pnl    = 0.0,
                updated_at      = now,
                created_at      = now,
            )
            session.add(bal)
        else:
            bal.balance         = body.initial_balance
            bal.initial_balance = body.initial_balance
            bal.deposited_total = 0.0
            bal.withdrawn_total = 0.0
            bal.realized_pnl    = 0.0
            bal.updated_at      = now

        await _record_txn(session, style_key, "reset", body.initial_balance, bal.balance, "reset")
        await session.commit()
        await session.refresh(bal)

    logger.info("paper_balance_reset", style=style_key, balance=bal.balance)

    return {
        "style":   style_key,
        "balance": round(bal.balance, 2),
        "message": f"Balance di-reset ke ${bal.balance:,.2f}",
    }


# ── Withdraw (Phase 9) ────────────────────────────────────────────────────────

class WithdrawRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Amount to withdraw (USD)")
    notes:  str   = Field(default="", description="Optional note for this withdrawal")


@router.post("/balance/{style}/withdraw")
async def withdraw_balance(style: str, body: WithdrawRequest) -> dict:
    """Withdraw funds from a paper wallet. Refused if it exceeds available (free) capital."""
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    style_key = STYLE_MAP.get(style, style)
    bal = await get_or_create_balance(style_key)

    # available = balance − margin locked by open positions
    async with AsyncSessionLocal() as session:
        open_trades = list((await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(_wallet_trade_styles(style_key)),
                PaperTrade.status == "open",
            )
        )).scalars().all())
    locked    = _locked_margin(open_trades)
    available = bal.balance - locked

    if body.amount > available + 1e-9:
        raise HTTPException(
            status_code=422,
            detail=(f"Tidak bisa withdraw ${body.amount:,.2f}: dana bebas hanya "
                    f"${available:,.2f} (saldo ${bal.balance:,.2f}, terkunci margin ${locked:,.2f})."),
        )

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(PaperBalance).where(PaperBalance.style == style_key)
        )).scalar_one()
        row.balance         -= body.amount
        row.withdrawn_total += body.amount
        row.updated_at       = time.time()
        await _record_txn(session, style_key, "withdraw", -body.amount, row.balance, body.notes)
        await session.commit()
        await session.refresh(row)
        new_balance = row.balance

    logger.info("paper_balance_withdraw", style=style_key, amount=body.amount, new_balance=new_balance)

    return {
        "style":     style_key,
        "withdrawn": round(body.amount, 2),
        "balance":   round(new_balance, 2),
        "available": round(available - body.amount, 2),
        "message":   f"Withdraw ${body.amount:,.2f} berhasil. Saldo sekarang ${new_balance:,.2f}",
    }


# ── Balance-sheet statement (Phase 9) ─────────────────────────────────────────

@router.get("/balance/{style}/statement")
async def get_statement(style: str, limit: int = 100) -> dict:
    """
    Chronological balance sheet: cash events (deposit/withdraw/reset) merged with
    realized trade P&L, each with a running balance. Newest first.
    """
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database tidak tersedia")

    style_key = STYLE_MAP.get(style, style)
    bal = await get_or_create_balance(style_key)

    async with AsyncSessionLocal() as session:
        txns = list((await session.execute(
            select(BalanceTransaction).where(BalanceTransaction.style == style_key)
        )).scalars().all())
        trades = list((await session.execute(
            select(PaperTrade).where(
                PaperTrade.style.in_(_wallet_trade_styles(style_key)),
                PaperTrade.status.in_(["tp", "sl", "manual", "expired"]),
                PaperTrade.pnl_dollar.isnot(None),
            )
        )).scalars().all())

    events: list[dict] = []
    for t in txns:
        events.append({"ts": t.created_at or 0.0, "kind": t.kind,
                       "amount": t.amount, "label": (t.note or t.kind).title()})
    for tr in trades:
        events.append({"ts": tr.closed_at or 0.0, "kind": "trade",
                       "amount": round(tr.pnl_dollar or 0.0, 2),
                       "label": f"{tr.symbol} {tr.direction} {tr.status.upper()}"})

    # Running balance forward from the original base capital; reset re-baselines.
    events.sort(key=lambda e: e["ts"])
    running = bal.initial_balance
    for e in events:
        if e["kind"] == "reset":
            running = e["amount"]
        else:
            running += e["amount"]
        e["balance_after"] = round(running, 2)

    events.reverse()  # newest first for display
    return {
        "style":   style_key,
        "balance": round(bal.balance, 2),
        "events":  events[:limit],
        "count":   len(events),
    }
