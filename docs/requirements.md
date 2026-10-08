# Соответствие заданию

Ниже каждый пункт ТЗ: что сделано и какой тест это подтверждает. Юнит-тесты работают на sqlite и подменах зависимостей. Интеграционные поднимают PostgreSQL 16 и RabbitMQ и, где нужен внешний вызов, ходят по настоящему HTTP.

## Сущность Payment

Поля: id, сумма, валюта (`RUB`, `USD`, `EUR`), описание, metadata, статус (`pending`, `succeeded`, `failed`), idempotency key, webhook URL, даты создания и обработки.

Реализация: `app/models.py` (`Payment`), миграция `alembic/versions/0001_initial.py`. Сумма — `Numeric(18, 2)`. Валюта и статус ограничены check-constraint. `request_hash` и `webhook_sent_at` в ответ API не входят: первое нужно, чтобы отличить повтор того же запроса от другого тела с тем же ключом, второе — чтобы не проводить платёж повторно, если webhook не доставился с первого раза.

- Юнит: `tests/unit/test_payments.py::test_create_writes_payment_and_outbox` — после создания в строке лежат сумма, валюта, metadata и статус `pending`.
- Юнит: `tests/unit/test_schemas.py` — валюта вне списка, нулевая и отрицательная сумма, больше двух знаков и лишнее поле отвергаются.
- Интеграция: `tests/integration/test_migrations.py::test_migrations_create_payment_and_outbox_tables` — после `alembic upgrade` в PostgreSQL есть обе таблицы и перечисленные колонки, включая `metadata`, `idempotency_key`, `webhook_url`, `created_at`, `processed_at`.
- Интеграция: `tests/integration/test_api.py::test_create_and_get_payment` — `GET` возвращает эти поля живого платежа.

## Таблица outbox

Реализация: модель `Outbox`, та же миграция. Строка хранит `aggregate_id`, тип `payments.new`, JSON payload, статус `pending` / `published` и `published_at`.

- Юнит: `tests/unit/test_payments.py::test_create_writes_payment_and_outbox` — payload содержит `payment_id` только что созданного платежа, статус `pending`.
- Юнит: `tests/unit/test_payments.py::test_failed_commit_keeps_database_empty` — если фиксация транзакции падает, не остаётся ни платежа, ни события.
- Интеграция: `tests/integration/test_migrations.py::test_downgrade_removes_tables` — `downgrade` убирает обе таблицы, повторный `upgrade` их возвращает (вызов в `finally`, чтобы следующие тесты видели схему).
- Интеграция: `tests/integration/test_api.py::test_idempotency_on_postgres` — на один платёж ровно одна строка outbox.

## POST /api/v1/payments

Заголовок `Idempotency-Key` обязателен. Тело: сумма, валюта, описание, metadata, `webhook_url`. Ответ `202 Accepted` с `payment_id`, статусом и `created_at`.

Реализация: `app/api.py`, схема `PaymentCreate` / `PaymentAccepted`.

- Юнит: `tests/unit/test_http.py::test_create_returns_accepted`.
- Юнит: `tests/unit/test_http.py::test_invalid_body_and_missing_idempotency_key` — нет ключа и кривое тело дают `422`.
- Интеграция: `tests/integration/test_api.py::test_create_and_get_payment`.

## GET /api/v1/payments/{payment_id}

Реализация: `app/api.py` (`read`), сборка ответа в `_details`.

- Юнит: `tests/unit/test_http.py::test_get_returns_payment` и `test_unknown_payment_returns_404`.
- Интеграция: `tests/integration/test_api.py::test_create_and_get_payment` и `test_auth_validation_and_missing_payment` (`404`).

## Аутентификация X-API-Key

Статический ключ из `API_KEY` на всех маршрутах `/api/v1`. Сравнение через `secrets.compare_digest`. Нет заголовка или чужой ключ — `401`.

- Юнит: `tests/unit/test_http.py::test_missing_and_wrong_api_key`.
- Интеграция: `tests/integration/test_api.py::test_auth_validation_and_missing_payment`.

## Идемпотентность

Тот же ключ и то же тело (хэш канонического JSON, `app/fingerprint.py`) возвращают уже созданный платёж и не пишут вторую строку. Тот же ключ и другое тело — `409`. Гонка двух одинаковых запросов упирается в уникальный индекс `ix_payments_idempotency_key`: второй запрос подхватывает уже вставленную строку.

- Юнит: `tests/unit/test_fingerprint.py` — порядок ключей metadata не меняет хэш, другая сумма меняет.
- Юнит: `tests/unit/test_payments.py::test_same_key_and_body_returns_existing_payment`, `test_same_key_and_different_body_conflicts`.
- Юнит: `tests/unit/test_http.py::test_idempotent_replay_and_conflict`.
- Интеграция: `tests/integration/test_api.py::test_idempotency_on_postgres`, `test_concurrent_create_with_one_key` — два параллельных POST дают один `payment_id` и одну строку в каждой таблице.

## Публикация payments.new и outbox

Создание платежа только пишет outbox. Отдельный цикл `run_relay` (`app/outbox.py`) забирает `pending` (`FOR UPDATE SKIP LOCKED` на PostgreSQL), публикует в обменник `payments` с ключом `payments.new` и только потом ставит `published`. Ошибка публикации откатывает отметку, строка остаётся `pending`.

Топология очередей: `app/topology.py`. Consumer подписывается на ту же спецификацию основной очереди (`app/consumer.py`).

- Юнит: `tests/unit/test_outbox.py::test_publish_pending_marks_row_published` и `test_publish_failure_leaves_row_pending`.
- Юнит: `tests/unit/test_publisher.py::test_outbox_publish_goes_to_payments_new` — ключ маршрутизации `payments.new`, сообщение persistent, заголовок `x-attempt = 0`.
- Юнит: `tests/unit/test_topology.py` — в спецификации есть `payments.new`, DLQ и две retry-очереди; очередь consumer совпадает со спецификацией.
- Интеграция: `tests/integration/test_relay.py::test_relay_publishes_payments_new_and_marks_outbox` — после публикации в живом RabbitMQ в `payments.new` лежит одно сообщение, строка outbox `published`.

## Consumer: шлюз, статус, webhook

Один обработчик `on_payment_new`. Эмуляция шлюза (`app/gateway.py`): `uniform(2, 5)` секунд и `random() < 0.9`. Отказ шлюза — это статус `failed`, а не повтор сообщения. Webhook (`app/webhook.py`) уходит после фиксации статуса. Если отправка падает, `webhook_sent_at` пустой, и следующая доставка сообщения шлёт webhook ещё раз, не вызывая шлюз.

В тестах пауза и датчик успеха подменяются, поэтому проверка 90/10 не зависит от случайности прогона: граница `0.89` — успех, `0.9` — отказ, в sleeper уходит значение из диапазона 2–5.

- Юнит: `tests/unit/test_gateway.py`.
- Юнит: `tests/unit/test_processing.py::test_success_updates_status_and_sends_webhook`, `test_decline_marks_payment_failed`, `test_webhook_failure_does_not_repeat_gateway`.
- Интеграция: `tests/integration/test_flow.py::test_processor_decline_and_webhook_retry_over_http` — PostgreSQL, шлюз с долей успеха 0, webhook на локальный HTTP-сервер, который дважды отвечает 500 и затем 200. Три реальных запроса, статус `failed`.
- Интеграция: `tests/integration/test_flow.py::test_queue_consumer_marks_success_and_calls_webhook` — сообщение из outbox доходит через RabbitMQ до consumer, `GET` показывает `succeeded` и `processed_at`, тестовый сервер получил тело с `payment_id` и суммой.

## Retry webhook

Три попытки, пауза `base * 2^n` между ними (по умолчанию 1с и 2с).

- Юнит: `tests/unit/test_webhook.py::test_webhook_retries_with_exponential_delay` фиксирует паузы `[1, 2]`; `test_webhook_raises_after_exhausted_attempts` — после трёх ответов 500 летит `WebhookDeliveryError`.
- Интеграция: тот же сценарий поверх сокета в `test_processor_decline_and_webhook_retry_over_http` (`probe.calls == 3`).

## Retry сообщения и DLQ

Три попытки обработки. После первой и второй ошибки сообщение уходит в очередь с TTL `base * 2^attempt` (по умолчанию 1с и 2с) и возвращается в `payments.new` с увеличенным `x-attempt`. Третья ошибка публикуется в `payments.dlx` / `payments.new.dlq`. Нечитаемое тело и отсутствие платежа (`PaymentNotFoundError`) в DLQ сразу: повтор их не починит.

Постоянный отказ шлюза (статус `failed`) сюда не входит — обработка при этом завершена успешно, если webhook доставлен.

- Юнит: `tests/unit/test_retry.py` — порог DLQ на третьей попытке и задержки 1000 / 2000 / 4000 мс.
- Юнит: `tests/unit/test_publisher.py::test_retry_uses_exponential_queue_then_dlq` — ключи `payments.new.retry.0`, `payments.new.retry.1`, затем DLQ.
- Юнит: `tests/unit/test_delivery.py` — временная ошибка планирует retry, постоянная и битое тело идут в DLQ, успешная обработка ничего не переотправляет.
- Юнит: `tests/unit/test_topology.py` — у retry-очередей TTL и dead-letter обратно в `payments.new`, у основной очереди dead-letter в DLX.
- Интеграция: `tests/integration/test_dlq.py::test_retry_queue_returns_message_to_main` — сообщение, отправленное в retry-очередь живого брокера, после TTL появляется в `payments.new`.
- Интеграция: `tests/integration/test_dlq.py::test_message_is_dead_lettered_after_three_attempts` — обработчик трижды бросает ошибку, счётчик вызовов равен 3, сообщение лежит в `payments.new.dlq`.

## Docker Compose

Сервисы `postgres`, `rabbitmq`, `api`, `consumer`. API сначала выполняет `alembic upgrade head`.

- Юнит: `tests/unit/test_compose.py` проверяет имена сервисов, образы и команду старта API.
- Интеграция использует те же образы PostgreSQL 16 и RabbitMQ 3.13, что и compose, и ту же миграцию, которой стартует контейнер `api`.

## Статус failed и очередь DLQ

Отказ эмуляции шлюза переводит платёж в `failed` и уведомляет webhook. В DLQ попадают сообщения, которые не удалось обработать: сбой записи, недоступный webhook после трёх попыток, битое тело, неизвестный платёж.
