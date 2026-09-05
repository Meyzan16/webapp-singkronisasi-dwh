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
from app.services.trading_costs import FUTURES_STARTING_BALANCE, FUTURES_BALANCE_STATUSES

router = APIRouter(tags=["balance"])
logger = structlog.get_logger(__name__)

# Phase 9: futures is ONE wallet ("futures") that both agents draw from.
STYLE_MAP = {
    "spot":    "opportunity_spot",
    "futures": "futures",
}

# Trades are tagged per agent, but they all settle into the single "futures" wallet.
# Semua lane futures berbagi SATU wallet cross-margin (Phase 2 BM1), jadi daftar
# ini harus selalu lengkap — diambil dari registry tunggal supaya lane baru tak
# pernah tertinggal dan salah hitung margin.
from app.services.agent_registry import FUTURES_AGENTS as _FUTURES_AGENTS  # noqa: E402

_FUTURES_AGENT_STYLES = _FUTURES_AGENTS


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
MAX_CONCURRENT_POSITIONS = 5      # capital concentrated in best setups only
# Lantai anti-posisi-debu. KEDUANYA harus dilihat bersama: yang berlaku adalah
# `max(ABS, balance × FRACTION)`, jadi menurunkan salah satu saja sering tak
# berefek — dengan balance $1.070, menurunkan ABS 150→50 tetap menghasilkan
# max(50, 160) = 160.
#
# TEMUAN 9 Agu 2026 (dari 303 blokir di log satu sesi): scanner menemukan
# kandidat berskor 90–108 tapi TIDAK SATU PUN bisa dibuka. Notional yang
# dihitung mengumpul di $54–70 (median $56) sementara ambangnya $161 — jadi
# gerbang ini memblokir 100% auto-open, dan seluruh mesin belajar ikut macet
# karena tak ada trade baru: 15 entry dalam 14 hari, nol posisi terbuka, dan
# canary butuh ~105–210 hari untuk mengumpulkan 15 exit.
#
# Angka 150/15% tampaknya dirancang untuk akun jauh lebih besar. Pada akun
# $1.070 ia bukan pelindung dari posisi debu melainkan pemblokir total: dengan
# batas 5 posisi bersamaan, minimum $161 berarti 75% akun terpakai saat penuh.
# 50/5% menahan porsi itu di 25% — jadi ini justru MENGURANGI konsentrasi,
# bukan melonggarkan disiplin.
#
# Risiko per trade sengaja TIDAK dinaikkan: menaikkannya ke 1,5% hanya membuka
# 14% kandidat sambil memperbesar kerugian per trade 50% — membayar mahal untuk
# perbaikan kecil.
MIN_NOTIONAL_ABS         = 50.0   # never open dust positions
MIN_NOTIONAL_FRACTION    = 0.05   # ...or 5% of balance, whichever is higher
MAX_NOTIONAL_FRACTION    = 0.40   # one position never exceeds 40% of balance
# PLAN_SPOT_LANES S7 (opsi B): portfolio heat HARUS sama dengan batas rugi harian.
# Dulu 4% sementara circuit breaker harian 3% — portofolio boleh dimuati sampai 4%
# risiko, jadi bila semua posisi stop di hari yang sama, batas harian terlampaui
# SEBELUM breaker sempat menyala. Dua rem, dua angka, saling bertabrakan.
# Scheduler meneruskan nilai HIDUP `spot.daily_loss_limit_pct` lewat parameter
# `max_portfolio_risk`, sehingga mengubah satu angka di config menggerakkan keduanya.
MAX_PORTFOLIO_RISK       = 0.03   # = DAILY_LOSS_LIMIT_FRACTION di scheduler


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


async def compute_spot_sizing(
    score: float,
    risk_pct: float,
    risk_fraction_override: float | None = None,
    risk_multiplier: float = 1.0,
    max_portfolio_risk: float | None = None,
) -> dict:
    """
    Balance-aware position sizing for opportunity_spot.

    Fixed-fractional risk: risk_dollar = balance × risk_fraction, where
    risk_fraction scales 1% → 2% with conviction (score 95 → 100).
    Notional = risk_dollar / (risk_pct / 100).

    risk_fraction_override (PLAN_v5 Group A): kalau di-set, pakai nilai ini
    sebagai risk_fraction (mengabaikan conviction scaling) — dipakai Early Radar
    yang risk-nya ½ normal (0.5%) karena micro-cap lebih berisiko. Drawdown
    halving tetap berlaku di atasnya.

    risk_multiplier (PLAN_SPOT_LANES B-Fix 6): rem lane — 0.5 saat ekspektasi lane
    berbalik negatif. Dikalikan SETELAH override/conviction dipilih, jadi ia berlaku
    di kedua jalur. Sebelumnya rem ini hidup di scheduler dan hanya menempel pada
    jalur Kelly, sehingga terlewat diam-diam ketika probabilitas learning belum ada.

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
    if risk_fraction_override is not None:
        risk_fraction = risk_fraction_override
    else:
        risk_fraction = RISK_BASE_FRACTION + (RISK_MAX_FRACTION - RISK_BASE_FRACTION) * conviction

    # B-Fix 6: rem lane berlaku untuk kedua jalur di atas, bukan hanya jalur Kelly.
    if risk_multiplier != 1.0:
        risk_fraction *= max(0.0, risk_multiplier)

    # §15.5: proteksi drawdown dari puncak ekuitas — pendarahan pelan yang tidak
    # tertangkap circuit breaker harian. Drawdown > 10% dari peak → risk dipotong
    # setengah sampai ekuitas pulih ke ≤5% dari peak.
    async with AsyncSessionLocal() as dd_session:
        closed_pnls = (await dd_session.execute(
            select(PaperTrade.pnl_dollar).where(
                PaperTrade.style == "opportunity_spot",
                PaperTrade.status.in_(["tp", "sl", "manual", "expired"]),
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

    # S7 opsi B: plafon portfolio heat. Pemanggil (scheduler) meneruskan nilai HIDUP
    # `spot.daily_loss_limit_pct` supaya rem portofolio dan rem harian selalu satu
    # angka; tanpa parameter, pakai konstanta modul yang nilainya sama.
    heat_cap = max_portfolio_risk if max_portfolio_risk is not None else MAX_PORTFOLIO_RISK

    # Discipline checks, most binding first
    can_open = True
    reason   = "ok"
    if len(open_trades) >= MAX_CONCURRENT_POSITIONS:
        can_open = False
        reason   = f"max {MAX_CONCURRENT_POSITIONS} posisi bersamaan (sekarang {len(open_trades)})"
    elif open_risk + risk_dollar > bal.balance * heat_cap:
        can_open = False
        reason   = (f"portfolio heat: risk terbuka ${open_risk:,.2f} + ${risk_dollar:,.2f} "
                    f"> {heat_cap:.0%} dari balance ${bal.balance:,.0f}")
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
        "heat_cap":       round(heat_cap, 4),      # S7: plafon yang benar-benar dipakai
        "drawdown_pct":   round(drawdown_pct, 2),
        "reason":         reason,
    }


# ── Futures sizing (Phase 9) ─ leverage-aware, single shared wallet ──────────
#
# Fase 1a (5 Sep 2026): angka-angka ini kini NILAI BEKU — cadangan saat DB tak
# terbaca. Nilai yang benar-benar dipakai datang dari `agents.futures.sizing_config`
# (tabel `agent_config`), sehingga risiko per trade dan plafon margin bisa diubah
# tanpa deploy. Sebelum ini, rantai yang menentukan BERAPA BESAR uang masuk justru
# satu-satunya bagian yang sama sekali tak bisa ditala: 18 konstanta, 0 dibaca
# dari config, sementara 141 kunci lain sudah dinamis.
#
# Nilai di sini WAJIB sama persis dengan `_FROZEN` di sizing_config — keduanya
# dipakai sebagai `default` saat membaca config, dan perbedaan di antara keduanya
# akan membuat perilaku berubah diam-diam saat DB kebetulan tak terbaca.
FUTURES_RISK_BASE_FRACTION  = 0.01    # 1% of wallet at risk on a baseline setup
FUTURES_RISK_MAX_FRACTION   = 0.015   # up to 1.5% for high-conviction (conservative w/ leverage)
FUTURES_CONVICTION_FLOOR    = 72.0    # auto-open threshold — where conviction scaling starts
FUTURES_CONVICTION_CEIL     = 90.0    # full conviction (futures scores cap at 100)
FUTURES_MAX_CONCURRENT      = 6       # max open positions across BOTH agents (one wallet)
FUTURES_MIN_NOTIONAL_ABS    = 50.0    # never open dust positions
FUTURES_MAX_PORTFOLIO_RISK  = 0.06    # Σ open risk_dollar ≤ 6% of wallet
FUTURES_MAX_MARGIN_FRACTION = 0.35    # one position's margin ≤ 35% of wallet
FUTURES_MAX_NOTIONAL_FRACTION = 1.5   # BUG-L4: one position's notional ≤ 1.5× wallet
# Pemotong risiko saat drawdown — dulu dua angka telanjang di tengah fungsi.
FUTURES_DRAWDOWN_CUT_PCT    = 10.0    # drawdown dari puncak > ini → risiko dipotong
FUTURES_DRAWDOWN_RISK_MULT  = 0.5     # …sebesar pengali ini


async def compute_futures_sizing(score: float, risk_pct: float, leverage: int) -> dict:
    """
    Balance-aware sizing for the unified `futures` wallet (both agents share it).

    risk_dollar = wallet × risk_fraction (conviction-scaled, halved on >10% drawdown).
    notional    = risk_dollar / (risk_pct/100);  margin = notional / leverage.

    Caps total open risk (portfolio heat) and locked margin against ONE wallet so the
    portfolio cannot over-leverage into liquidation. Returns can_open + sizing fields.
    """
    # Fase 1a: seluruh ambang di bawah dibaca dari `agent_config` lewat
    # sizing_config; konstanta modul hanya cadangan saat DB tak terbaca.
    from agents.futures import sizing_config as szcfg
    await szcfg.refresh()

    _risk_base   = szcfg.risk_fraction_base()
    _risk_max    = szcfg.risk_fraction_max()
    _conv_floor  = szcfg.get("size_conviction_floor")
    _conv_ceil   = szcfg.get("size_conviction_ceil")
    _max_conc    = int(szcfg.get("max_auto_positions"))   # satu kunci dgn auto_trader
    _min_not_abs = szcfg.get("size_min_notional_abs")
    _heat_cap    = szcfg.portfolio_max_risk_fraction()
    _max_margin  = szcfg.max_margin_fraction()
    _max_not_mlt = szcfg.get("size_max_notional_mult")
    _dd_cut      = szcfg.get("size_drawdown_cut_pct")
    _dd_mult     = szcfg.get("size_drawdown_risk_mult")

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
    span       = _conv_ceil - _conv_floor
    conviction = max(0.0, min(1.0, (score - _conv_floor) / span)) if span > 0 else 0.0
    risk_fraction = _risk_base + (_risk_max - _risk_base) * conviction

    # Drawdown cut from realized P&L across both agents (mirror of spot §15.5)
    async with AsyncSessionLocal() as dd_session:
        closed_pnls = (await dd_session.execute(
            select(PaperTrade.pnl_dollar).where(
                PaperTrade.style.in_(_FUTURES_AGENT_STYLES),
                PaperTrade.status.in_(list(FUTURES_BALANCE_STATUSES)),   # BUG-L19: include expired
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
    if drawdown_pct > _dd_cut:
        risk_fraction *= _dd_mult

    rp          = risk_pct if risk_pct and risk_pct > 0 else 2.0
    risk_dollar = bal.balance * risk_fraction
    notional    = risk_dollar / (rp / 100)

    # BUG-L4: cap notional per position so a tiny SL can't inflate size to a multiple of
    # the wallet (tiny rp → huge notional → small adverse move = outsized $ loss).
    max_notional = bal.balance * _max_not_mlt
    if notional > max_notional:
        notional    = max_notional
        risk_dollar = min(risk_dollar, notional * (rp / 100))
    margin = notional / lev

    # Cap a single position's margin. BUG-L9: use min() so capping never RAISES risk_dollar
    # above the intended fixed-fractional risk (the old code re-derived it upward).
    max_margin = bal.balance * _max_margin
    if margin > max_margin:
        margin      = max_margin
        notional    = margin * lev
        risk_dollar = min(risk_dollar, notional * (rp / 100))

    can_open = True
    reason   = "ok"
    if len(open_trades) >= _max_conc:
        can_open = False
        reason   = f"max {_max_conc} posisi futures bersamaan (sekarang {len(open_trades)})"
    elif open_risk + risk_dollar > bal.balance * _heat_cap:
        can_open = False
        reason   = (f"portfolio heat: risk ${open_risk:,.2f} + ${risk_dollar:,.2f} "
                    f"> {_heat_cap:.0%} dari wallet ${bal.balance:,.0f}")
    elif margin > available:
        can_open = False
        reason   = (f"margin ${margin:,.0f} > available ${available:,.0f} "
                    f"(wallet ${bal.balance:,.0f}, locked ${locked_margin:,.0f})")
    elif notional < _min_not_abs:
        can_open = False
        reason   = f"notional ${notional:,.0f} < minimum ${_min_not_abs:,.0f} (anti-debu)"

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
                PaperTrade.style.in_(_wallet_trade_styles(style_key)),
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
