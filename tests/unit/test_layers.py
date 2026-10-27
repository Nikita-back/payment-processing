import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _imports(relative: str) -> list[str]:
    found: list[str] = []
    base = ROOT / relative
    files = [base] if base.is_file() else sorted(base.rglob("*.py"))
    for path in files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module)
    return found


def test_domain_has_no_frameworks() -> None:
    modules = _imports("app/domain")
    banned = ("sqlalchemy", "fastapi", "faststream", "httpx", "aio_pika", "pydantic")
    assert not any(name == item or name.startswith(f"{item}.") for name in modules for item in banned)


def test_application_does_not_touch_sqlalchemy_or_http() -> None:
    modules = _imports("app/application")
    banned = ("sqlalchemy", "fastapi", "faststream", "httpx", "aio_pika", "app.infrastructure", "app.api")
    assert not any(name == item or name.startswith(f"{item}.") for name in modules for item in banned)


def test_router_does_not_decide_business_rules() -> None:
    source = (ROOT / "app/api/router.py").read_text()
    assert "def build_router" not in source
    assert "router = APIRouter" in source
    assert "assert_webhook_url" not in source
    assert "Idempotency-Key is empty" not in source
    assert "AsyncSession" not in source
    assert "sqlalchemy" not in source
