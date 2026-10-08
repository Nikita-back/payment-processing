from app.consumer import consumer_queue
from app.retry import retry_delay_ms, retry_queue_name
from app.topology import DLQ_QUEUE, DLX_EXCHANGE, NEW_QUEUE, PAYMENTS_EXCHANGE, main_queue_spec, queue_specs


def test_topology_has_main_queue_dlq_and_retry_queues() -> None:
    specs = {item.name: item for item in queue_specs(1000, 3)}
    assert set(specs) == {NEW_QUEUE, DLQ_QUEUE, retry_queue_name(0), retry_queue_name(1)}
    assert specs[NEW_QUEUE].exchange == PAYMENTS_EXCHANGE
    assert specs[NEW_QUEUE].arguments["x-dead-letter-exchange"] == DLX_EXCHANGE
    assert specs[DLQ_QUEUE].exchange == DLX_EXCHANGE
    assert specs[retry_queue_name(0)].arguments["x-message-ttl"] == retry_delay_ms(0, 1000)
    assert specs[retry_queue_name(1)].arguments["x-message-ttl"] == retry_delay_ms(1, 1000)
    assert specs[retry_queue_name(0)].arguments["x-dead-letter-routing-key"] == "payments.new"


def test_consumer_queue_uses_main_spec() -> None:
    spec = main_queue_spec()
    queue = consumer_queue()
    assert queue.name == spec.name
    assert queue.routing_key == spec.routing_key
    assert queue.arguments == spec.arguments
