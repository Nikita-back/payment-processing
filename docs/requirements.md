# Соответствие заданию

Источник задания: `docs/task.pdf`. Разбор ниже опирается на прогон `docs/test-run.log`.

## Разбор лога

Команда: `pytest -vv --tb=short -rA --log-cli-level=INFO`. В `pyproject.toml` включено `filterwarnings = ["error"]`: любое предупреждение Python роняет прогон.

Итог в конце лога: `91 passed in 13.76s`. Секций `warnings summary` и строк `FAILED` нет. Секция `PASSES` перечисляет все 91 теста по одному.

Готовность RabbitMQ ждёт строку `Server startup complete` в логе контейнера. Устаревший декоратор `@wait_container_is_ready` не импортируется, поэтому в логе нет `DeprecationWarning` и нет рукопожатий pika до старта брокера.

В логе нет тел запросов с ключом API и нет текста SQL из обработчика `503`.

## Поля платежа

| Требование | Где | Доказательство |
|---|---|---|
| Уникальный `payment_id` (UUID) | `app/payments.py`, `app/models.py` | `test_create_returns_accepted` проверяет UUID. `test_create_writes_payment_and_outbox` видит строку в БД. `test_create_and_get_payment` читает тот же id из PostgreSQL. `test_create_persists_single_row` — ровно одна строка на создание. |
| Сумма — десятичная, больше нуля, 2 знака | `Numeric(18, 2)`, `PaymentCreate.amount` | `test_amount_lower_bound_is_one_cent` принимает `0.01`. `test_rejects_invalid_payment_body[overrides2]` — `0`, `[overrides3]` — отрицательная, `[overrides4]` — три знака. `test_details_serialize_amount_with_two_decimals` отдаёт строку с двумя знаками. Check `amount > 0` в миграции `0001`. |
| Валюта только `RUB` / `USD` / `EUR` | `Literal` в схеме, check в миграции | `test_accepts_supported_currencies` и `test_accepts_each_currency` по каждой валюте. `overrides0` — `GBP`, `overrides1` — `rub` в нижнем регистре. |
| Описание | строка до 2000 символов, по умолчанию пустая | `test_accepts_payment_body`. `test_rejects_long_description` — 2001 символ. |
| `metadata` — JSON-объект | колонка `JSON`, лимит 8192 байта | `test_accepts_payment_body`. `test_rejects_oversized_metadata`. `test_create_and_get_payment` читает metadata обратно из PostgreSQL. |
| Статусы `pending` / `succeeded` / `failed` | check в модели и миграции | Создание отдаёт `pending`: `test_create_returns_accepted`. Успех: `test_success_updates_status_and_sends_webhook`, `test_queue_consumer_marks_success_and_calls_webhook`. Отказ шлюза: `test_decline_marks_payment_failed`, `test_processor_decline_and_webhook_retry_over_http`. |
| `idempotency_key` | уникальный индекс `ix_payments_idempotency_key` | `test_idempotent_replay_and_conflict`, `test_idempotency_on_postgres`, `test_concurrent_create_with_one_key`. Ключ со спецсимволами SQL хранится как данные: `test_idempotency_key_is_stored_as_data`. |
| `webhook_url` | `AnyHttpUrl` плюс сетевой фильтр | Публичный URL: `test_public_url_is_allowed`. Не URL: `overrides5`. |
| `created_at` в ответе создания | `PaymentAccepted` | `test_create_returns_accepted` — поле с таймзоной. |
| `processed_at` после обработки | проставляется в `PaymentProcessor` | `test_success_updates_status_and_sends_webhook`, `test_queue_consumer_marks_success_and_calls_webhook`. |

Внутренние колонки `request_hash`, `webhook_sent_at`, `gateway_claimed_at` в ответ API не входят: `test_get_hides_internal_columns`.

## `POST /api/v1/payments`

Обязательный заголовок `Idempotency-Key`. Тело: `amount`, `currency`, `description`, `metadata`, `webhook_url`. Ответ `202`: `payment_id`, `status`, `created_at`.

- Успех: `test_create_returns_accepted` (SQLite) и `test_create_and_get_payment` (PostgreSQL).
- Нет заголовка и кривое тело: `test_invalid_body_and_missing_idempotency_key`. Лишнее поле: `overrides6`.
- Пустой и пробельный ключ: `400`, `test_blank_idempotency_key_is_rejected`.
- Тот же ключ и то же тело — тот же платёж, `202`, текущий статус, без второй строки: `test_same_key_and_body_returns_existing_payment`, `test_idempotent_replay_and_conflict`, `test_idempotency_on_postgres`. Отпечаток тела — SHA-256 канонического JSON: `test_same_payload_has_stable_hash`, другая сумма меняет отпечаток: `test_different_amount_changes_hash`.
- Тот же ключ и другое тело — `409`: `test_same_key_and_different_body_conflicts`, `test_idempotency_on_postgres`.
- Два параллельных запроса с одним ключом оставляют одну строку: `test_concurrent_create_with_one_key`.
- Платёж и outbox пишутся одним commit. Сбой commit откатывает оба: `test_failed_commit_keeps_database_empty`.

## `GET /api/v1/payments/{payment_id}`

Полная карточка платежа: `test_get_returns_payment`, `test_create_and_get_payment`. Неизвестный id — `404`: `test_unknown_payment_returns_404`, `test_get_missing_payment`, `test_auth_validation_and_missing_payment`.

## Статический `X-API-Key`

На обоих методах, сравнение через `secrets.compare_digest`. Нет ключа и неверный ключ — `401`, тело не повторяет присланный секрет: `test_missing_and_wrong_api_key`, `test_rejects_private_webhook_and_keeps_api_key_out_of_the_body`, `test_auth_validation_and_missing_payment`. Пустой `API_KEY` в настройках не принимается валидатором `Settings`.

## Очередь `payments.new` и один consumer

Создание кладёт событие `payments.new` в outbox, а не сразу в брокер. Relay публикует в exchange `payments` с routing key `payments.new`.

- Строка outbox появляется вместе с платежом: `test_create_writes_payment_and_outbox`.
- Пока relay не отработал, статус outbox `pending` и глубина `payments.new` равна 0: `test_create_leaves_outbox_pending_until_relay`.
- После публикации строка `published`, в очереди одно сообщение: `test_publish_pending_marks_row_published`, `test_relay_publishes_payments_new_and_marks_outbox`, `test_outbox_publish_goes_to_payments_new`.
- Сбой публикации оставляет строку `pending`: `test_publish_failure_leaves_row_pending`. Если в пачке вторая публикация упала, первая уже `published`: `test_published_row_stays_published_when_next_publish_fails`.
- Второй relay не берёт строку, залоченную первым (`FOR UPDATE SKIP LOCKED`): `test_second_relay_skips_row_locked_by_the_first`.
- Один consumer читает `payments.new`, вызывает шлюз, пишет статус, шлёт webhook: `test_queue_consumer_marks_success_and_calls_webhook`. Успешная доставка не публикуется повторно: `test_success_acks_without_republish`.

Шлюз: пауза из диапазона 2–5 с и порог 90%. Ниже порога — успех, на границе `0.9` — отказ: `test_gateway_succeeds_below_success_rate`, `test_gateway_fails_at_success_rate_boundary`. В тестах генератор и sleep подменяются, чтобы не зависеть от случайности.

Webhook после смены статуса. Отказ шлюза тоже уходит в webhook, статус остаётся `failed`: `test_decline_marks_payment_failed`, `test_processor_decline_and_webhook_retry_over_http`. Ошибки отправки повторяются с паузой `base * 2^n` (1 с, затем 2 с), всего 3 попытки: `test_webhook_retries_with_exponential_delay`, `test_webhook_raises_after_exhausted_attempts`. Повторная доставка сообщения не вызывает шлюз снова, если статус уже конечный: `test_webhook_failure_does_not_repeat_gateway`.

## Outbox, ретраи, DLQ

Топология: durable direct exchange `payments`, DLX `payments.dlx`, очередь `payments.new`, retry-очереди `payments.new.retry.0` и `payments.new.retry.1` с TTL `base * 2^attempt` (по умолчанию 1000 мс и 2000 мс), DLQ `payments.new.dlq`. У всех очередей `x-queue-type=classic`, чтобы объявление из aio-pika и FastStream совпадало. Заголовок попытки `x-attempt`, по умолчанию 0.

- Состав очередей: `test_topology_has_main_queue_dlq_and_retry_queues`, consumer подписан на основную: `test_consumer_queue_uses_main_spec`.
- Формула задержки и момент ухода в DLQ: `test_delay_doubles_each_attempt`, `test_dead_letter_after_third_attempt`, `test_retry_routing_key_matches_attempt`, `test_read_attempt_defaults_to_zero`, `test_retry_uses_exponential_queue_then_dlq`.
- Живой RabbitMQ: TTL retry-очереди возвращает сообщение в `payments.new`: `test_retry_queue_returns_message_to_main`. Три неудачи — сообщение в DLQ, обработчик вызван 3 раза: `test_message_is_dead_lettered_after_three_attempts`.
- Временная ошибка обработки уходит в retry: `test_transient_error_schedules_retry`. Постоянная (нет платежа, битый payload) сразу в DLQ: `test_permanent_error_goes_to_dlq`, `test_unreadable_message_goes_to_dlq`, `test_missing_payment_is_permanent`.
- Отказ шлюза (`failed`) не считается ошибкой сообщения, если webhook доставлен.

Публикация ждёт confirm брокера (`publisher_confirms`). Prefetch consumer по умолчанию 8.

## Миграции и Docker

Alembic `0001` создаёт `payments` и `outbox`, `0002` добавляет `gateway_claimed_at`. `test_migrations_create_payment_and_outbox_tables` проверяет таблицы на PostgreSQL 16. `test_downgrade_removes_tables` откатывает до пустой схемы и поднимает head обратно.

`docker-compose.yml`: `postgres:16-alpine`, `rabbitmq:3.13-management-alpine`, `api`, `consumer`. Старт API: `alembic upgrade head`, затем `uvicorn app.main:create_app --factory`. README содержит команду запуска и примеры с `X-API-Key` и `Idempotency-Key`: `test_compose_declares_required_services`, `test_api_entrypoint_runs_migrations`, `test_readme_has_run_and_examples`.

## Безопасность

Фильтр webhook (`app/netpolicy.py`) по умолчанию запрещает не-http(s), userinfo в URL, `localhost`, `*.local`, хосты метаданных облака и любой неглобальный IP (частные сети, loopback, link-local, включая `169.254.169.254` и `::1`). Если DNS не ответил, имя остаётся допустимым, чтобы не резать внешние хосты из-за временного сбоя резолва. Если резолв вернул неглобальный адрес — отказ.

- Каждый запрещённый URL: параметризация `test_private_and_credential_urls_are_rejected` (9 случаев).
- Публичный `https://example.com/...` проходит: `test_public_url_is_allowed`.
- Флаг `webhook_allow_private_networks` нужен только тестам с локальным приёмником: `test_private_url_is_allowed_when_flag_is_on`. В проде флаг выключен.
- API отвечает `422` и не пишет адрес в тело: `test_rejects_private_webhook_and_keeps_api_key_out_of_the_body`.
- Клиент webhook не следует редиректам. Ответ `302` на `http://127.0.0.1/admin` не порождает второй запрос, повтор идёт на исходный URL: `test_webhook_does_not_follow_redirects`.
- Ошибка доставки в журнале — общая строка `webhook delivery failed`, без URL и секретов.

Отказ PostgreSQL на создании платежа — `503` с текстом `Service temporarily unavailable`, без SQL и без имён колонок: `test_database_outage_hides_sql`. Необработанные исключения не превращаются в общий handler, чтобы не прятать `401` и `422`.

## Отказоустойчивость под нагрузкой

- Приём платежа не зависит от RabbitMQ: outbox `pending` и пустая очередь до relay (`test_create_leaves_outbox_pending_until_relay`).
- Два relay не публикуют одну строку: `SKIP LOCKED` (`test_second_relay_skips_row_locked_by_the_first`).
- Падение на середине пачки не откатывает уже подтверждённые публикации (`test_published_row_stays_published_when_next_publish_fails`).
- Повторная доставка не вызывает шлюз, пока жив захват `gateway_claimed_at` (аренда 30 с). Второй worker получает `PaymentInProgress`, шлюз вызван один раз: `test_second_worker_does_not_call_gateway_while_claim_is_held`. Исключение шлюза снимает захват, чтобы следующая попытка могла забрать платёж. Если процесс умер в середине вызова шлюза, захват держится до конца аренды: короткие retry (1 с и 2 с) могут увести сообщение в DLQ раньше, чем аренда истечёт. Статус при этом остаётся `pending`, повторная обработка возможна после снятия аренды.
- Пул PostgreSQL: `pool_pre_ping`, размер 10, overflow 20, timeout 30 с, recycle 1800 с. `test_postgres_pool_is_bounded_and_checks_connections` проверяет размер пула без реального коннекта.
- Очереди durable, сообщения persistent, prefetch ограничен.

## Полный список тестов из лога

Интеграционные (PostgreSQL 16 и RabbitMQ 3.13):

- `tests/integration/test_api.py::test_create_and_get_payment`
- `tests/integration/test_api.py::test_auth_validation_and_missing_payment`
- `tests/integration/test_api.py::test_idempotency_on_postgres`
- `tests/integration/test_api.py::test_concurrent_create_with_one_key`
- `tests/integration/test_dlq.py::test_retry_queue_returns_message_to_main`
- `tests/integration/test_dlq.py::test_message_is_dead_lettered_after_three_attempts`
- `tests/integration/test_flow.py::test_processor_decline_and_webhook_retry_over_http`
- `tests/integration/test_flow.py::test_queue_consumer_marks_success_and_calls_webhook`
- `tests/integration/test_migrations.py::test_migrations_create_payment_and_outbox_tables`
- `tests/integration/test_migrations.py::test_downgrade_removes_tables`
- `tests/integration/test_relay.py::test_relay_publishes_payments_new_and_marks_outbox`
- `tests/integration/test_relay.py::test_create_leaves_outbox_pending_until_relay`
- `tests/integration/test_relay.py::test_second_relay_skips_row_locked_by_the_first`

Юнит (SQLite, без Docker), все со статусом `PASSED` в том же логе:

- `test_compose`: сервисы compose, README, entrypoint с миграциями
- `test_delivery`: ack, retry, DLQ для постоянной ошибки и битого сообщения
- `test_fingerprint`: стабильный хеш и смена суммы
- `test_gateway`: успех ниже 0.9 и отказ на границе
- `test_http`: создание, чтение, 401, 400, 409, 404, три валюты, SSRF, скрытые колонки, ключ как данные, пробельный ключ, 503 без SQL, одна строка
- `test_netpolicy`: 9 запрещённых URL, публичный URL, разрешение при флаге
- `test_outbox`: публикация, сбой, частичная пачка
- `test_payments`: запись, повтор, конфликт, откат commit, отсутствующий платёж
- `test_pool`: размер пула 10
- `test_processing`: успех, отказ шлюза, webhook без повторного шлюза, захват, отсутствующий платёж
- `test_publisher`: `payments.new` и переход retry → DLQ
- `test_retry`: удвоение паузы, DLQ на третьей попытке, ключ маршрута, `x-attempt` по умолчанию 0
- `test_schemas`: тело, три валюты, metadata, описание, `0.01`, семь невалидных тел, два знака суммы
- `test_topology`: очередь, DLQ, retry, подписка consumer
- `test_webhook`: успех с первой попытки, экспоненциальная пауза, запрет редиректа, исчерпание попыток
