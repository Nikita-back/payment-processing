from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.errors import UniqueViolation
from app.infrastructure.db.repositories import SqlAlchemyOutboxRepository, SqlAlchemyPaymentRepository


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self.payments: SqlAlchemyPaymentRepository
        self.outbox: SqlAlchemyOutboxRepository

    async def __aenter__(self) -> "SqlAlchemyUnitOfWork":
        self._session = self._session_factory()
        self.payments = SqlAlchemyPaymentRepository(self._session)
        self.outbox = SqlAlchemyOutboxRepository(self._session)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        try:
            if exc_type is not None and self._session is not None:
                await self.rollback()
        finally:
            if self._session is not None:
                await self._session.close()

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is closed")
        self.payments.flush()
        self.outbox.flush()
        try:
            await self._session.commit()
        except IntegrityError as exc:
            raise UniqueViolation() from exc

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is closed")
        await self._session.rollback()
        self.payments.clear()
        self.outbox.clear()
