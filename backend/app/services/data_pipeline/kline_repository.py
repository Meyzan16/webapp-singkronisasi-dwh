from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kline import Kline
from app.schemas.kline import KlineCreate


class KlineRepository:
    """Database operations for kline records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_many(self, klines: Sequence[KlineCreate]) -> int:
        """Insert or update klines by pair, timeframe, and open_time."""

        if not klines:
            return 0

        values = [kline.model_dump() for kline in klines]
        statement = insert(Kline).values(values)
        update_columns = {
            column.name: getattr(statement.excluded, column.name)
            for column in Kline.__table__.columns
            if column.name != "id"
        }
        upsert = statement.on_conflict_do_update(
            index_elements=["pair", "timeframe", "open_time"],
            set_=update_columns,
        )
        await self._session.execute(upsert)
        await self._session.commit()
        return len(values)

    async def list_by_pair_timeframe(
        self,
        pair: str,
        timeframe: str,
        limit: int = 500,
    ) -> Sequence[Kline]:
        """Return recent klines for a pair and timeframe."""

        statement: Select[tuple[Kline]] = (
            select(Kline)
            .where(Kline.pair == pair.upper(), Kline.timeframe == timeframe)
            .order_by(Kline.open_time.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return list(reversed(result.scalars().all()))

    async def get_latest_open_time(self, pair: str, timeframe: str) -> int | None:
        """Return the newest open_time for a pair and timeframe."""

        statement = (
            select(Kline.open_time)
            .where(Kline.pair == pair.upper(), Kline.timeframe == timeframe)
            .order_by(Kline.open_time.desc())
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
