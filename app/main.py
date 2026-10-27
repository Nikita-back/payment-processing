import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.errors import install_error_handlers
from app.api.router import router
from app.application.create_payment import CreatePayment
from app.application.get_payment import GetPayment
from app.config import Settings, get_settings
from app.infrastructure.db.engine import make_engine, make_session_factory
from app.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.messaging.relay import run_relay
from app.infrastructure.netpolicy import NetworkWebhookGuard

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    engine = make_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
    )
    session_factory = make_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)
    lifespan = _lifespan(settings, uow_factory) if settings.outbox_relay_enabled else None
    app = FastAPI(title="Payment processing", lifespan=lifespan)
    install_error_handlers(app)
    _install_database_handler(app)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.uow_factory = uow_factory
    app.state.create_payment = CreatePayment(
        NetworkWebhookGuard(allow_private_networks=settings.webhook_allow_private_networks)
    )
    app.state.get_payment = GetPayment()
    app.include_router(router)
    return app


def _install_database_handler(app: FastAPI) -> None:
    @app.exception_handler(OperationalError)
    async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
        logger.exception("database is unavailable")
        return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable"})


def _lifespan(settings: Settings, uow_factory):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        task = asyncio.create_task(run_relay(settings, uow_factory, stop))
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
