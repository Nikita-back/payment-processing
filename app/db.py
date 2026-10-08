import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


def make_engine(database_url: str) -> AsyncEngine:
    if database_url.startswith("sqlite"):
        return create_async_engine(
            database_url,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    return create_async_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def wait_for_schema(engine: AsyncEngine, attempts: int = 60) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1 FROM payments LIMIT 1"))
            return
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError("database schema is not ready") from last_error
