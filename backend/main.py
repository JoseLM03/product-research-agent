import asyncio
import hashlib
import hmac
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, update
from starlette.middleware.sessions import SessionMiddleware

from .config import Settings
from .db import Admission, AdmissionLock, Base, Job, ToolEvent, database
from .providers import BraveSearch, Ollama
from .schemas import ResearchInput
from .worker import worker


def create_app(settings=None, *, model=None, search=None):
    settings = settings or Settings()
    logger = logging.getLogger("fieldwork")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    engine, sessions = database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        if settings.environment != "production":
            Base.metadata.create_all(engine)
            with sessions.begin() as db:
                if not db.get(AdmissionLock, 1):
                    db.add(AdmissionLock(id=1, value=0))
        # Production schema is explicitly migrated before startup; fail closed if missing.
        with sessions() as db:
            if not db.get(AdmissionLock, 1):
                raise RuntimeError("Apply database migrations before starting the server")
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            task = (
                asyncio.create_task(
                    worker(
                        sessions,
                        settings,
                        model or Ollama(client, settings),
                        search or BraveSearch(client, settings.brave_api_key),
                    )
                )
                if settings.worker_enabled
                else None
            )
            yield
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        engine.dispose()

    app = FastAPI(
        title="Fieldwork Research API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.environment != "production" else None,
        openapi_url="/api/openapi.json" if settings.environment != "production" else None,
        redoc_url=None,
    )
    app.state.sessions, app.state.settings = sessions, settings
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="fieldwork_session",
        max_age=settings.retention_days * 86400,
        same_site="strict",
        https_only=settings.environment == "production",
    )

    @app.middleware("http")
    async def boundaries(request, call_next):
        request_id = str(uuid.uuid4())
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if request.headers.get("origin") != settings.app_origin:
                return JSONResponse({"detail": "Request origin is not allowed."}, status_code=403)
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"detail": "Use application/json."}, status_code=415)
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 8192:
                    return JSONResponse({"detail": "Request body is too large."}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        try:
            response = await call_next(request)
        except Exception as exc:
            logging.getLogger("fieldwork.api").error(
                "request_error id=%s type=%s", request_id, type(exc).__name__
            )
            response = JSONResponse(
                {"detail": "Unexpected server error.", "request_id": request_id}, status_code=500
            )
        response.headers.update(
            {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "detail": "Invalid request.",
                "errors": [
                    {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                    for e in exc.errors()
                ],
            },
            status_code=422,
        )

    def owner(request):
        value = request.session.get("owner")
        if not value:
            raise HTTPException(401, "Initialize a browser session first.")
        return value

    def owned(db, job_id, owner_id):
        job = db.scalar(select(Job).where(Job.id == job_id, Job.owner == owner_id))
        if not job:
            raise HTTPException(404, "Research task not found.")
        return job

    def serialize(job):
        return {
            "id": job.id,
            "idea": job.idea,
            "status": job.status,
            "created_at": job.created_at,
            "finished_at": job.finished_at,
            "error": job.error,
        }

    @app.get("/api/health")
    def health():
        with sessions() as db:
            db.execute(select(1))
        return {"status": "ok"}

    @app.get("/api/session")
    def session(request: Request):
        if "owner" not in request.session:
            request.session["owner"] = secrets.token_hex(32)
        return {
            "configured": settings.configured,
            "retention_days": settings.retention_days,
            "message": "Research is enabled. Provider connectivity is checked when a task runs."
            if settings.configured
            else "Research is disabled until the operator configures Ollama, BRAVE_API_KEY, and RESEARCH_ENABLED.",
            "daily_limit": settings.daily_session_limit,
        }

    @app.post("/api/research", status_code=202)
    def create_research(payload: ResearchInput, request: Request):
        owner_id = owner(request)
        if not settings.configured:
            raise HTTPException(
                503, "Research providers are not configured or research is disabled."
            )
        now, job_id = time.time(), str(uuid.uuid4())
        # Ignore spoofable forwarding headers. Trust proxy configuration is an operator decision.
        ip = request.client.host if request.client else "unknown"
        ip_hash = hmac.new(
            settings.session_secret.encode(), ip.encode(), hashlib.sha256
        ).hexdigest()
        midnight = now - now % 86400
        with sessions.begin() as db:
            # Serialize admission in SQL, so caps and concurrent-job checks are atomic.
            db.execute(
                update(AdmissionLock)
                .where(AdmissionLock.id == 1)
                .values(value=AdmissionLock.value + 1)
            )
            base = (
                select(func.count()).select_from(Admission).where(Admission.created_at >= midnight)
            )
            for query, limit in [
                (base, settings.daily_global_limit),
                (base.where(Admission.owner == owner_id), settings.daily_session_limit),
                (base.where(Admission.ip_hash == ip_hash), settings.daily_ip_limit),
            ]:
                if db.scalar(query) >= limit:
                    raise HTTPException(
                        429,
                        "Daily research limit reached. Limits reset at 00:00 UTC.",
                        headers={"Retry-After": str(int(midnight + 86400 - now))},
                    )
            active = (
                select(func.count()).select_from(Job).where(Job.status.in_(["queued", "running"]))
            )
            if db.scalar(active.where(Job.owner == owner_id)):
                raise HTTPException(409, "A research task is already active in this browser.")
            if db.scalar(active) >= 5:
                raise HTTPException(
                    429,
                    "The research queue is full. Try again later.",
                    headers={"Retry-After": "60"},
                )
            db.add(Admission(id=job_id, owner=owner_id, ip_hash=ip_hash, created_at=now))
            job = Job(
                id=job_id,
                owner=owner_id,
                idea=payload.idea,
                inputs=payload.model_dump(mode="json"),
                created_at=now,
                status="queued",
            )
            db.add(job)
        return serialize(job)

    @app.get("/api/research")
    def history(request: Request):
        with sessions() as db:
            jobs = db.scalars(
                select(Job)
                .where(Job.owner == owner(request))
                .order_by(Job.created_at.desc())
                .limit(100)
            )
            return [serialize(job) for job in jobs]

    @app.get("/api/research/{job_id}")
    def detail(job_id: uuid.UUID, request: Request):
        with sessions() as db:
            job = owned(db, str(job_id), owner(request))
            events = db.scalars(
                select(ToolEvent).where(ToolEvent.job_id == job.id).order_by(ToolEvent.id)
            )
            return {
                **serialize(job),
                "report": job.report,
                "inputs": job.inputs,
                "events": [
                    {
                        "id": e.id,
                        "tool": e.tool,
                        "status": e.status,
                        "detail": e.detail,
                        "created_at": e.created_at,
                    }
                    for e in events
                ],
            }

    @app.delete("/api/research/{job_id}")
    def remove(job_id: uuid.UUID, request: Request):
        with sessions.begin() as db:
            job = owned(db, str(job_id), owner(request))
            if job.status in ("queued", "running"):
                raise HTTPException(409, "Wait for the task to finish before deleting it.")
            db.delete(job)
        return {"deleted": True}

    static = Path(settings.static_dir)
    if static.is_dir() and (static / "index.html").exists():
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app


app = create_app()
