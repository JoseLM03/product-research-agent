import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.config import Settings
from backend.db import Job, ToolEvent
from backend.main import create_app
from backend.worker import run_job, worker
from tests.helpers import ModelFixture, SearchFixture


def test_worker_consumes_durable_queue(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'worker.db'}",
        worker_enabled=True,
        research_enabled=True,
        tavily_api_key="test-only",
        app_origin="http://testserver",
    )
    app = create_app(settings, model=ModelFixture(), search=SearchFixture())
    with TestClient(app) as client:
        client.headers["origin"] = settings.app_origin
        client.get("/api/session")
        task = client.post("/api/research", json={"idea": "compact coffee grinder"}).json()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            detail = client.get("/api/research/" + task["id"]).json()
            if detail["status"] == "completed":
                break
            time.sleep(0.05)
        assert detail["status"] == "completed"
        assert detail["events"][-1]["status"] == "completed"


def test_atomic_global_quota_across_clients(client, app):
    app.state.settings.daily_global_limit = 3
    clients = [TestClient(app) for _ in range(8)]
    for browser in clients:
        browser.headers["origin"] = "http://testserver"
        browser.get("/api/session")

    def submit(browser):
        return browser.post("/api/research", json={"idea": "compact coffee grinder"}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(submit, clients))
    for browser in clients:
        browser.close()
    assert statuses.count(202) == 3
    assert statuses.count(429) == 5


def test_worker_timeout_becomes_failed_task(client, app):
    class SlowModel:
        async def chat(self, *args):
            await asyncio.sleep(10)

    job_id = client.post("/api/research", json={"idea": "compact coffee grinder"}).json()["id"]
    with app.state.sessions.begin() as db:
        db.get(Job, job_id).status = "running"
    app.state.settings.job_timeout_seconds = 0.01
    asyncio.run(
        run_job(job_id, app.state.sessions, app.state.settings, SlowModel(), SearchFixture())
    )
    result = client.get("/api/research/" + job_id).json()
    assert result["status"] == "failed"
    assert "time limit" in result["error"]


def test_stale_worker_recovery_and_retention(client, app):
    now = time.time()
    with app.state.sessions.begin() as db:
        db.add(
            Job(
                id="stale",
                owner="test",
                idea="stale task",
                inputs={"idea": "stale task"},
                status="running",
                started_at=now - 1000,
            )
        )
        db.add(
            Job(
                id="expired",
                owner="test",
                idea="old task",
                inputs={"idea": "old task"},
                status="failed",
                created_at=now - 31 * 86400,
            )
        )
        db.flush()
        db.add(ToolEvent(job_id="expired", tool="agent", status="failed", detail="test"))

    async def cycle():
        task = asyncio.create_task(
            worker(app.state.sessions, app.state.settings, ModelFixture(), SearchFixture())
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(cycle())
    with app.state.sessions() as db:
        assert db.get(Job, "stale").status == "failed"
        assert db.get(Job, "expired") is None
        assert db.scalar(select(ToolEvent).where(ToolEvent.job_id == "expired")) is None


def test_production_configuration_rejects_unsafe_defaults():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(environment="production")
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(environment="production", session_secret="x" * 40)
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(
            environment="production", session_secret="x" * 40, app_origin="https://example.com"
        )
