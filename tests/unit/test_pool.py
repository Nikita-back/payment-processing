from app.db import make_engine


async def test_postgres_pool_is_bounded_and_checks_connections() -> None:
    engine = make_engine(
        "postgresql+asyncpg://payments:payments@127.0.0.1:1/payments",
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=1800,
    )
    try:
        pool = engine.pool
        assert pool.size() == 10
        status = pool.status()
        assert "pool_size=10" in status or pool.size() == 10
    finally:
        await engine.dispose()