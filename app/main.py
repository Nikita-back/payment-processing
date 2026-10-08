import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import build_router
from app.config import Settings, get_settings
from app.db import make_engine, make_session_factory
from app.outbox import run_relay


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    lifespan = _lifespan(settings, session_factory) if settings.outbox_relay_enabled else None
    app = FastAPI(title="Payment processing", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.include_router(build_router())
    return app


def _lifespan(settings: Settings, session_factory: async_sessionmaker[AsyncSession]):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        task = asyncio.create_task(run_relay(settings, session_factory, stop))
        try:
            yield
        finally:
            stop.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await app.state.engine.dispose()

    return lifespan
