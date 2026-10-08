import os
from pathlib import Path

import aio_pika
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.rabbitmq import RabbitMqContainer

from app.config import Settings
from app.db import make_engine
from app.main import create_app
from app.topology import declare_topology, queue_specs

ROOT = Path(__file__).resolve().parents[2]


def to_asyncpg(url: str) -> str:
    return "postgresql+asyncpg://" + url.split("://", 1)[1]


def alembic_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    return config


@pytest.fixture(scope="session")
def database_url():
    with PostgresContainer("postgres:16-alpine") as postgres:
        url = to_asyncpg(postgres.get_connection_url())
        os.environ["DATABASE_URL"] = url
        command.upgrade(alembic_config(), "head")
        yield url


@pytest.fixture(scope="session")
def rabbitmq_url():
    with RabbitMqContainer("rabbitmq:3.13-management-alpine") as rabbit:
        params = rabbit.get_connection_params()
        vhost = "" if params.virtual_host == "/" else params.virtual_host
        yield (
            f"amqp://{params.credentials.username}:{params.credentials.password}"
            f"@{params.host}:{params.port}/{vhost}"
        )


@pytest.fixture
def settings(database_url, rabbitmq_url):
    return Settings(
        _env_file=None,
        database_url=database_url,
        rabbitmq_url=rabbitmq_url,
        api_key="test-key",
        outbox_relay_enabled=False,
        retry_base_delay_ms=200,
        max_delivery_attempts=3,
        webhook_attempts=3,
        webhook_retry_base_seconds=0.05,
        webhook_timeout_seconds=2,
        gateway_min_delay_seconds=0,
        gateway_max_delay_seconds=0,
        gateway_success_rate=1,
    )


@pytest.fixture
async def engine(database_url):
    engine = make_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_database(engine):
    await _truncate(engine)
    yield
    await _truncate(engine)


@pytest.fixture(autouse=True)
async def clean_broker(rabbitmq_url):
    await declare_topology(rabbitmq_url, 200, 3)
    await purge_queues(rabbitmq_url)
    yield
    await purge_queues(rabbitmq_url)


@pytest.fixture
async def api(settings):
    application = create_app(settings)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, application
    await application.state.engine.dispose()


async def _truncate(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE outbox, payments RESTART IDENTITY CASCADE"))


async def purge_queues(url: str) -> None:
    connection = await aio_pika.connect_robust(url)
    try:
        channel = await connection.channel()
        for spec in queue_specs(200, 3):
            queue = await channel.declare_queue(spec.name, durable=True, arguments=spec.arguments)
            await queue.purge()
    finally:
        await connection.close()


async def queue_depth(url: str, name: str) -> int:
    connection = await aio_pika.connect_robust(url)
    try:
        channel = await connection.channel()
        queue = await channel.declare_queue(name, passive=True)
        return int(queue.declaration_result.message_count)
    finally:
        await connection.close()
