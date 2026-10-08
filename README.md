# Асинхронный сервис процессинга платежей

Сервис принимает запрос на оплату, сохраняет платёж и событие в одной транзакции, публикует событие в RabbitMQ и обрабатывает его отдельным consumer. Результат уходит на `webhook_url` клиента.

Исходное условие лежит в `docs/task.pdf`. Разбор каждого пункта и чем он закрыт — в `docs/requirements.md`.

## Стек

FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), PostgreSQL, RabbitMQ, FastStream, Alembic, Docker Compose.

## Запуск

```bash
docker compose up --build
```

Поднимаются `postgres`, `rabbitmq`, `api` (порт 8000) и `consumer`. Перед стартом API прогоняет миграции. Панель RabbitMQ: `http://localhost:15672` (`guest` / `guest`).

Ключ API задаётся переменной `API_KEY`. В compose для локального запуска стоит `dev-api-key`. Образец остальных переменных — `.env.example`.

## Примеры

Создание платежа:

```bash
curl -s -D - http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key" \
  -H "Idempotency-Key: order-42" \
  -d '{
    "amount": "100.50",
    "currency": "RUB",
    "description": "Оплата заказа 42",
    "metadata": {"order_id": "42"},
    "webhook_url": "https://example.com/payments/hook"
  }'
```

Ответ `202 Accepted`:

```json
{"payment_id": "...", "status": "pending", "created_at": "..."}
```

Повтор с тем же ключом и тем же телом возвращает тот же `payment_id`. Тот же ключ и другое тело — `409`. Без ключа API или с неверным ключом — `401`.

Чтение:

```bash
curl -s http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: dev-api-key"
```

Валюта: `RUB`, `USD`, `EUR`. Сумма больше нуля, не больше двух знаков после запятой.

## Как проходит платёж

1. `POST /api/v1/payments` пишет строку в `payments` и событие `payments.new` в `outbox` одной транзакцией.
2. Relay в процессе API публикует неопубликованные строки в обменник `payments`. Если брокер недоступен, платёж остаётся в outbox и уходит следующим циклом.
3. Consumer читает очередь `payments.new`, проводит платёж через эмуляцию шлюза (пауза 2–5 секунд, около 90% успех и 10% отказ), сохраняет `succeeded` или `failed` и отправляет webhook.
4. Ошибка отправки webhook повторяется 3 раза с паузой 1с, 2с. Если webhook так и не доставлен, сообщение обрабатывается повторно, но шлюз второй раз не вызывается.
5. Сбой самой обработки сообщения: пауза 1с, затем 2с, всего 3 попытки. После этого сообщение попадает в `payments.new.dlq`.

## Отказоустойчивость

Приём платежа не ждёт RabbitMQ: событие лежит в `outbox`, пока брокер не подтвердит публикацию. Повторная доставка не проводит платёж второй раз, пока действует захват обработки или статус уже конечный. Очереди устойчивые, сообщения persistent, у consumer ограничен prefetch. Пул PostgreSQL проверяет соединение перед выдачей и пересоздаёт его по таймеру.

Webhook на внутренние адреса (`localhost`, частные и link-local сети, в том числе адрес метаданных облака) отклоняется. Редиректы не выполняются. В журнал пишется только хост webhook, без query-строки. Ошибка базы на запросе возвращает `503` без текста SQL.

Полный прогон тестов и разбор каждой проверки лежат в `docs/test-run.log` и `docs/requirements.md`.

## Тесты

Нужен Docker: интеграционные тесты поднимают PostgreSQL и RabbitMQ.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

`tests/unit` не требует Docker. `tests/integration` проверяет миграции, API, outbox, webhook по HTTP, очередь, ретраи и DLQ.
