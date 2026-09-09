# Verification record — 2026-09-09

All results below refer to the Windows project in this handoff. No WSL files were copied, overwritten, or removed.

## Passed

- **40 backend tests** using Python 3.12 in the repository-local `.venv`. Covers decimal arithmetic, unsafe source links, schema rejection, exact citations, native tool-loop observations, invalid submission repair, tool/turn bounds, retry behavior, provider failures, session authorization, request origins, body limits, durable reports, deletion, concurrent SQL quotas, background queue execution, worker deadlines, stale recovery, and retention cascades.
- **7 frontend tests** across 2 Vitest files. Covers disabled providers, actual brief submission, explicit persisted failure, active-task recovery, reconnect feedback, same-origin API behavior, and HTTP failure handling.
- **TypeScript:** `npm run typecheck` exited successfully.
- **Frontend lint:** scoped to authored application/test code; generated UI primitives are excluded. A local exception documents the asynchronous session-bootstrap effect.
- **Python quality:** Ruff lint and format checks passed for application, tests, migrations, and scripts.
- **Dependency consistency:** `pip check` reported no broken requirements.
- **Production frontend build:** completed with exit code 0 on Node **22.23.2**, producing `dist/client/index.html` and compiled assets. The final build used the local Node 22 executable, not the system Node 24 executable.
- **Migrations:** `alembic upgrade head` and `alembic check` ran successfully against an isolated SQLite database; no model/schema drift was detected.
- **Combined runtime:** the final FastAPI process served the built frontend and all **7 referenced JS/CSS assets**, `/api/health`, `/api/session`, and session-private `/api/research` successfully. The smoke script confirmed a session cookie and `Cache-Control: no-store`. This did not make any model/search request.
- **npm audit:** the refreshed final audit reported **0 vulnerabilities**. Earlier generated-scaffold advisories were addressed with compatible dependency updates and the documented Sharp override. This is a point-in-time audit, not a permanent guarantee.

The Python tests emitted one upstream deprecation warning from Starlette's use of `anyio.abc.BlockingPortal`. Restricted sandbox temp-directory permissions required a fresh workspace-local pytest `--basetemp` and cache directory; assertions and test cases were unchanged.

## Not verified / unsuccessful

- **Real Ollama workflow:** the opt-in smoke test against the installed local `qwen3.5:9b` model timed out before returning a usable result. That test used clearly synthetic search evidence and would not establish real-market research even if it passed. Native tool protocol and multi-step orchestration passed deterministic tests.
- **Real Brave research:** no authorized search key was provided. No live market report is claimed. There is no production mock fallback.
- **Docker and PostgreSQL runtime:** Docker was unavailable and no PostgreSQL instance was provisioned. Docker/Compose and PostgreSQL migration CI are prepared but unexecuted here.
- **Remote CI:** workflow configured, not run on a remote repository.
- **Deployment:** not performed; no public URL or hosting resource exists for this application.
- **Browser visual/accessibility QA:** not performed. Component interaction tests and HTTP asset verification do not replace browser/device testing.
- **WebMCP:** optional feature-detected staging tool included; no supported browser validation context was exercised. It does not start paid/provider requests.
- **Node 24 build:** native Windows libuv assertion at process exit. Node 22 passed, `.nvmrc` records the tested version, and the prebuild check rejects unsupported majors.
- **WSL migration:** deferred at the user's instruction. The original Windows project is the delivered source.

## Reproduce

Use the README commands with Node 22 and the new local Python `.venv`. For the read-only built-app runtime check, start the Python service from the repository root and run:

```powershell
.\.venv\Scripts\python.exe -m scripts.http_smoke --url http://127.0.0.1:8000
```

Live-provider and production acceptance steps are in `DEPLOYMENT.md`. Configure providers before relying on the product for actual research; review cited claims manually.
