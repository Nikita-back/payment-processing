import asyncio

import pytest
from alembic import command
from sqlalchemy import inspect

from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration


async def test_migrations_create_payment_and_outbox_tables(engine) -> None:
    async with engine.connect() as connection:
        tables, payment_columns, outbox_columns = await connection.run_sync(_schema)
    assert {"payments", "outbox"} <= tables
    assert {
        "id",
        "amount",
        "currency",
        "description",
        "metadata",
        "status",
        "idempotency_key",
        "webhook_url",
        "created_at",
        "processed_at",
    } <= payment_columns
    assert {
        "id",
        "aggregate_id",
        "event_type",
        "payload",
        "status",
        "created_at",
        "published_at",
    } <= outbox_columns


async def test_downgrade_removes_tables(engine) -> None:
    config = alembic_config()
    try:
        await asyncio.to_thread(command.downgrade, config, "base")
        async with engine.connect() as connection:
            tables, _, _ = await connection.run_sync(_schema)
        assert "payments" not in tables
        assert "outbox" not in tables
    finally:
        await asyncio.to_thread(command.upgrade, config, "head")


def _schema(connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    payment_columns = {column["name"] for column in inspector.get_columns("payments")} if "payments" in tables else set()
    outbox_columns = {column["name"] for column in inspector.get_columns("outbox")} if "outbox" in tables else set()
    return tables, payment_columns, outbox_columns
