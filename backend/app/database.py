from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


settings = get_settings()
# EC4: multiple concurrent agents (scanner + monitor + auto_trader + risk_gate +
# weight_updater) hit the DB simultaneously.  Raise the pool to 20 + allow 10
# overflow connections; add a 5s wait timeout so exhaustion surfaces as a clear
# TimeoutError rather than a silent hang.
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping  = True,
    pool_size      = 20,
    max_overflow   = 10,
    pool_timeout   = 5,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

# ── DB availability flag ───────────────────────────────────────────────────────
# Set to True in main.py lifespan if create_db_schema() succeeds.
# Stays False when PostgreSQL is down — DB-dependent endpoints return 503.
_db_available: bool = False


def set_db_available(value: bool) -> None:
    global _db_available
    _db_available = value


def is_db_available() -> bool:
    return _db_available


async def require_db() -> None:
    """
    FastAPI dependency — raises 503 when PostgreSQL is unavailable.

    Usage:
        @router.get("/endpoint", dependencies=[Depends(require_db)])
    """
    if not _db_available:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable. Start PostgreSQL / Docker and restart the backend.",
        )


# ── Session helpers ────────────────────────────────────────────────────────────

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async SQLAlchemy session for FastAPI dependencies."""
    async with AsyncSessionLocal() as session:
        yield session


async def create_db_schema() -> None:
    """Create all registered tables and apply additive column migrations."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _migrate_columns(connection)


async def _migrate_columns(connection) -> None:
    """
    Idempotent ALTER TABLE migrations for new columns.
    Safe to run on every startup — skips columns that already exist.
    """
    migrations = [
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS leverage INTEGER",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS margin_type VARCHAR(10)",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS regime VARCHAR(20)",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS trail_sl FLOAT",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS trail_active BOOLEAN DEFAULT FALSE",
        # Real-balance tracking (v2)
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS position_size FLOAT",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS risk_dollar FLOAT",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS balance_snapshot FLOAT",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS pnl_dollar FLOAT",
        # §13.5: anti-duplikat — satu posisi open per (style, symbol);
        # partial unique index menutup race manual open vs auto-open
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_open_position_per_symbol "
        "ON paper_trades (style, symbol) WHERE status = 'open'",
        # SP1: signal performance enrichment columns
        "ALTER TABLE agent_signal_weights ADD COLUMN IF NOT EXISTS avg_pnl_pct FLOAT DEFAULT 0.0",
        "ALTER TABLE agent_signal_weights ADD COLUMN IF NOT EXISTS sample_count_raw INTEGER DEFAULT 0",
        # Phase 1 T4: big_mover_log forward-PnL horizons + dedup index
        "CREATE INDEX IF NOT EXISTS ix_big_mover_log_ts_symbol ON big_mover_log (ts, symbol)",
        "CREATE INDEX IF NOT EXISTS ix_big_mover_log_backfill ON big_mover_log (last_backfill_at)",
        # Phase 1 B1.2: force-open rate limit
        "CREATE INDEX IF NOT EXISTS ix_force_open_log_ts ON force_open_log (ts)",
        # PLAN_v2 P0.5 — per-trade heartbeat + denormalized setup_type
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS setup_type VARCHAR(20)",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS last_tick_at FLOAT",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS last_tick_price FLOAT",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS last_tick_pnl_pct FLOAT",
        "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS last_tick_event VARCHAR(40)",
        "CREATE INDEX IF NOT EXISTS ix_paper_trades_setup_type ON paper_trades (setup_type)",
        # PLAN_v2 P7.1 — rejection_log indexes (table created via Base.metadata.create_all)
        "CREATE INDEX IF NOT EXISTS ix_rl_symbol_ts ON rejection_log (symbol, rejected_at) "
        "WHERE EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='rejection_log')",
    ]
    for sql in migrations:
        try:
            await connection.execute(__import__("sqlalchemy").text(sql))
        except Exception:
            pass  # column may already exist on non-PG dialects


async def dispose_engine() -> None:
    """Dispose the global database engine on shutdown."""
    await engine.dispose()
