from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    api_key: str
    outbox_relay_enabled: bool = True
    outbox_poll_interval_seconds: float = 0.5
    outbox_batch_size: int = 50
    retry_base_delay_ms: int = 1000
    max_delivery_attempts: int = 3
    webhook_timeout_seconds: float = 5.0
    webhook_attempts: int = 3
    webhook_retry_base_seconds: float = 1.0
    gateway_min_delay_seconds: float = 2.0
    gateway_max_delay_seconds: float = 5.0
    gateway_success_rate: float = 0.9

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
