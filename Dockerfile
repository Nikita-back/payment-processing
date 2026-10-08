FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker/start-api.sh /start-api.sh

RUN pip install --no-cache-dir . \
    && chmod 755 /start-api.sh

USER nobody

CMD ["python", "-m", "app.consumer"]
