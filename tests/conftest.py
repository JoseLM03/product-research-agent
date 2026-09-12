import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            worker_enabled=False,
            research_enabled=True,
            tavily_api_key="test-only-not-a-key",
            app_origin="http://testserver",
        )
    )


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        client.headers["origin"] = "http://testserver"
        client.get("/api/session")
        yield client
