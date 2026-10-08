import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.db import make_engine, make_session_factory
from app.main import create_app
from app.models import Base


@pytest.fixture
async def session_factory():
    engine = make_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = make_session_factory(engine)
    yield factory
    await engine.dispose()


@pytest.fixture
async def application():
    application = create_app(
        Settings(
            _env_file=None,
            database_url="sqlite+aiosqlite://",
            rabbitmq_url="amqp://guest:guest@localhost:5672/",
            api_key="test-key",
            outbox_relay_enabled=False,
        )
    )
    async with application.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(application):
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
