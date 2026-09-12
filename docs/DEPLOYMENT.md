# Deployment guide

## Current status

Not deployed. The static production build and combined local FastAPI service have been verified in Windows using Node 22. Docker was not available in the execution environment, and no PostgreSQL server or hosting account was provisioned. The Docker/Compose and PostgreSQL CI paths are prepared, but their execution must be verified on the target host. No Sites URL is published: a static-only Sites deployment would not host the Python worker and database required by this application.

## Recommended topology

Deploy one Linux container on a host that supports a long-running Python process and a private reachable Ollama service. Use managed PostgreSQL with TLS, automated backups, and a restore procedure. Put an HTTPS reverse proxy in front of port 8000. The container serves both frontend and API; do not deploy the frontend separately unless you deliberately redesign same-origin sessions/proxying.

Use one replica and `--workers 1`. Do not use short-lived serverless request functions for the in-process queue worker. Hosting does not include inference hardware; provision an appropriate private Ollama endpoint yourself or leave research disabled. Do not expose unauthenticated Ollama to the public internet.

## Production configuration

Set `ENVIRONMENT=production`, a PostgreSQL `DATABASE_URL`, and `APP_ORIGIN=https://YOUR_HOST`. Generate `SESSION_SECRET` with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and store it in the hosting secret manager. Keep it stable across deploys. URI-encode special characters in the database password.

Set `OLLAMA_URL` to a private endpoint and `OLLAMA_MODEL` to a model already deployed there. Configure `TAVILY_API_KEY` and provider-side spend controls before setting `RESEARCH_ENABLED=true`. Initially leave it false. Set conservative global/session/IP budgets. Keep `WORKER_ENABLED=true`.

The app ignores `X-Forwarded-For` and the Docker command disables proxy headers. Behind a proxy, all users may share the proxy's IP quota; the global quota remains the hard application admission cap. Configure trusted-proxy handling intentionally if per-client IP quotas are needed. Never trust arbitrary forwarded headers from the public internet.

## Build and migration sequence

```bash
docker build -t fieldwork:local .
# Supply your secret environment file or platform secret injection.
docker run --rm --env-file .env fieldwork:local alembic upgrade head
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 fieldwork:local
```

Run migrations as a release step, not in every API worker. Back up the database before a schema-changing release. `alembic check` compares the model and migration schema. Never point test cleanup commands at production.

For the included Compose example, create an ignored `.env` containing the app settings plus `POSTGRES_PASSWORD`, and set `DATABASE_URL=postgresql+psycopg://fieldwork:YOUR_URI_ENCODED_PASSWORD@db:5432/fieldwork`. Compose starts PostgreSQL, runs a one-shot migration service, then starts the app. The database has no exposed host port. App port 8000 binds to loopback for a host TLS proxy.

```bash
docker compose up --build -d
docker compose logs app
```

For a local HTTP Compose smoke test only, use `ENVIRONMENT=development` and `APP_ORIGIN=http://127.0.0.1:8000`. For production use HTTPS and `ENVIRONMENT=production`. If inference is on the Docker host, `host.docker.internal` is provided by the example; verify its network accessibility and access controls before enabling research.

## Acceptance before inviting users

1. `/api/health` returns 200 and the root renders the built frontend.
2. Session cookies have HttpOnly, SameSite=Strict, and Secure in HTTPS production. No response contains provider secrets.
3. A real model with a real search key selects a research tool, consumes real results, and submits a report. Review exact quotes and links against the provider result and original site.
4. A second browser session cannot list/read/delete the first session's reports.
5. A malformed brief is rejected; an invalid key or disconnected model produces a clear failed task; low budgets produce 429.
6. Restart during a queued task and during a running task. Confirm queued persistence and explicit stale failure, rather than silent replay.
7. Verify retention, delete cascades, backup restoration, resource limits, and database migrations on PostgreSQL.
8. Check keyboard navigation, mobile layout, 200% zoom, focus behavior, and report/source readability in actual browsers.

Do not claim production readiness solely from a container build or a deterministic test suite. Live-provider, host, browser, and operational checks are part of release acceptance.

## Operations and rollback

Application logs contain task IDs, tool/status transitions, and sanitized error classes, not prompts, cookies, source snippets, request bodies, or keys. HTTP access logging is disabled in the documented start command; configure proxy logging with the same privacy intent. Monitor 5xx/429 rates, task failure rates, queue age, disk/database growth, and provider spend. No numeric performance claims have been measured.

`RESEARCH_ENABLED=false` stops new admissions and new claims after restarting with the setting. An in-flight task can finish; terminate the process if an immediate stop is necessary, understanding that a provider request may already have been accepted. There is no financial guarantee from local limits; enforce independent limits at the provider.

Keep the prior container image. Roll back the application only when its schema is compatible. Do not automatically run destructive migration downgrades on a live database. Rotate exposed provider credentials immediately; rotating the session key also invalidates history access for all browsers.

## Future manual WSL migration

The Windows project was not moved. Compare any existing WSL destination before copying. Preserve newer files and `.git`; do not overwrite blindly. Exclude `.venv`, `node_modules`, build caches, and generated output. If preserving local SQLite data, stop the application and take a consistent database backup first.

Inside WSL create a new Python 3.12 `.venv`, activate Node 22 from `.nvmrc`, install pinned dependencies, and rerun the README checks. Existing absolute Windows paths are not used by application source. `OLLAMA_URL` may need adjustment because Windows and WSL loopback/network access differ. Verify the endpoint from WSL without exposing it publicly. Retain the Windows original until source hashes, Git history, tests, build, and runtime checks pass.
