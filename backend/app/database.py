from collections.abc import AsyncGenerator

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


settings = get_settings()
engine = create_async_engine(settings.database_url, pool_pre_ping=True)
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
    """Create all registered tables. Raises on connection failure."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Dispose the global database engine on shutdown."""
    await engine.dispose()
