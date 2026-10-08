from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_compose_declares_required_services() -> None:
    text = (ROOT / "docker-compose.yml").read_text()
    for service in ("postgres:", "rabbitmq:", "api:", "consumer:"):
        assert service in text
    assert "postgres:16-alpine" in text
    assert "rabbitmq:3.13-management-alpine" in text


def test_api_entrypoint_runs_migrations() -> None:
    script = (ROOT / "docker" / "start-api.sh").read_text()
    assert "alembic upgrade head" in script
    assert "uvicorn app.main:create_app --factory" in script
